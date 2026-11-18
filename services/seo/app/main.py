"""Servico de SEO: meta tags, dados estruturados, sitemap e auditoria.

Terceiro caminho do projeto 14 — "ofereca recursos de SEO por padrao, como
meta tags, URLs amigaveis e carregamento rapido, para que o profissional
possa ser encontrado sem precisar entender de otimizacao".

A palavra que manda aqui e **padrao**: nada disto e configuravel, nada exige
que a pessoa saiba o que e Open Graph. O portfolio ja nasce otimizado.

Este servico le o banco diretamente em vez de chamar o portfolio-svc. E uma
consulta de leitura do mesmo schema, e uma chamada HTTP intermediaria so
acrescentaria latencia numa rota cujo requisito explicito e ser rapida.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Response, status
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prismo_shared import Dependency, create_app, get_logger, get_settings
from prismo_shared.db import close_db, get_session, ping_db
from prismo_shared.models import Portfolio

settings = get_settings()
log = get_logger("seo")

AUDITORIAS = Counter(
    "prismo_seo_auditorias_total", "Auditorias de SEO executadas."
)
SITEMAPS = Counter(
    "prismo_seo_sitemaps_gerados_total", "Sitemaps gerados."
)

# Base publica do site. Em producao vem de variavel de ambiente; aqui o valor
# local basta para o conteudo das tags ficar correto.
BASE_PUBLICA = "http://localhost:8000"

app = create_app(
    "seo",
    description="Meta tags, dados estruturados, sitemap e auditoria de SEO.",
    dependencies=[Dependency(name="postgres", check=ping_db, critical=True)],
    on_shutdown=lambda _app: close_db(),
    settings=settings,
)

router = APIRouter(prefix="/api/v1/seo", tags=["seo"])


async def _portfolio_publicado(slug: str, sessao: AsyncSession) -> Portfolio:
    resultado = await sessao.execute(
        select(Portfolio).where(Portfolio.slug == slug, Portfolio.publicado.is_(True))
    )
    portfolio = resultado.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio nao encontrado."
        )
    return portfolio


def _descricao(portfolio: Portfolio) -> str:
    """Descricao de ate 160 caracteres.

    160 e o limite pratico do que o Google exibe no resultado de busca; alem
    disso o texto e cortado com reticencias e a frase perde o sentido. Corta
    na palavra, nao no caractere.
    """
    bruto = (portfolio.headline or portfolio.bio or portfolio.titulo or "").strip()
    bruto = " ".join(bruto.split())
    if len(bruto) <= 160:
        return bruto
    cortado = bruto[:157]
    if " " in cortado:
        cortado = cortado[: cortado.rfind(" ")]
    return cortado + "..."


@router.get("/{slug}/meta", summary="Meta tags prontas para o <head>")
async def meta(slug: str, sessao: AsyncSession = Depends(get_session)) -> dict:
    """Tudo o que o servico web precisa injetar no <head> da pagina publica."""
    portfolio = await _portfolio_publicado(slug, sessao)
    url = f"{BASE_PUBLICA}/{portfolio.slug}"
    descricao = _descricao(portfolio)
    visiveis = [p for p in portfolio.projetos if not p.oculto]

    # JSON-LD: e o que permite ao buscador entender que a pagina descreve uma
    # PESSOA com TRABALHOS, em vez de texto solto. E o que habilita resultado
    # enriquecido na busca.
    dados_estruturados = {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {
            "@type": "Person",
            "name": portfolio.titulo,
            "description": descricao,
            "url": url,
            **({"image": portfolio.avatar_url} if portfolio.avatar_url else {}),
        },
        "hasPart": [
            {
                "@type": "CreativeWork",
                "name": p.titulo,
                **({"description": p.descricao} if p.descricao else {}),
                **({"url": p.url} if p.url else {}),
                **(
                    {"dateModified": p.atualizado_na_origem.isoformat()}
                    if p.atualizado_na_origem
                    else {}
                ),
            }
            # Os 10 mais relevantes: um JSON-LD gigante atrasa o carregamento
            # sem melhorar a indexacao.
            for p in sorted(visiveis, key=lambda x: x.score, reverse=True)[:10]
        ],
    }

    return {
        "title": f"{portfolio.titulo} · Portfolio",
        "description": descricao,
        "canonical": url,
        "meta": [
            {"name": "description", "content": descricao},
            {"name": "robots", "content": "index, follow"},
            # Open Graph: controla como o link aparece no LinkedIn, no
            # WhatsApp e no Slack. Sem isto, a previa fica vazia — e o
            # portfolio costuma ser compartilhado exatamente por esses canais.
            {"property": "og:type", "content": "profile"},
            {"property": "og:title", "content": portfolio.titulo},
            {"property": "og:description", "content": descricao},
            {"property": "og:url", "content": url},
            *(
                [{"property": "og:image", "content": portfolio.avatar_url}]
                if portfolio.avatar_url
                else []
            ),
            {"name": "twitter:card", "content": "summary_large_image"},
            {"name": "twitter:title", "content": portfolio.titulo},
            {"name": "twitter:description", "content": descricao},
        ],
        "json_ld": dados_estruturados,
        "json_ld_script": json.dumps(dados_estruturados, ensure_ascii=False),
    }


@router.get("/{slug}/auditoria", summary="Nota de SEO com recomendacoes acionaveis")
async def auditoria(slug: str, sessao: AsyncSession = Depends(get_session)) -> dict:
    """Nota de 0 a 100 e o que fazer para melhorar.

    Cada item vale pontos e vem com uma acao concreta. Uma nota sem
    recomendacao nao ajuda ninguem a melhorar.
    """
    portfolio = await _portfolio_publicado(slug, sessao)
    visiveis = [p for p in portfolio.projetos if not p.oculto]

    criterios = []

    def avaliar(nome: str, peso: int, aprovado: bool, recomendacao: str) -> None:
        criterios.append(
            {
                "criterio": nome,
                "peso": peso,
                "aprovado": aprovado,
                "recomendacao": None if aprovado else recomendacao,
            }
        )

    avaliar(
        "Titulo com tamanho adequado", 15,
        5 <= len(portfolio.titulo or "") <= 60,
        "Use entre 5 e 60 caracteres: o Google corta titulos mais longos.",
    )
    avaliar(
        "Descricao presente", 20,
        bool(portfolio.headline or portfolio.bio),
        "Preencha a headline ou a bio: e o texto que aparece sob o titulo na busca.",
    )
    avaliar(
        "Descricao com tamanho util", 10,
        50 <= len(_descricao(portfolio)) <= 160,
        "Escreva entre 50 e 160 caracteres: curta demais nao informa, longa demais e cortada.",
    )
    avaliar(
        "Imagem de perfil", 15,
        bool(portfolio.avatar_url),
        "Adicione um avatar: e a imagem exibida ao compartilhar o link.",
    )
    avaliar(
        "URL amigavel", 10,
        bool(portfolio.slug) and portfolio.slug.replace("-", "").isalnum(),
        "Use um endereco com apenas letras, numeros e hifens.",
    )
    avaliar(
        "Conteudo suficiente", 15,
        len(visiveis) >= 3,
        "Publique ao menos 3 projetos: paginas vazias sao mal ranqueadas.",
    )
    avaliar(
        "Projetos descritos", 15,
        bool(visiveis) and sum(1 for p in visiveis if p.descricao) / len(visiveis) >= 0.6,
        "Descreva ao menos 60% dos projetos: o texto e o que o buscador indexa.",
    )

    nota = sum(c["peso"] for c in criterios if c["aprovado"])
    AUDITORIAS.inc()

    if nota >= 90:
        veredito = "excelente"
    elif nota >= 70:
        veredito = "bom"
    elif nota >= 50:
        veredito = "precisa de atencao"
    else:
        veredito = "critico"

    return {
        "slug": portfolio.slug,
        "nota": nota,
        "veredito": veredito,
        "criterios": criterios,
        "proximos_passos": [c["recomendacao"] for c in criterios if not c["aprovado"]],
    }


# ---------------------------------------------------------------------------
#  Arquivos que os buscadores leem
# ---------------------------------------------------------------------------

arquivos = APIRouter(tags=["seo"])


@arquivos.get("/sitemap.xml", summary="Sitemap de todos os portfolios publicados")
async def sitemap(sessao: AsyncSession = Depends(get_session)) -> Response:
    """Lista para o buscador o que existe e quando mudou.

    `lastmod` e o que evita rastreamento desnecessario: o buscador so volta ao
    que mudou desde a ultima visita.
    """
    resultado = await sessao.execute(
        select(Portfolio).where(Portfolio.publicado.is_(True)).order_by(Portfolio.slug)
    )
    portfolios = list(resultado.scalars())

    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in portfolios:
        linhas.append("  <url>")
        # escape() evita que um slug com caractere especial quebre o XML.
        linhas.append(f"    <loc>{escape(BASE_PUBLICA)}/{escape(p.slug)}</loc>")
        linhas.append(f"    <lastmod>{p.atualizado_em.date().isoformat()}</lastmod>")
        linhas.append("    <changefreq>weekly</changefreq>")
        linhas.append("    <priority>0.8</priority>")
        linhas.append("  </url>")
    linhas.append("</urlset>")

    SITEMAPS.inc()
    log.info("sitemap_gerado", portfolios=len(portfolios))
    return Response(content="\n".join(linhas), media_type="application/xml")


@arquivos.get("/robots.txt", summary="Regras de rastreamento")
async def robots() -> Response:
    """Libera o conteudo publico e bloqueia o que nao deve ser indexado."""
    corpo = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            # A API nao e conteudo: indexa-la gastaria a cota de rastreamento
            # do site com paginas que ninguem procura.
            "Disallow: /api/",
            "Disallow: /docs",
            "Disallow: /status",
            "",
            f"Sitemap: {BASE_PUBLICA}/sitemap.xml",
            "",
        ]
    )
    return Response(content=corpo, media_type="text/plain")


@arquivos.get("/api/v1/seo/estatisticas", summary="Visao geral do SEO da plataforma")
async def estatisticas(sessao: AsyncSession = Depends(get_session)) -> dict:
    total = await sessao.scalar(select(Portfolio.id).where(Portfolio.publicado.is_(True)))
    resultado = await sessao.execute(
        select(Portfolio).where(Portfolio.publicado.is_(True))
    )
    publicados = list(resultado.scalars())
    return {
        "portfolios_publicados": len(publicados),
        "com_descricao": sum(1 for p in publicados if p.headline or p.bio),
        "com_avatar": sum(1 for p in publicados if p.avatar_url),
        "gerado_em": datetime.now(UTC).isoformat(),
        "_tem_algum": total is not None,
    }


app.include_router(router)
app.include_router(arquivos)
