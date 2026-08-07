# Assumir atendimento direto pela API administrativa

## Why

Hoje só existem dois jeitos de um contato entrar em atendimento humano
(`ia_ativa = FALSE`): o bot detectar um pedido explícito ("quero falar com
alguém"/pedido de catálogo) ou um admin usar o comando `assumir` pelo
WhatsApp — mas esse comando (`Database.assumir_contato`) só funciona se o
contato **já estiver na fila** (`handover_at IS NOT NULL AND atendido_at IS
NULL`), ou seja, o bot precisa ter acionado o handover primeiro.

Isso é uma limitação real ao operar pelo visualizador de conversas
(`conversation-history-media-storage`): um admin acompanhando o histórico
pode querer intervir numa conversa imediatamente — sem esperar o cliente
pedir humano — e hoje não há como.

## What Changes

- Novo método `Database.assumir_atendimento_direto(contact_id, *, motivo,
  assumido_por, prioridade)` — mesma transição de estado de
  `enroll_handover` (`ia_ativa = FALSE`, `handover_at = now()`,
  `atendido_at = NULL`, `handover_motivo`, `prioridade`), mas grava
  `assumido_por` na mesma escrita, pulando o estado intermediário "na fila
  aguardando alguém assumir" — quem chama já é quem vai atender.
- Nova rota `POST /admin/conversas/{contact_id}/assumir` em
  `whatbot/ingress.py` (mesma autenticação por bearer token das demais
  rotas `/admin/*`): idempotente (contato já em atendimento humano não é
  erro, só confirma o estado atual); contato inexistente é 404.
- Não dispara a notificação de fila normal (`process_new_handover`) — quem
  chama essa rota já é quem está assumindo, notificar a própria pessoa não
  agrega nada; distinto do handover automático, que precisa avisar alguém
  disponível.

## Impact

- Specs afetadas: `message-history` (estende)
- Código alterado: `whatbot/db.py`, `whatbot/ingress.py`
- Testes alterados: novo teste de `assumir_atendimento_direto` em
  `tests/` (DB) e da rota em `tests/test_ingress.py`
- Bloqueado por: nenhum (aditivo, reaproveita a mesma transição de estado
  de `enroll_handover`)
- Habilita: o botão "assumir atendimento" no visualizador temporário
  (`whatbot/static/admin_ui.html`) e, futuramente, o mesmo botão no painel
  definitivo (`camu-web-admin`) — a rota é a mesma para os dois.
