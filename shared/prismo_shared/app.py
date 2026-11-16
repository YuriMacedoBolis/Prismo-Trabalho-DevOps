"""Fabrica de aplicacao compartilhada por todos os servicos do Prismo.

Cada microsservico chama `create_app(...)` e recebe uma aplicacao FastAPI que
ja vem com:

  - logs estruturados em JSON
  - um request-id propagado entre servicos (header X-Request-ID)
  - /health   liveness probe
  - /ready    readiness probe, com as dependencias do servico
  - /metrics  metricas no formato Prometheus
  - tratamento de erro que nunca vaza stack trace para o cliente

Centralizar isso garante que os sete servicos se comportem igual em producao,
que e o que torna a observabilidade util.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from .health import Dependency, run_checks
from .logging import configure_logging, get_logger
from .settings import Settings, get_settings

REQUEST_COUNT = Counter(
    "prismo_http_requests_total",
    "Total de requisicoes HTTP recebidas.",
    ["service", "method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "prismo_http_request_duration_seconds",
    "Duracao das requisicoes HTTP em segundos.",
    ["service", "method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

SERVICE_INFO = Counter(
    "prismo_service_starts_total",
    "Numero de inicializacoes do servico (reinicios aparecem aqui).",
    ["service", "environment"],
)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Gera o request-id, mede a latencia e registra uma linha de log por request."""

    def __init__(self, app, service_name: str) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.log = get_logger("http")

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Se a requisicao vem de outro servico do Prismo, reaproveitamos o id
        # para que a cadeia inteira possa ser correlacionada nos logs.
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]

        structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id

        # Usamos o template da rota ("/users/{id}") e nao o caminho real
        # ("/users/42") como label. Caminhos reais criariam uma serie temporal
        # nova por usuario e explodiriam a memoria do Prometheus.
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.perf_counter() - started
            self.log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(elapsed * 1000, 2),
            )
            structlog.contextvars.unbind_contextvars("request_id")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )

        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        path_label = getattr(route, "path", request.url.path)

        REQUEST_COUNT.labels(
            self.service_name, request.method, path_label, str(response.status_code)
        ).inc()
        REQUEST_LATENCY.labels(self.service_name, request.method, path_label).observe(
            elapsed
        )

        response.headers["X-Request-ID"] = request_id

        # As probes batem a cada poucos segundos; logar todas poluiria tudo.
        if path_label not in ("/health", "/ready", "/metrics"):
            self.log.info(
                "request",
                method=request.method,
                path=path_label,
                status=response.status_code,
                duration_ms=round(elapsed * 1000, 2),
            )

        structlog.contextvars.unbind_contextvars("request_id")
        return response


def create_app(
    service_name: str,
    *,
    description: str = "",
    dependencies: list[Dependency] | None = None,
    on_startup: Callable[[FastAPI], Awaitable[None]] | None = None,
    on_shutdown: Callable[[FastAPI], Awaitable[None]] | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(service_name, settings.log_level)
    log = get_logger(service_name)
    deps = dependencies or []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        SERVICE_INFO.labels(service_name, settings.environment).inc()
        log.info("service_starting", environment=settings.environment)
        if on_startup:
            await on_startup(app)
        log.info("service_ready")
        yield
        log.info("service_stopping")
        if on_shutdown:
            await on_shutdown(app)

    app = FastAPI(
        title=f"Prismo :: {service_name}",
        description=description,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.state.settings = settings
    app.state.service_name = service_name
    app.add_middleware(ObservabilityMiddleware, service_name=service_name)

    @app.get("/health", tags=["infra"], summary="Liveness probe")
    async def health() -> dict:
        """O processo esta vivo. Nao consulta dependencia externa de proposito."""
        return {"status": "alive", "service": service_name}

    @app.get("/ready", tags=["infra"], summary="Readiness probe")
    async def ready(response: Response) -> dict:
        """O servico consegue atender: dependencias criticas respondendo."""
        ok, detail = await run_checks(deps)
        response.status_code = 200 if ok else 503
        return {
            "status": "ready" if ok else "not_ready",
            "service": service_name,
            "dependencies": detail,
        }

    @app.get("/metrics", tags=["infra"], include_in_schema=False)
    async def metrics() -> Response:
        """Endpoint raspado pelo Prometheus a cada 15s."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
