# Admin ativa/desativa o bot para 1 ou vários telefones, com criação/renomeação/exclusão de contato

## Why

O admin já pausa/reativa o bot para um contato via nome ou telefone
(`admin-bot-pause`), mas o caminho de telefone direto
(`extract_phone_from_text` em `_resolve_pause`/`_resolve_reactivate`) não
verifica o estado atual antes de mutar — repetir o mesmo comando sempre
executa `pausar_bot`/`reativar_bot` de novo e responde como se tivesse
mudado, mesmo quando o contato já estava no estado pedido. Só o caminho
por nome tem esse fallback idempotente hoje.

Além disso não existe forma de aplicar a mesma ação a **vários** telefones
de uma vez (só um contato por comando), nem de reconhecer "ativar" como
sinônimo de "reativar" (só "reativar" funciona).

Ao usar o comando, também não há o que fazer quando o telefone informado
não corresponde a nenhum contato — hoje só retorna "não encontrado". E não
existe comando de admin para renomear ou excluir um contato — mudanças que
hoje exigem mexer direto no banco.

## What Changes

- **Idempotência unificada por telefone**: novo helper
  `_toggle_bot_for_phones` que checa `contact.ia_ativa` antes de chamar
  `pausar_bot`/`reativar_bot` — se já está no estado pedido, não muta,
  só informa. Substitui o branch de telefone direto hoje presente (sem
  essa checagem) em `_resolve_pause`/`_resolve_reactivate`.
- **Lista de telefones separados por vírgula**: nova função
  `extract_phone_list_from_text` (`whatbot/contact_resolver.py`) e
  orquestração `_try_bulk_phone_toggle` — um comando de ativar/desativar
  aceita 1 telefone ou uma lista, respondendo com um resumo agrupado
  (mudou / já estava no estado / não encontrado / não reconhecido).
- **"Ativar" como sinônimo de "reativar"**: nova alternativa em
  `_REACTIVATE` (`whatbot/admin_nlu.py`), exigindo a palavra "bot" junto
  para não colidir com outros gatilhos (inclusive "desativar", já
  garantido por fronteira de palavra).
- **Criar contato ao não encontrar (só telefone único)**: quando o
  telefone de um comando de ativar/desativar não corresponde a nenhum
  contato, o bot oferece cadastrá-lo, pergunta o nome na próxima mensagem
  e cria o contato já no estado (ativo/pausado) pedido originalmente. Em
  lista (2+ números), não oferece — só reporta como "não encontrado".
- **Renomear contato**: nova intenção `rename` — "renomeia o X para
  Y"/"muda o nome do X para Y" — resolve o alvo por nome (com
  desambiguação) ou telefone, e chama
  `Database.update_contact_push_name` (já existente).
- **Excluir contato**: nova intenção `delete_contact` — "apaga o contato
  do X"/"exclui o contato do X" — resolve o alvo, mas **exige
  confirmação explícita** antes de apagar (`Database.delete_contact`,
  novo — `DELETE FROM contatos`, que via `ON DELETE CASCADE` também
  remove mensagens e mídia do contato; irreversível).
- Sem migration — reaproveita `contatos.ia_ativa`,
  `Database.pausar_bot`/`reativar_bot`/`get_contact_by_phone`/
  `create_contact`/`update_contact_push_name`/`search_contacts_for_admin`.
  Único método novo no banco é `delete_contact`.

## Impact

- Specs afetadas: `admin` (capability existente, `openspec/specs/admin/`)
  — estende os requirements de pause/reactivate e adiciona os de
  criação/renomeação/exclusão de contato.
- Código: `whatbot/admin_nlu.py`, `whatbot/admin.py`,
  `whatbot/contact_resolver.py`, `whatbot/db.py`, `tests/fakes.py`,
  `tests/test_admin_organic.py`.
- Sem impacto em `whatbot/main.py`, canais, ou schema (nenhuma migration).
