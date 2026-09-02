# -*- coding: utf-8 -*-
"""Checa a sintaxe do JS embutido no painel, sem abrir navegador.

Existe porque um parenteses sobrando ja derrubou este painel inteiro: o navegador
falha ao PARSEAR o bloco e nao executa nada — tela em branco, console limpo, zero
pista. `node --check` acha isso em milissegundos.
"""
import re, subprocess, sys
from pathlib import Path

NODE = r"C:\Program Files\nodejs\node.exe"
BASE = Path(__file__).resolve().parent
HTML = BASE / "painel_sesab.html"
TMP  = BASE / "_painel_check.js"

html = HTML.read_text(encoding="utf-8")
blocos = re.findall(r"<script>(.*?)</script>", html, re.S)
if not blocos:
    sys.exit("nenhum bloco <script> encontrado")

falhas = 0
for i, js in enumerate(blocos, 1):
    TMP.write_text(js, encoding="utf-8")
    r = subprocess.run([NODE, "--check", str(TMP)], capture_output=True, text=True)
    if r.returncode:
        falhas += 1
        print(f"bloco {i}: SINTAXE INVALIDA")
        print("\n".join(r.stderr.splitlines()[:12]))
    else:
        print(f"bloco {i}: ok ({len(js)/1024:.0f} KB)")
TMP.unlink(missing_ok=True)
sys.exit(1 if falhas else 0)
