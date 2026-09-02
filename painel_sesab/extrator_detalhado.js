/* ============================================================================
   EXTRATOR — Controle de Processos do SEI (visualizacao DETALHADA)
   Instancia validada: SESAB / seibahia.ba.gov.br — SEI 5.0.4

   COMO USAR
   1. Faca login no SEI e abra "Controle de Processos".
   2. Abra o console do navegador (F12 > Console).
   3. Cole este arquivo inteiro e tecle Enter.
   4. Acompanhe o progresso; ao final baixa "sei_processos_detalhado.json".

   POR QUE ELE SE AUTODESCOBRE
   Le o cabecalho <th> da tabela e monta o mapa de colunas em tempo de execucao.
   Assim funciona mesmo que a visualizacao detalhada traga colunas diferentes
   das esperadas, e continua funcionando se o SEI mudar a ordem.
   ========================================================================== */
(async () => {
'use strict';

const log = m => console.log('%c[SEI] ' + m, 'color:#0f5257;font-weight:bold');
const dec = new TextDecoder('iso-8859-1');   // o SEI responde em ISO-8859-1
const norm = s => (s || '').replace(/\s+/g, ' ').trim();
const params = u => { const o = {}; if (!u || u.indexOf('?') < 0) return o;
  u.split('?')[1].split('&').forEach(p => { const [k, v] = p.split('=');
    o[k] = decodeURIComponent(v || ''); }); return o; };

// ---------------------------------------------------------------- pre-voo
if (!document.getElementById('frmProcedimentoControlar')) {
  const lnk = document.getElementById('lnkControleProcessos');
  if (lnk) { log('Abrindo Controle de Processos… rode de novo em 3s.'); lnk.click(); return; }
  throw new Error('Nao estamos no Controle de Processos e nao achei #lnkControleProcessos.');
}
const form = document.getElementById('frmProcedimentoControlar');
const action = form.getAttribute('action');

// ------------------------------------------- alternar p/ visualizacao detalhada
// O SEI guarda o modo em #hdnTipoVisualizacao. Nao sabemos o valor de "detalhada"
// a priori: testamos os candidatos e ficamos com o que produzir #tblProcessosDetalhado.
async function pedir(extra) {
  const backup = {};
  Object.entries(extra || {}).forEach(([k, v]) => {
    const el = form.querySelector(`[id="${k}"],[name="${k}"]`);
    if (el) { backup[k] = el.value; el.value = v; }
  });
  const body = new URLSearchParams(new FormData(form));
  Object.entries(backup).forEach(([k, v]) => {
    const el = form.querySelector(`[id="${k}"],[name="${k}"]`); if (el) el.value = v; });
  const r = await fetch(action, { method: 'POST', body, credentials: 'same-origin' });
  return new DOMParser().parseFromString(dec.decode(await r.arrayBuffer()), 'text/html');
}

let modo = null, docTeste = null;
for (const cand of ['1', '2', 'D', '0']) {
  const d = await pedir({ hdnTipoVisualizacao: cand });
  if (d.getElementById('tblProcessosDetalhado')) { modo = cand; docTeste = d; break; }
}
if (modo) log('Visualizacao detalhada ativada (hdnTipoVisualizacao=' + modo + ')');
else log('AVISO: nao encontrei a visualizacao detalhada. Seguindo na resumida.');

// ------------------------------------------------------ mapa de colunas dinamico
function mapaColunas(tabela) {
  const ths = tabela.querySelectorAll('thead th, tr:first-child th');
  return Array.from(ths).map((th, i) => ({ i, rotulo: norm(th.textContent) || ('col' + i) }));
}

// ------------------------------------------------ extracao generica de uma celula
function lerCelula(td) {
  const o = { texto: norm(td.textContent) || null };
  const links = Array.from(td.querySelectorAll('a')).map(a => {
    const alvo = (a.getAttribute('href') || '') + (a.getAttribute('onclick') || '');
    const p = params(alvo);
    // tooltip nativo do SEI: infraTooltipMostrar('<corpo>','<titulo>')
    const tt = (a.getAttribute('onmouseover') || '')
      .match(/infraTooltipMostrar\('([\s\S]*?)','([\s\S]*?)'/);
    return {
      texto: norm(a.textContent) || null,
      acao: (alvo.match(/acao=([a-z_]+)/) || [])[1] || null,
      id_procedimento: p.id_procedimento || null,
      id_protocolo: p.id_protocolo || null,
      id_documento: p.id_documento || null,
      title: norm(a.getAttribute('title')) || null,
      aria: norm(a.getAttribute('aria-label')) || null,
      tip_corpo: tt ? norm(tt[1]) : null,
      tip_titulo: tt ? norm(tt[2]) : null,
      classe: a.className || null
    };
  }).filter(l => l.texto || l.acao || l.aria || l.tip_corpo);
  if (links.length) o.links = links;
  const imgs = Array.from(td.querySelectorAll('img')).map(im =>
    (im.getAttribute('src') || '').split('/').pop().split('?')[0]).filter(Boolean);
  if (imgs.length) o.icones = imgs;
  return (o.texto || o.links || o.icones) ? o : null;
}

function lerTabela(doc, idTabela, origem) {
  const tb = doc.getElementById(idTabela);
  if (!tb) return [];
  const cols = mapaColunas(tb);
  return Array.from(tb.querySelectorAll('tbody tr[id^="P"]')).map(tr => {
    const reg = { _id: tr.id.replace('P', ''), _origem: origem, _classes: tr.className || null };
    tr.querySelectorAll('td').forEach((td, i) => {
      const v = lerCelula(td);
      if (v) reg[(cols[i] && cols[i].rotulo) || ('col' + i)] = v;
    });
    return reg;
  });
}

// ------------------------------------------------------------------- paginacao
async function coletar(tipo, idTabela, origem) {
  const sel = document.getElementById('sel' + tipo + 'PaginacaoSuperior');
  // os value das options sao 0-based; nunca usar contador proprio
  const pgs = sel ? Array.from(sel.options).map(o => o.value) : ['0'];
  const out = [];
  for (const pg of pgs) {
    const extra = { ['hdn' + tipo + 'PaginaAtual']: pg };
    if (modo) extra.hdnTipoVisualizacao = modo;
    const doc = await pedir(extra);
    const linhas = lerTabela(doc, idTabela, origem);
    log(`${origem} · pagina ${pg} → ${linhas.length} linhas`);
    out.push(...linhas);
    await new Promise(r => setTimeout(r, 300));
  }
  return out;
}

// -------------------------------------------------------------------- execucao
const todos = [];
if (modo && docTeste && docTeste.getElementById('tblProcessosDetalhado')) {
  // na detalhada o SEI consolida; ainda assim paginamos pelos dois seletores
  for (const t of ['Recebidos', 'Gerados']) {
    if (document.getElementById('sel' + t + 'PaginacaoSuperior') ||
        document.getElementById('hdn' + t + 'PaginaAtual')) {
      todos.push(...await coletar(t, 'tblProcessosDetalhado', t));
    }
  }
  if (!todos.length) todos.push(...lerTabela(docTeste, 'tblProcessosDetalhado', 'Detalhado'));
} else {
  todos.push(...await coletar('Recebidos', 'tblProcessosRecebidos', 'Recebidos'));
  todos.push(...await coletar('Gerados', 'tblProcessosGerados', 'Gerados'));
}

const vistos = new Set();
const unicos = todos.filter(r => vistos.has(r._id) ? false : (vistos.add(r._id), true));

// relatorio de cobertura: quais colunas vieram e quantas preenchidas
const cobertura = {};
unicos.forEach(r => Object.keys(r).forEach(k => { if (!k.startsWith('_')) cobertura[k] = (cobertura[k] || 0) + 1; }));
console.table(Object.entries(cobertura).map(([coluna, preenchidas]) =>
  ({ coluna, preenchidas, de: unicos.length })));

window.__SEI_DET = unicos;
const blob = new Blob([JSON.stringify(unicos, null, 1)], { type: 'application/json' });
const a = document.createElement('a');
a.href = URL.createObjectURL(blob);
a.download = 'sei_processos_detalhado.json';
document.body.appendChild(a); a.click(); a.remove();

log(`PRONTO: ${unicos.length} processos · ${Object.keys(cobertura).length} colunas · arquivo baixado`);
log('Os dados tambem ficaram em window.__SEI_DET');
})();
