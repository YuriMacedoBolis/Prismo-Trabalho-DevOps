"""API Gateway do Prismo.

Unico ponto de entrada da API. Nenhum outro servico e exposto para fora do
cluster: isso concentra autenticacao, rate limiting e CORS em um lugar so, em
vez de repetir a mesma logica em sete servicos.

Estado na Fase 1: o esqueleto esta completo (observabilidade, probes, rate
limit funcionando no Redis) e o roteamento para os servicos de dominio entra
na Fase 2, conforme cada um nasce.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from prismo_shared import (
    Dependency,
    close_redis,
    create_app,
    get_logger,
    get_redis,
    get_settings,
    ping_redis,
)

settings = get_settings()
log = get_logger("gateway")

app = create_app(
    "gateway",
    description=(
        "Ponto unico de entrada da API do Prismo. Valida token, aplica rate "
        "limit e roteia para os servicos de dominio."
    ),
    # O Redis e critico aqui: sem ele nao ha rate limiting, e o gateway
    # desprotegido nao deve receber trafego.
    dependencies=[Dependency(name="redis", check=ping_redis, critical=True)],
    on_shutdown=lambda _app: close_redis(),
    settings=settings,
)

router = APIRouter(prefix="/api/v1")


async def enforce_rate_limit(request: Request) -> int:
    """Janela fixa de 1 minuto por IP, contada no Redis.

    INCR devolve o valor novo; quando ele vem 1, a chave acabou de ser criada
    e e esse o momento de definir o TTL. Duas operacoes, mas sem condicao de
    corrida: qualquer requisicao concorrente recebe um valor maior que 1.
    """
    client_ip = request.client.host if request.client else "desconhecido"
    key = f"ratelimit:{client_ip}:{request.url.path}"

    redis = get_redis()
    hits = await redis.incr(key)
    if hits == 1:
        await redis.expire(key, 60)

    if hits > settings.rate_limit_per_minute:
        log.warning("rate_limit_excedido", ip=client_ip, hits=hits)
        raise HTTPException(
            status_code=429,
            detail=f"Limite de {settings.rate_limit_per_minute} req/min excedido.",
            headers={"Retry-After": "60"},
        )
    return hits


@router.get("/ping", tags=["infra"], summary="Teste de ponta a ponta")
async def ping(request: Request) -> dict:
    """Confirma que o gateway responde e que o Redis esta gravando.

    Chame varias vezes para ver o contador subir, e mais de 120 vezes em um
    minuto para ver o 429 do rate limiter.
    """
    hits = await enforce_rate_limit(request)
    return {
        "message": "pong",
        "service": "gateway",
        "request_id": request.state.request_id,
        "rate_limit": {
            "hits_neste_minuto": hits,
            "limite": settings.rate_limit_per_minute,
        },
    }


@router.get("/info", tags=["infra"], summary="Configuracao efetiva")
async def info() -> dict:
    """Mostra como o servico foi configurado, sem expor segredo nenhum."""
    return {
        "service": "gateway",
        "environment": settings.environment,
        "banco_configurado": bool(settings.database_url),
        "github_oauth_configurado": bool(settings.github_client_id),
        "drive_configurado": bool(settings.google_drive_folder_id),
        "servicos_previstos": {
            "auth": settings.auth_url,
            "portfolio": settings.portfolio_url,
            "sync": settings.sync_url,
            "seo": settings.seo_url,
        },
    }


app.include_router(router)
