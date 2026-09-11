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
_SO_NUMERO = re.compile(r"^\d[\d.\-/]*\d$")
_MIN_DIGITOS = 10


def normalizar(texto):
    """O que a pessoa colou -> protocolo, ou None se não é número de processo."""
    t = (texto or "").strip()
    if not t or not _SO_NUMERO.match(t):
        return None
    if sum(c.isdigit() for c in t) < _MIN_DIGITOS:
        return None
    return t


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
    ja_seguidos = {r["protocolo"] for r in cx.execute(
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
        if p in ja_seguidos:
            continue
        if quantos >= TETO:
            recusados.append(linha.strip())
            continue
        cx.execute("""INSERT INTO acompanhado(usuario_id,instancia,protocolo,origem,
                      nota,adicionado_em,estado) VALUES(?,?,?,?,?,?,'novo')""",
                   (usuario_id, instancia, p, origem, nota, agora()))
        quantos += 1
        ja_seguidos.add(p)
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
    marc_p = ",".join("?" * len(pendentes))
    linhas = cx.execute(f"""
        SELECT p.protocolo, p.id_sei, p.ultimo_movimento, p.documentos, p.movimentos,
               p.medido_em, p.mesas_fonte, s.coletado_em,
               (SELECT GROUP_CONCAT(m.mesa, char(31)) FROM processo_mesa m
                 WHERE m.snapshot_id=p.snapshot_id AND m.id_sei=p.id_sei) AS mesas
        FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
        WHERE p.snapshot_id IN ({marc_s}) AND p.protocolo IN ({marc_p})
        -- DA MEDIÇÃO MAIS FRESCA PARA A MAIS VELHA, porque o mesmo processo pode
        -- vir de duas mesas desta conta, com uma coleta de cada dia. A régua é
        -- `medido_em or coletado_em`, a MESMA com que o painel e
        -- `relatorios.carregar` medem cada linha; ordenar pela hora do snapshot
        -- daria a linha de detalhe velho de uma coleta de lista nova.
        ORDER BY COALESCE(p.medido_em, s.coletado_em) DESC, s.id DESC""",
        ids + pendentes).fetchall()
    # UMA LEITURA POR PROTOCOLO, ainda que o processo esteja em DUAS mesas desta
    # conta — situação corrente, a mesma que `relatorios.carregar` trata na dedup.
    # Uma leitura por linha gravaria duas na mesma passada, e a segunda mediria o
    # delta contra a primeira, recém-inserida: a tela anunciaria "saiu de A,
    # entrou em B" para um processo que não se moveu, e `feitos` contaria dois
    # processos onde havia um.
    #
    # Contagem, movimento e régua saem da linha mais fresca; as mesas se SOMAM,
    # porque cada coleta vê o processo do ângulo da mesa dela. A união é o que
    # fica estável entre passadas — lista que oscila conforme qual coleta chegou
    # primeiro é exatamente o falso "mudou" que `delta` existe para não inventar.
    juntos = {}
    for r in linhas:
        d = juntos.get(r["protocolo"])
        if d is None:
            d = juntos[r["protocolo"]] = {
                "mesas": set(), "fontes": set(),
                "ultimo_movimento": json.loads(r["ultimo_movimento"] or "null"),
                "documentos": r["documentos"], "movimentos": r["movimentos"],
                "medido_em": r["medido_em"] or r["coletado_em"],
                "fonte_fresca": r["mesas_fonte"] or "andamento",
                "id_sei": r["id_sei"],
            }
        mesas = set((r["mesas"] or "").split(chr(31))) - {""}
        if mesas:
            d["mesas"] |= mesas
            # A fonte acompanha quem CONTRIBUIU com mesa: linha que não trouxe
            # unidade nenhuma não tem procedência a declarar sobre a lista.
            d["fontes"].add(r["mesas_fonte"] or "andamento")
    feitos = 0
    for protocolo, d in juntos.items():
        # `mesas_fonte` vem da coleta e pode valer 'andamento', que a medição de
        # 10/09/2026 mostrou errar em 100% dos 1.278 casos observáveis. Não se
        # relê por isso — seria uma requisição por dia para trocar dado velho por
        # dado novo do mesmo campo —, mas a tela marca como não confirmado pela
        # árvore, e para isso a fonte tem de chegar lá.
        #
        # Na união de duas mesas vale a fonte MAIS FRACA: dizer 'arvore' sobre uma
        # lista em que metade das unidades veio do andamento é afirmar
        # confirmação que não houve. É o princípio de `mesa_indeterminada`, que
        # significa "não sei" e nunca "sem divergência".
        if d["fontes"]:
            fonte_mesas = "arvore" if d["fontes"] == {"arvore"} else "andamento"
        else:
            fonte_mesas = d["fonte_fresca"]
        dados = {
            # LISTA, nunca None — e vazia quando a coleta não listou mesa alguma,
            # que acontece de verdade: `processo_mesa` nasce da linha "Processo
            # aberto nas unidades" da árvore, e coleta cuja árvore não parseou
            # grava o processo sem uma única linha de mesa. `listar()` devolve
            # None tanto para JSON null quanto para item que nunca foi lido, então
            # `[]` é o único valor que a tela consegue distinguir de "aguardando
            # primeira leitura" — e vazio aqui significa "a coleta não disse",
            # nunca "não está aberto em lugar nenhum".
            "aberto_em": sorted(d["mesas"]),
            "aberto_em_fonte": fonte_mesas,
            "ultimo_movimento": d["ultimo_movimento"],
            "documentos": d["documentos"], "movimentos": d["movimentos"],
        }
        gravar_leitura(cx, usuario_id, instancia, protocolo, dados,
                       fonte="carteira",
                       # A DATA DA MEDIÇÃO, nunca `agora()`: em 10/09/2026 as 12
                       # unidades estavam com coleta de nove dias úteis antes, e
                       # carimbar "lido hoje" sobre dado de 27/08 é mentir na
                       # procedência. `coletado_em` é a reserva porque
                       # `medido_em` é nulo em linha de coleta anterior à régua.
                       medido_em=d["medido_em"],
                       id_sei=d["id_sei"])
        feitos += 1
    return feitos
