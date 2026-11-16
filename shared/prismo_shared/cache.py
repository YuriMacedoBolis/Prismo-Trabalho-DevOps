"""Cliente Redis compartilhado.

Mantemos um unico pool de conexoes por processo. Abrir conexao por requisicao
seria o gargalo mais obvio do sistema: o custo do handshake TCP supera em
muito o tempo da operacao em si.
"""

from __future__ import annotations

import redis.asyncio as redis

from .settings import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def ping_redis() -> None:
    """Usada pela readiness probe. Levanta excecao se o Redis nao responder."""
    await get_redis().ping()
