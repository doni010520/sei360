# -*- coding: utf-8 -*-
"""
Vários usuários ao mesmo tempo — a validação que decide se o sistema é
multiusuário de verdade ou a automação de uma estação com tela de login.

As outras suítes entram com uma conta por vez. Esta mantém quatro sessões vivas
em paralelo, intercalando requisições, porque é assim que o sistema vai ser
usado: gente diferente, unidade diferente, papel diferente, ao mesmo tempo.

O que ela persegue, especificamente:
  * vazamento entre sessões — a carteira de um aparecendo para outro
  * papel que não faz nada (o `gestor` não fazia: a palavra não existia no app)
  * escrita concorrente no SQLite ("database is locked") com gente salvando junto
  * sessão de um sendo invalidada por ação de outro

    python teste_multiusuario.py
"""
# ---------------------------------------------------------------------------
# ISOLAMENTO antes de qualquer import do projeto — ver ambiente_teste.py.
# ---------------------------------------------------------------------------
import base64 as _b64, os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from ambiente_teste import isolar, subir_servidor          # noqa: E402
_dir = isolar(__file__)
_chave = _b64.urlsafe_b64encode(_os.urandom(32)).decode().rstrip("=")
_os.environ["SEI360_CHAVE_MESTRA"] = _chave
BASE, _parar = subir_servidor(_dir, chave_mestra=_chave)
import atexit as _atexit                                    # noqa: E402
_atexit.register(_parar)
print(f"banco isolado : {_dir}")
print(f"servidor      : {BASE}\n")

import http.cookiejar, json, re, sys, threading              # noqa: E402
import urllib.error, urllib.parse, urllib.request            # noqa: E402

import seguranca as seg                                      # noqa: E402
from banco import agora, conectar                            # noqa: E402

SENHA = "multiusuario-2026-sei"
ok, falhas = 0, []


def checar(nome, cond, det=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {det}")


class Pessoa:
    """Uma sessão viva, com cookie jar próprio — como um navegador diferente."""

    def __init__(self, email, papel, unidades):
        self.email, self.papel, self.unidades = email, papel, unidades
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        cx = conectar()
        h, s = seg.hash_senha(SENHA)
        cx.execute("DELETE FROM usuarios WHERE email=?", (email,))
        cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,
                      criado_em,ativo,senha_trocada_em) VALUES(?,?,?,?,?,'teste',?,1,?)""",
                   (email, email.split("@")[0], h, s, papel, agora(), agora()))
        self.uid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
        for un in unidades:
            cx.execute("""INSERT INTO usuario_unidade(usuario_id,unidade,concedida_em)
                          VALUES(?,?,?)""", (self.uid, un, agora()))
        cx.commit(); cx.close()

    def pega(self, caminho, dados=None):
        corpo = urllib.parse.urlencode(dados, doseq=True).encode() if dados else None
        try:
            r = self.op.open(urllib.request.Request(BASE + caminho, data=corpo), timeout=45)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    @property
    def csrf(self):
        return next((c.value for c in self.jar if c.name == "sei360_csrf"), "")

    def entrar(self):
        self.pega("/entrar")
        return self.pega("/entrar", {"email": self.email, "pw": SENHA, "csrf": self.csrf})

    def carteira(self):
        st, h = self.pega("/")
        i = h.find("const DADOS = ")
        if i < 0:
            return st, None
        return st, json.loads(h[i + 14: h.index(";" + chr(10), i)])


cx = conectar()
UNIDADES = [r["unidade"] for r in cx.execute(
    "SELECT DISTINCT unidade FROM snapshot WHERE estado='corrente' ORDER BY unidade")]
cx.close()
CESS = next(u for u in UNIDADES if u.endswith("CESS"))
UMA = next(u for u in UNIDADES if u.endswith("UMA-CMA"))

print("1. quatro pessoas entram ao mesmo tempo")
pessoas = [
    Pessoa("m.cess@teste.local", "servidor", [CESS]),
    Pessoa("m.uma@teste.local", "servidor", [UMA]),
    Pessoa("m.gestor@teste.local", "gestor", [CESS, UMA]),
    Pessoa("m.admin@teste.local", "admin", []),
]
resultados = {}
erros = []


def entra(p):
    try:
        st, corpo = p.entrar()
        resultados[p.email] = st
    except Exception as e:                                   # noqa: BLE001
        erros.append(f"{p.email}: {type(e).__name__} {e}")


linhas = [threading.Thread(target=entra, args=(p,)) for p in pessoas]
[t.start() for t in linhas]
[t.join() for t in linhas]
checar("quatro logins simultâneos, sem erro", not erros and set(resultados.values()) == {200},
       f"{resultados} {erros}")

print("\n2. cada um vê a SUA carteira, com as sessões vivas ao mesmo tempo")
cartas = {}


def carrega(p):
    try:
        st, dados = p.carteira()
        cartas[p.email] = dados
    except Exception as e:                                   # noqa: BLE001
        erros.append(f"{p.email}: {type(e).__name__}")


linhas = [threading.Thread(target=carrega, args=(p,)) for p in pessoas]
[t.start() for t in linhas]
[t.join() for t in linhas]
checar("nenhum erro ao carregar quatro painéis em paralelo", not erros, str(erros))

n_cess = len(cartas.get("m.cess@teste.local") or [])
n_uma = len(cartas.get("m.uma@teste.local") or [])
n_gestor = len(cartas.get("m.gestor@teste.local") or [])
n_admin = len(cartas.get("m.admin@teste.local") or [])
checar(f"CESS vê só CESS ({n_cess})", n_cess > 0 and all(
    CESS in (d.get("mesas_coleta") or []) for d in cartas["m.cess@teste.local"]))
checar(f"UMA-CMA vê só UMA-CMA ({n_uma})", n_uma > 0 and all(
    UMA in (d.get("mesas_coleta") or []) for d in cartas["m.uma@teste.local"]))
checar(f"gestor das duas vê a soma ({n_gestor} ≈ {n_cess} + {n_uma})",
       n_gestor >= max(n_cess, n_uma), f"{n_gestor} vs {n_cess}+{n_uma}")
checar(f"admin sem vínculo não vê carteira nenhuma ({n_admin})", n_admin == 0)

# O teste que decide: um processo que está SÓ em UMA-CMA não pode aparecer para
# quem só tem CESS. Sem isto, "fronteira por unidade" é texto de documento.
ids_cess = {d["id"] for d in cartas["m.cess@teste.local"]}
ids_uma = {d["id"] for d in cartas["m.uma@teste.local"]}
so_uma = ids_uma - ids_cess
checar(f"{len(so_uma)} processos exclusivos de UMA-CMA nunca aparecem para CESS",
       bool(so_uma) and not (so_uma & ids_cess))

print("\n3. o papel muda o que se pode fazer")
for p in pessoas:
    st, _ = p.pega("/alertas")
    esperado = 200 if p.papel in ("gestor", "admin") else 403
    checar(f"{p.papel:9} em /alertas -> {st} (esperado {esperado})", st == esperado, str(st))
# A porta "Pessoas" abre para o gestor — é onde se descobre por que fulano "não
# vê nada", e essa pergunta é da chefia da unidade, não da administração. O que
# NÃO abre é a escrita: papel, vínculo de unidade e senha continuam sendo ato de
# admin, porque vínculo define o que a pessoa enxerga.
for p in pessoas:
    st, corpo_pes = p.pega("/admin/usuarios")
    esperado = 200 if p.papel in ("gestor", "admin") else 403
    checar(f"{p.papel:9} em /admin/usuarios -> {st} (esperado {esperado})", st == esperado, str(st))
    if p.papel == "gestor":
        # Ler sem poder agir tem de ficar VISÍVEL: botão que o servidor recusa
        # ensina a desconfiar do sistema.
        # O <form> continua na página (ele envolve a tabela, é a tabela); o que
        # não pode vir são os CONTROLES — botão que o servidor recusaria ensina
        # a desconfiar do sistema.
        checar("gestor lê a lista mas não recebe os controles de ação em lote",
               'id="barraLote"' not in corpo_pes
               and 'value="ativar"' not in corpo_pes
               and "/admin/usuarios/" in corpo_pes)

# E a lista que o gestor vê é a das unidades DELE. Sem este recorte, abrir a
# porta entregaria o quadro de pessoal inteiro do órgão a quem chefia uma mesa.
_gestor = next(p for p in pessoas if p.papel == "gestor")
_admin = next(p for p in pessoas if p.papel == "admin")
_st, _lista_g = _gestor.pega("/admin/usuarios?f=todos")
_st, _lista_a = _admin.pega("/admin/usuarios?f=todos")
import re as _re_mu
_conta = lambda html: len(_re_mu.findall(r'/admin/usuarios/\d+', html))
# CONTAR LINHAS NÃO PROVA A FRONTEIRA: a lista pagina em 25, e com a base cheia
# as duas páginas enchem e os números empatam sem que nada tenha vazado. O que se
# quer afirmar é NOMINAL — existe uma conta fora das unidades do gestor que ele
# não alcança e o admin alcança. Imune ao tamanho da base e à paginação.
_fora = "m.forano@teste.local"
_cx_mu = conectar()
_cx_mu.execute("DELETE FROM usuarios WHERE email=?", (_fora,))
_h_mu, _sal_mu = seg.hash_senha(SENHA)
_cx_mu.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,
                  criado_em,ativo,senha_trocada_em) VALUES(?,?,?,?,'servidor','teste',?,1,?)""",
               (_fora, "Fora do alcance", _h_mu, _sal_mu, agora(), agora()))
_uid_mu = _cx_mu.execute("SELECT last_insert_rowid()").fetchone()[0]
_outra = _cx_mu.execute("""SELECT unidade FROM snapshot WHERE estado='corrente'
                           AND unidade NOT IN (?,?) LIMIT 1""", (CESS, UMA)).fetchone()
if _outra:
    _cx_mu.execute("""INSERT OR IGNORE INTO usuario_unidade(usuario_id,unidade,origem,
                      concedida_em) VALUES(?,?,'teste',?)""",
                   (_uid_mu, _outra["unidade"], agora()))
_cx_mu.commit(); _cx_mu.close()

checar("há unidade fora do alcance do gestor para exercitar", _outra is not None)
if _outra:
    _st, _busca_g = _gestor.pega("/admin/usuarios?f=todos&q=m.forano")
    _st, _busca_a = _admin.pega("/admin/usuarios?f=todos&q=m.forano")
    checar("a conta de OUTRA unidade não aparece para o gestor",
           _fora not in _busca_g, "o quadro de pessoal alheio vazou")
    checar("e aparece para o admin (senão o teste não prova nada)",
           _fora in _busca_a)
checar(f"o gestor continua vendo contas ({_conta(_lista_g)})", _conta(_lista_g) > 0)

# E o detalhe pela URL também: filtrar a lista e deixar /admin/usuarios/42 aberto
# é a forma mais comum de fronteira falsa.
_alheio = next((p for p in pessoas if p.papel == "servidor"
                and not (set(p.unidades) & set(_gestor.unidades))), None)
if _alheio:
    _st, _ = _gestor.pega(f"/admin/usuarios/{_alheio.uid}")
    checar("gestor não abre o detalhe de quem não divide unidade com ele (403)",
           _st == 403, str(_st))

# Gestor só reconhece alerta da unidade dele.
cx = conectar()
cx.execute("""INSERT INTO alerta(ts,tipo,severidade,unidade,texto)
              VALUES(?,?,?,?,?)""", (agora(), "teste_mu", "media", CESS, "alerta da CESS"))
a_cess = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
outra = next(u for u in UNIDADES if u not in (CESS, UMA))
cx.execute("""INSERT INTO alerta(ts,tipo,severidade,unidade,texto)
              VALUES(?,?,?,?,?)""", (agora(), "teste_mu", "media", outra, "alerta de outra"))
a_outra = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit(); cx.close()

g = pessoas[2]
g.pega("/alertas")
st, _ = g.pega(f"/alertas/{a_cess}", {"csrf": g.csrf})
cx = conectar()
feito = cx.execute("SELECT reconhecido_por FROM alerta WHERE id=?", (a_cess,)).fetchone()[0]
cx.close()
checar("gestor reconhece alerta da unidade dele", feito == g.uid, f"{st} / {feito}")

st, _ = g.pega(f"/alertas/{a_outra}", {"csrf": g.csrf})
cx = conectar()
nao = cx.execute("SELECT reconhecido_por FROM alerta WHERE id=?", (a_outra,)).fetchone()[0]
cx.close()
checar("e NÃO reconhece alerta de unidade alheia (403)", st == 403 and nao is None,
       f"status {st}, reconhecido_por={nao}")

print("\n4. escrita concorrente no SQLite")
# Quatro pessoas salvando ao mesmo tempo é onde o "database is locked" aparece.
# Já apareceu neste projeto, com uma transação aberta durante uma chamada HTTP.
saidas = []


def salva(p, i):
    try:
        st, _ = p.pega("/configuracao", {"csrf": p.csrf, "passo": "horarios",
                                         "janelas": f"0{i}:15", "dias": "uteis"})
        saidas.append(st)
    except Exception as e:                                   # noqa: BLE001
        saidas.append(type(e).__name__)


linhas = [threading.Thread(target=salva, args=(p, i)) for i, p in enumerate(pessoas, 1)]
[t.start() for t in linhas]
[t.join() for t in linhas]
checar("quatro gravações simultâneas, todas aceitas", all(s == 200 for s in saidas), str(saidas))

print("\n5. ação de um não derruba a sessão de outro")
adm = pessoas[3]
adm.pega("/admin/usuarios")
alvo = pessoas[1]
st, _ = adm.pega("/admin/usuario", {"csrf": adm.csrf, "acao": "revogar", "id": str(alvo.uid)})
# O DADO DO ALVO E O QUE DECIDE. A versao anterior jogava fora o segundo valor
# e afirmava `st_alvo == 200 and dados_outro is not None` — o primeiro e 200
# tanto para o painel quanto para a tela de acesso, e o segundo fala de OUTRA
# pessoa. Trocar o UPDATE de `revogar` por `pass` deixava a verificacao passar:
# o admin expulsava alguem e a pessoa seguia com a carteira aberta.
st_alvo, dados_alvo = alvo.carteira()
st_outro, dados_outro = pessoas[0].carteira()
checar("quem teve a sessão revogada é mandado ao login",
       dados_alvo is None, f"alvo={st_alvo} ainda recebeu {len(dados_alvo or [])} linhas")
checar("e a sessão de quem não foi alvo continua viva",
       dados_outro is not None and len(dados_outro) == n_cess, f"{len(dados_outro or [])}")

print("\n6. relatórios respeitam a mesma fronteira")
st, rel_cess = pessoas[0].pega("/relatorios/permanencia")
m = re.search(r"Base: <b>(\d+)</b>", rel_cess)
checar(f"relatório do usuário de CESS usa a base dele ({m.group(1) if m else '?'})",
       m and int(m.group(1)) == n_cess, f"{m.group(1) if m else '?'} vs {n_cess}")
vazou = [u for u in UNIDADES if u != CESS and re.search(re.escape(u) + r"(?![\w/-])", rel_cess)]
checar("e não cita nenhuma outra unidade", not vazou, str(vazou))

cx = conectar()
cx.execute("DELETE FROM alerta WHERE tipo='teste_mu'")
cx.commit(); cx.close()
# ---------------------------------------------------------------------------
# CADA UM VÊ A PRÓPRIA COLETA.
#
# Decisão do responsável: o dado de cada pessoa é dela, e ninguém consome a
# coleta de outro. Até aqui UMA coleta cobria as 6 unidades e servia a todos que
# tivessem vínculo.
#
# A regra tem duas metades, e as duas precisam ser provadas:
#   * a minha coleta vence a compartilhada, na mesma unidade;
#   * a coleta de OUTRA pessoa nunca aparece para mim — nem quando temos a
#     mesma unidade vinculada, que é justamente quando o vazamento seria fácil.
# A conta de admin não tem vínculo nenhum — e o painel dela mostra zero
# processos, corretamente, porque administrar não é ler. Mas a FAIXA mostrava as
# seis unidades assim mesmo: `if unidades:` tratava `None` (sem recorte) e `[]`
# (não alcança nada) como a mesma coisa, e o `else` listava tudo. Era esta a
# "mesma faixa aparecendo para todos os usuários".
print("\n6b. quem não tem unidade não vê faixa de unidade")
import app as _app0                                              # noqa: E402

_adm = next(p for p in pessoas if p.papel == "admin")
_est = _app0.estado_coleta([], _adm.uid)
checar("lista de unidades VAZIA devolve faixa vazia, não a base inteira",
       _est["unidades"] == [] and _est["pior"] == "vazio", str(_est)[:160])
checar("e nenhum alarme sobre coleta de unidade que ela não enxerga",
       _est["candidatos"] == 0, str(_est["candidatos"]))
# `None` continua sendo a visão do sistema — é o que a tela de saúde usa.
_global = _app0.estado_coleta(None, None)
checar("None continua significando 'sem recorte' (visão do sistema)",
       len(_global["unidades"]) > 0, str(len(_global["unidades"])))
# E na tela: a faixa do admin não pode citar sigla de unidade nenhuma.
_st, _painel_adm = _adm.pega("/")
checar("a faixa do painel do admin não lista unidade nenhuma",
       "COMASUP" not in _painel_adm and "UMA-CMA" not in _painel_adm,
       f"status {_st}")

print("\n7. cada um vê a própria coleta")
import app as _app                                               # noqa: E402

# O par PRECISA dividir unidade: é exatamente quando os dois alcançam a mesma
# unidade que o vazamento seria fácil e passaria despercebido. `pessoas[0]` tem
# só CESS e `pessoas[1]` só UMA — quem divide com as duas é o gestor.
_a = pessoas[0]
_uni = _a.unidades[0]
_b = next(p for p in pessoas[1:] if _uni in p.unidades)
cx = conectar()

# Uma coleta COMPARTILHADA (sem dono) desta unidade — é como toda instalação
# começa, antes de qualquer pessoa configurar a própria.
def _snap(dono, quantos, quando):
    cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,unicos,estado,
                  dono_usuario_id) VALUES(NULL,?,?,?,'corrente',?)""",
               (_uni, quando, quantos, dono))
    sid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    for k in range(quantos):
        cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,mesa_coleta)
                      VALUES(?,?,?,?)""",
                   (sid, f"{dono or 'cmp'}-{k}", f"P-{dono or 'cmp'}-{k}", _uni))
    return sid


cx.execute("UPDATE snapshot SET estado='expirado' WHERE unidade=?", (_uni,))
_s_comp = _snap(None, 3, "2026-08-18T07:00:00-03:00")
cx.commit()

_viu_a = _app.snapshots_de(cx, _a.uid, [_uni])
checar("sem coleta própria, a pessoa vê a compartilhada",
       _viu_a.get(_uni, (None, None))[0] == _s_comp, str(_viu_a))
checar("e o sistema sabe dizer que é compartilhada (sem dono)",
       _viu_a[_uni][1] is None, str(_viu_a))

# Agora A roda a própria coleta da mesma unidade.
_s_a = _snap(_a.uid, 7, "2026-08-19T07:00:00-03:00")
cx.commit()
_viu_a = _app.snapshots_de(cx, _a.uid, [_uni])
checar("com coleta própria, a dela vence a compartilhada",
       _viu_a[_uni] == (_s_a, _a.uid), str(_viu_a))

# B, que tem a MESMA unidade vinculada, continua na compartilhada — não herda a
# coleta de A. É aqui que o vazamento seria fácil.
checar(f"A e B dividem a unidade {_uni.split('/')[-1]} (senão o teste não prova nada)",
       _uni in _b.unidades, f"{_b.email}: {_b.unidades}")
_viu_b = _app.snapshots_de(cx, _b.uid, [_uni])
checar("a coleta de A NÃO aparece para B, mesmo com a unidade em comum",
       _viu_b[_uni][0] != _s_a, str(_viu_b))
checar("B cai na compartilhada, que é o que ele tem direito de ver",
       _viu_b[_uni] == (_s_comp, None), str(_viu_b))
# E o conteúdo: B não recebe UM processo sequer da coleta de A.
_db = _app.carteira([_uni], _b.uid)
checar("nenhum processo de A chega à carteira de B",
       not any(str(d["id"]).startswith(f"{_a.uid}-") for d in _db),
       str([d["id"] for d in _db][:5]))

# E o conteúdo bate: A vê os 7 dela, não os 3 compartilhados.
_da = _app.carteira([_uni], _a.uid)
checar(f"a carteira de A traz os processos DELA ({len(_da)})", len(_da) == 7,
       f"{len(_da)} processos: {[d['id'] for d in _da][:4]}")
checar("e nenhum processo da coleta compartilhada",
       not any(str(d["id"]).startswith("cmp-") for d in _da),
       str([d["id"] for d in _da][:4]))

# Chegar a coleta de B não pode expirar a de A: cada dono tem a sua corrente.
_s_b = _snap(_b.uid, 5, "2026-08-20T07:00:00-03:00")
cx.commit()
_est_a = cx.execute("SELECT estado FROM snapshot WHERE id=?", (_s_a,)).fetchone()[0]
checar("a coleta de B não expira a de A", _est_a == "corrente", _est_a)
_viu_a = _app.snapshots_de(cx, _a.uid, [_uni])
checar("e A continua vendo a dela", _viu_a[_uni] == (_s_a, _a.uid), str(_viu_a))

cx.execute("DELETE FROM processo WHERE snapshot_id IN (?,?,?)", (_s_comp, _s_a, _s_b))
cx.execute("DELETE FROM snapshot WHERE id IN (?,?,?)", (_s_comp, _s_a, _s_b))
cx.commit(); cx.close()


print("\nDUAS INSTALACOES DO SEI: O NOME DA UNIDADE NAO BASTA")
# `usuario_unidade` guarda `instancia` desde a migracao das duas instalacoes, e
# nem `unidades_do()` nem `snapshots_de()` liam a coluna. Nome de unidade nao e
# unico entre instalacoes — "GABINETE" existe na SESAB e na FESF. Quem tinha
# vinculo so na FESF recebia o snapshot compartilhado da SESAB com o mesmo nome:
# processos de uma instalacao onde a pessoa nao tem vinculo nenhum.
import banco as _bk                                                 # noqa: E402
import app as _ap                                                   # noqa: E402

_cx = _bk.conectar()
_cx.execute("INSERT INTO usuarios(email,nome,papel,ativo,senha_trocada_em) "
            "VALUES('t.fesf@teste.local','So FESF','servidor',1,?)", (_bk.agora(),))
_uid_f = _cx.execute("SELECT id FROM usuarios WHERE email='t.fesf@teste.local'").fetchone()["id"]
# UM unico vinculo: unidade GABINETE, na FESF.
_cx.execute("INSERT INTO usuario_unidade(usuario_id,instancia,unidade,origem) "
            "VALUES(?,'SEI-FESF','GABINETE','admin')", (_uid_f,))
# E um snapshot COMPARTILHADO de GABINETE, na SESAB — outra instalacao.
_cx.execute("INSERT INTO execucao(agente_id,estado,entregue_em) VALUES(NULL,'concluida',?)",
            (_bk.agora(),))
_ex = _cx.execute("SELECT MAX(id) FROM execucao").fetchone()[0]
_cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,coletados,unicos,
               estado,instancia,dono_usuario_id)
               VALUES(?,'GABINETE',?,1,1,'corrente','SEI-SESAB',NULL)""",
            (_ex, _bk.agora()))
_cx.commit()

_u = _ap.unidades_do(_uid_f)
checar("a pessoa tem o vinculo de GABINETE", _u == ["GABINETE"], str(_u))
_s = _ap.snapshots_de(_cx, _uid_f, _u)
checar("mas NAO recebe o snapshot de GABINETE da OUTRA instalacao",
       _s == {}, str(_s))
_cart = _ap.carteira(_u, _uid_f)
checar("e a carteira dela sai vazia, nao com processo de outra instalacao",
       len(_cart) == 0, f"{len(_cart)} processo(s)")

# Com o vinculo na instalacao CERTA, o mesmo snapshot passa a ser dela.
_cx.execute("UPDATE usuario_unidade SET instancia='SEI-SESAB' WHERE usuario_id=?", (_uid_f,))
_cx.commit()
_s2 = _ap.snapshots_de(_cx, _uid_f, _u)
checar("com o vinculo na instalacao certa, o snapshot aparece",
       len(_s2) == 1, str(_s2))

# Sem pessoa (`usuario_id=None`) nao ha vinculo a checar — e so o compartilhado.
_s3 = _ap.snapshots_de(_cx, None, _u)
checar("sem pessoa, vale o compartilhado (a visao do sistema continua)",
       len(_s3) == 1, str(_s3))

_cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=?", (_uid_f,))
_cx.execute("DELETE FROM usuarios WHERE id=?", (_uid_f,))
_cx.commit()
_cx.close()

print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
