# =============================================================================
#  Prismo :: worker
#
#  Celery com pool de threads. Nao e um servidor web, mas publica /metrics
#  por um servidor HTTP minimo do proprio prometheus_client — sem isso o
#  Prometheus nao teria como raspar as metricas de sincronizacao, que sao
#  justamente as que o HPA consome na Fase 5.
#
#  Contexto de build: RAIZ do repositorio.
# =============================================================================

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY shared/requirements.txt ./req-shared.txt
COPY shared/requirements-db.txt ./req-db.txt
COPY services/worker/requirements.txt ./req-service.txt

RUN pip install --upgrade pip \
    && pip install -r req-shared.txt -r req-db.txt -r req-service.txt

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    SERVICE_NAME=worker

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app shared/prismo_shared ./prismo_shared
COPY --chown=app:app services/worker/app ./app

USER app

EXPOSE 8000

# `celery inspect ping` pergunta ao worker se ele responde. Diferente de um
# healthcheck de porta: o processo pode estar vivo com a fila travada, e e
# justamente esse caso que precisamos detectar.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD celery -A app.celery_app inspect ping -d celery@$HOSTNAME || exit 1

# --pool=threads: o trabalho e de I/O (API externa + banco), nao de CPU, e
# manter tudo em um processo faz o contador do Prometheus ficar correto.
CMD ["celery", "-A", "app.celery_app", "worker", \
     "--loglevel=INFO", \
     "--pool=threads", \
     "--concurrency=4", \
     "-E"]
