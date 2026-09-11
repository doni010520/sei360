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
lateral nela — o reaproveitamento da carteira (`reaproveitar`, no fim deste
arquivo) sai de `snapshots_de`, o MESMO recorte por unidade que o painel usa,
nunca de um SELECT direto em `processo` que enxergaria mesa de qualquer dono.
"""
import json
import re

import janelas
from banco import agora

# Teto por pessoa. Com o reaproveitamento da carteira, só o que está fora das
# mesas custa requisição ao SEI: ~3 por processo, ou ~300 no pior caso de uma
# lista cheia inteiramente de fora — contra as ~5.900 que a coleta de 1.182
# processos já faz. O teto existe para a lista não virar uma segunda coleta sem
# ninguém ter decidido isso.
#
# A contagem é lida uma vez por chamada, e sob concorrência (3 workers x 2
# threads) duas colagens simultâneas da mesma conta podem passar do teto —
# medido, chega a 101. Aceito de propósito: este teto é ORÇAMENTO de requisição
# ao SEI, não fronteira de acesso, e três itens a mais custam nove requisições
# uma vez. Serializar a leitura+escrita da contagem para isso seria cerimônia
# desproporcional numa lista pessoal.
TETO = 100

# Só dígitos e a pontuação que o SEI usa. Linha que não casa NÃO é descartada em
# silêncio: volta como recusada, com o texto que a pessoa colou. É o princípio de
# `filtros_recusados` em `pesquisa_sei.js` — entrada que não pegou muda o universo
# da resposta sem mudar uma linha do resultado.
#
# Dígito nas DUAS PONTAS, não `^[\d.\-/]+$`. O ponto é separador legítimo DENTRO
# do número, e o regex antigo não distinguia isso de ponto final de frase: um
# número copiado de citação ("... conforme o SEI 019.5120.2026.0161681-50.")
# entrava com o ponto dentro do protocolo e nunca casava com o SEI — aceito na
# tela, eternamente "não encontrado" na leitura, e duplicado no dia em que a
# pessoa colasse de novo sem o ponto.
#
# `[0-9]`, NÃO `\d`: em Python `\d` casa dígito Unicode — '١٢٣' passa —, e o
# espelho em SQL (`_SQL_DIGITOS`, abaixo) não converte nada disso: ele só tira
# pontuação. Número que a régua de identidade não consegue representar entraria
# na lista com `digitos()` vazio, colidindo com qualquer outro igualmente
# exótico e não casando com carteira nenhuma. O alfabeto da identidade é ASCII
# nas duas pontas, ou não é o mesmo alfabeto.
_SO_NUMERO = re.compile(r"^[0-9][0-9.\-/]*[0-9]$")
_MIN_DIGITOS = 10


def normalizar(texto):
    """O que a pessoa colou -> protocolo, ou None se não é número de processo."""
    t = (texto or "").strip()
    if not t or not _SO_NUMERO.match(t):
        return None
    if sum(c.isdigit() for c in t) < _MIN_DIGITOS:
        return None
    return t


def digitos(protocolo):
    """Só os dígitos. É a IDENTIDADE do processo; a pontuação é apresentação.

    O SEI 4.0 da FESF e o 5.0.4 da SESAB imprimem o mesmo número com pontuação
    diferente, e quem cola cola o que viu. Comparar o texto puro fazia duas
    coisas erradas ao mesmo tempo: o número colado sem pontuação nunca casava
    com a carteira (que guarda a forma pontuada), caindo para sempre no caminho
    caro do SEI por um dado que já estava no banco; e a mesma pessoa colando o
    mesmo processo em duas formas ganhava duas linhas na lista.

    O `protocolo` continua GUARDADO como a pessoa colou — é a forma que ela
    reconhece na tela, e é a chave de `acompanhado`. Isto aqui é só a régua de
    comparação.
    """
    # `'0' <= c <= '9'`, não `isdigit()`: `isdigit()` é verdadeiro para '²' e
    # para dígito árabe-índico, e o espelho em SQL não trata nenhum dos dois —
    # ele só tira pontuação. A régua tem de ser a MESMA nas duas pontas, senão
    # a lista e a carteira passam a comparar coisas diferentes.
    return "".join(c for c in (protocolo or "") if "0" <= c <= "9")


# O espelho de `digitos()` em SQL, que é o que permite casar a lista com a
# carteira sem coluna nova nem mudança de esquema. Remove a pontuação que
# `_SO_NUMERO` aceita, mais o espaço — que a pessoa não consegue colar (o regex
# recusa), mas que pode vir no texto que o SEI imprime.
#
# NÃO HÁ ÍNDICE NISSO, e não precisa: `p.snapshot_id IN (...)` já restringe pelo
# PREFIXO da chave primária de `processo` — `(snapshot_id, id_sei)` —, então a
# expressão só é avaliada sobre as linhas da carteira daquela pessoa, ordem de
# 1.200 por coleta, nunca sobre a tabela inteira. Índice em expressão aqui seria
# custo de escrita em toda ingestão para economizar microssegundo em consulta que
# já está restrita.
_SQL_DIGITOS = ("REPLACE(REPLACE(REPLACE(REPLACE(p.protocolo,'.',''),'-',''),"
                "'/',''),' ','')")


def adicionar(cx, usuario_id, texto, instancia, origem="manual", nota=None):
    """Uma ou várias linhas -> (aceitos, recusados).

    `recusados` leva o texto ORIGINAL da linha, não a versão normalizada: quem
    colou precisa reconhecer o que não entrou para poder corrigir.
    """
    quantos = cx.execute(
        "SELECT COUNT(*) FROM acompanhado WHERE usuario_id=?", (usuario_id,)
    ).fetchone()[0]
    # UMA consulta para o conjunto já seguido, não uma por linha: colar 60
    # números fazia 61 SELECTs (e colar os mesmos 60 de novo, 61 SELECTs para
    # zero aceite) — o mesmo N+1 que o comentário de `listar()`, duas funções
    # abaixo, existe para evitar. Idioma da casa: `poco.py`, função `_carregar`.
    # Sem `IN (...)` em lotes porque aqui o universo já é o da PESSOA inteira,
    # sempre <= TETO — não uma lista de candidatos que pode passar dos limites
    # de variável por statement do SQLite.
    # O CONJUNTO É DE DÍGITOS, não do texto do protocolo. A pontuação é
    # apresentação: colar `019.5120.2026.0161681-50` e depois o mesmo número
    # corrido é seguir o MESMO processo duas vezes, e a chave primária — que é o
    # texto — não tem como impedir. Quem impede é esta comparação.
    ja_seguidos = {digitos(r["protocolo"]) for r in cx.execute(
        "SELECT protocolo FROM acompanhado WHERE usuario_id=? AND instancia=?",
        (usuario_id, instancia))}
    aceitos, recusados = [], []
    for linha in (texto or "").replace(",", "\n").splitlines():
        if not linha.strip():
            continue
        p = normalizar(linha)
        if not p:
            recusados.append(linha.strip())
            continue
        if digitos(p) in ja_seguidos:
            continue
        if quantos >= TETO:
            recusados.append(linha.strip())
            continue
        cx.execute("""INSERT INTO acompanhado(usuario_id,instancia,protocolo,origem,
                      nota,adicionado_em,estado) VALUES(?,?,?,?,?,?,'novo')""",
                   (usuario_id, instancia, p, origem, nota, agora()))
        quantos += 1
        ja_seguidos.add(digitos(p))
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


def instancias(cx, usuario_id):
    """As instalações em que esta pessoa tem item na lista.

    `listar()` devolve a lista INTEIRA, das duas instalações juntas, mas
    `reaproveitar` é POR instalação — o recorte da fronteira depende disso.
    Quem chama precisa saber quais percorrer, e a resposta é o que a lista diz,
    não a configuração ativa: reaproveitar só a ativa deixaria o item da FESF
    dizendo "aguardando primeira leitura" com a resposta pronta na coleta da
    FESF, que é o defeito que este módulo inteiro existe para não cometer.
    """
    return [r["instancia"] for r in cx.execute(
        "SELECT DISTINCT instancia FROM acompanhado WHERE usuario_id=? "
        "ORDER BY instancia", (usuario_id,))]


def delta(anterior, atual):
    """O que mudou entre duas leituras. None quando nada mudou, e na primeira.

    Compara só QUATRO campos: `aberto_em`, `ultimo_movimento`, `documentos` e
    `movimentos`. `fonte` e `medido_em` ficam fora de propósito: trocar de
    "respondido pela carteira" para "lido no SEI" não é mudança NO PROCESSO, e
    apareceria como se fosse — exatamente o ruído que o selo de divergência
    árvore/andamento já produziu uma vez neste produto.

    None na PRIMEIRA leitura, nunca "mudou tudo": não há com o que comparar, e
    anunciar mudança onde não houve observação é a mesma falsidade do aviso de
    divergência que a auditoria de 10/09/2026 mediu como 100% falso positivo.
    """
    if not anterior:
        return None
    d = {}
    # AUSÊNCIA NÃO É CONJUNTO VAZIO — o mesmo cuidado que as contagens, abaixo,
    # já tinham com `is not None`. Com `or []`, leitura relatada SEM o campo
    # (árvore que não parseou, JSON truncado, campo que a estação não soube
    # preencher) virava "não está aberto em lugar nenhum", e a tela dizia que o
    # processo saiu de TODAS as unidades. A estação relata o que leu; o que ela
    # não leu não pode virar afirmação — e é a docstring desta função que promete
    # não anunciar mudança onde não houve observação.
    antes_un, agora_un = anterior.get("aberto_em"), atual.get("aberto_em")
    if antes_un is not None and agora_un is not None:
        antes_un, agora_un = set(antes_un), set(agora_un)
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
    for campo, rotulo in (("documentos", "documento"), ("movimentos", "movimento")):
        n = d.get(campo)
        if not n:
            continue
        # COM SINAL. Documento cancelado no SEI faz a contagem CAIR, e a versão
        # anterior desta função só falava de aumento — o item aparecia marcado
        # como alterado, sem uma palavra dizendo o que mudou.
        plural = "" if abs(n) == 1 else "s"
        partes.append(f"{n:+d} {rotulo}{plural}")
    if not partes and d.get("movimentou_em"):
        partes.append(f"movimentou em {d['movimentou_em']}")
    return " · ".join(partes)


def _medicao_avancou(nova, anterior):
    """A medição nova é ESTRITAMENTE mais nova que a da leitura anterior?

    Sobre `medido_em`, que é ISO com offset — nunca sobre `ultimo_movimento.dh`,
    que é `dd/mm/yyyy` e como texto põe 05/09 depois de 11/08.

    Data faltando, ou ilegível, responde NÃO: sem frescor estabelecido não se
    anuncia mudança. É o lado seguro do erro — o outro lado é imprimir perda de
    documento na tela de quem confia no número.
    """
    if not nova or not anterior:
        return False
    try:
        return janelas.com_fuso(nova) > janelas.com_fuso(anterior)
    except (TypeError, ValueError):
        return False


def gravar_leitura(cx, usuario_id, instancia, protocolo, dados, fonte, medido_em,
                   estado="lido", id_sei=None):
    """Uma leitura, com o delta contra a anterior já calculado.

    O delta é calculado AQUI, no servidor, e nunca chega pronto de fora: a
    estação relata o que leu, não o que concluiu.

    `medido_em` é OBRIGATÓRIO. Era opcional, com reserva silenciosa em
    `agora()` — e reserva silenciosa é exatamente o defeito que este campo
    existe para não ter: chamador que esquecesse carimbava "medido agora" sobre
    dado de nove dias atrás. Quem lê no SEI passa `agora()`, explicitamente,
    porque ali a medição É agora.
    """
    anterior = cx.execute("""SELECT medido_em, aberto_em, ultimo_movimento,
                             documentos, movimentos
                             FROM acompanhado_leitura
                             WHERE usuario_id=? AND instancia=? AND protocolo=?
                             ORDER BY id DESC LIMIT 1""",
                          (usuario_id, instancia, protocolo)).fetchone()
    prev = None
    # SÓ SE COMPARA CONTRA OBSERVAÇÃO MAIS VELHA QUE ESTA. `ORDER BY id DESC` dá
    # a última INSERIDA, não a última MEDIDA, e as duas divergem no caso comum: o
    # processo sai da mesa de B, sobra a linha velha de A, e a medição anda para
    # trás. Sem esta guarda a tela anunciava "saiu de B · -5 documentos · -9
    # movimentos" — perda que nunca houve, só dado mais velho respondendo.
    #
    # Com a leitura no SEI na jogada fica pior: a guarda de "não lido hoje" é por
    # DIA, não por frescor, então amanhã a carteira de nove dias atrás responde
    # antes e o processo VOLTA NO TEMPO na tela, com movimentação inventada nas
    # duas direções.
    #
    # A doutrina é a que `delta()` já aplica à primeira leitura: não anunciar
    # mudança onde não houve observação nova. A leitura é gravada — a tela precisa
    # saber de quando é o dado que está mostrando —, mas `mudou` fica nulo.
    if anterior and _medicao_avancou(medido_em, anterior["medido_em"]):
        prev = {"aberto_em": json.loads(anterior["aberto_em"] or "null"),
                "ultimo_movimento": json.loads(anterior["ultimo_movimento"] or "null"),
                "documentos": anterior["documentos"],
                "movimentos": anterior["movimentos"]}
    d = delta(prev, dados)
    cx.execute("""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
                  lido_em,fonte,medido_em,aberto_em,aberto_em_fonte,
                  ultimo_movimento,documentos,movimentos,mudou)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
               (usuario_id, instancia, protocolo, agora(), fonte, medido_em,
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
    """Responde da CARTEIRA o que a carteira já sabe.

    Devolve quantos ITENS DA LISTA respondeu — que é o mesmo que processos,
    exceto quando a lista guarda o mesmo número em duas formas (ver
    `por_digitos`, no fim desta função).

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

    # UMA LEITURA POR DIA, seja de qual fonte for. `lido_em` é atualizado por
    # `gravar_leitura`, então o que foi lido no SEI hoje não é REBAIXADO em
    # seguida para o dado da carteira, que pode ser de nove dias antes; e a
    # segunda passada do mesmo dia não grava leitura repetida de delta nulo, que
    # encheria a única série temporal do produto com linhas sem observação nova.
    pendentes = [r["protocolo"] for r in cx.execute(
        """SELECT protocolo FROM acompanhado
           WHERE usuario_id=? AND instancia=?
             AND (lido_em IS NULL OR substr(lido_em,1,10) <> substr(?,1,10))""",
        (usuario_id, instancia, agora()))]
    if not pendentes:
        return 0
    # DÍGITO -> as formas em que a pessoa colou aquele número. É por ele que a
    # lista casa com a carteira, e é LISTA de formas porque a chave primária de
    # `acompanhado` é o texto: linha anterior a esta regra, ou inserida fora de
    # `adicionar`, pode ter as duas formas do mesmo processo. Quando tem, as duas
    # são respondidas — ficar com uma deixaria a outra 'novo' para sempre.
    por_digitos = {}
    for p in pendentes:
        por_digitos.setdefault(digitos(p), []).append(p)
    unidades = unidades_do(usuario_id)
    if not unidades:
        return 0
    escolhidos = snapshots_de(cx, usuario_id, unidades)
    # SÓ OS SNAPSHOTS DESTA INSTALAÇÃO. `unidades_do` devolve as unidades das duas
    # instalações juntas, e `snapshots_de` responde por todas elas. Sem este
    # filtro, um protocolo que existe na coleta da FESF responderia o item que a
    # pessoa colou na lista da SESAB, e a leitura sairia gravada sob
    # `instancia='SEI-SESAB'` com as mesas da FESF dentro — o mesmo defeito que
    # `coleta.py`, `configuracao.py` e `ingestao.py` documentam ter carimbado dado
    # da FESF como SESAB, e o motivo de `acompanhado.instancia` ter nascido sem
    # DEFAULT. Não é furo de fronteira (o vínculo existe nas duas), é carimbo
    # falso — e a chave de `snapshots_de` já é o par (instalação, unidade): basta
    # não jogar a instalação fora.
    ids = [sid for (inst, _unidade), (sid, _dono) in escolhidos.items()
           if inst == instancia]
    if not ids:
        return 0
    marc_s = ",".join("?" * len(ids))
    marc_p = ",".join("?" * len(por_digitos))
    linhas = cx.execute(f"""
        SELECT p.protocolo, p.id_sei, p.ultimo_movimento, p.documentos, p.movimentos,
               p.medido_em, p.mesas_fonte, s.coletado_em,
               (SELECT GROUP_CONCAT(m.mesa, char(31)) FROM processo_mesa m
                 WHERE m.snapshot_id=p.snapshot_id AND m.id_sei=p.id_sei) AS mesas
        FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
        WHERE p.snapshot_id IN ({marc_s})
          -- POR DÍGITOS nas duas pontas, não pelo texto. A carteira guarda a
          -- forma pontuada que o SEI imprime, e a lista guarda a forma que a
          -- pessoa colou; casar texto com texto deixava o número corrido
          -- eternamente no caminho caro do SEI por um dado que já estava aqui.
          -- `_SQL_DIGITOS` é o espelho de `digitos()`, e o comentário dele diz
          -- por que não há índice nisso.
          AND {_SQL_DIGITOS} IN ({marc_p})
        -- DA MEDIÇÃO MAIS FRESCA PARA A MAIS VELHA. O mesmo processo aparece em
        -- toda coleta de unidade onde ele está aberto, e é a MEDIÇÃO — não a hora
        -- da coleta — que diz qual dessas linhas descreve o processo hoje: 92,6%
        -- dos processos de uma coleta são servidos do poço, então lista nova com
        -- detalhe de dias atrás é o REGIME NORMAL, e é por isso que `medido_em`
        -- existe (ver a coluna em `banco.py`).
        --
        -- A régua de MEDIR é a mesma do painel e de `relatorios.carregar`
        -- (`medido_em or coletado_em`). O que difere é a ORDEM DE ESCOLHA entre
        -- linhas: lá é `s.coletado_em`, aqui é a medição, e a diferença é
        -- deliberada. Lá a ordem decide qual linha sobrevive à dedup entre as
        -- unidades de uma carteira coletada na mesma passada; aqui ela decide
        -- qual MEDIÇÃO responde por um processo que pode ter detalhe de 20/08
        -- sob coleta de 12/09.
        ORDER BY COALESCE(p.medido_em, s.coletado_em) DESC, s.id DESC""",
        ids + list(por_digitos)).fetchall()
    # UM MOMENTO, UM QUADRO. Tudo sai da MESMA linha — contagem, régua, mesas e
    # fonte. A escolhida é a mais fresca que TENHA lista de mesas; se nenhuma
    # tiver, a mais fresca, com `aberto_em` vazio.
    #
    # `processo_mesa` é a ÁRVORE INTEIRA por linha, NÃO o ângulo da mesa que
    # coletou: `ingestao.py` a preenche de `d["mesas"]`, que em
    # `automacao_sei.js` é `mesas, // onde esta aberto hoje` — a linha "Processo
    # aberto nas unidades: ..." do topo da árvore, com a máquina de estados do
    # andamento como reserva. `relatorios.py` já dizia isso por escrito.
    #
    # A versão anterior SOMAVA as mesas de todas as linhas, e fazia três danos:
    #
    #   1. importava bolor — mesa de 27/08 sob contagem e régua de 12/09,
    #      carimbada 'arvore' para unidade que a árvore fresca já não lista:
    #      retrato que não existiu em momento nenhum;
    #   2. calava o `saiu_de` ESTRUTURALMENTE — união só cresce, então enquanto o
    #      snapshot velho vivesse (nove dias úteis, no caso medido em 10/09/2026)
    #      o evento mais valioso do módulo nunca sairia: a tela diria "+2
    #      documentos" para um processo que saiu da unidade da pessoa;
    #   3. misturava lista medida errada com lista medida certa — a árvore bateu
    #      com a mesa em 1.278 de 1.278 casos observáveis, o andamento em 0.
    #
    # E NÃO se prefere 'arvore' sobre 'andamento' entre linhas diferentes: isso
    # juntaria a mesa de uma linha com a contagem de outra, que é o mesmo defeito
    # com outra roupa. Linha escolhida vinda do andamento => fonte 'andamento', e
    # a tela marca "não confirmado pela árvore" — é para isso que o campo existe.
    escolhida = {}
    for r in linhas:                     # já vêm da medição mais fresca
        # A CHAVE É O DÍGITO, não o texto: é ele que liga a linha da carteira
        # (pontuada, como o SEI imprime) ao item da lista (como a pessoa colou).
        chave = digitos(r["protocolo"])
        mesas = sorted(set((r["mesas"] or "").split(chr(31))) - {""})
        atual = escolhida.get(chave)
        # Fica com a primeira vista, que é a mais fresca; só troca quando ela não
        # trouxe mesa nenhuma e esta trouxe.
        if atual is None or (not atual[1] and mesas):
            escolhida[chave] = (r, mesas)
    feitos = 0
    for chave, (r, mesas) in escolhida.items():
        dados = {
            # LISTA, nunca None — e vazia quando a linha escolhida não listou
            # mesa alguma, que acontece de verdade: `processo_mesa` nasce da
            # linha "Processo aberto nas unidades" da árvore, e coleta cuja
            # árvore não parseou grava o processo sem uma única linha de mesa.
            # `listar()` devolve None tanto para JSON null quanto para item que
            # nunca foi lido, então `[]` é o único valor que a tela consegue
            # distinguir de "aguardando primeira leitura" — e vazio aqui
            # significa "a coleta não disse", nunca "não está aberto em lugar
            # nenhum".
            "aberto_em": mesas,
            # `mesas_fonte` vem da coleta e pode valer 'andamento', que a medição
            # de 10/09/2026 mostrou errar em 100% dos 1.278 casos observáveis.
            # Não se relê por isso — seria uma requisição por dia para trocar
            # dado velho por dado novo do mesmo campo —, mas a tela marca como
            # não confirmado pela árvore, e para isso a fonte tem de chegar lá.
            "aberto_em_fonte": r["mesas_fonte"] or "andamento",
            "ultimo_movimento": json.loads(r["ultimo_movimento"] or "null"),
            "documentos": r["documentos"], "movimentos": r["movimentos"],
        }
        # O PROTOCOLO DA LISTA, nunca o da carteira. A chave de `acompanhado` é a
        # forma que a pessoa colou; gravar a leitura sob a forma pontuada da
        # carteira faria a FK composta recusar — e com razão, porque não existe
        # leitura sem a linha da lista. São VÁRIAS formas só quando a lista já
        # tinha as duas (ver `por_digitos`); no caso normal, uma — e é por isso
        # que `feitos` conta ITEM DA LISTA respondido, não processo distinto.
        for protocolo in por_digitos.get(chave, ()):
            gravar_leitura(cx, usuario_id, instancia, protocolo, dados,
                           fonte="carteira",
                           # A DATA DA MEDIÇÃO, nunca `agora()`: em 10/09/2026 as
                           # 12 unidades estavam com coleta de nove dias úteis
                           # antes, e carimbar "lido hoje" sobre dado de 27/08 é
                           # mentir na procedência. `coletado_em` é a reserva
                           # porque `medido_em` é nulo em linha de coleta
                           # anterior à régua.
                           medido_em=r["medido_em"] or r["coletado_em"],
                           id_sei=r["id_sei"])
            feitos += 1
    return feitos
