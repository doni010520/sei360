# SEI360 — Especificação

> Ferramenta de triagem da carteira de processos do SEI.
> Instância de referência: **SESAB / seibahia.ba.gov.br — SEI 5.0.4**, órgão `GOVBA`.
> Última atualização: 12/08/2026.

---

## 1. O que é

Um painel que responde três perguntas que o Controle de Processos do SEI não responde bem:

1. **O que está parado e há quanto tempo?**
2. **O que é ação minha e o que é espera de terceiro?**
3. **Onde o processo está agora, e o que foi combinado sobre ele?**

Não substitui o SEI. É espelho: se o SEI não mostraria aquela linha àquele usuário, o painel também não mostra.

---

## 2. Decisão de arquitetura que define tudo

**A sessão do SEI mora no navegador do próprio usuário e nunca sai dele.**

Nenhum componente recebe senha, cookie, semente TOTP ou material de sessão de terceiro. O usuário autentica com as próprias mãos, 2FA incluso, e a coleta apenas reaproveita a sessão já aberta com `credentials:'same-origin'`.

### Descartado, sem gradação

| Opção | Por quê |
|---|---|
| Servidor guardando senha do SEI por usuário | Credencial institucional de terceiro em base de dados. "Criptografada" não muda nada: o servidor precisa da chave para usar |
| Conta de serviço institucional única | Mesmo problema, e vê mais do que qualquer usuário real — o isolamento viraria responsabilidade do nosso código |
| Enviar o cookie de sessão ao servidor | Credencial bearer com o risco inteiro e sem benefício |
| Campo de senha do SEI em tela nossa | Está a um atributo `action=` de virar a opção reprovada, e alguém digita ali por hábito |

O 2FA anunciado nesta instância só seria "resolvido" desativando-o ou guardando os dois fatores no mesmo lugar — contornar um controle de segurança do órgão.

E o log do SEI carimba o usuário nominal em cada movimento: um robô agindo com a credencial de alguém produz acesso imputado a quem não o fez.

### Alvo de médio prazo

Integração oficial via PRODEB / TIC SESAB. É o único caminho com coleta agendada, retrocarga e SLA. Se o órgão fornecer o dado, este projeto deixa de existir — o melhor desfecho possível.

---

## 3. Mecânica da coleta

### 3.1 O que o SEI expõe

Não há API. Não há endpoint em lote. Tudo vem de HTML.

| Item | Como |
|---|---|
| Lista de processos | `POST` em `#frmProcedimentoControlar` com `hdnTipoVisualizacao='D'` (detalhada) |
| Paginação | `hdnDetalhadoPaginaAtual`, **0-based**; iterar pelos `value` das options |
| Datas e mesas | **5** requisições por processo: `procedimento_trabalhar` → árvore → `procedimento_consultar_historico` → `acompanhamento_gerenciar` ‖ `procedimento_alterar`. Mais 4 por processo com histórico truncado. (Esta linha dizia 3 — as duas últimas foram acrescentadas depois e a conta nunca foi refeita: a rede era subestimada em 40%.) |
| Codificação | **ISO-8859-1** na resposta; UTF-8 na gravação |

### 3.2 Regras duras

Cada uma corrige um defeito observado em campo, não é precaução teórica.

1. **Nunca montar URL à mão.** Requisição sem `infra_hash` válido não devolve erro — **o SEI invalida a sessão** e joga para o login. Toda URL vem de elemento renderizado.
2. **Nunca cachear URL com `infra_hash`.** Hash expirado tem o mesmo efeito: derruba a sessão de trabalho real da pessoa. A cadeia é redescoberta sempre.
3. **Nunca navegar a aba do usuário.** Sem sessão, avisa e para.
4. **Disjuntor**: duas quedas de sessão numa execução encerram a coleta. Zero retry cego.
5. **Unidade lida do cabeçalho** a cada execução, nunca de constante.
6. **`dias_na_unidade` não é gravado.** Persiste-se a data-marco; o número é calculado na exibição. Número gravado congela e o painel de triagem mente conforme o snapshot envelhece.
7. **Falha é reprocessável.** Erro conta como pendente, não como concluído.
8. **Truncamento é declarado.** Histórico pagina em 100 linhas; quem bate no teto é marcado e reprocessado em modo completo (`hdnTipoHistorico='P'`).

### 3.3 Custo

| | |
|---|---|
| Uma mesa, 219 processos | ~669 requisições, ~45 s com concorrência 4 |
| Conta com 4 mesas | ~2.700 requisições |
| Periodicidade recomendada | **2× por dia** (mediana de permanência é 9 dias) |

De hora em hora seriam ~16 mil requisições/dia contra a PRODEB — não se justifica.

---

## 4. Modelo de dados

Um registro por processo por mesa.

| Campo | Origem |
|---|---|
| `id`, `protocolo` | linha da tabela |
| `tipo_processo`, `especificacao` | `aria-label` do link, formato `"<Tipo> / <Especificação>"` |
| `visualizado` | classe `processoNaoVisualizado` |
| `atribuido_login` / `atribuido_nome` | célula de atribuição: texto = login, `title` = nome |
| `marcador`, `marcador_cor` | `aria-label` do ícone; cor no nome do arquivo `marcador_<cor>.svg` |
| `anotacao`, `anotacao_autor`, `anotacao_data` | tooltip `infraTooltipMostrar('<texto>','<autor> em <data>')` |
| `retorno` | ícone de retorno programado |
| `doc_incluido` | ícone `exclamacao.svg` |
| `autuacao`, `gerador_unidade`, `gerador_usuario` | movimento "Processo gerado" no histórico |
| `recebimento`, `envio`, `unidade_envio` | movimentos da unidade corrente |
| `marco_unidade` | data de entrada nesta unidade (base do cálculo de dias) |
| `mesas` | `Nos[0].html` da árvore; máquina de estados do andamento como conferência |
| `mesa_coleta` | unidade em que a coleta rodou |

**Uma célula pode ter vários links.** Ler só o primeiro perde marcador, retorno e documento incluído — foi um defeito real.

---

## 5. Próxima etapa sugerida

Motor de **regras explícitas**, não julgamento. A primeira que casa vence, e cada uma expõe o motivo.

| # | Regra | Classe |
|---|---|---|
| 1 | Retorno programado | ação sua |
| 2 | Não visualizado | ação sua |
| 3 | Sem atribuição | ação sua |
| 4 | Aberto só em outra unidade | espera |
| 5 | "Aguardar retorno" há +30d | ação sua |
| 6 | "Aguardando validação" há +15d | espera |
| 7 | Bloco de assinatura | ação sua |
| 8 | Documento incluído | ação sua |
| 9 | Parado +90d | ação sua |
| 10 | Anotação há +60d | ação sua |
| 11 | (padrão) Acompanhar | em ordem |

A separação **ação sua × espera de terceiro** é o que muda o dia: 44 contra 28 na carteira atual.

---

## 5-ter. Busca avançada — perguntar ao SEI com o login de quem pergunta

A carteira é o que chegou até a mesa. A busca é o resto do SEI. Ela existe porque
a segunda pergunta de quem abre o sistema é sempre "e o processo que **não** está
na minha carteira?".

### O que ela é, e o que ela não é

**É** uma pergunta feita ao SEI com a credencial da própria pessoa, executada
pelo agente, cujo resultado é uma lista com estado honesto — completa, parcial,
vazia ou falhou.

**NÃO É** um caminho de ingestão. O resultado não vira `snapshot`, não entra no
poço, não cria linha em `processo` e não é servido a mais ninguém. O motivo é
concreto: a tela de resultado do SEI responde à pergunta que foi feita e **não
prova** que aquele processo pertence à mesa de quem buscou. A fronteira inteira
do produto se apoia em `mesa_coleta`, que é campo autodeclarado pela coleta —
deixar uma busca escrever ali seria sancionar a forja que as travas do poço
existem para impedir.

### Os filtros

Os seis do sistema irmão desta casa (`sei_sistema/sei_painel.py`, aba Busca
Avançada), mais quatro que ele não expõe:

| filtro | de onde veio |
|---|---|
| com tramitação na unidade | sistema irmão (marcado por padrão) |
| tipo do processo · especificação · contato · assunto · observação | sistema irmão |
| **número SEI** | o motor do sistema irmão já aceitava e a tela dele nunca mandou |
| **data de · data até · a data é de** | **novos** |

As datas são a adição que mais importa, e não é enfeite: sem elas, "com
tramitação na unidade" com os campos vazios é uma **varredura da mesa inteira
disparada por um clique**. No sistema irmão foi exatamente isso que rodou —
medido no log dele: 718 processos, 72 páginas, 226 s, sem ninguém ter digitado
nada. Aqui o servidor **recusa** busca sem nenhum critério, e diz por quê.

### Ids com alternativas, e recusa declarada

Cada campo tem vários ids candidatos, tentados em ordem — é o que faz o mesmo
motor atravessar o SEI 4.0 (FESF) e o 5.0.4 (SESAB) sem um `if` de versão
espalhado pelo parser. Essa forma vem do sistema irmão, que chegou nela por
tentativa e erro contra o SEI de verdade.

Campo que não casa com nenhum id **não é preenchido em silêncio**: entra em
`filtros_recusados` e aparece na tela de quem pediu. No sistema irmão o tipo de
processo é casado por `String.includes` **sensível a maiúscula**, e o log diz
"Filtro aplicado" mesmo quando nada casou — digitar `dispensa` em vez de
`Dispensa` devolve o acervo inteiro, e a tela não tem como saber.

### O estado é calculado, nunca aceito

O SEI escreve "N registros" na própria página. O servidor compara esse número com
o que veio:

```
sem total declarado          -> falhou   (não há com o que reconciliar)
declarado 0 e nada veio      -> vazia
colhidos == declarado        -> completa
bateu o teto de páginas      -> parcial, com o teto dito
declarado > colhidos         -> parcial, com os dois números
```

O sistema irmão captura esse total e **nunca o compara**; e o teto de 200 páginas
dele só emite um aviso no log, sem bandeira no valor de retorno. Uma paginação
que falha no meio devolve metade com cara de tudo.

### Uma busca por conta do SEI, de cada vez

**Medido, não suposto.** A troca de mesa no SEI é por **usuário**, não por sessão:
duas buscas simultâneas da mesma conta em mesas diferentes devolvem a carteira
errada **sem erro**. O sistema irmão desabilitou o paralelismo por isso, depois de
ver todos os workers voltarem com 0 linhas.

A trava é por `(instância, conta)` — quem tem conta nas duas instalações pode
buscar nas duas ao mesmo tempo. E ela **degrada**: pedir com uma busca em curso
devolve o id da que está rodando, e a tela mostra o progresso dela.

### O que não se guarda

`especificacao`, `anotacao` e `interessados` — o texto que um servidor escreveu, e
onde pode haver nome de paciente. Eles vivem em `processo_texto`, separados de
propósito, e o consentimento para tratá-los é por unidade (`aceite_ia`). Guardá-los
aqui seria um segundo caminho para o mesmo dado, sem o mesmo cuidado.

No `log_acesso` entra o **sha** dos filtros, não o texto: o log é lido por gestor
e admin, e o filtro de uma pessoa pode citar nome próprio. O sha responde "foi a
mesma busca?" sem dizer qual.

Prazo: **30 dias**. É lista de trabalho, não acervo.

---

## 5-quater. Duas instalações do SEI

| | SESAB | FESF-SUS |
|---|---|---|
| login | sip.seibahia.ba.gov.br | sip.fesfsus.ba.gov.br |
| versão | 5.0.4 | 4.0.x |
| órgão no login | `#selOrgao` = 23 | **não tem** (instalação de um órgão só) |
| **busca** | disponível | **disponível** |
| **coleta** | disponível | **não** |

A FESF **busca e não coleta**, e as duas disponibilidades são campos separados
porque são coisas diferentes: a busca usa a tela Pesquisa, que existe nas duas
versões; a coleta usa a visualização Detalhada do Controle de Processos
(`hdnTipoVisualizacao='D'`), que é do SEI 5 — no 4.0 a troca de visualização
**falha em silêncio**, devolve a tela antiga, e o parser da listagem do 4.0 não
existe. Uma flag só obrigaria a escolher entre mentir sobre a busca ou esconder o
que funciona.

### `id_sei` colide entre instalações — e por isso entra na chave

`id_sei` é o `id_procedimento` do SEI: sequência autoincremento **por
instalação**. Duas instalações são duas sequências começando em 1 sobre o mesmo
domínio de inteiros; não dá para provar que não colidem.

O custo de uma colisão: o poço devolveria a uma mesa da FESF o bloco de um
processo da SESAB — protocolo, assuntos, interessados, `gerador_usuario` e o
`mov_custodia` com o nome de quem movimentou. Nenhuma trava olharia, porque para
ela o id bate.

Coluna informativa não impede colisão; **chave impede**. `instancia` entrou na
PRIMARY KEY de `poco_processo`, `poco_conferencia`, `poco_acompanhamento`,
`poco_reserva` e `resumo`, e `sistema` na de `credencial` e `config_usuario`. E
entrou também em **toda consulta**: a chave impede a sobrescrita, não a leitura
que traz as duas linhas e fica com a última.

A migração é explícita (`migracao_instancia.py`), guardada por
`PRAGMA user_version`, e reconstrói as tabelas — `CREATE TABLE IF NOT EXISTS` não
reescreve tabela existente, e o SQLite não tem `ALTER TABLE` que mude PRIMARY KEY.

---

## 5-quinquies. Escala — o que o problema realmente é

O pedido foi "escalar buscas simultâneas em Chromes distintos, nem que seja no
proxy". Os números desta casa dizem que **o eixo é outro**.

**O que limita é a CONTA, não o navegador nem o IP.** A troca de mesa no SEI é por
usuário: dois workers com o mesmo login se atropelam e voltam com 0 linhas. Nenhum
número de Chromes e nenhum proxy resolve isso — e, do outro lado, o que funciona
já está medido: N páginas no mesmo contexto, validado com 3 páginas e **zero
logouts** (`sei_sistema/sei_extractor_parallel.py`).

**A boa notícia é estrutural:** no SEI360 cada pessoa tem o próprio login. Duas
pessoas buscando ao mesmo tempo são dois usuários distintos, e o limite não se
aplica entre elas. A trava por `(instância, conta)` é exatamente essa fronteira.

**Antes de comprar RAM, tirar o `sleep`.** Medido no sistema irmão: 226 s de busca,
dos quais ~213 s foram `wait_for_timeout(3000)` entre páginas — o SEI respondeu em
~30 ms. Paralelizar um laço que dorme 3 s por página é comprar memória para dormir
em paralelo. O motor daqui pagina por `fetch`, com a pausa curta que o coletor já
usa.

**Custo de memória, medido nesta casa:** ~800 MB de base mais ~150 MB por página
adicional; 16 GB comportam 8 a 12 páginas. Um VPS de 2 GB comporta poucas — e o
número que vale para dimensionar container é o do sistema irmão medido em
produção: **0,45 GB por worker**, com 1,5 GB reservados ao sistema.

### A decisão que não é minha

> **O container do VPS passa a rodar Chromium com a credencial do SEI de outras
> pessoas — revogando por escrito o §6.1 e o §3.7 do `ARQUITETURA_ACESSO.md` —
> sim ou não?**

Enquanto a resposta não vier, a busca roda **na estação**, pelo agente, exatamente
como a coleta. O servidor faz o mesmo nas duas hipóteses: valida, enfileira,
trava, reconcilia, grava e expurga. Muda só **quem executa o processo do coletor**
— e é por isso que a resposta pode chegar depois sem nada ser reescrito.

E há um teto acima de qualquer arquitetura: o arquivo de credenciais registra 2FA
**"ANUNCIADO na tela de login"** na SESAB e "possível" na FESF. Se o segundo fator
passar a ser exigido, nenhuma quantidade de navegadores resolve — a busca ao vivo
depende de uma sessão que só a pessoa consegue abrir.

---

## 5-bis. O poço — reaproveitar sem vazar a visão de ninguém

Cada pessoa entra no SEI com o login dela e traz a carteira dela. Duas pessoas
lotadas na CESS buscam os **mesmos 598 processos**, cada uma a 5 requisições por
processo. Com 60 contas, são ~156 mil requisições por dia contra a PRODEB para
produzir 1.165 processos-dia.

### A linha que não se cruza

O que decide o que pode ser compartilhado não é "é caro?", mas **de quem é este
valor**. Medido campo a campo, no HTML de origem:

| Natureza | Campos | Custo | Compartilha? |
|---|---|---|---|
| **do processo** | autuação, gerador (unidade/usuário), nível de acesso, hipótese legal, protocolo, tipo, especificação, assuntos, interessados, documentos, movimentos, anexados, sobrestado, urgente, mesas | caro (5 req) | **sim** |
| **da unidade** | recebimento, recebimento_por, envio, unidade_envio, marco_unidade | caro, mas **derivável** | **recalculado**, nunca copiado |
| **da unidade (lista)** | marcador, anotação, atribuído, retorno | ~12 req **por mesa** | não — é de graça reler |
| **da visão** | visualizado, doc_incluido, origem, mesa_coleta, mesas_coleta | ~0 | **nunca** |
| **da pessoa** | acompanhamento, acomp_grupos | caro | só para a **mesma pessoa** |

Perigoso e caro são conjuntos quase disjuntos — é isso que torna o cache
defensável. A cadeia cara devolve quase só campo do processo; tudo que se suspeita
depender de quem olha vem da lista, que custa quase nada.

Os cinco campos de unidade são **recalculados** a partir de `mov_custodia` (as
transições de custódia do histórico) para a unidade de quem lê. Sem persistir
`mov_custodia`, "recalcular" viraria copiar — e o defeito temido aconteceria
entre mesas em vez de entre pessoas.

### O que a guarda não vê

`CAMPOS_GUARDA` (marcador, atribuído, anotação, retorno, doc_incluido) detecta que
o processo se mexeu **sem custar requisição** — vem da lista. Medido nos 5 pares de
dias desta base:

| | |
|---|---|
| processos que andaram em 24 h | **407** |
| a guarda pegou | **224 (55%)** |
| escaparam → veredito "pular" | **183 (45%)** |
| destes, na faixa "cega" (sem marcador, sem anotação, sem retorno, sem atribuição) | **9 (4,9%)** |

> A primeira versão deste desenho afirmava o contrário — que os escapes estavam
> concentrados na faixa cega — e por isso a faxina priorizava reler justamente ela.
> **A medição inverteu a afirmação**: 95% dos escapes estão FORA da faixa cega. A
> faxina passou a ser uniforme, que é a única escolha defensável sem uma hipótese
> medida sobre onde reler primeiro.

Consequência que fica dita, porque é o que o gestor está lendo quando ordena a
triagem: com ~7%/dia útil de movimento e 45% de escape, **~9% da carteira pode
carregar `marco_unidade` velho dentro da janela de 72 h**. O painel avisa que a
LINHA é antiga (selo de leitura); ele não avisa que o número DENTRO dela pode ter
mudado sem a coleta perceber. Quem fecha esse buraco é a faxina (1/3 por dia) e o
canário, não a guarda.

### Prazos

| Faixa | Prazo | Base |
|---|---|---|
| "frio" (autuação, gerador, hipótese legal) | **sem prazo próprio no código** | 5 mudanças em 5.545 pares de leitura — quase nada, mas não zero; e reler junto custa 0 requisição a mais, porque vem no mesmo histórico |
| morno (movimentos, documentos, mesas, custódia) | 12 h para servir, **teto de 72 h** | ~9%/dia útil de mudança; 1 − 0,91³ = 25% |
| acompanhamento, assuntos, interessados | 7 dias | 1,1%, 0,1% e 0,0% em 5 dias |
| expurgo do bloco | 90 dias sem leitura | não herda o CASCADE do snapshot |

### Invariantes

0. **Bloco condenado nunca é servido.** O veredito `em_leitura` — "outro agente
   está lendo" — só substitui uma leitura quando o bloco anterior ainda responde.
   Sobre bloco vencido, com guarda acusando mudança, ou inexistente, todo mundo
   lê: duplicar custa 5 requisições, servir bloco reprovado custa um número
   plausível e errado. `poco.servir()` aplica o mesmo gate na saída, como segunda
   camada.
1. **A régua é por linha.** Cada linha carrega `medido_em` — a hora da leitura que
   produziu o detalhe dela. Medir uma data velha com o relógio de hoje imprime
   "388 dias na unidade" para um processo que chegou ontem.
2. **O carimbo não rejuvenesce sem leitura.** `morno_em` só avança quando alguém
   leu de fato (`_fresco`). Senão a corrente se realimenta e às 17h50 alguém
   recebe dado de 10h20 marcado como fresco.
3. **Dois relógios.** `morno_em` (estação) e `recebido_em` (servidor); a validade
   exige as duas dentro do prazo. Relógio torto na estação não estica o cache.
4. **Ausência significa "não sei".** Sem movimento da mesa na custódia, os cinco
   campos saem nulos e a linha vai marcada — nunca lida como "sem divergência".
5. **O poço nunca cria linha.** É um LEFT JOIN por `id_sei` sobre a lista que a
   pessoa trouxe. Acrescentar linha seria mostrar processo que o SEI talvez não
   mostrasse àquela pessoa.
6. **Leitura degradada não publica.** Sem histórico, truncado, com páginas não
   lidas, árvore que não parseou, nível de acesso fora de Público/Restrito: nada
   disso entra. Numa segunda-feira de layout novo, 10 coletas quebradas têm de
   ser 10 alarmes, não 1 alarme e 9 snapshots com cara de limpos.
7. **Saída por lista de permissão**, nunca de proibição — chave nova no coletor
   entraria sozinha no cache. `href` carrega `infra_hash` de sessão, e reusar
   hash morto **derruba a sessão** de quem está trabalhando (regra dura 3.2 #2).

### O plano

A coleta virou duas metades, com a pergunta ao servidor no meio:

    listarTodasAsMesas()          ~13 req por mesa, SEMPRE
      -> POST /api/poco/plano     veredito por processo
    detalharTodasAsMesas(plano)   5 req só por processo devido

Vereditos: `completa` | `so_acompanhamento` | `pular` | `canario` | `em_leitura`.
O servidor nunca devolve a data do bloco — o relógio é dele, e a estação não
decide validade. O plano **atribui**: os processos a ler ficam reservados por 20
min para aquela execução, senão as 31 pessoas da CESS recebem o mesmo plano no
mesmo minuto. Servidor fora do ar degrada para "ler tudo".

### Quanto isto economiza, de verdade

A primeira versão deste desenho prometia **−85%**. Refeita a conta com as taxas
medidas nesta base, o regime permanente é outro:

| | |
|---|---|
| guarda acusou mudança → `completa` (5 req) | 5,6% |
| faxina do dia → `completa` (5 req) | ~20% |
| restante → `so_acompanhamento` (3 req, não 0) | ~75% |
| **média** | **3,5 req/processo — cerca de −30%** |

Três pisos que a promessa de −85% ignorava:

- `so_acompanhamento` **não é grátis**: `procedimento_trabalhar` + árvore +
  `acompanhamento_gerenciar` = 3 das 5 requisições. Poupa 40%, não 100%. E 76% dos
  processos não têm acompanhamento nenhum: pagam as 3 requisições só para
  reconfirmar lista vazia.
- as ~12 requisições de **lista por mesa** nunca são poupadas — e é de propósito:
  é ali que estão os campos que não podem atravessar pessoa.
- **hoje N=1.** Há UM coletor real na instalação; as 60 contas são leitores do
  painel. Com uma pessoa por mesa, a única economia é a segunda coleta do mesmo
  dia. Os −85% pressupunham N pessoas por mesa e não descrevem o parque atual.

E no **primeiro dia** (ou no dia seguinte a um expurgo) a economia é **zero por
construção**: sem bloco no poço não há o que servir, e todo agente lê tudo. Pular
o que ninguém leu seria entregar linha vazia.

### Escalonamento

Todo agendamento nasce com `07:30`. Com uma coleta por conta, isso deixa de ser
um horário e vira uma marcação coletiva contra o mesmo servidor da PRODEB. Cada
agente ganha um desvio **estável** derivado do id (até 60 min, dentro da
tolerância de 90).

---

## 5-sexies. Os relatórios — o que a auditoria de 21/08/2026 encontrou

Duas rodadas: 5 lentes independentes acharam 56 defeitos; cada um foi entregue a
um agente instruído a **refutá-lo**, lendo o código e medindo no banco. Sobraram
**41 sustentados e 13 derrubados**. O que segue é o que os 41 ensinaram.

### As duas telas contavam dias de dois jeitos

`_dias()` truncava a hora nas duas pontas e devolvia diferença de **calendário**;
o painel, sobre o mesmo dado, contava o **intervalo** e fazia floor. No mesmo
segundo, sobre 1.165 processos: painel **432**, `/relatorios/triagem` **526** —
+21,8%. Os 94 da diferença têm marco em 19/05/2026: 91 dias contando viradas de
meia-noite, 90 contando horas.

O que torna isso um caso a estudar não é o defeito, é como ele sobreviveu. O
comentário do próprio `_dias()` **afirmava que a divergência tinha sido
corrigida** — e tinha, em parte: a régua por linha foi consertada e a truncagem
ficou. Conferência por leitura não separa "o comentário diz" de "o código faz".

Por isso a conferência agora **executa os dois**: `conferir_dias.js` extrai as
funções do `painel.html` servido, `teste_relatorios.py` escreve `_casos_dias.json`
com 415 casos (400 da base real + as bordas: 24h exatas, 90 dias exatos, virada
de ano, 29/02, marco no futuro, servido do poço) e a resposta do Python, e o
Node compara **número a número**. Foi ela que achou o que eu não veria: `31/02`
vindo do SEI, onde `new Date(2026,1,31)` rola para 3 de março e o painel dizia
"170 dias" enquanto o relatório recusava a data. Duas telas discordando por um
dado que nenhuma das duas deveria aceitar.

**Regra que fica:** quando dois códigos respondem à mesma pergunta, a conferência
é rodar os dois sobre os mesmos casos. Ler os dois não é conferir.

### Percentual sem denominador declarado

`grafico()` dividia pela **soma da coluna**. Isso só é a base quando as linhas
particionam a carteira — e em metade do catálogo elas não particionam: se
sobrepõem (`onde_aberto` soma 1.640), são recortes sobrepostos (`triagem` soma
962) ou vêm truncadas (`procedencia` somava 1.070). O panorama de triagem
imprimia "Parados há mais de 90 dias — 526 · **54,7%**" logo abaixo de "Base:
1165", quando são 45,2%; e como a tabela de triagem não tem coluna de %, aquele
era o **único** percentual que a pessoa via.

Hoje o denominador é a base e a legenda diz qual é, com a soma quando ela passa
do total. **Percentual que não diz sobre o quê é afirmação sem referente.**

### Rótulo é afirmação, e afirmação se mede

Três casos, o mesmo erro:

* "Última coisa que aconteceu" lia `mv['de']` e descartava `mv['un']`. As classes
  são frases com sujeito de unidade — "Concluído na unidade" —, a tela inteira
  tem por recorte a carteira de quem lê, e **321 dos 1.165 (27,6%)** aconteceram
  fora dela. Os 71 "Concluído na unidade" foram concluídos em outra e continuam
  abertos aqui; os 5 "Enviado a outra unidade" descrevem remessas entre duas
  unidades terceiras. Duas colunas novas — *na sua unidade* / *em outra*.
* "Nunca visualizados **por ninguém da unidade**" mede a marca da lista do SEI da
  **conta que coletou**. Um processo que a colega abriu aparece como nunca visto.
* "Mediana de dias" usava `valores[len//2]`, o elemento **superior** do par
  central: 21 das 58 linhas mostravam número que não é mediana (447 onde é 273).

### O que ficou de fora, nomeado — inclusive quando some por corte

`rel_procedencia` fazia `[:40]` sobre 123 grupos: 83 descartados, **95 processos
somiam** e a coluna somava 1.070 sob um cabeçalho anunciando 1.165. O corte ainda
caía no meio de um empate. Agora há linha de resto e a coluna fecha com a base.

`rel_volume` calculava o balde "sem informação" e nunca o listava. Hoje está
vazio; no dia em que não estiver, sumiria em silêncio.

### Números escritos à mão apodrecem

A lista de relatórios **inviáveis** trazia "62 processos em 1.165 (5%)" escrito
na constante — dentro do único módulo cuja regra declarada é "cobertura medida,
não estimada". Quando a auditoria foi conferir, dois dos cinco já estavam
errados (`hipotese_legal` tem 61, `unidade_envio` 314), e o numerador de uma
coleta convivia com o denominador de outra. O motivo continua sendo texto; o
número passou a ser medido na hora.

### Uma pergunta, uma regra de leitura

A tarja "Dado de" do relatório era derivada dos **processos** e ficava cega para
`medido_em IS NULL`, para o poço e para unidade cujo snapshot veio vazio — então
`/relatorios` mostrava VERMELHO "625 linha(s) SEM detalhe lido nesta coleta" e
`/relatorios/permanencia`, um clique depois, mostrava VERDE. As duas telas agora
chamam `estado_coleta()`.

Mesmo padrão na dedup: a chave era `id_sei` puro, e `id_sei` é sequência **por
instalação** — com a FESF ativa, dois processos diferentes viravam um. Hoje é
`(id_sei, instancia)`. E os cinco campos de custódia deixaram de ser lidos do
snapshot que venceu a dedup: `_por_unidade` guarda o dado de **cada** mesa, que é
a mesma regra que `poco.py` aplica ao servir bloco entre pessoas.

### O que foi DERRUBADO, e por quê importa registrar

13 dos 56 não sobreviveram à refutação, e a lista serve tanto quanto a outra:

* "o JOIN de `resumo` duplica linhas quando a segunda instância chegar" — mediu-se:
  o JOIN duplica a linha crua, mas a dedup consome a duplicata antes de qualquer
  relatório ver. (O JOIN saiu assim mesmo: ninguém lia o resultado.)
* "`_dias()` volta a medir contra o relógio quando a régua não parseia" — o
  caminho existe, mas `coletado_em` é `NOT NULL` no DDL e o valor é gerado por
  `agora()`: a entrada que dispararia isso não pode existir.
* "empate sem critério estável" — o desempate por rótulo já existia em `_agrupar`.
* "`_dias_autuacao` é calculado e jogado fora" — já tinha sido removido.
* "os 14 relatórios não entregam a lista por trás do número" — o drill-down existe
  na triagem, e o catálogo declara isso.

**Achado com número errado ainda pode ser real; achado com mecanismo certo e
consequência impossível, não.** A refutação separou os dois.

### O custo, medido

`SELECT p.*` mais dois LEFT JOIN cujas colunas ninguém lia: **11,8 ms → 3,6 ms**,
e 137 KB de texto livre do SEI (`especificacao`, `anotacao`, `acompanhamento`) —
que pode citar nome próprio — pararam de atravessar o processo a cada
requisição. `rel_por_responsavel` fazia 67.570 comparações para produzir 58
linhas. `cobertura()` era chamada duas vezes por campo. Nada disso era o gargalo
sozinho; juntos, eram a maior parte dele.

## 5-septies. O verificador mentiu — duas vezes, na mesma tarde

Caçando uma "intermitência do produto" em 25/08/2026, encontrei duas falhas no
ARNÊS, e nenhuma no sistema. Ficam registradas porque custaram horas e porque as
duas têm a mesma forma: **o verificador transformando ausência em aprovação**.

### 1. `isolar()` apagava o banco da execução vizinha

`ambiente_teste.isolar()` monta o diretório de trabalho com nome FIXO
(`TEMP/sei360_teste_<suíte>`) e a primeira coisa que faz é `shutil.rmtree`. Duas
execuções da mesma suíte ao mesmo tempo — eu medindo enquanto seis agentes de
revisão também rodavam a suíte — e a segunda apaga o SQLite que a primeira tem
aberto, no meio da corrida.

Medido: cinco rodadas deram **267, 340, 351, 453 e 744** verificações, com 0 a 12
falhas, todas em lugares diferentes. Passei horas atrás de um defeito que não
existia, e cheguei a suspeitar do `atendente.py` — que era inocente.

Hoje há uma trava por suíte: quem chega segundo é **recusado**, com o PID de quem
está dentro. Trava de execução morta é tomada, para Ctrl+C não trancar o
diretório para sempre.

### 2. Suíte que não rodava contava como zero falhas

```python
n_ok, n_falha = (int(m[1]), int(m[2])) if m else (0, -1)
total_falhas += max(0, n_falha)          # -1 vira 0
```

Quando uma suíte morria antes de imprimir o resumo, `n_falha` era -1 e o `max` o
transformava em **zero**. A linha da suíte dizia `FALHOU`; a linha final — que é
a que se lê — dizia `602 verificações, 0 falha(s)`.

O total nunca mentiu sobre um número. Mentiu sobre uma **ausência** — e é
exatamente contra isso que o resto deste documento foi escrito. O defeito estava
no próprio verificador, que é o último lugar onde alguém vai procurar.

Agora são **três** estados (`ok` / `FALHOU` / `BLOQUEADA`), suíte que não rodou é
nomeada na linha final, e a saída é diferente de zero — "passou" só quando TODAS
rodaram. A contagem virou `ler_saida()`, uma função pura, e **cinco casos dela
rodam a cada execução da suíte**, antes de tudo: se o conferidor estiver errado,
o relatório inteiro é opinião.

**A regra que fica:** quando o verificador e o verificado discordam, suspeite do
verificador primeiro — ele é quem ninguém confere.

## 5-octies. A revisão da sessão — o que a execução no servidor custou

Depois de trazer a busca para dentro do container, uma revisão adversarial de 6
lentes achou 56 defeitos; a refutação sustentou 33. O que segue é o que os mais
graves ensinaram — e três deles eram do próprio trabalho desta sessão.

### O `.dockerignore` não aceita comentário no fim da linha

`**/_dados   # o banco` é, para o Docker, um **padrão literal** com espaços e uma
cerquilha dentro. Ele não casa com nada. Cinco linhas escritas assim eram letra
morta, e o que elas deveriam barrar — **banco de produção, coletas brutas, a
sessão do SEI e a chave do cofre** — entrava na imagem.

O `conferir_contexto.py` não pegava porque **ele** removia o comentário antes de
avaliar: media a intenção de quem escreveu, não o efeito. Certificava "nada do
que não pode" sobre um contexto que o Docker leria como 282 arquivos e 70,8 MB
em vez de 93 e 2,4 MB.

**Conferidor que mede a intenção é pior que conferidor nenhum:** ele produz
confiança justamente onde o erro é invisível. Hoje ele lê como o Docker lê e
**recusa** a linha com `#` no meio, em vez de adivinhar.

### Um perfil de navegador para todo mundo quebrava a atribuição nominal

`SEI_PERFIL_DIR` era um diretório só. A busca de A logava e deixava o cookie; a
de B reaproveitava a sessão de A — `goto(LOGIN)` nem caía em `login.php`. O cofre
registrava "B usou a credencial", `busca` dizia que a busca era de B, e **o SEI
gravava tudo com o nome de A**.

A atribuição nominal é o custo que o §6.0 assumiu por escrito ao trazer a
execução para o VPS. Ela estava quebrada por dentro: nem o log do SEI nem o nosso
diziam a verdade. Hoje o perfil é `<raiz>/u<id>-<instalação>`.

Junto veio a senha no volume: `SEIAuto.credencial()` grava `{usuario,senha}` com
`btoa` no `localStorage`, e base64 é ofuscação. Depois de cada busca a senha
ficava legível no volume do VPS. Hoje o coletor a apaga logo após o login e
**mantém o cookie** — que é o que evita relogar, e relogar é onde o segundo fator
aparece. Só no servidor: na estação a coleta agendada roda sem stdin e depende
dela.

### O executor podia perder as vagas e nunca mais executar nada

Duas janelas entre `acquire()` e `Thread.start()` — `pegar()` levantando, e
`Thread.start()` levantando — e uma terceira em `banco.conectar()` fora do `try`.
Em qualquer delas a vaga sumia. **Duas ocorrências e o semáforo chegava a zero
para sempre:** o laço continuava vivo, `capacidade()` continuava dizendo que
podia, a tela continuava com o botão ligado, e toda busca de todo mundo morria em
90 s acusando "o agente não está rodando" — um agente que **não existe** no modo
servidor. Só reiniciar o container consertava.

O gatilho não era exótico: a ingestão escreve ~1.165 linhas num commit só, no
mesmo processo em que o laço sonda a fila a cada 3 s, com `busy_timeout=5000`.

E havia um quarto: `while _vagas.acquire()` re-adquiria a vaga que a thread
acabara de devolver, então uma execução que falhasse rápido virava criação de
thread em laço quente — medido, centenas de threads em segundos. Uma passada
oferece no máximo `LIMITE` vagas, e a vaga volta em **um único lugar**.

### Resultado meio gravado não pode ser "completa"

`receber()` gravava o veredito ANTES dos itens e `executar()` fechava com
`finally: cx.commit()`, incondicional. Um INSERT que levantasse no meio publicava
"completa · 5 de 5" com dois itens. É o "607 de 607 e ninguém conferiu" que o
cabeçalho de `busca.py` existe para impedir, produzido pelo executor recém-
escrito. Hoje os itens entram primeiro, o veredito por último, e o commit só
acontece no sucesso.

### Fila cheia não é "o agente não está rodando"

Com `LIMITE=2`, a terceira busca fica na fila — e `varrer()` a matava aos 90 s
com a frase do agente. Pior: **a própria tela dispara a varredura**, poleando a
cada 2 s. O ato de esperar matava a espera. Três pessoas ao mesmo tempo é o caso
normal de um painel multiusuário, e a maior busca medida levou 226 s.

### Cancelar soltava a conta com o coletor ainda logado

A trava caía no cancelamento, a pessoa pedia outra na hora, e dois Chromium
entravam na MESMA conta do SEI — a corrida que a troca de mesa não tolera. Hoje a
trava só cai quando ninguém pegou; quem já pegou solta em `receber()`, que é o
instante em que se sabe que o coletor saiu.

### A regra do teste que este projeto aprendeu de novo

Dos 22 mutantes rodados nesta sessão, **7 escaparam — e todos por teste fraco,
nenhum por código errado**:

* procurar `SEI_ESQUECER_APOS_LOGIN` no fonte passa com o valor trocado de `"1"`
  para `"0"`;
* chamar `pegar()` e `entregar()` em sequência não exercita corrida nenhuma — o
  `WHERE estado='pedida'` do SELECT já resolve; a corrida é os dois **lerem** e só
  depois escreverem;
* patchar `banco.conectar` e chamar `rodada()` sem conexão faz o próprio
  `rodada()` estourar **antes** de pegar vaga: o teste passava sem chegar à
  thread;
* afirmar `_at.ligado() is True` num teste chamado "o laço pode ser desligado"
  testa a posição em que o interruptor estava, não o interruptor.

**Teste que quebra quando o código melhora está testando a redação.** Foi o que
aconteceu quando o *denylist* virou *allowlist* e três verificações reclamaram —
elas procuravam a palavra `startswith`.

## 5-nonies. O poço estava certo; o dado é que era velho

A revisão anterior fechou com uma acusação: **o poço nunca serviu uma linha**
(`poco_processo` = 0, `servido_do_poco=1` = 0), e o culpado seria o agente de
*bootstrap* sem dono. Estava errado nas duas partes.

**O dono nulo é de propósito** e está dito no código (`app.py`, rota de
publicação): a estação de *bootstrap* é como toda instalação começa, e a coleta
dela fica marcada como COMPARTILHADA até cada pessoa ter a sua. Medido numa
cópia: com `dono=None` o poço publica **1.041 blocos** normalmente — só o
`poco_acompanhamento` fica em zero, e deve mesmo: acompanhamento é de uma
pessoa, não do órgão.

**A causa real é a idade do dado.** O único arquivo já ingerido no banco de
trabalho é `sei_sesab_2026-08-18.json`, e ele é ANTERIOR às marcas que o portão
do poço exige. Passando as duas coletas pelo mesmo `publicavel()`:

| coleta | passariam | por que não |
|---|---|---|
| 18/08 | **0 de 1.165** | 1.159 sem `alterar_disponivel` (o campo nem existe no arquivo), 6 truncados |
| 26/08 | **1.044 de 1.196** | 143 com páginas não lidas, 7 truncados, 2 sem árvore |

O portão fez exatamente o que existe para fazer. Os arquivos de 22/08 em diante
pulam de 2,4 MB para 6,1 MB — é o dia em que o coletor passou a trazer
`mov_custodia`, `alterar_disponivel` e a árvore.

**E o cache paga o que promete.** Ponta a ponta, numa cópia do banco: ingerida a
coleta de 25/08, o plano para a de 26/08 manda pular **620 dos 1.196** processos
e o poço serve os 620 — nenhum órfão. **52% da leitura evitada**, com sete mesas.

| mesa | itens | pular | servidos |
|---|---|---|---|
| CESS | 644 | 344 | 344 |
| UMA-CMA | 286 | 158 | 158 |
| COMASUP | 237 | 109 | 109 |
| DGESS | 13 | 2 | 2 |
| CESS/IM | 10 | 7 | 7 |

O que falta não é código: é **ingerir as coletas de 19/08 a 26/08**, que estão em
`painel_sesab/_coletas/` sem nunca terem entrado. Enquanto não entrarem, o painel
mostra 18/08 com a idade dita — e o poço fica vazio com razão.

### Quatro medidas de eficiência, nesta ordem de tamanho

**1. `PRAGMA journal_mode=WAL` a cada conexão — 1,48 ms dos 1,94 ms.** O modo é
PERSISTENTE: fica gravado no cabeçalho do arquivo e vale para qualquer conexão
que o abrir depois, de qualquer processo. Reaplicá-lo não muda nada e exige lock
no arquivo mesmo quando o modo já é o pedido. Medido: `connect()` sozinho leva
0,16 ms; com o PRAGMA, 1,94 ms. Agora roda **uma vez por processo e por caminho
de banco** — o que continua cobrindo o arquivo recém-criado, único caso em que o
modo realmente muda. `conectar()`: **1,94 ms → 0,17 ms (11×)**. O painel abre 6
conexões; a tela de relatórios, 5.

**2. O painel perguntava a idade da coleta duas vezes.** `estado_coleta()` era
chamada para carimbar a auditoria e de novo, vinte linhas abaixo, para a faixa —
duas passadas por `snapshots_de` e pela tabela `snapshot` a cada abertura, pelo
mesmo número.

**3. 1,34 MB de vendor pedindo permissão a cada tela.** O padrão do Flask é
`no-cache`, que não quer dizer "não guarde": quer dizer "guarde e PERGUNTE a cada
vez". A tela de acesso é a mais cara — sozinha puxa d3 (273 KB) e gsap (70 KB),
que existem para a animação e **são parte do desenho**: o conserto certo não é
tirar a animação, é fazer o arquivo descer uma vez. `estatico/vendor/` passa a
sair com `max-age=1 ano, immutable`; **`sei360.css`, `nav.css` e `lateral.css`
ficam de fora de propósito** — mudam a cada correção, somam 36 KB e o caminho não
tem versão. Um ano de cache neles seria consertar uma cor e a pessoa seguir vendo
a antiga.

**4. `_por_unidade` era montado para treze telas jogarem fora.** É lido por UM dos
catorze relatórios. Montá-lo na carga custava duas conversões de fuso e duas
subtrações de data por processo por unidade — 2.334 de cada em todo `carregar()`.
Agora a carga guarda a linha crua (referência, custo zero) e `por_unidade_de()`
calcula sob demanda, memorizando na própria linha.

| tela | antes | depois |
|---|---|---|
| painel | 101 ms | **93 ms** |
| /relatorios/permanencia | 52,8 ms | **49,5 ms** |
| /relatorios/procedencia | 49,6 ms | **48,2 ms** |
| `carregar()` | 27,9 ms | **25,8 ms** |
| `conectar()` | 1,94 ms | **0,17 ms** |

**Os quatro consertos viraram teste, e os quatro testes foram atacados.** Soltos
um a um, os mutantes — WAL de volta a cada conexão, painel perguntando duas
vezes, vendor de volta ao `no-cache`, `_por_unidade` de volta à carga — foram
pegos pelos quatro. O teste do `estado_coleta` **conta chamadas** em vez de ler o
fonte, porque ler o fonte já se provou fraco aqui (§5-septies). Suíte: **935
verificações, 0 falha**.

### O dado novo derrubou quatro verificações — uma era defeito de verdade

Ingerida a coleta de 26/08 no banco de trabalho, a suíte acusou 5 falhas. Não
foram do código novo: foram **do dado deixar de ser o de 18/08**.

**O defeito real: o catálogo media a UNIÃO das linhas; a dedup mede a VENCEDORA.**
`cobertura_agregada` usava `MAX(CASE ...) GROUP BY id_sei, instancia` — "conta
como preenchido se QUALQUER linha tem o campo". Mas um processo aberto em duas
unidades tem uma linha por mesa, e os campos de custódia são POR MESA:
`carregar()` mantém a do snapshot mais fresco e descarta as outras. Enquanto os 4
processos compartilhados de 18/08 tinham os campos idênticos nos dois snapshots o
erro era invisível — exatamente o que o comentário de `carregar()` avisava. Em
26/08 duas mesas divergiram e ele apareceu: `marco_unidade` 98,82% contra 98,90%,
`unidade_envio` 353 contra 354. Um processo, silencioso, na tela que existe para
dizer se o dado dá para confiar. Agora o SQL devolve um booleano POR LINHA na
mesma ordem de `carregar()` e a dedup fica com quem já a define — 20 de 20 campos
em paridade, e os 11,8 ms não mudaram.

**As outras três eram verificações cravando o número da base de hoje.**
`poco_processo == 0` (o poço agora tem 1.041 blocos) e o contador de retidos
fixado em `== 0` / `== 1` (a coleta de 26/08 reteve a DGESS por queda de 20 para
13 processos, e o snapshot retido é COMPARTILHADO — conta para qualquer pessoa
com vínculo na unidade, que é o certo). As três passaram a medir DELTA. A ironia:
a linha imediatamente acima de `nem no poço` já explicava, em quatro linhas de
comentário, por que cravar o número da base está errado.

**Regra que sai daqui: teste que afirma um total absoluto da base de produção
não testa o código, testa a manhã de ontem.**

## 5-decies. A caça adversarial — nove defeitos, dois deles meus

Perguntado se ainda havia falha, a resposta honesta era: **a suíte passar não é a
mesma coisa que não haver defeito**. Seis frentes independentes varreram o
sistema, cada achado foi atacado por dois céticos (um tentando REPRODUZIR, outro
atacando o IMPACTO), e um crítico de completude perguntou o que ninguém tinha
olhado. Dos **14 achados distintos, 7 sobreviveram** aos dois céticos; o crítico
somou 2. Todos os 9 eram reais.

### Os dois que bloqueavam o dono naquele minuto

**Promover snapshot retido expirava a coleta de TODOS os donos da unidade.** O
`UPDATE snapshot SET estado='expirado' WHERE unidade=? AND estado='corrente'`
não filtrava `dono_usuario_id` nem `instancia` — enquanto todo o resto do sistema
(`snapshots_de`, `estado_coleta`, a ingestão) trata `(unidade, dono, instalação)`
como a chave. Dois estragos, os dois silenciosos: a coleta própria de quem já
rodava a sua virava `expirado` por causa de uma decisão sobre o snapshot
compartilhado; e no caminho inverso a unidade **sumia do painel** de quem não tem
coleta própria, porque `snapshots_de` deixava de achar corrente para ela. Sem
alerta — o semáforo de "dado velho" fica mudo justamente quando a unidade
desaparece.

**A tela `/alertas` oferecia ao gestor uma decisão que a rota recusava.**
`/alertas` é `@exige_papel('gestor','admin')` e a docstring dela diz por quê:
"quem sabe se a queda de 40 para 4 processos é real é quem trabalha nela". Os
botões Promover/Rejeitar postavam em `/admin/snapshot`, que era `@exige_admin`.
O gestor via exatamente a coleta que a ingestão de 26/08 reteve, clicava, levava
**403**, e o painel dele seguia preso no retrato de 18/08 sem saída nenhuma.
A rota passou a aceitar gestor **com a fronteira conferida no servidor** — só
decide sobre unidade que alcança.

### Os dois que eu mesmo tinha acabado de introduzir

**O catálogo dava 0% para o campo que vem do snapshot.**
`_campos_do_catalogo()` tira `snap_unidade` do SQL porque ele não mora em
`processo` — mas o catálogo pergunta por ele, e o `cobertura.get(c, 0.0)` da tela
transformava a ausência em **0%**. O relatório "Comparativo entre unidades"
nascia permanentemente inviável, com tarja vermelha e `href="#"`, a um clique de
distância da tela que mostra o MESMO campo com 100% e monta sem reclamar. É
exatamente a divergência entre duas telas do mesmo sistema que o cabeçalho do
módulo diz existir para impedir. Agora existe `DO_SNAPSHOT`, e o teste percorre
**todo campo declarado pelo CATÁLOGO**, não os que o SQL já mede — a lacuna é que
virava número.

**`immutable` de um ano em `vendor/fontes.css`, que é nosso.** Os `.woff2` e os
`.min.js` carregam a versão no conteúdo e nunca mudam sem trocar de nome. O
`fontes.css` declara os `@font-face`: mexer num `unicode-range` é edição normal
do projeto, e com caminho sem versão a correção ficaria invisível por um ano —
nem o F5 traria, porque `immutable` dispensa até a revalidação manual.

### E cinco que ninguém tinha olhado

| defeito | efeito |
|---|---|
| `send_file` escreve `Cache-Control: no-cache` sozinho, e o `setdefault` do `after_request` virava no-op | a planilha `.xlsx` — a resposta com **mais dado nominal** do sistema — saía sem `no-store, private`, e sem ETag para sequer revalidar |
| `com_resumo` contava `SELECT COUNT(*) FROM resumo` | 113 resumos órfãos da rotatividade entre coletas: "1.054 com resumo · 256 sem" somava 1.310 sobre uma base de 1.197, e é esse número que decide se vale gerar mais |
| parear a estação não limpava `pausado_motivo` | caminho PADRÃO de quem entra: a pausa manda instalar o agente, a pessoa instala, e a pausa continua — agendamento inativo, coleta das 07h30 que nunca roda, e **nenhum alerta**, porque janela de agente pausado não conta como perdida |
| "Salvar vínculo" reinseria sem `origem`/`instancia`/`principal` | todo vínculo descoberto no SEI (`'sei'`) virava `'admin'` — e a reconciliação do "Testar acesso", que só desfaz o que ELA criou, **perdia para sempre** a capacidade de tirar acesso que o SEI tirou. Bastava clicar em Salvar sem mudar nada |
| o teste de sessão revogada jogava fora o dado do alvo | afirmava `st_alvo == 200 and dados_outro is not None`: o primeiro é 200 tanto para o painel quanto para o login, o segundo fala de OUTRA pessoa. Trocar o UPDATE por `pass` passava — o admin expulsava alguém e a pessoa seguia com a carteira aberta |

### O que a caça ensina sobre as duas perguntas

**"Não há mais falha?" e "a suíte passa" são perguntas diferentes.** A suíte
estava em 941 verificações, 0 falha, com nove defeitos vivos — sete deles
alcançáveis por um clique numa tela.

**Os dois céticos discordaram em três dos sete, e a discordância foi útil.** No
`.xlsx`, o cético da reprodução confirmou o fato e o do impacto o desmontou
("é anexo, não tela; sem validador o `no-cache` degenera em refetch; não há cache
compartilhado no caminho"). Ambos estavam certos, e a resposta certa foi consertar
assim mesmo — uma linha, e a documentação parava de afirmar o que não valia.

Todos os **nove consertos viraram teste, e os nove testes foram atacados**: com o
defeito solto de volta, **9 de 9 falharam**. Suíte: **966 verificações, 0 falha**.

## 5-undecies. De 2 pessoas para dezenas — o caminho crítico executado

O levantamento de 26/08/2026 (seis frentes, 47 achados) mudou a pergunta: **o
isolamento de leitura já estava pronto e provado** (`snapshots_de`, 983
verificações). O que faltava não era a fronteira — era **dado dentro dela** e
**gente com acesso**.

| medido antes | |
|---|---|
| contas | 60 — 3 ativas, 57 inativas |
| **sem senha nenhuma** (`senha_hash NULL`) | **57 — contas inacessíveis** |
| com vínculo de unidade | **2** |
| credenciais no cofre | **0** |
| `modo_coleta` da única conta configurada | **`estacao`** |

### O destravador custava quinze linhas

`semear.py` faz `SELECT ... FROM processo p JOIN snapshot s`. A unidade em que a
pessoa está atribuída chega na **mesma linha** — e era descartada: só `login` e
`nome` eram lidos. Pior, um `continue` pulava quem já existia, então as 57 contas
já semeadas nunca ganhariam vínculo.

Criar a conta sem o vínculo não adianta nada: `snapshots_de` recorta a carteira
por vínculo, então a pessoa entra e vê uma tela vazia. O único outro caminho para
dar escopo é **cada uma digitar a senha do SEI**, e isso não escala para dezenas.

Medido depois: **2 → 62 pessoas com escopo**, 62 vínculos `origem='snapshot'`,
idempotente (segunda execução: 0 novos). `ativo` e `senha_hash` **intocados** —
dar escopo não é dar acesso.

### O lote gerava a senha e a jogava fora

A ação "Ativar" sorteava `secrets.token_urlsafe(9)`, gravava o hash e **descartava
o valor**. A conta ficava ATIVA E INACESSÍVEL. O aviso mandava "abra cada uma para
copiar" — e mentia: a ficha individual não mostra senha nenhuma. Com 57 contas
eram **114 telas e nenhuma senha na mão**.

Agora o lote devolve as provisórias numa tabela, uma vez, na própria resposta de
quem clicou, com "copiar tudo". Nada vai para a URL nem para o log. Medido: 57
senhas devolvidas (era 0), todas entram, todas caem no primeiro acesso
obrigatório, nenhuma aparece no log, na URL ou na ficha.

### A prova do objetivo

Numa cópia, um clique ativou 61 contas e devolveu 61 senhas. Das oito conferidas:
**8/8 entraram, 8/8 com carteira isolada** — nada do que uma vê está fora das
unidades dela. **Nove carteiras distintas** entre as 61 pessoas, de 1 a 654
processos.

### O modo estação saiu do caminho do leigo

Decisão do dono, textual: *"não é exequível para um usuário leigo, precisa ser
extremamente fácil"*. O assistente apresentava duas opções em pé de igualdade, e
a segunda pedia instalar um agente e rodar `python sei360_agente.py` no terminal.

O modo **não foi removido** — recusar entregar a senha ao servidor é escolha
legítima sobre a senha da própria pessoa. Ele virou uma revelação com o custo
dito: *"exige instalar um programa, rodar dois comandos no terminal, e
normalmente ajuda de quem cuida da TI. Se você não faz ideia de como fazer isso,
a primeira opção é a certa para você."*

E a recusa da busca passou a falar a língua de quem lê: **57 das 60 contas têm
papel `servidor`**, e o texto que mandava editar o Dockerfile era, na prática, o
texto errado para quase todo mundo. Agora só admin e gestor recebem o detalhe
técnico; o resto lê que é um ajuste do servidor e que o painel segue funcionando.

### Dois degraus destravados por medição

`modo_coleta` da única conta configurada estava em `estacao` — no VPS isso é
"nenhuma estação vinculada a você", e a pessoa fica esperando uma máquina que o
desenho não pede mais. Corrigido, apareceu o degrau seguinte: **o cofre estava
desligado por falta de `SEI360_CHAVE_MESTRA`**, e é por isso que `credencial`
tinha 0 linhas — ninguém *conseguia* guardar a senha do SEI.

### O que sobrou, e é do dono

A senha em texto puro no `automacao_sei.js` continua bloqueando a busca no
servidor — e o sistema está certo em recusar. Ordem obrigatória: rotacionar →
semear no perfil (`SEIAuto.credencial`) → esvaziar o CONFIG. Invertendo, a coleta
das 07h30 falha calada.

**Suíte: 983 verificações, 0 falha.** Os mutantes soltos contra os testes novos —
semeadura sem vínculo, lote sem senha — foram todos pegos.

**E dois testes caíram por serem frágeis, não por defeito:** cravavam o estado
esparso da base ("o gestor vê MENOS contas que o admin" — com a lista paginada em
25 e a base cheia, os dois empatam sem nada ter vazado). Passaram a afirmar a
propriedade NOMINAL: existe uma conta fora das unidades do gestor que ele não
alcança e o admin alcança. É a quarta vez nesta sessão que a mesma classe de
teste quebra — **verificação que afirma um total da base não testa o código,
testa a manhã de ontem.**

## 5-duodecies. Resend — recuperação de senha e segundo fator

O pedido foi "integração com o Resend, porque vamos colocar esqueci a senha e
código multifator". O que decidiu o desenho não foi o Resend: foi que **um
segundo fator por e-mail é a única peça deste sistema capaz de fechar o acesso
para todo mundo ao mesmo tempo**, e que recuperação de senha é, por definição,
uma porta de entrada que dispensa a senha.

### O fato que veio antes do código

Das 64 contas, **as 3 ativas — incluindo admin e gestor — têm e-mail em
`@sei360.local`, domínio que não existe**. As 61 com endereço real
(`@saude.ba.gov.br`) estão inativas. Ligar o segundo fator hoje trancaria 100%
de quem usa o sistema, de forma permanente: o código sairia para um endereço que
nunca chega, sem erro visível.

Isso virou regra no código, não recado na tela: `email_saida.entregavel()` recusa
`.local`, `.localhost`, `.invalid`, `.test` e `.example` (RFC 6762 e RFC 2606), e
`acesso.salvar_politica()` **recusa armar** enquanto houver conta ativa do papel
escolhido com endereço assim — nomeando as contas.

### As três medições que mudaram a implementação

**O Cloudflare do Resend bane o User-Agent padrão do `urllib`.** Medido contra a
API real em 27/08/2026: `Python-urllib/3.12` devolve `403` com corpo `text/plain`
"error code: 1010" e a requisição **nunca chega no Resend**. Qualquer outra
string passa. Sem `User-Agent` próprio, a integração falharia sempre, com um erro
que não está na tabela de erros do provedor porque não é dele — e um `json.loads`
nesse corpo estoura, mascarando a causa.

**`onboarding@resend.dev` só entrega para o dono da conta.** Para qualquer outro
destinatário é `403 validation_error`. "Testei e chegou" com ele não prova nada
sobre os `@saude.ba.gov.br` — o aceite exige domínio verificado enviando para um
terceiro real.

**Domínio não verificado não degrada: recusa.** `403` síncrono em 100% dos
envios. E o conserto passa por propagação de DNS, que pode levar **até 72 h**.

### O que o código faz para não trancar ninguém

| trava | o que ela impede |
|---|---|
| nasce desligado (`fator2_papeis = '[]'`) | migração que arma o fator no primeiro boot |
| `pronto` exige um **teste que chegou** | "configurado" e "funciona" virarem a mesma coisa |
| `salvar_politica` recusa armar com conta de domínio morto | trancar exatamente quem administra |
| teto **próprio** de 60 envios/dia | descobrir o teto de 100 do provedor pelo `429`, no meio do expediente |
| `emergencia.py` | a saída sem e-mail e sem painel: `estado`, `desligar-fator2`, `desligar-tudo`, `senha <email>` |

### O furo que o meu próprio teste encontrou

`exige_fator2` consultava a saúde do e-mail e desligava o fator quando ela
falhava. Parecia prudente. Mas `guardar_chave` zera o teste de propósito — então
**rotacionar a chave do Resend desligava o segundo fator de todo mundo, em
silêncio**, até alguém lembrar de mandar outro teste. Quem conseguisse derrubar a
entrega ganhava, de brinde, um caminho para pular o segundo fator: o ataque
exato. Agora armado é armado; se o código não puder sair, a entrada **falha** com
o motivo na tela, e quem desliga desliga de propósito.

O mesmo teste achou um segundo defeito meu: `salvar_politica` fazia
`UPDATE config_acesso ... WHERE id=1` sem garantir a linha. Numa instalação nova a
tabela nasce vazia, o UPDATE atinge zero linhas — **e isso não é erro, é
silêncio**. A tela dizia "política salva" e nada tinha sido salvo, que é o pior
desfecho possível para um interruptor de segurança.

### O que ficou de fora, e por quê

**Códigos de recuperação de uso único** (o "quebra-vidro" por conta) não foram
feitos. `emergencia.py` cobre o caso — funciona sem e-mail e sem painel — e esta
instalação tem um administrador com acesso ao servidor. Com mais gente, ou com o
servidor fora do alcance de quem administra, eles passam a valer a pena.

**Envio assíncrono.** Hoje o envio acontece dentro da requisição, com 10 s de
teto. Com `--workers 3 --threads 2` são 6 vagas; se o Resend pendurar, seis
logins simultâneos degradam o painel por até 10 s. O caminho não autenticado
(`/esqueci`) só chega à rede 3 vezes por hora por conta, então a superfície é
pequena — mas uma fila resolveria isso e o vazamento por tempo de uma vez.

**Suíte nova: `teste_acesso.py`, 71 verificações.** O transporte é desviado para
um arquivo por `SEI360_EMAIL_FALSO` — o servidor de teste roda em outro processo,
e um teste que dependesse do Resend estar no ar mediria o Resend. Total:
**1.057 verificações, 0 falha**.

## 5-terdecies. A busca avançada — o CONFIG vencia a identidade

A pergunta era "por que a busca não funciona". A resposta tinha quatro camadas, e
a primeira estava errada na minha boca: **eu disse que a trava bloqueia a busca.
Ela não bloqueia.** O cético reproduziu: com `atendente.capacidade()` falso,
`busca.quem_executa` não recusa — cai para `_estacao_viva()` e, havendo estação
viva, ela executa. Pior, `_segredo_na_imagem()` inspeciona o `automacao_sei.js`
**do servidor** e nunca o da estação: a trava é cega justamente para o executor
que sobra quando ela dispara.

### O defeito: constante de arquivo vencia credencial entregue

```js
function lerCredencial() {
  // 1) o bloco CONFIG do topo, se preenchido   <- VENCIA
  // 2) senao, o localStorage
```

O servidor entrega a credencial de quem pediu a busca em `coletor_sesab.py:254`,
via `SEIAuto.credencial(u, s)` — que grava no **localStorage**, o nível 2. Com o
CONFIG preenchido, **toda busca entrava no SEI com a conta do CONFIG**, qualquer
que fosse quem pediu, e o SEI registrava os acessos com o nome dela.

E era **silencioso**: `grep -rn lnkUsuarioSistema` em `sei360/servidor` devolve
zero ocorrências. O único ponto que lê quem entrou é `coletor_sesab.py:295`,
dentro do `if TESTAR:`, num ramo que sai com `sys.exit(0)` antes do `if BUSCAR:`.
Reproduzido numa cópia: busca pedida com uma conta, sessão logada com outra,
mesma mesa → `receber()` devolveu `('completa', None)`, log `"busca 2 · completa
· 3/3"`, nada divergente em lugar nenhum.

**O §5-septies já registra este mesmo desastre uma vez** — perfil único, "o SEI
gravava tudo com o nome de A". A correção de então foi estrutural (perfil por
pessoa). Nenhuma verificação de runtime foi acrescentada, e **o CONFIG preenchido
derrota a defesa estrutural inteira**: ele vence o localStorage em qualquer perfil.

### O que foi feito (Fase A — fecha a troca de identidade sem tocar no CONFIG)

**C1.** A ordem é `entregue → localStorage → CONFIG`, e o CONFIG **some por
completo** quando alguém entregou credencial: melhor recusar o login do que
entrar com a conta errada. A marca vai por `add_init_script`, não por variável de
módulo — a navegação do submit do login destrói o contexto da página.

**C2.** A armadilha de precedência ficou **dentro da página**, e não no Python.
O plano pedia que o coletor lesse o `.js`; mas `coletor_sesab.py` declara, no
cabeçalho, que *"apenas REFERENCIA o caminho do .js — nunca lê nem imprime seu
conteúdo"*, e é essa invariante que mantém a credencial entre o arquivo e o
navegador. Quem já tem os dois valores na mão é a página: ela avisa pelo console,
o coletor já escuta o console e já acumula alertas.

**C3.** `SEIAuto.esquecer()` rodava só no sucesso; o caminho de falha saía por
`sys.exit(3)` **antes**, deixando a senha em base64 no leveldb do perfil —
justamente quando algo deu errado e ninguém vai olhar.

**Prova:** `painel_sesab/conferir_credencial.js` extrai as funções do `.js` e roda
nove casos em Node, ligado à suíte pelo padrão que `teste_busca.py:227` já usava.
Inclui o caso de que a estação depende: **sem credencial entregue, o CONFIG
continua valendo** — senão a coleta das 07h30 morre. Mutante solto (CONFIG
voltando a ignorar a marca): 2 verificações o pegaram. Suíte: **1081
verificações, 0 falha.**

### O que ainda impede a busca de rodar

Quatro coisas, e só duas são de código:

1. **0 credenciais no cofre.** Sem linha em `credencial` não há o que decifrar.
   Cada pessoa cadastra a dela em `/configuracao`. Não há contorno.
2. **A senha do CONFIG está comprometida** e precisa ser rotacionada antes de o
   bloco ser esvaziado — e a nova precisa ser semeada no perfil primeiro
   (`_perfil_sei` tem 165 arquivos e **zero** ocorrências de `SEI_CRED`).
3. **A busca nunca TROCA de mesa** (`pesquisa_sei.js:268` só *lê*
   `#lnkInfraUnidade`): qualquer mesa que não coincida por acaso com a unidade
   ativa volta `falhou`, acusando estado de sessão quando o que houve foi
   ausência de troca. **Pendente.**
4. **Ninguém carimba `usuario_confirmado`** — a conferência que tornaria a
   substituição de identidade detectável a posteriori. **Pendente.**

Outros dezoito achados sustentados aguardam: nenhum relógio varre a fila (a busca
id 1 viveu 926 s sob um teto de 90 s, e só morreu quando alguém abriu a tela); o
motivo da falha é reconstruído da configuração ATUAL, não da que valia no pedido;
e `/api/agente/busca` entrega pela instalação ativa da config, não pela da busca.

## 6. Isolamento — decisão pendente

O pedido original foi "cada usuário só acessa os dados do seu usuário". Isso tem duas leituras:

- **(A) por unidade** — cada um vê a carteira da unidade, exatamente o que o SEI já mostra
- **(B) por atribuído** — cada um vê só o que está no seu nome

**Recomendação: (A) como fronteira de segurança; (B) como filtro de apresentação.**

Motivo: os processos são da fila da unidade e todos os colegas já os veem no próprio SEI. Esconder no painel o que a fonte mostra é teatro. E (B) como fronteira destrói o produto — a distribuição é desigual (um responsável com 41 processos, mediana abaixo de 10), então o gestor veria quase nada.

> **Isto contraria a leitura literal do pedido e precisa de aceite por escrito antes de qualquer implementação de servidor.**

Nas fases sem servidor, a fronteira real é o **perfil do navegador** — o que só vale em estação corporativa, com disco cifrado e perfil não compartilhado. Não é mais forte do que isso, e não se deve fingir que é.

---

## 7. Dado pessoal

Os dados incluem nome completo, e-mail institucional, anotações em texto livre e especificações que podem conter nome de paciente — contexto de saúde.

- **Sem servidor, o dado não sai da máquina do usuário.** É a configuração de menor passivo e a razão de as fases 1 e 2 não terem backend.
- Um repositório centralizado fora do SEI perde a trilha de auditoria que o SEI tem, e passa a exigir base legal, registro de tratamento e provavelmente RIPD.
- Hospedagem, se houver, em região BR contratada pelo órgão. Nuvem estrangeira com dado de saúde é transferência internacional.

---

## 8. Componentes

| Arquivo | O que é |
|---|---|
| `painel_sesab/automacao_sei.js` | coletor de console: sessão, lista, histórico, mesas, checkpoint, retomada |
| `painel_sesab/painel_sesab.html` | painel autocontido: triagem, gráficos, lista e gaveta de detalhe |
| `painel_sesab/processos_sesab.xlsx` | exportação estruturada |
| `sei360/SEI360.html` | tela de acesso, autocontida, zero dependência externa |

### API do coletor

```javascript
SEIAuto.rodar()               // uma mesa
SEIAuto.rodarTodasAsMesas()   // a conta inteira
SEIAuto.descobrirMesas()      // só lista as unidades
SEIAuto.custo()               // volume de rede por execução
SEIAuto.limparCache()         // zera a coleta, preserva credencial
```

---

## 9. Limites conhecidos

- **Sem validação em campo** de: mesas, unidade/usuário geradores e multi-mesa. O código existe; falta uma sessão logada para provar.
- A descoberta de unidades foi escrita contra **três formatos possíveis** de seletor, sem referência — o SEI Pro não implementa troca de unidade.
- `Acompanhamento Especial` e `Consultar/Alterar` custam duas requisições extras por processo, em telas diferentes. **Já estão no escopo** — é delas que saem o grupo do acompanhamento e a classificação por assunto —, e são a razão de o custo ser 5 e não 3.
- `Observações` (`txaObservacoes`), prioridade e grau de sigilo vieram **vazios em 100%** da amostra. Não valem a requisição e não são lidos.
- O acesso a `.ba.gov.br` é **intermitente** em algumas redes; a coleta é uma rajada curta, mas pode cair no meio. O checkpoint cobre isso.
