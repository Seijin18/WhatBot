# Tasks — atendimento de DMs do Instagram

Detalhamento e justificativa de cada fase em `docs/INSTAGRAM_INTEGRATION_PLAN.md`.
Estimativa total: 13 dias de desenvolvimento, fora espera de App Review e DNS.

## 0. Pré-requisitos da Meta (sem código, começar já — envolve terceiros)

- [ ] 0.1 Conta do Instagram como profissional, com acesso a mensagens liberado
      em Ferramentas conectadas (sem isso os webhooks simplesmente não chegam —
      é a falha silenciosa mais comum)
- [ ] 0.2 App Business criado, produto Instagram adicionado na variante com
      Instagram Login; guardar App ID e App Secret
- [ ] 0.3 Escopos `instagram_business_basic` e
      `instagram_business_manage_messages`
- [ ] 0.4 Fluxo de token executado até o token de longa duração
- [ ] 0.5 Assinatura do campo `messages` no webhook
- [ ] 0.6 Checkpoint de App Review (esperado desnecessário sob Standard Access)

## 1. Camada de canais — ENTREGUE

- [x] 1.1 `whatbot/channels/` com contrato, cliente WhatsApp e roteador
- [x] 1.2 Todo envio passando pelo roteador
- [x] 1.3 Acabamento e cobertura — ver change `harden-channel-layer`

## 2. Migração de identidade no banco (bloqueia 3, 5, 6, 7)

- [ ] 2.1 Migração aditiva e idempotente dentro de `ensure_schema()`: `canal` e
      `external_id` em `contatos`, backfill a partir de `phone`, chave única por
      `(canal, external_id)`, `phone` deixa de ser obrigatório
- [ ] 2.2 `last_inbound_at` e `handle` em `contatos`; `canal` e `external_id` em
      `handover_historico`
- [ ] 2.3 Tabelas `canal_credenciais` e `webhook_eventos`
- [ ] 2.4 `Contact` e `WaitingContact` ganham `canal`, `external_id`, `handle` e
      um rótulo legível com precedência nome → arroba → identidade
- [ ] 2.5 Métodos de `db.py` passam a operar por `(canal, external_id)`, com
      compatibilidade assumindo `whatsapp` quando o canal não vier
- [ ] 2.6 Normalização de telefone restrita ao WhatsApp; extração de telefone em
      texto livre deixa de casar com IGSID
- [ ] 2.7 Limpeza periódica de `webhook_eventos` no job agendado existente
- [ ] 2.8 Teste de migração contra Postgres real: base no formato antigo,
      `ensure_schema()`, nenhuma linha perdida

## 3. Cliente e parser do Instagram

- [ ] 3.1 `whatbot/channels/instagram.py` implementando o contrato de canal
- [ ] 3.2 Tratamento explícito de fora-da-janela, permissão ausente e rate limit
      com backoff
- [ ] 3.3 Quebra de mensagem longa em blocos, preservando ordem
- [ ] 3.4 `whatbot/instagram_webhook.py`: parser de mensagem e de eco
- [ ] 3.5 Casos de borda: eco da própria secretaria, menção e resposta a story,
      mensagem só com mídia, mensagem apagada, múltiplos eventos num POST
- [ ] 3.6 Testes dos formatos de payload e dos cenários de erro, sem rede

## 4. Exposição HTTPS (paralelizável, pode começar no dia um)

- [ ] 4.1 Túnel com domínio próprio e certificado válido, URL estável
- [ ] 4.2 Expor apenas a rota de webhook; Windmill, Evolution API, Postgres e
      Redis permanecem inacessíveis pela internet
- [ ] 4.3 Token de verificação com entropia adequada
- [ ] 4.4 Procedimento documentado em `DEPLOYMENT.md`
- [ ] 4.5 Aceite: handshake respondido de fora da rede local com certificado
      válido, e portas internas confirmadamente fechadas

## 5. Regras da janela de 24 horas

- [ ] 5.1 Persistir o último recebimento a cada mensagem de entrada
- [ ] 5.2 Verificação da janela antes de todo envio pelo canal
- [ ] 5.3 Garantir que a reativação automática do bot não gere mensagem proativa
- [ ] 5.4 Notificação de fila informa canal, identificador legível e prazo
- [ ] 5.5 Testes dos três cenários com relógio injetado

## 6. Serviço de ingestão

- [ ] 6.1 `whatbot/ingress.py`: handshake de verificação e recebimento com
      validação de assinatura sobre o corpo bruto, comparação em tempo constante
- [ ] 6.2 Confirmação imediata, processamento fora do ciclo de resposta
- [ ] 6.3 Descarte de evento duplicado pelo identificador de mensagem
- [ ] 6.4 Serviço no compose e dependências novas em `requirements.txt`
- [ ] 6.5 Scripts operacionais espelhando os do WhatsApp: OAuth, renovação de
      token, assinatura de webhook, health check, simulação de webhook
- [ ] 6.6 Job agendado de renovação de token
- [ ] 6.7 Testes: token inválido recusado, assinatura inválida recusada,
      confirmação rápida medida, duplicata descartada

## 7. Integração ponta a ponta e conexão real

- [ ] 7.1 Registrar o cliente novo no roteador
- [ ] 7.2 Conectar a conta real e assinar o webhook
- [ ] 7.3 Lista de contas de teste como equivalente da lista do WhatsApp
- [ ] 7.4 Roteiro de homologação de 14 casos executado em conta real, cada caso
      com data, executor e evidência
- [ ] 7.5 Canário de 3 dias restrito à equipe, depois abertura gradual

## 8. Documentação e operação

- [ ] 8.1 `README.md`, `DEPLOYMENT.md` e `.env.example` atualizados
- [ ] 8.2 Atalhos de operação no `Makefile`
- [ ] 8.3 Runbook de renovação de credencial e de queda da integração
- [ ] 8.4 Alertas ao admin: credencial perto de expirar, sequência de falhas de
      envio, ausência prolongada de eventos
- [ ] 8.5 Rollback documentado e testado uma vez
- [ ] 8.6 Secretaria treinada no fluxo — responder DM pelo Instagram enquanto
      recebe o aviso pelo WhatsApp é o principal risco do projeto, e não é
      técnico
