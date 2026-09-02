# -*- coding: utf-8 -*-
"""As 'mesas' sao as unidades onde o processo esta aberto HOJE, ou lista historica?

Le a frase que o PROPRIO SEI escreve na raiz da arvore e compara com o que gravamos.
Amostra enviesada para os extremos (mais mesas): e la que uma leitura historica se
denunciaria. A arvore so e alcancavel pelo href da listagem (carrega infra_hash),
entao a conferencia refaz o caminho: troca de mesa -> listar -> abrir o processo.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE  = Path(__file__).resolve().parent
JS    = BASE / "automacao_sei.js"
PERF  = BASE / "_perfil_sei"
LOGIN = "https://sip.seibahia.ba.gov.br/login.php?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI"

dados = json.loads(sorted((BASE / "_coletas").glob("sei_sesab_*.json"))[-1].read_text("utf-8"))
ordenado = sorted(dados, key=lambda d: -len(d.get("mesas") or []))
alvo = ordenado[:3] + [d for d in dados if len(d.get("mesas") or []) == 1][:2]

# agrupa por mesa para trocar de unidade uma vez so
por_mesa = {}
for d in alvo:
    por_mesa.setdefault(d["mesa_coleta"], []).append(d)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PERF), headless=True)
    ctx.add_init_script(path=str(JS))
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.goto(LOGIN, wait_until="domcontentloaded")
    if "login.php" in pg.url:
        pg.select_option("#selOrgao", "23")
        pg.evaluate("() => { SEIAuto.garantirSessao(); }")
        pg.wait_for_url(lambda u: "login.php" not in u, timeout=60000)
    pg.wait_for_timeout(1000)
    pg.set_default_timeout(300_000)

    mesas = pg.evaluate("() => SEIAuto.descobrirMesas()")
    for sigla, itens in por_mesa.items():
        mesa = next((m for m in mesas if m["sigla"] == sigla), None)
        if not mesa:
            print(f"!! mesa {sigla} nao encontrada"); continue
        ids = [d["id"] for d in itens]
        res = pg.evaluate("""async ([mesa, ids]) => {
          const doc = await SEIAuto.trocarMesa(mesa);
          if (!doc) return {erro: 'troca falhou'};
          const lista = await SEIAuto.listar(doc);
          const out = {};
          for (const id of ids) {
            const r = lista.find(x => x.id === id);
            if (!r) { out[id] = {erro: 'nao esta na lista desta mesa'}; continue; }
            const h1 = await fetch(r.href, {credentials:'same-origin'})
                         .then(x => x.arrayBuffer())
                         .then(b => new TextDecoder('iso-8859-1').decode(b));
            const src = (h1.match(/id="ifrArvore"[^>]*src="([^"]+)"/) || [])[1];
            if (!src) { out[id] = {erro: 'sem iframe da arvore'}; continue; }
            const arv = await fetch(src.replace(/&amp;/g,'&'), {credentials:'same-origin'})
                          .then(x => x.arrayBuffer())
                          .then(b => new TextDecoder('iso-8859-1').decode(b));
            let linha = '';
            arv.split('\\n').forEach(l => {
              if (l.indexOf('Nos[0].html = ') !== -1) linha = l.split("'")[1] || ''; });
            const div = document.createElement('div');
            div.innerHTML = linha.replace(/<br \\/>/g, ' \\u00b7 ');
            out[id] = {rotulo: (div.textContent || '').replace(/\\s+/g,' ').trim()};
          }
          return out;
        }""", [mesa, ids])
        if res.get("erro"):
            print(f"!! {sigla}: {res['erro']}"); continue
        for d in itens:
            r = res.get(d["id"], {})
            nossas = [m["unidade"] for m in (d.get("mesas") or [])]
            print(f"\n=== {d['protocolo']}   mesa={sigla}")
            print(f"    gravamos {len(nossas)} mesa(s) | divergem={d.get('mesas_divergem')} "
                  f"| movimentos={d.get('movimentos')}")
            if r.get("erro"): print("    ERRO:", r["erro"]); continue
            rot = r.get("rotulo", "")
            print(f"    SEI  : {rot[:420]}")
            faltam = [u for u in nossas if u not in rot]
            sobra_n = rot.count("·") + 1 if rot else 0
            print(f"    gravadas AUSENTES na frase do SEI: {len(faltam)}"
                  + (f" -> {faltam[:4]}" if faltam else "  (todas conferem)"))
    ctx.close()
