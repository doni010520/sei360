# -*- coding: utf-8 -*-
"""Confere o total coletado contra o que o proprio SEI declara na tela."""
import json, sys
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
    pg.goto(LOGIN, wait_until="domcontentloaded")
    if "login.php" in pg.url:
        pg.select_option("#selOrgao", "23")
        pg.evaluate("() => { SEIAuto.garantirSessao(); }")
        pg.wait_for_url(lambda u: "login.php" not in u, timeout=60000)
    pg.wait_for_timeout(1500)

    info = pg.evaluate("""() => {
      const t = document.body.innerText;
      const decl = [...t.matchAll(/Processos\\s+(recebidos|gerados)\\s*\\((\\d+)\\s*registros/gi)]
                    .map(m => ({tipo: m[1], total: +m[2]}));
      const sel = id => { const s = document.getElementById(id);
                          return s ? s.options.length : null; };
      return {
        unidade: (document.getElementById('lnkInfraUnidade')||{}).textContent?.trim(),
        declarado: decl,
        tabelas: [...document.querySelectorAll('table[id]')]
                   .map(x => x.id + ':' + x.querySelectorAll('tbody tr[id^="P"]').length),
        pagRecebidos: sel('selRecebidosPaginacaoSuperior'),
        pagGerados:   sel('selGeradosPaginacaoSuperior'),
        pagDetalhado: sel('selDetalhadoPaginacaoSuperior'),
        tipoVis: (document.getElementById('hdnTipoVisualizacao')||{}).value
      };
    }""")
    print(json.dumps(info, ensure_ascii=False, indent=1))

    # quantas paginas a visualizacao DETALHADA oferece
    det = pg.evaluate("""async () => {
      const f = document.getElementById('frmProcedimentoControlar');
      if (!f) return 'sem formulario';
      const sp = new URLSearchParams(new FormData(f));
      sp.set('hdnTipoVisualizacao','D');
      const r = await fetch(f.getAttribute('action'), {method:'POST', body:sp, credentials:'same-origin'});
      const d = new DOMParser().parseFromString(
                  new TextDecoder('iso-8859-1').decode(await r.arrayBuffer()), 'text/html');
      const s = d.getElementById('selDetalhadoPaginacaoSuperior');
      return { linhasNaPagina: d.querySelectorAll('#tblProcessosDetalhado tbody tr[id^="P"]').length,
               paginas: s ? s.options.length : 0,
               opcoes: s ? [...s.options].map(o=>o.value) : [] };
    }""")
    print("\nDETALHADA:", json.dumps(det, ensure_ascii=False))
    ctx.close()

arq = sorted((BASE/"_coletas").glob("sei_sesab_*.json"))[-1]
n = len(json.load(open(arq, encoding="utf-8")))
print(f"\nCOLETADO no arquivo: {n}")
