# message-history Specification

## Purpose
TBD - created by archiving change conversation-history-media-storage. Update Purpose after archive.
## Requirements
### Requirement: Payload bruto persistido por mensagem

O sistema DEVE persistir o payload bruto (JSON) recebido do provedor
de canal junto de cada mensagem, quando disponível, sem exigir esse dado
para mensagens que não o têm (ex.: comandos internos do admin).

#### Scenario: Mensagem recebida via webhook grava o payload original

- **WHEN** uma mensagem de texto é recebida via WhatsApp Cloud API
- **THEN** a linha correspondente em `mensagens` grava `canal`,
  `message_id` e o payload bruto do evento em `payload`

#### Scenario: Mensagem sem payload de canal continua funcionando

- **WHEN** uma mensagem é salva por um fluxo que não tem payload de canal
  (ex.: `whatbot/admin.py`)
- **THEN** a mensagem é gravada normalmente com `payload` nulo, sem erro

#### Scenario: Reentrega do mesmo evento não duplica a mensagem

- **WHEN** o provedor reenvia o mesmo webhook (mesmo `canal` +
  `message_id`) após timeout
- **THEN** apenas uma linha existe em `mensagens` para esse
  `(canal, message_id)`

### Requirement: Mídia recebida é baixada e referenciada

O sistema DEVE baixar mídia recebida via WhatsApp Cloud API
(imagem/áudio/vídeo/documento/sticker) e referenciá-la em disco, em vez de
descartar o evento.

#### Scenario: Mensagem de mídia gera uma referência de arquivo

- **WHEN** o cliente envia uma imagem, áudio, vídeo, documento ou sticker
- **THEN** o sistema baixa o binário da Graph API e grava uma linha em
  `media_arquivos` com `tipo`, `mime_type`, `storage_key` e
  `origem_media_id`
- **AND** a mensagem correspondente em `mensagens` referencia essa linha
  via `media_id`

#### Scenario: Falha de download não bloqueia a mensagem

- **WHEN** o download do binário falha (rede, token expirado, mídia
  expirada na Meta)
- **THEN** a mensagem ainda é registrada em `mensagens`
- **AND** `media_arquivos.status` fica `falhou` com o erro em `erro`,
  sem interromper o restante do processamento da mensagem

### Requirement: Armazenamento local isolado por chave

O sistema DEVE armazenar mídia em disco através de uma abstração de
armazenamento por chave relativa (`storage_key`), sem expor paths
absolutos de disco fora do módulo de armazenamento, para permitir trocar o
backend (ex.: para um serviço em nuvem) sem alterar o schema ou os
consumidores da API.

#### Scenario: Chave de storage é relativa

- **WHEN** um arquivo de mídia é salvo
- **THEN** `media_arquivos.storage_key` é uma chave relativa (não um path
  absoluto de disco)

#### Scenario: Leitura de mídia não acessa o disco diretamente

- **WHEN** qualquer parte do sistema precisa ler um arquivo de mídia
  salvo
- **THEN** o acesso passa pela interface `StorageBackend` (`open`/`url`),
  nunca por um path de arquivo montado fora do módulo de armazenamento

### Requirement: Histórico paginado por conversa

O sistema DEVE expor uma forma de consultar o histórico de mensagens de
uma conversa com paginação por cursor, incluindo payload e referência de
mídia quando existirem.

#### Scenario: Histórico é retornado em ordem cronológica reversa

- **WHEN** o histórico de um contato é consultado sem cursor
- **THEN** as mensagens mais recentes são retornadas primeiro, respeitando
  o limite pedido

#### Scenario: Paginação por cursor não repete nem pula mensagens

- **WHEN** uma segunda página é pedida usando o cursor (`before`) da
  última mensagem da página anterior
- **THEN** a página seguinte não repete nenhuma mensagem já retornada

### Requirement: API administrativa exige autenticação

O sistema DEVE exigir um token de autenticação válido em toda rota
administrativa (`/admin/*`) usada para expor conversas a um consumidor
externo.

#### Scenario: Requisição sem token é rejeitada

- **WHEN** uma requisição a uma rota `/admin/*` não inclui um bearer token
  válido
- **THEN** o sistema responde com erro de autenticação (401) e nenhum
  dado de conversa é retornado

### Requirement: Envio humano reusa o roteador de canais

O sistema DEVE enviar mensagens originadas da API administrativa através
do `ChannelRouter` existente, nunca através de um cliente de canal
concreto, e DEVE recusar o envio quando o contato não está em modo de
atendimento humano.

#### Scenario: Envio em modo bot é recusado

- **WHEN** uma mensagem é enviada pela API administrativa para um contato
  que não está em atendimento humano
- **THEN** o envio é recusado, sem chamar nenhum canal

#### Scenario: Envio em atendimento humano usa o roteador

- **WHEN** uma mensagem é enviada pela API administrativa para um contato
  em atendimento humano
- **THEN** o envio passa por `ChannelRouter.send_to_contact`, no canal
  correto do contato

