# -*- coding: utf-8 -*-
"""O parser das mesas e fiel a arvore, ou inventa/perde unidade?

Teste decisivo: numa UNICA busca da arvore, extrai (a) a frase crua do SEI e
(b) a lista que o parser produz. Comparar as duas isola o parser do tempo — se
a divergencia vista antes fosse do parser, aparece aqui; se some, era o processo
que andou entre a coleta e a conferencia.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE  = Path(__file__).resolve().parent
JS    = BASE / "automacao_sei.js"
PERF  = BASE / "_perfil_sei"
LOGIN = "https://sip.seibahia.ba.gov.br/login.php?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI"
MESA  = "SESAB/SAIS/DGGUP/DGESS/COMASUP"

dados = json.loads(sorted((BASE / "_coletas").glob("sei_sesab_*.json"))[-1].read_text("utf-8"))
alvo = [d for d in dados if d["mesa_coleta"] == MESA]
alvo = sorted(alvo, key=lambda d: -len(d.get("mesas") or []))[:6]

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
    mesa = next(m for m in mesas if m["sigla"] == MESA)
    res = pg.evaluate("""async ([mesa, ids]) => {
      const doc = await SEIAuto.trocarMesa(mesa);
      const lista = await SEIAuto.listar(doc);
      const out = {};
      for (const id of ids) {
        const r = lista.find(x => x.id === id);
        if (!r) { out[id] = {erro: 'fora da lista'}; continue; }
        const h1 = await fetch(r.href, {credentials:'same-origin'})
                     .then(x=>x.arrayBuffer()).then(b=>new TextDecoder('iso-8859-1').decode(b));
        const src = (h1.match(/id="ifrArvore"[^>]*src="([^"]+)"/)||[])[1];
        const arv = await fetch(src.replace(/&amp;/g,'&'), {credentials:'same-origin'})
                      .then(x=>x.arrayBuffer()).then(b=>new TextDecoder('iso-8859-1').decode(b));
        let linha = '';
        arv.split('\\n').forEach(l => {
          if (l.indexOf('Nos[0].html = ') !== -1) linha = l.split("'")[1] || ''; });
        // (a) frase crua, so texto
        const d1 = document.createElement('div');
        d1.innerHTML = linha.replace(/<br \\/>/g, '\\u00b7');
        // (b) o que o parser de producao devolve, na MESMA busca
        const parsed = SEIAuto.mesasPorArvore ? SEIAuto.mesasPorArvore(arv) : null;
        out[id] = { frase: (d1.textContent||'').replace(/\\s+/g,' ').trim(),
                    parsed: parsed ? parsed.map(x=>x.unidade) : 'nao exportado' };
      }
      return out;
    }""", [mesa, [d["id"] for d in alvo]])

    for d in alvo:
        r = res.get(d["id"], {})
        if r.get("erro"):
            print(f"{d['protocolo']}: {r['erro']}"); continue
        frase, parsed = r["frase"], r["parsed"]
        if isinstance(parsed, str):
            print("parser nao exportado —", parsed); break
        fora = [u for u in parsed if u not in frase]
        gravado = [m["unidade"] for m in (d.get("mesas") or [])]
        sumiu = [u for u in gravado if u not in parsed]
        novo  = [u for u in parsed if u not in gravado]
        print(f"\n{d['protocolo']}  gravado={len(gravado)}  agora={len(parsed)}")
        print(f"   parser inventou unidade fora da frase: {len(fora)}"
              + (f" -> {fora}" if fora else ""))
        if sumiu or novo:
            print(f"   mudou desde a coleta: -{len(sumiu)} {sumiu[:3]}  +{len(novo)} {novo[:3]}")
        else:
            print("   identico ao coletado")
    ctx.close()
