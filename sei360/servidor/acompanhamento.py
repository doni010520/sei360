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
