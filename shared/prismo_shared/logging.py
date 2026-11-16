"""Logs estruturados em JSON, para a aplicacao e para as bibliotecas.

Por que JSON e nao texto: em um ambiente de microsservicos os logs de sete
servicos acabam misturados. Com JSON cada linha e um objeto com `service`,
`request_id`, `level` e `event`, o que permite filtrar e correlacionar uma
requisicao que atravessou varios servicos. Escrevemos sempre em stdout, nunca
em arquivo, porque no Docker e no Kubernetes a coleta de logs e feita a partir
da saida padrao do container (`docker logs` / `kubectl logs`).

O detalhe que exige cuidado e o uvicorn. Ele instala os seus proprios handlers
depois que este modulo roda, entao nao basta limpar os handlers uma vez: o
logger `uvicorn.access` precisa ficar com `propagate = False`. O uvicorn decide
se registra acesso chamando `access_logger.hasHandlers()`, que devolve True se
QUALQUER logger ancestral tiver handler. Com propagacao ligada, ele encontra o
handler da raiz e volta a imprimir acesso em texto puro, ignorando a flag
`--no-access-log`. Quem registra requisicao aqui e o nosso middleware, que alem
do basico tem `duration_ms` e `request_id`.
"""

import logging
import sys

import structlog


def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Processadores comuns: valem tanto para os logs emitidos via structlog
    # quanto para os emitidos por bibliotecas pelo logging padrao.
    processadores_comuns = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *processadores_comuns,
            # Entrega o evento ao formatter do logging padrao em vez de
            # renderizar aqui. E o que faz structlog e logging produzirem
            # exatamente o mesmo formato de saida.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # Aplicado aos registros vindos de bibliotecas (uvicorn, httpx, redis),
        # que nao passaram pelos processadores do structlog.
        foreign_pre_chain=processadores_comuns,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    raiz = logging.getLogger()
    raiz.handlers.clear()
    raiz.addHandler(handler)
    raiz.setLevel(level)

    # Estes devem aparecer (inicializacao, erro, aviso), em JSON pelo handler
    # da raiz.
    for nome in ("uvicorn", "uvicorn.error", "fastapi", "httpx"):
        biblioteca = logging.getLogger(nome)
        biblioteca.handlers.clear()
        biblioteca.propagate = True

    # Silenciado de proposito: ver a explicacao no docstring do modulo.
    acesso = logging.getLogger("uvicorn.access")
    acesso.handlers.clear()
    acesso.propagate = False

    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
