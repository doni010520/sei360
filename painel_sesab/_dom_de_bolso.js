/* O DOM DE BOLSO — um documento de mentira, pequeno e honesto.

   POR QUE ELE EXISTE
   ------------------
   Nao ha jsdom nesta estacao (conferido: `require('jsdom')` falha), e os testes
   do coletor precisam de um `document` para exercitar o parser. Este arquivo
   responde ao SUBCONJUNTO de seletores que o coletor usa, e devolve null para o
   que nao entende — de modo que um seletor novo faz o teste FALHAR, que e o
   comportamento certo. Um DOM que finge entender tudo transforma teste vermelho
   em teste verde mentiroso.

   POR QUE ELE E UM ARQUIVO, E NAO UM BLOCO DENTRO DE UM TESTE
   ----------------------------------------------------------
   Nasceu dentro de `_teste_parser40.js`. Quando `_teste_acompanhar.js` passou a
   precisar do mesmo documento, copia-lo seria fazer o que este projeto documenta
   ter dado errado em meia duzia de lugares: duas copias do mesmo parser divergem
   na primeira correcao que alguem fizer so numa delas — e aqui o que divergiria
   e a regua com que dois testes julgam o MESMO coletor.

   O QUE NAO DA PARA PROVAR COM ELE, e fica dito: que o HTML das fixtures e o HTML
   que o SEI devolve. Ele prova o PARSER; a rodada de campo prova a tela.

   Uso:  const { documento, elementoSolto } = require('./_dom_de_bolso');
*/
/* ======================================================== o DOM de bolso ==== */
const VAZIAS = new Set(['input', 'img', 'br', 'hr', 'meta', 'link', 'col']);
const ENTIDADES = { amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'", nbsp: ' ' };
const decodificar = s => String(s).replace(/&(#?\w+);/g,
  (t, e) => (e in ENTIDADES ? ENTIDADES[e] : t));

function atributos(bruto) {
  const a = {}, re = /([\w:.-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  let m;
  while ((m = re.exec(bruto || ''))) {
    if (!m[1]) continue;
    a[m[1].toLowerCase()] = decodificar(
      m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3]
      : m[4] !== undefined ? m[4] : '');
  }
  return a;
}

function analisar(html) {
  const raiz = { tag: '#doc', attrs: {}, filhos: [], pai: null, ini: 0, fim: html.length };
  const pilha = [raiz];
  const re = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][\w-]*)((?:\s+[\w:.-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)>/g;
  let m;
  while ((m = re.exec(html))) {
    if (m[0].startsWith('<!--')) continue;
    const tag = (m[2] || '').toLowerCase();
    if (m[1] === '/') {
      for (let i = pilha.length - 1; i > 0; i--) {
        if (pilha[i].tag === tag) { pilha[i].fim = m.index; pilha.length = i; break; }
      }
      continue;
    }
    const fim = m.index + m[0].length;
    const no = { tag, attrs: atributos(m[3]), filhos: [], pai: pilha[pilha.length - 1],
                 ini: fim, fim };
    no.pai.filhos.push(no);
    if (!(m[4] === '/') && !VAZIAS.has(tag)) pilha.push(no);
  }
  while (pilha.length > 1) { const n = pilha.pop(); n.fim = html.length; }
  return raiz;
}

/* Seletores aceitos: grupos separados por virgula; dentro de cada grupo, passos
   descendentes separados por espaco; cada passo e tag/#id/.classe/[attr op "v"]
   com op em =, ^=, *=, $=. E o que o coletor usa — nada alem disso. */
function compilar(sel) {
  return String(sel).split(',').map(g => g.trim()).filter(Boolean).map(grupo =>
    grupo.split(/\s+/).map(passo => {
      const p = { tag: null, id: null, classe: null, attrs: [] };
      const t = passo.match(/^([a-zA-Z][\w-]*)/);
      let resto = passo;
      if (t) { p.tag = t[1].toLowerCase(); resto = passo.slice(t[1].length); }
      const re = /#([\w-]+)|\.([\w-]+)|\[([\w:.-]+)(?:(\^=|\*=|\$=|=)"([^"]*)")?\]/g;
      let m;
      while ((m = re.exec(resto))) {
        if (m[1]) p.id = m[1];
        else if (m[2]) p.classe = m[2];
        else p.attrs.push({ nome: m[3].toLowerCase(), op: m[4] || null, valor: m[5] });
      }
      return p;
    }));
}

function casaPasso(no, p) {
  if (p.tag && no.tag !== p.tag) return false;
  if (p.id && (no.attrs.id || '') !== p.id) return false;
  if (p.classe && !String(no.attrs.class || '').split(/\s+/).includes(p.classe)) return false;
  for (const a of p.attrs) {
    const v = no.attrs[a.nome];
    if (v === undefined) return false;
    if (!a.op) continue;
    if (a.op === '=' && v !== a.valor) return false;
    if (a.op === '^=' && !v.startsWith(a.valor)) return false;
    if (a.op === '*=' && !v.includes(a.valor)) return false;
    if (a.op === '$=' && !v.endsWith(a.valor)) return false;
  }
  return true;
}

function casaGrupo(no, grupo) {
  if (!casaPasso(no, grupo[grupo.length - 1])) return false;
  let i = grupo.length - 2, p = no.pai;
  while (i >= 0 && p) { if (casaPasso(p, grupo[i])) i--; p = p.pai; }
  return i < 0;
}

function documento(html) {
  const raiz = analisar(html);
  const cache = new Map();
  const doc = {};
  const el = no => {
    if (!cache.has(no)) cache.set(no, novoEl(no));
    return cache.get(no);
  };

  function descendentes(no, saida) {
    for (const f of no.filhos) { saida.push(f); descendentes(f, saida); }
    return saida;
  }
  function buscar(no, sel, um) {
    const grupos = compilar(sel);
    const fora = [];
    for (const cand of descendentes(no, [])) {
      if (!grupos.some(g => casaGrupo(cand, g))) continue;
      if (um) return el(cand);
      fora.push(el(cand));
    }
    return um ? null : fora;
  }

  function novoEl(no) {
    const e = {
      _no: no,
      get id() { return no.attrs.id || ''; },
      get tagName() { return no.tag.toUpperCase(); },
      get className() { return no.attrs.class || ''; },
      get name() { return no.attrs.name || ''; },
      get type() { return no.attrs.type || (no.tag === 'select' ? 'select-one' : 'text'); },
      get checked() { return 'checked' in no.attrs; },
      get textContent() {
        return decodificar(html.slice(no.ini, no.fim).replace(/<[^>]*>/g, ''));
      },
      get innerHTML() { return html.slice(no.ini, no.fim); },
      get options() {
        if (no.tag !== 'select') return undefined;
        return no.filhos.filter(f => f.tag === 'option')
          .map(f => ({ value: f.attrs.value === undefined ? '' : f.attrs.value,
                       text: decodificar(html.slice(f.ini, f.fim).replace(/<[^>]*>/g, '')),
                       selected: 'selected' in f.attrs }));
      },
      get value() {
        if (no.tag === 'select') {
          const o = e.options || [];
          const sel = o.find(x => x.selected) || o[0];
          return sel ? sel.value : '';
        }
        return no.attrs.value === undefined ? '' : no.attrs.value;
      },
      get selectedIndex() {
        const o = e.options || [];
        const i = o.findIndex(x => x.selected);
        return i < 0 ? 0 : i;
      },
      get nextElementSibling() {
        if (!no.pai) return null;
        const irmaos = no.pai.filhos, i = irmaos.indexOf(no);
        return i >= 0 && irmaos[i + 1] ? el(irmaos[i + 1]) : null;
      },
      /* `rows` e `cells` sao o que `pesquisa_sei.js` usa para ler o resultado da
         Pesquisa, e nao existem em `querySelectorAll`: `tab.rows` e TODO `tr`
         descendente (o SEI envolve as linhas em `<tbody>`), e `tr.cells` sao as
         celulas FILHAS daquela linha — nunca as de uma tabela aninhada, que
         apareceriam como colunas extras da linha de fora. */
      get rows() {
        if (!['table', 'tbody', 'thead'].includes(no.tag)) return undefined;
        return descendentes(no, []).filter(f => f.tag === 'tr').map(el);
      },
      get cells() {
        if (no.tag !== 'tr') return undefined;
        return no.filhos.filter(f => f.tag === 'td' || f.tag === 'th').map(el);
      },
      getAttribute(n) {
        const v = no.attrs[String(n).toLowerCase()];
        return v === undefined ? null : v;
      },
      querySelector: s => buscar(no, s, true),
      querySelectorAll: s => buscar(no, s, false),
      closest(s) {
        const grupos = compilar(s);
        let p = no;
        while (p && p.tag !== '#doc') {
          if (grupos.some(g => casaGrupo(p, g))) return el(p);
          p = p.pai;
        }
        return null;
      },
    };
    return e;
  }

  function achar(no, id) {
    for (const f of no.filhos) {
      if ((f.attrs.id || '') === id) return f;
      const d = achar(f, id);
      if (d) return d;
    }
    return null;
  }

  doc.getElementById = id => { const n = achar(raiz, id); return n ? el(n) : null; };
  doc.querySelector = s => buscar(raiz, s, true);
  doc.querySelectorAll = s => buscar(raiz, s, false);
  Object.defineProperty(doc, 'body', {
    get: () => { const b = achar(raiz, '__body__'); return el(b || raiz); },
  });
  return doc;
}

/* Um elemento SOLTO, fora de documento nenhum — o que `document.createElement`
   devolve. `mesasPorArvore` e `acoesDaArvore` montam um `<div>`, atribuem
   `innerHTML` e consultam: e assim que o coletor le a arvore, que chega como
   texto de JavaScript e nao como pagina. Sem um innerHTML que REPARSE, esses dois
   caminhos ficariam sem teste — e sao eles que produzem `mesas` e `mesas_fonte`,
   os campos que o Acompanhamento manda ao servidor. */
function elementoSolto() {
  let doc = documento('');
  return {
    set innerHTML(h) { doc = documento(String(h)); },
    get innerHTML() { return doc.body.innerHTML; },
    get textContent() { return doc.body.textContent; },
    querySelector: s => doc.querySelector(s),
    querySelectorAll: s => doc.querySelectorAll(s),
    setAttribute() {}, click() {}, remove() {}, style: {},
  };
}

module.exports = { documento, elementoSolto, analisar, compilar, decodificar };
