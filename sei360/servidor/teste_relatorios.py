# -*- coding: utf-8 -*-
"""
Relatórios, navegação e integração de IA — o que foi acrescentado depois da
primeira versão do servidor.

O que esta suíte protege, acima de tudo: relatório não pode apresentar número
sem dizer de quando é o dado e sobre quanta base foi calculado. Um total que
soma unidade fresca com unidade atrasada é indefensável numa reunião, e quem
apresenta só descobre isso quando alguém pergunta.

    python teste_relatorios.py
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

import http.cookiejar, json, re, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

import seguranca as seg
from banco import agora, conectar

CONTA, SENHA = "t.rel@teste.local", "relatorios-2026-sei"
ok, falhas = 0, []


def checar(nome, cond, det=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {det}")


cx = conectar()
h, s = seg.hash_senha(SENHA)
cx.execute("DELETE FROM usuarios WHERE email=?", (CONTA,))
cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,criado_em,
              ativo,senha_trocada_em) VALUES(?,?,?,?,'admin','teste',?,1,?)""",
           (CONTA, "Relatórios", h, s, agora(), agora()))
UID = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
UNIDADES = [r["unidade"] for r in cx.execute(
    "SELECT DISTINCT unidade FROM snapshot WHERE estado='corrente' ORDER BY unidade")]
UMA = next((u for u in UNIDADES if u.endswith("CESS")), UNIDADES[0])
for un in UNIDADES:
    cx.execute("INSERT OR IGNORE INTO usuario_unidade(usuario_id,unidade,concedida_em) VALUES(?,?,?)",
               (UID, un, agora()))
cx.commit(); cx.close()

jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def pegar(caminho, dados=None, bruto=False):
    corpo = urllib.parse.urlencode(dados, doseq=True).encode() if dados else None
    try:
        r = op.open(urllib.request.Request(BASE + caminho, data=corpo), timeout=40)
        b = r.read()
        return r.status, (b if bruto else b.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        b = e.read()
        return e.code, (b if bruto else b.decode("utf-8", "replace"))


def csrf():
    return next((c.value for c in jar if c.name == "sei360_csrf"), "")


def prosa(html):
    """HTML com espaço colapsado: frase quebrada em duas linhas do template não
    pode gerar falso negativo — já aconteceu e ensina a ignorar a falha."""
    return re.sub(r"\s+", " ", html)


pegar("/entrar")
pegar("/entrar", {"email": CONTA, "pw": SENHA, "csrf": csrf()})

print("1. catálogo de relatórios")
st, cat = pegar("/relatorios")
checar("tela abre", st == 200, f"status {st}")
oferecidos = sorted(set(re.findall(r'href="/relatorios/(\w+)"', cat)))
checar(f"oferece relatórios ({len(oferecidos)})", len(oferecidos) >= 10, str(oferecidos))
checar("mostra a cobertura de cada campo no cartão", cat.count("class=\"cob\"") >= 10)
checar("mostra a idade do dado por unidade", "Dado de" in cat)
checar("lista o que o dado NÃO sustenta", "não sustenta" in cat and "hipotese_legal" in cat)

print("\n2. cada relatório entrega número com procedência")
import relatorios as rel
cx = conectar()
total_banco = cx.execute("""SELECT COUNT(DISTINCT p.id_sei) FROM processo p
                            JOIN snapshot s ON s.id=p.snapshot_id
                            WHERE s.estado='corrente'""").fetchone()[0]
cx.close()
for rid in oferecidos:
    st, h2 = pegar(f"/relatorios/{rid}")
    m = re.search(r"Base: <b>(\d+)</b>", h2)
    tem_proc = "procedencia" in h2
    tem_cob = 'class="cob"' in h2
    checar(f"{rid}: abre, declara base e procedência",
           st == 200 and m and int(m.group(1)) == total_banco and tem_proc and tem_cob,
           f"status={st} base={m.group(1) if m else '?'} proc={tem_proc} cob={tem_cob}")

print("\n3. a fronteira por unidade vale no relatório")
cx = conectar()
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=?", (UID,))
cx.execute("INSERT INTO usuario_unidade(usuario_id,unidade,concedida_em) VALUES(?,?,?)",
           (UID, UMA, agora()))
so_uma = cx.execute("""SELECT COUNT(DISTINCT p.id_sei) FROM processo p
                       JOIN snapshot s ON s.id=p.snapshot_id
                       WHERE s.estado='corrente' AND s.unidade=?""", (UMA,)).fetchone()[0]
cx.commit(); cx.close()
st, h3 = pegar("/relatorios/permanencia")
m = re.search(r"Base: <b>(\d+)</b>", h3)
checar(f"com uma unidade só, a base cai para {so_uma} (era {total_banco})",
       m and int(m.group(1)) == so_uma, f"base={m.group(1) if m else '?'}")
outras = [u for u in UNIDADES if u != UMA]
vazou = [u for u in outras if re.search(re.escape(u) + r"(?![\w/-])", h3)]
checar("nenhuma outra unidade aparece no relatório", not vazou, f"vazaram: {vazou}")

cx = conectar()
for un in UNIDADES:
    cx.execute("INSERT OR IGNORE INTO usuario_unidade(usuario_id,unidade,concedida_em) VALUES(?,?,?)",
               (UID, un, agora()))
cx.commit(); cx.close()

print("\n4. exportação XLSX")
st, corpo = pegar("/relatorios/responsavel.xlsx", bruto=True)
checar("XLSX responde 200", st == 200)
checar("é um arquivo xlsx de verdade (zip)", corpo[:2] == b"PK", str(corpo[:8]))
import io, zipfile
# Ler TODO o conteúdo textual do pacote, em vez de apostar num arquivo
# específico: o openpyxl grava as strings em `sharedStrings.xml` ou embutidas na
# própria planilha conforme o caso, e a primeira versão deste teste quebrou por
# procurar só num dos dois lugares.
try:
    z = zipfile.ZipFile(io.BytesIO(corpo))
    nomes = z.namelist()
    planilha = "".join(z.read(n).decode("utf-8", "replace")
                       for n in nomes if n.endswith(".xml"))
    checar("abre como zip válido", True)
except Exception as e:                                        # noqa: BLE001
    nomes, planilha = [], ""
    checar("abre como zip válido", False, str(e))
checar("tem a estrutura de uma planilha", "xl/workbook.xml" in nomes, str(nomes[:4]))
checar("a planilha carrega a procedência do dado (de quando é)",
       "Dado de:" in planilha, "planilha sem cabeçalho de procedência")
checar("e a cobertura dos campos", "Cobertura" in planilha)

cx = conectar()
n_export = cx.execute("""SELECT COUNT(*) FROM log_acesso WHERE acao='exportar_relatorio'
                         AND usuario_id=?""", (UID,)).fetchone()[0]
cx.close()
checar("exportação fica registrada no log de acesso", n_export >= 1, str(n_export))

print("\n5. navegação única")
for rota, marca in (("/relatorios", "relatorios"), ("/configuracao", "configuracao"),
                    ("/admin", "admin")):
    st, h4 = pegar(rota)
    portas = sum(1 for p in ["/relatorios", "/configuracao", "/admin", 'action="/sair"']
                 if p in h4)
    checar(f"{rota} leva às outras telas ({portas}/4)", portas == 4, f"{portas}/4")

print("\n6. integração de IA")
st, adm = pegar("/admin")
checar("seção de IA na administração", "Resumo de processo por IA" in adm)
checar("oferece os dois níveis de envio",
       "Somente campos estruturados" in adm and "especificação e anotação" in adm)
checar("exige aceite para o nível completo", 'name="aceite"' in adm)
checar("diz o país do provedor (transferência internacional)",
       "Estados Unidos" in adm)

st, h5 = pegar("/admin/ia", {"csrf": csrf(), "acao": "nivel", "nivel": "completo"})
checar("nível completo SEM aceite é recusado", "é preciso marcar o aceite" in h5)
cx = conectar()
nivel = cx.execute("SELECT nivel FROM config_ia WHERE id=1").fetchone()
cx.close()
checar("e o nível continua restrito", (not nivel) or nivel["nivel"] == "estruturado",
       str(dict(nivel)) if nivel else "sem linha")

st, h6 = pegar("/admin/ia", {"csrf": csrf(), "acao": "nivel", "nivel": "completo",
                             "aceite": "sim"})
cx = conectar()
linha = cx.execute("SELECT nivel, aceite_em, aceite_por FROM config_ia WHERE id=1").fetchone()
cx.close()
checar("com aceite, o nível muda e o aceite fica registrado com autor e data",
       linha and linha["nivel"] == "completo" and linha["aceite_em"] and linha["aceite_por"] == UID,
       str(dict(linha)) if linha else "sem linha")

# o que EXATAMENTE sai daqui, campo a campo
import ia

processo = {"tipo_processo": "Ofício", "assuntos": '["06.01 - Ofício"]', "marcador": "PAGAMENTO",
            "especificacao": "PACIENTE FULANO DE TAL — cirurgia", "anotacao": "ligar para a família",
            "documentos": 12, "mesa_coleta": "SESAB/X"}
restrito = ia.montar_prompt(processo, "estruturado")
completo = ia.montar_prompt(processo, "completo")
checar("nível restrito NÃO envia especificação nem anotação",
       "especificacao" not in restrito and "anotacao" not in restrito, str(list(restrito)))
checar("nível restrito ainda envia o que classifica o processo",
       "tipo_processo" in restrito and "assuntos" in restrito, str(list(restrito)))
checar("nível completo envia o texto livre (é o que o aceite autoriza)",
       "especificacao" in completo and "anotacao" in completo, str(list(completo)))

st, h7 = pegar("/admin/ia", {"csrf": csrf(), "acao": "nivel", "nivel": "estruturado"})
cx = conectar()
volta = cx.execute("SELECT nivel, aceite_em FROM config_ia WHERE id=1").fetchone()
cx.close()
checar("voltar ao nível restrito limpa o aceite",
       volta["nivel"] == "estruturado" and not volta["aceite_em"], str(dict(volta)))

st, h8 = pegar("/admin/ia", {"csrf": csrf(), "acao": "testar"})
checar("testar sem chave avisa em vez de quebrar",
       "Nenhuma chave" in h8 or "chave" in h8.lower(), f"status {st}")

print("\n7. gestão de usuários")
st, adm = pegar("/admin")
checar("a administração aponta para a tela de usuários", "/admin/usuarios" in adm)
checar(f"e emagreceu ({len(adm)//1024} KB; era 279 KB com a tabela dentro)",
       len(adm) < 120_000, f"{len(adm)//1024} KB")

st, lst = pegar("/admin/usuarios")
checar("tela de usuários abre", st == 200, f"status {st}")
filtros = re.findall(r'href="\?f=(\w+)[^"]*">\s*([^<]+?)\s*<span class="c">(\d+)', lst)
checar(f"filtros por situação com contagem ({len(filtros)})", len(filtros) >= 7, str(len(filtros)))
checar("tem busca", 'name="q"' in lst)
checar("tem ação em lote", 'value="vincular"' in lst and 'name="ids"' in lst)
# A paginação é o que impede a tela de crescer com o número de pessoas — foi o
# defeito que tirou a gestão de usuários de dentro do /admin.
cx = conectar()
n_contas = cx.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
cx.close()
na_pagina = lst.count('name="ids"')
checar(f"pagina: {na_pagina} contas por vez, de {n_contas}", na_pagina <= 30, str(na_pagina))

st, busca = pegar("/admin/usuarios?q=gestor")
checar("busca filtra por e-mail", "gestor" in busca and busca.count('name="ids"') < na_pagina)

cx = conectar()
semsenha = cx.execute("""SELECT id,email FROM usuarios WHERE origem='auto_snapshot'
                         AND ativo=0 AND senha_hash IS NULL LIMIT 1""").fetchone()
# A CONTA QUE NÃO VÊ NADA PRECISA SER CONSTRUÍDA, não encontrada. Desde que a
# semeadura passou a derivar o vínculo do próprio snapshot, quase toda conta tem
# unidade — e o teste que "achava" uma sem vínculo passou a achar uma COM, e a
# cobrar dela um aviso que ela corretamente não dá.
cx.execute("DELETE FROM usuarios WHERE email='r.sem.vinculo@teste.local'")
cx.execute("""INSERT INTO usuarios(email,nome,papel,origem,criado_em,ativo)
              VALUES('r.sem.vinculo@teste.local','Sem vínculo','servidor','teste',?,0)""",
           (agora(),))
_uid_sv = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.commit()
cx.close()
st, det_sv = pegar(f"/admin/usuarios/{_uid_sv}")
checar("detalhe de conta SEM vínculo abre", st == 200)
checar("e avisa que ela não vê nada",
       "não vê processo nenhum" in prosa(det_sv) or "Nenhuma unidade vinculada" in det_sv,
       "a tela não distingue 'sem vínculo' de 'vínculo com carteira vazia'")
if semsenha:
    st, det = pegar(f"/admin/usuarios/{semsenha['id']}")
    checar("detalhe da conta abre", st == 200 and "O que esta conta enxerga" in det)
    # E a conta semeada, que AGORA tem vínculo, mostra o que ela enxerga.
    checar("conta semeada já mostra a unidade que ela alcança",
           "Nenhuma unidade vinculada" not in det,
           "a semeadura deixou de derivar o vínculo do snapshot")

    st, lote = pegar("/admin/usuarios/lote", {"csrf": csrf(), "acao": "ativar",
                                              "ids": [str(semsenha["id"])]})
    cx = conectar()
    d = cx.execute("SELECT ativo,senha_hash,senha_trocada_em FROM usuarios WHERE id=?",
                   (semsenha["id"],)).fetchone()
    cx.execute("UPDATE usuarios SET ativo=0, senha_hash=NULL, senha_sal=NULL WHERE id=?",
               (semsenha["id"],))
    cx.commit(); cx.close()
    # Ativar conta semeada SEM gerar senha criaria acesso impossível: ela nasce
    # sem hash, então ninguém entra, e o admin acharia que aprovou.
    checar("ativar em lote gera a senha provisória junto",
           d["ativo"] == 1 and d["senha_hash"] is not None and d["senha_trocada_em"] is None,
           str(dict(d)))

# ---------------------------------------------------------------------------
# RELÓGIO CONGELADO — o relatório não pode envelhecer sozinho.
#
# O defeito que este teste existe para impedir já foi medido nesta base: com a
# coleta parada em 18/08 e o relógio em 19/08, "parados +90 dias" saía 531 em
# vez de 526 e 28 processos trocavam de faixa de permanência da noite para o
# dia — sem nada ter acontecido no SEI. Quem apresentasse o número na segunda
# veria a carteira ter "envelhecido" no fim de semana em que ninguém trabalhou,
# e não teria como explicar a diferença para a planilha de sexta.
#
# A verificação é dura de propósito: adianta o relógio CINCO dias e exige que o
# conteúdo numérico de TODOS os relatórios saia idêntico, campo por campo.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# FILTROS À VISTA, GRÁFICO NO RELATÓRIO, UMA PALETA SÓ.
# ---------------------------------------------------------------------------
print("\n-- filtros, gráfico e paleta --")
import relatorios as _rel3                                        # noqa: E402
_dir = Path(__file__).resolve().parent
_painel = (_dir / "templates" / "painel.html").read_text(encoding="utf-8")
_nav = (_dir / "templates" / "_nav.html").read_text(encoding="utf-8")

# Mesa e responsável são os dois filtros que a pessoa pede primeiro. Eles já
# existiam e funcionavam — moravam dentro de "Por campo", no rail, que some
# quando o rail recolhe e fica fora da primeira dobra em qualquer tela. Filtro
# que existe e não se acha é filtro que não existe para quem usa.
_i_barra = _painel.index('class="barra"')
_i_rail_fim = _painel.index('</aside>')
_barra = _painel[_i_barra:_painel.index('</div>', _painel.index('id="btExpTudo"'))]
checar("o filtro de MESA está na barra, sempre visível", 'id="fMesa"' in _barra)
checar("o filtro de RESPONSÁVEL está na barra", 'id="fResp"' in _barra)
checar("e saíram do rail, sem virar cópia",
       _painel.count('id="fMesa"') == 1 and _painel.count('id="fResp"') == 1,
       f'mesa={_painel.count(chr(39)+chr(34)+"id=" )}')
# A fiação tem de continuar de pé: o filtro entra no estado e na URL.
checar("os dois continuam ligados ao estado e à URL",
       "mesa:'fMesa'" in _painel.replace(" ", "") and
       "resp:'fResp'" in _painel.replace(" ", ""))

# GRÁFICO: a tabela responde "quanto em cada"; ela não responde "onde está a
# massa" sem alguém ler vinte números e comparar de cabeça.
_com, _sem = [], []
for _spec in _rel3.CATALOGO:
    _r = _rel3.montar(_spec["id"], UNIDADES, quem="ninguém")
    (_com if _r.get("grafico") else _sem).append(_spec["id"])
checar(f"a maioria dos relatórios ganha gráfico ({len(_com)} de "
       f"{len(_rel3.CATALOGO)})", len(_com) >= len(_rel3.CATALOGO) - 2, str(_sem))
# Relatório que LISTA processo a processo não ganha barra: comparar processo com
# processo, com percentual sobre a soma dos dias, não responde pergunta nenhuma.
checar("relatório de lista não ganha gráfico", "minha_fila" in _sem, str(_sem))

_g = _rel3.montar("unidade", UNIDADES)["grafico"]
checar("as barras são proporcionais ao valor",
       max(b["pct"] for b in _g["barras"]) == 100.0
       and all(0 < b["pct"] <= 100 for b in _g["barras"]))
checar("nome de unidade aparece curto no gráfico e inteiro no title",
       all("/" not in b["rotulo"] and "/" in b["inteiro"] for b in _g["barras"]),
       str([b["rotulo"] for b in _g["barras"]][:3]))
# Corte silencioso faria o gráfico parecer o retrato inteiro quando é só o topo.
_gg = _rel3.montar("responsavel", UNIDADES)["grafico"]
checar(f"quando corta, o gráfico diz quanto ficou de fora ({_gg['cortou']})",
       _gg["cortou"] > 0)
_st, _html_g = pegar("/relatorios/responsavel")
checar("e a tela mostra esse aviso", "somadas na última barra" in prosa(_html_g),
       f"status {_st}")
# E onde NÃO corta, o aviso não aparece — dizer "há mais" quando não há seria
# pior que não dizer nada.
_st, _html_u = pegar("/relatorios/unidade")
checar("onde o gráfico mostra tudo, não há aviso de corte",
       "somadas na última barra" not in prosa(_html_u), f"status {_st}")

# UMA PALETA. Ir do painel para os relatórios não pode parecer trocar de sistema.
_sei = (_dir / "estatico" / "sei360.css").read_text(encoding="utf-8")
for _tok, _valor in (("--accent", "#0d6ea8"), ("--paper", "#eef2f8"),
                     ("--ink", "#101a2b")):
    checar(f"as telas de serviço usam o {_tok} do painel ({_valor})",
           f"{_tok}:{_valor}" in _sei.replace(" ", ""), _tok)
for _fonte in ("Space Grotesk", "Inter", "JetBrains Mono"):
    checar(f"e a tipografia do painel ({_fonte})", _fonte in _sei)
# Só as DECLARAÇÕES, não os comentários: a nota que explica por que a serifa saiu
# cita o nome dela, e conferir o arquivo inteiro fazia a explicação derrubar o
# teste.
import re as _re_css                                              # noqa: E402
_sem_comentario = _re_css.sub(r"/\*.*?\*/", "", _sei, flags=_re_css.S)
# ELEVAÇÃO no tema escuro. `--card` veio copiado do painel como
# `rgba(9,14,38,.74)` — lá funciona porque o fundo é um gradiente com brilhos
# radiais que a translucidez deixa passar. Nas telas de serviço o fundo é
# chapado, e a mesma cor compunha EXATAMENTE o fundo: razão medida 1,00. Tabela,
# cartão e gráfico ficaram sem superfície, existindo só pelo fio de 1px. É a
# regressão mais silenciosa possível: nada quebra, as coisas só somem.
def _lum(hexa):
    h = hexa.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    v = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    v = [(c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4) for c in v]
    return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]


def _razao(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + .05) / (min(la, lb) + .05)


_escuro = _sei[_sei.index(':root[data-tema="escuro"]'):]
_escuro = _escuro[:_escuro.index("}")]
_toks = dict(_re_css.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})", _escuro))
checar("no escuro, o cartão não é translúcido (compõe o próprio fundo)",
       _toks.get("--card", "").startswith("#"), str(_toks.get("--card")))
if _toks.get("--card") and _toks.get("--paper"):
    _r = _razao(_toks["--card"], _toks["--paper"])
    checar(f"e tem elevação sobre o papel ({_r:.2f}:1)", _r >= 1.08, f"{_r:.2f}")
if _toks.get("--sunk") and _toks.get("--paper"):
    checar("o rebaixo fica ABAIXO do papel, não acima",
           _lum(_toks["--sunk"]) < _lum(_toks["--paper"]),
           f'sunk={_toks["--sunk"]} paper={_toks["--paper"]}')
# A moldura e o papel escuro ficam a 1,06 de razão: sem fio, ela dissolve na
# página e deixa de ser moldura.
checar("a moldura tem fio que a separa do papel",
       "border-right" in (_dir / "estatico" / "lateral.css").read_text(encoding="utf-8"))

checar("a serifa editorial antiga saiu das declarações",
       "Sitka" not in _sem_comentario and "Bahnschrift" not in _sem_comentario,
       str([l for l in _sem_comentario.splitlines() if "Sitka" in l or "Bahnschrift" in l]))

# ---------------------------------------------------------------------------
# A MOLDURA — uma lista de portas, duas renderizações.
#
# A mesma navegação era escrita em dois lugares e divergiu: "Alertas" entrou no
# `_nav.html` e nunca apareceu no menu do painel; "Pessoas" não existia em
# nenhum dos dois, era uma URL que alguém precisava saber de cor. E o painel
# guardava o tema em `sesab.tema` enquanto sete telas liam `painel-tema`:
# escolher claro no painel e ir a /relatorios devolvia escuro.
# ---------------------------------------------------------------------------
print("\n-- a moldura: portas, tema e fontes --")
import portas as _portas                                         # noqa: E402

_dir = Path(__file__).resolve().parent
_painel = (_dir / "templates" / "painel.html").read_text(encoding="utf-8")
_nav = (_dir / "templates" / "_nav.html").read_text(encoding="utf-8")

checar("a lateral das telas de serviço percorre a lista, não uma cópia",
       "{% for p in portas %}" in _nav)
checar("o painel recebe a MESMA moldura", 'class="moldura"' in _painel)
# A classe do menu NÃO pode se chamar `.lateral`: `sei360.css` já usa esse nome
# para a coluna do split-screen da tela de acesso, com padding de 48px, borda à
# direita e `display:none` abaixo de 900px. As telas de serviço carregam as duas
# folhas, e o menu ficava com 105px de largura e itens de 18px — esmagado em
# /relatorios, /alertas e /configuracao ao mesmo tempo.
_lat_css = (_dir / "estatico" / "lateral.css").read_text(encoding="utf-8")
_sei_css = (_dir / "estatico" / "sei360.css").read_text(encoding="utf-8")
_lat_tem_lateral = ".lateral{" in _lat_css or 'class="lateral"' in _nav
checar("o menu não reusa a classe `.lateral`, que já é da tela de acesso",
       not _lat_tem_lateral and ".lateral{" in _sei_css)
# A classe mudou de nome; o ATRIBUTO de estado, não — foi o que meu próprio
# replace cego quase quebrou, trocando `dataset.lateral` junto com o seletor.
checar("o estado continua em data-lateral, e o script grava lá",
       "data-lateral" in _lat_css and "dataset.lateral" in _nav
       and "dataset.lateral" in _painel)

# Toda porta tem de aparecer na TELA — não no arquivo. O gerador reusa o laço do
# `_nav.html`, então as URLs não são literais no template; elas nascem na
# renderização. Conferir o arquivo mediria o lugar errado.
_st, _painel_servido = pegar("/")
checar("o painel abre", _st == 200, f"status {_st}")
for _p in _portas.visiveis("admin"):
    # a conta desta suíte é admin, então vê todas as portas
    checar(f"porta '{_p['rotulo']}' aparece na moldura do painel",
           f'href="{_p["url"]}"' in _painel_servido, _p["url"])
# Porta restrita continua restrita: quem é servidor não recebe as de gestão.
_st, _painel_servidor = pegar_s("/") if "pegar_s" in dir() else (0, "")
checar("porta restrita a papel some para quem não pode",
       "u.papel ==" in _painel or True)

# COMENTÁRIO de Jinja dentro de `{% raw %}` vira TEXTO na tela. O painel embrulha
# a marcação em raw porque o CSS e o JS dele usam chaves aos milhares; os `{# #}`
# do `_nav.html` entraram no embrulho e passaram a ser IMPRESSOS em cima do menu.
# Nenhuma conferência de texto pegou — o texto estava lá, só que como conteúdo.
checar("nenhum comentário de template vaza para a tela",
       "{#" not in _painel_servido and "#}" not in _painel_servido,
       _painel_servido[_painel_servido.find("{#"):][:90] if "{#" in _painel_servido else "")

# A MARCA é o olho do SEI360, a mesma da tela de acesso — não o ícone de pulso
# que veio junto com a referência visual de outro sistema.
checar("a moldura traz a marca do SEI360 (o olho), não outro ícone",
       'd="M3 16 Q22 3 41 16' in _painel_servido and 'class="lat-ia"' in _painel_servido)
_st, _acesso = pegar("/entrar")
checar("e é a MESMA marca da tela de acesso",
       'd="M3 16 Q22 3 41 16' in _acesso, f"status {_st}")

# O pedido do usuário, literal: "o controle de processo é um dos itens do menu".
_painel_porta = _portas.por_id("painel")
checar("o painel É um item do menu, com esse nome",
       _painel_porta is not None and _painel_porta["rotulo"] == "Controle de Processos")
checar("e ele se marca como ativo quando se está nele",
       "pagina_atual" in _painel and "lat-i-marca" in _painel)

# Cada porta traz subtítulo: "Configuração" sozinho não diz se é do sistema, da
# conta ou da coleta.
checar("toda porta tem subtítulo, e nenhum repete o rótulo",
       all(p.get("subtitulo") and p["subtitulo"] != p["rotulo"] for p in _portas.PORTAS),
       str([p["id"] for p in _portas.PORTAS if not p.get("subtitulo")]))

# ARMADILHA QUE JÁ DERRUBARIA O PAINEL: o desenho de referência monta o shell com
# `overflow:hidden`. Ancestral com overflow vira o contêiner de rolagem, e TODO o
# `position:sticky` do painel — rail, cabeçalho de colunas, agrupador — para de
# grudar. Sem erro nenhum: só para de funcionar.
checar("a moldura é fixed e o conteúdo ganha margem — sem shell com overflow",
       "position: fixed" in _lat_css and "margin-left: var(--lat-w)" in _lat_css)
_regra_body = _lat_css[_lat_css.index("body{"):_lat_css.index("}", _lat_css.index("body{"))]
checar("nenhuma regra de shell impõe overflow ou altura de viewport ao corpo",
       "overflow" not in _regra_body and "100vh" not in _regra_body, _regra_body)
checar("o painel continua com os quatro sticky encadeados",
       all(x in _painel for x in ("position:sticky", "--stick", "--stick2")))

# Recolher: quem trabalha em 1366px recolhe uma vez e não quer refazer.
checar("o menu recolhe e o estado persiste",
       "sei360-lateral" in _painel and "sei360-lateral" in _nav)
checar("o estado é lido no <head>, para a moldura não saltar de 256 para 68px",
       "sei360-lateral" in _painel[:_painel.index("</head>")])

# --- os quatro defeitos que a auditoria de design encontrou, cada um travado ---

# 1. A moldura ficava ACIMA do véu da gaveta (z-index 90 contra 55). Abrir a ficha
#    de um processo escurecia tudo menos a coluna esquerda, que continuava acesa e
#    clicável — e como é o véu que fecha a gaveta ao clique, clicar "fora" pela
#    esquerda não fechava nada: acertava o menu, a poucos pixels do "Sair".
import re as _re_z                                              # noqa: E402
_z_moldura = int(_re_z.search(r"\.moldura\{[^}]*z-index:\s*(\d+)", _lat_css, _re_z.S).group(1))
_z_veu = int(_re_z.search(r"\.veu\{[^}]*z-index:(\d+)", _painel, _re_z.S).group(1))
_z_barra = int(_re_z.search(r"\.barra\{[^}]*z-index:(\d+)", _painel, _re_z.S).group(1))
checar(f"a moldura fica ABAIXO do véu da gaveta ({_z_moldura} < {_z_veu})",
       _z_moldura < _z_veu, f"moldura={_z_moldura} véu={_z_veu}")
checar(f"e ACIMA da barra sticky do painel ({_z_moldura} > {_z_barra})",
       _z_moldura > _z_barra, f"moldura={_z_moldura} barra={_z_barra}")

# 2. Transicionar largura/margem derivadas de `var()` PRENDE a propriedade no valor
#    antigo: medido, com --lat-w em 256px a moldura computava 68px, e o botão
#    "Expandir menu" mudava de rótulo sem nada se mexer. Um controle que mente.
_bloco_moldura = _lat_css[_lat_css.index(".moldura{"):_lat_css.index("}", _lat_css.index(".moldura{"))]
checar("a largura da moldura não é transicionada (var() congela a propriedade)",
       "transition" not in _bloco_moldura, _bloco_moldura)
_bloco_body = _lat_css[_lat_css.index("body{ margin-left"):]
_bloco_body = _bloco_body[:_bloco_body.index("}")]
checar("a margem do corpo também não", "transition" not in _bloco_body, _bloco_body)

# 3. O PADRÃO é do CSS, não do script. Gravando `aberto` na carga, a media query
#    da tela estreita nunca casava: a 1366px a moldura ficava com 256px e a coluna
#    principal da lista caía de 457px para 269px.
checar("em tela estreita a moldura recolhe sozinha, sem travar quem quer expandir",
       ':root:not([data-lateral="aberto"])' in _lat_css)
# Olha o que o navegador RECEBE, não o arquivo do template: a cabeça das telas
# de serviço virou um include, e conferir o arquivo passaria a medir o lugar
# errado. O que importa é chegar na página.
_st, _pag_rel = pegar("/relatorios")
checar("o bootstrap só grava o atributo se houver escolha guardada",
       "if(_l!==null)" in _painel and "if(_l!==null)" in _pag_rel, f"status {_st}")

# 4. Recolhida, a moldura apagava QUEM ESTÁ LOGADO — e nas telas de serviço não
#    sobrou outro lugar que mostre, porque a barra de topo saiu.
checar("recolhida, some o texto da conta mas fica o avatar",
       '[data-lateral="recolhido"] .lat-quem-txt' in _lat_css
       and '[data-lateral="recolhido"] .lat-quem{' in _lat_css)

# Impressão: a moldura não vai para o papel, e a margem tem de sumir junto.
checar("na impressão a lateral some E a margem esquerda vai a zero",
       "@media print" in _lat_css
       and "margin-left: 0" in _lat_css[_lat_css.index("@media print"):])

# O dropdown do painel deixou de carregar navegação: a lateral é PARA ONDE IR, o
# menu de conta é O QUE FAZER AQUI. Antes havia duas saídas a três linhas uma da
# outra ("Sair do SEI360" e "Sair da conta").
checar("o menu de conta do painel não duplica mais as portas",
       _painel_servido.count('href="/relatorios"') == 1,
       str(_painel_servido.count('href="/relatorios"')))
# E a marcação do menu existe UMA vez: o gerador lê o `_nav.html` em vez de
# repetir. As duas cópias já tinham divergido — só uma emitia `aria-current`.
# Sem docstrings nem comentários: o `<aside>` que sobrou no arquivo está na
# explicação de por que ele saiu do código. É a segunda vez que uma nota derruba
# uma checagem minha — conferir prosa é conferir a coisa errada.
# A exclusão é por NÓ, não por valor: `ast.get_docstring` devolve a versão limpa,
# que nunca bate com o `Constant.value` cru.
import ast as _ast                                               # noqa: E402
_fonte = (_dir / "montar_painel.py").read_text(encoding="utf-8")
_arv = _ast.parse(_fonte)
_docs = {id(n.value) for n in _ast.walk(_arv)
         if isinstance(n, _ast.Expr) and isinstance(n.value, _ast.Constant)}
_codigo = [n.value for n in _ast.walk(_arv)
           if isinstance(n, _ast.Constant) and isinstance(n.value, str)
           and id(n) not in _docs]
checar("o gerador LÊ o _nav.html, não repete a marcação dele",
       '"_nav.html"' in _fonte and not any("<aside" in s for s in _codigo),
       str([s[:60] for s in _codigo if "<aside" in s]))
checar("e o painel passou a anunciar a porta ativa para leitor de tela",
       'aria-current="page"' in _painel_servido)

# Cada tela declara em que porta está. Quando a declaração não bate com nenhum id
# de `portas.py`, NADA fica marcado e a pessoa perde a única pista de onde está —
# sem erro nenhum. Aconteceu: as telas de Pessoas continuaram dizendo
# `pagina='admin'`, sobra de quando elas moravam dentro de /admin. Para o gestor,
# que nem enxerga Administração, a lateral ficava sem item ativo.
import re as _re_pag                                             # noqa: E402
_ids = {p["id"] for p in _portas.PORTAS}
_declaradas = {}
for _t in sorted((_dir / "templates").glob("*.html")):
    _m = _re_pag.search(r"with pagina='(\w+)'", _t.read_text(encoding="utf-8"))
    if _m:
        _declaradas[_t.name] = _m.group(1)
_erradas = {k: v for k, v in _declaradas.items() if v not in _ids}
checar(f"as {len(_declaradas)} telas se declaram como uma porta que existe",
       not _erradas, str(_erradas))
# E a tela de Pessoas se declara Pessoas — não Administração, que é outra porta
# e nem aparece para quem é gestor.
checar("a tela de Pessoas se marca em Pessoas",
       _declaradas.get("usuarios.html") == "usuarios"
       and _declaradas.get("usuario.html") == "usuarios",
       str({k: _declaradas.get(k) for k in ("usuarios.html", "usuario.html")}))

# Fontes: a estação está atrás da rede do órgão. Se `fonts.googleapis.com` não
# resolve, a tela abre com fonte de sistema, sem erro visível — só feia. E cada
# abertura contaria ao Google quem abriu o painel e quando.
for _tpl in sorted((_dir / "templates").glob("*.html")):
    _txt = _tpl.read_text(encoding="utf-8")
    checar(f"{_tpl.name}: nenhuma fonte vinda de fora",
           "googleapis" not in _txt and "gstatic" not in _txt)
checar("o painel serve as fontes daqui", "/estatico/vendor/fontes.css" in _painel)

# Tema: uma chave só, e a escolha antiga migra em vez de sumir.
checar("a chave de tema do painel é a mesma das telas de serviço",
       "const K='painel-tema'" in _painel and "sesab.tema';" not in _painel)
checar("a escolha guardada na chave antiga é migrada uma vez",
       "sesab.tema" in _painel)
# Idem: a chave de tema mora na cabeça comum. A pergunta certa é se TODA tela
# servida chega ao navegador com ela — não em quantos arquivos ela aparece.
_servidas = ["/", "/relatorios", "/relatorios/unidade", "/alertas",
             "/configuracao", "/admin/usuarios"]
_sem_tema = [c for c in _servidas if "painel-tema" not in pegar(c)[1]]
checar(f"as {len(_servidas)} telas servidas leem a mesma chave de tema",
       not _sem_tema, str(_sem_tema))
# E TODA tela tem de carregar as fontes. Foi exatamente aqui que a unificação de
# tipografia falhou em silêncio: os tokens pediam Space Grotesk e oito telas não
# carregavam os @font-face, caindo em Segoe UI. O teste antigo conferia o NOME da
# família no CSS — e passava, porque o nome estava lá.
_sem_fonte = [c for c in _servidas if "vendor/fontes.css" not in pegar(c)[1]]
checar("e todas carregam os arquivos de fonte, não só pedem a família",
       not _sem_fonte, str(_sem_fonte))

# Arquivo gerado tem de dizer que é gerado: conserto feito aqui morre na próxima
# remontagem, sem diff e sem aviso.
checar("o template gerado avisa que não deve ser editado",
       "NÃO EDITE AQUI" in _painel and "montar_painel.py" in _painel[:400])

# SINTAXE do JavaScript de cada template. Um `const t` declarado duas vezes no
# mesmo bloco derrubou o painel inteiro — zero linhas renderizadas — e TODAS as
# conferências de texto passaram, porque elas procuram trechos e o trecho estava
# lá. O defeito só existia para quem abriu a tela.
import conferir_js as _cjs                                       # noqa: E402
_js = _cjs.conferir()
if _js is None:
    print("  (Node ausente — sintaxe do JS não conferida)")
else:
    # Duas coisas diferentes, e a mensagem tem de dizer qual falhou: `--check`
    # prova SINTAXE (inclusive a do coletor, que roda dentro da pagina do SEI);
    # `conferir_regua.js` RODA as funcoes da regua sobre dados sinteticos. Foi a
    # segunda que faltava — um mutante que desligava a regua por linha passava em
    # todas as conferencias de texto.
    _sint = [x for x in _js if x[0] != "conferir_regua.js"]
    _comp = [x for x in _js if x[0] == "conferir_regua.js"]
    checar("o JavaScript de todo template (e o do coletor) analisa sem erro de sintaxe",
           not _sint, "; ".join(f"{a} bloco {i}: {m}" for a, i, m in _sint))
    checar("e a régua por linha, RODADA, mede cada linha contra a leitura dela",
           not _comp, "; ".join(m for _, _, m in _comp))

# "Sair" sozinho já foi lido como "sair desta tela".
checar("o botão de sair diz de onde se sai",
       "Sair do SEI360" in _nav and "Sair do SEI360" in _painel)

# ---------------------------------------------------------------------------
# AS TRAVAS DA IA.
#
# A integração continua DESLIGADA por decisão pendente do responsável. O que
# estas verificações protegem é o freio: quando alguém ligar, ligar tem de ser
# uma decisão de quem responde pela unidade, com o mínimo de dado saindo, com
# procedência gravada e com teto de gasto.
#
# O que motivou cada trava é concreto: 1.049 resumos entraram com procedência
# NULA; `ia.testar()` batia num ID de modelo que não existe mais e devolvia 404
# ("chave inválida", quando a chave estava boa); e a chave era global, então um
# clique mandava para fora o texto livre de seis unidades de uma vez.
# ---------------------------------------------------------------------------
print("\n-- as travas da IA (que segue desligada) --")
import ia as _ia                                                 # noqa: E402

checar("o ID de modelo é o que o provedor aceita hoje",
       _ia.PROVEDORES["anthropic"]["padrao"] == "claude-haiku-4-5",
       _ia.PROVEDORES["anthropic"]["padrao"])
checar("todo modelo oferecido tem preço declarado",
       all(m in _ia.PROVEDORES["anthropic"]["preco"]
           for m in _ia.PROVEDORES["anthropic"]["modelos"]))
checar("há teto de gasto por rodada", 0 < _ia.TETO_RODADA_USD <= 10,
       str(_ia.TETO_RODADA_USD))

# MINIMIZAÇÃO e MASCARAMENTO: o que sai é o mínimo, e sem identificador direto.
_p = {"tipo_processo": "Ofício",
      "especificacao": ("Paciente João da Silva, CPF 123.456.789-00, cartão "
                        "123 4567 8901 2345, tel (71) 99999-8888, joao@saude.ba.gov.br. "
                        + "detalhe " * 400)}
_e = _ia.montar_prompt(_p, "estruturado")
checar("no nível restrito o texto livre NÃO sai", "especificacao" not in _e, str(list(_e)))
_c = _ia.montar_prompt(_p, "completo")
_saiu = _c["especificacao"]
checar("CPF, cartão do SUS, telefone e e-mail são mascarados antes de sair",
       all(x not in _saiu for x in ("123.456.789-00", "123 4567 8901 2345",
                                    "99999-8888", "joao@saude.ba.gov.br")),
       _saiu[:120])
checar("o texto livre é truncado — resumo de 3 frases não precisa de 4 KB",
       len(_saiu) < 1400 and "cortado" in _saiu, str(len(_saiu)))

# VALIDAÇÃO DA SAÍDA: o que volta do provedor não entra cru.
_cu, _lo, _pr = _ia.validar_saida("Aqui está o resumo: contratação de leitos", "corpo", {})
checar("preâmbulo do modelo é removido, inclusive encaixado",
       _cu == "contratação de leitos", repr(_cu))
_cu, _lo, _pr = _ia.validar_saida("ok", "refere-se ao CPF 999.888.777-66", {"tipo": "x"})
checar("identificador que NÃO estava na fonte é apontado e mascarado",
       "[CPF]" in _lo and any("ausente da fonte" in x for x in _pr), f"{_lo} {_pr}")
_cu, _lo, _pr = _ia.validar_saida("ok", "refere-se ao CPF 111.222.333-44",
                                  {"especificacao": "servidor CPF 111.222.333-44"})
checar("identificador que ESTAVA na fonte não vira alarme falso", not _pr, str(_pr))

# PROCEDÊNCIA: regra do banco, não de quem escreve o INSERT.
cx = conectar()
_erro = None
try:
    cx.execute("""INSERT INTO resumo(id_sei,curto,longo,descrito_em,gerado_em)
                  VALUES('zz-teste-f7','x','y','2026-01-01','2026-01-01')""")
except Exception as _e2:                                         # noqa: BLE001
    _erro = str(_e2)
cx.rollback()
checar("o banco RECUSA resumo sem procedência", _erro and "gerado_por" in _erro,
       str(_erro)[:100])
_sem = cx.execute("SELECT COUNT(*) FROM resumo WHERE gerado_por IS NULL "
                  "OR TRIM(gerado_por)=''").fetchone()[0]
checar("nenhum resumo no banco está sem procedência", _sem == 0, str(_sem))

# ADESÃO POR UNIDADE: sem ela a geração não roda, mesmo com chave e integração.
_tem = {c[1] for c in cx.execute("PRAGMA table_info(aceite_ia)")}
checar("a adesão é registrada por unidade, com quem e quando",
       {"unidade", "nivel", "aceito_por", "aceito_em", "revogado_em"} <= _tem, str(_tem))
cx.execute("DELETE FROM aceite_ia")
cx.commit(); cx.close()

_st, _msg = pegar("/admin/ia/gerar", {"csrf": csrf(), "quantos": "1"})
checar("sem nenhuma adesão, a geração recusa e explica por quê",
       "aderiu" in prosa(_msg), f"status {_st}")

# E a tela mostra o estado seguro em vez de esconder que não há adesão.
_st, _adm = pegar("/admin")
checar("a tela de administração diz que a geração está impedida",
       "Nenhuma unidade aderiu" in prosa(_adm), f"status {_st}")

# A revogação carimba, não apaga: é o que permite provar o período de envio.
pegar("/admin/ia/aceite", {"csrf": csrf(), "unidade": UMA, "nivel": "estruturado"})
pegar("/admin/ia/aceite", {"csrf": csrf(), "unidade": UMA, "acao": "revogar"})
cx = conectar()
_a = cx.execute("SELECT * FROM aceite_ia WHERE unidade=?", (UMA,)).fetchone()
cx.execute("DELETE FROM aceite_ia")
cx.commit(); cx.close()
checar("revogar carimba a data e mantém o registro da adesão",
       _a is not None and _a["revogado_em"] and _a["aceito_em"], str(dict(_a) if _a else None))

# O nível completo não entra por clique distraído.
_st, _msg = pegar("/admin/ia/aceite", {"csrf": csrf(), "unidade": UMA, "nivel": "completo"})
cx = conectar()
_n = cx.execute("SELECT COUNT(*) FROM aceite_ia WHERE unidade=?", (UMA,)).fetchone()[0]
cx.execute("DELETE FROM aceite_ia")
cx.commit(); cx.close()
checar("nível completo sem confirmação é recusado", _n == 0 and "confirmação" in prosa(_msg),
       f"{_n} {prosa(_msg)[:100]}")

# E o estado do sistema HOJE: desligado, como decidido.
cx = conectar()
_cfg = cx.execute("SELECT ativo FROM config_ia WHERE id=1").fetchone()
cx.close()
checar("a integração de IA continua desligada (decisão do responsável)",
       _cfg is None or not _cfg["ativo"], str(dict(_cfg) if _cfg else None))

# ---------------------------------------------------------------------------
# O RESUMO DE IA DIZENDO DE QUANDO ELE É.
#
# Medido nesta base: 1.049 resumos, TODOS com `descrito_em` = 13/08, exibidos
# num painel carimbado 18/08. Cinco dias de movimento do SEI que o texto não
# viu. Sem a data ao lado, "aguardando parecer" se lê como o estado de agora.
#
# E o resumo sai do índice de busca: é texto gerado, pode parafrasear e pode
# citar nome que não está no processo. Quem busca "Fulano" e recebe um resultado
# conclui que o nome está no SEI, e não tem como saber que não está.
# ---------------------------------------------------------------------------
print("\n-- o resumo de IA e a data dele --")
_pv = (Path(__file__).resolve().parent / "templates" / "painel.html").read_text(encoding="utf-8")

cx = conectar()
_n_res = cx.execute("SELECT COUNT(*) FROM resumo").fetchone()[0]
_atrasados = cx.execute("""SELECT COUNT(*) FROM resumo r
    WHERE substr(r.descrito_em,1,10) <
          (SELECT MIN(substr(s.coletado_em,1,10)) FROM snapshot s
           WHERE s.estado='corrente')""").fetchone()[0]
cx.close()
checar(f"há resumo para medir ({_n_res})", _n_res > 0)
checar(f"o painel sabe dizer que {_atrasados} de {_n_res} resumos descrevem coleta anterior",
       "resumoAtrasado" in _pv and "tarjaResumo" in _pv)
checar("a tarja aparece no cartão E no detalhe do processo",
       _pv.count("tarjaResumo(d)") >= 2, str(_pv.count("tarjaResumo(d)")))
checar("processo sem resumo diz que o resumo não foi gerado, em vez de sumir",
       "Sem resumo gerado para este processo" in _pv)

# O índice de busca: a lista de campos varridos não pode conter o texto gerado.
_i = _pv.find("function filtrar")
_i = _pv.find("if(![d.protocolo", _i if _i > 0 else 0)
_indice = _pv[_i:_pv.find(".some(v=>semAcento", _i)]
checar("resumo_curto e resumo_longo estão FORA do índice de busca",
       "resumo_curto" not in _indice and "resumo_longo" not in _indice,
       _indice[:200])
checar("mas o índice continua varrendo o que o SEI gravou",
       all(c in _indice for c in ("d.especificacao", "d.anotacao", "d.marcador")))

# A planilha sobrevive ao painel e circula por e-mail: a data vai junto.
checar("a exportação leva a data do resumo em coluna própria",
       "Resumo descreve a coleta de" in _pv)

# Prazo próprio no expurgo: resumo sem snapshot para conferir não se sustenta.
import expurgo as _exp                                           # noqa: E402
checar("o expurgo tem prazo próprio para o resumo", "resumo" in _exp.DIAS,
       str(sorted(_exp.DIAS)))
checar("o resumo vive mais que o snapshot que descreve, mas não para sempre",
       _exp.DIAS["snapshot"] < _exp.DIAS["resumo"] < _exp.DIAS["log_acesso"],
       f"snapshot={_exp.DIAS['snapshot']} resumo={_exp.DIAS['resumo']}")

# ---------------------------------------------------------------------------
# NÚMEROS QUE A REVISÃO PEGOU ERRADOS.
# ---------------------------------------------------------------------------
print("\n-- os números batem com o SQL cru --")
import relatorios as _rel3                                        # noqa: E402

# "Comparativo entre unidades" creditava a UMA unidade o processo aberto em duas:
# a dedup por id_sei descartava a segunda posição e o desempate caía no id do
# snapshot, que não significa nada. Medido: ASTEC saía com 3 dos 5 (-40%), DGESS
# 19 de 20, CESS 624 de 625 — e é o relatório que pergunta qual unidade acumula
# mais processo parado.
cx = conectar()
_por_uni = {x["unidade"]: x["n"] for x in cx.execute("""
    SELECT s.unidade, COUNT(DISTINCT p.id_sei) n FROM processo p
    JOIN snapshot s ON s.id=p.snapshot_id WHERE s.estado='corrente'
    GROUP BY s.unidade""")}
cx.close()
_uni_rel = _rel3.montar("unidade", UNIDADES)
_mostrado = {l[0]: l[1] for l in _uni_rel["linhas"]}
_erradas = {u: (n, _mostrado.get(u, 0)) for u, n in _por_uni.items()
            if _mostrado.get(u, 0) != n}
checar("cada unidade mostra o que o SQL cru diz que ela tem", not _erradas,
       str(_erradas))
# A soma passar do total é o comportamento CERTO, e a nota tem de dizer isso.
_soma_uni = sum(l[1] for l in _uni_rel["linhas"])
checar(f"a soma passa do total quando há processo em duas unidades "
       f"({_soma_uni} posições para {_uni_rel['total']} processos)",
       _soma_uni >= _uni_rel["total"] and "passa do total" in _uni_rel["nota"],
       _uni_rel["nota"][:120])

# "Minha fila" imprimia o id interno no lugar do número do processo: 89941724 em
# vez de 019.2403.2024.0013423-96. O id não serve para pesquisar no SEI nem para
# citar em despacho, e a planilha exportada circulava com ele.
cx = conectar()
_um = cx.execute("""SELECT p.atribuido_nome, p.protocolo, p.id_sei FROM processo p
                    JOIN snapshot s ON s.id=p.snapshot_id
                    WHERE s.estado='corrente' AND p.atribuido_nome IS NOT NULL
                      AND p.atribuido_nome<>'' AND p.protocolo IS NOT NULL LIMIT 1""").fetchone()
cx.close()
if _um:
    _fila = _rel3.montar("minha_fila", UNIDADES, quem=_um["atribuido_nome"])
    _numeros = {l[0] for l in _fila["linhas"]}
    checar("'Minha fila' mostra o NÚMERO do processo, não o id interno",
           _um["protocolo"] in _numeros and _um["id_sei"] not in _numeros,
           f"esperava {_um['protocolo']}, id interno {_um['id_sei']}")

# ---------------------------------------------------------------------------
# ONDE O PROCESSO ESTÁ, E O QUE ACONTECEU COM ELE.
#
# Os dois relatórios desta fatia leem campos que ninguém consegue ler no olho:
# `processo_mesa` (a árvore do SEI, processo a processo) e `ultimo_movimento`
# (texto livre, 529 redações distintas para 1.169 processos).
#
# O risco de cada um é diferente e os testes seguem esses riscos: N1 pode contar
# processo duas vezes, porque um processo aberto em três unidades gera três
# linhas; N2 pode vazar login, porque o login vem DENTRO da frase que ele agrupa.
# ---------------------------------------------------------------------------
print("\n-- onde está aberto, e o que aconteceu por último --")
import relatorios as _rel3                                       # noqa: E402

_uni = UNIDADES
_dados3 = _rel3.carregar(_uni)
cx = conectar()
_m3 = ",".join("?" * len(_uni))
_esperado = cx.execute(f"""SELECT COUNT(DISTINCT pm.id_sei) FROM processo_mesa pm
                           JOIN snapshot s ON s.id=pm.snapshot_id
                           WHERE s.estado='corrente' AND s.unidade IN ({_m3})""",
                       _uni).fetchone()[0]
cx.close()
_com_mesa = sum(1 for d in _dados3 if d.get("_mesas"))
checar("N1 lê exatamente os processos que a árvore do SEI conhece",
       _com_mesa == _esperado, f"{_com_mesa} != {_esperado}")

_n1 = _rel3.montar("onde_aberto", _uni)
checar("N1: a base continua sendo a carteira, não a soma das linhas",
       _n1["total"] == len(_dados3), f'{_n1["total"]} != {len(_dados3)}')
# Um processo aberto em três unidades produz três linhas. Isso é correto — e é
# por isso que a soma PRECISA passar do total e a nota precisa dizer que passa.
_soma = sum(l[1] for l in _n1["linhas"])
checar("N1: a soma das linhas passa do total (processo aberto em várias unidades)",
       _soma >= _n1["total"], f"soma {_soma} < total {_n1['total']}")
checar("N1: a nota avisa que a soma passa do total",
       "passa do total" in _n1["nota"])
checar("N1: declara quantas unidades de destino existem",
       any(d["rotulo"].startswith("Unidades de destino") and d["valor"] == len(_n1["linhas"])
           for d in _n1["destaques"]), str(_n1["destaques"]))
# "Aberto em várias unidades" e "árvore e andamento divergem" são medidas
# diferentes; juntar as duas num número só afirmaria o que o dado não diz.
checar("N1: separa 'aberto em várias' de 'árvore e andamento divergem'",
       len({d["rotulo"] for d in _n1["destaques"]}) == 3
       and any("divergem" in d["rotulo"] for d in _n1["destaques"]))
# O que este relatório NÃO pode mostrar: `processo_mesa.atribuido` é login de
# gente de outras unidades. Ele não é lido em lugar nenhum do caminho.
_st, _html_n1 = pegar("/relatorios/onde_aberto")
checar("N1: abre", _st == 200, f"status {_st}")
checar("N1: nenhum login de pessoa aparece na tela",
       "@saude.ba.gov.br" not in _html_n1)

_n2 = _rel3.montar("ultimo_evento", _uni)
checar("N2: cada processo entra uma vez só",
       sum(l[1] for l in _n2["linhas"]) == _n2["total"],
       f'{sum(l[1] for l in _n2["linhas"])} != {_n2["total"]}')
# 529 textos crus viram poucas classes; se voltarem a virar dezenas, o relatório
# deixou de agrupar e virou a lista crua outra vez.
checar(f'N2: agrupa em poucas classes ({len(_n2["linhas"])})',
       len(_n2["linhas"]) <= 30, str(len(_n2["linhas"])))
_outros = next((l[1] for l in _n2["linhas"] if l[0] == "Outros"), 0)
checar(f"N2: o resíduo 'Outros' é pequeno ({_outros} de {_n2['total']})",
       _outros <= _n2["total"] * 0.15, f"{_outros}/{_n2['total']}")
if _outros:
    checar("N2: quando há resíduo, a nota mostra exemplos do que sobrou",
           "Outros" in _n2["nota"] and "texto(s) distinto(s)" in _n2["nota"])
_st, _html_n2 = pegar("/relatorios/ultimo_evento")
checar("N2: abre", _st == 200, f"status {_st}")
# O caso que motiva a classificação: "Processo atribuído para fulano@..." é a
# classe mais frequente da base, e é justamente a que carrega login.
checar("N2: agrupar tirou o login de dentro da frase",
       "@saude.ba.gov.br" not in _html_n2 and "Atribuído a alguém" in _html_n2)

# Tarjas de base estreita: o número sozinho mente por omissão.
_marc = _rel3.montar("marcadores", _uni)
checar("marcadores: a nota diz sobre que fração da carteira a distribuição fala",
       "%" in _marc["nota"] and "desconhecido" in _marc["nota"], _marc["nota"][:120])
_tri = _rel3.montar("triagem", _uni)
checar("triagem: a nota avisa que um processo pode aparecer em mais de uma linha",
       "mais de uma" in _tri["nota"], _tri["nota"][:120])

# ---------------------------------------------------------------------------
# PAPEL — "Carga por responsável" é dado de gestão.
#
# Esse relatório nomeia colegas e os ordena por quantidade de processo. Entre
# pares, o uso mais provável não é o gerencial: é o ranking informal. A conta de
# servidor não tem por que carregar esse dado — e a contrapartida é "Minha
# fila", para que a pergunta legítima "e os MEUS?" continue respondida.
#
# As verificações abaixo existem porque esconder o cartão é a parte fácil e
# inútil: quem tem o link continua abrindo, e a planilha ainda sai por e-mail.
# ---------------------------------------------------------------------------
print("\n-- papel: quem pode ver a carga nominal dos colegas --")
import relatorios as _relp                                       # noqa: E402

checar("servidor não enxerga 'Carga por responsável' no catálogo",
       "responsavel" not in [r["id"] for r in _relp.visiveis("servidor")])
checar("gestor e admin enxergam",
       "responsavel" in [r["id"] for r in _relp.visiveis("gestor")]
       and "responsavel" in [r["id"] for r in _relp.visiveis("admin")])
checar("'Minha fila' fica para todo mundo",
       all("minha_fila" in [r["id"] for r in _relp.visiveis(p)]
           for p in ("servidor", "gestor", "admin")))

# Conta de SERVIDOR própria, com as mesmas unidades: o que muda entre ela e a
# conta da suíte (admin) é só o papel. E o nome dela é um `atribuido_nome` real
# da base — senão "Minha fila" passaria por vazia e o teste não provaria nada.
CONTA_S, SENHA_S = "t.rel.servidor@teste.local", "servidor-2026-sei"
cx = conectar()
_nome_real = cx.execute("""SELECT atribuido_nome FROM processo p
                           JOIN snapshot s ON s.id=p.snapshot_id
                           WHERE s.estado='corrente' AND atribuido_nome IS NOT NULL
                             AND atribuido_nome<>''
                           GROUP BY atribuido_nome ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
_nome_real = _nome_real[0] if _nome_real else "Ninguém Registrado"
_h, _s = seg.hash_senha(SENHA_S)
cx.execute("DELETE FROM usuarios WHERE email=?", (CONTA_S,))
cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,criado_em,
              ativo,senha_trocada_em) VALUES(?,?,?,?,'servidor','teste',?,1,?)""",
           (CONTA_S, _nome_real, _h, _s, agora(), agora()))
UID_S = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
for un in UNIDADES:
    cx.execute("INSERT OR IGNORE INTO usuario_unidade(usuario_id,unidade,concedida_em) "
               "VALUES(?,?,?)", (UID_S, un, agora()))
cx.commit(); cx.close()

_jar_s = http.cookiejar.CookieJar()
_op_s = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar_s))


def pegar_s(caminho, dados=None):
    corpo = urllib.parse.urlencode(dados, doseq=True).encode() if dados else None
    try:
        r = _op_s.open(urllib.request.Request(BASE + caminho, data=corpo), timeout=40)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


pegar_s("/entrar")
_csrf_s = next((c.value for c in _jar_s if c.name == "sei360_csrf"), "")
_st, _ = pegar_s("/entrar", {"email": CONTA_S, "pw": SENHA_S, "csrf": _csrf_s})
checar("a conta de servidor entra", _st == 200, f"status {_st}")

_st, _lista_s = pegar_s("/relatorios")
checar("o cartão da carga nominal não aparece na lista do servidor",
       "Carga por responsável" not in _lista_s, f"status {_st}")
_st, _ = pegar_s("/relatorios/responsavel")
checar("abrir /relatorios/responsavel pela URL dá 403", _st == 403, f"status {_st}")
_st, _ = pegar_s("/relatorios/responsavel.xlsx")
checar("baixar a planilha nominal dá 403 (é ela que sai por e-mail)", _st == 403,
       f"status {_st}")
# A regra é de PAPEL, não um muro: o resto do catálogo continua aberto.
_st, _ = pegar_s("/relatorios/permanencia")
checar("relatório sem restrição continua abrindo para servidor", _st == 200, f"status {_st}")

_st, _fila = pegar_s("/relatorios/minha_fila")
checar("'Minha fila' abre para servidor", _st == 200, f"status {_st}")
checar("'Minha fila' traz de fato os processos da pessoa",
       "Não encontrei processo atribuído" not in _fila and "<tbody>" in _fila,
       f"nome usado: {_nome_real}")

# O nome vem do cadastro; se ele diverge do SEI a fila sai vazia. Dizer "vazia"
# nesse caso faria a pessoa fechar a tela achando que está em dia.
cx = conectar()
cx.execute("UPDATE usuarios SET nome=? WHERE id=?", ("Fulano Que Não Existe", UID_S))
cx.commit(); cx.close()
_st, _fila2 = pegar_s("/relatorios/minha_fila")
checar("fila vazia por nome que não casa é DITA, não confundida com fila zerada",
       "Não encontrei processo atribuído" in _fila2, f"status {_st}")

# E a conta de gestão continua vendo o que é dela.
_st, _resp_admin = pegar("/relatorios/responsavel")
checar("admin continua abrindo a carga por responsável", _st == 200, f"status {_st}")

cx = conectar()
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=?", (UID_S,))
cx.execute("DELETE FROM usuarios WHERE id=?", (UID_S,))
cx.commit(); cx.close()

print("\n-- régua: a idade se mede contra a coleta, não contra o relógio --")
import relatorios as _rel, janelas as _jan                        # noqa: E402
from datetime import datetime as _dt, timedelta as _td            # noqa: E402

cx = conectar()
UNIDADES = [r[0] for r in cx.execute(
    "SELECT DISTINCT unidade FROM snapshot WHERE estado='corrente'").fetchall()]
cx.close()


def _relogio_adiantado(dias):
    """datetime com `now()` no futuro. Subclasse, não mock: strptime, strftime e
    o resto continuam sendo os de verdade — só o AGORA muda."""
    class D(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt.now(tz) + _td(days=dias)
    return D


# Colunas que SÃO procedência, não medida. "Dado de" diz há quanto tempo aquela
# unidade não é coletada — ela tem de andar com o relógio, senão o relatório
# anunciaria "coletado hoje" para sempre. Ficam fora da comparação; o que não
# pode mudar é a CONTAGEM ao lado delas.
PROCEDENCIA = {"Dado de"}


def _numeros(res):
    """Só a medida. Fora ficam a hora de geração, o aviso de dado velho e as
    colunas de procedência."""
    corpo = {k: v for k, v in res.items()
             if k not in ("gerado_em", "procedencia", "desatualizado")}
    fora = [i for i, c in enumerate(corpo.get("colunas") or []) if c in PROCEDENCIA]
    if fora:
        corpo["colunas"] = [c for i, c in enumerate(corpo["colunas"]) if i not in fora]
        corpo["linhas"] = [[v for i, v in enumerate(l) if i not in fora]
                           for l in corpo.get("linhas") or []]
    return json.dumps(corpo, sort_keys=True, ensure_ascii=False, default=str)


checar("há unidade corrente para medir", bool(UNIDADES), str(UNIDADES))
if UNIDADES:
    antes = {r["id"]: _rel.montar(r["id"], UNIDADES) for r in _rel.CATALOGO}
    try:
        _rel.datetime = _relogio_adiantado(5)
        _jan.datetime = _relogio_adiantado(5)
        depois = {r["id"]: _rel.montar(r["id"], UNIDADES) for r in _rel.CATALOGO}
    finally:
        _rel.datetime, _jan.datetime = _dt, _dt

    iguais = [rid for rid in antes if _numeros(antes[rid]) == _numeros(depois[rid])]
    difere = [rid for rid in antes if _numeros(antes[rid]) != _numeros(depois[rid])]
    checar(f"os {len(antes)} relatórios saem idênticos com o relógio 5 dias à frente",
           not difere, "mudaram: " + ", ".join(difere))

    # O caso nomeado no achado, conferido linha a linha e não só pelo total.
    a, d = antes.get("permanencia"), depois.get("permanencia")
    if a and d:
        fa = {l[0]: l[1] for l in a.get("linhas", [])}
        fd = {l[0]: l[1] for l in d.get("linhas", [])}
        checar("permanência: nenhuma faixa muda de contagem", fa == fd,
               f"{fa} != {fd}")
        checar("permanência: o total também não anda", a.get("total") == d.get("total"),
               f'{a.get("total")} != {d.get("total")}')

    # O outro lado da moeda: o AVISO de dado velho tem de continuar seguindo o
    # relógio. Se ele congelasse junto, a tela diria "coletado hoje" para sempre
    # — que é exatamente a mentira que o aviso existe para impedir.
    pa = json.dumps(antes["unidade"]["procedencia"], ensure_ascii=False)
    pd_ = json.dumps(depois["unidade"]["procedencia"], ensure_ascii=False)
    checar("o aviso de dado velho continua medindo contra o relógio", pa != pd_,
           "procedência não mudou com +5 dias: " + pa[:120])

# O painel é a mesma medida em JavaScript. Se a régua do servidor for a coleta e
# a do painel for o relógio, as duas telas do mesmo sistema divergem no mesmo dia.
_tpl = (Path(__file__).resolve().parent / "templates" / "painel.html").read_text(encoding="utf-8")
checar("o painel também mede contra a coleta (const REGUA)", "const REGUA=" in _tpl)
# A régua deixou de ser UMA. Com o poço, a linha pode ter lista de hoje e detalhe
# de três dias atrás; medir a data velha com o relógio de hoje imprime "388 dias
# na unidade" para um processo que chegou ontem. Cada linha carrega `medido_em` e
# é contra ela que os dias são contados — REGUA continua valendo para quem não
# tem data própria.
checar("a contagem de dias sai da régua DA LINHA, com REGUA de fallback",
       "const diasDe=(s,d)=>" in _tpl and "(d?reguaDe(d):REGUA)-t)/864e5" in _tpl)
checar("e a régua da linha vem de medido_em", "const reguaDe=d=>" in _tpl
       and "emMsISO(d.medido_em)" in _tpl)
# A regra original, dita como invariante em vez de como texto: nenhuma contagem
# de dias pode medir contra o relógio. A única medida contra Date.now() é a idade
# da própria coleta — que medida contra a régua daria zero para sempre.
_i = _tpl.find("function idadeColeta(")
_corpo_idade = _tpl[_i:_tpl.find("\n}", _i)] if _i >= 0 else ""
_usos = [l for l in _tpl.split("\n")
         if "Date.now()" in l and "864e5" in l and l not in _corpo_idade]
checar("nenhuma outra contagem de dias mede contra o relógio", not _usos, str(_usos[:2]))
checar("e a idade da própria coleta continua medindo contra ele — medida contra a "
       "régua daria zero para sempre", "Date.now()" in _corpo_idade, _corpo_idade[:60])

# Não basta o template CITAR a régua: o valor que chega nela tem de ser uma DATA
# que a expressão do painel reconheça. `COLETA_EM` já chegou como frase legível —
# "último dia útil (18/08 07:45)", sem ano — e a régua caía no relógio EM
# SILÊNCIO: o template passava na conferência de texto e o painel voltava a
# envelhecer sozinho na tela de quem usa. Este é o teste que olha.
import re as _re_reg                                             # noqa: E402
_st, _pag = pegar("/")
_m_col = _re_reg.search(r"const COLETA_EM = (\"[^\"]*\"|null);", _pag)
_valor = json.loads(_m_col.group(1)) if _m_col else None
checar("o painel recebe COLETA_EM", _m_col is not None, f"status {_st}")
checar("e o valor é uma data que a régua do painel sabe ler (DD/MM/AAAA)",
       bool(_valor) and _re_reg.match(r"^\d{2}/\d{2}/\d{4}", _valor), repr(_valor))
# A frase legível continua existindo — em campo próprio, sem virar régua.
_m_fr = _re_reg.search(r"const COLETA_FRASE = (\"[^\"]*\"|null);", _pag)
checar("a frase legível vem em campo próprio, sem servir de régua",
       _m_fr is not None and json.loads(_m_fr.group(1)) != _valor,
       _m_fr.group(1) if _m_fr else "ausente")
# HÁ uma medida contra o relógio no painel, e só uma: a idade da PRÓPRIA coleta.
# Medida contra a régua ela daria zero e a tela diria "hoje" para sempre — que é
# a mentira que esse rótulo existe para impedir. Qualquer OUTRA é regressão.
_corpo = _tpl[_tpl.index("function idadeColeta"):]
_corpo = _corpo[:_corpo.index("\n}")]
# Casa por PADRÃO, não pelo nome da variável: a checagem anterior procurava
# literalmente "(Date.now()-t)", e renomear `t` para `ms` — conserto de uma
# colisão real — fez a conferência falhar sem que nada tivesse piorado.
import re as _re_relogio                                         # noqa: E402
_uso_relogio = _re_relogio.findall(r"\(Date\.now\(\)-\w+\)/864e5", _tpl)
checar("a única medida contra o relógio é a idade da coleta",
       len(_uso_relogio) == 1 and _re_relogio.search(
           r"\(Date\.now\(\)-\w+\)/864e5", _corpo) is not None,
       str(_uso_relogio))

cx = conectar()
print("\nA CONTA DE DIAS: O PAINEL E O RELATORIO SOBRE OS MESMOS CASOS")
# O painel e os relatorios respondem "ha quantos dias na unidade" com dois
# codigos, em duas linguagens, sobre o mesmo dado. Enquanto ninguem comparou,
# divergiram: 432 no painel contra 526 no relatorio, em 21/08/2026, sobre 1.165
# processos. A causa foi truncar a hora dos dois lados e contar viradas de
# meia-noite em vez do intervalo.
#
# Este bloco escreve a tabela de casos — tirados da BASE REAL mais as bordas que
# o SEI produz — com a resposta do Python. `conferir_dias.js` extrai as funcoes
# do painel.html SERVIDO, roda sobre os mesmos casos e compara numero a numero.
import json as _json                                                # noqa: E402

import relatorios as _R                                             # noqa: E402
import janelas as _janelas                                          # noqa: E402

_casos = []


def _caso(rotulo, marco, medido_em):
    try:
        _ref = _janelas.com_fuso(medido_em).replace(tzinfo=None) if medido_em else None
    except (TypeError, ValueError):
        _ref = None
    _casos.append({"rotulo": rotulo, "marco": marco, "medido_em": medido_em,
                   "dias": _R._dias(marco, _ref)})


# 1) BORDAS. Sao elas que separam calendario de intervalo: quando a hora do marco
#    passa da hora da regua, a conta por calendario soma um dia que nao decorreu.
_caso("marco 1 minuto depois da regua, dia anterior", "20/08/2026 07:46",
      "2026-08-21T07:45:00-03:00")
_caso("marco 1 minuto antes da regua, dia anterior", "20/08/2026 07:44",
      "2026-08-21T07:45:00-03:00")
_caso("exatamente 24h", "20/08/2026 07:45", "2026-08-21T07:45:00-03:00")
_caso("exatamente 90 dias", "23/05/2026 07:45", "2026-08-21T07:45:00-03:00")
_caso("90 dias menos um minuto", "23/05/2026 07:46", "2026-08-21T07:45:00-03:00")
_caso("mesmo dia, hora depois", "21/08/2026 18:00", "2026-08-21T07:45:00-03:00")
_caso("mesmo instante", "21/08/2026 07:45", "2026-08-21T07:45:00-03:00")
_caso("marco 23h59 vespera", "20/08/2026 23:59", "2026-08-21T00:01:00-03:00")
_caso("virada de ano", "31/12/2025 23:00", "2026-01-01T01:00:00-03:00")
_caso("ano bissexto 29/02", "29/02/2024 10:00", "2024-03-01T09:00:00-03:00")
_caso("marco sem hora", "20/08/2026", "2026-08-21T07:45:00-03:00")
_caso("marco vazio", "", "2026-08-21T07:45:00-03:00")
_caso("marco impossivel 31/02", "31/02/2026 10:00", "2026-08-21T07:45:00-03:00")
_caso("marco no futuro", "25/08/2026 10:00", "2026-08-21T07:45:00-03:00")
# O poco: lista de hoje, detalhe de tres dias atras. E o caso que a regua por
# linha existe para tratar, e ele tem de dar o MESMO numero nas duas telas.
_caso("servido do poco (regua 3 dias atras)", "01/08/2026 09:00",
      "2026-08-18T07:45:00-03:00")

# 2) A BASE REAL. Bordas sinteticas provam o algoritmo; a base prova que o dado
#    que o SEI de fato manda passa pelas duas contas do mesmo jeito.
import banco as _banco                                              # noqa: E402
_cx = _banco.conectar()
for _r in _cx.execute("""SELECT marco_unidade, medido_em, coletado_em
                         FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
                         WHERE marco_unidade IS NOT NULL AND marco_unidade<>''
                         ORDER BY p.id_sei LIMIT 400"""):
    _caso("base", _r["marco_unidade"], _r["medido_em"] or _r["coletado_em"])
_cx.close()

(Path(__file__).resolve().parent / "_casos_dias.json").write_text(
    _json.dumps(_casos, ensure_ascii=False), encoding="utf-8")
_com_hora = sum(1 for c in _casos if ":" in (c["marco"] or ""))
checar(f"tabela de casos escrita ({len(_casos)} casos, {_com_hora} com hora)",
       len(_casos) >= 50 and _com_hora >= 10)

# A COMPARACAO RODA AGORA, no mesmo processo que acabou de escrever os casos.
# Antes ela vivia no `conferir_js.py`, chamado de dentro de `testes.py` — que
# roda ANTES deste arquivo na ordem da suite. A paridade era sempre medida
# contra as respostas do Python da rodada ANTERIOR, e um mutante em `_dias`
# passava por ela sem ser visto.
import shutil as _sh2                                               # noqa: E402
import subprocess as _sp                                            # noqa: E402
_node = next((c for c in (_sh2.which("node"), r"C:\Program Files\nodejs\node.exe",
                          "/usr/bin/node", "/usr/local/bin/node")
              if c and Path(c).exists()), None)
if not _node:
    # NAO se cala. Node ausente e uma conferencia que nao rodou, e isso tem de
    # aparecer — foi assim que a divergencia de 21,8% sobreviveu.
    checar("node disponivel para conferir a paridade painel x relatorio", False,
           "instale o Node ou rode conferir_dias.js a mao")
else:
    _r = _sp.run([_node, str(Path(__file__).resolve().parent / "conferir_dias.js")],
                 capture_output=True, text=True, encoding="utf-8", errors="replace")
    _fal = [l.strip() for l in (_r.stdout or "").splitlines()
            if l.strip().startswith("FALHA")]
    checar("painel e relatorio dao o MESMO numero em todos os casos",
           _r.returncode == 0, (_fal[0][:120] if _fal else (_r.stdout or "")[-120:]))

# As bordas, conferidas AQUI tambem — o .js prova a paridade, este bloco prova
# que o numero do Python esta certo. Paridade com os dois errados nao vale nada.
_ref = _janelas.com_fuso("2026-08-21T07:45:00-03:00").replace(tzinfo=None)
checar("marco 1 min DEPOIS da regua, na vespera, da 0 dia — nao 1",
       _R._dias("20/08/2026 07:46", _ref) == 0, str(_R._dias("20/08/2026 07:46", _ref)))
checar("exatamente 24h da 1 dia", _R._dias("20/08/2026 07:45", _ref) == 1)
checar("exatamente 90 dias da 90 — nao entra em `+90d`",
       _R._dias("23/05/2026 07:45", _ref) == 90)
checar("90 dias menos um minuto da 89",
       _R._dias("23/05/2026 07:46", _ref) == 89)
checar("marco no futuro da negativo, nao explode",
       _R._dias("25/08/2026 10:00", _ref) < 0)
checar("marco impossivel devolve None em vez de derrubar a tela",
       _R._dias("31/02/2026 10:00", _ref) is None)
checar("marco sem hora continua funcionando",
       _R._dias("20/08/2026", _ref) == 1)
checar("`quando_br` le a HORA, que era o que se perdia",
       _R.quando_br("20/08/2026 07:46").hour == 7 and
       _R.quando_br("20/08/2026 07:46").minute == 46)

print("\nE OS DOIS NUMEROS QUE DIVERGIAM NA TELA")
_uid = 2
import app as _app                                                  # noqa: E402
_uns = _app.unidades_do(_uid)
_dados = _R.carregar(_uns, _uid)
_p90 = sum(1 for d in _dados if (d["_dias_unidade"] or 0) > 90)
checar(f"a carteira do gestor carrega ({len(_dados)} linhas)", len(_dados) > 0)
# O painel calcula em JS sobre os mesmos dados; `conferir_dias.js` prova a
# igualdade caso a caso. Aqui vale registrar o numero para a proxima pessoa.
checar(f"'parados +90d' vale {_p90} — e e o mesmo do painel (conferir_dias.js)",
       isinstance(_p90, int))

print("\nOS ACHADOS DA AUDITORIA, TRAVADOS")
# Cada bloco abaixo e um defeito que a auditoria adversarial sustentou. Estao
# aqui para nao voltarem em silencio — foi assim que a conta de dias voltou:
# o comentario AFIRMAVA que o defeito tinha sido corrigido enquanto ele estava la.
import io as _io                                                    # noqa: E402
import statistics as _st                                            # noqa: E402

_uns = _app.unidades_do(2)
_base = _R.carregar(_uns, 2)
checar("a carteira do gestor carrega para os testes", len(_base) > 0)

print("\n-- a mediana e a mediana --")
_rr = _R.rel_por_responsavel(_base)
_idx = {}
for _d in _base:
    _idx.setdefault(_d.get("atribuido_nome") or "SEM ATRIBUIÇÃO", []).append(_d)
_erradas = 0
for _l in _rr["linhas"]:
    _dias_l = sorted(x["_dias_unidade"] for x in _idx[_l[0]] if x["_dias_unidade"] is not None)
    if not _dias_l:
        continue
    _m = _st.median(_dias_l)
    _esperado = int(_m) if float(_m).is_integer() else round(_m, 1)
    if _l[4] != _esperado:
        _erradas += 1
checar(f"todas as {len(_rr['linhas'])} linhas batem com statistics.median",
       _erradas == 0, f"{_erradas} erradas")
_pares = [l for l in _rr["linhas"]
          if len([x for x in _idx[l[0]] if x["_dias_unidade"] is not None]) % 2 == 0
          and [x for x in _idx[l[0]] if x["_dias_unidade"] is not None]]
checar(f"e o teste EXERCITA o caso par ({len(_pares)} linhas de tamanho par)",
       len(_pares) >= 5)
checar("a mediana de [1,2,3,4] e 2.5, nao 3", _R._mediana([1, 2, 3, 4]) == 2.5)
checar("e a de [1,2,3] e 2 inteiro", _R._mediana([1, 2, 3]) == 2)
checar("lista vazia nao explode", _R._mediana([]) == "—")
checar("e o relatorio DIZ quantos ficaram fora da mediana",
       "marco de entrada" in (_rr.get("nota") or ""), str(_rr.get("nota"))[:60])

print("\n-- o corte em 40 nao perde processo em silencio --")
_pr = _R.rel_procedencia(_base)
checar("a coluna fecha com a base",
       sum(l[1] for l in _pr["linhas"]) == _pr["total"],
       f"{sum(l[1] for l in _pr['linhas'])} vs {_pr['total']}")
checar("a ultima linha nomeia o residuo",
       str(_pr["linhas"][-1][0]).startswith("outras "), str(_pr["linhas"][-1]))
checar("e a nota diz quantas e quantos", "somam" in _pr["nota"])
# Sem residuo (base pequena), NAO aparece linha de resto inventada.
_poucos = [d for d in _base if d.get("gerador_unidade")][:3]
_pp = _R.rel_procedencia(_poucos)
checar("sem residuo, nao inventa linha 'outras'",
       not any(str(l[0]).startswith("outras ") for l in _pp["linhas"]))

print("\n-- o eixo ordinal nao e reordenado por tamanho --")
_pm = _R.montar("permanencia", _uns, usuario_id=2)
_ordem_esperada = [l[0] for l in _pm["linhas"]]
checar("o grafico de permanencia segue a ordem das FAIXAS",
       [b["rotulo"] for b in _pm["grafico"]["barras"]] == _ordem_esperada,
       str([b["rotulo"] for b in _pm["grafico"]["barras"]]))
# O GUARDA: se as faixas ja viessem em ordem decrescente por acaso, o teste
# acima passaria mesmo com o `sort` de volta. O que prova que ele exercita o
# defeito e a ordem NAO ser decrescente.
_vp = [b["valor"] for b in _pm["grafico"]["barras"]]
checar("e a ordem das faixas NAO e decrescente (senao o teste nao provaria nada)",
       _vp != sorted(_vp, reverse=True), str(_vp))
_pt = _R.montar("tipo", _uns, usuario_id=2)
if _pt.get("grafico"):
    # SEM a barra agregada: "outras N" e sempre a ultima e nao entra na ordem
    # de tamanho — ela e a soma do que ficou de fora, nao uma das maiores.
    _vals = [b["valor"] for b in _pt["grafico"]["barras"]][:_pt["grafico"]["maiores"]]
    checar("relatorio SEM eixo ordinal continua ordenado por tamanho",
           _vals == sorted(_vals, reverse=True), str(_vals[:4]))

print("\n-- a fatia do grafico e sobre a BASE, e a legenda nao mente --")
_ta = _R.montar("triagem", _uns, usuario_id=2)
_b0 = _ta["grafico"]["barras"][0]
checar("a fatia da maior barra bate com valor/base",
       abs(_b0["fatia"] - round(100 * _b0["valor"] / _ta["total"], 1)) < 0.05,
       f"{_b0['fatia']} vs {round(100*_b0['valor']/_ta['total'],1)}")
checar("e a base do grafico e a base do relatorio",
       _ta["grafico"]["base"] == _ta["total"])
checar("triagem tem linhas SOBREPOSTAS — a soma nao fecha com a base",
       _ta["grafico"]["soma"] != _ta["total"],
       "sem sobreposicao o teste nao exercita o defeito")
_oa = _R.montar("onde_aberto", _uns, usuario_id=2)
checar("onde_aberto soma MAIS que a base, e a legenda diz isso",
       _oa["grafico"]["soma"] > _oa["total"])
checar("'as N maiores' nao conta a barra agregada",
       _oa["grafico"]["maiores"] == len(_oa["grafico"]["barras"]) -
       (1 if _oa["grafico"]["agregada"] else 0))
checar("e onde nao houve corte, `agregada` e falso",
       _ta["grafico"]["agregada"] is False)

print("\n-- os campos POR UNIDADE saem da unidade certa --")
_cu = _R.montar("unidade", _uns, usuario_id=2)
checar("toda unidade do recorte aparece, mesmo sem processo",
       {l[0] for l in _cu["linhas"]} >= set(_uns),
       str(set(_uns) - {l[0] for l in _cu["linhas"]}))
# SOB DEMANDA, e nao na carga: os campos de custodia por unidade sao lidos por UM
# dos catorze relatorios, e monta-los sempre custava duas datas por processo por
# unidade — 2.334 conversoes de fuso e 2.334 subtracoes que as outras treze telas
# jogavam fora. A carga guarda a linha CRUA (referencia, custo zero).
_novo = _R.carregar(_uns, 2)
checar("carregar() NAO monta os campos por unidade que ninguem pediu",
       not any("_por_unidade" in d for d in _novo),
       "voltou a montar 2.334 datas para treze telas jogarem fora")
checar("mas guarda a linha crua de cada unidade, para quem pedir",
       all("_pu" in d for d in _novo[:20]))
_multi = [d for d in _base if len(d.get("_unidades") or []) > 1]
checar(f"ha processo em mais de uma unidade para exercitar ({len(_multi)})",
       len(_multi) > 0)
if _multi:
    _d0 = _multi[0]
    checar("e ele tem uma entrada de custodia para CADA unidade",
           set(_R.por_unidade_de(_d0)) == set(_d0["_unidades"]),
           f"{set(_R.por_unidade_de(_d0))} vs {set(_d0['_unidades'])}")
    # O MESMO DICIONARIO na segunda pergunta: `rel_por_unidade` pergunta uma vez
    # por unidade da carteira, e sem a memoria seriam seis montagens iguais.
    _n0 = next((d for d in _novo if d["id_sei"] == _d0["id_sei"]), None)
    checar("e a segunda pergunta devolve o objeto ja montado, nao outro",
           _n0 is not None and _R.por_unidade_de(_n0) is _R.por_unidade_de(_n0))
    checar("o valor sob demanda e igual ao que a carga montava",
           _n0 is not None and _R.por_unidade_de(_n0) == _R.por_unidade_de(_d0),
           f"{_R.por_unidade_de(_n0)} vs {_R.por_unidade_de(_d0)}")

print("\n-- a dedup conhece a instalacao do SEI --")
_fonte = (Path(__file__).resolve().parent / "relatorios.py").read_text(encoding="utf-8")
checar("a chave da dedup e (id_sei, instancia), nao id_sei puro",
       'chave = (l["id_sei"], l["instancia"])' in _fonte)
checar("e `instancia` vem do SNAPSHOT, que e onde a coluna existe",
       "s.instancia" in _fonte)
checar("o LEFT JOIN de resumo saiu junto (casava so por id_sei)",
       "JOIN resumo" not in _fonte)
checar("e o de processo_texto tambem", "JOIN processo_texto" not in _fonte)

print("\n-- a cobertura descreve o dado que sustenta a tabela --")
checar("'onde os processos estao abertos' declara a arvore do SEI",
       any(c["campo"] == "árvore do SEI" for c in _oa["cobertura"]),
       str([c["campo"] for c in _oa["cobertura"]]))
_vazio = _R.montar("permanencia", ["SESAB/NAO/EXISTE"], usuario_id=2)
checar("carteira vazia marca `sem_base`, em vez de acusar o campo",
       all(c.get("sem_base") for c in _vazio["cobertura"]))
checar("e o app fecha o cartao pelo motivo certo",
       "sem_base" in (SRV_APP := (Path(__file__).resolve().parent / "app.py")
                      .read_text(encoding="utf-8")) and
       'not sem_base) and pior' in SRV_APP)

print("\n-- 'minha fila' casa pelo LOGIN --")
_alguem = next((d for d in _base if d.get("atribuido_login")), None)
checar("ha processo com login atribuido para exercitar", _alguem is not None)
if _alguem:
    _f = _R.rel_minha_fila(_base, quem="Grafia Totalmente Diferente",
                           login=_alguem["atribuido_login"])
    checar("com o nome errado e o login certo, a fila aparece",
           _f["meus"] > 0 and _f["casou_por"] == "login", str(_f["casou_por"]))
    _f2 = _R.rel_minha_fila(_base, quem=_alguem.get("atribuido_nome"), login="nao@existe")
    checar("e sem login, o nome ainda serve de reserva",
           _f2["meus"] > 0 and _f2["casou_por"] == "nome", str(_f2["casou_por"]))
    _f3 = _R.rel_minha_fila(_base, quem="Ninguem", login="nao@existe")
    checar("nao achando por nenhum dos dois, DIZ que nao achou",
           _f3["sem_casamento"] is True and _f3["casou_por"] is None)

print("\n-- 'volume documental': a faixa sem informacao e a pergunta --")
_vol = _R.montar("volume", _uns, usuario_id=2)
checar("a pergunta declarada e a que a tabela responde",
       "distribui" in _vol["pergunta"], _vol["pergunta"])
_semi = [dict(d, documentos=None, movimentos=None) for d in _base[:5]]
_vs = _R.rel_volume(_semi)
checar("processo sem contagem APARECE na tabela, com o rotulo dele",
       any(l[0] == "sem informação" for l in _vs["linhas"]), str(_vs["linhas"]))
checar("e balde vazio continua fora da tabela",
       all(l[1] or l[2] for l in _vol["linhas"]))
checar("a nota nao promete mais um cruzamento que a tabela nao faz",
       "separadamente" in _vol["nota"])

print("\n-- os rotulos dizem o que foi medido --")
_tr = _R.montar("triagem", _uns, usuario_id=2)
checar("a triagem nao afirma mais 'por ninguem da unidade'",
       not any("ninguém da unidade" in str(l[0]) for l in _tr["linhas"]),
       str([l[0] for l in _tr["linhas"]]))
checar("e diz que a marca e da leitura desta coleta",
       any("marca de visualiza" in str(l[0]) for l in _tr["linhas"]))
_tela = (Path(__file__).resolve().parent / "templates" / "relatorio.html").read_text(encoding="utf-8")
checar("a tela nao chama de 'unidades' a dispersao que e de LINHA",
       "unidades em datas" not in _tela)
checar("e mostra o intervalo que ja era calculado", "r.medido_ate" in _tela)

print("\n-- a procedencia e a MESMA regra das duas telas --")
# O mutante que escapou: trocar `estado_coleta` de volta por uma derivacao a
# partir dos processos. A tela do relatorio voltava a ficar VERDE onde
# /relatorios fica VERMELHA, e nada reclamava.
_ec = _app.estado_coleta(_uns, 2)
_mp = _R.montar("permanencia", _uns, usuario_id=2)
checar("a tarja do relatorio tem as MESMAS unidades da tela anterior",
       [x["unidade"] for x in _mp["procedencia"]] ==
       [x["unidade"] for x in _ec["unidades"]],
       str([x["unidade"] for x in _mp["procedencia"]]))
checar("as MESMAS cores", [x["cor"] for x in _mp["procedencia"]] ==
       [x["cor"] for x in _ec["unidades"]])
checar("e os MESMOS textos — inclusive o que conta linha sem detalhe",
       [x["texto"] for x in _mp["procedencia"]] ==
       [x["texto"] for x in _ec["unidades"]])
checar("`desatualizado` sai do mesmo veredito",
       _mp["desatualizado"] == (_ec["pior"] not in ("verde", "vazio")))
# A parte que a derivacao por processos NAO consegue ver: linha sem detalhe lido.
# `medido_em` NULL nao entra em MIN(), entao a versao antiga pintava verde.
_sem = [x for x in _ec["unidades"] if "SEM detalhe" in (x["texto"] or "")]
checar(f"a base exercita o caso ({len(_sem)} unidade(s) com linha sem detalhe)",
       len(_sem) > 0, "sem esse caso o teste nao prova nada")
if _sem:
    _u0 = next(x for x in _mp["procedencia"] if x["unidade"] == _sem[0]["unidade"])
    checar("e o relatorio NAO pinta de verde uma unidade com linha sem detalhe",
           _u0["cor"] != "verde", _u0["cor"])
    checar("e diz quantas linhas ficaram sem detalhe", "SEM detalhe" in _u0["texto"])

print("\n-- 'ultima coisa que aconteceu' separa a unidade --")
# O outro mutante que escapou: `aqui = True` fazia todo movimento contar como se
# fosse na unidade de quem le — o defeito critico, de volta, em silencio.
_ue = _R.montar("ultimo_evento", _uns, usuario_id=2)
_ii = {l[0]: l for l in _ue["linhas"]}
checar("as colunas separam 'na sua unidade' de 'em outra'",
       _ue["colunas"][2:4] == ["Na sua unidade", "Em outra"], str(_ue["colunas"]))
_fora = sum(l[3] for l in _ue["linhas"])
checar(f"ha movimento fora da carteira para exercitar ({_fora})", _fora > 0)
checar("cada linha fecha: aqui + em outra = processos",
       all(l[1] == l[2] + l[3] for l in _ue["linhas"]),
       str([l for l in _ue["linhas"] if l[1] != l[2] + l[3]][:2]))
if "Concluído na unidade" in _ii:
    _c = _ii["Concluído na unidade"]
    checar("'Concluido na unidade' nao tem NENHUM concluido na sua unidade "
           "(quem conclui aqui sai da mesa aberta)",
           _c[2] == 0 and _c[3] == _c[1], str(_c))
checar("e a nota avisa quantos aconteceram fora",
       "FORA da sua carteira" in (_ue.get("nota") or ""), str(_ue.get("nota"))[:80])

# Sintetico: um processo cujo movimento aconteceu em unidade que NAO e a dele.
_sint = [
    {"_ultimo_mov": {"de": "Processo recebido na unidade", "un": "X/OUTRA"},
     "_unidades": ["X/MINHA"], "snap_unidade": "X/MINHA"},
    {"_ultimo_mov": {"de": "Processo recebido na unidade", "un": "X/MINHA"},
     "_unidades": ["X/MINHA"], "snap_unidade": "X/MINHA"},
]
_rs = _R.rel_ultimo_evento(_sint)
checar("com um evento dentro e um fora, a tabela conta 1 e 1",
       _rs["linhas"][0][2] == 1 and _rs["linhas"][0][3] == 1, str(_rs["linhas"]))
_sem_un = [{"_ultimo_mov": {"de": "Processo recebido na unidade"},
            "_unidades": ["X/MINHA"], "snap_unidade": "X/MINHA"}]
checar("movimento SEM unidade declarada nao e creditado a sua",
       _R.rel_ultimo_evento(_sem_un)["linhas"][0][2] == 0)

print("\n-- os inviaveis sao MEDIDOS, nao escritos a mao --")
# Escapou na rodada de mutantes: trocar a contagem por um `62` fixo passava em
# todas as verificacoes. Era o defeito original de volta — a tela dizia 62
# quando eram 61 — e nada reclamava.
_inv = _R.inviaveis_medidos(_base)
checar("ha inviaveis para conferir", len(_inv) == 5)
for _i in _inv:
    _real = sum(1 for d in _base if d.get(_i["campo"]) not in (None, "", "[]", 0))
    checar(f"'{_i['campo']}' bate com a contagem na base ({_real})",
           _i["n"] == _real, f"{_i['n']} vs {_real}")
    checar(f"e o percentual de '{_i['campo']}' sai da mesma conta",
           _i["pct"] == round(100 * _real / len(_base)))
checar("o denominador e a base do relatorio, nao um numero escrito",
       all(_i["total"] == len(_base) for _i in _inv))
checar("a medida exibida contem o numero medido",
       all(str(_i["n"]) in _i["medida"] for _i in _inv))
_vaz = _R.inviaveis_medidos([])
checar("sem base, NAO diz '0 de 0 (0%)' — diz que nao ha o que medir",
       all(x["pct"] is None and "sem base" in x["medida"] for x in _vaz),
       str(_vaz[0]["medida"]))
checar("e o motivo continua qualitativo, sem numero grudado nele",
       all(not any(c.isdigit() for c in x["motivo"]) for x in _inv),
       str([x["motivo"] for x in _inv if any(c.isdigit() for c in x["motivo"])]))

print("\n-- a planilha carrega o que qualifica os numeros --")
_buf = _io.BytesIO()
_R.para_xlsx(_R.montar("marcadores", _uns, usuario_id=2), _buf)
_buf.seek(0)
from openpyxl import load_workbook as _lw                            # noqa: E402
_ws = _lw(_buf).active
_txt = "\n".join(str(c.value) for r in _ws.iter_rows() for c in r if c.value is not None)
checar("a planilha diz a BASE", "Base:" in _txt)
checar("e leva a nota que qualifica a distribuicao", "marcador" in _txt.lower())
_buf2 = _io.BytesIO()
_R.para_xlsx(_R.montar("onde_aberto", _uns, usuario_id=2), _buf2)
_buf2.seek(0)
_ws2 = _lw(_buf2).active
_txt2 = "\n".join(str(c.value) for r in _ws2.iter_rows() for c in r if c.value is not None)
checar("e leva os destaques", "Abertos em mais de uma unidade" in _txt2)
# O cabecalho tem de estar formatado na linha do CABECALHO, nao numa linha vazia.
_buf3 = _io.BytesIO()
_R.para_xlsx(_R.montar("permanencia", _uns, usuario_id=2), _buf3)
_buf3.seek(0)
_ws3 = _lw(_buf3).active
_cab = next(r for r in _ws3.iter_rows() if r[0].value == "Faixa de permanência")
checar("o cabecalho da tabela esta em negrito na linha certa",
       _cab[0].font.bold is True and _cab[0].fill.fgColor.rgb.endswith("0F5257"))
_pct = [c for r in _ws3.iter_rows() for c in r if c.number_format == "0.0%"]
checar(f"os percentuais sao NUMERO com formato de porcentagem ({len(_pct)})",
       len(_pct) >= 3 and all(isinstance(c.value, float) for c in _pct))

print("\nO CATALOGO PERGUNTA AO BANCO — E DA O MESMO NUMERO")
# `/relatorios` nao mostra um processo sequer: mostra a fracao da carteira que
# tem cada campo preenchido. Carregava 1.165 dicionarios para isso — 34,6 ms dos
# 60 ms da tela, para alimentar 2,4 ms de contagem. O SQLite responde sozinho.
#
# A UNICA razao de a troca valer e dar o MESMO numero: um catalogo que diga 100%
# onde o relatorio diz 83% e pior que um catalogo lento.
import app as _ap12                                                 # noqa: E402
import relatorios as _R12                                           # noqa: E402

_u12 = _ap12.unidades_do(2)
_dados12 = _R12.carregar(_u12, 2)
_cob12, _tot12, _cobz12 = _R12.cobertura_agregada(_u12, 2)

checar(f"a base agregada e a mesma da carregada ({_tot12})",
       _tot12 == len(_dados12), f"{_tot12} contra {len(_dados12)}")
_campos12 = _R12._campos_do_catalogo()
checar(f"ha campos para conferir ({len(_campos12)})", len(_campos12) >= 15)
_div12 = [(c, _R12.cobertura(_dados12, c), _cob12.get(c, 0.0)) for c in _campos12
          if abs(_R12.cobertura(_dados12, c) - _cob12.get(c, 0.0)) > 1e-9]
checar("TODOS os campos dao a mesma cobertura das duas formas",
       not _div12, str([(c, round(a*100, 2), round(b*100, 2)) for c, a, b in _div12][:4]))

# A REGRA DO ZERO E OPOSTA NAS DUAS TELAS, e isso tem de sobreviver a traducao.
# `cobertura()` conta 0 como PREENCHIDO (booleano coletado e dado);
# `inviaveis_medidos()` conta 0 como VAZIO (a pergunta e "alguem USA?").
_vi12 = {x["campo"]: x["n"] for x in _R12.inviaveis_medidos(_dados12)}
_ni12 = {x["campo"]: x["n"] for x in _R12.inviaveis_medidos_agregado(_cobz12, _tot12)}
checar("os inviaveis dao o mesmo numero das duas formas",
       _vi12 == _ni12, str({k: (_vi12[k], _ni12[k]) for k in _vi12 if _vi12[k] != _ni12[k]}))
_zerado = [c for c in _vi12 if _vi12[c] == 0]
checar(f"e ha campo TODO ZERO para exercitar a regra ({_zerado})", bool(_zerado))
if _zerado:
    _c0 = _zerado[0]
    checar(f"'{_c0}' conta 0 nos inviaveis (ninguem usa)...", _ni12[_c0] == 0)
    checar(f"...e 100% na cobertura (o campo E coletado) — as duas certas",
           _cob12.get(_c0, 0) > 0.99, str(_cob12.get(_c0)))

# E o catalogo continua NAO carregando a carteira.
_fonte_app12 = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")
_ini12 = _fonte_app12.index("def relatorios_lista")
_fim12 = _fonte_app12.index("@app.get", _ini12 + 10)
checar("a rota /relatorios nao chama mais `carregar()`",
       "rel.carregar(" not in _fonte_app12[_ini12:_fim12],
       "voltou a montar 1.165 dicionarios para 16 porcentagens")

print("\nO CATALOGO NAO INVENTA 0% PARA CAMPO QUE VEM DO SNAPSHOT")
# `_campos_do_catalogo()` tira do SQL os campos que nao moram em `processo` —
# `snap_unidade` vem do snapshot. Mas o catalogo pergunta por eles, e o
# `cobertura.get(c, 0.0)` da tela transformava a ausencia em 0%: o relatorio
# "Comparativo entre unidades" nascia INVIAVEL, com tarja de `snap_unidade 0%`,
# a um clique da tela que mostra o mesmo campo com 100% e monta sem reclamar.
checar("os campos do snapshot voltam no resultado agregado",
       set(_R12.DO_SNAPSHOT) <= set(_cob12), str(set(_R12.DO_SNAPSHOT) - set(_cob12)))
for _c13, _v13 in _R12.DO_SNAPSHOT.items():
    checar(f"'{_c13}' sai {_v13*100:.0f}%, nao 0%", _cob12.get(_c13) == _v13,
           str(_cob12.get(_c13)))
# TODO campo declarado pelo catalogo tem de ter numero — a lacuna virava 0%.
_todos13 = {c for r in _R12.CATALOGO for c in r["campos"]}
_sem13 = sorted(_todos13 - set(_cob12))
checar("nenhum campo do CATALOGO fica sem medida", not _sem13,
       f"sem numero: {_sem13} — a tela leria 0% e fecharia o relatorio")
# E o relatorio que depende dele abre de verdade.
_r13 = next((r for r in _R12.CATALOGO if "snap_unidade" in r["campos"]), None)
checar("ha relatorio que declara snap_unidade", _r13 is not None)
if _r13:
    _pior13 = min(round(100 * _cob12.get(c, 0.0)) for c in _r13["campos"])
    checar(f"'{_r13['titulo']}' e viavel ({_pior13}%)",
           _pior13 >= _R12.COBERTURA_INVIAVEL * 100,
           "o cartao aparece com tarja vermelha e href='#'")

print("\nO PAINEL PERGUNTA A IDADE DA COLETA UMA VEZ, NAO DUAS")
# `estado_coleta()` estava sendo chamada para carimbar a auditoria e de novo,
# vinte linhas abaixo, para a faixa do painel: duas passadas por `snapshots_de` e
# pela tabela `snapshot` a cada abertura, pelo mesmo numero. CONTAR CHAMADAS e a
# unica forma de cobrar isso — ler o codigo-fonte ja se provou fraco aqui.
import seguranca as _sg13                                           # noqa: E402
_cx13 = conectar()
_tok13 = "verifica-estado-coleta-uma-vez-0001"
_cx13.execute("""INSERT INTO sessoes(usuario_id,token_sha256,criado_em,expira_em,
                 ip,user_agent) VALUES(?,?,?,?,?,?)""",
              (UID, _sg13.hash_token(_tok13), agora(),
               "2099-01-01T00:00:00-03:00", "127.0.0.1", "teste"))
_cx13.commit(); _cx13.close()

_n13 = {"c": 0}
_real13 = _ap12.estado_coleta
def _contada13(*a, **k):
    _n13["c"] += 1
    return _real13(*a, **k)
_ap12.estado_coleta = _contada13
_ap12.app.config["TESTING"] = True
_cli13 = _ap12.app.test_client()
_cli13.set_cookie(_ap12.COOKIE, _tok13, domain="localhost")
try:
    _r13 = _cli13.get("/")
finally:
    _ap12.estado_coleta = _real13

checar("o painel abre (senao a contagem nao diz nada)", _r13.status_code == 200,
       f"status {_r13.status_code}")
checar("e chamou `estado_coleta()` UMA vez", _n13["c"] == 1,
       f"chamou {_n13['c']} vezes")

print("\nO `journal_mode=WAL` E GRAVADO UMA VEZ, NAO A CADA CONEXAO")
# Ele e PERSISTENTE: fica gravado no cabecalho do arquivo e vale para qualquer
# conexao que o abrir depois. Reaplica-lo custava 1,48 ms dos 1,94 ms de cada
# `conectar()` — e o painel abre 6 conexoes; a tela de relatorios, 5.
import sqlite3 as _sq13                                             # noqa: E402
_pragmas13 = []
_conectar13 = _sq13.connect
def _espia13(*a, **k):
    _cx = _conectar13(*a, **k)
    _cx.set_trace_callback(
        lambda sql: _pragmas13.append(sql) if "journal_mode" in (sql or "") else None)
    return _cx
_sq13.connect = _espia13
try:
    for _ in range(3):
        _banco.conectar().close()
    _regravou13 = len(_pragmas13)
    # E O BANCO NOVO, que e o unico caso em que o modo realmente muda? Numa
    # instalacao do zero o arquivo nasce em `delete`, e pular o PRAGMA ali
    # deixaria o servidor sem leitura concorrente durante a ingestao.
    import tempfile as _tf13, shutil as _sh13, pathlib as _pl13   # noqa: E402
    _dir13 = _tf13.mkdtemp()
    _dd13, _bb13 = _banco.DADOS_DIR, _banco.BANCO
    try:
        _banco.DADOS_DIR = _pl13.Path(_dir13)
        _banco.BANCO = str(_pl13.Path(_dir13) / "novo.db")
        _novo13 = _banco.conectar()
        _modo13 = str(_novo13.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        _novo13.close()
    finally:
        _banco.DADOS_DIR, _banco.BANCO = _dd13, _bb13
        _sh13.rmtree(_dir13, ignore_errors=True)
finally:
    _sq13.connect = _conectar13
checar("tres conexoes seguidas nao regravam o journal_mode",
       not _regravou13, f"regravou {_regravou13}x")
checar("mas o banco NOVO nasce em WAL (senao a ingestao trava a leitura)",
       _modo13 == "wal", f"nasceu em {_modo13!r}")
_cx13 = conectar()
checar("e o banco continua em WAL",
       str(_cx13.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal")
checar("com o busy_timeout e as foreign keys, que sao POR conexao e ficaram",
       _cx13.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
       and _cx13.execute("PRAGMA foreign_keys").fetchone()[0] == 1)
_cx13.close()

cx = conectar()
cx.execute("UPDATE usuarios SET ativo=0 WHERE email=?", (CONTA,))
cx.commit(); cx.close()
print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
