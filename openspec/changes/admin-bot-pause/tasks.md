# Tasks — admin pausa o bot fora da fila

## 1. Camada de dados

- [ ] 1.1 `Database.pausar_bot(external_id: str, *, canal: str | None =
      None) -> bool` em `whatbot/db.py`, espelhando `reativar_bot`: resolve
      o contato por `(canal, external_id)` (default WhatsApp quando `canal`
      omitido, mesma convenção de `reativar_bot`), faz `UPDATE contatos SET
      ia_ativa = FALSE WHERE ...` e retorna `True`/`False` conforme achou
      o contato (→ Requirement "Admin pausa o bot de um contato específico")

## 2. Comando de admin

- [ ] 2.1 Nova intenção `pause` em `whatbot/admin_nlu.py` — regex cobrindo
      "pausar/pausa o bot", "desativar/desativa o bot", "desligar/desliga
      o bot" seguido do alvo; `_strip_intent_prefix` reaproveitado igual
      às intenções existentes
- [ ] 2.2 `_resolve_pause` em `whatbot/admin.py`: por telefone direto
      (`extract_phone_from_text`) resolve sem ambiguidade; por nome,
      `search_contacts_for_admin` filtrando só contatos com
      `ia_ativa=True`; múltiplos resultados desambiguam via
      `db.save_admin_sessao` (mesmo padrão de `_resolve_reactivate`)
- [ ] 2.3 Branch `"pause"` em `_execute_action` chamando `db.pausar_bot` e
      confirmando ("🔕 Bot pausado para *{label}*. Envie *libera o bot
      para {label}* para retomar.")
- [ ] 2.4 Contato já pausado (`ia_ativa=False`) não aparece como opção em
      `_resolve_pause` — resposta ao admin indica que já está pausado, sem
      erro

## 3. Testes

- [ ] 3.1 `pausar_bot` desativa `ia_ativa` de um contato existente e
      retorna `True`; retorna `False` para contato inexistente
- [ ] 3.2 Comando "pausa o bot para o João" com contato único pausa direto
- [ ] 3.3 Nome ambíguo desambigua antes de pausar, mesmo formato de
      `reactivate`
- [ ] 3.4 Contato pausado por este comando NÃO é reativado por
      `process_auto_reactivations()` (não tem `bot_resume_at` setado) —
      só volta via "libera o bot" explícito
- [ ] 3.5 Comando "libera o bot para o João" (já existente) reativa um
      contato pausado por este novo comando, sem mudança nenhuma no
      comando de reativação
- [ ] 3.6 Suíte completa verde (`make test` / `pytest -q`)
