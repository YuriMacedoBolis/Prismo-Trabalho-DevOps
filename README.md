# Prismo — SaaS de portfólio com atualização automática

> Trabalho final de **DevOps** — CEUB
> Projeto selecionado: **nº 14 — SaaS de portfólio com atualização automática**

Um portfólio que se mantém atualizado sozinho. O profissional conecta a conta do
GitHub uma vez; a partir daí a plataforma importa os projetos novos, reordena os
mais relevantes no topo e cuida do SEO — sem trabalho manual.

---

## Integrantes

Equipe de **3 integrantes**, o que corresponde a **1 projeto** conforme o
enunciado (times de 2 a 4 participantes entregam um projeto).

| Nome | Matrícula | GitHub | Frente principal |
|---|---|---|---|
| Yuri Macedo Bolis | _preencher_ | `YuriMacedoBolis` | Docker, Compose e CI/CD |
| Vinicius Gabriel | _preencher_ | `GcmVinicius` | Kubernetes, HPA e observabilidade |
| Daniel Lourenço | _preencher_ | `DanielCScience` | Backend, conector GitHub e frontend |

> Cada integrante tem uma frente principal, mas **todos devem saber explicar a
> configuração de Docker e Kubernetes** — é tema de arguição na apresentação.

---

## Por que escolhemos este projeto

Três motivos pesaram na decisão:

**1. O domínio exige processamento assíncrono de verdade.** "Atualização
automática" não é um CRUD com um botão de salvar: é um processo que roda em
segundo plano, em horários próprios, consumindo uma API externa que pode estar
lenta ou indisponível. Isso nos obriga a separar o serviço que recebe a
requisição do serviço que executa o trabalho, com uma fila entre os dois — que é
exatamente a arquitetura que o trabalho pede que seja demonstrada.

**2. A carga é naturalmente irregular, então a escalabilidade é real.** Em
repouso o sistema praticamente não consome recursos. Quando vários usuários
sincronizam ao mesmo tempo, a fila cresce e os workers precisam se multiplicar.
Isso nos dá uma justificativa honesta para o HorizontalPodAutoscaler: não um
autoescalamento decorativo, mas uma resposta a uma variação de carga que podemos
provocar e medir na apresentação.

**3. O requisito de SEO cria uma necessidade genuína de observabilidade.**
"Carregamento rápido" é um requisito do próprio enunciado do projeto, e requisito
de desempenho só se cumpre se for medido. Latência p95, taxa de acerto do cache e
tempo de resposta por serviço deixam de ser métricas enfeitando um painel e
passam a ser o instrumento que mostra se o produto cumpre o que promete.

---

## Arquitetura

Sete serviços de aplicação, cada um com uma responsabilidade única.

```
                         ┌──────────────────┐
        Internet ───────▶│  Ingress / NGINX │
                         └────┬────────┬────┘
                              │        │
                   ┌──────────┘        └──────────┐
                   ▼                              ▼
          ┌─────────────────┐            ┌─────────────────┐
          │      web        │            │     gateway     │
          │  SSR (Jinja2)   │            │  JWT · rate     │
          │  portfólio      │            │  limit · rotas  │
          │  público        │            └──┬────┬────┬────┘
          └─────────────────┘               │    │    │
                              ┌─────────────┘    │    └──────────────┐
                              ▼                  ▼                   ▼
                      ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
                      │     auth     │   │  portfolio   │   │     sync     │
                      │ contas · JWT │   │ projetos ·   │   │ conector     │
                      │ token GitHub │   │ temas ·score │   │ GitHub       │
                      └──────────────┘   └──────────────┘   └──────┬───────┘
                                                                   │ enfileira
                      ┌──────────────┐                             ▼
                      │     seo      │                     ┌──────────────┐
                      │ meta tags ·  │                     │    worker    │
                      │ sitemap      │                     │ Celery +Beat │
                      └──────────────┘                     │ ← alvo do HPA│
                                                           └──────────────┘
                              │              │              │
          ┌───────────────────┴──────┬───────┴──────┬───────┴───────────┐
          ▼                          ▼              ▼                   ▼
   ┌─────────────┐          ┌─────────────┐  ┌─────────────┐   ┌─────────────┐
   │  Postgres   │          │    Redis    │  │   Google    │   │ Prometheus  │
   │ dados ·PVC  │          │ cache ·fila │  │    Drive    │   │  + Grafana  │
   │ StatefulSet │          │ rate limit  │  │  (arquivos) │   │             │
   └─────────────┘          └─────────────┘  └─────────────┘   └─────────────┘
```

Os diagramas UML formais estão em [`docs/uml/`](docs/uml/) e as decisões de
arquitetura, com a justificativa de cada uma, em [`docs/decisoes/`](docs/decisoes/).

### Papel de cada serviço

| Serviço | Responsabilidade | Fase |
|---|---|---|
| `gateway` | Único ponto de entrada da API. Valida JWT, aplica rate limit, roteia | **1** |
| `web` | Renderização server-side: landing, status, portfólio público | **1** |
| `auth` | Contas, JWT, OAuth do GitHub, guarda do token | 2 |
| `portfolio` | CRUD de projetos, temas, cálculo do score de destaque | 2 |
| `sync` | API do conector GitHub; enfileira o trabalho, não o executa | 3 |
| `worker` | Celery + Beat: sincroniza, baixa thumbnails, recalcula score | 3 |
| `seo` | Meta tags, Open Graph, JSON-LD, sitemap, auditoria | 3 |

### Serviços de apoio

| Componente | Função | Onde roda |
|---|---|---|
| **Postgres 16** | Fonte de verdade dos dados. Volume persistente | Container |
| **Redis** | Cache de render, fila do Celery, rate limit, locks | Container |
| **Google Drive** | Armazenamento de imagens (service account) | Externo |
| **Prometheus** | Coleta de métricas, a cada 15s | Container |
| **Grafana** | Visualização e alertas | Container |

---

## Como rodar

### Pré-requisitos

- Docker Desktop com backend WSL2
- Python 3.12 (só para os scripts auxiliares)

Nada além disso: a stack é autocontida, sem cadastro nem chave de API.

### Passo a passo

```bash
git clone <url-do-repo>
cd prismo

# 1. Configuração
cp .env.example .env     # ou: ./dev.ps1 setup
#    gere um JWT_SECRET; a DATABASE_URL já vem pronta para o Postgres da stack

# 2. (opcional) Confirme que o banco responde
pip install "psycopg[binary]"
python scripts/check_db.py

# 3. Suba a aplicação
docker compose up --build -d          # ou: make up / ./dev.ps1 up

# 4. Com observabilidade
docker compose -f docker-compose.yml -f docker-compose.obs.yml up --build -d
#    ou: make obs / ./dev.ps1 obs

# 5. Verifique
python scripts/smoke_test.py          # ou: make smoke
```

### Endereços

| O quê | URL | Credenciais |
|---|---|---|
| Aplicação | http://localhost:8000 | — |
| Status dos serviços | http://localhost:8000/status | — |
| API (Swagger) | http://localhost:8001/docs | — |
| Grafana | http://localhost:3000 | `admin` / `prismo` |
| Prometheus | http://localhost:9090 | — |
| Postgres | `localhost:5432` | `prismo` / `prismo` |

### O banco

O Postgres roda como serviço da stack, com volume persistente. A `DATABASE_URL`
já vem configurada no `.env.example` e aponta para o nome do serviço:

```
postgresql+asyncpg://prismo:prismo@postgres:5432/prismo
```

O host é `postgres` porque o DNS interno do Docker resolve nomes de serviço. De
**fora** dos containers — DBeaver, pgAdmin, um script no Windows — o mesmo banco
responde em `localhost:5432`, sem o sufixo `+asyncpg`.

A senha é trivial de propósito: banco local e descartável. Em produção ela vem
de um `Secret` do Kubernetes. A escolha de rodar o banco no cluster em vez de
usar um serviço gerenciado, com os prós e contras, está no
[ADR 001](docs/decisoes/001-postgres-no-cluster.md).

> `docker compose down -v` (e o alvo `make nuke`) **apaga o volume do banco**.

---

## Funcionalidades

### Básicas

- [x] Esqueleto de microsserviços com observabilidade e probes
- [x] Rate limiting por IP, no Redis
- [x] Temas visuais (prévia client-side)
- [ ] Cadastro e login com JWT
- [ ] CRUD de projetos e perfil
- [ ] Slug público amigável (`/{slug}`)
- [ ] Conector do GitHub com OAuth
- [ ] Sincronização automática a cada 30 min
- [ ] Destaque dinâmico por score
- [ ] SEO: meta tags, Open Graph, JSON-LD, sitemap
- [ ] Deploy em Kubernetes com HPA

### Extras escolhidos

- [ ] **Temas visuais** — 4 identidades, persistidas por usuário
- [ ] **Export estático** — `.zip` com HTML e CSS puros, hospedável em qualquer lugar

### Fora de escopo (decisão consciente)

Conectores de Dev.to, Medium e Behance; analytics próprio; multi-tenant por
subdomínio. A API pública do Behance foi descontinuada pela Adobe, então o
adapter fica previsto na arquitetura mas sem implementação — registrado em
[`docs/decisoes/`](docs/decisoes/).

---

## Observabilidade

Escolhemos a versão enxuta: **dois containers** em vez dos seis de uma stack
completa.

| Pilar | Ferramenta | Como consultar |
|---|---|---|
| Métricas | Prometheus + Grafana | Dashboard "Prismo :: Visão geral" |
| Recursos por serviço | `prometheus-client` (no próprio `/metrics`) | Painéis de memória e CPU |
| Logs | JSON estruturado em stdout | `docker compose logs` / `kubectl logs` |
| Tracing | — | Fora de escopo nesta entrega |

O cAdvisor foi avaliado e removido: no Docker Desktop com WSL2 ele não mapeia
cgroup para nome de container e publica zero séries com o label `name`. As
métricas de recurso por serviço vêm do `prometheus-client`, que já expõe
`process_resident_memory_bytes` e `process_cpu_seconds_total` sozinho. Detalhes
em [`docs/decisoes/003`](docs/decisoes/003-observabilidade-enxuta.md).

Os logs saem em JSON com `service`, `request_id`, `level` e `duration_ms`. O
`request_id` é propagado pelo header `X-Request-ID` entre os serviços, o que
permite reconstruir uma requisição que atravessou vários deles — o essencial de
um trace, sem a infraestrutura de um Jaeger.

### Métricas expostas

| Métrica | Tipo | Para quê |
|---|---|---|
| `prismo_http_requests_total` | Counter | Volume de tráfego e taxa de erro |
| `prismo_http_request_duration_seconds` | Histogram | Latência p50/p95/p99 |
| `prismo_service_starts_total` | Counter | Detecção de crash loop |
| `process_resident_memory_bytes` | Gauge | Memória do processo, por serviço |
| `process_cpu_seconds_total` | Counter | CPU do processo; alvo do HPA na Fase 5 |

---

## Estrutura do repositório

```
prismo/
├── docker-compose.yml          # aplicação
├── docker-compose.obs.yml      # observabilidade (overlay)
├── Makefile · dev.ps1          # atalhos (bash / PowerShell)
├── shared/prismo_shared/       # infra transversal: config, logs, probes, cache
├── services/
│   ├── gateway/                # Dockerfile + app
│   └── web/                    # Dockerfile + app + templates + static
├── observability/
│   ├── prometheus/             # scrape config + alertas
│   └── grafana/                # datasource + dashboards, provisionados
├── k8s/                        # manifests (Fase 5)
├── scripts/                    # smoke test, verificação do banco
└── docs/
    ├── uml/                    # diagramas em PlantUML
    └── decisoes/               # ADRs
```

---

## Convenções

**Branches.** `main` protegida, merge só por Pull Request com uma aprovação.
Trabalho em `feat/<assunto>`, `fix/<assunto>` ou `docs/<assunto>`.

**Commits.** [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.

**Dockerfiles.** Toda imagem é multi-stage, roda como usuário non-root, declara
`HEALTHCHECK` e tem versão fixada — nunca `:latest`.

**Segredos.** Nenhum valor sensível no Git. Desenvolvimento usa `.env`
(ignorado); produção usa `Secret` do Kubernetes. Os dois chegam ao processo como
variável de ambiente, então o código não muda entre ambientes.

---

## Entrega

- Repositório **privado** no GitHub
- Convite de colaborador para **`wagnerpequeno-sudo`** (wagner.pequeno@ceub.edu.br)
- Documentação do código: docstrings + OpenAPI em `/docs` de cada serviço
- Diagramas UML em [`docs/uml/`](docs/uml/)
