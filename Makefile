.PHONY: up up-d down logs ps test test-migration chat chat-test

COMPOSE = docker compose
PROFILES = --profile windmill
CHAT_DOCKER = docker run --rm -v "$(CURDIR):/app" -w /app --env-file .env \
	--add-host=host.docker.internal:host-gateway \
	-e DB_DSN=postgresql://whatbot:whatbot@host.docker.internal:5432/whatbot \
	python:3.12-slim
CHAT_INSTALL = pip install -q -r requirements.txt &&

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

# Teste de migração de schema contra Postgres real (fora de `make test`).
# Requer WHATBOT_TEST_DSN apontando para o serviço `db` do docker-compose.
# Ex.: WHATBOT_TEST_DSN=postgresql://whatbot:whatbot@localhost:5432/whatbot make test-migration
test-migration:
	python -m pytest tests/integration/test_identity_migration.py -v

# Teste local do bot (simulado, sem WhatsApp). Ex.: make chat-test MSG='Quais modalidades?'
chat-test:
	$(CHAT_DOCKER) bash -lc "$(CHAT_INSTALL) python scripts/chat_test.py \"$(MSG)\""

chat:
	docker run --rm -it -v "$(CURDIR):/app" -w /app --env-file .env \
		--add-host=host.docker.internal:host-gateway \
		-e DB_DSN=postgresql://whatbot:whatbot@host.docker.internal:5432/whatbot \
		python:3.12-slim bash -lc "$(CHAT_INSTALL) python scripts/chat_test.py -i"
