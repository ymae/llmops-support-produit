# ============================================
# Makefile - Support Produit Nexus Platform 
# ============================================

.PHONY: all help setup build start up stop down rebuild restart status ps logs logs-json test tests clean

.DEFAULT_GOAL := help

DOCKER_COMPOSE := docker compose
SERVICES := langfuse-db langfuse-server litellm-proxy backend-api frontend
LOG_FILE := logs/app.jsonl

all: build up ## Construit les images puis démarre l'ensemble des services

help: ## Affiche l'aide auto-générée des commandes disponibles
	@echo "=============================================================================="
	@echo "  Support Produit - Nexus Platform - Commandes Makefile"
	@echo "=============================================================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo "=============================================================================="

setup: ## Initialise l'environnement local (.env, dossier logs/ et synchronisation uv)
	@echo "--> Vérification du fichier .env..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "    Fichier .env créé à partir de .env.example."; \
	else \
		echo "    Fichier .env déjà présent."; \
	fi
	@echo "--> Création du dossier logs/..."
	@mkdir -p logs
	@touch logs/.gitkeep
	@echo "--> Synchronisation de l'environnement virtuel via uv..."
	uv sync
	@echo "--> Initialisation terminée avec succès."

build: ## Construit les images Docker de l'architecture via Docker Compose
	$(DOCKER_COMPOSE) build $(SERVICES)

start: up ## Alias de 'make up' : démarre l'ensemble des conteneurs en arrière-plan

up: ## Démarre l'ensemble des conteneurs Docker en arrière-plan et affiche leurs URLs
	@mkdir -p logs
	$(DOCKER_COMPOSE) up -d $(SERVICES)
	@echo "=============================================================================="
	@echo "  Frontend Chainlit     : http://localhost:8000"
	@echo "  Backend API (Swagger) : http://localhost:8080/docs"
	@echo "  LiteLLM Proxy         : http://localhost:4000"
	@echo "  Langfuse Local        : http://localhost:3000"
	@echo "=============================================================================="

stop: down ## Alias de 'make down' : arrête et supprime les conteneurs actifs

down: ## Arrête et supprime les conteneurs Docker actifs
	$(DOCKER_COMPOSE) down

rebuild: ## Reconstruit les images et redémarre tous les services applicatifs
	$(DOCKER_COMPOSE) down
	$(DOCKER_COMPOSE) build $(SERVICES)
	$(MAKE) up

restart: down up ## Redémarre complètement tous les conteneurs Docker

status: ps ## Alias de 'make ps' : affiche l'état de santé des conteneurs

ps: ## Affiche l'état des conteneurs Docker Compose
	$(DOCKER_COMPOSE) ps

logs: ## Affiche les journaux Docker en temps réel de tous les services
	$(DOCKER_COMPOSE) logs -f --tail=50

logs-json: ## Affiche les traces techniques locales du Logger JSON structuré (logs/app.jsonl)
	@if [ -f $(LOG_FILE) ]; then \
		cat $(LOG_FILE); \
	else \
		echo "Aucun fichier de log JSON trouvé dans $(LOG_FILE)."; \
	fi

test: ## Exécute la suite de tests unitaires et fonctionnels via uv run pytest
	uv run pytest -v

tests: ## Exécute les tests unitaires et d'intégration dans le conteneur dédié Docker
	$(DOCKER_COMPOSE) up -d --build backend-api
	$(DOCKER_COMPOSE) --profile test run --rm --build tests; status=$$?; \
	$(DOCKER_COMPOSE) stop backend-api; \
	exit $$status

clean: ## Nettoie les caches Python/pytest et les conteneurs Docker orphelins
	@echo "--> Nettoyage des caches Python et pytest..."
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "--> Nettoyage des conteneurs Docker orphelins..."
	-@$(DOCKER_COMPOSE) down --remove-orphans 2>/dev/null || true
	@echo "--> Nettoyage terminé."
