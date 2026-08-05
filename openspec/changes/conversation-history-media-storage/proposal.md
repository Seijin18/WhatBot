# Histórico de conversas com payload bruto, mídia recebida e API de leitura/envio

## Why

O WhatBot passou a usar a WhatsApp Cloud API
(`whatsapp-cloud-channel-client`), mas hoje não existe nenhuma forma de
visualizar as conversas: a tabela `mensagens` é rudimentar (`id,
contact_id, direction, text, created_at` — sem canal, sem payload bruto,
sem mídia), e toda mensagem de mídia recebida
(áudio/imagem/vídeo/documento/sticker) é classificada como
`KIND_MEDIA_ONLY` e **descartada silenciosamente**
(`whatbot/whatsapp_cloud_webhook.py:51-59`, produz `data=None` — nada é
baixado, nada é persistido).

Sem isso, não há como auditar o que o bot respondeu, investigar uma
reclamação, ou sequer saber que um cliente mandou um áudio. Também não há
nenhuma forma de conectar essas conversas a uma interface — o painel
administrativo da empresa (estoque, vendas, precificação) vive num
repositório separado (`Projeto-Aba-Reta/camu-web-admin`, Next.js/Supabase,
banco Postgres **diferente** do WhatBot), então a integração só pode ser
via API HTTP, não leitura direta de tabela.

## What Changes

- Estende a tabela `mensagens` com `canal`, `message_id`, `payload JSONB`
  (o payload bruto recebido do provedor) e `media_id` — sem criar tabela
  paralela de histórico.
- Nova tabela `media_arquivos` para referenciar mídia recebida: tipo, mime,
  tamanho, backend de armazenamento, chave de storage, id de mídia do
  provedor, status de download.
- Novo módulo `whatbot/storage/` — abstração de armazenamento
  (`StorageBackend` Protocol) com implementação local em disco hoje,
  desenhada para trocar por S3 depois sem tocar no restante do código
  (mesmas `storage_key`s, só troca a implementação do backend).
- Pipeline de download de mídia: `whatsapp_cloud_webhook.py` para de
  descartar `KIND_MEDIA_ONLY` e passa a extrair a referência de mídia;
  `WhatsAppCloudClient.download_media()` baixa o binário da Graph API;
  `whatbot/main.py` grava o arquivo via `StorageBackend` e registra em
  `media_arquivos`. Falha no download não derruba o processamento da
  mensagem (fica marcada `status='falhou'`, revisável depois).
- `Database.save_message` ganha parâmetros opcionais (`canal`,
  `message_id`, `payload`, `media_id`) — compatível com as 7 chamadas
  existentes sem alteração. Nova `Database.get_conversation(...)` com
  paginação por cursor.
- Novo grupo de rotas em `whatbot/ingress.py` (único serviço HTTP do
  projeto), autenticado por bearer token simples
  (`ADMIN_API_TOKEN`): listar conversas, histórico paginado de uma
  conversa, servir mídia, e enviar mensagem como atendente humano
  (reaproveitando `ChannelRouter.send_to_contact` — nunca client
  concreto direto).

## Impact

- Specs afetadas: nova capability `message-history`
- Código alterado: `whatbot/db.py`, `whatbot/whatsapp_cloud_webhook.py`,
  `whatbot/channels/whatsapp_cloud.py`, `whatbot/channels/base.py`
  (referência de mídia em `InboundMessage`), `whatbot/main.py`,
  `whatbot/ingress.py`, novo pacote `whatbot/storage/`
- Testes alterados: `tests/` (parser de mídia, `save_message`/
  `get_conversation`), novo `tests/integration/` para a migração aditiva,
  novo teste unitário de `LocalDiskStorage`
- Bloqueado por: nenhum (aditivo, independente de
  `whatsapp-cloud-channel-client` já mesclado)
- Habilita: a tela de conversas no `camu-web-admin` (repositório externo,
  fora do escopo deste change — só a API é entregue aqui)

## Fora de escopo (decisão explícita)

- **Implementação do backend S3.** A abstração (`StorageBackend`) já
  prevê o valor `s3` em `MEDIA_STORAGE_BACKEND`, mas a classe concreta não
  é escrita agora — só faz sentido quando a operação realmente for migrar
  para nuvem.
- **A tela de conversas em si no `camu-web-admin`.** Repositório e stack
  próprios (Next.js/Supabase); este change entrega só a API HTTP que essa
  tela consumiria.
- **Download de mídia para o canal Instagram / Evolution API.** Mesmo
  problema existe em `whatbot/instagram_webhook.py`, mas o pipeline aqui é
  desenhado só para WhatsApp Cloud API (única fonte de mídia hoje com
  Graph API oficial disponível); estender para Instagram é aditivo e pode
  ser um change separado reaproveitando `whatbot/storage/`.
