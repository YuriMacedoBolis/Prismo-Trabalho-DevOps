# ADR 003 — Observabilidade enxuta: métricas sim, Loki e Jaeger não

- **Data:** 2026-11-16
- **Status:** aceito
- **Fase:** 1

## Contexto

A proposta inicial tinha seis containers de observabilidade: Prometheus,
Grafana, Loki, Promtail, Jaeger e cAdvisor. O trabalho exige
"observabilidade de funcionamento", sem especificar quais ferramentas.

## Decisão

Dois containers: **Prometheus** e **Grafana**. Logs permanecem estruturados em
JSON na saída padrão. Tracing distribuído fica fora desta entrega.

> **Revisão de 2026-11-16.** A decisão original incluía um terceiro container,
> o cAdvisor. Ele foi removido após verificação na máquina de desenvolvimento:
> ver "Por que o cAdvisor saiu", abaixo.

## Justificativa

Observabilidade tem três pilares — métricas, logs e traces. A decisão foi
cobrir cada pilar pelo meio mais simples que ainda responda às perguntas
operacionais, em vez de instalar a ferramenta canônica de cada um.

**Métricas: Prometheus + Grafana.** Sem negociação. É o que responde "está no
ar?", "está rápido?" e "está errando?", e é a fonte das métricas que o
HorizontalPodAutoscaler consome.

**Logs: JSON em stdout, sem Loki.** O que o Loki agrega é busca centralizada
entre serviços. Com sete serviços e escala de trabalho acadêmico,
`docker compose logs -f` e `kubectl logs -l app=prismo` atendem. O que
*realmente* importa nós mantivemos: log estruturado em JSON com `service`,
`request_id`, `level` e `duration_ms`. Log estruturado sem Loki continua
pesquisável; log não estruturado com Loki continua ruim. A estrutura é a parte
que vale.

**Traces: nenhum, com um substituto parcial.** Jaeger exige instrumentar sete
serviços com OpenTelemetry, e é a maior adição de trabalho da lista. Em troca,
implementamos a propagação de `request_id` pelo header `X-Request-ID`: filtrar
os logs por um id reconstrói o caminho de uma requisição pelos serviços. Não
dá o detalhe por span nem o gráfico de cascata, mas responde a pergunta
principal — "por onde essa requisição passou e onde demorou".

## Por que o cAdvisor saiu

O cAdvisor entrou na proposta para entregar CPU e memória por container sem
instrumentação nossa. Medido na prática, não entrega isso neste ambiente.

No Docker Desktop com WSL2 o container sobe e fica `healthy`, o Prometheus o
raspa com sucesso, e ele publica mais de 1.700 séries `container_*` — porém
**nenhuma com o label `name`**. As séries de memória saem apenas com caminhos
de cgroup agregados (`id="/docker"`, `id="/kubepods"`), sem mapear container
individual, porque dentro da VM do Docker Desktop o cAdvisor não consegue
associar cgroup a nome de container. O painel "Memória por container"
simplesmente não tinha dado.

A substituição é melhor do que o original: o `prometheus-client`, que já usamos
em todo serviço, expõe sozinho `process_resident_memory_bytes` e
`process_cpu_seconds_total` no `/metrics` de cada aplicação. Isso já vem
rotulado por `servico` pelos nossos `static_configs`, funciona em qualquer
ambiente, e mede o processo que de fato nos interessa em vez do container que o
hospeda — um container ocioso com 300 MB reservados não diz nada; o processo
usando 63 MB diz.

Na Fase 5 o assunto se resolve por outro caminho: o cAdvisor **embutido no
kubelet** fornece as métricas por pod com os labels corretos, sem container
extra nenhum. Ou seja, abrimos mão de algo que não funcionava localmente e que
no destino final vem de graça.

## Consequências

- Investigar incidente exige `docker compose logs | grep <request_id>` em vez
  de uma busca em interface gráfica. Aceitável nesta escala.
- Os dashboards do Grafana são provisionados por arquivo versionado, não
  criados pela interface: observabilidade também é infraestrutura como código.
- Se houver folga de tempo na Fase 5, adicionar Jaeger é incremento, não
  refatoração: a propagação de contexto já existe.
- O alerta `ReinicioEmLoop` compensa parte da falta do Loki, detectando crash
  loop por métrica em vez de leitura de log.
- Localmente não temos métrica de disco nem de rede por container. Nenhuma
  pergunta operacional do projeto depende disso hoje.
- As consultas dos painéis de recurso são restritas a `job="prismo-servicos"`,
  senão as métricas de processo do próprio Prometheus apareceriam nos gráficos
  sem rótulo de serviço.
