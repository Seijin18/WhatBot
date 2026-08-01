# Atendimento de DMs do Instagram

## Why

A associação recebe mensagens por Instagram Direct que hoje ninguém responde
automaticamente, enquanto o WhatsApp já tem bot com base de conhecimento, fila e
handover. A Evolution API v2 (`2.3.7`, a que está no `docker-compose.yml`) só
suporta WhatsApp — Instagram e Messenger constam como roadmap, não como recurso.
Não existe caminho de configuração: é desenvolvimento.

Contexto completo, com pré-requisitos da Meta, riscos e estratégia de
homologação, em `docs/INSTAGRAM_INTEGRATION_PLAN.md`. Este change rastreia a
execução; o documento segue como a referência narrativa.

## What Changes

Quatro decisões estruturam o resto:

1. **Refatorar para multicanal, não bifurcar o projeto.** Uma segunda instância
   duplicaria banco, base de conhecimento e fila, e daria à secretaria duas filas
   para gerenciar. Refatorar a identidade uma vez custa menos que manter dois
   sistemas para sempre.
2. **Usar a Instagram API with Instagram Login** (`graph.instagram.com`), que não
   exige Página do Facebook vinculada nem App Review para contas próprias sob
   Standard Access — removendo o maior risco de cronograma.
3. **Identidade do contato passa a ser `(canal, external_id)`.** Uma pessoa por
   canal; WhatsApp e Instagram não são unificados. Migração aditiva, histórico
   atual integralmente preservado como `canal='whatsapp'`.
4. **Serviço de ingestão HTTP dedicado**, em vez de apontar o webhook da Meta
   direto para o Windmill. A Meta exige handshake `GET`, validação de assinatura
   sobre o corpo bruto e resposta em menos de 20 s; o fluxo atual do Windmill é
   síncrono e chama o modelo antes de responder, o que geraria reentrega e
   resposta duplicada ao cliente.

Fases, em ordem de dependência (detalhe em `tasks.md`):

- **Fase 1 — camada de canais.** Entregue em `18ce004`; acabamento no change
  `harden-channel-layer`.
- **Fase 2 — migração de identidade no banco** (pré-requisito de tudo)
- **Fase 3 — cliente e parser do Instagram**
- **Fase 4 — exposição HTTPS** (paralelizável, pode começar no dia um)
- **Fase 5 — regras da janela de 24 horas**
- **Fase 6 — serviço de ingestão**
- **Fase 7 — integração ponta a ponta e conexão real**
- **Fase 8 — documentação e operação**

## Impact

- Specs afetadas: `instagram` (nova), `channels` (roteamento por canal do contato)
- Código novo: `whatbot/channels/instagram.py`, `whatbot/instagram_webhook.py`,
  `whatbot/ingress.py`, `scripts/ig_*.py`,
  `windmill/f/whatbot/refresh_ig_token.py`
- Código alterado: `whatbot/db.py` (identidade), `whatbot/queue.py` e
  `whatbot/contact_resolver.py` (normalização de telefone deixa de valer para
  todo canal), `whatbot/config.py`, `docker-compose.yml`, `requirements.txt`
- Sem regressão no WhatsApp: nada no caminho dele passa pelo serviço novo, e as
  migrações são aditivas
- Bloqueado por: `harden-channel-layer` (rede de segurança de testes para a
  reescrita do `db.py`)
