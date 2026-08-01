# WhatBot — contexto do projeto

## Propósito

Bot de atendimento para uma associação esportiva. Recebe mensagens de clientes,
responde com IA ancorada numa base de conhecimento local (`knowledge/`), e
transfere para a secretaria humana (handover) quando necessário — mantendo uma
fila que a secretaria opera por comandos em linguagem natural.

## Stack

- **Python 3.13**, sem framework. Pacote único `whatbot/`.
- **Postgres** via `psycopg` + `psycopg_pool` (`whatbot/db.py`).
- **LLM:** Gemini (`google-genai`) com fallback para Ollama e, por último,
  resposta montada a partir da base de conhecimento (`whatbot/fallback.py`).
- **WhatsApp:** Evolution API v2 (Baileys) em container.
- **Orquestração:** Windmill. Os entrypoints de produção são
  `windmill/f/whatbot/handler.py` (webhook) e `windmill/f/whatbot/check_queue.py`
  (job agendado), que delegam para `whatbot.main.main(payload)` e
  `whatbot.main.check_queue()`.
- Infra local: `docker-compose.yml` (perfis `windmill` e `bot`), `Makefile`,
  `run.ps1`.

## Convenções

- **Testes:** `unittest` puro, sem `conftest.py` e sem fixtures de pytest.
  Descoberta por `python -m unittest discover -s tests -p 'test_*.py'`
  (`make test`); `pytest -q` também roda a mesma suíte.
  Fakes compartilhados vivem em `tests/fakes.py` — nada de rede e nada de
  Postgres nos testes unitários.
- **Idioma:** código, identificadores e docstrings em inglês; mensagens ao
  usuário final, logs de negócio e documentação em português.
- **Camadas:** `whatbot/channels/` é a única fronteira de saída. Nenhum módulo de
  domínio deve segurar um cliente de canal concreto — sempre o `ChannelRouter`
  ou os helpers `send_admin` / `send_to_contact`.
- **Chave de identidade:** hoje `contatos.phone`. A migração para
  `(canal, external_id)` está planejada (ver capability `instagram`).

## Documentos de referência

- `docs/INSTAGRAM_INTEGRATION_PLAN.md` — o plano narrativo completo da
  integração com Instagram (fases, riscos, pré-requisitos da Meta, estratégia de
  homologação). As specs em `openspec/specs/` destilam dele os requisitos
  verificáveis; o documento segue sendo a fonte de contexto e justificativa.
- `DEPLOYMENT.md` — pareamento do WhatsApp e troubleshooting da Evolution API.
