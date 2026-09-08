# -*- coding: utf-8 -*-
"""
Teste ponta a ponta contra o servidor RODANDO. Sem framework: urllib da stdlib.

Por que testar contra o servidor de verdade e nao com cliente de teste do Flask:
os defeitos que este sistema tem historia de produzir sao de COOKIE, REDIRECT e
FRONTEIRA — coisas que so aparecem quando ha um socket, um cookie jar e um
navegador seguindo 302. Cliente de teste esconde exatamente essa classe.

    python testes.py                 # usa http://127.0.0.1:8360
    python testes.py http://host:porta
"""

# ---------------------------------------------------------------------------
# ISOLAMENTO — antes de qualquer import do projeto.
# Esta suíte roda contra uma CÓPIA do banco e contra um servidor próprio, em
# porta própria. Antes ela escrevia no banco de trabalho, e o efeito foi medido:
# a procedência dos seis snapshots correntes passou a apontar para um arquivo
# temporário de teste em vez da coleta real, além de dezenas de contas `t.*`
# residuais. Teste não suja o banco de quem trabalha.
#
# A ordem importa: `banco.py` resolve o caminho do arquivo no import. Chamar
# `isolar()` depois disso não isola nada — por isso a própria função recusa.
# ---------------------------------------------------------------------------
import base64 as _b64, os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from ambiente_teste import isolar, subir_servidor          # noqa: E402
_dir = isolar(__file__)
_chave = _os.environ.get("SEI360_CHAVE_MESTRA") or _b64.urlsafe_b64encode(
    _os.urandom(32)).decode().rstrip("=")
_os.environ["SEI360_CHAVE_MESTRA"] = _chave
BASE, _parar = subir_servidor(_dir, chave_mestra=_chave)
import atexit as _atexit                                    # noqa: E402
_atexit.register(_parar)
print(f"banco isolado : {_dir}")
print(f"servidor      : {BASE}")

import http.cookiejar, json, sys, urllib.request, urllib.parse, urllib.error
import hmac, hashlib
from datetime import datetime, timedelta

import banco, seguranca as seg
from banco import conectar, agora, TZ

SENHA_TESTE = "teste-sei360-2026"
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


def pegar(op, caminho, dados=None, cabecalhos=None, metodo=None, bruto=False):
    """`bruto=True` devolve BYTES. Serve para o que não é texto — a planilha — e
    para o que precisa ser medido antes de virar texto, como a compressão.

    Atenção ao `urllib`: ele decodifica gzip sozinho SE o cabeçalho
    `Accept-Encoding` for posto por ele. Como aqui o cabeçalho é declarado à mão,
    o corpo chega comprimido de verdade — que é justamente o que se quer medir."""
    url = BASE + caminho
    corpo = None
    if isinstance(dados, dict):
        corpo = urllib.parse.urlencode(dados, doseq=True).encode()
    elif isinstance(dados, bytes):
        corpo = dados
    req = urllib.request.Request(url, data=corpo, method=metodo,
                                 headers=cabecalhos or {})
    try:
        r = op.open(req)
        b = r.read()
        return r.status, (b if bruto else b.decode("utf-8", "replace")), r.headers, r.url
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, (b if bruto else b.decode("utf-8", "replace")), e.headers, url


def csrf(op):
    for c in op.jar:
        if c.name == "sei360_csrf":
            return c.value
    return ""


def usuario_de_teste(email, papel, unidades, senha=SENHA_TESTE, trocada=True):
    """Cria/reseta direto no banco: o teste nao pode depender de senha impressa
    no console de uma execucao anterior."""
    cx = conectar()
    h, sal = seg.hash_senha(senha)
    ja = cx.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
    if ja:
        cx.execute("""UPDATE usuarios SET senha_hash=?,senha_sal=?,papel=?,ativo=1,
                      bloqueado_ate=NULL,senha_trocada_em=? WHERE id=?""",
                   (h, sal, papel, agora() if trocada else None, ja["id"]))
        uid = ja["id"]
    else:
        cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,
                      criado_em,ativo,senha_trocada_em) VALUES(?,?,?,?,?,'teste',?,1,?)""",
                   (email, "Teste", h, sal, papel, agora(), agora() if trocada else None))
        uid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=?", (uid,))
    for un in unidades:
        cx.execute("INSERT INTO usuario_unidade(usuario_id,unidade,concedida_em) VALUES(?,?,?)",
                   (uid, un, agora()))
    cx.execute("UPDATE sessoes SET revogada_em=? WHERE usuario_id=?", (agora(), uid))
    # Sem isto a suite fica flaky por comportamento CERTO: as falhas propositais
    # de um run contam na janela de 15 min do run seguinte e bloqueiam a conta.
    cx.execute("DELETE FROM tentativas_login WHERE email=?", (email,))
    cx.commit(); cx.close()
    return uid


def entrar(op, email, senha):
    pegar(op, "/entrar")
    return pegar(op, "/entrar", {"email": email, "pw": senha, "csrf": csrf(op)})


print(f"SEI360 — teste ponta a ponta contra {BASE}\n")

# ---------------------------------------------------------------- 1. acesso
print("1. tela de acesso")
op = cliente()
s, corpo, _, _ = pegar(op, "/entrar")
checar("GET /entrar responde 200", s == 200, f"status {s}")
checar("cookie CSRF emitido", bool(csrf(op)))
checar("aviso 'não é a senha do SEI' presente", "nunca pede a senha do SEI" in corpo)
checar("sem dependência externa (unpkg/googleapis)",
       "unpkg.com" not in corpo and "googleapis" not in corpo)
# A tela é a SEI360 original. O que não pode voltar é a FABRICAÇÃO de número:
# os contadores subiam sozinhos a cada 500 ms e sobrescreviam o valor real que o
# servidor renderiza nos mesmos elementos. ("R$ 3.218,40" continua no arquivo e
# deve continuar: é o valor de um documento de exemplo dentro da demonstração.)
checar("contador de sessões não é constante chumbada",
       'id="sessAct">3.218<' not in corpo)
checar("nenhum ticker fabricando número", "let n=847392" not in corpo and
       "s += (Math.random()<.5?1:-1)" not in corpo)
cx = conectar()
n_real = cx.execute("""SELECT COUNT(DISTINCT p.id_sei) FROM processo p
                       JOIN snapshot s ON s.id=p.snapshot_id
                       WHERE s.estado='corrente'""").fetchone()[0]
cx.close()
checar(f"a tela mostra o número real de processos ({n_real})",
       f"{n_real:,}".replace(",", ".") in corpo, "número da base não aparece na tela")
# A PORTA NAO FALA DA OPERACAO. Estado da coleta e contagem de sessoes ativas
# eram mostrados a quem ainda nao entrou: o primeiro diz de fora se o sistema
# esta atrasado, o segundo diz quanta gente esta trabalhando agora. Saiu da tela
# E do payload — esconder no template deixaria o numero no fonte da pagina.
checar("a tela de acesso ainda tem o payload com os numeros da base",
       "SEI360_REAIS" in corpo)
for _termo in ("última coleta", "Estado da coleta", "Sessões ativas",
               "ATUALIZADO", "COLETA"):
    checar(f"a porta NAO conta {_termo!r} para quem esta fora",
           _termo not in corpo, "voltou a vazar operacao na tela de acesso")
checar("nem pelo payload, que e onde alguem olharia",
       '"janela"' not in corpo and '"coleta"' not in corpo,
       "o valor saiu da tela mas continua no fonte")

# -- A TELA DE ACESSO TEM UM DONO SO DO ENVIO --
# A tela nasceu como maquete e foi ligada ao servidor depois. Duas copias do
# comportamento continuaram vivas: um `submit` que nao falava com servidor nenhum
# e escrevia "acesso liberado" no botao depois de 900 ms — por cima da recusa —
# e um segundo `click` no "ver" que alternava o campo junto com o real, de modo
# que um clique alternava DUAS vezes e a senha nunca aparecia. Numa tela cuja
# primeira entrada e com senha provisoria COLADA, era a unica forma de conferir
# a digitacao.
_s9, _tela9, _, _ = pegar(cliente(), "/entrar")
_n_sub = _tela9.count("addEventListener('submit'") + _tela9.count(".onsubmit")
checar(f"um unico dono do envio do formulario (achei {_n_sub})", _n_sub == 1,
       "duas copias do comportamento respondem ao mesmo submit")
_n_tog = _tela9.count("addEventListener('click'") + _tela9.count("togglePw').onclick")
checar(f"e um unico dono do botao 'ver' (achei {_n_tog})", _n_tog == 1,
       "duas ligacoes alternam duas vezes e a senha nunca aparece")
checar("nenhum rotulo de sucesso da maquete sobrou no botao",
       "acesso liberado</span>" not in _tela9,
       "o botao volta a anunciar sucesso sem resposta do servidor")


s, corpo, _, _ = pegar(op, "/", metodo="GET")
checar("rota protegida redireciona para o acesso", "/entrar" in _ or "Acesso ao painel" in corpo)

# ---------------------------------------------------------------- 2. login
print("\n2. autenticação")
unidades = [r["unidade"] for r in conectar().execute(
    "SELECT DISTINCT unidade FROM snapshot WHERE estado='corrente' ORDER BY unidade")]
uma = next((u for u in unidades if u.endswith("CESS")), unidades[0])
usuario_de_teste("t.gestor@teste.local", "gestor", unidades)
usuario_de_teste("t.servidor@teste.local", "servidor", [uma])
usuario_de_teste("t.admin@teste.local", "admin", [])
usuario_de_teste("t.novo@teste.local", "servidor", [uma], trocada=False)

op = cliente()
s, corpo, _, _ = entrar(op, "t.gestor@teste.local", "senha-errada-mesmo")
checar("senha errada devolve 401", s == 401, f"status {s}")
checar("mensagem não revela se a conta existe",
       "incorretos" in corpo.lower() and "não existe" not in corpo.lower())

op2 = cliente()
s2, corpo2, _, _ = entrar(op2, "ninguem@teste.local", "qualquer-coisa")
checar("e-mail inexistente devolve o MESMO 401", s2 == 401 and json.loads(corpo2)["erro"] == json.loads(corpo)["erro"])

op = cliente()
s, corpo, _, _ = entrar(op, "t.gestor@teste.local", SENHA_TESTE)
checar("login válido devolve 200", s == 200, f"status {s} {corpo[:120]}")
checar("sessão emitida em cookie HttpOnly",
       any(c.name == "sei360_sess" for c in op.jar))

# SENHA COLADA COM ESPACO SOBRANDO AINDA ENTRA. Toda conta comeca com uma senha
# provisoria COLADA — de um terminal, de um chat, de um e-mail — e a colagem
# carrega espaco ou quebra de linha no fim com frequencia. Sem aparar, a pessoa
# recebe "senha incorreta" com a senha certa na mao, e gasta as cinco tentativas
# antes do bloqueio tentando entender o que houve.
_c9 = cliente()
pegar(_c9, "/entrar")
_s9, _corpo9, _, _ = entrar(_c9, "t.gestor@teste.local", "  " + SENHA_TESTE + "\n")
checar("senha colada com espaco em volta entra do mesmo jeito", _s9 == 200,
       "status " + str(_s9) + " — " + _corpo9[:80])

print("\n2c. escopo para dezenas: a semeadura e o lote")

# -- A SEMEADURA GRAVA O VINCULO QUE JA TEM NA MAO --
# O SELECT de semear.py faz `processo JOIN snapshot`: a unidade em que a pessoa
# esta atribuida chega na MESMA linha e era descartada. Criar a conta sem o
# vinculo nao adianta — `snapshots_de` recorta a carteira por vinculo, entao a
# pessoa entra e ve uma tela vazia. Era o unico caminho para dar escopo a dezenas
# de pessoas sem cada uma digitar a senha do SEI.
import os as _os10, re as _re10, subprocess as _sp10                # noqa: E402
from pathlib import Path as _P10                                    # noqa: E402
_cx10 = conectar()
_antes10 = _cx10.execute("SELECT COUNT(DISTINCT usuario_id) FROM usuario_unidade").fetchone()[0]
_cx10.close()

_amb10 = dict(_os10.environ)
_amb10["PYTHONIOENCODING"] = "utf-8"
_r10 = _sp10.run([sys.executable, str(_P10(__file__).resolve().parent / "semear.py")],
                 env=_amb10, capture_output=True, text=True, encoding="utf-8",
                 cwd=str(_P10(__file__).resolve().parent))
checar("semear.py roda sem erro", _r10.returncode == 0, (_r10.stderr or "")[-200:])

_cx10 = conectar()
_dep10 = _cx10.execute("SELECT COUNT(DISTINCT usuario_id) FROM usuario_unidade").fetchone()[0]
_snap10 = _cx10.execute("SELECT COUNT(*) FROM usuario_unidade WHERE origem='snapshot'").fetchone()[0]
# Quantos pares (pessoa, unidade) o snapshot corrente PODE sustentar?
_deriv10 = _cx10.execute("""SELECT COUNT(*) FROM (
    SELECT DISTINCT LOWER(TRIM(p.atribuido_login)) AS login, s.unidade
    FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
    WHERE s.estado='corrente' AND p.atribuido_login LIKE '%@%')""").fetchone()[0]
checar(f"a semeadura derivou vinculo do snapshot ({_snap10} linha(s))", _snap10 > 0,
       "o vinculo continua sendo descartado no SELECT")
checar(f"gente com escopo subiu de {_antes10} para {_dep10}", _dep10 >= _antes10)
checar(f"cobre os pares derivaveis do snapshot ({_deriv10})", _snap10 >= _deriv10 * 0.9,
       f"{_snap10} de {_deriv10} pares")

# ESCOPO NAO E ACESSO: a conta semeada continua inativa e sem senha.
_semeadas10 = _cx10.execute("""SELECT COUNT(*) FROM usuarios
                               WHERE origem='auto_snapshot' AND (ativo=1 OR senha_hash IS NOT NULL)"""
                            ).fetchone()[0]
checar("dar escopo NAO ativou nem deu senha a ninguem", _semeadas10 == 0,
       f"{_semeadas10} conta(s) semeada(s) ficaram ativas ou com senha")
_cx10.close()

# IDEMPOTENTE: a chave e (usuario_id, instancia, unidade) e o INSERT e OR IGNORE.
_sp10.run([sys.executable, str(_P10(__file__).resolve().parent / "semear.py")],
          env=_amb10, capture_output=True, text=True, encoding="utf-8",
          cwd=str(_P10(__file__).resolve().parent))
_cx10 = conectar()
_dup10 = _cx10.execute("SELECT COUNT(*) FROM usuario_unidade WHERE origem='snapshot'").fetchone()[0]
_cx10.close()
checar("rodar de novo nao duplica vinculo", _dup10 == _snap10, f"{_snap10} -> {_dup10}")

# -- O LOTE DEVOLVE AS SENHAS QUE GERA --
# Antes ele sorteava, gravava o hash e DESCARTAVA o valor: a conta ficava ATIVA
# E INACESSIVEL, e o aviso mandava "abra cada uma para copiar" — mas a ficha nao
# mostra senha nenhuma. Com 57 contas eram 114 telas e nenhuma senha na mao.
usuario_de_teste("t.lote1@teste.local", "servidor", [uma], trocada=False)
usuario_de_teste("t.lote2@teste.local", "servidor", [uma], trocada=False)
_cx10 = conectar()
_ids10 = [r["id"] for r in _cx10.execute(
    "SELECT id FROM usuarios WHERE email IN ('t.lote1@teste.local','t.lote2@teste.local')")]
_cx10.execute(f"UPDATE usuarios SET ativo=0, senha_hash=NULL, senha_sal=NULL "
              f"WHERE id IN ({','.join('?' * len(_ids10))})", _ids10)
_cx10.commit(); _cx10.close()

_opa10 = cliente()
entrar(_opa10, "t.admin@teste.local", SENHA_TESTE)
_s10, _c10, _, _ = pegar(_opa10, "/admin/usuarios/lote",
                         {"acao": "ativar", "ids": [str(i) for i in _ids10],
                          "csrf": csrf(_opa10)})
_pares10 = _re10.findall(r"<td>([^<]+@[^<]+)</td><td><code[^>]*>([^<]+)</code></td>", _c10)
checar(f"o lote devolve as provisorias que gerou ({len(_pares10)})",
       len(_pares10) == len(_ids10), f"{len(_pares10)} de {len(_ids10)}")
checar("e o aviso parou de mandar 'abra cada uma para copiar'",
       "abra cada uma" not in _c10, "o texto que mente voltou")

if _pares10:
    _em10, _se10 = _pares10[0]
    _opb10 = cliente()
    pegar(_opb10, "/entrar")
    _s11, _c11, _, _ = pegar(_opb10, "/entrar",
                             {"email": _em10, "pw": _se10, "csrf": csrf(_opb10)})
    checar("a senha devolvida REALMENTE entra", _s11 == 200, f"status {_s11}")
    _s12, _c12, _cab12, _ = pegar(_opb10, "/", metodo="GET")
    checar("e a pessoa cai no primeiro acesso obrigatorio",
           "primeiro-acesso" in str(_cab12) or "Defina" in _c12 or "senha" in _c12.lower())
    # A senha nao pode sobrar em lugar nenhum persistente.
    _cx10 = conectar()
    _nlog10 = _cx10.execute("SELECT COUNT(*) FROM log_acesso WHERE alvo LIKE ?",
                            (f"%{_se10}%",)).fetchone()[0]
    _cx10.close()
    checar("a senha nao foi para o log", _nlog10 == 0, f"{_nlog10} linha(s)")
    _s13, _c13, _, _ = pegar(_opa10, f"/admin/usuarios/{_ids10[0]}")
    checar("nem para a ficha individual", _se10 not in _c13)


# ---------------------------------------------------------------- 3. bloqueio
print("\n3. bloqueio por tentativa")
usuario_de_teste("t.alvo@teste.local", "servidor", [uma])
opb = cliente()
codigos = []
for i in range(6):
    s, corpo, _, _ = entrar(opb, "t.alvo@teste.local", f"errada{i}")
    codigos.append(s)
checar("5 falhas levam a 423 (conta bloqueada)", 423 in codigos, f"códigos: {codigos}")
s, corpo, _, _ = entrar(opb, "t.alvo@teste.local", SENHA_TESTE)
checar("senha CERTA durante o bloqueio continua barrada", s == 423, f"status {s}")

# ---------------------------------------------------------------- 4. 1o acesso
print("\n4. primeiro acesso")
opn = cliente()
s, corpo, _, _ = entrar(opn, "t.novo@teste.local", SENHA_TESTE)
destino = json.loads(corpo).get("destino") if s == 200 else None
checar("login com senha provisória manda para /primeiro-acesso", destino == "/primeiro-acesso", str(destino))
s, corpo, _, url = pegar(opn, "/")
checar("painel é bloqueado antes da troca", "Defina a sua senha" in corpo, url)
s, corpo, _, _ = pegar(opn, "/primeiro-acesso",
                       {"nova": "curta", "confirma": "curta", "csrf": csrf(opn)})
checar("senha curta é recusada", "pelo menos 12" in corpo)
s, corpo, _, _ = pegar(opn, "/primeiro-acesso",
                       {"nova": "senha-boa-de-teste-1", "confirma": "outra-coisa", "csrf": csrf(opn)})
checar("confirmação divergente é recusada", "não são iguais" in corpo)
s, corpo, _, url = pegar(opn, "/primeiro-acesso",
                         {"nova": "senha-boa-de-teste-1", "confirma": "senha-boa-de-teste-1",
                          "csrf": csrf(opn)})
checar("troca aceita e devolve à tela de acesso", "Acesso ao painel" in corpo, url)
s, corpo, _, _ = pegar(opn, "/")
checar("sessão antiga foi revogada pela troca", "Acesso ao painel" in corpo)

# ---------------------------------------------------------------- 4b. limite por IP
print("\n4b. limite por IP")
opip = cliente()
s, corpo, _, _ = entrar(opip, "t.gestor@teste.local", SENHA_TESTE)
checar("login legítimo passa mesmo com muitas tentativas boas antes",
       s == 200, f"status {s} — o limite por IP não pode contar acertos")
cx = conectar()
recentes = cx.execute("""SELECT COUNT(*) FROM tentativas_login WHERE ip='127.0.0.1'
                         AND ts > datetime('now','-1 minute')""").fetchone()[0]
cx.close()

# ---------------------------------------------------------------- 5. fronteira
print("\n5. fronteira por unidade (o teste que decide o produto)")
cx = conectar()
por_unidade = {u: cx.execute("""SELECT COUNT(*) FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
                                WHERE s.estado='corrente' AND s.unidade=?""", (u,)).fetchone()[0]
               for u in unidades}
cx.close()

opg = cliente(); entrar(opg, "t.gestor@teste.local", SENHA_TESTE)
s, painel_gestor, _, _ = pegar(opg, "/")
checar("gestor abre o painel", s == 200 and "const DADOS = " in painel_gestor,
       f"status {s}; veio a tela de acesso? {'Acesso ao painel' in painel_gestor}")
if "const DADOS = " not in painel_gestor:
    print("  ABORTANDO: sem painel nao ha o que conferir de fronteira")
    sys.exit(1)
i = painel_gestor.find("const DADOS = ")
dados_gestor = json.loads(painel_gestor[i + 14: painel_gestor.index(";\n", i)])
checar(f"gestor com {len(unidades)} unidades recebe a carteira toda ({len(dados_gestor)} processos)",
       len(dados_gestor) > 1000, str(len(dados_gestor)))

ops = cliente(); entrar(ops, "t.servidor@teste.local", SENHA_TESTE)
s, painel_serv, _, _ = pegar(ops, "/")
i = painel_serv.find("const DADOS = ")
dados_serv = json.loads(painel_serv[i + 14: painel_serv.index(";\n", i)])
checar(f"servidor de UMA unidade recebe só ela ({len(dados_serv)} de {len(dados_gestor)})",
       len(dados_serv) < len(dados_gestor), f"{len(dados_serv)} vs {len(dados_gestor)}")
fora = [d for d in dados_serv if uma not in (d.get("mesas_coleta") or [])]
checar("nenhum processo de outra unidade no corpo da resposta", not fora,
       f"{len(fora)} vazaram")
# A sigla de outra unidade PODE aparecer — como campo de um processo que e do
# usuario (quem gerou, para onde foi, onde mais esta aberto). Isso o SEI mostra a
# ele dentro do proprio processo; esconder seria teatro. O que nao pode e sigla
# de outra unidade FORA do bloco de dados (faixa de coleta, filtro de mesa) nem
# registro que nao seja da unidade dele.
inicio = painel_serv.find("const DADOS = ")
fim = painel_serv.index(";" + chr(10), inicio)
fora_do_blob = painel_serv[:inicio] + painel_serv[fim:]
outras = [u for u in unidades if u != uma]
# Comparar por SUBSTRING acusaria falso: "SESAB/SAIS/DGGUP/DGESS" e prefixo de
# "SESAB/SAIS/DGGUP/DGESS/CESS", que e justamente a unidade do usuario. A sigla
# so conta quando termina ali — nao quando e o comeco do caminho de outra.
import re as _re
vazou = [u for u in outras if _re.search(_re.escape(u) + r"(?![\w/-])", fora_do_blob)]
checar("nenhuma outra unidade na moldura da página (faixa de coleta, filtros)",
       not vazou, f"vazaram: {vazou}")
checar("toda linha entregue pertence à unidade do usuário",
       all(uma in d["mesas_coleta"] for d in dados_serv))

opa = cliente(); entrar(opa, "t.admin@teste.local", SENHA_TESTE)
s, painel_admin, _, _ = pegar(opa, "/")
i = painel_admin.find("const DADOS = ")
dados_admin = json.loads(painel_admin[i + 14: painel_admin.index(";\n", i)])
checar("admin sem vínculo NÃO recebe carteira (administrar não é ler)",
       len(dados_admin) == 0, str(len(dados_admin)))
s, corpo, _, _ = pegar(opa, "/admin")
checar("admin acessa /admin", s == 200 and "Administração" in corpo)
s, corpo, _, _ = pegar(ops, "/admin")
checar("servidor recebe 403 em /admin", s == 403, f"status {s}")

# ---------------------------------------------------------------- 6. CSRF
print("\n6. CSRF")
opc = cliente(); entrar(opc, "t.gestor@teste.local", SENHA_TESTE)
s, corpo, _, _ = pegar(opc, "/sair", {"csrf": "valor-errado"})
checar("POST com CSRF errado é recusado (400)", s == 400, f"status {s}")
s, corpo, _, _ = pegar(opc, "/", metodo="GET")
checar("sessão continua viva após a tentativa", "Controle de Processos" in corpo)

# ---------------------------------------------------------------- 7. agente
print("\n7. agente e agendamento")
cx = conectar()
ag = cx.execute("SELECT * FROM agentes ORDER BY id LIMIT 1").fetchone()
import secrets as _s
codigo = _s.token_urlsafe(12)
cx.execute("""INSERT INTO enrolamentos(codigo_sha256,agente_id,criado_em,expira_em)
              VALUES(?,?,?,?)""",
           (hashlib.sha256(codigo.encode()).digest(), ag["id"], agora(),
            (datetime.now(TZ).replace(microsecond=0)).replace(year=datetime.now(TZ).year + 1).isoformat()))
cx.commit(); cx.close()

opag = cliente()
s, corpo, _, _ = pegar(opag, "/api/agente/enrolar",
                       json.dumps({"codigo": codigo, "versao": "1.0.0"}).encode(),
                       {"Content-Type": "application/json"})
checar("agente troca código por token", s == 200, f"status {s} {corpo[:120]}")
token = json.loads(corpo)["token"] if s == 200 else ""

s, corpo, _, _ = pegar(opag, "/api/agente/enrolar",
                       json.dumps({"codigo": codigo}).encode(),
                       {"Content-Type": "application/json"})
checar("código de uso único não funciona duas vezes", s == 401, f"status {s}")

def assinado(caminho, corpo_obj=None, metodo=None, tok=None, ts=None):
    corpo = json.dumps(corpo_obj).encode() if corpo_obj is not None else b""
    ts = ts or agora()
    cab = {"Authorization": f"Bearer {tok or token}",
           "X-SEI360-Ts": ts,
           "X-SEI360-Assinatura": hmac.new((tok or token).encode(),
                                           ts.encode() + b"." + corpo, hashlib.sha256).hexdigest(),
           "Content-Type": "application/json"}
    return pegar(cliente(), caminho, corpo if corpo_obj is not None else None, cab, metodo)

s, corpo, _, _ = assinado("/api/agente/tarefa", metodo="GET")
checar("GET /tarefa autenticado responde 200", s == 200, f"status {s} {corpo[:120]}")
resposta = json.loads(corpo) if s == 200 else {}
checar("servidor decide a janela e explica o motivo", "motivo" in resposta, corpo[:120])
print(f"        -> coletar={resposta.get('coletar')} motivo={resposta.get('motivo')!r}")

s, corpo, _, _ = pegar(cliente(), "/api/agente/tarefa", None,
                       {"Authorization": f"Bearer {token}"}, "GET")
checar("sem assinatura HMAC o agente é recusado (401)", s == 401, f"status {s}")

s, corpo, _, _ = assinado("/api/agente/tarefa", metodo="GET",
                          ts="2020-01-01T00:00:00-03:00")
checar("timestamp fora da janela é recusado", s == 401, f"status {s}")

s, corpo, _, _ = assinado("/api/agente/tarefa", metodo="GET", tok="token-inventado")
checar("token inválido é recusado", s == 401, f"status {s}")

s, corpo, _, _ = assinado("/api/agente/resultado",
                          {"execucao_id": None,
                           "dados": [{"id": "1", "mesa_coleta": "UNIDADE/INEXISTENTE",
                                      "mesas_coleta": ["UNIDADE/INEXISTENTE"]}]})
checar("publicação fora do escopo do agente é recusada (409)", s == 409, f"status {s}")

s, corpo, _, _ = assinado("/api/agente/resultado",
                          {"execucao_id": 999999,
                           "dados": [{"id": "1", "mesa_coleta": uma, "mesas_coleta": [uma]}]})
checar("publicação com execução inexistente é recusada (404)", s == 404, f"status {s}")

# ------------------------------------------------------------ 7b-bis. o plano
print("\n7b-bis. a porta do plano do poço")
import poco as _poco                                             # noqa: E402

_itens = [{"id": "1", "marcador": None, "atribuido_login": None}]
s, corpo, _, _ = assinado("/api/poco/plano",
                          {"mesa": uma, "parser_versao": _poco.PARSER_VERSAO,
                           "itens": _itens})
checar("o agente pergunta o plano da própria mesa e recebe veredito", s == 200,
       f"status {s} {corpo[:120]}")
_r = json.loads(corpo) if s == 200 else {}
checar("processo que o poço nunca viu volta como 'completa'",
       _r.get("veredito", {}).get("1") == "completa", corpo[:160])

s, corpo, _, _ = assinado("/api/poco/plano",
                          {"mesa": "UNIDADE/INEXISTENTE",
                           "parser_versao": _poco.PARSER_VERSAO, "itens": _itens})
checar("plano de mesa fora do escopo é recusado (409) — o veredito já é informação",
       s == 409, f"status {s}")

s, corpo, _, _ = assinado("/api/poco/plano",
                          {"mesa": uma, "parser_versao": "de-outra-era", "itens": _itens})
_r = json.loads(corpo) if s == 200 else {}
checar("coletor de outra versão do parser recebe 'leia tudo', nunca bloco antigo",
       s == 200 and _r.get("veredito", {}).get("1") == "completa", corpo[:160])

s, corpo, _, _ = pegar(cliente(), "/api/poco/plano",
                       json.dumps({"mesa": uma, "itens": []}).encode(),
                       {"Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"})
checar("sem assinatura HMAC o plano é recusado (401)", s == 401, f"status {s}")

s, corpo, _, _ = assinado("/api/poco/plano", {"mesa": uma})
checar("corpo sem itens é recusado (400)", s == 400, f"status {s}")

s, corpo, _, _ = assinado("/api/poco/plano",
                          {"mesa": uma, "execucao_id": 999999,
                           "parser_versao": _poco.PARSER_VERSAO, "itens": _itens})
checar("plano sobre execução que não é deste agente é recusado (404)",
       s == 404, f"status {s}")

# --- O PLANO COM O POÇO QUENTE ------------------------------------------------
# Com o poço vazio todo veredito é 'completa', e era só isso que a porta produzia.
# Os vereditos que existem por causa da regra de vazamento nunca passavam por aqui
# — e é neles que mora o dono: trocar `dono_usuario_id` por `id` do agente daria
# 'pular' para uma pessoa cujo acompanhamento é de outra, sem erro nenhum.
_cxp = conectar()
# O agente precisa de DONO: e do dono que sai o acompanhamento, e sem ele o
# veredito nunca chega a 'pular'. Restaurado no fim do bloco, para nao mudar o que
# os testes seguintes veem.
_dono_antes = _cxp.execute("SELECT dono_usuario_id FROM agentes WHERE id=1").fetchone()[0]
_dono_ag = _dono_antes or _cxp.execute(
    "SELECT id FROM usuarios WHERE email=?", ("t.gestor@teste.local",)).fetchone()[0]
_cxp.execute("UPDATE agentes SET dono_usuario_id=? WHERE id=1", (_dono_ag,))
_linha_q = {"id": "T-POCO-1", "mesa_coleta": uma, "protocolo": "019.T.1",
            "marcador": "PAGAMENTO", "atribuido_login": "alguem", "anotacao_data": None,
            "marcador_cor": "azul", "retorno": None, "doc_incluido": False,
            "autuacao": "28/07/2025 08:58", "gerador_unidade": "X", "gerador_usuario": "y",
            "nivel_acesso": "Público", "documentos": 5, "mesas_fonte": "arvore",
            "alterar_disponivel": True, "acomp_disponivel": True,
            "acompanhamento": [{"grupo": "G", "observacao": "", "usuario": "u", "data": ""}],
            "acomp_grupos": ["G"], "mov_custodia": [
                {"dh": "07/08/2026 15:39", "un": uma, "us": "w",
                 "de": "Processo recebido na unidade"}],
            "_fresco": True, "sem_historico": False, "truncado": False, "mov_parcial": False}
_poco.publicar(_cxp, [_linha_q], dono_usuario_id=_dono_ag, coletado_em=agora(), instancia="SEI-SESAB")
_cxp.commit(); _cxp.close()
_it_q = [{k: _linha_q[k] for k in ("id", "atribuido_login", "marcador", "marcador_cor",
                                   "anotacao_data", "retorno", "doc_incluido")}]
s, corpo, _, _ = assinado("/api/poco/plano",
                          {"mesa": uma, "parser_versao": _poco.PARSER_VERSAO, "itens": _it_q})
_r = json.loads(corpo) if s == 200 else {}
checar("bloco fresco do PRÓPRIO dono, guarda igual: a porta devolve 'pular'",
       _r.get("veredito", {}).get("T-POCO-1") == "pular", corpo[:200])

# a mesma pergunta com a lista MUDADA tem de voltar a ler
s, corpo, _, _ = assinado("/api/poco/plano",
                          {"mesa": uma, "parser_versao": _poco.PARSER_VERSAO,
                           "itens": [dict(_it_q[0], marcador="OUTRO")]})
_r = json.loads(corpo) if s == 200 else {}
checar("marcador novo na lista: a porta volta a mandar ler",
       _r.get("veredito", {}).get("T-POCO-1") == "completa", corpo[:200])

# e o acompanhamento de OUTRA pessoa não serve: o dono é lido do agente
_cxp = conectar()
_cxp.execute("DELETE FROM poco_acompanhamento WHERE id_sei='T-POCO-1'")
_cxp.commit(); _cxp.close()
s, corpo, _, _ = assinado("/api/poco/plano",
                          {"mesa": uma, "parser_versao": _poco.PARSER_VERSAO, "itens": _it_q})
_r = json.loads(corpo) if s == 200 else {}
checar("sem o acompanhamento DESTA pessoa, a porta pede só ele",
       _r.get("veredito", {}).get("T-POCO-1") == "so_acompanhamento", corpo[:200])

_cxp = conectar()
_cxp.execute("UPDATE agentes SET dono_usuario_id=? WHERE id=1", (_dono_antes,))
_cxp.commit(); _cxp.close()

# ------------------------------------------------- 7c. ordem entre duas coletas
# Reingerir um arquivo antigo — para reprocessar, para conferir, por engano — já
# fez o dado velho tomar o lugar do novo EM SILÊNCIO nesta base: seis snapshots
# `expirado` ficaram com data POSTERIOR à do corrente, e o painel passou a
# mostrar a carteira de ontem sem nenhum aviso. O caso é sorrateiro porque o
# arquivo antigo é legítimo: nada nele denuncia que está atrasado, só a data.
#
# O teste é deliberadamente pelo caminho MAIS permissivo: `forcar=True` desliga
# o gate de queda suspeita. Nem forçado o passado pode vencer o presente.
print("\n7c. a coleta de ontem não derruba a de hoje")
import ingestao as _ing                                          # noqa: E402
import tempfile as _tempfile                                     # noqa: E402
from pathlib import Path as _Path                                # noqa: E402

UNI_ORDEM = "UNIDADE/ORDEM-TESTE"
_pasta_ordem = _Path(_tempfile.mkdtemp(prefix="sei360_ordem_"))


def _coleta_falsa(nome, ids):
    arq = _pasta_ordem / nome
    arq.write_text(json.dumps(
        [{"id": i, "processo": f"0000.{i}", "mesa_coleta": UNI_ORDEM,
          "mesas_coleta": [UNI_ORDEM], "mesas_conta": [UNI_ORDEM]} for i in ids],
        ensure_ascii=False), encoding="utf-8")
    return str(arq)


_ing.ingerir(_coleta_falsa("hoje.json", ["o1", "o2", "o3"]), forcar=True,
             coletado_em="2026-08-19T07:43:00-03:00")
_ing.ingerir(_coleta_falsa("ontem.json", ["o1"]), forcar=True,
             coletado_em="2026-08-18T07:43:00-03:00")

cx = conectar()
_linhas = cx.execute("""SELECT id,coletado_em,estado,motivo,unicos FROM snapshot
                        WHERE unidade=? ORDER BY id""", (UNI_ORDEM,)).fetchall()
_corrente = [l for l in _linhas if l["estado"] == "corrente"]
checar("depois de reingerir a coleta de ontem, a corrente continua sendo a de hoje",
       len(_corrente) == 1 and _corrente[0]["coletado_em"].startswith("2026-08-19"),
       str([dict(l) for l in _linhas]))
checar("a coleta atrasada fica REJEITADA, e o motivo diz por quê",
       any(l["estado"] == "rejeitado" and "anterior à corrente" in (l["motivo"] or "")
           for l in _linhas),
       str([dict(l) for l in _linhas]))
# Snapshot rejeitado não pode deixar processo para trás: se as 3 linhas de hoje
# virassem 1, o painel mostraria a carteira encolhida mesmo com o snapshot certo.
_visiveis = cx.execute("""SELECT COUNT(*) FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
                          WHERE s.unidade=? AND s.estado='corrente'""", (UNI_ORDEM,)).fetchone()[0]
checar("a carteira visível continua com os 3 processos de hoje", _visiveis == 3,
       f"{_visiveis} processos")

# Limpeza: esta unidade é de teste e não pode sobreviver à suíte.
_ids = [l["id"] for l in _linhas]
if _ids:
    _m = ",".join("?" * len(_ids))
    cx.execute(f"DELETE FROM processo WHERE snapshot_id IN ({_m})", _ids)
    cx.execute(f"DELETE FROM processo_texto WHERE snapshot_id IN ({_m})", _ids)
    cx.execute(f"DELETE FROM snapshot WHERE id IN ({_m})", _ids)
cx.execute("DELETE FROM alerta WHERE unidade=?", (UNI_ORDEM,))
cx.commit(); cx.close()


# ------------------------------------------------------- 7b. defeitos da auditoria
# Estes existem porque a auditoria mostrou que as 46 verificações originais
# passavam com TODOS os defeitos vivos. Teste que não olha não é garantia.
print("\n7b. regressões da auditoria")

opx = cliente()
pegar(opx, "/entrar")
s, corpo, _, _ = pegar(opx, "/entrar", {"email": "t.gestor@teste.local", "pw": SENHA_TESTE,
                                        "csrf": csrf(opx), "proximo": "javascript:alert(1)"})
destino = json.loads(corpo).get("destino") if s == 200 else "?"
checar("proximo com javascript: não vira destino (o JS faz location.href=destino)",
       destino == "/", f"destino={destino!r}")

opx = cliente(); pegar(opx, "/entrar")
s, corpo, _, _ = pegar(opx, "/entrar", {"email": "t.gestor@teste.local", "pw": SENHA_TESTE,
                                        "csrf": csrf(opx), "proximo": "//evil.example.com/x"})
destino = json.loads(corpo).get("destino") if s == 200 else "?"
checar("proximo com // (host externo) não vira destino", destino == "/", f"destino={destino!r}")

opx = cliente(); entrar(opx, "t.gestor@teste.local", SENHA_TESTE)
s, corpo, _, _ = pegar(opx, "/primeiro-acesso", metodo="GET")
checar("/primeiro-acesso fecha para quem já trocou a senha (404)", s == 404, f"status {s}")

# A armadilha do prefixo, agora do lado do admin: DGESS é prefixo de DGESS/CESS.
opa2 = cliente(); entrar(opa2, "t.admin@teste.local", SENHA_TESTE)
s, html_admin, _, _ = pegar(opa2, "/admin")
import re as _re2
bloco = html_admin[html_admin.find("t.servidor@teste.local"):]
bloco = bloco[:bloco.find("</tr></table>") if "</tr></table>" in bloco[:6000] else 6000]
pai = [m for m in _re2.finditer(r'value="([^"]+)"\s+checked', bloco)]
marcadas = {m.group(1) for m in pai}
checar("admin não marca unidade-pai por substring (DGESS x DGESS/CESS)",
       marcadas <= {uma}, f"marcadas para t.servidor: {marcadas}")

cx = conectar()
antes = cx.execute("SELECT papel FROM usuarios WHERE email='t.admin@teste.local'").fetchone()["papel"]
uid_admin = cx.execute("SELECT id FROM usuarios WHERE email='t.admin@teste.local'").fetchone()["id"]
cx.close()
pegar(opa2, "/admin/usuario", {"csrf": csrf(opa2), "acao": "papel", "id": str(uid_admin),
                               "papel": "servidor"})
cx = conectar()
depois = cx.execute("SELECT papel FROM usuarios WHERE id=?", (uid_admin,)).fetchone()["papel"]
cx.close()
checar("admin não consegue rebaixar a si mesmo", antes == depois == "admin", f"{antes} -> {depois}")

cx = conectar()
cx.execute("DELETE FROM usuarios WHERE email='t.criado@teste.local'")
cx.commit(); cx.close()
s, corpo, cab, _ = pegar(opa2, "/admin/usuario",
                         {"csrf": csrf(opa2), "acao": "criar", "papel": "servidor",
                          "email": "t.criado@teste.local", "nome": "Criado no teste"})
checar("senha provisória vem no CORPO, não na URL",
       "Senha provisória" in corpo and "senha=" not in (cab.get("Location") or ""),
       f"location={cab.get('Location')!r}")

cx = conectar()
sem_senha = cx.execute("""SELECT id,email FROM usuarios WHERE senha_hash IS NULL
                          AND origem='auto_snapshot' LIMIT 1""").fetchone()
cx.close()
if sem_senha:
    s, corpo, _, _ = pegar(opa2, "/admin/usuario",
                           {"csrf": csrf(opa2), "acao": "nova_senha", "id": str(sem_senha["id"])})
    m = _re2.search(r"<code>([^<]+)</code>", corpo)
    nova = m.group(1).strip() if m else ""
    cx = conectar()
    cx.execute("UPDATE usuarios SET ativo=1 WHERE id=?", (sem_senha["id"],))
    cx.commit(); cx.close()
    opz = cliente()
    s2, c2, _, _ = entrar(opz, sem_senha["email"], nova)
    checar("conta semeada sem senha volta a ser acessível com 'Nova senha'",
           s2 == 200 and json.loads(c2).get("destino") == "/primeiro-acesso",
           f"status {s2}")
    cx = conectar(); cx.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (sem_senha["id"],))
    cx.commit(); cx.close()

# Reaper: execução em curso sem pulso não pode segurar a janela para sempre.
cx = conectar()
velho = "2026-01-01T07:30:00-03:00"
cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em,iniciado_em,heartbeat_em)
              VALUES(1,?,'em_curso','janela',?,?,?)""", (velho, velho, velho, velho))
travada_id = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()
assinado("/api/agente/tarefa", metodo="GET")
cx = conectar()
estado = cx.execute("SELECT estado FROM execucao WHERE id=?", (travada_id,)).fetchone()["estado"]
cx.close()
checar("execução sem pulso vira 'travada' e libera a janela", estado == "travada", estado)

# Data sem fuso no banco não pode derrubar a tela de login.
cx = conectar()
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado)
              VALUES(NULL,'UNIDADE/SEM-FUSO','2026-08-18T07:45:00',1,'corrente')""")
cx.commit(); cx.close()
s, corpo, _, _ = pegar(cliente(), "/entrar")
checar("carimbo sem fuso no banco não derruba /entrar", s == 200, f"status {s}")
cx = conectar()
cx.execute("DELETE FROM snapshot WHERE unidade='UNIDADE/SEM-FUSO'")
cx.commit(); cx.close()

# ------------------------------------------------------- 7c. achados da revisão
print("\n7d. correções da revisão")

cx = conectar()
cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em,terminado_em)
              VALUES(1,?,'concluida','janela',?,?)""", (agora(), agora(), agora()))
ex_fim = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()
s, corpo, _, _ = assinado("/api/agente/evento",
                          {"execucao_id": ex_fim, "tipo": "fim", "exit_code": 3})
checar("'fim' em execução já encerrada é recusado (409)", s == 409, f"status {s}")
cx = conectar()
estado = cx.execute("SELECT estado FROM execucao WHERE id=?", (ex_fim,)).fetchone()["estado"]
cx.close()
checar("o desfecho anterior permanece intacto", estado == "concluida", estado)

s, corpo, _, _ = assinado("/api/agente/evento", {"execucao_id": ex_fim, "tipo": "voar"})
checar("tipo de evento desconhecido é recusado (400)", s == 400, f"status {s}")

# Snapshot retido tinha de ter saída: `candidato` era estado terminal.
cx = conectar()
uni_teste = "SESAB/TESTE/CANDIDATO"
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado,suspeito,motivo)
              VALUES(NULL,?,?,7,'corrente',0,NULL)""", (uni_teste, agora()))
antigo = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado,suspeito,motivo)
              VALUES(NULL,?,?,2,'candidato',1,'queda de 7 para 2')""", (uni_teste, agora()))
cand = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()

opa3 = cliente(); entrar(opa3, "t.admin@teste.local", SENHA_TESTE)
s, corpo, _, _ = pegar(opa3, "/admin")
checar("snapshot retido aparece na tela de administração",
       "Snapshots retidos" in corpo and uni_teste in corpo)
pegar(opa3, "/admin/snapshot", {"csrf": csrf(opa3), "acao": "promover", "id": str(cand)})
cx = conectar()
e_novo = cx.execute("SELECT estado FROM snapshot WHERE id=?", (cand,)).fetchone()["estado"]
e_velho = cx.execute("SELECT estado FROM snapshot WHERE id=?", (antigo,)).fetchone()["estado"]
cx.close()
checar("promover troca o corrente da unidade",
       e_novo == "corrente" and e_velho == "expirado", f"{e_novo}/{e_velho}")

cx = conectar()
cx.execute("UPDATE snapshot SET estado='candidato' WHERE id=?", (cand,))
cx.commit(); cx.close()
pegar(opa3, "/admin/snapshot", {"csrf": csrf(opa3), "acao": "rejeitar", "id": str(cand)})
cx = conectar()
e_rej = cx.execute("SELECT estado FROM snapshot WHERE id=?", (cand,)).fetchone()["estado"]
cx.close()
checar("rejeitar grava 'rejeitado' (estado que antes ninguém escrevia)",
       e_rej == "rejeitado", e_rej)

# RESUMO DE PROCESSO QUE SAIU DA CARTEIRA NAO CONTA. `resumo` guarda por id_sei e
# nao e apagado quando o processo sai; a rotatividade entre duas coletas deixou
# 113 resumos orfaos, e eles entravam no numerador de "N com resumo" enquanto o
# "N sem" era contado sobre a carteira corrente. Somava 1.310 sobre uma base de
# 1.197 — e e esse numero que decide se vale mandar gerar mais resumo, e quanto.
import app as _ap14                                              # noqa: E402
cx = conectar()
_com_antes = cx.execute(_ap14.SQL_COM_RESUMO).fetchone()[0]
cx.execute("""INSERT OR REPLACE INTO resumo(id_sei,instancia,curto,gerado_em,gerado_por)
              VALUES('999999999','SEI-SESAB',?,?,'teste/orfao/nenhum')""",
           ("resumo de processo que nao esta em snapshot nenhum", agora()))
cx.commit()
_com_depois = cx.execute(_ap14.SQL_COM_RESUMO).fetchone()[0]
_bruto = cx.execute("SELECT COUNT(*) FROM resumo").fetchone()[0]
cx.close()
checar("resumo orfao NAO entra na contagem da carteira",
       _com_antes == _com_depois, f"{_com_antes} -> {_com_depois}")
checar("e a contagem crua da tabela e mesmo maior (o orfao existe)",
       _bruto > _com_depois, f"tabela {_bruto}, carteira {_com_depois}")
cx = conectar()
cx.execute("DELETE FROM resumo WHERE id_sei='999999999'")
cx.commit(); cx.close()

# SALVAR VINCULO SEM MUDAR NADA NAO PODE REESCREVER A ORIGEM. O formulario vem
# com as unidades atuais marcadas, entao "Salvar vinculo" sem alterar e o clique
# mais provavel — e ele apagava tudo e reinseria sem `origem`, que caia no
# DEFAULT 'admin'. Vinculo descoberto entrando no SEI virava concedido a mao, e
# a reconciliacao do "Testar acesso" (que so desfaz o que ELA criou) perdia para
# sempre a capacidade de tirar acesso que o SEI tirou.
cx = conectar()
_uid_s = cx.execute("SELECT id FROM usuarios WHERE email='t.servidor@teste.local'").fetchone()[0]
cx.execute("UPDATE usuario_unidade SET origem='sei', principal=1 WHERE usuario_id=?", (_uid_s,))
cx.commit()
_uns_s = [r["unidade"] for r in cx.execute(
    "SELECT unidade FROM usuario_unidade WHERE usuario_id=?", (_uid_s,))]
cx.close()
pegar(opa3, "/admin/usuario", {"csrf": csrf(opa3), "acao": "unidades", "id": str(_uid_s),
                               "unidades": _uns_s})
cx = conectar()
_depois_s = {r["unidade"]: (r["origem"], r["principal"]) for r in cx.execute(
    "SELECT * FROM usuario_unidade WHERE usuario_id=?", (_uid_s,))}
cx.close()
checar("salvar sem mudar preserva origem='sei'",
       all(v[0] == "sei" for v in _depois_s.values()), str(_depois_s))
checar("e preserva o vinculo principal",
       all(v[1] == 1 for v in _depois_s.values()), str(_depois_s))

# PROMOVER RECORTA POR DONO E POR INSTALACAO. O UPDATE expirava TODO corrente da
# unidade: a coleta propria de quem ja tinha rodado a sua virava 'expirado' por
# causa da decisao sobre o snapshot compartilhado — e, no caminho inverso, o
# compartilhado morria e a unidade SUMIA do painel de quem nao tem coleta
# propria, sem alerta nenhum.
cx = conectar()
_uid_g = cx.execute("SELECT id FROM usuarios WHERE email='t.gestor@teste.local'").fetchone()[0]
_uni_d = "SESAB/TESTE/DONOS"
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado,
              dono_usuario_id,instancia) VALUES(NULL,?,?,9,'corrente',NULL,'SEI-SESAB')""",
           (_uni_d, agora()))
_compart = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado,
              dono_usuario_id,instancia) VALUES(NULL,?,?,20,'corrente',?,'SEI-SESAB')""",
           (_uni_d, agora(), _uid_g))
_meu = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado,
              dono_usuario_id,instancia) VALUES(NULL,?,?,9,'corrente',NULL,'SEI-FESF')""",
           (_uni_d, agora()))
_outra_inst = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado,suspeito,
              motivo,dono_usuario_id,instancia)
              VALUES(NULL,?,?,3,'candidato',1,'queda',NULL,'SEI-SESAB')""",
           (_uni_d, agora()))
_cand_d = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()

pegar(opa3, "/admin/snapshot", {"csrf": csrf(opa3), "acao": "promover", "id": str(_cand_d)})
cx = conectar()
_est = {n: cx.execute("SELECT estado FROM snapshot WHERE id=?", (i,)).fetchone()["estado"]
        for n, i in (("compartilhado", _compart), ("do gestor", _meu),
                     ("outra instalacao", _outra_inst), ("candidato", _cand_d))}
cx.close()
checar("promover expira o corrente do MESMO dono", _est["compartilhado"] == "expirado", str(_est))
checar("e o candidato vira corrente", _est["candidato"] == "corrente", str(_est))
checar("mas NAO toca na coleta propria de outra pessoa",
       _est["do gestor"] == "corrente", str(_est))
checar("nem na mesma unidade da OUTRA instalacao do SEI",
       _est["outra instalacao"] == "corrente", str(_est))

# O GESTOR DECIDE NA UNIDADE DELE — a tela /alertas ja lhe mostrava os botoes, e
# eles postavam numa rota `@exige_admin`: 403 garantido, com o painel preso no
# retrato velho e nenhuma saida.
cx = conectar()
cx.execute("UPDATE snapshot SET estado='candidato' WHERE id=?", (_cand_d,))
cx.execute("UPDATE snapshot SET estado='corrente' WHERE id=?", (_compart,))
cx.commit(); cx.close()
_opg2 = cliente(); entrar(_opg2, "t.gestor@teste.local", SENHA_TESTE)
_s, _c, _, _ = pegar(_opg2, "/admin/snapshot",
                     {"csrf": csrf(_opg2), "acao": "promover", "id": str(_cand_d)})
checar("gestor NAO decide sobre unidade que nao alcanca (403)", _s == 403, f"status {_s}")
cx = conectar()
cx.execute("INSERT OR IGNORE INTO usuario_unidade(usuario_id,unidade,concedida_em) "
           "VALUES(?,?,?)", (_uid_g, _uni_d, agora()))
cx.commit(); cx.close()
_s, _c, _, _ = pegar(_opg2, "/admin/snapshot",
                     {"csrf": csrf(_opg2), "acao": "promover", "id": str(_cand_d)})
cx = conectar()
_e = cx.execute("SELECT estado FROM snapshot WHERE id=?", (_cand_d,)).fetchone()["estado"]
cx.close()
checar("mas decide na unidade DELE", _e == "corrente", f"status {_s}, estado {_e}")

# LIMPA O QUE ESTE BLOCO CRIOU. Os snapshots ficariam 'corrente' e a contagem de
# `/saude` — conferida mais abaixo contra a lista de unidades da instalacao —
# passaria a acusar unidade que so existe dentro deste teste.
cx = conectar()
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=? AND unidade=?", (_uid_g, _uni_d))
cx.execute("DELETE FROM snapshot WHERE unidade=?", (_uni_d,))
cx.commit(); cx.close()

# A coleta que NÃO aconteceu não aparecia em lugar nenhum: estação desligada não
# gera execução, e ausência ninguém vê. A taxa base medida em campo é 1 janela
# perdida em 6, então isto não é hipótese.
cx = conectar()
cfg = cx.execute("SELECT * FROM agendamento WHERE agente_id=1").fetchone()
# A janela do agente NAO e o horario configurado: e ele MAIS o desvio estavel do
# escalonamento. Sessenta contas com "07:30" no papel acordariam no mesmo minuto e
# bateriam juntas no mesmo servidor do SEI. Calcular aqui o mesmo desvio que o
# servidor calcula e o que faz este teste medir o comportamento, e nao um ISO.
import janelas as _jan                                              # noqa: E402
# A IDENTIDADE da janela e o horario CONFIGURADO; o desvio do escalonamento vive
# so no relogio. Guardar o ISO deslocado fazia a chave mudar quando alguem editava
# a tolerancia — e a coleta ja feita deixava de casar.
_desvio = _jan.desvio_do_agente(1)
_base = datetime.now(TZ).replace(hour=0, minute=5, second=0, microsecond=0)
_acorda = _base + timedelta(minutes=_desvio)
_vence = _acorda + timedelta(minutes=cfg["tolerancia_min"])
janela_ontem = _base.isoformat(timespec="seconds")
# O agente 1 é o pareado da suíte (tem token) — mas precisa de DONO: só recebe
# janela quem tem de quem tirar credencial.
dono_1 = cx.execute("SELECT id FROM usuarios ORDER BY id LIMIT 1").fetchone()[0]
cx.execute("UPDATE agentes SET dono_usuario_id=COALESCE(dono_usuario_id,?), "
           "pausado_motivo=NULL WHERE id=1", (dono_1,))
cx.execute("UPDATE agendamento SET janelas='[\"00:05\"]', ativo=1, dias='todos' WHERE agente_id=1")
cx.execute("DELETE FROM execucao WHERE janela=? AND estado='perdida'", (janela_ontem,))
cx.commit(); cx.close()
assinado("/api/agente/tarefa", metodo="GET")            # dispara a varredura
cx = conectar()
perdida = cx.execute("""SELECT COUNT(*) FROM execucao WHERE janela=? AND estado='perdida'""",
                     (janela_ontem,)).fetchone()[0]
alerta_p = cx.execute("""SELECT COUNT(*) FROM alerta WHERE tipo='janela_perdida'""").fetchone()[0]
cx.commit(); cx.close()
# A asserção depende do RELÓGIO, e por isso ela é dupla em vez de otimista: a
# janela só pode ser cobrada depois de vencer a tolerância. Antes disso, cobrar
# seria o defeito. Rodar a suíte de madrugada não pode inventar uma falha.
if datetime.now(TZ) > _vence:
    checar("janela que fechou sem ninguém pedir vira execução 'perdida'",
           perdida == 1, str(perdida))
else:
    checar(f"janela que ainda não venceu (vence {_vence:%H:%M}) NÃO é cobrada",
           perdida == 0, str(perdida))
checar("e gera alerta — a coleta que não aconteceu deixa de ser invisível",
       alerta_p >= 1, str(alerta_p))

# O OUTRO lado, que é o defeito que esta fatia conserta: agente que nunca foi
# pareado não pode gerar "janela perdida". O texto do alerta diz "estação
# desligada, sem rede ou tarefa não agendada" — três acusações, todas erradas,
# para uma coleta que o sistema nunca teve como fazer. Foram 18 janelas perdidas
# e 27 coletas travadas assim, todas do agente lógico do modo servidor.
cx = conectar()
cx.execute("""INSERT INTO agentes(nome_estacao,unidades_esperadas,ativo,criado_em,pausado_motivo)
              VALUES('SERVIDOR/orfao','[]',1,?,'modo servidor: não há executor')""", (agora(),))
ag_orfao = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.execute("INSERT INTO agendamento(agente_id,janelas,dias,ativo) VALUES(?,'[\"05:15\"]','todos',1)",
           (ag_orfao,))
antes_orfao = cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=?",
                         (ag_orfao,)).fetchone()[0]
cx.commit(); cx.close()
assinado("/api/agente/tarefa", metodo="GET")            # dispara a varredura de novo
cx = conectar()
depois_orfao = cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=?",
                          (ag_orfao,)).fetchone()[0]
checar("agente nunca pareado NÃO ganha janela perdida (o sistema não culpa o usuário)",
       depois_orfao == antes_orfao == 0, f"{antes_orfao} -> {depois_orfao}")
cx.execute("DELETE FROM agendamento WHERE agente_id=?", (ag_orfao,))
cx.execute("DELETE FROM execucao WHERE agente_id=?", (ag_orfao,))
cx.execute("DELETE FROM agentes WHERE id=?", (ag_orfao,))
cx.execute("UPDATE agendamento SET janelas=?, dias=? WHERE agente_id=1",
           (cfg["janelas"], cfg["dias"]))
cx.commit(); cx.close()

# ------------------------------------------- 7c-bis. alertas que dá para ler
# 78 ocorrências em 4 grupos, sendo 77 do mesmo defeito. Numa lista corrida, a
# única ocorrência DIFERENTE fica na página três — e a fila que não esvazia
# deixa de ser aberta. Agrupar não é enfeite: é o que mantém a tela sendo lida.
print("\n7c-bis. alertas agrupados e reconhecimento em lote")
cx = conectar()
UNI_AL = "UNIDADE/ALERTA-TESTE"
cx.execute("DELETE FROM alerta WHERE unidade=?", (UNI_AL,))
for i in range(7):
    cx.execute("""INSERT INTO alerta(ts,tipo,severidade,unidade,texto)
                  VALUES(?,?,?,?,?)""",
               (agora(), "mesa_falhou", "alta", UNI_AL, f"ocorrência repetida {i}"))
ids_al = [r[0] for r in cx.execute("SELECT id FROM alerta WHERE unidade=?", (UNI_AL,))]
# O gestor da suíte precisa enxergar a unidade para poder reconhecer.
g_id = cx.execute("SELECT id FROM usuarios WHERE email='t.gestor@teste.local'").fetchone()[0]
cx.execute("INSERT OR IGNORE INTO usuario_unidade(usuario_id,unidade,concedida_em) VALUES(?,?,?)",
           (g_id, UNI_AL, agora()))
cx.commit(); cx.close()

opal = cliente(); entrar(opal, "t.gestor@teste.local", SENHA_TESTE)
s, tela, _, _ = pegar(opal, "/alertas")
checar("a tela de alertas abre para gestor", s == 200, f"status {s}")
checar("as 7 repetições aparecem como UM grupo, com a contagem",
       "Dar por vistos (7)" in tela, "não achei o botão de lote com 7")
checar("a lista ocorrência a ocorrência continua disponível, recolhida",
       "<details" in tela and "Ver ocorrência por" in tela)

s, _, _, _ = pegar(opal, "/alertas/lote", {"csrf": csrf(opal), "ids": [str(i) for i in ids_al]})
cx = conectar()
abertos = cx.execute("SELECT COUNT(*) FROM alerta WHERE unidade=? AND reconhecido_em IS NULL",
                     (UNI_AL,)).fetchone()[0]
cx.close()
checar("reconhecer em lote zera o grupo de uma vez", abertos == 0, f"{abertos} ainda abertos")

# A fronteira do lote é a mesma da ação individual. Sem esta conferência, o lote
# seria a porta larga por onde se reconhece alerta de unidade alheia.
cx = conectar()
cx.execute("""INSERT INTO alerta(ts,tipo,severidade,unidade,texto)
              VALUES(?,?,?,?,?)""", (agora(), "mesa_falhou", "alta",
                                     "UNIDADE/NAO-MINHA", "de outra unidade"))
alheio = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()
pegar(opal, "/alertas/lote", {"csrf": csrf(opal), "ids": [str(alheio)]})
cx = conectar()
ainda = cx.execute("SELECT reconhecido_em FROM alerta WHERE id=?", (alheio,)).fetchone()[0]
cx.execute("DELETE FROM alerta WHERE id=? OR unidade=?", (alheio, UNI_AL))
cx.execute("DELETE FROM usuario_unidade WHERE unidade=?", (UNI_AL,))
cx.commit(); cx.close()
checar("o lote não alcança alerta de unidade alheia", ainda is None, str(ainda))

# Recusa legível: agente sem dono não tem de quem tirar credencial. Entregar
# tarefa a ele produz falha de login e um alerta que aponta o motivo errado —
# e motivo errado é pior que nenhum, porque manda procurar no lugar errado.
cx = conectar()
dono_antes = cx.execute("SELECT dono_usuario_id FROM agentes WHERE id=1").fetchone()[0]
cx.execute("UPDATE agentes SET dono_usuario_id=NULL WHERE id=1")
cx.commit(); cx.close()
s, corpo, _, _ = assinado("/api/agente/tarefa", metodo="GET")
_j = json.loads(corpo) if s == 200 else {}
cx = conectar()
cx.execute("UPDATE agentes SET dono_usuario_id=? WHERE id=1", (dono_antes,))
cx.commit(); cx.close()
checar("agente sem dono recebe recusa, não tarefa", _j.get("coletar") is False, corpo[:120])
checar("e a recusa diz o que fazer, em português",
       "não tem dono" in (_j.get("motivo") or "") and "/admin" in (_j.get("motivo") or ""),
       _j.get("motivo", "")[:140])

# ------------------- 7d-ter. a tarefa de COLETA leva instalação e perfil
# A tarefa de BUSCA já mandava `perfil` (`/api/agente/busca`); a de coleta, não.
# O coletor sem perfil cai na constante interna — a SESAB —, então uma coleta da
# FESF entraria no SEI errado e falharia de um jeito que parece senha inválida.
# As duas metades do mesmo agente não podem falar de instalações diferentes.
import perfil_sei as _psei                                        # noqa: E402
cx = conectar()
_dono_t = cx.execute("SELECT dono_usuario_id FROM agentes WHERE id=1").fetchone()[0]
_pausa_t = cx.execute("SELECT pausado_motivo FROM agentes WHERE id=1").fetchone()[0]
cx.execute("UPDATE agentes SET pausado_motivo=NULL WHERE id=1")
cx.execute("UPDATE agendamento SET ativo=1, motivo_inativo=NULL WHERE agente_id=1")
cx.execute("DELETE FROM execucao WHERE agente_id=1 AND estado IN ('entregue','em_curso')")
# Execução ENTREGUE força o ramo "retomando", que responde sem depender de haver
# janela devida agora — o contrato tem de ser o mesmo nos dois ramos.
cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em)
              VALUES(1,?,'entregue','manual_admin',?)""", (agora(), agora()))
cx.execute("DELETE FROM config_usuario WHERE usuario_id=? AND sistema='SEI-FESF'", (_dono_t,))
cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,atualizado_em)
              VALUES(?,'SEI-FESF',?)""", (_dono_t, agora()))
cx.commit(); cx.close()
s, corpo, _, _ = assinado("/api/agente/tarefa", metodo="GET")
_t = json.loads(corpo) if s == 200 else {}
# A instalação vem da configuração do DONO — e a prova é a recusa citar a FESF:
# com a instalação saindo do padrão, nada disto apareceria.
checar("a instalação da tarefa é derivada da configuração do dono",
       _t.get("instancia") == "SEI-FESF", corpo[:180])
# E `disponivel_coleta` VIRA TRAVA. Desde que o passo 1 aceita instalação que só
# serve para buscar, alguém pode configurar coleta na FESF: o coletor entraria, a
# visualização Detalhada falharia em silêncio (é do SEI 5) e a publicação seria
# carteira vazia com cara de carteira vazia de verdade.
checar("instalação sem coletor NÃO recebe tarefa de coleta",
       _t.get("coletar") is False, corpo[:180])
checar("e a recusa traz o motivo escrito no perfil, não um texto genérico",
       _psei.INSTANCIAS["SEI-FESF"]["motivo_sem_coleta"][:40] in (_t.get("motivo") or ""),
       (_t.get("motivo") or "")[:180])
checar("dizendo também que a BUSCA continua funcionando lá",
       "busca nesta instalação continua" in (_t.get("motivo") or ""),
       (_t.get("motivo") or "")[:180])

cx = conectar()
cx.execute("DELETE FROM config_usuario WHERE usuario_id=? AND sistema='SEI-FESF'", (_dono_t,))
cx.commit(); cx.close()
# Instalação que COLETA: a tarefa sai, com instalação e perfil junto.
s, corpo, _, _ = assinado("/api/agente/tarefa", metodo="GET")
_t2 = json.loads(corpo) if s == 200 else {}
checar("na instalação que coleta, a tarefa é entregue",
       _t2.get("coletar") is True, corpo[:180])
checar("e leva a instalação declarada", _t2.get("instancia") == _psei.PADRAO,
       str(_t2.get("instancia")))
checar("e o perfil que diz em qual SEI entrar, não uma constante do coletor",
       (_t2.get("perfil") or {}).get("login_url", "").startswith("https://sip.seibahia"),
       str(_t2.get("perfil"))[:160])
checar("o perfil da coleta é o MESMO envelope da busca — uma definição só",
       _t2.get("perfil") == _psei.envelope_do_coletor(_psei.PADRAO),
       str(_t2.get("perfil"))[:160])
cx = conectar()
cx.execute("DELETE FROM execucao WHERE agente_id=1 AND estado='entregue'")
cx.execute("UPDATE agentes SET pausado_motivo=? WHERE id=1", (_pausa_t,))
cx.commit(); cx.close()

# ------------------------- 7d-bis. a fronteira por unidade vale para ESCREVER
# O defeito era este: o escopo de publicação do agente saía do FORMULÁRIO, sem
# conferir vínculo, e no modo "todas" era `SELECT DISTINCT unidade FROM snapshot`
# — todas as unidades do banco. Como é esse campo que a publicação confere, a
# fronteira por unidade protegia a LEITURA e não a ESCRITA: bastava digitar a
# sigla de outra unidade para publicar snapshot 'corrente' nela, e a carteira
# daquela unidade era substituída para todos os servidores dela.
print("\n7d-bis. a fronteira também vale para escrever")
import configuracao as _cfgmod                                    # noqa: E402

cx = conectar()
_uid_s = cx.execute("SELECT id FROM usuarios WHERE email='t.servidor@teste.local'").fetchone()[0]
_minhas = [r[0] for r in cx.execute(
    "SELECT unidade FROM usuario_unidade WHERE usuario_id=?", (_uid_s,))]
_alheia = cx.execute("""SELECT unidade FROM snapshot WHERE estado='corrente'
                        AND unidade NOT IN (SELECT unidade FROM usuario_unidade
                                            WHERE usuario_id=?) LIMIT 1""",
                     (_uid_s,)).fetchone()
cx.close()
checar("o servidor de teste tem unidade própria e existe unidade alheia",
       bool(_minhas) and _alheia is not None, f"minhas={_minhas}")

if _minhas and _alheia:
    _alheia = _alheia[0]
    ops = cliente(); entrar(ops, "t.servidor@teste.local", SENHA_TESTE)
    s, _, _, _ = pegar(ops, "/configuracao", {"csrf": csrf(ops), "passo": "mesas",
                                              "mesas_modo": "selecionadas",
                                              "mesas": [_alheia]})
    cx = conectar()
    _c = _cfgmod.ler(cx, _uid_s)
    cx.close()
    checar("pedir mesa de unidade alheia NÃO grava ela no escopo",
           _alheia not in (_c["mesas"] or []), str(_c["mesas"]))

    # E o modo "todas" quer dizer todas DA PESSOA — não todas do banco.
    pegar(ops, "/configuracao", {"csrf": csrf(ops), "passo": "mesas", "mesas_modo": "todas"})
    cx = conectar()
    import app as _appmod
    _esc = _appmod.escopo_do_dono(cx, _uid_s, _cfgmod.ler(cx, _uid_s))
    cx.close()
    checar("\"todas as mesas\" é todas as MINHAS, não todas do banco",
           set(_esc) == set(_minhas), f"{_esc} != {_minhas}")

# A publicação reconfere contra o vínculo ATUAL: revogar vínculo tem de fechar a
# porta também para o agente já pareado, sem depender de reconfigurar a estação.
# O agente 1 é o do BOOTSTRAP: nasce sem dono, e aí o escopo posto pelo admin
# vale como está — é o que permite a primeira coleta de uma instalação nova, onde
# ninguém tem vínculo porque as unidades ainda não existem. Para medir o recorte
# pelo vínculo é preciso DAR um dono a ele.
cx = conectar()
_dono_antes = cx.execute("SELECT dono_usuario_id FROM agentes WHERE id=1").fetchone()[0]
_dono_ag = cx.execute(
    "SELECT id FROM usuarios WHERE email='t.gestor@teste.local'").fetchone()[0]
cx.execute("UPDATE agentes SET dono_usuario_id=?, unidades_esperadas=? WHERE id=1",
           (_dono_ag, json.dumps([uni_teste, "SESAB/INVENTADA"], ensure_ascii=False)))
cx.commit(); cx.close()
s, corpo, _, _ = assinado("/api/agente/resultado",
                          {"execucao_id": None,
                           "dados": [{"id": "x1", "mesa_coleta": "SESAB/INVENTADA",
                                      "mesas_coleta": ["SESAB/INVENTADA"]}]})
checar("unidade que o dono não tem vínculo é recusada mesmo estando no escopo do agente",
       s == 409, f"status {s} {corpo[:120]}")

# `mesas_conta` é o campo que a INGESTÃO usa para decidir de que unidades nascem
# snapshots. Conferir só `mesas_coleta` deixava passar exatamente o campo que
# decide — a porta olhava um lado e a ingestão lia o outro.
s, corpo, _, _ = assinado("/api/agente/resultado",
                          {"execucao_id": None,
                           "dados": [{"id": "x2", "mesa_coleta": uni_teste,
                                      "mesas_coleta": [uni_teste],
                                      "mesas_conta": [uni_teste, "SESAB/PELA-PORTA-DOS-FUNDOS"]}]})
checar("mesas_conta também passa pela conferência de escopo", s == 409,
       f"status {s} {corpo[:140]}")

# Desativar a pessoa tem de desarmar a estação dela. O token não é a conta: quem
# saiu do órgão seguia publicando, e o histórico seguia carimbando o nome dele.
cx = conectar()
_ativo_antes = cx.execute("SELECT ativo FROM usuarios WHERE id=?", (_dono_ag,)).fetchone()
if _dono_ag:
    cx.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (_dono_ag,))
    cx.commit(); cx.close()
    s, corpo, _, _ = assinado("/api/agente/tarefa", metodo="GET")
    cx = conectar()
    cx.execute("UPDATE usuarios SET ativo=? WHERE id=?",
               (_ativo_antes["ativo"] if _ativo_antes else 1, _dono_ag))
    cx.commit()
checar("com o dono desativado, a estação para de ser atendida (401)",
       s == 401, f"status {s} {corpo[:120]}")
cx.execute("UPDATE agentes SET unidades_esperadas=?, dono_usuario_id=? WHERE id=1",
           (json.dumps([uni_teste], ensure_ascii=False), _dono_antes))
cx.commit(); cx.close()

# E o outro lado da regra, que é o que mantém a instalação nova viva: agente SEM
# dono usa o escopo que o admin digitou, sem recorte nenhum.
cx = conectar()
cx.execute("UPDATE agentes SET dono_usuario_id=NULL, unidades_esperadas=? WHERE id=1",
           (json.dumps([uni_teste], ensure_ascii=False),))
cx.commit(); cx.close()
s, corpo, _, _ = assinado("/api/agente/resultado",
                          {"execucao_id": None,
                           "dados": [{"id": "x3", "mesa_coleta": uni_teste,
                                      "mesas_coleta": [uni_teste]}]})
checar("agente sem dono (primeiro deploy) continua publicando no escopo do admin",
       s != 409, f"status {s} {corpo[:120]}")
cx = conectar()
cx.execute("UPDATE agentes SET dono_usuario_id=? WHERE id=1", (_dono_antes,))
cx.commit(); cx.close()

# --------------------------------------------- 7e. o peso do painel na rede
# O painel embute a carteira inteira no HTML — decisão de projeto, porque ele
# também roda como arquivo solto, sem servidor. O preço, medido: 2.604 KB por
# abertura, sem compressão nenhuma. Comprimido dá 306 KB. Com seis pessoas
# abrindo três vezes ao dia, são 915 MB por mês contra 108 MB — numa rede de
# órgão, e num painel feito para ser aberto toda manhã.
print("\n7e. peso do painel na rede")
import gzip as _gz                                                # noqa: E402

opz = cliente(); entrar(opz, "t.gestor@teste.local", SENHA_TESTE)
s, corpo, cab, _ = pegar(opz, "/", cabecalhos={"Accept-Encoding": "gzip, deflate"},
                         bruto=True)
checar("o painel abre", s == 200, f"status {s}")
_enc = (cab.get("Content-Encoding") or "").lower()
checar("e vem comprimido quando o navegador aceita", _enc == "gzip", f"encoding={_enc!r}")
if _enc == "gzip":
    _cru = _gz.decompress(corpo)
    _razao = len(corpo) / max(1, len(_cru))
    checar(f"a compressão vale a pena ({len(_cru)//1024} KB -> {len(corpo)//1024} KB)",
           _razao < 0.35, f"razão {_razao:.2f}")
# Sem `Vary`, um intermediário entregaria a versão comprimida a quem não aceita.
checar("declara Vary: Accept-Encoding",
       "accept-encoding" in (cab.get("Vary") or "").lower(), str(cab.get("Vary")))
# A proteção contra o botão Voltar depois do logout depende deste cabeçalho.
checar("e o no-store continua onde estava",
       "no-store" in (cab.get("Cache-Control") or ""), str(cab.get("Cache-Control")))

# O VENDOR DESCE UMA VEZ SÓ, o CSS do projeto revalida sempre. `no-cache` não
# quer dizer "não guarde": quer dizer "guarde e PERGUNTE a cada vez" — e eram
# 1,34 MB de bibliotecas e fontes pedindo permissão a cada abertura de tela, com
# a de acesso puxando d3 (273 KB) e gsap (70 KB) que existem para a animação.
for _cam in ("/estatico/vendor/d3.min.js", "/estatico/vendor/gsap.min.js",
             "/estatico/vendor/Inter-400-latin.woff2"):
    _s, _, _cc, _ = pegar(opz, _cam, bruto=True)
    _v = (_cc.get("Cache-Control") or "")
    checar(f"{_cam.split('/')[-1]} desce com cache de um ano e imutável",
           _s == 200 and "max-age=31536000" in _v and "immutable" in _v,
           f"status {_s} — {_v!r}")
for _cam in ("/estatico/sei360.css", "/estatico/nav.css", "/estatico/lateral.css"):
    _s, _, _cc, _ = pegar(opz, _cam, bruto=True)
    _v = (_cc.get("Cache-Control") or "")
    # Um ano de cache aqui seria consertar uma cor e a pessoa seguir vendo a
    # antiga: estes três mudam a cada correção e o caminho não tem versão.
    checar(f"{_cam.split('/')[-1]} NÃO ganha cache longo (muda a cada correção)",
           _s == 200 and "31536000" not in _v, f"status {_s} — {_v!r}")

# Binário não se comprime duas vezes: a planilha sai por `send_file`, em
# streaming, e mexer nela ali custaria CPU à toa ou corromperia o arquivo.
s, corpo_x, cab_x, _ = pegar(opz, "/relatorios/permanencia.xlsx",
                             cabecalhos={"Accept-Encoding": "gzip"}, bruto=True)
checar("a planilha sai sem recompressão",
       s == 200 and not cab_x.get("Content-Encoding"),
       f"status {s} encoding={cab_x.get('Content-Encoding')}")
checar("e continua sendo um .xlsx que abre", corpo_x[:2] == b"PK", str(corpo_x[:8]))
# E A PLANILHA NOMINAL NAO PODE FICAR GUARDADA. `send_file` do Werkzeug escreve
# `Cache-Control: no-cache` sozinho, e o `setdefault` do after_request virava
# no-op justamente na resposta com MAIS dado nominal do sistema — `no-cache`
# autoriza ARMAZENAR, so exige revalidar, e nao traz `private`.
_cc_x = (cab_x.get("Cache-Control") or "")
checar("a planilha sai com no-store, private",
       "no-store" in _cc_x and "private" in _cc_x, repr(_cc_x))

# O CSS DE FONTES E NOSSO, apesar de morar em vendor/: ele declara os @font-face,
# e um `unicode-range` corrigido com um ano de `immutable` ficaria invisivel —
# nem o F5 traria, porque `immutable` dispensa a revalidacao manual.
_s, _, _cc, _ = pegar(opz, "/estatico/vendor/fontes.css", bruto=True)
checar("vendor/fontes.css NAO ganha cache de um ano (e nosso, muda)",
       "31536000" not in (_cc.get("Cache-Control") or ""), str(_cc.get("Cache-Control")))
_s, _, _cc, _ = pegar(opz, "/estatico/vendor/d3.min.js", bruto=True)
checar("mas a biblioteca de terceiro continua com um ano",
       "31536000" in (_cc.get("Cache-Control") or ""), str(_cc.get("Cache-Control")))

# ------------------------------------------------------- 7d. expurgo
print("\n7d. expurgo (o que ele NÃO pode apagar decide tudo)")
from expurgo import expurgar
cx = conectar()
velha = "2020-01-01T07:45:00-03:00"
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado)
              VALUES(NULL,?,?,3,'expirado')""", (uni_teste, velha))
snap_velho = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
# O SQLite REUSA rowid depois de apagar o maior: o snapshot criado agora pode
# receber o mesmo id de um apagado numa execução anterior, e aí a linha filha
# órfã que sobrou colide na chave. Limpar os filhos daquele id antes é o que
# torna esta suíte repetível — e a lição maior é que órfão existe de verdade,
# porque o CASCADE não vale em banco criado antes de a FK entrar no DDL.
for _t in ("processo", "processo_texto", "processo_mesa"):
    cx.execute(f"DELETE FROM {_t} WHERE snapshot_id=?", (snap_velho,))
cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo) VALUES(?,'zzz','X')""",
           (snap_velho,))
cx.execute("""INSERT INTO processo_texto(snapshot_id,id_sei,especificacao)
              VALUES(?,'zzz','texto que precisa sumir junto')""", (snap_velho,))
# um corrente ANTIGO, que jamais pode ser apagado
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado)
              VALUES(NULL,'SESAB/TESTE/PARADA',?,9,'corrente')""", (velha,))
corrente_velho = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()

plano = expurgar(simular=True)
cx = conectar()
ainda = cx.execute("SELECT COUNT(*) FROM snapshot WHERE id=?", (snap_velho,)).fetchone()[0]
cx.close()
checar("simulação não apaga nada", ainda == 1 and any(p[0] == "snapshot" for p in plano),
       f"plano={plano}")

expurgar()
cx = conectar()
sumiu = cx.execute("SELECT COUNT(*) FROM snapshot WHERE id=?", (snap_velho,)).fetchone()[0]
texto_sumiu = cx.execute("SELECT COUNT(*) FROM processo_texto WHERE snapshot_id=?",
                         (snap_velho,)).fetchone()[0]
ficou = cx.execute("SELECT COUNT(*) FROM snapshot WHERE id=?", (corrente_velho,)).fetchone()[0]
correntes = cx.execute("SELECT COUNT(*) FROM snapshot WHERE estado='corrente'").fetchone()[0]
cx.close()
orfaos = cx0 = conectar()
n_orfaos = cx0.execute("""SELECT COUNT(*) FROM processo_texto
                          WHERE snapshot_id NOT IN (SELECT id FROM snapshot)""").fetchone()[0]
cx0.close()
checar("nenhum texto livre órfão sobra depois do expurgo",
       n_orfaos == 0, f"{n_orfaos} linhas de processo_texto sem snapshot")
checar("snapshot expirado antigo é apagado", sumiu == 0)
checar("o texto livre dele some junto (é onde pode haver nome de paciente)",
       texto_sumiu == 0, f"{texto_sumiu} linhas de texto órfãs")
checar("snapshot CORRENTE antigo NUNCA é apagado, por mais velho que seja",
       ficou == 1, "apagar deixaria a unidade em branco, e branco lê-se como 'nada parado'")
checar(f"as {correntes} unidades correntes seguem de pé", correntes >= 6, str(correntes))

cx = conectar()
cx.execute("DELETE FROM snapshot WHERE unidade IN (?, 'SESAB/TESTE/PARADA')", (uni_teste,))
cx.commit(); cx.close()

# ---------------------------------------------------------------- 8. janelas
print("\n8. regra de janela (unidade)")
import janelas
from datetime import date

checar("sábado não é dia útil", not janelas.dia_util(date(2026, 8, 22)))
checar("2 de julho (Bahia) não é dia útil", not janelas.dia_util(date(2026, 7, 2)))
checar("Páscoa de 2026 calculada", janelas.pascoa(2026) == date(2026, 4, 5), str(janelas.pascoa(2026)))
cor, texto = janelas.idade(agora())
checar("snapshot de agora é verde", cor == "verde", f"{cor} {texto}")
cor, _ = janelas.idade("2026-08-10T07:45:00-03:00")
checar("snapshot de 8 dias é vermelho", cor == "vermelho", cor)

# ---------------------------------------------------------------- 9. saúde
print("\n9. saúde")
s, corpo, _, _ = pegar(cliente(), "/saude")
checar("/saude responde 200", s == 200)
j = json.loads(corpo) if s == 200 else {}
checar(f"{j.get('unidades_correntes')} unidades correntes", j.get("unidades_correntes") == len(unidades))

# ---------------------------------------------------------------- limpeza
# As contas t.* ficam DESATIVADAS ao fim: uma delas é admin com senha conhecida
# escrita neste arquivo. Deixá-las ativas transformaria a suíte de teste numa
# porta dos fundos permanente no mesmo banco que a instalação usa.
cx = conectar()
n = cx.execute("UPDATE usuarios SET ativo=0 WHERE origem='teste'").rowcount
cx.execute("UPDATE sessoes SET revogada_em=? WHERE usuario_id IN "
           "(SELECT id FROM usuarios WHERE origem='teste')", (agora(),))
cx.execute("DELETE FROM usuarios WHERE email='t.criado@teste.local'")
cx.commit(); cx.close()
print(f"\nlimpeza: {n} conta(s) de teste desativada(s) e sessões revogadas")

print(f"\n{'='*58}\n{ok_total} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
