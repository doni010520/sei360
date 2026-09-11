# Módulo de Acompanhamento — desenho aprovado

> Desenho validado com o usuário em 11/09/2026.
> Funcionalidade **nova**, em **porta nova do menu**. Nada do que existe hoje muda:
> painel, relatórios, busca avançada, poço e coleta das mesas seguem iguais.

---

## 1. O que é, e a pergunta que responde

Uma lista de processos que a pessoa quer acompanhar **mesmo que eles não estejam em
nenhuma das mesas dela**. Ela cola o número, o sistema vai ler no SEI com o login
dela, e passa a reconferir todo dia.

A pergunta: **"onde este processo está agora, e o que mudou nele desde a última vez
que olhei?"**

Hoje o produto não responde isso. A carteira é o que chegou até a mesa; quando o
processo sai da mesa, ele desaparece do painel e a pessoa perde de vista exatamente
o que mais lhe interessa acompanhar.

## 2. O que o módulo NÃO faz — e por quê

Estas ausências são o desenho, não lacunas a preencher depois.

**Não entra na carteira.** Processo acompanhado não soma aos indicadores do painel,
não aparece nos 14 relatórios, não vira `snapshot`. Se entrasse, todo número do
produto passaria a misturar "o que é meu" com "o que eu observo" — e a carteira é a
fronteira que o resto do sistema inteiro defende.

**Não responde "parado há N dias aqui".** Os cinco campos de custódia
(`marco_unidade`, `recebimento`, `recebimento_por`, `envio`, `unidade_envio`) são
derivados PARA UMA MESA — é o que `poco.py` já trata como recalculável e nunca
copiável. Fora da mesa eles não têm referente. O módulo mostra "aberto em CIR-IBOT
há 14 dias", que é verdade, e **omite** o resto em vez de fabricá-lo.

**Não atravessa pessoa, e não passa pelo poço.** A lista é por conta e a leitura sai
do login daquela conta. Se duas pessoas seguem o mesmo processo, são duas leituras —
porque o que o SEI mostra depende de quem pergunta. O poço existe para reaproveitar
bloco caro **dentro de uma mesa compartilhada**; aqui não há mesa que justifique.

**Não amplia acesso.** O agente lê com o login da própria pessoa. Se o SEI não mostra
àquele login, o estado é `sem_acesso` e a tela diz isso — nunca ficha vazia com cara
de "processo sem novidade".

## 3. A porta no menu

Uma entrada nova em `portas.py`, depois de **Busca avançada** e antes de
**Relatórios** — a ordem segue a lógica que o próprio arquivo já documenta: painel é
a carteira que chegou, busca é o resto do SEI, e acompanhamento é o pedaço do resto
do SEI que a pessoa decidiu não perder de vista.

```python
{"id": "acompanhamento", "rotulo": "Acompanhamento",
 "subtitulo": "Processos que você segue, onde estiverem",
 "url": "/acompanhamento", "papeis": None},
```

`papeis: None` — toda conta logada tem a sua lista, como painel, busca, relatórios e
configuração. Ícone novo em `_ICONES["acompanhamento"]` (marcador/bookmark), no mesmo
formato dos existentes: `path`/`circle` sem `<svg>` em volta.

## 4. Modelo de dados — duas tabelas novas, nenhuma alterada

```sql
-- A LISTA. A chave é o PROTOCOLO, não o id_sei: o número é o que a pessoa tem na
-- mão; o id interno do SEI só se conhece depois da primeira leitura.
CREATE TABLE IF NOT EXISTS acompanhado(
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  protocolo TEXT NOT NULL,
  id_sei TEXT,
  origem TEXT NOT NULL,        -- 'manual' | 'painel' | 'sei_acompanhamento'
  nota TEXT,                   -- por que estou seguindo; texto da pessoa
  adicionado_em TEXT NOT NULL,
  estado TEXT NOT NULL,        -- 'novo'|'lido'|'sem_acesso'|'nao_encontrado'
  lido_em TEXT,
  PRIMARY KEY(usuario_id, instancia, protocolo));

-- O HISTÓRICO. Uma linha por leitura, para "o que mudou" ser DIFERENÇA MEDIDA e
-- não texto escrito à mão. É também a primeira série temporal do produto: hoje
-- todos os relatórios são retrato de um instante e o snapshot velho é expurgado
-- em 30 dias.
CREATE TABLE IF NOT EXISTS acompanhado_leitura(
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  instancia TEXT NOT NULL,
  protocolo TEXT NOT NULL,
  lido_em TEXT NOT NULL,
  aberto_em TEXT,              -- JSON: unidades da ÁRVORE do SEI
  ultimo_movimento TEXT,       -- JSON {dh, un, de}
  documentos INTEGER,
  movimentos INTEGER,
  mudou TEXT);                 -- JSON com o delta; NULL na primeira leitura
CREATE INDEX IF NOT EXISTS ix_acomp_leitura
  ON acompanhado_leitura(usuario_id, instancia, protocolo, id DESC);
```

**A fonte de `aberto_em` é a ÁRVORE, não a máquina de estados do andamento.** Medido
em 10/09/2026 sobre 15 coletas: em 1.278 discordâncias observáveis entre as duas, a
árvore bateu com a realidade da mesa em 100% dos casos e o andamento em 0%. O módulo
não repete esse erro.

## 5. Fluxo

```
pessoa cola números  ->  POST /acompanhamento/adicionar
                            valida formato, aplica teto, grava estado='novo'
                                        |
servidor tenta a     ->  para cada um, procura na CARTEIRA da pessoa (secao
CARTEIRA primeiro           5-bis). Achou? grava a leitura dali, de graca, e o
                            processo NAO vai para a fila do agente.
                                        |
estação pergunta     ->  GET /api/agente/acompanhamento
                            devolve so o que a carteira NAO respondeu: os 'novo'
                            e os nao lidos hoje, todos do dono daquele agente
                            (nunca de outra conta)
                                        |
estação lê no SEI    ->  pesquisa_sei.js busca por numero_sei -> link do processo
                            leitura REDUZIDA, ~3 requisições: a página do
                            processo, a árvore (de onde sai aberto_em, via
                            mesasPorArvore) e o histórico (último movimento e
                            as contagens). NÃO chama daMesa(): os cinco campos
                            por mesa nem são calculados.
                                        |
estação devolve      ->  POST /api/agente/acompanhamento
                            servidor calcula o DELTA contra a leitura anterior,
                            grava leitura + atualiza estado/lido_em
                                        |
pessoa vê            ->  GET /acompanhamento
```

O padrão do agente é o mesmo da busca avançada (`/api/agente/busca`): trabalho que a
estação **pega**, não tarefa empurrada. Assim o módulo reaproveita o plantão
(`rodar --atender`) para a leitura imediata ao adicionar, e a janela diária para a
reconferência — sem máquina nova de agendamento.

**O delta é calculado no servidor, comparando quatro coisas:** conjunto de unidades
abertas, data/hora do último movimento, contagem de documentos e contagem de
movimentos. O texto da tela é gerado do delta ("saiu da DGESS e foi recebido na
CIR-IBOT"), nunca escrito à mão em lugar nenhum.

## 5-bis. Reaproveitar a coleta da mesa

**Se o processo já está numa mesa da pessoa, o módulo não lê nada: usa o que a
coleta trouxe.** É a mesma economia do poço, aplicada dentro de uma conta só — e
aqui ela é integral, porque os quatro campos de que o módulo vive já estão
guardados: `processo_mesa` tem as unidades da árvore, e `processo` tem
`ultimo_movimento`, `documentos` e `movimentos`.

Efeito no custo: quem acompanha processo da própria carteira não gera **nenhuma**
requisição ao SEI. Só o que está fora da mesa é lido de fato — que é exatamente o
caso que o módulo existe para atender.

Três armadilhas que o reaproveitamento abre, e o que fecha cada uma:

**1. A fronteira.** A busca na carteira tem de passar pela MESMA função de recorte
que o painel usa (`snapshots_de(cx, usuario_id, unidades)`), nunca por um `SELECT`
direto em `processo`. Um `SELECT` por `id_sei` encontraria a linha de qualquer
unidade do banco, inclusive de mesa que aquela conta não alcança — e o módulo
viraria a porta lateral que contorna a fronteira que o resto do sistema defende.

**2. A idade.** A linha da carteira pode ser de dias atrás: na base medida em
10/09/2026, todas as 12 unidades estavam com coleta de 27/08 — nove dias úteis.
Gravar isso como "lido hoje" seria mentir com o carimbo. Então cada leitura registra
`fonte` e `medido_em`:

```sql
ALTER TABLE acompanhado_leitura ADD COLUMN fonte TEXT;      -- 'carteira' | 'sei'
ALTER TABLE acompanhado_leitura ADD COLUMN medido_em TEXT;  -- quando o dado foi medido
```

A tela diz **"pela sua coleta de 27/08"** quando vem da carteira e **"lido agora"**
quando vem de leitura direta. São procedências diferentes e o produto inteiro trata
procedência como parte do número, não como rodapé.

**3. A fonte de `aberto_em`.** A linha da carteira carrega `mesas_fonte`, que pode
ser `'andamento'` quando a árvore não veio. Nesse caso o `aberto_em` reaproveitado é
o que a medição de 10/09 mostrou errar em 100% dos casos observáveis. Não se relê por
isso — relê seria trocar um dado velho por uma requisição a cada dia —, mas a tela
marca `aberto_em` como não confirmado pela árvore, do mesmo modo que a faixa do
painel marca coleta compartilhada.

**Quando o processo sai da mesa**, ele simplesmente deixa de ser achado na carteira e
volta para a fila do agente na leitura seguinte. A transição é automática e não
precisa de aviso nenhum: é o momento em que o módulo começa a fazer o que prometeu.

**O delta não vê a fonte.** "O que mudou" compara os quatro valores e mais nada —
trocar de `carteira` para `sei` não é mudança no processo e não pode aparecer como se
fosse.

## 6. Estados, e nenhum silêncio

| Estado | Quando | O que a tela diz |
|---|---|---|
| `novo` | acabou de entrar na lista | "aguardando primeira leitura" |
| `lido` | leitura bem-sucedida | a ficha, com data da leitura |
| `sem_acesso` | o SEI recusou ao login daquela conta | "o SEI não mostra este processo ao seu login" |
| `nao_encontrado` | a busca por número não devolveu nada | "número não encontrado neste SEI — confira o dígito" |

Nenhum dos quatro é exibido como ausência de movimento. Foi o defeito que a auditoria
de 10/09 encontrou no vazio do painel ("nenhum processo corresponde aos filtros" para
quem nunca filtrou) e ele não se repete aqui.

## 7. Limites

**Teto de 100 processos por pessoa.** Com o reaproveitamento da carteira (5-bis), só
o que está fora das mesas custa requisição: **5 por processo** (medido em 11/09/2026 —
GET da tela de Pesquisa, POST da pesquisa, GET do processo, GET da árvore, GET do
andamento; a conta anterior dizia 3 e esquecia o par da pesquisa, que é refeito a cada
protocolo porque reusar formulário velho é o risco de `infra_hash` morto), ou **~500**
no pior caso de uma lista cheia inteiramente fora da carteira — contra as ~5.900 que a
coleta de 1.182 processos já faz, ou ~8,5% a mais. O teto
existe para a lista não virar uma segunda coleta sem ninguém ter decidido isso. Ao
estourar, a tela recusa com o número atual — não descarta em silêncio.

**Formato do protocolo validado na entrada.** Só dígitos, pontos e hífen. Linha que
não casa entra numa lista de recusadas exibida à pessoa, com o texto que ela colou —
o mesmo princípio de `filtros_recusados` em `pesquisa_sei.js`: filtro que não pegou
muda o universo da resposta sem mudar uma linha do resultado.

**Expurgo.** `acompanhado_leitura` entra em `expurgo.DIAS` com 180 dias: a série é o
valor do módulo, e ela não carrega texto livre além do `ultimo_movimento` que
`processo` já guarda. `acompanhado` **não** expira — é escolha da pessoa, e apagá-la
por idade seria decidir por ela.

## 8. Testes

Suíte nova, `teste_acompanhamento.py`, no padrão de `ambiente_teste.isolar()`:

1. adicionar um número grava `estado='novo'` e não toca `snapshot` nem `processo`;
2. lista de vários números de uma vez; linha inválida vai para recusadas, as válidas entram;
3. teto de 100 recusa com o número atual;
4. `GET /api/agente/acompanhamento` só devolve os processos **do dono daquele agente**
   (fronteira — o teste que importa mais);
5. leitura devolvida grava `acompanhado_leitura` e muda o estado;
6. segunda leitura com unidade diferente produz `mudou` com o delta certo;
7. primeira leitura tem `mudou` nulo, não "mudou tudo";
8. `sem_acesso` e `nao_encontrado` chegam à tela como texto próprio, não como ficha vazia;
9. processo acompanhado **não** aparece em `carteira()` nem em `relatorios.carregar()`;
10. a porta nova aparece no menu para todo papel logado;
11. processo que ESTÁ na carteira é respondido pela carteira e **não** entra na fila
    do agente — e a leitura sai com `fonte='carteira'` e o `medido_em` do snapshot,
    não com a hora de agora;
12. processo na carteira de OUTRA conta, fora do vínculo desta, **não** é
    reaproveitado: vai para a fila do agente como qualquer processo de fora (o teste
    que prova que o reaproveitamento não contorna a fronteira);
13. processo que sai da mesa entre duas leituras volta para a fila do agente sozinho;
14. mudar de `fonte` entre duas leituras não aparece no delta como mudança.

## 9. O que fica de fora desta versão

- **Regra por unidade geradora** ("tudo que a DGESS criar"). Exige o filtro
  `unidade_geradora` na busca avançada, que hoje não existe — a busca devolve o campo
  em `CAMPOS_ITEM` mas não filtra por ele. Vem depois, junto de busca salva.
- **Lista compartilhada por unidade.** Decidido: por pessoa. Compartilhar exige
  resolver "com o login de quem se lê", e a resposta honesta dependeria de tela de
  permissão por lista.
- **Resumo de IA do processo acompanhado.** A IA existe e está desligada; ligá-la
  aqui seria decidir custo por um módulo que ainda não tem uso medido.
- **Botão "atualizar agora" avulso.** A leitura imediata ao adicionar cobre o caso
  urgente; releitura sob demanda a qualquer momento pede trava para não virar marreta
  contra o SEI.

## 10. Importar do Acompanhamento Especial do SEI

Ação **opcional**, disparada pela pessoa — nunca sincronia automática. O SEI tem a
função "Acompanhamento Especial", e quem já a usa tem uma lista pronta lá. A
importação lê aquela listagem uma vez e insere o que encontrar com
`origem='sei_acompanhamento'`.

O SEI360 continua **dono da lista**: importar é semear, não espelhar. Remover aqui
não remove lá, e marcar lá depois não aparece aqui sem uma nova importação — dito na
tela, porque a alternativa é a pessoa supor sincronia que não existe.

A listagem é uma tela do SEI que o coletor ainda não abre; é o único ponto do módulo
que precisa de navegação nova, e é por isso que ela é opcional e sai por último.
