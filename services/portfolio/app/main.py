"""Servico de portfolio do Prismo.

Dono do schema `portfolio`. Responsavel pelo conteudo (perfil, projetos,
tema), pela URL publica e pelo calculo do score de destaque.

Autenticacao: este servico nao valida token. O gateway ja fez isso e repassa
o id do usuario no header `X-Usuario-Id`. Concentrar a validacao em um lugar
evita que sete servicos repitam — e errem — a mesma logica. A contrapartida e
que estes servicos nao podem ser expostos diretamente para fora do cluster, o
que e justamente a funcao do Ingress.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from prometheus_client import Counter, Histogram
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from prismo_shared import Dependency, create_app, get_logger, get_settings
from prismo_shared.db import close_db, get_session, ping_db
from prismo_shared.models import Plataforma, Portfolio, Projeto

from .esquemas import (
    PortfolioAtualizacao,
    PortfolioEntrada,
    PortfolioPublico,
    PortfolioSaida,
    ProjetoAtualizacao,
    ProjetoEntrada,
    ProjetoSaida,
    gerar_slug,
)
from .ranking import calcular_score, explicar_score

settings = get_settings()
log = get_logger("portfolio")

PROJETOS_CRIADOS = Counter(
    "prismo_portfolio_projetos_criados_total",
    "Projetos criados, por origem.",
    ["plataforma"],
)
RECALCULOS = Counter(
    "prismo_portfolio_recalculos_score_total",
    "Projetos que tiveram o score recalculado.",
)
DURACAO_PAGINA_PUBLICA = Histogram(
    "prismo_portfolio_pagina_publica_segundos",
    "Tempo para montar a resposta do portfolio publico.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

app = create_app(
    "portfolio",
    description="Perfis, projetos, temas e score de destaque.",
    dependencies=[Dependency(name="postgres", check=ping_db, critical=True)],
    on_shutdown=lambda _app: close_db(),
    settings=settings,
)


async def usuario_atual(x_usuario_id: str | None = Header(default=None)) -> uuid.UUID:
    """Id do usuario, vindo do gateway."""
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


def _pontuar(projeto: Projeto) -> float:
    """Score de um projeto, inclusive antes dele ter sido gravado.

    Os `or` nao sao defensividade gratuita: o `default` de uma coluna do
    SQLAlchemy e aplicado no INSERT, nao na construcao do objeto. Um projeto
    recem-criado tem `estrelas is None` ate o flush, e e exatamente nesse
    momento que calculamos o score pela primeira vez.
    """
    return calcular_score(
        atualizado_na_origem=projeto.atualizado_na_origem,
        estrelas=projeto.estrelas or 0,
        destaque_manual=bool(projeto.destaque_manual),
        descricao=projeto.descricao,
        imagem_url=projeto.imagem_url,
        tags=projeto.tags or [],
        url=projeto.url,
    )


async def _slug_disponivel(sessao: AsyncSession, base: str) -> str:
    """Garante unicidade acrescentando sufixo numerico quando necessario."""
    candidato = base
    for tentativa in range(2, 50):
        existe = await sessao.scalar(
            select(Portfolio.id).where(Portfolio.slug == candidato)
        )
        if existe is None:
            return candidato
        candidato = f"{base}-{tentativa}"
    return f"{base}-{uuid.uuid4().hex[:6]}"


# ===========================================================================
#  Portfolio
# ===========================================================================

router = APIRouter(prefix="/api/v1/portfolios", tags=["portfolio"])


@router.post(
    "", response_model=PortfolioSaida, status_code=status.HTTP_201_CREATED,
    summary="Cria o portfolio do usuario",
)
async def criar_portfolio(
    dados: PortfolioEntrada,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> PortfolioSaida:
    base = dados.slug or gerar_slug(dados.titulo)
    slug = await _slug_disponivel(sessao, base)

    portfolio = Portfolio(
        usuario_id=usuario_id,
        slug=slug,
        titulo=dados.titulo,
        headline=dados.headline,
        bio=dados.bio,
        avatar_url=dados.avatar_url,
        tema=dados.tema,
        publicado=dados.publicado,
    )
    sessao.add(portfolio)
    try:
        await sessao.flush()
    except IntegrityError:
        await sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este endereco ja esta em uso.",
        ) from None

    await sessao.refresh(portfolio)
    log.info("portfolio_criado", slug=slug, usuario_id=str(usuario_id))
    return PortfolioSaida.model_validate(portfolio)


@router.get("/meus", response_model=list[PortfolioSaida], summary="Portfolios do usuario")
async def listar_meus(
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> list[PortfolioSaida]:
    resultado = await sessao.execute(
        select(Portfolio)
        .where(Portfolio.usuario_id == usuario_id)
        .order_by(Portfolio.criado_em.desc())
    )
    return [PortfolioSaida.model_validate(p) for p in resultado.scalars()]


async def _meu_portfolio(
    portfolio_id: uuid.UUID, usuario_id: uuid.UUID, sessao: AsyncSession
) -> Portfolio:
    """Busca o portfolio garantindo que ele pertence a quem pediu.

    A checagem de dono vai na mesma consulta, nao em um `if` depois. Assim um
    portfolio de outra pessoa responde 404 em vez de 403: dizer "existe, mas
    nao e seu" ja seria informacao a mais.
    """
    portfolio = await sessao.get(Portfolio, portfolio_id)
    if portfolio is None or portfolio.usuario_id != usuario_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio nao encontrado."
        )
    return portfolio


@router.patch("/{portfolio_id}", response_model=PortfolioSaida, summary="Atualiza o portfolio")
async def atualizar_portfolio(
    portfolio_id: uuid.UUID,
    dados: PortfolioAtualizacao,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> PortfolioSaida:
    portfolio = await _meu_portfolio(portfolio_id, usuario_id, sessao)
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(portfolio, campo, valor)
    await sessao.flush()
    await sessao.refresh(portfolio)
    return PortfolioSaida.model_validate(portfolio)


@router.delete(
    "/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Remove o portfolio e seus projetos",
)
async def remover_portfolio(
    portfolio_id: uuid.UUID,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> None:
    portfolio = await _meu_portfolio(portfolio_id, usuario_id, sessao)
    # Os projetos saem junto: ondelete="CASCADE" na FK.
    await sessao.delete(portfolio)
    log.info("portfolio_removido", portfolio_id=str(portfolio_id))


# ===========================================================================
#  Projetos
# ===========================================================================


@router.post(
    "/{portfolio_id}/projetos",
    response_model=ProjetoSaida,
    status_code=status.HTTP_201_CREATED,
    summary="Adiciona um projeto manualmente",
)
async def criar_projeto(
    portfolio_id: uuid.UUID,
    dados: ProjetoEntrada,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> ProjetoSaida:
    await _meu_portfolio(portfolio_id, usuario_id, sessao)

    projeto = Projeto(
        portfolio_id=portfolio_id,
        plataforma=Plataforma.MANUAL.value,
        **dados.model_dump(),
    )
    projeto.score = _pontuar(projeto)

    sessao.add(projeto)
    await sessao.flush()
    await sessao.refresh(projeto)

    PROJETOS_CRIADOS.labels(Plataforma.MANUAL.value).inc()
    return ProjetoSaida.model_validate(projeto)


@router.get(
    "/{portfolio_id}/projetos",
    response_model=list[ProjetoSaida],
    summary="Projetos do portfolio, ordenados por destaque",
)
async def listar_projetos(
    portfolio_id: uuid.UUID,
    incluir_ocultos: bool = Query(default=True),
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> list[ProjetoSaida]:
    await _meu_portfolio(portfolio_id, usuario_id, sessao)

    consulta = select(Projeto).where(Projeto.portfolio_id == portfolio_id)
    if not incluir_ocultos:
        consulta = consulta.where(Projeto.oculto.is_(False))

    # Pin primeiro, score depois: o destaque manual vence o algoritmo, que e
    # exatamente a regra que documentamos.
    consulta = consulta.order_by(
        Projeto.destaque_manual.desc(), Projeto.score.desc(), Projeto.criado_em.desc()
    )
    resultado = await sessao.execute(consulta)
    return [ProjetoSaida.model_validate(p) for p in resultado.scalars()]


@router.patch(
    "/{portfolio_id}/projetos/{projeto_id}",
    response_model=ProjetoSaida,
    summary="Atualiza um projeto e recalcula o score",
)
async def atualizar_projeto(
    portfolio_id: uuid.UUID,
    projeto_id: uuid.UUID,
    dados: ProjetoAtualizacao,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> ProjetoSaida:
    await _meu_portfolio(portfolio_id, usuario_id, sessao)

    projeto = await sessao.get(Projeto, projeto_id)
    if projeto is None or projeto.portfolio_id != portfolio_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Projeto nao encontrado."
        )

    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(projeto, campo, valor)

    # Qualquer campo alterado pode mudar a completude ou o pin, entao o score
    # e sempre recalculado. E uma conta barata, feita em memoria.
    projeto.score = _pontuar(projeto)
    RECALCULOS.inc()

    await sessao.flush()
    await sessao.refresh(projeto)
    return ProjetoSaida.model_validate(projeto)


@router.delete(
    "/{portfolio_id}/projetos/{projeto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Remove um projeto",
)
async def remover_projeto(
    portfolio_id: uuid.UUID,
    projeto_id: uuid.UUID,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> None:
    await _meu_portfolio(portfolio_id, usuario_id, sessao)
    projeto = await sessao.get(Projeto, projeto_id)
    if projeto is None or projeto.portfolio_id != portfolio_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Projeto nao encontrado."
        )
    await sessao.delete(projeto)


@router.post(
    "/{portfolio_id}/recalcular",
    summary="Recalcula o score de todos os projetos do portfolio",
)
async def recalcular(
    portfolio_id: uuid.UUID,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> dict:
    """Recalculo em lote.

    Necessario porque a recencia decai com o tempo: um score correto hoje
    estara desatualizado em um mes sem nada ter mudado no projeto. Na Fase 3
    o worker passa a chamar isto depois de cada sincronizacao.
    """
    await _meu_portfolio(portfolio_id, usuario_id, sessao)

    resultado = await sessao.execute(
        select(Projeto).where(Projeto.portfolio_id == portfolio_id)
    )
    projetos = list(resultado.scalars())
    alterados = 0
    for projeto in projetos:
        novo = _pontuar(projeto)
        if novo != projeto.score:
            projeto.score = novo
            alterados += 1

    RECALCULOS.inc(alterados)
    await sessao.flush()
    log.info("scores_recalculados", total=len(projetos), alterados=alterados)
    return {"projetos": len(projetos), "alterados": alterados}


@router.get(
    "/{portfolio_id}/projetos/{projeto_id}/score",
    summary="Abre o calculo do score, parcela por parcela",
)
async def detalhar_score(
    portfolio_id: uuid.UUID,
    projeto_id: uuid.UUID,
    usuario_id: uuid.UUID = Depends(usuario_atual),
    sessao: AsyncSession = Depends(get_session),
) -> dict:
    await _meu_portfolio(portfolio_id, usuario_id, sessao)
    projeto = await sessao.get(Projeto, projeto_id)
    if projeto is None or projeto.portfolio_id != portfolio_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Projeto nao encontrado."
        )
    return explicar_score(
        atualizado_na_origem=projeto.atualizado_na_origem,
        estrelas=projeto.estrelas,
        destaque_manual=projeto.destaque_manual,
        descricao=projeto.descricao,
        imagem_url=projeto.imagem_url,
        tags=projeto.tags,
        url=projeto.url,
    )


# ===========================================================================
#  Publico — sem autenticacao
# ===========================================================================

publico = APIRouter(prefix="/api/v1/publico", tags=["publico"])


@publico.get(
    "/{slug}",
    response_model=PortfolioPublico,
    summary="Portfolio publico pelo slug",
)
async def portfolio_publico(
    slug: str, sessao: AsyncSession = Depends(get_session)
) -> PortfolioPublico:
    """O que o servico web renderiza em /{slug}.

    So devolve portfolio publicado, e sem os projetos ocultos: rascunho nao
    vaza por adivinhacao de endereco.
    """
    with DURACAO_PAGINA_PUBLICA.time():
        resultado = await sessao.execute(
            select(Portfolio).where(
                Portfolio.slug == slug, Portfolio.publicado.is_(True)
            )
        )
        portfolio = resultado.scalar_one_or_none()
        if portfolio is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Portfolio nao encontrado.",
            )

        visiveis = sorted(
            (p for p in portfolio.projetos if not p.oculto),
            key=lambda p: (p.destaque_manual, p.score),
            reverse=True,
        )

        return PortfolioPublico(
            slug=portfolio.slug,
            titulo=portfolio.titulo,
            headline=portfolio.headline,
            bio=portfolio.bio,
            avatar_url=portfolio.avatar_url,
            tema=portfolio.tema,
            projetos=[ProjetoSaida.model_validate(p) for p in visiveis],
        )


app.include_router(router)
app.include_router(publico)
