"""Configuracao centralizada, carregada de variaveis de ambiente.

Todo servico do Prismo le a sua configuracao daqui. Nenhum valor sensivel fica
no codigo: em desenvolvimento vem do arquivo .env, em producao vem de um
Secret do Kubernetes. Os dois chegam ao processo da mesma forma (variaveis de
ambiente), por isso o codigo nao muda entre os dois ambientes.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Identidade do servico -------------------------------------------
    # Sobrescrito por servico no docker-compose. Aparece em todos os logs e
    # metricas, e e o que permite filtrar por servico no Grafana.
    service_name: str = "prismo"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    # --- Banco de dados (Supabase) ---------------------------------------
    # Supabase e Postgres gerenciado, entao a URL tem o formato padrao do
    # Postgres. Para usar o container local em vez do Supabase, basta apontar
    # esta variavel para postgresql+asyncpg://prismo:prismo@postgres:5432/prismo
    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    # --- Redis ------------------------------------------------------------
    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 300

    # --- Autenticacao -----------------------------------------------------
    jwt_secret: str = "troque-isto-em-producao"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14

    # --- Conector GitHub --------------------------------------------------
    github_client_id: str = ""
    github_client_secret: str = ""
    github_api_base: str = "https://api.github.com"

    # --- Storage (Google Drive) ------------------------------------------
    google_service_account_file: str = "/run/secrets/google-sa.json"
    google_drive_folder_id: str = ""

    # --- Enderecos internos dos servicos ---------------------------------
    # No Docker Compose e no Kubernetes o nome do servico resolve via DNS
    # interno, por isso o host e o nome do container/Service e nao localhost.
    auth_url: str = "http://auth:8000"
    portfolio_url: str = "http://portfolio:8000"
    sync_url: str = "http://sync:8000"
    seo_url: str = "http://seo:8000"
    gateway_url: str = "http://gateway:8000"

    # --- Rate limiting ----------------------------------------------------
    rate_limit_per_minute: int = 120

    http_timeout_seconds: float = Field(default=10.0, ge=1.0)


@lru_cache
def get_settings() -> Settings:
    """Devolve a configuracao, lida uma unica vez por processo."""
    return Settings()
