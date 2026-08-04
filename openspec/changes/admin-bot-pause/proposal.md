# Admin pausa o bot para um contato fora da fila de atendimento

## Why

`contatos.ia_ativa` já existe e já controla se o bot responde a um
contato, mas hoje só é desligado pelo fluxo de handover
(`enroll_handover`, disparado quando o cliente pede atendimento humano ou o
admin assume/completa um item da fila). Não existe forma de um admin
desativar o bot para um contato que **não** está na fila — por exemplo, um
contato que o admin decide atender por fora do bot sem que o cliente tenha
pedido isso explicitamente. Hoje a única forma de fazer isso seria mexer
direto no banco.

## What Changes

- Nenhuma mudança de schema — reaproveita `contatos.ia_ativa`, já
  existente, e o método `Database.update_contact_ia_active()`, já
  existente.
- Novo método `Database.pausar_bot(external_id: str, *, canal: str | None
  = None) -> bool`, espelhando a assinatura de `reativar_bot(phone, *,
  canal=None)` (já existente em `whatbot/db.py`) — por consistência de API
  entre as duas pontas da mesma operação, em vez de reaproveitar o setter
  por `contact_id` (`update_contact_ia_active`), que exige já ter
  resolvido o `id` interno.
- Nova intenção `pause` em `whatbot/admin_nlu.py` (ex.: "pausa o bot para
  X", "desativa o bot para X", "desliga o bot para X") — regex distinto de
  `_REACTIVATE` para não colidir com os verbos já usados por "libera o
  bot"/"bot pode voltar".
- Novo resolvedor `_resolve_pause` em `whatbot/admin.py`, espelhando
  `_resolve_reactivate`: busca por telefone (`extract_phone_from_text`) ou
  por nome (`search_contacts_for_admin`), mas filtrando contatos com
  `ia_ativa=True` (o inverso do filtro que `_resolve_reactivate` já usa
  para achar contatos desativados) — só oferece como alvo um contato que
  ainda pode ser pausado.
- Novo branch `"pause"` em `_execute_action`, chamando `db.pausar_bot` e
  confirmando ao admin.

## Impact

- Specs afetadas: `admin` (capability nova — primeira spec formal para o
  comportamento de `whatbot/admin.py`, que hoje já existe em código mas
  nunca teve requisitos capturados em `openspec/specs/`)
- Código alterado: `whatbot/db.py`, `whatbot/admin_nlu.py`, `whatbot/admin.py`
- Testes alterados: `tests/test_admin_organic.py`
- Bloqueado por: nenhum
- Não depende de `contact-segmentation-b2b-b2c` nem de
  `campaign-csv-broadcast`

## Fora de escopo (decisão explícita)

- Pausa com prazo automático de retomada (como o `AUTO_REACTIVATE_HOURS`
  do fluxo de handover) — este comando é uma pausa manual e indefinida,
  simétrica ao "libera o bot" já existente; combinar as duas semânticas
  (pausa manual vs. pausa temporária de handover) no mesmo prazo
  automático misturaria dois conceitos distintos sem necessidade real
  identificada.
- Comando de retomada novo — o comando "libera o bot"/"bot pode voltar"
  (`reactivate`, já existente) já cobre a retomada, tanto para contatos
  pausados por handover quanto por este comando novo, porque os dois usam
  o mesmo campo `ia_ativa`.
