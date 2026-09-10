# -*- coding: utf-8 -*-
"""
Relatórios — só o que o dado sustenta.

A REGRA QUE GOVERNA ESTE ARQUIVO
--------------------------------
Todo relatório declara a COBERTURA dos campos que usa, medida na hora. Um gráfico
de "processos por marcador" parece verdade e é construído sobre 53% da base: os
47% sem marcador não somem do mundo, somem do gráfico. Quem leva esse número para
uma reunião defende um recorte sem saber que é recorte.

Por isso cada relatório carrega três coisas na própria tela:
  * a cobertura de cada campo que ele usa (medida, não estimada)
  * a idade do dado POR UNIDADE, e um aviso quando há unidade atrasada
  * o total que ficou de fora, nomeado — "sem atribuição: 202", não silêncio

E há relatórios que este módulo se RECUSA a oferecer. Medido em 19/08/2026 sobre
1.165 processos: `retorno` tem 1 registro (0%), `anexados` 7 (1%), `hipotese_legal`
62 (5%), `envio`/`unidade_envio` 317 (27%). Relatório sobre esses campos não seria
análise, seria ficção com aparência de planilha.
"""
import json
import re
import statistics
import unicodedata
from datetime import datetime

from banco import TZ, conectar
import janelas

# Cobertura abaixo disto = o relatório sai com tarja, não escondido. Esconder
# faria a pessoa procurar; a tarja faz ela entender.
COBERTURA_FRACA = 0.80
# Abaixo disto o relatório nem é oferecido: o dado não sustenta a pergunta.
COBERTURA_INVIAVEL = 0.30


_BR = re.compile(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}):(\d{2}))?")


def quando_br(data_br):
    """'DD/MM/AAAA HH:MM' -> datetime local ingênuo. None se não parsear.

    A HORA IMPORTA, e foi ela o defeito. A versão anterior fazia
    `strptime(str(data_br)[:10], "%d/%m/%Y")` e jogava a hora fora. O painel, no
    mesmo dado, faz `new Date(a, m-1, d, H, M)` (templates/painel.html:843) e
    conta o intervalo inteiro. Resultado medido em 21/08/2026, 1.165 processos:
    o relatório dizia "parados +90 dias: 526" e o painel dizia 432 — 94
    processos, +21,8%, nas duas telas do mesmo sistema no mesmo segundo. Todos
    com marco em 19/05/2026: 91 dias truncando para data, 90 contando o
    intervalo.

    Ingênuo, e não com fuso, DE PROPÓSITO: é o que o painel faz. `emMsISO`
    (painel.html:858) lê o ISO com o regex e monta um Date local, descartando o
    offset. Como os dois lados vêm do mesmo banco, com o mesmo offset, descartar
    dos dois é equivalente — e é a única forma de as duas contas coincidirem
    linha a linha.
    """
    if not data_br:
        return None
    m = _BR.search(str(data_br))
    if not m:
        return None
    try:
        return datetime(int(m[3]), int(m[2]), int(m[1]),
                        int(m[4] or 0), int(m[5] or 0))
    except ValueError:                       # 31/02, 99/99 — o SEI já mandou
        return None


def _dias(data_br, referencia=None):
    """'DD/MM/AAAA HH:MM' -> dias decorridos até a REFERÊNCIA.

    A referência é a régua da LINHA, não o relógio. Contar contra `now()` faz o
    mesmo relatório, sobre o mesmo dado, devolver números diferentes a cada dia:
    medido aqui, "parados +90 dias" saiu 531 hoje e 526 ontem, com a coleta
    parada em 18/08 — 28 processos trocaram de faixa sem nada ter acontecido no
    SEI. Relatório que anda sozinho não se defende em reunião nenhuma.

    FLOOR sobre o INTERVALO, não diferença de calendário. `(ref.date() - d.date()).days`
    conta viradas de meia-noite: um processo que chegou ontem às 23h e é medido
    hoje às 8h "está há 1 dia na unidade" tendo 9 horas de casa. O painel sempre
    contou o intervalo; era o relatório que contava calendário. FLOOR e nunca
    round porque com round a tela dizia 31 e a planilha 30 para o mesmo processo,
    na mesma entrega.
    """
    d = quando_br(data_br)
    if d is None:
        return None
    ref = referencia or datetime.now(TZ).replace(tzinfo=None)
    return int((ref - d).total_seconds() // 86400)


FAIXAS = [(0, 7, "até 7 dias"), (8, 30, "8 a 30 dias"), (31, 90, "31 a 90 dias"),
          (91, 180, "91 a 180 dias"), (181, 10**6, "mais de 180 dias")]


def faixa_de(n):
    if n is None:
        return "sem data"
    for ini, fim, rot in FAIXAS:
        if ini <= n <= fim:
            return rot
    return "sem data"


# AS COLUNAS QUE ESTE MÓDULO LÊ, uma a uma. Antes era `p.*` mais dois LEFT JOIN
# (`processo_texto` e `resumo`) cujas cinco colunas não são lidas em lugar nenhum
# — nem aqui, nem nos templates. Medido: 11,8 ms contra 3,6 ms, 3,3x, em TODA
# requisição de relatório, mais 186 KB de colunas de `processo` e 137 KB de texto
# livre (`especificacao`, `anotacao`, `acompanhamento`) atravessando o processo
# à toa. Texto livre do SEI pode citar nome próprio: trazer o que não se usa é
# custo e superfície de exposição pelo mesmo preço.
#
# `p.*` também era o que fazia o JOIN de `resumo` casar só por `id_sei`, sem
# `instancia` — e `id_sei` é sequência POR INSTALAÇÃO (banco.py). Sem o JOIN, o
# problema deixa de existir; se um relatório futuro precisar do resumo, o JOIN
# volta COM `instancia` e com nome.
COLUNAS = [
    # `especificacao` e o TITULO que a pessoa reconhece — "PACTUACAO LINHA DE
    # CUIDADO HTLV", nao "019.2403.2024.0013423-96". Ficou fora por anos e o
    # efeito so apareceu quando a planilha passou a listar processo a processo:
    # uma coluna de numeros de 25 digitos que ninguem consegue ler.
    "id_sei", "snapshot_id", "protocolo", "especificacao", "tipo_processo", "atribuido_nome",
    "atribuido_login", "marco_unidade", "visualizado", "doc_incluido",
    "marcador", "assuntos", "origem", "gerador_unidade", "nivel_acesso",
    "mesas_divergem", "documentos", "movimentos", "ultimo_movimento", "medido_em",
    # `instancia` NÃO está aqui: ela é coluna de `snapshot`, não de `processo` —
    # e é de lá que o SELECT a traz, para entrar na CHAVE da dedup.
    # As cinco de baixo NÃO alimentam relatório nenhum: alimentam a lista dos
    # INVIÁVEIS, que passou a MEDIR a cobertura em vez de trazer o número escrito
    # à mão. Sem elas, a tela voltaria a afirmar "62 processos em 1.165" para
    # sempre, mesmo depois de o SEI passar a preencher o campo.
    "retorno", "anexados", "hipotese_legal", "unidade_envio", "urgente",
]
COLUNAS_SQL = ", ".join(f"p.{c}" for c in COLUNAS)


def carregar(unidades, usuario_id=None):
    """Processos correntes DESTA pessoa, deduplicados por id_sei.

    A fronteira é aplicada AQUI, no SQL. Relatório que filtra no navegador não
    filtra nada: o dado já saiu.

    Duas camadas, as mesmas do painel: a unidade (o que eu alcanço) e o DONO da
    coleta (de quem é este dado). Usa a MESMA função de recorte que o painel — se
    os dois lessem por regras diferentes, o total do relatório divergiria do total
    do painel na mesma tela do mesmo sistema, e quem apresenta descobriria isso
    numa reunião.
    """
    if not unidades:
        return []
    cx = conectar()
    from app import snapshots_de
    escolhidos = snapshots_de(cx, usuario_id, unidades)
    ids = [sid for sid, _ in escolhidos.values()]
    if not ids:
        cx.close()
        return []
    marc = ",".join("?" * len(ids))
    unidades = ids          # daqui para baixo o recorte é por snapshot
    linhas = cx.execute(f"""
        SELECT {COLUNAS_SQL}, s.unidade AS snap_unidade, s.coletado_em,
               s.instancia
        FROM processo p
        JOIN snapshot s ON s.id = p.snapshot_id
        WHERE s.id IN ({marc})
        ORDER BY s.coletado_em DESC, s.id DESC""", unidades).fetchall()
    # ANTES DA DEDUP: o que a dedup joga fora e a tela precisa.
    #
    # Não é só "em que unidades o processo aparece". Os cinco campos de custódia
    # do SEI — marco de entrada, quem recebeu, envio, unidade de destino — são
    # POR MESA: o mesmo processo está há 3 dias numa unidade e há 200 em outra.
    # A dedup mantém a linha do snapshot mais fresco e descarta as outras, então
    # ler `d["marco_unidade"]` para falar da unidade B é ler o dado da unidade A.
    # É a mesma regra que `poco.py` aplica ao servir bloco entre pessoas: os
    # campos de custódia se RECALCULAM para a mesa que lê, nunca se copiam.
    #
    # Hoje o efeito medido é zero — os 4 processos compartilhados têm os campos
    # idênticos nos dois snapshots. Isso não torna o código certo: torna o
    # defeito invisível até o dia em que duas mesas divergirem, e nesse dia ele
    # apareceria como um número errado sem sintoma nenhum.
    # A CHAVE INCLUI A INSTALAÇÃO, como na dedup. `id_sei` é sequência por
    # instalação: com a FESF ativa, o processo 4823 da SESAB e o 4823 da FESF são
    # coisas distintas, e um índice por `id_sei` puro faz cada um sair com as
    # unidades e as mesas do outro.
    por_unidade_do_processo = {}
    for l in linhas:
        por_unidade_do_processo.setdefault(
            (l["id_sei"], l["instancia"]), {})[l["snap_unidade"]] = {
            "marco_unidade": l["marco_unidade"], "visualizado": l["visualizado"],
            "medido_em": l["medido_em"], "coletado_em": l["coletado_em"],
        }

    vistos, saida = set(), []
    for l in linhas:
        # A CHAVE INCLUI A INSTALAÇÃO. `id_sei` é `id_procedimento`, uma sequência
        # autoincremento POR INSTALAÇÃO do SEI: o processo 4823 da SESAB e o 4823
        # da FESF são coisas diferentes com o mesmo número. Com `id_sei` puro, o
        # segundo seria descartado como duplicata do primeiro — e a carteira
        # perderia linhas em silêncio no dia em que a segunda instalação entrar.
        chave = (l["id_sei"], l["instancia"])
        if chave in vistos:
            continue
        vistos.add(chave)
        d = dict(l)
        # Cada linha é medida contra a LEITURA DELA. Não contra o relógio de quem
        # abriu a tela, e não contra a hora da coleta: com o poço, a linha pode ter
        # lista de hoje e detalhe de três dias atrás, e é o detalhe que produz
        # `marco_unidade`. Medir a data velha com a régua nova inflava os dias — o
        # painel dizia 426 "parados +90d" e este relatório dizia 526, na mesma
        # base, no mesmo segundo.
        _regua = d.get("medido_em") or d.get("coletado_em")
        try:
            # SEM FUSO, para bater com o painel linha a linha (ver `quando_br`).
            # E DATETIME, não `.date()`: era a truncagem daqui, somada à do
            # `_dias`, que fazia "parados +90d" sair 526 aqui e 432 no painel.
            ref = janelas.com_fuso(_regua).replace(tzinfo=None) if _regua else None
        except (TypeError, ValueError):
            ref = None
        # `_medido_em` continua sendo DATA. Quem a lê (`medido_varias_datas`, o
        # carimbo do cabeçalho) pergunta de quantos DIAS distintos é este dado;
        # com datetime, duas linhas do mesmo minuto diferente já acenderiam o
        # aviso de "medido em datas diferentes" em toda coleta.
        d["_medido_em"] = ref.date() if ref else None
        d["_regua_em"] = ref
        d["_dias_unidade"] = _dias(d.get("marco_unidade"), ref)
        mv = json.loads(d["ultimo_movimento"]) if d.get("ultimo_movimento") else {}
        # O JSON já está aberto aqui; `rel_ultimo_evento` reabria a MESMA string.
        d["_ultimo_mov"] = mv
        d["_dias_parado"] = _dias(mv.get("dh"), ref)
        d["_assuntos"] = json.loads(d["assuntos"]) if d.get("assuntos") else []
        d["_mesas"] = []
        # TODAS as unidades em que este processo aparece na carteira — não só a do
        # snapshot que venceu a dedup. Sem isto, processo aberto em duas unidades
        # era creditado a uma só, e o desempate era o id do snapshot, que não
        # significa nada.
        _pu = por_unidade_do_processo.get((l["id_sei"], l["instancia"]), {})
        d["_unidades"] = sorted(_pu)
        # A CRU fica guardada; a derivada sai em `por_unidade_de()`, sob demanda.
        # Ela é lida por UM dos catorze relatórios, e montá-la aqui custava duas
        # datas a mais por processo por unidade — 2.334 conversões de fuso e
        # 2.334 subtrações de data em cada `carregar()`, para as outras treze
        # telas jogarem fora. É referência, não cópia: guardar não custa nada.
        d["_pu"] = _pu
        saida.append(d)

    # ONDE cada processo está aberto. Vem de `processo_mesa`, que o coletor
    # preenche a partir da árvore do SEI — não de `mesas_coleta`, que só diz por
    # qual mesa NÓS o vimos. A diferença é o relatório inteiro: `mesas_coleta`
    # tem as 6 mesas da conta, `processo_mesa` tem as 241 unidades onde os
    # processos realmente estão.
    #
    # A fronteira continua valendo: só entram as mesas dos snapshots que já
    # passaram pelo filtro de unidade acima. A coluna `atribuido` NÃO é lida —
    # ela traz login de gente de outras unidades, e isso não é da conta de quem
    # abre este relatório.
    if saida:
        snaps = sorted({d["snapshot_id"] for d in saida})
        m = ",".join("?" * len(snaps))
        # A árvore do SEI também é por instalação. `processo_mesa` não tem a
        # coluna, mas o snapshot tem — e é dele que a instalação sai, aqui e na
        # dedup, para as duas concordarem.
        inst_do_snap = {d["snapshot_id"]: d["instancia"] for d in saida}
        por_proc = {}
        for l in cx.execute(f"""SELECT id_sei, mesa, snapshot_id FROM processo_mesa
                                WHERE snapshot_id IN ({m}) AND mesa IS NOT NULL
                                  AND mesa <> ''""", snaps):
            chave = (l["id_sei"], inst_do_snap.get(l["snapshot_id"]))
            por_proc.setdefault(chave, set()).add(l["mesa"])
        for d in saida:
            d["_mesas"] = sorted(por_proc.get((d["id_sei"], d["instancia"]), ()))
    # UMA conexão para as duas consultas. A anterior fechava e reabria no meio da
    # função — nada entre elas exigia isso, e cada abertura é um arquivo aberto,
    # um WAL lido e um `busy_timeout` a mais por requisição de relatório.
    cx.close()
    return saida


# Os campos que o catálogo precisa medir: os declarados pelos 14 relatórios mais
# os cinco dos INVIÁVEIS. Montado na importação para o SQL nascer do CATÁLOGO, e
# não de uma segunda lista que alguém teria de lembrar de atualizar.
# Campos que o catálogo mede mas que NÃO moram em `processo`: eles vêm do
# snapshot, existem sempre, e a cobertura deles é 100% por construção
# (`snapshot.unidade` é NOT NULL). Ficam de fora do SQL e voltam no resultado —
# tirá-los sem repor fazia o `cobertura.get(c, 0.0)` da tela virar 0%, e o
# relatório "Comparativo entre unidades" nascer morto.
DO_SNAPSHOT = {"snap_unidade": 1.0}


def _campos_do_catalogo():
    campos = {c for r in CATALOGO for c in r["campos"]}
    campos |= {campo for _t, campo, _m in INVIAVEIS}
    return sorted(campos - set(DO_SNAPSHOT))


def cobertura_agregada(unidades, usuario_id=None):
    """({campo: fração}, total, {campo: fração_sem_zero}) — sem montar 1.165 dicts.

    A tela `/relatorios` é um catálogo: ela não mostra um processo sequer, só a
    fração de preenchimento de cada campo. Carregar a carteira inteira para isso
    custava 34,6 ms dos 60 ms da tela, para alimentar 2,4 ms de contagem.

    A REGRA DE PREENCHIMENTO É A MESMA de `cobertura()`, e essa igualdade é o que
    importa aqui — um catálogo que diga 100% onde o relatório diz 83% é pior do
    que um catálogo lento. `0` conta como preenchido (booleano coletado é dado);
    `''` e `'[]'` não (lista JSON vazia é ausência).

    A base é o número de processos DEDUPLICADOS por (id_sei, instancia) — a mesma
    chave de `carregar()`, senão o denominador seria de linhas e não de processos.

    E É A MESMA LINHA, não a união delas. Um processo aberto em duas unidades tem
    uma linha por mesa, e os campos de custódia são POR MESA: `carregar()` mantém
    a do snapshot mais fresco (`coletado_em DESC, id DESC`) e descarta as outras.
    Um `MAX(...)` por grupo mediria "qualquer linha tem o campo", que é outra
    pergunta — e a divergência só aparece no dia em que duas mesas discordarem.
    Na coleta de 26/08 apareceu: `marco_unidade` 98,82% contra 98,90%,
    `unidade_envio` 353 contra 354. Um processo, silencioso, na tela que existe
    para dizer se o dado dá para confiar.

    O TERCEIRO VALOR conta com a regra OPOSTA para o zero, porque a lista dos
    INVIÁVEIS pergunta outra coisa: lá, "alguém USA este campo?", e um zero é a
    resposta "não". É o que faz `urgente` aparecer como não usado apesar de estar
    "preenchido" em 100% das linhas. Reaproveitar o primeiro para a segunda
    inverte o número — medido: 1.165 de 1.165 onde o certo é 0.
    """
    if not unidades:
        return {}, 0, {}
    cx = conectar()
    try:
        from app import snapshots_de
        escolhidos = snapshots_de(cx, usuario_id, unidades)
        ids = [sid for sid, _ in escolhidos.values()]
        if not ids:
            return {}, 0, {}
        marc = ",".join("?" * len(ids))
        campos = _campos_do_catalogo()
        sem_zero = [c for _t, c, _m in INVIAVEIS]
        # Um booleano por campo, POR LINHA. O banco decide o preenchimento (é o
        # trabalho barato dele) e a dedup fica com quem já a define: a MESMA ordem
        # de `carregar()`, primeira linha vista por chave.
        cols = ", ".join(
            [f"CASE WHEN p.{c} IS NOT NULL AND p.{c} <> '' AND p.{c} <> '[]' "
             f"THEN 1 ELSE 0 END AS t_{c}" for c in campos]
            # `<> 0` a mais: a regra dos INVIÁVEIS.
            + [f"CASE WHEN p.{c} IS NOT NULL AND p.{c} <> '' AND p.{c} <> '[]' "
               f"AND p.{c} <> 0 THEN 1 ELSE 0 END AS z_{c}" for c in sem_zero])
        linhas = cx.execute(f"""
            SELECT p.id_sei, s.instancia, {cols}
            FROM processo p JOIN snapshot s ON s.id = p.snapshot_id
            WHERE s.id IN ({marc})
            ORDER BY s.coletado_em DESC, s.id DESC""", ids).fetchall()
    finally:
        cx.close()
    vistos, venc = set(), []
    for l in linhas:
        chave = (l["id_sei"], l["instancia"])
        if chave in vistos:
            continue
        vistos.add(chave)
        venc.append(l)
    total = len(venc)
    if not total:
        return {}, 0, {}
    cob = {c: sum(l[f"t_{c}"] for l in venc) / total for c in campos}
    # OS CAMPOS QUE VEM DO SNAPSHOT VOLTAM. `_campos_do_catalogo()` os tira do SQL
    # porque eles nao existem na tabela `processo` — mas o catalogo pergunta por
    # eles, e `cobertura.get(c, 0.0)` transformava a ausencia em 0%. O efeito era
    # o relatorio "Comparativo entre unidades" aparecer permanentemente inviavel,
    # com tarja de `snap_unidade 0%`, a um clique de distancia da tela que mostra
    # o MESMO campo com 100% e monta o relatorio sem reclamar.
    #
    # 100% nao e chute: `snapshot.unidade` e NOT NULL e toda linha carregada vem
    # de um snapshot, entao a cobertura dele e total por construcao.
    cob.update(DO_SNAPSHOT)
    return (cob, total,
            {c: sum(l[f"z_{c}"] for l in venc) / total for c in sem_zero})


def inviaveis_medidos_agregado(sem_zero, total):
    """Os inviáveis a partir do agregado que conta `0` como VAZIO.

    Recebe o TERCEIRO valor de `cobertura_agregada`, não o primeiro. Usar o
    primeiro inverte o número: `urgente` sairia 1.165 de 1.165 (100%) onde o
    certo é 0 (0%), porque ali a pergunta é "alguém USA este campo?" e um zero é
    a resposta "não".
    """
    saida = []
    for titulo, campo, motivo in INVIAVEIS:
        f = sem_zero.get(campo, 0.0) if total else None
        n = round(f * total) if total else 0
        saida.append({
            "titulo": titulo, "campo": campo, "motivo": motivo,
            "n": n, "total": total,
            "pct": (round(100 * f) if total else None),
            "medida": (f"{n} de {total} ({round(100 * f)}%)" if total
                       else "sem base coletada para medir"),
        })
    return saida


def cobertura(dados, campo):
    """Fração de processos com o campo PREENCHIDO.

    `0` conta como preenchido. A primeira versão o tratava como vazio, e o efeito
    foi silencioso e grave: todo indicador booleano (`visualizado`,
    `doc_incluido`, `mesas_divergem`) aparecia com 0% de cobertura, e o relatório
    mais importante do sistema — o panorama de triagem — foi excluído do catálogo
    por "dado insuficiente" enquanto o dado estava lá, completo.

    Cobertura e utilidade são coisas diferentes: um campo booleano é sempre 100%
    coletado; se ele nunca varia (como `urgente`, zero em toda a base), o problema
    não é cobertura, é o campo não estar sendo usado no SEI — e isso está dito na
    lista de relatórios inviáveis, com esse nome.
    """
    if not dados:
        return 0.0
    n = sum(1 for d in dados if d.get(campo) not in (None, "", "[]"))
    return n / len(dados)


def varia(dados, campo):
    """Quantos valores distintos o campo assume. Campo que não varia não separa
    nada: `urgente` está preenchido em 100% da base e vale zero em todos."""
    return len({str(d.get(campo)) for d in dados if d.get(campo) not in (None, "", "[]")})


# ---------------------------------------------------------------------------
# Os relatórios. Cada um responde UMA pergunta de gestão — se não dá para
# escrever a pergunta em uma linha, o relatório não deveria existir.
# ---------------------------------------------------------------------------
def _agrupar(dados, chave, rotulo_nulo="(sem informação)"):
    conta = {}
    for d in dados:
        v = chave(d)
        v = rotulo_nulo if v in (None, "", []) else v
        conta[v] = conta.get(v, 0) + 1
    return sorted(conta.items(), key=lambda x: (-x[1], str(x[0])))


def _chave_nome(nome):
    """Nome comparável: sem acento, sem caixa, sem espaço duplo. O SEI mistura as
    três coisas no mesmo campo."""
    if not nome:
        return ""
    s = unicodedata.normalize("NFD", str(nome))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def rel_permanencia(dados):
    ordem = [r for _, _, r in FAIXAS] + ["sem data"]
    # ORDINAL: as faixas são uma escala, e reordenar por tamanho a embaralha.
    conta = dict(_agrupar(dados, lambda d: faixa_de(d["_dias_unidade"])))
    return {
        "colunas": ["Faixa de permanência", "Processos", "% da carteira"],
        "linhas": [[f, conta.get(f, 0), f"{100*conta.get(f,0)/max(1,len(dados)):.1f}%"]
                   for f in ordem if conta.get(f)],
        "total": len(dados),
        "ordinal": True,
    }


def _mediana(valores):
    """A mediana de verdade, formatada para a tela.

    `valores[len(valores) // 2]` devolve o elemento SUPERIOR do par central em
    lista de tamanho par — não a média dos dois. Medido nesta base: das 58 linhas
    do relatório, 26 têm quantidade par e 21 exibiam número diferente da mediana.
    Não era arredondamento: 'Kadyja' saía 447 onde a mediana é 273, 'Vinícius' 78
    onde é 64. A coluna se chama "Mediana de dias".

    Inteiro quando é inteiro: dias são contagens, e "131.0" ao lado de "116" faz
    a tabela parecer quebrada. O ,5 legítimo de uma lista par fica.
    """
    if not valores:
        return "—"
    m = statistics.median(valores)
    return int(m) if float(m).is_integer() else round(m, 1)


def rel_por_responsavel(dados):
    """Quanto cada pessoa carrega, e há quanto tempo.

    UMA passada para indexar, não uma varredura por responsável. A versão
    anterior refazia `[d for d in dados if ...]` dentro do laço: com 58
    responsáveis e 1.165 linhas, 67.570 comparações para produzir 58 linhas.
    """
    conta = _agrupar(dados, lambda d: d.get("atribuido_nome"), "SEM ATRIBUIÇÃO")
    indice = {}
    for d in dados:
        indice.setdefault(d.get("atribuido_nome") or "SEM ATRIBUIÇÃO", []).append(d)
    linhas, sem_data = [], 0
    for nome, n in conta:
        do_resp = indice.get(nome, [])
        parados = sum(1 for d in do_resp if (d["_dias_unidade"] or 0) > 90)
        novos = sum(1 for d in do_resp if not d.get("visualizado"))
        dias = sorted(x["_dias_unidade"] for x in do_resp if x["_dias_unidade"] is not None)
        sem_data += len(do_resp) - len(dias)
        linhas.append([nome, n, parados, novos, _mediana(dias)])
    nota = ("Um processo sem marco de entrada na unidade não tem quantos dias "
            "contar: ele conta em \u201cProcessos\u201d e fica fora da mediana.")
    if sem_data:
        # O QUE FICOU DE FORA, NOMEADO. A cobertura global de `marco_unidade`
        # (98%) não cobre isto: a ausência é concentrada, e há linha com 3 de 7
        # processos sem data cuja mediana é calculada sobre 4 enquanto a coluna
        # ao lado anuncia 7.
        nota = (f"{sem_data} de {len(dados)} processos não têm marco de entrada na "
                "unidade: eles contam em \u201cProcessos\u201d e ficam fora da "
                "mediana, que por isso pode ser calculada sobre menos linhas do "
                "que a coluna ao lado mostra.")
    return {"colunas": ["Responsável", "Processos", "Parados +90d", "Não vistos",
                        "Mediana de dias"], "linhas": linhas, "total": len(dados),
            "nota": nota}


def rel_minha_fila(dados, quem=None, login=None):
    """A carteira de UMA pessoa: a dela.

    Existe como contrapartida da regra de papel. "Carga por responsável" é dado
    de gestão — ela nomeia colegas e ordena por quantidade, e virar ranking
    informal entre pares é o uso mais provável, não o menos. Fechar esse
    relatório sem oferecer nada no lugar puniria o servidor por um risco que não
    é dele: a pergunta legítima "e os MEUS?" continua de pé.

    O casamento é por nome, normalizado, porque é isso que o SEI devolve em
    `atribuido_nome` — e ele vem com caixa inconsistente ("joão guilherme gama
    carvalho" convive com "Maria do Rosário"). Comparar cru perderia a fila
    inteira de quem estivesse do lado errado da caixa.
    """
    # O LOGIN PRIMEIRO, o nome como reserva. `atribuido_login` é identificador —
    # o SEI o escreve sempre igual. `atribuido_nome` é texto livre, e o próprio
    # SEI mistura caixa e acento no mesmo campo: quem estiver do lado errado da
    # grafia vê fila vazia e uma tela que culpa o cadastro. Hoje, nesta base,
    # nenhum dos 57 servidores cai nesse caso — o defeito é latente, e casar por
    # login o remove em vez de esperar o primeiro homônimo.
    eu_login = (login or "").strip().lower()
    meus = [d for d in dados
            if eu_login and (d.get("atribuido_login") or "").strip().lower() == eu_login]
    por_login = bool(meus)
    eu = _chave_nome(quem)
    if not meus:
        meus = [d for d in dados if eu and _chave_nome(d.get("atribuido_nome")) == eu]
    meus.sort(key=lambda d: (d["_dias_unidade"] is None, -(d["_dias_unidade"] or 0)))
    # `protocolo`, não `processo`: a tabela não tem coluna com esse nome, então o
    # `or` caía sempre no id interno. O número do processo é o que se pesquisa no
    # SEI e o que se cita em despacho; o id não serve para nenhum dos dois.
    linhas = [[d.get("protocolo") or d.get("id_sei"),
               d.get("tipo_processo") or "—",
               d["_dias_unidade"] if d["_dias_unidade"] is not None else "—",
               "não" if not d.get("visualizado") else "sim",
               (d.get("marcador") or "—")]
              for d in meus]
    # `total` é a BASE varrida, como em todo relatório do catálogo — não o
    # tamanho da minha fatia. Pôr aqui o número de processos meus faria a tela
    # anunciar "Base: 12" ao lado da procedência de 1.165, e "base" passaria a
    # significar uma coisa neste relatório e outra em todos os demais.
    return {"colunas": ["Processo", "Tipo", "Dias na unidade", "Já visto",
                        "Marcador"], "linhas": linhas, "total": len(dados),
            "meus": len(meus),
            "nota": f"{len(meus)} processo(s) atribuídos a {quem or 'você'}, "
                    f"de {len(dados)} na carteira das suas unidades.",
            # A tela precisa saber SE o nome casou. Zero linhas por não ter
            # processo e zero por o nome não bater são situações opostas, e sem
            # esta marca a pessoa lê "carteira vazia" quando o certo é "não
            # consegui te encontrar no dado".
            "sem_casamento": not (eu or eu_login) or (not meus and bool(dados)),
            # POR ONDE casou. "Não achei você" tem duas causas diferentes — o
            # login não bate ou o nome está grafado de outro jeito — e elas
            # levam a ações diferentes.
            "casou_por": "login" if por_login else ("nome" if meus else None),
            "quem": quem or "—"}


def por_unidade_de(d):
    """Os campos de custódia de CADA unidade, medidos com a régua DAQUELA leitura.

    Quem fala de uma unidade lê daqui, não do vencedor da dedup: `_dias_unidade`
    e `visualizado` do processo vêm do snapshot mais fresco, que pode ser o de
    outra unidade — creditar o processo às duas (certo) e medi-lo com o marco de
    uma só (errado) preenche a coluna de uma unidade com o dado de outra.

    Calculado na primeira pergunta e guardado na própria linha: `rel_por_unidade`
    pergunta uma vez por unidade da carteira, e sem a memória seriam seis
    montagens da mesma coisa.
    """
    pronto = d.get("_por_unidade")
    if pronto is not None:
        return pronto
    pronto = {}
    for _u, _c in (d.get("_pu") or {}).items():
        _r = _c.get("medido_em") or _c.get("coletado_em")
        try:
            _rd = janelas.com_fuso(_r).replace(tzinfo=None) if _r else None
        except (TypeError, ValueError):
            _rd = None
        pronto[_u] = {
            "dias": _dias(_c.get("marco_unidade"), _rd),
            "visualizado": _c.get("visualizado"),
            "quando": _c.get("medido_em") or _c.get("coletado_em") or "",
        }
    d["_por_unidade"] = pronto
    return pronto


def rel_por_unidade(dados, recorte=None):
    """Quanto cada unidade carrega — contando o processo em TODAS onde ele está.

    Antes o relatório agrupava pelo snapshot que venceu a dedup, e o processo
    aberto em duas unidades era creditado a uma só. Medido nesta base: ASTEC
    aparecia com 3 dos 5 processos dela (-40%), DGESS com 19 de 20, CESS com 624
    de 625. Justamente o relatório que pergunta "qual unidade acumula mais
    processo parado?" — e o erro batia mais forte na unidade pequena, onde um
    processo a menos muda a leitura.
    """
    # AS UNIDADES DO RECORTE, não as que sobraram nos dados. Unidade cujo
    # snapshot corrente veio vazio não tem linha nenhuma em `dados` — e sumia da
    # tabela, deixando a tela sem distinguir "coletei e não há nada aqui" de
    # "esta unidade nem existe para você". Zero processo é um fato sobre a
    # unidade; ausência é um fato sobre a coleta, e são leituras diferentes.
    unidades = sorted(set(recorte or []) |
                      {u for d in dados for u in (d.get("_unidades") or
                                                  [d.get("snap_unidade")]) if u})
    linhas, posicoes = [], 0
    for un in unidades:
        da_un = [d for d in dados
                 if un in (d.get("_unidades") or [d.get("snap_unidade")])]
        posicoes += len(da_un)

        # CADA COLUNA COM O DADO DAQUELA UNIDADE. `d["_dias_unidade"]` e
        # `d["visualizado"]` vêm do snapshot que venceu a dedup — que é sempre o
        # mais fresco, não o desta unidade. Creditar o processo às duas unidades
        # (certo) e medi-lo com o marco de uma só (errado) faz a coluna de uma
        # unidade ser preenchida com o dado de outra.
        def _da(d, campo, reserva):
            return por_unidade_de(d).get(un, {}).get(campo, reserva)

        # o mais atrasado, pela régua da linha — mesma razão do cabeçalho
        coletado = min((_da(d, "quando", None) or d.get("medido_em")
                        or d.get("coletado_em") or "") for d in da_un) if da_un else ""
        cor, texto = janelas.idade(coletado) if coletado else ("vazio", "sem linha nesta coleta")
        linhas.append([un, len(da_un),
                       sum(1 for d in da_un
                           if (_da(d, "dias", d["_dias_unidade"]) or 0) > 90),
                       sum(1 for d in da_un
                           if not _da(d, "visualizado", d.get("visualizado"))),
                       texto])
    linhas.sort(key=lambda l: -l[1])
    duplos = posicoes - len(dados)
    nota = ("Um processo aberto em mais de uma unidade é contado em cada uma — é "
            "trabalho de cada uma delas. Por isso a soma da coluna passa do total.")
    if duplos:
        nota += (f" São {duplos} posição(ões) a mais que processos: {len(dados)} "
                 f"processos distintos ocupando {posicoes} lugares.")
    return {"colunas": ["Unidade", "Processos", "Parados +90d", "Não vistos",
                        "Dado de"], "linhas": linhas, "total": len(dados),
            "nota": nota}


def rel_por_tipo(dados):
    linhas = [[t, n, f"{100*n/max(1,len(dados)):.1f}%"]
              for t, n in _agrupar(dados, lambda d: d.get("tipo_processo"))]
    return {"colunas": ["Tipo de processo", "Processos", "% da carteira"],
            "linhas": linhas, "total": len(dados)}


def rel_por_assunto(dados):
    conta = {}
    for d in dados:
        for a in (d["_assuntos"] or ["(sem assunto)"]):
            curto = str(a).split(" - ", 1)[-1][:70]
            conta[curto] = conta.get(curto, 0) + 1
    linhas = sorted(([a, n] for a, n in conta.items()), key=lambda x: -x[1])
    return {"colunas": ["Assunto", "Processos"], "linhas": linhas, "total": len(dados),
            "nota": "Um processo pode ter mais de um assunto, então a soma passa do total."}


def rel_origem(dados):
    linhas = [[o, n, f"{100*n/max(1,len(dados)):.1f}%"]
              for o, n in _agrupar(dados, lambda d: d.get("origem"), "(não identificada)")]
    return {"colunas": ["Origem", "Processos", "% da carteira"], "linhas": linhas,
            "total": len(dados)}


TETO_PROCEDENCIA = 40


def rel_procedencia(dados):
    """De onde vêm os processos — com o que ficou de fora NOMEADO.

    O `[:40]` era o único truncamento de tabela do módulo, e era mudo. Medido:
    123 grupos, 40 exibidos, 83 descartados, 95 processos somem — a coluna somava
    1.070 embaixo de um cabeçalho que anuncia "Base: 1.165". A planilha exportada
    saía truncada junto, e o gráfico calculava o "cortou" dele sobre a tabela já
    cortada, subdeclarando o próprio corte.

    O corte cai no meio de um empate (14 unidades com 2 processos, 2 entram e 12
    somem, desempatadas por ordem alfabética) — mais uma razão para a linha de
    resto existir: "as 40 que mais originam" não é afirmação bem definida na
    fronteira, mas "as outras 83 somam 95" é.
    """
    todas = [[u, n] for u, n in _agrupar(dados, lambda d: d.get("gerador_unidade"))]
    linhas, resto = todas[:TETO_PROCEDENCIA], todas[TETO_PROCEDENCIA:]
    nota = (f"As {len(linhas)} unidades que mais originam processos para a sua "
            "carteira.")
    residuo = False
    if resto:
        n_resto = sum(n for _, n in resto)
        linhas = linhas + [[f"outras {len(resto)} unidades", n_resto]]
        residuo = True
        nota += (f" As outras {len(resto)} somam {n_resto} processo(s) e entram "
                 "como uma linha só, para a coluna fechar com a base.")
    return {"colunas": ["Unidade que gerou", "Processos"], "linhas": linhas,
            "total": len(dados), "nota": nota,
            # A ÚLTIMA LINHA JÁ É UM RESTO. Sem dizer isso, `grafico()` a
            # ordenava por tamanho — ela caía no MEIO das barras — e ainda
            # somava um segundo "outras" no fim: dois restos no mesmo desenho.
            "residuo_na_ultima": residuo, "residuo_qtd": len(resto)}


def rel_sem_movimento(dados):
    conta = _agrupar(dados, lambda d: faixa_de(d["_dias_parado"]))
    ordem = [r for _, _, r in FAIXAS] + ["sem data"]
    c = dict(conta)
    return {"colunas": ["Sem movimento há", "Processos", "% da carteira"],
            "linhas": [[f, c.get(f, 0), f"{100*c.get(f,0)/max(1,len(dados)):.1f}%"]
                       for f in ordem if c.get(f)],
            "total": len(dados),
            "ordinal": True,
            "nota": "Conta desde o último movimento no histórico do SEI, não desde a "
                    "entrada na unidade — processo pode estar parado aqui e ter andado lá."}


def rel_marcadores(dados):
    linhas = [[m, n] for m, n in _agrupar(dados, lambda d: (d.get("marcador") or "").split(" / ")[0].strip(),
                                          "SEM MARCADOR")]
    com = sum(1 for d in dados if (d.get("marcador") or "").strip())
    pct = round(100 * com / max(1, len(dados)), 1)
    return {"colunas": ["Marcador (família)", "Processos"], "linhas": linhas,
            "total": len(dados),
            # A tarja é o relatório. Sem ela, "Convênio: 80" parece um retrato da
            # carteira, quando é um retrato da METADE que alguém se deu ao
            # trabalho de marcar — e a metade sem marcador não é "sem assunto".
            "nota": (f"Só {com} dos {len(dados)} processos ({pct}%) têm marcador. "
                     "A distribuição abaixo descreve essa parte, não a carteira: "
                     "o que não está marcado não é \u201coutros\u201d, é desconhecido. "
                     "O SEI cola texto livre depois de \" / \"; aqui vale o que vem antes.")}


# ---------------------------------------------------------------------------
# CLASSES DE EVENTO. O SEI grava o último andamento como texto livre com o dado
# variável dentro dele — login, número de bloco, número de documento. São 529
# textos distintos para 1.169 processos: agrupar por texto cru produz uma tabela
# de 529 linhas com quase todas valendo 1, que não responde pergunta nenhuma.
#
# A classificação também é o que tira LOGIN da tela: "Processo atribuído para
# fulano@saude.ba.gov.br" vira "Atribuído a alguém". Quem precisa do nome tem o
# relatório de carga por responsável, que é fechado por papel.
#
# A ordem importa: a primeira regra que casar vence. Regras mais específicas
# primeiro ("bloco N retornado" antes de qualquer coisa com "bloco").
# ---------------------------------------------------------------------------
CLASSES_EVENTO = [
    (r"processo recebido na unidade", "Recebido na unidade"),
    (r"conclus[ãa]o do processo na unidade", "Concluído na unidade"),
    (r"reabertura do processo na unidade", "Reaberto na unidade"),
    (r"processo atribu[íi]do", "Atribuído a alguém"),
    (r"processo remanejado", "Remanejado"),
    (r"bloco \d+ disponibilizado", "Disponibilizado em bloco"),
    (r"cancelada disponibiliza[çc][ãa]o do bloco", "Bloco cancelado"),
    (r"bloco \d+ retornado", "Bloco devolvido"),
    (r"conclus[ãa]o do bloco", "Bloco concluído"),
    (r"(retirado|inserido) (do|no) bloco", "Documento movido em bloco"),
    (r"remo[çc][ãa]o de sobrestamento", "Sobrestamento removido"),
    (r"sobrestamento do processo", "Sobrestado"),
    (r"processo (enviado|tramitado|remetido)", "Enviado a outra unidade"),
    (r"assinado documento|assinatura do documento", "Documento assinado"),
    (r"gerado documento|gera[çc][ãa]o do documento", "Documento gerado"),
    (r"registro de documento externo", "Documento externo registrado"),
    (r"exclus[ãa]o do documento|documento .* exclu[íi]do", "Documento excluído"),
    (r"cancelado documento|cancelamento do documento", "Documento cancelado"),
    (r"envio de correspond[êe]ncia eletr[ôo]nica|e-?mail enviado", "E-mail enviado"),
    (r"(inclus[ãa]o|remo[çc][ãa]o) de marcador|marcador ", "Marcador alterado"),
    (r"(inclus[ãa]o|altera[çc][ãa]o|remo[çc][ãa]o) de anota[çc][ãa]o", "Anotação alterada"),
    (r"marca de urg[êe]ncia", "Urgência alterada"),
    (r"processo anexado|anexa[çc][ãa]o do processo", "Anexação"),
    (r"relacionamento do processo|processo relacionado", "Relacionamento"),
    (r"alterada ordem dos protocolos", "Ordem dos documentos alterada"),
    (r"n[íi]vel de acesso|processo (p[úu]blico|restrito|sigiloso)", "Nível de acesso alterado"),
    (r"publica[çc][ãa]o", "Publicação"),
]
_CLASSES = [(re.compile(rx), rot) for rx, rot in CLASSES_EVENTO]


def classe_evento(descricao):
    if not descricao:
        return "Sem histórico"
    b = str(descricao).lower()
    return next((rot for rx, rot in _CLASSES if rx.search(b)), "Outros")


_LOGIN = re.compile(r"[\w.+-]+@[\w.-]+", re.U)
_NUMERO = re.compile(r"\b\d[\d./-]{3,}\b")


def _sem_identificacao(texto):
    """O texto do SEI sem login e sem número — para poder ir para a tela.

    A nota de "Outros" existe para a próxima regra de classificação sair do
    dado, e não de palpite; para isso bastam as PALAVRAS. O que ela não pode
    levar é justamente o que a classificação existe para tirar: o cabeçalho de
    `CLASSES_EVENTO` diz, com todas as letras, que "Processo atribuído para
    fulano@saude.ba.gov.br" tem de virar "Atribuído a alguém". Colar o texto
    cru na nota — que vai para a tela E para a planilha que circula — desfazia
    isso no mesmo relatório que o promete.
    """
    t = _LOGIN.sub("(login)", str(texto or ""))
    return _NUMERO.sub("(n)", t)


def rel_ultimo_evento(dados):
    """A última coisa que aconteceu com cada processo, agrupada por classe.

    E ONDE ela aconteceu. As classes são frases com sujeito de unidade —
    "Concluído na unidade", "Recebido na unidade", "Reaberto na unidade" — e a
    tela inteira tem por recorte a carteira de quem lê: sem dizer a unidade, o
    leitor completa a frase com a dele. Medido nesta base: 321 dos 1.165 (27,6%)
    tiveram o último movimento FORA da carteira. Os 71 "Concluído na unidade"
    foram concluídos em outra e continuam abertos aqui — e os 5 "Enviado a outra
    unidade" descrevem remessas entre duas unidades terceiras, sem o leitor no
    meio. O dado sempre esteve no mesmo dicionário, na chave `un`, e era o único
    lugar do sistema que o descartava: `poco.py` compara `un` para decidir a
    custódia, e o painel o exibe em três telas.
    """
    classes, residuo = {}, {}
    for d in dados:
        mv = d.get("_ultimo_mov") or {}
        c = classe_evento(mv.get("de"))
        minhas = set(d.get("_unidades") or ()) | {d.get("snap_unidade")}
        aqui = bool(mv.get("un")) and mv["un"] in minhas
        atual = classes.get(c) or [0, 0, 0]
        classes[c] = [atual[0] + 1, atual[1] + (1 if aqui else 0),
                      atual[2] + (0 if aqui else 1)]
        if c == "Outros":
            texto = (mv.get("de") or "").strip()
            residuo[texto] = residuo.get(texto, 0) + 1
    linhas = sorted(([c, v[0], v[1], v[2], f"{100*v[0]/max(1,len(dados)):.1f}%"]
                     for c, v in classes.items()), key=lambda x: -x[1])
    fora = sum(v[2] for v in classes.values())
    n_outros = (classes.get("Outros") or [0])[0]
    nota = ("Cada processo entra uma vez, pela última coisa que aconteceu com ele. "
            "O texto do SEI traz login e número de bloco dentro da frase; aqui só "
            "fica a classe do evento.")
    if fora:
        nota += (f" {fora} de {len(dados)} desses movimentos aconteceram em unidade "
                 "FORA da sua carteira — as classes dizem \u201cna unidade\u201d, e "
                 "nesses casos a unidade não é a sua. É por isso que há duas colunas.")
    if n_outros:
        # "Outros" grande esconde o relatório; "Outros" sem explicação esconde o
        # que ele é. Os exemplos ficam à vista para que a próxima regra de
        # classificação saia do dado, e não de palpite.
        exemplos = sorted(residuo.items(), key=lambda x: -x[1])[:5]
        nota += (f" Em 'Outros' ficaram {n_outros} processo(s) de "
                 f"{len(residuo)} texto(s) distinto(s); os mais comuns: "
                 + "; ".join(f"\u201c{_sem_identificacao(k)[:70]}\u201d"
                             for k, _ in exemplos) + ".")
    return {"colunas": ["Última coisa que aconteceu", "Processos",
                        "Na sua unidade", "Em outra", "% da carteira"],
            "linhas": linhas, "total": len(dados), "nota": nota}


def rel_onde_aberto(dados):
    """Em quais unidades a carteira está aberta — inclusive fora daqui.

    Processo aberto em duas unidades ao mesmo tempo é o caso que mais gera
    retrabalho: as duas acham que a outra vai agir. O SEI mostra isso na árvore,
    processo a processo; ninguém abre 1.165 árvores para descobrir.
    """
    conta, com_mesa = {}, 0
    varios = 0
    divergem = sum(1 for d in dados if d.get("mesas_divergem"))
    for d in dados:
        mesas = d.get("_mesas") or []
        if mesas:
            com_mesa += 1
        if len(mesas) > 1:
            varios += 1
        for m in mesas:
            conta[m] = conta.get(m, 0) + 1
    linhas = sorted(([m, n] for m, n in conta.items()), key=lambda x: (-x[1], x[0]))
    return {"colunas": ["Unidade onde está aberto", "Processos"],
            "linhas": linhas, "total": len(dados),
            # Duas medidas parecidas e DIFERENTES, lado a lado de propósito:
            # "aberto em mais de uma unidade" sai da árvore; "árvore e andamento
            # divergem" é o caso em que as duas telas do próprio SEI não contam a
            # mesma história. Fundir as duas num número só faria o relatório
            # afirmar algo que o dado não diz.
            "destaques": [
                {"rotulo": "Unidades de destino distintas", "valor": len(conta)},
                {"rotulo": "Abertos em mais de uma unidade", "valor": varios},
                {"rotulo": "Árvore e andamento divergem", "valor": divergem},
            ],
            "nota": (f"{com_mesa} de {len(dados)} processos têm essa informação na árvore. "
                     f"{varios} estão abertos em mais de uma unidade ao mesmo tempo — a soma "
                     "da coluna passa do total por isso. Quem está na sua unidade não é "
                     "identificado aqui: este relatório mostra UNIDADES, nunca pessoas.")}


def rel_volume(dados):
    """Como a carteira se distribui por TAMANHO de processo.

    A pergunta declarada era "Quais processos exigem mais leitura?" e a resposta
    é uma tabela de faixas: nenhum processo nomeado, nenhuma lista. Promessa e
    entrega diferentes na mesma tela. A pergunta foi corrigida para o que a
    tabela responde — quem quer os processos grandes tem a triagem, que lista.

    E a nota prometia um cruzamento ("muitos documentos E muitos movimentos")
    que duas distribuições marginais não sustentam: as colunas são contadas
    separadamente, e nada aqui diz que são os MESMOS processos.
    """
    faixas = [(0, 5, "até 5"), (6, 20, "6 a 20"), (21, 50, "21 a 50"), (51, 10**6, "mais de 50")]
    def fx(n):
        for a, b, r in faixas:
            if n is not None and a <= n <= b:
                return r
        return "sem informação"
    docs = dict(_agrupar(dados, lambda d: fx(d.get("documentos"))))
    movs = dict(_agrupar(dados, lambda d: fx(d.get("movimentos"))))
    # "sem informação" ENTRA na ordem. `fx` devolve esse rótulo e `_agrupar` o
    # conta, mas a lista de exibição vinha só das faixas numéricas — então o
    # balde era calculado e nunca listado, e processo sem contagem sumia da
    # tabela sem aviso. Hoje ele está vazio nesta base; no dia em que não
    # estiver, sumiria em silêncio, que é o modo de falha que este módulo
    # persegue. Baldes vazios continuam fora, como nos relatórios irmãos.
    ordem = [r for _, _, r in faixas] + ["sem informação"]
    return {"colunas": ["Faixa", "Processos por nº de documentos", "Processos por nº de movimentos"],
            "linhas": [[f, docs.get(f, 0), movs.get(f, 0)] for f in ordem
                       if docs.get(f) or movs.get(f)],
            "total": len(dados),
            "ordinal": True,
            "nota": "As duas colunas são contadas separadamente: a linha \u201c21 a 50\u201d "
                    "não diz que são os mesmos processos nas duas. Processo grande "
                    "costuma exigir mais tempo de leitura antes de qualquer decisão; "
                    "para chegar a ELES, use a triagem, que lista processo a processo."}


def rel_triagem(dados):
    """A pergunta que o sistema existe para responder."""
    # (a nota de procedência da marca de visualização é acrescentada no fim)
    nao_vistos = [d for d in dados if not d.get("visualizado")]
    sem_atrib = [d for d in dados if not d.get("atribuido_login")]
    doc_novo = [d for d in dados if d.get("doc_incluido")]
    parados = [d for d in dados if (d["_dias_unidade"] or 0) > 90]
    restritos = [d for d in dados if d.get("nivel_acesso")
                 and "públic" not in (d.get("nivel_acesso") or "").lower()]
    divergem = [d for d in dados if d.get("mesas_divergem")]
    linhas = [
        # NÃO "por ninguém da unidade". A marca de visualização vem da lista do
        # SEI do login que fez a coleta: ela responde "esta CONTA abriu?", e não
        # "alguém da unidade abriu?". Um processo aberto pela colega ao lado
        # aparece como nunca visto. O rótulo dizia o contrário do que foi medido.
        ["Sem marca de visualização na leitura desta coleta", len(nao_vistos),
         "ninguém abriu pela conta que coletou; podem esconder prazo"],
        ["Sem responsável atribuído", len(sem_atrib),
         "não há a quem cobrar"],
        ["Documento novo incluído ou assinado", len(doc_novo),
         "algo mudou desde a última leitura"],
        ["Parados há mais de 90 dias na unidade", len(parados),
         "revisar: ou está esquecido, ou depende de terceiro"],
        ["Acesso restrito", len(restritos),
         "muda o que se pode fazer com o processo"],
        ["Árvore e andamento divergem", len(divergem),
         "conferir no SEI onde o processo está de fato"],
    ]
    # DE ONDE VEM A MARCA DE VISUALIZAÇÃO. Ela é lida da lista do SEI da conta
    # que fez a coleta, então responde "esta conta abriu?" — não "alguém da
    # unidade abriu?". Um processo que a colega ao lado abriu aparece aqui como
    # sem marca. Dito na tela porque a diferença muda a decisão: "ninguém viu"
    # pede triagem, "eu não vi" pede só olhar.
    # Toda linha aqui é uma CONTAGEM sobre a base inteira, menos as que dependem
    # de campo que nem sempre vem preenchido. Sem dizer isso, "6 restritos" se lê
    # como "só 6 são restritos" quando pode ser "só 6 têm o campo".
    estreitas = [(rot, campo) for rot, campo in
                 (("Acesso restrito", "nivel_acesso"),
                  ("Árvore e andamento divergem", "mesas_divergem"))
                 if cobertura(dados, campo) < COBERTURA_FRACA]
    nota = ("Cada linha é um recorte da mesma carteira; um processo pode aparecer "
            "em mais de uma, então a soma passa do total.")
    for rot, campo in estreitas:
        nota += (f" Atenção: \u201c{rot}\u201d é contado sobre "
                 f"{round(100*cobertura(dados, campo))}% da carteira — o campo "
                 f"\u201c{campo}\u201d falta no resto, e o que falta não é zero.")
    return {"colunas": ["Situação", "Processos", "Por que importa"],
            "linhas": [l for l in linhas if l[1]], "total": len(dados),
            "nota": nota}


CATALOGO = [
    {"id": "triagem", "titulo": "Panorama de triagem",
     "pergunta": "O que exige ação minha agora, e por quê?",
     "campos": ["visualizado", "atribuido_login", "doc_incluido", "marco_unidade",
                "nivel_acesso", "mesas_divergem"],
     "fn": rel_triagem, "destaque": True},
    {"id": "permanencia", "titulo": "Tempo de permanência na unidade",
     "pergunta": "Há quanto tempo os processos estão parados aqui?",
     "campos": ["marco_unidade"], "fn": rel_permanencia, "destaque": True},
    # ÚNICO relatório com restrição de papel, e a restrição é declarada AQUI —
    # não espalhada por decoradores de rota. Assim a tela que lista, a rota que
    # abre e a que exporta leem a mesma regra; foi a divergência entre esses três
    # que já deixou passar "some o cartão mas a URL continua servindo".
    {"id": "responsavel", "titulo": "Carga por responsável",
     "pergunta": "Como o trabalho está distribuído entre as pessoas?",
     "campos": ["atribuido_nome", "marco_unidade"], "fn": rel_por_responsavel,
     "papel": ("gestor", "admin"), "destaque": True},
    # `lista`: uma linha por PROCESSO, não uma agregação. Barra comparando
    # processo com processo, com percentual sobre a soma dos dias, não responde
    # pergunta nenhuma.
    {"id": "minha_fila", "titulo": "Minha fila",
     "pergunta": "Quais processos estão comigo, e há quanto tempo?",
     "campos": ["atribuido_nome", "marco_unidade"], "fn": rel_minha_fila,
     "pessoal": True, "lista": True, "destaque": True},
    {"id": "unidade", "titulo": "Comparativo entre unidades",
     "pergunta": "Qual unidade acumula mais processo parado?",
     "campos": ["snap_unidade", "marco_unidade"], "fn": rel_por_unidade,
     "recorte": True},
    {"id": "sem_movimento", "titulo": "Tempo sem movimento",
     "pergunta": "Quanto tempo faz que alguém mexeu no processo?",
     "campos": ["ultimo_movimento"], "fn": rel_sem_movimento},
    {"id": "tipo", "titulo": "Composição por tipo de processo",
     "pergunta": "De que a carteira é feita?",
     "campos": ["tipo_processo"], "fn": rel_por_tipo},
    {"id": "assunto", "titulo": "Composição por assunto",
     "pergunta": "Que temas ocupam a unidade?",
     "campos": ["assuntos"], "fn": rel_por_assunto},
    {"id": "origem", "titulo": "Recebidos e gerados",
     "pergunta": "A unidade recebe ou produz mais processo?",
     "campos": ["origem"], "fn": rel_origem},
    {"id": "procedencia", "titulo": "De onde os processos vêm",
     "pergunta": "Quais unidades mais nos mandam processo?",
     "campos": ["gerador_unidade"], "fn": rel_procedencia},
    {"id": "onde_aberto", "titulo": "Onde os processos estão abertos",
     "pergunta": "Em que unidades esta carteira está aberta, além daqui?",
     # `mesas_divergem` sustenta o TERCEIRO destaque, não a tabela: a tabela é
     # construída sobre `_mesas`, que vem de `processo_mesa`. Declarar só o
     # booleano fazia a tela anunciar a cobertura de um campo que não é o dado
     # do relatório — e `cobertura()` conta `0` como preenchido, então o número
     # exibido era 100% por construção, dissesse o que dissesse a árvore.
     "campos": ["mesas_divergem"], "cobertura_extra": "arvore",
     "fn": rel_onde_aberto, "destaque": True},
    {"id": "ultimo_evento", "titulo": "Última coisa que aconteceu",
     "pergunta": "O que foi o último movimento de cada processo?",
     "campos": ["ultimo_movimento"], "fn": rel_ultimo_evento},
    {"id": "marcadores", "titulo": "Uso de marcadores",
     "pergunta": "A unidade marca os processos? Com o quê?",
     "campos": ["marcador"], "fn": rel_marcadores},
    {"id": "volume", "titulo": "Volume documental",
     # A PERGUNTA QUE A TABELA RESPONDE. A anterior — "Quais processos exigem
     # mais leitura?" — pedia processos e recebia faixas.
     "pergunta": "Como a carteira se distribui por tamanho de processo?",
     "campos": ["documentos", "movimentos"], "fn": rel_volume},
]

# Perguntas que o dado NÃO sustenta. Ficam listadas na tela, com o motivo: é mais
# útil dizer "não dá, e por quê" do que deixar a pessoa procurar o relatório que
# não existe — ou pior, construí-lo sobre 5% da base.
#
# O MOTIVO É QUALITATIVO; O NÚMERO É MEDIDO. A versão anterior tinha os dois
# escritos à mão — "62 processos em 1.165 (5%)" — dentro do único módulo cuja
# regra declarada, no alto deste arquivo, é "a cobertura de cada campo que ele
# usa (medida, não estimada)". Quando a auditoria foi conferir, dois dos cinco
# já estavam errados: `hipotese_legal` tinha 61 e não 62, `unidade_envio` 314 e
# não 317, e o denominador escrito (1.165) convivia na mesma frase com um
# numerador de outra coleta. Números à mão não envelhecem: eles apodrecem em
# silêncio, e a divergência só cresce a cada coleta.
INVIAVEIS = [
    ("Retorno programado", "retorno",
     "só existe quando alguém programa retorno no SEI"),
    ("Processos anexados", "anexados",
     "só existe quando há processo anexado a este"),
    ("Hipótese legal de restrição", "hipotese_legal",
     "só existe em processo restrito, e nem todo restrito declara a hipótese"),
    ("Para onde foi enviado", "unidade_envio",
     "só existe quando a unidade já despachou o processo"),
    ("Urgentes e sobrestados", "urgente",
     "o campo existe no SEI e esta carteira não o usa"),
]


def inviaveis_medidos(dados):
    """Os inviáveis COM a cobertura medida agora. É o que a tela mostra.

    Sem `dados` (carteira vazia), devolve o motivo sem número: dizer "0 em 0
    (0%)" seria afirmar sobre o campo o que na verdade se sabe sobre a coleta.
    """
    saida = []
    for titulo, campo, motivo in INVIAVEIS:
        n = sum(1 for d in dados if d.get(campo) not in (None, "", "[]", 0)) if dados else 0
        pct = round(100 * n / len(dados)) if dados else None
        saida.append({
            "titulo": titulo, "campo": campo, "motivo": motivo,
            "n": n, "total": len(dados), "pct": pct,
            "medida": (f"{n} de {len(dados)} ({pct}%)" if dados
                       else "sem base coletada para medir"),
        })
    return saida


def por_id(rid):
    return next((r for r in CATALOGO if r["id"] == rid), None)


def pode_ver(rel, papel):
    """A regra de papel mora no catálogo; quem pergunta é a tela E a rota."""
    return papel in rel["papel"] if rel and rel.get("papel") else True


def visiveis(papel):
    return [r for r in CATALOGO if pode_ver(r, papel)]


TETO_BARRAS = 12


def grafico(resultado):
    """Prepara as barras. Devolve None quando o dado não sustenta um gráfico.

    Não sustenta quando: não há coluna numérica; há uma linha só (uma barra não
    compara nada); ou todas as fatias são iguais (um gráfico que não separa nada
    é ruído com aparência de análise).
    """
    linhas = resultado.get("linhas") or []
    if len(linhas) < 2:
        return None
    # A coluna do gráfico é a primeira NUMÉRICA — nas tabelas deste catálogo é
    # sempre a contagem, logo depois do rótulo.
    col = next((i for i, v in enumerate(linhas[0]) if isinstance(v, (int, float))), None)
    if col is None:
        return None
    pares = [(str(l[0]), l[col]) for l in linhas if isinstance(l[col], (int, float))]
    pares = [(r, v) for r, v in pares if v]
    # A LINHA DE RESTO SAI DA DISPUTA. Quem já é "as outras N" não concorre por
    # tamanho com uma unidade: ela volta no fim, junto com o que este gráfico
    # cortar por conta própria.
    ja_resto = None
    if resultado.get("residuo_na_ultima") and pares:
        ja_resto = pares.pop()
    if len(pares) < 2 or len({v for _, v in pares}) == 1:
        return None
    # EIXO ORDINAL NÃO SE REORDENA. "Até 7 dias / 8 a 30 / 31 a 90 / 91 a 180 /
    # mais de 180" é uma escala: as linhas foram construídas nessa ordem
    # justamente para o gráfico ser legível como escala. Ordenar por tamanho
    # embaralhava a escala — em permanência, a barra de "mais de 180" aparecia
    # entre "até 7" e "8 a 30", e o desenho deixava de significar qualquer coisa.
    if not resultado.get("ordinal"):
        pares.sort(key=lambda x: -x[1])
    corte, resto = pares[:TETO_BARRAS], pares[TETO_BARRAS:]
    # O ENCURTAMENTO É DECIDIDO ANTES DE AGREGAR. A barra "outras N" não tem "/",
    # então bastava HAVER corte para o encurtamento ser desligado — justamente
    # no gráfico com mais rótulos, que é onde ele serve.
    caminhos = [r for r, _ in corte if "/" in r]
    encurtar = len(caminhos) == len(corte) and len(corte) > 1
    maiores = len(corte)
    # UMA barra de resto, somando os dois restos: o que a tabela já tinha
    # agregado e o que este gráfico cortou agora.
    n_resto = len(resto) + (int(ja_resto[1] and 1) if ja_resto else 0)
    v_resto = sum(v for _, v in resto) + (ja_resto[1] if ja_resto else 0)
    if ja_resto is not None:
        # UM número só, somando os dois restos: as que a tabela já agregou mais
        # as que ESTE gráfico cortou. Dizer "outras 83 + outras 28" faria o
        # leitor somar de cabeça um número que o desenho já conhece.
        qtd = (resultado.get("residuo_qtd") or 0) + len(resto)
        corte.append((f"outras {qtd} unidades" if qtd else "outras", v_resto))
    elif resto:
        corte.append((f"outras {len(resto)}", v_resto))
    maior = max(v for _, v in corte)
    # A BASE, NÃO A SOMA DA COLUNA. `sum(pares)` só é igual à base quando as
    # linhas particionam a carteira, e em metade do catálogo elas não particionam:
    # se sobrepõem (onde_aberto soma 1.640, assunto 1.208), são recortes
    # sobrepostos (triagem soma 962) ou vêm truncadas (procedencia soma 1.070).
    # Medido: o panorama de triagem imprimia "Parados há mais de 90 dias — 526 ·
    # 54,7%" (526/962) logo abaixo de "Base: 1165", quando 526/1.165 = 45,2%; e em
    # "Onde os processos estão abertos" o erro invertia — CESS saía com 38,1%
    # (625/1.640) contra 53,6% reais. Como a tabela de triagem não tem coluna de
    # %, aquele era o ÚNICO percentual que a pessoa via.
    total = resultado.get("total") or sum(v for _, v in pares)
    # Rótulo curto quando TODOS são caminho de unidade com o mesmo prefixo: o que
    # distingue está no fim, e o começo igual só faz o olho percorrer 22
    # caracteres iguais seis vezes. O nome inteiro continua no `title` e na tabela.
    # (`encurtar` é decidido acima, ANTES de a barra agregada entrar no corte.)
    return {
        "barras": [{"rotulo": (r.rsplit("/", 1)[-1] if encurtar else r),
                    "inteiro": r, "valor": v,
                    "pct": round(100 * v / maior, 1),
                    "fatia": round(100 * v / max(1, total), 1)} for r, v in corte],
        "coluna": resultado["colunas"][col] if col < len(resultado.get("colunas", [])) else "",
        "cortou": len(resto),
        "resto_agregado": bool(resto or ja_resto),
        # O QUE A FATIA MEDE, dito para a tela poder rotular. Percentual sem
        # denominador declarado é o mesmo defeito de novo, com outra cara.
        "base": total,
        "soma": sum(v for _, v in pares),
        # QUANTAS SÃO DE FATO "AS MAIORES". A legenda contava a barra agregada
        # entre elas — "as 13 maiores" para 12 maiores mais um resto.
        "maiores": maiores,
        "agregada": bool(resto or ja_resto),
    }


def montar(rid, unidades, quem=None, usuario_id=None, login=None):
    """Executa um relatório e devolve o resultado COM a procedência do dado."""
    rel = por_id(rid)
    if not rel:
        return None
    dados = carregar(unidades, usuario_id)
    if rel.get("pessoal"):
        resultado = rel["fn"](dados, quem, login)
    elif rel.get("recorte"):
        # O RECORTE, e não só os dados. Unidade cuja coleta veio vazia não tem
        # linha em `dados` e sumia da tabela — a tela não distinguia "zero
        # processos aqui" de "esta unidade não existe para você".
        resultado = rel["fn"](dados, unidades)
    else:
        resultado = rel["fn"](dados)
    resultado["id"] = rel["id"]
    resultado["titulo"] = rel["titulo"]
    resultado["pergunta"] = rel["pergunta"]
    # Cobertura de cada campo, medida agora. É o que impede alguém de defender
    # numa reunião um número construído sobre metade da base sem saber.
    # UMA varredura por campo, não duas: a lista anterior chamava `cobertura()`
    # para o `pct` e de novo para o `fraca`, sobre a mesma base — em triagem, 12
    # passadas completas onde 6 bastam.
    resultado["cobertura"] = []
    if rel.get("cobertura_extra") == "arvore":
        # A COBERTURA DO DADO QUE SUSTENTA A TABELA. `_mesas` é lista, e
        # `cobertura()` trata `[]` como preenchido (a lista vazia não é igual à
        # string "[]"), então ela não serve aqui: quem responde é a contagem
        # direta de quem TEM árvore.
        _com = sum(1 for d in dados if d.get("_mesas"))
        _f = _com / len(dados) if dados else 0.0
        resultado["cobertura"].append(
            {"campo": "árvore do SEI", "pct": round(100 * _f),
             "fraca": _f < COBERTURA_FRACA, "sem_base": not dados})
    for c in rel["campos"]:
        f = cobertura(dados, c)
        resultado["cobertura"].append(
            {"campo": c, "pct": round(100 * f), "fraca": f < COBERTURA_FRACA,
             # SEM BASE não é campo vazio. Com a carteira vazia, `cobertura()`
             # devolve 0.0 e o cartão dizia "0% preenchido" — culpando o
             # preenchimento do campo no SEI por uma coleta que nunca houve.
             "sem_base": not dados})
    # Idade do dado por unidade: somar unidade fresca com unidade atrasada produz
    # número que ninguém consegue defender.
    # O PIOR retrato de cada unidade, não o melhor. O painel usa min() pelo mesmo
    # motivo: quem soma unidades tem de medir contra o retrato mais atrasado,
    # senão o cabeçalho anuncia um frescor que metade das linhas não tem.
    # A MESMA FUNÇÃO QUE A TELA ANTERIOR USA. A versão anterior derivava a tarja
    # dos PROCESSOS — pegava `snap_unidade` da linha que venceu a dedup e media
    # `medido_em or coletado_em` — e com isso ficava cega para três coisas que
    # `estado_coleta()` enxerga:
    #
    #   * linha com `medido_em` NULL (detalhe que ninguém conseguiu ler). NULL não
    #     entra em MIN(), então uma coleta em que TUDO falhou pintava verde
    #     "coletado hoje". Reproduzido: /relatorios mostrava VERMELHO "625 linha(s)
    #     SEM detalhe lido nesta coleta" e /relatorios/permanencia — um clique
    #     depois — mostrava VERDE, apagando a tarja de dado velho;
    #   * linha servida do poço, que tem detalhe de outra leitura;
    #   * unidade cujo snapshot corrente veio VAZIO — coleta que voltou sem linha,
    #     mesa que falhou. Sem linha, ela não aparecia em `dados`, e portanto
    #     sumia da tarja: a tela não distinguia "coletei e não há nada" de "não
    #     coletei".
    #
    # Duas telas do mesmo sistema respondendo "de quando é este dado" por regras
    # diferentes é o defeito que este módulo inteiro existe para não cometer.
    from app import estado_coleta
    _est = estado_coleta(unidades, usuario_id)
    resultado["procedencia"] = [{"unidade": u["unidade"], "cor": u["cor"],
                                 "texto": u["texto"], "do_poco": u.get("do_poco") or 0}
                                for u in _est["unidades"]]
    resultado["desatualizado"] = _est["pior"] not in ("verde", "vazio")
    # Duas datas, nunca uma. "Medido sobre a coleta de X" é o que torna o número
    # reproduzível; "gerado em Y" é o que explica por que a tela mudou de tom
    # sem o número mudar.
    # O MAIS VELHO, e a dispersão medida sobre a régua da LINHA. Com MAX, a
    # planilha saía por e-mail carimbada com a data mais nova carregando linhas de
    # dias antes; e `medido_varias_datas` só via diferença ENTRE snapshots, nunca a
    # dispersão DENTRO de um — que é justamente o que o poço cria.
    medidos = sorted({d["_medido_em"] for d in dados if d.get("_medido_em")})
    resultado["medido_em"] = (medidos[0].strftime("%d/%m/%Y") if medidos else None)
    resultado["medido_varias_datas"] = len(medidos) > 1
    resultado["medido_ate"] = (medidos[-1].strftime("%d/%m/%Y")
                               if len(medidos) > 1 else None)
    resultado["gerado_em"] = datetime.now(TZ).strftime("%d/%m/%Y %H:%M")
    resultado["grafico"] = None if rel.get("lista") else grafico(resultado)
    # OS PROCESSOS QUE SUSTENTAM OS NÚMEROS. A planilha saía só com o agregado:
    # "Sem responsável 137" e nenhum meio de saber QUAIS 137 — quem recebia por
    # e-mail não tinha como conferir nem como agir, e voltava a pedir a lista à
    # mão. Vai como SEGUNDA aba, com os campos que este relatório mediu, para a
    # pessoa reproduzir qualquer linha filtrando na própria planilha.
    # A fronteira é a mesma da tela: `dados` já veio recortado por unidade e por
    # dono em `carregar()`, e a rota do .xlsx aplica o mesmo `pode_ver`.
    resultado["processos"] = dados
    resultado["campos_medidos"] = list(rel["campos"])
    return resultado


def _num_pct(cel):
    """'37.1%' -> 0.371. Qualquer outra coisa passa intacta."""
    if isinstance(cel, str) and cel.endswith("%"):
        try:
            return float(cel[:-1].replace(",", ".")) / 100
        except ValueError:
            return cel
    return cel


# A aba "Processos" da planilha: identificação primeiro, o que o relatório mediu
# depois. Os rótulos são os da TELA — quem abre o .xlsx não conhece
# `atribuido_nome` nem `_dias_unidade`, e nome de coluna de banco numa planilha
# que circula por e-mail é ruído que a pessoa tem de decifrar.
DETALHE_FIXO = [
    ("protocolo",      "Processo"),
    ("especificacao",  "Especificação"),
    ("tipo_processo",  "Tipo"),
    ("_unidades",      "Unidade(s) da minha carteira"),
    ("_mesas",         "Aberto em (árvore do SEI)"),
    ("atribuido_nome", "Responsável"),
    ("_dias_unidade",  "Dias na unidade"),
    ("_dias_parado",   "Dias sem movimento"),
    ("marco_unidade",  "Entrou na unidade em"),
]
DETALHE_ROTULO = {
    "visualizado":     "Tem marca de visualização",
    "atribuido_login": "Login do responsável",
    "doc_incluido":    "Documento novo",
    "nivel_acesso":    "Nível de acesso",
    "mesas_divergem":  "Árvore e andamento divergem",
    "marcador":        "Marcador",
    "origem":          "Origem",
    "gerador_unidade": "Unidade geradora",
    "documentos":      "Documentos",
    "movimentos":      "Movimentos",
    "_assuntos":       "Assuntos",
    "assuntos":        "Assuntos",
    "ultimo_movimento": "Último movimento",
}


def _cel_detalhe(v):
    """Valor de processo -> célula. Lista vira texto, booleano vira sim/não."""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    if isinstance(v, dict):
        # `ultimo_movimento` é {dh, un, de}: interessa o que aconteceu e quando.
        return " · ".join(str(v[k]) for k in ("dh", "un", "de") if v.get(k))
    return v


def _aba_processos(wb, resultado):
    """Segunda aba: um processo por linha, com o que o relatório mediu."""
    procs = resultado.get("processos")
    if not procs:
        return
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    colunas = list(DETALHE_FIXO)
    ja = {c for c, _ in colunas}
    for campo in resultado.get("campos_medidos") or []:
        # `assuntos` chega como JSON cru da coluna; `_assuntos` é a lista já
        # decodificada por `carregar()`. Na planilha vale a decodificada.
        chave = "_assuntos" if campo == "assuntos" else campo
        if chave not in ja:
            colunas.append((chave, DETALHE_ROTULO.get(chave, campo)))
            ja.add(chave)

    ws = wb.create_sheet("Processos")
    ws.append([f"Os {len(procs)} processo(s) por trás dos números da primeira aba."])
    ws["A1"].font = Font(bold=True)
    ws.append(["Filtre por uma coluna para reproduzir qualquer linha do relatório."])
    ws.append([])
    cab = ws._current_row + 1
    ws.append([rot for _, rot in colunas])
    for cel in ws[cab][:len(colunas)]:
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = PatternFill("solid", fgColor="0F5257")
        cel.alignment = Alignment(vertical="center")
    for d in procs:
        ws.append([_cel_detalhe(d.get(c)) for c, _ in colunas])
    ws.freeze_panes = ws.cell(cab + 1, 1)
    ws.auto_filter.ref = f"A{cab}:{get_column_letter(len(colunas))}{cab + len(procs)}"
    for i, (chave, rot) in enumerate(colunas, 1):
        largura = max([len(str(rot))] +
                      [len(str(_cel_detalhe(d.get(chave)))) for d in procs[:200]])
        ws.column_dimensions[get_column_letter(i)].width = min(52, max(12, largura + 3))


def para_xlsx(resultado, caminho_ou_buffer):
    """Exporta com o CABEÇALHO DE PROCEDÊNCIA junto.

    Planilha que sai sem dizer de quando é o dado vira anexo de e-mail e, três
    semanas depois, argumento em reunião — com número de três semanas atrás.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = resultado["titulo"][:31]
    ws.append([resultado["titulo"]])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([resultado["pergunta"]])
    ws.append([])
    # A planilha CIRCULA. Fora do painel nao ha como distinguir uma linha medida
    # hoje de uma medida tres dias antes, entao o carimbo tem de dizer o intervalo
    # inteiro e nao so a ponta mais nova.
    _ate = resultado.get("medido_ate")
    ws.append([f"Medido sobre a leitura de: {resultado.get('medido_em') or '—'}"
               + (f" a {_ate}  (linhas medidas em datas diferentes)" if _ate else "")])
    ws.append([f"Planilha gerada em: {resultado.get('gerado_em')}"])
    ws.append([])
    ws.append(["Dado de:"])
    for p in resultado["procedencia"]:
        ws.append([p["unidade"], p["texto"]])
    ws.append(["Cobertura dos campos:"])
    for c in resultado["cobertura"]:
        ws.append([c["campo"], f"{c['pct']}%" + ("  (parcial)" if c["fraca"] else "")])
    # O QUE QUALIFICA OS NÚMEROS VAI JUNTO. A planilha sai por e-mail e é lida
    # longe da tela: sem a base, "SEM MARCADOR 551" parece um retrato da carteira
    # em vez de um retrato da metade que alguém marcou; sem a nota, a tabela de
    # 40 linhas somando 1.070 não diz que é o topo de 123; sem os destaques,
    # "Onde os processos estão abertos" perde os três números que são a resposta.
    ws.append([])
    ws.append(["Base:", resultado.get("total"), "processo(s)"])
    for d in resultado.get("destaques") or []:
        ws.append([d.get("rotulo"), d.get("valor")])
    if resultado.get("nota"):
        ws.append([])
        ws.append([resultado["nota"]])
    ws.append([])
    # O ÍNDICE, CONTADO À MÃO. `ws.max_row` do openpyxl só conta linha que tem
    # célula, e `ws.append([])` avança o cursor sem criar nenhuma — então
    # `max_row + 1` apontava para uma linha acima do cabeçalho real, e o negrito
    # com fundo escuro caía numa faixa vazia enquanto o cabeçalho saía sem
    # formato. `_current_row` é o cursor de verdade.
    inicio = ws._current_row + 1

    ws.append(resultado["colunas"])
    # SÓ AS COLUNAS DO RELATÓRIO. `ws[inicio]` devolve a linha INTEIRA da
    # planilha, e ela pode ter mais células do que o relatório tem colunas — os
    # blocos de procedência, cobertura e destaques criam células à direita. O
    # efeito era uma célula a mais, vazia, pintada de verde-escuro no fim do
    # cabeçalho.
    for cel in ws[inicio][:len(resultado["colunas"])]:
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = PatternFill("solid", fgColor="0F5257")
        cel.alignment = Alignment(vertical="center")
    for linha in resultado["linhas"]:
        # PERCENTUAL VIRA NÚMERO NA PLANILHA, e só na planilha. As colunas de %
        # nascem como texto ("37.1%") porque é assim que a TELA as imprime e
        # alinha; no Excel, texto não ordena nem soma — "9.9%" fica acima de
        # "12.0%". A conversão vive aqui, no exportador, para não mexer no que a
        # tela faz.
        ws.append([_num_pct(c) for c in linha])
    for i, col in enumerate(resultado["colunas"], 1):
        if "%" in str(col):
            for cel in ws.iter_cols(min_col=i, max_col=i, min_row=inicio + 1):
                for c in cel:
                    c.number_format = "0.0%"
    ws.freeze_panes = ws.cell(inicio + 1, 1)
    for i, _ in enumerate(resultado["colunas"], 1):
        largura = max([len(str(resultado["colunas"][i-1]))] +
                      [len(str(l[i-1])) for l in resultado["linhas"] if len(l) >= i] or [10])
        ws.column_dimensions[get_column_letter(i)].width = min(60, max(12, largura + 3))
    _aba_processos(wb, resultado)
    wb.save(caminho_ou_buffer)
    return caminho_ou_buffer
