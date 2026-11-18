"""Contratos de entrada e saida do servico auth.

Modelo Pydantic nao e o modelo do banco, de proposito. O modelo do banco tem
`senha_hash`; o de saida nunca pode te-lo. Manter os dois separados torna
impossivel vazar um campo por descuido — nao existe caminho do `senha_hash`
ate a resposta HTTP.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegistroEntrada(BaseModel):
    email: EmailStr
    nome: str = Field(min_length=2, max_length=120)
    # 8 e o minimo da recomendacao atual da OWASP. O limite superior existe
    # porque o Argon2 trabalha sobre a senha inteira: sem teto, uma senha de
    # megabytes viraria negacao de servico barata.
    senha: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("nome")
    @classmethod
    def limpar_nome(cls, v: str) -> str:
        return " ".join(v.split())


class LoginEntrada(BaseModel):
    email: EmailStr
    senha: str

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: str) -> str:
        return v.strip().lower()


class RefreshEntrada(BaseModel):
    refresh_token: str


class UsuarioSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    nome: str
    ativo: bool
    criado_em: datetime


class TokensSaida(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expira_em_segundos: int


class SessaoSaida(BaseModel):
    usuario: UsuarioSaida
    tokens: TokensSaida
