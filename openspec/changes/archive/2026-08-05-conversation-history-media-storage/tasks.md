# Tasks — histórico de conversas, mídia e API de leitura

## 1. Schema

- [x] 1.1 Estender `mensagens` em `ensure_schema()` (`whatbot/db.py`):
      `canal VARCHAR(32)`, `message_id VARCHAR(128)`, `payload JSONB`,
      `media_id INTEGER REFERENCES media_arquivos(id)`; backfill
      `canal = 'whatsapp'` para linhas existentes; índice
      `mensagens_contact_created_idx (contact_id, created_at DESC)`;
      índice único parcial `mensagens_canal_message_id_idx (canal,
      message_id) WHERE message_id IS NOT NULL` (→ Requirement "Payload
      bruto persistido por mensagem")
- [x] 1.2 Nova tabela `media_arquivos` (`id, contact_id, canal, tipo,
      mime_type, tamanho_bytes, storage_backend, storage_key,
      origem_media_id, status, erro, created_at`) + índice
      `media_arquivos_contact_idx (contact_id, created_at DESC)`
      (→ Requirement "Mídia recebida é baixada e referenciada")
- [x] 1.3 `MessageRecord` (dataclass) ganha os novos campos; atualizar
      qualquer lugar que constrói `MessageRecord` manualmente

## 2. Abstração de storage

- [x] 2.1 `whatbot/storage/base.py` — `StorageBackend` (Protocol):
      `save(key, data, content_type) -> None`, `open(key) -> bytes`,
      `url(key) -> str | None`
- [x] 2.2 `whatbot/storage/local.py` — `LocalDiskStorage(root_dir)`:
      grava/lê em `root_dir/key`, cria diretórios pai, rejeita chave que
      resolva para fora de `root_dir` (path traversal)
      (→ Requirement "Armazenamento local isolado por chave")
- [x] 2.3 `whatbot/storage/factory.py` — `get_storage_backend()` lê
      `MEDIA_STORAGE_BACKEND` (default `local`) e `MEDIA_STORAGE_ROOT`;
      levanta erro claro se `s3` for pedido (não implementado nesta etapa)

## 3. Download de mídia (WhatsApp Cloud)

- [x] 3.1 `whatsapp_cloud_webhook.py`: `classify_whatsapp_cloud_event`
      continua igual; `KIND_MEDIA_ONLY` passa a produzir `data` com
      `media_id` (Graph), `tipo`, `mime_type`, `caption` — não mais
      `None` (→ Requirement "Mídia recebida é baixada e referenciada")
- [x] 3.2 `InboundMessage` (`whatbot/channels/base.py`) ganha campo
      opcional para referência de mídia, sem quebrar canais que não usam
      mídia
- [x] 3.3 `WhatsAppCloudClient.download_media(media_id) -> tuple[bytes,
      str]` (`whatbot/channels/whatsapp_cloud.py`): `GET /{media-id}`
      (URL temporária) + `GET` autenticado nessa URL
- [x] 3.4 `whatbot/main.py`: no recebimento de mensagem com mídia — baixa
      via `download_media`, salva via `StorageBackend.save`, insere
      `media_arquivos`, chama `save_message(..., payload=raw_event,
      media_id=...)`. Falha no download grava `status='falhou'`/`erro`
      e não interrompe o processamento da mensagem
      (→ Requirement "Falha de download não bloqueia a mensagem")

## 4. Persistência de payload + leitura paginada

- [x] 4.1 `Database.save_message(contact_id, direction, text, *,
      canal=None, message_id=None, payload=None, media_id=None)` —
      todos os 7 call sites existentes continuam passando sem alteração
- [x] 4.2 `Database.get_conversation(contact_id, *, limit, before=None)`
      — paginação por cursor (`created_at`/`id`), substitui o uso de
      `get_recent_messages` onde histórico completo é necessário
- [x] 4.3 Pontos que já têm o payload bruto do webhook (`whatbot/main.py`
      linhas atuais de `save_message` para mensagens recebidas) passam a
      informar `canal`/`message_id`/`payload`

## 5. API administrativa (`whatbot/ingress.py`)

- [x] 5.1 Autenticação por bearer token (`ADMIN_API_TOKEN`, env var
      nova) nas rotas `/admin/*`
      (→ Requirement "API administrativa exige autenticação")
- [x] 5.2 `GET /admin/conversas` — lista contatos com última
      mensagem/preview, canal, status bot/humano
- [x] 5.3 `GET /admin/conversas/{contact_id}/mensagens?before=&limit=` —
      histórico paginado via `get_conversation`, com `payload` e
      metadados de mídia quando houver
      (→ Requirement "Histórico paginado por conversa")
- [x] 5.4 `GET /admin/midia/{media_id}` — stream do binário via
      `StorageBackend.open`, `Content-Type` do `mime_type` salvo
- [x] 5.5 `POST /admin/conversas/{contact_id}/mensagens` — só aceito
      quando o contato está em atendimento humano; envia via
      `ChannelRouter.send_to_contact`, nunca client concreto
      (→ Requirement "Envio humano reusa o roteador de canais")

## 6. Testes

- [x] 6.1 Teste de integração (`tests/integration/`, padrão
      `test_identity_migration.py`) validando a migração aditiva de
      `mensagens`/`media_arquivos` contra Postgres real
      (`WHATBOT_TEST_DSN`)
- [x] 6.2 `LocalDiskStorage`: save/open roundtrip, rejeição de path
      traversal, diretório criado automaticamente
- [x] 6.3 `whatsapp_cloud_webhook.py`: uma mensagem de cada tipo de
      mídia (image/audio/video/document/sticker) gera `data` com
      referência de mídia, não `None`
- [x] 6.4 `WhatsAppCloudClient.download_media`: sucesso e falha (fake
      HTTP), garantindo que a falha não propaga exceção não tratada até
      `main.py`
- [x] 6.5 `save_message`/`get_conversation`: compatibilidade dos 7 call
      sites existentes (sem os novos kwargs) + paginação por cursor
- [x] 6.6 Rotas `/admin/*`: 401 sem token válido; fluxo feliz de listar
      conversas, histórico paginado e envio humano (fake `ChannelRouter`)
- [x] 6.7 Suíte completa verde (`python -m unittest discover -s tests -p
      'test_*.py'`, via `mcp__context-mode__ctx_execute`)
