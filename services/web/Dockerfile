# =============================================================================
#  Prismo :: web (renderizacao server-side)
#  Contexto de build: RAIZ do repositorio. Ver docker-compose.yml.
# =============================================================================

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY shared/requirements.txt ./req-shared.txt
COPY services/web/requirements.txt ./req-service.txt

RUN pip install --upgrade pip \
    && pip install -r req-shared.txt -r req-service.txt

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    SERVICE_NAME=web

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app shared/prismo_shared ./prismo_shared
COPY --chown=app:app services/web/app ./app
COPY --chown=app:app services/web/templates ./templates
COPY --chown=app:app services/web/static ./static

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# Ver comentario no Dockerfile do gateway sobre --no-access-log e --proxy-headers.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--no-access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
