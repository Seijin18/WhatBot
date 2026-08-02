# Janela de mensageria do Instagram

## Why

A política da Meta para o Instagram Direct restringe quando uma conta pode
enviar mensagem: dentro de 24h do último contato do usuário, envio livre;
entre 24h e 7 dias, só sob permissão de atendimento humano; depois de 7 dias,
nada. Enviar fora da janela não é só um bug — é violação de política que pode
suspender a conta.

Hoje não existe onde guardar "quando foi o último recebimento daquele
contato" (`last_inbound_at` não existe no schema) nem nenhuma checagem antes
de enviar. Este change fecha essa lacuna, depois que `identity-multichannel`
já tiver criado a coluna.

## What Changes

- Persistir `last_inbound_at` a cada mensagem de entrada do Instagram.
- Verificação da janela antes de todo envio pelo canal Instagram: dentro de
  24h, envio normal; fora de 24h e dentro de 7 dias, só com
  `human_agent=True`; fora de 7 dias, envio bloqueado e registrado como
  falha identificada.
- Reativação automática do bot (quando o handover é encerrado) NÃO gera
  mensagem proativa — só volta a responder na próxima mensagem do cliente.
- Notificação de fila informa o prazo de resposta quando o canal impõe
  janela (extensão do rótulo definido em `channel-queue-visibility`,
  específica do Instagram).

## Impact

- Specs afetadas: `instagram`
- Código alterado: `whatbot/channels/instagram.py` (checagem da janela
  dentro do cliente, antes de despachar o envio — ver `design.md`, não
  `whatbot/domain.py`), `whatbot/queue.py` (prazo na notificação, estendendo
  o rótulo que `channel-queue-visibility` já introduziu), pontos que
  persistem `last_inbound_at` no caminho de entrada
- Testes novos: `tests/test_messaging_window.py`, com relógio injetado (sem
  depender do horário real da máquina)
- Bloqueado por:
  - `identity-multichannel` (usa a coluna `last_inbound_at`)
  - `instagram-channel-client` (edita `whatbot/channels/instagram.py`, que
    esse change cria; usa a causa `window_expired` de `ChannelError` já
    definida lá)
  - `channel-queue-visibility` (estende a mesma notificação de fila que
    aquele change introduz — evita duas edições concorrentes da mesma
    string)
