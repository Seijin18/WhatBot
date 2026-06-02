.PHONY: up up-d down logs ps test

COMPOSE = docker compose
PROFILES = --profile windmill

# Sobe infra (Postgres, Redis, Evolution API) + Windmill
up:
	$(COMPOSE) $(PROFILES) up

up-d:
	$(COMPOSE) $(PROFILES) up -d

down:
	$(COMPOSE) $(PROFILES) down

logs:
	$(COMPOSE) logs -f evolution-api windmill_server windmill_worker_native

ps:
	$(COMPOSE) $(PROFILES) ps

test:
	python -m unittest discover -s tests -p 'test_*.py' -v
