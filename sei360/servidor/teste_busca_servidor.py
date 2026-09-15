# -*- coding: utf-8 -*-
"""
BUSCA NO SERVIDOR — por que ela não rodava, e por que não tentava de novo.

Nasce da perícia de 15/09/2026 sobre as pesquisas de processo que "não rodaram":
105 modos de falha levantados, 70 confirmados por verificação independente. Esta
suíte prende os que foram consertados no caminho do VPS — o único que roda:

  * a causa real no lugar de "o servidor não chegou a executar a busca";
  * nova tentativa para falha PASSAGEIRA, e nenhuma para falha permanente;
  * a varredura que matava busca viva na fila e descartava resultado tardio;
  * o veredito que jogava itens colhidos fora como 'falhou';
  * o aceite de pedido que o servidor não tinha como executar (sem senha);
  * a conta do SEI compartilhada entre busca, coleta e acompanhamento;
  * a tentativa do acompanhamento cobrada de volta que nem chegou ao SEI;
  * a busca que nunca ativava a mesa pedida.

Roda contra banco NOVO (`copiar=False`) e com coletor de mentira: não precisa do
banco de trabalho, não abre Chromium e não fala com o SEI.

    python teste_busca_servidor.py
"""
import json
import os
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ambiente_teste import isolar

isolar(__file__, copiar=False)
import base64 as _b64
os.environ.setdefault("SEI360_CHAVE_MESTRA",
                      _b64.b64encode(b"chave-de-teste-32-bytes-!!!!!!!!").decode())
os.environ["SEI360_ATENDENTE"] = "0"
sys.stdout.reconfigure(encoding="utf-8")

import banco                                                     # noqa: E402
banco.migrar()
import acompanhamento as acmod                                   # noqa: E402
import acompanhamento_servidor as asv                            # noqa: E402
import atendente as at                                           # noqa: E402
import busca as bmod                                             # noqa: E402
import coleta_servidor as cs                                     # noqa: E402
import cofre                                                     # noqa: E402
from banco import TZ, agora, conectar                            # noqa: E402

SCRATCH = Path(__file__).resolve().parent
ok = mau = 0


def checar(nome, cond, viu=None):
    global ok, mau
    if cond:
        ok += 1
        print(f"  ok    {nome}")
    else:
        mau += 1
        print(f"  FALHA {nome}" + (f"  -> {viu}" if viu is not None else ""))


cx = conectar()
cx.execute("""INSERT INTO usuarios(email,nome,papel,ativo,senha_trocada_em)
              VALUES('zaine.teste@saude.ba.gov.br','Zaine Teste','servidor',1,?)""", (agora(),))
UID = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
CONTA = "zaine.teste@saude.ba.gov.br"
cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,modo_coleta,sei_login,atualizado_em)
              VALUES(?,'SEI-SESAB','servidor',?,?)""", (UID, CONTA, agora()))
cofre.guardar(cx, UID, "SEI-SESAB", CONTA, "senha-de-teste")
cx.commit()


def coletor_falso(corpo):
    """Um coletor de mentira: lê o pedido do stdin e faz o que o corpo mandar."""
    p = SCRATCH / "_coletor_falso_busca.py"
    p.write_text("import json, sys, os\npedido = json.loads(sys.stdin.readline())\n" + corpo,
                 encoding="utf-8")
    at.COLETOR = p
    return p


def nova_busca():
    cx.execute("DELETE FROM busca_trava")
    _orig = at.capacidade
    at.capacidade = lambda: (True, None)
    try:
        bid, erro, _ = bmod.pedir(cx, UID, "SEI-SESAB", CONTA, "SESAB/SAIS/DGGUP/DGESS",
                                  {"assunto": "teste"})
    finally:
        at.capacidade = _orig
    cx.commit()
    assert bid, erro
    return bid


def rodar(bid):
    """Pega e executa UMA busca, como o laço faria."""
    r = at.pegar(cx)
    assert r and r["id"] == bid, (r, bid)
    return at.executar(cx, r)


def linha(bid):
    return dict(cx.execute("SELECT * FROM busca WHERE id=?", (bid,)).fetchone())


_coletor_real = at.COLETOR
try:
    print("A. A CAUSA REAL, no lugar de 'o servidor não chegou a executar a busca'")
    coletor_falso("print('LOGIN NAO CONCLUIU em 60s')\nsys.exit(3)\n")
    b = nova_busca()
    rodar(b)
    L = linha(b)
    checar("login recusado sai com a causa, não com 'não chegou a executar'",
           "login" in (L["motivo"] or "") and "não chegou" not in (L["motivo"] or ""), L["motivo"])
    checar("e é PERMANENTE: falhou, sem nova tentativa", L["estado"] == "falhou"
           and not L["tentativas"], (L["estado"], L["tentativas"]))

    print("\nB. FALHA PASSAGEIRA GANHA NOVA TENTATIVA — com espera e com limite")
    coletor_falso("print('ERRO DE INFRAESTRUTURA: net::ERR_CONNECTION_RESET')\nsys.exit(4)\n")
    b = nova_busca()
    rodar(b)
    L = linha(b)
    checar("infraestrutura volta para a fila", L["estado"] == "pedida" and L["tentativas"] == 1,
           (L["estado"], L["tentativas"], L["motivo"]))
    checar("com espera marcada, não no mesmo segundo", bool(L["tentar_apos"]), L["tentar_apos"])
    checar("e o motivo diz que é nova tentativa, e por quê",
           "nova tentativa" in (L["motivo"] or "") and "infraestrutura" in (L["motivo"] or ""),
           L["motivo"])
    checar("a conta continua travada entre uma tentativa e outra",
           bmod.trava_viva(cx, "SEI-SESAB", CONTA) is not None)
    checar("pegar NÃO a leva antes da espera", at.pegar(cx) is None)
    cx.execute("UPDATE busca SET tentar_apos=? WHERE id=?",
               ((datetime.now(TZ) - timedelta(seconds=1)).isoformat(timespec="seconds"), b))
    cx.commit()
    rodar(b)
    L = linha(b)
    checar("segunda falha: terceira e última tentativa marcada", L["estado"] == "pedida"
           and L["tentativas"] == 2, (L["estado"], L["tentativas"]))
    cx.execute("UPDATE busca SET tentar_apos=? WHERE id=?",
               ((datetime.now(TZ) - timedelta(seconds=1)).isoformat(timespec="seconds"), b))
    cx.commit()
    rodar(b)
    L = linha(b)
    checar(f"esgotadas as {bmod.MAX_EXECUCOES} execuções, falhou com o motivo da última",
           L["estado"] == "falhou" and "infraestrutura" in (L["motivo"] or ""),
           (L["estado"], L["motivo"]))
    checar("e a conta é solta", bmod.trava_viva(cx, "SEI-SESAB", CONTA) is None)

    print("\nC. NAVEGADOR MORTO POR MEMÓRIA É DITO — e é passageiro")
    coletor_falso("os._exit(137)\n")
    b = nova_busca()
    rodar(b)
    L = linha(b)
    checar("processo morto por sinal volta para a fila", L["estado"] == "pedida", L)
    checar("e o motivo fala em memória", "memória" in (L["motivo"] or ""), L["motivo"])
    cx.execute("UPDATE busca SET estado='cancelada' WHERE id=?", (b,))
    cx.execute("DELETE FROM busca_trava")
    cx.commit()

    print("\nD. MOTIVO PERMANENTE DO COLETOR NÃO É REPETIDO")
    coletor_falso(
        "print('BUSCA_OK ' + json.dumps({'busca_id': pedido['busca']['busca_id'], 'itens': [],"
        " 'total_declarado': None, 'mesa_confirmada': 'SESAB/X',"
        " 'motivo': 'nao consegui ativar a mesa pedida: a mesa nao esta entre as unidades',"
        " 'motivo_permanente': True}))\nsys.exit(1)\n")
    b = nova_busca()
    rodar(b)
    L = linha(b)
    checar("mesa que a conta não tem: falhou na primeira, sem repetir",
           L["estado"] == "falhou" and not L["tentativas"], (L["estado"], L["tentativas"]))
    checar("sessão caída no meio É passageira (o próximo processo loga de novo)",
           bool(at._PASSAGEIRA.search("SESSAO caiu durante a busca")))
    checar("filtro recusado NÃO é passageiro",
           not at._PASSAGEIRA.search("o SEI nao aceitou o filtro tipo_processo"))

    print("\nE. O VEREDITO NÃO JOGA FORA O QUE O SEI JÁ DEVOLVEU")
    checar("motivo com itens colhidos é parcial, não falhou",
           bmod.veredito(40, 20, 2, 200, "SESSAO caiu")[0] == "parcial")
    checar("sem total declarado mas com itens é parcial, com o número dito",
           bmod.veredito(None, 7, 1, 200, None) == (
               "parcial", "o SEI não declarou o total de registros; vieram 7, sem como "
                          "conferir se é tudo"))
    checar("sem total e sem itens continua falha (não há o que afirmar)",
           bmod.veredito(None, 0, 1, 200, None)[0] == "falhou")
    checar("total zero declarado é vazia (o JS agora lê 'Nenhum registro')",
           bmod.veredito(0, 0, 1, 200, None)[0] == "vazia")

    print("\nF. FILTRO RECUSADO PELO SEI VIRA PARCIAL DITO, não completa")
    coletor_falso(
        "print('BUSCA_OK ' + json.dumps({'busca_id': pedido['busca']['busca_id'],"
        " 'itens': [{'protocolo': 'P1'}], 'total_declarado': 1,"
        " 'mesa_confirmada': 'SESAB/SAIS/DGGUP/DGESS',"
        " 'filtros_recusados': [{'campo': 'tipo_processo', 'motivo': 'nao casou'}],"
        " 'motivo': None}))\n")
    b = nova_busca()
    rodar(b)
    L = linha(b)
    checar("o resultado sai parcial e nomeia o critério que não foi aplicado",
           L["estado"] == "parcial" and "tipo_processo" in (L["motivo"] or ""),
           (L["estado"], L["motivo"]))

    print("\nG. A VARREDURA NÃO MATA BUSCA VIVA E NÃO DESCARTA RESULTADO TARDIO")
    cx.execute("DELETE FROM busca_trava")
    b = nova_busca()
    velho = (datetime.now(TZ) - timedelta(seconds=bmod.PEGAR_TETO_S + 30)).isoformat(timespec="seconds")
    cx.execute("UPDATE busca SET pedida_em=? WHERE id=?", (velho, b))
    cx.commit()
    _o_vivo, _o_fila = at.vivo, bmod._fila_pode_estar_cheia
    at.vivo = lambda: True
    bmod._fila_pode_estar_cheia = lambda: False
    try:
        bmod.varrer(cx)
        checar("executor neste processo com vaga livre: a busca da fila espera a vez",
               linha(b)["estado"] == "pedida", linha(b)["estado"])
        muito = (datetime.now(TZ) - timedelta(seconds=bmod.FILA_TETO_S + 30)).isoformat(timespec="seconds")
        cx.execute("UPDATE busca SET pedida_em=? WHERE id=?", (muito, b))
        cx.commit()
        bmod.varrer(cx)
        checar("mas fila parada por mais de 15 min é falha dita",
               linha(b)["estado"] == "falhou", linha(b)["estado"])
    finally:
        at.vivo, bmod._fila_pode_estar_cheia = _o_vivo, _o_fila
    cx.execute("DELETE FROM busca_trava")
    b = nova_busca()
    at.pegar(cx)
    orfa = (datetime.now(TZ) - timedelta(seconds=bmod.SEGUNDOS_TETO + bmod.FOLGA_VARREDURA_S + 5)
            ).isoformat(timespec="seconds")
    cx.execute("UPDATE busca SET entregue_em=? WHERE id=?", (orfa, b))
    cx.commit()
    bmod.varrer(cx)
    L = linha(b)
    checar("órfã de executor que morreu volta para a fila em vez de falhar",
           L["estado"] == "pedida" and L["tentativas"] == 1, (L["estado"], L["motivo"]))
    cx.execute("UPDATE busca SET estado='falhou', motivo=? WHERE id=?",
               ("o executor de busca deste servidor não devolveu resultado em 10 min", b))
    cx.commit()
    est, _m = bmod.receber(cx, b, {"itens": [{"protocolo": "P9"}], "total_declarado": 1,
                                   "mesa_confirmada": "SESAB/SAIS/DGGUP/DGESS"})
    checar("resultado que chega depois da falha POR PRAZO é aceito",
           est == "completa" and linha(b)["colhidos"] == 1, (est, _m))
    cx.execute("UPDATE busca SET estado='cancelada' WHERE id=?", (b,))
    cx.commit()
    est, _m = bmod.receber(cx, b, {"itens": [{"protocolo": "P9"}], "total_declarado": 1})
    checar("mas cancelada continua cancelada", est == "cancelada", est)

    print("\nH. O SERVIDOR NÃO ACEITA O QUE NÃO TEM COMO EXECUTAR")
    cx.execute("""INSERT INTO usuarios(email,nome,papel,ativo) VALUES('sem.senha@x','S','servidor',1)""")
    _u2 = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,modo_coleta,sei_login,atualizado_em)
                  VALUES(?,'SEI-SESAB','servidor','sem.senha@x',?)""", (_u2, agora()))
    cx.commit()
    _orig = at.capacidade
    at.capacidade = lambda: (True, None)
    try:
        _ag, _mot, _como = bmod.quem_executa(cx, _u2, instancia="SEI-SESAB")
    finally:
        at.capacidade = _orig
    checar("sem a senha da instalação no cofre, o pedido é recusado na hora",
           _ag is None and "senha" in (_mot or ""), (_ag, _mot))
    checar("e a recusa diz onde resolver", "Configuração" in (_como or ""), _como)

    print("\nI. UMA CONTA DO SEI, TRÊS EXECUTORES — uma trava")
    cx.execute("DELETE FROM busca_trava")
    bmod._travar(cx, "SEI-SESAB", CONTA, None, minutos=30)
    cx.commit()
    _orig = at.capacidade
    at.capacidade = lambda: (True, None)
    try:
        _b, _e, _cur = bmod.pedir(cx, UID, "SEI-SESAB", CONTA, "SESAB/SAIS/DGGUP/DGESS",
                                  {"assunto": "x"})
    finally:
        at.capacidade = _orig
    checar("com a coleta segurando a conta, a busca diz isso — não 'já há uma busca'",
           _b is None and "coleta" in (_e or "") and "já há uma busca" not in (_e or ""), _e)
    cx.execute("DELETE FROM busca_trava")
    cx.commit()

    print("\nJ. TRABALHO PESADO, UM POR VEZ — e a vaga dele não é 'perdida'")
    at._pesado.acquire()
    try:
        checar("com o lock pesado tomado, a coleta não começa",
               cs.rodada(cx) == 0)
        _o_vagas = at.vagas_livres
        at.vagas_livres = lambda: 0
        try:
            pode, motivo = at.capacidade()
            checar("zero vagas com trabalho pesado em curso NÃO é 'vagas perdidas'",
                   "perderam" not in (motivo or ""), motivo)
        finally:
            at.vagas_livres = _o_vagas
    finally:
        at._pesado.release()

    print("\nK. ACOMPANHAMENTO: a tentativa volta quando nada chegou ao SEI")
    os.environ["SEI360_COLETA_SERVIDOR"] = "1"
    acmod.adicionar(cx, UID, "019.7001.2026.0000001-11", "SEI-SESAB")
    cx.commit()
    _chamadas = []
    _exec_real = asv._executar
    asv._executar = lambda u, i, p: (_chamadas.append(p) or (0, 0, "o coletor não devolveu leitura nenhuma"))
    asv._falhas_seguidas.clear()
    try:
        asv.rodada(cx)
        _t = cx.execute("SELECT tentativas FROM acompanhado WHERE usuario_id=?", (UID,)).fetchone()[0]
        checar("a volta rodou", len(_chamadas) == 1, _chamadas)
        checar("volta sem leitura NÃO gasta a tentativa do dia", (_t or 0) == 0, _t)
        asv.rodada(cx)
        checar("e o par espera antes de tentar de novo (não martela a cada 2 min)",
               len(_chamadas) == 1, _chamadas)
        asv._falhas_seguidas.clear()
        _bk = nova_busca()                 # a busca na fila segura a conta
        asv.rodada(cx)
        checar("conta ocupada por busca: o acompanhamento não entra, e não cobra nada",
               len(_chamadas) == 1 and (cx.execute(
                   "SELECT tentativas FROM acompanhado WHERE usuario_id=?", (UID,)).fetchone()[0] or 0) == 0)
        cx.execute("UPDATE busca SET estado='cancelada' WHERE id=?", (_bk,))
        cx.execute("DELETE FROM busca_trava")
        cx.commit()
        asv._executar = lambda u, i, p: (_ for _ in ()).throw(RuntimeError("quebrou"))
        asv._falhas_seguidas.clear()
        _feitas = asv.rodada(cx)
        checar("par que levanta não derruba a passada (e devolve a tentativa)",
               _feitas == 0 and (cx.execute(
                   "SELECT tentativas FROM acompanhado WHERE usuario_id=?", (UID,)).fetchone()[0] or 0) == 0)
        checar("e as travas não ficam presas", not at._pesado.locked()
               and bmod.trava_viva(cx, "SEI-SESAB", CONTA) is None)
    finally:
        asv._executar = _exec_real
        asv._falhas_seguidas.clear()

    print("\nL. A BUSCA ATIVA A MESA PEDIDA ANTES DE PESQUISAR")
    _col = (SCRATCH.parent.parent / "painel_sesab" / "coletor_sesab.py").read_text(encoding="utf-8")
    _i_busca = _col.index("if BUSCAR:")
    _i_pesq = _col.index('SEIBusca.pesquisar(p)', _i_busca)
    _trecho = _col[_i_busca:_i_pesq]
    checar("o modo --buscar troca de unidade (trocarMesa) ANTES da pesquisa",
           "SEIAuto.trocarMesa(m)" in _trecho and "descobrirMesas" in _trecho)
    checar("e recarrega a aba para o cabeçalho refletir a unidade nova",
           "pg.reload(" in _trecho)
    checar("e devolve a conta para onde a pessoa a deixou",
           "SEIAuto.trocarMesa(m).then" in _col[_i_pesq:_i_pesq + 1500])
    checar("mesa que a conta não tem sai como falha PERMANENTE",
           '"motivo_permanente": True' in _trecho)
finally:
    at.COLETOR = _coletor_real
    (SCRATCH / "_coletor_falso_busca.py").unlink(missing_ok=True)

cx.close()
print("\n" + "=" * 62)
print(f"{ok} verificações OK, {mau} falha(s)")
sys.exit(1 if mau else 0)
