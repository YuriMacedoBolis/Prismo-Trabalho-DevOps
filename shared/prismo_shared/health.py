"""Verificacoes de saude usadas pelas probes do Docker e do Kubernetes.

A distincao entre as duas probes importa e e pergunta classica de arguicao:

  liveness  (`/health`)  -> "o processo esta vivo?"
                            Se falhar, o Kubernetes MATA e recria o container.
                            Por isso nao pode depender de nada externo: se o
                            Redis cair, matar a aplicacao nao resolve nada.

  readiness (`/ready`)   -> "o processo consegue atender agora?"
                            Se falhar, o Kubernetes apenas TIRA o pod do
                            balanceamento, sem reiniciar. Aqui sim checamos as
                            dependencias (Redis, banco), porque sem elas a
                            resposta sairia errada.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

CheckFn = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class Dependency:
    """Uma dependencia externa verificada pela readiness probe."""

    name: str
    check: CheckFn
    critical: bool = True


async def run_checks(dependencies: list[Dependency]) -> tuple[bool, dict]:
    """Executa todas as verificacoes em paralelo e resume o resultado."""
    if not dependencies:
        return True, {}

    results = await asyncio.gather(
        *(_safe(dep) for dep in dependencies), return_exceptions=False
    )

    detail: dict[str, dict] = {}
    ready = True
    for dep, (ok, error) in zip(dependencies, results):
        detail[dep.name] = {"ok": ok}
        if not ok:
            detail[dep.name]["error"] = error
            if dep.critical:
                ready = False
    return ready, detail


async def _safe(dep: Dependency) -> tuple[bool, str | None]:
    try:
        await asyncio.wait_for(dep.check(), timeout=3.0)
        return True, None
    except asyncio.TimeoutError:
        return False, "timeout apos 3s"
    except Exception as exc:  # noqa: BLE001 - a probe nunca deve estourar
        return False, f"{type(exc).__name__}: {exc}"
