# ADR 001 — Supabase como banco de dados

- **Data:** 2026-11-16
- **Status:** aceito
- **Fase:** 1

## Contexto

O projeto precisa de um banco relacional. Duas opções se apresentavam: um
container de Postgres dentro da própria stack, ou um Postgres gerenciado
externo.

O trabalho é avaliado sobre a configuração de Docker, Kubernetes e
observabilidade, o que cria uma tensão real: um banco externo é mais simples de
operar, mas remove da nossa stack justamente um dos componentes mais
interessantes de demonstrar.

## Decisão

Usar **Supabase** (Postgres gerenciado) como banco da aplicação, e manter um
container de Postgres disponível sob o perfil `local-db` do Docker Compose.

## Justificativa

A favor do Supabase:

- Backup, atualização de versão e disponibilidade deixam de ser trabalho nosso,
  o que libera tempo para a parte que é efetivamente avaliada.
- O time inteiro compartilha o mesmo banco de desenvolvimento, eliminando a
  classe de bug "funciona na minha máquina".
- Reflete a prática corrente: banco gerenciado é o padrão da indústria, e
  manter um Postgres em container no cluster é a exceção, não a regra.
- O pooler (porta 6543) resolve de graça o problema de esgotamento de conexões
  que apareceria com várias réplicas de vários serviços.

Contra, e como tratamos:

- **Perdemos a demonstração de `StatefulSet` e `PersistentVolumeClaim`.** É a
  objeção séria. Mitigada pelo perfil `local-db`: como Supabase *é* Postgres,
  trocar entre os dois é trocar a `DATABASE_URL`, sem nenhuma mudança de
  código. Podemos demonstrar o banco com volume persistente quando isso for
  relevante.
- **Dependência de rede.** O perfil `local-db` também cobre o caso de
  desenvolver ou apresentar sem internet confiável.
- **O plano free pausa o projeto após 7 dias sem uso.** Registrado no runbook:
  acessar o painel na véspera da apresentação.

## Consequências

- `DATABASE_URL` passa a ser configuração crítica, e é o primeiro ponto a
  verificar em qualquer falha de banco — daí o `scripts/check_supabase.py`.
- O Redis se torna o único serviço com estado dentro do cluster, e portanto o
  lugar onde demonstramos persistência em Kubernetes.
- A `SUPABASE_SERVICE_KEY` ignora Row Level Security e só pode existir em
  serviço de backend, nunca no navegador.
