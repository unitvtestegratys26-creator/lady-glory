# Referências consultadas — Free Fire API (documentação indicada pelo usuário)

Consulta feita em 2026-10-08. Estas notas registram apenas documentação externa; não foram enviadas credenciais nem consultados dados reais de jogadores.

## Fontes

- Visão geral: https://hostfreefire-api.squareweb.app/docs-api
- Jogador: https://hostfreefire-api.squareweb.app/docs-api/jogador
- Banimento: https://hostfreefire-api.squareweb.app/docs-api/banimento
- Conta: https://hostfreefire-api.squareweb.app/docs-api/conta
- Estatísticas: https://hostfreefire-api.squareweb.app/docs-api/estatisticas
- Utilidades: https://hostfreefire-api.squareweb.app/docs-api/utilidades

## Detalhes que afetam a implementação

- A base HTTP documentada é `https://hostfreefire-api.squareweb.app`; rotas ficam sob `/api`, usam GET e respondem JSON por padrão.
- Perfil público: `GET /api/info_player?uid=<ID_NUMERICO>&region=br`; opcional `clothes=true` entrega URLs de `images.profileCard` e `images.outfit` e substitui `profileInfo.clothes` por `{ids, images}`. Resposta contém `basicInfo` (nickname, region, level, exp, bannerId, headPic, etc.), `resolved.clothes`, `resolved.weaponSkinShows`, `resolved.avatar`, `resolved.banner`, além de `images.avatar` e `images.banner`.
- Imagem de item: `GET /api/iconsff?image=<ITEM_ID>&format=webp|png`; documentação diz cache público por 24 horas.
- Banimento público: `GET /api/check_banned?id=<ID_NUMERICO>&region=br`; `details.is_banned` é exemplo textual `yes`/`no`; `banned_period` não está em segundos. Pode retornar 404 jogador não encontrado ou 500 se falhar.
- Outra rota, `/api/check_guest_ban`, pede UID e senha Guest em query parameters. A senha em query URL pode acabar em logs do servidor/proxies, por isso não foi escolhida para integração.
- Estatísticas de carreira: `GET /api/stats?id=<ID>&region=br&mode=br` ou `mode=cs`. Em BR há blocos BR_CAREER/CLASSIC/RANKED e métricas solo/duo/squad; em CS há carreira, casual e ranqueado.
- `region=br` também cobre `sac`, `us`, `na`, `latam` segundo o guia.
- A visão geral alerta que alguns endpoints na categoria Conta fazem alterações reais (nickname, bio, wishlist, amigos, clã); não são necessários para estas solicitações de leitura.

## Rotas de conta adicionadas ao painel

- `/api/v1/token?access_token=...&token_type=game` valida o Access Token de jogo e retorna `tokenBasicInfo.uid`, `open_id` e `platform`. O dashboard exige esse tipo de token antes de salvar.
- `/api/guest?guest_uid=...&guest_password=...` devolve Access Token para operações de nickname/bio, que exigem token. Para amigos e wishlist mutável, a API aceita Guest UID + senha ou Access Token.
- Amigos: `/api/get_friends`, `/api/add_friend?id=...` e `/api/remove_friend?id=...`.
- Perfil: `/api/change_nick?nickname=...&access_token=...` e `/api/bio_change?new_bio=...&access_token=...&region=br`.
- Wishlist: consulta pública `/api/wishlist?id=...&region=br`; mutações `/api/wishlist_add` e `/api/wishlist_remove`, com `item_id` e credencial.
- A rota de perfil documentada é `/api/info_player`; a implementação herdada chamava `/api/info_player_cached`, que não aparece na documentação consultada. Essa chamada foi corrigida. O normalizador de imagens agora suporta string, URL relativa e objeto `webp`/`jpeg`/`png`, com fallback ao ID via `/api/iconsff`.
- As rotas de conta são chamadas apenas a partir do backend local quando o usuário aciona o painel. As credenciais ficam em `accounts.json` sem criptografia; o arquivo é chmod 600 no Linux. A API documenta credenciais Guest em query string HTTPS, então devem ser tratadas como segredos enviados ao provedor.

- Consultas adicionais da seção Conta: `/api/diamonds` lê diamantes/ouro e dados de recarga; `/api/guest/check_airdrop` consulta elegibilidade e período do airdrop; `/api/check_xp_card` procura cartão de EXP. Nenhuma dessas três ações do painel resgata ou consome itens.
