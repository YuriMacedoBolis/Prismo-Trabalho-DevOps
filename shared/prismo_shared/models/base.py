"""Base declarativa e convencoes comuns a todas as tabelas."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Nomear indices e constraints por convencao, em vez de deixar o Postgres
# inventar. Sem isto, o Alembic gera migrations que nao conseguem remover uma
# constraint por nao saber o nome que o banco deu a ela.
CONVENCAO_DE_NOMES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=CONVENCAO_DE_NOMES)


class Base(DeclarativeBase):
    metadata = metadata


class ChavePrimariaUUID:
    """Id como UUID gerado pelo proprio Postgres.

    UUID em vez de inteiro sequencial por dois motivos: nao revela quantos
    usuarios existem nem a ordem de cadastro, e permite gerar o id antes de
    gravar, o que simplifica operacoes distribuidas entre servicos.

    `gen_random_uuid()` e nativa do Postgres 13+, sem precisar de extensao.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


class Carimbos:
    """Datas de criacao e alteracao, mantidas pelo banco.

    `server_default` e `onupdate` no servidor garantem o preenchimento mesmo
    quando a escrita vem de uma migration ou de um psql, nao so pelo ORM.
    Sempre com fuso (`timestamptz`): guardar horario sem fuso e fonte garantida
    de erro quando o servidor e o usuario estao em zonas diferentes.
    """

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
