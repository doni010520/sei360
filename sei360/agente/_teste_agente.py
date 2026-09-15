# -*- coding: utf-8 -*-
"""
O LADO DA ESTACAO, sem SEI e sem navegador: o agente e o coletor, de verdade.

O QUE DA PARA PROVAR AQUI
-------------------------
Que o agente acha o coletor DESTA arvore; que ele confere, antes de mandar
trabalho, se o coletor conhece o modo; que um coletor que recebe modo
desconhecido recusa em voz alta em vez de cair na coleta; que o teto de relogio
mata filho que emudece (e devolve a trava); que o teto NAO joga fora as fatias
validas que ja chegaram; que um nao-200 passageiro numa fatia nao descarta as
outras; e que falhas, motivo e a conta de reconciliacao chegam mesmo quando a
primeira fatia se perde.

COMO. O agente e importado de verdade e roda contra um COLETOR FALSO: um script
Python que imprime o que o caso mandar e, quando o caso pedir, emudece. Nada
disto fala com o SEI nem com o servidor — `chamar()` e trocado por uma funcao do
caso, que e o que permite medir quantos POSTs sairam e com que corpo.

O que NAO da para provar aqui: nada disto diz que a leitura no SEI funciona. Isso
e do `_teste_acompanhar.js` (a composicao) e da estacao de uma pessoa (o SEI).

    python _teste_agente.py
"""
import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ok_total, falhas = 0, []


def checar(nome, cond, detalhe=""):
    global ok_total
    if cond:
        ok_total += 1
        print(f"  ok    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {detalhe}")


def carregar_agente():
    """O agente de verdade, importado como modulo.

    `sei360_agente.py` nao e pacote e tem hifen nenhum no nome, mas roda como
    script: importa-lo por spec e o que permite chamar `_rodar_coletor` sem
    passar por `main()` e sem tocar em `agente.json`.
    """
    spec = importlib.util.spec_from_file_location("sei360_agente",
                                                  BASE / "sei360_agente.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ag = carregar_agente()


# --------------------------------------------------------------- coletor falso
def coletor_falso(corpo):
    """Um script que faz o que o caso mandar. Devolve o caminho.

    E o padrao que funciona para o agente: o codigo REAL do agente contra um
    filho que imprime — e emudece — sob controle do teste. Simular o
    `subprocess` no lugar provaria o simulador.
    """
    arq = Path(tempfile.mkdtemp(prefix="sei360_falso_")) / "coletor_sesab.py"
    arq.write_text("# -*- coding: utf-8 -*-\n" + corpo, encoding="utf-8")
    return arq


def coletor_que_conhece(corpo, modos=("--acompanhar", "--buscar")):
    """O mesmo, ja passando o aperto de mao — para o caso ser sobre outra coisa."""
    return coletor_falso(
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "if '--modos' in sys.argv:\n"
        f"    print('MODOS_OK ' + json.dumps({{'modos': {list(modos)!r}, "
        "'versao': 'falso'}))\n"
        "    sys.exit(0)\n" + corpo)


print("SEI360 — o lado da estacao (agente + coletor)\n")

# =============================================================== C1, a 2a ponta
print("1. o coletor recusa --acompanhar sem o campo do numero no perfil")
COLETOR_REAL = BASE.parent.parent / "painel_sesab" / "coletor_sesab.py"


def rodar_coletor_real(args, pedido):
    """O coletor DESTE repositorio, com o navegador indisponivel de proposito.

    `PLAYWRIGHT_BROWSERS_PATH` apontando para um diretorio vazio faz o Chromium
    faltar, e o coletor morre no `launch_persistent_context` — SEM abrir janela e,
    o que importa aqui, SEM tocar a rede. Nenhum caso deste arquivo pode chegar
    perto do SEI: o que se mede sao as guardas, que sao todas anteriores ao
    navegador.
    """
    p = subprocess.run([sys.executable, str(COLETOR_REAL)] + args,
                       input=json.dumps(pedido) + "\n", capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       cwd=str(COLETOR_REAL.parent), timeout=120,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8",
                            "PLAYWRIGHT_BROWSERS_PATH": SEM_NAVEGADOR})
    return p.returncode, (p.stdout or "") + (p.stderr or "")


SEM_NAVEGADOR = tempfile.mkdtemp(prefix="sei360_sem_navegador_")


checar("o coletor deste repositorio existe", COLETOR_REAL.exists(), str(COLETOR_REAL))
# SEM `campos_busca`: e o envelope que um perfil truncado (ou uma chamada a mao)
# produz, e era o que fazia a pesquisa sair sem filtro nenhum.
codigo, saida = rodar_coletor_real(
    ["--acompanhar"],
    {"acompanhamento": {"instancia": "SEI-SESAB", "protocolos": ["019.5120.2026.0161681-50"]},
     "perfil": {"instancia": "SEI-SESAB", "versao": "5.0.4"}})
checar("recusa com codigo 4 (infraestrutura), nao roda a busca", codigo == 4,
       f"codigo {codigo}: {saida[:200]}")
checar("e diz que falta campos_busca.numero_sei", "campos_busca" in saida,
       saida[:200])

# COM o campo: a recusa nao pode disparar. A execucao segue e vai morrer no
# navegador ausente — e e exatamente isso que prova que passou desta guarda.
codigo, saida = rodar_coletor_real(
    ["--acompanhar"],
    {"acompanhamento": {"instancia": "SEI-SESAB", "protocolos": ["019.5120.2026.0161681-50"]},
     "perfil": {"instancia": "SEI-SESAB", "versao": "5.0.4",
                "campos_busca": {"numero_sei": ["txtProtocoloPesquisa"]}}})
checar("com o campo no perfil, a recusa do numero nao dispara",
       "campos_busca" not in saida, saida[:200])
checar("e a execucao so para depois, no navegador que este teste nao tem",
       "launch_persistent_context" in saida or "Executable" in saida, saida[:300])


# ==================================================================== C2, o par
print("\n2. o agente aponta para o coletor DESTA arvore")
checar("COLETOR e o coletor deste repositorio",
       Path(ag.COLETOR).resolve() == COLETOR_REAL.resolve(), str(ag.COLETOR))
checar("e o COLETAS ao lado dele",
       Path(ag.COLETAS).resolve() == (COLETOR_REAL.parent / "_coletas").resolve(),
       str(ag.COLETAS))
# O DEFEITO ERA ESTE: o caminho absoluto da arvore anterior a separacao do
# repositorio. O arquivo de la e de 7 de setembro e nao tem uma mencao a
# "acompanhar" — todo o lado da estacao que este ramo construiu nunca rodaria.
checar("o coletor apontado conhece o modo --acompanhar",
       "acompanhar" in Path(ag.COLETOR).read_text(encoding="utf-8"), str(ag.COLETOR))

print("\n3. o coletor responde ao aperto de mao, e sem navegador")
conhece, texto = ag.coletor_conhece("--acompanhar")
checar("o coletor real diz que conhece --acompanhar", conhece, texto)
conhece, texto = ag.coletor_conhece("--buscar")
checar("e --buscar tambem", conhece, texto)
conhece, texto = ag.coletor_conhece("--modo-que-nunca-existiu")
checar("e diz que NAO conhece um modo inventado", not conhece, texto)

print("\n4. o coletor recusa modo desconhecido em voz alta — nunca coleta")
codigo, saida = rodar_coletor_real(["--modo-que-nunca-existiu"], {})
checar("recusa com codigo 4", codigo == 4, f"codigo {codigo}: {saida[:200]}")
checar("e nomeia o modo que nao conhece", "--modo-que-nunca-existiu" in saida,
       saida[:200])
# O CUSTO DO CONTRARIO, medido no desenho antigo: a flag desconhecida era
# ignorada, o coletor caia no caminho da COLETA, logava, colhia uma mesa so e
# gravava por cima da coleta boa do dia.
checar("e nao chega a abrir o navegador (nao caiu na coleta)",
       "launch_persistent_context" not in saida and "abrindo o SEI" not in saida,
       saida[:300])

print("\n5. o agente NAO manda trabalho a coletor que nao conhece o modo")
# O coletor "velho": responde ao `--modos` sem o modo pedido, e — se receber
# trabalho assim mesmo — deixa marca no disco. A marca e o que separa "recusou"
# de "rodou e nao devolveu nada".
MARCA = Path(tempfile.mkdtemp(prefix="sei360_marca_")) / "rodou.txt"
VELHO = coletor_falso(
    "import json, sys\n"
    "from pathlib import Path\n"
    "if '--modos' in sys.argv:\n"
    "    print('MODOS_OK ' + json.dumps({'modos': ['--buscar']}))\n"
    "    sys.exit(0)\n"
    f"Path(r'{MARCA}').write_text('recebi trabalho', encoding='utf-8')\n"
    "sys.stdin.readline()\n"
    "print('coletando a mesa toda, como sempre')\n")
guardado, ag.COLETOR = ag.COLETOR, VELHO
try:
    ag._MODOS_DO_COLETOR.clear()
    try:
        ag._rodar_coletor({"acompanhamento": {}}, "--acompanhar", "ACOMP_OK ", 30,
                          varios=True)
        recusou = False
    except ag.ColetorNaoConhece as e:
        recusou, texto = True, str(e)
    checar("o agente recusa antes de rodar", recusou,
           "rodou assim mesmo" if not recusou else "")
    checar("e a recusa diz qual modo falta", recusou and "--acompanhar" in texto,
           texto if recusou else "")
    checar("o coletor velho NAO recebeu trabalho nenhum", not MARCA.exists(),
           str(MARCA))

    # O outro coletor velho: nem sabe o que e `--modos`. Sai 0 e imprime log de
    # coleta. Sem linha de marca nao ha aperto de mao, e sem aperto de mao nao ha
    # trabalho — este e o caso REAL do arquivo de 7 de setembro.
    MUDO = coletor_falso("import sys\n"
                         "sys.stdin.readline()\n"
                         "print('coletor antigo: comecando a coleta')\n")
    ag.COLETOR = MUDO
    ag._MODOS_DO_COLETOR.clear()
    try:
        ag._rodar_coletor({}, "--acompanhar", "ACOMP_OK ", 30, varios=True)
        recusou = False
    except ag.ColetorNaoConhece:
        recusou = True
    checar("coletor que nem conhece --modos tambem nao recebe trabalho", recusou)
finally:
    ag.COLETOR = guardado
    ag._MODOS_DO_COLETOR.clear()


# =========================================================== I1, o teto de fato
print("\n6. o teto de relogio nao espera o filho falar")
# O DEFEITO MEDIDO: `for linha in proc.stdout` BLOQUEIA, e o `if time.time() -
# inicio > teto` so roda depois que uma linha chega. Com teto de 2 s e um filho
# que emudece, `_rodar_coletor` ainda estava rodando aos 10 s. Este caso e o
# relogio: o filho imprime UMA linha e depois cala por 30 s.
MUDO_APOS_UMA = coletor_que_conhece(
    "sys.stdin.readline()\n"
    "print('comecando')\n"
    "sys.stdout.flush()\n"
    "time.sleep(30)\n"
    "print('ACOMP_OK {\"leituras\": []}')\n")
guardado, ag.COLETOR = ag.COLETOR, MUDO_APOS_UMA
ag._MODOS_DO_COLETOR.clear()
try:
    t0 = time.time()
    saida_env = ag._rodar_coletor({}, "--acompanhar", "ACOMP_OK ", 2, varios=True)
    gasto = time.time() - t0
    checar("com teto de 2 s, volta em menos de 6", gasto < 6, f"{gasto:.1f}s")
    checar("e nao inventa envelope", saida_env == [], repr(saida_env))

    # O MESMO CAMINHO VALE PARA A BUSCA: e a mesma funcao, e era o mesmo laco.
    ag._MODOS_DO_COLETOR.clear()
    t0 = time.time()
    um = ag._rodar_coletor({}, "--buscar", "BUSCA_OK ", 2)
    gasto = time.time() - t0
    checar("a busca tem o mesmo teto, pelo mesmo caminho", gasto < 6, f"{gasto:.1f}s")
    checar("e devolve None, que e o que `buscar()` ja trata", um is None, repr(um))

    # A CONSEQUENCIA QUE O COMENTARIO DE `rodar()` NEGAVA. O bloco esta dentro de
    # `with Trava():`; enquanto o laco nao voltava, o `__exit__` nao rodava, o
    # `agente.lock` ficava com PID VIVO e a batida seguinte morria na trava de
    # `buscar()` — que roda ANTES da coleta. Nao era "o acompanhamento do dia se
    # perde": era TODA coleta futura parada ate alguem reparar.
    trava_real, ag.TRAVA = ag.TRAVA, Path(tempfile.mkdtemp(prefix="sei360_trava_")) / "agente.lock"
    try:
        ag._MODOS_DO_COLETOR.clear()
        with ag.Trava():
            ag._rodar_coletor({}, "--acompanhar", "ACOMP_OK ", 2, varios=True)
        checar("e a trava e devolvida — a coleta de amanha nao morre nela",
               not ag.TRAVA.exists(), str(ag.TRAVA))
    finally:
        ag.TRAVA = trava_real
finally:
    ag.COLETOR = guardado
    ag._MODOS_DO_COLETOR.clear()


# ================================================== I2, o que ja chegou fica
print("\n7. o teto NAO joga fora as fatias validas que ja chegaram")
# MEDIDO: 3 fatias boas chegam, o teto estoura na linha seguinte, e as 3 eram
# descartadas. A justificativa escrita era "json.loads aceita truncado" — que nao
# vale para estas: elas JA passaram por `json.loads`, uma a uma, e cada pedaco e
# um envelope completo e independente.
TRES_E_PENDURA = coletor_que_conhece(
    "sys.stdin.readline()\n"
    "for i in range(3):\n"
    "    print('ACOMP_OK ' + json.dumps({'instancia': 'SEI-SESAB',\n"
    "        'leituras': [{'protocolo': '019.%d.2026.0000001-11' % i,\n"
    "                      'estado': 'lido'}]}))\n"
    "    sys.stdout.flush()\n"
    "time.sleep(30)\n")
guardado, ag.COLETOR = ag.COLETOR, TRES_E_PENDURA
ag._MODOS_DO_COLETOR.clear()
try:
    t0 = time.time()
    envelopes = ag._rodar_coletor({}, "--acompanhar", "ACOMP_OK ", 2, varios=True)
    gasto = time.time() - t0
    checar("o teto disparou (o filho continuava pendurado)", gasto < 6, f"{gasto:.1f}s")
    checar("e as 3 fatias validas voltam, em vez de serem descartadas",
           len(envelopes) == 3, repr(envelopes)[:200])
    checar("com as leituras inteiras",
           len(envelopes) == 3
           and all((e.get("leituras") or [{}])[0].get("estado") == "lido"
                   for e in envelopes),
           repr(envelopes)[:200])
finally:
    ag.COLETOR = guardado
    ag._MODOS_DO_COLETOR.clear()


# ============================================ I3, um nao-200 nao mata os outros
def _fatiar_do_coletor():
    """A `fatiar()` do coletor DE VERDADE, sem executar o script inteiro.

    O contrato dos pedacos tem duas pontas — quem corta (o coletor) e quem
    remonta (o agente) — e um teste que inventa o formato dos pedacos so provaria
    a invencao. Importar o coletor nao da: o modulo e um script que abre
    navegador. Entao se extrai a FUNCAO da fonte, por AST, e se roda ela mesma.
    """
    arvore = ast.parse(COLETOR_REAL.read_text(encoding="utf-8"))
    trecho = next(n for n in arvore.body
                  if isinstance(n, ast.FunctionDef) and n.name == "fatiar")
    espaco = {}
    exec(compile(ast.Module(body=[trecho], type_ignores=[]),
                 str(COLETOR_REAL), "exec"), espaco)
    return espaco["fatiar"]


fatiar = _fatiar_do_coletor()


def rodar_acompanhar(respostas_post, fatias=5, falhas_do_env=(), motivo=None,
                     pedidos=None, perder_primeira=False):
    """Roda `acompanhar()` de verdade contra um coletor falso e um servidor falso.

    Devolve (registro dos POSTs, texto impresso). `chamar()` e trocado: e o que
    permite medir quantos POSTs sairam, com que corpo, e sem rede nenhuma. Os
    pedacos saem da `fatiar()` real, uma leitura por pedaco.
    """
    import io
    import contextlib

    leituras = [{"protocolo": "019.%d.2026.0000001-11" % i, "estado": "lido"}
                for i in range(fatias)]
    env = {"instancia": "SEI-SESAB", "leituras": leituras,
           "falhas": [dict(f) for f in falhas_do_env], "motivo": motivo,
           "pedidos": pedidos if pedidos is not None
                      else fatias + len(falhas_do_env)}
    corpo = ["sys.stdin.readline()\n"]
    for i, pedaco in enumerate(fatiar(env, por_linha=1)):
        if i == 0 and perder_primeira:
            # A LINHA CORROMPIDA, que e o caso que o corte em pedacos existe para
            # sobreviver: escrita nao atomica no pipe. O agente a descarta em
            # `_rodar_coletor`, com aviso, e segue com as outras.
            corpo.append("print('ACOMP_OK ' + json.dumps(%r)[:30])\n" % pedaco)
        else:
            corpo.append("print('ACOMP_OK ' + json.dumps(%r))\n" % pedaco)
    FALSO = coletor_que_conhece("".join(corpo))

    registro, restantes = [], list(respostas_post)

    def chamar_falso(cfg, caminho, corpo=None, metodo=None, timeout=120):
        registro.append((caminho, metodo, corpo))
        if metodo == "GET":
            return 200, {"ler": True, "instancia": "SEI-SESAB",
                         "protocolos": [x["protocolo"] for x in leituras],
                         "perfil": {"instancia": "SEI-SESAB"}}
        return restantes.pop(0) if restantes else (200, {"gravadas": 1, "ignoradas": 0})

    guardado_c, guardado_ch = ag.COLETOR, ag.chamar
    ag.COLETOR, ag.chamar = FALSO, chamar_falso
    ag._MODOS_DO_COLETOR.clear()
    try:
        tela = io.StringIO()
        with contextlib.redirect_stdout(tela):
            ag.acompanhar({"servidor": "http://nao-usado", "token": "x"})
        return [r for r in registro if r[1] != "GET"], tela.getvalue()
    finally:
        ag.COLETOR, ag.chamar = guardado_c, guardado_ch
        ag._MODOS_DO_COLETOR.clear()


print("\n8. um nao-200 passageiro numa fatia nao descarta as outras")
# MEDIDO: 500 na primeira fatia -> 1 POST tentado de 5, 80 leituras boas perdidas
# na mao do agente. O `break` era por QUALQUER nao-200, e `chamar()` devolve 0
# para servidor inalcancavel e para timeout.
posts, tela = rodar_acompanhar([(500, {"erro": "erro interno"})])
checar("as 5 fatias sao tentadas mesmo com 500 na primeira", len(posts) == 5,
       f"{len(posts)} POST(s)")
checar("e a recusa da primeira aparece na tela", "500" in tela, tela[:300])
checar("o servidor recebeu as outras 4", "gravou 4" in tela, tela[:300])

posts, tela = rodar_acompanhar([(0, {"erro": "servidor inalcançável"})])
checar("servidor inalcancavel numa fatia tambem nao mata as outras",
       len(posts) == 5, f"{len(posts)} POST(s)")

# O 409 CONTINUA PARANDO, e o argumento e o escrito: "a instalacao do dono mudou
# entre o pedido e a resposta" vale para TODOS os pedacos — a instalacao declarada
# e a mesma nos cinco. Insistir seriam 5 recusas iguais.
posts, tela = rodar_acompanhar([(409, {"erro": "a estação relata leitura de..."})])
checar("mas o 409 para no primeiro, porque vale para todos", len(posts) == 1,
       f"{len(posts)} POST(s)")
checar("e diz por que parou", "409" in tela and "instala" in tela, tela[:300])

# 401/403 tambem valem para todos: o token nao muda entre uma fatia e outra.
posts, tela = rodar_acompanhar([(401, {"erro": "token inválido"})])
checar("401 tambem para no primeiro (o token nao muda no meio)", len(posts) == 1,
       f"{len(posts)} POST(s)")


# ==================================== I4, a fatia 0 nao decide pelas outras
print("\n9. falhas, motivo e a conta de reconciliacao nao viajam so na fatia 0")
# MEDIDO: a fatia 0 e tao perdivel quanto as outras (mesma escrita nao atomica), e
# com ela sumiam de uma vez a lista de falhas — UNICO lugar onde um item que nao
# pode ser lido aparece —, o motivo (sessao caida, teto de tempo) e o numero de
# reconciliacao. O agente imprimia "gravou 40, ignorou 0 (em 2 pedacos)", e "2
# pedacos" eram os RECEBIDOS, nao os enviados: nada fechava conta com nada.
pedacos = fatiar({"instancia": "SEI-SESAB",
                  "leituras": [{"protocolo": "p%d" % i} for i in range(3)],
                  "falhas": [{"protocolo": "px", "motivo": "caiu"}],
                  "motivo": "sessao caiu apos 3 de 5", "pedidos": 5},
                 por_linha=1)
checar("fatiar corta uma leitura por pedaco", len(pedacos) == 3, repr(pedacos)[:200])
checar("e TODO pedaco leva falhas, motivo e pedidos",
       all(p.get("falhas") and p.get("motivo") and p.get("pedidos") == 5
           for p in pedacos), repr(pedacos)[:300])
checar("e cada um sabe quem e no conjunto",
       [p["pedaco"] for p in pedacos] == [1, 2, 3]
       and all(p["pedacos"] == 3 for p in pedacos), repr(pedacos)[:200])

FALHA_UM = {"protocolo": "019.9.2026.0000009-99", "motivo": "historico nao respondeu"}
posts, tela = rodar_acompanhar([], fatias=5, falhas_do_env=[FALHA_UM],
                               motivo="teto de tempo da estacao (9 min): 5 de 6",
                               perder_primeira=True)
checar("a fatia 0 se perdeu (4 POSTs de 5)", len(posts) == 4, f"{len(posts)} POST(s)")
checar("mesmo assim a falha aparece — e o unico lugar onde ela aparece",
       "019.9.2026.0000009-99" in tela, tela[:400])
checar("e o motivo tambem", "teto de tempo" in tela, tela[:400])
checar("a falha nao e contada 4 vezes", "1 processo(s) não puderam ser lidos" in tela,
       tela[:400])
checar("nem o motivo repetido 4 vezes", tela.count("teto de tempo") == 1, tela[:400])
checar("e a conta fecha em voz alta: 1 leitura sem noticia",
       "reconcilia" in tela and "1 sem" in tela, tela[:500])
checar("os pedacos recebidos sao distinguidos dos declarados",
       "4 de 5" in tela, tela[:400])

# NADA PERDIDO: a conta tem de calar. Linha de reconciliacao em execucao boa vira
# ruido, e ruido diario e o que faz ninguem ler o log no dia em que ele importa.
posts, tela = rodar_acompanhar([], fatias=3, pedidos=3)
checar("sem perda nenhuma, a reconciliacao nao imprime nada",
       "reconcilia" not in tela, tela[:400])


# ======================================= o residuo: infra_hash no eco do console
print("\n10. o eco do console da pagina nao carrega infra_hash")
# SEM GATILHO CONHECIDO, e fechado assim mesmo: `on_console` ecoa TODO console da
# pagina para o stdout, e stdout da estacao vira log, arquivo e anexo. Hash de
# sessao morto nao devolve erro — ele DERRUBA a sessao de quem esta trabalhando —,
# entao ele nao pode ficar em lugar nenhum onde alguem possa copia-lo de volta.


def _do_coletor(nomes, espaco):
    """Levanta funcoes e constantes do coletor real, sem executar o script.

    Inclui as CONSTANTES de que a funcao depende (a regra de mascaramento, aqui)
    pelo mesmo motivo de `fatiar`: um teste que reescreve a regra prova a copia.
    """
    arvore = ast.parse(COLETOR_REAL.read_text(encoding="utf-8"))
    corpo = []
    for n in arvore.body:
        if isinstance(n, ast.FunctionDef) and n.name in nomes:
            corpo.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(a, ast.Name) and a.id in nomes for a in n.targets):
            corpo.append(n)
    exec(compile(ast.Module(body=corpo, type_ignores=[]),
                 str(COLETOR_REAL), "exec"), espaco)
    return espaco


import re                                                          # noqa: E402


class _Msg:
    def __init__(self, texto):
        self.text = texto


ecoado, guardadas = [], []
espaco = {"log": ecoado.append, "ALERTAS": ("sessao",),
          "FALHAS_N": re.compile(r"\((?!0\s)\d+\s+falhas?\)", re.IGNORECASE),
          "alertas": guardadas, "re": re}
on_console = _do_coletor(("on_console", "SEM_HASH"), espaco)["on_console"]
on_console(_Msg("[BUSCA] falhou: caiu em /sei/x?infra_hash=SEGREDO123&id=9"))
checar("o hash nao vai para o stdout da estacao",
       not any("SEGREDO123" in l for l in ecoado), repr(ecoado))
checar("mas o resto da mensagem continua legivel",
       any("caiu em" in l and "infra_hash" in l for l in ecoado), repr(ecoado))
on_console(_Msg("[SEI] sessao caiu em /sei/x?infra_hash=SEGREDO123"))
checar("nem para a lista de alertas, que vira anexo",
       guardadas and "SEGREDO123" not in guardadas[0], repr(guardadas))
checar("e o alerta continua sendo detectado", len(guardadas) == 1, repr(guardadas))


# O FORMATO E CONTRATO, nao estilo: `rodar_testes.py` casa a frase exata
# "N verificacoes OK, M falha" e conta como FALHA qualquer suite que nao a
# imprima — verde nenhum a salva. Ver o comentario de `ler_saida` la, escrito
# depois de rodadas de 267, 340 e 602 verificacoes declararem sucesso sobre
# suite que morreu antes do resumo.
print(f"\n{ok_total} verificações OK, {len(falhas)} falha(s)")
if falhas:
    print("FALHOU: " + "; ".join(falhas))
sys.exit(1 if falhas else 0)
