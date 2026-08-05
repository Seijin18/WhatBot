# Finalizar atendimento não desliga mais o bot

## Why

Hoje, sempre que um atendimento é finalizado — admin envia "atendi o
João" (`acao == "complete"` em `whatbot/admin.py`), finaliza em lote
(`mark_all_attended`), ou a secretaria responde direto pelo WhatsApp
Business (`handle_staff_outgoing_message` em `whatbot/queue.py`) — o bot
fica com `ia_ativa = FALSE` para aquele contato por `AUTO_REACTIVATE_HOURS`
(default 24h, `whatbot/config.py`), só voltando sozinho quando
`process_auto_reactivations()` roda e encontra `bot_resume_at <= now()`.

Isso foi observado na prática: um contato de teste mandou mensagem depois
de um atendimento ter sido marcado como concluído e não recebeu resposta
nenhuma — nem do bot (desativado) nem de um humano (ninguém assumiu de
novo) — porque o `bot_resume_at` ainda estava no futuro. O usuário decidiu
que esse desligamento pós-atendimento não deve mais existir: ao finalizar
um atendimento, o bot deve voltar a responder imediatamente, não depois de
um prazo.

## What Changes

- `mark_attended` continua existindo com a mesma assinatura (usada
  livremente por outros fluxos), mas os três call sites que hoje
  finalizam atendimento passam a chamá-lo com `reativar_bot=True` em vez
  de `reativar_bot=False, schedule_resume_hours=AUTO_REACTIVATE_HOURS`:
  - `whatbot/admin.py` — ação `complete` (finalizar um item da fila)
  - `whatbot/admin.py` — finalização em lote (`mark_all_attended`)
  - `whatbot/queue.py` — `handle_staff_outgoing_message` (auto-completar
    quando a secretaria responde via WhatsApp Business)
- As mensagens de confirmação ao admin que citam "Bot reativa
  automaticamente em Xh" são atualizadas para refletir que o bot já está
  ativo de novo, sem prazo.
- `AUTO_REACTIVATE_HOURS` (`whatbot/config.py`) e
  `process_auto_reactivations()` (`whatbot/db.py`,
  chamado por `whatbot/main.py` e `whatbot/queue.py`) permanecem no
  código — deixam de ser exercitados pelo fluxo de finalizar atendimento,
  mas continuam corretos e inofensivos (nenhum dos três call sites volta a
  setar `bot_resume_at`, então o sweep simplesmente não encontra nada a
  reativar). Removê-los é decisão separada, fora deste change (ver Fora
  de escopo).
- **Não afeta** a pausa manual (`admin-bot-pause`, "pausa o bot para
  X"/"libera o bot para X") — essa já era indefinida por design (Decisão 2
  do change arquivado) e continua igual.

## Impact

- Specs afetadas: `admin` (novo requisito, substituindo a mensagem hoje
  implícita em código sem cobertura formal em `openspec/specs/`)
- Código alterado: `whatbot/admin.py`, `whatbot/queue.py`
- Testes alterados: `tests/test_admin_organic.py`, `tests/test_queue.py`,
  `tests/test_messaging_window.py` (onde citarem `bot_resume_at`/
  `AUTO_REACTIVATE_HOURS` para os três fluxos acima)
- Bloqueado por: nenhum

## Fora de escopo (decisão explícita)

- Remover `AUTO_REACTIVATE_HOURS`/`process_auto_reactivations` do código —
  ficam como mecanismo morto-mas-inofensivo após este change; removê-los
  totalmente é um cleanup separado, sem urgência funcional.
- Qualquer mudança na pausa manual (`pausar_bot`/`reativar_bot` via
  comando de admin) — comportamento já indefinido por design, não é o que
  foi pedido.
