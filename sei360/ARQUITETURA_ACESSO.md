# SEI360 — Decisão de Arquitetura (Fase 3: servidor em EasyPanel)

**Status:** decidido, condicionado a aceites formais (seção 2)
**Data:** 18/08/2026
**Substitui:** nada. **Altera:** `SPECS.md` §2 e §7 (reescrita obrigatória no mesmo commit do primeiro deploy)
**Evidência de base:** coleta de 18/08/2026 (`_coletas/sei_sesab_2026-08-18.json`, 1.165 registros) e `_logs/coleta_20260818.log`, verificados na escrita deste documento

---

## 1. Decisão em uma frase

O EasyPanel hospeda **painel, banco, autorização e regras de triagem**; a **coleta continua rodando na estação Windows da titular da credencial**, executada por um agente local que pergunta ao servidor quando há janela devida — de modo que **nenhuma senha do SEI, nenhum cookie de sessão e nenhum navegador existem dentro do container**.

> **Nota de 07/09/2026 — revogado em parte, em 21/08/2026 (ver §6.0).** A frase acima descreve só a **coleta**, que continua exatamente assim. Deixou de valer para a **busca avançada**: desde 21/08/2026 o container passou a rodar Chromium e Playwright, e a credencial de quem busca é decifrada em memória ali dentro (§6.0, §3.5, §3.6). Nenhuma senha do SEI e nenhum navegador existiam no container até 21/08; hoje existem, para a busca — nunca para a coleta.

Formulação negativa, que é a que importa: *quem tomar o servidor leva a base coletada — grave, notificável — e não leva a capacidade de agir no SEI em nome de ninguém.*

---

## 2. O que muda em relação ao SPECS.md e o que exige ACEITE POR ESCRITO

### 2.1 O que muda no SPECS

| Trecho | Situação |
|---|---|
| §2, linhas 21-25 — "a sessão do SEI mora no navegador do próprio usuário e nunca sai dele" | **Mantida na substância, reescrita na forma.** A sessão continua morando num navegador na estação; deixa de ser o navegador *interativo* do usuário e passa a ser o Chromium do coletor **na mesma máquina, com a mesma credencial, sob a mesma fronteira de disco**. Nenhum componente remoto recebe senha, cookie, semente TOTP ou material de sessão. |
| §2, tabela "Descartado, sem gradação", linha 1 (servidor guardando senha do SEI) | **NÃO revogada. Continua valendo, e o desenho não a toca.** |
| §2, tabela, linha 2 (conta de serviço institucional única) | **NÃO revogada.** Só voltaria à mesa na via 3.2 (seção 3.6), e por ato do órgão, nunca por decisão de engenharia. |
| §2, tabela, linha 3 (cookie de sessão no servidor) | **NÃO revogada. Não há volume de perfil no container.** |
| §2, tabela, linha 4 (campo de senha do SEI em tela nossa) | **NÃO revogada.** A tela de login do SEI360 pede senha **do SEI360**, com rótulo e aviso explícitos. |
| §7, linha 151 — "sem servidor, o dado não sai da máquina do usuário… razão de as fases 1 e 2 não terem backend" | **Esta é a única premissa que cai.** Passa a existir backend, com dado pessoal em repouso fora da estação. Exige base legal, registro de tratamento e as medidas da seção 9. |
| §3.2, regras duras #1 a #8 | **Intactas e agora também vinculantes para o schema** (seção 4) e para o agendador (seção 7). |
| §5, motor de triagem | **Migra para o servidor, calculado na consulta.** `dias_na_unidade` continua proibido como coluna. |
| §6, isolamento | **Vira pré-requisito de deploy**, não item de roadmap (seção 8). |

Não apresentar isto como continuidade técnica das fases 1-2: **é a Fase 3, declarada**, e o SPECS precisa dizer isso por extenso.

### 2.2 Aceites e atos exigidos ANTES do primeiro Dockerfile

*(Colunas Responsável e Prazo acrescentadas em 07/09/2026 — nenhuma pessoa nem data está registrada em documento ou banco algum para A0–A6; ver `PLANO_EXECUCAO_2026-09-07.md` §2.6. Preenchidas com placeholder até existir registro.)*

| # | Ato | Quem assina | Bloqueia o quê | Responsável | Prazo |
|---|---|---|---|---|---|
| **A0** | **Rotação da senha do SEI da titular** (ação, não aceite — ver 2.3) | titular | tudo | [a nomear] | [a datar] |
| **A1** | Termo de isolamento por unidade (§6, leitura A como fronteira, B como apresentação) — **texto exato na seção 8** | gestor da unidade + titular | qualquer endpoint que devolva carteira | [a nomear] | [a datar] |
| **A2** | Termo de imputação nominal — ciência de que a trilha do SEI passará a conter atos de máquina em nome da titular — **texto exato na seção 6.6** | titular + gestor | primeira coleta orquestrada pelo servidor | [a nomear] | [a datar] |
| **A3** | Ato do órgão designando a SESAB **controladora**, com finalidade e encarregado; **contrato de hospedagem no CNPJ do órgão** | SESAB | provisionamento do host | [a nomear] | [a datar] |
| **A4** | Base legal registrada + registro das operações (art. 37) + RIPD simplificado | encarregado | exposição no Traefik | [a nomear] | [a datar] |
| **A5** | **Lista nominal** de quem tem conta no painel do EasyPanel e no host, com MFA obrigatório nessas contas | admin de infraestrutura | exposição no Traefik | [a nomear] | [a datar] |
| **A6** | Decisão datada sobre **local do host** — (a) VPS BR contratado pelo órgão ou (c) servidor interno. **(b) fora do Brasil descartado por decisão** (seção 9.6) | SESAB/TIC | provisionamento do host | [a nomear] | [a datar] |

### 2.3 Contradição a registrar sem suavizar

A operação de hoje **já opera fora do SPECS**: existe **uma credencial em texto puro no bloco CONFIG** de `C:\Claude\sei_sistema\painel_sesab\automacao_sei.js`, de login nominal de pessoa física, e um contexto Chromium persistente (`_perfil_sei`) com cookie de sessão. O diretório não tem `.gitignore` nem `.dockerignore` e contém, lado a lado, o `.js` com a credencial, o perfil com a sessão, `_coletas` com a base pessoal e o `painel_sesab.html` com os 1.165 registros embutidos.

Consequências que este documento fixa:

1. **A senha deve ser considerada comprometida.** Ela já esteve em texto puro em disco não cifrado por decisão de projeto, e portanto em qualquer cópia do diretório, backup da estação ou ferramenta que tenha lido o arquivo. **A rotação (A0) é o passo zero do plano**, anterior a qualquer código novo — proteger um segredo já vazado não é proteção.
2. **A existência da rotina atual não é precedente autorizador.** "Já roda assim" não substitui A1-A6.
3. O desenho escolhido **não melhora** a custódia na estação; ele impede que ela seja **replicada** em infraestrutura de terceiro. A melhoria local (CONFIG vazio + Credential Manager) é item datado da Fatia 0, não subproduto do deploy.

---

## 3. Arquitetura

### 3.1 Visão

```
ESTAÇÃO WINDOWS (titular)                 EASYPANEL (Traefik + Docker)
┌──────────────────────────────┐          ┌──────────────────────────────┐
│ Task Scheduler (a cada 30min)│          │ sei360-web  (App service)    │
│   └─> sei360_agente.py       │  HTTPS   │   Flask + gunicorn           │
│        GET /api/agente/tarefa├─────────>│   /login /api/* /status      │
│        POST inicio/heartbeat │  pull    │   SQLite em /data            │
│        POST resultado (gzip) │ (só saída│   SEM Playwright             │
│   └─> coletor_sesab.py       │  da rede │   SEM SEI_USUARIO/SEI_SENHA  │
│        Chromium + perfil      │  interna)│   SEM volume de perfil       │
│        credencial via stdin  │          └──────────────┬───────────────┘
│   PNGs de falha ficam AQUI   │                         │ append-only
└──────────────┬───────────────┘                         v
               │ HTTPS                          destino de auditoria
               v                                fora do host (seção 9.4)
        sip.seibahia.ba.gov.br
```

O servidor **nunca** fala com `sip.seibahia.ba.gov.br`. Com isso somem, de uma vez, alcance de rede, DNS split-horizon da PRODEB, latência sobre milhares de requisições, risco de bloqueio de faixa de datacenter, `shm_size`/`ipc:host`, seccomp, sandbox do Chromium e build pesado de imagem Playwright. Sobra a questão jurídica do host, que é a que realmente decide.

> **Nota de 07/09/2026.** O diagrama e o parágrafo acima descrevem só o caminho da **coleta**, que continua exatamente assim — o servidor de fato nunca fala com o SEI para coletar. Desde 21/08/2026 existe um segundo caminho, o da **busca avançada** (§6.0), em que o MESMO container roda Chromium/Playwright e fala diretamente com o SEI da instância buscada. "SEM Playwright" no diagrama acima descreve `sei360-web` antes de 21/08; hoje a mesma imagem também executa `atendente.py`, com Playwright — ver §3.5, §3.6 e §3.6-bis ("Dois serviços, se a memória apertar").

### 3.2 Serviços no EasyPanel

| Serviço | Tipo | Recursos | Réplicas |
|---|---|---|---|
| `sei360-web` | **App service** (Swarm serve) | ~~256 MB / 0,5 vCPU~~ **mínimo 2 GB** *(corrigido 07/09/2026: desde 21/08/2026 a imagem inclui Chromium/Playwright para a busca — ~0,45 GB por busca simultânea, ver §3.6-bis; a premissa "não há Chromium" não vale mais)* | 1 hoje; escalável quando o banco sair para Postgres |
| banco | **SQLite em volume**, no próprio `sei360-web` | — | — |

**Postgres do EasyPanel: não provisionar agora.** É 1.165 linhas por coleta, um único processo escritor. Provisiona-se quando e se `sei360-web` precisar de mais de uma réplica.

### 3.3 Portas e domínio

- Container escuta `8000` (gunicorn, `-w 2 --threads 4`, `--timeout 60`).
- Traefik publica `443` com Let's Encrypt.
- **Enquanto o segundo fator do painel não estiver ARMADO (seção 5.7): middleware de restrição por IP do órgão ou VPN.** HTTPS garante que dado de saúde trafega cifrado até quem quer que tenha achado a URL — não é autenticação. *(Nota de 07/09/2026: o segundo fator existe no código desde 25–27/08/2026 — §3.5-bis — mas nasce desligado; a redação anterior dizia "não houver", como se não existisse. A restrição de origem continua obrigatória até alguém armar a política.)*
- CSP fechada: `default-src 'self'; connect-src 'self'; font-src 'self' data:; script-src 'self'`.

### 3.4 Volumes

| Caminho | Conteúdo | Retenção | Backup |
|---|---|---|---|
| `/data/db` | `sei360.db` (SQLite/WAL) | vida do sistema | **cifrado, com chave custodiada FORA do painel do EasyPanel** |
| `/data/snapshots` | JSON bruto recebido, gzipado (~2,5 MB/dia crus) | **30 dias**, expurgo por job | idem |

**Não existe** volume de perfil de navegador **para a coleta** — a coleta continua na estação. *(Nota de 07/09/2026: para a busca, existe sim, desde 21/08/2026 — `/dados/_perfil_sei`, dentro deste mesmo volume; ver §3.5, §3.5-bis e §6.0. A frase original valia em 18/08 e não foi atualizada quando a busca migrou para o container.)* **Não existe** volume de screenshots — `falha_login.png` e `falha_coleta.png` são tela cheia do Controle de Processos, com nomes, logins e anotações livres; **ficam na estação**, expurgados em 7 dias pelo agente, e o servidor recebe apenas nome do arquivo e carimbo, para o operador saber onde olhar.

### 3.5 Variáveis de ambiente

**Estas nunca existiram no código, e o documento as pediu por meses:**

```
SEI360_DB=...            NÃO É LIDA POR NADA. O caminho sai de SEI360_DADOS.
SEI360_SNAPSHOTS=...     NÃO É LIDA POR NADA.
FERIADOS_BA=...          NÃO É LIDA POR NADA.
SMTP_* / AUDIT_SINK_*    NÃO SÃO LIDAS POR NADA (o espelho de auditoria não existe).
```

Ficam registradas como ausência porque o modo de falha é silencioso: o operador
define, o processo ignora e nada reclama. A auditoria de 19/08/2026 já apontou
isto; o documento só foi corrigido em 25/08/2026.

**O que o código LÊ DE FATO** (medido com grep sobre `os.environ` em todos os
`.py` do servidor):

```
TZ=America/Bahia
SEI360_DADOS=/dados                      # raiz do volume; o banco é <ela>/sei360.db
SEI360_SEGREDO=<32B aleatórios>          # `SEI360_SECRET_KEY` também é aceita
SEI360_FORCAR_HTTPS=1                    # quando o proxy não manda X-Forwarded-Proto
SEI360_CHAVE_MESTRA=<32B base64>         # AES-256-GCM do cofre — SEM ELA não há busca
SEI360_BUSCAS_SIMULTANEAS=2              # teto de MEMÓRIA: ~0,45 GB por busca
SEI360_ATENDENTE=1                       # 0 desliga o executor de busca neste container
SEI360_COLETA_SERVIDOR=0                 # 1 liga a coleta diária p/ modo servidor (nasce OFF — §3.7)
SEI360_ACOMPANHAMENTO_SERVIDOR=1         # 0 desliga SÓ o acompanhamento; por padrão segue a linha acima
SEI360_LOG_ARQUIVO=1                     # 0 desliga o diário em /dados/log (ver diario.py)
SEI360_DIAG_TOKEN=<32+ caracteres>       # LIGA a rota /diag?t=… ; sem ela a rota não existe
SEI360_COLETOR=/app/painel_sesab/coletor_sesab.py
SEI_PERFIL_DIR=/dados/_perfil_sei        # perfil do navegador, no volume
SEI_SEM_SANDBOX=1                        # so em container (ver abaixo)
SEI_UNIDADE_ORIGEM=SESAB/SAIS/DGGUP/DGESS  # a unidade de LOTACAO da titular
SEI_ESQUECER_APOS_LOGIN=1                # o atendente define, por execucao
PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
PORT=8000

SEI360_COLETAS=/dados/_coletas           # so para `semear.py --coleta` e ingestao
SEI360_RESUMOS=/dados/_resumos/resumos.json   # manual; o padrao e caminho Windows

SEI360_BASE_URL=https://painel.seu.dominio  # endereco PUBLICO; monta o link de recuperacao
SEI360_EMAIL_TETO_DIA=60                 # teto PROPRIO de envios/dia (padrao 60)
SEI360_EMAIL_RESERVA=20                  # dos 60, os ultimos 20 so para CODIGO de acesso
SEI360_EMAIL_FALSO=<arquivo>             # NAO DEFINA EM PRODUCAO — ver abaixo
```

**`SEI360_EMAIL_FALSO` e so para teste, e a tela grita quando ela esta ligada.**
Definida, ela faz o envio GRAVAR uma linha JSON no arquivo apontado em vez de
sair pela rede. Existe porque o servidor das suites roda em outro processo —
trocar a funcao no processo do teste nao o alcancaria — e porque um teste que
dependesse do Resend estar no ar mediria o Resend, nao o SEI360.

Em producao ela nao pode existir: um sistema que acha que manda e-mail e nao
manda e pior que um sistema sem e-mail nenhum. Por isso `email_saida.ler_config`
devolve o caminho e a tela `/admin` estampa **CAIXA FALSA LIGADA** com o arquivo
em que as mensagens estao caindo.

## 3.5-bis. E-mail de saida (Resend) — recuperacao de senha e segundo fator

**O que o dono precisa fazer, e nesta ordem:**

1. Criar a conta no Resend e **verificar um dominio proprio** (`resend.com/domains`).
   Exige tres registros de DNS: `MX` em `send` -> `feedback-smtp.<regiao>.amazonses.com`
   (prioridade 10), `TXT` em `send` com `v=spf1 include:amazonses.com ~all`, e `TXT`
   em `resend._domainkey` com o valor DKIM. DMARC e recomendado, nao exigido.
   Costuma verificar em ~15 min, mas propagacao de DNS pode levar **ate 72 h**.
2. Gerar a chave (`re_...`) e salva-la em `/admin` -> Acesso por e-mail.
3. Preencher o remetente, `Nome <caixa@dominio-verificado>`.
4. **Mandar o teste.** So depois disso a recuperacao e o segundo fator aceitam
   ser ligados.

**`onboarding@resend.dev` NAO serve para operar.** Ele so entrega para o e-mail
DONO da conta Resend; para qualquer outro destinatario a API devolve `403
validation_error`. Um "testei e chegou" com ele nao prova nada sobre os
`@saude.ba.gov.br`.

**Dominio nao verificado nao degrada: recusa.** E `403` sincrono em 100% dos
envios — nao e "cai no spam". O mesmo vale se a verificacao se perder depois.

**Limites do plano gratuito:** 100 e-mails por dia, 3.000 por mes, 10 requisicoes
por segundo por equipe. Um segundo fator gasta um e-mail por LOGIN, nao por
pessoa.

**O User-Agent nao e cortesia.** Medido em 27/08/2026 contra a API real: o
Cloudflare na frente do Resend **bane a assinatura padrao do `urllib`**
(`Python-urllib/3.12`) e devolve `403` com corpo `text/plain` "error code: 1010",
sem a requisicao chegar na Resend. `email_saida.USER_AGENT` existe por isso.

**A saida de emergencia.** O segundo fator e a unica peca capaz de fechar o
sistema para todos ao mesmo tempo. Quando o envio para, quem tem acesso ao
servidor roda, sem e-mail e sem painel:

```bash
python emergencia.py estado
python emergencia.py desligar-fator2
python emergencia.py senha <email>
```

**Contas cujo dominio nao recebe correio sao barradas na ARMACAO, nao na
entrada.** `acesso.salvar_politica` recusa ligar o segundo fator enquanto houver
conta ATIVA do papel escolhido com endereco em dominio reservado (`.local`,
`.invalid`, `.test`, `.localhost`, `.example`). Esta instalacao nasceu com tres
contas em `@sei360.local` — ligar o fator para elas seria tranca-las para sempre.

**`exige_fator2` olha SO a politica.** Uma versao anterior tambem perguntava se o
e-mail estava saudavel e desligava o fator quando nao estava: como `guardar_chave`
zera o teste de proposito, **rotacionar a chave desligava o segundo fator de todo
mundo em silencio**. Armado e armado; se o codigo nao puder sair, a entrada
FALHA com o motivo na tela, e quem desliga desliga de proposito.

**`SEI_PERFIL_DIR` passou a ser a PASTA-MAE, nao o perfil.** O `atendente.py`
monta, por execucao, `<ela>/u<usuario_id>-<instancia>`. Com um perfil so, a busca
de B reaproveitava a sessao do SEI de A — `goto(LOGIN)` nem caia em `login.php` —
e o SEI gravava as consultas de B com o nome de A, enquanto o cofre registrava
"B usou a credencial". A atribuicao nominal, que e o custo que o §6.0 assumiu,
quebrava por dentro: nem o log do SEI nem o nosso diziam a verdade.

**`SEI_ESQUECER_APOS_LOGIN=1` tira a senha do volume.** `SEIAuto.credencial()`
grava `{usuario,senha}` com `btoa` no `localStorage`, que vive no perfil, que no
servidor vive no VOLUME — e base64 e ofuscacao, nao cifra. Com esta variavel o
coletor apaga a credencial logo depois do login e **mantem o cookie**, que e o
que evita relogar (e relogar e onde o segundo fator aparece). Quem a define e o
`atendente`, por execucao, porque so ele pode reenviar a credencial por stdin.
**Na estacao ela nao existe**: la a coleta agendada roda sem stdin e depende do
`localStorage`.

**`SEI_SEM_SANDBOX=1` e do Dockerfile, nao do EasyPanel.** O sandbox do Chromium
usa namespaces de usuario; em container sem `SYS_ADMIN`, e com
`unprivileged_userns_clone` desligado (padrao em muito host), ele falha no start
— e a falha aparece so na PRIMEIRA BUSCA: o build passa e o healthcheck fica
verde. Junto vai `--disable-dev-shm-usage`, porque o `/dev/shm` padrao do Docker
tem 64 MB e e ali que o Chromium poe memoria compartilhada. Quem isola aqui e o
container, e a pagina carregada e o SEI. **Na estacao a variavel nao existe e o
sandbox continua ligado** — la o navegador roda no Windows da pessoa.

As duas ultimas so importam em ingestao manual (`python ingestao.py`). O padrao
delas e um caminho `C:\Claude\...` que nao existe no container — inofensivo
enquanto ninguem ingere a mao la dentro, e confuso no dia em que alguem tentar.

**`SEI360_SEGREDO` não protege a sessão.** Não há `session[...]` nem `flash()`
nesta aplicação: a sessão é um token aleatório guardado como SHA-256 em
`sessoes`, e o CSRF é um token aleatório em cookie comparado com o do
formulário. `secret_key` existe porque o Flask quer uma. Definir a variável
antecipa o dia em que alguém usar `session` — não fecha buraco de hoje.

Acrescentadas em 21/08/2026, com a busca no servidor (§6.0):

```
SEI360_CHAVE_MESTRA=<32B base64>         # AES-256-GCM do cofre. SEM ELA nada de busca.
SEI360_BUSCAS_SIMULTANEAS=2              # teto de MEMÓRIA: ~0,45 GB por busca
SEI360_ATENDENTE=1                       # 0 desliga o executor neste container
SEI360_COLETOR=/app/painel_sesab/coletor_sesab.py
SEI_PERFIL_DIR=/dados/_perfil_sei        # CAMINHO do perfil, no volume
PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
```

**Ausência declarada, e escrita como comentário no `docker-compose`/config:** não existem `SEI_USUARIO` nem `SEI_SENHA`, nem qualquer variável que **carregue** credencial do SEI. Variável de ambiente de PaaS **não é cofre** — é legível em `docker inspect`, em `/proc/1/environ` e no `.env` que o EasyPanel guarda no host.

**Ressalva a registrar, porque contradiz a redação anterior deste parágrafo:** `SEI_PERFIL_DIR` existe hoje, e o texto de antes dizia que `SEI_PERFIL` não existiria. A variável carrega um **caminho**, não um segredo — mas o caminho aponta para o `_perfil_sei`, que o §6.2 (item 4) classifica como **material de credencial**, já que `SEIAuto.credencial()` grava com `btoa`, e base64 é ofuscação. Quem lê essa variável já tem o host; o que ela muda é que agora **há** perfil de navegador dentro do volume do VPS. Isso é consequência do §6.0, não descuido.

**`SEI360_CHAVE_MESTRA` é o segredo que não pode morar no painel do EasyPanel.** É ela que abre a senha do SEI de todo mundo. Guardá-la na mesma tela em que se lê o log e se abre o Terminal do container anula o cofre — o §4 da tabela de volumes já dizia "chave custodiada FORA do painel do EasyPanel", e continua valendo. Trocar a chave com credenciais já guardadas as torna **indecifráveis**, e o cofre não tem como avisar antes.

### 3.6 Imagem e build

- Base `python:3.12-slim`. Dependências: `flask`, `gunicorn`, `cryptography`, `openpyxl` e — desde 21/08/2026 — **`playwright`, com Chromium instalado na imagem** (§6.0). Tudo o mais é stdlib.
- **Contexto de build = a raiz do repositório**, não `sei360/servidor/`: o coletor e os dois `.js` vivem em `painel_sesab/`, que é irmão de `sei360/`, e `COPY` não enxerga fora do contexto.
  `docker build -f sei360/servidor/Dockerfile -t sei360 .`
- **Desde 04/09/2026 a raiz é um repositório próprio** — [`github.com/doni010520/sei360`](https://github.com/doni010520/sei360), com `sei360/` e `painel_sesab/` como irmãos, local `C:\Claude\SEI360\` nesta máquina. Antes disso a raiz era `sei_sistema/`: uma pasta de trabalho compartilhada com o pipeline HECC/FESF-SUS (outro projeto, sem relação), nunca versionada como um repositório só do SEI360. `git init` ali teria levado dezenas de arquivos daquele outro projeto — inclusive um repositório Git aninhado dele, com credencial não protegida pelo próprio `.gitignore` dele.
- **Build em CI, publicação em registry, deploy por digest imutável.** Nunca `Dockerfile` construído no VPS. *(Não cumprido hoje: o EasyPanel constrói no host. Fica como dívida, não como fato.)*
- `.dockerignore` que **nega tudo e reabre duas pastas**, na forma escalonada (`*` / `!sei360` / `sei360/*` / `!sei360/servidor`) — `*` seguido de `!sei360/servidor` não funciona, porque um diretório excluído não é percorrido. Resultado medido: **100 arquivos, 8,8 MB**, contra 27.449 na raiz.
- **`automacao_sei.js` NÃO pode mais ser excluído**, ao contrário do que este parágrafo dizia: o coletor não roda sem ele. Ou ele entra **com o bloco CONFIG vazio**, ou não há build.
- **Teste de build que falha:** `python sei360/servidor/conferir_contexto.py` — lista o que entraria, exige os arquivos que o build precisa e **recusa (saída 1)** banco, `_perfil_sei`, `.env` ou qualquer arquivo com CONFIG preenchido. Aponta arquivo e linha, **nunca o valor**.
- **Guard equivalente em execução:** `atendente.capacidade()` recusa executar busca quando a imagem carrega credencial em texto puro. Uma imagem assim funcionaria perfeitamente — é esse o problema.

### 3.6-bis Receita do EasyPanel (HostGator)

| campo | valor |
|---|---|
| Source | **GitHub** — `doni010520/sei360`, branch `main`, Auto Deploy ligado (constrói a cada push) |
| Build context | `.` (a raiz) |
| Dockerfile | `sei360/servidor/Dockerfile` |
| Port | `8000` |
| Volume | `/dados` (nomeado, não bind — bind de host chega `root:root`) |
| Memória | **mínimo 2 GB**: ~1 GB para painel + Chromium base, ~0,45 GB por busca simultânea |

Variáveis obrigatórias: `SEI360_CHAVE_MESTRA`, `TZ=America/Bahia`, e
`SEI360_FORCAR_HTTPS=1` se o proxy não mandar `X-Forwarded-Proto` (sem ela o
cookie de sessão sai sem `Secure` num site em HTTPS).
Recomendada: `SEI360_SEGREDO` (ver §3.5 sobre o que ela protege — e o que não).
Opcionais com padrão sadio: `SEI360_BUSCAS_SIMULTANEAS=2`, `SEI360_ATENDENTE=1`.
`SEI360_DADOS` e `SEI360_COLETOR` já vêm no `ENV` do Dockerfile.

**E-mail (Resend) — só se for ligar recuperação de senha e/ou segundo fator,
ver §3.5-bis.** `SEI360_BASE_URL=https://seu.dominio` é obrigatória para ligar a
recuperação (o link do e-mail sai dela, nunca do `Host` da requisição — ver
§3.5-bis). `SEI360_EMAIL_TETO_DIA` e `SEI360_EMAIL_RESERVA` têm padrão sadio (60
e 20). **`SEI360_EMAIL_FALSO` NUNCA entra aqui** — é só de teste, e a tela de
administração denuncia se ela estiver definida.

**O perfil do navegador é POR PESSOA.** `SEI_PERFIL_DIR` é a pasta-mãe; o
`atendente` monta `<ela>/u<usuario_id>-<instancia>` por execução. Com um perfil
só, a busca de B reaproveitava a sessão do SEI de A e o SEI gravava as consultas
de B com o nome de A — a atribuição nominal, que é o custo assumido no §6.0,
quebrada por dentro.

**Antes do primeiro build**, nesta ordem, porque a ordem é o que impede o vazamento:

1. **Rotacionar a senha do SEI.** A atual esteve em texto puro em disco (§6.2 item 1 — cumprido em 01/09/2026).
2. Semear a nova no perfil da estação (`SEIAuto.credencial(...)`) — sem isso, esvaziar o CONFIG faz a coleta agendada falhar no login, em silêncio.
3. Esvaziar o bloco CONFIG do `automacao_sei.js`.
4. `python sei360/servidor/conferir_contexto.py` — tem de sair **0**. Ele confere o `.dockerignore` da raiz do repositório, não o órfão que ainda existe em `sei360/servidor/` (ver abaixo).
5. Só então `git push` — ou empacotar, se o Source do EasyPanel ainda for **Upload**.

**GitHub (padrão desde 04/09/2026).** O EasyPanel clona
[`github.com/doni010520/sei360`](https://github.com/doni010520/sei360) sozinho a cada
deploy — não existe "empacotar" nesse fluxo, e o caminho local (`C:\Claude\SEI360\`
nesta máquina) só importa para editar e dar `git push`. Do lado do EasyPanel: Source
→ GitHub → repositório `doni010520/sei360`, branch `main`, build path `.` (a raiz),
Dockerfile `sei360/servidor/Dockerfile`, **Auto Deploy ligado** — sem isso a troca de
configuração não vale nada, o serviço continua servindo a imagem antiga depois de um
push. O passo 4 continua obrigatório **antes de cada push**: nada do lado do EasyPanel
impede um CONFIG preenchido de subir, o único portão é local, e é manual.

**Upload direto (sem Git, mantido como alternativa manual):
`python sei360/servidor/conferir_contexto.py --empacotar`.**
Ele roda o MESMO portão do passo 4 e só escreve o ZIP se sair 0 — zipar a pasta
pelo Explorer levaria o banco de produção, `_perfil_sei` e a senha em texto puro
para o armazenamento do EasyPanel antes de o Docker existir, e um upload não tem
"desfazer". Sai em `sei360_upload_easypanel.zip` (ao lado da raiz do repositório,
nunca dentro dela), pronto para o Source → Upload do EasyPanel.

**O `.dockerignore` que vale é o da RAIZ do repositório** — hoje
`C:\Claude\SEI360\.dockerignore`, não o de `sei360/servidor/`, que ficou órfão
quando o contexto mudou de lugar e hoje não tem regra nenhuma, só um aviso dizendo
isso. **Em 04/09/2026, ao criar o repositório novo, esse arquivo não foi trazido
junto** — só o `.gitignore` (git e Docker filtram coisas diferentes: um decide o
que entra no histórico, o outro o que entra na imagem). `conferir_contexto.py`
teria barrado o próximo build com um erro explícito, mas a lacuna foi encontrada
e fechada antes do primeiro push por GitHub, não em produção. Ele **não aceita
comentário no fim da linha**: `**/_dados   # o banco` vira um padrão literal que
não casa com nada. Foi assim que o banco de produção, a sessão do SEI e a chave
do cofre passaram a entrar na imagem sem ninguém ver, da primeira vez. O
comentário vai na linha de cima, sempre, e o `conferir_contexto.py` recusa quem
não seguir.

**Dois serviços, se a memória apertar:** a mesma imagem sobe duas vezes, com o mesmo volume. No serviço do painel, `SEI360_ATENDENTE=0`; no de execução, o comando vira `python atendente.py`. A reivindicação em `atendente.pegar()` é atômica (`UPDATE ... WHERE estado='pedida'`), então nenhuma busca é executada duas vezes.

### 3.7 Worker no container — IMPLEMENTADO em 21/08/2026 para a BUSCA

Este parágrafo dizia "NÃO implementar agora" e condicionava tudo a uma conta de serviço. A condição **não foi cumprida** — o que houve foi a decisão do dono de hospedar em VPS próprio e aceitar o custo. Ver **§6.0**.

**O que roda no container hoje:** a **busca avançada** (`atendente.py`), com a credencial nominal do cofre.

**Desde 08/09/2026, também a coleta diária de quem está em modo servidor** (`coleta_servidor.py`) — atrás de um interruptor que nasce **desligado** (`SEI360_COLETA_SERVIDOR`, ao contrário de `SEI360_ATENDENTE`): a busca já tinha decisão formal antes de subir; a coleta automática ainda não teve carga real medida (6 mesas × N pessoas de Chromium num VPS de 2 GB continua sem número), e ligar por padrão repetiria o erro que este próprio parágrafo já registrou uma vez. Duas defesas herdadas do atendente, não inventadas de novo: a coleta só começa com a busca ociosa, e enquanto roda segura uma vaga do MESMO semáforo de memória — os dois moram na mesma thread de processo de propósito (ver o cabeçalho de `coleta_servidor.py`), porque o semáforo não atravessa processo do gunicorn. No máximo uma coleta por vez no container.

**Desde 12/09/2026, também o ACOMPANHAMENTO** (`acompanhamento_servidor.py`), e este não é uma melhoria — é um motor que **não existia**. O módulo de Acompanhamento subiu em 11/09/2026 com um caminho só para a metade caro (ler no SEI processo que não está em mesa nenhuma da pessoa): as duas rotas `/api/agente/acompanhamento`, que existem para uma ESTAÇÃO buscar trabalho por HTTP. Medido pela leitura do código: `acompanhamento.pendentes` e `.receber` tinham **um chamador cada**, essas rotas, e `coleta_servidor.py` não conhecia o módulo. Neste container, portanto, o processo acompanhado entrava na lista, ficava `novo` e **nunca era lido** — a tela dizia "aguardando primeira leitura" para sempre, e a frase era verdadeira. Nenhuma linha vermelha em lugar nenhum.

O laço novo é o de `coleta_servidor.py` com três diferenças que importam, e todas as três são ganho que a estação não tem:

| | estação | container |
|---|---|---|
| instalações por ciclo | **uma** — ela faz login numa por vez, e o item da outra ficava `novo` para sempre (medido: três ciclos) | **as duas**, no mesmo ciclo: o cofre guarda credencial por instalação e o atendente já mantém um perfil de navegador por pessoa **e** por instalação |
| quando lê | a cada 30 min, por relógio próprio | **depois da coleta do dia** — é ela que responde de graça o que está na carteira (`reaproveitar`); ler antes é pagar 6 requisições por processo pelo que ia chegar sozinho. Item recém colado não espera (o gatilho "ao adicionar"), e ninguém espera depois das 12h |
| quanto custa perguntar | sobe o Chromium para descobrir | um `COUNT(*)` (`acompanhamento.quantos_pendentes`), e a vaga de memória só é tomada depois dele |

**Interruptor: o mesmo da coleta.** `SEI360_COLETA_SERVIDOR` liga os dois, porque a decisão é uma — "este container lê o SEI sozinho, com senha guardada". Um segundo interruptor seria uma segunda coisa para esquecer, e a falha de esquecer é silenciosa (item parado, tela dizendo a verdade). Quem precisar desligar só o acompanhamento tem `SEI360_ACOMPANHAMENTO_SERVIDOR=0`. As defesas de memória são as de lá, não reinventadas: só começa com busca e coleta ociosas, segura uma vaga do MESMO semáforo, no máximo uma leitura por vez, e mora no processo que venceu a eleição do atendente.

### Como saber, de fora, como o servidor está rodando

Em 15/09/2026 a coleta ficou **três dias úteis** sem rodar, e descobrir o motivo dependeu de alguém abrir o painel do provedor e copiar o log do container à mão. Duas coisas faltavam, e as duas existem agora.

**O diário** (`diario.py`). O mesmo texto que vai para o `stdout` — as linhas de `atendente de busca:`, `coleta(servidor):`, `acompanhamento(servidor):`, a ingestão e o log de acesso do gunicorn — também vai para `/dados/log/sei360-AAAA-MM-DD.log`, no volume, que é o que sobrevive a redeploy. Nada é tirado do `stdout`. O arquivo passa por `_sem_segredo` (senha, token, chave de API e `infra_hash` de sessão nunca entram), tem prazo de 14 dias e o **expurgo aplica o prazo** — arquivo no volume é dado guardado como qualquer outro. `SEI360_LOG_ARQUIVO=0` desliga.

**O motivo da decisão.** Os laços da coleta e do acompanhamento imprimem por que NÃO rodaram, uma linha por **mudança** de motivo — não por passada, senão seriam 1.440 linhas iguais por dia, que é a outra forma de não dizer nada.

**A rota `/diag`.** Só existe quando `SEI360_DIAG_TOKEN` tem 24 caracteres ou mais; a comparação é em tempo constante e token errado responde **404**, não 403 — para quem não tem, a rota não existe. Toda consulta e toda recusa ficam no `log_acesso`. Ela devolve: interruptores (só se estão definidos, nunca o valor), estado do motor (executor no container e neste worker, vagas, capacidade), agentes e agendamentos, últimas execuções com motivo, coleta por unidade, alertas, buscas com veredito, acompanhamento agregado, travas de conta e as últimas linhas do diário (teto de 500).

**O que ela NÃO devolve**, e por decisão: valor de variável secreta, texto de processo (especificação, anotação, interessados) e os **filtros** de uma busca — o filtro é a pergunta de uma pessoa e pode citar nome. O que o diagnóstico precisa é do veredito e do motivo.

**O que ela não alcança:** o que acontece antes de o processo subir. Se o container não inicia, só o log do Docker conta.

**O que continua na estação:** modo estação inteiro (senha nunca sai da máquina da pessoa), e qualquer coleta ou acompanhamento enquanto `SEI360_COLETA_SERVIDOR` estiver desligado. As duas rotas do agente continuam de pé e atendem essas contas — `acompanhamento_servidor._candidatos` ignora de propósito quem está em `modo_coleta='estacao'`, porque a senha dessa conta não está aqui.

**O que continua verdadeiro deste parágrafo:** o único caminho que traz execução para dentro do container **sem** colocar credencial nominal de terceiro num host alugado continua sendo a **conta de serviço institucional criada formalmente pela TIC/PRODEB**, com escopo de leitura, termo de uso e log próprio. Isso deixou de ser pré-requisito e passou a ser **dívida**: enquanto não existir, cada busca feita pelo VPS é imputada, no log do SEI, à pessoa cuja credencial o cofre guardou.

---

## 4. Modelo de dados

SQLite/WAL, `busy_timeout=5000`. Tipos em notação SQLite.

### 4.1 Proibições de esquema, escritas por extenso no DDL

```sql
-- NÃO EXISTE tabela de credencial do SEI. A ausência é decisão de arquitetura,
-- não lacuna. Ver DECISAO_ARQUITETURA.md §6. Não "completar o que faltou".
-- PROIBIDO: coluna dias_na_unidade ou qualquer métrica derivada de tempo.
--           Grava-se marco_unidade; o número é calculado na exibição (§3.2 #6).
-- PROIBIDO: qualquer coluna com href/URL contendo infra_hash (§3.2 #2).
-- PROIBIDO: constante de unidade em variável de ambiente (§3.2 #5).
```

### 4.2 Identidade e acesso

```sql
usuarios(
  id INTEGER PK, email TEXT UNIQUE NOT NULL,        -- normalizado minúsculo
  nome TEXT, senha_hash BLOB, senha_sal BLOB,
  senha_algo TEXT DEFAULT 'scrypt-n15-r8-p1',
  senha_trocada_em TEXT,                            -- ISO+offset; NULL = 1º acesso
  papel TEXT CHECK(papel IN ('admin','gestor','servidor')),
  ativo INTEGER DEFAULT 1, origem TEXT,             -- 'admin' | 'auto_snapshot'
  criado_em TEXT, ultimo_login_em TEXT,
  falhas_seq INTEGER DEFAULT 0, bloqueado_ate TEXT)

usuario_unidade(usuario_id INTEGER, unidade TEXT, principal INTEGER,
                concedida_por INTEGER, concedida_em TEXT,
                PRIMARY KEY(usuario_id, unidade))

sessoes(id INTEGER PK, usuario_id INTEGER, token_sha256 BLOB UNIQUE,
        criado_em TEXT, expira_em TEXT, ultimo_uso_em TEXT,
        ip TEXT, user_agent TEXT, lembrar INTEGER, revogada_em TEXT)

tentativas_login(id INTEGER PK, email TEXT, ip TEXT, ts TEXT, sucesso INTEGER)

log_acesso(id INTEGER PK, ts TEXT, usuario_id INTEGER, acao TEXT,
           alvo TEXT, unidade TEXT, ip TEXT, espelhado INTEGER DEFAULT 0)
-- alvo guarda IDENTIFICADOR (id_sei, protocolo, id de usuário). Nunca conteúdo.
```

### 4.3 Agentes e execução

```sql
agentes(id INTEGER PK, nome_estacao TEXT, dono_usuario_id INTEGER,
        token_sha256 BLOB, unidades_esperadas TEXT,      -- JSON
        versao_agente TEXT, ultimo_contato_em TEXT,
        ativo INTEGER, pausado_motivo TEXT,
        higiene_config_vazio INTEGER, higiene_verificada_em TEXT,
        credencial_titular TEXT,                          -- nome civil, para o rodapé
        credencial_login_mascarado TEXT,                  -- ex.: l****@saude.ba.gov.br
        credencial_aceite_ref TEXT, credencial_aceite_em TEXT,
        credencial_rotacionada_em TEXT, credencial_validade_ate TEXT)
-- credencial_* é METADADO. Nenhuma coluna guarda senha, hash de senha do SEI,
-- cookie ou material de sessão.

enrolamentos(codigo_sha256 BLOB PK, agente_id INTEGER, criado_por INTEGER,
             expira_em TEXT, usado_em TEXT)

agendamento(agente_id INTEGER PK, janelas TEXT,           -- JSON: ["07:30","19:00"]
            tz TEXT DEFAULT 'America/Bahia', tolerancia_min INTEGER DEFAULT 90,
            max_entregas_janela INTEGER DEFAULT 2,
            dias TEXT DEFAULT 'uteis',                    -- 'uteis' | 'todos'
            ativo INTEGER, motivo_inativo TEXT, desarmado_em TEXT)

execucao(id INTEGER PK, agente_id INTEGER, janela TEXT,   -- ISO da janela devida
         estado TEXT CHECK(estado IN ('entregue','em_curso','concluida',
              'sem_dados','bloqueada','infra','travada','perdida','nao_executada')),
         gatilho TEXT,                                    -- 'janela' | 'manual_admin'
         gatilho_por INTEGER, entregue_em TEXT, iniciado_em TEXT,
         heartbeat_em TEXT, terminado_em TEXT, duracao_s INTEGER,
         exit_code INTEGER, alertas TEXT, log_resumo TEXT,
         png_falha TEXT)                                  -- nome do arquivo NA ESTAÇÃO
```

### 4.4 Snapshot — **por unidade**, não por execução

```sql
snapshot(id INTEGER PK, execucao_id INTEGER, unidade TEXT NOT NULL,
         coletado_em TEXT NOT NULL,        -- ISO COM OFFSET, carimbado na estação
         coletados INTEGER,                -- contagem reportada pela mesa (ex.: 218)
         unicos INTEGER,                   -- únicos nesta mesa (ex.: 214)
         sem_historico INTEGER, truncado_restante INTEGER,
         estado TEXT CHECK(estado IN ('candidato','corrente','rejeitado','expirado')),
         suspeito INTEGER, motivo TEXT, arquivo TEXT, sha256 TEXT, bytes INTEGER,
         UNIQUE(execucao_id, unidade))
```

A divergência **218 coletados / 214 únicos** em COMASUP (18/08, "4 já vistos") não é erro: é processo presente em mais de uma mesa. **O gate compara `coletados`**, não o `COUNT` do campo `mesa_coleta` — senão a dedup entre mesas é lida como perda.

> **Nota de 07/09/2026.** O `UNIQUE(execucao_id, unidade)` acima presume uma `execucao` de um `agente` — mas `agentes.dono_usuario_id` pode ser NULL (coleta de bootstrap, compartilhada por toda a unidade; ver §7.3 e `SPECS.md` §5-nonies). O esquema não impede isso, e não deveria: é o estado inicial de qualquer instalação nova.

### 4.5 Conteúdo

```sql
processo(snapshot_id INTEGER, id_sei TEXT, protocolo TEXT, mesa_coleta TEXT,
         tipo_processo TEXT, atribuido_login TEXT, atribuido_nome TEXT,
         marco_unidade TEXT,               -- data-marco; NUNCA dias_na_unidade
         nivel_acesso TEXT, hipotese_legal TEXT,
         visualizado INTEGER, retorno INTEGER, doc_incluido INTEGER,
         marcador TEXT, marcador_cor TEXT, urgente INTEGER, sobrestado INTEGER,
         sem_historico INTEGER, truncado INTEGER,
         ultimo_movimento TEXT, documentos INTEGER,   -- CONTAGEM, nunca conteúdo
         PRIMARY KEY(snapshot_id, id_sei))

processo_mesa(snapshot_id INTEGER, id_sei TEXT, mesa TEXT, atribuido TEXT)

processo_texto(snapshot_id INTEGER, id_sei TEXT,
               especificacao TEXT, anotacao TEXT, anotacao_autor TEXT,
               anotacao_data TEXT, interessados TEXT, acompanhamento TEXT,
               PRIMARY KEY(snapshot_id, id_sei))
-- Tabela separada de propósito: é onde estão os campos com nome de paciente.
-- Só é lida no endpoint de DETALHE, para usuário da unidade dona. Nunca em lista.

resumo(id_sei TEXT PK, unidade TEXT, texto TEXT,
       descrito_em TEXT,                  -- data da coleta que o resumo descreve
       gerado_em TEXT, gerado_por TEXT)

alerta(id INTEGER PK, ts TEXT, tipo TEXT, severidade TEXT, execucao_id INTEGER,
       unidade TEXT, texto TEXT, reconhecido_por INTEGER, reconhecido_em TEXT)
```

Índices: `processo(snapshot_id, mesa_coleta)`, `processo(snapshot_id, atribuido_login)`, `snapshot(unidade, estado, coletado_em)`, `log_acesso(ts)`.

---

## 5. Autenticação do SEI360

### 5.1 Princípio

**Conta do painel não é conta do SEI.** Senha própria, jamais a do SEI (§2, linha 4 da tabela). O rótulo do campo diz **"senha do SEI360"** e há aviso curto sob ele: *"esta não é a sua senha do SEI. O SEI360 nunca pede sua senha do SEI."*

### 5.2 Hash e verificação

- `hashlib.scrypt(n=2**15, r=8, p=1, dklen=64)`, sal de 16 bytes por usuário, comparação com `hmac.compare_digest`.
- E-mail inexistente roda contra **hash-isca**, para não vazar existência de conta por diferença de tempo. Resposta 401 idêntica em ambos os casos.
- Sem `bcrypt`/`passlib` — a stdlib resolve e uma dependência a menos é uma superfície a menos.

### 5.3 Política de senha

Mínimo 12 caracteres; bloqueio das 200 senhas mais comuns; troca obrigatória no primeiro acesso (`senha_trocada_em IS NULL` redireciona antes de qualquer outra rota). Sem expiração periódica — expiração forçada empurra para senha derivada e não é o risco desta aplicação.

### 5.4 Bloqueio por tentativa (não existe hoje em lugar nenhum)

- **Rate limit por IP:** 20 tentativas/min → `429`.
- **Lockout por conta:** 5 falhas em 15 min → `bloqueado_ate = agora + 15 min` → `423` com os minutos restantes. Reincidência dentro de 24 h → 60 min.
- Submit recebe `disabled` durante o envio (hoje duplo clique dispara duas autenticações).
- Estados de erro no front, todos código novo: `401` genérico, `423`, `429`, `5xx`/timeout, mais `aria-invalid` e a classe `.field-in.err` (o `:focus-within` já está pronto).

### 5.5 Sessão

Server-side, não cookie assinado. Token opaco `secrets.token_urlsafe(32)`; o banco guarda **apenas o SHA-256**. Cookie `sei360_sess`: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.

- Expiração absoluta **12 h**; inatividade **30 min** encerra.
- A caixa **"Lembrar este dispositivo"** — hoje morta, o id `remember` não aparece uma única vez no JS — passa a ser campo do POST: marcada, expiração absoluta de **30 dias** com renovação deslizante. Nunca para papel `admin`.
- Logout revoga a linha; troca de senha revoga **todas** as sessões do usuário.
- CSRF por double-submit (cookie legível + header `X-CSRF`), validado em tempo constante, em toda mutação.

### 5.6 Papéis

| Papel | Vê | Pode |
|---|---|---|
| `servidor` | carteira das unidades vinculadas | ler, filtrar, exportar o próprio escopo |
| `gestor` | mesmas unidades, com a visão por atribuído dos colegas (o que o SEI já lhe mostra) | idem + reconhecer alertas da unidade |
| `admin` | **nenhuma carteira por padrão** | usuários, agentes, rearme de agendamento, abrir janela extra, ver PNG de falha, ler o log de acesso |

**Administrar não é ler.** Um `admin` que precise de carteira recebe vínculo de unidade explícito, registrado em `usuario_unidade` com `concedida_por`.

### 5.7 Gestão de usuários e provisionamento

- **Auto-provisionamento semeado pelo snapshot:** o primeiro acesso é liberado para e-mail institucional que **já apareça** em `atribuido_login` ou `processo_mesa.atribuido` do snapshot corrente, com a unidade derivada dali; o admin apenas aprova. Isso existe porque a alternativa — admin cadastrar um a um os **58 atribuídos nominais distintos** da carteira, entregando token fora de banda — não acontece na prática, nascem 2 ou 3 contas, e o painel volta a ser ferramenta de um gestor só, caso em que o servidor não se justificava.
- Fora dessa lista: criação manual pelo admin, com token de uso único válido 48 h.
- `/admin/usuarios`: criar, **desativar (nunca apagar — o log referencia)**, redefinir senha, vincular/desvincular unidade, revogar sessões ativas. Toda ação administrativa vai para `log_acesso`.
- **Sem segundo fator ARMADO no painel** — *(nota de 07/09/2026: esta linha dizia "sem segundo fator na v1", como se ele não existisse; o código foi escrito em 25–27/08/2026, §3.5-bis. O que continua verdade é que ele nasce desligado e nenhuma política foi armada até hoje)* —, e isso é dito ao decisor em vez de escondido. Compensação enquanto não existir: restrição de origem no Traefik (IP do órgão ou VPN) e sessão curta. **O painel do EasyPanel, esse sim, exige MFA e lista nominal (A5)** — ele é chave-mestra sobre tudo o que está descrito aqui.

---

## 6. Custódia da credencial do SEI

### 6.0 REVOGAÇÃO DO §6.1 E DO §3.7 — 21/08/2026

**Quem decidiu:** o dono do sistema, por escrito, nesta data.
**O que decidiu:** hospedar o SEI360 em **VPS próprio, EasyPanel na HostGator**, e executar a **busca avançada no servidor**, não na estação.
**Consequência direta:** a imagem passa a ter Chromium e Playwright, e o `atendente.py` decifra a credencial do cofre para entregá-la ao navegador. O texto do §6.1 abaixo — "o container não tem Playwright, não tem Chromium, não tem perfil" — **deixa de ser verdade nesta data**.

**O que a decisão custa, repetido aqui porque foi dito antes dela e continua valendo:**

- A credencial do SEI é **nominal**. Tudo o que este container fizer, o SEI registra com o nome da pessoa. Não há como distinguir, no log do SEI, uma consulta feita por ela de uma consulta feita por quem tomou o container.
- O conjunto de quem consegue ler a credencial deixa de ser o do §6.3 (titular, admin local, backup da estação) e passa a **somar** o conjunto que o próprio §6.3 já nomeava como o custo do desenho em container: **painel do EasyPanel, root do host, snapshot de disco e de RAM do provedor, e qualquer RCE nesta aplicação**. O §6.3 dizia que essa redução "é a razão de ser desta arquitetura". A razão de ser foi revogada; o conjunto maior é o preço aceito.
- **O segundo fator piora, não melhora.** A SESAB anuncia 2FA no login. Na estação há uma pessoa para digitar o código. No VPS não há ninguém. Por isso `SEI_PERFIL_DIR` aponta para o **volume**, e não para a imagem: é a sessão persistida que evita relogar a cada redeploy. Se o 2FA passar a ser exigido a cada login, **este desenho para de funcionar sozinho**, e nenhuma linha de código resolve isso — automatizar segundo fator continua fora de escopo, por decisão anterior que esta revogação **não** toca.
- O teto de buscas simultâneas passa a ser **memória**: ~0,45 GB por busca, medido em produção no sistema irmão. `SEI360_BUSCAS_SIMULTANEAS` (padrão 2) existe para o container não morrer por OOM — e o OOM killer costuma escolher o gunicorn, não o Chromium.

**O que esta revogação NÃO alcança:**

- Não revoga a exigência de **rotacionar** a senha que esteve em texto puro no `CONFIG` do `automacao_sei.js`. Continua comprometida.
- Não autoriza senha em `argv` nem em variável de ambiente. Continua **stdin, e só stdin** (`atendente.executar`).
- Não dispensa o §6.6 (imputação visível). Se algo mais, ela fica **mais** necessária: a pessoa precisa saber que o servidor age com o nome dela.
- Não transforma o §3.7 em obsoleto. A **conta de serviço institucional** continua sendo o único desenho em que ninguém coloca credencial nominal de terceiro num host alugado, e continua sendo o que se deve pedir à TIC/PRODEB. A revogação diz que não se espera por ela para operar — não que ela deixou de ser melhor.

### 6.1 Onde ela fica

**Revogado em 21/08/2026 — ver §6.0.** Texto original, mantido para que a mudança seja legível:

> Na estação Windows da titular, e em nenhum outro lugar. O container não tem Playwright, não tem Chromium, não tem perfil, não tem variável e não tem tabela.

**Vale hoje:** a credencial fica **cifrada no cofre** (AES-256-GCM, chave em `SEI360_CHAVE_MESTRA`, AAD `usuario_id|sistema|login`) e é decifrada **em memória, no instante do uso**, para a busca executada no servidor. O modo `estacao` continua existindo e continua sendo o desenho em que a senha nunca chega ao servidor — quem escolhe é a pessoa, em `/configuracao`.

### 6.2 Mecanismo concreto (Fatia 0)

1. **Rotacionar a senha no SEI** (A0) — a atual está comprometida por ter residido em texto puro em disco.
2. `automacao_sei.js` passa a ter o **bloco CONFIG vazio** no arquivo em disco e no repositório. Guard no início do agente recusa executar se detectar CONFIG preenchido (checa presença, **jamais imprime valor**).
3. A credencial passa a viver no **Windows Credential Manager** (alvo `SEI360/coleta`, escopo do usuário, protegido por DPAPI). O agente lê no momento da execução e passa ao `coletor_sesab.py` **por stdin**, em JSON — nunca por `argv` (visível em `ps`/Process Explorer), nunca por variável de ambiente, nunca por arquivo temporário.
4. O coletor semeia via `pg.evaluate("(c)=>SEIAuto.credencial(c.u,c.s)", ...)`. Vale registrar sem eufemismo: `SEIAuto.credencial()` grava com `btoa` em `localStorage` — **base64 é ofuscação, não cifra** —, logo `_perfil_sei` continua sendo material de credencial.
5. `_perfil_sei` fica em **disco cifrado (BitLocker), ACL restrita ao usuário, fora de qualquer pasta sincronizada em nuvem e fora de backup não cifrado**. Procedimento escrito de "esquecer": apagar `_perfil_sei` + `SEIAuto.esquecer()`, acionado na saída da titular ou na revogação do agente.

### 6.3 Quem consegue ler mesmo assim (a nomear em A2)

- A própria titular.
- Quem tiver **administrador local ou acesso físico** à estação.
- Quem tiver acesso a **backup ou imagem** da estação.
- Quem tiver acesso ao **Credential Manager do perfil Windows** enquanto a sessão dela está aberta.

Esse conjunto tem de ser nomeado — "a equipe de TI" não é resposta. É um conjunto **menor** que o do desenho em container (que somaria: painel do EasyPanel, root do host, snapshot de disco e de RAM do provedor, registry, e qualquer RCE na app), e essa redução é a razão de ser desta arquitetura.

### 6.4 Segredos que ficam no servidor (todos nossos, todos revogáveis por nós)

1. Senha do painel por pessoa (scrypt).
2. **Token do agente** — gerado no servidor, exibido uma única vez, persistido só como SHA-256. Quem rouba o token consegue **gravar** um snapshot; jamais **ler** o SEI nem agir nele.
3. `SEI360_SECRET_KEY` (sessão/CSRF) e credenciais de SMTP e do espelho de auditoria.

### 6.5 Rotação, 2FA e revogação

- **Rotação:** procedimento escrito — titular troca no SEI, atualiza o Credential Manager, roda `sei360_agente.py testar`, o painel registra `credencial_rotacionada_em`. Sem essa etapa, a coleta cai em `exit 3` e fica muda.
- **2FA:** **PROIBIDO** implementar leitor de TOTP, semente em variável, bypass ou fila de código por chat/e-mail — seria guardar os dois fatores no mesmo lugar, contornando controle de segurança do órgão. No dia em que a SESAB ligar segundo fator obrigatório, a coleta agendada morre. **Aqui a queda é suave e é a única vantagem real deste desenho:** a titular abre o SEI na própria estação, digita o código, e o agente segue na janela seguinte com o perfil vivo. Num container seria fim de linha.
- **Revogação:** revogar o token do agente **não** revoga nada no SEI. A revogação real é **trocar a senha no SEI**, e o painel diz isso em texto na tela de administração do agente.

### 6.6 Imputação visível — TEXTO EXATO do termo A2

> **Nota de 07/09/2026.** O item 5 abaixo, antes desta data, afirmava sem ressalva que "o painel hospedado não [possui a senha] nem pode obtê-la" — verdade em 18/08/2026, quando este termo foi escrito, e **falsa desde 21/08/2026** para quem usa o modo servidor (§6.0). Reescrito abaixo para dizer a verdade nos dois modos. Nenhum termo já assinado com a redação anterior perde validade por este ajuste; é a redação que passa a valer para novas assinaturas.

> **TERMO DE CIÊNCIA — OPERAÇÃO AUTOMATIZADA COM CREDENCIAL NOMINAL (SEI360)**
>
> Eu, [NOME COMPLETO], matrícula [Nº], lotada em [UNIDADE], titular do login [LOGIN] do SEI Bahia, declaro estar ciente e de acordo com o seguinte:
>
> 1. Uma rotina automatizada (SEI360) passará a acessar o SEI utilizando **a minha credencial nominal**, em janelas programadas, na estação de trabalho [IDENTIFICAÇÃO DA ESTAÇÃO], sob minha guarda.
> 2. **Todos os acessos realizados por essa rotina serão registrados no log do SEI em meu nome**, ainda que eu não os tenha praticado pessoalmente. Estou ciente de que isso afeta o não-repúdio dos registros de acesso associados ao meu login.
> 3. A rotina **altera a unidade ativa da minha sessão** ao percorrer as mesas de trabalho. Se eu estiver utilizando o SEI no mesmo momento, a unidade ativa poderá mudar sem ação minha.
> 4. A duração medida de uma execução completa foi de **14 minutos e 47 segundos** (coleta de 18/08/2026, 6 mesas, 1.165 processos). As janelas programadas são [HORÁRIOS], [Nº] vezes por dia útil.
> 5. Minha senha do SEI **não é armazenada em texto legível em lugar nenhum**. Se eu optar pelo modo **estação**, ela fica exclusivamente nesta estação, no Cofre de Credenciais do Windows, e o painel hospedado não a possui. Se eu optar pelo modo **servidor** (para a busca avançada), ela fica **cifrada no cofre do painel** (AES-256-GCM) e é **decifrada em memória, apenas no instante em que uma busca minha é executada**; nesse caso o painel hospedado **passa a ser capaz de obtê-la**, e um conjunto maior de pessoas passa a ser capaz de lê-la: quem tiver acesso ao painel administrativo do EasyPanel, root do host, cópia de disco ou de memória feita pelo provedor, ou qualquer falha de execução remota de código nesta aplicação (§6.0 e §6.3 detalham esse conjunto e o comparam ao da estação).
> 6. **Nenhum usuário do painel SEI360 pode disparar coleta em meu nome.** Somente o agendamento interno e, quando necessário, um administrador nomeado abrindo janela extra — registrada com o nome dele.
> 7. Comprometo-me a comunicar imediatamente à equipe do SEI360 qualquer troca da minha senha do SEI, ciente de que a troca interrompe a coleta.
> 8. Estou ciente de que posso revogar esta autorização a qualquer momento, por escrito, e de que a revogação efetiva do acesso automatizado se dá pela troca da minha senha no SEI.
>
> Salvador/BA, __/__/____ — [assinatura da titular] — [assinatura do gestor da unidade]

O painel exibe, **em rodapé permanente**: *"coleta operando com a credencial de [titular], aceite de [data], rotacionada em [data]"*. A imputação fica visível na tela, não escondida no log — senão a frase "o servidor não tem senha" vira amnésia coletiva sobre a credencial que continua na estação.

---

## 7. Agendamento

### 7.1 Gatilho e direção

O agente **sempre puxa**. A estação está atrás de NAT e firewall corporativo, nunca aceita conexão de entrada, e essa direção única é também o que impede o servidor de virar canal de comando sobre a máquina que detém a credencial.

- Task Scheduler (tarefa existente `SEI_SESAB_Coleta`) passa a chamar **o agente**, não o coletor, a cada 30 min dentro da faixa operacional.
- O agente pergunta `GET /api/agente/tarefa`; **quem decide se há coleta devida é o servidor**.
- Autenticação de cada chamada: Bearer sobre HTTPS **mais** HMAC-SHA256 do corpo com o token (`X-SEI360-Ts`, `X-SEI360-Assinatura`), rejeitando timestamp fora de ±5 min e nonce já visto. É `hmac` da stdlib e sobrevive a um proxy do órgão que termine o TLS.
- **Sem autoatualização do agente.** O `/tarefa` informa `versao_disponivel` e o painel mostra "agente desatualizado"; a troca é comando manual. Autoatualização transformaria o servidor em canal de execução remota de código na única máquina que tem a credencial — exatamente o que este desenho evita.
- **Teto local, no lado que detém a credencial:** o agente recusa executar mais de `N` vezes por dia e fora da faixa horária configurada **localmente**, independentemente do que o servidor pedir. É o único limite que sobrevive ao comprometimento do servidor.

### 7.1-bis Os três trabalhos do ciclo, e a ordem entre eles

Desde 11/09/2026 o agente tem três trabalhos por batida, nesta ordem:

1. **`GET /api/agente/busca`** — a busca avançada, primeiro porque **alguém está
   olhando a tela**. Uma coleta de 14 minutos na frente de uma busca de 20 segundos
   transforma "pesquisar" em "pesquisar amanhã".
2. **a coleta**, pelo `GET /api/agente/tarefa`.
3. **`GET /api/agente/acompanhamento`** — os processos acompanhados que estão fora da
   carteira (§5-quindecies de `SPECS.md`).

O acompanhamento vem **por último, e isso é decisão medida, não arranjo**. Ele
começou na frente da coleta, pelo mesmo argumento da busca, e a revisão desmontou:
não existe plantão de acompanhamento (`atender()` só chama `buscar`), a latência já
é de 0 a 30 min de qualquer jeito, e há trava de uma leitura por dia por item — a
posição na frente comprava zero. Em troca, expunha a coleta diária a dois modos de
falha provados: linha de resultado corrompida levantando `JSONDecodeError` não
capturado (e `stderr` funde no mesmo pipe sem buffer, então uma linha do Chromium no
meio de um envelope de dezenas de KB basta), e filho pendurado segurando a Trava
indefinidamente, porque o teto de relógio só é avaliado quando chega uma linha. Nos
dois casos a coleta do dia não era pedida, e a batida seguinte via o PID vivo e saía.

Hoje o acompanhamento roda depois da coleta, dentro de `try/except`, e a asserção que
a suíte cobra é essa: **a coleta é pedida mesmo quando o acompanhamento falha.**

Contrato dos dois endpoints novos, mesma autenticação dos demais (Bearer + HMAC):

| | |
|---|---|
| `GET /api/agente/acompanhamento` | devolve `{ler, instancia, protocolos[], perfil}` ou `{ler:false, motivo}`. **Não** manda a nota que a pessoa escreveu (texto de gente, pode citar nome), nem o tamanho da lista. |
| `POST /api/agente/acompanhamento` | recebe `{instancia, leituras[]}`. O **dono e a instalação saem do token**, nunca do envelope: a instância do corpo é apenas conferida, e divergência devolve 409 sem gravar. Estado inventado é recusado, não traduzido. |

**Recuo:** falha técnica não carimba leitura, então o item continua pendente — e sem
contador isso o reofereceria a cada 30 min. Uma falha sistemática que não derrube a
sessão custaria 100 processos × 5 requisições × 34 ciclos ≈ 17 mil requisições por
dia contra o SEI do órgão, três vezes a coleta inteira, sem nada perceber. Por isso
`acompanhado.tentativas`: três entregas sem resposta no mesmo dia e o item descansa
até o dia virar, com o motivo dito no log do agente.

### 7.2 Janelas — números medidos, não estimados

Medição real de 18/08/2026 (`_logs/coleta_20260818.log`):

| Trecho | Relógio | Duração |
|---|---|---|
| início do wrapper | 07:30:01 | — |
| `evaluate` da coleta | 07:30:28 → 07:45:15 | **14m47s** |
| CESS | 07:30:56 → 07:38:51 | 7m55s |
| COMASUP | 07:38:51 → 07:41:06 | 2m15s |
| UMA-CMA | 07:41:06 → 07:45:15 | 4m09s |
| DGESS / ASTEC / GT-HTLV | — | segundos |
| fim, `EXIT=0` | 07:45:19 | total 14m47s |

Toda estimativa anterior de "~4 min" está errada por cerca de 3,7x, e com ela caem as contas derivadas de latência, de lease e de viabilidade de frequência.

- **Janela 1: 07:30, dias úteis.** Consolidada.
- **Janela 2: DECISÃO PENDENTE (P2).** Recomendação: **19:00**, fora do expediente. Motivo: a segunda coleta é uma sessão de robô de ~15 min com a credencial nominal da titular, **alterando a unidade ativa da sessão real dela**, em pleno horário de trabalho. Se a segunda janela ficar em horário de expediente, ela precisa constar explicitamente no item 3 do termo A2.
- Frequência máxima: **2x por dia útil**. De hora em hora seria carga desproporcional contra a PRODEB a partir de um único login.

### 7.3 Concorrência

- **A entrega da tarefa é o lock**, feita em transação: o servidor só entrega se houver janela devida, se não houver execução `entregue`/`em_curso` para aquele agente, e se a janela ainda não fechou com sucesso. `max_entregas_janela = 2` é teto absoluto.
- `flock` local no agente impede duas execuções sobre o mesmo perfil (perfil Chromium é single-writer; duas execuções o corrompem).
- **Uma unidade pertence a um agente NOMINAL.** Publicação fora de `unidades_esperadas` é recusada e vira alerta. *(Nota de 07/09/2026: exceção que já existia e não estava dita aqui — a coleta de bootstrap, sem dono, `dono_usuario_id=NULL`, fica COMPARTILHADA por toda a unidade até cada pessoa passar a coletar a própria; não é lacuna, é o estado inicial de qualquer instalação. Ver `SPECS.md` §5-nonies e `LEIAME_EASYPANEL.md` §3.)*
- **Zero retry.** Retry por fora do processo reintroduz o retry cego que o disjuntor de duas quedas existe para impedir, e cada tentativa derruba a sessão real.

### 7.4 Watchdog — o sexto estado que nenhum desenho anterior tratava

`page.evaluate` **não** é governado por `set_default_timeout`: prova empírica, o `evaluate` de 18/08 rodou 887 s sob um "teto" de 600 s sem levantar exceção. Se a PRODEB descartar um pacote em vez de mandar RST, um `fetch` nunca resolve, um dos 4 slots de concorrência nunca libera, o `evaluate` nunca retorna e **não existe exit code nenhum** — nem 0, nem 1, nem 2, nem 3, nem 4.

Correções obrigatórias, todas na estação:

1. **`AbortController` por `fetch`** em `automacao_sei.js`, com timeout individual. Hoje não há nenhum.
2. **Kill por relógio de parede no processo filho**: `subprocess` com timeout de **30 min** (≈2x a duração medida) → `SIGKILL`/`TerminateProcess` → **exit sintético 5 = travada**.
3. O **heartbeat monitora o processo do coletor**, não o do agente. O agente pode estar vivíssimo enquanto o filho está pendurado — monitorar o pai é monitorar o processo errado.
4. Estado `travada` no banco, com alerta próprio.

### 7.5 Códigos de saída — sete casos, não "falhou"

| Código | Significado | Tratamento |
|---|---|---|
| **0** | coletou sem alertas | **não publica direto** — vai ao gate (7.6). "Sem alerta" não é "completo" |
| **1** | coletou com alerta (2FA, sessão, captcha, `(N falhas)`, "ficou de fora") | passa pelo gate; o que promover entra com `suspeito=1` e **selo visível em tela** com o texto do alerta; alerta ativo. **Não repete** — pode ser 2FA, e repetir derruba sessão |
| **2** | rodou e não devolveu dados | nada é gravado; snapshot anterior permanece **com a data antiga em destaque**; alerta; no máximo uma nova entrega na mesma janela |
| **3** | login não concluiu | **pausa o agendamento daquele agente**, exige rearme manual pelo admin. Jamais em loop: cada tentativa é login falho no log do SEI contra conta nominal e aproxima bloqueio da conta da servidora |
| **4** | infraestrutura da estação (Playwright ausente, arquivo faltando, navegador) | alerta para o **mantenedor**, não para o usuário do painel; nova tentativa só na janela seguinte |
| **5** | **travada** (novo, do watchdog) | mata o filho, registra `travada`, alerta, **não reabre a janela** |
| **—** | **`nao_executada`** (novo) | janela devida venceu sem nenhuma entrega: estação desligada, usuária deslogada, tarefa não disparada. É estado de primeira classe, não ausência de registro |

**Sobre `exit 3`, o diagnóstico é ambíguo hoje e isso queima a conta da titular.** `ORGAO='23'` é constante fixa e o campo `#selOrgao` só é preenchido se existir; se a PRODEB renomear o select ou renumerar a SESAB, o login falha em silêncio e o operador recebe um PNG de tela de login idêntico ao de senha errada — o caminho provável é "senha expirou", rotação desnecessária, nova tentativa, mais um login falho. Correções: **`exit 3` sai subdividido pela causa observável** (`3.1` órgão ausente/inesperado, `3.2` campo de senha ausente, `3.3` mensagem de credencial inválida, `3.4` prompt de 2FA, `3.5` captcha), a constante `ORGAO` é **validada pelo texto da opção** a cada execução, e o PNG de falha fica acessível em um clique no painel desde o dia 1.

### 7.6 Coleta parcial — gate de publicação POR UNIDADE

Este é o defeito que já mordeu o projeto: parcial não sai como `exit 2`, sai como 0 ou 1 e **tem cara de completa**.

**Envelope obrigatório (mudança de formato do JSON).** Hoje `coletor_sesab.py` lê `(dados[0] or {}).get('mesas_falhas') or []` — e o arquivo de **12/08 tem 20 registros e não possui as chaves `mesas_falhas`, `mesas_conta`, `sem_historico`, `truncado` nem `nivel_acesso`**, tendo saído com `EXIT=0`. Com `None`, a condição é falsa e o portão abre. O JSON passa a ser objeto com envelope no topo:

```json
{ "envelope": { "versao": 1, "coletado_em": "2026-08-18T07:45:15-03:00",
    "modo": "mesas", "registros": 1165, "exit_code": 0, "alertas": [],
    "mesas_conta": [...], "mesas_falhas": [],
    "por_mesa": { "SESAB/SAIS/DGGUP/DGESS/COMASUP":
      {"coletados":218,"unicos":214,"sem_historico":0,"truncado_restante":0} } },
  "processos": [ ... ] }
```

**Envelope ausente ou incompleto = REPROVA**, nunca "vazio". Validação estrita no envelope; validação **frouxa** nos registros, porque as chaves variam entre registros do mesmo arquivo.

**Gate, avaliado por unidade** (`snapshot.estado`: `candidato` → `corrente` ou `rejeitado`):

1. a unidade aparece em `mesas_falhas` → **rejeita**;
2. `coletados` da unidade **< 90% do `coletados` da corrente daquela unidade** → **rejeita**;
3. **piso absoluto:** unidade que tinha `> 0` e voltou `0` → **rejeita, sem percentual**;
4. `sem_historico`/`truncado_restante` acima do piso observado → **promove marcando**, com contador na tela.

Por que por unidade e não global: com **CESS = 625 de 1.165**, um gate global retém 625 linhas frescas por causa de uma mesa de 1 processo; no sentido inverso, perder **DGESS (20) + ASTEC (5) + GT-HTLV (1)** deixa o total em 97,8% e passa o gate com folga — e o servidor da ASTEC abre o painel, vê a carteira dele cair de 5 para 0, e recebe semáforo verde. *"Nada pendente"* é a coisa mais perigosa que um painel de triagem pode dizer.

Registro com falha entra como **pendente**, nunca como concluído nos totais (§3.2 #7). Nada de média, nada de fusão com o snapshot anterior.

### 7.7 Retenção do JSON

| Artefato | Onde | Retenção | Gatilho do expurgo |
|---|---|---|---|
| JSON bruto gzipado | `/data/snapshots` | **30 dias** | job diário no servidor |
| Linhas de `processo`/`processo_texto` | banco | **30 dias** além do corrente | job diário |
| `snapshot`/`execucao` (metadados) | banco | 90 dias | job diário |
| JSON e `.anterior.json` | estação | 7 dias | agente |
| `falha_*.png` | estação | **7 dias** | **gatilho próprio do agente, independente do sucesso da coleta** — o caminho que gera os PNGs é exatamente o caminho em que o resto não roda |
| `log_acesso` | banco + espelho | 180 dias | job diário |
| `tentativas_login` | banco | 30 dias | job diário |
| `resumo` (resumo de IA) | banco | **60 dias** | job diário — *linha ausente até 07/09/2026; o prazo já existia no código (`expurgo.py`, `DIAS['resumo']=60`, ver `PLANO_PRODUTO.md` Fatia 8) e não estava nesta tabela* |

### 7.8 Alerta de coleta atrasada — e o semáforo consciente de calendário

Isto não é hipótese: **não existe `_logs/coleta_20260814.log` nem `_coletas/sei_sesab_2026-08-14.json`**. Sexta-feira 14/08/2026, dia útil, a tarefa não disparou — e não é falha de coleta, é ausência de execução, porque o wrapper grava `INICIO` incondicionalmente. **Os dias 15 (sábado) e 16 (domingo) rodaram normalmente.** Perdeu-se o único dia da janela em que o SEI se move e coletou-se o fim de semana em que nada anda. Taxa base observada da estação: **1 falta em 6 disparos**.

Regras derivadas:

- `dias_na_unidade` é **calculado na consulta**, a partir de `marco_unidade` e do relógio `America/Bahia` — efeito desejado: um snapshot velho **envelhece visivelmente na tela** em vez de mentir com número congelado. Os **29 processos sem `marco_unidade`** aparecem como pendência própria, não somem das regras 9 e 10.
- `coletado_em` é **carimbado na estação como ISO com offset dentro do JSON**, nunca inferido de `mtime` — `mtime` não sobrevive a cópia entre volumes, ao gzip nem ao upload, e a idade do snapshot é a última defesa do desenho inteiro.
- **Semáforo verde só quando: a última janela ÚTIL devida foi cumprida, com `exit ≤ 1`, e o gate promoveu.** Com calendário de dias úteis e **feriados estaduais da Bahia** — senão o verde aparece num domingo (dado inútil) e o vermelho num feriado (correto por acidente).
- Idade do snapshot **por unidade**, em elemento fixo no topo da tela, não em rodapé. Acima da tolerância: tarja com *"coleta atrasada desde HH:MM de DD/MM"*.
- Alerta ativo por e-mail em `exit 1/2/3/4/5`, em `nao_executada` e em atraso. **Container não tem tela e ninguém lê log de container.**
- Só `admin` abre janela extra, registrada com `gatilho='manual_admin'` e o nome dele — e o efeito é apenas abrir a janela: o agente a executa no próximo poll, na estação, com a credencial da titular. **Nenhum usuário do painel consegue gerar movimento no SEI em nome de outra pessoa.**

---

## 8. Isolamento: por unidade x por atribuído

### 8.1 Recomendação

**Fronteira de segurança = UNIDADE (`mesa_coleta`). Filtro por ATRIBUÍDO = apresentação.** É a recomendação (A)+(B) do SPECS §6.

Por que (A) é defensável: os processos são da fila da unidade e os colegas já os veem no próprio SEI — esconder no painel o que a fonte mostra é teatro. Por que (B) **não** serve de fronteira: a distribuição é desigual (um responsável com 41 processos, mediana abaixo de 10) e o gestor veria quase nada; (B) como fronteira destrói o produto.

Implementação: `usuario_unidade` define o escopo, e **todo endpoint que devolve carteira monta `WHERE mesa_coleta IN (...)` no servidor** — nunca no JavaScript do cliente. As 4 consts embutidas no `painel_sesab.html` de 2,7 MB são contrato de arquivo único, um leitor, um estado; servidas pela rede, entregam a carteira inteira a quem abrir o DevTools.

**Correção de produto obrigatória:** o chip **"meus" nasce DESLIGADO**, e a triagem exibe contador fixo *"sem atribuído na sua unidade: N"*. **203 dos 1.165 processos não têm atribuído, 185 deles na UMA-CMA (62% da unidade)** — são exatamente os que a regra 3 do §5 classifica como "ação sua". Com o chip ligado por padrão, a maior pilha acionável da unidade fica fora da tela.

Três reforços que o dado real exige:

1. **Restrito (61 registros, todos com hipótese legal: 38 sigilo de licitação, 13 Lei estadual 12.618/2012 art. 18, 6 pela própria LGPD, 1 apuração):** regra do espelho — se o SEI não mostraria aquela linha àquele usuário, o painel também não mostra; `hipotese_legal` é exibida junto.
2. **`nivel_acesso` não pode ser a única regra de autorização:** os processos que citam nome civil de paciente estão **majoritariamente classificados como Público**. Por isso `processo_texto` é tabela separada, servida **só no detalhe, só para usuário da unidade dona**, nunca no payload de lista.
3. **Busca global por texto livre não existe como funcionalidade.** Procurar por nome de paciente não pode ser recurso do produto. Busca apenas dentro do escopo da unidade e por campos estruturados.

### 8.2 TEXTO EXATO do aceite (A1) a ser assinado

> **TERMO DE ACEITE — MODELO DE ISOLAMENTO DE ACESSO DO PAINEL SEI360**
>
> Referência: SEI360, Especificação Técnica (SPECS.md), seção 6 — "Isolamento".
>
> O pedido original de que "cada usuário só acesse os dados do seu usuário" admite duas leituras:
> **(A) por unidade** — cada usuário acessa a carteira de processos da(s) unidade(s) a que está vinculado, que é exatamente o que o SEI já lhe apresenta;
> **(B) por atribuído** — cada usuário acessa somente os processos atribuídos ao seu login.
>
> A equipe técnica recomenda **(A) como fronteira de segurança** e **(B) como filtro de apresentação**, pelas seguintes razões, que declaro ter compreendido:
>
> 1. A distribuição de processos por responsável é desigual (na carteira de referência, um responsável concentra 41 processos e a mediana está abaixo de 10). Adotar (B) como fronteira faria com que gestores e coordenações vissem uma fração mínima da carteira, inviabilizando o uso do painel para gestão da unidade.
> 2. Na carteira de referência, **203 de 1.165 processos não possuem atribuído**, sendo **185 deles em uma única unidade**. Sob (B) como fronteira, esses processos — precisamente os que o painel classifica como exigindo ação da unidade — não seriam visíveis a ninguém.
> 3. (A) não amplia o acesso existente: os processos da fila de uma unidade já são visíveis, no próprio SEI, a qualquer servidor lotado naquela unidade.
>
> **Declaro, portanto, aceitar que:**
>
> a) O painel SEI360 exibirá a cada usuário autenticado a carteira das unidades às quais ele estiver formalmente vinculado no sistema, e nada além disso. A filtragem é aplicada no servidor, em todos os pontos de acesso, incluindo exportações.
> b) O filtro "somente os meus processos" existirá como recurso de visualização, à escolha do usuário, e **não** como barreira de segurança.
> c) Processos classificados no SEI como Restritos só serão exibidos a usuários vinculados à unidade correspondente, acompanhados da respectiva hipótese legal.
> d) Campos de texto livre (especificação, anotações, interessados, observações de acompanhamento) somente serão exibidos na tela de detalhe, a usuários vinculados à unidade do processo, e **não** integrarão listagens nem exportações de escopo ampliado.
> e) **Não existirá busca por texto livre sobre a base local do painel.** *(Nota de 07/09/2026: desde 21/08/2026 existe busca avançada — ver `SPECS.md` §5-ter —, mas ela interroga o SEI diretamente, com a credencial de quem pergunta; a base local do SEI360 continua sem busca por texto livre. O resultado da busca não vira snapshot, não entra no poço, não cria linha em `processo` e não é servido a mais ninguém.)*
> f) O perfil de administrador do painel **não** confere acesso a carteira de nenhuma unidade; administrar contas e agentes não é ler processos.
> g) Todo acesso a processo será registrado em log próprio do painel (usuário, identificador do processo, data/hora e endereço de origem), com retenção de 180 dias.
>
> **Declaro ainda estar ciente de que este modelo contraria a leitura literal do pedido original**, conforme registrado na seção 6 do SPECS.md, e que este aceite é condição prévia à implementação de qualquer componente servidor do SEI360.
>
> Salvador/BA, __/__/____
> [gestor da unidade — nome, cargo, assinatura] — [titular da credencial de coleta — nome, assinatura]

---

## 9. LGPD

### 9.1 Inventário — o que a base realmente contém

Verificado na coleta de 18/08 (1.165 registros, 46 campos): **303 e-mails funcionais nominais**, **57 nomes civis completos**, **535 campos de texto livre** (614 marcadores, 269 anotações, 266 observações de acompanhamento, 345 listas de interessados), **61 registros de nível Restrito** com hipótese legal, e **5 processos que citam nome civil de paciente colado a condição ou tratamento — 4 deles em processos classificados como Público**. Nenhum CPF ou CNS formatado. O coletor grava `documentos` como **contagem**, nunca o corpo do documento.

Isso fixa o escopo: **base de dado pessoal de servidor, com dado sensível de saúde de cidadão em volume residual mas real**. Não é "só número de processo".

### 9.2 Base legal

- **Dado comum de servidor:** art. 23 c/c art. 7º, III (execução de política pública / competência legal do órgão).
- **Dado de saúde em texto livre:** **art. 11, II, "b"** (execução de política pública prevista em lei). **Não** a alínea "f" (tutela da saúde) — a finalidade do SEI360 é administrativa, não assistencial.
- **Consentimento é inadequado e não deve ser invocado** (art. 7º, §3º, assimetria com o poder público).
- Finalidade amarrada: **triagem da carteira processual**. Fica **proibido** reuso para avaliação de desempenho de servidor, cruzamento com outras bases ou consulta por nome de paciente.

### 9.3 Registro das operações (art. 37) — exigível, não boa prática

Na estação havia um arquivo e um operador. No servidor há **cinco operações com agentes e prazos distintos**: coleta na estação, transmissão ao servidor, gravação em volume, persistência em banco/exibição a N usuários, e expurgo. Registro mínimo por operação: finalidade, base legal, categorias de titular (servidor SESAB; cidadão citado em texto livre), retenção, destinatários e medidas de segurança.

### 9.4 Log de acesso — e o problema de quem audita o auditor

O painel **destrói a trilha de auditoria que o SEI tem** e precisa pôr algo no lugar (arts. 37 e 46; insumo do art. 48). `log_acesso` registra autenticação, logout, falha, consulta de detalhe e exportação — **identificadores, nunca conteúdo**.

Ressalva que precisa estar escrita: um log que mora no mesmo SQLite, no mesmo volume, sob o mesmo root, é **apagável por uma linha no Terminal do painel do EasyPanel sem deixar vestígio** — e é ali que se registraria quem consultou os processos com nome de paciente. Por isso: **espelho append-only para um destino que o administrador do EasyPanel não controla** (`AUDIT_SINK_URL`), com retenção declarada de 180 dias e alerta quando o espelho fica em atraso.

### 9.5 RIPD

**Não afirmar que é obrigatório por regra fixa** — a LGPD não impõe RIPD por hipótese automática; os arts. 38 e 32 permitem à ANPD determinar ou solicitar. Contra a obrigatoriedade: o volume de dado de saúde é residual. A favor: dado sensível + servidor exposto na internet + múltiplos usuários + credencial nominal formam risco combinado alto.

**Decisão: RIPD simplificado, como instrumento de accountability** (A4). No cenário (b) — host fora do Brasil — ele deixa de ser recomendável e vira **obrigatório de fato**, por ser o documento que sustentaria a decisão perante a ANPD. É mais um motivo para não ir por ali.

### 9.6 Local do host e o gatilho que torna (b) inaceitável

**O gatilho é estrutural e já está disparado:** a base contém **dado pessoal sensível de saúde** (5 registros verificados citando nome civil de paciente junto a condição), e o texto livre é imprevisível por natureza — não há como garantir que a próxima coleta não traga mais. Hospedar isso fora do Brasil é **transferência internacional de dado sensível por poder público (art. 33)**, e a lei não abre exceção por volume.

Vias do art. 33, na configuração realista:
- inciso I (país com nível adequado) — **fechado**: a ANPD não reconheceu nenhum país;
- inciso II — exige as **Cláusulas-Padrão Contratuais da Resolução CD/ANPD nº 19/2024**, cujo prazo de adequação de contratos venceu em agosto/2025 e que **nenhum VPS de prateleira assina** (contrata-se por termo de adesão não negociável);
- incisos III e IX (cooperação) — não descrevem hospedagem comercial.

**Conclusão: (b) descartada por decisão, não por preferência técnica.** Reforço convergente, secundário: com a duração medida de 14m47s, latência transatlântica sobre milhares de requisições sequenciadas a CONC=4 empurra a coleta para muito além da janela — mas esse não é o argumento decisivo.

> **Nota de 07/09/2026:** a pergunta abaixo foi **respondida de fato em 21/08/2026** pela decisão do dono (§6.0): via **(a)**, VPS na HostGator. O que segue pendente é registrar a **região** do host (tem de ser Brasil — ver a conclusão acima) e o contrato no CNPJ do órgão (A3). O texto original fica como registro da recomendação que não prevaleceu.

**DECISÃO (A6/P1) — (a) VPS BR contratado pelo órgão x (c) servidor interno.** Recomendação da época: **(c) > (a)**. Diferença que precisa ser dita: em VPS comercial o provedor tem acesso de hipervisor, o cliente **não controla cifragem de disco, não desabilita swap do host e não impede snapshot** — então (a) só é admissível se o provedor for declarado **operador com acesso efetivo**, em contrato no CNPJ do órgão (art. 39), e com o passivo minimizado em consequência disso. Só (c) tira o provedor da fronteira de confiança.

### 9.7 Minimização, elevada a regra de arquitetura

- **"Não baixar corpo de documento" deixa de ser acidente feliz e vira regra escrita e testada.** Nenhuma evolução pode puxar texto de documento para o servidor.
- `processo_texto` separada, servida só no detalhe e só para a unidade dona.
- **Redator de nome de paciente** antes da escrita, com honestidade sobre o limite: heurística por padrão léxico (`paciente <Nome>`, `Sr./Sra. <Nome>`) é **redução de risco, não anonimização do art. 12**, falha em nome sem marcador e **não substitui controle de acesso**.
- Backup do banco **cifrado, com chave custodiada fora do painel do EasyPanel** — cifrar backup com chave guardada no mesmo painel que guarda o dado não é cifrar.

### 9.8 Incidente

Plano de resposta com responsável nomeado e **prazo de 3 dias úteis da Resolução CD/ANPD nº 15/2024** para comunicar incidente relevante, contados da ciência. Na estação, um vazamento é um notebook; no servidor, é a base inteira de uma vez, com o dado sensível junto.

---

## 10. Plano de implementação em fatias

Cada fatia é entregável e testável isoladamente. **As fatias 0 a 2 rodam na estação e entregam valor sem nenhum servidor** — se os aceites travarem, o produto melhora mesmo assim.

### Fatia 0 — Higiene da credencial (bloqueia tudo)
Rotacionar a senha no SEI. CONFIG vazio no arquivo. Credencial para o Windows Credential Manager, lida pelo agente e passada por stdin. `.gitignore` e `.dockerignore`. Guard de boot que recusa executar com CONFIG preenchido. `_perfil_sei` em disco cifrado, ACL restrita, fora de sincronização em nuvem.
**Pronto quando:** `grep` no repositório e no diretório de trabalho não encontra credencial; a coleta roda normalmente com o CONFIG vazio; o guard aborta com exit 4 quando o CONFIG é preenchido de propósito num teste; a senha antiga não funciona mais no SEI.

### Fatia 1 — Sobrevivência da coleta: watchdog + envelope
`AbortController` por `fetch`; timeout de 30 min no subprocesso com kill e **exit 5**; envelope obrigatório no JSON com `coletado_em` ISO+offset e `por_mesa`; `exit 3` subdividido por causa; validação de `ORGAO` pelo texto da opção.
**Pronto quando:** um teste que bloqueia artificialmente uma requisição produz exit 5 em até 30 min, com log; um JSON sem envelope é recusado pelo próprio coletor; o log registra a causa específica quando o `#selOrgao` é renomeado num teste.

### Fatia 2 — O painel para de mentir (ainda local)
Idade do snapshot por unidade no topo; semáforo com calendário de dias úteis e feriados BA; selo de idade do resumo no card da lista e contador "N sem resumo"; chip "meus" desligado por padrão e contador "sem atribuído: N"; os 29 sem `marco_unidade` como pendência visível.
**Pronto quando:** abrir o painel num domingo mostra amarelo com "última janela útil: sexta"; um snapshot de 3 dias exibe tarja; o contador de resumos sem gerar bate com o log (**hoje: 116 de 1.165, descrevendo a coleta de 13/08**).

### Fatia 3 — Servidor mínimo, sem agente
Imagem, App service, SQLite, `/login` com scrypt/lockout/rate-limit/sessão/CSRF, `/status`, ingestão por **upload manual** do JSON pelo admin, gate por unidade, `log_acesso`.
**Pronto quando:** subir o JSON de 18/08 promove 6 snapshots de unidade; subir o de 12/08 (sem envelope) é **recusado**; 6 tentativas de login erradas devolvem 423; sessão expira em 12 h; toda ação aparece em `log_acesso`.

### Fatia 4 — Agente e protocolo pull
`sei360_agente.py` (enroll, rodar, status, testar, instalar-tarefa, atualizar), HMAC + nonce, lease/heartbeat sobre o **processo do coletor**, máquina de estados das execuções, teto local.
**Pronto quando:** a estação coleta sozinha na janela; matar o Chromium no meio produz `travada` no painel em ≤ 10 min; requisição com timestamp fora de ±5 min é rejeitada; o agente recusa a 3ª execução do dia mesmo com o servidor pedindo.

### Fatia 5 — Alertas, expurgo e espelho de auditoria
Notificador por código (0-5, `nao_executada`, atraso); expurgo com os TTLs da 7.7, com **gatilho próprio para os PNGs**; espelho append-only do `log_acesso`.
**Pronto quando:** desligar a estação numa janela gera e-mail em até 90 min; PNG de falha some em 7 dias mesmo sem coleta bem-sucedida no período; apagar `log_acesso` no banco não apaga o espelho.

### Fatia 6 — Autorização por unidade e API
`usuario_unidade`, `WHERE` server-side em todos os endpoints, `/api/coleta`, `/api/processos` paginado, `/api/export.xlsx` em memória, `processo_texto` só no detalhe. Migração do `painel_sesab.html` das 4 consts para `fetch`.
**Pronto quando:** usuário da ASTEC recebe 5 linhas e a resposta HTTP não contém nenhum registro de outra unidade; export registra a contagem de linhas em `log_acesso`; não há busca global por texto livre.

### Fatia 7 — Tela de acesso real e administração
Na `SEI360.html`: remover a `section.showcase` (leva junto D3, GSAP, 12 `setInterval`, 8 `rAF` e ~640 KB dos 743) e **os 6 contadores fictícios, em especial "Sessões ativas 3.218" dentro da moldura de login** — declaração factual falsa em tela de autenticação de órgão público, que sai antes de qualquer outra coisa; no lugar, data/hora da última coleta e mesas cobertas. Mecânica do form: CSRF, `role="alert"`, `.field-in.err`, `disabled` no submit, `fetch('/login')` com 401/423/429. Auto-provisionamento semeado pelo snapshot; `/admin`.
**Pronto quando:** a página não faz nenhuma requisição externa e passa na CSP fechada; nenhum número na tela é inventado; um dos 58 e-mails da carteira consegue primeiro acesso com aprovação do admin; nenhum e-mail fora da carteira consegue.

### Fatia 8 — Exposição (só depois de A1-A6)
Domínio, Let's Encrypt, restrição de origem, MFA nas contas do EasyPanel, backup cifrado com chave externa, RIPD e registro do art. 37 arquivados.
**Pronto quando:** os seis documentos existem assinados e datados, e o SPECS §2/§7 foi reescrito **no mesmo commit** que criou o serviço.

### Fatia 9 — CONDICIONADA: worker no container
Só se a TIC/PRODEB criar conta de serviço institucional com escopo de leitura e termo de uso (P4). Não iniciar sem esse ato.

**Estimativa honesta ao decisor:** software pronto em cerca de 10 a 12 dias úteis de uma pessoa. **Autorizado para produção: indeterminado** — o caminho crítico são os aceites, não o código.

---

## 11. O que NÃO será feito (YAGNI), e por quê

| Descartado | Por quê |
|---|---|
| **Playwright/Chromium no container** — ***revogado em 21/08/2026 para a busca, ver §6.0*** | valia até 21/08: dispensava `shm_size`, `ipc:host`, seccomp, sandbox, `--no-sandbox`, App x Compose service, build pesado em CI e 2 GB de limite de memória. **Nota de 07/09/2026:** a coleta continua sem Chromium no container (esta linha continua valendo para ELA); a busca passou a exigir tudo isso — inclusive o mínimo de 2 GB (§3.6-bis) — por decisão do dono, não por reversão técnica |
| **Senha do SEI em secret do EasyPanel** | secret de PaaS não é cofre: legível em `docker inspect`, `/proc/1/environ` e no `.env` do host. Não é mitigação, é redistribuição |
| **Cofre por usuário com Argon2id + chave em memória** | protege o dump frio e nada mais; falha diariamente por falta de chave após qualquer redeploy, e gera pressão previsível para "guardar a chave no servidor" — que colapsa o desenho na linha 1 do §2 |
| **Leitor de TOTP / semente em variável / fila de código** | contornar controle de segurança do órgão |
| **Retry automático em qualquer nível** | reintroduz o retry cego que o disjuntor de duas quedas existe para impedir; em `exit 3`, aproxima bloqueio da conta da servidora |
| **APScheduler** | o servidor não coleta; sobrou uma comparação de janelas numa thread com `zoneinfo` |
| **Redis** | não há fila nem cache a 2 execuções por dia |
| **Postgres** | 1.165 linhas/dia, um escritor. Provisionar só quando o web precisar de réplicas em nós diferentes |
| **bcrypt / passlib / SQLAlchemy** | `hashlib.scrypt` está na stdlib; 14 tabelas em SQL direto são mais auditáveis |
| **`supercronic` / `crond` dentro do container** | engolem stdout e não propagam exit code — a lição do `PYTHONUNBUFFERED`, de novo |
| **Autoatualização do agente** | seria canal de execução remota de código na única máquina com a credencial |
| **Upload de screenshots ao servidor** | tela cheia do Controle de Processos com nomes, logins e anotações livres |
| **Cache de URL / worker pool sobre links persistidos** | §3.2 #1 e #2: hash expirado derruba a sessão real da pessoa. A cadeia é redescoberta sempre |
| **Coluna `dias_na_unidade` ou qualquer derivada de tempo** | §3.2 #6: número gravado congela e o painel mente conforme o snapshot envelhece |
| **Busca global por texto livre** | procurar por nome de paciente não pode ser funcionalidade |
| **Geração de resumo por IA dentro do container na v1** | exige chave, verba e dono declarado (P6). Enquanto não houver, a falta é **estado exposto na tela**, não linha de log |
| **SSO, multi-tenant, WebSocket, app mobile, réplicas do web** | nenhum tem demanda; cada um é superfície nova numa aplicação que expõe dado sensível |

---

## 12. Perguntas abertas — só o usuário responde

**P1 — Onde fica o host? (a) VPS BR contratado pelo órgão ou (c) servidor interno.** — **RESPONDIDA em 07/09/2026** (de fato, em 21/08/2026, pela escolha do dono: HostGator/EasyPanel — via **(a)**; região BR a confirmar `[a datar]`). *Texto original da recomendação, mantido porque a decisão real foi tomada em sentido contrário a ela:*
*Recomendação:* **(c)**. *Custo de (c):* depende de Docker+Traefik liberados pela TIC, egresso permitido e fila de provisionamento interna — pode levar meses e não está sob controle da engenharia. *Custo de (a):* provisionamento em dias, mas o provedor entra na fronteira de confiança com acesso de hipervisor (sem controle de cifragem de disco, swap ou snapshot), exige contrato no CNPJ do órgão com cláusula de operador, e o passivo do art. 39 passa a existir. **(b) fora do Brasil: descartada por decisão, ver 9.6.**

**P2 — A segunda coleta diária existe? Em que horário?** — **PENDENTE** *(conferido em 07/09/2026)*
*Recomendação:* **19:00**, dias úteis, fora do expediente. *Custo de manter em horário comercial:* ~15 min de sessão de robô com a unidade ativa da titular mudando durante o trabalho dela, duas vezes por dia — e isso precisa constar no termo A2. *Custo de 1x/dia apenas:* dado da tarde envelhece 24 h; para triagem com mediana de permanência de 9 dias, o impacto é baixo.

**P3 — Quem assina A1-A6, e em que prazo?** — **PENDENTE** *(conferido em 07/09/2026)*
*Recomendação:* fechar A1 e A2 primeiro (dependem de duas pessoas identificadas) e tocar A3/A4 em paralelo com o encarregado. *Custo de esperar todos:* o servidor não sobe, mas as Fatias 0-2 entregam melhoria real na estação. *Custo de subir antes:* expor por Traefik decide o §6 por omissão e cria tratamento sem controlador formalizado.

**P4 — Pedir à TIC/PRODEB uma conta de serviço institucional com escopo de leitura?** — **PENDENTE** *(conferido em 07/09/2026)*
*Recomendação:* **pedir**, como alvo de médio prazo, mesmo sabendo que a resposta pode demorar ou ser negativa. É a única saída que remove a imputação nominal. *Custo de pedir:* expõe formalmente a automação, e a TIC pode responder proibindo — que é uma resposta legítima e melhor de receber agora que depois. *Custo de não pedir:* a imputação nominal fica permanente e a Fatia 9 nunca se desbloqueia.

**P5 — Quem tem conta no painel do EasyPanel e no host?** — **PENDENTE**, precisa de lista nominal (A5) *(conferido em 07/09/2026)*
*Recomendação:* o menor conjunto possível, com MFA obrigatório e restrição de origem na porta administrativa. *Custo de restringir:* dependência de poucas pessoas para operação. *Custo de não restringir:* esse conjunto é chave-mestra sobre a base inteira e sobre o log que deveria auditá-lo — segurança que depende de o administrador do PaaS ser irrepreensível não é segurança.

**P6 — Quem gera os resumos, com que chave e com que verba?** — **PENDENTE** *(conferido em 07/09/2026; as travas de código estão prontas — ver `PLANO_PRODUTO.md` Fatia 7 — a decisão de ligar, não)*
Hoje **116 de 1.165 processos não têm resumo, e os 1.049 existentes descrevem a coleta de 13/08** sob um cabeçalho que diz 18/08. *Recomendação:* job com dono declarado, chave em secret, agendado após a coleta; enquanto não existir, selo de idade no card e contador no cabeçalho. *Custo de manter manual:* o campo mais lido da tela é o mais velho da tela, e a distância cresce um dia por dia. *Custo de automatizar:* chave de API, verba recorrente e mais um caminho que lê texto livre com dado de saúde — o que traz o RIPD junto.

**P7 — A coleta continua na estação pessoal da titular ou vai para uma máquina dedicada?** — **PENDENTE** *(conferido em 07/09/2026; a taxa de 1 janela perdida em 6 já produziu 11 dias corridos parados — ver `PLANO_EXECUCAO_2026-09-07.md` §0)*
*Recomendação:* **máquina dedicada** ligada permanentemente, com logon automático e sessão bloqueada. *Custo de manter na estação atual:* a taxa base observada é **1 janela perdida em 6** (14/08, sexta-feira, dia útil, sem execução) e a tarefa exige logon interativo. *Custo da dedicada:* um equipamento a mais sob a guarda de alguém, com o mesmo requisito de disco cifrado — e a credencial nominal continua sendo de pessoa física.

**P8 — Quantas contas o painel terá: os 58 atribuídos ou só gestores?** — **PENDENTE** *(conferido em 07/09/2026; 62 contas já têm vínculo semeado por medição — §5-undecies do SPECS.md —, mas a decisão formal de quantas ATIVAR não foi tomada)*
*Recomendação:* abrir para os 58, via auto-provisionamento semeado pelo snapshot com aprovação do admin. *Custo de abrir:* mais gente lendo a base, log de acesso maior, suporte. *Custo de restringir a 2-3 gestores:* o produto vira relatório de um gestor só — caso em que o servidor não se justificava e a Fase 3 inteira perde a razão.

**P9 — O painel fica exposto na internet aberta ou atrás de VPN/IP do órgão?** — **PENDENTE** *(conferido em 07/09/2026)*
*Recomendação:* **atrás de VPN ou restrição de IP**, ao menos enquanto não houver segundo fator no painel. *Custo:* servidor em teletrabalho ou em celular precisa de VPN. *Custo de abrir:* uma tela de login sem MFA, com senha escolhida por usuário, protegendo dado sensível de saúde, encontrável por varredura de certificado.

**P10 — Retenção: 30 dias de JSON bruto e 180 dias de log de acesso são aceitáveis?** — **PENDENTE** *(conferido em 07/09/2026)*
*Recomendação:* sim — 30 dias cobrem a janela de reprocessamento e 180 dias cobrem investigação de incidente. *Custo de reter mais:* cópias quase idênticas de dado pessoal acumulando, snapshot velho degradando qualidade (art. 6º, V) e atrapalhando pedido de correção (art. 18, III). *Custo de reter menos:* perde-se a capacidade de reconstruir o que o painel mostrava numa data passada.