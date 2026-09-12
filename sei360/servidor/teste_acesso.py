# -*- coding: utf-8 -*-
"""
Recuperação de senha e segundo fator — sem mandar um e-mail sequer.

O TRANSPORTE É DESVIADO PARA UM ARQUIVO, O RESTO É DE VERDADE. O servidor de
teste roda em OUTRO processo, então trocar uma função aqui não o alcançaria: o
desvio é a variável `SEI360_EMAIL_FALSO`, que o processo filho herda. Assim a
política, o token, o código, a sessão pendente, o bloqueio e a auditoria são
exercitados contra o banco e as rotas reais — e um teste que dependesse do
Resend estar no ar mediria o Resend, não o SEI360.
"""
# ---------------------------------------------------------------------------
# ISOLAMENTO PRIMEIRO. `banco.py` resolve o caminho do arquivo no import; chamar
# `isolar()` depois disso não isola nada.
# ---------------------------------------------------------------------------
import base64 as _b64, os as _os, sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from ambiente_teste import isolar, subir_servidor          # noqa: E402

_dir = isolar(__file__)
_chave = _os.environ.get("SEI360_CHAVE_MESTRA") or _b64.urlsafe_b64encode(
    _os.urandom(32)).decode().rstrip("=")
_os.environ["SEI360_CHAVE_MESTRA"] = _chave
# A caixa falsa mora no diretório isolado desta suíte — o processo filho herda a
# variável e grava lá; aqui a gente lê.
CAIXA_ARQ = _os.path.join(str(_dir), "caixa_falsa.jsonl")
_os.environ["SEI360_EMAIL_FALSO"] = CAIXA_ARQ
# DE PROPÓSITO diferente do endereço em que o servidor de teste escuta: é assim
# que dá para provar que o link do e-mail sai da CONFIGURAÇÃO e não do cabeçalho
# `Host` da requisição, que quem faz a requisição controla.
BASE_PUBLICA = "https://painel.exemplo-configurado.com.br"
_os.environ["SEI360_BASE_URL"] = BASE_PUBLICA
BASE, _parar = subir_servidor(_dir, chave_mestra=_chave)
import atexit as _atexit                                    # noqa: E402
_atexit.register(_parar)
print(f"banco isolado : {_dir}")
print(f"servidor      : {BASE}")
print(f"caixa falsa   : {CAIXA_ARQ}")

import http.cookiejar, json, re, sys                        # noqa: E402
import urllib.error, urllib.parse, urllib.request           # noqa: E402

import acesso                                               # noqa: E402
import email_saida                                          # noqa: E402
import seguranca as seg                                     # noqa: E402
from banco import agora, conectar                           # noqa: E402

SENHA = "teste-acesso-sei360-2026"
ok_total, falhas = 0, []


def checar(nome, condicao, detalhe=""):
    global ok_total
    if condicao:
        ok_total += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {detalhe}")


def cliente():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.jar = jar
    return op


def pegar(op, caminho, dados=None):
    corpo = urllib.parse.urlencode(dados, doseq=True).encode() if dados else None
    try:
        r = op.open(urllib.request.Request(BASE + caminho, data=corpo), timeout=30)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def csrf(op):
    return next((c.value for c in op.jar if c.name == "sei360_csrf"), "")


def tem_cookie(op, nome):
    return any(c.name == nome for c in op.jar)


def caixa():
    """O que foi 'enviado' até agora."""
    if not _os.path.exists(CAIXA_ARQ):
        return []
    with open(CAIXA_ARQ, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def ultimo(padrao):
    for m in reversed(caixa()):
        achou = re.search(padrao, (m.get("text") or "") + " " + (m.get("subject") or ""))
        if achou:
            return achou.group(1)
    return None


def entrar(op, email, senha):
    pegar(op, "/entrar")
    return pegar(op, "/entrar", {"email": email, "pw": senha, "csrf": csrf(op)})


# ------------------------------------------------------------------- a conta
REAL = "t.acesso@exemplo.com.br"
cx = conectar()
h, sal = seg.hash_senha(SENHA)
cx.execute("DELETE FROM usuarios WHERE email=?", (REAL,))
cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,criado_em,
              ativo,senha_trocada_em) VALUES(?,?,?,?,'gestor','teste',?,1,?)""",
           (REAL, "Teste de Acesso", h, sal, agora(), agora()))
UID = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit()
cx.close()

print("\n1. o endereço que não recebe correio é reconhecido ANTES")
# As três contas de administração deste sistema nasceram em `@sei360.local`.
# Mandar um código para lá é trancar a conta para sempre: não volta, não dá erro
# visível, e a pessoa fica olhando um campo que nunca vai ser preenchido.
for e, esperado in ((REAL, True), ("gestor@sei360.local", False),
                    ("a@b.localhost", False), ("sem-arroba", False),
                    ("x@y.invalid", False), ("nome.sobrenome@saude.ba.gov.br", True)):
    vale, porque = email_saida.entregavel(e)
    checar(f"{e!r} -> {'entrega' if esperado else 'não entrega'}", vale == esperado, str(porque))
_m = email_saida.mascarar("zaine.lima@saude.ba.gov.br")
checar("o endereço é mascarado para o log: primeira, última e o domínio",
       _m.startswith("z") and _m.endswith("a@saude.ba.gov.br")
       and set(_m.split("@")[0][1:-1]) == {"*"}
       and len(_m.split("@")[0]) == len("zaine.lima"), _m)
checar("e caixa curta não vaza a primeira letra",
       email_saida.mascarar("ab@x.com") == "**@x.com", email_saida.mascarar("ab@x.com"))

print("\n2. nada liga antes de um teste de envio que chegou")
cx = conectar()
try:
    acesso.salvar_politica(cx, True, ["gestor"], UID)
    checar("ligar sem e-mail configurado é recusado", False, "deixou ligar")
except RuntimeError as e:
    checar("ligar sem e-mail configurado é recusado", "testado" in str(e), str(e))
email_saida.guardar_chave(cx, "re_chave_de_teste", UID)
email_saida.guardar_remetente(cx, "SEI360 <nao-responda@exemplo.com.br>", "", UID)
cfg = email_saida.ler_config(cx)
checar("com chave e remetente, ainda NÃO está pronto (falta o teste)",
       cfg["tem_chave"] and cfg["remetente"] and not cfg["pronto"], str(cfg))
n = len(caixa())
ok, erro = email_saida.testar(cx, REAL, UID)
cx.commit()
checar("o teste de envio passa pela caixa falsa", ok, str(erro))
checar("e a mensagem foi parar lá", len(caixa()) == n + 1)
checar("agora está pronto", email_saida.ler_config(cx)["pronto"])
# A CONTA QUE NÃO RECEBE CORREIO BARRA A POLÍTICA — e é assim que tem de ser.
# O banco desta instalação nasceu com três contas em `@sei360.local`; ligar o
# segundo fator para o papel delas as trancaria para sempre, sem tela por onde
# destrancar.
_presa = "gestor@sei360.local"
# A CONTA É CRIADA AQUI, não presumida do banco copiado.
#
# A versão anterior só fazia `UPDATE ... SET ativo=1 WHERE email=?`, contando
# com as três contas `@sei360.local` com que esta instalação nasceu. Num banco
# sem elas — máquina de quem desenvolve, clone novo — o UPDATE não pegava nada,
# não havia conta indeliverável para barrar, `salvar_politica` passava, e a
# verificação ficava VERMELHA acusando o produto de deixar trancar uma conta que
# não existia. A cena é sobre a REGRA, e a regra precisa de um sujeito.
cx.execute("""INSERT INTO usuarios(email,nome,papel,origem,criado_em,ativo,senha_hash)
              VALUES(?,?,'gestor','teste',?,1,NULL)
              ON CONFLICT(email) DO UPDATE SET ativo=1, papel='gestor'""",
           (_presa, "Gestor sem correio", agora()))
cx.commit()
try:
    acesso.salvar_politica(cx, True, ["gestor"], UID)
    checar("conta ativa que não recebe correio impede ligar o fator2", False,
           "deixou ligar e trancaria a conta")
except RuntimeError as e:
    checar("conta ativa que não recebe correio impede ligar o fator2",
           _presa in str(e) and "trancadas" in str(e), str(e)[:160])
# O conserto é o e-mail dela, não uma exceção na regra.
cx.execute("UPDATE usuarios SET email=? WHERE email=?",
           ("gestor.demo@exemplo.com.br", _presa))
cx.commit()
acesso.salvar_politica(cx, True, ["gestor"], UID)
cx.commit()
checar("com o endereço corrigido, a política aceita ser ligada",
       acesso.ler_politica(cx)["fator2_papeis"] == ["gestor"])

print("\n3. a chave da API não volta para tela nenhuma")
checar("a chave guardada abre de volta com a chave mestra",
       email_saida.abrir_chave(cx) == "re_chave_de_teste")
bruto = bytes(cx.execute("SELECT chave FROM config_email WHERE id=1").fetchone()["chave"])
checar("mas no banco ela está cifrada", b"re_chave_de_teste" not in bruto,
       "a chave está em texto puro")
cx.close()

print("\n4. o segundo fator: a senha certa NÃO basta")
op = cliente()
antes = len(caixa())
s, corpo = entrar(op, REAL, SENHA)
destino = json.loads(corpo).get("destino") if s == 200 else ""
checar("o login manda para a tela do código", s == 200 and destino == "/verificar",
       f"status {s} destino {destino!r}")
checar("nenhuma sessão foi emitida ainda", not tem_cookie(op, "sei360_sess"),
       "entrou sem o segundo fator")
checar("mas o desafio ganhou cookie próprio", tem_cookie(op, "sei360_2fa"))
checar("e um código foi enviado", len(caixa()) == antes + 1)
codigo = ultimo(r"seu código: (\d{6})")
checar("o código tem 6 dígitos", bool(codigo) and len(codigo) == 6, str(codigo))
cx = conectar()
_logs = [r["alvo"] or "" for r in cx.execute(
    "SELECT alvo FROM log_acesso ORDER BY id DESC LIMIT 60")]
cx.close()
checar("o código NÃO aparece no log de auditoria",
       codigo and not any(codigo in a for a in _logs),
       "o código foi parar no log — é a chave guardada junto com a fechadura")
s, corpo = pegar(op, "/verificar")
checar("a tela do código abre", s == 200 and "Digite o código" in corpo, f"status {s}")
checar("e mostra o destino MASCARADO, não o e-mail inteiro",
       REAL not in corpo and "@exemplo.com.br" in corpo)

print("\n5. código errado gasta tentativa; certo emite a sessão")
s, corpo = pegar(op, "/verificar", {"codigo": "000000", "csrf": csrf(op)})
checar("código errado é recusado dizendo quantas tentativas restam",
       "Restam" in corpo, corpo[:140])
checar("e continua sem sessão", not tem_cookie(op, "sei360_sess"))
pegar(op, "/verificar", {"codigo": codigo, "csrf": csrf(op)})
checar("o código certo emite a sessão", tem_cookie(op, "sei360_sess"))
checar("e o cookie do desafio some", not tem_cookie(op, "sei360_2fa"))
s, corpo = pegar(op, "/")
checar("e o painel abre", s == 200 and "rail" in corpo, f"status {s}")

print("\n6. o mesmo código não serve duas vezes")
op2 = cliente()
entrar(op2, REAL, SENHA)
novo = ultimo(r"seu código: (\d{6})")
checar("um código novo foi emitido", bool(novo) and novo != codigo, f"{novo} vs {codigo}")
pegar(op2, "/verificar", {"codigo": codigo, "csrf": csrf(op2)})
checar("o código ANTIGO não vale no desafio novo", not tem_cookie(op2, "sei360_sess"))
pegar(op2, "/verificar", {"codigo": novo, "csrf": csrf(op2)})
checar("o novo vale", tem_cookie(op2, "sei360_sess"))
op4 = cliente()
entrar(op4, REAL, SENHA)
mais_um = ultimo(r"seu código: (\d{6})")
op4b = cliente()
entrar(op4b, REAL, SENHA)
pegar(op4, "/verificar", {"codigo": mais_um, "csrf": csrf(op4)})
checar("e pedir outro desafio mata o anterior",
       not tem_cookie(op4, "sei360_sess"),
       "dois desafios vivos dobram a janela de adivinhação")

print("\n7. tentativas esgotam e o desafio morre")
op5 = cliente()
entrar(op5, REAL, SENHA)
certo = ultimo(r"seu código: (\d{6})")
errado = "111111" if certo != "111111" else "222222"
for _ in range(acesso.TENTATIVAS_CODIGO):
    pegar(op5, "/verificar", {"codigo": errado, "csrf": csrf(op5)})
pegar(op5, "/verificar", {"codigo": certo, "csrf": csrf(op5)})
checar(f"depois de {acesso.TENTATIVAS_CODIGO} erros, nem o código certo entra",
       not tem_cookie(op5, "sei360_sess"))

print("\n8. quando o envio falha, a porta NÃO se abre sozinha")
# O remetente é apagado para simular a configuração que quebrou — domínio que
# perdeu verificação, chave revogada, provedor fora do ar. O efeito no código é
# o mesmo: `enviar` devolve (False, motivo).
cx = conectar()
cx.execute("UPDATE config_email SET remetente='' WHERE id=1")
cx.commit()
cx.close()
op6 = cliente()
s, corpo = entrar(op6, REAL, SENHA)
checar("o login responde 503 em vez de deixar entrar", s == 503, f"status {s}")
_erro8 = (json.loads(corpo).get("erro") if corpo.startswith("{") else corpo)
checar("e a mensagem diz o que houve", "não está configurado" in _erro8, _erro8[:180])
checar("nenhuma sessão nasceu", not tem_cookie(op6, "sei360_sess"))
cx = conectar()
cx.execute("UPDATE config_email SET remetente='SEI360 <nao-responda@exemplo.com.br>', "
           "teste_ok=1 WHERE id=1")
cx.commit()
cx.close()

print("\n8-bis. ROTACIONAR A CHAVE não pode desligar o segundo fator")
# `guardar_chave` zera `teste_ok` de propósito — a chave nova pode ser de outra
# conta. Se `exige_fator2` olhasse a saúde do e-mail, trocar a chave desligaria o
# segundo fator de todo mundo em silêncio, e quem derrubasse a entrega ganharia
# um caminho para pular o fator. Armado é armado; quem desliga, desliga de
# propósito.
cx = conectar()
email_saida.guardar_chave(cx, "re_chave_rotacionada", UID)
cx.commit()
checar("depois da troca, o e-mail deixa de estar 'pronto'",
       not email_saida.ler_config(cx)["pronto"])
_u = cx.execute("SELECT * FROM usuarios WHERE id=?", (UID,)).fetchone()
checar("mas o segundo fator CONTINUA exigido", acesso.exige_fator2(cx, _u),
       "rotacionar a chave virou um bypass do segundo fator")
cx.close()
op_rot = cliente()
s, corpo = entrar(op_rot, REAL, SENHA)
checar("e a entrada continua caindo na tela do código",
       s == 200 and "/verificar" in corpo, f"status {s} {corpo[:120]}")
checar("sem sessão antes do código", not tem_cookie(op_rot, "sei360_sess"))

print("\n9. a saída de emergência devolve o acesso sem e-mail e sem painel")
import emergencia                                           # noqa: E402
cx = conectar()
emergencia.desligar_fator2(cx)
cx.commit()
checar("o segundo fator ficou desligado", acesso.ler_politica(cx)["fator2_papeis"] == [])
cx.close()
op7 = cliente()
s, corpo = entrar(op7, REAL, SENHA)
checar("e agora a senha sozinha entra", tem_cookie(op7, "sei360_sess"), f"status {s}")
# Para religar, o caminho e o mesmo de sempre: testar o envio de novo. A chave
# rotacionada na 8-bis desarmou o teste de proposito.
cx = conectar()
email_saida.testar(cx, REAL, UID)
acesso.salvar_politica(cx, True, ["gestor"], UID)
cx.commit()
checar("religar exige testar o envio outra vez",
       acesso.ler_politica(cx)["fator2_papeis"] == ["gestor"])
cx.close()

print("\n10. recuperação de senha: a resposta é a mesma exista a conta ou não")
op8 = cliente()
pegar(op8, "/esqueci")
n = len(caixa())
s, corpo_existe = pegar(op8, "/esqueci", {"email": REAL, "csrf": csrf(op8)})
existe_enviou = len(caixa()) - n
op9 = cliente()
pegar(op9, "/esqueci")
n = len(caixa())
s2, corpo_nao = pegar(op9, "/esqueci",
                      {"email": "ninguem.aqui@exemplo.com.br", "csrf": csrf(op9)})
nao_enviou = len(caixa()) - n
checar("a frase é idêntica nos dois casos",
       acesso.MESMA_RESPOSTA in corpo_existe and acesso.MESMA_RESPOSTA in corpo_nao)
checar("mas só sai e-mail quando a conta existe",
       existe_enviou == 1 and nao_enviou == 0,
       f"existe={existe_enviou} não-existe={nao_enviou}")

print("\n11. o link redefine a senha, e o que ele derruba junto")
link = ultimo(r"(https?://\S+/recuperar/\S+)")
checar("o e-mail traz um link de recuperação", bool(link), str(link))
token = (link or "").rsplit("/", 1)[-1]
cx = conectar()
vivas_antes = cx.execute("""SELECT COUNT(*) FROM sessoes WHERE usuario_id=?
                            AND revogada_em IS NULL""", (UID,)).fetchone()[0]
cx.close()
checar(f"há sessão viva desta conta para ser derrubada ({vivas_antes})", vivas_antes > 0)
opr = cliente()
s, corpo = pegar(opr, "/recuperar/" + token)
checar("a tela da nova senha abre", s == 200 and "Defina a sua senha" in corpo, f"status {s}")
NOVA = "senha-nova-de-recuperacao-2026"
pegar(opr, "/recuperar/" + token, {"nova": NOVA, "confirma": NOVA, "csrf": csrf(opr)})
cx = conectar()
vivas_depois = cx.execute("""SELECT COUNT(*) FROM sessoes WHERE usuario_id=?
                             AND revogada_em IS NULL""", (UID,)).fetchone()[0]
cx.close()
checar("todas as sessões vivas caem junto com a troca", vivas_depois == 0,
       f"{vivas_depois} continuaram vivas")
opn = cliente()
s, corpo = entrar(opn, REAL, NOVA)
checar("a senha nova entra (e cai no segundo fator)",
       s == 200 and "/verificar" in corpo, f"status {s} {corpo[:100]}")
opv = cliente()
s, corpo = entrar(opv, REAL, SENHA)
checar("e a senha velha não entra mais", s == 401, f"status {s}")

print("\n12. o link serve uma vez só")
checar("o mesmo link, de novo, está vencido",
       "Link vencido" in pegar(cliente(), "/recuperar/" + token)[1])
checar("token inventado também",
       "Link vencido" in pegar(cliente(), "/recuperar/inventado-do-nada")[1])

print("\n13. pedir outro link mata o anterior")
cx = conectar()
cx.execute("DELETE FROM recuperacao WHERE usuario_id=?", (UID,))
cx.commit()
cx.close()
o = cliente()
pegar(o, "/esqueci")
pegar(o, "/esqueci", {"email": REAL, "csrf": csrf(o)})
t1 = (ultimo(r"(https?://\S+/recuperar/\S+)") or "").rsplit("/", 1)[-1]
o = cliente()
pegar(o, "/esqueci")
pegar(o, "/esqueci", {"email": REAL, "csrf": csrf(o)})
t2 = (ultimo(r"(https?://\S+/recuperar/\S+)") or "").rsplit("/", 1)[-1]
checar("os dois pedidos deram tokens diferentes", bool(t1) and bool(t2) and t1 != t2)
checar("e o PRIMEIRO deixou de valer",
       "Link vencido" in pegar(cliente(), "/recuperar/" + t1)[1])
checar("enquanto o segundo vale",
       "Defina a sua senha" in pegar(cliente(), "/recuperar/" + t2)[1])

print("\n14. o teto por hora segura a inundação")
cx = conectar()
cx.execute("DELETE FROM recuperacao WHERE usuario_id=?", (UID,))
cx.commit()
cx.close()
n = len(caixa())
for _ in range(acesso.PEDIDOS_POR_HORA + 3):
    o = cliente()
    pegar(o, "/esqueci")
    pegar(o, "/esqueci", {"email": REAL, "csrf": csrf(o)})
enviados = len(caixa()) - n
checar(f"no máximo {acesso.PEDIDOS_POR_HORA} e-mails por hora por conta",
       enviados == acesso.PEDIDOS_POR_HORA, f"saíram {enviados}")

print("\n15-bis. o teto diário próprio para antes do teto do provedor")
# O plano gratuito do Resend entrega 100/dia; estourar devolve 429 e o sistema
# descobre no meio do expediente, com o segundo fator ligado. O teto próprio para
# ANTES, grava alerta e diz o que houve — em vez de o provedor cortar sem aviso.
cx = conectar()
_gastos = email_saida.enviados_hoje(cx)
checar(f"o contador do dia enxerga os envios já feitos ({_gastos})", _gastos > 0)
_teto_real = email_saida.TETO_DIARIO
email_saida.TETO_DIARIO = 1          # já passamos de 1 hoje
_ok, _erro = email_saida.enviar(cx, REAL, "não deve sair", "corpo", motivo="teto")
email_saida.TETO_DIARIO = _teto_real
cx.commit()
checar("com o teto estourado, o envio é recusado", not _ok, str(_erro))
checar("e a mensagem explica que volta à meia-noite",
       "teto diário" in (_erro or "") and "meia-noite" in (_erro or ""), str(_erro))
checar("e o motivo fica registrado",
       any(r["acao"] == "email_teto_diario" for r in cx.execute(
           "SELECT acao FROM log_acesso ORDER BY id DESC LIMIT 5")))

print("\n15-ter. o log não afirma entrega, e guarda a chave de investigação")
# O 200 do provedor diz que ele ACEITOU — não que alguém recebeu. O filtro do
# Microsoft 365 da SESAB pode engolir depois. E o `id` devolvido é a única chave
# que correlaciona um "não chegou" com o painel do provedor.
_ac = [dict(r) for r in cx.execute(
    "SELECT acao, alvo FROM log_acesso WHERE acao LIKE 'email_%' ORDER BY id DESC LIMIT 20")]
checar("a ação registrada é 'email_aceito', não 'enviado'",
       any(r["acao"] == "email_aceito" for r in _ac),
       str({r["acao"] for r in _ac}))
checar("nenhum log afirma 'enviar_email'",
       not any(r["acao"] == "enviar_email" for r in _ac))
checar("e o identificador do provedor está guardado",
       any("id=" in (r["alvo"] or "") for r in _ac if r["acao"] == "email_aceito"),
       str([r["alvo"] for r in _ac][:3]))
checar("o endereço no log está mascarado, nunca inteiro",
       not any(REAL in (r["alvo"] or "") for r in _ac))
cx.close()

print("\n15-quater. conta sem senha nunca vira destino de e-mail automático")
# As 57 contas semeadas do snapshot do SEI nascem sem senha. Se uma for ativada
# e ficar assim, ela viraria destino de e-mail em nome do órgão sem nunca ter
# havido conta — e endereço extraído de tela que já não existe vira devolução.
# Devolução acima de ~4% suspende a chave, e aí o segundo fator para para todos.
cx = conectar()
_semeada = "t.semeada@exemplo.com.br"
cx.execute("DELETE FROM usuarios WHERE email=?", (_semeada,))
cx.execute("""INSERT INTO usuarios(email,nome,papel,origem,criado_em,ativo,senha_hash)
              VALUES(?,?,'servidor','auto_snapshot',?,1,NULL)""",
           (_semeada, "Semeada", agora()))
cx.commit()
cx.close()
o = cliente()
pegar(o, "/esqueci")
n = len(caixa())
s, corpo = pegar(o, "/esqueci", {"email": _semeada, "csrf": csrf(o)})
checar("a frase continua sendo a mesma", acesso.MESMA_RESPOSTA in corpo)
checar("mas nenhum e-mail sai para conta ativa SEM senha", len(caixa()) == n,
       f"saíram {len(caixa()) - n}")
cx = conectar()
cx.execute("DELETE FROM usuarios WHERE email=?", (_semeada,))
cx.commit()
cx.close()

print("\n15-quinquies. o link sai da CONFIGURAÇÃO, não do cabeçalho Host")
# `url_for(_external=True)` monta a URL a partir do host que chegou — e com
# `ProxyFix(x_host=1)` esse host vem de `X-Forwarded-Host`, que quem faz a
# requisição controla. Um POST em /esqueci com `Host: servidor-do-atacante` faria
# sair, do NOSSO remetente, um e-mail legítimo apontando para o servidor dele.
cx = conectar()
cx.execute("DELETE FROM recuperacao WHERE usuario_id=?", (UID,))
cx.commit()
cx.close()
_o = cliente()
pegar(_o, "/esqueci")
_req = urllib.request.Request(
    BASE + "/esqueci",
    data=urllib.parse.urlencode({"email": REAL, "csrf": csrf(_o)}).encode(),
    headers={"Host": "servidor-do-atacante.example",
             "X-Forwarded-Host": "servidor-do-atacante.example",
             "X-Forwarded-Proto": "https"})
try:
    _o.open(_req, timeout=30).read()
except urllib.error.HTTPError:
    pass
_link = ultimo(r"(https?://\S+/recuperar/\S+)")
checar("o link do e-mail usa a base configurada",
       bool(_link) and _link.startswith(BASE_PUBLICA), str(_link))
checar("e NÃO o host que veio na requisição",
       bool(_link) and "atacante" not in _link, str(_link))

print("\n15-sexies. armar a recuperação exige a base pública configurada")
# Sem ela o link seria montado de um cabeçalho controlado por quem pede.
cx = conectar()
_guardada = _os.environ.pop("SEI360_BASE_URL")
try:
    acesso.salvar_politica(cx, True, [], UID)
    checar("sem SEI360_BASE_URL, ligar a recuperação é recusado", False, "deixou ligar")
except RuntimeError as _e:
    checar("sem SEI360_BASE_URL, ligar a recuperação é recusado",
           "SEI360_BASE_URL" in str(_e), str(_e)[:140])
# O segundo fator NÃO cai nesta regra: o e-mail dele leva um número, não um link.
try:
    acesso.salvar_politica(cx, False, ["gestor"], UID)
    checar("mas o segundo fator sozinho não exige base (não manda link)", True)
except RuntimeError as _e:
    checar("mas o segundo fator sozinho não exige base (não manda link)", False, str(_e)[:140])
_os.environ["SEI360_BASE_URL"] = _guardada
acesso.salvar_politica(cx, True, ["gestor"], UID)
cx.commit()
cx.close()

print("\n15-septies. o token não pode ir para o log de acesso")
# O gunicorn roda com `--access-logfile -`, e o log do container é onde se enxerga
# o sistema no EasyPanel. `/recuperar/<token>` inteiro ali é o token em texto,
# legível pelo painel do provedor e por qualquer backup dele — durante os 30
# minutos em que ele abre a conta sem senha.
#
# A REGRA é testada aqui, não o adaptador: `gunicorn_conf.py` só a chama, e o
# `gunicorn` nem instala em Windows. O servidor de desenvolvimento usa a mesma.
_sujo = "/recuperar/SEGREDO-QUE-ABRE-A-CONTA"
_limpo = seg.caminho_sem_segredo(_sujo)
checar("o segredo some do caminho", "SEGREDO-QUE-ABRE-A-CONTA" not in _limpo, _limpo)

# O ÁTOMO QUE O FORMATO PADRÃO IMPRIME É `r`, NÃO `U`. O formato do gunicorn é
# '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"' — `%(U)s` não
# aparece. Uma primeira versão reescrevia só `U`, passava num teste que olhava
# `U`, e deixava o token intacto na linha realmente impressa. Aqui a verificação
# é sobre a LINHA FORMATADA.
_FORMATO = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
_at = seg.atomos_sem_segredo({
    "h": "10.0.0.5", "l": "-", "u": "-", "t": "[27/Aug/2026:14:02:11 -0300]",
    "r": "GET /recuperar/SEGREDO-QUE-ABRE-A-CONTA HTTP/1.1",
    "s": "200", "b": "12", "f": "-", "a": "-", "U": "/recuperar/SEGREDO-QUE-ABRE-A-CONTA"})
_linha_log = _FORMATO % _at
checar("a LINHA do log não contém o token",
       "SEGREDO-QUE-ABRE-A-CONTA" not in _linha_log, _linha_log)
checar("e ela continua legível para a auditoria (método, caminho, status, IP)",
       all(x in _linha_log for x in ("GET", "/recuperar/", "200", "10.0.0.5")), _linha_log)
_at2 = seg.atomos_sem_segredo({"r": "GET /relatorios/triagem HTTP/1.1",
                               "U": "/relatorios/triagem"})
checar("caminho sem segredo passa intacto nos DOIS átomos",
       _at2["r"] == "GET /relatorios/triagem HTTP/1.1" and _at2["U"] == "/relatorios/triagem",
       str(_at2))
checar("mas o caminho continua identificável para a auditoria",
       _limpo.startswith("/recuperar/"), _limpo)
for _c in ("/relatorios/triagem", "/", "/entrar", "/verificar", "/estatico/vendor/d3.min.js"):
    checar(f"{_c!r} passa intacto", seg.caminho_sem_segredo(_c) == _c,
           seg.caminho_sem_segredo(_c))
checar("a rota de recuperação está mesmo na lista",
       any("/recuperar" in x for x in seg.SEGREDO_NO_CAMINHO), str(seg.SEGREDO_NO_CAMINHO))
# E o filtro do servidor de desenvolvimento usa a MESMA regra, sobre a linha
# inteira que o werkzeug imprime.
import app as _ap16                                          # noqa: E402
import logging as _lg16                                      # noqa: E402
_f16 = _ap16._SemSegredoNoLog()
_reg = _lg16.LogRecord("werkzeug", _lg16.INFO, "", 0,
                       '127.0.0.1 - - [27/Aug/2026 14:02:11] '
                       '"GET /recuperar/SEGREDO-DO-LOG HTTP/1.1" 200 -', (), None)
_f16.filter(_reg)
checar("o filtro do servidor de desenvolvimento também omite",
       "SEGREDO-DO-LOG" not in _reg.getMessage(), _reg.getMessage())
checar("e mantém o resto da linha (método, status, IP)",
       "200" in _reg.getMessage() and "127.0.0.1" in _reg.getMessage(),
       _reg.getMessage())

print("\n15-octies. a requisição que sai de verdade: cabeçalhos e corpo")
# MEDIDO contra a API real em 27/08/2026: o Cloudflare na frente do Resend BANEIA
# a assinatura padrão do urllib ("Python-urllib/3.12") — devolve 403 com corpo
# text/plain "error code: 1010" e a requisição NEM CHEGA no Resend. Sem
# User-Agent próprio, todo envio falha, sempre.
#
# A caixa falsa curto-circuita antes de montar a requisição, então este é o único
# ponto da suíte que exercita `_postar` de verdade — contra um servidor nosso,
# aqui, que devolve o que recebeu. Sem isto, trocar o cabeçalho por engano passa
# despercebido e a integração vai quebrada para produção.
import http.server                                           # noqa: E402
import threading                                             # noqa: E402

_recebido = {}


class _Eco(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        _recebido["cabecalhos"] = {k.lower(): v for k, v in self.headers.items()}
        _recebido["corpo"] = self.rfile.read(
            int(self.headers.get("Content-Length") or 0)).decode("utf-8")
        corpo = b'{"id":"eco-de-teste"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


_srv = http.server.HTTPServer(("127.0.0.1", 0), _Eco)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
_api_real, email_saida.API = email_saida.API, f"http://127.0.0.1:{_srv.server_port}/emails"
_falso_real = _os.environ.pop("SEI360_EMAIL_FALSO")     # a caixa falsa não pode desviar aqui
try:
    _st, _resp = email_saida._postar("re_chave_de_teste", {
        "from": "SEI360 <x@exemplo.com.br>", "to": ["y@exemplo.com.br"],
        "subject": "assunto de teste", "text": "corpo de teste"})
finally:
    _os.environ["SEI360_EMAIL_FALSO"] = _falso_real
    email_saida.API = _api_real
    _srv.shutdown()

_ua = _recebido.get("cabecalhos", {}).get("user-agent", "")
checar("a requisição chegou e foi aceita", _st == 200 and _resp.get("id") == "eco-de-teste",
       f"status {_st} {_resp}")
checar("ela leva um User-Agent PRÓPRIO", bool(_ua) and email_saida.USER_AGENT in _ua, repr(_ua))
checar("e NÃO a assinatura padrão do urllib, que o Cloudflare do Resend bane",
       "Python-urllib" not in _ua, repr(_ua))
checar("leva a chave como Bearer",
       _recebido["cabecalhos"].get("authorization") == "Bearer re_chave_de_teste",
       repr(_recebido["cabecalhos"].get("authorization")))
checar("e declara JSON",
       _recebido["cabecalhos"].get("content-type") == "application/json",
       repr(_recebido["cabecalhos"].get("content-type")))
_corpo = json.loads(_recebido["corpo"])
checar("o corpo tem os três campos que a API exige",
       {"from", "to", "subject"} <= set(_corpo), str(sorted(_corpo)))
checar("e `to` é lista, como a API pede", isinstance(_corpo["to"], list), str(_corpo["to"]))

print("\n15-nonies. resposta NÃO-JSON não estoura — é o 403 do Cloudflare")
# O 1010 vem em text/plain. Um json.loads nesse corpo levanta ValueError e a
# tela de acesso viraria erro 500 em vez de mensagem.
class _Cloudflare(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        corpo = b"error code: 1010"
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


_srv2 = http.server.HTTPServer(("127.0.0.1", 0), _Cloudflare)
threading.Thread(target=_srv2.serve_forever, daemon=True).start()
_api_real, email_saida.API = email_saida.API, f"http://127.0.0.1:{_srv2.server_port}/emails"
_falso_real = _os.environ.pop("SEI360_EMAIL_FALSO")
try:
    _st2, _resp2 = email_saida._postar("re_x", {"from": "a@b.c", "to": ["d@e.f"],
                                                "subject": "s", "text": "t"})
    _frase = email_saida._explicar(_st2, _resp2)
finally:
    _os.environ["SEI360_EMAIL_FALSO"] = _falso_real
    email_saida.API = _api_real
    _srv2.shutdown()
checar("corpo text/plain não estoura o parser", _st2 == 403, f"status {_st2}")
checar("e a frase nomeia a causa real, que não é do Resend",
       "Cloudflare" in _frase and "User-Agent" in _frase, _frase)

print("\n16. tirar a pessoa de dentro leva o desafio PENDENTE junto")
# Um desafio pendente é acesso EM TRÂNSITO. Quem tem o cookie e o código conclui
# /verificar depois de o administrador ter revogado as sessões — e no caminho de
# "gerar senha provisória" é pior: a sessão nasce, cai em /primeiro-acesso (que
# não pede a senha antiga) e o portador do código define a PRÓPRIA senha, ficando
# com a conta enquanto a provisória do administrador morre sem uso.
cx = conectar()
_u16 = cx.execute("SELECT * FROM usuarios WHERE id=?", (UID,)).fetchone()
_tok16, _err16 = acesso.abrir_desafio(cx, _u16, "127.0.0.1", "t", False)
cx.commit()
checar("há desafio pendente para exercitar", bool(_tok16), str(_err16))
checar("e ele vale antes", acesso.ler_desafio(cx, _tok16) is not None)
_s16, _d16, _r16 = acesso.derrubar_acesso(cx, UID, "prova")
cx.commit()
checar("derrubar_acesso cancela o desafio", acesso.ler_desafio(cx, _tok16) is None,
       f"sessões={_s16} desafios={_d16} links={_r16}")
checar("e o contador diz quantos foram", _d16 >= 1, str(_d16))
cx.close()

# E AS TRÊS AÇÕES DO PAINEL, pelas rotas — não procurando o nome da função no
# arquivo. Verificação que lê o código-fonte quebra quando ele melhora e passa
# quando ele piora; esta faz o administrador clicar e olha o desafio.
cx = conectar()
_ADM = "t.admin.acesso@exemplo.com.br"
cx.execute("DELETE FROM usuarios WHERE email=?", (_ADM,))
_ha, _sa = seg.hash_senha(SENHA)
cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,
              criado_em,ativo,senha_trocada_em) VALUES(?,?,?,?,'admin','teste',?,1,?)""",
           (_ADM, "Admin de teste", _ha, _sa, agora(), agora()))
cx.commit()
cx.close()
_opadm = cliente()
entrar(_opadm, _ADM, SENHA)          # admin não está na política do fator2
pegar(_opadm, "/")                   # emite o cookie de CSRF


def _com_desafio_pendente():
    """Abre um desafio e devolve o token dele."""
    _c = conectar()
    _u = _c.execute("SELECT * FROM usuarios WHERE id=?", (UID,)).fetchone()
    _tk, _er = acesso.abrir_desafio(_c, _u, "127.0.0.1", "t", False)
    _c.commit()
    _c.close()
    return _tk


def _ainda_vale(tk):
    _c = conectar()
    try:
        return acesso.ler_desafio(_c, tk) is not None
    finally:
        _c.close()


for _acao, _extra, _rotulo in (
        ("revogar", {}, "Revogar sessões"),
        ("nova_senha", {}, "Gerar senha provisória"),
        ("papel", {"papel": "gestor"}, "Trocar o papel")):
    _tk = _com_desafio_pendente()
    checar(f"[{_rotulo}] há desafio pendente antes", _ainda_vale(_tk))
    pegar(_opadm, "/admin/usuario",
          dict({"csrf": csrf(_opadm), "acao": _acao, "id": str(UID)}, **_extra))
    checar(f"[{_rotulo}] o desafio pendente morre junto", not _ainda_vale(_tk),
           "acesso em trânsito sobreviveu ao gesto do administrador")
cx = conectar()
cx.execute("UPDATE usuarios SET papel='gestor' WHERE id=?", (UID,))
cx.execute("DELETE FROM usuarios WHERE email=?", (_ADM,))
cx.commit()
cx.close()

print("\n17. o código de uso único emite UMA sessão, não N")
# `ler_desafio` lê fora de transação e o `usado_em` só era gravado depois: duas
# requisições com o mesmo código liam `usado_em` nulo, as duas passavam pela
# comparação e as duas emitiam sessão. Um código de USO ÚNICO virava N sessões
# independentes — e revogar uma não derrubava as outras.
#
# A LEITURA VELHA É FORÇADA, não esperada. Rodar seis threads e torcer pelo
# entrelaçamento passava por acaso: com um escritor só e `busy_timeout`, as
# escritas serializam antes de a janela abrir, e o teste dizia "uma sessão" sem
# nunca ter exercitado o defeito. Aqui `ler_desafio` é substituída por uma que
# devolve SEMPRE o retrato de antes — que é exatamente o que a segunda requisição
# enxergaria na janela real.
cx = conectar()
_u17 = cx.execute("SELECT * FROM usuarios WHERE id=?", (UID,)).fetchone()
_tok17, _ = acesso.abrir_desafio(cx, _u17, "127.0.0.1", "t", False)
cx.commit()
_cod17 = ultimo(r"seu código: (\d{6})")
_retrato = acesso.ler_desafio(cx, _tok17)
checar("há desafio e código para exercitar", bool(_retrato) and bool(_cod17), str(_cod17))

_ler_real = acesso.ler_desafio
acesso.ler_desafio = lambda _c, _t: _retrato      # todo mundo vê o retrato de antes
try:
    _a, _ea = acesso.conferir_desafio(cx, _tok17, _cod17, "127.0.0.1")
    cx.commit()
    _b, _eb = acesso.conferir_desafio(cx, _tok17, _cod17, "127.0.0.1")
    cx.commit()
finally:
    acesso.ler_desafio = _ler_real
checar("a primeira autoriza", _a is not None, str(_ea))
checar("a segunda, com a MESMA leitura velha, é recusada", _b is None,
       "um código de uso único emitiu duas sessões")
checar("e a recusa diz que o código já foi usado",
       _b is None and "já foi usado" in (_eb or ""), str(_eb))
_dep17 = cx.execute("SELECT usado_em FROM desafio WHERE token_sha256=?",
                    (acesso._hash(_tok17),)).fetchone()
checar("o desafio ficou marcado como usado uma vez só", bool(_dep17["usado_em"]))
cx.close()

print("\n18. o teto diário guarda uma reserva para quem está ENTRANDO")
# /esqueci é porta aberta, sem sessão. Sem reserva, alguém de fora queima o
# orçamento do dia pedindo recuperação e ninguém — nem admin, nem gestor —
# consegue entrar até a meia-noite, porque o login é fail-closed.
cx = conectar()
_teto, _res = email_saida.TETO_DIARIO, email_saida.RESERVA_ACESSO
checar(f"a reserva existe e é menor que o teto ({_res} de {_teto})",
       0 < _res < _teto)
_gastos = email_saida.enviados_hoje(cx)
email_saida.TETO_DIARIO = _gastos + 2
email_saida.RESERVA_ACESSO = 2          # sobra 0 para o que não é acesso
try:
    _ok_n, _e_n = email_saida.enviar(cx, REAL, "normal", "x", motivo="recuperação")
    _ok_a, _e_a = email_saida.enviar(cx, REAL, "acesso", "x", motivo="código",
                                     prioridade="acesso")
finally:
    email_saida.TETO_DIARIO, email_saida.RESERVA_ACESSO = _teto, _res
cx.commit()
checar("com a reserva no limite, a recuperação PARA", not _ok_n, str(_e_n))
checar("mas o código de acesso ainda SAI", _ok_a, str(_e_a))
cx.close()

print("\n19. `pronto` não afirma o que o sistema não consegue entregar")
# Num redeploy que preserve o volume e perca SEI360_CHAVE_MESTRA, os bytes
# cifrados continuam na coluna e `teste_ok` continua 1 — a tela estampava
# "pronto" em verde e `salvar_politica` deixava armar o segundo fator sobre um
# envio que já não funcionava.
cx = conectar()
checar("está pronto agora", email_saida.ler_config(cx)["pronto"])
_mestra = _os.environ.pop("SEI360_CHAVE_MESTRA")
try:
    checar("sem a chave mestra, NÃO está pronto",
           not email_saida.ler_config(cx)["pronto"])
    try:
        acesso.salvar_politica(cx, True, ["gestor"], UID)
        checar("e armar é recusado", False, "deixou armar sobre envio quebrado")
    except RuntimeError as _e19:
        checar("e armar é recusado", "testado" in str(_e19), str(_e19)[:120])
finally:
    _os.environ["SEI360_CHAVE_MESTRA"] = _mestra
checar("com a chave de volta, volta a estar pronto", email_saida.ler_config(cx)["pronto"])
cx.close()

print("\n20. falha de envio não reescreve o carimbo do TESTE")
# Uma falha momentânea ao mandar um código carimbava `testado_em` — a coluna que
# a tela rotula "último teste" — e deixava um erro vermelho ao lado da tag verde
# "pronto", permanentemente, descrevendo um teste que nunca houve.
cx = conectar()
_antes20 = dict(cx.execute("SELECT testado_em, teste_ok, teste_erro FROM config_email "
                           "WHERE id=1").fetchone())
# O PROVEDOR recusando — que é o caso para o qual a coluna existe. Falta de
# configuração sai antes e não é falha de envio.
_postar20 = email_saida._postar
email_saida._postar = lambda chave, corpo: (
    429, {"statusCode": 429, "name": "rate_limit_exceeded", "message": "Too many requests"})
try:
    email_saida.enviar(cx, REAL, "vai falhar", "x", motivo="prova")
finally:
    email_saida._postar = _postar20
cx.commit()
_dep20 = dict(cx.execute("SELECT testado_em, teste_ok, teste_erro, envio_erro "
                         "FROM config_email WHERE id=1").fetchone())
checar("o carimbo do teste fica intacto", _dep20["testado_em"] == _antes20["testado_em"],
       f"{_antes20['testado_em']} -> {_dep20['testado_em']}")
checar("o veredito do teste fica intacto", _dep20["teste_ok"] == _antes20["teste_ok"])
checar("mas a falha do ENVIO fica registrada em coluna própria",
       bool(_dep20["envio_erro"]), str(_dep20))
_ok20, _ = email_saida.enviar(cx, REAL, "vai passar", "x", motivo="prova")
cx.commit()
_dep20b = cx.execute("SELECT envio_erro FROM config_email WHERE id=1").fetchone()
checar("e um envio bem-sucedido LIMPA a falha do envio",
       _ok20 and not _dep20b["envio_erro"], str(dict(_dep20b)))
cx.close()

print("\n21. ler não escreve: as páginas públicas saíram do caminho da trava")
# `ler_politica` e `ler_config` abriam com INSERT OR IGNORE, que toma a trava de
# escrita única do SQLite mesmo sem nada a inserir — e `ler_politica` é chamada em
# TODO GET /entrar, a única página exposta sem sessão.
import sqlite3 as _sq21                                      # noqa: E402
import banco as _bk21                                       # noqa: E402
_ro = _sq21.connect("file:" + str(_bk21.BANCO).replace("\\", "/") + "?mode=ro", uri=True)
_ro.row_factory = _sq21.Row
try:
    _pol21 = acesso.ler_politica(_ro)
    checar("ler_politica funciona numa conexão SÓ DE LEITURA", isinstance(_pol21, dict))
except Exception as _e21:                                     # noqa: BLE001
    checar("ler_politica funciona numa conexão SÓ DE LEITURA", False, str(_e21)[:120])
try:
    _cfg21 = email_saida.ler_config(_ro)
    checar("ler_config também", isinstance(_cfg21, dict))
except Exception as _e21:                                     # noqa: BLE001
    checar("ler_config também", False, str(_e21)[:120])
_ro.close()

print("\n22. o envio acontece FORA da transação de escrita")
# O sqlite3 abre transação no primeiro DML, e o SQLite tem UM escritor: manter a
# trava durante um POST de até 10 s ao provedor faz TODA escrita do painel
# esperar — e cada requisição carimba `ultimo_uso_em` da sessão.
_escreveu = {"ok": None}
_postar_real = email_saida._postar


def _postar_que_escreve(chave, corpo):
    _c = conectar()
    try:
        _c.execute("UPDATE config_email SET atualizado_em=? WHERE id=1", (agora(),))
        _c.commit()
        _escreveu["ok"] = True
    except Exception as _ex:                                  # noqa: BLE001
        _escreveu["ok"] = str(_ex)
    finally:
        _c.close()
    return _postar_real(chave, corpo)


cx = conectar()
_u22 = cx.execute("SELECT * FROM usuarios WHERE id=?", (UID,)).fetchone()
email_saida._postar = _postar_que_escreve
try:
    acesso.abrir_desafio(cx, _u22, "127.0.0.1", "t", False)
    cx.commit()
finally:
    email_saida._postar = _postar_real
cx.close()
checar("outra conexão consegue ESCREVER enquanto o e-mail está sendo enviado",
       _escreveu["ok"] is True, str(_escreveu["ok"]))

print("\n15. nem token nem código ficam em texto no banco")
cx = conectar()
r = cx.execute("SELECT token_sha256 FROM recuperacao ORDER BY id DESC LIMIT 1").fetchone()
checar("a recuperação guarda o hash, não o token",
       bool(r) and len(bytes(r["token_sha256"])) == 32
       and t2.encode() not in bytes(r["token_sha256"]))
d = cx.execute("SELECT codigo_sha256 FROM desafio ORDER BY id DESC LIMIT 1").fetchone()
checar("e o desafio guarda o hash do código",
       bool(d) and len(bytes(d["codigo_sha256"])) == 32)
cx.execute("DELETE FROM usuarios WHERE email=?", (REAL,))
cx.commit()
cx.close()

print(f"\n{'=' * 58}\n{ok_total} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
