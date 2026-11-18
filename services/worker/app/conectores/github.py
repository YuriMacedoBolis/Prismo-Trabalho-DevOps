"""Conector do GitHub, em dois modos.

**Real** (`GITHUB_MODO_SIMULADO=false`): consulta `GET /users/{conta}/repos`
na API publica do GitHub.

**Simulado** (padrao): gera repositorios deterministicos a partir do nome da
conta. Nao e preguica — e uma decisao de confiabilidade. A demonstracao do
trabalho nao pode depender do Wi-Fi da sala nem do limite de requisicoes da
API do GitHub, e desenvolver nao deveria exigir que cada integrante crie o
seu proprio OAuth App. Os dois modos devolvem exatamente o mesmo
`ItemExterno`, entao o worker nao sabe qual esta ativo.

Determinismo importa: a mesma conta gera sempre os mesmos repositorios, com
as mesmas datas relativas. Isso torna o resultado da sincronizacao
reproduzivel e permite escrever teste sobre ele.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import httpx

from prismo_shared import get_logger, get_settings

from .base import Conector, ConectorError, ItemExterno

log = get_logger("conector.github")
settings = get_settings()

# Vocabulario do gerador. Combinacoes suficientes para que dois usuarios nao
# vejam a mesma lista.
_PREFIXOS = [
    "api", "cli", "dash", "core", "lib", "app", "bot", "kit",
    "flow", "sync", "edge", "nano",
]
_SUFIXOS = [
    "tracker", "manager", "engine", "toolkit", "monitor", "parser",
    "scheduler", "gateway", "pipeline", "analyzer", "builder", "runner",
]
_LINGUAGENS = [
    ("Python", ["python", "fastapi", "asyncio"]),
    ("TypeScript", ["typescript", "node", "react"]),
    ("Go", ["golang", "cli", "concurrency"]),
    ("Rust", ["rust", "performance", "systems"]),
    ("Java", ["java", "spring", "backend"]),
    ("PHP", ["php", "laravel", "web"]),
]
_TEMAS = [
    "Ferramenta de linha de comando para automatizar tarefas repetitivas do dia a dia",
    "Biblioteca leve para processar dados em lote com baixo consumo de memoria",
    "Painel web para acompanhar metricas de infraestrutura em tempo real",
    "Integracao que sincroniza informacoes entre servicos sem configuracao manual",
    "Servico HTTP minimalista com foco em latencia previsivel sob carga",
    "Conjunto de utilitarios para validar e normalizar entrada de usuario",
    "Agendador de tarefas com tentativas automaticas e registro de execucao",
    "Analisador estatico que aponta problemas antes do codigo chegar a producao",
]


class ConectorGitHub(Conector):
    plataforma = "github"

    def __init__(self, simulado: bool | None = None) -> None:
        self.simulado = settings.github_modo_simulado if simulado is None else simulado

    async def buscar_itens(self, conta: str, token: str | None = None) -> list[ItemExterno]:
        if self.simulado:
            return self._gerar(conta)
        return await self._buscar_na_api(conta, token)

    # ----------------------------------------------------------------- real
    async def _buscar_na_api(self, conta: str, token: str | None) -> list[ItemExterno]:
        cabecalhos = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            # O GitHub exige User-Agent e recusa a requisicao sem ele.
            "User-Agent": "prismo-portfolio",
        }
        if token:
            cabecalhos["Authorization"] = f"Bearer {token}"

        url = f"{settings.github_api_base}/users/{conta}/repos"
        parametros = {"sort": "updated", "per_page": 100, "type": "owner"}

        try:
            async with httpx.AsyncClient(timeout=20.0) as cliente:
                resposta = await cliente.get(url, headers=cabecalhos, params=parametros)
        except httpx.RequestError as erro:
            raise ConectorError(f"falha de rede ao consultar o GitHub: {erro}") from erro

        if resposta.status_code == 404:
            raise ConectorError(f"conta '{conta}' nao encontrada no GitHub")
        if resposta.status_code == 403:
            # Limite de requisicoes: 60/h sem token, 5.000/h com token.
            restante = resposta.headers.get("X-RateLimit-Remaining", "?")
            raise ConectorError(f"limite de requisicoes do GitHub atingido (restam {restante})")
        if resposta.status_code >= 400:
            raise ConectorError(f"GitHub respondeu {resposta.status_code}")

        itens = []
        for repo in resposta.json():
            if repo.get("fork") or repo.get("archived"):
                # Fork nao e trabalho autoral e arquivado nao representa o que
                # a pessoa faz hoje: nenhum dos dois deveria entrar no portfolio.
                continue
            itens.append(
                ItemExterno(
                    id_externo=str(repo["id"]),
                    titulo=repo["name"],
                    descricao=repo.get("description"),
                    url=repo.get("html_url"),
                    tags=repo.get("topics") or [],
                    linguagem=repo.get("language"),
                    engajamento=repo.get("stargazers_count", 0),
                    atualizado_em=_data_iso(repo.get("pushed_at") or repo.get("updated_at")),
                )
            )
        log.info("github_api_consultada", conta=conta, itens=len(itens))
        return itens

    # ------------------------------------------------------------- simulado
    def _gerar(self, conta: str) -> list[ItemExterno]:
        """Repositorios deterministicos a partir do nome da conta.

        A semente vem do nome, entao a mesma conta produz sempre o mesmo
        resultado — em qualquer maquina, em qualquer execucao.
        """
        aleatorio = random.Random(f"prismo:{conta.lower()}")
        agora = datetime.now(UTC)
        quantidade = settings.github_itens_simulados

        itens: list[ItemExterno] = []
        usados: set[str] = set()

        for i in range(quantidade):
            nome = f"{aleatorio.choice(_PREFIXOS)}-{aleatorio.choice(_SUFIXOS)}"
            while nome in usados:
                nome = f"{aleatorio.choice(_PREFIXOS)}-{aleatorio.choice(_SUFIXOS)}-{aleatorio.randint(2, 99)}"
            usados.add(nome)

            linguagem, tags_base = aleatorio.choice(_LINGUAGENS)

            # Distribuicao realista: poucos repositorios recentes e muito
            # ativos, varios antigos e parados. E o que torna o ranking
            # visivel na demonstracao — se tudo tivesse a mesma idade, a
            # ordenacao por score nao mostraria nada.
            dias_atras = int(aleatorio.triangular(0, 900, 45))

            # Engajamento igualmente desigual: a maioria com poucas estrelas,
            # um ou outro com muitas.
            estrelas = int(aleatorio.triangular(0, 320, 4))

            # Nem todo repositorio tem descricao, como na vida real. Isso faz
            # a parcela de completude do score variar de verdade.
            tem_descricao = aleatorio.random() > 0.25

            itens.append(
                ItemExterno(
                    id_externo=f"sim-{conta.lower()}-{i:03d}",
                    titulo=nome,
                    descricao=aleatorio.choice(_TEMAS) if tem_descricao else None,
                    url=f"https://github.com/{conta}/{nome}",
                    imagem_url=None,
                    tags=aleatorio.sample(tags_base, k=aleatorio.randint(1, len(tags_base))),
                    linguagem=linguagem,
                    engajamento=estrelas,
                    atualizado_em=agora - timedelta(days=dias_atras, hours=aleatorio.randint(0, 23)),
                )
            )

        log.info("github_simulado", conta=conta, itens=len(itens))
        return itens


def _data_iso(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
