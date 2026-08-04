"""Synthetic knowledge-base fixtures for tests.

Tests must never depend on `knowledge/associacao.md` (the real, deployable
business content) — that file changes whenever the deployed business
changes, and several tests broke exactly that way when it was swapped from
a sports-class association to a made-to-order product catalog (see
docs/REVISAO_CAMADA_CONVERSACIONAL.md, P2.4). These two fixtures cover the
two KB *shapes* the code is meant to support:

- `CLASS_SCHEDULE_KB`: a business with a `## Modalidades` section (class
  schedules, per-student monthly/semester plans, an "aula experimental"
  booking flow) — exercises `experimental_slots`, day-of-week validation,
  and the monthly/semester price-plan `ClaimValidator` rules.
- `CATALOG_KB`: a business with no `## Modalidades` section (a flat product
  catalog under "Preços", made-to-order, no class schedule) — exercises
  every "no modalidades" fallback path fixed in this session (intent
  routing, FAQ matching, reply composition).

Use `load_class_schedule_kb()` / `load_catalog_kb()` in `setUp` — they load
straight into the process-wide `KnowledgeStore` singleton via
`reload_from_text`, exactly like `whatbot.tools`/`whatbot.reply_composer`
read it in production, with no file I/O.
"""

from __future__ import annotations

from whatbot.knowledge import KnowledgeStore, get_knowledge_store
from whatbot.knowledge_facts import reset_knowledge_facts_cache

CLASS_SCHEDULE_KB = """# Associação Desportiva e Cultural

## Sobre a associação

Agradecemos o seu contato! Somos a associação Kannon Do, uma associação desportiva e cultural com aulas de judô e yoga. Para agendar aula experimental ou matrícula, entre em contato pelo atendimento ou responda com os dados solicitados na seção de aula experimental.

## Endereço e contato

- WhatsApp: atendimento pelo número deste canal
- Endereço Físico: Av. Teste, 350 - Bairro Teste, Cidade Teste - TS, 00000-000

## Modalidades

### Judô infantil

- Horários: Terças e quintas, das 18:30 às 19:30
- Frequência: Aula 2x por semana (terça e quinta-feira)
- Público-alvo: Crianças de 6 a 12 anos
- Preço mensal: R$ 150 (1 aluno)
- Preço semestral: R$ 840 (1 aluno)
- Desconto: disponível para o 2º integrante da mesma família
- Observações: Aconselhável comparecer com roupa confortável, chinelo e garrafinha de água. O chinelo é necessário para a aula de judô.

### Judô adulto

- Horários: Terças e quintas, das 20:00 às 21:30
- Frequência: Aula 2x por semana (terça e quinta-feira)
- Público-alvo: A partir de 12 anos
- Preço mensal: R$ 150 (1 aluno)
- Preço semestral: R$ 840 (1 aluno)
- Desconto: disponível para o 2º integrante da mesma família
- Observações: Aconselhável comparecer com roupa confortável, chinelo e garrafinha de água. O chinelo é necessário para a aula de judô.

### Yoga

- Horários: Quartas-feiras, das 19:30 às 20:30
- Frequência: Aula 1x por semana (quarta-feira)
- Público-alvo: Todas as idades
- Preço mensal: R$ 150 (1 aluno)
- Preço semestral: R$ 840 (1 aluno)
- Desconto: disponível para o 2º integrante da mesma família
- Observações: Aconselhável comparecer com roupa confortável e garrafinha de água. Chinelo não é necessário para yoga.

## Preços

### Judô (infantil e adulto)

- Aula 2x por semana (terça e quinta-feira)
- Plano mensal: R$ 150 (1 aluno)
- Plano semestral: R$ 840 (1 aluno)
- Desconto para o 2º integrante da mesma família

### Yoga

- Aula 1x por semana (quarta-feira)
- Plano mensal: R$ 150 (1 aluno)
- Plano semestral: R$ 840 (1 aluno)
- Desconto para o 2º integrante da mesma família

## Matrícula e pagamentos

- Aula experimental: disponível para judô e yoga — preencher nome, idade, celular/telefone e dia desejado
- Dias disponíveis para aula experimental de judô: quinta-feira (5ªf)
- Dias disponíveis para aula experimental de yoga: quarta-feira (4ªf)
- Planos: mensal ou semestral (valores na seção Preços e em cada modalidade)
- Desconto familiar: consulte o atendimento para valores do 2º integrante da mesma família

## FAQ

### O que devo levar para a aula?

Roupa confortável e garrafinha de água são recomendados para todas as modalidades. Para judô, traga também chinelo — é necessário. Para yoga, chinelo não é necessário.

### Quais são os horários do judô?

Judô infantil (6 a 12 anos): terças e quintas, das 18:30 às 19:30. Judô adulto (acima de 12 anos): terças e quintas, das 20:00 às 21:30.

### Quais são os horários do yoga?

Yoga: quartas-feiras, das 19:30 às 20:30.

### Como agendo uma aula experimental?

Informe os seguintes dados: NOME, IDADE, CEL/TEL e o DIA desejado — quinta-feira (5ªf) para JUDÔ ou quarta-feira (4ªf) para YOGA.

### Preciso de chinelo?

Sim, para a aula de judô. Para yoga, chinelo não é necessário.

### Quanto custam as aulas?

Judô e yoga: plano mensal R$ 150 (1 aluno) ou plano semestral R$ 840 (1 aluno). Há desconto para o 2º integrante da mesma família.
"""

CATALOG_KB = """# Ateliê Fictício de Teste

## Sobre a associação

Somos o Ateliê Fictício, especializado em produtos artesanais personalizados feitos sob encomenda.

## Endereço e contato

- WhatsApp: atendimento pelo número deste canal
- Instagram: @ateliefake
- Não trabalhamos com retirada no local — todos os pedidos são enviados pelos Correios

## Preços

Produto personalizado:

- Tamanho pequeno: R$ 39,90
- Tamanho grande: R$ 49,90

Frete: calculado por pedido conforme a distância até o destino.

## Matrícula e pagamentos

Como encomendar um produto personalizado:

- Envie fotos de referência
- Confirme o tamanho desejado

Prazo de produção: até 5 dias úteis após a confirmação do pedido.

Formas de pagamento:

- Pix
- Cartão via Mercado Pago

## FAQ

### Quanto custa um produto personalizado?

Depende do tamanho: pequeno R$ 39,90 ou grande R$ 49,90.

### Vocês entregam em qualquer lugar?

Sim, enviamos pelos Correios para qualquer endereço.

### Como faço para pagar?

Pix ou cartão via Mercado Pago.

### Posso retirar no local?

Não, todos os pedidos são enviados pelos Correios.
"""


def load_class_schedule_kb() -> KnowledgeStore:
    store = get_knowledge_store()
    store.reload_from_text(CLASS_SCHEDULE_KB)
    reset_knowledge_facts_cache()
    return store


def load_catalog_kb() -> KnowledgeStore:
    store = get_knowledge_store()
    store.reload_from_text(CATALOG_KB)
    reset_knowledge_facts_cache()
    return store
