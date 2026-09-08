# PLANO DE PRODUTO — SEI360

Verificado no código em 19/08/2026, entre 13:40 e 14:10, com o repositório sendo editado em paralelo (app.py, relatorios.py, banco.py e os templates de usuário mudaram entre 13:15 e 13:39). Toda linha citada vale para esse instante. Todo número foi medido agora, no banco `C:\Claude\sei_sistema\sei360\servidor\_dados\sei360.db`.

Nos comandos abaixo, `$PY` = `C:\Users\Lucaskaram\AppData\Local\Programs\Python\Python312\python.exe` e `$B` = `C:\Claude\sei_sistema\sei360\servidor`.

---

## 1. O sistema em uma frase, e onde ele está hoje

**O SEI360 é o espelho da carteira do SEI que responde três perguntas que o SEI não responde: o que está parado e há quanto tempo, o que é ação minha e o que é espera de terceiro, e onde o processo está agora.**

O que já está de pé (verificado, não declarado):

| Peça | Estado real |
|---|---|
| Fronteira por unidade | Aplicada no SQL, nas 4 consultas de `carteira()` (`app.py:361-373`) e em `relatorios.carregar()` (`relatorios.py:78`) — exceto `SELECT * FROM resumo` (`app.py:374`), sem `WHERE` |
| Login | scrypt + lockout + CSRF (`seguranca.py`), sessão revogável (`app.py:268-277`) |
| Cofre da credencial | AES-256-GCM, chave mestra fora do banco (`cofre.py`) |
| Relatórios | 11 no catálogo (`relatorios.py:270-307`), tela + XLSX funcionando; `cobertura()` já foi corrigida para não tratar `0` como vazio (`relatorios.py:96-113`) |
| Gestão de usuários | Já saiu do `/admin`: `/admin/usuarios` com busca, 8 filtros e paginação de 25 (`app.py:776-802`) |
| Navegação única | `templates/_nav.html`, incluída em 6 telas, com CSS pronto em `estatico/nav.css:13-33`; o menu do painel também já aponta para `/relatorios` (`montar_painel.py:39-41`) |
| IA | Estrutura pronta e **desligada**: `ia.py` (185 linhas), tabela `config_ia` (id=1, `ativo=0`, sem chave), rotas `/admin/ia` e `/admin/ia/gerar` |

Onde ele está hoje, sem maquiagem — cinco fatos medidos:

1. **O painel mostra ontem.** Os 6 snapshots `corrente` (ids 13-18) têm `coletado_em = 2026-08-18T07:45:16`. Existem snapshots `expirado` (ids 7-12) com `coletado_em = 2026-08-19T00:02:36`, mais novos que o corrente. `ingestao.py:171-173` expira o anterior sem comparar datas.
2. **A procedência do dado corrente aponta para um arquivo de teste.** Os 6 snapshots correntes têm `arquivo='sei360_3.json'` — temporário criado e apagado por uma suíte, não `sei_sesab_2026-08-18.json`. Nenhuma das suítes, exceto `teste_deploy_novo.py`, isola o banco (`SEI360_DADOS|tempfile|mkdtemp`: 0 ocorrências em `testes.py`, `teste_configuracao.py`, `teste_relatorios.py`, `teste_container.py`).
3. **A idade anda sozinha.** `relatorios.py:44` conta contra `datetime.now(TZ).date()`. Com 1 dia de defasagem, "parados +90 dias" sai 531 em vez de 526, e **28 processos trocam de faixa** sem que nada tenha acontecido no SEI.
4. **O deploy quebra no primeiro uso real.** `requisitos.txt` declara só `Flask==3.0.3` e `gunicorn==23.0.0`; `cofre.py`, `ia.py` e `relatorios.py:364` importam `cryptography` e `openpyxl`. Funciona na estação, dá 500 no container ao guardar a senha do SEI (modo padrão) e em toda exportação XLSX. `cofre.disponivel()` só testa a variável de ambiente — a tela diz "cofre ligado" e só depois estoura.
5. **O papel `gestor` não existe.** A palavra "gestor" aparece **zero vezes** em `app.py`. `exige_admin` (`app.py:100-107`) é o único teste de papel do arquivo. Há 2 gestores no banco que não administram nada e, ao mesmo tempo, veem o relatório que nomeia 57 servidores.

Base: 1.165 processos distintos em 1.169 linhas, 6 unidades (CESS 625, UMA-CMA 300, COMASUP 218, DGESS 20, ASTEC 5, GT-HTLV 1), 71 contas, 1.049 resumos de IA, 78 alertas.

---

## 2. Relatórios: quais, com que campos, para quem, e a idade do dado neles

### 2.1 A regra que atravessa todos (R0) — sem isto, nenhum relatório é defensável

**Idade medida contra a coleta, nunca contra o relógio.** O `SELECT` de `relatorios.py:71` já traz `s.coletado_em` por linha; `_dias()` (`relatorios.py:35-44`) ignora e usa `now()`. Toda tela e todo XLSX passam a carregar duas linhas separadas: *"Medido sobre a coleta de 18/08/2026 07:45"* e *"Gerado em 19/08/2026 14:10"*.

**Quórum declarado.** A procedência é montada a partir do dado carregado (`relatorios.py:345-349`), então unidade sem snapshot corrente some da tela e some do total, em silêncio. Passa a ser montada a partir de `unidades_do(usuario)`: cada unidade recebe `no corte` / `atrasada (N dias úteis)` / `sem coleta`. Total e percentual só sobre `no corte`; as outras aparecem nomeadas, com contagem própria, fora da soma.

**Preenchimento não é incidência.** Campo booleano é 100% coletado por construção. `visualizado` está 100% preenchido e é verdadeiro em 1.153 — o número útil é **12 nunca visualizados**, não "100% de cobertura". Cada campo declara qual das duas medidas vale.

**Denominador em toda tela:** "sobre 1.165 de 1.165 da sua carteira; 0 em unidade sem coleta". E a nota de dedup: 1.169 ocorrências para 1.165 processos — 4 estão abertos em duas das unidades do usuário e contam uma vez em cada no comparativo por unidade.

### 2.2 O que o dado sustenta — medido em 19/08 sobre os 1.165 correntes

| Campo | Preenchimento | Distintos | Serve para |
|---|---|---|---|
| `tipo_processo` | 100% | 33 | Composição |
| `mesa_coleta` | 100% | 6 | Comparativo entre unidades |
| `ultimo_movimento` | 100% | 1.010 | Tempo sem movimento **e classe do evento** |
| `documentos` / `movimentos` | 100% | 35 / 100 | Volume documental |
| `autuacao` | 99,9% | 1.154 | Idade do processo |
| `gerador_unidade` | 99,9% | 122 | Procedência |
| `nivel_acesso` | 99,9% | 2 (1.106 Público / 59 Restrito) | Triagem |
| `origem` | 99,9% | 2 | Recebidos x gerados |
| `assuntos` | 99,1% | 35 | Composição por tema |
| `marco_unidade` | 97,5% | 968 | Permanência (29 sem data, nomeados) |
| `atribuido_login` / `atribuido_nome` | 82,6% | 57 pessoas | Carga por responsável (**203 sem ninguém**) |
| `recebimento` / `recebimento_por` | 77,2% | 735 / 57 | Tempo até a primeira ação |
| `marcador` | **52,7%** | 236 (57 famílias) | Marcadores — **só com tarja** |
| `visualizado` | 100% preench. | 1.153 verdadeiros | **12 nunca vistos** |
| `mesas_divergem` | 100% preench. | **150 verdadeiros** | Conferir onde o processo está |
| `doc_incluido` | 100% preench. | **10 verdadeiros** | Base estreita — tarja obrigatória |
| `processo_mesa` | 1.682 linhas | 241 mesas, 1.078 atribuídos | **Onde o processo está aberto** |

### 2.3 O que o dado NÃO sustenta — e o que fazer antes

Estes ficam listados na tela com o motivo escrito. "Não dá, e por quê" vale mais que um gráfico sobre 1% da carteira.

| Pergunta | Campo | Medido | O que fazer antes |
|---|---|---|---|
| Retorno programado | `retorno` | **1 em 1.165 (0,1%)** | Nada. A unidade não usa o campo do SEI. Só volta a existir se a prática mudar. |
| Processos anexados | `anexados` | **7 (0,6%)** | Nada. |
| Hipótese legal de restrição | `hipotese_legal` | **~61 (5,2%)** | Nada — e é coerente: só 59 são Restritos. |
| Urgentes / sobrestados | `urgente`, `sobrestado`, `sem_historico` | **1 valor distinto, 0 verdadeiros** | Não é falta de coleta: é campo do SEI que a unidade nunca usou. Dizer isso com essas palavras. |
| Para onde foi enviado | `envio` / `unidade_envio` | **27,0% (~315)** | Só existe depois de despachar. Vira coluna do "Onde está aberto", não relatório próprio. |
| Documento novo incluído | `doc_incluido` | **10 verdadeiros (0,9%)** | Entra no painel de triagem **com tarja de base estreita** — hoje aparece com o mesmo peso visual de 526. |
| Combinados com prazo | sufixo do `marcador` | **12 de 1.165 (1%)** | Medi: dos 221 marcadores com ` / `, só **12** têm data legível. Os outros são descrição de item ou destino. **Não construir "prazos vencidos".** Publicar a família no eixo e o sufixo contado, sem interpretar data. |
| Assinatura externa / e-mails enviados | `assinatura_externa`, `emails_enviados` | contagens, incidência **não medida** | Medir a incidência antes de publicar; se for menor que 5%, vai para a lista de inviáveis. |
| Conferência declarado x contado | `snapshot.coletados` | **NULL nos 6 correntes**, por decisão (`ingestao.py:164-166`) | Ou o coletor entrega o total que a mesa declara e o gate compara de verdade, ou o campo sai do esquema. Meio gate é pior que nenhum: parece conferência. |
| Fonte das mesas | `mesas_fonte` | **1 valor distinto ('arvore')** | Campo morto. Sai do esquema no próximo banco limpo. |

### 2.4 O catálogo final — 14 relatórios, ordenados por valor

Os 11 atuais permanecem; muda quem os vê e como se contam. Três são novos e **nenhum exige coleta nova**.

**Novos:**

- **N1 — Onde o processo está aberto agora** *(a terceira pergunta do propósito; hoje sem resposta)*. Fonte: `processo_mesa`, 1.682 linhas correntes, 241 unidades de destino, **219 processos abertos em mais de uma mesa**, 150 com `mesas_divergem=1`. Por unidade de destino: quantos da carteira estão abertos lá, quantos divergem entre árvore e andamento. Fora das 6 unidades do usuário: **contagem apenas** — `processo_mesa.atribuido` guarda e-mail institucional completo, e ele sai mascarado por `app.py:688` ou não sai. **Quem vê:** contagens para qualquer logado; login só gestor/admin.
- **N2 — Último evento por classe** *(o que foi combinado sobre o processo)*. `ultimo_movimento.de` é texto padronizado e hoje só o `dh` é aproveitado (`relatorios.py:90`). Classificação por prefixo, medida: **atribuído 386, bloco de assinatura 158, recebido 129, concluído 85, sobrestamento 21, reaberto 9, outros 377**. A classe "outros" (32%) fica **visível e contada** — classe residual escondida vira erro silencioso quando o SEI mudar o texto. Cruzada com a faixa de permanência: "atribuído há mais de 90 dias" e "recebido e nunca concluído" são as duas linhas que a gestão usa. **Quem vê:** qualquer logado; a tela mostra a CLASSE, nunca a frase (que contém login).
- **N3 — Saúde do dado** *(dá para confiar nas outras treze telas hoje?)*. Três blocos: coleta por unidade (data, atraso, snapshots retidos), cobertura x incidência campo a campo, e saúde dos resumos de IA (1.049 de 1.165 = 90,0%; 116 sem; 100% com `descrito_em` anterior ao snapshot; `gerado_por` nulo em 1.049 de 1.049). **Quem vê:** admin e gestor. Nenhum texto de resumo aparece — só contagem.

**Mudanças nos existentes:**

- **Triagem** (`relatorios.py:243`, marcado `destaque`): passa a usar incidência. Números de hoje: 12 nunca visualizados, 203 sem responsável, 10 com documento novo (tarja), 526 parados +90d **na data da coleta**, 59 restritos, 150 divergentes. `urgente`/`sobrestado` saem da tabela e vão para "campo existe no SEI e a unidade não usa".
- **Carga por responsável** (`relatorios.py:128`): **vira gestor/admin**. Ver 2.5.
- **Marcadores** (`relatorios.py:200`): tarja de 52,7% obrigatória **antes** do número. 57 famílias; as maiores são "Relatórios Trimestrais - 2025" 91, PATRICIA 61, "RENATA -PLANILHADO" 57, "AGUARDAR RETORNO DA UNIDADE" 52. Sufixo truncado em 70 caracteres na tela (é texto digitado por servidor e contém nome), completo só no XLSX de gestor.
- **Composição** (tipo, assunto, origem, procedência): 4 cliques viram uma tela de 4 blocos com filtro cruzado.
- **XLSX** (`relatorios.py:358`): a folha de rosto com procedência está certa e fica. Três correções: (a) nome do arquivo passa de `sei360_triagem_2026-08-19.xlsx` (`app.py:771`, data de geração — justamente a errada quando o arquivo circular) para `sei360_triagem_dado-2026-08-18_gerado-2026-08-19.xlsx`; (b) `carregar()` (`relatorios.py:72-73`) traz `especificacao`, `anotacao`, `acompanhamento` e `resumo_curto` no SELECT e **nenhum dos 11 relatórios usa** — é texto que pode citar paciente a uma linha de código de qualquer exportação futura; sai; (c) PDF por `@media print` sobre a tela, **sem biblioteca nova** (o defeito de `requisitos.txt` não pode ser agravado).

### 2.5 Para quem — a regra de papel

| Relatório | servidor | gestor | admin |
|---|---|---|---|
| Triagem, permanência, composição, volume, marcadores, sem movimento, N1 (contagens), N2 | sim, nas unidades dele | sim | sim |
| **Carga por responsável (ranking + XLSX)** | **não** — recebe "Minha fila", só a própria carga | sim | sim |
| N1 com login da unidade externa | não | sim | sim |
| N3 — Saúde do dado | não | sim | sim |

Motivo, medido: `rel_por_responsavel` devolve nome completo, volume, "parados +90d" e mediana de dias sobre **57 pessoas**, hoje acessível pelo papel mais baixo (`app.py:698`, `:728`, `:749` usam só `@exige_login`) e exportável em XLSX. A atribuição é espelho do SEI; **o ranking comparativo com planilha não existe no SEI**. A coluna "sem atribuição" (203) fica nas duas versões — é a única que gera ação imediata.

---

## 3. Navegação e gestão de usuários

Boa parte já foi feita hoje. O que falta é pouco, específico e mensurável.

**Já existe:** `_nav.html` com 4 portas, incluída em `admin.html:10`, `configuracao.html:70`, `relatorios.html:10`, `relatorio.html:10`, `usuarios.html:30`, `usuario.html:10`; CSS em `estatico/nav.css`; `/admin/usuarios` com busca, filtros e paginação; menu do painel com `/relatorios`.

**O que falta:**

1. **Quinta porta: Pessoas.** `_nav.html:9-14` tem Painel / Relatórios / Configuração / Administração. `/admin/usuarios` só é alcançável por dentro de `/admin` (`admin.html:104`). A fronteira LGPD do sistema — quem vê o quê — é decisão recorrente e merece porta própria, visível a **admin e gestor**; `/admin` (agentes, execuções, expurgo, log, IA) continua só admin.
2. **`exige_papel('admin','gestor')`.** Não existe. Sem ele, "gestor" segue sendo rótulo: zero ocorrências de "gestor" em `app.py`.
3. **Uma lista de portas, duas renderizações.** Hoje a lista é escrita duas vezes — Jinja em `_nav.html` e a constante `MENU` em `montar_painel.py:37-58`. Foi assim que `/relatorios` nasceu ausente do painel. Extrair para `portas.py` (`PORTAS = [(chave, rota, rótulo, papéis)]`), injetada por `context_processor` e importada pelo gerador. **O painel NÃO recebe a barra `.nav-topo`:** `painel.html` tem `.topo`, `.wrap` e rail próprios e roda também como arquivo solto (`montar_painel.py:9-11`) — empilhar barra sticky deslocaria o rail e existiria só na versão servida.
4. **Chave de tema morta.** `painel.html:1615` grava `localStorage['sesab.tema']`; `admin.html:5`, `configuracao.html:5`, `primeiro_acesso.html:5`, `relatorio.html:5`, `relatorios.html:5`, `usuario.html:5` e `usuarios.html:5` leem `localStorage['painel-tema']` — chave que **arquivo nenhum escreve**. 7 linhas. Hoje quem põe o painel em claro e clica em qualquer porta recebe tela escura se o SO estiver escuro.
5. **Fontes bloqueadas pela própria CSP.** `painel.html:5-7` pede `fonts.googleapis.com`; a CSP do app fixa `style-src 'self'` e `font-src 'self'`. As mesmas três famílias já estão auto-hospedadas em `estatico/vendor/fontes.css` e são usadas pelo login. `montar_login.py` resolveu isso com a lista `EXTERNOS`; `montar_painel.py` não tem equivalente. A tela onde as pessoas passam o dia cai para fonte de sistema e enche o console de violação de CSP.
6. **Duas saídas no mesmo menu, com o rótulo genérico na errada.** `painel.html:553` "Sair do SEI360" (POST `/sair`, que revoga a sessão de fato) e `painel.html:571` "Sair da conta", que abre o logout de `seibahia.ba.gov.br`. Renomear a segunda para **"Encerrar sessão no SEI Bahia"**, movê-la para junto dos atalhos externos, e levar a nota ("este painel continua aberto") para dentro dela — hoje ela fica abaixo das duas e, lida como legenda do bloco, nega o que `/sair` faz.

**Tudo isso entra no gerador, nunca no template.** `templates/painel.html` (109 KB) e `templates/login.html` (101 KB) são saída de `montar_painel.py` e `montar_login.py` e **não trazem cabeçalho dizendo isso**. Conserto feito à mão morre na próxima remontagem, sem diff e sem aviso.

---

## 4. IA por chave de API: desenho, privacidade, custo, controle

### 4.1 Onde está

`ia.py` já faz o certo em três pontos: guarda a chave no mesmo cofre AES-256-GCM da credencial do SEI (`ia.py:89-107`), separa dois níveis com o restrito como padrão (`ia.py:47-63`), e declara o país do provedor na própria tela (`ia.py:42`). `config_ia` no banco: `id=1, ativo=0, provedor='anthropic', nivel='estruturado'`, sem chave.

### 4.2 Cinco defeitos medidos, antes da primeira chamada

1. **O modelo padrão não existe.** `ia.py:40-41` e a linha gravada em `config_ia` trazem `claude-haiku-4-5-20251001`. Os IDs corretos não levam sufixo de data: **`claude-haiku-4-5`**, **`claude-sonnet-5`**, **`claude-opus-5`**. Como está, a primeira chamada devolve 404 e `ia.testar()` (`ia.py:182`) mostra "erro 404" — quem testar vai concluir que a chave está errada e girar uma nova à toa.
2. **O nível "estruturado" não é o que diz ser.** `ia.py:50-51` promete "nenhum texto escrito por servidor sai do SEI360", e a lista de campos (`ia.py:52-54`) inclui `atribuido_nome` (57 pessoas) e `marcador` — que é texto livre digitado, com nome de pessoa no prefixo: PATRICIA 61, "RENATA -PLANILHADO" 57, "Mariana Alcântara - PLANILHADO" 24, "RENIARA PEIXOTO" 23.
3. **O aceite é global.** `config_ia` é linha única (`id=1`). Um admin aceitaria pelas 6 unidades. E `admin_ia_gerar` (`app.py:1291`) varre `WHERE s.estado='corrente'` **sem fronteira de unidade**: manda para fora processo de unidade que não é dele.
4. **A tela não marca nada.** `app.py:413` monta `resumo_em`; `resumo_em`, `resumoEm` e `descrito_em` aparecem **0 vezes** em `templates/painel.html`. Os 1.049 resumos têm `descrito_em='2026-08-13'` contra snapshot de 18/08 — cinco dias — e `gerado_por` nulo em 1.049 de 1.049. O painel imprime o resumo (`painel.html:1062`, `:1281`) sem data e sem quem gerou.
5. **O texto da IA entrou na busca livre.** `painel.html:881` inclui `d.resumo_curto` e `d.resumo_longo` entre os campos varridos pela caixa de busca. Medido nos 1.049 resumos: **17 citam "paciente"**, 1 cita matrícula, 10 trazem número de 6+ dígitos. A fronteira por unidade não é violada (a busca roda sobre a carteira já filtrada), mas **procurar por nome de paciente não pode ser funcionalidade**.

### 4.3 Desenho proposto

- **Chave:** fica onde está — cofre, AAD `b"config_ia"`, nunca reexibida. Não trocar a PK de `credencial`: a chave é do órgão, `config_ia` é o lugar certo.
- **`aceite_ia(unidade PK, escopo CHECK('estruturado','completo'), aceito_por, aceito_em, revogado_em)`.** A geração só percorre processos cujas mesas tenham aceite vigente. Escopo "completo" (com `especificacao` 88,1% e `anotacao`) exige aceite separado. Vira o 5º passo do assistente (`configuracao.py` tem 4 e nenhum fala de IA). Sem aceite, a tela mostra "unidade não aderiu" — não um vazio.
- **Minimização:** tirar `atribuido_nome` do nível estruturado (o resumo não precisa saber de quem é o processo — já é coluna da tela) e mascarar o prefixo-que-é-nome do `marcador`, mantendo a família. Mascarar antes de serializar: "em favor de \<Nome\>", "paciente \<Nome\>", matrícula, CPF, CNS. **Escrever na tela que isto é redução de risco, não anonimização do art. 12** — para ninguém tratar o mascarador como autorização.
- **Validação na saída:** descartar e reprocessar o resumo que casar com padrão de nome ou matrícula, na mesma camada que hoje só extrai o JSON (`ia.py:154-161`). É a lacuna que produziu "já foi planilhado por Mariana Alcântara" nos resumos atuais.
- **Quem dispara:** na ingestão, depois do commit, para (processo novo) ∪ (processo cujo `ultimo_movimento` mudou), com teto diário. Botão "gerar agora" só no `/admin`, e **nunca** no caminho do painel. Manter síncrono e com parada no primeiro erro, como `app.py:1299-1303` já faz.
- **Proveniência:** `gerado_por` obrigatório (modelo + versão do prompt), mais `prompt_versao`, `fonte_sha256` do payload e `custo_tokens` na tabela `resumo`. Backfill honesto dos 1.049 existentes como `rodada-manual-2026-08-13/desconhecido` — mentir que se sabe é pior que admitir que não. **`NOT NULL` em tabela existente exige recriar a tabela**: `banco.py` migra por comparação de colunas e não impõe restrição nova.
- **Retenção:** `DIAS['resumo']` no `expurgo.py:30-45` (hoje só há snapshot 30, log 180, sessões 7, tentativas 7, alerta 90, execução 180) e apagar o resumo junto quando `processo_texto` do mesmo `id_sei` for apagado — o derivado não pode sobreviver à fonte. Hoje `expurgo.py:99-106` só alcança o órfão, e um resumo que descreve caso de paciente vive enquanto o processo ficar na carteira.
- **Fronteira:** trocar `SELECT * FROM resumo` (`app.py:374`) por join filtrado pelas mesmas unidades das outras três consultas. Hoje não vaza — o dicionário é indexado por processos já filtrados —, mas a defesa é acidental, não estrutural.

### 4.4 Custo, declarado

Medida: payload estruturado ≈ 107 tokens/processo + ~160 tokens de instrução por chamada; saída medida nos resumos existentes ≈ 110 tokens (curto 67 + longo 300 caracteres). Preços de tabela: Haiku 4.5 US$1 / US$5 por MTok; Sonnet 5 US$3 / US$15 (intro US$2 / US$10 até 31/08/2026); Opus 5 US$5 / US$25. Batches: −50%.

| Cenário | Haiku 4.5 | Sonnet 5 (intro) | Opus 5 |
|---|---|---|---|
| Carga inicial, 1.165 processos, **uma vez** | **US$0,95** (~R$5) | US$1,90 | US$4,76 |
| Idem com Batches | US$0,48 | US$0,95 | US$2,38 |
| Incremental (12 a 67 novos/dia, medido na série em disco) | US$0,01–0,06/dia | US$0,02–0,12 | US$0,05–0,28 |
| **Regerar tudo todo dia útil** | US$21/mês | US$42/mês | US$105/mês |

Antes da primeira rodada real, medir com `client.messages.count_tokens` em vez de confiar na conversão de 4 caracteres por token usada aqui. E acrescentar `custo_usd_estimado` e `teto_dia_usd` em `config_ia`, recusando geração acima do teto: o cenário a barrar **por código** é regerar tudo todo dia, que é 22x a carga inicial por mês sem ganho — o resumo curto descreve o que o processo **é**, e isso não muda.

---

## 5. Limpeza: o que apagar e o que consolidar

### APAGAR do banco vivo (com a lista impressa e conferida antes)

| O quê | Medido |
|---|---|
| Conta **admin ATIVA** `origem='cetico'` | 1 — e a palavra "cetico" não existe em nenhum `.py` ou `.md` do projeto: o script sumiu, a conta ficou. É a porta mais barata que este sistema tem. |
| Contas `origem='teste'` | 10 (6 admin, 1 gestor, 3 servidor, todas inativas) |
| `ultimo_login_em` em contas `auto_snapshot` nunca ativadas | **26** — a tela mostra isso como último acesso de servidores reais que nunca entraram |
| Execuções `travada` com janela sintética | 27 travadas, 3 perdidas, 1 bloqueada |
| Alertas | **78, dos quais 0 reconhecidos** |

### APAGAR do código

- Imports mortos: `cofre.py` (`json`), `coleta.py`/`expurgo.py`/`ia.py` (`banco.agora`), `semear.py` (`Path`), `teste_configuracao.py` (`os`), variável `f` em `janelas.pascoa()`.
- `janelas.ultimo_dia_util` (nunca chamada) e `coleta.TIMEOUT_COLETA_S` (nunca usada).
- Do esquema, **só em banco novo** (a migração compara colunas e não remove): `agentes.pausado_motivo`, `higiene_config_vazio`, `higiene_verificada_em`, `agendamento.tz`, `agendamento.desarmado_em`, `log_acesso.espelhado`, `usuarios.senha_algo`, `processo.mesas_fonte`. `agendamento.tz` é a mais enganosa: faz quem lê o esquema acreditar que o fuso é configurável por agente, e ele é fixo em `banco.TZ`.
- `sei360/SEI360.html` (743 KB, órfão — o gerador lê `SEI360.original.html`) e a linha de `SPECS.md:164` que aponta o arquivo errado. Hoje quem seguir a documentação edita o arquivo que o build ignora.

### CONSOLIDAR

- **`requisitos.txt`**: acrescentar `cryptography` e `openpyxl` com versão fixada; `cofre.disponivel()` passa a tentar o import além de checar a chave mestra.
- **Suítes em banco descartável**: `testes.py`, `teste_configuracao.py`, `teste_relatorios.py` definem `SEI360_DADOS` para tempdir **antes** de importar `banco`, no padrão que `teste_deploy_novo.py` já usa, e criam os próprios usuários descartáveis em vez de sequestrar contas semeadas.
- **`teste_container.py`** ganha um passo que importa `app, cofre, ia, relatorios, expurgo, coleta, configuracao, ingestao, semear, janelas, seguranca` **dentro da imagem** — é exatamente a classe de defeito que ele existe para pegar e hoje não pega (grep por `import app` nele: 0).
- **`.dockerignore`**: exclui `testes.py`, `montar_painel.py`, `montar_login.py`; `teste_configuracao.py` (com senha de teste em claro), `teste_deploy_novo.py`, `teste_relatorios.py` e `teste_container.py` **entram na imagem**.
- **`.gitignore`** sobe de `servidor/` para `sei360/`, cobrindo `agente/agente.json` — que guarda o token Bearer do agente 1 em texto claro. Rotacionar o token pelo botão do `/admin`, já que ele está em claro num arquivo lido por auditoria.
- **`montagem.py`**: `montar_painel.py` e `montar_login.py` repetem ~40 linhas (embrulho `{% raw %}` por regex, conferência de âncoras, escrita, relatório). Quando esse código erra, produz template que passa em toda conferência e chega quebrado ao navegador — já aconteceu uma vez, e os dois arquivos documentam o episódio separadamente.
- **Cabeçalho "gerado — não edite, fonte: \<caminho absoluto\>"** no topo de `painel.html` e `login.html`.
- **Post/Redirect/Get** nos POSTs do `/admin` que hoje fazem `return admin(...)` de dentro do handler (`app.py:1284`, `:1317` e os demais): um F5 depois do expurgo dispara um **segundo expurgo real**. Exceção documentada: a senha provisória continua renderizada, para não passar pela URL.
- **Alertas**: `expurgo.py:124` só apaga alerta com `reconhecido_em` preenchido, e há 78 com **zero** reconhecidos; `/admin` lista `LIMIT 20` com botão de um em um. Agrupar por (tipo, unidade) com contador, reconhecer em lote, e dar prazo de expurgo também ao não reconhecido. Alerta que ninguém alcança é ruído com custo de armazenamento — e é assim que um alerta real passa despercebido.
- **Agente lógico `SERVIDOR/<login>`**: nasce com `agendamento ativo=1` quando `modo_coleta='servidor'` (o padrão), e `janelas_perdidas()` (`app.py:1341`) fabrica execução perdida + alerta duas vezes por dia útil dizendo "estação desligada" sobre uma estação que nunca existiu. E não há o que coletar: `coleta.py` só expõe `testar_acesso()` e `COLETOR` aponta para um caminho que não existe no container. Nasce com `ativo=0` e a tela diz que a coleta depende de estação pareada.
- **Agente sem dono não recebe janela**: o agente id=1 tem `dono_usuario_id` NULL e `credencial_titular='titular a preencher'`, enquanto a trilha do SEI carimba um nome.

---

## 6. Multiusuário: o que falta para várias pessoas usarem de verdade

1. **`exige_papel`** — sem ele, `gestor` não existe (zero ocorrências em `app.py`) e o papel mais baixo exporta o ranking de 57 pessoas.
2. **Porta Pessoas para gestor** — hoje `/admin/usuarios` está atrás de `@exige_admin`; os 2 gestores não concedem nem revogam acesso a unidade nenhuma.
3. **Fronteira testada nos relatórios e nas planilhas** — `testes.py` prova a fronteira no painel; **nenhuma rota de relatório e nenhum `.xlsx` tem teste de fronteira**, e é o `.xlsx` que sai do sistema por e-mail. O teste tem de abrir a planilha e conferir célula a célula, não o status HTTP.
4. **Cinco perfis simultâneos** — gestor com as 6 unidades, servidor de uma, servidor de outra, admin sem vínculo, usuário sem unidade nenhuma; cada um percorrendo `/`, `/relatorios`, `/relatorios/<id>`, `/relatorios/<id>.xlsx`, `/configuracao`, `/admin/usuarios`, com sessões concorrentes vivas.
5. **Concorrência sobre SQLite** — o EasyPanel roda 1 worker e 8 threads (CMD do Dockerfile); `relatorios.carregar()` traz a carteira inteira por requisição e a ingestão escreve milhares de linhas segurando o lock. Com 20 pessoas dentro, "database is locked" aparece primeiro em quem só queria abrir o painel. 200 requisições em paralelo durante uma ingestão, esperando zero.
6. **Custo estrutural declarado** — `/` embute a carteira no HTML e `app.py` impõe `Cache-Control: no-store` (correto para estação compartilhada). Cada ida a `/relatorios` e volta rebaixa a carteira inteira. **Declarar como custo estrutural, não esconder.** Reabrir quando uma unidade passar de ~3.000 processos.

---

## 7. Plano em fatias, na ordem, com critério de pronto

Cerca de **46 h** de trabalho focado (6 dias úteis). Ordem por valor para o usuário, com a Fatia 0 como portão porque custa quase nada e sem ela nada sobe.

---

### Fatia 0 — O sistema instala e não mente sobre o cofre — 1h30 *(portão de deploy)*

`cryptography` e `openpyxl` fixados em `requisitos.txt`; `cofre.disponivel()` tenta o import além de checar `SEI360_CHAVE_MESTRA`; `teste_container.py` ganha o passo de import; `teste_*.py` no `.dockerignore`.

**PRONTO:**
```
docker run --rm <imagem> python -c "import app,cofre,ia,relatorios,expurgo,coleta,configuracao,ingestao,semear,janelas,seguranca"   # sai 0
```
Num container limpo: guardar credencial devolve 200 e baixar `/relatorios/triagem.xlsx` devolve 200.

---

### Fatia 1 — "De quando é este número?" — 6h *(o maior ganho de confiança do sistema)*

Idade contra `coletado_em` da unidade, nunca `now()` (`relatorios.py:44`, `painel.html`); rótulo "medido em DD/MM" em tela e XLSX; quórum montado a partir de `unidades_do(usuario)`; denominador declarado; separação idade x mistura.

**PRONTO:**
```
& $PY $B\teste_relatorios.py   # inclui teste que congela o relogio 5 dias a frente
```
Com a coleta parada e o relógio 5 dias à frente, a distribuição de faixas de `rel_permanencia` **não muda uma linha**. Hoje, com 1 dia, 28 processos trocam de faixa e "+90d" sai 531 em vez de 526.

---

### Fatia 2 — O painel deixa de mostrar ontem — 3h

Promoção só se o novo for mais recente que o corrente da mesma unidade (`ingestao.py:171-173`), com recusa registrada; ingerir a série de `C:\Claude\sei_sistema\painel_sesab\_coletas` em ordem.

**PRONTO:**
```
& $PY -c "import sqlite3;cx=sqlite3.connect(r'$B\_dados\sei360.db');print(cx.execute(\"SELECT unidade,coletado_em,arquivo FROM snapshot WHERE estado='corrente'\").fetchall())"
```
As 6 linhas trazem a data mais nova em disco e um `arquivo` que **existe** (hoje: `sei360_3.json`, temporário de teste). Teste que ingere 19/08 e depois 18/08 e prova que o corrente continua 19/08. Nenhum `expirado` com `coletado_em` maior que o corrente da mesma unidade.

**QUEBRA SE SAIR ERRADO:** ingerir 7 dias multiplica `processo`, `processo_texto` e `processo_mesa` por 7 — cerca de 8 mil linhas de texto livre com dado de saúde. `expurgo.py` apaga as três junto com o snapshot e `DIAS['snapshot']=30`. **Rodar `expurgo --simular` ANTES** e confirmar que o histórico morre no prazo.

---

### Fatia 3 — Onde o processo está agora, e o que foi combinado — 8h

N1 (Onde está aberto), N2 (Último evento por classe), triagem por incidência com tarja de base estreita, marcadores com tarja de 52,7%.

**PRONTO:** em cada relatório, a soma das linhas bate com o total da carteira do usuário; nenhum campo abaixo de 30% entra; a classe "outros" de N2 aparece com seus 377; N1 mostra as 241 unidades de destino e os 150 divergentes; nenhum login de unidade externa aparece para o papel servidor. Teste que compara o total de N1 com `SELECT COUNT(DISTINCT id_sei) FROM processo_mesa` filtrado pelas unidades do usuário.

---

### Fatia 4 — Ninguém vira ranking sem decisão — 3h

`exige_papel('admin','gestor')`; chave `"papel"` no item do CATALOGO; 403 no relatório **e** no `.xlsx`; card some do catálogo de quem não pode abrir; "Minha fila" para o papel servidor.

**PRONTO:** servidor recebe 403 em `/relatorios/responsavel` e em `/relatorios/responsavel.xlsx`, e não vê o card; gestor recebe 200. Teste automatizado com os três papéis cobrindo tela e planilha. `app.py:765` continua gravando a contagem exportada.

---

### Fatia 5 — Moldura que não se desfaz — 4h

`portas.py` com a lista única; quinta porta Pessoas; `/admin/usuarios` liberado a gestor; chave de tema em 7 arquivos; fontes auto-hospedadas via `montar_painel.py`; renomear "Sair da conta" e mover a nota; cabeçalho "gerado — não edite".

**PRONTO:**
```
Select-String -Path $B\templates\*.html -Pattern "googleapis|painel-tema"   # zero linhas
& $PY $B\montar_painel.py; & $PY $B\montar_painel.py                        # segunda execucao, diff vazio
```
Painel abre com zero violação de CSP no console; tema escolhido no painel persiste em `/relatorios`, `/configuracao` e `/admin`; teste que assere que toda porta de `PORTAS` aparece nos dois artefatos.

---

### Fatia 6 — Bancada limpa e rastro apagado — 4h

Suítes em `SEI360_DADOS` temporário; usuários descartáveis; limpeza do banco vivo com lista impressa.

**PRONTO:**
```
& $PY -c "import sqlite3;cx=sqlite3.connect(r'$B\_dados\sei360.db');print(cx.execute(\"SELECT COUNT(*) FROM usuarios WHERE origem IN ('teste','cetico')\").fetchone(), cx.execute('SELECT COUNT(*) FROM usuarios WHERE origem=\"auto_snapshot\" AND ultimo_login_em IS NOT NULL').fetchone())"
```
Devolve `(0,) (0,)` — hoje `(11,) (26,)`. As três suítes passam com `_dados\sei360.db` marcado somente-leitura.

**QUEBRA SE SAIR ERRADO:** apagar por origem sem conferir tira acesso de gente real — há 8 admins para 2 gestores e ninguém sabe de cor quais vieram de script. **Imprimir e confirmar antes de apagar.**

---

### Fatia 7 — IA que pode ser ligada — 8h *(bloqueada pela DECISÃO 9.1)*

Corrigir os IDs de modelo (20 min); `aceite_ia` por unidade; fronteira na query de geração (`app.py:1291`); minimização e mascaramento; validação na saída; `gerado_por` obrigatório + `fonte_sha256` + `prompt_versao`; teto de gasto; disparo por delta na ingestão.

**PRONTO:** `ia.testar()` devolve "chave válida" contra `claude-haiku-4-5` (hoje: 404); processo de unidade sem aceite **não entra no lote** e a tela mostra "unidade não aderiu"; nível "completo" sem aceite explícito é recusado; INSERT em `resumo` sem `gerado_por` falha; o mascarador limpa um corpus de amostra tirado dos 1.049 resumos atuais (17 citam "paciente", 1 cita matrícula); cada chamada aparece em `log_acesso` com `id_sei` e modelo, **nunca** com o texto; o custo da rodada aparece na tela em dólar.

---

### Fatia 8 — O resumo dizendo de quando ele é — 4h

`resumo_em` renderizado ao lado do selo IA com tarja quando `descrito_em < coletado_em`; `resumo_curto`/`resumo_longo` fora do índice de busca (`painel.html:881`); `SELECT * FROM resumo` vira join filtrado (`app.py:374`); coluna de data no XLSX (`painel.html:1387`); `DIAS['resumo']` no expurgo; os 116 sem resumo passam a dizer por quê em vez de cair no fallback silencioso (`painel.html:1062`).

**PRONTO:** com os dados de hoje, **100% dos cards** mostram a tarja "descreve a coleta de 13/08"; buscar por um nome próprio não devolve nada vindo de resumo; `expurgo --simular` lista `resumo` com prazo próprio; a planilha traz a data em toda linha com texto de IA.

---

### Fatia 9 — Operação que não culpa o usuário — 5h

Alertas agrupados por (tipo, unidade) com reconhecimento em lote e prazo de expurgo para não reconhecido; agente lógico nasce desarmado; agente sem dono não recebe janela.

**PRONTO:** `/admin` mostra os 78 alertas em poucos grupos e reconhecer em lote zera a fila; configurar modo "servidor" **não gera nenhum alerta nas 24 h seguintes** (teste com relógio); `/api/agente/tarefa` para agente sem dono devolve recusa com motivo legível.

---

### Fatia 10 — Prova de uso por muitos — 6h

Suíte que sobe a imagem e exercita cinco perfis simultâneos + 200 requisições em paralelo durante uma ingestão.

**PRONTO:** nenhum byte de unidade alheia em nenhuma resposta HTML **nem dentro de nenhuma planilha gerada** (abrir a planilha, célula a célula); admin sem vínculo continua sem carteira; zero "database is locked" nas 200 requisições; contagem total de verificações publicada (hoje 136 + as novas). **Refazer a cada fatia que acrescente rota.**

---

**Marco mais curto, se for preciso mostrar valor antes:** Fatias 0+1+2 = **10h30**, e o sistema passa a poder ser instalado e a não publicar número indefensável.

---

## 8. O que NÃO fazer

1. **NÃO transformar o painel em tela servida por `/api`.** Ele embute a carteira porque também roda como arquivo solto — plano B para quando o servidor cair (`montar_painel.py:9-11`), e essa propriedade se perde na conversão. Enquanto a carteira for de mil e não de dez mil, o custo é estrutural e deve ser **declarado**. Reabrir quando uma unidade passar de ~3.000 processos.
2. **NÃO dar a barra `.nav-topo` ao painel.** Ele tem `.topo`, `.wrap` e rail próprios; barra sticky acima do `.wrap` desloca o rail e existe só na versão servida. A regra é uma lista, duas renderizações.
3. **NÃO construir "combinados com prazo vencido".** Contei: dos 221 marcadores com ` / `, **12** têm data legível — 1% da carteira. E `retorno`, o campo oficial, tem 1 registro em 1.165. Publicar prazo vencido que ninguém escreveu é pior que não ter a tela.
4. **NÃO construir "entrou x saiu por dia" antes de duas semanas de série contínua.** O arquivo de 12/08 tem 20 linhas de uma única mesa: comparado como coleta inteira produziria "entraram 1.125 em 13/08" — artefato de coleta apresentado como movimento de processo. E `DIAS['snapshot']=30` apaga o histórico em 30 dias: a tela não pode oferecer período que o banco não tem.
5. **NÃO trocar a PK de `credencial` por (usuario_id, sistema).** A chave de IA já tem lugar em `config_ia`; a troca exige recriar tabela num volume de produção, e `banco.py` migra por comparação de colunas, sem cobrir mudança de PK nem `NOT NULL`. Só se aparecer um segundo sistema com credencial por pessoa.
6. **NÃO acrescentar segundo provedor de IA.** `PROVEDORES` já é dicionário; a estrutura existe para o dia em que houver escolha. Oferecer escolha inexistente é a mesma classe de mentira que "painel inteligente" na tela de login.
7. **NÃO implementar executor de coleta dentro do container.** Não há navegador nem Playwright na imagem, e mudar isso muda a arquitetura de acesso — o documento a alterar seria `ARQUITETURA_ACESSO.md`, não o Dockerfile. A Fatia 9 resolve o sintoma pelo caminho honesto: o modo servidor deixa de prometer o que não faz.
8. **NÃO preencher `snapshot.coletados` com a contagem de linhas.** O gate compararia o dado consigo mesmo. Ou o coletor entrega o total que a mesa declara, ou o campo sai do esquema.
9. **NÃO apagar agora as colunas mortas do DDL.** A migração por comparação de colunas não remove: isso só vale para banco novo. Até lá, marcar no comentário do DDL que não são usadas — `agendamento.tz` hoje faz quem lê o esquema acreditar que o fuso é configurável por agente.
10. **NÃO tocar em `Cache-Control: no-store`.** A proteção contra o botão Voltar depois do logout depende dele.
11. **NÃO editar `templates/painel.html` nem `templates/login.html` à mão.** São saída de gerador. O conserto morre na próxima remontagem, sem diff e sem aviso.
12. **NÃO ligar a IA antes da Fatia 7 inteira.** Ligar antes repete dentro do sistema, e em escala, um envio que já aconteceu uma vez fora dele.

---

## 9. Decisões que dependem do dono

### DECISÃO 9.1 — Enviar dado de saúde a uma API de terceiro *(bloqueia a Fatia 7)*

Os 1.049 resumos existentes foram gerados **fora do sistema**, enviando `especificacao` e `anotacao` — texto livre em contexto de saúde, com nome civil colado a prescrição, em processo classificado como **Público**. `ARQUITETURA_ACESSO.md` já descartou host estrangeiro por transferência internacional de dado sensível (art. 33); a mesma lei vale para a API, e a decisão nunca foi tomada.

- **Ligar com nível "estruturado" (recomendado):** custo US$0,95 na carga inicial e centavos por dia; nenhum texto livre sai; resumo mais pobre e mais genérico. Ainda é tratamento por operador e ainda exige registro do art. 37 (finalidade, base legal, destinatário, retenção) e contrato de operador. Se o provedor for estrangeiro, exige Cláusulas-Padrão da Res. CD/ANPD 19/2024 e RIPD.
- **Ligar com nível "completo":** o resumo fica de fato útil (a `especificacao` é onde está o que o processo é), e a redução de token é de apenas 20% ao cortá-la — ou seja, o texto livre é barato de mandar e caro de justificar. Exige aceite por unidade, mascaramento e RIPD sem discussão.
- **Não ligar:** custo zero, e os 1.049 resumos existentes continuam sendo exibidos — o que é a pior das três opções, porque mantém o benefício sem o controle. Se for esta, **apagar os resumos existentes** é parte da decisão.

**Recomendação:** ligar em "estruturado", com aceite por unidade, depois do registro do art. 37 e da escolha de provedor. E decidir o que fazer com os 1.049 resumos já gerados, que existem hoje sem base registrada.

### DECISÃO 9.2 — Qual modelo

O padrão do projeto para código Claude é `claude-opus-5`, e não se troca por modelo mais barato sem decisão do dono. Para esta tarefa — resumo de até 3 frases sobre campos estruturados — a diferença de custo é 5x (US$0,95 contra US$4,76 na carga inicial; US$21 contra US$105/mês no cenário de reprocessamento diário, que o plano barra por código). A diferença de qualidade **não foi medida**.

**Recomendação:** rodar os dois sobre a mesma amostra de 40 processos (custo somado abaixo de US$0,20), ler as 80 saídas e decidir com o texto na frente. Assumir que o barato basta é tão arbitrário quanto assumir que o caro é necessário.

### DECISÃO 9.3 — Semear conta a partir do nome e e-mail de terceiros

`semear.py` cria uma conta por `atribuido_login` do SEI: **57 contas** `origem='auto_snapshot'`, inativas, a maioria sem senha, e **26 delas com `ultimo_login_em` preenchido pelos testes**. É criação de cadastro de quem não pediu, a partir de dado colhido de mesa de trabalho alheia.

- **Manter:** o admin aprova com um clique e a pessoa entra rápido.
- **Trocar por convite:** o admin cria a conta quando a pessoa for entrar; nenhum cadastro nasce de coleta.

**Recomendação:** trocar por convite, e enquanto isso zerar `ultimo_login_em`, `senha_hash` e `senha_trocada_em` das 57 — a tela hoje afirma que servidores reais acessaram o sistema, e eles não acessaram.

### DECISÃO 9.4 — Quem é dono da coleta

O agente id=1, que fez o último contato hoje, tem `dono_usuario_id` NULL e `credencial_titular='titular a preencher'`, com login mascarado `z****@saude.ba.gov.br`. A trilha do SEI carimba um nome em cada ação. **A coleta roda hoje em nome de alguém que o painel não sabe identificar.** Precisa de um nome antes de qualquer uso do sistema fora da estação do desenvolvedor — não é decisão de código.

### DECISÃO 9.5 — Retenção da série histórica

`DIAS['snapshot']=30`. Se o dono quiser relatório de fluxo mensal ou comparação trimestral, o prazo tem de subir — e subir o prazo significa **estocar por mais tempo texto livre com dado de paciente** (`processo_texto` cai junto com o snapshot). Os dois lados: 30 dias cobre a janela em que alguém contesta uma triagem e minimiza retenção; 180 dias habilita tendência e multiplica por 6 o volume de dado sensível retido. **Recomendação:** manter 30 para `processo_texto` e criar retenção separada, mais longa, só para os campos estruturados agregados — o que exige uma tabela de agregado diário, não o aumento do prazo do snapshot.

---

# EXECUÇÃO — 19/08/2026

As nove fatias foram executadas. A suíte saiu de **209** para **312**
verificações, 0 falha, ~21 s, e o corredor agora confere que o banco de trabalho
sai **byte a byte igual** ao que entrou.

| Fatia | Estado | O que ficou medido |
|---|---|---|
| 0 — dependências | feito | `cryptography` e `openpyxl` fixadas; `cofre.disponivel()` prova o import; suítes fora da imagem |
| 1 — régua da coleta | feito | com o relógio 5 dias à frente, os 14 relatórios saem **idênticos**; a única medida contra o relógio é a idade da própria coleta |
| 2 — ordem das coletas | feito | ingerir 18/08 depois de 19/08 mantém 19/08 corrente e marca a atrasada como `rejeitado`, com motivo |
| 3 — onde está / o que houve | feito | N1: 241 unidades de destino, 219 abertos em mais de uma, 153 com árvore≠andamento; N2: 529 textos crus → 20 classes, resíduo de **3** processos |
| 4 — papel na carga nominal | feito | servidor recebe 403 na tela **e** no `.xlsx`; ganha "Minha fila", que diz quando o nome não casa |
| 5 — moldura | feito | `portas.py` única (5 portas, incluindo Pessoas); zero fonte externa em 11 templates; chave de tema unificada com migração; montagem idempotente |
| 6 — bancada limpa | feito | contas de teste 0; `auto_snapshot` com acesso registrado 0 (eram 26, todos falsos); suítes passam com o banco marcado somente-leitura |
| 7 — travas da IA | **só as travas** | modelo corrigido, adesão por unidade, mascaramento, validação de saída, procedência obrigatória por gatilho, teto de gasto. **A integração segue desligada** (DECISÃO 9.1 pendente) |
| 8 — resumo com data | feito | 71 de 71 cartões com texto de IA mostram "descreve 13/08"; resumo fora do índice de busca; `DIAS['resumo']=60` |
| 9 — operação sem culpa | feito | 78 alertas em **4 grupos** com reconhecimento em lote; agente lógico nasce desarmado; agente sem dono recebe recusa legível |

## Defeitos que só a tela mostrou

Três achados não vieram da suíte — vieram de abrir o painel no navegador. Ficam
registrados porque o padrão importa mais que os casos:

1. **`COLETA_EM` chegava como frase** ("último dia útil (18/08 07:45)", sem ano).
   A régua da Fatia 1 não casava e caía no relógio **em silêncio**: o template
   passava em toda conferência de texto e o painel voltava a envelhecer sozinho.
   Hoje `coleta_em` é data e `coleta_frase` é o rótulo.
2. **`const t` declarado duas vezes** no mesmo bloco derrubou o painel inteiro —
   zero linhas renderizadas — e todas as conferências passaram, porque elas
   procuram trechos e o trecho estava lá.
3. **A tarja de data do resumo estava só na ficha expandida.** A ficha é onde a
   pessoa já desconfiou; o cartão é onde ela decide sem abrir.

A lição comum: **conferir texto de template não é conferir a tela.** Daí saiu
`conferir_js.py`, que analisa o JavaScript de cada template com o Node e está
ligado à suíte — provado contra o defeito real que o motivou.

## O que continua pendente

* **Docker** exige reinício da máquina; `teste_container.py` não rodou.
* **DECISÃO 9.1** (ligar a IA) segue com o responsável. As travas estão prontas;
  ligar sem elas repetiria, dentro do sistema e em escala, um envio que já
  aconteceu uma vez fora dele.
* **A senha do SEI em `automacao_sei.js`** continua comprometida e precisa ser
  rotacionada — proteger segredo já vazado não é proteção.

## Nota de 07/09/2026 — a auditoria de 19/08 está fechada no código

Conferido no código, sem que nenhum documento tivesse dito isso até esta data
(ver `PLANO_EXECUCAO_2026-09-07.md` §2.4). Três bloqueios críticos apontados na
auditoria de 19/08 estão **fechados**:

* a migração do esquema passou a rodar **no import** de `app.py:35` (antes só
  rodava em `__main__`, que o `gunicorn app:app` nunca executa);
* `semear.py --so-contas` existe e é o caminho documentado de bootstrap
  (`servidor/LEIAME_EASYPANEL.md` §3);
* `destino_interno` está tratado como conjunto em `app.py:195` e `:419`.

O que continua **aberto**, sem código novo desde 19/08:

* a assinatura HMAC do agente usa o **próprio Bearer** como chave — garante
  integridade, não sigilo (`ARQUITETURA_ACESSO.md` §6, "O que ainda não existe");
* a senha **provisória** de conta nova não tem expiração.

---

# REVISÃO — 19/08/2026 (oito lentes, verificação adversarial)

46 achados brutos, **33 sobreviveram** a duas tentativas de refutação cada. As
345 verificações de então passavam com **os dois críticos vivos** — que é como
eles chegaram até aqui.

## Corrigidos nesta rodada

**CRÍTICO — a fronteira por unidade valia para LER e não para ESCREVER.**
O escopo de publicação do agente saía do formulário (`f.getlist("mesas")`, sem
conferir vínculo) e, no modo padrão "todas", de `SELECT DISTINCT unidade FROM
snapshot` — todas as unidades do banco. Esse mesmo campo era a única coisa
conferida na publicação. Uma conta comum publicava snapshot `corrente` de unidade
onde não tem vínculo, e a carteira daquela unidade era substituída para todos os
servidores dela. Corrigido em três pontos, com um conceito só: **o escopo é
derivado do vínculo e reconferido no instante da publicação**. O bootstrap
continua vivo — agente sem dono usa o escopo que o admin digitou à mão, que é o
único caminho para a primeira coleta de uma instalação nova.

**ALTO — `mesas_conta` escapava da conferência.** A porta olhava `mesas_coleta`;
a ingestão decide de que unidades nascem snapshots lendo `mesas_conta`. Dois
campos diferentes, e o que decidia não era conferido.

**ALTO — desativar a pessoa não desarmava a estação dela.** `agentes.ativo` nunca
era escrito como 0 por caminho nenhum: a conferência existia e não tinha quem a
acionasse. Quem saiu do órgão seguia publicando, com o nome dele no histórico.

**ALTO — "Comparativo entre unidades" perdia processo aberto em duas unidades.**
Medido: ASTEC saía com 3 dos 5 (−40%), DGESS 19 de 20, CESS 624 de 625 — e é o
relatório que pergunta qual unidade acumula mais processo parado. Agora bate com
o SQL cru: 1.169 = 1.169, e a nota explica por que a soma passa do total.

**ALTO — "Minha fila" imprimia o id interno** (`89941724`) no lugar do número do
processo (`019.2403.2024.0013423-96`). O id não serve nem para pesquisar no SEI
nem para citar em despacho, e a planilha exportada circulava com ele.

**ALTO — "Bloqueados agora" contava bloqueio já vencido.** `bloqueado_ate` é ISO
com offset; `datetime('now')` devolve espaço no lugar do `T`. Como texto,
`'T' > ' '`, então todo bloqueio de HOJE passava no teste mesmo vencido.

**ALTO — o painel ia 2,6 MB pela rede a cada abertura**, sem compressão em lugar
nenhum. Comprimido dá 306 KB: 88% a menos. Com seis pessoas abrindo três vezes ao
dia, 915 MB por mês contra 108 MB.

## Ainda em aberto

Sobraram achados MÉDIOS e BAIXOS não tratados nesta rodada — entre eles o agente
que ignora o escopo e roda `--mesas` sempre (o servidor agora recorta, então a
coleta funciona, mas segue coletando mais do que precisa), o aviso "COLETA
INCOMPLETA" que não filtra por execução, e a duplicação da marcação do menu entre
`templates/_nav.html` e `montar_painel._lateral()`.

**Suíte: 355 verificações, 0 falha.** Cada achado corrigido virou teste — sem
isso, a suíte voltaria a passar com o defeito vivo.

---

# CRITÉRIOS DE SUCESSO — proposta de 07/09/2026, a aprovar pelo dono

Até esta data não existia critério de RESULTADO nenhum — só "pronto" técnico por
fatia (`ARQUITETURA_ACESSO.md` §10, este documento §7). Os quatro abaixo são
**proposta da engenharia**, não decisão do dono, e ficam marcados como proposta
enquanto não forem aprovados, alterados ou substituídos.

| # | Critério | Como medir | Situação em 07/09/2026 |
|---|---|---|---|
| 1 | **≥ 95% das janelas úteis cumpridas, por instância** | execuções com sucesso ÷ janelas devidas no calendário útil, separado por `instancia` | SESAB: 11 dias corridos sem nenhuma coleta; FESF: nenhuma coleta jamais rodou |
| 2 | **Dado com ≤ 1 dia útil de defasagem no painel** | idade do snapshot corrente por unidade, contra o calendário de dias úteis (a mesma régua de R0, §2.1) | SESAB: defasagem de 11 dias; FESF: sem dado |
| 3 | **Usuários ativos por semana** | sessões distintas por `usuario_id` numa janela de 7 dias | não medido — 3 contas ativas hoje, de 64 |
| 4 | **Redução dos processos parados +90 dias** | `rel_permanencia`, faixa "+90d", na mesma régua (R0) | baseline **526**, medido em 19/08/2026; alvo `[a definir]` pelo dono |

Nenhum dos quatro é critério técnico de "pronto" — são medida de resultado, e só
viram compromisso quando o dono aprovar (ou substituir por outros).
