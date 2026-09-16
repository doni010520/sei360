# -*- coding: utf-8 -*-
"""
O LOG DE CADA EXECUÇÃO, A CAUSA LEGÍVEL E A SENHA QUE O SEI RECUSOU.

Em 16/09/2026, com o /admin aberto, três perguntas não tinham resposta:

  * por que a coleta da Letícia falha? Código 3, e a cauda de 300 caracteres
    guardada era o banner do motor JS. O SEI tinha dito o motivo na tela de login;
    ninguém guardou. Foram cinco logins recusados seguidos na conta dela — três
    cliques em "Testar acesso" e duas tentativas da coleta, a um minuto uma da outra;
  * a UMA-CMA caiu de 298 para 205 de verdade? A saída do coletor dizia "a tela
    declara N" por lista, e foi jogada fora;
  * por que a coleta do Lucas (FESF) parou? Um clique no passo "sistema" da SESAB
    criou uma configuração sem senha, que virou a "mais recente".

Esta suíte prende o conserto das três, e o que veio junto:

    python teste_log_execucao.py
"""
import contextlib
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta

from ambiente_teste import isolar

isolar(__file__, copiar=False)
import base64 as _b64
os.environ.setdefault("SEI360_CHAVE_MESTRA",
                      _b64.b64encode(b"chave-de-teste-32-bytes-!!!!!!!!").decode())
os.environ["SEI360_ATENDENTE"] = "0"
os.environ["SEI360_COLETA_SERVIDOR"] = "1"
sys.stdout.reconfigure(encoding="utf-8")

import banco                                                     # noqa: E402
banco.migrar()
import cofre                                                     # noqa: E402
import diario                                                    # noqa: E402
import leitura_saida as ls                                       # noqa: E402
from banco import TZ, agora, conectar                            # noqa: E402

ok = mau = 0


def checar(nome, cond, viu=None):
    global ok, mau
    if cond:
        ok += 1
        print(f"  ok    {nome}")
    else:
        mau += 1
        print(f"  FALHA {nome}" + (f"  -> {viu}" if viu is not None else ""))


# O que o coletor imprime quando o SEI recusa a senha — no formato real do log:
# relógio, `page>` com o `%c` e o estilo grudados, o banner do motor JS no fim.
SAIDA_RECUSA = """[04:08:02] instalacao: SEI-SESAB (SEI 5.0.4)
[04:08:03] orgao selecionado: GOVBA
[04:08:03] credencial recebida por stdin (leticia.teste@saude.ba.gov.br)
[04:08:03] acionando SEIAuto.garantirSessao()
[04:08:03]   page> %c[SEI] enviando login… color:#0f5257;font-weight:bold
[04:08:05]   dialog> alert: Usuário ou senha inválida.
[04:09:03] LOGIN_SEI_DISSE {"textos": [], "captcha": false, "codigo": false, "url": "/sip/login.php"}
[04:09:04] LOGIN NAO CONCLUIU em 60s — ver _coletas/falha_login.png
[04:09:04]   page> %c[SEI] ▶ SEIAuto.custo() mostra o volume de rede por execucao. color:#666a72;font-weight:bold
"""

print("A. A SAÍDA INTEIRA FICA NO VOLUME — sem segredo e sem o resultado de ninguém")
_txt = (SAIDA_RECUSA
        + "senha: \"segredo-que-nao-pode\" e pwdSenha=outro-segredo\n"
        + "GET /controlador.php?infra_hash=abcdef123456\n"
        + 'BUSCA_OK {"busca_id": 1, "itens": [{"especificacao": "nome de paciente"}]}\n')
_nome = diario.guardar_saida("coleta", 901, _txt)
_lido = diario.ler_saida("coleta", 901) or ""
checar("grava e devolve pelo id da execução", _nome == "coleta-901.log" and "LOGIN NAO" in _lido,
       (_nome, _lido[:80]))
checar("a frase do SEI fica LEGÍVEL (o filtro de segredo não come 'senha inválida')",
       "Usuário ou senha inválida." in _lido, [l for l in _lido.splitlines() if "dialog" in l])
checar("valor depois de 'senha:' não fica", "segredo-que-nao-pode" not in _lido)
checar("nem o do campo pwdSenha", "outro-segredo" not in _lido)
checar("nem o infra_hash da sessão", "abcdef123456" not in _lido)
checar("o envelope do resultado é omitido, com o tamanho dito",
       "nome de paciente" not in _lido and "BUSCA_OK <envelope omitido" in _lido)
checar("identificador vira nome de arquivo seguro, sem subir diretório",
       diario.arquivo_saida("coleta", "../../etc").name == "coleta-etc.log",
       diario.arquivo_saida("coleta", "../../etc").name)
checar("execução sem saída guardada devolve None", diario.ler_saida("coleta", 99999) is None)
_velho = diario.arquivo_saida("coleta", 902)
diario.guardar_saida("coleta", 902, "saída antiga")
_antigo = time.time() - (diario.DIAS + 2) * 86400
os.utime(_velho, (_antigo, _antigo))
_n, _b = diario.limpar(simular=True)
checar("o expurgo enxerga a saída vencida sem apagar no simulado",
       _n >= 1 and _velho.exists(), (_n, _velho.exists()))
diario.limpar()
checar("e apaga a vencida, mantendo a de hoje",
       not _velho.exists() and diario.arquivo_saida("coleta", 901).exists())

print("\nB. A CAUSA — o que o SEI disse, e o que ele NÃO disse")
c = ls.causa(3, SAIDA_RECUSA)
checar("alerta 'senha inválida' é recusa CERTA", c["chave"] == "login_recusado" and c["certeza"], c)
checar("e a frase do SEI vai no texto", "Usuário ou senha inválida." in c["texto"], c["texto"])
_disse = ('[04:09:03] LOGIN_SEI_DISSE {"textos": ["Informe o código de autenticação enviado"], '
          '"captcha": false, "codigo": true, "url": "/sip/login.php"}\n')
checar("campo de código na tela é segundo fator",
       ls.causa(3, _disse)["chave"] == "segundo_fator")
checar("CAPTCHA na tela é CAPTCHA",
       ls.causa(3, '[x] LOGIN_SEI_DISSE {"textos": [], "captcha": true, "codigo": false}')["chave"]
       == "captcha")
checar("senha expirada tem causa própria (não é 'bloqueada')",
       ls.causa(3, '[x] LOGIN_SEI_DISSE {"textos": ["Senha expirada. Altere sua senha."]}')["chave"]
       == "senha_expirada")
checar("conta bloqueada é conta bloqueada",
       ls.causa(3, "[x]   dialog> alert: Usuário bloqueado por excesso de tentativas")["chave"]
       == "conta_bloqueada")
# A ARMADILHA DOCUMENTADA em automacao_sei.js: a tela de login do SEI Bahia fala de
# "Autenticação em dois fatores" em TODO acesso. Texto fixo da tela não é pedido de código.
_fixo = ("[x]   page> %c[SEI] Autenticação em dois fatores disponível color:#0f5257;font-weight:bold\n"
         "[x] LOGIN NAO CONCLUIU em 60s\n")
c = ls.causa(3, _fixo)
checar("texto fixo 'dois fatores' NÃO vira segundo fator", c["chave"] == "login_sem_resposta", c)
checar("login sem mensagem nenhuma é INCERTO", c["certeza"] is False, c)
checar("sem senha guardada é outra coisa (não é login)",
       ls.causa(3, "nenhuma credencial guardada para o usuário 7 em SEI-SESAB")["chave"]
       == "sem_credencial")
checar("relógio", ls.causa(5, "morto pelo relógio após 30 min")["chave"] == "relogio")
checar("processo morto por sinal é memória", ls.causa(-9, "")["chave"] == "memoria"
       and ls.causa(137, "")["chave"] == "memoria")
checar("código 4 é infraestrutura, com a última linha útil",
       ls.causa(4, "[x] ERRO: nao achei pesquisa_sei.js\n")["chave"] == "infra"
       and "pesquisa_sei.js" in ls.causa(4, "[x] ERRO: nao achei pesquisa_sei.js\n")["texto"])
_alerta = "[x]   page> %c[SEI] ATENCAO: 1 mesa(s) falhou: SESAB/UMA color:#a3391f;font-weight:bold\n"
checar("código 1 com mesa que falhou é 'coletou com alerta', citando a mesa",
       ls.causa(1, _alerta)["chave"] == "ok_com_alerta" and "SESAB/UMA" in ls.causa(1, _alerta)["texto"])
checar("código 0 limpo é ok", ls.causa(0, "[x] exportado: 75\n")["chave"] == "ok")
_res = ls.resumo(None, ls.causa(3, SAIDA_RECUSA), SAIDA_RECUSA)
checar("o resumo COMEÇA pela causa — não pelo banner",
       _res.startswith("não publicado · o SEI recusou") and "SEIAuto.custo" not in _res.split(" ‖ ")[0],
       _res[:120])
checar("e o login por extenso não entra no resumo (o /admin mostra login mascarado)",
       "leticia.teste@" not in _res, _res)

print("\nC. POR MESA — a prova que decide um snapshot retido por queda")
_listagem = """[07:31:00]   page> %c[SEI] trocando para SESAB/UMA-CMA… color:#0f5257;font-weight:bold
[07:31:09]   page> %c[SEI]   Detalhado: 205 linha(s) em 3 pagina(s) (a tela declara 205) color:#0f5257;font-weight:bold
[07:31:10]   page> %c[SEI] trocando para SESAB/DGESS… color:#0f5257;font-weight:bold
[07:31:12]   page> %c[SEI] Detalhado: a tela declara 20 processo(s) e a leitura trouxe 15 — leitura INCOMPLETA desta lista color:#a3391f;font-weight:bold
[07:31:12]   page> %c[SEI]   Detalhado: 15 linha(s) em 1 pagina(s) (a tela declara 20) color:#0f5257;font-weight:bold
[07:40:00]   page> %c[SEI] trocando para SESAB/UMA-CMA… color:#0f5257;font-weight:bold
[07:40:01]   page> %c[SEI]   Detalhado: 999 linha(s) em 9 pagina(s) (a tela declara 999) color:#0f5257;font-weight:bold
"""
pm = ls.por_mesa(_listagem)
checar("a mesa que fechou: declarou 205, leu 205",
       pm.get("SESAB/UMA-CMA", {}).get("declaradas") == 205
       and pm["SESAB/UMA-CMA"]["lidas"] == 205 and not pm["SESAB/UMA-CMA"]["incompleta"], pm)
checar("a mesa que veio pela metade é marcada incompleta",
       pm.get("SESAB/DGESS", {}).get("incompleta") is True
       and pm["SESAB/DGESS"]["declaradas"] == 20, pm.get("SESAB/DGESS"))
checar("a segunda passada (fase de detalhe) não soma na contagem da listagem",
       pm["SESAB/UMA-CMA"]["lidas"] == 205, pm["SESAB/UMA-CMA"])

# ------------------------------------------------------------------ fixture
import coleta_servidor as cs                                     # noqa: E402
import perfil_sei                                                # noqa: E402

cx = conectar()


def usuario(email, papel="servidor", senha=None):
    import seguranca as seg
    h, sal = seg.hash_senha(senha) if senha else (None, None)
    cx.execute("""INSERT INTO usuarios(email,nome,papel,ativo,senha_hash,senha_sal,criado_em,
                  senha_trocada_em) VALUES(?,?,?,1,?,?,?,?)""",
               (email, email.split("@")[0], papel, h, sal, agora(), agora()))
    return cx.execute("SELECT last_insert_rowid()").fetchone()[0]


def config(uid, sistema, quando=None, senha=True):
    cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,modo_coleta,sei_login,
                  atualizado_em) VALUES(?,?,'servidor',?,?)""",
               (uid, sistema, f"login.{uid}", quando or agora()))
    if senha:
        cx.execute("""INSERT OR REPLACE INTO credencial(usuario_id,sistema,login,segredo,nonce,
                      algo,criado_em,usos) VALUES(?,?,?,?,?,'teste',?,0)""",
                   (uid, sistema, f"login.{uid}", b"x", b"x", agora()))


def agente(uid, unidades=("SESAB/SAIS/DGGUP/DGESS",), janelas=("00:00",), tolerancia=600):
    cx.execute("""INSERT INTO agentes(nome_estacao,dono_usuario_id,unidades_esperadas,ativo,
                  criado_em) VALUES(?,?,?,1,?)""",
               (f"SERVIDOR/teste{uid}", uid, json.dumps(list(unidades)), agora()))
    aid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    cx.execute("""INSERT INTO agendamento(agente_id,janelas,dias,tolerancia_min,
                  max_entregas_janela,ativo) VALUES(?,?,'todos',?,3,1)""",
               (aid, json.dumps(list(janelas)), tolerancia))
    return aid


def janela_passada():
    """Uma janela vencida HÁ POUCO, dentro da tolerância: o desvio por agente
    soma até 60 min ao horário, então 2 h atrás (ou 00:00 de madrugada)."""
    agora_dt = datetime.now(TZ)
    return (agora_dt - timedelta(hours=2)).strftime("%H:%M") if agora_dt.hour >= 2 else "00:00"


print("\nD. A INSTALAÇÃO COLETADA É A QUE TEM SENHA — não a configurada por último")
uL = usuario("lucas.teste@fesfsus.ba.gov.br")
config(uL, "SEI-FESF", quando="2026-09-09T18:25:47-03:00", senha=True)
config(uL, "SEI-SESAB", quando="2026-09-15T16:20:19-03:00", senha=False)
aL = agente(uL, unidades=("FESF/DIGAS/HECC/GAF",), janelas=(janela_passada(),))
cx.commit()
ex, janela, inst, _p = cs._decidir(cx, aL)
cx.commit()
checar("a FESF (com senha) é coletada, mesmo com a SESAB (sem senha) mais recente",
       ex is not None and inst == "SEI-FESF", (ex, janela, inst))
uI = usuario("igor.teste@fesfsus.ba.gov.br")
config(uI, "SEI-FESF", senha=False)
aI = agente(uI, janelas=(janela_passada(),))
cx.commit()
_antes = cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=?", (aI,)).fetchone()[0]
r = cs._decidir(cx, aI)
cx.commit()
checar("sem senha em lugar nenhum: recusa dizendo o que fazer",
       r[0] is None and "sem senha" in r[1] and "Configuração" in r[1], r)
checar("e NÃO grava execução 'bloqueada' (era uma por janela, todo dia)",
       cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=?", (aI,)).fetchone()[0] == _antes)

print("\nE. SEM ESCOPO NÃO SE COLETA — só sobraria o efeito colateral no SEI")
uV = usuario("vazio.teste@saude.ba.gov.br")
config(uV, "SEI-SESAB")
aV = agente(uV, unidades=(), janelas=(janela_passada(),))
cx.commit()
r = cs._decidir(cx, aV)
checar("agente sem unidade no escopo não recebe entrega", r[0] is None and "sem escopo" in r[1], r)
checar("e a situação do /admin diz 'parado'", cs.situacao(cx, aV)["estado"] == "parado",
       cs.situacao(cx, aV))

print("\nF. LOGIN RECUSADO: a execução diz por quê, a senha é marcada e ninguém tenta de novo")
uR = usuario("leticia.teste@saude.ba.gov.br", senha="senha-do-sei360-teste-1")
config(uR, "SEI-SESAB")
aR = agente(uR, janelas=(janela_passada(),))
cx.commit()
exR, janR, instR, _ = cs._decidir(cx, aR)
cx.commit()
_coletar_real = cs._coletar
cs._coletar = lambda uid, inst: (3, SAIDA_RECUSA)
_buf = io.StringIO()
try:
    with contextlib.redirect_stdout(_buf):
        cs._executar(aR, exR, janR, instR)
finally:
    cs._coletar = _coletar_real
L = dict(cx.execute("SELECT * FROM execucao WHERE id=?", (exR,)).fetchone())
checar("estado 'bloqueada' e causa em chave", L["estado"] == "bloqueada"
       and L["causa"] == "login_recusado", (L["estado"], L["causa"]))
checar("o resumo começa pelo que o SEI disse",
       (L["log_resumo"] or "").startswith("não publicado · o SEI recusou")
       and "Usuário ou senha inválida." in L["log_resumo"], (L["log_resumo"] or "")[:160])
checar("a saída inteira ficou guardada com o id da execução",
       "LOGIN_SEI_DISSE" in (diario.ler_saida("coleta", exR) or ""))
checar("e o fim da execução foi DITO no log do servidor, uma linha, com a causa",
       f"execução {exR}" in _buf.getvalue() and "o SEI recusou" in _buf.getvalue(), _buf.getvalue())
checar("a senha fica marcada como recusada pelo SEI",
       cofre.recusa(cx, uR, "SEI-SESAB") is not None, cofre.recusa(cx, uR, "SEI-SESAB"))
_al = cx.execute("SELECT texto FROM alerta WHERE tipo='login_falhou' AND execucao_id=?",
                 (exR,)).fetchone()
checar("o /admin ganha UM alerta, com o nome do agente e a consequência",
       _al and f"SERVIDOR/teste{uR}" in _al["texto"] and "PARADA" in _al["texto"],
       _al["texto"] if _al else None)
_n0 = cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=?", (aR,)).fetchone()[0]
r = cs._decidir(cx, aR)
cx.commit()
checar("a próxima passada NÃO tenta de novo — nem na mesma janela, nem em outra",
       r[0] is None and "recusou a senha" in r[1], r)
checar("e não grava execução nova",
       cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=?", (aR,)).fetchone()[0] == _n0)
checar("a situação do agente mostra a recusa", cs.situacao(cx, aR)["estado"] == "parado"
       and "recusou" in cs.situacao(cx, aR)["texto"], cs.situacao(cx, aR))

print("\nG. SALVAR A SENHA DE NOVO desfaz a marca e reabre a janela")
if cofre.disponivel():
    time.sleep(1.1)                     # `agora()` tem resolução de segundo
    cofre.guardar(cx, uR, "SEI-SESAB", f"login.{uR}", "senha-corrigida")
    cx.commit()
    checar("guardar apaga a recusa", cofre.recusa(cx, uR, "SEI-SESAB") is None)
    r = cs._decidir(cx, aR)
    cx.commit()
    checar("e a mesma janela volta a ser devida — quem corrigiu às 8h não espera amanhã",
           r[0] is not None, r)
    if r[0]:
        cx.execute("UPDATE execucao SET estado='concluida', causa='ok', terminado_em=? WHERE id=?",
                   (agora(), r[0]))
        cx.commit()
else:
    checar("cofre disponível para a cena de salvar de novo", False, "sem cryptography/chave")

print("\nH. LOGIN SEM RESPOSTA (incerto): não marca a senha, e não repete NA MESMA janela")
uS = usuario("lento.teste@saude.ba.gov.br")
config(uS, "SEI-SESAB")
aS = agente(uS, janelas=("01:00", "13:00"))
cx.commit()
_hoje = datetime.now(TZ)
_t1 = _hoje.replace(hour=3, minute=0, second=0, microsecond=0)
exS, janS, instS, _ = cs._decidir(cx, aS, _t1)
cx.commit()
cs._coletar = lambda uid, inst: (3, "[x] LOGIN NAO CONCLUIU em 60s\n")
try:
    with contextlib.redirect_stdout(io.StringIO()):
        cs._executar(aS, exS, janS, instS)
finally:
    cs._coletar = _coletar_real
checar("(cena) a execução saiu como login sem resposta",
       cx.execute("SELECT causa FROM execucao WHERE id=?", (exS,)).fetchone()[0]
       == "login_sem_resposta")
checar("recusa incerta NÃO marca a senha (pode ter sido o SEI lento)",
       cofre.recusa(cx, uS, "SEI-SESAB") is None)
checar("e o alerta diz que a próxima tentativa é a janela seguinte",
       "janela seguinte" in (cx.execute("SELECT texto FROM alerta WHERE execucao_id=?",
                                        (exS,)).fetchone() or {"texto": ""})["texto"])
r = cs._decidir(cx, aS, _t1 + timedelta(minutes=5))
checar("um minuto depois, na MESMA janela: não repete (foi o 04:08 → 04:10 de 16/09)",
       r[0] is None and "não repito" in r[1], r)
r = cs._decidir(cx, aS, _hoje.replace(hour=15, minute=0, second=0, microsecond=0))
cx.commit()
checar("na janela seguinte, tenta de novo", r[0] is not None and r[1].endswith("13:00:00-03:00"), r)

print("\nI. A MARCA VALE PARA OS OUTROS MOTORES — busca e acompanhamento")
import atendente as at                                           # noqa: E402
import busca as bmod                                             # noqa: E402
cofre.marcar_recusa(cx, uS, "SEI-SESAB", "o SEI recusou o usuário ou a senha. (teste)")
cx.commit()
_cap = at.capacidade
at.capacidade = lambda: (True, None)
try:
    exe, motivo, dica = bmod.quem_executa(cx, uS, instancia="SEI-SESAB")
finally:
    at.capacidade = _cap
checar("a busca recusa na hora, citando a recusa do SEI e o que fazer",
       exe is None and "recusou" in (motivo or "") and "Salve a senha" in (dica or ""),
       (motivo, dica))
import acompanhamento as acmod                                   # noqa: E402
import acompanhamento_servidor as asv                            # noqa: E402
acmod.adicionar(cx, uS, "019.5001.2026.0000009-99", "SEI-SESAB")
cx.commit()
_chamou = []
_exec_real = asv._executar
asv._executar = lambda *a: (_chamou.append(a) or (0, 0, None, True))
_buf2 = io.StringIO()
try:
    with contextlib.redirect_stdout(_buf2):
        asv.rodada(cx)
finally:
    asv._executar = _exec_real
checar("o acompanhamento não sobe navegador com a senha recusada", _chamou == [], _chamou)
checar("e diz por quê, uma vez", "recusou a senha" in _buf2.getvalue(), _buf2.getvalue())

print("\nJ. JANELA PERDIDA DO AGENTE DO SERVIDOR — que antes não era registrada")
import app as A                                                  # noqa: E402
uP = usuario("perdida.teste@saude.ba.gov.br")
config(uP, "SEI-SESAB")
aP = agente(uP, janelas=("00:00",), tolerancia=10)
uN = usuario("semsenha.teste@saude.ba.gov.br")
config(uN, "SEI-SESAB", senha=False)
aN = agente(uN, janelas=("00:00",), tolerancia=10)
cx.commit()
import janelas as jan                                            # noqa: E402
_base = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
_vence = _base + timedelta(minutes=jan.desvio_do_agente(aP) + 10)
A.janelas_perdidas(cx)
cx.commit()
_perdidaP = cx.execute("SELECT id FROM execucao WHERE agente_id=? AND estado='perdida'",
                       (aP,)).fetchone()
if datetime.now(TZ) > _vence:
    checar("agente do servidor SEM token, apto a coletar: a janela vira 'perdida'",
           _perdidaP is not None)
    _txt_al = (cx.execute("SELECT texto FROM alerta WHERE execucao_id=?",
                          (_perdidaP["id"],)).fetchone() or {"texto": ""})["texto"] if _perdidaP else ""
    checar("e o alerta nomeia o agente e culpa o motor — não uma 'estação desligada'",
           f"SERVIDOR/teste{uP}" in _txt_al and "motor do servidor" in _txt_al
           and "estação desligada" not in _txt_al, _txt_al)
else:
    checar(f"janela que ainda não venceu (vence {_vence:%H:%M}) não é cobrada", _perdidaP is None)
checar("agente PARADO (sem senha) não ganha janela perdida todo dia",
       cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=?", (aN,)).fetchone()[0] == 0)

print("\nK. AS TELAS — admin vê causa, mesas e a saída; a pessoa vê a recusa")
A.app.config["TESTING"] = True
_adm = usuario("admin.teste@sei360.local", papel="admin", senha="senha-admin-teste-123")
cx.commit()


def entrar(email, senha):
    c = A.app.test_client()
    c.get("/entrar")
    tok = c.get_cookie("sei360_csrf")
    c.post("/entrar", data={"email": email, "pw": senha, "csrf": tok.value if tok else ""})
    return c


ca = entrar("admin.teste@sei360.local", "senha-admin-teste-123")
r = ca.get(f"/admin/execucao/{exR}")
_html = r.get_data(as_text=True)
checar("a execução abre para o admin", r.status_code == 200, r.status_code)
checar("com a causa e a frase do SEI", "o SEI recusou o usuário ou a senha" in _html
       and "Usuário ou senha inválida." in _html)
checar("e a saída inteira do coletor", "LOGIN_SEI_DISSE" in _html)
checar("execução que não existe: 404", ca.get("/admin/execucao/987654").status_code == 404)
r = ca.get("/admin/diagnostico")
_html = r.get_data(as_text=True)
checar("o diagnóstico abre para o admin, sem token", r.status_code == 200, r.status_code)
checar("com a situação de cada agente do servidor e o motivo",
       f"SERVIDOR/teste{uR}" in _html and "recusou" in _html)
checar("e o código no ar", A.CODIGO_NO_AR in _html)
r = ca.get("/admin")
_html = r.get_data(as_text=True)
checar("a lista de execuções do /admin leva à execução", f'href="/admin/execucao/{exR}"' in _html)
checar("e a linha do agente diz a situação que o motor vê (a frase da decisão, não o selo antigo)",
       "nenhuma unidade que este agente possa publicar" in _html)
cx.execute("UPDATE usuarios SET senha_hash=?, senha_sal=? WHERE id=?",
           (*__import__("seguranca").hash_senha("senha-do-sei360-teste-1"), uR))
cx.commit()
cofre.marcar_recusa(cx, uR, "SEI-SESAB", "o SEI recusou o usuário ou a senha. (teste)")
cx.commit()
cp = entrar("leticia.teste@saude.ba.gov.br", "senha-do-sei360-teste-1")
checar("quem não é admin não abre o diagnóstico",
       cp.get("/admin/diagnostico").status_code in (302, 403))
checar("nem a execução", cp.get(f"/admin/execucao/{exR}").status_code in (302, 403))
_html = cp.get("/configuracao").get_data(as_text=True)
checar("a pessoa vê, sem clicar em nada, que a coleta parou e por quê",
       "A coleta automática está parada" in _html and "recusou" in _html)
import coleta as colmod                                          # noqa: E402
_testou = []
_ta = colmod.testar_acesso
colmod.testar_acesso = lambda *a, **k: (_testou.append(a) or (False, "x", "y"))
try:
    _tok = cp.get_cookie("sei360_csrf")
    r = cp.post("/configuracao/testar", data={"csrf": _tok.value if _tok else ""})
finally:
    colmod.testar_acesso = _ta
checar("'Testar acesso' com a senha recusada NÃO vai ao SEI", _testou == [], _testou)
checar("e explica que salvar de novo é o caminho",
       "Salve a senha de novo" in r.get_data(as_text=True))
checar("/saude diz qual código está no ar",
       A.app.test_client().get("/saude").get_json().get("codigo") == A.CODIGO_NO_AR)

cx.close()
print("\n" + "=" * 62)
print(f"{ok} verificações OK, {mau} falha(s)")
sys.exit(1 if mau else 0)
