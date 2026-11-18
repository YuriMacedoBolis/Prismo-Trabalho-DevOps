"""Tokens JWT.

Hash de senha fica em `senhas.py`, que depende do Argon2: so os servicos que
lidam com contas instalam aquela dependencia, enquanto todo servico que valida
token usa este modulo.

Uma escolha que vale explicacao, porque e pergunta de arguicao:

**Dois tokens, nao um.** O access token vale 30 minutos e viaja em toda
requisicao; se vazar, o estrago tem prazo curto. O refresh token vale 14 dias,
e usado so no endpoint de renovacao e pode ser revogado. Um unico token de
longa duracao juntaria o pior dos dois: exposicao constante e janela longa.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from .settings import get_settings

TipoToken = Literal["access", "refresh"]


class ErroDeToken(Exception):
    """Token ausente, expirado, adulterado ou do tipo errado."""


# --------------------------------------------------------------------------
#  Tokens
# --------------------------------------------------------------------------


def _criar_token(sub: str, tipo: TipoToken, validade: timedelta, **extras: Any) -> str:
    settings = get_settings()
    agora = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": sub,
        "tipo": tipo,
        "iat": agora,
        "exp": agora + validade,
        # Identificador unico do token. E o que permite revogar um refresh
        # especifico (lista negra no Redis) sem invalidar todos os outros.
        "jti": uuid.uuid4().hex,
        **extras,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def criar_access_token(usuario_id: str, **extras: Any) -> str:
    settings = get_settings()
    return _criar_token(
        usuario_id,
        "access",
        timedelta(minutes=settings.access_token_ttl_minutes),
        **extras,
    )


def criar_refresh_token(usuario_id: str) -> str:
    settings = get_settings()
    return _criar_token(
        usuario_id, "refresh", timedelta(days=settings.refresh_token_ttl_days)
    )


def decodificar_token(token: str, tipo_esperado: TipoToken | None = None) -> dict[str, Any]:
    """Valida assinatura, expiracao e tipo. Levanta ErroDeToken em qualquer falha.

    A checagem de tipo importa: sem ela, um refresh token seria aceito como
    access token e a separacao de validades perderia o sentido.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "tipo"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ErroDeToken("token expirado") from exc
    except jwt.InvalidTokenError as exc:
        raise ErroDeToken("token invalido") from exc

    if tipo_esperado and payload.get("tipo") != tipo_esperado:
        raise ErroDeToken(
            f"tipo de token incorreto: esperado {tipo_esperado}, "
            f"recebido {payload.get('tipo')}"
        )
    return payload
