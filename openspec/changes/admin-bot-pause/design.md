# Design — admin pausa o bot fora da fila

## Decisão 1: reaproveitar `ia_ativa`, não criar campo novo

Alternativas consideradas:

1. **Novo campo `pausado_manualmente BOOLEAN`, independente de
   `ia_ativa`.** Rejeitada: criaria dois campos controlando a mesma coisa
   (se o bot responde ou não) e exigiria que `process_customer_message`
   (`whatbot/main.py`) checasse os dois em toda mensagem — mais estado
   para manter sincronizado sem benefício real, já que os dois casos
   (pausa por handover, pausa manual do admin) querem exatamente o mesmo
   efeito: o bot não responde até alguém religar.
2. **Reaproveitar `ia_ativa`, distinguir a causa por outro campo (ex.:
   `handover_motivo`).** Escolhida. `ia_ativa=FALSE` continua sendo "o bot
   não responde"; a causa (handover vs. pausa manual) não precisa de campo
   novo porque nenhum consumidor atual do sistema toma decisão diferente
   com base nisso — os dois casos usam o mesmo caminho de saída (`libera o
   bot`) e o mesmo early-return em `process_customer_message`.

## Decisão 2: pausa não seta `bot_resume_at`

`bot_resume_at` é o campo que `process_auto_reactivations()` usa para
saber quando reativar automaticamente um contato pausado por handover
(`AUTO_REACTIVATE_HOURS`, default 24h). Uma pausa manual do admin **não**
deve reativar sozinha depois de um prazo — é uma decisão operacional
explícita, não um "aguardando atendimento" com prazo natural. Não setar
`bot_resume_at` (deixando `NULL`) já garante isso sem precisar de nenhuma
lógica condicional nova em `process_auto_reactivations()`: o `WHERE
bot_resume_at <= now()` da sweep já ignora essas linhas.

## Decisão 3: `pausar_bot` por `external_id`/`canal`, não por `contact_id`

`update_contact_ia_active(contact_id, ia_ativa)` já existe e faria o
trabalho, mas exige que o chamador já tenha resolvido o `id` interno do
contato. `reativar_bot(phone, *, canal=None)` — o comando simétrico a este
— já resolve por `external_id`/`canal`, que é o dado que o admin realmente
fornece (telefone ou nome, nunca um id de banco). `pausar_bot` segue a
mesma assinatura por consistência: quem usa um dos dois comandos não
precisa lembrar que o outro tem uma convenção diferente.

## Decisão 4: capability `admin` nova, cobrindo só o requisito novo

`whatbot/admin.py` já implementa assumir/completar/reativar/listar fila
há tempo, mas nenhum desses requisitos foi capturado formalmente em
`openspec/specs/` — o módulo foi construído antes (ou à margem) do
processo de spec-delta usado pelos changes mais recentes deste
repositório. Este change não tenta documentar retroativamente todo esse
comportamento (isso seria um change à parte, só de documentação); cria a
capability `admin` com apenas o requisito novo introduzido aqui. Os
requisitos preexistentes ficam para um change de "captura retroativa" se e
quando isso for considerado valioso — não bloqueia nem é bloqueado por
este change.
