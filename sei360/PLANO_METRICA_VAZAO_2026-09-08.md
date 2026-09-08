# Produtividade por responsável no SEI360 — o que dá, o que não dá, e o que precisa ser decidido

**Para:** Diretor Geral do HECC, gestor da unidade
**Data:** 08/09/2026
**Base de todos os números:** última coleta do SEI, de 27/08/2026 07:45 (12 dias atrás), e os arquivos de coleta guardados na estação. Nenhum número aqui é estimativa; onde a origem é frágil, isso está escrito ao lado.

---

## 1. A pergunta por trás do pedido

O pedido foi "quantos processos cada responsável está analisando e dando vazão". Dentro dele há quatro perguntas diferentes, e elas têm respostas muito diferentes:

| A pergunta | Vira que medida | Situação |
|---|---|---|
| Onde o trabalho empaca? | Fila por unidade: quantos processos, há quanto tempo parados, sob que evento | **Respondível hoje** |
| Quem está sobrecarregado? | Estoque por pessoa: quantos processos estão atribuídos a cada um | **Respondível hoje**, com ressalvas |
| O que não anda? | Processos sem dono e processos sem movimento há mais de 90 dias | **Respondível hoje** — é o número mais acionável que temos |
| Quem produz mais? | Vazão nominal: quantos processos cada pessoa despachou por mês | **Não respondível**, e não é por falta de autorização — ver seção 4 |

As três primeiras são diagnóstico de fila. A quarta é avaliação de desempenho, e é a única que exige mudar a regra escrita do sistema (seção 5) — e mesmo com a regra mudada, o dado não a sustenta.

---

## 2. O que dá para responder hoje, sem construir nada

Tudo abaixo sai da carteira de 27/08 (1.177 processos, depois de descontar 5 que estão abertos em duas mesas ao mesmo tempo).

### 2.1 Onde o trabalho está parado

Classificando cada processo por tempo na unidade e tempo desde o último movimento:

- **Em curso** (entrou há até 30 dias): 463
- **Andando** (mais velho, mas movimentado nos últimos 30 dias): 206
- **Lento** (sem movimento entre 30 e 90 dias): 202
- **Parado** (mais de 90 dias na unidade e mais de 90 sem movimento): **294**
- Sem data de entrada legível: 12

Os 294 parados se concentram: **CESS 230 (38% da fila dela), UMA-CMA 51, CESS/IM 10 (de 10)**. COMASUP tem 3; DGESS, ASTEC e GT-HTLV, nenhum.

**O que isso não diz:** "parado" é ninguém ter tocado no processo dentro do SEI. Não distingue processo esquecido de processo aguardando resposta de terceiro — o campo de "retorno" tem 1 registro em 1.165, é inservível. E há um viés conhecido: a data de entrada na unidade é a do **último** recebimento; em 35,7% dos casos o processo foi recebido mais de uma vez pela mesma unidade, então o tempo real de fila é **maior** do que o número mostrado, nunca menor. O número é piso.

### 2.2 Quem está com carga desproporcional

62 pessoas, 978 processos atribuídos. Mediana de 7 processos por pessoa; a maior fila é 136. As 10 maiores concentram 59,3% de tudo que está atribuído.

Por unidade (a única comparação que faz sentido, porque a carga não é comparável entre mesas):

| Unidade | Processos | Pessoas | Mediana | Maior fila |
|---|---|---|---|---|
| CESS | 611 | 20 | 19 | 136 |
| UMA-CMA | 287 | 7 | 4 | 78 |
| COMASUP | 243 | 28 | 6 | 36 |
| DGESS | 20 | 3 | 4 | 11 |
| CESS/IM | 10 | 3 | 3 | 5 |
| ASTEC | 10 | 2 | 2 | 3 |
| GT-HTLV | 1 | 1 | 1 | 1 |

**O que isso não diz:** mede quanto foi **alocado** a cada um, não quanto cada um trabalhou. Da 25ª pessoa para baixo o ranking é ruído — 25 das 62 têm 5 processos ou menos, e uma diferença de 2 processos inverte metade da tabela. Em quatro das sete unidades (DGESS, CESS/IM, ASTEC, GT-HTLV) há 3 pessoas ou menos: ali qualquer número "da unidade" é, na prática, o número de uma pessoa.

### 2.3 O que não anda porque não tem dono

**199 processos (16,9%) não têm responsável atribuído no SEI.** Deles, **186 estão na UMA-CMA** — que tem 287 processos e só 101 atribuídos. Entre os sem dono, 125 estão há mais de 90 dias, mediana de 141 dias.

Essa é a maior linha de qualquer tabela por pessoa — 46% maior que a maior fila individual — e é a única ação de gestão disponível hoje sem construir nada. Também não é abandono: a UMA-CMA aparentemente trabalha por lista, não por atribuição. A decisão é sua: ou aquela unidade passa a atribuir, ou o painel para de contar isso como buraco.

### 2.4 Onde chegar nesses números hoje

Já existem no painel, prontos e exportáveis em planilha:

- **"Carga por responsável"** (menu Relatórios, restrito a gestor/admin) — é o item 2.2. Ele já responde metade do seu pedido.
- **"Panorama de triagem"** (aberto a qualquer usuário) — traz a linha "Sem responsável atribuído", item 2.3.
- **"Permanência"** e **"Última coisa que aconteceu"** — sustentam o item 2.1.
- **"Minha fila"** — dá a cada pessoa a fila dela. Hoje ninguém a usa: das 64 contas do sistema, 61 estão inativas e nenhum servidor jamais entrou no painel.

**Ressalva que vale para os quatro:** todos descrevem 27/08. Hoje é 08/09.

### 2.5 Um número que estava errado e vale corrigir antes que circule

Existia a leitura de que a unidade externa COPRO-DA seria a origem de 137 dos 294 processos parados. Isso usava o campo "quem gerou o processo". Extraindo **quem de fato remeteu** (disponível no histórico, com 95% de cobertura entre os parados), o quadro é outro: **DGESS 78, COPAT 27, CGI 24 — e COPRO-DA 11**. Não leve o primeiro número a reunião nenhuma.

---

## 3. O que exige construir, em fases

### Fase 0 — Religar a coleta e ingerir o atraso (operação, não engenharia)
**Entrega:** o painel volta a descrever hoje.
**O que muda:** habilitar a tarefa `SEI_SESAB_Coleta` na estação; ingerir os 11 arquivos parados em `painel_sesab\_coletas`.
**Esforço:** meio dia. **Tem prazo:** o arquivo de 12/08 é descartado por volta de 11/09 e o retrato de 18/08 morre por volta de 17/09.
**Pronto quando:** `SELECT COUNT(DISTINCT substr(coletado_em,1,10)) FROM snapshot` retorna 14 ou mais **e** `SELECT MAX(coletado_em) FROM snapshot` é do dia anterior. Hoje retorna 3 e 27/08.

### Fase 1 — Tela "Saúde do dado", com trava
**Entrega:** uma tela só dizendo, em número e não em cor: idade da coleta por unidade, cobertura de cada campo, quantos processos têm histórico truncado. E uma regra dura: **relatório com coleta de mais de 3 dias não abre** — mostra o motivo.
**O que muda:** relatório novo em `servidor/relatorios.py` (catálogo) + tarja em `templates/relatorio.html`.
**Esforço:** 1,5 dia.
**Pronto quando:** com a coleta parada como está hoje, abrir "Carga por responsável" devolve o aviso e não a tabela; e o teste `teste_relatorios.py::test_bloqueia_coleta_velha` passa.

### Fase 2 — Diagnóstico de fila por unidade
**Entrega:** os cinco estados do item 2.1 por unidade; sem dono por unidade e faixa; envelhecimento por tipo de processo; classe do último evento com idade mediana. Nenhum nome de pessoa em nenhuma tela.
**O que muda:** cinco relatórios em `servidor/relatorios.py`; regra de piso — unidade com menos de 30 processos **não entra em ordenação comparativa** (senão CESS/IM, com 10 processos e 100% parados, lidera todo ranking de gargalo).
**Esforço:** 3 dias.
**Pronto quando:** a soma dos cinco estados é igual ao total da carteira em toda unidade (teste automatizado), e o total da tela bate com o total do painel com a mesma dedup.

### Fase 3 — Guardar o histórico de custódia (a peça que falta)
**Entrega:** três coisas que hoje não existem: (a) **há quanto tempo o processo está de fato na unidade** — a primeira entrada, não a última; (b) **quem realmente remeteu** cada processo para nós; (c) entradas e saídas por unidade, por dia.
**O que muda:** tabela nova `processo_movimento` em `servidor/banco.py`; gravação em `servidor/ingestao.py` (o dado já chega ao servidor todo dia e é descartado ali — **zero requisição a mais ao SEI, zero segundo a mais de robô**); prazo de descarte próprio em `servidor/expurgo.py`.
**Restrições obrigatórias:** só se grava ato ocorrido em uma das nossas mesas (sem isso, a tabela vira cadastro de 1.107 servidores de toda a SESAB para servir 122); e o prazo de descarte tem de ser escrito junto com a tabela, senão o sistema ganha por esquecimento seu primeiro acervo permanente de dado pessoal.
**Esforço:** 2 dias. **Custo de disco:** cerca de 2 MB de carga inicial (o banco inteiro tem 7,4 MB hoje).
**Pronto quando:** para os processos da carteira, o número de "passagens abertas" calculado pela tabela nova bate com a carteira real com divergência abaixo de 2%. Sem isso, nenhum número de fluxo é publicado.

### Fase 4 — Segunda passada nos processos que saíram (opcional, mas é o que separa "resolver" de "repassar")
**Entrega:** hoje, quando um processo sai da nossa mesa, o painel não sabe se ele foi concluído ou empurrado adiante. Medido: dos 62 processos que saíram entre 26 e 27/08, **62 saíram sem deixar registro do motivo**. A correção é reler, no dia seguinte, o andamento dos processos que sumiram.
**O que muda:** um passo no coletor (`painel_sesab/automacao_sei.js`). Custo: cerca de 33 leituras a mais por dia, sobre uma base de 5.897 — **0,6%**.
**Esforço:** 2 dias.
**Pronto quando:** na comparação de dois dias, o motivo de saída é conhecido para 90% ou mais dos processos que sumiram. Hoje é 0%.

### Fase 5 — "Meu trabalho" (espelho pessoal), condicionada
Só existe se (a) as contas dos servidores forem ativadas e comunicadas e (b) houver 14 dias seguidos de coleta. Cada pessoa vê a própria fila e os próprios atos; o gestor vê a distribuição da equipe sem nomes. **Não vira tabela comparativa.**
**Esforço:** 2 dias de código + o tempo de ativar e avisar 61 pessoas, que não é engenharia.
**Pronto quando:** um teste garante que nenhuma tela de gestor devolve nome ou e-mail de servidor.

---

## 4. O que não será medido, e por quê

**Não será medido: "quantos processos cada pessoa despachou".** Não por escrúpulo. Por quatro defeitos do dado, cada um deles suficiente sozinho:

1. **O ato de dar vazão é o que menos aparece.** Quando alguém conclui ou remete um processo, ele sai da nossa mesa — e o robô, que lê a mesa uma vez por dia, nunca vê esse último ato. Medido: 62 de 62 saídas de um dia sem registro; numa janela de 5 dias, 165 processos saíram contra 127 atos de saída visíveis. **A métrica erraria justamente contra quem termina o trabalho.**

2. **O número não é reprodutível, e a erosão tem direção.** Medindo o **mesmo mês já fechado** a partir de coletas de dias diferentes: 1.826 atos vistos em 22/08, 1.428 vistos em 27/08 — 26% a menos em cinco dias. Por tipo de ato, o que some mais rápido é exatamente "conclusão" (sobrevive 67%). Um ranking de agosto recalculado em outubro dá outro resultado. Indicador que muda sozinho não é indicador.

3. **O topo do ranking seria o balcão de roteamento.** Na medição de 30 dias, a pessoa com mais "atos de saída" tem 114, um quarto de todos — e 111 dessas 112 remessas foram para outra mesa **da própria diretoria**. O processo não saiu; mudou de sala. O segundo colocado tem 38.

4. **Base pequena demais.** Em 30 dias houve **53 conclusões, por 17 pessoas, mediana de 1 a 2 por pessoa**. Nessa escala, "zero" quase sempre significa "não houve amostra", não "não houve trabalho". E mais da metade dos atos registrados é "recebido na unidade" — abrir a correspondência.

**A assimetria que precisa ficar clara: destinatário não é autor.** O campo que o painel tem hoje diz **quem recebeu** o processo ("Processo atribuído para fulano"), não quem praticou o ato. Em 96,6% dos casos ele só repete o nome que já está no campo de responsável. O nome de quem **agiu** existe no histórico do SEI e é lido pelo robô todo dia — mas hoje é descartado (é o que a Fase 3 conserta). Mesmo com ele: **apenas 12,6% dos atos de saída foram praticados pelo responsável atual do processo**. Ou seja, "carga por responsável" e "vazão por autor" são tabelas sobre pessoas diferentes com a mesma aparência. Publicadas lado a lado, produzem o ranking errado.

**Numa contestação, o que aconteceria.** O servidor diz "esses 136 não são meu trabalho". Para provar o contrário, o órgão precisaria exibir os atos — e tem um único evento por processo, o último, que em 96,6% dos casos só repete o campo de atribuição. O histórico completo não está guardado. O retrato que gerou o número é apagado em 30 dias. O registro de quem gerou e exportou o número mora no mesmo banco, apagável por uma linha de comando sem deixar vestígio. **O órgão não prova o número e o servidor não o derruba** — o dado não está errado; a conclusão tirada dele é que está. É o pior insumo possível para um ato que afeta carreira.

**Também não será medido:** esforço de análise. Redigir despacho, assinar, anexar documento — nada disso sobrevive ao filtro que o robô aplica. O que restaria mediria tramitação e premiaria quem despacha rápido.

---

## 5. A decisão que é sua

A regra escrita do sistema (`ARQUITETURA_ACESSO.md`, seção de base legal) diz: *"Finalidade amarrada: triagem da carteira processual. Fica proibido reuso para avaliação de desempenho de servidor."* Isso não é política acessória — é a amarra da hipótese legal que autoriza o painel a existir. Três caminhos:

**Opção A — Manter a finalidade e medir fila (unidade, não pessoa).**
Custo: nenhum ato formal. Entrega as seções 2 e 3 (fases 0 a 4). Preço político: o painel vai dizer "a CESS tem 230 processos parados" e "a UMA-CMA tem 186 sem dono" — quem responde por isso é a chefia da unidade, não o técnico. Isso pesa mais numa reunião, não menos. É preciso querer.

**Opção B — Ampliar a finalidade e medir pessoa.**
Custo: nove atos formais, nenhum deles de engenharia — designação formal de controladora e encarregado (hoje sete termos do próprio projeto estão "a nomear" e "a datar"); ato do órgão declarando "acompanhamento de produtividade" como finalidade autônoma; citação, por nome e número, da norma de avaliação de desempenho da SESAB que sustentaria a base legal; registro de tratamento atualizado; relatório de impacto refeito; ciência prévia individual a **122 pessoas** (os autores de atos, não os 62 responsáveis — são conjuntos diferentes); e um destinatário formal para o número, com rito de contraditório. Prazo realista: meses. **E, ao fim disso, os quatro defeitos da seção 4 continuam de pé.** Autorizar não conserta dado.

**Opção C — Via intermediária: espelho + curva.**
Cada pessoa vê o próprio número; o gestor vê a forma da distribuição da equipe (mediana, faixas, maior fila) sem nomes; e o sistema nomeia alguém apenas nos casos em que o nome é a própria ação de gestão. Custo: exige ativar e comunicar 61 contas, e exige uma decisão sua sobre o relatório "Carga por responsável" que já existe — enquanto ele estiver na tela, exportável em planilha, ordenando 62 pessoas por volume, prometer "sem ranking" é conversa.

**Recomendo a Opção A agora, com a porta aberta para a C depois da Fase 5.** Motivo, em uma frase: a Opção B custa meses de trâmite para entregar um número que não se prova, e as três perguntas que de fato lhe interessam — onde empaca, quem está sobrecarregado, o que não anda — são respondidas pela A já na primeira semana. Se depois de 14 dias de série contínua os números de fluxo por unidade se mostrarem estáveis, a C acrescenta o espelho pessoal sem criar ranking e sem mudar a finalidade registrada.

**O que a Opção A não responde, e é bom ficar registrado por escrito:** quantos processos cada pessoa despachou; se o processo saiu por conclusão ou por repasse (até a Fase 4); e quanto esforço cada processo deu.

---

## 6. Pré-requisito que atravessa tudo: a série

**A coleta está desligada desde 27/08. Há 12 dias o sistema não vê o SEI.**

No banco existem **três dias de retrato, e não consecutivos** (18, 26 e 27/08). Há **11 arquivos de coleta na estação que nunca foram carregados**. O sistema apaga retrato com mais de 30 dias: o de 18/08 morre por volta de 17/09, e o arquivo mais antigo do atraso, por volta de 11/09.

Consequências práticas, sem rodeio:

- **Tudo o que está na seção 2 descreve 27/08.** Se for para reunião esta semana, tem de ir com a data na cara.
- **Nenhuma medida de fluxo — entrou, saiu, andou — pode ser construída antes de 14 dias seguidos de coleta.** É regra escrita do próprio projeto, e ela existe porque uma coleta incompleta já produziu, num teste, "entraram 1.125 processos num dia", que era falha do robô lida como movimento de processo.
- **Cada dia parado destrói dado de forma irreversível.** Quando um processo sai da carteira, o histórico dele deixa de ser lido — e não volta.
- **O passado quase não é recuperável.** Os arquivos de 12 a 20/08 não trazem o nome de quem praticou os atos (o robô só passou a gravar isso a partir de 22/08). Descontando fim de semana, o histórico com autor que existe hoje é de **três dias úteis**.

**A primeira coisa a mandar fazer, antes de aprovar qualquer tela: religar a tarefa de coleta e carregar os 11 arquivos.** Sem isso, o resto deste plano é planejamento sobre uma fotografia que envelhece.# ERRATA — nota técnica ao gestor (SEI360)

**Causa raiz única e transversal:** os números foram apurados sobre as **12 unidades com snapshot corrente**, não sobre as **6 unidades da carteira do gestor**. Reproduzi o erro de ponta a ponta em três blocos: rodar a consulta sem a fronteira devolve os números publicados byte a byte. O vazamento é uma unidade só — `SESAB/SAIS/DGGUP/DGESS/CESS/IM`, 10 processos, todos parados há 1.019–1.832 dias.

**Segundo aviso global:** toda medida em dias está congelada na régua da coleta — **27/08/2026 07:45**, 12 dias atrás. A nota não datou a medição; relida em um mês, envelhece sozinha. Publicar a data e os operadores (`>` vs `>=`), sem os quais nenhum número é reproduzível por terceiro.

---

## 1. O que caiu

| # | Publicado | Certo | Por quê |
|---|---|---|---|
| 1 | 1.177 processos | **1.167** distintos (1.172 linhas; 5 abertos em duas mesas do gestor) | fronteira ausente; os 10 excedentes são todos da CESS/IM |
| 2 | Parados 294 | **284** | todo o vazamento caiu neste balde — o erro não se diluiu, concentrou-se no indicador mais grave |
| 3 | CESS/IM: 10 de 10 parados / 10 proc. / 3 pessoas | **linha sai inteira** | unidade fora da carteira; era a estatística retoricamente mais forte da nota e é sobre processos que o gestor não pode abrir |
| 4 | 1.826 atos em 22/08 → 1.428 em 27/08 = **−26%** ("erosão") | **2.528 → 2.389 = −5,5% bruto; −1,2% com o conjunto de processos fixo** | não reproduzi 1.826 nem 1.428 em ~1.500 combinações. A queda bruta é **composição** (103 processos saíram levando 595 atos, 119 entraram trazendo 479), não erosão. A própria aritmética da nota não fecha: 1.428/1.826 = −21,8%, não −26% |
| 5 | "o histórico visível encolhe entre coletas" | **cresce**: 15.004 → 15.134 atos (+0,9%) nos mesmos 1.048 processos | 985 iguais, 54 cresceram, 9 encolheram |
| 6 | Por tipo de ato, "conclusão" sobrevive 67% | **101%** (113 → 114). Nenhuma classe abaixo de 94% em mês fechado | 67% não sai de nenhuma combinação testada |
| 7 | 35,7% recebidos mais de uma vez pela mesma unidade | **30,5%** (361 de 1.182 pares) | **não é vazamento de fronteira** (sem fronteira dá 30,7%): é erro da própria conta. ~20 definições alternativas testadas, nenhuma cai na faixa 35,3–36,1% |
| 8 | 137 de **294** parados gerados na COPRO-DA | **137 de 285** (48,1%, não 46,6%) | o 137 sobrevive; o denominador é o número sem fronteira, com 1 de erro |
| 9 | Remetentes dos parados: DGESS 78, COPAT 27, CGI 24, COPRO-DA 11 | **DGESS 83, CGI 31, COPAT 29, COPRO-DA 11** | método defeituoso: a nota usou "última remessa para qualquer destino", ignorando se foi para a mesa do gestor (erra em 25 dos 285 casos). **A ordem também está trocada** — a CGI é a 2ª, não a 3ª: quem cobrar na ordem publicada cobra a unidade errada primeiro |
| 10 | "ciência prévia a 122 pessoas — contra os 62 responsáveis" | **114 autores contra 61 responsáveis** | o par 122/62 é a assinatura exata do vazamento: o 122º autor e o 62º responsável estão os dois na CESS/IM. O argumento de mérito (universo de titulares ≈ dobro dos responsáveis) sobrevive |
| 11 | "nenhum servidor jamais entrou no painel" | **falso como escrito**: a conta de papel *servidor* (@sei360.local) entrou em 19/08. Verdadeiro só para os 61 servidores **reais** (@saude.ba.gov.br) | |
| 12 | "o arquivo de 12/08 é descartado por volta de 11/09" | **nenhum arquivo de `_coletas` é descartado, nunca** | o prazo de 30 dias vale para *linha de banco* (snapshot), não para arquivo em disco. Não existe rotina de retenção de arquivo |
| 13 | "histórico com autor: três dias úteis" | **4 dias úteis (24–27/08), em 6 coletas. No banco: zero** — nenhum ato com autor está persistido | |
| 14 | 62 pessoas / 978 atribuídos / 59,3% no top-10 / 25 com ≤5 | **61 / 969 (972 por mesa) / 59,4% / 24** | o parágrafo inteiro saiu da mesma consulta sem fronteira. A pessoa que some é a única que só existe na CESS/IM |
| 15 | 199 sem responsável (16,9%) | **198 (17,0%)** — o próprio percentual denuncia o denominador: 198/1.167 = 16,97%; só 199/1.177 dá 16,9% | |
| 16 | 125 sem dono há mais de 90 dias | **124** (régua 27/08; 126 se remedido hoje) | ressalva material: "90 dias" aqui é **dias na unidade**; se lido como "sem movimento", são **36**, não 124 |
| 17 | "165 processos saíram em 5 dias" | **165 é soma de eventos diários**; processos distintos **163**; saídas líquidas **103** | e a comparação "165 contra 127 atos de saída" é inválida (soma de eventos × estoque de um arquivo). Olhando todas as coletas: 172 atos de saída em 119 processos — **mais** atos que saídas líquidas, o inverso do publicado |
| 18 | 12,6% dos atos de saída pelo responsável atual | **12,5%** (55 de 441) | anacrônico por construção (ato histórico × responsável atual); a pessoa A sozinha aporta 114 atos que nunca casam — sem ela, 16,8% |
| 19 | 96,6% "atribuído para" repete o responsável | **97,1% por processo — e 100,0% (365/365) dentro da unidade** | **retirar a frase, não corrigir o número**: é tautológico, mede o modelo de dados do SEI, não comportamento |
| 20 | "mediana de 1 a 2 conclusões por pessoa" | **mediana = 1** (10 das 17 fizeram exatamente 1; seis pessoas respondem por 41 das 53) | a faixa suaviza uma distribuição muito mais desigual |
| 21 | Tabela nova ≈ 2 MB de carga inicial | **0,80 MiB sem índice / 1,29 MiB com índices; teto real ~1,6 MiB** | e é número **modelado**, contra a abertura da nota ("nenhum número aqui é estimativa") |
| 22 | "33 leituras a mais por dia sobre 5.897 = 0,6%" | **~62 processos/dia no último par (média 36); 2,1%–5,3%** | mistura unidades (5.897 são *requisições*, 33 são *processos*) e se contradiz com o "62 saídas" do mesmo parágrafo. O 5.897 também é modelado |
| 23 | Ressalva "o total de pessoas não é a soma da coluna" | **retirar**: dentro da fronteira a soma **é** o total (20+7+28+3+2+1 = 61) | a advertência só era verdadeira por causa do próprio vazamento; mantê-la faria o leitor desconfiar de uma soma correta |
| 24 | "1.107 servidores de toda a SESAB" | **≥1.109 na coleta de 27/08; 1.391 na união 22–27/08** | o risco de virar cadastro de pessoal da SESAB inteira é maior do que a nota diz |
| 25 | "para servir 122" (fase 3) | **não reproduzível por nenhum recorte** (61 / 62 / 64 / 66 / 224 / 353) | remover |

---

## 2. O que ficou de pé

- **Em curso 463, Andando 206, Lento 202, Sem data 12** — idênticos com e sem fronteira (os 10 vazados eram todos extremos e caíram só no balde Parado).
- **Concentração dos parados: CESS 230 (37,6% da fila dela), UMA-CMA 51 (18%), COMASUP 3 (1%), DGESS/ASTEC/GT-HTLV zero.** Soma 284 — fecha. A atribuição é robusta (dá 230 nas duas leituras de dedup). Muda só o denominador da frase: 230 são **81% dos 284**, não 78% de 294.
- **Régua**: os agentes acertaram — a medida é a data da coleta, não o relógio. Esta suspeita não se confirmou.
- **Mediana de 7 processos por pessoa** e **maior fila 136** (com ressalva: a tela mostra 135 por desempate de dedup — declarar qual das duas está publicando).
- **Tabela por unidade do BLOCO 2** (CESS 611/20/19/136; UMA-CMA 287/7/4/78; COMASUP 243/28/6/36; DGESS 20/3/4/11; ASTEC 10/2/2/3; GT-HTLV 1/1/1/1) — todas as células batem.
- **186 dos sem-dono estão na UMA-CMA; a unidade tem 287 processos e só 101 atribuídos; mediana de 141 dias entre os sem dono.**
- **BLOCO 6 quase inteiro**: 114 atos de saída da pessoa A (um quarto dos 441 praticados pelas 6 unidades), 111 das 112 remessas para outra mesa da própria diretoria, 2º colocado com 38, 53 conclusões por 17 pessoas.
- **BLOCO 7 de sistema**: 64 contas / 61 inativas; banco de 7,4 MB; 11 arquivos nunca ingeridos; autor gravado só a partir de 22/08; retrato de 18/08 morre por volta de 17/09.

**Argumentos inteiros que sobrevivem (é o que sustenta a recomendação):**

1. **Recebimento repetido esconde tempo de fila** — confirmado e **subestimado**. `marco_unidade` é a *última* entrada, então a tela mede só a estada atual: mediana de **40 dias mostrados contra 138 acumulados**; o acumulado supera o mostrado em **93,5%** dos casos. A tese vai à reunião — com 30,5% e com esta medição, não com 35,7%.
2. **Gerador ≠ remetente** — confirmado. A COPRO-DA gera 137 parados e remeteu só **11** deles para a mesa do gestor (único número do bloco que sobrevive a todas as variantes). O diagnóstico está certo; o que cai é a tabela que o acompanha.
3. **O universo de quem age é o dobro do universo de responsáveis** — 114 contra 61.

**Argumento que NÃO sobrevive: a erosão do histórico.** Não há decaimento distribuído. Se a recusa da vazão nominal se apoiava nela, precisa de outro fundamento (há três, na seção 4).

---

## 3. O que não é verificável — e o que fazer

| Item | Situação | Decisão |
|---|---|---|
| **"62 de 62 saídas sem registro do motivo"** | Tautológico: a coleta é escopada por mesa, então o ato que causa a saída acontece sempre **depois** do último snapshot daquele processo e nunca poderia aparecer. Dá 0 de 163 em qualquer dia. | **Sair.** Mede o desenho do coletor, não ausência de registro no SEI |
| **"96,6% o atribuído-para repete o responsável"** | 100% dentro da unidade, 0% fora — é o modelo de dados do SEI | **Sair** |
| **Todo o BLOCO 5 (atos/erosão) e o BLOCO 6 (autores)** | O banco **não guarda histórico de movimentos** (só `movimentos` e `ultimo_movimento`; `poco_processo.mov_custodia` tem 0 linhas). Só existem nos JSON de coleta, que não são o que o gestor vê | **"Medido uma vez, não reproduzível pelo painel"**, com a janela e a data declaradas |
| **Janela declarada 12/08–27/08** | Só **6 dos 15 arquivos** têm `mov_custodia` (22–27/08). Os 9 de 12/08 a 20/08 têm zero movimento | **Corrigir a janela para 22–27/08.** E ela é sábado a quinta: ~4 dias úteis, com um fim de semana inteiro dentro. Não extrapolar taxa diária |
| **5.897 requisições e 2 MB da tabela** | Modelados a partir de comentários de código, não medidos | **Ficar com ressalva explícita**, ou corrigir a abertura ("nenhum número aqui é estimativa") |
| **24 dos 284 parados com `mov_parcial=1`** | `ultimo_movimento` é o último movimento **lido**, não o real — até 8% do balde mais grave pode ser falso-parado | **Ficar com margem declarada** |
| **`truncado_restante` = 4 nos snapshots da fronteira** | A carteira pode estar até 4 linhas incompleta na origem | Nota de rodapé |

---

## 4. Achados novos (a nota não mencionava)

**Muda a reunião:**

- **O passivo real é cerca do dobro do publicado.** `_dias_parado` usa o último movimento do processo em **qualquer** unidade. Medindo estagnação **dentro da mesa do gestor**, são **536** processos sem nenhum ato há mais de 90 dias, contra 285 pela regra do painel — os 285 são subconjunto estrito (zero falso positivo). **251 processos parados na mesa do gestor são invisíveis** porque uma cópia em outra unidade se mexeu. Este número vai na direção contrária da correção publicada.
- **Em 64 dos 285 parados, o movimento que zera o relógio ocorreu em outra unidade.** Ex.: um processo na CESS desde 03/09/2025 (~360 dias) aparece com 111 dias de parado porque a conclusão foi feita na COPAT.
- **17% da carteira não tem responsável, e é uma unidade só.** UMA-CMA concentra 186 dos 200 sem dono (64,8% dela); CESS 4 em 611, COMASUP 0 em 243. Dizer "16,9% da carteira" dilui um problema de 65% numa média que não descreve nenhuma unidade real. Não é falha de coleta (devidos = lidos, `processo_mesa.atribuido` também vazio).
- **Os 198 sem dono são dois fenômenos, não um.** Os 12 fora da UMA-CMA têm 0 ou 1 dia na unidade — são chegadas do dia. **Os 124 "sem dono há mais de 90 dias" estão todos na UMA-CMA.**
- **Na UMA-CMA: 186 sem dono + 78 numa única pessoa = 92% dos 287 processos.** Este era o número a publicar.
- **Duas das seis unidades não praticaram nenhum ato de saída em 30 dias** — UMA-CMA (287 processos, o 2º maior acervo) e GT-HTLV. Um terço do acervo do gestor sem movimento de saída algum.
- **Conclusões são inversas ao tamanho:** ASTEC (10 processos) fez 29; CESS (611, 52% da carteira) fez 4.
- **3 pessoas com processo atribuído hoje não têm conta**, e 3 contas não têm processo. "Ativar e avisar 61 pessoas" deixaria 3 responsáveis atuais sem acesso à própria fila — derruba a condição de entrada da fase 5.

**Qualidade do dado e do texto:**

- **Os 12 "sem data de entrada legível" são 12/12 `mov_parcial=1`** — não é o SEI que não tem a data, é a **coleta** que leu o histórico pela metade. E 11 dos 12 se moveram há 0 ou 1 dia (208 a 2.075 movimentos cada): são a parte **mais ativa** da fila, apresentados como limbo.
- **Os 314 atos "perdidos" se concentram em 19 processos, 297 deles em apenas 10** (um cai de 69 para 30 atos). É falha de captura pontual — o que merecia investigação — e a nota transformou em taxa média aplicada a tudo.
- **`unidade_envio` é uma terceira armadilha**: guarda o *destino* da última remessa feita pela unidade, não quem mandou o processo para lá. Quem "corrigir" `gerador_unidade` por ele erra de novo, de forma plausível.
- **Em remessa, o texto nomeia a ORIGEM e o campo de unidade traz o DESTINO.** Filtrar pelo campo de unidade mede quem *recebeu*. Essa inversão produziu, no caminho original, um topo de 363 atos inexistente.
- **Uma remessa multi-destino gera várias linhas**: contar linhas infla o topo de 114 para 115 e o 2º colocado de 38 para 47. A nota publicou "114/112" e "38" na mesma frase — duas contagens diferentes misturadas.
- **A taxonomia dos cinco estados não existe no código** (grep em `relatorios.py`, `app.py`, `montar_painel.py`, `templates/` não retorna nada). Foi inventada na nota: **o gestor não consegue conferir esses cinco números clicando em lugar nenhum.**
- **O arquivo de 26/08 foi ingerido duas vezes** (execuções 67 e 68): o banco tem 24 snapshots de 26/08, não 12. Qualquer contagem por data conta 26/08 em dobro — e a nota chama "18, 26 e 27/08" de três retratos.
- **Houve tentativa de coleta em 01/09 e ela falhou** (EXIT=4, TimeoutError de 60s no login do SIP; o mesmo em 21/08). A série tem furos por **falha**, não só por tarefa desabilitada — qualifica a tese de "coleta parada por desligamento".
- **Fragilidade de borda não declarada:** 7 processos com exatamente 30 dias de unidade, 4 com exatamente 90 sem movimento. Ler "até 30" como estrito leva Em curso de 463 para 456; "90 ou mais" leva Parado de 284 para 288.
- **O balde Parado é redundante**: nenhum processo tem 31–90 dias de unidade e >90 sem movimento (o movimento nunca é anterior à entrada). O segundo critério implica o primeiro.
- **Somar filas (972) ≠ processos atribuídos (969)**: 3 processos estão em duas mesas do gestor com pessoas *diferentes*.
- **A restrição "só ato ocorrido nas nossas mesas" corta dois terços do volume** (5.900 de 17.796) — é ela que torna o custo de disco pequeno. Sem ela, a carga inicial seria 3,70 MiB, metade do banco atual.

---

## 5. A conclusão muda?

**Não cai — e sai mais forte. Mas troca de sustentação, e o eixo "responder hoje" precisa de um número novo.**

- **"Responder fila / carga / sem-dono hoje": continua de pé, com números corrigidos.** Os cinco estados (menos o Parado), a concentração por unidade, a tabela por pessoa e o bloco sem-dono sobrevivem. E ganham dois fatos que a nota não tinha: a falta de responsável é **um problema de uma unidade (65% da UMA-CMA)**, não uma média de 17%; e **92% da UMA-CMA está sem dono ou com uma pessoa só**. Isso é mais acionável que o publicado.
- **"Recusar vazão nominal": mantém-se, mas o fundamento é outro.** O defeito "erosão do histórico" **cai** — o histórico não encolhe, cresce; o que existe é falha pontual de captura em 10 processos. Substituir por três defeitos que a verificação **confirmou e agravou**: (a) o banco **não persiste** movimento algum, então vazão é irreprodutível pelo painel; (b) autor só existe desde 22/08, em **4 dias úteis**, com fim de semana dentro; (c) o campo que mede estagnação é **contaminado entre unidades** — o passivo real é ~536, quase o dobro dos 285. Vazão nominal medida sobre essa base seria pior que o publicado, não melhor.
- **"Manter a finalidade registrada (opção A)": reforçada.** A fase 3 tocaria **1.109–1.391 logins de toda a SESAB** (não 1.107) para servir 61 pessoas (não 122), gravando **login/e-mail**, não nome de exibição. O custo de disco é menor que o estimado (≤1,6 MiB), então o argumento a favor nunca foi o disco — é a finalidade. Nada nela mudou.

**Uma correção de escopo é obrigatória antes de republicar:** a nota afirma "10 de 10 processos parados na CESS/IM" sobre uma unidade que o gestor **não pode abrir**. Não é imprecisão — é dado fora da fronteira de acesso apresentado ao gestor como sendo dele. Essa linha sai, não se corrige.