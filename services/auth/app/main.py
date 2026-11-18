"""Servico de autenticacao do Prismo.

Dono do schema `auth`. Nenhum outro servico le ou escreve nas tabelas dele:
quem precisa saber quem e o usuario valida o JWT, que carrega o id assinado.
Essa e a fronteira que torna os servicos independentes de verdade.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from prismo_shared import Dependency, create_app, get_logger, get_settings
from prismo_shared.db import close_db, get_session, ping_db
from prismo_shared.models import Usuario
from prismo_shared.security import (
    ErroDeToken,
    criar_access_token,
    criar_refresh_token,
    decodificar_token,
)
from prismo_shared.senhas import gerar_hash_senha, precisa_rehash, verificar_senha

from .esquemas import (
    LoginEntrada,
    RefreshEntrada,
    RegistroEntrada,
    SessaoSaida,
    TokensSaida,
    UsuarioSaida,
)

settings = get_settings()
log = get_logger("auth")

# Metricas de dominio. Contar tentativa de login que falha e util de verdade:
# um salto nessa curva e o sinal mais barato de ataque por forca bruta.
LOGINS = Counter(
    "prismo_auth_logins_total",
    "Tentativas de login por resultado.",
    ["resultado"],
)
REGISTROS = Counter(
    "prismo_auth_registros_total",
    "Contas criadas com sucesso.",
)

app = create_app(
    "auth",
    description="Contas, autenticacao e emissao de tokens do Prismo.",
    dependencies=[Dependency(name="postgres", check=ping_db, critical=True)],
    on_shutdown=lambda _app: close_db(),
    settings=settings,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _montar_tokens(usuario: Usuario) -> TokensSaida:
    return TokensSaida(
        access_token=criar_access_token(str(usuario.id), email=usuario.email),
        refresh_token=criar_refresh_token(str(usuario.id)),
        expira_em_segundos=settings.access_token_ttl_minutes * 60,
    )


@router.post(
    "/registrar",
    response_model=SessaoSaida,
    status_code=status.HTTP_201_CREATED,
    summary="Cria uma conta e ja devolve a sessao",
)
async def registrar(
    dados: RegistroEntrada, sessao: AsyncSession = Depends(get_session)
) -> SessaoSaida:
    usuario = Usuario(
        email=dados.email,
        nome=dados.nome,
        senha_hash=gerar_hash_senha(dados.senha),
    )
    sessao.add(usuario)

    try:
        # O flush envia o INSERT sem fechar a transacao, o que permite tratar
        # o conflito de e-mail aqui. Conferir antes com um SELECT teria uma
        # janela de corrida entre a consulta e a gravacao; a constraint UNIQUE
        # do banco nao tem essa janela.
        await sessao.flush()
    except IntegrityError:
        await sessao.rollback()
        log.info("registro_email_duplicado")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ja existe uma conta com este e-mail.",
        ) from None

    await sessao.refresh(usuario)
    REGISTROS.inc()
    log.info("usuario_registrado", usuario_id=str(usuario.id))

    return SessaoSaida(
        usuario=UsuarioSaida.model_validate(usuario), tokens=_montar_tokens(usuario)
    )


@router.post("/login", response_model=SessaoSaida, summary="Autentica e emite tokens")
async def login(
    dados: LoginEntrada, sessao: AsyncSession = Depends(get_session)
) -> SessaoSaida:
    resultado = await sessao.execute(select(Usuario).where(Usuario.email == dados.email))
    usuario = resultado.scalar_one_or_none()

    # A mensagem e a mesma para e-mail inexistente e senha errada, de
    # proposito: respostas diferentes permitiriam descobrir quais e-mails
    # estao cadastrados.
    credenciais_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="E-mail ou senha incorretos.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if usuario is None or not verificar_senha(dados.senha, usuario.senha_hash):
        LOGINS.labels("falha").inc()
        log.info("login_falhou")
        raise credenciais_invalidas

    if not usuario.ativo:
        LOGINS.labels("inativo").inc()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Conta desativada."
        )

    # Fortalecimento silencioso: se os parametros do Argon2 mudaram desde o
    # cadastro, o hash e regravado agora, sem pedir nada ao usuario.
    if precisa_rehash(usuario.senha_hash):
        usuario.senha_hash = gerar_hash_senha(dados.senha)
        log.info("hash_de_senha_atualizado", usuario_id=str(usuario.id))

    LOGINS.labels("sucesso").inc()
    log.info("login_ok", usuario_id=str(usuario.id))

    return SessaoSaida(
        usuario=UsuarioSaida.model_validate(usuario), tokens=_montar_tokens(usuario)
    )


@router.post("/refresh", response_model=TokensSaida, summary="Renova o access token")
async def refresh(
    dados: RefreshEntrada, sessao: AsyncSession = Depends(get_session)
) -> TokensSaida:
    try:
        payload = decodificar_token(dados.refresh_token, tipo_esperado="refresh")
    except ErroDeToken as erro:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(erro)
        ) from erro

    usuario = await sessao.get(Usuario, uuid.UUID(payload["sub"]))
    if usuario is None or not usuario.ativo:
        # Token valido de conta que foi apagada ou desativada depois da
        # emissao. A assinatura confere, mas a sessao nao vale mais.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessao invalida."
        )

    return _montar_tokens(usuario)


@router.get("/eu", response_model=UsuarioSaida, summary="Dados do usuario autenticado")
async def eu(request: Request, sessao: AsyncSession = Depends(get_session)) -> UsuarioSaida:
    """Quem sou eu, segundo o token enviado.

    O gateway ja validou o token e repassou o id no header `X-Usuario-Id`.
    Ainda assim revalidamos o Authorization quando ele vem: o servico precisa
    continuar correto se um dia for chamado por outro caminho.
    """
    usuario_id = request.headers.get("X-Usuario-Id")

    if not usuario_id:
        autorizacao = request.headers.get("Authorization", "")
        if not autorizacao.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token ausente."
            )
        try:
            payload = decodificar_token(autorizacao[7:], tipo_esperado="access")
        except ErroDeToken as erro:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(erro)
            ) from erro
        usuario_id = payload["sub"]

    usuario = await sessao.get(Usuario, uuid.UUID(usuario_id))
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado."
        )
    return UsuarioSaida.model_validate(usuario)


app.include_router(router)
