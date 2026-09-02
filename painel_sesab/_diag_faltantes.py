# -*- coding: utf-8 -*-
"""Que ESTADOS dao para derivar do andamento que ja baixamos?

A tentativa anterior casava texto no HTML inteiro da arvore e batia no MENU de acoes
("Sobrestar Processo", "Relacionamentos do Processo"), nao no estado do processo —
44% de "sobrestado" era o rotulo do botao. Aqui a fonte e o historico, que a coleta
ja busca para todo processo: custo ZERO por campo novo derivado dele.
"""
import json, collections, re
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE  = Path(__file__).resolve().parent
JS    = BASE / "automacao_sei.js"
PERF  = BASE / "_perfil_sei"
LOGIN = "https://sip.seibahia.ba.gov.br/login.php?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI"
POR_MESA = 12

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
          const uh = (arv.match(/['"]([^'"]*acao=procedimento_consultar_historico[^'"]*)['"]/)||[])[1];
          if (!uh) continue;
          const d = new DOMParser().parseFromString(
                      await pegar(uh.replace(/&amp;/g,'&')), 'text/html');
          const mov = [...d.querySelectorAll('#tblHistorico tr')].map(tr => {
            const td = tr.querySelectorAll('td');
            return td.length >= 4 ? {dh: td[0].textContent.trim(), de: td[3].textContent.trim()} : null;
          }).filter(Boolean);

          // quais propriedades os nos da arvore realmente usam (para achar documentos)
          const props = [...new Set([...arv.matchAll(/Nos\\[\\d+\\]\\.(\\w+)\\s*=/g)].map(m=>m[1]))];
          const nNos = new Set([...arv.matchAll(/Nos\\[(\\d+)\\]/g)].map(m=>m[1])).size;

          out.push({protocolo: r.protocolo, mov: mov.map(x=>x.de), props, nNos});
        }
      }
      return out;
    }""", POR_MESA)
    ctx.close()

print(f"amostra: {len(res)} processos\n")
print("propriedades dos nos da arvore:", res[0]["props"] if res else "-")
nos = [r["nNos"] for r in res]
nos.sort()
print(f"nos por arvore (processo + documentos): min={nos[0]} mediana={nos[len(nos)//2]} max={nos[-1]}")

# normaliza a descricao: tira nomes de unidade/usuario/numero para agrupar por TIPO
def tipo(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(unidade|para a unidade|pela unidade)\s+\S+", r"\1 X", s, flags=re.I)
    s = re.sub(r"\d{2}/\d{2}/\d{4}[\d:\s]*", "DATA ", s)
    s = re.sub(r"\b\d{5,}\b", "N", s)
    return s[:70]

c = collections.Counter(tipo(m) for r in res for m in r["mov"])
print(f"\ntipos de movimento distintos: {len(c)}\n")
print("os que aparecem em mais processos (candidatos a estado derivavel):")
por_proc = collections.Counter()
for r in res:
    for t in {tipo(m) for m in r["mov"]}:
        por_proc[t] += 1
for t, k in por_proc.most_common(28):
    print(f"  {k:3}/{len(res)} processos   {t}")
