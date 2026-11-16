# ADR 002 — Google Drive como armazenamento de arquivos

- **Data:** 2026-11-16
- **Status:** aceito, com mitigação obrigatória
- **Fase:** 1 (decisão) / 3 (implementação)

## Contexto

O portfólio precisa guardar imagens: avatar, capas de projeto e thumbnails
importados do GitHub. As opções consideradas foram MinIO em container,
Supabase Storage, e Google Drive via service account.

## Decisão

Usar **Google Drive** como armazenamento, acessado por uma **service account**,
e **sempre atrás de um endpoint próprio com cache**, nunca referenciado
diretamente no HTML.

## Justificativa

A favor:

- Não adiciona container nem volume à stack, que é o que o time quer.
- Cota generosa no plano gratuito.
- Os arquivos ficam visíveis e auditáveis numa pasta comum, o que facilita a
  conferência durante o desenvolvimento.

Contra, e por isso a mitigação é obrigatória:

- **O Drive não é um CDN.** A latência fica na faixa de centenas de
  milissegundos por arquivo, contra poucos milissegundos de um object storage.
- **Links públicos do Drive são instáveis como `src` de imagem**: mudam de
  formato, sofrem redirecionamento e podem ser bloqueados por volume.
- **A API tem cota por minuto**, que uma página com muitas imagens estoura.

Isso entra em conflito direto com o requisito de **carregamento rápido** que o
enunciado do projeto nº 14 estabelece. Aceitar o Drive sem tratamento seria
aceitar descumprir um requisito.

## Mitigação (não é opcional)

1. O Drive é o **armazenamento**, não o canal de entrega. Nenhum template
   referencia `drive.google.com`.
2. O serviço `web` expõe `GET /media/{id}`, que:
   - procura o arquivo no cache do Redis (chave `media:{id}`, TTL de 24h);
   - em caso de falta, busca no Drive, grava no cache e devolve;
   - responde com `Cache-Control: public, max-age=31536000, immutable`, já que
     o id é derivado do conteúdo e portanto nunca aponta para bytes diferentes.
3. Thumbnails são redimensionados **antes** do upload (máx. 1200px, WebP), para
   que o arquivo trafegado seja pequeno.
4. Métrica `prismo_media_cache_hits_total` contra `prismo_media_drive_fetches_total`:
   se a taxa de acerto cair abaixo de 90%, a decisão precisa ser revista.

## Consequências

- A primeira visualização de cada imagem é lenta; as seguintes não.
- A chave da service account é um segredo de verdade: `Secret` no Kubernetes,
  montado em `/run/secrets/google-sa.json`, e no `.gitignore`.
- Se a taxa de acerto do cache não se sustentar, a alternativa já mapeada é o
  Supabase Storage, que tem CDN e usa a conta que já temos.
