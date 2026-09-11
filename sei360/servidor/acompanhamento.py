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
lateral nela — o reaproveitamento da carteira (tarefa adiante desta) tem de passar
pelo MESMO recorte por unidade que o painel usa, nunca por um SELECT direto em
`processo` que enxergaria mesa de qualquer dono.
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
