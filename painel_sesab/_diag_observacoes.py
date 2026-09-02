# -*- coding: utf-8 -*-
"""O que gravo como 'anotacao' e realmente Anotacao, ou e Acompanhamento Especial?

Compara, para os MESMOS processos: (a) os icones da linha da lista com seus
aria-label e arquivo de icone, (b) o conteudo de anotacao_registrar, (c) o de
acompanhamento_gerenciar. SOMENTE LEITURA.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE  = Path(__file__).resolve().parent
JS    = BASE / "automacao_sei.js"
PERF  = BASE / "_perfil_sei"
LOGIN = "https://sip.seibahia.ba.gov.br/login.php?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI"
MESA  = "SESAB/SAIS/DGGUP/DGESS"

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

    print(json.dumps(pg.evaluate("""async (sigla) => {
      const mesas = await SEIAuto.descobrirMesas();
      const doc0 = await SEIAuto.trocarMesa(mesas.find(m => m.sigla === sigla));
      const pegar = u => fetch(u, {credentials:'same-origin'})
          .then(x=>x.arrayBuffer()).then(b=>new TextDecoder('iso-8859-1').decode(b));

      // recarrega a lista CRUA para inspecionar os icones como o SEI os entrega
      const f = doc0.getElementById('frmProcedimentoControlar');
      const sp = new URLSearchParams(new FormData(f));
      sp.set('hdnTipoVisualizacao','D');
      const d0 = new DOMParser().parseFromString(
        await fetch(f.getAttribute('action'), {method:'POST', body:sp, credentials:'same-origin'})
          .then(x=>x.arrayBuffer()).then(b=>new TextDecoder('iso-8859-1').decode(b)), 'text/html');

      const linhas = [...d0.querySelectorAll('#tblProcessosDetalhado tbody tr[id^="P"]')].slice(0,3);
      const saida = [];
      for (const tr of linhas) {
        const td = tr.querySelectorAll('td');
        const a = td[2].querySelector('a[href*="procedimento_trabalhar"]');
        const icones = [];
        [td[1], td[4]].filter(Boolean).forEach(c =>
          c.querySelectorAll('a').forEach(x => {
            const img = x.querySelector('img');
            icones.push({
              aria: x.getAttribute('aria-label') || '',
              arquivo: img ? (img.getAttribute('src')||'').split('/').pop().split('?')[0] : '',
              acao: ((x.getAttribute('href')||'').match(/acao=([a-z_]+)/)||[])[1] || '',
              tooltip: ((x.getAttribute('onmouseover')||'')
                        .match(/infraTooltipMostrar\\('([\\s\\S]*?)','([\\s\\S]*?)'\\)/)||[]).slice(1,3)
            });
          }));

        // acoes do processo
        const h1 = await pegar(a.getAttribute('href').replace(/&amp;/g,'&'));
        const src = (h1.match(/id="ifrArvore"[^>]*src="([^"]+)"/)||[])[1];
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

        const item = {processo: a.textContent.trim(), icones};
        if (acoes.anotacao_registrar) {
          const d = new DOMParser().parseFromString(await pegar(acoes.anotacao_registrar), 'text/html');
          const ta = d.querySelector('textarea');
          item.anotacao_registrar = {
            texto: ta ? (ta.value || ta.textContent || '').trim().slice(0,90) : '(sem textarea)',
            prioridade: !!d.querySelector('input[type=checkbox]:checked')
          };
        }
        if (acoes.acompanhamento_gerenciar) {
          const d = new DOMParser().parseFromString(await pegar(acoes.acompanhamento_gerenciar), 'text/html');
          item.acompanhamento = [...d.querySelectorAll('table tr')].slice(1,3)
            .map(tr => [...tr.querySelectorAll('td')].map(c=>c.textContent.trim().slice(0,45)));
        }
        saida.push(item);
      }
      return saida;
    }""", MESA), ensure_ascii=False, indent=1))
    ctx.close()
