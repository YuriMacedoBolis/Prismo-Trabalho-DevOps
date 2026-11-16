#!/usr/bin/env python3
"""Testa a conexao com o Supabase antes de escrever qualquer codigo de banco.

Vale rodar isto na Fase 1: o erro mais comum e a connection string, e descobrir
isso agora economiza horas de depuracao na Fase 2.

Requer:  pip install "psycopg[binary]"
Uso:     python scripts/check_supabase.py
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

    if not url or "SEU_REF" in url or "SUA_SENHA" in url:
        print(f"\n{VERMELHO}DATABASE_URL nao configurada.{RESET}")
        print(f"{CINZA}Preencha no .env com a URI do painel do Supabase:")
        print("  Project Settings > Database > Connection string > URI")
        print(f"  Use a porta 6543 (pooler), nao a 5432.{RESET}\n")
        return 1

    print(f"\n{CINZA}Conectando em {mascarar(url)}{RESET}")

    if ":5432" in url:
        print(f"{AMARELO}  Aviso: porta 5432 (conexao direta). Prefira a 6543,")
        print(f"  que usa o pooler e aguenta muito mais conexoes.{RESET}")

    # psycopg usa o esquema postgresql://; o sufixo +asyncpg e so para o
    # SQLAlchemy async e precisa sair aqui.
    url_sync = url.replace("+asyncpg", "").replace("+psycopg", "")

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
