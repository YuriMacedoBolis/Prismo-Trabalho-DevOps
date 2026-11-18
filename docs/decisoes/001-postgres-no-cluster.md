# ADR 001 — Postgres no cluster, não em banco gerenciado

- **Data:** 2026-11-16 (decisão original) · **revisada em 2026-11-18**
- **Status:** aceito
- **Substitui:** a decisão original deste ADR, que escolhia o Supabase
- **Fase:** 1

## Contexto

O projeto precisa de um banco relacional. Duas opções: um container de Postgres
dentro da própria stack, ou um Postgres gerenciado externo (Supabase).

O trabalho é avaliado sobre a configuração de Docker, Kubernetes e
observabilidade, o que cria uma tensão real: um banco gerenciado é mais simples
de operar, mas remove da nossa stack justamente um dos componentes mais
interessantes de demonstrar.

## Decisão

**Postgres 16 rodando como serviço da própria stack**, com volume persistente.
Nenhum banco gerenciado.

## Histórico desta decisão

A versão original deste ADR escolhia o **Supabase**, com o argumento de que
backup e disponibilidade deixariam de ser trabalho nosso. Naquela versão
registramos a objeção séria à escolha:

> Perdemos a demonstração de `StatefulSet` e `PersistentVolumeClaim`. É a
> objeção séria.

A mitigação proposta era manter um Postgres em container sob um perfil
opcional do Compose. Ao revisar, a equipe concluiu que manter dois caminhos
para a mesma coisa — um usado no dia a dia, outro guardado só para a
apresentação — era pior que escolher um. E se um dos dois tinha de cair, o
que deveria cair era o que não é avaliado.

A decisão foi invertida: o Postgres saiu do perfil opcional e virou serviço
principal; o Supabase foi removido do projeto.

## Justificativa

**O componente com estado é onde o Kubernetes fica interessante.** Serviço sem
estado escala por `Deployment` + `HPA`, que é o caso fácil. O banco obriga a
tratar `StatefulSet`, `PersistentVolumeClaim`, ordem de inicialização e o que
acontece quando o pod morre. Essa é a parte que o trabalho avalia e que a
arguição provavelmente vai cobrar.

**Elimina dependência externa no pior momento possível.** O plano gratuito do
Supabase pausa o projeto após 7 dias sem uso — exatamente o cenário de um
trabalho acadêmico, onde o uso é concentrado em poucas semanas. Um banco que
dorme na véspera da apresentação é um risco que não precisamos correr.

**A stack fica autocontida.** `docker compose up` sobe o sistema inteiro, sem
cadastro, sem chave de API, sem rede. Qualquer integrante clona e roda. O
professor clona e roda.

**Não custa trabalho a mais no desenvolvimento.** Supabase é Postgres: mesmo
driver, mesmas migrations do Alembic, mesma connection string. A diferença
entre os dois era uma variável de ambiente, e é por isso que a reversão saiu
barata.

## Consequências

- **Backup passa a ser nossa responsabilidade.** Em desenvolvimento não
  importa, porque o banco é descartável. Na VPS, entra um `pg_dump` agendado
  com retenção, e isso precisa estar no runbook antes do deploy.
- **O dado vive no volume `postgres-data`.** `docker compose down -v` apaga
  tudo. O alvo `nuke` do Makefile faz exatamente isso e está documentado como
  destrutivo.
- **Ganhamos a demonstração de persistência no Kubernetes**, que era a maior
  perda da decisão anterior: `StatefulSet` + `PVC`, e a pergunta "o que
  acontece com os dados se o pod do banco cair?" passa a ter resposta
  demonstrável.
- **A senha é trivial em desenvolvimento** (`prismo`/`prismo`), de propósito:
  banco local que nunca sai da máquina. Em produção vem de um `Secret` do
  Kubernetes, nunca do `docker-compose.yml`.
- `scripts/check_db.py` verifica a conexão de fora dos containers, trocando o
  host `postgres` por `localhost` — o mesmo banco por um caminho diferente.
- Os serviços esperam o `healthcheck` do Postgres (`pg_isready`), não a mera
  criação do container: subir antes do banco aceitar conexão causaria falha na
  inicialização.
