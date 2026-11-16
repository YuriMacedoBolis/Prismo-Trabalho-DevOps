"""Biblioteca compartilhada pelos microsservicos do Prismo.

Contem apenas infraestrutura transversal (configuracao, logs, probes, cache).
Regra de ouro: nada de regra de negocio aqui. Se um dominio especifico
vazasse para ca, os servicos deixariam de ser independentes e perderiamos a
principal vantagem de ter microsservicos.
"""

from .app import create_app
from .cache import close_redis, get_redis, ping_redis
from .health import Dependency
from .logging import configure_logging, get_logger
from .settings import Settings, get_settings

__all__ = [
    "Dependency",
    "Settings",
    "close_redis",
    "configure_logging",
    "create_app",
    "get_logger",
    "get_redis",
    "get_settings",
    "ping_redis",
]

__version__ = "0.1.0"
