"""Biblioteca compartilhada pelos microsservicos do Prismo.

Contem apenas infraestrutura transversal (configuracao, logs, probes, cache,
banco, seguranca). Regra de ouro: nada de regra de negocio aqui. Se um dominio
especifico vazasse para ca, os servicos deixariam de ser independentes e
perderiamos a principal vantagem de ter microsservicos.

**Importacao preguicosa (PEP 562).** Os nomes abaixo so carregam o modulo que
os define quando sao efetivamente usados. Sem isso, qualquer `import
prismo_shared.models` executaria este arquivo, que importaria `app.py`, que
importa FastAPI e structlog — e o migrator, que so precisa do SQLAlchemy,
quebraria por falta de dependencia que ele nao tem motivo para instalar.

O efeito pratico: cada imagem instala apenas o que o seu servico usa, e o
pacote compartilhado nao impoe as dependencias de um servico aos outros.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

__version__ = "0.2.0"

# nome exportado -> modulo que o define
_EXPORTACOES = {
    "create_app": ".app",
    "Dependency": ".health",
    "Settings": ".settings",
    "get_settings": ".settings",
    "configure_logging": ".logging",
    "get_logger": ".logging",
    "get_redis": ".cache",
    "close_redis": ".cache",
    "ping_redis": ".cache",
}

__all__ = [*sorted(_EXPORTACOES), "__version__"]


def __getattr__(nome: str) -> Any:
    modulo = _EXPORTACOES.get(nome)
    if modulo is None:
        raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
    valor = getattr(import_module(modulo, __name__), nome)
    # Guarda no proprio modulo: a partir daqui o acesso e direto, sem passar
    # mais por esta funcao.
    globals()[nome] = valor
    return valor


def __dir__() -> list[str]:
    return __all__


if TYPE_CHECKING:  # pragma: no cover - apenas para analise estatica
    from .app import create_app  # noqa: F401
    from .cache import close_redis, get_redis, ping_redis  # noqa: F401
    from .health import Dependency  # noqa: F401
    from .logging import configure_logging, get_logger  # noqa: F401
    from .settings import Settings, get_settings  # noqa: F401
