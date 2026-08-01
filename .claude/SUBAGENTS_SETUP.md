# Setup: subagentes + Zen + Context Mode + Codebase Memory + OpenSpec

Este documento descreve o fluxo de desenvolvimento assistido configurado neste
repositório via `.claude/agents/`, `.claude/commands/` e `.mcp.json`.

## 1. MCPs (`.mcp.json`)

O `.mcp.json` já está na raiz do repositório (escopo de projeto, versionado no
git) com três servidores: `zen`, `context-mode` e `codebase-memory`.

Por enquanto o plano é usar o **tier free da OpenRouter** (modelos com sufixo
`:free`, sem cobrança) — mesmo assim é preciso uma API key da OpenRouter
(gratuita, gerada em openrouter.ai). O `.mcp.json` referencia
`"${OPENROUTER_API_KEY}"` e `"${ZEN_MCP_SERVER_HOME}"`, que o Claude Code CLI
expande a partir de variáveis de ambiente no momento em que o servidor sobe —
**nenhum segredo/caminho fica em texto puro no arquivo versionado**.

O Claude Code **não** carrega `.env` automaticamente, nem usa
`.claude/settings.local.json` para essa expansão (testado e confirmado que
não funciona) — só variáveis de ambiente reais do processo. No Windows, use
variáveis de ambiente **persistentes de usuário** (não precisa setar de novo
a cada terminal):

```powershell
[Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", "sua-key-aqui", "User")
[Environment]::SetEnvironmentVariable("ZEN_MCP_SERVER_HOME", "$env:USERPROFILE\.zen-mcp-server", "User")
```

Abra um terminal **novo** depois disso (só processos criados depois enxergam
a mudança).

Atenção: o tier free da OpenRouter tem rate limit bem mais apertado que o
pago — se o Zen começar a travar em rate limit no meio de uma sessão longa,
esse é o motivo mais provável (ver seção 4).

### Setup do Zen (`ZEN_MCP_SERVER_HOME`)

O `.mcp.json` chama o Zen (o projeto oficial `BeehiveInnovations/zen-mcp-server`,
hoje rebatizado **PAL MCP** — "formerly known as Zen MCP") diretamente pelo
Python de um venv local, sem depender de wrapper npx nenhum. Isso exige
montar esse venv uma vez:

```powershell
# 1. bootstrap: deixa o instalador de conveniência clonar o repo e montar o venv
npx -y zen-mcp-server-199bio
# Ctrl+C assim que aparecer "Active tools: [...]" ou um erro — o objetivo aqui
# é só clonar o repo e criar o venv em %USERPROFILE%\.zen-mcp-server

# 2. o requirements.txt do projeto não tem teto de versão pro pacote `mcp`,
#    então o pip pode puxar uma versão incompatível com o server.py — force
#    uma versão 1.x, que é a que a API usada no código espera:
cd $env:ZEN_MCP_SERVER_HOME
.\venv\Scripts\python -m pip install "mcp<2.0.0"

# 3. o instalador de conveniência espera um `run.py` que esse repo não tem
#    (ele usa `server.py`) — cria um shim de uma linha:
Set-Content -Path "$env:ZEN_MCP_SERVER_HOME\run.py" -Value 'import runpy
runpy.run_path("server.py", run_name="__main__")' -Encoding utf8

cd C:\Projetos\WhatBot
```

Isso é uma correção pontual de bugs do instalador `zen-mcp-server-199bio`
nessa versão, num Windows sem WSL — não deveria ser necessário todo setup,
mas foi o que resolveu aqui. Se o repo oficial atualizar o `run.py` ou pinar
a versão do `mcp` corretamente, esses passos deixam de ser necessários.

Depois, na raiz do projeto:

```bash
# valida se o Claude Code reconhece os servidores
claude mcp list
```

`context-mode` e `codebase-memory` são pacotes npm padrão, sem esse problema
— sobem direto com `npx -y context-mode` / `npx -y codebase-memory-mcp`.

## 2. Subagentes e comandos

Já instalados em:
- `.claude/agents/planner.md`, `critic.md`, `implementer.md`, `scope-explorer.md`
- `.claude/commands/ideate.md`, `develop.md`

Claude Code carrega automaticamente qualquer `.md` dentro dessas pastas.

Teste com:

```
> use o subagente planner para planejar [sua tarefa aqui]
```

## 3. Fluxo de trabalho recomendado (o ciclo completo)

0. **Ideia com escopo amplo e ainda mal definido** (ex: "quero expandir o
   WhatBot para outro canal de atendimento"): dispare primeiro o subagente
   `scope-explorer`, não o planner. Ele mapeia gaps e sugere features
   candidatas ANTES de qualquer plano concreto existir. Pule esta etapa se a
   tarefa já for bem definida.
   ```
   > use o subagente scope-explorer para expandir o escopo do WhatBot e
     sugerir features relacionadas cobrindo gaps da versão atual
   ```
   Ou use o atalho `/ideate [ideia]`, que encadeia `scope-explorer` → `planner`
   com um checkpoint de confirmação do usuário no meio.
1. **Plan Mode** (Shift+Tab duas vezes) na sessão principal para tarefas
   pequenas/médias, OU dispare o subagente `planner` explicitamente para
   tarefas grandes que merecem ficar isoladas do contexto principal. Se veio
   do passo 0, passe a lista priorizada do scope-explorer como entrada.
2. O OpenSpec já está configurado neste projeto (`openspec/`) — o planner lê
   as specs existentes e `openspec/project.md` antes de propor qualquer
   coisa, sem precisar pedir.
3. Para decisões de arquitetura de alto impacto, peça consenso multi-modelo
   antes de aprovar o plano:
   ```
   > use zen consensus com gemini a favor e kimi neutro para avaliar esse plano
   ```
4. Aprove o plano → dispare o subagente `implementer`, ou use `/develop
   [plano]` para rodar o ciclo implementer→critic automaticamente (com teto de
   3 iterações).
5. Ao final, dispare o subagente `critic` para revisão — ele pode escalar
   pro `zen challenge` se achar que está concordando fácil demais.
6. Para tarefas bem definidas e verificáveis (ex: "todos os testes passam"),
   considere `/goal` em vez de supervisionar turno a turno:
   ```
   /goal todos os testes em tests/ passam e make test não retorna erro
   ```

## 4. Onde cada peça economiza token/dinheiro

- **Context Mode**: sandboxa saídas grandes de ferramentas (logs, respostas
  de API, snapshots) — ativa automaticamente via hook, não precisa chamar
  manualmente na maioria dos casos.
- **Codebase Memory**: use para perguntas estruturais ("o que chama essa
  função", "quais rotas existem", "quem usa `ChannelRouter`") em vez de
  deixar o agente fazer grep arquivo por arquivo.
- **Zen com Kimi/OpenRouter pago**: reserve para consensus/challenge e
  leitura em massa de código — evite o tier free para não travar em rate
  limit no meio de uma sessão longa.
- **Subagentes nativos**: usam a cota do seu plano Pro — bons para o
  trabalho principal (planejar, implementar, revisar), não para todo
  ciclo de "segunda opinião" que o Zen resolve mais barato.

## 5. Checklist rápido

- [ ] Variáveis de ambiente de usuário `OPENROUTER_API_KEY` (key free da
      OpenRouter) e `ZEN_MCP_SERVER_HOME` definidas via
      `[Environment]::SetEnvironmentVariable(..., "User")` — o `.mcp.json` só
      referencia `${OPENROUTER_API_KEY}` / `${ZEN_MCP_SERVER_HOME}`, nunca
      valores literais
- [ ] `claude` disponível no PATH (`npm install -g @anthropic-ai/claude-code`)
- [ ] `%ZEN_MCP_SERVER_HOME%\venv` montado com `mcp<2.0.0` instalado e
      `run.py` presente (ver "Setup do Zen" acima)
- [ ] `.claude/agents/planner.md`, `critic.md`, `implementer.md`,
      `scope-explorer.md` no lugar
- [ ] `claude mcp list` mostra zen, context-mode e codebase-memory ativos
- [ ] Rodar `npx -y codebase-memory-mcp --index .` uma vez por projeto
      (reindexação é incremental depois disso)
- [ ] Testar o ciclo completo numa tarefa pequena antes de confiar nele
      numa tarefa grande
