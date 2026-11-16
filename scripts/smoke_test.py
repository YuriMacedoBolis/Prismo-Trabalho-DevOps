#!/usr/bin/env python3
"""Teste de fumaca: confirma que a Fase 1 esta de pe.

Usa apenas a biblioteca padrao, de proposito: roda na maquina de qualquer
integrante sem instalar nada, e serve tambem como etapa do pipeline de CI.

Uso:
    python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

WEB = "http://localhost:8000"
GATEWAY = "http://localhost:8001"

VERIFICACOES = [
    ("web", "liveness", f"{WEB}/health", 200),
    ("web", "readiness", f"{WEB}/ready", 200),
    ("web", "metricas", f"{WEB}/metrics", 200),
    ("web", "landing", f"{WEB}/", 200),
    ("web", "status", f"{WEB}/status", 200),
    ("web", "css", f"{WEB}/static/css/app.css", 200),
    ("web", "js", f"{WEB}/static/js/app.js", 200),
    ("gateway", "liveness", f"{GATEWAY}/health", 200),
    ("gateway", "readiness", f"{GATEWAY}/ready", 200),
    ("gateway", "metricas", f"{GATEWAY}/metrics", 200),
    ("gateway", "ping", f"{GATEWAY}/api/v1/ping", 200),
    ("gateway", "info", f"{GATEWAY}/api/v1/info", 200),
    ("gateway", "openapi", f"{GATEWAY}/openapi.json", 200),
]

VERDE = "\033[32m"
VERMELHO = "\033[31m"
CINZA = "\033[90m"
RESET = "\033[0m"


def buscar(url: str) -> tuple[int, bytes]:
    requisicao = urllib.request.Request(url, headers={"User-Agent": "prismo-smoke/1.0"})
    try:
        with urllib.request.urlopen(requisicao, timeout=8) as resposta:
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read()


def main() -> int:
    falhas: list[str] = []

    print(f"\n{CINZA}Prismo :: teste de fumaca da Fase 1{RESET}\n")

    for servico, nome, url, esperado in VERIFICACOES:
        rotulo = f"{servico:<8} {nome:<10}"
        try:
            status, _ = buscar(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  {VERMELHO}FALHOU{RESET}  {rotulo} {CINZA}{type(exc).__name__}{RESET}")
            falhas.append(f"{servico}/{nome}: {exc}")
            continue

        if status == esperado:
            print(f"  {VERDE}ok{RESET}      {rotulo} {CINZA}{status}{RESET}")
        else:
            print(f"  {VERMELHO}FALHOU{RESET}  {rotulo} {CINZA}esperado {esperado}, veio {status}{RESET}")
            falhas.append(f"{servico}/{nome}: HTTP {status}")

    # O rate limiter e a unica logica de negocio da Fase 1, entao vale testar
    # o comportamento e nao so o status code.
    print(f"\n{CINZA}Rate limiter (Redis){RESET}")
    try:
        _, corpo = buscar(f"{GATEWAY}/api/v1/ping")
        primeiro = json.loads(corpo)["rate_limit"]["hits_neste_minuto"]
        _, corpo = buscar(f"{GATEWAY}/api/v1/ping")
        segundo = json.loads(corpo)["rate_limit"]["hits_neste_minuto"]

        if segundo == primeiro + 1:
            print(f"  {VERDE}ok{RESET}      contador incrementou {primeiro} -> {segundo}")
        else:
            print(f"  {VERMELHO}FALHOU{RESET}  contador nao incrementou ({primeiro} -> {segundo})")
            falhas.append("rate limiter nao incrementa (Redis gravando?)")
    except Exception as exc:  # noqa: BLE001
        print(f"  {VERMELHO}FALHOU{RESET}  {exc}")
        falhas.append(f"rate limiter: {exc}")

    print()
    if falhas:
        print(f"{VERMELHO}{len(falhas)} falha(s):{RESET}")
        for falha in falhas:
            print(f"  - {falha}")
        print(f"\n{CINZA}A stack esta no ar? Rode: docker compose ps{RESET}\n")
        return 1

    print(f"{VERDE}Fase 1 completa: {len(VERIFICACOES)} verificacoes passaram.{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
