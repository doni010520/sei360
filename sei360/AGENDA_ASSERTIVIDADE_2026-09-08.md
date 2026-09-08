# AGENDA DE ASSERTIVIDADE — SEI360

*Base de toda medição citada: carteira do usuário 2 (6 unidades), snapshots correntes 37/38/39/40/47/48, coleta de 27/08/2026 07:45 — 1.167 processos distintos, 1.172 linhas. Banco lido em modo somente-leitura; nada foi escrito e nenhum arquivo foi editado.*

---

## 1. O diagnóstico em cinco linhas

1. **A fronteira existe, é correta e não é obrigatória.** Quatro funções a aplicam; seis consultas de produção contam a base sem ela — e a mais exposta é a tela de login, pública, que imprime "1.177 processos · 12 unidades" quando o número do gestor é 1.167 / 6. A nota de hoje não abriu buraco novo: repetiu o número que o produto publica na porta da rua.
2. **A suíte usa como valor esperado exatamente a consulta que errou.** `teste_relatorios.py:66-71` vincula a conta de teste a TODA unidade corrente e `:113-124` exige que os 14 relatórios batam com o COUNT sem fronteira (1.177). Um relatório que ignorasse a carteira passa em 275 das 277 verificações.
3. **A régua do dado não é declarada e não é única.** Três medidas de tempo discordam sobre o mesmo processo no mesmo segundo (permanência 62 dias, sem movimento 19,5, idade 149); 39,2% dos processos mudam de faixa conforme a régua, e duas tabelas exportadas usam os mesmos cinco rótulos de faixa sobre eixos diferentes — só uma tem nota.
4. **A coleta declara completude que não tem.** 133 processos (11,4%) com histórico lido pela metade sem nenhuma marca na lista, no filtro ou no export; `acomp_lido=0` em 5.912 de 5.912 linhas por causa de uma linha de JavaScript; 2.365 de 5.912 linhas do banco (40%) são a mesma leitura ingerida duas vezes.
5. **Resultado prático:** todo número da tela é indefensável na contestação por três perguntas triviais — *sobre qual carteira?*, *de quando?*, *lido inteiro?* — e o sistema hoje não responde nenhuma das três por escrito, no próprio artefato.

---

## 2. A tabela da agenda

Ordenada por **quanto cada conserto aumenta a chance de um número sobreviver a uma contestação**.
**(D)** = declarar em vez de consertar: o número não muda, passa a vir acompanhado do que o qualifica.

| # | O que conserta | Tamanho do problema (medido) | Esforço | O que passa a ser verdade depois |
|---|---|---|---|---|
| 1 | **(D)** Corrigir o corpo da nota já entregue (base, tabelas, CESS/IM) — `PLANO_METRICA_VAZAO_2026-09-08.md:26, :38, :52-58` | Corpo declara 1.177 e lista CESS/IM 4x antes da errata, 2x dentro de tabela de dado; 32 afirmações derrubadas | 3 h | O documento em circulação declara 1.167/1.172/6 unidades e a régua 27/08 07:45; nenhuma unidade fora da carteira aparece no corpo |
| 2 | Teste estático de porta única + rótulo honesto na tela pública (`app.py:244`, `login.html:916, 991`, `testes.py`) | 6 consultas de produção sem fronteira contra 4 com; login público imprime 1.177/12 (correto: 1.167/6); excedente = 10 processos, todos exclusivos da CESS/IM | 4 h | Consulta nova que junta `processo`↔`snapshot` sem `s.id IN (...)` reprova a suíte, salvo lista branca com motivo escrito e impresso a cada rodada |
| 3 | Fixture da suíte deixa de ser o banco inteiro (`teste_relatorios.py:66-71, 113-124, 127-149`) + fronteira nos 14 relatórios, destaques, gráfico e XLSX | 2 de 277 verificações tocam a fronteira; 1 delas é incapaz de reprovar (procura caminho inteiro num HTML que só imprime o último segmento) | 5 h | `base == carregar(subconjunto, uid)` **e** `base != total do sistema`; inverter `unidades_do` para devolver tudo derruba ≥14 verificações |
| 4 | Recortar `processo_mesa.atribuido` fora da carteira (`app.py:905-907`, `painel.html:1134`) | 81 logins de pessoas em 58 unidades sem acesso, em 107 pares processo-unidade, viajam no JSON do painel do gestor | 1 h | Nenhum login de mesa alheia sai da fronteira; os 980 chips legítimos continuam intactos |
| 5 | Guarda de leitura repetida + série canônica por dia + expurgo das cópias (`ingestao.py:431/489`, `relatorios.serie_por_dia`) | 2.365 de 5.912 linhas (40%) são segunda cópia; série lê 2.338→2.392→1.182 quando é 1.169→1.196→1.182; queda falsa de 51% em 27/08 | 8 h | Um retrato por (unidade, dono, instância, instante); nenhum gráfico por data conta o mesmo arquivo duas vezes — sem isso, o painel de vazão nasce errado |
| 6 | Chave do dicionário de resumos (`app.py:915`) | 927 dos 1.167 têm resumo; a busca acerta 0 em 1.167 (dict de `str`, chave `tuple`); `/admin` diz "927 com resumo" na mesma hora | 1 h | Painel e admin param de se contradizer; 927 resumos aparecem, denominador 1.167 e não 1.177 |
| 7 | Procedência responde quem REMETEU: coluna `remetente_unidade` + backfill dos 15 dias + troca do campo no relatório | 657 de 885 casos conferíveis (74,2%) divergem; o nº 1 da tela (COPRO-DA, 310) é o 7º remetente real (21); o maior remetente real (DGESS, 273) aparece com 2 | 9 h | "Quais unidades mais nos mandam processo?" passa a ser respondida pelo remetente; gerador vira item próprio com a pergunta que ele responde |
| 8 | Apagar `o._acomp_fresco = !!d._acomp_fresco` (`automacao_sei.js:1742`) | `acomp_lido=1` em 0 de 5.912 linhas, embora 296 processos tenham acompanhamento gravado; 872 gavetas dizem "não lido" sobre leitura feita | 30 min | A marca de leitura do acompanhamento passa a significar o que diz; a cobertura da coleta deixa de ser subdeclarada em 100% |
| 9 | **(D)** "Permanência" para de se chamar "parado" + nota com o desconto medido (`relatorios.py:1001, 452`) | 533 "parados +90d"; 142 (26,6%) moveram no SEI nos últimos 30 dias, 107 (20,1%) nos últimos 7 | 1 h | A tabela diz que conta desde a última ENTRADA e informa quantos não estão esquecidos — número recalculado, nunca escrito |
| 10 | **(D)** Panorama de triagem e etapa do painel declaram a segunda régua (`relatorios.py:949, 964-965`; `painel_v2.html:835-836`) | Fila "Revisar: parado há muito tempo" = 407 processos; 160 (39,3%) moveram em 90d, 58 (14,3%) em 30d, 24 (5,9%) em 7d | 3 h | O operador vê, linha a linha, dias na unidade **e** dias desde o último movimento no SEI, antes de gastar hora de trabalho |
| 11 | **(D)** "Tempo sem movimento" declara o ato de terceiro (`_mov_aqui`, coluna + nota) | 321 (27,5%) tiveram o último movimento fora da carteira; 257 aparecem como "moveu há ≤90d" por isso; 249 parados na mesa do gestor não aparecem no relatório que existe para achá-los | 3 h | A tabela mostra quantos "moveram" por ato alheio e admite que "parado na minha mesa" não é calculável neste banco |
| 12 | **(D)** Saúde do dado em TODOS os 14 relatórios (`saude` em `montar()`, tarja + folha de rosto do XLSX) | Nenhuma tela conta os 133 com histórico parcial nem os 1.167 sem acompanhamento lido; a tela N3 prometida no PLANO_PRODUTO §2.4 não existe | 3 h | Todo número publicado sai com "133 destes 1.167 tiveram o histórico lido pela metade"; a 15ª tela vira conveniência, não pré-requisito |
| 13 | **(D)** Tarja de coleta deixa de ficar verde com buraco (`app.py:646-657, 712-726`) | 6 de 6 unidades verdes; a consulta só olha `medido_em IS NULL` (=0) e ignora 134 linhas parciais (CESS 58, UMA-CMA 51, COMASUP 24) | 2 h | Unidade com leitura parcial fica amarela com a contagem no texto; acompanhamento não lido vira frase, não cor |
| 14 | Cobertura x incidência nas duas telas (`relatorios.py:293-372`) | `doc_incluido` 100% de cobertura contra 4,5% de incidência (52 processos) — 95 pontos; `mesas_divergem` 100% x 13,0% (152) | 3 h | O cartão para de anunciar 100% acima de uma tabela que conta 52; campo booleano se declara sozinho |
| 15 | Selo, filtro, coluna e tarja para `mov_parcial` (`painel.html:1216, 1062, 1678` + `montar_painel.py`) | 133 processos (11,4%) sem marca na lista/export, contra 4 (0,3%) com `truncado` que têm selo, filtro e coluna | 4 h | Quem varre a lista ou exporta o .xlsx enxerga as 133 leituras incompletas; o rótulo carrega contagem medida do banco |
| 16 | Movimentos nunca regridem: `Math.max` + alerta `movimentos_regrediram` (`automacao_sei.js:1091-1093`, `ingestao.py`) | 18 de 1.140 processos (1,6%) tiveram `movimentos` DIMINUIR entre coletas (100→2, 91→1, 100→8); 13 só entre 26 e 27/08 | 1 dia | A contagem que alimenta gaveta, ordenação, faixas de volume, `truncado` e `mov_parcial` para de encolher; regressão nova avisa no dia |
| 17 | Persistir `movimentos_paginas` (`banco.py` DDL + `ingestao.py:55-56`) | Faixa 101–200 movimentos VAZIA em 5.912 linhas, entre 224 em 91–100 e 231 em 201–300; todo `mov_parcial=1` tem `movimentos>=201` | 2 h + 1 dia de apuração | As três hipóteses da aritmética se separam por consulta, sem reler o SEI; o recorte dos "133" deixa de ser suspeito |
| 18 | `truncado` só quando não alcançou o início (`automacao_sei.js:917`) | 3 dos 4 marcados têm autuação — leitura completa marcada como truncada; o filtro devolve 4 onde o defensável é 1 | 2 h | O selo "histórico truncado" passa a significar o que a gaveta afirma; invariante: nunca `truncado=1` com autuação preenchida |
| 19 | Os 12 sem data de entrada param de contar como "não parados" (`automacao_sei.js:1717`, `painel.html` REGRAS, `relatorios.py:492/640/949`) | 12 processos com `marco_unidade` NULL (todos `mov_parcial=1`, 11 sem marca de "não sei"); idades de 30 a 868 dias; `(x or 0) > 90` os conta como zero dia | 10 h | "Não sei" deixa de virar "não"; parados + sem-marco fecha com a base (533 + 12 = 545) e os 12 ganham etapa "Conferir no SEI" |
| 20 | **(D)** `mesas_divergem` em três estados (`relatorios.py:897`, `app.py`, `painel.html:1215, 1557`) | 152 processos marcados; 35 (23%) calculados sobre histórico parcial e nunca recalculados por `consertarTruncados`; taxa 26,1% nos parciais x 11,5% nos completos | 2 h | "Conferir no SEI" só acende onde a comparação é possível; os dois destaques somam os 152 de hoje (nada some por reclassificação) |
| 21 | Persistir `acomp_disponivel` + três frases na gaveta (`banco.py`, `ingestao.py`, `app.py`, `painel.html:1552`) | Campo coletado (`:1020`) e exportado (`:1667`), sem coluna no banco; impossível separar os 872 vazios entre "não tem" e "não me deixaram ver" | 1 dia (depende do #8) | "Vazio" passa a ter causa: sem grupo, tela negada, ou não lido — três caixas que somam 1.167 |
| 22 | Idade do processo entra nos relatórios (`relatorios.py:119-131`, `rel_minha_fila`) | `autuacao` fora de `COLUNAS`; painel exibe idade em 4 lugares e os 14 relatórios em nenhum; 115 autuados há +2 anos, 7 deles com ≤7 dias na unidade | 2 h | A planilha distingue "velho e recém-chegado" de "velho e esquecido"; invariante idade ≥ dias na unidade |
| 23 | **(D)** Cabeçalhos e notas das duas tabelas de faixa (`relatorios.py:452, 721-726`) | Mesmos 5 rótulos sobre réguas diferentes; 457 processos (39,2%) mudam de faixa; "mais de 180" vale 275 numa e 145 na outra | 30 min | Fora da tela, as duas planilhas dizem qual eixo mediram; toda tabela ordinal passa a exigir nota |
| 24 | `movimentos_exato` desenhado (`painel.html:1537, 1671`) | 1.172 de 1.172 linhas trazem o campo; 0 ocorrências em `templates/` | 2 h | "234" e "ao menos 234" deixam de ser a mesma célula, justamente nos 133 em que a diferença importa (fazer depois de #16 e #17) |
| 25 | Data absoluta e sigla que identifica no catálogo `/relatorios` (`app.py:731, 1727-1731`) | Catálogo declara denominador e omite `medido_em`/`gerado_em`; régua só relativa, sem ano; `curta = split('/')[-1]` não separa CESS de CESS/IM | 3 h | Número copiado da tela sai com a data que o reproduz e com unidade identificável — o vetor exato do vazamento de hoje |
| 26 | Tarja de procedência lida por valor + frase de ausência (`relatorio.html:20-31`) | A verificação atual (`"procedencia" in h2`) casa com o nome de uma classe CSS de um `<div>` incondicional: tarja vazia passa verde | 2 h | Tela sem coleta declara "SEM PROCEDÊNCIA — este número não é reproduzível" em vez de publicar número mudo |
| 27 | Rótulo do gráfico que identifica (`relatorios.py:1156-1157, 1187`) | Em "De onde os processos vêm": ENG.CLINICA (11) e PATRIMONIO (10) nomeiam agregado e mostram uma unidade; 14 siglas finais colidem no universo (DA em 11 unidades) | 3 h | Cada barra identifica exatamente 1 unidade; as duas asserções que hoje EXIGEM o encurtamento passam a exigir identificação |
| 28 | Nome do XLSX carimba o dado (`app.py:1792`, `montar()`) | Nome usa `datetime.now`; o conteúdo (folha de rosto) está certo — é o nome que sobrevive ao e-mail | 1 h | `sei360_permanencia_dado-2026-08-27_gerado-2026-09-08.xlsx`; sem coleta, `dado-sem-coleta`, nunca a data de hoje |
| 29 | `mesas_coleta` recortada na leitura + alerta de conteúdo fora do escopo (`app.py`, `ingestao.py:515`, `painel.html:1245/1336/1563`) | Fronteira desses campos é a CONTA (12 mesas), não a carteira (6); efeito vivo hoje = 0, mas basta um processo aberto em CESS e CESS/IM para repetir o incidente — sem alerta | 3 h | O nome de mesa sem acesso vira contador ("+1 fora da sua carteira") e gera `unidade_inesperada` na ingestão |
| 30 | Promoção de candidato não instala retrato velho (`app.py:2431-2444`) | 12 arquivos nunca ingeridos (12.642 linhas); simulando-os, 19 viram candidato; 1 clique instalaria a COMASUP de 13/08 (208) sobre a de 27/08 (243) | 4 h | Promover candidato anterior à corrente é recusado com motivo nas duas datas; ingerir os 12 dias vira operação, não risco |
| 31 | Recusa por sha deixa de ser silenciosa e passa a recortar por dono/instância; `--reprocessar` separado de `--forcar` (`ingestao.py:303-315`, `app.py:3423-3427`) | Recusa não grava alerta (única do arquivo assim) e responde `ok=true`; consulta com 1 parâmetro contra 3 e 4 das irmãs — recusaria publicação legítima de outra pessoa | 4,5 h | Republicar o arquivo de ontem aparece como repetição, não como coleta boa; segunda pessoa consegue ter carteira própria |
| 32 | Alerta `coleta_falhou` no servidor (`coleta.py:307`) | 3 de 18 execuções falharam (16,7%), todas em `Page.goto: Timeout 60000ms` no login do SIP (21/08, 01/09 x2); nenhuma virou execução ou alerta no banco; sem log desde 02/09 | 1,5 h | Falha de coleta deixa de custar dois dias úteis de série em silêncio |
| 33 | `regra_versao` no snapshot (`banco.py` DDL, `ingestao.py`) | `sei_sesab_2026-08-18.json` tem sha idêntico ao gravado, mas 214 linhas COMASUP contra 218 no snapshot: o retrato depende do código, não só do arquivo | 4 h | "Já ingerido" passa a significar "já ingerido por esta regra"; os 36 snapshots antigos ficam declaradamente não reproduzíveis |
| 34 | Canário do poço distingue NULL de zero (`poco.py:206-211, 269-278`) | `canario_divergencias=0` em ex67 e ex68 (o arquivo conferido contra si mesmo) contra 14 em ex69 | 2 h | "Não tinha com o que conferir" para de aparecer como nota cheia |
| 35 | `unidades_do()` falha fechado com nome ambíguo + promoção compara o par (`app.py:210-231, 2428`) | 12 sítios decidem fronteira por nome contra 1 pelo par; efeito hoje = 0 (só SEI-SESAB, 48 snapshots, 0 nomes compartilhados) | 4 h | No dia em que a FESF trouxer GABINETE homônimo, ninguém promove, rejeita ou recebe alerta de snapshot da outra instalação em silêncio |
| 36 | **(D)** Rótulo único das mesas + sha no log do coletor + recusa de `.anterior` (`painel.html:1245/1563/1659`, `coletor_sesab.py`, `ingestao.py`) | "Mesas da conta" promete 12 e entrega no máximo 6; log de 13/08 diz 1.134 e os dois arquivos no disco têm 1.135 e 1.138 | 2,5 h | Quem audita a planilha fora da tela para de concluir que faltam 6 mesas; arquivo↔log vira conferência de um comando |

---

## 3. O bloco zero — antes de publicar qualquer número novo

Hoje foi ao gestor uma nota com **67 afirmações numéricas, das quais 32 caíram em sete verificações independentes**, e o erro incluiu **expor dado de uma unidade a que ele não tem acesso** (CESS/IM). Nenhuma trava impediu; nenhum teste pegou; e a suíte, escrita como está, **considerava correto** o número que produziu o incidente. Enquanto os cinco itens abaixo não estiverem prontos, **nenhum número novo sai** — nem em nota, nem em slide, nem em planilha, nem em tela nova. Não é conservadorismo: é que hoje não existe como responder à pergunta "de onde saiu esse número?" sem reabrir o banco à mão.

**Z1 — Corrigir o corpo da nota entregue (item 1, 3 h).** A errata está no fim do arquivo; o corpo, que é a parte que responde as perguntas, ainda declara base 1.177 e ainda lista CESS/IM em duas tabelas de dado. Enquanto isso for verdade, o erro de acesso continua publicado, não corrigido. A errata fica onde está — ela é o registro de que 32 afirmações caíram.

**Z2 — Teste estático da porta única + rótulo honesto no login (item 2, 4 h).** A tela pública imprime hoje o mesmo 1.177 da nota. Não dá para consertar o número numa página sem sessão (ela não tem carteira): dá para deixar de chamá-lo de "carteira coberta". E a sétima consulta sem fronteira tem de ser impedida por teste, não por disciplina.

**Z3 — Desmontar a tautologia da suíte (item 3, 5 h).** Enquanto o fixture vincular a conta de teste às 12 unidades e exigir que os relatórios batam com o total do sistema, **a suíte continua sendo o carimbo do erro**. Este é o item que muda a natureza de tudo o que vier depois: sem ele, qualquer conserto abaixo é reversível por acidente na próxima edição.

**Z4 — Estancar o vazamento de pessoa (item 4, 1 h).** O painel entrega ao navegador do gestor 81 logins de servidores de 58 unidades a que ele não tem acesso. O relatório recusa explicitamente esse campo e tem teste dizendo que "ele não é lido em lugar nenhum do caminho" — afirmação falsa desde `app.py:905`. Uma hora de trabalho.

**Z5 — Deduplicar a série antes de qualquer métrica de vazão (item 5, 8 h).** 40% das linhas do banco são a mesma leitura ingerida duas vezes; a série por data mostra queda de 51% em 27/08 onde a variação real é −1,2%. O painel de vazão proposto no `PLANO_METRICA_VAZAO_2026-09-08.md` se apoia exatamente nessa contagem. Publicar vazão antes disto é repetir o erro de hoje com outro número.

**Custo do bloco zero: 21 h — 2,5 dias-pessoa.** Z1 é editorial, Z4 é uma hora; Z2 e Z3 são a mesma tarde de trabalho em arquivos diferentes; Z5 é o único que exige cuidado com migração e roda em cópia antes.

---

## 4. As travas — uma verificação por classe de erro

| Classe de erro | Trava | Arquivo |
|---|---|---|
| **Consulta nova sem fronteira** — *teria pegado o erro de hoje* | Toda ocorrência de `FROM processo p JOIN snapshot s` tem `s.id IN (...)` ou está na lista branca com motivo >40 caracteres, impressa a cada rodada | `testes.py` |
| **Relatório que ignora a carteira** — *teria pegado o erro de hoje* | Fixture com subconjunto estrito: `base == len(carregar(subconjunto, uid))` **e** `base != total_do_sistema` | `teste_relatorios.py` |
| Unidade fora do vínculo publicada | `set(unidades_apuradas) <= set(unidades_do(uid))` em rota HTML, destaques, gráfico e XLSX | `teste_relatorios.py` |
| Pessoa fora do vínculo publicada | Payload de `/painel` não traz `atribuido` de mesa fora da carteira; 980 chips legítimos preservados | `teste_multiusuario.py` |
| Documento entregue com número derrubado | Corpo da nota não cita nenhum número da coluna "Publicado" da errata nem unidade fora de `unidades_do(2)` — lista vinda da função, não escrita à mão | `conferir_nota.py` |
| Mesma leitura ingerida duas vezes | 1 snapshot por (unidade, dono, instância, `coletado_em`); publicar de novo devolve `repetido`, alerta e execução `nao_executada` | `testes.py` |
| Corrente substituída por retrato igual ou mais velho | Nenhum `expirado` sem corrente estritamente mais novo; promover candidato anterior não troca a corrente | `testes.py` |
| Marca de leitura que mente | Nenhuma atribuição a `_acomp_fresco` com `d.` à direita; `truncado=1` nunca com autuação preenchida; `movimentos` nunca regride | `_teste_gavetas.js`, `conferir_js.py`, `testes.py` |
| Contagem de movimentos impossível | Nenhuma faixa de 100 movimentos vazia entre duas faixas povoadas (falha hoje, de propósito) | `testes.py` |
| Número publicado sem qualificação | Todos os 14 relatórios devolvem `saude` com `saude['total'] == resultado['total']`, batendo com SQL sobre os mesmos snapshot_ids | `teste_relatorios.py` |
| Cobertura confundida com incidência | Para todo campo, `cobertura_agregada` e a recontagem sobre `carregar()` dão a mesma incidência; existe campo com 100% x <50% na base | `teste_relatorios.py` |
| Nota com número escrito à mão | Notas de permanência, triagem e sem-movimento contêm o valor **recalculado** no próprio teste; a frase some numa base sem o caso | `teste_relatorios.py` |
| "Não sei" contado como "não" | `parados + sem_marco == total dos que não são comprovadamente recentes`; `_acima(-3, 90) is False` | `teste_relatorios.py` |
| Corte dos 90 dias mudado sem querer | `_p90 == soma das faixas "91 a 180" e "mais de 180"`; sabotagem `>`→`>=` tem de reprovar | `teste_relatorios.py` |
| Procedência como enfeite | Cada `p['texto']` de `montar()['procedencia']` presente no HTML servido (não no arquivo de template); base sem coleta renderiza a frase de ausência | `teste_relatorios.py` |
| Rótulo que não identifica | Cada rótulo do gráfico casa com exatamente 1 unidade do relatório — rodado em `procedencia`, onde a colisão existe | `teste_relatorios.py`, `teste_busca.py` |
| Artefato que se apresenta pela data errada | Data do `download_name` == data da folha de rosto do XLSX; `dado-` ≠ `gerado-` na base atual | `teste_relatorios.py` |
| Remetente derivado errado | `remetente_para`: remessa cujo `un` é o destino, unidade que só recebeu, custódia vazia, e a armadilha da mesma unidade como destino e remetente | `teste_poco.py` |
| Canário que confere contra si mesmo | Dois `publicar()` com o mesmo carimbo → `canario_divergencias` NULL, não 0 | `teste_poco.py` |
| Fronteira por nome de unidade | Gestor com vínculo só na FESF recebe 403 ao promover candidato homônimo da SESAB, **e** o snapshot continua `candidato` no banco | `testes.py` |

---

## 5. O que continua não sendo assertivo depois de tudo — e vai na tela como tarja permanente

Estes não são débito técnico: são limite do que o SEI entrega e do que já foi (ou não foi) guardado. Nenhum some com código.

1. **"Parado na minha mesa" não é calculável.** O banco não persiste histórico de movimentos — só `processo.movimentos` (contagem) e `ultimo_movimento` (o último); `poco_processo.mov_custodia` tem 0 linhas. Os 536 parados +90d dentro da mesa (contra 284 pela regra atual, 251 invisíveis) são dado recebido, não reproduzível por consulta a este banco. A tela pode dizer que a régua é global; não pode substituí-la.
2. **`marco_unidade` é a ÚLTIMA entrada na unidade, não a primeira.** Em 30,5% dos casos houve entrada anterior; mediana de 40 dias mostrados contra 138 acumulados. Sem histórico persistido, isso também não é re-mensurável hoje.
3. **133 processos (11,4%) têm as páginas do meio do histórico não lidas.** Resolver exige reler o SEI, processo a processo, com custo de requisição. Enquanto não for relido, a data de entrada desses pode sair mais velha do que é — até 56 deles estão entre os 533 "parados +90d".
4. **O remetente só existe para 886 de 1.167 (75,9%).** 275 nasceram na própria mesa e nunca vieram de lugar nenhum; o restante depende dos JSONs originais e não é recuperável para dias cujo arquivo se perder.
5. **13/08 não é auditável.** O log diz 1.134 registros; no disco há um arquivo de 1.135 e outro de 1.138, ambos posteriores ao log. Nenhum dos dois é o que a automação registrou. Isso fica escrito, não escolhido a dedo.
6. **18/08 não é reproduzível a partir do arquivo.** A regra de mesa mudou depois; o mesmo arquivo hoje dá 214 linhas COMASUP contra as 218 gravadas.
7. **Atribuição e responsável em unidade alheia não são exibidos** — por desenho, depois do item 4 da agenda. Ausência declarada, não "sem responsável".
8. **A faixa 101–200 movimentos vazia pode ser do SEI e não nossa.** Distinguir as três hipóteses exige reler o SEI; o item 17 apenas torna a pergunta respondível por consulta.
9. **A coleta depende de rede e do login do SIP.** 3 de 18 execuções falharam por timeout de 60 s; não há log para 14/08, 28–31/08 nem de 02/09 em diante. A série tem furo por falha e por tarefa parada, e o alerta do item 32 avisa — não impede.
10. **Todo número é de uma coleta, não de agora.** A régua de 27/08 07:45 envelhece a cada dia sem coleta nova; enquanto a coleta SESAB estiver parada, o painel está correto sobre um retrato, e essa distinção tem de estar impressa em cima do número, não no rodapé.

**Texto sugerido da tarja permanente:** *"Medido sobre a coleta de DD/MM/AAAA HH:MM, nas N unidades da sua carteira (base: X processos). Tempo na unidade conta desde a última ENTRADA; tempo sem movimento conta o SEI inteiro, inclusive atos de outras unidades. K destes tiveram o histórico lido pela metade."*

---

## 6. Custo total e ordem de execução

**Total: ≈ 124 h ≈ 15,5 dias-pessoa.** Com duas frentes em paralelo, ≈ 3 semanas de calendário.

| Onda | Itens | Custo | Regra |
|---|---|---|---|
| **0 — bloco zero** | 1, 2, 3, 4, 5 | 21 h (2,5 d) | Sequencial no que toca a suíte (3 antes de tudo que dependa de teste). Nenhum número novo publicado até o fim. |
| **1 — o que a tela afirma errado hoje** | 6, 7, 8, 9, 10, 11 | 18 h (2,3 d) | 7 depende da coluna de remetente (gravar antes, backfill em cópia); 8 é de uma linha e destrava 21. |
| **2 — qualificar todo número publicado** | 12, 13, 14, 15, 23, 25, 26, 28 | 20 h (2,5 d) | Toda esta onda é **(D)**: nenhum número muda, todos passam a vir acompanhados. Pode rodar em paralelo com a onda 1. |
| **3 — a contagem que alimenta as réguas** | 16, 17, 18, 19, 20, 21, 22, 24 | 39 h (5 d) | Ordem obrigatória: 16 → 17 → 24. Fazer 24 antes de 16/17 dá precisão aparente sobre número duvidoso. |
| **4 — série, ingestão e coleta** | 29, 30, 31, 32, 33, 34, 36 | 22 h (2,8 d) | Depende do 5. Ingerir os 12 arquivos parados só depois do 30. |
| **5 — o que só dói quando a FESF chegar** | 27, 35 | 7 h (0,9 d) | Efeito medido hoje = 0. Não antecipar; não esquecer. |

**Paralelismo real — duas frentes, sem conflito de arquivo:**
- **Frente A (servidor/relatórios):** `relatorios.py`, `app.py`, `templates/`, `teste_relatorios.py` — ondas 0 (2/3/4), 2, e os itens de relatório da 3.
- **Frente B (coletor e ingestão):** `automacao_sei.js`, `ingestao.py`, `banco.py`, `poco.py`, `coleta.py` — ondas 0 (5), 4, e os itens 16–18, 21 da 3.
- **Ponto de encontro:** o item 19 (12 sem marco) toca as duas frentes e o painel gerado — agendar como tarefa única, não dividir.

**Duas condições que a agenda não controla:**
1. **Sete consertos vivem em `automacao_sei.js` e só produzem efeito na coleta seguinte.** Com a coleta SESAB parada, eles ficam prontos e mudos. Religar a coleta é pré-requisito de verificação dos itens 8, 16, 17, 18, 19 e 21 — o critério "pronto" deles é uma consulta ao snapshot do dia seguinte, não um teste local.
2. **`templates/painel.html` e `painel_solto.html` são gerados.** Editar diretamente é trabalho apagado na próxima geração: a origem é `painel_sesab\painel_v2.html` + `montar_painel.py`. Vale para os itens 10, 15, 20, 24, 29 e 36.