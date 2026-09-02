# -*- coding: utf-8 -*-
"""
Confere a SINTAXE do JavaScript dos templates gerados.

POR QUE ISTO EXISTE
-------------------
Um `const t` declarado duas vezes no mesmo bloco derrubou o painel inteiro: zero
linhas renderizadas, tela em branco abaixo do cabeçalho. E TODAS as conferências
de texto passaram — elas procuram trechos no arquivo, e o trecho estava lá. O
defeito só aparecia no navegador, num `SyntaxError` do console.

Templates são HTML com JS embutido, então a conferência extrai os blocos
`<script>` e pede ao Node para analisá-los. Não executa nada: `--check` só
analisa. Se o Node não estiver instalado, a conferência DIZ que não rodou em vez
de passar em silêncio — conferência que se cala quando não pode rodar é pior que
não ter conferência.

    python conferir_js.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
# Blocos de template do Jinja saem antes da análise: `{{ dados|tojson }}` não é
# JavaScript, e é substituído por um literal para o analisador ver o formato
# certo sem precisar renderizar nada.
JINJA = re.compile(r"\{\{[^}]*\}\}|\{%[^%]*%\}")
SCRIPT = re.compile(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def node():
    for c in (shutil.which("node"), r"C:\Program Files\nodejs\node.exe",
              "/usr/bin/node", "/usr/local/bin/node"):
        if c and Path(c).exists():
            return c
    return None


def blocos(html):
    for m in SCRIPT.finditer(html):
        js = m.group(1)
        # `null` é um literal válido em qualquer posição onde a injeção aparece.
        yield JINJA.sub("null", js)


def conferir(caminhos=None):
    exe = node()
    if not exe:
        print("Node não encontrado — a sintaxe do JS NÃO foi conferida.")
        return None
    alvos = list(caminhos or sorted((BASE / "templates").glob("*.html")))
    problemas = []
    if not caminhos:
        # O COLETOR TAMBEM. Sao ~1.100 linhas que rodam dentro da pagina do SEI,
        # onde um erro de sintaxe nao aparece como erro: a coleta simplesmente nao
        # acontece. Ficava fora daqui porque nao e template — e o unico lugar que o
        # conferia era uma linha de teste presa a um caminho absoluto do Windows.
        coletor = BASE.parent.parent / "painel_sesab" / "automacao_sei.js"
        if coletor.exists():
            r = subprocess.run([exe, "--check", str(coletor)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                erro = (r.stderr or "").strip().splitlines()
                msg = next((l for l in erro if "Error" in l), erro[-1] if erro else "?")
                problemas.append((coletor.name, 0, msg.strip()[:120]))
        # AS DUAS GAVETAS do coletor, rodadas: bloco por processo, acompanhamento
        # por (processo, mesa). Enquanto dividiram a mesma, a leitura completa da
        # segunda mesa era pulada em silencio e o acompanhamento de uma mesa
        # aparecia na linha da outra.
        gav = BASE.parent.parent / "painel_sesab" / "_teste_gavetas.js"
        if gav.exists():
            r = subprocess.run([exe, str(gav)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                falhas = [l.strip() for l in (r.stdout or "").splitlines()
                          if l.strip().startswith("FALHA")]
                problemas.append(("_teste_gavetas.js", 0,
                                  falhas[0][:120] if falhas else "gavetas do coletor"))
        # A CONTA VOLTA PARA A UNIDADE DA TITULAR, em toda saida. É o pior defeito
        # já registrado neste projeto: a coleta troca a unidade ativa da sessão
        # nominal 19 vezes e, até 27/08/2026, terminava SEMPRE fora — as 13
        # execuções com dados de 13/08 a 27/08 pararam todas em
        # SESAB/SAIS/DGGUP/UMA-CMA, mesa onde a titular praticou ZERO atos nos 31
        # meses anteriores. Quem estivesse com o SEI aberto veria a tela congelada
        # na unidade antiga e praticaria ato na unidade errada, em nome dela.
        uni = BASE.parent.parent / "painel_sesab" / "_teste_unidade.js"
        if uni.exists():
            r = subprocess.run([exe, str(uni)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                falhas = [l.strip() for l in (r.stdout or "").splitlines()
                          if l.strip().startswith("FALHA")]
                problemas.append(("_teste_unidade.js", 0,
                                  falhas[0][:120] if falhas else "a conta nao volta para a origem"))
        # E A REGUA POR LINHA, RODADA. `--check` prova sintaxe; isto prova
        # comportamento — que e onde o defeito estava.
        regua = BASE / "conferir_regua.js"
        if regua.exists():
            r = subprocess.run([exe, str(regua)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                falhas = [l.strip() for l in (r.stdout or "").splitlines()
                          if l.strip().startswith("FALHA")]
                problemas.append(("conferir_regua.js", 0,
                                  falhas[0][:120] if falhas else "régua por linha quebrada"))
        # A CONTA DE DIAS NÃO É CONFERIDA AQUI. Ela era — e do jeito errado:
        # quem ESCREVE `_casos_dias.json` é o `teste_relatorios.py`, que roda
        # DEPOIS de `testes.py` na ordem da suíte. A comparação saía sempre
        # contra as respostas do Python da rodada ANTERIOR, e um mutante em
        # `_dias` passava por ela. Pior: sem o arquivo, este bloco simplesmente
        # se calava e saía 0.
        #
        # Hoje quem gera os casos roda a comparação, no mesmo processo, logo
        # depois de escrever — ver `teste_relatorios.py`. Uma pergunta, um dono.
    for arq in alvos:
        html = Path(arq).read_text(encoding="utf-8")
        for i, js in enumerate(blocos(html), 1):
            if not js.strip():
                continue
            tmp = Path(tempfile.gettempdir()) / f"sei360_js_{Path(arq).stem}_{i}.mjs"
            tmp.write_text(js, encoding="utf-8")
            r = subprocess.run([exe, "--check", str(tmp)], capture_output=True, text=True)
            os.unlink(tmp)
            if r.returncode != 0:
                erro = (r.stderr or "").strip().splitlines()
                # A mensagem útil do Node é a linha com "SyntaxError".
                msg = next((l for l in erro if "Error" in l), erro[-1] if erro else "?")
                problemas.append((Path(arq).name, i, msg.strip()[:120]))
    return problemas


if __name__ == "__main__":
    p = conferir()
    if p is None:
        sys.exit(0)
    for arq, i, msg in p:
        print(f"  ERRO  {arq} (bloco {i}): {msg}")
    print(f"{'sintaxe do JS ok' if not p else f'{len(p)} bloco(s) com erro'}")
    sys.exit(1 if p else 0)
