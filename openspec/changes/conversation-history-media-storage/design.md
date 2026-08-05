# Design — histórico de conversas, mídia e API de leitura

## Decisão 1: estender `mensagens`, não criar tabela paralela

Alternativas consideradas:

1. **Tabela nova (`mensagens_completas`/`conversas`) mantendo `mensagens`
   intocada.** Rejeitada — duplicaria toda mensagem em duas tabelas
   (uma "resumida" para o bot, outra "completa" para a interface),
   exigindo manter as duas em sincronia para sempre. Sem ganho real: nada
   hoje lê `mensagens` de um jeito incompatível com colunas adicionais
   nullable.
2. **Estender `mensagens` com colunas opcionais.** Escolhida — mesmo
   padrão aditivo já usado em todo `ensure_schema()` (`ALTER TABLE ADD
   COLUMN IF NOT EXISTS`, ver a migração de identidade multicanal em
   `contatos`). `canal`, `message_id`, `payload`, `media_id` são todos
   nullable, então as 7 chamadas existentes de `save_message` continuam
   funcionando sem alteração — só quem tem o payload bruto do webhook
   passa a informá-lo.

## Decisão 2: `media_arquivos` como tabela própria, referenciada por `mensagens.media_id`

Mídia tem atributos que não fazem sentido em `mensagens` (tipo, mime,
tamanho, backend de storage, status de download, erro) e o relacionamento é
1:1 opcional (nem toda mensagem tem mídia) — mesmo critério já usado em
`produtos_catalogo`/`contact-interest-memory`: só criar tabela nova quando o
dado é uma entidade própria, não um atributo solto. `media_id` fica em
`mensagens` (não o inverso) porque a mensagem é o lado "principal" da
relação — uma consulta de histórico busca mensagens e faz join opcional
para mídia, nunca o contrário.

## Decisão 3: abstração de storage por chave relativa (`storage_key`), não path/URL absoluto

O maior risco de "rudimentar hoje, S3 depois" é deixar paths de disco
absolutos vazarem para o banco ou para a API — trocar de backend viraria
uma migração de dados, não só de código. Por isso:

- `media_arquivos.storage_key` é sempre uma chave relativa (ex.
  `whatsapp/2026/08/42/9f3e...ogg`), nunca um path absoluto.
- `LocalDiskStorage` resolve `root_dir/key` internamente; nada fora do
  módulo `whatbot/storage/` sabe onde o arquivo mora fisicamente.
- Um futuro backend S3 usaria a mesma `storage_key` como object key do
  bucket — migrar é reprocessar as linhas de `media_arquivos`
  (`storage_backend='local' → 's3'` + upload), não redesenhar o schema.
- Acesso ao binário sempre passa por `StorageBackend.open()`/`url()`,
  nunca por leitura direta de arquivo fora do módulo — inclusive a rota
  HTTP `GET /admin/midia/{id}` chama o backend, não monta um path.

## Decisão 4: API de leitura fica em `whatbot/ingress.py`, não um serviço novo

`whatbot/ingress.py` já é o único serviço HTTP do projeto (FastAPI,
dedicado a webhooks Meta). Cogitou-se um serviço separado só para a API
administrativa, mas isso duplicaria setup (Docker, deploy, auth) para um
volume de tráfego baixo (uso interno). Reaproveitar o mesmo `FastAPI app`
com um novo prefixo de rota (`/admin/...`) e autenticação por bearer token
próprio (`ADMIN_API_TOKEN`, distinto do secret de webhook da Meta) é
suficiente para "rodar localmente" hoje e não impede separar depois se o
tráfego justificar.

Autenticação fica deliberadamente simples (token estático via env var) —
não é SSO nem JWT — porque o consumidor é um único backend interno
(`camu-web-admin`, chamando do lado do servidor). Trocar por algo mais
forte no futuro não muda o formato da API, só o middleware de auth.

## Decisão 5: envio humano reusa `ChannelRouter.send_to_contact`, API não fala com client de canal

A regra de layering do projeto (`openspec/project.md`, "channels é a única
fronteira de saída") não abre exceção para a nova rota `POST
/admin/conversas/{id}/mensagens`. A rota chama exatamente o mesmo caminho
que `whatbot/admin.py` já usa para responder um contato em modo de
atendimento humano — reaproveita a checagem de status (só aceita envio
quando o contato está de fato em handover) em vez de duplicá-la.

## Decisão 6: falha de download de mídia não bloqueia a mensagem

Cogitou-se falhar a mensagem inteira (não gravar nada) se o download da
mídia falhar. Rejeitada: perderia o registro de que o cliente mandou algo,
dificultando qualquer investigação depois. Em vez disso, `media_arquivos`
grava com `status='falhou'`/`erro`, e `mensagens.media_id` aponta pra essa
linha mesmo assim — a mensagem existe no histórico, só sem o binário
disponível ainda (pode ser reprocessada manualmente depois, reusando
`origem_media_id`).

## Decisão 7: pipeline de mídia só para WhatsApp Cloud API nesta etapa

Ver "Fora de escopo" em `proposal.md`. Instagram tem o mesmo gap
(`KIND_MEDIA_ONLY` em `instagram_webhook.py`), mas resolver os dois juntos
dobraria a superfície deste change sem necessidade — `whatbot/storage/` já
fica pronto para reuso, então estender para Instagram depois é aditivo puro
(mesmo padrão, outro parser).
