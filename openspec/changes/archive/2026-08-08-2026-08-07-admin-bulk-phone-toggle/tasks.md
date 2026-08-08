# Tasks — ativar/desativar bot por telefone (único/lista) + criar/renomear/excluir contato

## 1. Ativar/desativar por telefone (idempotente, único ou lista)

- [x] 1.1 `_REACTIVATE` em `whatbot/admin_nlu.py` ganha alternativa
      `ativa(?:r)?\s+(?:o\s+)?bot` (exige "bot" junto, não colide com
      "desativar" por fronteira de palavra) → Requirement "Admin ativa o
      bot com o verbo 'ativar'"
- [x] 1.2 `extract_phone_list_from_text` em `whatbot/contact_resolver.py`:
      sem vírgula → `None`; com vírgula → extrai telefone por segmento
      (reaproveita `extract_phone_from_text`), ignora segmento
      irreconhecível, dedupa preservando ordem
- [x] 1.3 `_toggle_bot_for_phones(phones, activate, db)` em
      `whatbot/admin.py`: por telefone, busca `get_contact_by_phone`; já
      no estado pedido → não muta; senão muta e registra → Requirement
      "Ativar/desativar por telefone é idempotente"
- [x] 1.4 `_try_bulk_phone_toggle` em `whatbot/admin.py`, chamado antes de
      `_resolve_reactivate`/`_resolve_pause` nos branches
      `"reactivate"`/`"pause"` de `handle_admin_message`: resolve 1 ou N
      telefones, monta a resposta (única preservando o texto atual; lista
      como resumo agrupado) → Requirement "Ativar/desativar uma lista de
      telefones"
- [x] 1.5 Remove o branch de telefone direto (sem checagem de estado) de
      `_resolve_pause`/`_resolve_reactivate` — fica coberto por 1.4

## 2. Criar contato ao não encontrar (telefone único)

- [x] 2.1 `_try_bulk_phone_toggle`, telefone único não encontrado: salva
      `admin_sessao` (`acao="confirmar_criacao"`) e pergunta o nome →
      Requirement "Oferecer criar contato ao não encontrar telefone único"
- [x] 2.2 `_try_pending_contact_creation` em `whatbot/admin.py`, checado em
      `handle_admin_message` antes de `_try_pending_disambiguation`:
      resposta de cancelamento (ou vazia/só espaços) não cria nada; texto
      que `parse_admin_intent` reconhece como comando também não é tomado
      como nome — a sessão pendente é abandonada e o comando segue seu
      próprio fluxo normal; qualquer outro texto vira o `push_name` do
      `create_contact`, já com o `ia_ativa` do pedido original (correção
      pós-review: bug em que um comando real enviado enquanto o prompt
      estava pendente virava `push_name` de um contato-lixo)
- [x] 2.3 Lista (2+ telefones) com número não encontrado NÃO dispara esse
      fluxo — só aparece na seção "Não encontrado" do resumo

## 3. Renomear contato

- [x] 3.1 Intenção `rename` em `whatbot/admin_nlu.py` — "renomeia X para
      Y" / "muda o nome do X para Y" / "troca o nome do X para Y"
- [x] 3.2 `_resolve_rename` em `whatbot/admin.py`: separa `query` em
      `(alvo, novo_nome)` no literal " para "; resolve alvo por telefone
      ou nome (com desambiguação, `new_name` sobrevive via `acao`
      codificada, mesmo truque de `_resolve_set_tipo_cliente`) →
      Requirement "Admin renomeia um contato"
- [x] 3.3 Branch `rename:` em `_execute_action` chama
      `db.update_contact_push_name`

## 4. Excluir contato (com confirmação)

- [x] 4.1 `Database.delete_contact(external_id, *, canal=None) -> bool`
      em `whatbot/db.py` (`DELETE FROM contatos ... RETURNING id`) +
      espelho em `tests/fakes.py::FakeDatabase`
- [x] 4.2 Intenção `delete_contact` em `whatbot/admin_nlu.py` — "apaga/
      exclui/deleta/remove o contato do X" (exige a palavra "contato")
- [x] 4.3 `_resolve_delete_contact` em `whatbot/admin.py`, mesma forma de
      `_resolve_mark_active_client`
- [x] 4.4 Branch `delete_contact` em `_execute_action` NÃO apaga direto —
      salva `admin_sessao` (`acao="confirmar_exclusao"`) e pede
      confirmação → Requirement "Excluir contato exige confirmação"
- [x] 4.5 `_try_pending_delete_confirmation` em `whatbot/admin.py`,
      checado antes de `_try_pending_disambiguation`: só "sim"/"s"/
      "confirmar"/"confirmo"/"yes" apaga; qualquer outra resposta cancela
      sem apagar

## 5. Ajuda e testes

- [x] 5.1 `_build_help_text` ganha exemplos dos 4 comandos novos/estendidos
- [x] 5.2 `TestAdminNlu`: `ativar` reconhecido como reactivate,
      `desativar` continua pause (regressão), `rename`/`delete_contact`
      reconhecidos
- [x] 5.3 `TestBulkPhoneToggleCommand`: telefone único idempotente (pause
      e reactivate), lista com estados mistos, número inexistente em
      lista, duplicata deduplicada, segmento não numérico
- [x] 5.4 `TestContactCreationFlow`: pergunta nome, cria no estado pedido,
      cancelamento com "não"
- [x] 5.5 `TestRenameCommand`: nome, telefone, desambiguação, uso
      incorreto (sem " para "), contato não encontrado
- [x] 5.6 `TestDeleteContactCommand`: pede confirmação sem apagar,
      confirma e apaga (`get_contact_by_phone` some depois), cancela sem
      apagar, desambiguação + confirmação
- [x] 5.7 Testes existentes de `TestPauseCommand` continuam verdes sem
      ajuste de texto (`test_phone_query_pauses_the_contact_directly`,
      `test_confirmation_message_suggests_a_command_that_actually_reactivates`)
- [x] 5.8 Suíte completa verde (`make test` / `pytest -q`)
