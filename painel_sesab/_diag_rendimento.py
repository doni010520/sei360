# -*- coding: utf-8 -*-
"""Vale a pena pagar +1/+2 requisicoes por processo? Mede o RENDIMENTO antes.

Cada endpoint extra custa ~1134 requisicoes (~2 min) por coleta. Coletar campo que
vem vazio em 100% dos casos e custo puro. Amostra em varias mesas. SOMENTE LEITURA.
"""
import json, collections
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE  = Path(__file__).resolve().parent
JS    = BASE / "automacao_sei.js"
PERF  = BASE / "_perfil_sei"
LOGIN = "https://sip.seibahia.ba.gov.br/login.php?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI"
AMOSTRA_POR_MESA = 8

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
    pg.set_default_timeout(600_000)

    res = pg.evaluate("""async (n) => {
      const pegar = u => fetch(u, {credentials:'same-origin'})
          .then(x=>x.arrayBuffer()).then(b=>new TextDecoder('iso-8859-1').decode(b));
      const mesas = await SEIAuto.descobrirMesas();
      const out = [];
      for (const mesa of mesas) {
        const doc = await SEIAuto.trocarMesa(mesa);
        if (!doc) continue;
        const lista = await SEIAuto.listar(doc);
        for (const r of lista.slice(0, n)) {
          const h1 = await pegar(r.href);
          const src = (h1.match(/id="ifrArvore"[^>]*src="([^"]+)"/)||[])[1];
          if (!src) continue;
          const arv = await pegar(src.replace(/&amp;/g,'&'));
          let acoes = {};
          arv.split('\\n').forEach(l => {
            if (l.indexOf('Nos[0].acoes') !== -1) {
              const m = l.match(/'([\\s\\S]*)'/);
              if (m) { const d = document.createElement('div'); d.innerHTML = m[1];
                [...d.querySelectorAll('a')].forEach(x => {
                  const h = (x.getAttribute('href')||'').replace(/&amp;/g,'&');
                  const ac = (h.match(/acao=([a-z_]+)/)||[])[1];
                  if (ac) acoes[ac] = h; }); }
            }
          });
          const it = {mesa: mesa.sigla, protocolo: r.protocolo};

          if (acoes.acompanhamento_gerenciar) {
            const d = new DOMParser().parseFromString(
                        await pegar(acoes.acompanhamento_gerenciar), 'text/html');
            const linhas = [...d.querySelectorAll('table tr')]
              .map(tr => [...tr.querySelectorAll('td')].map(c=>c.textContent.trim()))
              .filter(c => c.length >= 5 && c[1]);
            it.acomp_n = linhas.length;
            it.acomp_grupo = linhas.length ? linhas[0][1] : null;
            it.acomp_obs   = linhas.length ? linhas[0][2] : null;
          }
          if (acoes.procedimento_alterar) {
            const d = new DOMParser().parseFromString(
                        await pegar(acoes.procedimento_alterar), 'text/html');
            const val = id => { const e = d.getElementById(id); return e ? (e.value||e.textContent||'').trim() : ''; };
            const selTxt = id => { const s = d.getElementById(id);
              return s && s.selectedIndex >= 0 ? s.options[s.selectedIndex].text.trim() : ''; };
            it.observacoes  = val('txaObservacoes');
            it.prioridade   = selTxt('selTipoPrioridade');
            it.interessados = [...(d.getElementById('selInteressadosProcedimento')||{options:[]}).options]
                                .map(o=>o.text.trim()).filter(Boolean).slice(0,3).join(' | ');
            it.assuntos     = [...(d.getElementById('selAssuntos')||{options:[]}).options]
                                .map(o=>o.text.trim()).filter(Boolean).slice(0,2).join(' | ');
            it.sigilo       = selTxt('selGrauSigilo');
          }
          out.push(it);
        }
      }
      return out;
    }""", AMOSTRA_POR_MESA)
    ctx.close()

n = len(res)
print(f"amostra: {n} processos\n")
def taxa(campo, cond=lambda v: bool(v)):
    k = sum(1 for r in res if cond(r.get(campo)))
    print(f"  {campo:16} preenchido em {k:3}/{n}  ({100*k/n:.0f}%)")
for c in ("acomp_grupo", "acomp_obs", "observacoes", "prioridade",
          "interessados", "assuntos", "sigilo"):
    taxa(c)

print("\ngrupos de acompanhamento mais comuns:")
for g, k in collections.Counter(r["acomp_grupo"] for r in res if r.get("acomp_grupo")).most_common(10):
    print(f"  {k:3}x  {g[:60]}")
print("\nexemplos de observacao (Acompanhamento):")
for r in [x for x in res if x.get("acomp_obs")][:3]:
    print(f"  [{r['acomp_grupo'][:28]}] {r['acomp_obs'][:90]}")
print("\nprioridades vistas:",
      dict(collections.Counter(r.get("prioridade") or "(vazio)" for r in res)))
