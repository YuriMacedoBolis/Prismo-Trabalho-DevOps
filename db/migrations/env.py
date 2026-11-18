"""Ambiente do Alembic.

Duas particularidades deste projeto:

1. **A URL vem do ambiente**, nunca do alembic.ini, para nao versionar
   credencial. O sufixo `+asyncpg` e removido: as migrations rodam de forma
   sincrona, com psycopg, porque DDL nao se beneficia de I/O assincrono e o
   codigo fica mais simples de depurar quando algo falha no meio.

2. **Varios schemas.** `include_schemas=True` faz o autogenerate enxergar
   `auth` e `portfolio`; sem isso ele compararia apenas o `public` e proporia
   apagar tudo o que existe nos outros.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# A biblioteca compartilhada e copiada para /app na imagem do migrator; em
# execucao local, ela esta dois niveis acima deste arquivo.
RAIZ = Path(__file__).resolve().parents[2]
for caminho in (str(RAIZ / "shared"), "/app"):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

from prismo_shared.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

SCHEMAS = ("auth", "portfolio")


def _url_do_ambiente() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL nao definida. As migrations nao sabem em qual banco rodar."
        )
    # Driver sincrono para DDL. Precisa ser explicito: diante de um
    # `postgresql://` sem driver, o SQLAlchemy assume psycopg2, que nao
    # instalamos — usamos psycopg 3.
    url = url.replace("+asyncpg", "").replace("+psycopg2", "")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def incluir_objeto(objeto, nome, tipo, reflexo, objeto_comparado) -> bool:
    """Mantem o autogenerate restrito aos nossos schemas.

    Sem este filtro, o Alembic veria a tabela `alembic_version` e tabelas de
    extensoes do Postgres e proporia remove-las.
    """
    if tipo == "table":
        return objeto.schema in SCHEMAS
    return True


def run_migrations_offline() -> None:
    """Gera o SQL sem conectar — util para revisar o que sera executado."""
    context.configure(
        url=_url_do_ambiente(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_object=incluir_objeto,
        version_table_schema="public",
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    secao = config.get_section(config.config_ini_section, {})
    secao["sqlalchemy.url"] = _url_do_ambiente()

    conectavel = engine_from_config(
        secao, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with conectavel.connect() as conexao:
        context.configure(
            connection=conexao,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=incluir_objeto,
            # O controle de versao fica no `public`, fora dos schemas de
            # dominio: ele e do Alembic, nao de nenhum servico.
            version_table_schema="public",
            # Detecta mudanca de tipo de coluna, que por padrao passa batido.
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
