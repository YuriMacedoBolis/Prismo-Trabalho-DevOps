# =============================================================================
#  Prismo :: seo
#
#  Build multi-stage. O estagio `builder` tem compilador e cabecalhos para
#  montar as dependencias; o estagio final so recebe o virtualenv pronto.
#  Resultado: a imagem publicada nao carrega gcc nem cache do pip.
#
#  IMPORTANTE: o contexto de build e a RAIZ do repositorio, nao esta pasta,
#  porque precisamos copiar `shared/` tambem. Ver docker-compose.yml.
# =============================================================================

# meta tags, dados estruturados, sitemap e auditoria

# ---------- Estagio 1: build das dependencias --------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiamos apenas os requirements primeiro. Enquanto eles nao mudarem, o
# Docker reaproveita esta camada e o build leva segundos em vez de minutos.
COPY shared/requirements.txt ./req-shared.txt
COPY shared/requirements-db.txt ./req-db.txt
COPY services/seo/requirements.txt ./req-service.txt

RUN pip install --upgrade pip \
    && pip install -r req-shared.txt -r req-db.txt -r req-service.txt

# ---------- Estagio 2: imagem final ------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    SERVICE_NAME=seo

# Container nunca roda como root. Se a aplicacao for comprometida, o atacante
# cai em um usuario sem privilegio. Pergunta frequente de arguicao.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app shared/prismo_shared ./prismo_shared
COPY --chown=app:app services/seo/app ./app

USER app

EXPOSE 8000

# Healthcheck do Docker. No Kubernetes quem faz esse papel e a liveness probe
# declarada no Deployment, apontando para o mesmo endpoint.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# --no-access-log: o uvicorn reconfigura o logging depois do nosso setup e
#   voltaria a imprimir acesso em texto puro, misturado ao nosso JSON. Quem
#   registra cada requisicao e o nosso middleware, em JSON e com request_id.
# --proxy-headers: atras do Ingress, sem isto todo request.client.host seria o
#   IP do proxy, e o rate limiting por IP contaria todo mundo junto.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--no-access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
