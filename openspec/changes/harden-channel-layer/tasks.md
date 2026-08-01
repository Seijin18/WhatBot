# Tasks — endurecer a camada de canais

## 1. Harness de teste

- [ ] 1.1 Criar `tests/fakes.py` com `FakeDatabase` em memória cobrindo a
      superfície pública de `whatbot.db.Database` usada por `main`, `queue`,
      `admin` e `domain`, devolvendo `Contact` / `WaitingContact` /
      `MessageRecord` reais
- [ ] 1.2 Mover `FakeClient` e `LegacyClient` de `tests/test_channel_router.py`
      para `tests/fakes.py` e importá-los de volta, sem alterar nenhuma asserção
      daquele arquivo
- [ ] 1.3 Adicionar `FakeLlm` (resposta fixa e modo indisponível) e um helper de
      injeção dos globais `_db` / `_router` / `_llm` de `whatbot.main`

## 2. Testes end-to-end

- [ ] 2.1 `tests/test_main_e2e.py`: payload cru da Evolution → `main()` →
      resposta entregue no cliente WhatsApp
- [ ] 2.2 Handover: cliente recebe no canal dele e admin é notificado no WhatsApp
- [ ] 2.3 Cliente em canal não-WhatsApp: resposta no canal do cliente,
      notificação de admin ainda no WhatsApp
- [ ] 2.4 Comando de admin (`#assumir`) → `handle_admin_message` → `send_admin`
- [ ] 2.5 Staff respondendo pelo WhatsApp Business (`fromMe`) → fila
      auto-completada
- [ ] 2.6 LLM indisponível → `MODEL_UNAVAILABLE_MSG` sai pelo canal correto

## 3. Cobertura do cliente WhatsApp

- [ ] 3.1 `tests/test_evolution_client.py` com `requests.post` mockado: URL,
      headers e corpo corretos
- [ ] 3.2 `simulated=True` não chama a rede e devolve `{"simulated": True}`
- [ ] 3.3 `log_outbound` recebe `delivery` `sent` / `skipped` / `failed`
- [ ] 3.4 Falha de transporte propaga erro tipado

## 4. Correções

- [ ] 4.1 D1 — propagar `canal` de `run_admin_simulation` para
      `process_customer_message`
- [ ] 4.2 D2 — validar canal contra `SUPPORTED_CHANNELS` na borda de entrada
- [ ] 4.3 D3 — renomear o primeiro parâmetro de `EvolutionApiClient.send_text`
      para `to`, alinhando ao protocolo
- [ ] 4.4 D4 — embrulhar falha de transporte em `ChannelError(retryable=...)` e
      ajustar o tratamento em `main.py`, com log agnóstico de canal
- [ ] 4.5 D5 — `send_to_contact` passa a despachar por `hasattr`, como
      `send_admin`
- [ ] 4.6 D6 — `webhook.py` constrói `InboundMessage` e emite `.to_payload()`;
      `to_payload()` normaliza o canal antes de comparar
- [ ] 4.7 D7 — remover import morto de `DEFAULT_CHANNEL` em `main.py`

## 5. Fechamento

- [ ] 5.1 Suíte completa verde, com os 84 testes anteriores sem alteração de
      asserção
- [ ] 5.2 Verificar que cada teste novo falha se a correção correspondente for
      revertida
- [ ] 5.3 Confirmar por busca que não há envio direto por cliente concreto
- [ ] 5.4 Smoke com Docker: `make chat-test` produz a mesma resposta que em
      `db9db6a` (critério de aceite da Fase 1 que ficou em aberto)
