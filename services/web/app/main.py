"""Servico web do Prismo: renderizacao server-side.

Por que SSR e nao uma SPA: o requisito de SEO do projeto exige que o
rastreador do Google receba HTML pronto, com meta tags e conteudo, sem
depender de JavaScript. Uma SPA entregaria uma pagina vazia. As animacoes
continuam sendo client-side; o conteudo e que vem do servidor.

Na Fase 1 este servico entrega a landing page e a pagina /status, que consulta
a saude dos demais servicos ao vivo. A edicao do portfolio e a pagina publica
entram na Fase 4.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from prismo_shared import (
    Dependency,
    close_redis,
    create_app,
    get_logger,
    get_settings,
    ping_redis,
)

settings = get_settings()
log = get_logger("web")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = create_app(
    "web",
    description="Renderizacao server-side do Prismo (landing, portfolio publico).",
    # Redis nao e critico para o web: sem cache a pagina fica mais lenta, mas
    # ainda e renderizada. Marcar como nao-critico evita tirar o site do ar
    # por causa de uma dependencia de performance.
    dependencies=[Dependency(name="redis", check=ping_redis, critical=False)],
    on_shutdown=lambda _app: close_redis(),
    settings=settings,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# Servicos monitorados na pagina /status. A lista cresce a cada fase.
MONITORED = [
    ("gateway", settings.gateway_url, "Ponto de entrada da API"),
    ("auth", settings.auth_url, "Contas, JWT e sessoes"),
    ("portfolio", settings.portfolio_url, "Projetos, temas e score"),
    ("web", "http://127.0.0.1:8000", "Renderizacao server-side"),
]

PLANNED = [
    ("sync", "Conector do GitHub", "Fase 3"),
    ("worker", "Sincronizacao automatica (Celery)", "Fase 3"),
    ("seo", "Meta tags, sitemap e auditoria", "Fase 3"),
]


async def probe(name: str, base_url: str, descricao: str) -> dict:
    """Consulta /ready de um servico e traduz o resultado para a interface."""
    url = f"{base_url.rstrip('/')}/ready"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resposta = await client.get(url)
        pronto = resposta.status_code == 200
        corpo = resposta.json()
        return {
            "nome": name,
            "descricao": descricao,
            "estado": "online" if pronto else "degradado",
            "dependencias": corpo.get("dependencies", {}),
            "latencia_ms": round(resposta.elapsed.total_seconds() * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("probe_falhou", servico=name, erro=str(exc))
        return {
            "nome": name,
            "descricao": descricao,
            "estado": "offline",
            "dependencias": {},
            "latencia_ms": None,
        }


@app.get("/", response_class=HTMLResponse, tags=["paginas"])
async def landing(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "titulo": "Prismo",
            "subtitulo": "Seu portfolio, sempre atualizado.",
            "ambiente": settings.environment,
        },
    )


@app.get("/status", response_class=HTMLResponse, tags=["paginas"])
async def status(request: Request):
    """Pagina publica de status, lendo /ready de cada servico em paralelo."""
    resultados = await asyncio.gather(*(probe(*item) for item in MONITORED))
    total_online = sum(1 for r in resultados if r["estado"] == "online")

    return templates.TemplateResponse(
        request=request,
        name="status.html",
        context={
            "titulo": "Status dos servicos",
            "servicos": resultados,
            "planejados": PLANNED,
            "total_online": total_online,
            "total": len(resultados),
            "ambiente": settings.environment,
        },
    )
