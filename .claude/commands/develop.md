---
description: Take an approved plan or proposal and run the implement-review loop (implementer + critic) until it passes or hits the iteration limit.
argument-hint: [plano/proposta, ou referência ao documento gerado por /ideate]
allowed-tools: Task, Read, Glob, Grep, Bash
model: opus
---

Você está no modo de desenvolvimento ativo. A fase de ideação já terminou —
não questione o escopo aqui, apenas execute e valide.

Plano/proposta recebido: $ARGUMENTS

Se $ARGUMENTS estiver vazio ou vago, procure o documento de proposta mais
recente gerado por `/ideate` na conversa ou no projeto antes de continuar.
Se não encontrar nada claro, peça o plano ao usuário — não invente escopo.

Execute o ciclo:

1. **Dispare o subagente `implementer`** com o plano completo.
2. **Dispare o subagente `critic`** para revisar o resultado.
3. Avalie o veredito do critic:
   - **Aprovado** → encerre o ciclo. Reporte resumo final ao usuário.
   - **Aprovado com ressalvas** → decida se as ressalvas são bloqueadoras
     para o objetivo original; se não forem, encerre e reporte as ressalvas
     como pendências conhecidas. Se forem, trate como rejeitado.
   - **Rejeitado** → volte ao passo 1, chamando o `implementer` de novo
     com o feedback estruturado do critic como entrada adicional.

4. **Limite de 3 iterações do ciclo implementer→critic.** Se ainda não
   convergiu na 3ª volta, pare e reporte ao usuário: o que foi tentado,
   por que continua falhando, e uma recomendação (ex: replanejar com
   `/ideate`, ou pedir intervenção humana num ponto específico). Nunca
   entre num loop sem esse teto.

5. Para saídas grandes de teste/log durante o ciclo, deixe o Context Mode
   processar — não copie output bruto extenso no relatório final.

Ao final, sempre produza um resumo curto: o que foi implementado, quantas
iterações foram necessárias, o veredito final do critic, e qualquer
pendência conhecida.
