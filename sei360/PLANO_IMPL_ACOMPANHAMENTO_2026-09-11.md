# Módulo de Acompanhamento — plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA — use `superpowers:subagent-driven-development`
> (recomendado) ou `superpowers:executing-plans` para implementar tarefa por tarefa.
> Os passos usam checkbox (`- [ ]`) para acompanhamento.

**Objetivo:** dar ao SEI360 uma porta nova onde a pessoa acompanha processos por número,
mesmo fora das mesas dela, vendo onde cada um está e o que mudou desde a última leitura.

**Arquitetura:** módulo isolado — duas tabelas novas, um arquivo de regra novo
(`acompanhamento.py`), uma tela nova e dois endpoints de agente. Nada do que existe é
alterado além de três pontos de encaixe: o DDL, a lista de portas e o expurgo. Processo
que já está na carteira da pessoa é respondido pela própria coleta, sem ida ao SEI;
só o que está fora vira trabalho para a estação.

**Pilha:** Flask + SQLite (stdlib `sqlite3`), Jinja2, JS sem framework na estação,
testes em script próprio com `ambiente_teste.isolar`.

**Desenho aprovado:** `sei360/PLANO_ACOMPANHAMENTO_2026-09-11.md`. Leia antes de começar —
as seções 2 e 5-bis contêm as ausências deliberadas e as três armadilhas do
reaproveitamento, e um passo deste plano que contradiga aquele documento está errado.

---

## Divisão em duas fases

**Fase 1 (tarefas 1 a 7)** entrega o módulo inteiro para processo que está na carteira:
tabelas, regra, tela, porta no menu e reaproveitamento. Nada na estação muda. É
software funcionando e testável sozinho — a pessoa já acompanha, vê "o que mudou" e a
procedência, e o custo ao SEI é zero.

**Fase 2 (tarefas 8 a 10)** entrega o caso que motivou o módulo: processo **fora** das
mesas, lido pela estação. Depende da fase 1 estar verde.

Pare entre as fases e rode a suíte inteira antes de seguir.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `sei360/servidor/acompanhamento.py` | **Criar.** Toda a regra: normalizar número, teto, reaproveitar a carteira, calcular delta, gravar leitura. Nenhuma rota, nenhum HTML. |
| `sei360/servidor/banco.py` | **Modificar.** Duas tabelas novas no `DDL`. |
| `sei360/servidor/portas.py` | **Modificar.** A porta nova e o ícone. |
| `sei360/servidor/app.py` | **Modificar.** Três rotas de tela e dois endpoints de agente. Só transporte: a regra fica em `acompanhamento.py`. |
| `sei360/servidor/templates/acompanhamento.html` | **Criar.** A tela. |
| `sei360/servidor/expurgo.py` | **Modificar.** Retenção da série de leituras. |
| `sei360/servidor/teste_acompanhamento.py` | **Criar.** A suíte. |
| `sei360/agente/sei360_agente.py` | **Modificar (fase 2).** Ciclo que pega e devolve leituras. |
| `painel_sesab/coleta.py` | **Modificar (fase 2).** Modo `--acompanhar`. |
| `painel_sesab/automacao_sei.js` | **Modificar (fase 2).** Leitura reduzida de um processo por número. |

`acompanhamento.py` nasce separado de `app.py` de propósito: `app.py` já tem 3.500
linhas, e regra dentro de rota é o que torna teste sem servidor impossível. O padrão
já existe na casa — `busca.py`, `ingestao.py` e `poco.py` são regra pura, e `app.py`
só os chama.

---

# Fase 1 — o módulo, respondido pela carteira

## Tarefa 1: as duas tabelas

**Arquivos:**
- Modificar: `sei360/servidor/banco.py` (constante `DDL`, no fim, antes do `"""` de fecho)
- Testar: `sei360/servidor/teste_acompanhamento.py` (criar)

`migrar()` cria tabela nova pelo `executescript(DDL)` e acrescenta coluna nova
comparando o DDL com o `PRAGMA table_info`. Então **basta escrever no DDL** — nunca
escreva `ALTER TABLE` à mão neste projeto.

- [ ] **Passo 1: escrever o teste que falha**

Criar `sei360/servidor/teste_acompanhamento.py`:

```python
# -*- coding: utf-8 -*-
"""O módulo de Acompanhamento: lista por pessoa, lida com o login dela.

`copiar=False`: esta suíte semeia tudo o que usa. Copiar o banco de trabalho a
faria depender de uma carteira que pode não existir na árvore — foi o que deixou
`teste_relatorios.py` sem rodar depois da separação do repositório.

    python teste_acompanhamento.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["SEI360_ATENDENTE"] = "0"

from ambiente_teste import isolar          # noqa: E402

isolar(__file__, copiar=False)

import banco                               # noqa: E402
from banco import agora, conectar          # noqa: E402

ok, falhas = 0, []


def checar(nome, cond, det=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {det}")


banco.migrar()

print("1. esquema")
_cx = conectar()
_tabelas = {r["name"] for r in _cx.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
checar("a tabela da lista existe", "acompanhado" in _tabelas, str(sorted(_tabelas))[:200])
checar("a tabela do histórico existe", "acompanhado_leitura" in _tabelas)
_cols = {r[1] for r in _cx.execute("PRAGMA table_info(acompanhado_leitura)")}
# `fonte` e `medido_em` são a armadilha 2 do desenho: dado da carteira pode ser
# de dias atrás, e gravá-lo como "lido hoje" seria mentir no carimbo.
checar("o histórico sabe de ONDE e de QUANDO é o dado",
       {"fonte", "medido_em", "aberto_em_fonte"} <= _cols, str(sorted(_cols)))
_cx.close()

print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
```

- [ ] **Passo 2: rodar e ver falhar**

Rodar: `cd sei360/servidor && python teste_acompanhamento.py`
Esperado: `FALHA a tabela da lista existe`

- [ ] **Passo 3: escrever o DDL**

Em `sei360/servidor/banco.py`, acrescentar ao fim da constante `DDL`:

```sql
-- ACOMPANHAMENTO — a lista de processos que a pessoa segue mesmo FORA das mesas
-- dela. Tabela separada de `processo` de propósito: processo acompanhado não é
-- carteira, não vira snapshot e não entra em relatório nenhum. Se entrasse, todo
-- número do produto passaria a misturar "o que é meu" com "o que eu observo".
--
-- A chave é o PROTOCOLO, não o `id_sei`: o número é o que a pessoa tem na mão, e
-- o id interno do SEI só se conhece depois da primeira leitura.
CREATE TABLE IF NOT EXISTS acompanhado(
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  protocolo TEXT NOT NULL,
  id_sei TEXT,
  origem TEXT NOT NULL,                   -- 'manual'|'painel'|'sei_acompanhamento'
  nota TEXT,
  adicionado_em TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'novo',    -- 'novo'|'lido'|'sem_acesso'|'nao_encontrado'
  lido_em TEXT,
  PRIMARY KEY(usuario_id, instancia, protocolo));

-- O HISTÓRICO: uma linha por leitura. Existe para "o que mudou" ser DIFERENÇA
-- MEDIDA, e não texto escrito à mão em algum lugar. É também a primeira série
-- temporal do produto — todos os relatórios são retrato de um instante, e o
-- snapshot velho é expurgado em 30 dias.
--
-- `fonte` e `medido_em` não são enfeite: a leitura pode vir da carteira, que
-- pode ser de dias atrás (medido: nove dias úteis, em 10/09/2026). Carimbar isso
-- como "lido hoje" seria mentir. `aberto_em_fonte` diz se as unidades vieram da
-- ÁRVORE ou da máquina de estados do andamento — a segunda errou em 100% dos
-- 1.278 casos observáveis, e a tela precisa poder dizer isso.
CREATE TABLE IF NOT EXISTS acompanhado_leitura(
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  instancia TEXT NOT NULL,
  protocolo TEXT NOT NULL,
  lido_em TEXT NOT NULL,
  fonte TEXT,                             -- 'carteira' | 'sei'
  medido_em TEXT,
  aberto_em TEXT,                         -- JSON: lista de unidades
  aberto_em_fonte TEXT,                   -- 'arvore' | 'andamento'
  ultimo_movimento TEXT,                  -- JSON {dh, un, de}
  documentos INTEGER,
  movimentos INTEGER,
  mudou TEXT);                            -- JSON do delta; NULL na 1a leitura
CREATE INDEX IF NOT EXISTS ix_acomp_leitura
  ON acompanhado_leitura(usuario_id, instancia, protocolo, id DESC);
```

- [ ] **Passo 4: rodar e ver passar**

Rodar: `python teste_acompanhamento.py`
Esperado: `3 verificações OK, 0 falha(s)`

- [ ] **Passo 5: commit**

```bash
git add sei360/servidor/banco.py sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: as duas tabelas do modulo"
```

---

## Tarefa 2: normalizar o número do processo

**Arquivos:**
- Criar: `sei360/servidor/acompanhamento.py`
- Modificar: `sei360/servidor/teste_acompanhamento.py`

- [ ] **Passo 1: escrever o teste que falha**

Acrescentar em `teste_acompanhamento.py`, antes do bloco final de contagem:

```python
print("\n2. normalizar o número colado")
import acompanhamento as ac                                      # noqa: E402

checar("espaço em volta sai", ac.normalizar("  019.5120.2026.0161681-50 ")
       == "019.5120.2026.0161681-50")
checar("linha vazia é recusada", ac.normalizar("   ") is None)
checar("texto que não é número é recusado", ac.normalizar("processo da Laisa") is None)
# O SEI 4.0 da FESF e o 5.0.4 da SESAB imprimem o mesmo número com pontuação
# diferente; quem cola, cola o que viu.
checar("número sem pontuação passa", ac.normalizar("019512020260161681") is not None)
checar("número curto demais é recusado", ac.normalizar("123") is None)
```

- [ ] **Passo 2: rodar e ver falhar**

Rodar: `python teste_acompanhamento.py`
Esperado: `ModuleNotFoundError: No module named 'acompanhamento'`

- [ ] **Passo 3: criar o módulo com a normalização**

Criar `sei360/servidor/acompanhamento.py`:

```python
# -*- coding: utf-8 -*-
"""Acompanhamento: processos que a pessoa segue, onde eles estiverem.

REGRA PURA, SEM ROTA E SEM HTML. `app.py` só transporta — é o mesmo arranjo de
`busca.py`, `ingestao.py` e `poco.py`, e é o que torna esta suíte possível sem
subir servidor.

O QUE ESTE MÓDULO NÃO FAZ, E É DESENHO
--------------------------------------
Não escreve em `snapshot`, `processo` nem `poco_*`. Processo acompanhado não é
carteira: não soma indicador do painel e não entra em relatório. A fronteira que o
resto do sistema defende continua sendo a da carteira, e este módulo não abre porta
lateral nela — ver `_da_carteira`, que passa pelo MESMO recorte do painel.
"""
import json
import re

from banco import agora

# Teto por pessoa. Com o reaproveitamento da carteira, só o que está fora das
# mesas custa requisição ao SEI: ~3 por processo, ou ~300 no pior caso de uma
# lista cheia inteiramente de fora — contra as ~5.900 que a coleta de 1.182
# processos já faz. O teto existe para a lista não virar uma segunda coleta sem
# ninguém ter decidido isso.
TETO = 100

# Só dígitos e a pontuação que o SEI usa. Linha que não casa NÃO é descartada em
# silêncio: volta como recusada, com o texto que a pessoa colou. É o princípio de
# `filtros_recusados` em `pesquisa_sei.js` — entrada que não pegou muda o universo
# da resposta sem mudar uma linha do resultado.
_SO_NUMERO = re.compile(r"^[\d.\-/]+$")
_MIN_DIGITOS = 10


def normalizar(texto):
    """O que a pessoa colou -> protocolo, ou None se não é número de processo."""
    t = (texto or "").strip()
    if not t or not _SO_NUMERO.match(t):
        return None
    if sum(c.isdigit() for c in t) < _MIN_DIGITOS:
        return None
    return t
```

- [ ] **Passo 4: rodar e ver passar**

Rodar: `python teste_acompanhamento.py`
Esperado: `8 verificações OK, 0 falha(s)`

- [ ] **Passo 5: commit**

```bash
git add sei360/servidor/acompanhamento.py sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: normalizar o numero colado, e recusar o que nao e"
```

---

## Tarefa 3: adicionar, listar e remover — com teto

**Arquivos:**
- Modificar: `sei360/servidor/acompanhamento.py`
- Modificar: `sei360/servidor/teste_acompanhamento.py`

- [ ] **Passo 1: escrever o teste que falha**

```python
print("\n3. adicionar, listar, remover")
_cx = conectar()
_cx.execute("INSERT INTO usuarios(id,email,papel,criado_em,ativo) "
            "VALUES(7,'seguidora@teste.local','servidor',?,1)", (agora(),))
_cx.execute("INSERT INTO usuarios(id,email,papel,criado_em,ativo) "
            "VALUES(8,'outra@teste.local','servidor',?,1)", (agora(),))
_cx.commit()

_aceitos, _recusados = ac.adicionar(_cx, 7, "019.5120.2026.0161681-50", "SEI-SESAB")
checar("um número entra", _aceitos == ["019.5120.2026.0161681-50"] and not _recusados)

_aceitos, _recusados = ac.adicionar(
    _cx, 7, "019.9393.2026.0163871-16\nprocesso da Laisa\n019.2403.2024.0013423-96",
    "SEI-SESAB")
checar("lista de vários: as válidas entram", len(_aceitos) == 2, str(_aceitos))
checar("e a inválida volta com o texto que a pessoa colou",
       _recusados == ["processo da Laisa"], str(_recusados))

_aceitos, _ = ac.adicionar(_cx, 7, "019.5120.2026.0161681-50", "SEI-SESAB")
checar("repetido não duplica nem estoura", _aceitos == [], str(_aceitos))

_lista = ac.listar(_cx, 7)
checar(f"a lista tem os três ({len(_lista)})", len(_lista) == 3)
checar("todos nascem 'novo'", all(x["estado"] == "novo" for x in _lista))
checar("a lista é da PESSOA: a outra conta vê vazio", ac.listar(_cx, 8) == [])

ac.remover(_cx, 7, "SEI-SESAB", "019.5120.2026.0161681-50")
checar("remover tira da lista", len(ac.listar(_cx, 7)) == 2)

# O teto recusa com o número atual, em vez de descartar em silêncio.
_muitos = "\n".join(f"019.0000.2026.{i:07d}-11" for i in range(ac.TETO + 5))
_aceitos, _recusados = ac.adicionar(_cx, 7, _muitos, "SEI-SESAB")
checar(f"o teto de {ac.TETO} corta", len(ac.listar(_cx, 7)) == ac.TETO,
       str(len(ac.listar(_cx, 7))))
checar("e o que não caber volta como recusado, não some",
       len(_recusados) >= 5, str(len(_recusados)))
_cx.commit(); _cx.close()
```

- [ ] **Passo 2: rodar e ver falhar**

Rodar: `python teste_acompanhamento.py`
Esperado: `AttributeError: module 'acompanhamento' has no attribute 'adicionar'`

- [ ] **Passo 3: implementar**

Acrescentar em `acompanhamento.py`:

```python
def adicionar(cx, usuario_id, texto, instancia, origem="manual", nota=None):
    """Uma ou várias linhas -> (aceitos, recusados).

    `recusados` leva o texto ORIGINAL da linha, não a versão normalizada: quem
    colou precisa reconhecer o que não entrou para poder corrigir.
    """
    quantos = cx.execute(
        "SELECT COUNT(*) FROM acompanhado WHERE usuario_id=?", (usuario_id,)
    ).fetchone()[0]
    aceitos, recusados = [], []
    for linha in (texto or "").replace(",", "\n").splitlines():
        if not linha.strip():
            continue
        p = normalizar(linha)
        if not p:
            recusados.append(linha.strip())
            continue
        ja = cx.execute("""SELECT 1 FROM acompanhado
                           WHERE usuario_id=? AND instancia=? AND protocolo=?""",
                        (usuario_id, instancia, p)).fetchone()
        if ja:
            continue
        if quantos >= TETO:
            recusados.append(linha.strip())
            continue
        cx.execute("""INSERT INTO acompanhado(usuario_id,instancia,protocolo,origem,
                      nota,adicionado_em,estado) VALUES(?,?,?,?,?,?,'novo')""",
                   (usuario_id, instancia, p, origem, nota, agora()))
        quantos += 1
        aceitos.append(p)
    return aceitos, recusados


def remover(cx, usuario_id, instancia, protocolo):
    """Sai da lista, e o histórico sai com ela — foi a pessoa que desistiu."""
    cx.execute("""DELETE FROM acompanhado
                  WHERE usuario_id=? AND instancia=? AND protocolo=?""",
               (usuario_id, instancia, protocolo))
    cx.execute("""DELETE FROM acompanhado_leitura
                  WHERE usuario_id=? AND instancia=? AND protocolo=?""",
               (usuario_id, instancia, protocolo))


def listar(cx, usuario_id):
    """A lista da pessoa, cada item com a ÚLTIMA leitura já embutida.

    Uma consulta, não N+1: a tela mostra lista com ficha, e uma consulta por item
    transformaria 100 processos em 101 idas ao banco a cada abertura.
    """
    linhas = cx.execute("""
        SELECT a.*, l.lido_em AS leitura_em, l.fonte, l.medido_em, l.aberto_em,
               l.aberto_em_fonte, l.ultimo_movimento, l.documentos, l.movimentos,
               l.mudou
        FROM acompanhado a
        LEFT JOIN acompanhado_leitura l ON l.id = (
            SELECT id FROM acompanhado_leitura
            WHERE usuario_id=a.usuario_id AND instancia=a.instancia
              AND protocolo=a.protocolo
            ORDER BY id DESC LIMIT 1)
        WHERE a.usuario_id=?
        ORDER BY a.adicionado_em DESC""", (usuario_id,)).fetchall()
    saida = []
    for r in linhas:
        d = dict(r)
        for campo in ("aberto_em", "ultimo_movimento", "mudou"):
            d[campo] = json.loads(d[campo]) if d.get(campo) else None
        saida.append(d)
    return saida
```

- [ ] **Passo 4: rodar e ver passar**

Rodar: `python teste_acompanhamento.py`
Esperado: `18 verificações OK, 0 falha(s)`

- [ ] **Passo 5: commit**

```bash
git add sei360/servidor/acompanhamento.py sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: adicionar, listar e remover, com teto que recusa em voz alta"
```

---

## Tarefa 4: o delta — "o que mudou"

**Arquivos:**
- Modificar: `sei360/servidor/acompanhamento.py`
- Modificar: `sei360/servidor/teste_acompanhamento.py`

- [ ] **Passo 1: escrever o teste que falha**

```python
print("\n4. o delta")
_a = {"aberto_em": ["SESAB/DGESS"], "ultimo_movimento": {"dh": "01/08/2026 10:00"},
      "documentos": 10, "movimentos": 20}
_b = {"aberto_em": ["SESAB/CIR-IBOT"], "ultimo_movimento": {"dh": "09/09/2026 16:00"},
      "documentos": 12, "movimentos": 23}

checar("primeira leitura não tem delta", ac.delta(None, _b) is None)
checar("leitura igual não inventa mudança", ac.delta(_a, dict(_a)) is None)

_d = ac.delta(_a, _b)
checar("saiu de uma unidade e entrou em outra",
       _d["saiu_de"] == ["SESAB/DGESS"] and _d["entrou_em"] == ["SESAB/CIR-IBOT"], str(_d))
checar("documento novo é contado", _d["documentos"] == 2, str(_d))
checar("movimento novo é contado", _d["movimentos"] == 3, str(_d))
checar("o texto da tela sai do delta, não da mão",
       "CIR-IBOT" in ac.texto_do_delta(_d), ac.texto_do_delta(_d))

# A armadilha do desenho: trocar de fonte não é mudança NO PROCESSO.
_c = dict(_a); _c["fonte"] = "sei"
checar("mudar de fonte não aparece como mudança", ac.delta(_a, _c) is None)
```

- [ ] **Passo 2: rodar e ver falhar**

Rodar: `python teste_acompanhamento.py`
Esperado: `AttributeError: module 'acompanhamento' has no attribute 'delta'`

- [ ] **Passo 3: implementar**

Acrescentar em `acompanhamento.py`:

```python
# Os ÚNICOS quatro campos que o delta compara. `fonte` e `medido_em` ficam fora de
# propósito: trocar de "respondido pela carteira" para "lido no SEI" não é mudança
# NO PROCESSO, e apareceria como se fosse — exatamente o ruído que o selo de
# divergência árvore/andamento já produziu uma vez neste produto.
_COMPARADOS = ("aberto_em", "ultimo_movimento", "documentos", "movimentos")


def delta(anterior, atual):
    """O que mudou entre duas leituras. None quando nada mudou, e na primeira.

    None na PRIMEIRA leitura, nunca "mudou tudo": não há com o que comparar, e
    anunciar mudança onde não houve observação é a mesma falsidade do aviso de
    divergência que a auditoria de 10/09/2026 mediu como 100% falso positivo.
    """
    if not anterior:
        return None
    antes_un = set(anterior.get("aberto_em") or [])
    agora_un = set(atual.get("aberto_em") or [])
    d = {}
    if antes_un - agora_un:
        d["saiu_de"] = sorted(antes_un - agora_un)
    if agora_un - antes_un:
        d["entrou_em"] = sorted(agora_un - antes_un)
    mov_antes = (anterior.get("ultimo_movimento") or {}).get("dh")
    mov_agora = (atual.get("ultimo_movimento") or {}).get("dh")
    if mov_agora and mov_agora != mov_antes:
        d["movimentou_em"] = mov_agora
    for contagem in ("documentos", "movimentos"):
        a, b = anterior.get(contagem), atual.get(contagem)
        if a is not None and b is not None and b != a:
            d[contagem] = b - a
    return d or None


def texto_do_delta(d):
    """O delta em português. Gerado do dado — nunca escrito à mão na tela."""
    if not d:
        return ""
    partes = []
    if d.get("saiu_de"):
        partes.append("saiu de " + ", ".join(u.split("/")[-1] for u in d["saiu_de"]))
    if d.get("entrou_em"):
        partes.append("foi recebido em "
                      + ", ".join(u.split("/")[-1] for u in d["entrou_em"]))
    if d.get("documentos", 0) > 0:
        n = d["documentos"]
        partes.append(f"{n} documento(s) novo(s)")
    if not partes and d.get("movimentou_em"):
        partes.append(f"movimentou em {d['movimentou_em']}")
    return " · ".join(partes)
```

- [ ] **Passo 4: rodar e ver passar**

Rodar: `python teste_acompanhamento.py`
Esperado: `25 verificações OK, 0 falha(s)`

- [ ] **Passo 5: commit**

```bash
git add sei360/servidor/acompanhamento.py sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: o delta e o texto que sai dele"
```

---

## Tarefa 5: reaproveitar a carteira — e não furar a fronteira

**Arquivos:**
- Modificar: `sei360/servidor/acompanhamento.py`
- Modificar: `sei360/servidor/teste_acompanhamento.py`

Esta é a tarefa de maior risco do plano. O teste da fronteira (passo 1, último
`checar`) é o que impede o módulo de virar a porta lateral que contorna o recorte
por unidade que todo o resto do sistema respeita.

- [ ] **Passo 1: escrever o teste que falha**

```python
print("\n5. reaproveitar a carteira")
_cx = conectar()
# Uma coleta plausível: snapshot corrente de uma unidade, com dono, e um processo
# dentro. `medido_em` deliberadamente ANTIGO — é o caso real medido em 10/09/2026,
# em que as 12 unidades estavam com coleta de nove dias úteis antes.
_cx.execute("""INSERT INTO snapshot(id,unidade,coletado_em,estado,dono_usuario_id,
               instancia) VALUES(900,'SESAB/MINHA','2026-08-27T07:45:00-03:00',
               'corrente',7,'SEI-SESAB')""")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,ultimo_movimento,
               documentos,movimentos,medido_em,mesas_fonte)
               VALUES(900,'111','019.1111.2026.0000001-11',
               '{"dh":"20/08/2026 09:00","un":"SESAB/MINHA","de":"Processo recebido"}',
               9,14,'2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'111','SESAB/MINHA',NULL)""")
_cx.execute("INSERT INTO usuario_unidade(usuario_id,unidade,concedida_em) "
            "VALUES(7,'SESAB/MINHA',?)", (agora(),))
# A MESMA coleta, mas de unidade que a conta 7 NÃO alcança.
_cx.execute("""INSERT INTO snapshot(id,unidade,coletado_em,estado,dono_usuario_id,
               instancia) VALUES(901,'SESAB/ALHEIA','2026-08-27T07:45:00-03:00',
               'corrente',8,'SEI-SESAB')""")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,
               movimentos,medido_em,mesas_fonte)
               VALUES(901,'222','019.2222.2026.0000002-22',3,4,
               '2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(901,'222','SESAB/ALHEIA',NULL)""")
_cx.commit()

ac.adicionar(_cx, 7, "019.1111.2026.0000001-11", "SEI-SESAB")
ac.adicionar(_cx, 7, "019.2222.2026.0000002-22", "SEI-SESAB")
_cx.commit()

_n = ac.reaproveitar(_cx, 7, "SEI-SESAB")
_cx.commit()
checar("o processo da minha mesa é respondido pela carteira", _n == 1, str(_n))

_itens = {x["protocolo"]: x for x in ac.listar(_cx, 7)}
_meu = _itens["019.1111.2026.0000001-11"]
checar("e fica com estado lido", _meu["estado"] == "lido", str(_meu["estado"]))
checar("com a fonte dita", _meu["fonte"] == "carteira", str(_meu["fonte"]))
# A armadilha 2: a data é a da MEDIÇÃO, não a de agora.
checar("e com a data da COLETA, não a de agora",
       (_meu["medido_em"] or "").startswith("2026-08-27"), str(_meu["medido_em"]))
checar("as unidades abertas vieram da árvore",
       _meu["aberto_em"] == ["SESAB/MINHA"] and _meu["aberto_em_fonte"] == "arvore",
       str(_meu["aberto_em"]))

# O TESTE QUE MAIS IMPORTA: processo que existe no banco, mas em unidade fora do
# vínculo desta conta, NÃO é reaproveitado. Se este passar a falhar, o módulo
# virou porta lateral na fronteira do sistema.
_alheio = _itens["019.2222.2026.0000002-22"]
checar("processo de mesa ALHEIA não é reaproveitado",
       _alheio["estado"] == "novo" and _alheio["fonte"] is None,
       f"{_alheio['estado']} / {_alheio['fonte']}")
_cx.commit(); _cx.close()
```

- [ ] **Passo 2: rodar e ver falhar**

Rodar: `python teste_acompanhamento.py`
Esperado: `AttributeError: module 'acompanhamento' has no attribute 'reaproveitar'`

- [ ] **Passo 3: implementar**

Acrescentar em `acompanhamento.py`:

```python
def gravar_leitura(cx, usuario_id, instancia, protocolo, dados, fonte,
                   medido_em=None, estado="lido", id_sei=None):
    """Uma leitura, com o delta contra a anterior já calculado.

    O delta é calculado AQUI, no servidor, e nunca chega pronto de fora: a
    estação relata o que leu, não o que concluiu.
    """
    anterior = cx.execute("""SELECT aberto_em, ultimo_movimento, documentos, movimentos
                             FROM acompanhado_leitura
                             WHERE usuario_id=? AND instancia=? AND protocolo=?
                             ORDER BY id DESC LIMIT 1""",
                          (usuario_id, instancia, protocolo)).fetchone()
    prev = None
    if anterior:
        prev = {"aberto_em": json.loads(anterior["aberto_em"] or "null"),
                "ultimo_movimento": json.loads(anterior["ultimo_movimento"] or "null"),
                "documentos": anterior["documentos"],
                "movimentos": anterior["movimentos"]}
    d = delta(prev, dados)
    cx.execute("""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
                  lido_em,fonte,medido_em,aberto_em,aberto_em_fonte,
                  ultimo_movimento,documentos,movimentos,mudou)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
               (usuario_id, instancia, protocolo, agora(), fonte,
                medido_em or agora(),
                json.dumps(dados.get("aberto_em"), ensure_ascii=False),
                dados.get("aberto_em_fonte"),
                json.dumps(dados.get("ultimo_movimento"), ensure_ascii=False),
                dados.get("documentos"), dados.get("movimentos"),
                json.dumps(d, ensure_ascii=False) if d else None))
    cx.execute("""UPDATE acompanhado SET estado=?, lido_em=?,
                  id_sei=COALESCE(?, id_sei)
                  WHERE usuario_id=? AND instancia=? AND protocolo=?""",
               (estado, agora(), id_sei, usuario_id, instancia, protocolo))
    return d


def reaproveitar(cx, usuario_id, instancia):
    """Responde da CARTEIRA o que a carteira já sabe. Devolve quantos respondeu.

    A economia é a do poço, aplicada dentro de uma conta só — e aqui é integral,
    porque os quatro campos de que o módulo vive já estão guardados: as unidades
    da árvore em `processo_mesa`, e `ultimo_movimento`/`documentos`/`movimentos`
    em `processo`. Quem acompanha processo da própria carteira não gera nenhuma
    requisição ao SEI.

    A FRONTEIRA MORA AQUI. O recorte sai de `snapshots_de`, a MESMA função que o
    painel usa — nunca de um `SELECT` por protocolo em `processo`, que acharia a
    linha de qualquer unidade do banco, inclusive de mesa que esta conta não
    alcança. Sem isto o módulo seria a porta lateral que contorna a fronteira que
    o resto do sistema inteiro defende.
    """
    from app import snapshots_de, unidades_do

    pendentes = [r["protocolo"] for r in cx.execute(
        """SELECT protocolo FROM acompanhado
           WHERE usuario_id=? AND instancia=?
             AND (lido_em IS NULL OR substr(lido_em,1,10) <> substr(?,1,10))""",
        (usuario_id, instancia, agora()))]
    if not pendentes:
        return 0
    unidades = unidades_do(usuario_id)
    if not unidades:
        return 0
    escolhidos = snapshots_de(cx, usuario_id, unidades)
    ids = [sid for sid, _ in escolhidos.values()]
    if not ids:
        return 0
    marc_s = ",".join("?" * len(ids))
    marc_p = ",".join("?" * len(pendentes))
    linhas = cx.execute(f"""
        SELECT p.protocolo, p.id_sei, p.ultimo_movimento, p.documentos, p.movimentos,
               p.medido_em, p.mesas_fonte, s.coletado_em,
               (SELECT GROUP_CONCAT(m.mesa, char(31)) FROM processo_mesa m
                 WHERE m.snapshot_id=p.snapshot_id AND m.id_sei=p.id_sei) AS mesas
        FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
        WHERE p.snapshot_id IN ({marc_s}) AND p.protocolo IN ({marc_p})""",
        ids + pendentes).fetchall()
    feitos = 0
    for r in linhas:
        dados = {
            "aberto_em": sorted(set((r["mesas"] or "").split(chr(31))) - {""}),
            # `mesas_fonte` vem da coleta e pode ser 'andamento', que a medição de
            # 10/09/2026 mostrou errar em 100% dos 1.278 casos observáveis. Não se
            # relê por isso — seria uma requisição por dia para trocar dado velho
            # por dado novo do mesmo campo —, mas a tela marca como não confirmado.
            "aberto_em_fonte": r["mesas_fonte"] or "andamento",
            "ultimo_movimento": json.loads(r["ultimo_movimento"] or "null"),
            "documentos": r["documentos"], "movimentos": r["movimentos"],
        }
        gravar_leitura(cx, usuario_id, instancia, r["protocolo"], dados,
                       fonte="carteira",
                       medido_em=r["medido_em"] or r["coletado_em"],
                       id_sei=r["id_sei"])
        feitos += 1
    return feitos
```

- [ ] **Passo 4: rodar e ver passar**

Rodar: `python teste_acompanhamento.py`
Esperado: `31 verificações OK, 0 falha(s)`

- [ ] **Passo 5: commit**

```bash
git add sei360/servidor/acompanhamento.py sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: reaproveita a carteira pelo MESMO recorte do painel"
```

---

## Tarefa 6: a porta no menu

**Arquivos:**
- Modificar: `sei360/servidor/portas.py` (`_ICONES` e `PORTAS`)
- Modificar: `sei360/servidor/teste_acompanhamento.py`

- [ ] **Passo 1: escrever o teste que falha**

```python
print("\n6. a porta no menu")
import portas                                                    # noqa: E402

_ids = [p["id"] for p in portas.PORTAS]
checar("existe a porta de acompanhamento", "acompanhamento" in _ids, str(_ids))
checar("ela vem depois da busca e antes dos relatórios",
       _ids.index("busca") < _ids.index("acompanhamento") < _ids.index("relatorios"),
       str(_ids))
checar("todo papel logado a vê",
       all("acompanhamento" in [p["id"] for p in portas.visiveis(pap)]
           for pap in ("servidor", "gestor", "admin")))
checar("e ela tem ícone próprio", bool(portas._ICONES.get("acompanhamento")))
```

- [ ] **Passo 2: rodar e ver falhar**

Rodar: `python teste_acompanhamento.py`
Esperado: `FALHA existe a porta de acompanhamento`

- [ ] **Passo 3: implementar**

Em `sei360/servidor/portas.py`, acrescentar ao dicionário `_ICONES` (marcador — a
mesma família de traço dos existentes, sem `<svg>` em volta):

```python
    "acompanhamento": '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
```

E em `PORTAS`, entre a entrada de `busca` e a de `relatorios`:

```python
    # Terceira pergunta de quem abre o sistema, depois de "o que chegou na minha
    # mesa?" (painel) e "e o que NÃO chegou?" (busca): "e aquele processo que eu
    # não quero perder de vista, onde ele foi parar?". A carteira responde
    # enquanto o processo está na mesa; quando ele sai, o painel fica cego — e é
    # exatamente aí que alguém mais precisa de resposta.
    {"id": "acompanhamento", "rotulo": "Acompanhamento",
     "subtitulo": "Processos que você segue, onde estiverem",
     "url": "/acompanhamento", "papeis": None},
```

- [ ] **Passo 4: rodar e ver passar**

Rodar: `python teste_acompanhamento.py`
Esperado: `35 verificações OK, 0 falha(s)`

- [ ] **Passo 5: commit**

```bash
git add sei360/servidor/portas.py sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: a porta nova no menu"
```

---

## Tarefa 7: a tela e as rotas

**Arquivos:**
- Criar: `sei360/servidor/templates/acompanhamento.html`
- Modificar: `sei360/servidor/app.py` (depois da rota `/busca`, por volta da linha 3216)
- Modificar: `sei360/servidor/teste_acompanhamento.py`

- [ ] **Passo 1: escrever o teste que falha**

```python
print("\n7. a tela")
import app as A                                                  # noqa: E402
A.app.config["TESTING"] = True
_c = A.app.test_client()
_r = _c.get("/entrar")
_csrf = _r.headers["Set-Cookie"].split("sei360_csrf=")[1].split(";")[0]

# Sessão da conta 7, direto no banco: o caminho de login já tem suíte própria.
import secrets as _sec                                           # noqa: E402
import seguranca as _seg                                         # noqa: E402
_tok = _sec.token_urlsafe(32)
_cx = conectar()
_cx.execute("""INSERT INTO sessoes(usuario_id,token_sha256,criado_em,ultimo_uso_em,
               expira_em) VALUES(7,?,?,?,'2099-01-01T00:00:00-03:00')""",
            (_seg.hash_token(_tok), agora(), agora()))
_cx.commit(); _cx.close()
_c.set_cookie("sei360_sess", _tok)

_r = _c.get("/acompanhamento")
checar("a tela abre", _r.status_code == 200, str(_r.status_code))
_corpo = _r.data.decode("utf-8", "replace")
checar("lista o que a pessoa segue", "019.1111.2026.0000001-11" in _corpo)
checar("mostra a procedência do dado da carteira, não 'lido hoje'",
       "27/08" in _corpo, "a data da coleta tem de aparecer")
checar("NÃO mostra o processo de mesa alheia como lido",
       "019.2222.2026.0000002-22" in _corpo
       and "aguardando primeira leitura" in _corpo)

_r = _c.post("/acompanhamento/adicionar",
             data={"csrf": _csrf, "numeros": "019.7777.2026.0000007-77"})
checar("adicionar pela tela funciona", _r.status_code in (200, 302), str(_r.status_code))
checar("e o processo entrou", any(
    x["protocolo"] == "019.7777.2026.0000007-77" for x in ac.listar(conectar(), 7)))

_r = _c.post("/acompanhamento/remover",
             data={"csrf": _csrf, "protocolo": "019.7777.2026.0000007-77",
                   "instancia": "SEI-SESAB"})
checar("remover pela tela funciona", _r.status_code in (200, 302))
checar("e o processo saiu", not any(
    x["protocolo"] == "019.7777.2026.0000007-77" for x in ac.listar(conectar(), 7)))
```

- [ ] **Passo 2: rodar e ver falhar**

Rodar: `python teste_acompanhamento.py`
Esperado: `FALHA a tela abre  404`

- [ ] **Passo 3: escrever o template**

Criar `sei360/servidor/templates/acompanhamento.html`:

```html
<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEI360 — Acompanhamento</title>
{% include '_cabeca.html' %}
</head><body>

{% with pagina='acompanhamento' %}{% include '_nav.html' %}{% endwith %}

<div class="folha" style="max-width:1180px">
  <h1 style="font-family:var(--display);font-size:27px;margin:0 0 6px;font-weight:600">Acompanhamento</h1>
  <div style="color:var(--ink-2);margin-bottom:20px;max-width:74ch">
    Processos que você segue, <b>onde eles estiverem</b> — inclusive fora das suas mesas.
    O que já está na sua carteira é respondido pela própria coleta, sem ida ao SEI.
  </div>

  {% if recusados %}
  {# Linha que não é número volta com o texto ORIGINAL: quem colou precisa
     reconhecer o que não entrou para poder corrigir. #}
  <div class="destaque" style="border-left-color:var(--alerta);background:var(--alerta-soft)">
    <b>{{ recusados|length }} linha(s) não entraram</b> — não parecem número de processo:
    {% for t in recusados %}<code>{{ t }}</code>{% if not loop.last %}, {% endif %}{% endfor %}
  </div>
  {% endif %}

  <div class="cartao" style="margin-bottom:18px">
    <form method="post" action="/acompanhamento/adicionar">
      <input type="hidden" name="csrf" class="csrf">
      <label>Colar um número, ou vários (um por linha)</label>
      <textarea name="numeros" rows="3" style="width:100%;font-family:var(--mono);
        font-size:12px;padding:9px;border:1px solid var(--rule);border-radius:var(--r);
        background:var(--card);color:var(--ink)"
        placeholder="019.5120.2026.0161681-50"></textarea>
      <label style="margin-top:8px">Por que você está seguindo (opcional)</label>
      <input name="nota" placeholder="Repactuação HECC" style="width:100%">
      <div style="margin-top:10px"><button class="bt forte" type="submit">Acompanhar</button>
        <span style="color:var(--ink-3);font-size:12px;margin-left:8px">{{ itens|length }} de {{ teto }}</span></div>
    </form>
  </div>

  {% for x in itens %}
  <div class="cartao" style="margin-bottom:10px">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline">
      <span class="mono" style="font-size:13px">{{ x.protocolo }}</span>
      {% if x.mudou %}<span class="tag al">{{ x.texto_mudou }}</span>
      {% elif x.estado == 'novo' %}<span class="tag es">aguardando primeira leitura</span>
      {% elif x.estado == 'sem_acesso' %}<span class="tag al">sem acesso</span>
      {% elif x.estado == 'nao_encontrado' %}<span class="tag al">número não encontrado</span>
      {% else %}<span style="color:var(--ink-3);font-size:12px">sem mudança</span>{% endif %}
    </div>
    {% if x.nota %}<div style="color:var(--ink-2);font-size:13px;margin-top:3px">{{ x.nota }}</div>{% endif %}

    {% if x.estado == 'sem_acesso' %}
      <div style="color:var(--alerta);font-size:13px;margin-top:8px">
        O SEI não mostra este processo ao seu login. Nada foi lido.</div>
    {% elif x.estado == 'nao_encontrado' %}
      <div style="color:var(--alerta);font-size:13px;margin-top:8px">
        Número não encontrado nesta instalação do SEI — confira o dígito.</div>
    {% elif x.aberto_em %}
      <div style="font-size:13px;margin-top:8px">aberto em
        <b>{% for u in x.aberto_em %}{{ u.split('/')|last }}{% if not loop.last %}, {% endif %}{% endfor %}</b>
        {% if x.aberto_em_fonte != 'arvore' %}
        <span class="tag es" title="as unidades foram derivadas do andamento, não da árvore do SEI">não confirmado pela árvore</span>
        {% endif %}
      </div>
      {% if x.ultimo_movimento %}
      <div style="color:var(--ink-2);font-size:13px">{{ x.ultimo_movimento.dh }} ·
        {{ x.ultimo_movimento.de }}</div>
      {% endif %}
    {% endif %}

    {# PROCEDÊNCIA, sempre: dado da carteira pode ser de dias atrás, e dizer
       "lido hoje" sobre ele seria mentir no carimbo. #}
    {% if x.fonte %}
    <div style="color:var(--ink-3);font-size:11.5px;margin-top:6px">
      {% if x.fonte == 'carteira' %}pela sua coleta de {{ x.medido_em[8:10] }}/{{ x.medido_em[5:7] }}
      {% else %}lido no SEI em {{ x.leitura_em[8:10] }}/{{ x.leitura_em[5:7] }}{% endif %}
    </div>
    {% endif %}

    <form method="post" action="/acompanhamento/remover" style="margin-top:8px">
      <input type="hidden" name="csrf" class="csrf">
      <input type="hidden" name="protocolo" value="{{ x.protocolo }}">
      <input type="hidden" name="instancia" value="{{ x.instancia }}">
      <button class="bt" type="submit">Parar de acompanhar</button>
    </form>
  </div>
  {% else %}
  <div class="vazio-msg">Nenhum processo acompanhado ainda. Cole um número acima.</div>
  {% endfor %}
</div>

<script>
const c=(document.cookie.match(/sei360_csrf=([^;]+)/)||[])[1]||'';
document.querySelectorAll('.csrf').forEach(i=>i.value=c);
</script>
</body></html>
```

- [ ] **Passo 4: escrever as rotas**

Em `sei360/servidor/app.py`, depois da rota `@app.get("/busca")`:

```python
@app.get("/acompanhamento")
@exige_login
def acompanhamento_tela(recusados=None):
    import acompanhamento as acmod
    u = request.usuario
    cx = conectar()
    # A carteira responde ANTES de a tela pintar: é de graça, e evita a tela
    # dizer "aguardando primeira leitura" sobre processo que a coleta já leu.
    inst = cfgmod.ler(cx, u["usuario_id"])["sistema"] or "SEI-SESAB"
    acmod.reaproveitar(cx, u["usuario_id"], inst)
    itens = acmod.listar(cx, u["usuario_id"])
    for x in itens:
        x["texto_mudou"] = acmod.texto_do_delta(x.get("mudou"))
    registrar(cx, u["usuario_id"], "ver_acompanhamento",
              alvo=f"{len(itens)} processo(s)", ip=ip_cliente())
    cx.commit(); cx.close()
    resp = make_response(render_template("acompanhamento.html", u=u, itens=itens,
                                         teto=acmod.TETO, recusados=recusados or []))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax",
                    secure=cookie_seguro(), path="/")
    return resp


@app.post("/acompanhamento/adicionar")
@exige_login
def acompanhamento_adicionar():
    import acompanhamento as acmod
    confere_csrf()
    u = request.usuario
    cx = conectar()
    inst = cfgmod.ler(cx, u["usuario_id"])["sistema"] or "SEI-SESAB"
    aceitos, recusados = acmod.adicionar(
        cx, u["usuario_id"], request.form.get("numeros"), inst,
        nota=(request.form.get("nota") or "").strip() or None)
    registrar(cx, u["usuario_id"], "acompanhar",
              alvo=f"+{len(aceitos)} -{len(recusados)}", ip=ip_cliente())
    cx.commit(); cx.close()
    # As recusadas voltam RENDERIZADAS, não por query string: o texto é o que a
    # pessoa colou, e pode citar nome — e a URL vai para o log do gunicorn.
    return acompanhamento_tela(recusados=recusados)


@app.post("/acompanhamento/remover")
@exige_login
def acompanhamento_remover():
    import acompanhamento as acmod
    confere_csrf()
    u = request.usuario
    cx = conectar()
    acmod.remover(cx, u["usuario_id"], request.form.get("instancia") or "SEI-SESAB",
                  request.form.get("protocolo") or "")
    registrar(cx, u["usuario_id"], "parar_acompanhar",
              alvo=request.form.get("protocolo"), ip=ip_cliente())
    cx.commit(); cx.close()
    return redirect(url_for("acompanhamento_tela"))
```

- [ ] **Passo 5: rodar e ver passar**

Rodar: `python teste_acompanhamento.py`
Esperado: `42 verificações OK, 0 falha(s)`

- [ ] **Passo 5-bis: provar que o módulo NÃO invadiu a carteira**

Acrescentar em `teste_acompanhamento.py` (é a checagem 9 da seção 8 do desenho — a
que prova que "não entra na carteira" é verdade e não intenção):

```python
print("
7-bis. o módulo não invadiu a carteira")
import relatorios as _rel                                        # noqa: E402
_cx = conectar()
_uns7 = A.unidades_do(7)
_cart = A.carteira(_uns7, 7)
checar("processo acompanhado de FORA não entra na carteira",
       not any(x.get("protocolo") == "019.2222.2026.0000002-22" for x in _cart),
       "o modulo virou carteira")
_dados_rel = _rel.carregar(_uns7, 7)
checar("nem em relatorios.carregar()",
       not any(d["protocolo"] == "019.2222.2026.0000002-22" for d in _dados_rel))
checar("e a carteira continua trazendo o que é dela",
       any(x.get("protocolo") == "019.1111.2026.0000001-11" for x in _cart))
# Checagem 13 do desenho: processo que SAI da mesa volta para a fila do agente.
_cx.execute("UPDATE snapshot SET estado='expirado' WHERE id=900")
_cx.execute("""UPDATE acompanhado SET lido_em=NULL, estado='novo'
               WHERE protocolo='019.1111.2026.0000001-11'""")
_cx.commit()
checar("processo que saiu da mesa volta para a fila do agente",
       "019.1111.2026.0000001-11" in ac.pendentes(_cx, 7, "SEI-SESAB"))
_cx.execute("UPDATE snapshot SET estado='corrente' WHERE id=900")
_cx.commit(); _cx.close()
```

Rodar: `python teste_acompanhamento.py`
Esperado: `46 verificações OK, 0 falha(s)`

> Esta checagem usa `ac.pendentes`, que só existe a partir da tarefa 8. Se estiver
> executando em ordem, mova as três primeiras linhas para cá e a última para o fim
> da tarefa 8 — ou rode este passo depois dela.

- [ ] **Passo 6: conferir que o resto não quebrou**

```bash
python teste_deploy_novo.py
python conferir_contexto.py
```
Esperado: `42 verificações OK, 0 falha(s)` no primeiro e `ok: entra o que o build precisa`
no segundo. O contexto sobe de 87 para 89 arquivos (o módulo e o template).

- [ ] **Passo 7: commit**

```bash
git add sei360/servidor/app.py sei360/servidor/templates/acompanhamento.html \
        sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: a tela, com procedencia em cada linha"
```

**PARE AQUI.** Fase 1 completa: o módulo funciona para processo da carteira. Verifique
na tela antes de seguir para a fase 2.

---

# Fase 2 — leitura pelo agente, para o que está fora da mesa

## Tarefa 8: os endpoints do agente

**Arquivos:**
- Modificar: `sei360/servidor/acompanhamento.py`
- Modificar: `sei360/servidor/app.py` (junto dos outros `/api/agente/*`, ~linha 3262)
- Modificar: `sei360/servidor/teste_acompanhamento.py`

- [ ] **Passo 1: escrever o teste que falha**

```python
print("\n8. o agente")
_cx = conectar()
_cx.execute("DELETE FROM agentes")
_cx.execute("""INSERT INTO agentes(nome_estacao,dono_usuario_id,ativo,token_sha256,
               ultimo_contato_em) VALUES('ESTACAO-7',7,1,X'A7',?)""", (agora(),))
_cx.commit(); _cx.close()

_pend = ac.pendentes(conectar(), 7, "SEI-SESAB")
checar("o de mesa alheia está pendente de leitura no SEI",
       "019.2222.2026.0000002-22" in _pend, str(_pend))
checar("o da minha carteira NÃO está — já foi respondido de graça",
       "019.1111.2026.0000001-11" not in _pend, str(_pend))

_cx = conectar()
_n = ac.receber(_cx, 7, {"instancia": "SEI-SESAB", "leituras": [
    {"protocolo": "019.2222.2026.0000002-22", "id_sei": "222",
     "aberto_em": ["SESAB/ALHEIA"], "aberto_em_fonte": "arvore",
     "ultimo_movimento": {"dh": "01/09/2026 10:00", "un": "SESAB/ALHEIA",
                          "de": "Processo recebido na unidade"},
     "documentos": 3, "movimentos": 4}]})
_cx.commit()
checar("a leitura da estação é aceita", _n == 1, str(_n))
_it = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.2222.2026.0000002-22"]
checar("com fonte 'sei'", _it["fonte"] == "sei", str(_it["fonte"]))
checar("e estado lido", _it["estado"] == "lido")

_n = ac.receber(_cx, 7, {"instancia": "SEI-SESAB", "leituras": [
    {"protocolo": "019.2222.2026.0000002-22", "estado": "sem_acesso"}]})
_cx.commit()
_it = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.2222.2026.0000002-22"]
checar("recusa do SEI vira estado próprio, não ficha vazia",
       _it["estado"] == "sem_acesso", str(_it["estado"]))
_cx.close()
```

- [ ] **Passo 2: rodar e ver falhar**

Rodar: `python teste_acompanhamento.py`
Esperado: `AttributeError: module 'acompanhamento' has no attribute 'pendentes'`

- [ ] **Passo 3: implementar a regra**

Acrescentar em `acompanhamento.py`:

```python
def pendentes(cx, usuario_id, instancia):
    """O que a estação precisa ler: não lido hoje, e que a carteira não respondeu.

    Chama `reaproveitar` primeiro de propósito. Sem isso a estação leria no SEI
    processo que a coleta já trouxe de graça — e a economia do desenho existiria
    só no papel.
    """
    reaproveitar(cx, usuario_id, instancia)
    return [r["protocolo"] for r in cx.execute(
        """SELECT protocolo FROM acompanhado
           WHERE usuario_id=? AND instancia=?
             AND (lido_em IS NULL OR substr(lido_em,1,10) <> substr(?,1,10))
           ORDER BY estado='novo' DESC, adicionado_em
           LIMIT ?""", (usuario_id, instancia, agora(), TETO))]


# O `exit`/estado que a estação relata quando o SEI recusou ou não achou. Traduzido
# aqui, e não na estação: a estação relata o que viu; o significado é do servidor.
_ESTADOS_ACEITOS = ("lido", "sem_acesso", "nao_encontrado")


def receber(cx, usuario_id, envelope):
    """Leituras vindas da estação. Devolve quantas foram gravadas.

    O `usuario_id` vem do DONO DO AGENTE autenticado, nunca do envelope: aceitar
    o dono de dentro do corpo deixaria um agente escrever na lista de outra conta.
    """
    inst = envelope.get("instancia") or "SEI-SESAB"
    n = 0
    for leitura in envelope.get("leituras") or []:
        p = normalizar(leitura.get("protocolo") or "")
        if not p:
            continue
        # Só o que ESTÁ na lista desta conta. Protocolo que a pessoa não segue não
        # entra por relato de estação.
        seguido = cx.execute("""SELECT 1 FROM acompanhado
                                WHERE usuario_id=? AND instancia=? AND protocolo=?""",
                             (usuario_id, inst, p)).fetchone()
        if not seguido:
            continue
        estado = leitura.get("estado") or "lido"
        if estado not in _ESTADOS_ACEITOS:
            estado = "lido"
        if estado != "lido":
            cx.execute("""UPDATE acompanhado SET estado=?, lido_em=?
                          WHERE usuario_id=? AND instancia=? AND protocolo=?""",
                       (estado, agora(), usuario_id, inst, p))
            n += 1
            continue
        gravar_leitura(cx, usuario_id, inst, p, leitura, fonte="sei",
                       medido_em=agora(), id_sei=leitura.get("id_sei"))
        n += 1
    return n
```

- [ ] **Passo 4: escrever os endpoints**

Em `sei360/servidor/app.py`, junto dos outros `/api/agente/*`:

```python
@app.get("/api/agente/acompanhamento")
def agente_acompanhamento():
    """Os processos acompanhados que a carteira não respondeu. Mesmo contrato da busca."""
    import acompanhamento as acmod
    ag, erro = agente_autenticado()
    if not ag:
        return jsonify(erro=erro), 401
    if not ag["dono_usuario_id"]:
        return jsonify(ler=False, motivo="agente sem dono não tem credencial do SEI")
    cx = conectar()
    inst = cfgmod.ler(cx, ag["dono_usuario_id"])["sistema"] or "SEI-SESAB"
    lista = acmod.pendentes(cx, ag["dono_usuario_id"], inst)
    cx.commit(); cx.close()
    if not lista:
        return jsonify(ler=False, motivo="nada acompanhado fora da carteira")
    return jsonify(ler=True, instancia=inst, protocolos=lista,
                   perfil=perfil_sei.envelope_do_coletor(inst))


@app.post("/api/agente/acompanhamento")
def agente_acompanhamento_resultado():
    import acompanhamento as acmod
    ag, erro = agente_autenticado()
    if not ag:
        return jsonify(erro=erro), 401
    if not ag["dono_usuario_id"]:
        return jsonify(erro="agente sem dono"), 400
    cx = conectar()
    # O DONO SAI DO AGENTE, não do envelope: aceitar o dono de dentro do corpo
    # deixaria um agente escrever na lista de outra conta.
    n = acmod.receber(cx, ag["dono_usuario_id"], request.get_json(silent=True) or {})
    cx.commit(); cx.close()
    return jsonify(gravadas=n)
```

- [ ] **Passo 5: rodar e ver passar**

Rodar: `python teste_acompanhamento.py`
Esperado: `48 verificações OK, 0 falha(s)`

- [ ] **Passo 6: commit**

```bash
git add sei360/servidor/acompanhamento.py sei360/servidor/app.py \
        sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: endpoints do agente, com o dono saindo do token"
```

---

## Tarefa 9: a leitura reduzida na estação

**Arquivos:**
- Modificar: `painel_sesab/automacao_sei.js` (função nova, no fim, antes do
  `window.SEIAutomacao = ...`)
- Modificar: `painel_sesab/coleta.py` (modo `--acompanhar`)
- Testar: `painel_sesab/_teste_acompanhar.js` (criar), rodado por `node`

A leitura é **reduzida**: página do processo, árvore e histórico. Cerca de 3
requisições. **Não chame `daMesa()`** — os cinco campos de custódia são derivados
para uma mesa, e um processo fora das mesas não tem mesa para a qual derivá-los.

- [ ] **Passo 1: escrever a função na estação**

As funções que esta leitura compõe **já existem** em `automacao_sei.js`; nenhuma
precisa ser escrita. Verificado no arquivo em 11/09/2026:

| Função | Linha | O que faz |
|---|---|---|
| `urlHistorico(href)` | 930 | Duas requisições: a página do processo e o iframe da árvore. Devolve `{url, arvore, acoes}` e **lança** `'sem arvore'` / `'sem historico'` |
| `pegar(url)` | 280 | Uma requisição, com a sessão do próprio navegador |
| `derivar(doc, arvore)` | 836 | O registro inteiro, já com `mesas` (da árvore), `mesas_fonte`, `ultimo_movimento`, `movimentos` e `documentos` (contagem de nós da árvore, linha 894) |
| `SEIBusca.rodar(...)` | `pesquisa_sei.js` | A pesquisa por número, que devolve o link do processo |

São três requisições por processo, e a função nova é composição — não reimplementa
leitura nenhuma:

```js
/* ACOMPANHAMENTO — ler UM processo por número, fora de qualquer mesa.

   `derivar()` é reaproveitado inteiro e o resultado é FILTRADO: só quatro campos
   sobem. Os cinco de custódia que ele também calcula (`marco_unidade`,
   `recebimento`, `recebimento_por`, `envio`, `unidade_envio`) saem de
   `camposDaMesa(mov, UNIDADE)` — derivados para a mesa em que a estação está
   parada, que NÃO é a mesa deste processo. Mandá-los ao servidor seria mandar o
   dado de outra mesa com o nome deste processo. Por isso a lista de campos aqui é
   explícita, e não um espalhamento do objeto.

   Três estados de saída, e nenhum silencioso: 'lido', 'sem_acesso' (o SEI recusou
   a este login — é o que os `throw` de `urlHistorico` significam aqui) e
   'nao_encontrado' (a pesquisa por número não devolveu linha). Ficha vazia com
   cara de "processo sem novidade" seria pior que os três. */
async function acompanhar(protocolo) {
  let achados;
  try {
    achados = await SEIBusca.rodar({ filtros: { numero_sei: protocolo },
                                     paginas_teto: 1 });
  } catch (e) {
    return { protocolo, estado: 'nao_encontrado' };
  }
  const item = (achados.itens || [])[0];
  if (!item || !item.link) return { protocolo, estado: 'nao_encontrado' };
  let url, arvore;
  try {
    ({ url, arvore } = await urlHistorico(item.link));
  } catch (e) {
    // 'sem arvore' e 'sem historico': o SEI devolveu a página sem o conteúdo que
    // só aparece para quem pode ver o processo.
    return { protocolo, estado: 'sem_acesso' };
  }
  const doc = new DOMParser().parseFromString(await pegar(url), 'text/html');
  const d = derivar(doc, arvore);
  return {
    protocolo, estado: 'lido', id_sei: item.id_sei || null,
    aberto_em: (d.mesas || []).map(x => x.unidade),
    aberto_em_fonte: d.mesas_fonte || 'andamento',
    ultimo_movimento: d.ultimo_movimento || null,
    documentos: d.documentos, movimentos: d.movimentos,
  };
}
```

- [ ] **Passo 2: expor no envelope**

No fim de `automacao_sei.js`, acrescentar `acompanhar` ao objeto exportado:

```js
window.SEIAutomacao = { /* ...o que já está aqui... */, acompanhar };
```

- [ ] **Passo 3: modo `--acompanhar` no coletor**

Em `painel_sesab/coleta.py`, espelhando o modo `--buscar` que já existe: lê o pedido
de `stdin` (`{"acompanhamento": {"instancia", "protocolos"}, "perfil": {...}}`),
abre o SEI pelo perfil, chama `SEIAutomacao.acompanhar` para cada protocolo em série
(nunca em paralelo — o SEI derruba sessão sob rajada) e imprime uma linha
`ACOMP_OK {json}` com `{"instancia": ..., "leituras": [...]}`.

- [ ] **Passo 4: conferir o JS**

Rodar: `cd painel_sesab && python ../sei360/servidor/conferir_js.py`
Esperado: nenhum erro de sintaxe.

- [ ] **Passo 5: commit**

```bash
git add painel_sesab/automacao_sei.js painel_sesab/coleta.py
git commit -m "Acompanhamento: leitura reduzida de um processo por numero"
```

---

## Tarefa 10: o ciclo do agente, e o expurgo

**Arquivos:**
- Modificar: `sei360/agente/sei360_agente.py`
- Modificar: `sei360/servidor/expurgo.py`
- Modificar: `sei360/servidor/teste_acompanhamento.py`

- [ ] **Passo 1: o ciclo na estação**

Em `sei360/agente/sei360_agente.py`, uma função nova espelhando `buscar(cfg)`
(linha 225), chamada no mesmo ciclo, **depois** de `buscar` e **antes** da coleta —
acompanhamento é lista curta e alguém pode estar olhando; coleta de 13 minutos na
frente dela transformaria "acompanhar" em "acompanhar amanhã":

```python
def acompanhar(cfg):
    """Os processos acompanhados fora da carteira, se houver algum."""
    s, tarefa = chamar(cfg, "/api/agente/acompanhamento", metodo="GET")
    if s != 200 or not tarefa.get("ler"):
        return False
    print(f"acompanhamento: {len(tarefa['protocolos'])} processo(s)")
    pedido = {"acompanhamento": {k: tarefa.get(k)
                                 for k in ("instancia", "protocolos")},
              "perfil": tarefa.get("perfil") or {}}
    envelope = _rodar_coletor(pedido, "--acompanhar", "ACOMP_OK ", teto=600)
    if envelope is None:
        envelope = {"instancia": tarefa.get("instancia"), "leituras": []}
    s, r = chamar(cfg, "/api/agente/acompanhamento", envelope, timeout=120)
    print(f"  servidor gravou {r.get('gravadas')}")
    return True
```

`_rodar_coletor` é a extração do corpo de `buscar()` (o `Popen`, a leitura de
`stdout` até a linha-marca, o teto de relógio e o `exit 5` sintético). Extraia
primeiro, num commit próprio, provando que `buscar()` continua idêntico — é o
padrão que a casa já usa e duplicá-lo faria as duas cópias divergirem.

- [ ] **Passo 2: o expurgo**

Em `sei360/servidor/expurgo.py`, acrescentar ao dicionário `DIAS`:

```python
    # A série de leituras do acompanhamento: 180 dias. Ela É o valor do módulo —
    # é a única série temporal do produto — e não carrega texto livre além do
    # `ultimo_movimento` que `processo` já guarda. A LISTA (`acompanhado`) não
    # expira: é escolha da pessoa, e apagá-la por idade seria decidir por ela.
    "acompanhado_leitura": 180,
```

E a limpeza correspondente, junto das outras:

```python
    alvo_acomp = cx.execute(
        "SELECT COUNT(*) FROM acompanhado_leitura WHERE lido_em < ?",
        (_corte(DIAS["acompanhado_leitura"]),)).fetchone()[0]
    if alvo_acomp:
        plano.append(("acompanhado_leitura", alvo_acomp, "série de leituras antiga"))
        if not simular:
            cx.execute("DELETE FROM acompanhado_leitura WHERE lido_em < ?",
                       (_corte(DIAS["acompanhado_leitura"]),))
```

- [ ] **Passo 3: o teste do expurgo**

```python
print("\n10. expurgo")
import expurgo                                                   # noqa: E402
_cx = conectar()
_cx.execute("""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
               lido_em,fonte) VALUES(7,'SEI-SESAB','019.1111.2026.0000001-11',
               '2020-01-01T00:00:00-03:00','sei')""")
_cx.commit(); _cx.close()
_plano = expurgo.expurgar(simular=True)
checar("o expurgo conhece a série de leituras",
       any(t == "acompanhado_leitura" for t, _, _ in _plano), str(_plano))
expurgo.expurgar()
_cx = conectar()
_velhas = _cx.execute("SELECT COUNT(*) FROM acompanhado_leitura "
                      "WHERE lido_em < '2021-01-01'").fetchone()[0]
_cx.close()
checar("leitura velha sai", _velhas == 0, str(_velhas))
checar("e a LISTA não é apagada por idade", len(ac.listar(conectar(), 7)) > 0)
```

- [ ] **Passo 4: rodar tudo**

```bash
python teste_acompanhamento.py
python teste_deploy_novo.py
python teste_busca.py
python conferir_contexto.py
```
Esperado: todas verdes; `teste_acompanhamento.py` com `51 verificações OK`.

- [ ] **Passo 5: commit**

```bash
git add sei360/agente/sei360_agente.py sei360/servidor/expurgo.py \
        sei360/servidor/teste_acompanhamento.py
git commit -m "Acompanhamento: ciclo do agente e retencao da serie"
```

---

## Depois do plano

- Atualizar `sei360/SPECS.md` com a seção do módulo (o arquivo é a especificação do
  produto, por seções numeradas — o módulo é uma seção nova, não um parágrafo solto).
- Atualizar `sei360/ARQUITETURA_ACESSO.md` com os dois endpoints novos do agente.
- A importação do Acompanhamento Especial do SEI (seção 10 do desenho) é plano
  próprio: é a única parte que precisa de tela nova do SEI e sai por último.
