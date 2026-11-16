# =============================================================================
#  Prismo — atalhos de desenvolvimento
#
#  No Windows use o Git Bash ou o WSL. Se preferir PowerShell, use ./dev.ps1,
#  que tem exatamente os mesmos alvos.
# =============================================================================

COMPOSE     := docker compose
COMPOSE_OBS := docker compose -f docker-compose.yml -f docker-compose.obs.yml

.DEFAULT_GOAL := help
.PHONY: help setup up down obs build logs ps restart smoke clean nuke

help: ## Lista os alvos disponiveis
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Cria o .env a partir do modelo (nao sobrescreve o existente)
	@test -f .env || (cp .env.example .env && echo "  .env criado. Preencha DATABASE_URL e JWT_SECRET.")
	@test -f .env && echo "  .env pronto."

up: ## Sobe a aplicacao (redis + gateway + web)
	$(COMPOSE) up --build -d
	@echo ""
	@echo "  web ............ http://localhost:8000"
	@echo "  status ......... http://localhost:8000/status"
	@echo "  gateway (API) .. http://localhost:8001/docs"

obs: ## Sobe aplicacao + Prometheus + Grafana
	$(COMPOSE_OBS) up --build -d
	@echo ""
	@echo "  web ............ http://localhost:8000"
	@echo "  grafana ........ http://localhost:3000  (admin / prismo)"
	@echo "  prometheus ..... http://localhost:9090"

down: ## Para tudo, preservando os volumes
	$(COMPOSE_OBS) down

build: ## Reconstroi as imagens sem usar cache
	$(COMPOSE) build --no-cache

logs: ## Acompanha os logs (make logs s=gateway para um servico)
	$(COMPOSE_OBS) logs -f --tail=100 $(s)

ps: ## Estado dos containers e healthchecks
	$(COMPOSE_OBS) ps

restart: ## Reinicia um servico (make restart s=web)
	$(COMPOSE) restart $(s)

smoke: ## Verifica se os endpoints essenciais respondem
	@python scripts/smoke_test.py

clean: ## Remove containers e redes, preservando os volumes
	$(COMPOSE_OBS) down --remove-orphans

nuke: ## Remove TUDO, inclusive os volumes (apaga os dados do Redis)
	$(COMPOSE_OBS) down -v --remove-orphans
