#!/usr/bin/env python3
"""Teste de integracao da Fase 3: importacao automatica, destaque e SEO.

Exercita os tres caminhos que o enunciado do projeto 14 pede, ponta a ponta:
conectar uma conta, esperar o worker importar em segundo plano, conferir que
os mais relevantes subiram ao topo e que o SEO foi gerado sozinho.

Uso:  python scripts/teste_fase3.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8001"
WEB = "http://localhost:8000"

VERDE = "\033[32m"
VERMELHO = "\033[31m"
AMARELO = "\033[33m"
CINZA = "\033[90m"
RESET = "\033[0m"

falhas: list[str] = []


def chamar(metodo, caminho, corpo=None, token=None, base=BASE):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(f"{base}{caminho}", data=dados, method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            bruto = r.read()
            tipo = r.headers.get("Content-Type", "")
            if "json" in tipo:
                return r.status, (json.loads(bruto) if bruto else None)
            return r.status, bruto.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        bruto = e.read()
        try:
            return e.code, json.loads(bruto) if bruto else None
        except json.JSONDecodeError:
            return e.code, bruto.decode("utf-8", "replace")


def checar(descricao, condicao, detalhe=""):
    if condicao:
        print(f"  {VERDE}ok{RESET}      {descricao}")
    else:
        print(f"  {VERMELHO}FALHOU{RESET}  {descricao} {CINZA}{detalhe}{RESET}")
        falhas.append(descricao)


def esperar_sync(token, tentativas=30):
    """Espera o worker concluir. A sincronizacao e assincrona por natureza."""
    for _ in range(tentativas):
        status, historico = chamar("GET", "/api/v1/sincronizacoes", token=token)
        if status == 200 and historico:
            ultima = historico[0]
            if ultima["status"] in ("concluida", "falhou"):
                return ultima
        time.sleep(2)
    return None


def main() -> int:
    print(f"\n{CINZA}Prismo :: fluxo da Fase 3 (importacao, destaque, SEO){RESET}\n")
    sufixo = uuid.uuid4().hex[:8]
    email = f"fase3-{sufixo}@exemplo-prismo.com"
    senha = "senha-bem-grande-123"

    # --- Preparacao -------------------------------------------------------
    status, sessao = chamar("POST", "/api/v1/auth/registrar",
                            {"email": email, "nome": "Teste Fase 3", "senha": senha})
    if status != 201:
        print(f"{VERMELHO}nao foi possivel criar a conta: {status}{RESET}")
        return 1
    token = sessao["tokens"]["access_token"]

    status, pf = chamar("POST", "/api/v1/portfolios",
                        {"titulo": f"Portfolio Fase 3 {sufixo}", "tema": "aurora",
                         "headline": "Desenvolvedor focado em automacao e infraestrutura",
                         "avatar_url": "https://exemplo.com/avatar.png"}, token)
    if status != 201:
        print(f"{VERMELHO}nao foi possivel criar o portfolio: {status}{RESET}")
        return 1
    pf_id, slug = pf["id"], pf["slug"]

    # --- Conexao e importacao --------------------------------------------
    print(f"{CINZA}Conector do GitHub (modo simulado){RESET}")
    status, conexao = chamar("POST", "/api/v1/conexoes",
                             {"plataforma": "github", "conta": "YuriMacedoBolis"}, token)
    checar("conexao criada", status == 201, f"status {status}")
    if status != 201:
        return 1
    conexao_id = conexao["id"]

    status, _ = chamar("POST", "/api/v1/conexoes",
                       {"plataforma": "github", "conta": "outro"}, token)
    checar("segunda conexao na mesma plataforma e recusada", status == 409, f"status {status}")

    status, _ = chamar("POST", "/api/v1/conexoes",
                       {"plataforma": "behance", "conta": "x"}, token)
    checar("plataforma sem conector e recusada", status == 422, f"status {status}")

    print(f"  {AMARELO}aguardando o worker importar em segundo plano...{RESET}")
    ultima = esperar_sync(token)
    checar("worker concluiu a sincronizacao", ultima is not None and ultima["status"] == "concluida",
           f"status={ultima['status'] if ultima else 'sem registro'}"
           + (f" erro={ultima.get('erro')}" if ultima and ultima.get("erro") else ""))
    if not ultima or ultima["status"] != "concluida":
        return 1

    checar("importou projetos", ultima["itens_novos"] > 0, f"novos={ultima['itens_novos']}")

    # --- Destaque dinamico ------------------------------------------------
    print(f"\n{CINZA}Destaque dinamico{RESET}")
    status, projetos = chamar("GET", f"/api/v1/portfolios/{pf_id}/projetos", token=token)
    checar("projetos aparecem no portfolio", status == 200 and len(projetos) > 0,
           f"total={len(projetos) if isinstance(projetos, list) else '-'}")

    importados = [p for p in projetos if p["plataforma"] == "github"]
    checar("projetos marcados como vindos do GitHub", len(importados) > 0)
    checar("todos tem score calculado", all(p["score"] > 0 for p in importados))

    scores = [p["score"] for p in projetos]
    checar("listagem vem ordenada por score", scores == sorted(scores, reverse=True),
           f"{[round(s, 3) for s in scores[:4]]}")
    checar("scores variam entre si (ranking util)", len(set(scores)) > 1,
           f"distintos={len(set(scores))}")

    # --- Idempotencia -----------------------------------------------------
    print(f"\n{CINZA}Idempotencia da sincronizacao{RESET}")
    antes = len(projetos)
    status, _ = chamar("POST", f"/api/v1/conexoes/{conexao_id}/sincronizar", token=token)
    checar("sincronizacao sob demanda aceita com 202", status == 202, f"status {status}")

    status, _ = chamar("POST", f"/api/v1/conexoes/{conexao_id}/sincronizar", token=token)
    checar("trava impede sincronizacao duplicada", status == 409, f"status {status}")

    time.sleep(8)
    status, projetos2 = chamar("GET", f"/api/v1/portfolios/{pf_id}/projetos", token=token)
    checar("reimportar nao duplica projetos", len(projetos2) == antes,
           f"antes={antes} depois={len(projetos2)}")

    # --- O worker respeita o que e do usuario -----------------------------
    print(f"\n{CINZA}Fronteira entre worker e usuario{RESET}")
    alvo = projetos2[-1]
    chamar("PATCH", f"/api/v1/portfolios/{pf_id}/projetos/{alvo['id']}",
           {"destaque_manual": True, "oculto": True}, token)

    status, _ = chamar("POST", f"/api/v1/conexoes/{conexao_id}/sincronizar", token=token)
    time.sleep(10)
    status, projetos3 = chamar("GET", f"/api/v1/portfolios/{pf_id}/projetos", token=token)
    depois = next((p for p in projetos3 if p["id"] == alvo["id"]), None)
    checar("worker nao desfaz o pin do usuario", depois is not None and depois["destaque_manual"])
    checar("worker nao reexibe projeto que o usuario ocultou",
           depois is not None and depois["oculto"])
    checar("projeto com pin vai para o topo", projetos3[0]["id"] == alvo["id"])

    # --- SEO --------------------------------------------------------------
    print(f"\n{CINZA}SEO por padrao{RESET}")
    chamar("PATCH", f"/api/v1/portfolios/{pf_id}", {"publicado": True}, token)

    status, meta = chamar("GET", f"/api/v1/seo/{slug}/meta")
    checar("meta tags geradas sem autenticacao", status == 200, f"status {status}")
    if status == 200:
        nomes = {m.get("property") or m.get("name") for m in meta["meta"]}
        checar("inclui Open Graph", {"og:title", "og:description", "og:url"} <= nomes)
        checar("inclui Twitter Card", {"twitter:card", "twitter:title"} <= nomes)
        checar("tem URL canonica", meta["canonical"].endswith(slug))
        checar("descricao respeita o limite de 160 caracteres",
               len(meta["description"]) <= 160, f"{len(meta['description'])} chars")
        ld = meta["json_ld"]
        checar("JSON-LD descreve uma Person", ld["mainEntity"]["@type"] == "Person")
        checar("JSON-LD lista os trabalhos", len(ld.get("hasPart", [])) > 0,
               f"hasPart={len(ld.get('hasPart', []))}")

    status, aud = chamar("GET", f"/api/v1/seo/{slug}/auditoria")
    checar("auditoria responde", status == 200, f"status {status}")
    if status == 200:
        checar("nota entre 0 e 100", 0 <= aud["nota"] <= 100, f"nota={aud['nota']}")
        checar("portfolio bem preenchido tira nota alta", aud["nota"] >= 70,
               f"nota={aud['nota']} veredito={aud['veredito']}")
        soma = sum(c["peso"] for c in aud["criterios"])
        checar("pesos dos criterios somam 100", soma == 100, f"soma={soma}")
        reprovados = [c for c in aud["criterios"] if not c["aprovado"]]
        checar("todo criterio reprovado traz recomendacao",
               all(c["recomendacao"] for c in reprovados))

    status, xml = chamar("GET", "/sitemap.xml", base=WEB.replace("8000", "8001")) \
        if False else chamar("GET", "/api/v1/seo/estatisticas")
    checar("estatisticas de SEO respondem", status == 200, f"status {status}")

    # --- Historico --------------------------------------------------------
    print(f"\n{CINZA}Historico de sincronizacao{RESET}")
    status, historico = chamar("GET", "/api/v1/sincronizacoes", token=token)
    checar("historico registra as execucoes", status == 200 and len(historico) >= 3,
           f"registros={len(historico) if isinstance(historico, list) else '-'}")
    checar("historico em ordem decrescente",
           all(historico[i]["iniciada_em"] >= historico[i + 1]["iniciada_em"]
               for i in range(len(historico) - 1)))

    # --- Desconectar nao apaga conteudo -----------------------------------
    status, _ = chamar("DELETE", f"/api/v1/conexoes/{conexao_id}", token=token)
    checar("desconectar responde 204", status == 204, f"status {status}")
    status, restantes = chamar("GET", f"/api/v1/portfolios/{pf_id}/projetos", token=token)
    checar("projetos importados permanecem apos desconectar",
           len(restantes) == len(projetos3), f"{len(restantes)} de {len(projetos3)}")

    chamar("DELETE", f"/api/v1/portfolios/{pf_id}", token=token)

    print()
    if falhas:
        print(f"{VERMELHO}{len(falhas)} falha(s):{RESET}")
        for f in falhas:
            print(f"  - {f}")
        print()
        return 1
    print(f"{VERDE}Fluxo da Fase 3 completo: todas as verificacoes passaram.{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
