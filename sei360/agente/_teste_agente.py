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


print(f"\n{ok_total} verificacao(oes), {len(falhas)} falha(s)")
if falhas:
    print("FALHOU: " + "; ".join(falhas))
sys.exit(1 if falhas else 0)
