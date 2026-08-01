# Design — endurecer a camada de canais

## Contexto

Auditoria do commit `18ce004` (Fase 1) contra `docs/INSTAGRAM_INTEGRATION_PLAN.md`.
O contrato `ChannelClient` e o dataclass `InboundMessage` saíram idênticos ao que
o plano especifica em §5, e o invariante de roteamento está correto e
centralizado: todo tráfego de admin passa por `notify_admin` → `send_admin` →
`send_admin_text`, que fixa `canal=self.admin_channel`. O que falta é cobertura e
o acabamento de sete pontas soltas.

## Decisão 1 — `FakeDatabase` em memória, não Postgres de teste

`whatbot/db.py` usa SQL cru de Postgres (`JSONB`, `ON CONFLICT`, `now()`), sem
caminho sqlite. As opções eram um Postgres de teste via docker-compose ou um fake
em memória.

Escolhido o **fake em memória**: roda em segundos, sem Docker, e cobre exatamente
o que precisa ser coberto agora — as *chamadas* que os módulos de domínio fazem
ao banco, que é onde o rename `whatsapp` → `router` passa. O que um fake não pega
é o SQL em si, e o SQL não mudou nesta fase.

A integração real com Postgres fica para a Fase 2, onde o que precisa ser provado
é a migração aditiva (nenhuma linha perdida, todo contato terminando com
`canal='whatsapp'` e `external_id = phone`) — aí um fake não serviria.

O fake espelha a superfície pública de `Database` e devolve os mesmos dataclasses
(`Contact`, `WaitingContact`, `MessageRecord`) que o código de produção já espera,
então nenhum módulo precisa saber que está falando com um fake.

## Decisão 2 — Testar na costura do `main()`, não abaixo dela

Os testes E2E injetam `_db`, `_router` e `_llm` diretamente nos globais do módulo
e neutralizam `_init_infra`, entrando pelo `main(payload)` com payload cru da
Evolution API. É a mesma porta que `windmill/f/whatbot/handler.py` usa em
produção, então o teste cobre o caminho real, incluindo `normalize_payload`,
`parse_evolution_payload`, roteamento de admin e o despacho final.

Testar mais abaixo (chamando `process_customer_message` direto) pularia
justamente as costuras que a Fase 1 mexeu.

## Decisão 3 — Corrigir os sete defeitos agora

| # | Defeito | Correção |
|---|---|---|
| D1 | `run_admin_simulation` chama `process_customer_message` sem `canal` | Propagar o canal. Hoje é correto por acidente (admin é WhatsApp); com Instagram, simular um contato mandaria o IGSID pelo cliente WhatsApp. |
| D2 | `normalize_channel` aceita qualquer string; `SUPPORTED_CHANNELS` nunca valida nada | Validar na borda. Um `canal` desconhecido deve falhar onde entra, não lá no fundo do envio. |
| D3 | Protocolo declara `to`; `EvolutionApiClient.send_text` usa `to_phone` | Renomear para `to`. Funciona hoje só porque toda chamada é posicional — o `InstagramClient` da Fase 3 herdaria a ambiguidade. |
| D4 | `ChannelError` / `retryable` definidos e nunca lançados | Cliente passa a embrulhar falha de transporte em `ChannelError`. A Fase 3 precisa dessa taxonomia para tratar janela de 24h e rate limit; deixá-la decorativa agora significa refazer o tratamento de erro depois. |
| D5 | `send_to_contact` despacha por `isinstance(ChannelRouter)`, `send_admin` por `hasattr` | Unificar em `hasattr`. A assimetria faz um router duck-typed perder `canal` e `human_agent` **em silêncio** — a pior classe de bug de roteamento. |
| D6 | `InboundMessage` não é construído por nenhum código de produção; `to_payload()` compara `canal` sem normalizar | `webhook.py` passa a construir `InboundMessage` e emitir `.to_payload()`. Elimina a costura morta e deixa a Fase 3 com um formato de entrada só para implementar, em vez de dois paralelos. |
| D7 | Import morto de `DEFAULT_CHANNEL`; log "Erro ao enviar via Evolution API" em caminho agnóstico | Limpeza. |

Cada correção entra junto com o teste que a pega. D1 e D6 só são demonstráveis
com o harness — é por isso que o harness vem antes.

## Decisão 4 — `tests/fakes.py`, não `conftest.py`

A suíte é `unittest` puro e `make test` usa `unittest discover`. Um `conftest.py`
só funcionaria sob pytest e criaria dois modos de execução divergentes. Um módulo
importável serve aos dois.

## Riscos

O `FakeDatabase` pode divergir do `Database` real com o tempo — um teste passa
contra um comportamento que o Postgres não tem. Mitigação: o fake espelha
assinaturas e dataclasses, e a Fase 2 acrescenta o teste de migração contra
Postgres real, que é onde a divergência apareceria.
