"""Destaque dinamico: o calculo que decide o que sobe ao topo.

E o segundo dos tres caminhos que o enunciado do projeto 14 pede — "coloque
automaticamente os projetos mais recentes ou relevantes no topo da pagina".

A formula e deliberadamente simples e auditavel:

    score = 0.40·recencia + 0.25·engajamento + 0.20·pin + 0.15·completude

Cada parcela entra normalizada em [0, 1], entao o score final tambem fica em
[0, 1] e os pesos sao diretamente comparaveis. Um modelo mais sofisticado
seria impossivel de explicar a quem perguntasse "por que este projeto esta em
primeiro?" — e essa pergunta tem de ter resposta.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

# Pesos. Somam 1.0; a verificacao esta nos testes para que uma alteracao
# descuidada nao passe despercebida.
PESO_RECENCIA = 0.40
PESO_ENGAJAMENTO = 0.25
PESO_PIN = 0.20
PESO_COMPLETUDE = 0.15

# Meia-vida da recencia: um projeto parado por 90 dias vale metade do que
# valia no dia em que foi atualizado.
MEIA_VIDA_DIAS = 90.0

# Teto do engajamento. Acima disto o ganho satura: a diferenca entre 200 e
# 400 estrelas nao deveria enterrar todo o resto do portfolio.
ESTRELAS_DE_REFERENCIA = 50.0


def _recencia(atualizado_em: datetime | None, agora: datetime) -> float:
    """Decaimento exponencial a partir da data de atualizacao na origem.

    Exponencial e nao linear porque a diferenca entre ontem e uma semana atras
    importa muito mais que a diferenca entre dois e tres anos atras.
    """
    if atualizado_em is None:
        return 0.0

    if atualizado_em.tzinfo is None:
        atualizado_em = atualizado_em.replace(tzinfo=UTC)

    dias = (agora - atualizado_em).total_seconds() / 86400.0
    if dias <= 0:
        return 1.0
    return math.pow(0.5, dias / MEIA_VIDA_DIAS)


def _engajamento(estrelas: int | None) -> float:
    """Logaritmo saturado: cresce rapido no comeco e satura depois.

    Com escala linear, um unico repositorio popular dominaria o portfolio
    inteiro. A primeira estrela deve valer mais que a centesima.

    Aceita None porque o valor pode vir de um objeto ainda nao gravado: o
    `default` de uma coluna do SQLAlchemy so e aplicado no INSERT, entao
    antes do flush o atributo e None, e nao 0.
    """
    if not estrelas or estrelas <= 0:
        return 0.0
    return min(1.0, math.log1p(estrelas) / math.log1p(ESTRELAS_DE_REFERENCIA))


def _completude(
    descricao: str | None, imagem_url: str | None, tags: list[str] | None, url: str | None
) -> float:
    """Premia o projeto bem preenchido.

    Tem um efeito pratico alem do ranking: empurra a pessoa a completar os
    campos, o que melhora tanto a aparencia do portfolio quanto o SEO.
    """
    preenchidos = sum(
        [
            bool(descricao and len(descricao.strip()) >= 40),
            bool(imagem_url),
            bool(tags),
            bool(url),
        ]
    )
    return preenchidos / 4.0


def calcular_score(
    *,
    atualizado_na_origem: datetime | None,
    estrelas: int | None = 0,
    destaque_manual: bool | None = False,
    descricao: str | None = None,
    imagem_url: str | None = None,
    tags: list[str] | None = None,
    url: str | None = None,
    agora: datetime | None = None,
) -> float:
    """Devolve o score em [0, 1], arredondado a 6 casas.

    O arredondamento evita ruido de ponto flutuante gerando UPDATE inutil a
    cada sincronizacao quando nada mudou de fato.
    """
    agora = agora or datetime.now(UTC)

    total = (
        PESO_RECENCIA * _recencia(atualizado_na_origem, agora)
        + PESO_ENGAJAMENTO * _engajamento(estrelas)
        + PESO_PIN * (1.0 if destaque_manual else 0.0)
        + PESO_COMPLETUDE * _completude(descricao, imagem_url, tags, url)
    )
    return round(min(1.0, max(0.0, total)), 6)


def explicar_score(**kwargs) -> dict[str, float]:
    """Mesma conta, com as parcelas abertas.

    Existe para a interface poder mostrar POR QUE um projeto esta em primeiro,
    e para a arguicao: um numero que ninguem sabe decompor nao convence.
    """
    agora = kwargs.get("agora") or datetime.now(UTC)
    recencia = _recencia(kwargs.get("atualizado_na_origem"), agora)
    engajamento = _engajamento(kwargs.get("estrelas", 0) or 0)
    pin = 1.0 if kwargs.get("destaque_manual") else 0.0
    completude = _completude(
        kwargs.get("descricao"),
        kwargs.get("imagem_url"),
        kwargs.get("tags"),
        kwargs.get("url"),
    )
    return {
        "recencia": round(recencia, 4),
        "engajamento": round(engajamento, 4),
        "pin": pin,
        "completude": round(completude, 4),
        "contribuicao_recencia": round(PESO_RECENCIA * recencia, 4),
        "contribuicao_engajamento": round(PESO_ENGAJAMENTO * engajamento, 4),
        "contribuicao_pin": round(PESO_PIN * pin, 4),
        "contribuicao_completude": round(PESO_COMPLETUDE * completude, 4),
        "total": calcular_score(**kwargs),
    }
