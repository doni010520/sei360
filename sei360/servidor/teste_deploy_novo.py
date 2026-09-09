# -*- coding: utf-8 -*-
"""
A história do PRIMEIRO DEPLOY, do volume vazio até a primeira coleta aceita.

Por que este teste existe separado do testes.py: aquele roda contra um servidor
já semeado, com 6 snapshots e 60 contas. Ele nunca passaria perto do caminho que
alguém percorre num EasyPanel novo — e foi exatamente ali que a auditoria achou
os três defeitos que travavam o deploy, mais um impasse que nem ela viu:

  * o esquema não era criado quando o módulo é IMPORTADO (que é o que o gunicorn
    faz), então o container subia "verde" e devolvia 500 em tudo;
  * criar o primeiro admin dependia de ingerir uma coleta de um caminho Windows;
  * agente nasce com escopo vazio e escopo vazio recusa tudo (certo), mas a tela
    só oferecia unidades vindas de snapshot — que só existe DEPOIS da primeira
    publicação. Instalação nova não saía do lugar.

Roda em processo, com volume temporário. Não toca no banco de desenvolvimento.

    python teste_deploy_novo.py
"""
import importlib, json, os, secrets, shutil, subprocess, sys, tempfile
from pathlib import Path

VOLUME = Path(tempfile.gettempdir()) / "sei360_deploy_novo"
ok_total, falhas = 0, []


def checar(nome, cond, detalhe=""):
    global ok_total
    if cond:
        ok_total += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {detalhe}")


shutil.rmtree(VOLUME, ignore_errors=True)
VOLUME.mkdir(parents=True)
os.environ["SEI360_DADOS"] = str(VOLUME)

print(f"SEI360 — primeiro deploy, volume vazio em {VOLUME}\n")

# ---------------------------------------------------------------- 1. o import
print("1. o container sobe")
# Recarrega os módulos para que leiam o SEI360_DADOS novo (banco.py resolve o
# caminho no import — é assim que o container também faz, uma vez só).
for m in ("banco", "seguranca", "janelas", "ingestao", "app"):
    if m in sys.modules:
        del sys.modules[m]
app_mod = importlib.import_module("app")          # <- único gatilho, como gunicorn
checar("banco criado só pelo import do módulo", (VOLUME / "sei360.db").exists())

cliente = app_mod.app.test_client()
r = cliente.get("/saude")
checar("/saude responde 200 em instalação vazia", r.status_code == 200, str(r.status_code))
checar("/saude não expõe inventário de unidades sem sessão",
       "unidades" not in r.get_json() or isinstance(r.get_json().get("unidades_correntes"), int))
r = cliente.get("/entrar")
checar("tela de acesso abre sem nenhum snapshot", r.status_code == 200, str(r.status_code))
checar("tela mostra zero em vez de número inventado", b"847" not in r.data)

# ---------------------------------------------------------------- 2. bootstrap
print("\n2. bootstrap da conta de administração")
saida = subprocess.run([sys.executable, "semear.py", "--so-contas"],
                       capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
texto = saida.stdout + saida.stderr
checar("semear --so-contas roda sem coleta nenhuma", saida.returncode == 0, texto[-200:])
senha = None
for linha in texto.splitlines():
    if "admin@sei360.local" in linha:
        senha = linha.split()[-1]
checar("senha provisória do admin foi impressa uma vez", bool(senha), texto[-200:])
checar("NÃO criou conta de demonstração em modo produção",
       "gestor@sei360.local" not in texto)

from banco import conectar          # noqa: E402  (depois do semear, de propósito)
cx = conectar()
contas = [r["email"] for r in cx.execute("SELECT email FROM usuarios")]
cx.close()
checar(f"só a conta de administração existe ({contas})", contas == ["admin@sei360.local"])

# ---------------------------------------------------------------- 3. 1o login
print("\n3. primeiro login e troca de senha")
c = app_mod.app.test_client()
c.get("/entrar")
csrf = next((v for k, v in c.get_cookie("sei360_csrf").__dict__.items() if k == "value"), None) \
    if hasattr(c, "get_cookie") else None
if not csrf:                                     # Flask < 3.1 não tem get_cookie
    r = c.get("/entrar")
    csrf = r.headers["Set-Cookie"].split("sei360_csrf=")[1].split(";")[0]
r = c.post("/entrar", data={"email": "admin@sei360.local", "pw": senha, "csrf": csrf})
checar("login com a provisória funciona", r.status_code == 200, str(r.status_code))
checar("e manda trocar a senha antes de qualquer tela",
       r.get_json().get("destino") == "/primeiro-acesso", str(r.get_json()))
nova = "primeiro-deploy-2026"
r = c.post("/primeiro-acesso", data={"nova": nova, "confirma": nova, "csrf": csrf})
checar("troca aceita", r.status_code in (200, 302), str(r.status_code))

c = app_mod.app.test_client()
r = c.get("/entrar")
csrf = r.headers["Set-Cookie"].split("sei360_csrf=")[1].split(";")[0]
r = c.post("/entrar", data={"email": "admin@sei360.local", "pw": nova, "csrf": csrf})
checar("login com a senha nova entra no sistema",
       r.status_code == 200 and r.get_json().get("destino") == "/", str(r.get_json()))
r = c.get("/admin")
checar("/admin abre", r.status_code == 200, str(r.status_code))
# A moldura lateral (`_nav.html`) mostrava o LOGIN acima do botão "Sair" —
# `admin@sei360.local` virava "admin" — mesmo com `usuarios.nome` preenchido
# desde a criação da conta (`semear.py` grava "Administração SEI360" para o
# bootstrap). Esta conta é o caso perfeito para pegar a regressão: nome e
# e-mail são visivelmente diferentes.
_corpo_admin = r.data.decode("utf-8", "replace")
# O par <b>nome</b><i>papel</i> é o `.lat-quem-txt` inteiro (ver `_nav.html`) —
# comparar só isso, e não "admin" avulso, importa: a MESMA palavra "admin"
# aparece de novo na tela, sem relação nenhuma, no rótulo do papel na política
# de segundo fator ("Segundo fator para <b>admin</b>").
checar("a lateral mostra o NOME da conta, não o login",
       "<b>Administração SEI360</b><i>admin</i>" in _corpo_admin
       and "<b>admin</b><i>admin</i>" not in _corpo_admin)
checar("e as iniciais do avatar vêm do nome (AS), não do e-mail (AD)",
       'lat-av">AS<' in _corpo_admin)

# ---------------------------------------------------------------- 4. o impasse
print("\n4. o impasse do escopo (agente novo x nenhuma unidade conhecida)")
cx = conectar()
cx.execute("""INSERT INTO agentes(nome_estacao,unidades_esperadas,ativo,criado_em)
              VALUES('ESTACAO-NOVA','[]',1,datetime('now'))""")
aid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.execute("INSERT INTO agendamento(agente_id,janelas,ativo) VALUES(?,'[\"07:30\"]',1)", (aid,))
cx.commit(); cx.close()

r = c.get("/admin")
checar("a tela oferece campo de texto para o escopo (não só caixas de seleção)",
       b"unidades_texto" in r.data)

UNIDADE = "SESAB/SAIS/DGGUP/DGESS/CESS"
r = c.post("/admin/agente", data={"csrf": csrf, "acao": "escopo", "id": str(aid),
                                  "unidades_texto": UNIDADE + "\nSESAB/SAIS/DGGUP/UMA-CMA"})
cx = conectar()
escopo = json.loads(cx.execute("SELECT unidades_esperadas FROM agentes WHERE id=?",
                               (aid,)).fetchone()[0])
cx.close()
checar(f"escopo gravado por texto livre ({escopo})", UNIDADE in escopo and len(escopo) == 2)

# ---------------------------------------------------------------- 4b. o dono
print("\n4b. dono do agente (estação física, ligada depois de criada)")
# "Novo agente" (a estação física) nunca perguntou o dono — só o modo servidor
# grava isso sozinho, ao nascer (`aplicar_agendamento`). Antes desta forma, ligar
# uma estação já instalada à conta de quem tem a credencial exigia UPDATE direto
# no banco pelo shell do host (foi o que aconteceu com FESF/Laisa, 08/09/2026).
cx = conectar()
cx.execute("""INSERT INTO usuarios(email,papel,criado_em) VALUES(?,?,datetime('now'))""",
           ("dona.teste@fesfsus.ba.gov.br", "servidor"))
uid_dona = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()

r = c.get("/admin")
checar("a tela oferece campo para ligar o agente a uma conta",
       b'name="dono_usuario_id"' in r.data and b"dona.teste@fesfsus.ba.gov.br" in r.data)

r = c.post("/admin/agente", data={"csrf": csrf, "acao": "dono", "id": str(aid),
                                  "dono_usuario_id": str(uid_dona)})
cx = conectar()
dono = cx.execute("SELECT dono_usuario_id FROM agentes WHERE id=?", (aid,)).fetchone()[0]
cx.close()
checar(f"dono gravado pela tela (uid={dono})", dono == uid_dona)

r = c.post("/admin/agente", data={"csrf": csrf, "acao": "dono", "id": str(aid),
                                  "dono_usuario_id": ""})
cx = conectar()
dono = cx.execute("SELECT dono_usuario_id FROM agentes WHERE id=?", (aid,)).fetchone()[0]
cx.close()
checar("'— nenhum —' limpa o dono de volta para NULL", dono is None, str(dono))

# ---------------------------------------------------------------- 5. publicação
print("\n5. vínculo do agente e primeira publicação")
import hashlib
from banco import agora
codigo = secrets.token_urlsafe(12)
cx = conectar()
cx.execute("""INSERT INTO enrolamentos(codigo_sha256,agente_id,criado_em,expira_em)
              VALUES(?,?,?,'2099-01-01T00:00:00-03:00')""",
           (hashlib.sha256(codigo.encode()).digest(), aid, agora()))
cx.commit(); cx.close()

ca = app_mod.app.test_client()
r = ca.post("/api/agente/enrolar", json={"codigo": codigo, "versao": "1.0.0"})
checar("agente troca código por token", r.status_code == 200, str(r.status_code))
token = r.get_json().get("token", "")

import hmac
def assinado(caminho, corpo=None, metodo="GET"):
    dados = json.dumps(corpo).encode() if corpo is not None else b""
    ts = agora()
    cab = {"Authorization": f"Bearer {token}", "X-SEI360-Ts": ts,
           "X-SEI360-Assinatura": hmac.new(token.encode(), ts.encode() + b"." + dados,
                                           hashlib.sha256).hexdigest(),
           "Content-Type": "application/json"}
    if metodo == "GET":
        return ca.get(caminho, headers=cab)
    return ca.post(caminho, data=dados, headers=cab)

r = assinado("/api/agente/tarefa")
checar("agente pergunta a tarefa e recebe resposta explicada",
       r.status_code == 200 and "motivo" in r.get_json(), str(r.status_code))

cx = conectar()
cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em)
              VALUES(?,?,'entregue','manual_admin',?)""", (aid, agora(), agora()))
ex = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()

linhas = [{"id": "1", "protocolo": "019.0000.2026.0000001-11", "mesa_coleta": UNIDADE,
           "mesas_coleta": [UNIDADE], "mesas_conta": [UNIDADE], "mesas_falhas": [],
           "tipo_processo": "Documento tramitável: Ofício", "especificacao": "TESTE",
           "marco_unidade": "01/08/2026 09:00", "visualizado": True}]
r = assinado("/api/agente/resultado",
             {"execucao_id": ex, "dados": linhas,
              "coletado_em": "2026-08-19T07:45:00-03:00"}, "POST")
checar("primeira publicação é aceita", r.status_code == 200, str(r.get_json())[:160])

# Publicação INTEIRAMENTE fora do escopo continua recusada — não há o que
# recortar, o lote todo é de outra unidade.
_ex2 = None
r2 = assinado("/api/agente/tarefa", metodo="GET")
if r2.status_code == 200:
    _ex2 = (r2.get_json() or {}).get("execucao_id")
fora = assinado("/api/agente/resultado",
                {"execucao_id": _ex2 or ex,
                 "dados": [dict(linhas[0], mesa_coleta="OUTRA/UNIDADE",
                                mesas_coleta=["OUTRA/UNIDADE"],
                                mesas_conta=["OUTRA/UNIDADE"])],
                 "coletado_em": "2026-08-19T07:45:00-03:00"}, "POST")
checar("publicação inteiramente fora do escopo continua recusada",
       fora.status_code == 409, f"{fora.status_code} {str(fora.get_json())[:120]}")

# E republicar a mesma execução é recusado com motivo, não com 500.
de_novo = assinado("/api/agente/resultado",
                   {"execucao_id": ex, "dados": linhas,
                    "coletado_em": "2026-08-19T07:45:00-03:00"}, "POST")
checar("republicar a mesma execução é recusado (409), não estoura 500",
       de_novo.status_code == 409, f"{de_novo.status_code} {str(de_novo.get_json())[:140]}")

r = ca.get("/entrar")
corpo = r.data.decode("utf-8", "replace")
# A tela mostra AGREGADO, não a sigla: contagem e data de coleta bastam para dar
# sinal de vida, e sigla de unidade numa página sem sessão é inventário da
# carteira para quem só abriu o endereço. (A primeira versão desta tela, que eu
# tinha escrito, listava as seis unidades ali — a original não lista, e é melhor.)
checar("os números da tela de acesso passam a refletir a publicação",
       ">1<" in corpo.replace(" ", "") or "SEI360_REAIS" in corpo)
import re as _re
reais = _re.search(r"window\.SEI360_REAIS = (\{.*?\});", corpo)
dados_tela = json.loads(reais.group(1)) if reais else {}
checar(f"contagem real na tela: {dados_tela.get('processos')} processo(s), "
       f"{dados_tela.get('unidades')} unidade(s)",
       dados_tela.get("processos") == "1" and dados_tela.get("unidades") == "1",
       str(dados_tela))
# Pela TERCEIRA vez nesta base um teste caiu na armadilha do substring: "CESS"
# está dentro de "ACESSO" e de "PROCESSO", que aparecem na tela dezenas de vezes.
# Antes já tinha acontecido com DGESS/DGESS-CESS no painel e no admin. A regra
# que sobrou: sigla de unidade se compara pelo CAMINHO INTEIRO, nunca por pedaço.
checar("a tela de acesso NÃO expõe sigla de unidade sem sessão",
       UNIDADE not in corpo)

print("\nO DOCUMENTO SO MANDA DEFINIR VARIAVEL QUE O CODIGO LE")
# `SEI360_SECRET_KEY`, `SEI360_DB` e `SEI360_SNAPSHOTS` ficaram meses no §3.5 sem
# existirem em lugar nenhum. O operador define, o processo ignora, nao ha
# sintoma. A auditoria de 19/08 apontou e nada mudou — porque nada falhava.
import re as _re                                                    # noqa: E402

_SRV = Path(__file__).resolve().parent
_DOC = _SRV.parent / "ARQUITETURA_ACESSO.md"

# 1. O que o CODIGO le, de fato.
_lidas = set()
for _f in _SRV.glob("*.py"):
    if _f.name.startswith("teste_"):
        continue
    _src = _f.read_text(encoding="utf-8")
    _lidas |= set(_re.findall(r'environ(?:\.get)?\(?\[?["\'](SEI360_[A-Z_]+|SEI_[A-Z_]+)["\']', _src))
# O Dockerfile tambem DEFINE variaveis que o coletor le do outro lado.
_dock = (_SRV / "Dockerfile").read_text(encoding="utf-8")
_lidas |= set(_re.findall(r"^\s*(SEI360_[A-Z_]+|SEI_[A-Z_]+)=", _dock, _re.M))
_col = (_SRV.parent.parent / "painel_sesab" / "coletor_sesab.py")
if _col.exists():
    _lidas |= set(_re.findall(r'environ(?:\.get)?\(?\[?["\'](SEI_[A-Z_]+)["\']',
                              _col.read_text(encoding="utf-8")))
checar(f"o codigo le {len(_lidas)} variavel(is) SEI360_/SEI_", len(_lidas) >= 6,
       str(sorted(_lidas)))

# 2. O que o DOCUMENTO manda definir — so os blocos de receita, nao a lista de
#    ausencias declaradas (que existe justamente para nomear as que NAO sao lidas).
_texto = _DOC.read_text(encoding="utf-8")
_ausentes = set(_re.findall(r"^(SEI360_[A-Z_]+)=.*NAO E LIDA|^(SEI360_[A-Z_]+)=.*NÃO É LIDA",
                            _texto, _re.M))
_declaradas_ausentes = {a or b for a, b in _ausentes}
_pedidas = set(_re.findall(r"^(SEI360_[A-Z_]+|SEI_[A-Z_]+)=", _texto, _re.M)) - _declaradas_ausentes
_fantasmas = sorted(_pedidas - _lidas)
checar("nenhuma variavel do documento e ignorada pelo codigo",
       not _fantasmas,
       f"o documento manda definir, e ninguem le: {_fantasmas}")

# 3. E o contrario: variavel que o codigo le e o documento nao cita.
_mudas = sorted(v for v in _lidas if v not in _texto)
checar("nenhuma variavel que o codigo le fica fora do documento",
       not _mudas, f"o codigo le e o documento nao cita: {_mudas}")

# 4. O nome que quebrou: os dois sao aceitos, para quem seguiu o documento antigo.
_appsrc = (_SRV / "app.py").read_text(encoding="utf-8")
checar("`SEI360_SEGREDO` e `SEI360_SECRET_KEY` sao ambos aceitos",
       "SEI360_SEGREDO" in _appsrc and "SEI360_SECRET_KEY" in _appsrc)
checar("e o codigo diz que o segredo NAO protege a sessao (ela e token no banco)",
       "não há `session[...]`" in _appsrc or "Não há `session[...]`" in _appsrc)

import os as _os4                                                  # noqa: E402
print("\nA TRAVA DA SUITE NAO PODE GIRAR PARA SEMPRE")
# Ela ja travou a propria suite: `while True` com o `unlink` dentro de um
# `except OSError: pass`. No Windows, arquivo ainda aberto por outro processo da
# PermissionError, o laco repetia sem teto e sem espera, e a suite simplesmente
# nao comecava — sem uma linha na tela dizendo por que.
#
# E o criterio de "dono vivo" era so o PID, que o sistema recicla: um PID reusado
# por qualquer processo trancaria a suite para sempre.
import subprocess as _sp4                                           # noqa: E402
import time as _t4                                                  # noqa: E402

import ambiente_teste as _amb                                       # noqa: E402

_tr = Path(_os4.environ.get("TEMP") or "/tmp") / "sei360_teste_provatrava.lock"
_tr.unlink(missing_ok=True)
try:
    _amb._travar("provatrava", Path("."))
    checar("toma a trava quando ela esta livre", _tr.exists())

    _amb._travar("provatrava", Path("."))
    checar("e a propria trava nao bloqueia a si mesma", _tr.exists())

    _tr.write_text(f"999999 {int(_t4.time())}\n")      # o \n e o terminador do registro
    _amb._travar("provatrava", Path("."))
    checar("toma a trava de processo MORTO (Ctrl+C nao tranca para sempre)",
           _amb._dono_da_trava(_tr)[0] == _os4.getpid())

    # Trava velha vence por TEMPO, mesmo com o dono vivo: e o que protege contra
    # PID reciclado, que nenhum teste de "processo existe" consegue distinguir.
    _tr.write_text(f"{_os4.getpid()} {int(_t4.time()) - _amb.TRAVA_VELHA_S - 60}\n")
    _amb._travar("provatrava", Path("."))
    checar(f"trava mais velha que {_amb.TRAVA_VELHA_S // 60} min vence por tempo",
           _amb._dono_da_trava(_tr)[1] > _t4.time() - 60)

    # E o caso que ela existe para atender: OUTRO processo, vivo, agora.
    _outro = _sp4.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _tr.write_text(f"{_outro.pid} {int(_t4.time())}\n")
        try:
            _amb._travar("provatrava", Path("."))
            checar("recusa a trava de outro processo VIVO", False, "deixou passar")
        except SystemExit as _e4:
            checar("recusa a trava de outro processo VIVO",
                   "em curso" in str(_e4), str(_e4)[:60])
            checar("e a mensagem diz o que fazer, com o caminho da trava",
                   "apague" in str(_e4).lower() and ".lock" in str(_e4))
    finally:
        _outro.kill()

    # Trava ilegivel nao imortaliza nada.
    _tr.write_text("lixo que nao e numero")
    _amb._travar("provatrava", Path("."))
    checar("trava ilegivel e tomada, nao respeitada",
           _amb._dono_da_trava(_tr)[0] == _os4.getpid())

    # REGISTRO SEM TERMINADOR — o que uma versao anterior deixaria, ou um
    # processo morto no meio da escrita. Esperar por ele para sempre transformaria
    # a protecao em bloqueio permanente.
    _tr.write_text("999999 " + str(int(_t4.time())))     # sem o \n
    _amb._travar("provatrava", Path("."))
    checar("registro SEM terminador nao imortaliza a trava",
           _amb._dono_da_trava(_tr)[0] == _os4.getpid())
finally:
    _tr.unlink(missing_ok=True)

print(f"\n{'='*58}\n{ok_total} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
shutil.rmtree(VOLUME, ignore_errors=True)
sys.exit(1 if falhas else 0)
