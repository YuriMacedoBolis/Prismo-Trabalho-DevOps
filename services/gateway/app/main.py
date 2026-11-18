"""API Gateway do Prismo.

Unico ponto de entrada da API. Nenhum outro servico e exposto para fora do
cluster, o que concentra tres responsabilidades aqui em vez de repeti-las em
sete lugares:

  1. **Rate limiting** por IP, contado no Redis.
  2. **Autenticacao**: valida o JWT e repassa o id do usuario aos servicos de
     dominio no header `X-Usuario-Id`. Os servicos confiam nesse header
     porque so o gateway os alcanca — eles nao tem porta publicada.
  3. **Roteamento**: encaminha para auth, portfolio e, nas proximas fases,
     sync e seo.

O encaminhamento e transparente: repassa metodo, corpo, query e status sem
interpretar o conteudo. Um gateway que entende o payload de cada servico vira
acoplamento disfarcado — mexer num servico passaria a exigir mexer aqui.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status

from prismo_shared import (
    Dependency,
    close_redis,
    create_app,
    get_logger,
    get_redis,
    get_settings,
    ping_redis,
)
from prismo_shared.security import ErroDeToken, decodificar_token

settings = get_settings()
log = get_logger("gateway")

# Rotas que dispensam token. Tudo o que nao estiver aqui exige autenticacao:
# a lista e de liberacao, nao de bloqueio, para que uma rota nova nasca
# protegida mesmo se alguem esquecer de pensar no assunto.
ROTAS_PUBLICAS = (
    "/api/v1/auth/registrar",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/publico",
    "/api/v1/ping",
    "/api/v1/info",
    # SEO e conteudo publico por definicao: existe para ser lido por
    # buscador, que nunca tera token.
    "/api/v1/seo",
)

# Prefixo -> servico de destino.
DESTINOS = {
    "/api/v1/auth": settings.auth_url,
    "/api/v1/portfolios": settings.portfolio_url,
    "/api/v1/publico": settings.portfolio_url,
    "/api/v1/conexoes": settings.sync_url,
    "/api/v1/sincronizacoes": settings.sync_url,
    "/api/v1/seo": settings.seo_url,
}

# Headers que nao podem ser repassados: sao da conexao entre cliente e
# gateway, nao da conexao entre gateway e servico. Repassar Host faria o
# destino achar que e "localhost:8001"; repassar Content-Length com o corpo
# recodificado produziria resposta truncada.
HEADERS_IGNORADOS = {
    "host", "content-length", "connection", "keep-alive",
    "transfer-encoding", "upgrade",
}

_cliente: httpx.AsyncClient | None = None


async def abrir_cliente(_app) -> None:
    """Um unico cliente HTTP, com pool de conexoes reaproveitado.

    Criar um AsyncClient por requisicao abriria conexao TCP nova a cada
    chamada entre servicos, e o custo do handshake dominaria o tempo total.
    """
    global _cliente
    _cliente = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds, connect=3.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=False,
    )


async def fechar_cliente(_app) -> None:
    global _cliente
    if _cliente is not None:
        await _cliente.aclose()
        _cliente = None
    await close_redis()


app = create_app(
    "gateway",
    description=(
        "Ponto unico de entrada da API do Prismo. Valida token, aplica rate "
        "limit e roteia para os servicos de dominio."
    ),
    dependencies=[Dependency(name="redis", check=ping_redis, critical=True)],
    on_startup=abrir_cliente,
    on_shutdown=fechar_cliente,
    settings=settings,
)


async def aplicar_rate_limit(request: Request) -> int:
    """Janela fixa de 1 minuto por IP.

    INCR devolve o valor novo; quando vem 1, a chave acabou de nascer e e esse
    o momento de definir o TTL. Duas operacoes, sem condicao de corrida:
    qualquer requisicao concorrente recebe um valor maior que 1.
    """
    ip = request.client.host if request.client else "desconhecido"
    chave = f"ratelimit:{ip}"

    redis = get_redis()
    batidas = await redis.incr(chave)
    if batidas == 1:
        await redis.expire(chave, 60)

    if batidas > settings.rate_limit_per_minute:
        log.warning("rate_limit_excedido", ip=ip, batidas=batidas)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Limite de {settings.rate_limit_per_minute} req/min excedido.",
            headers={"Retry-After": "60"},
        )
    return batidas


def rota_publica(caminho: str) -> bool:
    return any(caminho.startswith(p) for p in ROTAS_PUBLICAS)


def resolver_destino(caminho: str) -> str | None:
    # Do prefixo mais especifico para o mais generico, senao "/api/v1/auth"
    # poderia casar com uma entrada mais curta por acidente.
    for prefixo in sorted(DESTINOS, key=len, reverse=True):
        if caminho.startswith(prefixo):
            return DESTINOS[prefixo]
    return None


def autenticar(request: Request) -> str:
    """Valida o Bearer token e devolve o id do usuario."""
    autorizacao = request.headers.get("Authorization", "")
    if not autorizacao.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token ausente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decodificar_token(autorizacao[7:], tipo_esperado="access")
    except ErroDeToken as erro:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(erro),
            headers={"WWW-Authenticate": "Bearer"},
        ) from erro
    return payload["sub"]


# ---------------------------------------------------------------------------
#  Rotas proprias do gateway
# ---------------------------------------------------------------------------

proprio = APIRouter(prefix="/api/v1", tags=["infra"])


@proprio.get("/ping", summary="Teste de ponta a ponta")
async def ping(request: Request) -> dict:
    batidas = await aplicar_rate_limit(request)
    return {
        "message": "pong",
        "service": "gateway",
        "request_id": request.state.request_id,
        "rate_limit": {
            "hits_neste_minuto": batidas,
            "limite": settings.rate_limit_per_minute,
        },
    }


@proprio.get("/info", summary="Configuracao efetiva e destinos de roteamento")
async def info() -> dict:
    return {
        "service": "gateway",
        "environment": settings.environment,
        "rotas_publicas": list(ROTAS_PUBLICAS),
        "destinos": DESTINOS,
    }


app.include_router(proprio)


# ---------------------------------------------------------------------------
#  Encaminhamento
# ---------------------------------------------------------------------------


@app.api_route(
    "/api/v1/{caminho:path}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    include_in_schema=False,
)
async def encaminhar(caminho: str, request: Request) -> Response:
    caminho_completo = f"/api/v1/{caminho}"

    await aplicar_rate_limit(request)

    destino = resolver_destino(caminho_completo)
    if destino is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhum servico atende {caminho_completo}.",
        )

    cabecalhos = {
        k: v for k, v in request.headers.items() if k.lower() not in HEADERS_IGNORADOS
    }

    if not rota_publica(caminho_completo):
        cabecalhos["X-Usuario-Id"] = autenticar(request)

    # Propaga o request-id para que os logs dos dois servicos possam ser
    # correlacionados por uma unica chave.
    cabecalhos["X-Request-ID"] = request.state.request_id

    if _cliente is None:  # pragma: no cover - so ocorreria fora do lifespan
        raise HTTPException(status_code=503, detail="Gateway inicializando.")

    try:
        resposta = await _cliente.request(
            method=request.method,
            url=f"{destino}{caminho_completo}",
            content=await request.body(),
            headers=cabecalhos,
            params=request.query_params,
        )
    except httpx.TimeoutException:
        log.warning("destino_timeout", destino=destino, caminho=caminho_completo)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="O servico de destino nao respondeu a tempo.",
        ) from None
    except httpx.RequestError as erro:
        log.error("destino_inalcancavel", destino=destino, erro=str(erro))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servico de destino indisponivel.",
        ) from erro

    # 204 nao pode ter corpo; devolver um causaria erro de protocolo.
    if resposta.status_code == status.HTTP_204_NO_CONTENT:
        return Response(status_code=204)

    return Response(
        content=resposta.content,
        status_code=resposta.status_code,
        media_type=resposta.headers.get("content-type"),
    )
