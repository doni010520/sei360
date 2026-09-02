# -*- coding: utf-8 -*-
"""Checa descobrirMesas()/trocarMesa() ja corrigidos, sem rodar a coleta inteira."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE  = Path(__file__).resolve().parent
JS    = BASE / "automacao_sei.js"
PERF  = BASE / "_perfil_sei"
LOGIN = "https://sip.seibahia.ba.gov.br/login.php?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PERF), headless=True)
    ctx.add_init_script(path=str(JS))
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.on("console", lambda m: print("  page>", m.text))
    pg.goto(LOGIN, wait_until="domcontentloaded")
    if "login.php" in pg.url:
        pg.select_option("#selOrgao", "23")
        pg.evaluate("() => { SEIAuto.garantirSessao(); }")
        pg.wait_for_url(lambda u: "login.php" not in u, timeout=60000)
    pg.wait_for_timeout(1200)

    mesas = pg.evaluate("() => SEIAuto.descobrirMesas()")
    print("\nMESAS:", json.dumps(mesas, ensure_ascii=False, indent=1))

    # troca em cada mesa e conta o tamanho da lista (sem coletar datas)
    print("\nTAMANHO DA CARTEIRA POR MESA:")
    for m in mesas:
        r = pg.evaluate("""async (m) => {
          const doc = await SEIAuto.trocarMesa(m);
          if (!doc) return {erro: 'troca falhou'};
          const l = await SEIAuto.listar(doc);
          return {n: l.length, amostra: l.slice(0,2).map(x => x.protocolo)};
        }""", m)
        print(f"  {m['sigla']:<34} {json.dumps(r, ensure_ascii=False)}")
    ctx.close()
