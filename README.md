# Lady Glory — painel local de contas

O Lady Glory é um painel local para acompanhar contas Free Fire e controlar a Main. Abra-o em `http://127.0.0.1:20335` depois de iniciar `Main.py`.

## Contas e painel

- Adicione uma conta **Guest** (UID + senha) ou um **Access Token de jogo**. O token é validado pela API antes de ser salvo; ambos os tipos iniciam o worker da Main.
- Os cartões mostram avatar, banner, outfit, itens equipados, EXP, nível, estado de banimento e estatísticas de carreira BR/CS quando a API retorna esses dados.
- O botão **Gerenciar conta** permite consultar/adicionar/remover amigos; consultar/adicionar/remover itens da lista de desejos; alterar nickname e bio; e consultar carteira (diamantes/ouro), elegibilidade de airdrop e presença de cartão de EXP.
- A API usada está documentada em [hostfreefire-api.squareweb.app/docs-api](https://hostfreefire-api.squareweb.app/docs-api). As ações de conta só são enviadas quando você as solicita no painel. A troca de nickname pode consumir um cartão de alteração de nome; o painel pede confirmação antes de enviá-la. A verificação de airdrop é somente consulta; não resgata nem compra nada.
- O layout foi ajustado para telas pequenas: controles se reorganizam, formulários usam campos adequados ao toque e a lista de logs fica rolável.

## Iniciar

Use Python 3.10 ou superior; Python 3.12 é recomendado.

**Windows (PowerShell):**

```powershell
cd caminho\para\new-main-web
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python Main.py
```

**Linux/macOS:**

```bash
cd /caminho/para/new-main-web
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python Main.py
```

Acesse `http://127.0.0.1:20335` na mesma máquina. Para montar squad CS, selecione quatro contas Guest distintas e clique em **Iniciar squad CS**. O UID externo `168274223` é convidado pelo fluxo existente; uma única fila só deve começar depois que o servidor confirmar a squad 4/4. O comportamento real do protocolo depende da versão/servidor do jogo e precisa ser validado no cliente; testes locais não equivalem a uma confirmação do servidor.

## Segurança e privacidade

- `accounts.json` contém credenciais Guest ou Access Tokens em texto simples; o arquivo não é criptografado. No Linux, o programa restringe as permissões do arquivo. Mantenha a pasta privada e nunca compartilhe esse arquivo, o token ou capturas que os exibam.
- O painel foi configurado para escutar em `127.0.0.1` e não tem autenticação de usuários. Não exponha a porta à internet nem troque o endereço por `0.0.0.0` sem adicionar controles de acesso.
- As rotas de perfil/ban/estatísticas enviam UID/região à API pública. As ações de gerenciamento precisam autenticar a conta junto à API; a API documenta credenciais em parâmetros de consulta HTTPS, portanto o provedor recebe esses dados para executar a solicitação.
- A API pode ficar indisponível ou devolver perfil/estatísticas incompletos. Nesses casos o painel indica indisponibilidade em vez de afirmar um resultado.
