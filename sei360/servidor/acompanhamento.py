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
