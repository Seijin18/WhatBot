# Plano de Integração — Instagram DMs no WhatBot

**Repositório:** `Seijin18/WhatBot` · commit base `db9db6a` (02/06/2026)
**Versão do plano:** 1.1 — 28/07/2026
**Objetivo:** habilitar o bot a receber e responder Direct Messages do Instagram, reaproveitando integralmente a camada de IA, base de conhecimento, fila e handover existentes, sem regressão no canal WhatsApp.

---

## 1. Decisões de arquitetura

Quatro decisões estruturam o resto do documento.

**Decisão 1 — Refatorar para multicanal, não bifurcar o projeto.** A alternativa seria subir uma segunda instância do WhatBot só para Instagram, o que duplicaria banco, base de conhecimento e fila, e daria à secretaria duas filas separadas para gerenciar. O custo de refatorar a identidade do contato uma única vez é menor que o custo permanente de manter dois sistemas.

**Decisão 2 — Usar a "Instagram API with Instagram Login" (host `graph.instagram.com`), não a variante com Facebook Login.** A variante com Instagram Login não exige Página do Facebook vinculada e, segundo a documentação da Meta, não exige App Review nem verificação de negócio quando o app atende apenas contas que você mesmo possui ou administra (Standard Access). Como a associação vai automatizar a própria conta, isso remove o maior risco de cronograma.

**Decisão 3 — Identidade do contato passa a ser o par `(canal, external_id)`.** Cada pessoa vira um contato por canal; WhatsApp e Instagram não são unificados numa mesma pessoa. É a opção de menor risco: a migração é aditiva, o histórico atual é integralmente preservado como `canal='whatsapp'`, e nenhuma lógica de vinculação de identidade precisa ser inventada. Unificar pessoa entre canais fica como evolução futura, se e quando houver necessidade real.

**Decisão 4 — Serviço de ingestão HTTP dedicado, em vez de apontar o webhook da Meta direto para o Windmill.** A Meta exige handshake `GET` de verificação, validação de assinatura `X-Hub-Signature-256` sobre o corpo bruto, e resposta `200` em menos de 20 segundos sob pena de reentrega. O fluxo atual do Windmill é síncrono e processa a mensagem inteira (incluindo a chamada ao Gemini) antes de responder — numa resposta lenta do modelo, isso geraria reentrega e resposta duplicada ao cliente.

---

## 2. Situação atual e pontos de acoplamento

O bot hoje é uma cadeia linear: Evolution API recebe a mensagem do WhatsApp → dispara webhook → Windmill chama `whatbot.main.main(payload)` → `parse_evolution_payload` normaliza → busca/cria contato no Postgres pelo telefone → monta prompt com `knowledge/associacao.md` → Gemini (fallback Ollama) → validação de grounding → envia a resposta pela Evolution API. Em paralelo roda a fila: o handover desliga a IA para aquele contato (`ia_ativa=false`), enfileira, notifica a secretaria por WhatsApp e aceita comandos administrativos em linguagem natural.

A parte inteligente é agnóstica de canal e não muda: `llm.py`, `gemini_client.py`, `ollama_client.py`, `knowledge.py`, `knowledge_facts.py`, `prompt_builder.py`, `intent_router.py`, `grounding.py`, `claim_validator.py`, `reply_composer.py`, `session_state.py`, `fallback.py`, `priority.py`, `booking_flow.py` e a maior parte de `domain.py`. São cerca de 2.400 das 5.400 linhas do pacote, reaproveitadas integralmente.

O acoplamento a WhatsApp/telefone concentra-se nestes pontos:

| Arquivo | Acoplamento | Impacto |
|---|---|---|
| `whatbot/db.py` | `contatos.phone VARCHAR(32) UNIQUE NOT NULL` é a chave de identidade; `handover_historico.phone`; dataclasses `Contact` e `WaitingContact`; ~15 métodos com assinatura `(phone: str)` | Alto |
| `whatbot/main.py` | Cliente único `_whatsapp` global; `process_customer_message(phone, ...)`; `_whatsapp.send_text` chamado direto em 6 pontos | Alto |
| `whatbot/whatsapp.py` | `EvolutionApiClient` é a única implementação de envio | Médio |
| `whatbot/webhook.py` | `parse_evolution_payload` / `parse_outgoing_staff_message` entendem só o formato Baileys | Médio |
| `whatbot/queue.py` | `normalize_phone()` aplica `re.sub(r"\D", "")`; `is_admin_phone()`; a fila imprime `contact.phone` | Médio — IGSIDs são numéricos e passariam pelo filtro silenciosamente |
| `whatbot/contact_resolver.py` | `extract_phone_from_text` usa regex `\d{10,15}` | Médio — um IGSID de 17 dígitos casaria parcialmente e resolveria o contato errado |
| `whatbot/admin.py` | Resolução de contato e resposta ao admin assumem telefone | Médio |
| `whatbot/message_log.py` | `log_inbound`/`log_outbound`/`log_llm_turn` recebem `phone` posicional | Baixo |
| `whatbot/config.py` | `TEST_PHONES`, `ADMIN_NOTIFY_PHONES`, `should_respond_to_customer` | Baixo |

O que impede o Instagram hoje, objetivamente: a Evolution API v2 (versão `2.3.7` no `docker-compose.yml`) suporta apenas WhatsApp — Instagram e Messenger constam como roadmap, não como recurso disponível. Não existe caminho de configuração; é desenvolvimento.

---

## 3. Pré-requisitos externos (Meta) — Fase 0

Itens que não dependem de código e devem começar imediatamente, em paralelo ao desenvolvimento, porque envolvem terceiros.

**Conta.** O Instagram da associação precisa ser conta profissional (Business ou Creator). Em Configurações → Mensagens e respostas de história → Ferramentas conectadas, a permissão de acesso a mensagens precisa estar ativada. Sem isso os webhooks simplesmente não são entregues, e esse é o erro silencioso mais comum na integração.

**App na Meta.** Criar app em `developers.facebook.com`, tipo Business, adicionar o produto Instagram na configuração "Instagram API with Instagram Login". Guardar App ID e App Secret.

**Escopos.** `instagram_business_basic` e `instagram_business_manage_messages`. Os escopos antigos sem prefixo (`business_basic`, `business_manage_messages`) foram descontinuados em 27/01/2025 e não devem ser usados.

**Token.** Autorização em `https://www.instagram.com/oauth/authorize` → código válido por 1 hora e uso único → troca por token curto em `https://api.instagram.com/oauth/access_token` → troca por token longo em `https://graph.instagram.com/access_token`, válido por 60 dias → renovação em `https://graph.instagram.com/refresh_access_token`. A renovação de 60 em 60 dias é obrigatória e precisa ser automatizada; é a principal causa de queda de integrações Instagram em produção.

**Webhook.** Endpoint HTTPS público com certificado válido, inscrito no campo `messages` (opcionalmente também `messaging_postbacks`, `messaging_seen`, `messaging_reactions`). A inscrição da conta é feita via `POST https://graph.instagram.com/v23.0/me/subscribed_apps?subscribed_fields=messages`. A infraestrutura para isso é tratada na seção 4.

**App Review.** Em Standard Access, atendendo apenas a própria conta, a expectativa é não ser necessário. Ainda assim há um checkpoint na Fase 7 para confirmar em ambiente real; caso a Meta exija review, o prazo típico é de 1 a 4 semanas e o projeto continua entregável em modo desenvolvedor (até 25 testadores) enquanto tramita.

**Regras de uso.** A API não permite abordagem fria. Resposta livre apenas dentro de 24 horas após a última mensagem do usuário; fora disso, somente mensagens com a tag `HUMAN_AGENT`, por até 7 dias, e exclusivamente para atendimento humano. Isso tem consequência direta de produto, tratada na Fase 5.

---

## 4. Infraestrutura: expor o webhook em HTTPS

Esta seção existe porque o stack hoje roda inteiramente local, e **nada nele precisa receber conexões vindas da internet**. O WhatsApp funciona porque a Evolution API abre uma conexão de saída para o WhatsApp Web; o webhook dela é interno, de container para container. O Instagram inverte isso: a Meta precisa alcançar o seu serviço. É a primeira dependência de entrada do projeto e, na prática, o item de infraestrutura mais subestimado dessa integração.

Três exigências da Meta condicionam a escolha: a URL precisa ser **HTTPS com certificado válido** (autoassinado é rejeitado), precisa ser **estável** (mudou a URL, a inscrição do webhook quebra e precisa ser refeita) e precisa estar **disponível quando a mensagem chega** — a Meta reentrega em caso de falha, mas não indefinidamente, e mensagem perdida é lead perdido.

### Opções

**A. Cloudflare Tunnel + domínio próprio.** O `cloudflared` roda como container ao lado do stack e abre uma conexão de saída para a Cloudflare; nenhuma porta é aberta no roteador e o IP residencial não é exposto. A Cloudflare emite e renova o certificado automaticamente. Funciona atrás de CGNAT, que é o caso da maioria das operadoras brasileiras em conexões residenciais. Exige um domínio com nameservers na Cloudflare (plano gratuito serve). Custo: apenas o domínio, algo entre R$ 40 e R$ 60 por ano num `.com.br`.

Importante: os "quick tunnels" gratuitos com URL `trycloudflare.com` **não servem**, porque a URL muda a cada reinício e a inscrição do webhook quebra junto.

**B. VPS + Caddy (reverse proxy com TLS automático).** Uma VPS pequena (1 vCPU / 2 GB) hospeda o stack ou ao menos o serviço de ingestão, com Caddy emitindo certificado Let's Encrypt automaticamente. Custo típico entre R$ 25 e R$ 45 por mês. Ganho real: disponibilidade 24/7 sem depender de a máquina de casa estar ligada.

**C. ngrok com domínio estático.** O plano gratuito oferece um domínio estático por conta, o que atende o requisito de URL fixa. Serve bem para desenvolvimento e homologação, mas tem limites de conexão e é uma ferramenta de desenvolvimento — não é recomendável como solução permanente.

### Recomendação

Para **desenvolvimento e homologação**, opção C (ngrok com domínio estático) ou um Cloudflare Tunnel apontando para um subdomínio de homologação. É rápido e descartável.

Para **produção**, a decisão depende de uma pergunta operacional, não técnica: a máquina que roda o stack fica ligada 24 horas por dia, com internet estável? Se sim, a opção A resolve com custo quase zero e boa segurança. Se não — se é um desktop que dorme, reinicia ou fica sujeito a queda de energia — a opção B é a escolha sóbria, porque cada hora offline é DM não respondida.

O plano assume **A para homologação e produção inicial**, com migração para B prevista como item de acompanhamento caso a taxa de indisponibilidade se mostre relevante nos primeiros 30 dias.

### Regras de segurança da exposição

Expor apenas a rota `/webhook/instagram` do serviço de ingestão. **Windmill (8000), Evolution API (8080), Postgres (5432) e Redis (6379) jamais devem ficar acessíveis pela internet** — hoje são portas publicadas no compose para uso local, e o túnel não deve alcançá-las. O serviço de ingestão rejeita qualquer requisição sem assinatura `X-Hub-Signature-256` válida, o que na prática já descarta todo tráfego que não venha da Meta. Convém ainda aplicar limitação de taxa na borda (Cloudflare permite isso no plano gratuito) e manter o `IG_WEBHOOK_VERIFY_TOKEN` com pelo menos 32 caracteres aleatórios.

### Entregáveis da fase

Serviço `cloudflared` no `docker-compose.yml` sob perfil próprio; arquivo de configuração do túnel mapeando `webhook.seudominio.com.br` → `http://whatbot-ingress:8090`; documentação do procedimento em `DEPLOYMENT.md`; e um teste de fumaça (`curl` externo ao endpoint de verificação) que confirma certificado válido e resposta correta antes de registrar o webhook na Meta.

*Esforço estimado:* 1,5 dia, mais o tempo de propagação de DNS.

---

## 5. Arquitetura alvo

```
                    ┌──────────────────────────────────────────┐
   WhatsApp ────────► Evolution API ──► webhook interno ──┐    │
                    └────────────────────────────────────┼────┤
                                                          ▼    │
  Instagram ──► Meta ──► Cloudflare Tunnel ──► whatbot-ingress │
              webhook      (HTTPS, TLS)        FastAPI :8090   │
                                               GET verify      │
                                               POST + HMAC     │
                                               ACK 200 <20s    │
                                                          ▼    │
                                          ┌────────────────────┴─┐
                                          │  whatbot.main.main() │
                                          │  (núcleo inalterado) │
                                          └──────────┬───────────┘
                                                     ▼
                                          ┌──────────────────────┐
                                          │    ChannelRouter     │
                                          │ resolve o cliente    │
                                          │ por contact.canal    │
                                          └───┬──────────────┬───┘
                                              ▼              ▼
                                     EvolutionClient   InstagramClient
                                       (WhatsApp)         (IG DMs)
```

O ponto central é o `ChannelRouter`: em vez de um `_whatsapp` global, `main.py` resolve o cliente de saída a partir do canal do contato. As notificações para a secretaria continuam sempre pelo WhatsApp, independentemente do canal de origem do cliente — a secretaria não muda de ferramenta de trabalho.

Interface comum (`whatbot/channels/base.py`):

```python
class ChannelClient(Protocol):
    canal: str  # "whatsapp" | "instagram"
    def send_text(self, to: str, text: str, *, source: str = "bot",
                  contact_id: int | None = None, simulated: bool = False,
                  human_agent: bool = False) -> dict: ...

@dataclass
class InboundMessage:
    canal: str
    external_id: str        # telefone (WA) ou IGSID (IG)
    text: str
    display_name: str | None
    message_id: str | None
    is_echo: bool = False   # equivalente ao fromMe do WhatsApp
    raw: dict | None = None
```

O parâmetro `human_agent` é ignorado pelo cliente WhatsApp e, no Instagram, adiciona `messaging_type: MESSAGE_TAG` com `tag: HUMAN_AGENT`.

---

## 6. Migração de banco de dados

A identidade do contato deixa de ser o telefone e passa a ser `(canal, external_id)`. A coluna `phone` é preservada para não quebrar histórico e relatórios, mas deixa de ser chave. A migração é aditiva e idempotente, no mesmo estilo do `ensure_schema()` atual.

```sql
-- contatos: identidade multicanal
ALTER TABLE contatos ADD COLUMN IF NOT EXISTS canal VARCHAR(16) NOT NULL DEFAULT 'whatsapp';
ALTER TABLE contatos ADD COLUMN IF NOT EXISTS external_id VARCHAR(64);
UPDATE contatos SET external_id = phone WHERE external_id IS NULL;
ALTER TABLE contatos ALTER COLUMN external_id SET NOT NULL;
ALTER TABLE contatos ALTER COLUMN phone DROP NOT NULL;
ALTER TABLE contatos DROP CONSTRAINT IF EXISTS contatos_phone_key;
CREATE UNIQUE INDEX IF NOT EXISTS contatos_canal_external_key
    ON contatos (canal, external_id);

-- janela de 24h do Instagram e identificação visual
ALTER TABLE contatos ADD COLUMN IF NOT EXISTS last_inbound_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE contatos ADD COLUMN IF NOT EXISTS handle VARCHAR(64);   -- @username no IG

-- histórico
ALTER TABLE handover_historico ADD COLUMN IF NOT EXISTS canal VARCHAR(16) NOT NULL DEFAULT 'whatsapp';
ALTER TABLE handover_historico ADD COLUMN IF NOT EXISTS external_id VARCHAR(64);
UPDATE handover_historico SET external_id = phone WHERE external_id IS NULL;

-- credenciais de canal (token longo do Instagram e controle de renovação)
CREATE TABLE IF NOT EXISTS canal_credenciais (
    canal VARCHAR(16) PRIMARY KEY,
    account_id VARCHAR(64),
    access_token TEXT NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    refreshed_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- idempotência de webhook (a Meta reentrega eventos)
CREATE TABLE IF NOT EXISTS webhook_eventos (
    canal VARCHAR(16) NOT NULL,
    message_id VARCHAR(128) NOT NULL,
    received_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (canal, message_id)
);
CREATE INDEX IF NOT EXISTS webhook_eventos_received_idx ON webhook_eventos (received_at);
```

Contatos WhatsApp existentes continuam funcionando sem intervenção: recebem `canal='whatsapp'` e `external_id = phone`. Toda consulta que hoje faz `WHERE phone = %s` passa a fazer `WHERE canal = %s AND external_id = %s`, com camada de compatibilidade que assume `canal='whatsapp'` quando não informado, mantendo os chamadores antigos funcionando durante a transição.

O `webhook_eventos` precisa de limpeza periódica (registros com mais de 7 dias), acoplada ao job `check_queue` que já roda no Windmill.

---

## 7. Fases de implementação

### Fase 1 — Camada de canais (sem mudança de comportamento)

Criar `whatbot/channels/` com `base.py` (protocolo e `InboundMessage`), `whatsapp_evolution.py` (mover o `EvolutionApiClient` para lá, mantendo `whatbot/whatsapp.py` como alias de importação) e `router.py` (o `ChannelRouter`, que registra clientes por nome de canal e resolve por contato).

Ainda sem Instagram. Ao final desta fase o sistema funciona exatamente como antes, mas todo envio passa pelo roteador.

*Aceite:* `make test` passa sem alteração de asserções; `make chat-test` produz a mesma resposta de antes; nenhum `_whatsapp.send_text` direto permanece em `main.py`, `domain.py` ou `queue.py` (verificável por grep).

*Esforço:* 1,5 dia.

### Fase 2 — Migração de identidade no banco

Aplicar a migração da seção 6 dentro de `ensure_schema()`. Estender `Contact` e `WaitingContact` com `canal`, `external_id`, `handle` e uma propriedade `label` (prioridade: `push_name` → `@handle` → `external_id`). Reescrever os métodos de `db.py` para operar por `(canal, external_id)` mantendo sobrecarga compatível. Ajustar `queue.normalize_phone` para só normalizar quando o canal for WhatsApp, e `contact_resolver.extract_phone_from_text` para não casar IGSIDs.

*Aceite:* teste de migração que popula um banco no formato antigo, roda `ensure_schema()` e verifica que todos os contatos ficaram com `canal='whatsapp'` e `external_id = phone`, sem perda de linhas; suíte atual passa; fila e comandos admin funcionam com contatos WhatsApp legados.

*Esforço:* 2 dias.

### Fase 3 — Cliente e parser do Instagram

`whatbot/channels/instagram.py` implementando `send_text` contra `POST https://graph.instagram.com/v23.0/me/messages`, com `Authorization: Bearer <token>` e corpo `{"recipient": {"id": IGSID}, "message": {"text": ...}}`. Tratamento explícito de erro para fora da janela de 24h (código 100, subcódigo 2534014), permissão ausente (código 10) e rate limit (429 / código 613, com backoff exponencial e no máximo 3 tentativas). Divisão de mensagens longas em blocos de 1.000 caracteres, já que a resposta do Gemini pode ultrapassar o limite prático do DM.

`whatbot/instagram_webhook.py` com `parse_instagram_payload` e `parse_instagram_echo`, espelhando a semântica de `webhook.py`. Payload de entrada:

```json
{"object": "instagram",
 "entry": [{"id": "<IG_ID_DA_CONTA>", "time": 1753700000,
   "messaging": [{"sender": {"id": "<IGSID>"},
                  "recipient": {"id": "<IG_ID_DA_CONTA>"},
                  "timestamp": 1753700000,
                  "message": {"mid": "aWc...", "text": "oi, tem yoga?"}}]}]}
```

Casos a tratar: `message.is_echo = true` (mensagem enviada pela conta, o que inclui a secretaria respondendo pelo app do Instagram; mapeia para o fluxo de `parse_outgoing_staff_message`), `story_mention` e `reply_to.story` em `attachments`, mensagens só com mídia e sem texto (ignorar, como já se faz no WhatsApp), `message.is_deleted`, e múltiplas entradas em `entry`/`messaging` num único POST.

*Aceite:* testes unitários cobrindo os 8 formatos de payload, sem rede; cliente testado com `requests` mockado, incluindo os três cenários de erro e o split de mensagem longa.

*Esforço:* 2 dias.

### Fase 4 — Exposição HTTPS

Executar a seção 4: túnel Cloudflare, domínio, serviço no compose, teste de fumaça externo. Pode rodar em paralelo com as fases 1 a 3, já que não depende do código do bot — apenas de um endpoint HTTP qualquer respondendo na porta 8090.

*Aceite:* `curl https://webhook.seudominio.com.br/webhook/instagram?hub.mode=subscribe&hub.verify_token=...&hub.challenge=teste` executado de fora da rede local devolve `teste` com certificado válido; portas 8000, 8080, 5432 e 6379 confirmadamente inacessíveis pela internet.

*Esforço:* 1,5 dia.

### Fase 5 — Regras da janela de 24 horas

Aqui a integração deixa de ser mecânica e vira decisão de produto. Persistir `last_inbound_at` a cada mensagem recebida. Antes de qualquer envio pelo canal Instagram, o roteador consulta a janela:

- Dentro de 24h: envio normal.
- Fora de 24h, mensagem de handover ou atendimento humano: envio com tag `HUMAN_AGENT` (válido por até 7 dias).
- Fora de 24h, mensagem automática do bot: **não enviar**, registrar em log e devolver `{"ok": False, "error": "outside_messaging_window"}`.

Consequência direta: a reativação automática (`AUTO_REACTIVATE_HOURS=24`) não deve gerar mensagem proativa ao cliente do Instagram. Hoje a reativação já não envia nada ao cliente, apenas notifica o admin — então o comportamento atual é compatível e precisa apenas de um teste que garanta que continue assim.

Segunda consequência: a notificação de handover enviada à secretaria pelo WhatsApp precisa deixar explícitos o canal e o prazo, algo como *"🆕 Novo na fila — Maria (@maria.silva) via **Instagram** — responda pelo app do Instagram em até 24h"*. Sem isso a secretaria tenta responder pelo WhatsApp um contato que não tem telefone.

*Aceite:* testes com relógio injetado cobrindo os três cenários; mensagem de fila renderiza canal e handle corretamente; nenhuma mensagem automática sai fora da janela.

*Esforço:* 1 dia.

### Fase 6 — Serviço de ingestão

`whatbot/ingress.py`, aplicação FastAPI com dois endpoints:

- `GET /webhook/instagram` — se `hub.mode == "subscribe"` e `hub.verify_token` bate com `IG_WEBHOOK_VERIFY_TOKEN`, devolve `hub.challenge` como texto puro, status 200.
- `POST /webhook/instagram` — valida `X-Hub-Signature-256` com HMAC-SHA256 do corpo bruto usando o App Secret (comparação em tempo constante), responde 200 imediatamente e enfileira o processamento em background.

O processamento em background chama `whatbot.main.main()` com o payload normalizado. Antes de processar, checa `webhook_eventos` pelo `message.mid`; se já existe, descarta. Essa checagem é o que impede resposta duplicada quando a Meta reentrega.

Adicionar o serviço ao `docker-compose.yml` (porta 8090), acrescentar `fastapi` e `uvicorn[standard]` ao `requirements.txt`.

Scripts operacionais, espelhando os que já existem para WhatsApp em `scripts/`: `ig_oauth.py` (autorização e troca de tokens), `ig_refresh_token.py` (renovação, também publicado como job agendado no Windmill em `windmill/f/whatbot/refresh_ig_token.py`), `ig_subscribe_webhook.py` (inscrição em `subscribed_apps`), `ig_health_check.py` (valida token, expiração, inscrição e conectividade) e `ig_simulate_webhook.py` (assina e posta um payload local para teste ponta a ponta sem depender da Meta).

*Aceite:* handshake responde corretamente a token válido e rejeita inválido; assinatura inválida retorna 403; POST responde em menos de 500 ms medidos; evento duplicado é descartado; `ig_health_check.py` reporta token válido e inscrição ativa.

*Esforço:* 2 dias.

### Fase 7 — Integração ponta a ponta e conexão real

Registrar o `InstagramClient` no roteador, conectar a conta real via `ig_oauth.py`, inscrever o webhook e rodar o roteiro de homologação. Adicionar `IG_TEST_USERNAMES` como equivalente de `TEST_PHONES` para o canal Instagram, permitindo canário controlado.

*Aceite:* o roteiro de 14 casos da seção 8 passa integralmente em conta real de teste.

*Esforço:* 2 dias, mais espera se App Review for exigido.

### Fase 8 — Documentação e operação

Atualizar `README.md` (tabela de serviços e variáveis), `DEPLOYMENT.md` (seção de setup do Instagram e do túnel, paralela à do WhatsApp), `.env.example` e `Makefile` (alvos `ig-health`, `ig-refresh`, `ig-simulate`). Documentar o runbook de renovação de token e o procedimento quando a integração cai.

*Esforço:* 1 dia.

**Total: 13 dias de desenvolvimento**, sem contar espera de App Review nem propagação de DNS. As fases 1 e 2 são pré-requisito de tudo; as fases 3, 4 e 6 podem ser paralelizadas entre dois desenvolvedores, e a fase 4 pode começar no dia um.

---

## 8. Estratégia de testes

### Testes unitários (`unittest`, sem rede, no padrão atual do projeto)

`tests/test_instagram_webhook.py` — texto simples; múltiplas `entry` no mesmo POST; eco (`is_echo`); menção de story; resposta a story; anexo sem texto; mensagem apagada; payload malformado; `object` diferente de `instagram`.

`tests/test_instagram_client.py` — corpo e cabeçalhos da requisição; split de mensagem longa; erro de janela expirada; erro de permissão; retry com backoff em 429; modo `simulated` não faz chamada de rede.

`tests/test_channel_router.py` — resolve o cliente correto por canal; notificação de admin sempre vai pelo WhatsApp mesmo com contato de Instagram; canal desconhecido falha de forma explícita.

`tests/test_messaging_window.py` — dentro da janela envia; fora da janela bloqueia mensagem de bot; fora da janela permite handover com `HUMAN_AGENT`; após 7 dias bloqueia até handover.

`tests/test_webhook_signature.py` — assinatura válida aceita; inválida, ausente e corpo alterado rejeitados.

`tests/test_migration_compat.py` — schema antigo migra sem perda; `external_id` preenchido a partir de `phone`; índice único composto criado; contato WhatsApp legado continua sendo encontrado.

`tests/test_contact_resolver_multichannel.py` — IGSID de 17 dígitos não é confundido com telefone; resolução por `@handle`; desambiguação entre contatos de canais diferentes com nomes parecidos.

Meta de cobertura para o código novo: 85% de linhas. Os módulos de IA existentes ficam fora dessa meta por não serem alterados.

### Regressão do WhatsApp

Toda a suíte atual (`test_webhook.py`, `test_queue.py`, `test_domain.py`, `test_knowledge.py`, `test_grounding.py`, `test_fallback.py`, `test_admin_organic.py`, `test_message_log.py`, `test_test_mode.py`, `test_ollama.py`) deve passar sem modificação de asserções. Se algum teste precisar mudar, isso é sinal de quebra de contrato e exige justificativa explícita no PR. Complementar com teste manual do fluxo completo de WhatsApp após as fases 2 e 7.

### Integração local

Com o compose de pé, `scripts/ig_simulate_webhook.py` gera um payload assinado com o App Secret local e posta no serviço de ingestão. Valida: assinatura aceita, resposta 200 rápida, contato criado no Postgres com `canal='instagram'`, mensagem registrada em `mensagens`, resposta gerada e (com o cliente Instagram em modo `simulated`) registrada em `logs/messages.jsonl` sem chamada real à Meta. O mesmo script com `--duplicate` valida a idempotência.

### Roteiro de homologação em conta real (14 casos)

| # | Caso | Resultado esperado |
|---|---|---|
| 1 | DM nova: "quais modalidades vocês têm?" | Resposta do bot no Instagram, baseada em `knowledge/associacao.md` |
| 2 | Pergunta de preço | Preço correto ou handover; nunca preço inventado (grounding) |
| 3 | "quero falar com atendente" | Handover; secretaria notificada no WhatsApp com canal e handle |
| 4 | Secretaria responde pelo app do Instagram | Eco detectado; contato marcado como atendido; bot não interfere |
| 5 | Cliente responde de novo após atendimento | Bot permanece desligado até reativação |
| 6 | `#assumir` no WhatsApp para contato de Instagram | Funciona; fila exibe canal corretamente |
| 7 | Fila mista (WhatsApp + Instagram) | Lista mostra ambos com identificação de canal |
| 8 | Menção em story | Comportamento definido, sem erro nem loop |
| 9 | Só figurinha ou foto sem legenda | Ignorado silenciosamente |
| 10 | Envio automático após 25h de silêncio | Bloqueado com log claro, sem erro para o usuário |
| 11 | Reentrega do mesmo evento pela Meta | Uma única resposta ao cliente |
| 12 | Resposta do modelo com 3.000 caracteres | Dividida e entregue na ordem |
| 13 | Token revogado (simulando expiração) | `ig_health_check.py` acusa; admin notificado; sem loop de erro |
| 14 | Queda do túnel por 10 minutos | Meta reentrega; mensagem respondida ao voltar; sem duplicidade |

Cada caso registrado com data, executor e evidência (print do DM e linha correspondente do `messages.jsonl`).

---

## 9. Validação e implantação

**Canário.** Subir com `IG_TEST_USERNAMES` preenchido apenas com contas da equipe. O bot responde só a essas contas; DMs de clientes reais continuam chegando normalmente à secretaria, sem resposta automática. Duração sugerida: 3 dias.

**Abertura gradual.** Remover a restrição em horário de menor volume, com a secretaria acompanhando.

**Sinais de saúde a monitorar** (todos derivam do `messages.jsonl` e do Postgres, sem infraestrutura nova): taxa de erro por canal; latência entre recebimento do webhook e envio da resposta; envios bloqueados por janela de 24h; taxa de handover por canal (um salto no Instagram indica base de conhecimento inadequada ao público de lá); eventos duplicados descartados; dias restantes do token; e disponibilidade do túnel.

**Alertas para o admin no WhatsApp:** token com menos de 7 dias para expirar; mais de 5 falhas de envio no Instagram em 10 minutos; webhook sem receber nenhum evento por mais de 24h em dia útil.

**Rollback.** Desregistrar o webhook na Meta (`DELETE /me/subscribed_apps`) ou parar o container de ingestão. O WhatsApp segue intacto porque nada no caminho dele passa pelo serviço novo. As migrações de banco são aditivas e não precisam ser revertidas.

---

## 10. Riscos

O risco mais provável não é técnico: **a secretaria precisa responder DMs do Instagram pelo próprio Instagram**, enquanto recebe o aviso pelo WhatsApp. Se o time não absorver essa troca de contexto, contatos vão ficar parados na fila. Mitigação: notificação explícita sobre o canal, o alerta de espera prolongada que já existe, e treinamento antes do go-live. A alternativa — a secretaria responder por dentro do bot — é um projeto adicional de painel de atendimento, fora deste escopo.

Em seguida, por ordem de impacto: **disponibilidade da máquina local**, agravada por depender de um túnel doméstico (mitigação: monitorar 30 dias e migrar para VPS se necessário); **expiração do token de 60 dias** (job agendado de renovação, alerta com 7 dias de antecedência, health check diário); **App Review inesperadamente exigido** (manter modo desenvolvedor com testadores enquanto tramita, o que não bloqueia nenhuma outra fase); **resposta duplicada por reentrega** (idempotência por `mid`, testada explicitamente); **quota do Gemini**, já que o Instagram adiciona volume a uma cota que hoje já recorre a fallback de modelo e resposta offline — convém revisar limites antes do go-live; e **regressão no WhatsApp durante a refatoração de identidade** (fases 1 e 2 entregues separadamente, com a suíte de regressão como portão).

Há ainda um risco de conformidade: a política do Instagram proíbe abordagem fria e espera que automações não se façam passar por humano sem contexto. Vale incluir na primeira resposta do bot no Instagram uma indicação de que é atendimento automatizado, coerente com o que já se faz nas boas práticas de LGPD.

---

## 11. Checklist de encerramento

- [ ] Suíte completa passando, incluindo os 7 arquivos novos de teste
- [ ] Cobertura do código novo ≥ 85%
- [ ] Roteiro de 14 casos de homologação executado e registrado
- [ ] Zero regressão no WhatsApp confirmada por teste manual
- [ ] Túnel HTTPS estável, com certificado válido e portas internas inacessíveis de fora
- [ ] Renovação de token automatizada e testada com token real
- [ ] Alertas de saúde configurados e disparando para o admin
- [ ] `README.md`, `DEPLOYMENT.md` e `.env.example` atualizados
- [ ] Runbook de rollback documentado e testado uma vez
- [ ] Secretaria treinada no fluxo de resposta pelo Instagram
- [ ] Canário de 3 dias concluído sem incidentes

---

## Fontes

- [Instagram Platform — Overview (Meta for Developers)](https://developers.facebook.com/docs/instagram-platform/overview/)
- [Business Login for Instagram (Meta for Developers)](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login)
- [Send Messages using the Instagram API with Instagram Login (Meta for Developers)](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/)
- [Evolution API v2 — Introduction](https://doc.evolution-api.com/v2/en/get-started/introduction)
- [How to Integrate the Instagram Messaging API: 2 ways in 2026](https://zernio.com/blog/instagram-messaging-api)
