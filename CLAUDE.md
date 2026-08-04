# WhatBot — instruções para o Claude Code

## Context Mode — uso obrigatório para saídas grandes

O MCP `context-mode` está habilitado neste projeto (`.claude/settings.local.json`).
Use `mcp__context-mode__ctx_execute` / `ctx_batch_execute` em vez de `Bash` sempre
que o comando gerar uma saída grande e o objetivo for **derivar** uma resposta
dela (filtrar, contar, resumir), não ler o conteúdo bruto na íntegra. Só o que
for impresso (`echo`/`console.log`/`print`) entra na conversa — o resto fica no
sandbox.

Exemplos concretos deste projeto:
- `docker logs whatbot_ingress` / `docker logs whatbot-db-1` — sempre grepar/
  resumir via `ctx_execute`, nunca colar log bruto inteiro na conversa.
- `python -m unittest discover -s tests -p 'test_*.py'` / `pytest` — rodar via
  `ctx_execute` quando só o resultado final (quantidade de testes, falhas)
  importa; usar `Bash` diretamente só quando precisar investigar uma falha
  específica linha a linha.
- Greps amplos em `whatbot/`, `openspec/`, `tests/` que retornariam muitas
  linhas — preferir `ctx_execute`/`ctx_batch_execute` com `intent` descrevendo
  o que se procura.
- Consultas ao Postgres/Graph API que retornam JSON grande (ex.: `get_subscribed_apps`,
  listagem de credenciais) — mesma lógica.

**Quando NÃO usar**: comando único e curto (`git status`, `docker ps`), ou
qualquer coisa cujo conteúdo exato/bruto seja necessário para o próximo passo
(ex.: ler um arquivo antes de editar — use `Read`, não o sandbox).

## MCP Codebase Memory

O MCP `codebase-memory` também está habilitado neste projeto (`.mcp.json`).
Já foi indexado (`index_repository`) — mas a indexação **não é automática**:
se uma sessão notar que o índice está bem atrás do `HEAD` atual (`index_status`
vs `git log`), rode `index_repository` de novo antes de confiar nas respostas.

Use-o para perguntas estruturais deste repo em vez de grep manual/agente de
exploração, por exemplo:
- "o que chama `ChannelRouter.send`", "quem usa `send_admin`/`send_to_contact`"
  — `query_graph`/`trace_path`, já que `whatbot/channels/` é a única fronteira
  de saída e vale confirmar que nenhum módulo de domínio está furando essa
  camada.
- "quais rotas/handlers de webhook existem hoje" (Evolution API, Windmill
  entrypoints) — `get_architecture` antes de mexer em `windmill/f/whatbot/`.
- Localizar onde a chave de identidade (`contatos.phone` hoje, migrando para
  `(canal, external_id)` na capability `identity`) é usada — `search_code`/
  `search_graph` em vez de grep espalhado por `whatbot/`.

Para busca textual simples (uma string exata, um TODO específico), `grep`/
`Explore` continua sendo mais direto — o grafo é para relações, não substitui
busca literal.

## OpenSpec

Este projeto usa OpenSpec (`openspec/`) como fonte de verdade do planejamento.
Ver `openspec/project.md` para convenções específicas do repositório (testes,
camadas, chave de identidade) e a ordem de dependência entre os changes ativos.
As regras gerais de fluxo OpenSpec (propor → aplicar → sincronizar → arquivar)
estão nas instruções globais do usuário (`~/.claude/CLAUDE.md`).
