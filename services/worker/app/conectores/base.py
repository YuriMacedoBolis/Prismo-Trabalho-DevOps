"""Contrato comum a todos os conectores.

A Fase 3 implementa apenas o GitHub, mas a interface ja existe porque o
enunciado do projeto 14 cita Behance e Medium, e porque e ela que permite
acrescentar uma plataforma sem tocar no worker: basta uma classe nova que
devolva `ItemExterno`.

`ItemExterno` e o formato normalizado. Cada plataforma tem o seu vocabulario
— repositorio, artigo, projeto — e a traducao para esse formato unico acontece
dentro do adaptador. O worker nunca sabe de qual plataforma veio o item.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ItemExterno:
    """Um trabalho publicado numa plataforma externa, ja normalizado."""

    # Id na origem. E a metade da chave de deduplicacao, junto com a
    # plataforma: e por ele que sabemos se um item e novo ou ja conhecido.
    id_externo: str
    titulo: str
    descricao: str | None = None
    url: str | None = None
    imagem_url: str | None = None
    tags: list[str] = field(default_factory=list)
    linguagem: str | None = None
    # Sinal de engajamento, normalizado: estrelas no GitHub, reacoes no
    # Dev.to, likes no Behance.
    engajamento: int = 0
    # Data da ultima alteracao NA ORIGEM. E esta que mede recencia no score.
    atualizado_em: datetime | None = None


class ConectorError(Exception):
    """Falha ao consultar a plataforma externa."""


class Conector(ABC):
    """Interface que todo conector implementa."""

    plataforma: str

    @abstractmethod
    async def buscar_itens(self, conta: str, token: str | None = None) -> list[ItemExterno]:
        """Devolve os trabalhos publicados pela conta na plataforma.

        Levanta ConectorError em falha de rede, credencial ou limite de
        requisicoes. O worker trata a excecao, registra a sincronizacao como
        falha e mantem o conteudo que ja estava la — uma importacao que falha
        nunca pode esvaziar o portfolio de alguem.
        """
