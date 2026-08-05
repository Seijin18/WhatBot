# Design — janela de mensageria do Instagram

## Decisão: a checagem vive dentro de `whatbot/channels/instagram.py`, não em `domain.py`

Cogitou-se inicialmente colocar a regra em `whatbot/domain.py`, perto de
onde o handover decide agir. Rejeitada: `openspec/project.md` (seção
"Convenções") estabelece que `whatbot/channels/` é a única fronteira que
conhece particularidades de canal, e nenhum módulo de domínio deve saber que
um canal específico impõe janela de mensageria — isso acoplaria lógica de
conversa a uma regra que só existe para o Instagram.

**Escolha**: a checagem entra no `send_text` do próprio cliente
`whatbot/channels/instagram.py` (criado por `instagram-channel-client`,
editado por este change): antes de despachar a chamada HTTP, o cliente
consulta `last_inbound_at` do contato (via uma pequena função de acesso
injetada, não uma dependência direta em `db.py` dentro do cliente) e decide
enviar, exigir `human_agent=True`, ou levantar
`ChannelError(..., cause="window_expired")` — a causa já definida como
contrato por `instagram-channel-client`. Isso mantém `domain.py` e `main.py`
agnósticos de canal: eles só reagem a `ChannelError`, do mesmo jeito que já
reagem a falha de transporte do WhatsApp.

Consequência prática: qualquer envio automático futuro (lembrete, mensagem
proativa) passa pela mesma regra automaticamente, só por usar o cliente do
canal — não precisa reimplementar a checagem em cada lugar que decide
"enviar uma mensagem".

## Decisão: relógio injetado nos testes

A regra depende de "agora menos `last_inbound_at`". Testar isso com o
relógio real do sistema é frágil (testes ficam dependentes de quando rodam).
Os quatro cenários (dentro de 24h, entre 24h e 7 dias, além de 7 dias,
reativação sem mensagem proativa) recebem um `now` injetável — não existe
hoje um padrão equivalente em `tests/test_queue.py` (que usa
`datetime.now(timezone.utc)` direto), então este change introduz o padrão de
injeção de relógio, a ser reaproveitado por testes futuros que precisem de
tempo determinístico.

## Não-objetivos

- Envio de mensagem proativa de reengajamento — fora de escopo, e a regra diz
  o oposto (reativação não gera mensagem).
- Persistência de fila de mensagens adiadas para reenvio quando a janela
  reabrir — não existe essa funcionalidade hoje em nenhum canal, e não é
  necessária para o Instagram funcionar.
