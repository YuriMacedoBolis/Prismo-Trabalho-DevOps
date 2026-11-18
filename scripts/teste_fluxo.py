#!/usr/bin/env python3
"""Teste de integracao do fluxo da Fase 2, pelo gateway.

Exercita o caminho real: cadastro, login, criacao de portfolio, projetos,
ordenacao por score, pagina publica e as regras de autorizacao. Usa apenas a
biblioteca padrao, para rodar em qualquer maquina e no CI sem instalar nada.

Uso:  python scripts/teste_fluxo.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

BASE = "http://localhost:8001"

VERDE = "\033[32m"
VERMELHO = "\033[31m"
CINZA = "\033[90m"
RESET = "\033[0m"

falhas: list[str] = []


def chamar(
    metodo: str, caminho: str, corpo: dict | None = None, token: str | None = None
) -> tuple[int, dict | None]:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(f"{BASE}{caminho}", data=dados, method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            bruto = r.read()
            return r.status, (json.loads(bruto) if bruto else None)
    except urllib.error.HTTPError as e:
        bruto = e.read()
        try:
            return e.code, json.loads(bruto) if bruto else None
        except json.JSONDecodeError:
            return e.code, None


def checar(descricao: str, condicao: bool, detalhe: str = "") -> None:
    if condicao:
        print(f"  {VERDE}ok{RESET}      {descricao}")
    else:
        print(f"  {VERMELHO}FALHOU{RESET}  {descricao} {CINZA}{detalhe}{RESET}")
        falhas.append(descricao)


def main() -> int:
    print(f"\n{CINZA}Prismo :: fluxo da Fase 2 (via gateway){RESET}\n")
    sufixo = uuid.uuid4().hex[:8]
    email = f"teste-{sufixo}@exemplo-prismo.com"
    senha = "senha-bem-grande-123"

    # --- Cadastro ---------------------------------------------------------
    print(f"{CINZA}Contas{RESET}")
    status, corpo = chamar("POST", "/api/v1/auth/registrar",
                           {"email": email, "nome": "Teste Integracao", "senha": senha})
    checar("registro cria a conta", status == 201, f"status {status}")
    if status != 201:
        print(f"\n{VERMELHO}sem conta nao da para seguir{RESET}\n")
        return 1

    token = corpo["tokens"]["access_token"]
    refresh = corpo["tokens"]["refresh_token"]
    checar("resposta nao expoe o hash da senha", "senha_hash" not in json.dumps(corpo))
    checar("e-mail normalizado para minusculas", corpo["usuario"]["email"] == email)

    status, _ = chamar("POST", "/api/v1/auth/registrar",
                       {"email": email.upper(), "nome": "Outro", "senha": senha})
    checar("e-mail duplicado e recusado com 409", status == 409, f"status {status}")

    status, _ = chamar("POST", "/api/v1/auth/registrar",
                       {"email": f"curta-{sufixo}@exemplo-prismo.com", "nome": "X", "senha": "1234"})
    checar("senha curta e recusada com 422", status == 422, f"status {status}")

    # --- Login ------------------------------------------------------------
    status, corpo_login = chamar("POST", "/api/v1/auth/login", {"email": email, "senha": senha})
    checar("login com senha correta", status == 200, f"status {status}")

    status, _ = chamar("POST", "/api/v1/auth/login", {"email": email, "senha": "errada"})
    checar("login com senha errada da 401", status == 401, f"status {status}")

    status, _ = chamar("POST", "/api/v1/auth/login",
                       {"email": f"naoexiste-{sufixo}@exemplo-prismo.com", "senha": senha})
    checar("e-mail inexistente tambem da 401 (nao enumera contas)", status == 401)

    status, corpo_ref = chamar("POST", "/api/v1/auth/refresh", {"refresh_token": refresh})
    checar("refresh emite novo access token", status == 200 and "access_token" in (corpo_ref or {}))

    status, _ = chamar("POST", "/api/v1/auth/refresh", {"refresh_token": token})
    checar("access token nao serve como refresh", status == 401, f"status {status}")

    # --- Autorizacao ------------------------------------------------------
    print(f"\n{CINZA}Autorizacao{RESET}")
    status, _ = chamar("GET", "/api/v1/portfolios/meus")
    checar("rota protegida sem token da 401", status == 401, f"status {status}")

    status, _ = chamar("GET", "/api/v1/portfolios/meus", token="nao-e-um-token")
    checar("token invalido da 401", status == 401, f"status {status}")

    status, _ = chamar("GET", "/api/v1/auth/eu", token=token)
    checar("rota protegida com token valido passa", status == 200, f"status {status}")

    # --- Portfolio --------------------------------------------------------
    print(f"\n{CINZA}Portfolio{RESET}")
    status, pf = chamar("POST", "/api/v1/portfolios",
                        {"titulo": "Portfolio do Daniel Lourenço", "tema": "aurora"}, token)
    checar("portfolio criado", status == 201, f"status {status}")
    if status != 201:
        return 1
    pf_id = pf["id"]
    checar("slug remove acentos", pf["slug"].startswith("portfolio-do-daniel-lourenco"),
           f"slug={pf['slug']}")
    checar("nasce como rascunho", pf["publicado"] is False)

    status, _ = chamar("POST", "/api/v1/portfolios", {"titulo": "X", "slug": "api"}, token)
    checar("slug reservado e recusado", status == 422, f"status {status}")

    status, _ = chamar("POST", "/api/v1/portfolios", {"titulo": "X", "tema": "neon"}, token)
    checar("tema invalido e recusado", status == 422, f"status {status}")

    # --- Projetos e score -------------------------------------------------
    print(f"\n{CINZA}Projetos e score de destaque{RESET}")
    agora = datetime.now(UTC)
    antigo = (agora - timedelta(days=400)).isoformat()
    recente = agora.isoformat()

    status, p_antigo = chamar("POST", f"/api/v1/portfolios/{pf_id}/projetos",
                              {"titulo": "Projeto antigo", "atualizado_na_origem": antigo}, token)
    checar("projeto antigo criado", status == 201, f"status {status}")

    status, p_recente = chamar("POST", f"/api/v1/portfolios/{pf_id}/projetos",
                               {"titulo": "Projeto recente", "atualizado_na_origem": recente,
                                "descricao": "d" * 60, "url": "https://exemplo.com",
                                "imagem_url": "https://exemplo.com/i.png", "tags": ["python"]}, token)
    checar("projeto recente e completo criado", status == 201, f"status {status}")

    checar("recente pontua mais que antigo",
           p_recente["score"] > p_antigo["score"],
           f"{p_recente['score']} vs {p_antigo['score']}")

    status, lista = chamar("GET", f"/api/v1/portfolios/{pf_id}/projetos", token=token)
    checar("listagem ordena por score", status == 200 and lista[0]["titulo"] == "Projeto recente",
           f"primeiro={lista[0]['titulo'] if lista else '-'}")

    status, _ = chamar("PATCH", f"/api/v1/portfolios/{pf_id}/projetos/{p_antigo['id']}",
                       {"destaque_manual": True}, token)
    checar("pin aplicado", status == 200, f"status {status}")

    status, lista = chamar("GET", f"/api/v1/portfolios/{pf_id}/projetos", token=token)
    checar("pin manual vence o algoritmo", lista[0]["titulo"] == "Projeto antigo",
           f"primeiro={lista[0]['titulo']}")

    status, det = chamar("GET",
                         f"/api/v1/portfolios/{pf_id}/projetos/{p_recente['id']}/score", token=token)
    soma = sum(v for k, v in (det or {}).items() if k.startswith("contribuicao_"))
    checar("parcelas do score somam o total", status == 200 and abs(soma - det["total"]) < 1e-4,
           f"soma={soma} total={det.get('total') if det else '-'}")

    # --- Pagina publica ---------------------------------------------------
    print(f"\n{CINZA}Pagina publica{RESET}")
    slug = pf["slug"]
    status, _ = chamar("GET", f"/api/v1/publico/{slug}")
    checar("rascunho nao aparece publicamente", status == 404, f"status {status}")

    chamar("PATCH", f"/api/v1/portfolios/{pf_id}", {"publicado": True}, token)
    status, publico = chamar("GET", f"/api/v1/publico/{slug}")
    checar("publicado aparece sem token", status == 200, f"status {status}")
    checar("pagina publica nao expoe usuario_id", "usuario_id" not in json.dumps(publico or {}))

    chamar("PATCH", f"/api/v1/portfolios/{pf_id}/projetos/{p_antigo['id']}", {"oculto": True}, token)
    status, publico = chamar("GET", f"/api/v1/publico/{slug}")
    checar("projeto oculto some da pagina publica",
           all(p["titulo"] != "Projeto antigo" for p in publico["projetos"]))

    # --- Isolamento entre usuarios ---------------------------------------
    print(f"\n{CINZA}Isolamento entre contas{RESET}")
    status, outro = chamar("POST", "/api/v1/auth/registrar",
                           {"email": f"outro-{sufixo}@exemplo-prismo.com", "nome": "Outro",
                            "senha": senha})
    token_outro = outro["tokens"]["access_token"]

    status, _ = chamar("GET", f"/api/v1/portfolios/{pf_id}/projetos", token=token_outro)
    checar("portfolio alheio responde 404, nao 403", status == 404, f"status {status}")

    status, _ = chamar("PATCH", f"/api/v1/portfolios/{pf_id}", {"titulo": "invadido"}, token_outro)
    checar("nao da para alterar portfolio alheio", status == 404, f"status {status}")

    status, _ = chamar("DELETE", f"/api/v1/portfolios/{pf_id}", token=token_outro)
    checar("nao da para remover portfolio alheio", status == 404, f"status {status}")

    # --- Limpeza ----------------------------------------------------------
    status, _ = chamar("DELETE", f"/api/v1/portfolios/{pf_id}", token=token)
    checar("dono remove o proprio portfolio", status == 204, f"status {status}")

    print()
    if falhas:
        print(f"{VERMELHO}{len(falhas)} falha(s):{RESET}")
        for f in falhas:
            print(f"  - {f}")
        print()
        return 1

    print(f"{VERDE}Fluxo da Fase 2 completo: todas as verificacoes passaram.{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
