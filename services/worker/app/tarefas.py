"""Tarefas do worker: a sincronizacao automatica do portfolio.

Este modulo e o coracao do produto — e o que faz o portfolio se manter
atualizado sozinho, que e o pedido do projeto 14.

O worker usa SQLAlchemy **sincrono**, nao a engine assincrona dos servicos
HTTP. Celery executa tarefas de forma sincrona; envolver tudo em `asyncio.run`
so acrescentaria indireção sem ganho, porque aqui nao ha milhares de conexoes
concorrentes a multiplexar — ha um punhado de tarefas longas.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import redis as redis_cliente
from celery.utils.log import get_task_logger
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from prismo_shared import get_settings
from prismo_shared.models import (
    Conexao,
    Plataforma,
    Portfolio,
    Projeto,
    Sincronizacao,
    StatusSync,
)

from .celery_app import app
from .conectores.base import ConectorError, ItemExterno
from .conectores.github import ConectorGitHub
from .ranking import calcular_score

log = get_task_logger(__name__)
settings = get_settings()

# --------------------------------------------------------------------------
#  Metricas
# --------------------------------------------------------------------------

SYNCS = Counter(
    "prismo_sync_execucoes_total",
    "Sincronizacoes executadas, por plataforma e resultado.",
    ["plataforma", "resultado"],
)
ITENS = Counter(
    "prismo_sync_itens_total",
    "Itens processados, por tipo de alteracao.",
    ["plataforma", "acao"],
)
DURACAO = Histogram(
    "prismo_sync_duracao_segundos",
    "Duracao de uma sincronizacao completa.",
    ["plataforma"],
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
# Gauge, nao Counter: e um valor instantaneo que sobe e desce. E a metrica
# que o HorizontalPodAutoscaler consome na Fase 5.
FILA = Gauge(
    "prismo_sync_fila_tamanho",
    "Conexoes aguardando sincronizacao na ultima varredura.",
)

# --------------------------------------------------------------------------
#  Banco (sincrono)
# --------------------------------------------------------------------------

_engine = None
_Sessao: sessionmaker[Session] | None = None


def obter_sessao() -> Session:
    global _engine, _Sessao
    if _Sessao is None:
        url = settings.database_url.replace("+asyncpg", "")
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        _engine = create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=5)
        _Sessao = sessionmaker(bind=_engine, expire_on_commit=False)
    return _Sessao()


CONECTORES = {Plataforma.GITHUB.value: ConectorGitHub()}

_redis = None


def _liberar_trava(conexao_id: str) -> None:
    """Remove a trava de sincronizacao assim que a tarefa termina.

    A trava e criada pelo sync-svc com `SET NX EX 300` antes de enfileirar.
    O TTL existe como rede de seguranca para o caso de o worker morrer no
    meio; o caminho normal e esta liberacao explicita. Sem ela a trava viraria
    uma espera obrigatoria de 5 minutos entre sincronizacoes, o que nao e o
    que ela deveria significar: a trava impede execucao CONCORRENTE, nao
    execucao frequente.
    """
    global _redis
    try:
        if _redis is None:
            _redis = redis_cliente.from_url(settings.redis_url, socket_timeout=3)
        _redis.delete(f"lock:sync:{conexao_id}")
    except Exception as erro:  # noqa: BLE001
        # Falhar aqui nao pode derrubar a sincronizacao, que ja terminou: o
        # TTL cuida da limpeza no pior caso.
        log.warning("nao foi possivel liberar a trava: %s", erro)


# --------------------------------------------------------------------------
#  Tarefas
# --------------------------------------------------------------------------


@app.task(name="prismo.sincronizar_conexao", bind=True, max_retries=3)
def sincronizar_conexao(self, conexao_id: str) -> dict:
    """Importa os trabalhos de uma conexao para o portfolio do usuario.

    Idempotente: executar duas vezes com os mesmos dados externos produz o
    mesmo estado final. Isso e exigido pelo `acks_late` do Celery, que pode
    reentregar a tarefa se o worker morrer no meio.
    """
    inicio = datetime.now(UTC)
    sessao = obter_sessao()

    try:
        conexao = sessao.get(Conexao, uuid.UUID(conexao_id))
        if conexao is None or not conexao.ativo:
            log.warning("conexao inexistente ou inativa: %s", conexao_id)
            return {"status": "ignorada", "motivo": "conexao inexistente ou inativa"}

        registro = Sincronizacao(
            conexao_id=conexao.id,
            status=StatusSync.EXECUTANDO.value,
            iniciada_em=inicio,
        )
        sessao.add(registro)
        sessao.commit()

        conector = CONECTORES.get(conexao.plataforma)
        if conector is None:
            raise ConectorError(f"plataforma sem conector: {conexao.plataforma}")

        try:
            # O conector e assincrono (httpx); aqui estamos num contexto
            # sincrono. asyncio.run cria um loop proprio para esta chamada.
            itens = asyncio.run(conector.buscar_itens(conexao.conta, conexao.token_cifrado))
        except ConectorError as erro:
            registro.status = StatusSync.FALHOU.value
            registro.concluida_em = datetime.now(UTC)
            registro.erro = str(erro)
            sessao.commit()
            SYNCS.labels(conexao.plataforma, "falha").inc()
            log.error("sincronizacao falhou: %s", erro)
            # O conteudo que ja estava la permanece intacto: uma importacao
            # que falha nunca pode esvaziar o portfolio de alguem.
            return {"status": "falhou", "erro": str(erro)}

        portfolio = sessao.scalar(
            select(Portfolio)
            .where(Portfolio.usuario_id == conexao.usuario_id)
            .order_by(Portfolio.criado_em)
            .limit(1)
        )
        if portfolio is None:
            registro.status = StatusSync.FALHOU.value
            registro.concluida_em = datetime.now(UTC)
            registro.erro = "usuario ainda nao tem portfolio"
            sessao.commit()
            SYNCS.labels(conexao.plataforma, "falha").inc()
            return {"status": "falhou", "erro": "usuario ainda nao tem portfolio"}

        novos, atualizados = _aplicar_itens(sessao, portfolio, conexao.plataforma, itens)

        conexao.ultima_sync_em = datetime.now(UTC)
        registro.status = StatusSync.CONCLUIDA.value
        registro.concluida_em = datetime.now(UTC)
        registro.itens_novos = novos
        registro.itens_atualizados = atualizados
        sessao.commit()

        duracao = (datetime.now(UTC) - inicio).total_seconds()
        DURACAO.labels(conexao.plataforma).observe(duracao)
        SYNCS.labels(conexao.plataforma, "sucesso").inc()
        ITENS.labels(conexao.plataforma, "novo").inc(novos)
        ITENS.labels(conexao.plataforma, "atualizado").inc(atualizados)

        log.info(
            "sincronizacao concluida: conta=%s novos=%d atualizados=%d em %.2fs",
            conexao.conta, novos, atualizados, duracao,
        )
        return {
            "status": "concluida",
            "conta": conexao.conta,
            "novos": novos,
            "atualizados": atualizados,
            "duracao_segundos": round(duracao, 2),
        }

    except Exception as erro:  # noqa: BLE001
        sessao.rollback()
        log.exception("erro inesperado na sincronizacao")
        # Backoff exponencial: 60s, 120s, 240s. Repetir de imediato contra um
        # servico que acabou de falhar costuma so piorar a situacao.
        raise self.retry(exc=erro, countdown=60 * (2**self.request.retries)) from erro
    finally:
        _liberar_trava(conexao_id)
        sessao.close()


def _aplicar_itens(
    sessao: Session, portfolio: Portfolio, plataforma: str, itens: list[ItemExterno]
) -> tuple[int, int]:
    """Insere o que e novo e atualiza o que mudou.

    A deduplicacao usa (portfolio, plataforma, id_externo), que e a mesma
    chave da UniqueConstraint no banco. Carregamos os existentes num dicionario
    para evitar uma consulta por item — com 100 repositorios, seriam 100
    viagens ao banco.
    """
    existentes = {
        p.id_externo: p
        for p in sessao.scalars(
            select(Projeto).where(
                Projeto.portfolio_id == portfolio.id,
                Projeto.plataforma == plataforma,
            )
        )
    }

    novos = atualizados = 0

    for item in itens:
        projeto = existentes.get(item.id_externo)

        if projeto is None:
            projeto = Projeto(
                portfolio_id=portfolio.id,
                plataforma=plataforma,
                id_externo=item.id_externo,
                titulo=item.titulo,
                descricao=item.descricao,
                url=item.url,
                imagem_url=item.imagem_url,
                tags=item.tags,
                linguagem=item.linguagem,
                estrelas=item.engajamento,
                atualizado_na_origem=item.atualizado_em,
                destaque_manual=False,
                oculto=False,
            )
            projeto.score = _pontuar(projeto)
            sessao.add(projeto)
            novos += 1
            continue

        # Campos vindos da origem sao sobrescritos; `destaque_manual` e
        # `oculto` nunca, porque sao decisao da pessoa. O worker so pode
        # mexer no que ele mesmo trouxe.
        mudou = (
            projeto.titulo != item.titulo
            or projeto.descricao != item.descricao
            or projeto.estrelas != item.engajamento
            or projeto.atualizado_na_origem != item.atualizado_em
            or projeto.tags != item.tags
        )
        if mudou:
            projeto.titulo = item.titulo
            projeto.descricao = item.descricao
            projeto.url = item.url
            projeto.tags = item.tags
            projeto.linguagem = item.linguagem
            projeto.estrelas = item.engajamento
            projeto.atualizado_na_origem = item.atualizado_em
            atualizados += 1

        # O score e sempre recalculado, mesmo sem mudanca na origem: a
        # recencia decai com o tempo por si so.
        projeto.score = _pontuar(projeto)

    return novos, atualizados


def _pontuar(projeto: Projeto) -> float:
    return calcular_score(
        atualizado_na_origem=projeto.atualizado_na_origem,
        estrelas=projeto.estrelas or 0,
        destaque_manual=bool(projeto.destaque_manual),
        descricao=projeto.descricao,
        imagem_url=projeto.imagem_url,
        tags=projeto.tags or [],
        url=projeto.url,
    )


@app.task(name="prismo.sincronizar_todas")
def sincronizar_todas() -> dict:
    """Varredura periodica: enfileira uma tarefa por conexao ativa.

    Enfileira em vez de executar: assim o trabalho se distribui entre todas as
    replicas do worker, em vez de uma so fazer tudo. E o tamanho dessa fila
    que o HPA observa.
    """
    sessao = obter_sessao()
    try:
        conexoes = list(sessao.scalars(select(Conexao.id).where(Conexao.ativo.is_(True))))
        FILA.set(len(conexoes))
        for conexao_id in conexoes:
            sincronizar_conexao.delay(str(conexao_id))
        log.info("varredura periodica: %d conexoes enfileiradas", len(conexoes))
        return {"enfileiradas": len(conexoes)}
    finally:
        sessao.close()


@app.task(name="prismo.recalcular_scores")
def recalcular_scores() -> dict:
    """Recalcula o score de todos os projetos.

    Necessario porque a recencia decai com o tempo: sem isto, um projeto
    parado continuaria com o score do dia em que foi importado.
    """
    sessao = obter_sessao()
    try:
        projetos = list(sessao.scalars(select(Projeto)))
        alterados = 0
        for projeto in projetos:
            novo = _pontuar(projeto)
            if novo != projeto.score:
                projeto.score = novo
                alterados += 1
        sessao.commit()
        log.info("scores recalculados: %d de %d alterados", alterados, len(projetos))
        return {"projetos": len(projetos), "alterados": alterados}
    finally:
        sessao.close()
