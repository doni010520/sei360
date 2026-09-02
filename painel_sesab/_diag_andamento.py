# -*- coding: utf-8 -*-
"""Que descricoes existem no andamento, e quais a maquina de estados casa?

Hipotese: no padrao de abertura, 'gerado' esta SEM ancora, entao casa
'Documento X gerado na unidade Y' e abre unidade que so gerou documento —
e documento nunca 'fecha', entao a unidade fica aberta para sempre.
"""
import json, collections, re
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE  = Path(__file__).resolve().parent
JS    = BASE / "automacao_sei.js"
PERF  = BASE / "_perfil_sei"
LOGIN = "https://sip.seibahia.ba.gov.br/login.php?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI"
MESA  = "SESAB/SAIS/DGGUP/DGESS"

dados = json.loads((BASE / "_coletas" / "sei_sesab_2026-08-13.json").read_text("utf-8"))
alvo = [d for d in dados if d["mesa_coleta"] == MESA and d.get("mesas_divergem")
        and 15 <= (d.get("movimentos") or 0) < 99][:3]

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
        if (!r) { out[id] = {erro:'fora da lista'}; continue; }
        const h1 = await fetch(r.href, {credentials:'same-origin'})
                     .then(x=>x.arrayBuffer()).then(b=>new TextDecoder('iso-8859-1').decode(b));
        const src = (h1.match(/id="ifrArvore"[^>]*src="([^"]+)"/)||[])[1];
        const arv = await fetch(src.replace(/&amp;/g,'&'), {credentials:'same-origin'})
                      .then(x=>x.arrayBuffer()).then(b=>new TextDecoder('iso-8859-1').decode(b));
        const uh = (arv.match(/['"]([^'"]*acao=procedimento_consultar_historico[^'"]*)['"]/)||[])[1];
        const hh = await fetch(uh.replace(/&amp;/g,'&'), {credentials:'same-origin'})
                     .then(x=>x.arrayBuffer()).then(b=>new TextDecoder('iso-8859-1').decode(b));
        const d2 = new DOMParser().parseFromString(hh, 'text/html');
        const mov = [...d2.querySelectorAll('#tblHistorico tr')].map(tr => {
          const td = tr.querySelectorAll('td');
          if (td.length < 4) return null;
          return {dh: td[0].textContent.trim(), un: td[1].textContent.trim(),
                  de: td[3].textContent.trim()};
        }).filter(Boolean);
        out[id] = { mov,
                    andamento: SEIAuto.mesasPorAndamento(mov).map(x=>x.unidade),
                    arvore: SEIAuto.mesasPorArvore(arv).map(x=>x.unidade) };
      }
      return out;
    }""", [mesa, [d["id"] for d in alvo]])

ABRE  = re.compile(r"^Processo recebido na unidade|^Reabertura do processo na unidade|gerado", re.I)
FECHA = re.compile(r"^Processo remetido pela unidade|^Conclus.o do processo na unidade", re.I)

for d in alvo:
    r = res.get(d["id"], {})
    if r.get("erro"):
        print(d["protocolo"], r["erro"]); continue
    print(f"\n=== {d['protocolo']}  mov={len(r['mov'])}")
    print(f"    arvore   : {r['arvore']}")
    print(f"    andamento: {r['andamento']}")
    extra = [u for u in r["andamento"] if u not in r["arvore"]]
    print(f"    SOBRANDO no andamento: {extra}")
    print("    -- REMESSAS: coluna 'Unidade' x unidade nomeada na descricao --")
    difs = 0
    for m in r["mov"]:
        mm = re.match(r"^Processo remetido pela unidade\s+(.+)$", m["de"], re.I)
        if not mm: continue
        remetente = mm.group(1).strip()
        if remetente != m["un"]:
            difs += 1
            if difs <= 4:
                print(f"       coluna={m['un']}   descricao diz remetente={remetente}")
    print(f"       remessas em que a coluna NAO e o remetente: {difs}")

    print("    -- TODAS as descricoes distintas (o que a maquina faz com cada uma) --")
    c = collections.Counter(m["de"][:70] for m in r["mov"])
    for de, n in c.most_common(30):
        if FECHA.search(de):   acao = "FECHA"
        elif ABRE.search(de):  acao = "ABRE "
        else:                  acao = "  -  "
        print(f"       {acao} {n:3}x  {de}")
