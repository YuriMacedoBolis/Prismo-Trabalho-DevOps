"""Acesso ao banco: engine assincrona, sessoes e a verificacao de saude.

Um engine por processo. O engine mantem um pool de conexoes; criar um por
requisicao significaria abrir e fechar conexao TCP toda hora, e o custo do
handshake supera em muito o da consulta.

Dimensionamento do pool: `pool_size` e o numero de conexoes mantidas abertas,
`max_overflow` quantas a mais podem ser abertas num pico. O limite real esta do
outro lado: o Postgres aceita 100 conexoes por padrao. Com varios servicos e
varias replicas de cada um, esse teto chega rapido — por isso os valores
baixos e `pool_pre_ping`, que descarta conexao morta antes de usar.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .logging import get_logger
from .settings import get_settings

log = get_logger("db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            # Testa a conexao com um SELECT 1 antes de entregar. Sem isto, uma
            # conexao derrubada pelo servidor (reinicio do pod, timeout de
            # firewall) so e descoberta quando a consulta falha.
            pool_pre_ping=True,
            # Recicla conexoes com mais de 30 min, evitando acumular conexao
            # ociosa que o Postgres mantem viva mas ja nao serve.
            pool_recycle=1800,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependencia do FastAPI: uma sessao por requisicao.

    Commit automatico no sucesso, rollback em qualquer excecao. Isso evita o
    erro mais comum com ORM — deixar a transacao aberta depois de uma falha e
    contaminar a proxima operacao que reutilizar a conexao.
    """
    async with get_session_factory()() as sessao:
        try:
            yield sessao
            await sessao.commit()
        except Exception:
            await sessao.rollback()
            raise


async def ping_db() -> None:
    """Usada pela readiness probe. Levanta excecao se o banco nao responder."""
    async with get_engine().connect() as conexao:
        await conexao.execute(text("SELECT 1"))


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
