"""Schema `auth`: contas de usuario. Dominio do servico auth."""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Carimbos, ChavePrimariaUUID

SCHEMA = "auth"


class Usuario(Base, ChavePrimariaUUID, Carimbos):
    __tablename__ = "usuarios"
    __table_args__ = {"schema": SCHEMA}

    # Guardado sempre em minusculas (normalizado no servico). Sem isso,
    # "Yuri@x.com" e "yuri@x.com" criariam duas contas para a mesma pessoa.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)

    nome: Mapped[str] = mapped_column(String(120), nullable=False)

    # Argon2id. O nome do campo diz o que e para evitar qualquer duvida: aqui
    # nunca entra senha em texto, em nenhuma circunstancia.
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Desativar em vez de apagar: remover a linha quebraria os portfolios que
    # referenciam este id. Conta inativa nao autentica.
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - auxilio de depuracao
        return f"<Usuario {self.email}>"
