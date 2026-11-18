"""Contratos de entrada e saida do servico portfolio."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

TEMAS = {"midnight", "aurora", "brutalist", "paper"}

# Reservados porque colidiriam com rotas do proprio site: o portfolio publico
# mora em /{slug}, entao um slug chamado "api" tornaria a API inalcancavel.
SLUGS_RESERVADOS = {
    "api", "admin", "app", "docs", "static", "media", "status", "health",
    "ready", "metrics", "login", "registrar", "sitemap", "robots", "sobre",
    "painel", "u", "assets", "favicon",
}


def gerar_slug(texto: str) -> str:
    """Transforma um titulo em slug amigavel para URL.

    NFKD separa a letra do acento e o filtro remove os acentos: "Daniel
    Lourenço" vira "daniel-lourenco", nao "daniel-louren-o". Feito a mao para
    nao adicionar uma dependencia por tao pouco.
    """
    normalizado = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in normalizado if not unicodedata.combining(c))
    minusculo = sem_acento.lower()
    apenas_validos = re.sub(r"[^a-z0-9]+", "-", minusculo)
    return apenas_validos.strip("-")[:60] or "portfolio"


class PortfolioEntrada(BaseModel):
    titulo: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=60)
    headline: str | None = Field(default=None, max_length=200)
    bio: str | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    tema: str = "midnight"
    publicado: bool = False

    @field_validator("tema")
    @classmethod
    def validar_tema(cls, v: str) -> str:
        if v not in TEMAS:
            raise ValueError(f"tema deve ser um de: {', '.join(sorted(TEMAS))}")
        return v

    @field_validator("slug")
    @classmethod
    def validar_slug(cls, v: str | None) -> str | None:
        if v is None:
            return None
        limpo = gerar_slug(v)
        if len(limpo) < 2:
            raise ValueError("slug muito curto")
        if limpo in SLUGS_RESERVADOS:
            raise ValueError(f"'{limpo}' e um endereco reservado do sistema")
        return limpo


class PortfolioAtualizacao(BaseModel):
    """Atualizacao parcial: tudo opcional, so o enviado e alterado."""

    titulo: str | None = Field(default=None, min_length=2, max_length=120)
    headline: str | None = Field(default=None, max_length=200)
    bio: str | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    tema: str | None = None
    publicado: bool | None = None

    @field_validator("tema")
    @classmethod
    def validar_tema(cls, v: str | None) -> str | None:
        if v is not None and v not in TEMAS:
            raise ValueError(f"tema deve ser um de: {', '.join(sorted(TEMAS))}")
        return v


class ProjetoEntrada(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    descricao: str | None = None
    url: str | None = Field(default=None, max_length=500)
    imagem_url: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=12)
    linguagem: str | None = Field(default=None, max_length=40)
    destaque_manual: bool = False
    oculto: bool = False
    atualizado_na_origem: datetime | None = None

    @field_validator("tags")
    @classmethod
    def limpar_tags(cls, v: list[str]) -> list[str]:
        vistas: list[str] = []
        for tag in v:
            limpa = tag.strip().lower()[:40]
            if limpa and limpa not in vistas:
                vistas.append(limpa)
        return vistas


class ProjetoAtualizacao(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=200)
    descricao: str | None = None
    url: str | None = Field(default=None, max_length=500)
    imagem_url: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = None
    linguagem: str | None = Field(default=None, max_length=40)
    destaque_manual: bool | None = None
    oculto: bool | None = None


class ProjetoSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    titulo: str
    descricao: str | None
    url: str | None
    imagem_url: str | None
    tags: list[str]
    plataforma: str
    linguagem: str | None
    estrelas: int
    atualizado_na_origem: datetime | None
    destaque_manual: bool
    oculto: bool
    score: float
    criado_em: datetime


class PortfolioSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    usuario_id: uuid.UUID
    slug: str
    titulo: str
    headline: str | None
    bio: str | None
    avatar_url: str | None
    tema: str
    publicado: bool
    criado_em: datetime
    atualizado_em: datetime


class PortfolioPublico(BaseModel):
    """O que o visitante ve. Sem `usuario_id` e sem projeto oculto."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    titulo: str
    headline: str | None
    bio: str | None
    avatar_url: str | None
    tema: str
    projetos: list[ProjetoSaida]
