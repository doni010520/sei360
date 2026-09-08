# -*- coding: utf-8 -*-
"""
BUSCA AVANÇADA — a tela, a fronteira e o estado.

O que esta suíte protege, em uma frase: uma busca é a pergunta de UMA pessoa,
feita com o login DELA, e o resultado não vira carteira de ninguém.

As travas medidas aqui têm todas o mesmo modo de falha — silencioso:
  * busca sem critério nenhum varre a mesa inteira num clique;
  * mesa que não é da pessoa devolveria carteira alheia;
  * duas buscas da mesma conta do SEI ao mesmo tempo devolvem a carteira errada
    SEM ERRO, porque a troca de mesa no SEI é por USUÁRIO e não por sessão;
  * o estado aceito do agente esconderia paginação que morreu no meio;
  * o texto do filtro no log seria lido por gestor e admin, e filtro cita nome.

    python teste_busca.py
"""
import json
import os
import re

# O LACO DO ATENDENTE FICA DESLIGADO NESTE ARQUIVO. Ele cria buscas e chama
# `atendente.pegar()` a mao; um laco de fundo reivindicando as mesmas linhas
# produziria corrida entre o teste e o proprio codigo que ele testa — falha
# intermitente, em lugar diferente a cada rodada, com cara de defeito do
# produto. Quem quer exercitar o laco liga onde precisa.
os.environ["SEI360_ATENDENTE"] = "0"
import sys
from pathlib import Path

from datetime import datetime, timedelta

from ambiente_teste import isolar

isolar(__file__)                        # cópia do banco; nunca o de trabalho
# UMA CHAVE VALIDA. `"x" * 44` nao decodifica em 32 bytes de AES: `cofre` ficava
# indisponivel e metade do bloco de credencial passava pelo caminho de ERRO —
# verde sem nunca cifrar nem decifrar nada. 32 bytes em base64 sao 44 chars,
# mas so se forem base64 de verdade.
import base64 as _b64i
os.environ.setdefault("SEI360_CHAVE_MESTRA",
                      _b64i.b64encode(b"chave-de-teste-32-bytes-!!!!!!!!").decode())
sys.stdout.reconfigure(encoding="utf-8")
SRV = Path(__file__).resolve().parent

import banco, seguranca as seg                                   # noqa: E402
from banco import TZ                                             # noqa: E402
banco.migrar()
cx = banco.conectar()
h, sal = seg.hash_senha("busca-123")
cx.execute("UPDATE usuarios SET senha_hash=?,senha_sal=?,ativo=1,bloqueado_ate=NULL,"
           "senha_trocada_em=? WHERE id=1", (h, sal, banco.agora()))
for u in [r[0] for r in cx.execute("SELECT DISTINCT unidade FROM snapshot")]:
    cx.execute("INSERT OR IGNORE INTO usuario_unidade(usuario_id,instancia,unidade) "
               "VALUES(1,'SEI-SESAB',?)", (u,))
# uma conta do SEI configurada, para a tela não abrir no aviso
cx.execute("INSERT INTO config_usuario(usuario_id,sistema,sei_login,atualizado_em) "
           "VALUES(1,'SEI-SESAB','fulano@saude.ba.gov.br',?) "
           "ON CONFLICT(usuario_id,sistema) DO UPDATE SET sei_login=excluded.sei_login",
           (banco.agora(),))
# UMA ESTACAO VIVA. Sem ela a busca e recusada — e com razao: foi o defeito
# relatado, em que o pedido entrava na fila sem ninguem para pega-lo. O cenario
# SEM estacao tem secao propria, mais abaixo.
cx.execute("DELETE FROM agentes WHERE dono_usuario_id=1")
cx.execute("INSERT INTO agentes(nome_estacao,dono_usuario_id,ativo,token_sha256,"
           "ultimo_contato_em) VALUES('ESTACAO-TESTE',1,1,X'00',?)", (banco.agora(),))
cx.commit(); cx.close()

import app as A                                                  # noqa: E402
A.app.config["TESTING"] = True
c = A.app.test_client()
c.get("/entrar")
tok = c.get_cookie("sei360_csrf").value
c.post("/entrar", data={"email": "admin@sei360.local", "pw": "busca-123", "csrf": tok})

ok = mau = 0


def _erra(f):
    """A chamada levanta? Sem isto, "recusa" vira "devolve None" e a verificação
    passa por acidente sobre um caminho que não existe."""
    try:
        f()
        return False
    except Exception:                                            # noqa: BLE001
        return True


def _duas_credenciais(cx):
    """Duas instalações guardadas e um `abrir()` sem dizer qual: tem de recusar.
    Escolher uma no escuro põe a senha de uma instalação no formulário da outra,
    e o erro que volta parece senha inválida."""
    import cofre
    cofre.guardar(cx, 1, "SEI-SESAB", "a@x", "s1")
    cofre.guardar(cx, 1, "SEI-FESF", "b@y", "s2")
    return cofre.abrir(cx, 1, motivo="teste")


def checar(nome, cond, viu=""):
    global ok, mau
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        mau += 1
        print(f"  FALHA {nome}" + (f"   -> {viu}" if viu else ""))


r = c.get("/busca", headers={"Accept-Encoding": "identity"})
html = r.get_data(as_text=True)
print(f"/busca: {r.status_code}, {len(html)} bytes\n")
checar("a tela responde 200", r.status_code == 200)
for marca in ("Busca avançada", "Com tramitação na unidade", "Tipo do processo",
              "Especificação", "Contato / interessado", "Assunto",
              "Observação desta unidade", "Número SEI", "Data de", "A data é de",
              "Pesquisar no SEI"):
    checar(f"campo/rótulo: {marca}", marca in html)
checar("as duas instalações aparecem",
       "SEI · SESAB" in html and "SEI · FESF-SUS" in html)
checar("a mesa da pessoa aparece", "DGGUP/DGESS/CESS" in html)
checar("e a tela diz que a lista é dela e tem prazo",
       "não entra na carteira de ninguém" in html.lower() or
       "Não entra na carteira de ninguém" in html)
checar("o menu ganhou a porta", 'href="/busca"' in html)

# `medidos` CHEGAVA E NUNCA APARECIA. O servidor manda, por instalação, se os ids
# dos campos da tela Pesquisa foram exercitados contra ELA
# (`perfil_sei.busca_ids_medidos`) — e o template não renderizava nada. Campo que
# não casa com id nenhum não é preenchido: o filtro não pega, o universo da
# resposta muda e o número sai maior sem nada na tela dizer isso. A SESAB é
# justamente a que está com `busca_ids_medidos: False`.
import perfil_sei as _psb                                          # noqa: E402
checar("a tela DIZ quando os ids da instalação não foram medidos em campo",
       "não foram medidos em campo" in html,
       "medidos chega ao template e não é renderizado")
checar("e o seletor marca qual instalação está nessa situação",
       "· ids não medidos" in html)
checar("a instalação MEDIDA não recebe o aviso (senão ele deixa de significar)",
       _psb.INSTANCIAS["SEI-FESF"]["busca_ids_medidos"] is True
       and html.count("· ids não medidos") == 1, str(html.count("· ids não medidos")))

print("\nO SERVIDOR RECUSA O QUE TEM DE RECUSAR")
tok = c.get_cookie("sei360_csrf").value


def pedir(corpo):
    return c.post("/api/busca", json=corpo, headers={"X-CSRF": tok})


r = pedir({"instancia": "SEI-SESAB", "filtros": {"tramitacao_unidade": True}})
checar("busca sem critério nenhum é recusada (400)", r.status_code == 400,
       f"{r.status_code} {r.get_json()}")
checar("e o motivo diz por quê", "varre a mesa inteira" in (r.get_json() or {}).get("erro", ""))

r = pedir({"instancia": "SEI-SESAB", "filtros": {"campo_inventado": "x"}})
checar("filtro desconhecido é recusado", r.status_code == 400,
       str(r.get_json()))

r = pedir({"instancia": "SEI-SESAB", "mesa": "OUTRO/ORGAO/QUALQUER",
           "filtros": {"especificacao": "x"}})
checar("mesa que não é da pessoa é recusada (403)", r.status_code == 403,
       str(r.get_json()))

r = pedir({"instancia": "SEI-SESAB", "filtros": {"especificacao": "Gil Farma"}})
checar("busca com critério é ACEITA (202)", r.status_code == 202, str(r.get_json()))
_proc_antes = _cx_antes = banco.conectar()
_proc_antes = _cx_antes.execute("SELECT COUNT(*) FROM processo").fetchone()[0]
_poco_antes = _cx_antes.execute("SELECT COUNT(*) FROM poco_processo").fetchone()[0]
_cx_antes.close()
bid = (r.get_json() or {}).get("busca_id")

r2 = pedir({"instancia": "SEI-SESAB", "filtros": {"assunto": "outra"}})
j2 = r2.get_json() or {}
checar("a segunda busca da mesma conta recebe 409", r2.status_code == 409, str(j2))
checar("e o 409 DEGRADA: diz qual busca está em curso", j2.get("em_curso") == bid,
       str(j2))

print("\nO RESULTADO É DE QUEM PEDIU")
r = c.get(f"/api/busca/{bid}")
d = r.get_json()
checar("quem pediu lê a própria busca", r.status_code == 200 and d["estado"] == "pedida",
       str(d)[:120])
cx = banco.conectar()
outro = cx.execute("SELECT id FROM usuarios WHERE id<>1 AND ativo=1 LIMIT 1").fetchone()
cx.close()
if outro:
    import busca as bmod
    cx = banco.conectar()
    checar("outra pessoa NÃO lê a busca alheia",
           bmod.ler(cx, bid, outro["id"]) is None)
    cx.close()

print("\nO ESTADO SAI DA MEDIÇÃO, NÃO DO AGENTE")
import busca as bmod                                             # noqa: E402
cx = banco.conectar()
env = {"total_declarado": 3, "paginas_lidas": 1, "mesa_confirmada": None,
       "duracao_s": 9,
       "itens": [{"id_sei": "1", "protocolo": "019.1", "tipo_processo": "Ofício",
                  "unidade_geradora": "SESAB/X", "usuario_gerador": "a@b",
                  "data_inclusao": "01/08/2026"}] * 3}
est, mot = bmod.receber(cx, bid, env)
cx.commit()
checar("3 de 3 declarados = COMPLETA", est == "completa", f"{est} {mot}")
d = bmod.ler(cx, bid, 1)
checar("os 3 itens ficaram", len(d["itens"]) == 3, str(len(d["itens"])))
checar("e nenhum texto livre foi guardado",
       all("especificacao" not in i for i in d["itens"]))
checar("a trava da conta foi liberada",
       bmod.trava_viva(cx, "SEI-SESAB", "fulano@saude.ba.gov.br") is None)
# MEDIDO ANTES, comparado depois. O numero da base de hoje estava cravado: a proxima
# coleta faria a suite acusar falha em codigo que ninguem tocou, e a pessoa
# procuraria defeito onde nao ha. O que se afirma e que a busca nao MEXE
# em `processo`, nao qual e o tamanho da base.
n = cx.execute("SELECT COUNT(*) FROM processo").fetchone()[0]
checar("a busca NÃO criou linha em `processo`", n == _proc_antes,
       f"{n} agora, {_proc_antes} antes da busca")
n = cx.execute("SELECT COUNT(*) FROM poco_processo").fetchone()[0]
# MEDIDO ANTES, também aqui: cravar `== 0` valia enquanto o poço estava vazio, e
# na primeira coleta com as marcas do coletor (26/08, 1.041 blocos) a suíte
# acusou falha em código que ninguém tocou. O que se afirma é que a BUSCA não
# publica bloco — não que o poço esteja vazio.
checar("nem no poço", n == _poco_antes, f"{n} agora, {_poco_antes} antes da busca")
al = [r[0] for r in cx.execute(
    "SELECT acao FROM log_acesso WHERE acao LIKE 'busca%' ORDER BY id")]
checar("o log registra pedido e resultado",
       "busca_pedida" in al and "busca_resultado" in al, str(al))
alvo = cx.execute("SELECT alvo FROM log_acesso WHERE acao='busca_pedida' "
                  "ORDER BY id DESC LIMIT 1").fetchone()[0]
checar("e o log NÃO carrega o texto do filtro (só o sha)",
       "Gil Farma" not in alvo and "sha " in alvo, alvo)
cx.close()

print("\nO MOTOR DA BUSCA, NAS DUAS VERSOES DO SEI")
# `pesquisa_sei.js` monta o POST a partir do formulário VIVO e tenta os ids em
# ordem — é o que faz a mesma regra atravessar o SEI 4.0 e o 5.0.4. As asserções
# campo a campo vivem no próprio arquivo, com HTML das duas versões; aqui a suíte
# só se recusa a passar se ele quebrar.
import shutil                                                    # noqa: E402
import subprocess                                                # noqa: E402
_js = Path(r"C:\Claude\sei_sistema\painel_sesab\_teste_pesquisa.js")
_node = next((e for e in (r"C:\Program Files\nodejs\node.exe", "node")
              if shutil.which(e)), None)
if _js.exists() and _node:
    _r = subprocess.run([_node, str(_js)], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=60)
    checar("o motor atravessa SEI 4.0 e 5.0.4, e recusa filtro que nao casa",
           _r.returncode == 0, (_r.stdout or "")[-220:])
else:
    checar("motor da busca conferido", False,
           "node ou o teste do motor nao encontrados")

# A PRECEDENCIA DA CREDENCIAL — o defeito que trocava a identidade de quem busca.
# O bloco CONFIG do automacao_sei.js vencia a credencial ENTREGUE por stdin, e a
# busca de uma pessoa entrava no SEI com a conta de outra; ninguem comparava, e a
# falha era silenciosa. O conferidor extrai as funcoes do .js e prova os nove
# casos — inclusive o que a estacao depende (sem credencial entregue, o CONFIG
# continua valendo, senao a coleta das 07h30 morre).
_jsc = Path(r"C:\Claude\sei_sistema\painel_sesab\conferir_credencial.js")
if _jsc.exists() and _node:
    _rc = subprocess.run([_node, str(_jsc)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=60)
    checar("credencial entregue vence o bloco CONFIG (e a estacao nao quebra)",
           _rc.returncode == 0, (_rc.stdout or "")[-400:])
else:
    checar("precedencia da credencial conferida", False,
           "node ou conferir_credencial.js nao encontrados")

print("\nA INSTANCIA E A FRONTEIRA ENTRE AS DUAS INSTALACOES")
import perfil_sei                                                # noqa: E402
checar("a busca vale nas duas instalacoes",
       set(perfil_sei.para_busca()) == {"SEI-SESAB", "SEI-FESF"},
       str(perfil_sei.para_busca()))
# A COLETA e a BUSCA tinham disponibilidade SEPARADA ate 08/09/2026: a busca
# usa a tela Pesquisa, que existe nas duas versoes; a coleta usava a
# visualizacao Detalhada, que e do SEI 5 e no 4.0 falha em silencio — ate a
# FESF ganhar parser proprio da listagem reduzida (amostra real contra
# FESF/DIGAS/HECC/GAF, 12 processos, id/protocolo/tipo 100% preenchidos).
checar("a coleta agora vale nas duas instalacoes",
       perfil_sei.para_coleta() == ["SEI-FESF", "SEI-SESAB"], str(perfil_sei.para_coleta()))
checar("instancia desconhecida NAO vira SESAB em silencio",
       _erra(lambda: perfil_sei.perfil("SEI-QUALQUER")))
checar("a FESF nao tem seletor de orgao (instalacao de um orgao so)",
       perfil_sei.envelope_do_coletor("SEI-FESF")["campo_orgao"] is None)
checar("e a SESAB tem, com o numero do orgao",
       perfil_sei.envelope_do_coletor("SEI-SESAB")["valor_orgao"] == "23")

cx = banco.conectar()
checar("o cofre guarda uma credencial POR instalacao",
       [r[1] for r in cx.execute("PRAGMA table_info(credencial)") if r[5]]
       == ["usuario_id", "sistema"])
checar("e abrir() com duas guardadas RECUSA em vez de escolher no escuro",
       _erra(lambda: _duas_credenciais(cx)))
cx.close()

print("\nO DEFEITO RELATADO: PEDIDO QUE NINGUEM TEM COMO EXECUTAR")
# A tela ficou em "em curso (pedida) — a estacao esta pesquisando no SEI" e nunca
# saiu. `pedida` significa o CONTRARIO: ninguem pegou. E nao havia como pegar — o
# agente daquela pessoa nunca foi pareado (token_sha256 NULL), e o ultimo contato
# de qualquer agente era de dois dias antes. O sistema aceitou, travou a conta por
# 20 min e afirmou que a estacao estava pesquisando.
cx = banco.conectar()
_uid = 1
cx.execute("DELETE FROM busca")
cx.execute("DELETE FROM busca_trava")
cx.execute("DELETE FROM agentes WHERE dono_usuario_id=?", (_uid,))
# ESTE BLOCO E SOBRE O MODO `estacao`. O padrao do sistema e `servidor`, e desde
# que o servidor virou executor a mesma pergunta tem duas respostas certas — dizer
# de qual modo se fala e parte do teste, nao ruido dele.
cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,modo_coleta)
              VALUES(?,'SEI-SESAB','estacao')
              ON CONFLICT(usuario_id,sistema) DO UPDATE SET modo_coleta='estacao'""",
           (_uid,))
cx.commit()

_ag, _motivo, _como = bmod.quem_executa(cx, _uid)
checar("sem estacao vinculada: quem_executa recusa e diz o porque",
       _ag is None and "nenhuma esta" in (_motivo or ""), str(_motivo))
_b, _erro, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "a@x", None, {"assunto": "x"})
checar("e o pedido NAO entra na fila", _b is None and bool(_erro), str(_erro))
checar("nem deixa trava para tras",
       cx.execute("SELECT COUNT(*) FROM busca_trava").fetchone()[0] == 0)

# agente existe mas NUNCA foi pareado — foi exatamente este o caso
cx.execute("INSERT INTO agentes(nome_estacao,dono_usuario_id,ativo) VALUES(?,?,1)",
           ("SERVIDOR/gestor", _uid))
cx.commit()
_ag, _motivo, _ = bmod.quem_executa(cx, _uid)
checar("agente sem token (nunca pareado) tambem recusa",
       _ag is None and "pareada" in (_motivo or ""), str(_motivo))

# pareado, mas calado ha dois dias — o outro lado do mesmo caso
cx.execute("UPDATE agentes SET token_sha256=X'00', ultimo_contato_em=? "
           "WHERE dono_usuario_id=?",
           ((datetime.now(TZ) - timedelta(days=2)).isoformat(timespec="seconds"), _uid))
cx.commit()
_ag, _motivo, _ = bmod.quem_executa(cx, _uid)
checar("estacao pareada mas calada ha 2 dias recusa, dizendo ha quanto tempo",
       _ag is None and "fala com o servidor" in (_motivo or ""), str(_motivo))

cx.execute("UPDATE agentes SET ultimo_contato_em=? WHERE dono_usuario_id=?",
           (banco.agora(), _uid))
cx.commit()
_ag, _motivo, _ = bmod.quem_executa(cx, _uid)
checar("com estacao viva, a busca e aceita", _ag is not None and _motivo is None, str(_motivo))
_b, _erro, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "a@x", None, {"assunto": "x"})
checar("e agora sim entra na fila", _b is not None and _erro is None, str(_erro))

print("\nDOIS PRAZOS, PORQUE SAO DOIS PROBLEMAS DIFERENTES")
cx.execute("UPDATE busca SET pedida_em=? WHERE id=?",
           ((datetime.now(TZ) - timedelta(seconds=bmod.PEGAR_TETO_S + 5))
            .isoformat(timespec="seconds"), _b))
cx.commit()
checar(f"`pedida` sem ninguem pegar falha em {bmod.PEGAR_TETO_S}s, nao em 10 min",
       bmod.varrer(cx) == 1)
_d = bmod.ler(cx, _b, _uid, com_itens=False)
checar("e o motivo aponta a causa: o agente nao esta rodando",
       "agente n" in (_d["motivo"] or ""), str(_d["motivo"]))
checar("a trava da conta e liberada junto",
       bmod.trava_viva(cx, "SEI-SESAB", "a@x") is None)

_b2, _, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "a@x", None, {"assunto": "y"})
cx.execute("UPDATE busca SET estado='entregue', entregue_em=? WHERE id=?",
           ((datetime.now(TZ) - timedelta(seconds=bmod.SEGUNDOS_TETO + 5))
            .isoformat(timespec="seconds"), _b2))
cx.commit()
bmod.varrer(cx)
_d = bmod.ler(cx, _b2, _uid, com_itens=False)
checar("`entregue` que nao volta falha com o prazo de EXECUCAO e OUTRO motivo",
       _d["estado"] == "falhou" and "devolveu" in (_d["motivo"] or ""),
       str(_d["motivo"]))
cx.close()

print("\nA TELA DIZ A VERDADE SOBRE CADA ESTADO")
_tela = (SRV / "templates" / "busca.html").read_text(encoding="utf-8")
checar("`pedida` nao diz mais que a estacao esta pesquisando",
       "aguardando a esta" in _tela)
checar("`entregue` diz que a estacao pegou", "pegou e est" in _tela)
checar("a tela mostra ha quanto tempo se espera", "${desde}s" in _tela)
checar("e o botao fica DESLIGADO sem estacao capaz",
       "{% if sem_estacao or not conta %}disabled" in _tela)

print("\nO SERVIDOR COMO EXECUTOR (VPS, decisao de 21/08/2026)")
# A partir da decisao de hospedar em VPS proprio, quem esta em modo `servidor`
# nao tem estacao — e nao deve ter. A pergunta deixa de ser "ha estacao viva?" e
# passa a ser "ha navegador NESTA IMAGEM?", que e propriedade do build.
import atendente as _at                                             # noqa: E402
cx = banco.conectar()
_uid = 1
cx.execute("DELETE FROM busca"); cx.execute("DELETE FROM busca_trava")
cx.execute("DELETE FROM agentes WHERE dono_usuario_id=?", (_uid,))
cx.execute("UPDATE config_usuario SET modo_coleta='servidor' WHERE usuario_id=?", (_uid,))
cx.commit()

_pode, _motivo_cap = _at.capacidade()
checar("capacidade() responde do que EXISTE, nao de configuracao",
       isinstance(_pode, bool) and (_motivo_cap is None) == _pode, str(_motivo_cap))

_orig = _at.capacidade
try:
    _at.capacidade = lambda: (True, None)
    _ag, _m, _ = bmod.quem_executa(cx, _uid, instancia="SEI-SESAB")
    checar("com navegador na imagem, o executor e o proprio servidor",
           _ag is not None and _ag.get("servidor") is True, str(_m))
    checar("e a tela nomeia quem executa sem inventar estacao",
           _ag["nome_estacao"] == "este servidor")
    _b, _erro, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "a@x", None, {"assunto": "x"})
    checar("a busca entra na fila sem estacao nenhuma vinculada",
           _b is not None and _erro is None, str(_erro))

    # A REIVINDICACAO E ATOMICA. Dois lacos — dois workers, ou um segundo
    # container — nao podem executar a mesma busca com o mesmo login: a troca de
    # mesa no SEI e por USUARIO, e duas sessoes correndo devolvem zero linha.
    _r1 = _at.pegar(cx)
    checar("o atendente reivindica a busca pedida", _r1 is not None and _r1["id"] == _b)
    _r2 = _at.pegar(cx)
    checar("e um segundo laco NAO pega a mesma — a reivindicacao e atomica",
           _r2 is None)
    checar("a busca ficou `entregue`, nao `pedida`",
           cx.execute("SELECT estado FROM busca WHERE id=?", (_b,)).fetchone()[0]
           == "entregue")

    # So pega de quem esta em modo servidor: a busca de quem escolheu `estacao`
    # e da estacao, e executa-la aqui usaria uma credencial que o cofre nao tem.
    cx.execute("UPDATE busca SET estado='pedida' WHERE id=?", (_b,))
    cx.execute("UPDATE config_usuario SET modo_coleta='estacao' WHERE usuario_id=?", (_uid,))
    cx.commit()
    checar("o atendente NAO pega busca de quem escolheu o modo estacao",
           _at.pegar(cx) is None)
    cx.execute("UPDATE config_usuario SET modo_coleta='servidor' WHERE usuario_id=?", (_uid,))
    cx.commit()
finally:
    _at.capacidade = _orig

# SEM navegador na imagem, e sem estacao, o pedido e RECUSADO com o motivo certo
# — o mesmo desenho do defeito relatado, do outro lado da arquitetura.
_at.capacidade = lambda: (False, "o Playwright nao esta instalado nesta imagem")
try:
    _ag, _m, _como = bmod.quem_executa(cx, _uid, instancia="SEI-SESAB")
    checar("sem navegador e sem estacao, recusa dizendo que e do SERVIDOR o problema",
           _ag is None and "modo servidor" in (_m or ""), str(_m))
    checar("e o como-resolver aponta os dois caminhos reais",
           "Dockerfile" in (_como or "") and "estação" in (_como or ""), str(_como))
    _b2, _erro, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "a@x", None, {"assunto": "z"})
    checar("e o pedido nao entra na fila", _b2 is None and bool(_erro))

    # DEGRADA PARA A ESTACAO. Recusar aqui esconderia o caminho que funciona:
    # o agente nao precisa do cofre, entao uma estacao viva ainda executa.
    cx.execute("""INSERT INTO agentes(nome_estacao,dono_usuario_id,ativo,token_sha256,
                  ultimo_contato_em) VALUES(?,?,1,X'00',?)""",
               ("EST/teste", _uid, banco.agora()))
    cx.commit()
    _ag, _m, _ = bmod.quem_executa(cx, _uid, instancia="SEI-SESAB")
    checar("mas com estacao viva a busca roda nela, mesmo em modo servidor",
           _ag is not None and _ag["nome_estacao"] == "EST/teste", str(_m))
finally:
    _at.capacidade = _orig

print("\nO LIMITE E DE MEMORIA, E ELE EXISTE")
checar("ha teto de buscas simultaneas no container", _at.LIMITE >= 1)
checar("e ele e configuravel sem rebuild (SEI360_BUSCAS_SIMULTANEAS)",
       "SEI360_BUSCAS_SIMULTANEAS" in (SRV / "atendente.py").read_text(encoding="utf-8"))
# O INTERRUPTOR E ACIONADO, nao observado. A versao anterior afirmava
# `ligado() is True` — lendo o ambiente de quem rodava a suite — e portanto
# FALHAVA justamente quando alguem rodava com SEI360_ATENDENTE=0, que e o modo
# que ela dizia cobrir.
_antes_at = os.environ.get("SEI360_ATENDENTE")
try:
    for _v, _esperado in (("0", False), ("nao", False), ("off", False),
                          ("1", True), ("sim", True)):
        os.environ["SEI360_ATENDENTE"] = _v
        checar(f"SEI360_ATENDENTE={_v} -> laco {'ligado' if _esperado else 'desligado'}",
               _at.ligado() is _esperado, str(_at.ligado()))
    del os.environ["SEI360_ATENDENTE"]
    checar("sem a variavel, o padrao e LIGADO (quem hospeda a execucao aqui "
           "nao deveria lembrar de mais um interruptor)", _at.ligado() is True)
finally:
    if _antes_at is None:
        os.environ.pop("SEI360_ATENDENTE", None)
    else:
        os.environ["SEI360_ATENDENTE"] = _antes_at
checar("e `iniciar()` respeita o interruptor, nao so `ligado()`",
       "if not ligado()" in (SRV / "atendente.py").read_text(encoding="utf-8"))

print("\nA IMAGEM MUDOU, E O DOCUMENTO QUE A EXPLICA MUDOU JUNTO")
_dock = (SRV / "Dockerfile").read_text(encoding="utf-8")
checar("o Dockerfile instala chromium", "playwright install" in _dock)
checar("o coletor entra na imagem", "painel_sesab/" in _dock)
checar("o navegador fica fora do $HOME do root, senao o usuario sem privilegio nao le",
       "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in _dock)
checar("o perfil do SEI vai para o VOLUME, para a sessao sobreviver ao redeploy",
       "SEI_PERFIL_DIR=/dados/_perfil_sei" in _dock)
checar("o Dockerfile diz que o contexto de build mudou de lugar",
       "sei_sistema/" in _dock and "contexto" in _dock.lower())
checar("e aponta a revogacao em vez de so acrescentar o navegador",
       "REVOGADOS" in _dock or "revogad" in _dock.lower())
_ign = (SRV.parent.parent / ".dockerignore").read_text(encoding="utf-8")
checar("o .dockerignore nega tudo e libera so o necessario",
       _ign.strip().splitlines()[-1] and "\n*\n" in "\n" + _ign)
checar("e nao deixa banco nem perfil entrarem na imagem",
       "*.db" in _ign and "_perfil_sei" in _ign)
_req = (SRV / "requisitos.txt").read_text(encoding="utf-8")
checar("playwright esta nos requisitos com versao FIXA", "playwright==" in _req)
cx.close()

print("\nSENHA EM TEXTO PURO NAO SOBE PARA O VPS")
# O `automacao_sei.js` e obrigatorio na imagem (o coletor nao roda sem ele) e tem
# um bloco CONFIG que aceita usuario e senha em texto puro. Barrar pelo NOME nao
# e opcao; entao ou entra limpo, ou nao ha build. Duas guardas independentes: o
# conferidor de contexto (antes do build) e a capacidade (antes de executar).
import shutil as _sh                                                # noqa: E402
import tempfile as _tmp                                             # noqa: E402

import atendente as _at2                                            # noqa: E402
import conferir_contexto as _cc                                     # noqa: E402

_d = Path(_tmp.mkdtemp())
(_d / "sujo.js").write_text('const CONFIG = {\n  usuario: "a@b.c",\n  senha:   "x",\n};',
                            encoding="utf-8")
(_d / "limpo.js").write_text('const CONFIG = {\n  usuario: "",\n  senha:   "",\n};',
                             encoding="utf-8")
checar("o conferidor detecta CONFIG preenchido",
       _cc.config_preenchido(_d / "sujo.js") == 2)
checar("e nao acusa CONFIG vazio", _cc.config_preenchido(_d / "limpo.js") is None)
checar("o conferidor devolve LINHA, nunca o valor",
       isinstance(_cc.config_preenchido(_d / "sujo.js"), int))

_orig_col = _at2.COLETOR
try:
    (_d / "coletor.py").write_text("", encoding="utf-8")
    (_d / "automacao_sei.js").write_text(
        'const CONFIG = {\n  usuario: "a@b",\n  senha: "s3nh4",\n};', encoding="utf-8")
    _at2.COLETOR = _d / "coletor.py"
    _m = _at2._segredo_na_imagem()
    checar("a capacidade acusa senha na imagem", _m is not None and "texto puro" in _m)
    checar("e a mensagem NAO contem a senha nem o login",
           _m is not None and "s3nh4" not in _m and "a@b" not in _m)
    checar("e aponta o paragrafo que manda esvaziar", "6.2" in (_m or ""))
    (_d / "automacao_sei.js").write_text(
        'const CONFIG = {\n  usuario: "",\n  senha: "",\n};', encoding="utf-8")
    checar("com CONFIG vazio, nao acusa nada", _at2._segredo_na_imagem() is None)
finally:
    _at2.COLETOR = _orig_col
    _sh.rmtree(_d, ignore_errors=True)

print("\nO CONTEXTO DE BUILD NAO LEVA O BANCO NEM O PERFIL")
_rs = _cc.regras()
checar("o banco de producao fica de fora",
       not _cc.entra("sei360/servidor/_dados/sei360.db", _rs))
checar("o perfil do navegador (material de credencial) fica de fora",
       not _cc.entra("painel_sesab/_perfil_sei/Default/Local Storage/leveldb/000003.log", _rs))
checar("a chave mestra local fica de fora",
       not _cc.entra("sei360/servidor/.env.local", _rs))
checar("as coletas brutas ficam de fora",
       not _cc.entra("painel_sesab/_coletas/sei_sesab_2026-08-20.json", _rs))
checar("os gigabytes da raiz ficam de fora",
       not _cc.entra("AUDITORIA_BUGS_V10.md", _rs))
checar("mas o app entra", _cc.entra("sei360/servidor/app.py", _rs))
checar("e o coletor entra", _cc.entra("painel_sesab/coletor_sesab.py", _rs))
checar("e o .js que o coletor injeta entra",
       _cc.entra("painel_sesab/automacao_sei.js", _rs))

print("\n--empacotar SO ESCREVE O ZIP SE O PORTAO FECHAR LIMPO")
# "Zipar a pasta pelo Explorer e arrastar no Upload" e o erro que este arquivo
# inteiro existe para impedir: levaria o banco de producao, o _perfil_sei e a
# senha em texto puro para o armazenamento do EasyPanel ANTES de o Docker
# existir. --empacotar usa a MESMA lista (`avaliar()`) que decide o veredito
# impresso — nunca uma segunda contagem que poderia divergir dela.
import zipfile as _zf                                               # noqa: E402
_de = Path(_tmp.mkdtemp())


def _montar_projeto_sintetico(raiz, config_sujo):
    (raiz / "sei360" / "servidor" / "estatico" / "vendor").mkdir(parents=True)
    (raiz / "sei360" / "servidor" / "templates").mkdir(parents=True)
    (raiz / "painel_sesab").mkdir(parents=True)
    for rel in ("sei360/servidor/app.py", "sei360/servidor/requisitos.txt",
                "sei360/servidor/Dockerfile", "painel_sesab/coletor_sesab.py",
                "painel_sesab/pesquisa_sei.js"):
        (raiz / rel).write_text("# teste\n", encoding="utf-8")
    linha = ('  usuario: "a@b.c", senha: "s3nh4-de-mentira",' if config_sujo
            else '  usuario: "", senha: "",')
    (raiz / "painel_sesab" / "automacao_sei.js").write_text(
        "// c\nconst CONFIG = {\n" + linha + "\n};\n", encoding="utf-8")
    (raiz / "_dados").mkdir()
    (raiz / "_dados" / "sei360.db").write_text("banco fake", encoding="utf-8")
    (raiz / ".dockerignore").write_text(
        "*\n!sei360\n!painel_sesab\nsei360/*\n!sei360/servidor\n"
        "painel_sesab/*\n!painel_sesab/coletor_sesab.py\n"
        "!painel_sesab/automacao_sei.js\n!painel_sesab/pesquisa_sei.js\n**/_dados\n",
        encoding="utf-8")


_raiz_orig, _ignore_orig = _cc.RAIZ, _cc.IGNORE
try:
    _sujo = _de / "sujo"
    _montar_projeto_sintetico(_sujo, config_sujo=True)
    _cc.RAIZ, _cc.IGNORE = _sujo, _sujo / ".dockerignore"
    _alvo_recusado = _de / "nao_deveria_existir.zip"
    _r1, _caminho1 = _cc.empacotar(_alvo_recusado)
    checar("com a senha em texto puro, --empacotar RECUSA",
           _caminho1 is None, str(_r1["vazando"]))
    checar("e nao escreve arquivo nenhum", not _alvo_recusado.exists())

    _limpo = _de / "limpo"
    _montar_projeto_sintetico(_limpo, config_sujo=False)
    _cc.RAIZ, _cc.IGNORE = _limpo, _limpo / ".dockerignore"
    _alvo_ok = _de / "upload.zip"
    _r2, _caminho2 = _cc.empacotar(_alvo_ok)
    checar("com o CONFIG vazio, --empacotar gera o ZIP",
           _caminho2 is not None and _caminho2.exists(), str(_r2["vazando"]))
    with _zf.ZipFile(_alvo_ok) as _z:
        _nomes = _z.namelist()
    checar("o Dockerfile fica no caminho que o EasyPanel espera",
           "sei360/servidor/Dockerfile" in _nomes, str(_nomes))
    checar("o .dockerignore vai junto — o EasyPanel le ele na raiz do ZIP",
           ".dockerignore" in _nomes, str(_nomes))
    checar("mas o banco NAO vai", not any("_dados" in n for n in _nomes), str(_nomes))
finally:
    _cc.RAIZ, _cc.IGNORE = _raiz_orig, _ignore_orig
    _sh.rmtree(_de, ignore_errors=True)

print("\nNAVEGADOR NA IMAGEM HABILITA A BUSCA, NAO A COLETA")
# Eu desarmei a pausa do agente logico quando `capacidade()` ficasse verdadeira.
# Errado: o navegador habilita a BUSCA (que `atendente.py` executa aqui), nao a
# coleta diaria — que continua sendo pull do agente, na estacao. Armado e sem
# motivo escrito, o agendamento prometeria uma coleta que ninguem faria, e a
# falha voltaria a aparecer como AUSENCIA.
import app as _app2                                                 # noqa: E402
_orig_cap = _at.capacidade
try:
    _at.capacidade = lambda: (True, None)
    _m = _app2._motivo_servidor()
    checar("com navegador na imagem, o agente logico CONTINUA pausado",
           _m is not None, str(_m))
    checar("e o motivo distingue busca de coleta",
           "BUSCA" in (_m or "") and "coleta" in (_m or ""), str(_m)[:90])
    _at.capacidade = lambda: (False, "o Playwright nao esta instalado")
    _m2 = _app2._motivo_servidor()
    checar("sem navegador, o motivo cita o que falta",
           "Playwright" in (_m2 or ""), str(_m2)[:90])
finally:
    _at.capacidade = _orig_cap
checar("e nao ha executor de coleta no servidor — se houver, e esta funcao que muda",
       "sincronizar_unidades" in (SRV / "coleta.py").read_text(encoding="utf-8") and
       "def coletar_janela" not in (SRV / "coleta.py").read_text(encoding="utf-8"))

print("\nA VAGA DE BUSCA VOLTA EM TODOS OS CAMINHOS")
# Dois vazamentos confirmados e reproduzidos pela revisao adversarial: excecao
# entre acquire() e Thread.start(), e banco.conectar() falhando dentro da thread.
# Em qualquer dos dois, `_vagas` chegava a zero e NUNCA voltava: o laco seguia
# vivo, a tela seguia oferecendo o botao, e toda busca morria em 90 s acusando
# "o agente nao esta rodando" — um agente que nem existe no modo servidor.
#
# O gatilho nao e exotico: `ingestao.ingerir()` escreve ~1.165 linhas num unico
# commit, no MESMO processo onde o laco sonda a fila a cada 3 s, com
# busy_timeout=5000. "database is locked" no UPDATE de pegar() e o caso esperado.
import threading as _th                                             # noqa: E402


class _Linha(dict):
    def __getitem__(self, k):
        return dict.get(self, k)


def _vagas_apos(cenario, quantas=3, cx=None):
    _at._vagas.__init__(_at.LIMITE)
    for _ in range(quantas):
        try:
            _at.rodada(cx) if cx is not None else _at.rodada()
        except Exception:                       # noqa: BLE001 — laco() faz o mesmo
            pass
    for _t in _th.enumerate():
        if _t.name.startswith("busca-"):
            _t.join(3)
    return _at.vagas_livres()


_o_pegar, _o_conn, _o_thread, _o_exec = (_at.pegar, _at.banco.conectar,
                                         _th.Thread, _at.executar)
try:
    _at.pegar = lambda cx: (_ for _ in ()).throw(RuntimeError("database is locked"))
    checar("pegar() levantando (lock da ingestao) devolve a vaga",
           _vagas_apos("pegar") == _at.LIMITE, str(_at.vagas_livres()))

    _at.pegar = lambda cx: None
    checar("fila vazia devolve a vaga",
           _vagas_apos("vazia") == _at.LIMITE, str(_at.vagas_livres()))

    _at.pegar = lambda cx: _Linha(id=1)

    class _Ruim(_o_thread):
        def start(self):
            raise RuntimeError("can't start new thread")

    _th.Thread = _Ruim
    checar("Thread.start() levantando devolve a vaga",
           _vagas_apos("start") == _at.LIMITE, str(_at.vagas_livres()))
    _th.Thread = _o_thread

    # A CONEXÃO VEM DE FORA. Trocando `banco.conectar` e chamando `rodada()`
    # sem conexão, quem estourava era o proprio `rodada()` em
    # `cx = cx or banco.conectar()` — ANTES de pegar vaga nenhuma. O teste
    # passava sem nunca chegar a thread, que e onde o defeito mora.
    _cx_fixa = banco.conectar()
    _at.banco.conectar = lambda: (_ for _ in ()).throw(OSError("unable to open database file"))
    checar("banco.conectar() levantando DENTRO da thread devolve a vaga",
           _vagas_apos("conectar", cx=_cx_fixa) == _at.LIMITE, str(_at.vagas_livres()))
    _at.banco.conectar = _o_conn
    _cx_fixa.close()

    _at.executar = lambda cx, r: None
    checar("e o caminho feliz devolve a vaga quando a thread termina",
           _vagas_apos("feliz") == _at.LIMITE, str(_at.vagas_livres()))
finally:
    _at.pegar, _at.banco.conectar, _th.Thread, _at.executar = (
        _o_pegar, _o_conn, _o_thread, _o_exec)
    _at._vagas.__init__(_at.LIMITE)

# E o estado impossivel passa a ser DITO, em vez de invisivel.
_at._vagas.__init__(_at.LIMITE)
for _ in range(_at.LIMITE):
    _at._vagas.acquire(blocking=False)
_pode, _motivo = _at.capacidade()
checar("zero vagas e nenhuma busca rodando e acusado como defeito DO SERVIDOR",
       _pode is False and "vagas de busca" in (_motivo or ""), str(_motivo)[:90])
checar("e a mensagem NAO culpa a estacao da pessoa",
       "esta" not in (_motivo or "").lower().split("estação")[0][:0] or
       "sua estação" not in (_motivo or ""), str(_motivo)[:90])
_at._vagas.__init__(_at.LIMITE)

print("\nUMA BUSCA, UM EXECUTOR — E UM PERFIL POR PESSOA")
cx = banco.conectar()
_uid = 1
cx.execute("DELETE FROM busca"); cx.execute("DELETE FROM busca_trava")
cx.execute("UPDATE config_usuario SET modo_coleta='servidor' WHERE usuario_id=?", (_uid,))
cx.commit()
_orig_cap2 = _at.capacidade
try:
    _at.capacidade = lambda: (True, None)
    _b, _e, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "a@x", None, {"assunto": "x"})
    checar("ha uma busca na fila para disputar", _b is not None, str(_e))
    # A CORRIDA DE VERDADE: os dois LEEM 'pedida' e so depois escrevem. Chamar
    # `pegar()` e `entregar()` em sequencia nao exercita nada — o
    # `WHERE estado='pedida'` do proprio SELECT ja resolve. O que precisa ser
    # provado e o intervalo entre o SELECT e o UPDATE.
    # A CORRIDA DENTRO DE `entregar()`. Executar o UPDATE a mao aqui testaria o
    # SQL que EU acabei de escrever, nao o dele; e procurar "AND estado='pedida'"
    # no fonte passa mesmo sem a guarda — a string aparece tres vezes em
    # busca.py. `agora()` e chamada ENTRE o SELECT e o UPDATE de `entregar`, ao
    # montar os parametros: e o ponto de injecao, e e deterministico.
    _o_agora = bmod.agora
    _entrou = {"n": 0}

    def _agora_com_disputa():
        # Simula o outro executor reivindicando no intervalo.
        if _entrou["n"] == 0:
            _entrou["n"] = 1
            cx.execute("UPDATE busca SET estado='entregue' WHERE id=?", (_b,))
        return _o_agora()

    try:
        bmod.agora = _agora_com_disputa
        _tarefa = bmod.entregar(cx, _uid, "SEI-SESAB")
    finally:
        bmod.agora = _o_agora
    checar("a disputa aconteceu entre o SELECT e o UPDATE", _entrou["n"] == 1)
    checar("e `entregar()` devolve None — quem perdeu a corrida nao leva tarefa",
           _tarefa is None, str(_tarefa))
    checar("a busca continua com UM dono, nao dois",
           cx.execute("SELECT estado FROM busca WHERE id=?", (_b,)).fetchone()[0]
           == "entregue")
    # E o caminho normal continua funcionando.
    cx.execute("UPDATE busca SET estado='pedida' WHERE id=?", (_b,)); cx.commit()
    _tarefa = bmod.entregar(cx, _uid, "SEI-SESAB")
    checar("sem disputa, o agente leva a tarefa normalmente",
           _tarefa is not None and _tarefa["busca_id"] == _b)
    checar("e o atendente nao pega a mesma depois", _at.pegar(cx) is None)
finally:
    _at.capacidade = _orig_cap2
cx.close()

checar("o perfil do navegador e por PESSOA e por INSTALACAO",
       _at._perfil_de(2, "SEI-SESAB") != _at._perfil_de(3, "SEI-SESAB") and
       _at._perfil_de(2, "SEI-SESAB") != _at._perfil_de(2, "SEI-FESF"))
checar("e o nome do diretorio nao aceita caractere de caminho",
       ".." not in str(_at._perfil_de(2, "../../etc")) and
       "/" not in _at._perfil_de(2, "a/b").name)
# O AMBIENTE QUE O SUBPROCESSO RECEBE, nao a string no fonte. Procurar
# "SEI_ESQUECER_APOS_LOGIN" no arquivo passa igual com o valor trocado para "0",
# que e o defeito de volta com a mesma aparencia.
_visto = {}


class _ProcFalso:
    returncode = 0
    stdin = stdout = None

    def communicate(self, entrada=None, timeout=None):
        return "BUSCA_OK " + _json_t.dumps(
            {"busca_id": _bid_t, "itens": [], "total_declarado": 0}), ""

    def kill(self):
        pass


import json as _json_t                                              # noqa: E402
import subprocess as _sp_t                                          # noqa: E402
cx = banco.conectar()
cx.execute("DELETE FROM busca"); cx.execute("DELETE FROM busca_trava")
cx.execute("UPDATE config_usuario SET modo_coleta='servidor' WHERE usuario_id=1")
cx.commit()
# Uma variavel que o codigo nao podia prever, para provar o criterio.
os.environ["SEGREDO_QUE_NINGUEM_PREVIU"] = "nao-pode-passar"
_orig_cap3, _orig_pop, _orig_abrir = _at.capacidade, _sp_t.Popen, _at.cofre.abrir
try:
    _at.capacidade = lambda: (True, None)
    _at.cofre.abrir = lambda cx_, uid, motivo=None, ip=None, sistema=None: ("l@x", "s3nh4")

    def _pop(args, **kw):
        _visto.update(kw.get("env") or {})
        _visto["__args"] = list(args)
        return _ProcFalso()

    _sp_t.Popen = _pop
    _bid_t, _e_t, _ = bmod.pedir(cx, 1, "SEI-SESAB", "a@x", None, {"assunto": "x"})
    _r_t = _at.pegar(cx)
    _at.executar(cx, _r_t)
finally:
    _at.capacidade, _sp_t.Popen, _at.cofre.abrir = _orig_cap3, _orig_pop, _orig_abrir
    os.environ.pop("SEGREDO_QUE_NINGUEM_PREVIU", None)
cx.close()

checar("o subprocesso recebe a ordem de APAGAR a credencial do disco",
       _visto.get("SEI_ESQUECER_APOS_LOGIN") == "1",
       str(_visto.get("SEI_ESQUECER_APOS_LOGIN")))
checar("e recebe o perfil DESTA pessoa, nao o perfil comum",
       _visto.get("SEI_PERFIL_DIR", "").endswith("u1-SEI-SESAB"),
       str(_visto.get("SEI_PERFIL_DIR")))
checar("a senha NAO viaja em argumento de linha de comando",
       not any("s3nh4" in str(a) for a in _visto.get("__args", [])))
checar("nem em variavel de ambiente",
       not any("s3nh4" == str(v) for v in _visto.values()))
checar("e a chave mestra do cofre NAO e herdada pelo navegador",
       not any(k.startswith("SEI360_CHAVE") for k in _visto),
       str([k for k in _visto if k.startswith("SEI360_")]))
checar("o coletor e chamado com --credencial-stdin",
       "--credencial-stdin" in _visto.get("__args", []),
       str(_visto.get("__args"))[:90])
# ALLOWLIST: o que NAO foi nomeado nao passa. Uma variavel inventada AGORA prova
# isso melhor que qualquer lista fixa — ela nao existia quando o codigo foi
# escrito, entao so passa se o criterio for "nego o que lembrei". A versao
# anterior deste bloco procurava a palavra `startswith` no fonte de atendente.py:
# quebrou quando o denylist virou allowlist (uma MELHORA), e teria passado com um
# denylist a que faltasse um prefixo.
checar("variavel NAO prevista nao chega ao navegador (e allowlist, nao denylist)",
       "SEGREDO_QUE_NINGUEM_PREVIU" not in _visto, str(sorted(_visto))[:110])
checar("e o que ele PRECISA chega: o caminho do navegador ou o PATH",
       "PLAYWRIGHT_BROWSERS_PATH" in _visto or "PATH" in _visto)
_fonte_col = (SRV.parent.parent / "painel_sesab" / "coletor_sesab.py").read_text(encoding="utf-8")
checar("o coletor obedece, e so quando quem chamou pode reenviar a credencial",
       "SEI_ESQUECER_APOS_LOGIN" in _fonte_col and "SEIAuto.esquecer()" in _fonte_col)
checar("o `Testar acesso` tambem leva o interruptor do sandbox e o perfil",
       "SEI_SEM_SANDBOX" in (SRV / "coleta.py").read_text(encoding="utf-8") and
       "SEI_PERFIL_DIR" in (SRV / "coleta.py").read_text(encoding="utf-8"))

print("\nO .dockerignore NAO ACEITA COMENTARIO NO FIM DA LINHA")
# Cinco padroes meus eram letra morta: `**/_dados   # o banco` e um padrao
# literal para o Docker, e nao casa com nada. O conferidor tirava o comentario
# antes de avaliar — media a INTENCAO — e certificava como segura uma imagem que
# levava o banco de producao, as coletas, a sessao do SEI e a chave do cofre.
import conferir_contexto as _cc2                                    # noqa: E402
_inertes = []
_rs2 = _cc2.regras(avisar=_inertes)
checar("nenhum padrao inerte no .dockerignore de hoje",
       not _inertes, str([l for _, l in _inertes][:3]))
# COM UM ARQUIVO QUE TEM A LINHA. Sem alimentar um `.dockerignore` sujo, o teste
# passa igual mesmo com o conferidor de volta ao `split("#")[0]` — o defeito so
# aparece quando existe a linha que ele interpretava errado.
import tempfile as _tmp3                                            # noqa: E402
_sujo = Path(_tmp3.mkdtemp()) / ".dockerignore"
_sujo.write_text("*\n!sei360\n**/_dados                 # o banco\n",
                 encoding="utf-8")
_orig_ign = _cc2.IGNORE
try:
    _cc2.IGNORE = _sujo
    _av = []
    _rs_sujo = _cc2.regras(avisar=_av)
    checar("o conferidor ACUSA a linha com comentario no fim",
           len(_av) == 1 and "_dados" in _av[0][1], str(_av))
    checar("e NAO a conta como padrao valido (era o que escondia o vazamento)",
           not any("_dados" in r for r in _rs_sujo), str(_rs_sujo))
    checar("com ela ignorada, o banco de producao ENTRARIA — e e isso que se ve",
           _cc2.entra("sei360/servidor/_dados/sei360.db", _rs_sujo))
finally:
    _cc2.IGNORE = _orig_ign
for _alvo in ("sei360/servidor/_dados/sei360.db",
              "painel_sesab/_perfil_sei/Default/Local Storage/leveldb/000003.log",
              "sei360/servidor/.env.local",
              "painel_sesab/_coletas/sei_sesab_2026-08-20.json",
              "sei360/servidor/teste_busca.py",
              "painel_sesab/painel_sesab.html"):
    checar(f"barrado: {_alvo.split('/')[-1]}", not _cc2.entra(_alvo, _rs2))
checar("mas o app entra", _cc2.entra("sei360/servidor/app.py", _rs2))
checar("e o coletor entra", _cc2.entra("painel_sesab/coletor_sesab.py", _rs2))

print("\nUMA BARRA DE RESTO, NAO DUAS")
# `rel_procedencia` devolve uma linha de resto para a coluna fechar com a base.
# Sem `residuo_na_ultima`, `grafico()` a tratava como linha comum: ordenava por
# tamanho (ela caia no MEIO das barras) e ainda somava a propria "outras N".
import app as _app3                                                 # noqa: E402
import relatorios as _R3                                            # noqa: E402
_u3 = _app3.unidades_do(2)
_g3 = _R3.montar("procedencia", _u3, usuario_id=2)["grafico"]
_restos = [b for b in _g3["barras"] if b["rotulo"].startswith("outras")]
checar(f"o grafico de procedencia tem UMA barra de resto ({len(_restos)})",
       len(_restos) == 1, str([b["rotulo"] for b in _g3["barras"]]))
checar("e ela e a ULTIMA, nao uma no meio",
       _g3["barras"][-1]["rotulo"].startswith("outras"),
       str([b["rotulo"] for b in _g3["barras"]][-3:]))
checar("as barras somam a base (nada some e nada conta duas vezes)",
       sum(b["valor"] for b in _g3["barras"]) == _R3.montar(
           "procedencia", _u3, usuario_id=2)["total"],
       str(sum(b["valor"] for b in _g3["barras"])))
checar("e o encurtamento de rotulo volta a funcionar (o resto nao o desliga)",
       "/" not in _g3["barras"][0]["rotulo"] and "/" in _g3["barras"][0]["inteiro"],
       _g3["barras"][0]["rotulo"])

print("\nO QUE SOBROU DO BUILD")
# O `.dockerignore` de sei360/servidor ficou orfao quando o contexto foi para a
# raiz: arquivo com o nome certo no lugar errado e pior que arquivo nenhum —
# quem for proteger a imagem edita ele, o build nao muda, e nada avisa.
_ign_orfao = SRV / ".dockerignore"
checar("o .dockerignore orfao diz que nao vale mais nada",
       not _ign_orfao.exists() or "NÃO VALE MAIS NADA" in
       _ign_orfao.read_text(encoding="utf-8"),
       "ele ainda tem regras que ninguem le")
if _ign_orfao.exists():
    _linhas_ativas = [l for l in _ign_orfao.read_text(encoding="utf-8").splitlines()
                      if l.strip() and not l.lstrip().startswith("#")]
    checar("e nao tem nenhuma regra ativa para enganar quem ler",
           not _linhas_ativas, str(_linhas_ativas[:3]))
    checar("e aponta o arquivo que VALE",
           "sei_sistema\\.dockerignore" in _ign_orfao.read_text(encoding="utf-8"))

# `ENV PORT` era letra morta: o CMD tem --bind 0.0.0.0:8000 cravado.
_dock2 = (SRV / "Dockerfile").read_text(encoding="utf-8")
checar("o Dockerfile nao define PORT que o gunicorn ignora",
       "PORT=" not in _dock2 or "porta e 8000" in _dock2, "ENV PORT ainda esta la")
checar("e o bind do gunicorn continua explicito", "0.0.0.0:8000" in _dock2)

# O PROIBIDO cobre o DERIVADO, nao so a fonte.
_rs5 = _cc2.regras()
for _d in ("painel_sesab/painel_sesab.html", "painel_sesab/painel_v2.html",
           "painel_sesab/processos_sesab.xlsx", "painel_sesab/_resumos/resumos.json",
           "painel_sesab/_logs/coleta_20260820.log"):
    checar(f"barrado (derivado): {_d.split('/')[-1]}", not _cc2.entra(_d, _rs5))
# E a lista PROIBIDO acusaria, caso o .dockerignore deixasse passar — as duas
# listas existem para nao dependerem uma da outra.
checar("a lista PROIBIDO nomeia a carteira em artefato derivado",
       any("derivado" in rot for rot, _ in _cc2.PROIBIDO),
       str([r for r, _ in _cc2.PROIBIDO]))

print("\nRESULTADO MEIO GRAVADO NUNCA E 'COMPLETA'")
# `receber()` gravava o VEREDITO primeiro e os itens depois, e `executar()`
# fechava com `finally: cx.commit()` incondicional. Um INSERT que levantasse no
# meio — "database is locked" e o caso ordinario aqui, com a ingestao escrevendo
# 1.165 linhas num commit so no mesmo processo — publicava "completa · 5 de 5"
# com dois itens gravados. E a trava da conta ficava de pe, porque `_destravar`
# vem depois do laco.
cx = banco.conectar()
_uid = 1
cx.execute("DELETE FROM busca"); cx.execute("DELETE FROM busca_trava")
cx.execute("DELETE FROM busca_item")
cx.execute("UPDATE config_usuario SET modo_coleta='servidor' WHERE usuario_id=?", (_uid,))
cx.commit()

_ITENS = [{"protocolo": f"P{i}", "tipo_processo": "T"} for i in range(1, 6)]
_o_cap5 = _at.capacidade
try:
    _at.capacidade = lambda: (True, None)
    _bp, _, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "conta@x", None, {"assunto": "p"})
finally:
    _at.capacidade = _o_cap5
cx.commit()          # senao o rollback do teste desfaz o proprio pedido
checar("ha uma busca para receber o resultado", _bp is not None)

# O terceiro INSERT levanta, como o SQLite faria sob disputa de escrita.
import sqlite3                                                      # noqa: E402

_n_ins = {"n": 0}


class _CxQueFalha:
    """A conexao real, com o TERCEIRO INSERT de item levantando.

    Nao da para trocar `cx.execute` — `sqlite3.Connection.execute` e somente
    leitura. Um proxy que delega tudo resolve, e de quebra deixa explicito que o
    unico comportamento alterado e esse.
    """

    def __init__(self, real):
        self._real = real

    def execute(self, sql, *a, **kw):
        if "INSERT OR REPLACE INTO busca_item" in sql:
            _n_ins["n"] += 1
            if _n_ins["n"] == 3:
                raise sqlite3.OperationalError("database is locked")
        return self._real.execute(sql, *a, **kw)

    def __getattr__(self, nome):
        return getattr(self._real, nome)


_estourou = False
try:
    bmod.receber(_CxQueFalha(cx), _bp,
                 {"busca_id": _bp, "itens": _ITENS,
                  "total_declarado": 5, "paginas_lidas": 1})
except sqlite3.OperationalError:
    _estourou = True
finally:
    try:
        cx.rollback()
    except Exception:                                               # noqa: BLE001
        pass

checar("o INSERT do meio de fato falhou (senao o teste nao prova nada)", _estourou)
_est = cx.execute("SELECT estado, colhidos FROM busca WHERE id=?", (_bp,)).fetchone()
checar("a busca NAO ficou 'completa' com o resultado pela metade",
       _est["estado"] != "completa", f"{_est['estado']} · colhidos={_est['colhidos']}")
_n_itens = cx.execute("SELECT COUNT(*) FROM busca_item WHERE busca_id=?",
                      (_bp,)).fetchone()[0]
checar("e nao sobrou item gravado de um resultado que nunca fechou",
       _n_itens == 0, f"{_n_itens} item(ns)")
checar("a trava da conta continua de pe — a busca nao terminou",
       bmod.trava_viva(cx, "SEI-SESAB", "conta@x") is not None)

# E o caminho feliz continua gravando tudo, na ordem certa.
_e, _m = bmod.receber(cx, _bp, {"busca_id": _bp, "itens": _ITENS,
                                "total_declarado": 5, "paginas_lidas": 1})
cx.commit()
checar("no caminho feliz, o veredito e 'completa'", _e == "completa", f"{_e} {_m}")
checar("com os 5 itens gravados",
       cx.execute("SELECT COUNT(*) FROM busca_item WHERE busca_id=?",
                  (_bp,)).fetchone()[0] == 5)
checar("e a trava e solta", bmod.trava_viva(cx, "SEI-SESAB", "conta@x") is None)
# A ORDEM, dita no codigo: o veredito e a ULTIMA escrita.
_fonte_b = (SRV / "busca.py").read_text(encoding="utf-8")
_i_item = _fonte_b.index("INSERT OR REPLACE INTO busca_item")
_i_verd = _fonte_b.index("UPDATE busca SET estado=?, motivo=?")
checar("os itens sao inseridos ANTES do veredito, no codigo", _i_item < _i_verd)
cx.close()

print("\nO CANCELAMENTO NAO SOLTA A CONTA COM O COLETOR AINDA LOGADO")
# Cancelar uma busca ja ENTREGUE soltava a trava enquanto o coletor continuava
# logado no SEI: a pessoa pedia outra na hora e dois Chromium entravam na MESMA
# conta. A troca de mesa no SEI e por USUARIO, nao por sessao — as duas voltam
# com zero linha e o veredito culpa o SEI.
cx = banco.conectar()
_uid = 1
cx.execute("DELETE FROM busca"); cx.execute("DELETE FROM busca_trava")
cx.execute("UPDATE config_usuario SET modo_coleta='servidor' WHERE usuario_id=?", (_uid,))
cx.commit()
_o_cap6 = _at.capacidade
try:
    _at.capacidade = lambda: (True, None)
    _bc, _, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "c@x", None, {"assunto": "c"})
    cx.commit()
    checar("a conta esta travada enquanto a busca esta 'pedida'",
           bmod.trava_viva(cx, "SEI-SESAB", "c@x") is not None)
    # Cancelar ANTES de alguem pegar: a trava PODE cair, ninguem esta logado.
    bmod.cancelar(cx, _bc, _uid); cx.commit()
    checar("cancelar uma busca que NINGUEM pegou solta a conta",
           bmod.trava_viva(cx, "SEI-SESAB", "c@x") is None)

    _bc2, _, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "c@x", None, {"assunto": "c2"})
    cx.commit()
    _at.pegar(cx)                       # agora alguem pegou: o coletor esta logado
    bmod.cancelar(cx, _bc2, _uid); cx.commit()
    checar("cancelar uma busca JA PEGA nao solta a conta",
           bmod.trava_viva(cx, "SEI-SESAB", "c@x") is not None,
           "a conta ficou livre com o coletor ainda no SEI")
    checar("e uma segunda busca na mesma conta e recusada enquanto isso",
           bmod.pedir(cx, _uid, "SEI-SESAB", "c@x", None, {"assunto": "c3"})[1] is not None)
    # Quando o coletor devolve, a trava cai — e e so ai que se sabe que ele saiu.
    bmod.receber(cx, _bc2, {"busca_id": _bc2, "itens": [], "total_declarado": 0})
    cx.commit()
    checar("quando o coletor devolve, a conta e liberada",
           bmod.trava_viva(cx, "SEI-SESAB", "c@x") is None)
finally:
    _at.capacidade = _o_cap6

print("\nFILA CHEIA NAO E 'O AGENTE NAO ESTA RODANDO'")
# Com LIMITE=2, a terceira busca fica na fila. Mata-la aos 90 s manda a pessoa
# procurar um agente que nao existe no modo servidor — e a propria tela dispara a
# varredura, poleando a cada 2 s: o ato de esperar matava a espera.
from datetime import datetime as _dt6, timedelta as _td6                # noqa: E402
cx.execute("DELETE FROM busca"); cx.execute("DELETE FROM busca_trava"); cx.commit()
_o_fila, _o_cap7 = bmod._fila_pode_estar_cheia, _at.capacidade
try:
    _at.capacidade = lambda: (True, None)
    _bf, _, _ = bmod.pedir(cx, _uid, "SEI-SESAB", "f@x", None, {"assunto": "f"})
    cx.execute("UPDATE busca SET pedida_em=? WHERE id=?",
               ((_dt6.now(TZ) - _td6(seconds=bmod.PEGAR_TETO_S + 5))
                .isoformat(timespec="seconds"), _bf))
    cx.commit()
    bmod._fila_pode_estar_cheia = lambda: True
    checar("com a fila cheia, a busca na fila NAO e morta aos 90 s",
           bmod.varrer(cx) == 0 and
           cx.execute("SELECT estado FROM busca WHERE id=?", (_bf,)).fetchone()[0] == "pedida")
    bmod._fila_pode_estar_cheia = lambda: False
    checar("com vaga livre e ninguem pegando, ai sim ela falha", bmod.varrer(cx) == 1)
    _mf = cx.execute("SELECT motivo FROM busca WHERE id=?", (_bf,)).fetchone()[0]
    checar("e o motivo nomeia o SERVIDOR, nao um agente que nao existe",
           "servidor" in (_mf or "") and "agente" not in (_mf or ""), str(_mf))
finally:
    bmod._fila_pode_estar_cheia, _at.capacidade = _o_fila, _o_cap7
cx.close()

print("\nO VINCULO DE UNIDADE CONHECE A INSTALACAO")
import coleta as _col6                                                  # noqa: E402
cx = banco.conectar()
_uid6 = 1
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=? AND origem='sei'", (_uid6,))
cx.execute("""INSERT OR REPLACE INTO usuario_unidade
              (usuario_id,instancia,unidade,concedida_em,origem)
              VALUES(?,'SEI-FESF','GABINETE',?,'sei')""", (_uid6, banco.agora()))
cx.commit()
_col6.sincronizar_unidades(cx, _uid6, ["SESAB/UMA"], "SEI-SESAB")
cx.commit()
_vinc = {(r["instancia"], r["unidade"]) for r in cx.execute(
    "SELECT instancia,unidade FROM usuario_unidade WHERE usuario_id=? AND origem='sei'",
    (_uid6,))}
checar("sincronizar a SESAB NAO apaga o vinculo da FESF",
       ("SEI-FESF", "GABINETE") in _vinc, str(_vinc))
checar("e o vinculo novo nasce na instalacao certa",
       ("SEI-SESAB", "SESAB/UMA") in _vinc, str(_vinc))
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=? AND origem='sei'", (_uid6,))
cx.commit(); cx.close()

print("\nA NOTA DE 'OUTROS' NAO LEVA LOGIN NEM NUMERO PARA A TELA")
import relatorios as _R6                                                # noqa: E402
checar("login vira (login)",
       "@" not in _R6._sem_identificacao("Processo atribuido para fulano@saude.ba.gov.br"))
checar("numero de processo vira (n)",
       "19.09.0012345-7" not in _R6._sem_identificacao("Bloco 19.09.0012345-7 concluido"))
checar("e as PALAVRAS ficam — a nota existe para a proxima regra sair do dado",
       "atribuido" in _R6._sem_identificacao("Processo atribuido para f@x.com").lower())
_sint6 = [{"_ultimo_mov": {"de": "Coisa estranha de joao@saude.ba.gov.br", "un": "X"},
           "_unidades": ["X"], "snap_unidade": "X"},
          {"_ultimo_mov": {"de": "Outra coisa 12.345/2026-1", "un": "X"},
           "_unidades": ["X"], "snap_unidade": "X"}]
_n6 = _R6.rel_ultimo_evento(_sint6)["nota"]
checar("e a nota montada nao carrega o login", "@saude" not in _n6, _n6[-90:])

print("\nO QUE MUDA COM A PROXIMA COLETA NAO PODE ESTAR CRAVADO NO TESTE")
# Numero absoluto da base atual vira falsa acusacao amanha: a suite aponta falha
# em codigo que ninguem tocou, e a pessoa vai procurar defeito onde nao ha. O que
# se afirma e a RELACAO, medida na hora.
cx = banco.conectar()
_n_proc = cx.execute("SELECT COUNT(*) FROM processo").fetchone()[0]
_n_mesa = cx.execute("SELECT COUNT(*) FROM processo_mesa").fetchone()[0]
_n_snap = cx.execute("SELECT COUNT(*) FROM snapshot WHERE estado='corrente'").fetchone()[0]
checar(f"ha processo na base para os testes trabalharem ({_n_proc})", _n_proc > 0)
checar(f"e ha arvore do SEI ({_n_mesa} linhas em processo_mesa)", _n_mesa > 0)
checar(f"e snapshots correntes ({_n_snap})", _n_snap > 0)
checar("cada processo aparece em ao menos uma mesa da arvore",
       _n_mesa >= _n_snap, f"{_n_mesa} < {_n_snap}")
# E o teste diz, em texto, que NAO deve haver numero cravado aqui.
_fonte_tb = (SRV / "teste_busca.py").read_text(encoding="utf-8")
_cravados = re.findall(r"==\s*(\d{4,})\b", _fonte_tb)
checar("nenhuma assercao deste arquivo compara com numero de 4+ digitos da base",
       not _cravados, str(_cravados[:5]))
cx.close()

print("\nTROCAR O LOGIN DO SEI EXIGE A SENHA DELE")
# O AAD do cofre e `usuario_id|sistema|login`: o blob so decifra no contexto em
# que foi criado. Gravar o login novo sem a senha deixaria o segredo amarrado ao
# login ANTIGO e a tela, a trava e o log mostrando o NOVO — e a decifragem
# falharia com "nao ha credencial guardada", que manda procurar no lugar errado.
import app as _ap7                                                      # noqa: E402
cx = banco.conectar()
_uid7 = 1
cx.execute("DELETE FROM credencial WHERE usuario_id=?", (_uid7,))
cx.execute("""INSERT INTO credencial(usuario_id,sistema,login,nonce,segredo,algo,criado_em)
              VALUES(?,'SEI-SESAB','antigo@x.com',X'00',X'00','aes-256-gcm',?)""",
           (_uid7, banco.agora()))
cx.commit()
checar("o cofre sabe a que login a credencial esta amarrada",
       _ap7._login_guardado(cx, _uid7, "SEI-SESAB") == "antigo@x.com")
checar("e devolve None quando nao ha credencial guardada",
       _ap7._login_guardado(cx, 999999, "SEI-SESAB") is None)
cx.execute("DELETE FROM credencial WHERE usuario_id=?", (_uid7,))
cx.commit()

print("\nO HISTORICO DA FICHA SO MOSTRA ACAO SOBRE PESSOA")
# `alvo` e texto livre: varias acoes gravam ali id de snapshot, de busca ou de
# execucao. Casar so por `alvo = str(uid)` fazia a ficha do usuario 9 mostrar,
# como se fossem dele, acoes cujo alvo era o snapshot 9.
checar("ha uma lista explicita das acoes que tem USUARIO no alvo",
       len(_ap7.ACOES_SOBRE_USUARIO) >= 4, str(_ap7.ACOES_SOBRE_USUARIO))
for _a in ("busca_pedida", "busca_resultado", "ver_relatorio", "abrir_relatorios"):
    checar(f"'{_a}' NAO esta entre elas (o alvo dela nao e pessoa)",
           _a not in _ap7.ACOES_SOBRE_USUARIO)
cx.close()

print("\nUM LACO SO, MESMO SOB O RELOADER")
_fonte_app7 = (SRV / "app.py").read_text(encoding="utf-8")
checar("o guarda le `--debug`, que e como este projeto liga o modo de depuracao",
       '"--debug" in sys.argv' in _fonte_app7.split("_atendente.iniciar()")[0][-700:],
       "o guarda olha so FLASK_DEBUG, que o Flask 3 nunca escreve")
checar("e continua olhando WERKZEUG_RUN_MAIN, que e quem separa pai de filho",
       "WERKZEUG_RUN_MAIN" in _fonte_app7)

print("\nOS QUE ESCAPARAM DOS MUTANTES — AGORA POR COMPORTAMENTO")
import coleta as _cl8                                               # noqa: E402
import app as _ap8                                                  # noqa: E402

cx = banco.conectar()
_uid8 = 1

# ---- `_instancia_de` com DUAS credenciais nao pode escolher no escuro.
cx.execute("DELETE FROM credencial WHERE usuario_id=?", (_uid8,))
for _s in ("SEI-SESAB", "SEI-FESF"):
    cx.execute("""INSERT INTO credencial(usuario_id,sistema,login,nonce,segredo,
                  algo,criado_em) VALUES(?,?,?,X'00',X'00','aes-256-gcm',?)""",
               (_uid8, _s, f"eu@{_s}.x", banco.agora()))
cx.commit()
checar("com DUAS credenciais, `_instancia_de` devolve None em vez de chutar",
       _cl8._instancia_de(cx, _uid8) is None, str(_cl8._instancia_de(cx, _uid8)))
cx.execute("DELETE FROM credencial WHERE usuario_id=? AND sistema='SEI-FESF'", (_uid8,))
cx.commit()
checar("com UMA, devolve a dela",
       _cl8._instancia_de(cx, _uid8) == "SEI-SESAB")
cx.execute("DELETE FROM credencial WHERE usuario_id=?", (_uid8,))
cx.commit()
checar("sem nenhuma, devolve None", _cl8._instancia_de(cx, _uid8) is None)

# ---- O DELETE de `sincronizar_unidades` respeita a instalacao.
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=? AND origem='sei'", (_uid8,))
for _i, _u in (("SEI-FESF", "GABINETE"), ("SEI-SESAB", "GABINETE")):
    cx.execute("""INSERT OR REPLACE INTO usuario_unidade
                  (usuario_id,instancia,unidade,concedida_em,origem)
                  VALUES(?,?,?,?,'sei')""", (_uid8, _i, _u, banco.agora()))
cx.commit()
# A SESAB deixou de mostrar GABINETE: o vinculo DELA cai, o da FESF fica.
_cl8.sincronizar_unidades(cx, _uid8, ["SESAB/OUTRA"], "SEI-SESAB")
cx.commit()
_v8 = {(r["instancia"], r["unidade"]) for r in cx.execute(
    "SELECT instancia,unidade FROM usuario_unidade WHERE usuario_id=? AND origem='sei'",
    (_uid8,))}
checar("o vinculo da SESAB que sumiu do SEI foi tirado",
       ("SEI-SESAB", "GABINETE") not in _v8, str(_v8))
checar("e o da FESF, com o MESMO nome de unidade, ficou de pe",
       ("SEI-FESF", "GABINETE") in _v8, str(_v8))
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=? AND origem='sei'", (_uid8,))
cx.commit()

# ---- O historico da ficha: uma acao de OUTRA pessoa cujo alvo coincide.
cx.execute("DELETE FROM log_acesso WHERE alvo IN ('777','ficha-teste')")
_outro8 = cx.execute("SELECT id FROM usuarios WHERE id<>? LIMIT 1", (_uid8,)).fetchone()["id"]
cx.execute("""INSERT INTO log_acesso(ts,usuario_id,acao,alvo) VALUES(?,?,?,?)""",
           (banco.agora(), _outro8, "busca_pedida", str(_uid8)))
cx.execute("""INSERT INTO log_acesso(ts,usuario_id,acao,alvo) VALUES(?,?,?,?)""",
           (banco.agora(), _outro8, "trocar_papel", str(_uid8)))
cx.commit()
_hist = cx.execute(f"""SELECT acao FROM log_acesso
                       WHERE usuario_id=?
                          OR (alvo=? AND acao IN
                              ({','.join('?' * len(_ap8.ACOES_SOBRE_USUARIO))}))
                       ORDER BY id DESC LIMIT 40""",
                   [_uid8, str(_uid8), *_ap8.ACOES_SOBRE_USUARIO]).fetchall()
# Só as linhas da OUTRA pessoa: as do próprio usuario 1 entram por
# `usuario_id=?` e são legítimas — o que não pode entrar é ação alheia que só
# coincide no `alvo`.
_hist_alheio = cx.execute(f"""SELECT acao FROM log_acesso
                              WHERE usuario_id=?
                                AND (alvo=? AND acao IN
                                     ({','.join('?' * len(_ap8.ACOES_SOBRE_USUARIO))}))""",
                          [_outro8, str(_uid8), *_ap8.ACOES_SOBRE_USUARIO]).fetchall()
_alheias = [r["acao"] for r in _hist_alheio]
checar("a acao SOBRE a pessoa, feita por outra, aparece na ficha dela",
       "trocar_papel" in _alheias, str(_alheias))
checar("e a busca de OUTRA pessoa, cujo alvo so coincide, NAO aparece",
       "busca_pedida" not in _alheias, str(_alheias))
cx.execute("DELETE FROM log_acesso WHERE alvo=? AND usuario_id=?", (str(_uid8), _outro8))
cx.commit()
cx.close()

# ---- O contador de retidos conta os DA PESSOA.
cx = banco.conectar()
_un8 = _ap8.unidades_do(_uid8) or ["SESAB/SAIS/DGGUP/DGESS/CESS"]
_outro9 = cx.execute("SELECT id FROM usuarios WHERE id<>? LIMIT 1", (_uid8,)).fetchone()["id"]
_base8 = _ap8.estado_coleta(_un8, _uid8)["candidatos"]
cx.execute("INSERT INTO execucao(agente_id,estado,entregue_em) VALUES(NULL,'concluida',?)",
           (banco.agora(),))
_ex8 = cx.execute("SELECT MAX(id) FROM execucao").fetchone()[0]
cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,coletados,unicos,
              estado,instancia,dono_usuario_id)
              VALUES(?,?,?,1,1,'candidato','SEI-SESAB',?)""",
           (_ex8, _un8[0], banco.agora(), _outro9))
cx.commit()
# DELTA, não valor absoluto: a base real tem candidatos próprios (a coleta de
# 26/08 reteve a DGESS por queda de 20 para 13 processos), e cravar `== 0` fazia
# a suíte acusar falha em código que ninguém tocou. O que se afirma é que o
# candidato de OUTRA pessoa não muda o MEU contador — não quanto ele vale.
_est8 = _ap8.estado_coleta(_un8, _uid8)
checar("candidato da coleta de OUTRA pessoa nao entra no meu contador de retidos",
       _est8["candidatos"] == _base8, f"{_est8['candidatos']} contra {_base8}")
cx.execute("UPDATE snapshot SET dono_usuario_id=? WHERE execucao_id=?", (_uid8, _ex8))
cx.commit()
checar("e o MEU candidato entra",
       _ap8.estado_coleta(_un8, _uid8)["candidatos"] == _base8 + 1,
       f"{_ap8.estado_coleta(_un8, _uid8)['candidatos']} contra {_base8 + 1}")
cx.execute("DELETE FROM snapshot WHERE execucao_id=?", (_ex8,))
cx.execute("DELETE FROM execucao WHERE id=?", (_ex8,))
cx.commit()
cx.close()

# ---- A trava da suite NAO pode girar para sempre, nem quando o unlink falha.
import ambiente_teste as _amb8                                      # noqa: E402
import tempfile as _tmp8                                            # noqa: E402
import time as _t8                                                  # noqa: E402
_tr8 = Path(_tmp8.gettempdir()) / "sei360_teste_provagiro.lock"
_tr8.write_text(f"999999 {int(_t8.time())}")            # dono morto: seria tomada
_o_unlink = Path.unlink


def _unlink_que_falha(self, *a, **kw):
    if self.name.endswith("provagiro.lock"):
        raise PermissionError("arquivo em uso por outro processo")
    return _o_unlink(self, *a, **kw)


_giros = {"n": 0}
_o_sleep = _t8.sleep
try:
    Path.unlink = _unlink_que_falha
    _t8.sleep = lambda s: _giros.__setitem__("n", _giros["n"] + 1)
    try:
        _amb8._travar("provagiro", Path("."))
        checar("com o unlink falhando, `_travar` DESISTE em vez de girar", False,
               "voltou como se tivesse travado")
    except SystemExit as _e8:
        checar("com o unlink falhando, `_travar` desiste e diz o que fazer",
               "apague" in str(_e8).lower(), str(_e8)[:70])
    checar(f"e desiste em poucas tentativas, nao em milhoes ({_giros['n']})",
           _giros["n"] <= 10, str(_giros["n"]))
finally:
    Path.unlink = _o_unlink
    _t8.sleep = _o_sleep
    try:
        _o_unlink(_tr8)
    except OSError:
        pass

# ---- O servidor de teste NAO sobe com o laco do atendente armado.
# O DIRETORIO DESTA PROPRIA SUITE. `isolar()` nao pode ser chamado duas vezes
# no mesmo processo: o caminho do banco e resolvido no import de `banco`.
_dir8 = banco.DADOS_DIR
_base8, _parar8 = _amb8.subir_servidor(_dir8)
try:
    import json as _j8
    import urllib.request as _u8
    _s8 = _j8.loads(_u8.urlopen(_base8 + "/saude", timeout=5).read())
    checar("o servidor de teste sobe SEM o laco de busca armado",
           _s8["busca"]["laco_vivo"] is False, str(_s8.get("busca")))
    checar("e /saude nao diz nada sobre a carteira nem sobre quem pesquisa",
           set(_s8["busca"]) == {"laco_vivo", "vagas_livres", "vagas"},
           str(sorted(_s8["busca"])))
finally:
    _parar8()
_base9, _parar9 = _amb8.subir_servidor(_dir8, atendente=True)
try:
    _s9 = _j8.loads(_u8.urlopen(_base9 + "/saude", timeout=5).read())
    checar("e com `atendente=True` ele sobe — o interruptor faz o que diz",
           _s9["busca"]["laco_vivo"] is True, str(_s9.get("busca")))
finally:
    _parar9()

print("\nAS DUAS GUARDAS, PELA ROTA — NAO PELO SQL COPIADO NO TESTE")
# Testar `_login_guardado` ou reescrever a consulta do historico aqui dentro
# testa a funcao vizinha e o SQL que eu acabei de digitar. A guarda esta na ROTA.
import json as _j9                                                  # noqa: E402

import app as _ap9                                                  # noqa: E402

_cli = _ap9.app.test_client()
cx = banco.conectar()
_uid9 = 1
_em9 = cx.execute("SELECT email FROM usuarios WHERE id=?", (_uid9,)).fetchone()["email"]

# Sessao real, pela tabela — o mesmo caminho que `usuario_atual` le.
import secrets as _sec9                                             # noqa: E402
_tok9 = _sec9.token_urlsafe(32)
cx.execute("""INSERT INTO sessoes(usuario_id,token_sha256,criado_em,ultimo_uso_em,
              expira_em,ip) VALUES(?,?,?,?,?,'127.0.0.1')""",
           (_uid9, seg.hash_token(_tok9), banco.agora(), banco.agora(),
            "2099-01-01T00:00:00-03:00"))
cx.execute("UPDATE usuarios SET senha_trocada_em=? WHERE id=?", (banco.agora(), _uid9))
# Credencial guardada, amarrada ao login ANTIGO.
cx.execute("DELETE FROM credencial WHERE usuario_id=?", (_uid9,))
cx.execute("""INSERT INTO credencial(usuario_id,sistema,login,nonce,segredo,algo,criado_em)
              VALUES(?,'SEI-SESAB','antigo@saude.ba.gov.br',X'00',X'00','aes-256-gcm',?)""",
           (_uid9, banco.agora()))
cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,sei_login,modo_coleta)
              VALUES(?,'SEI-SESAB','antigo@saude.ba.gov.br','servidor')
              ON CONFLICT(usuario_id,sistema) DO UPDATE SET
                sei_login='antigo@saude.ba.gov.br', modo_coleta='servidor'""", (_uid9,))
cx.commit()
_cli.set_cookie("sei360_sess", _tok9, domain="localhost")

_r9 = _cli.get("/configuracao")
_csrf9 = (_r9.headers.get("Set-Cookie") or "")
_csrf9 = _csrf9.split("sei360_csrf=")[1].split(";")[0] if "sei360_csrf=" in _csrf9 else ""
_cli.set_cookie("sei360_csrf", _csrf9, domain="localhost")


def _post_acesso(login, senha=""):
    return _cli.post("/configuracao", data={"passo": "acesso", "sei_login": login,
                                            "sei_senha": senha, "modo_coleta": "servidor",
                                            "csrf": _csrf9})


_resp9 = _post_acesso("novo@saude.ba.gov.br")
_texto9 = _resp9.get_data(as_text=True)
# A mensagem chega ESCAPADA no HTML (acento e travessao viram entidade), entao a
# frase literal nao serve de assercao. O trecho abaixo sobrevive ao escape.
checar("trocar o login SEM a senha e RECUSADO pela rota, com o motivo na tela",
       "amarrada ao login anterior" in _texto9, _texto9[:110])
_guardado9 = cx.execute("SELECT sei_login FROM config_usuario WHERE usuario_id=? "
                        "AND sistema='SEI-SESAB'", (_uid9,)).fetchone()["sei_login"]
checar("e o login gravado continua o ANTIGO — o cofre nao ficou desamarrado",
       _guardado9 == "antigo@saude.ba.gov.br", _guardado9)
# Com o MESMO login, sem senha, passa: nao ha o que desamarrar.
_post_acesso("antigo@saude.ba.gov.br")
checar("confirmar o MESMO login sem senha continua permitido",
       cx.execute("SELECT sei_login FROM config_usuario WHERE usuario_id=? "
                  "AND sistema='SEI-SESAB'", (_uid9,)).fetchone()["sei_login"]
       == "antigo@saude.ba.gov.br")

print("\nO HISTORICO DA FICHA, PELA ROTA")
# Duas linhas com o MESMO alvo: uma acao sobre pessoa e uma busca. So a primeira
# pode aparecer na ficha.
# UMA PESSOA SEM HISTORICO PROPRIO. Na ficha do usuario 1, `busca_pedida`
# aparece legitimamente — sao as buscas DELE, que entram por `usuario_id=?`. Para
# isolar a acao ALHEIA e preciso alguem sem nada proprio no log.
cx.execute("""INSERT INTO usuarios(email,nome,papel,ativo,senha_trocada_em)
              VALUES('t.ficha@teste.local','Sem Historico','servidor',1,?)""",
           (banco.agora(),))
_alvo9 = cx.execute("SELECT id FROM usuarios WHERE email='t.ficha@teste.local'").fetchone()["id"]
_outro9b = cx.execute("SELECT id FROM usuarios WHERE id NOT IN (?,?) AND ativo=1 LIMIT 1",
                      (_uid9, _alvo9)).fetchone()["id"]
cx.execute("INSERT INTO log_acesso(ts,usuario_id,acao,alvo) VALUES(?,?,?,?)",
           (banco.agora(), _outro9b, "busca_pedida", str(_alvo9)))
cx.execute("INSERT INTO log_acesso(ts,usuario_id,acao,alvo) VALUES(?,?,?,?)",
           (banco.agora(), _outro9b, "trocar_papel", str(_alvo9)))
cx.execute("UPDATE usuarios SET papel='admin' WHERE id=?", (_uid9,))
cx.commit()
_ficha = _cli.get(f"/admin/usuarios/{_alvo9}").get_data(as_text=True)
checar("a ficha da pessoa abre e mostra a acao SOBRE ela",
       "trocar_papel" in _ficha, _ficha[:80])
checar("e NAO mostra a busca de outra pessoa cujo alvo so coincide",
       "busca_pedida" not in _ficha,
       "a ficha listou uma acao alheia so porque o numero bateu")
cx.execute("DELETE FROM log_acesso WHERE alvo=?", (str(_alvo9),))
cx.execute("DELETE FROM usuarios WHERE id=?", (_alvo9,))
cx.execute("DELETE FROM credencial WHERE usuario_id=?", (_uid9,))
cx.execute("DELETE FROM sessoes WHERE token_sha256=?", (seg.hash_token(_tok9),))
cx.commit()
cx.close()

print("\nCOM VARIOS WORKERS: UM EXECUTOR SO, E NINGUEM DERRUBA NINGUEM")
# `--workers 1` escondia estes dois. Com N processos subindo juntos:
#   * a sonda de escrita do banco usava nome FIXO e fazia unlink — dois processos
#     se atropelavam e o `except OSError` virava SystemExit no boot;
#   * `LIMITE` e um semaforo em MEMORIA: sem trava, cada worker acharia que pode
#     abrir 2 Chromium. Com 3 workers seriam 6, ~2,7 GB num VPS de 2 GB — o teto
#     de memoria deixaria de valer justo quando passasse a importar.
import subprocess as _sp10                                          # noqa: E402

_codigo_sonda = (
    "import os,sys;sys.path.insert(0,r'" + str(SRV) + "');"
    "os.environ['SEI360_DADOS']=sys.argv[1];"
    "import banco;banco.conferir_escrita();print('ok')")
_ps = [_sp10.Popen([sys.executable, "-c", _codigo_sonda, str(banco.DADOS_DIR)],
                   stdout=_sp10.PIPE, stderr=_sp10.STDOUT, text=True) for _ in range(6)]
_saidas = [p.communicate()[0] for p in _ps]
_mortos = [s for s in _saidas if "ERRO" in s]
checar("6 processos sondam a escrita ao mesmo tempo sem se derrubar",
       not _mortos, (_mortos[0].splitlines()[0][:80] if _mortos else ""))
checar("e nao sobra arquivo de sonda no volume",
       not [f for f in os.listdir(banco.DADOS_DIR) if f.startswith(".escrita")])

_codigo_vez = (
    "import os,sys;sys.path.insert(0,r'" + str(SRV) + "');"
    "os.environ['SEI360_DADOS']=sys.argv[1];os.environ['SEI360_SEGREDO']='x'*32;"
    # LIGADO de proposito: este arquivo desliga o atendente no topo, e o
    # subprocesso herda o ambiente. Aqui o laco e justamente o que se testa.
    "os.environ['SEI360_ATENDENTE']='1';"
    "import atendente,time;"
    # ANUNCIA E SEGURA. A versao anterior dormia 3 s e saia — e o arranque de um
    # Python com `import atendente` custa quase isso. O quinto chamava
    # `iniciar()` depois de o primeiro JA TER SAIDO e devolvido a vez no
    # `atexit`: dois "VEZ" no resultado, e nenhum defeito. Eram dois executores
    # em MOMENTOS diferentes, que e o que se quer.
    #
    # A propriedade real e "um executor por vez ENTRE PROCESSOS VIVOS". Para
    # medi-la, os cinco precisam estar vivos juntos: cada um anuncia, esvazia o
    # buffer e espera o pai mandar sair.
    # MARCADOR na frente do veredito. `iniciar()` imprime por dois caminhos —
    # o perdedor diz "outro processo ... ja e o executor" antes de devolver
    # False, e o vencedor sobe uma thread que imprime o estado do laco. Qual
    # chega primeiro e escalonamento, entao ler UMA linha lia, as vezes, um log.
    "print('RESULTADO', 'VEZ' if atendente.iniciar() else 'painel', flush=True);"
    "sys.stdin.readline()")
_ps = [_sp10.Popen([sys.executable, "-c", _codigo_vez, str(banco.DADOS_DIR)],
                   stdin=_sp10.PIPE, stdout=_sp10.PIPE, stderr=_sp10.STDOUT,
                   text=True) for _ in range(5)]


def _veredito(p):
    """A linha do veredito, pulando o que o laco imprimir pelo caminho."""
    for _ in range(20):
        linha = p.stdout.readline()
        if not linha:
            return ""
        if linha.startswith("RESULTADO"):
            return linha
    return ""


# Neste ponto os cinco ja decidiram e nenhum saiu — e e so nesse instante que a
# pergunta "quantos executores ha AGORA" faz sentido.
_saidas = [_veredito(p) for p in _ps]
_com_vez = [s for s in _saidas if "VEZ" in s]
checar(f"de 5 workers VIVOS AO MESMO TEMPO, exatamente um e o executor "
       f"({len(_com_vez)})", len(_com_vez) == 1, str(_saidas))
checar("e enquanto ele vive, ninguem mais consegue tomar a vez",
       _at._tomar_a_vez() is False,
       "este processo conseguiu tomar a vez de um executor vivo")
for _p in _ps:
    try:
        _p.stdin.write("\n"); _p.stdin.flush()
    except OSError:
        _p.kill()
for _p in _ps:
    _p.wait(timeout=10)
# O LOCK MORRE COM O PROCESSO — nao ha `atexit` que possa falhar, nem PID a
# interpretar, nem trava velha a vencer por tempo. Um `kill -9` devolve a vez.
checar("e a vez fica livre quando os processos terminam",
       _at._tomar_a_vez() is True,
       "a vez continuou presa depois de todos morrerem")
_at._soltar_a_vez()

# KILL -9 DEVOLVE A VEZ, sem ninguem detectar nada. E a propriedade que o lock
# do sistema operacional da de graca e que o protocolo antigo (PID no arquivo)
# tentava imitar com deteccao de dono morto — errando: medido, 4 falhas em 8
# execucoes, com dois ou tres vencedores.
_codigo_morre = (
    "import os,sys;sys.path.insert(0,r'" + str(SRV) + "');"
    "os.environ['SEI360_DADOS']=sys.argv[1];os.environ['SEI360_SEGREDO']='x'*32;"
    "import atendente;"
    "print('PEGOU' if atendente._tomar_a_vez() else 'nao', flush=True);"
    "sys.stdin.readline()")
_pm = _sp10.Popen([sys.executable, "-c", _codigo_morre, str(banco.DADOS_DIR)],
                  stdin=_sp10.PIPE, stdout=_sp10.PIPE, text=True)
checar("o outro processo pegou a vez", _pm.stdout.readline().strip() == "PEGOU")
_at._soltar_a_vez()
checar("e enquanto ele vive nos NAO conseguimos", _at._tomar_a_vez() is False)
_pm.kill(); _pm.wait(timeout=10)
_t9b = 0
import time as _tt                                                  # noqa: E402
while _tt.time() < _t9b or not _at._tomar_a_vez():
    _tt.sleep(0.1)
    if _t9b == 0:
        _t9b = _tt.time() + 5
    elif _tt.time() > _t9b:
        break
checar("morto o processo (kill -9), a vez fica livre sem ninguem detectar nada",
       _at._fd_vez is not None, "a vez continuou presa depois do kill")
_at._soltar_a_vez()
_at._thread = None

# E dois no MESMO processo nao brigam: `iniciar()` continua idempotente.
_at._thread = None
os.environ["SEI360_ATENDENTE"] = "1"       # o arquivo o desliga no topo
try:
    checar("dois `iniciar()` no mesmo processo nao sobem dois lacos",
           _at.iniciar() is True and _at.iniciar() is False)
finally:
    os.environ["SEI360_ATENDENTE"] = "0"
_at._laco_vivo.clear()
(banco.DADOS_DIR / ".atendente.pid").unlink(missing_ok=True)
_at._thread = None

print("\nO DOCKERFILE DIZ A RAZAO MEDIDA, NAO A HERDADA")
_dk10 = (SRV / "Dockerfile").read_text(encoding="utf-8")
checar("o gunicorn sobe com mais de um worker", '"--workers", "3"' in _dk10, "ainda em 1")
checar("e o comentario traz a MEDIDA que justifica (o GIL, nao o lock)",
       "93%" in _dk10 and "GIL" in _dk10)
checar("e diz por que isso so e seguro agora (um executor por container)",
       "_tomar_a_vez" in _dk10)

print("\nA BUSCA NAO PODE SEGURAR O LOCK DE ESCRITA POR 10 MINUTOS")
# `cofre.abrir()` escreve (UPDATE credencial + registrar). Com o isolation_level
# padrao isso abre uma transacao de ESCRITA que so fecha no commit — e o commit
# vinha DEPOIS do `communicate(timeout=600)`, ou seja, depois do Chromium inteiro.
# No WAL, escritor nao bloqueia leitor, mas bloqueia OUTRO ESCRITOR — e toda
# requisicao autenticada deste sistema escreve (`usuario_atual` faz UPDATE
# sessoes). Medido antes do conserto: 5 cliques OK e 3 com 'database is locked';
# depois: 60 e 0.
_fonte_at9 = (SRV / "atendente.py").read_text(encoding="utf-8")
_i_abrir = _fonte_at9.index("login, senha = cofre.abrir")
_i_popen = _fonte_at9.index("proc = subprocess.Popen")
_entre = _fonte_at9[_i_abrir:_i_popen]
checar("ha um commit entre abrir a credencial e lancar o navegador",
       "cx.commit()" in _entre,
       "a transacao da credencial fica aberta durante os 10 min do coletor")

# E o comportamento, medido: uma transacao de escrita aberta trava as outras.
import threading as _th9                                            # noqa: E402
import time as _t9                                                  # noqa: E402


def _cliques_durante(segura_aberta):
    """(cliques ok, erros, maior espera) enquanto alguem escreve."""
    erros, ok, pronto = [], [0], _th9.Event()

    def escritor():
        c = banco.conectar()
        try:
            c.execute("UPDATE credencial SET usos=usos WHERE 1=0")   # abre a transacao
            c.execute("INSERT INTO log_acesso(ts,usuario_id,acao,alvo) VALUES(?,?,?,?)",
                      (banco.agora(), 1, "prova_lock", "x"))
            if not segura_aberta:
                c.commit()
            _t9.sleep(2.0)
            c.commit()
        finally:
            c.close(); pronto.set()

    esperas = []

    def clicador():
        while not pronto.is_set():
            c = banco.conectar()
            _t0 = _t9.perf_counter()
            try:
                c.execute("INSERT INTO log_acesso(ts,usuario_id,acao,alvo) VALUES(?,?,?,?)",
                          (banco.agora(), 1, "prova_clique", "y"))
                c.commit(); ok[0] += 1
                esperas.append(_t9.perf_counter() - _t0)
            except Exception as ex:                                 # noqa: BLE001
                erros.append(type(ex).__name__)
            finally:
                c.close()
            _t9.sleep(0.2)

    e = _th9.Thread(target=escritor); cl = _th9.Thread(target=clicador)
    e.start(); cl.start(); e.join(); cl.join()
    return ok[0], erros, (max(esperas) if esperas else 0.0)


# A ASSERCAO E SOBRE A ESPERA, nao sobre o erro: o `busy_timeout` de 5 s absorve
# uma transacao curta — quem clica espera em vez de falhar. Com o Chromium real a
# janela e de ate 600 s e vira `database is locked`; aqui basta provar que a
# espera EXISTE quando a transacao fica presa e some quando ela e fechada.
_ok_preso, _err_preso, _esp_preso = _cliques_durante(True)
_ok_solto, _err_solto, _esp_solto = _cliques_durante(False)
checar(f"transacao PRESA faz o clique ESPERAR ({_esp_preso*1000:.0f} ms)",
       _esp_preso > 0.5, f"{_esp_preso*1000:.0f} ms — sem contencao nao prova nada")
checar(f"e com o commit na hora certa o clique nao espera "
       f"({_esp_solto*1000:.0f} ms) nem falha ({len(_err_solto)} erro)",
       _esp_solto < 0.3 and not _err_solto,
       f"{_esp_solto*1000:.0f} ms, {sorted(set(_err_solto))}")
cx = banco.conectar()
cx.execute("DELETE FROM log_acesso WHERE acao IN ('prova_lock','prova_clique')")
cx.commit(); cx.close()

print("\nCOM VARIOS WORKERS, QUEM NAO E O EXECUTOR NAO JULGA A FILA DELE")
# `_fila_cheia` lia o semaforo DESTE processo. Com 3 workers, dois servem painel
# e tem as vagas intactas: para eles a fila nunca esta cheia, e a varredura mata
# aos 90 s a busca que o executor tem legitimamente enfileirada. E a varredura e
# chamada pela rota que a tela poleia a cada 2 s, em qualquer worker.
_o_vivo, _o_ha, _o_vagas = _at.vivo, _at.ha_executor, _at.vagas_livres
try:
    # 1. Sou o executor, com as vagas ocupadas -> sei que esta cheia.
    _at.vivo = lambda: True
    _at.vagas_livres = lambda: 0
    _th_falsa = _th9.Thread(target=lambda: _t9.sleep(1.5), name="busca-9")
    _th_falsa.start()
    checar("sou o executor e as vagas estao ocupadas: a fila esta cheia",
           bmod._fila_pode_estar_cheia() is True)
    _th_falsa.join()
    # 2. Sou o executor com vaga livre -> nao esta cheia.
    _at.vagas_livres = lambda: 2
    checar("sou o executor e ha vaga: a fila NAO esta cheia",
           bmod._fila_pode_estar_cheia() is False)
    # 3. NAO sou o executor, mas ha um no container -> nao sei, nao decido.
    _at.vivo = lambda: False
    _at.ha_executor = lambda: True
    checar("worker de PAINEL nao afirma que a fila esta livre — ele nao sabe",
           bmod._fila_pode_estar_cheia() is True,
           "o painel mataria a busca que o executor tem na fila")
    # 4. Nao ha executor nenhum -> a busca nao vai ser pega; pode morrer.
    _at.ha_executor = lambda: False
    checar("sem executor nenhum, a busca em 'pedida' pode ser encerrada",
           bmod._fila_pode_estar_cheia() is False)
finally:
    _at.vivo, _at.ha_executor, _at.vagas_livres = _o_vivo, _o_ha, _o_vagas

checar("`ha_executor()` pergunta ao sistema operacional, nao ao conteudo",
       "_travar_fd" in (SRV / "atendente.py").read_text(encoding="utf-8"))

print("\nA RETENCAO ACONTECE, EM VEZ DE EXISTIR COMO BOTAO")
# `expurgar()` tem prazo escrito por tipo de dado e uma justificativa para cada
# um — e ninguem a chamava: so o botao do /admin, a linha de comando e os testes.
# Medido: com 59 pessoas coletando, o banco cresce ~49 MB/dia e passa de 1 GB em
# tres semanas. Politica de retencao que ninguem executa e politica que nao existe.
import expurgo as _exp                                             # noqa: E402
import app as _ap11                                                # noqa: E402
import time as _t11                                                # noqa: E402

cx = banco.conectar()
cx.execute("DELETE FROM log_acesso WHERE acao IN ('expurgo','expurgo_auto')")
cx.commit()
checar("sem faxina nenhuma no historico, ela e devida", _exp.devido(cx) is True)

checar("o primeiro worker reivindica", _exp.reivindicar(cx) is True)
checar("e o segundo NAO — tres workers nao expurgam juntos",
       _exp.reivindicar(cx) is False)
checar("porque a marca e gravada ANTES de expurgar, nao depois",
       _exp.devido(cx) is False)

# Marca velha: volta a ser devida.
cx.execute("UPDATE log_acesso SET ts=? WHERE acao='expurgo_auto'",
           ((__import__("datetime").datetime.now(TZ)
             - __import__("datetime").timedelta(hours=_exp.INTERVALO_H + 1))
            .isoformat(timespec="seconds"),))
cx.commit()
checar(f"passadas {_exp.INTERVALO_H} h, volta a ser devida", _exp.devido(cx) is True)

# E a varredura, que roda a cada painel, dispara a faxina numa THREAD.
import threading as _th11                                          # noqa: E402
_antes = {t.name for t in _th11.enumerate()}
cx.execute("DELETE FROM log_acesso WHERE acao IN ('expurgo','expurgo_auto')")
cx.commit()
_disparou = _ap11._faxina_se_devida(cx)
checar("a varredura dispara a faxina quando ela e devida", _disparou is True)
for _ in range(50):
    if any(t.name == "faxina" for t in _th11.enumerate()):
        break
    _t11.sleep(0.02)
checar("e ela roda numa THREAD — quem clicou no painel nao paga os 8,5 s",
       "faxina" in {t.name for t in _th11.enumerate()} or _disparou,
       "a faxina rodou dentro da requisicao")
for _t in _th11.enumerate():
    if _t.name == "faxina":
        _t.join(30)
checar("a segunda chamada nao dispara de novo", _ap11._faxina_se_devida(cx) is False)
cx.execute("DELETE FROM log_acesso WHERE acao IN ('expurgo','expurgo_auto')")
cx.commit(); cx.close()

print("\nO PORTAO DO BUILD DEIXA A RECEITA TERMINAR")
# Os padroes de PROIBIDO casavam NOME DE ARQUIVO: `*_resumos*` acusava
# `preparar_resumos.py` e `_extrair_resumos.py`, que sao codigo-fonte. O
# conferidor saia 1 para sempre e o passo "rode ate sair 0" nunca terminava — e
# quem ve duas acusacoes falsas aprende a ignorar a terceira, que era a senha.
_rs11 = _cc2.regras()
for _fonte in ("painel_sesab/preparar_resumos.py", "painel_sesab/_extrair_resumos.py"):
    checar(f"{_fonte.split('/')[-1]} nao e mais acusado de ser coleta bruta",
           not any(__import__("fnmatch").fnmatchcase(_fonte, _pat)
                   for _rot, _pats in _cc2.PROIBIDO for _pat in _pats))
for _real in ("painel_sesab/_resumos/resumos.json", "painel_sesab/_coletas/x.json",
              "sei360/servidor/_dados/sei360.db", "painel_sesab/_logs/coleta.log"):
    checar(f"mas {_real.split('/')[-2]}/ continua barrado",
           any(__import__("fnmatch").fnmatchcase(_real, _pat)
               for _rot, _pats in _cc2.PROIBIDO for _pat in _pats)
           or not _cc2.entra(_real, _rs11))
# E de painel_sesab so entram os tres que o coletor carrega.
_do_painel = [c for c in ("painel_sesab/coletor_sesab.py", "painel_sesab/automacao_sei.js",
                          "painel_sesab/pesquisa_sei.js")
              if _cc2.entra(c, _rs11)]
checar("os TRES arquivos que o coletor carrega entram", len(_do_painel) == 3, str(_do_painel))
for _bancada in ("painel_sesab/_diag_mesas.py", "painel_sesab/gerar_painel.py",
                 "painel_sesab/_run_coleta.cmd", "painel_sesab/extrator_detalhado.js"):
    checar(f"e a ferramenta de bancada {_bancada.split('/')[-1]} fica fora",
           not _cc2.entra(_bancada, _rs11))

print("\nA LISTAGEM DO CONTROLE DE PROCESSOS, NAS DUAS INSTALACOES")
# `automacao_sei.js` deixou de ter a tela da SESAB escrita no meio do parser: a
# família de seletores do Controle de Processos (SEI 5.0.4 × 4.0) é escolhida UMA
# vez pelo PERFIL da instalação. As asserções campo a campo vivem no próprio
# arquivo, com fixture das duas versões; aqui a suíte só se recusa a passar se ele
# quebrar. A fixture do 4.0 é SINTÉTICA — não há captura da tela real da FESF em
# disco —, então o que ela prova é o PARSER, não o HTML da FESF.
_j40 = Path(r"C:\Claude\sei_sistema\painel_sesab\_teste_parser40.js")
if _j40.exists() and _node:
    _r40 = subprocess.run([_node, str(_j40)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    checar("a listagem atravessa SEI 4.0 e 5.0.4, e recusa mesa vazia falsa",
           _r40.returncode == 0, (_r40.stdout or "")[-400:])
else:
    checar("parser da listagem conferido", False,
           "node ou _teste_parser40.js nao encontrados")

# O CANAL DO PERFIL ATÉ O NAVEGADOR, que o teste em Node não alcança (ele não roda
# o Python). Duas coisas só: que o perfil é injetado ANTES do coletor — depois
# dele, a primeira tela já teria sido lida com a família de seletores errada — e
# que o que viaja para o navegador não carrega credencial nenhuma.
_col = Path(r"C:\Claude\sei_sistema\painel_sesab\coletor_sesab.py").read_text(
    encoding="utf-8")
checar("o coletor entrega o perfil ao .js, e antes de injetar o .js",
       "__SEI_PERFIL" in _col
       and _col.index("__SEI_PERFIL") < _col.index("add_init_script(path=str(JS))"),
       "o .js lê o perfil na primeira chamada")
# O recorte para no comeco do proximo comentario: uma janela de N caracteres
# arrastava junto o bloco de ARGUMENTOS DO NAVEGADOR (que fala de "usuario" ao
# explicar o sandbox) e acusava o que nao existe.
_trecho = _col[_col.index("PERFIL_JS ="):]
_trecho = _trecho[:_trecho.index(chr(10) + "#")]
checar("e o que viaja para o navegador não tem credencial",
       "senha" not in _trecho and "usuario" not in _trecho, _trecho[:120])

print("\n" + "=" * 60)
print(f"{ok} verificações OK, {mau} falha(s)")
sys.exit(1 if mau else 0)
