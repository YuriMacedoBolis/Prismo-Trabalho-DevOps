#!/usr/bin/env python3
"""Testa a conexao com o Postgres da stack.

Roda a partir do Windows, de fora dos containers, entao troca o host `postgres`
(nome do servico, que so existe na rede interna do Docker) por `localhost`, onde
a porta esta publicada. O banco e o mesmo; muda so o caminho ate ele.

Requer:  pip install "psycopg[binary]"
Uso:     python scripts/check_db.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

VERDE = "\033[32m"
VERMELHO = "\033[31m"
AMARELO = "\033[33m"
CINZA = "\033[90m"
RESET = "\033[0m"


def carregar_env() -> dict[str, str]:
    """Le o .env sem depender de biblioteca externa."""
    caminho = Path(__file__).resolve().parent.parent / ".env"
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def mascarar(url: str) -> str:
    """Esconde a senha antes de imprimir a URL."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", url)


def main() -> int:
    env = carregar_env()
    url = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL", "")

    if not url:
        print()
        print(f"{VERMELHO}DATABASE_URL nao configurada no .env.{RESET}")
        print(f"{CINZA}Valor esperado:")
        print("  postgresql+asyncpg://prismo:prismo@postgres:5432/prismo")
        print(f"Copie o modelo com: cp .env.example .env{RESET}")
        print()
        return 1


    # psycopg usa o esquema postgresql://; o sufixo +asyncpg e so para o
    # SQLAlchemy async e precisa sair aqui.
    url_sync = url.replace("+asyncpg", "").replace("+psycopg", "")

    # `postgres` so resolve dentro da rede do Docker. Rodando no Windows, o
    # caminho ate o mesmo banco e a porta publicada no host.
    if "@postgres:" in url_sync:
        url_sync = url_sync.replace("@postgres:", "@localhost:")
        print(f"{AMARELO}  host `postgres` trocado por `localhost`:"
              f" execucao fora dos containers{RESET}")

    print(f"{CINZA}Conectando em {mascarar(url_sync)}{RESET}")

    try:
        import psycopg
    except ImportError:
        print(f"\n{VERMELHO}psycopg nao instalado.{RESET}")
        print(f'{CINZA}  pip install "psycopg[binary]"{RESET}\n')
        return 1

    try:
        with psycopg.connect(url_sync, connect_timeout=10) as conexao:
            with conexao.cursor() as cursor:
                cursor.execute("SELECT version(), current_database(), current_user")
                versao, banco, usuario = cursor.fetchone()

                cursor.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                (tabelas,) = cursor.fetchone()

        print(f"\n{VERDE}Conexao estabelecida.{RESET}")
        print(f"  {CINZA}servidor .......{RESET} {versao.split(',')[0]}")
        print(f"  {CINZA}banco ..........{RESET} {banco}")
        print(f"  {CINZA}usuario ........{RESET} {usuario}")
        print(f"  {CINZA}tabelas (public){RESET} {tabelas}")
        print(f"\n{CINZA}Pronto para as migrations da Fase 2.{RESET}\n")
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"\n{VERMELHO}Falha na conexao:{RESET} {exc}\n")
        print(f"{CINZA}Causas mais comuns:")
        print("  - senha errada (redefina em Database > Reset password)")
        print("  - projeto em pausa (o plano free pausa apos 7 dias sem uso)")
        print(f"  - host ou regiao incorretos na URI{RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
