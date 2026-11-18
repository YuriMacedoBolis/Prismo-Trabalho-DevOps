# =============================================================================
#  Prismo :: migrator
#
#  Container de execucao unica: aplica `alembic upgrade head` e encerra.
#  Nao e um servico — nao fica no ar, nao tem porta, nao tem healthcheck.
#
#  Por que um container so para isso, em vez de rodar a migration no startup
#  de cada servico: com varias replicas, todas tentariam migrar ao mesmo tempo
#  na mesma tabela, e duas replicas aplicando DDL concorrente e receita de
#  deadlock. Aqui exatamente um processo migra, e os servicos so sobem depois
#  que ele termina com sucesso (`service_completed_successfully` no Compose;
#  um initContainer ou um Job no Kubernetes).
#
#  Contexto de build: RAIZ do repositorio.
# =============================================================================

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY shared/requirements-db.txt ./req-db.txt

# O migrator nao sobe servidor HTTP: so precisa do Alembic, do SQLAlchemy e de
# um driver sincrono. Nao instala FastAPI nem uvicorn.
RUN pip install --upgrade pip \
    && pip install -r req-db.txt "psycopg[binary]==3.2.3"

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Os modelos vao para /app/prismo_shared, que o env.py adiciona ao sys.path:
# o autogenerate precisa enxergar o metadata completo.
COPY --chown=app:app shared/prismo_shared ./prismo_shared
COPY --chown=app:app db/alembic.ini ./alembic.ini
COPY --chown=app:app db/migrations ./migrations

USER app

# `upgrade head` e idempotente: se o banco ja esta na ultima versao, o Alembic
# nao faz nada e sai com codigo 0. Isso permite subir a stack quantas vezes
# quiser sem tratamento especial.
CMD ["alembic", "upgrade", "head"]
