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

    print("\nL. A BUSCA ATIVA A MESA PEDIDA ANTES DE PESQUISAR — e devolve a conta")
    _col = (SCRATCH.parent.parent / "painel_sesab" / "coletor_sesab.py").read_text(encoding="utf-8")
    _i_busca = _col.index("if BUSCAR:")
    _i_pesq = _col.index('SEIBusca.pesquisar(p)', _i_busca)
    _trecho = _col[_i_busca:_i_pesq]
    _bloco = _col[_i_busca:_col.index("# Zera os checkpoints.", _i_busca)]
    checar("o modo --buscar troca de unidade (trocarMesa) ANTES da pesquisa",
           "SEIAuto.trocarMesa(m)" in _trecho and "descobrirMesas" in _trecho)
    checar("a origem é ANUNCIADA antes de trocar (MESA_ORIGEM), para sobreviver à morte",
           _trecho.index('print("MESA_ORIGEM "') < _trecho.index("SEIAuto.trocarMesa(m)"))
    checar("e a origem guardada pela primeira execução manda (volta_para)",
           "volta_para" in _trecho)
    checar("navega para o link da unidade NOVA em vez de recarregar a URL velha",
           "pg.goto(_troca[\"url\"]" in _trecho)
    checar("e CONFERE a unidade depois da troca, em vez de só registrar",
           "_N(_agora) != _N(_mesa_pedida)" in _trecho)
    checar("a volta roda num finally — também quando a pesquisa levanta",
           _bloco.index("finally:") < _bloco.index("SEIAuto.trocarMesa(m).then"))
    checar("lista de unidades que não veio (sem ids) NÃO é 'a conta não tem a mesa'",
           "permanente: false" in _trecho and "nao consegui ler as unidades" in _trecho)
    checar("o envelope de falha da troca sai com mesa_confirmada nula",
           '"mesa_confirmada": None' in _trecho)

    print("\nM. A TRAVA TEM DONO — ninguém toma nem solta a de outro")
    cx.execute("DELETE FROM busca_trava")
    cx.commit()
    DONO_COLETA = f"motor:{at.TOKEN}:coleta"
    checar("a coleta toma a conta livre", bmod._travar(cx, "SEI-SESAB", CONTA, None,
                                                        minutos=30, dono=DONO_COLETA))
    cx.commit()
    _bx = cx.execute("""INSERT INTO busca(usuario_id,instancia,conta,mesa,filtros,estado,
                        pedida_em,entregue_em) VALUES(?,?,?,?,?,'entregue',?,?)""",
                     (UID, "SEI-SESAB", CONTA, "SESAB/SAIS/DGGUP/DGESS", "{}", agora(),
                      agora())).lastrowid
    cx.commit()
    checar("a busca NÃO toma a trava viva da coleta",
           bmod._travar(cx, "SEI-SESAB", CONTA, _bx) is False
           and bmod.trava_viva(cx, "SEI-SESAB", CONTA)["dono"] == DONO_COLETA)
    checar("reenfileirar a busca não troca o dono da trava",
           bmod.reenfileirar(cx, _bx, "teste") and
           bmod.trava_viva(cx, "SEI-SESAB", CONTA)["dono"] == DONO_COLETA)
    cx.execute("UPDATE busca SET tentar_apos=NULL WHERE id=?", (_bx,))
    cx.commit()
    checar("pegar NÃO entrega busca cuja conta está com a coleta", at.pegar(cx) is None)
    bmod.receber(cx, _bx, {"itens": [], "total_declarado": 0,
                           "mesa_confirmada": "SESAB/SAIS/DGGUP/DGESS"})
    cx.commit()
    checar("o fim de uma busca não apaga a trava de OUTRO dono",
           (bmod.trava_viva(cx, "SEI-SESAB", CONTA) or {})["dono"] == DONO_COLETA)
    checar("trava de motor de um executor MORTO (outro token) é limpa",
           cx.execute("UPDATE busca_trava SET dono='motor:tokenmorto:coleta'").rowcount == 1
           and bmod.limpar_travas_de_motor(cx, at.TOKEN) == 1
           and bmod.trava_viva(cx, "SEI-SESAB", CONTA) is None)
    checar("e a do executor vivo, não",
           bmod._travar(cx, "SEI-SESAB", CONTA, None, minutos=30, dono=DONO_COLETA)
           and bmod.limpar_travas_de_motor(cx, at.TOKEN) == 0)
    checar("soltar_conta solta pelo dono, com conexão própria",
           (cx.commit() or True) and bmod.soltar_conta("SEI-SESAB", CONTA, None, DONO_COLETA)
           and bmod.trava_viva(cx, "SEI-SESAB", CONTA) is None)
    b = nova_busca()
    _r = at.pegar(cx)
    _t = bmod.trava_viva(cx, "SEI-SESAB", CONTA)
    checar("pegar RENOVA a trava a partir da entrega, e com o dono certo",
           _r and _t and _t["busca_id"] == b
           and _t["ate"] > (datetime.now(TZ) + timedelta(minutes=bmod.SEGUNDOS_TETO // 60 + 2)
                            ).isoformat(timespec="seconds"), dict(_t) if _t else None)
    cx.execute("UPDATE busca SET estado='cancelada' WHERE id=?", (b,))
    cx.execute("DELETE FROM busca_trava")
    cx.commit()

    print("\nN. VARREDURA E CANCELAMENTO NÃO DESFAZEM O QUE O OUTRO ACABOU DE FAZER")
    b = nova_busca()
    at.pegar(cx)
    _velha = (datetime.now(TZ) - timedelta(seconds=bmod.SEGUNDOS_TETO + bmod.FOLGA_VARREDURA_S + 5)
              ).isoformat(timespec="seconds")
    cx.execute("UPDATE busca SET entregue_em=? WHERE id=?", (_velha, b))
    cx.commit()
    import banco as _banco_n

    class _CxComCorrida:
        """Uma conexão que, logo depois de listar as órfãs, deixa OUTRA varredura agir."""
        def __init__(self, real):
            self.real, self.feito = real, False

        def execute(self, sql, *a):
            cur = self.real.execute(sql, *a)
            if not self.feito and "estado IN ('entregue','em_curso')" in sql and sql.lstrip().startswith("SELECT"):
                linhas = cur.fetchall()
                self.feito = True
                outra = _banco_n.conectar()
                bmod.reenfileirar(outra, b, "a outra varredura chegou antes")
                outra.commit()
                outra.close()
                return type("C", (), {"fetchall": lambda _s: linhas})()
            return cur

        def __getattr__(self, n):
            return getattr(self.real, n)

    bmod.varrer(_CxComCorrida(cx))
    cx.commit()
    L = linha(b)
    checar("a segunda varredura não grava 'falhou' por cima da nova tentativa da primeira",
           L["estado"] == "pedida" and L["tentativas"] == 1, (L["estado"], L["motivo"]))
    checar("e a trava da busca continua", bmod.trava_viva(cx, "SEI-SESAB", CONTA) is not None)
    checar("cancelar a busca que voltou para a fila solta a conta",
           bmod.cancelar(cx, b, UID) and (cx.commit() or True)
           and bmod.trava_viva(cx, "SEI-SESAB", CONTA) is None)

    print("\nO. CLASSIFICAÇÃO: o que se repete e o que não")
    checar("arquivo do motor ausente (código 4) NÃO é passageiro",
           at._causa(4, "ERRO: nao achei /app/painel_sesab/pesquisa_sei.js")[1] is False)
    checar("rede caída (código 4) continua passageira",
           at._causa(4, "ERRO DE INFRAESTRUTURA: net::ERR_CONNECTION_RESET")[1] is True)
    coletor_falso("print('BUSCA_OK {\"busca_id\": 1, \"itens\": [{\"protoc')\nsys.exit(0)\n")
    b = nova_busca()
    rodar(b)
    L = linha(b)
    checar("envelope cortado no pipe é passageiro e diz 'ilegível'",
           L["estado"] == "pedida" and "ilegível" in (L["motivo"] or ""), (L["estado"], L["motivo"]))
    cx.execute("UPDATE busca SET estado='cancelada' WHERE id=?", (b,))
    cx.execute("DELETE FROM busca_trava")
    cx.commit()

    print("\nP. A ORIGEM DA MESA SOBREVIVE À EXECUÇÃO QUE MORREU")
    _visto_pedido = SCRATCH / "_pedido_visto.json"
    coletor_falso(
        "open(r'" + str(_visto_pedido) + "', 'w', encoding='utf-8').write(json.dumps(pedido))\n"
        "print('MESA_ORIGEM SESAB/SAIS/DGGUP/DGESS/ORIGEM', flush=True)\n"
        "print('ERRO DE INFRAESTRUTURA: Target closed')\nsys.exit(4)\n")
    b = nova_busca()
    rodar(b)
    L = linha(b)
    checar("a origem anunciada fica gravada mesmo com o coletor morrendo depois",
           L["mesa_origem"] == "SESAB/SAIS/DGGUP/DGESS/ORIGEM", L["mesa_origem"])
    cx.execute("UPDATE busca SET tentar_apos=NULL WHERE id=?", (b,))
    cx.commit()
    rodar(b)
    _ped = json.loads(_visto_pedido.read_text(encoding="utf-8"))
    checar("e a tentativa seguinte recebe essa origem para devolver a conta",
           _ped["busca"].get("volta_para") == "SESAB/SAIS/DGGUP/DGESS/ORIGEM", _ped["busca"])
    checar("o pedido leva o prazo do motor, para busca grande virar parcial",
           (_ped["busca"].get("prazo_ms") or 0) > 0)
    _visto_pedido.unlink(missing_ok=True)
    cx.execute("UPDATE busca SET estado='cancelada' WHERE id=?", (b,))
    cx.execute("DELETE FROM busca_trava")
    cx.commit()

    print("\nQ. O MOTIVO DA TROCA QUE FALHOU NÃO É TROCADO PELA FRASE ANTIGA")
    coletor_falso(
        "print('BUSCA_OK ' + json.dumps({'busca_id': pedido['busca']['busca_id'], 'itens': [],"
        " 'total_declarado': None, 'mesa_confirmada': None,"
        " 'motivo': 'nao consegui ativar a mesa pedida: a mesa X nao esta entre as unidades desta conta no SEI',"
        " 'motivo_permanente': True}))\nsys.exit(1)\n")
    b = nova_busca()
    rodar(b)
    L = linha(b)
    checar("a pessoa lê que não conseguiu ativar a mesa, e não 'a mesa ativa no SEI é X'",
           "nao consegui ativar" in (L["motivo"] or "") and "mesa ativa no SEI" not in (L["motivo"] or ""),
           L["motivo"])
    checar("mesmo com mesa_confirmada divergente e sem itens, o motivo do coletor manda",
           bmod.receber(cx, nova_busca(), {"itens": [], "total_declarado": None,
                                           "mesa_confirmada": "SESAB/OUTRA",
                                           "motivo": "SESSAO caiu durante a busca"})[1]
           == "SESSAO caiu durante a busca")
    cx.execute("DELETE FROM busca_trava")
    cx.commit()

    print("\nR. ACOMPANHAMENTO: falha do PROCESSO conta; falha da VOLTA não")
    asv._falhas_seguidas.clear()
    cx.execute("UPDATE acompanhado SET tentativas=0, tentativa_em=NULL, lido_em=NULL WHERE usuario_id=?",
               (UID,))
    cx.commit()
    _ex_real2 = asv._executar
    asv._executar = lambda u, i, p: (0, 0, "a busca devolveu 2 linha(s), nenhuma com este numero", True)
    try:
        asv.rodada(cx)
        _t = cx.execute("SELECT tentativas FROM acompanhado WHERE usuario_id=? AND protocolo=?",
                        (UID, "019.7001.2026.0000001-11")).fetchone()[0]
        checar("o SEI respondeu com falha do processo: a tentativa FICA (o item descansa depois de 3)",
               _t == 1, _t)
        checar("e o par não entra em espera por isso",
               (UID, "SEI-SESAB") not in asv._falhas_seguidas, asv._falhas_seguidas)
        asv._executar = lambda u, i, p: (0, 0, "o coletor não devolveu leitura nenhuma", False)
        import time as _time_r
        asv._falhas_seguidas[(UID, "SEI-SESAB")] = (3, _time_r.time() + 3600,
                                                   datetime.now(TZ).date(),
                                                   (datetime.now(TZ) - timedelta(minutes=5)
                                                    ).isoformat(timespec="seconds"))
        acmod.adicionar(cx, UID, "019.7002.2026.0000002-22", "SEI-SESAB")
        cx.commit()
        _antes = len(asv._falhas_seguidas)
        _n = asv.rodada(cx)
        checar("item recém colado não fica refém da espera do par ('ao adicionar')", _n == 1, _n)
        asv._falhas_seguidas[(UID, "SEI-SESAB")] = (5, _time_r.time() + 3600,
                                                   (datetime.now(TZ) - timedelta(days=1)).date(),
                                                   agora())
        cx.execute("UPDATE acompanhado SET estado='lido', lido_em=NULL WHERE usuario_id=?", (UID,))
        cx.commit()
        asv.rodada(cx)
        checar("a espera de ONTEM não vale hoje", (asv._falhas_seguidas.get((UID, "SEI-SESAB")) or (0,))[0] <= 1,
               asv._falhas_seguidas.get((UID, "SEI-SESAB")))
    finally:
        asv._executar = _ex_real2
        asv._falhas_seguidas.clear()
    print("\nS. O EXECUTOR É REELEITO — quem perdeu a vez na subida continua candidato")
    # Medido em produção em 15/09/2026: 15 de 15 consultas a /saude sem executor vivo.
    # A eleição era uma só, no import: se a trava estava com outro processo naquele
    # instante (o container antigo durante o redeploy), ninguém tentava de novo, e
    # toda busca morria em 90 s. Aqui um processo SEPARADO segura a trava, e solta.
    import subprocess as _sp_s
    import time as _time_s
    _trava_s = banco.DADOS_DIR / ".atendente.lock"
    _sentinela = SCRATCH / "_segura_trava.sentinela"
    _sentinela.write_text("x", encoding="utf-8")
    _script = SCRATCH / "_segura_trava.py"
    _script.write_text(
        "import os, sys, time\n"
        f"p = r'{_trava_s}'\n"
        f"s = r'{_sentinela}'\n"
        "fd = os.open(p, os.O_CREAT | os.O_RDWR)\n"
        "if os.name == 'nt':\n"
        "    import msvcrt; msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)\n"
        "else:\n"
        "    import fcntl; fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "print('SEGURANDO', flush=True)\n"
        "while os.path.exists(s):\n"
        "    time.sleep(0.1)\n", encoding="utf-8")
    _dono = _sp_s.Popen([sys.executable, str(_script)], stdout=_sp_s.PIPE, text=True)
    _o_cand, _o_env = at.CANDIDATO_S, os.environ.get("SEI360_ATENDENTE")
    _o_cap_s = at.capacidade
    _subiram = []
    try:
        checar("(cena) outro processo segura a vez", _dono.stdout.readline().strip() == "SEGURANDO")
        at.CANDIDATO_S = 0.5
        os.environ["SEI360_ATENDENTE"] = "1"
        at.capacidade = lambda: (False, "teste: sem navegador")   # o laço sobe, mas não executa
        at.ao_assumir(lambda: _subiram.append("coleta"))
        checar("na subida, a vez está com outro: este worker não é o executor",
               at.iniciar() is False and at.vivo() is False)
        checar("mas fica candidato", bool(at._candidato and at._candidato.is_alive()))
        _sentinela.unlink()
        _dono.wait(timeout=10)
        for _ in range(40):
            if at.vivo():
                break
            _time_s.sleep(0.25)
        checar("quando a vez se solta, o candidato ASSUME — sem reiniciar nada", at.vivo())
        checar("e quem pega carona no executor (coleta, acompanhamento) sobe junto",
               _subiram == ["coleta"], _subiram)
    finally:
        at._laco_vivo.clear()
        if _sentinela.exists():
            _sentinela.unlink()
        try:
            _dono.kill()
        except Exception:                                      # noqa: BLE001
            pass
        at.CANDIDATO_S = _o_cand
        at.capacidade = _o_cap_s
        at._soltar_a_vez()
        if _o_env is None:
            os.environ.pop("SEI360_ATENDENTE", None)
        else:
            os.environ["SEI360_ATENDENTE"] = _o_env
        at._ao_assumir.clear()
        _script.unlink(missing_ok=True)
    checar("/saude diz se há executor NO CONTAINER, não só neste worker",
           '"executor_no_container": _at.ha_executor()' in
           (SCRATCH / "app.py").read_text(encoding="utf-8"))
finally:
    at.COLETOR = _coletor_real
    (SCRATCH / "_coletor_falso_busca.py").unlink(missing_ok=True)

cx.close()
print("\n" + "=" * 62)
print(f"{ok} verificações OK, {mau} falha(s)")
sys.exit(1 if mau else 0)
