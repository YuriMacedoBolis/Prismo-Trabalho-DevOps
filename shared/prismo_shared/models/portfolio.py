"""Schema `portfolio`: conteudo, conexoes e historico de sincronizacao.

Dominio dos servicos portfolio, sync e worker.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Carimbos, ChavePrimariaUUID

SCHEMA = "portfolio"


class Plataforma(str, enum.Enum):
    """Origem de um projeto.

    `manual` e o padrao; `github` marca o que foi importado. A distincao
    importa na hora de sincronizar: o worker so pode sobrescrever o que ele
    mesmo trouxe, nunca o que a pessoa escreveu a mao.
    """

    MANUAL = "manual"
    GITHUB = "github"


class StatusSync(str, enum.Enum):
    EXECUTANDO = "executando"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"


class Portfolio(Base, ChavePrimariaUUID, Carimbos):
    __tablename__ = "portfolios"
    __table_args__ = {"schema": SCHEMA}

    # Sem ForeignKey para auth.usuarios de proposito: e a fronteira entre os
    # dominios. Ver a explicacao no __init__.py do pacote.
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )

    # A URL publica: prismo.app/{slug}. E o requisito de "URLs amigaveis" do
    # enunciado, e por isso e unico e indexado.
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)

    titulo: Mapped[str] = mapped_column(String(120), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(200))
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(500))

    # Um dos extras escolhidos: midnight, aurora, brutalist, paper.
    tema: Mapped[str] = mapped_column(String(32), default="midnight", nullable=False)

    # Rascunho ate ser publicado: evita que um portfolio pela metade apareca
    # no sitemap e seja indexado pelo Google.
    publicado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    projetos: Mapped[list["Projeto"]] = relationship(
        back_populates="portfolio",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Portfolio /{self.slug}>"


class Projeto(Base, ChavePrimariaUUID, Carimbos):
    __tablename__ = "projetos"
    __table_args__ = (
        # Impede importar o mesmo repositorio duas vezes. E a deduplicacao do
        # worker garantida pelo banco, nao pela logica da aplicacao: se dois
        # workers sincronizarem o mesmo usuario ao mesmo tempo, o segundo
        # esbarra nesta constraint em vez de duplicar o projeto.
        UniqueConstraint(
            "portfolio_id", "plataforma", "id_externo", name="projeto_origem_unica"
        ),
        {"schema": SCHEMA},
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.portfolios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    imagem_url: Mapped[str | None] = mapped_column(String(500))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list, nullable=False)

    # --- Origem -----------------------------------------------------------
    plataforma: Mapped[str] = mapped_column(
        String(20), default=Plataforma.MANUAL.value, nullable=False
    )
    # Id do item na plataforma de origem (no GitHub, o id numerico do repo).
    # Nulo quando o projeto foi criado a mao.
    id_externo: Mapped[str | None] = mapped_column(String(120))

    # --- Sinais usados pelo score ----------------------------------------
    linguagem: Mapped[str | None] = mapped_column(String(40))
    estrelas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Data da ultima alteracao NA ORIGEM, nao no nosso banco. E esta que mede
    # recencia: `atualizado_em` mudaria a cada sincronizacao e faria todo
    # projeto parecer recem-atualizado.
    atualizado_na_origem: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Destaque dinamico ------------------------------------------------
    # Fixar manualmente no topo. O humano vence o algoritmo.
    destaque_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Calculado pelo modulo de ranking. Indexado em ordem decrescente porque
    # toda listagem publica ordena por ele.
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)

    oculto: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    portfolio: Mapped[Portfolio] = relationship(back_populates="projetos")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Projeto {self.titulo!r} score={self.score:.3f}>"


class Conexao(Base, ChavePrimariaUUID, Carimbos):
    """Conta externa ligada por um usuario. Na Fase 3, so GitHub."""

    __tablename__ = "conexoes"
    __table_args__ = (
        UniqueConstraint("usuario_id", "plataforma", name="conexao_unica_por_plataforma"),
        {"schema": SCHEMA},
    )

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    plataforma: Mapped[str] = mapped_column(String(20), nullable=False)

    # Nome de usuario na plataforma de origem (ex.: YuriMacedoBolis).
    conta: Mapped[str] = mapped_column(String(120), nullable=False)

    # Token OAuth cifrado antes de gravar — nunca em texto. A cifragem entra
    # com o conector, na Fase 3.
    token_cifrado: Mapped[str | None] = mapped_column(Text)

    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ultima_sync_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Conexao {self.plataforma}:{self.conta}>"


class Sincronizacao(Base, ChavePrimariaUUID):
    """Registro de cada execucao do worker.

    Existe para responder "por que meu projeto novo nao apareceu?" sem abrir
    log. Tambem e a fonte das metricas de fila que o HPA usa na Fase 5.
    """

    __tablename__ = "sincronizacoes"
    __table_args__ = {"schema": SCHEMA}

    conexao_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.conexoes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20), default=StatusSync.EXECUTANDO.value, nullable=False
    )
    iniciada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    itens_novos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    itens_atualizados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    erro: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Sincronizacao {self.status} +{self.itens_novos}>"
