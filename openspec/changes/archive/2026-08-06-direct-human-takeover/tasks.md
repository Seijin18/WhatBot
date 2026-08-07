# Tasks — assumir atendimento direto

## 1. Persistência

- [x] 1.1 `Database.assumir_atendimento_direto(contact_id, *, motivo="assumido_via_painel",
      assumido_por=None, prioridade=0)` (`whatbot/db.py`) — mesma transição
      de `enroll_handover` + `assumido_por` na mesma escrita
      (→ Requirement "Assumir atendimento direto pela API administrativa")

## 2. API administrativa

- [x] 2.1 `POST /admin/conversas/{contact_id}/assumir` (`whatbot/ingress.py`),
      mesma autenticação bearer das demais rotas `/admin/*`
- [x] 2.2 Contato já em atendimento humano: resposta `ok`, sem erro
      (idempotente) — não reenrola nem sobrescreve `assumido_por` já setado
- [x] 2.3 Contato inexistente: 404

## 3. Testes

- [x] 3.1 `assumir_atendimento_direto`: contato com `ia_ativa=TRUE` vira
      `FALSE`, `handover_at` setado, `assumido_por` gravado na mesma chamada
- [x] 3.2 Rota `/admin/conversas/{id}/assumir`: fluxo feliz, idempotência
      (segunda chamada não é erro), 404 para contato inexistente, 401 sem
      token
- [x] 3.3 Suíte completa verde
