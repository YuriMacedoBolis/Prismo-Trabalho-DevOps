"""Servico de sincronizacao: a API dos conectores.

Este servico **enfileira trabalho, nao o executa**. Essa separacao e o motivo
de o projeto 14 ter sido escolhido: consultar uma API externa leva segundos ou
falha, e uma requisicao HTTP nao pode ficar esperando por isso. O cliente
recebe `202 Accepted` imediatamente, e o worker processa quando puder.

O despacho usa `send_task`, que envia a tarefa **pelo nome**. Assim o sync nao
importa nada do worker: os dois sobem, escalam e sao implantados de forma
independente, ligados apenas pelo contrato do nome da tarefa.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from celery import Celery
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from prismo_shared import Dependency, create_app, get_logger, get_redis, get_settings
from prismo_shared.cache import close_redis, ping_redis
from prismo_shared.db import close_db, get_session, ping_db
from prismo_shared.models import Conexao, Plataforma, Sincronizacao

settings = get_settings()
log = get_logger("sync")

PLATAFORMAS_DISPONIVEIS = {Plataforma.GITHUB.value}

ENFILEIRADAS = Counter(
    "prismo_sync_tarefas_enfileiradas_total",
    "Tarefas de sincronizacao colocadas na fila.",
    ["plataforma", "origem"],
)

# Cliente so para despachar. Nao registra tarefa nenhuma: o nome basta.
despachante = Celery("prismo-sync", broker=settings.broker)


class ConexaoEntrada(BaseModel):
    plataforma: str = Field(default=Plataforma.GITHUB.value)
    conta: str = Field(min_length=1, max_length=120)

    @field_validator("plataforma")
    @classmethod
    def validar_plataforma(cls, v: str) -> str:
        if v not in PLATAFORMAS_DISPONIVEIS:
            raise ValueError(
                f"plataforma indisponivel. Disponiveis: {', '.join(sorted(PLATAFORMAS_DISPONIVEIS))}"
            )
        return v

    @field_validator("conta")
    @classmethod
    def limpar_conta(cls, v: str) -> str:
        return v.strip().lstrip("@")


class ConexaoSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plataforma: str
    conta: str
    ativo: bool
    ultima_sync_em: datetime | None
    criado_em: datetime


class SincronizacaoSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conexao_id: uuid.UUID
    status: str
    iniciada_em: datetime
    concluida_em: datetime | None
    itens_novos: int
    itens_atualizados: int
    erro: str | None


app = create_app(
    "sync",
    description="Conectores de plataformas externas e despacho de sincronizacao.",
    dependencies=[
        Dependency(name="postgres", check=ping_db, critical=True),
        # O Redis e a fila: sem ele nao ha como enfileirar, e aceitar a
        # requisicao seria mentir para o cliente.
        Dependency(name="redis", check=ping_redis, critical=True),
    ],
    on_shutdown=lambda _app: _encerrar(),
    settings=settings,
)


async def _encerrar() -> None:
    await close_db()
    await close_redis()


async def usuario_atual(x_usuario_id: str | None = Header(default=None)) -> uuid.UUID:
    if not x_usuario_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Requisicao sem identificacao de usuario.",
        )
    try:
        return uuid.UUID(x_usuario_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identificador de usuario invalido.",
        ) from None


router = APIRouter(prefix="/api/v1/conexoes", tags=["sync"])


@router.post(
    "", response_model=ConexaoSaida, status_code=status.HTTP_201_CREATED,
    summary="Conecta uma conta externa e dispara a primeira importacao",
)
async def conectar(
    dados: ConexaoEntrada,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> ConexaoSaida:
    conexao = Conexao(
        usuario_id=usuario_id,
        plataforma=dados.plataforma,
        conta=dados.conta,
        ativo=True,
    )
    sessao.add(conexao)
    try:
        await sessao.flush()
    except IntegrityError:
        await sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ja existe uma conexao com {dados.plataforma} nesta conta.",
        ) from None

    await sessao.refresh(conexao)
    # Commit antes de enfileirar: o worker pode pegar a tarefa em
    # milissegundos, e precisa encontrar a conexao ja gravada.
    await sessao.commit()

    despachante.send_task("prismo.sincronizar_conexao", args=[str(conexao.id)])
    ENFILEIRADAS.labels(dados.plataforma, "conexao_nova").inc()

    log.info("conexao_criada", plataforma=dados.plataforma, conta=dados.conta)
    return ConexaoSaida.model_validate(conexao)


@router.get("", response_model=list[ConexaoSaida], summary="Conexoes do usuario")
async def listar(
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> list[ConexaoSaida]:
    resultado = await sessao.execute(
        select(Conexao).where(Conexao.usuario_id == usuario_id).order_by(Conexao.criado_em)
    )
    return [ConexaoSaida.model_validate(c) for c in resultado.scalars()]


async def _minha_conexao(
    conexao_id: uuid.UUID, usuario_id: uuid.UUID, sessao: AsyncSession
) -> Conexao:
    conexao = await sessao.get(Conexao, conexao_id)
    if conexao is None or conexao.usuario_id != usuario_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conexao nao encontrada."
        )
    return conexao


@router.post(
    "/{conexao_id}/sincronizar",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dispara uma sincronizacao sob demanda",
)
async def sincronizar(
    conexao_id: uuid.UUID,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> dict:
    """202 Accepted: o trabalho foi aceito, nao concluido.

    A trava no Redis evita que cliques repetidos empilhem sincronizacoes da
    mesma conexao. `SET NX EX` e atomico: ou cria a chave, ou falha — nao ha
    janela entre verificar e gravar.
    """
    conexao = await _minha_conexao(conexao_id, usuario_id, sessao)
    if not conexao.ativo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Conexao desativada."
        )

    chave = f"lock:sync:{conexao_id}"
    adquiriu = await get_redis().set(
        chave, "1", nx=True, ex=settings.sync_lock_ttl_segundos
    )
    if not adquiriu:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ja existe uma sincronizacao em andamento para esta conexao.",
        )

    tarefa = despachante.send_task("prismo.sincronizar_conexao", args=[str(conexao_id)])
    ENFILEIRADAS.labels(conexao.plataforma, "sob_demanda").inc()

    log.info("sincronizacao_enfileirada", conexao_id=str(conexao_id), tarefa=tarefa.id)
    return {
        "status": "enfileirada",
        "tarefa_id": tarefa.id,
        "mensagem": "A sincronizacao roda em segundo plano. Acompanhe em /api/v1/sincronizacoes.",
    }


@router.delete(
    "/{conexao_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Desconecta a conta",
)
async def desconectar(
    conexao_id: uuid.UUID,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> None:
    """Remove a conexao. Os projetos ja importados permanecem.

    Desconectar e parar de importar, nao apagar o que foi construido: remover
    o conteudo seria uma surpresa desagradavel e irreversivel.
    """
    conexao = await _minha_conexao(conexao_id, usuario_id, sessao)
    await sessao.delete(conexao)
    log.info("conexao_removida", conexao_id=str(conexao_id))


historico = APIRouter(prefix="/api/v1/sincronizacoes", tags=["sync"])


@historico.get(
    "", response_model=list[SincronizacaoSaida],
    summary="Historico de sincronizacoes do usuario",
)
async def listar_sincronizacoes(
    limite: int = Query(default=20, ge=1, le=100),
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> list[SincronizacaoSaida]:
    """Responde "por que meu projeto novo nao apareceu?" sem abrir log."""
    resultado = await sessao.execute(
        select(Sincronizacao)
        .join(Conexao, Conexao.id == Sincronizacao.conexao_id)
        .where(Conexao.usuario_id == usuario_id)
        .order_by(desc(Sincronizacao.iniciada_em))
        .limit(limite)
    )
    return [SincronizacaoSaida.model_validate(s) for s in resultado.scalars()]


app.include_router(router)
app.include_router(historico)
