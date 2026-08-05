# Tasks — finalizar atendimento não desliga mais o bot

## 1. Código

- [x] 1.1 `whatbot/admin.py`, ação `complete` (~linha 199): trocar
      `reativar_bot=False, schedule_resume_hours=AUTO_REACTIVATE_HOURS`
      por `reativar_bot=True` (sem `schedule_resume_hours`); atualizar a
      mensagem de confirmação (linha ~211) removendo "Bot reativa
      automaticamente em {AUTO_REACTIVATE_HOURS}h" — refletir que o bot já
      está ativo de novo
- [x] 1.2 `whatbot/admin.py`, finalização em lote (~linha 593): mesma troca
      (`reativar_bot=True`), mesma atualização de mensagem (~linha 602)
- [x] 1.3 `whatbot/queue.py`, `handle_staff_outgoing_message` (~linha 391):
      mesma troca; atualizar a notificação ao admin (~linha 401) removendo
      a menção ao prazo
- [x] 1.4 Conferir se `AUTO_REACTIVATE_HOURS` (`whatbot/config.py`) ainda é
      importado/usado em algum lugar depois das trocas acima — não sobrou
      nenhum uso fora da própria definição em `config.py`; imports agora
      não utilizados removidos de `admin.py` e `queue.py`, e a linha de
      ajuda em `admin.py` que citava o prazo também foi atualizada

## 2. Testes

- [x] 2.1 Teste cobrindo ação `complete`: após finalizar, contato fica com
      `ia_ativa=True` e `bot_resume_at=None` imediatamente (não só
      "eventualmente" via `process_auto_reactivations`)
- [x] 2.2 Mesma cobertura para finalização em lote
- [x] 2.3 Teste cobrindo `handle_staff_outgoing_message`: contato sai da
      fila com `ia_ativa=True` e `bot_resume_at=None` imediatamente
- [x] 2.4 Nenhum teste existente depende da mensagem "reativa
      automaticamente em Xh" para os três fluxos acima — suíte já passava
      sem exigir ajuste em asserts literais
- [x] 2.5 Suíte completa verde (`.venv/bin/python -m unittest discover -s
      tests -p 'test_*.py'` — 428 testes, OK)

## 3. OpenSpec

- [x] 3.1 Após validar os testes, mover este change para
      `openspec/changes/archive/` seguindo a convenção do projeto
