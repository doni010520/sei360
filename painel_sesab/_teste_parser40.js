/* O PARSER DA TELA CONTROLE DE PROCESSOS, NAS DUAS INSTALACOES.

   O que da para provar aqui, sem navegador e sem SEI: que a familia de
   seletores e escolhida UMA vez pelo perfil; que a listagem do SEI 4.0 sai da
   tela do 4.0 (duas tabelas, paginadas separadamente, ancoradas pelo LINK e nao
   pela posicao da celula); que a visao lida e REGISTRADA em vez de suposta; que
   `instancia` viaja da coleta ate o JSON exportado; que a descoberta de mesas
   atravessa as paginas da tela de selecao; e — o caso que mais importa — que um
   seletor que nao casa vira RECUSA DECLARADA, nunca zero linhas com cara de mesa
   vazia.

   O QUE NAO DA PARA PROVAR AQUI, e fica dito: que o HTML abaixo e o HTML que a
   FESF devolve. Nao existe em disco nenhuma captura da tela Controle de
   Processos do 4.0 (procurado em `sei_sistema/` e `sei_extraidos/`: os .html
   guardados sao DOCUMENTOS, nao telas). A fixture do 4.0 e SINTETICA, montada a
   partir dos seletores que o sistema irmao desta casa usa contra a FESF todo dia
   (`sei_extractor.py:635-720`, `:2765-2870`, `:3500-3560`) e da secao S de
   `.claude/skills/sei-navegacao/referencia-seipro.md`. Ela prova o PARSER; a
   rodada de campo prova o HTML.

   Nao ha jsdom nesta estacao (conferido: `require('jsdom')` falha). O DOM abaixo
   e pequeno e honesto: responde ao subconjunto de seletores que o coletor usa, e
   devolve null para o que nao entende — de modo que um seletor novo faz o teste
   FALHAR, que e o comportamento certo.

   node _teste_parser40.js
*/
const fs = require('fs'), path = require('path'), vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, 'automacao_sei.js'), 'utf8');

let ok = 0, mau = 0;
const checar = (nome, cond, viu) => {
  if (cond) { ok++; console.log('  ok    ' + nome); }
  else { mau++; console.log('  FALHA ' + nome + (viu !== undefined ? '  -> ' + viu : '')); }
};

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

/* ============================================================== o ambiente == */
function ambiente(resolver, opc = {}) {
  const guardado = {}, saida = [];
  const caixa = {
    console: { log: (...a) => saida.push(a.join(' ')) },
    TextDecoder: function () { this.decode = x => x; },
    URLSearchParams, Date, Math, JSON,
    // Sem espera: `dorme(240)` por pagina somaria segundos a cada caso e nao
    // prova nada — a pausa e gentileza com o SEI, nao regra de negocio.
    setTimeout: f => { f(); return 0; },
    setInterval: () => 0, clearInterval: () => {},
    Blob: function () {}, URL: { createObjectURL: () => 'x' },
    FormData: function (form) {
      const pares = [];
      (form && form.querySelectorAll ? form.querySelectorAll('input,select,textarea') : [])
        .forEach(e => {
          if (!e.name) return;
          if ((e.type === 'checkbox' || e.type === 'radio') && !e.checked) return;
          pares.push([e.name, e.value || '']);
        });
      this[Symbol.iterator] = function* () { for (const p of pares) yield p; };
    },
    DOMParser: function () { this.parseFromString = s => documento(s); },
    document: opc.document || {
      getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
      createElement: () => ({ setAttribute() {}, click() {}, remove() {}, style: {} }),
      body: { appendChild() {} },
    },
    location: { href: 'https://sei.fesfsus.ba.gov.br/sei/' },
    localStorage: {
      getItem: k => (k in guardado ? guardado[k] : null),
      setItem: (k, v) => { guardado[k] = v; },
      removeItem: k => { delete guardado[k]; },
    },
    async fetch(url, o) {
      const html = resolver(url, o);
      if (html == null) throw new Error('fixture sem resposta para ' + url);
      return { url, arrayBuffer: async () => html };
    },
  };
  caixa.window = caixa;
  vm.createContext(caixa);
  vm.runInContext(SRC, caixa);
  return { caixa, saida, guardado };
}

const FESF = { instancia: 'SEI-FESF', versao: '4.0.x',
               raiz: 'https://sei.fesfsus.ba.gov.br/' };
const SESAB = { instancia: 'SEI-SESAB', versao: '5.0.4',
                raiz: 'https://seibahia.ba.gov.br/' };

/* ========================================================== as fixtures ===== */
const ACAO = '/sei/controlador.php?acao=procedimento_controlar&infra_hash=abc';
const URL_DETALHADA = '/sei/controlador.php?acao=procedimento_controlar'
                    + '&hdnTipoVisualizacao=D&infra_hash=abc';

/* Uma linha do 4.0. Os nomes de pessoa sao inventados.
   ACENTOS LITERAIS, e nao entidades: e o que o DOM entrega a quem le
   `getAttribute` e `innerHTML` — o navegador decodifica na hora de parsear. Uma
   fixture com `&ccedil;` provaria um decodificador que a producao nao tem. */
function linha40(id, proto, opc = {}) {
  const detalhe = opc.detalhe
    ? `<tr id="trD${id}"><td colspan="4">Tipo: ${opc.detalhe.tipo}<br />`
      + `Especificação: ${opc.detalhe.espec}<br />`
      + `Interessado: FESF-SUS</td></tr>`
    : '';
  const anot = opc.anotacao
    ? `<a href="controlador.php?acao=anotacao_registrar&id_procedimento=${id}"`
      + ` onmouseover="infraTooltipMostrar('${opc.anotacao}','fulano.um em 12/08/2026 09:14')">`
      + `<img src="imagens/anotacao.gif" alt="Anotações"></a>`
    : '';
  const marc = opc.marcador
    ? `<a href="controlador.php?acao=andamento_marcador_gerenciar&id_procedimento=${id}"`
      + ` onmouseover="infraTooltipMostrar('${opc.marcador}','Marcador')">`
      + `<img src="imagens/marcador_${opc.cor}.png" alt="Marcador"></a>`
    : '';
  const excl = opc.novoDoc
    ? '<img src="imagens/exclamacao.png" alt="Documento incluído por outra unidade">'
    : '';
  const atrib = opc.atribuido
    ? `<a href="controlador.php?acao=procedimento_atribuicao_listar&id_procedimento=${id}"`
      + ` title="Atribuído para ${opc.atribuido.nome}">(${opc.atribuido.login})</a>`
    : '';
  const classe = opc.naoVisualizado ? 'processoNaoVisualizado' : 'processoVisualizado';
  const dica = opc.tooltip
    ? ` onmouseover="infraTooltipMostrar('${opc.tooltip.espec}','${opc.tooltip.tipo}')"`
    : '';
  return `
    <tr id="P${id}">
      <td><input type="checkbox" name="chkRecebidosItem${id}" value="${id}"></td>
      <td>${anot}${marc}</td>
      <td><a href="controlador.php?acao=procedimento_trabalhar&id_procedimento=${id}&infra_hash=zz"`
      + ` class="${classe}"${dica}>${proto}</a>${excl}</td>
      <td>${atrib}</td>
    </tr>${detalhe}`;
}

/* A tela do 4.0. `detalhe` liga as linhas trD (o que a Visualizacao Detalhada
   acrescenta) e `comIcone` liga o icone que leva ate ela. */
function tela40(opc = {}) {
  const pagRec = String(opc.pagRec == null ? 0 : opc.pagRec);
  const det = !!opc.detalhe;
  const d1 = det ? { tipo: 'Administrativo: Pagamento Indenizatorio',
                     espec: 'Gil Farma - competencia 07/2026' } : null;
  const rec = pagRec === '0'
    ? linha40('4001', '0016.000251/2026-62', {
        detalhe: d1, naoVisualizado: true, novoDoc: true,
        anotacao: 'Aguardando parecer da PROJUR', marcador: 'URGENTE', cor: 'vermelho',
        atribuido: { login: 'fulano.um', nome: 'Fulano 1' },
        tooltip: { tipo: 'Administrativo: Pagamento Indenizatorio',
                   espec: 'Gil Farma - competencia 07/2026' },
      })
      /* Os valores do trD sao DIFERENTES dos do tooltip de proposito: e o unico
         jeito de o teste dizer de qual das tres fontes o campo saiu. */
      + linha40('4002', '0272.000092/2026-75', {
        detalhe: det ? { tipo: 'Gestao de Pessoas: Ferias',
                         espec: 'Escala de ferias 2026 (veio do trD)' } : null,
        tooltip: { tipo: 'Gestao de Pessoas: Ferias', espec: 'Escala 2026' },
      })
    : linha40('4003', '0317.000015/2026-51', {
        detalhe: det ? { tipo: 'Compras: Dispensa', espec: 'Oxigenio medicinal' } : null,
        tooltip: { tipo: 'Compras: Dispensa', espec: 'Oxigenio medicinal' },
      });
  const ger = linha40('4009', '0016.000300/2026-10', {
    detalhe: det ? { tipo: 'Contratos: Aditivo', espec: 'Termo aditivo HECC' } : null,
    tooltip: { tipo: 'Contratos: Aditivo', espec: 'Termo aditivo HECC' },
  });
  const icone = opc.comIcone
    ? `<a href="${URL_DETALHADA}"><img src="imagens/detalhado.gif"`
      + ' alt="Visualização Detalhada"></a>'
    : '';
  const tabelaRec = opc.tabelaRecebidos === null ? null
    : (opc.tabelaRecebidos || 'tblProcessosRecebidos');
  return `<html><body id="__body__">
  <a id="lnkInfraUnidade" onclick="window.location.href='controlador.php?acao=infra_trocar_unidade&infra_hash=uu'">FESF/DIGAS/HECC</a>
  <form id="frmProcedimentoControlar" action="${ACAO}">
    <input type="hidden" name="hdnInfraTipoPagina" value="1">
    <input type="hidden" id="hdnRecebidosPaginaAtual" name="hdnRecebidosPaginaAtual" value="${pagRec}">
    <input type="hidden" id="hdnGeradosPaginaAtual" name="hdnGeradosPaginaAtual" value="0">
    <input type="hidden" id="hdnRecebidosNroItens" name="hdnRecebidosNroItens" value="${opc.declaraRec == null ? 3 : opc.declaraRec}">
    <input type="hidden" id="hdnGeradosNroItens" name="hdnGeradosNroItens" value="1">
    ${icone}
    <select id="selRecebidosPaginacaoSuperior" name="selRecebidosPaginacaoSuperior">
      <option value="0">1</option><option value="1">2</option>
    </select>
    <table id="${tabelaRec || 'tblOutraCoisa'}"><tbody>${rec}</tbody></table>
    <select id="selGeradosPaginacaoSuperior" name="selGeradosPaginacaoSuperior">
      <option value="0">1</option>
    </select>
    <table id="tblProcessosGerados"><tbody>${ger}</tbody></table>
  </form></body></html>`;
}

/* A tela do 5.0.4, visualizacao Detalhada: UMA tabela, `aria-label` com
   "<Tipo> / <Especificacao>", icones no td[1] e atribuicao no td[3]. */
function tela50() {
  return `<html><body id="__body__">
  <form id="frmProcedimentoControlar" action="${ACAO}">
    <input type="hidden" name="hdnTipoVisualizacao" value="D">
    <input type="hidden" id="hdnDetalhadoPaginaAtual" name="hdnDetalhadoPaginaAtual" value="0">
    <select id="selDetalhadoPaginacaoSuperior" name="selDetalhadoPaginacaoSuperior">
      <option value="0">1</option>
    </select>
    <table id="tblProcessosDetalhado"><tbody>
      <tr id="P5001">
        <td><input type="checkbox" name="chkDetalhadoItem1"></td>
        <td><a aria-label="Anotação / ver" onmouseover="infraTooltipMostrar('Falta a CI','fulano.dois@saude.ba.gov.br em 22/11/2024 08:41')"><img src="/infra_css/imagens/anotacao.svg"></a>
            <a aria-label="Marcador / PRIORIDADE"><img src="/infra_css/imagens/marcador_verde_amazonas.svg"></a></td>
        <td><a href="controlador.php?acao=procedimento_trabalhar&id_procedimento=5001" class="processoVisualizado" aria-label="Administrativo: Pagamento / Del Mar 06/2026">019.000123/2026-11</a></td>
        <td><a title="Atribuído para Fulano 2">fulano.dois</a></td>
        <td><a aria-label="Documento incluido"><img src="/infra_css/imagens/exclamacao.svg"></a></td>
      </tr>
    </tbody></table>
  </form></body></html>`;
}

/* A tela de selecao de unidade (`acao=infra_trocar_unidade`), em duas paginas. */
function telaUnidades(pagina) {
  const linhas = pagina === 0
    ? [['110000001', 'FESF/DIGAS/HECC', 'Hospital Estadual Costa dos Coqueiros'],
       ['110000002', 'FESF/DIGAS/HECC/GAF', 'Gerencia Administrativa Financeira']]
    : [['110000003', 'FESF/DIGAS/HECC/GC', 'Gerencia de Contratos'],
       ['110000004', 'FESF', 'Fundacao Estatal Saude da Familia']];
  const tr = linhas.map(([id, sigla, desc]) => `
    <tr class="infraTrClara">
      <td><input type="radio" name="chkInfraItem" value="${id}" title="${sigla}"></td>
      <td>${sigla}</td><td>${desc}</td><td>FESF</td>
    </tr>`).join('');
  const prox = pagina === 0
    ? '<a href="/sei/controlador.php?acao=infra_trocar_unidade&hdnInfraPaginaAtual=1&infra_hash=uu" title="Próxima página">&gt;&gt;</a>'
    : '';
  return `<html><body id="__body__">
  <form id="frmInfraSelecaoUnidade" action="/sei/controlador.php?acao=infra_trocar_unidade">
    <caption>Lista de Unidades com Permissão (4 registros):</caption>
    <input type="hidden" id="hdnInfraItens" value="${linhas.map(l => l[0]).join(',')}">
    <table class="infraTable"><tbody>${tr}</tbody></table>
    ${prox}
  </form></body></html>`;
}

/* ================================================================ os casos == */
(async () => {

console.log('A. SEI 4.0, VISAO REDUZIDA — duas tabelas, paginadas separadamente\n');
{
  const pedidos = [];
  const { caixa, saida } = ambiente((url, o) => {
    pedidos.push((o && o.method) || 'GET');
    if (!o || o.method !== 'POST') return null;
    return tela40({ pagRec: o.body.get('hdnRecebidosPaginaAtual') });
  });
  caixa.SEIAuto.perfil(FESF);
  const doc = documento(tela40());
  const lista = await caixa.SEIAuto.listar(doc);

  checar('leu as duas tabelas e as duas paginas de Recebidos (3+1)',
         lista.length === 4, lista.length + ': ' + lista.map(r => r.protocolo).join(', '));
  checar('a linha traz a INSTANCIA do perfil',
         lista.every(r => r.instancia === 'SEI-FESF'),
         JSON.stringify(lista.map(r => r.instancia)));
  checar('e a tela diz de qual lista a linha veio',
         lista.filter(r => r.origem_tabela === 'Recebidos').length === 3
      && lista.filter(r => r.origem_tabela === 'Gerados').length === 1,
         JSON.stringify(lista.map(r => r.origem_tabela)));
  const p1 = lista.find(r => r.id === '4001');
  checar('protocolo e href saem do link do processo',
         p1 && p1.protocolo === '0016.000251/2026-62'
           && /procedimento_trabalhar/.test(p1.href), JSON.stringify(p1 && p1.href));
  checar('processoNaoVisualizado vira visualizado=false',
         p1 && p1.visualizado === false, String(p1 && p1.visualizado));
  checar('atribuicao: texto e o login, `title` e o nome',
         p1 && p1.atribuido_login === 'fulano.um' && p1.atribuido_nome === 'Fulano 1',
         JSON.stringify(p1 && [p1.atribuido_login, p1.atribuido_nome]));
  checar('marcador vem do tooltip e a COR do nome do arquivo do icone',
         p1 && p1.marcador === 'URGENTE' && p1.marcador_cor === 'vermelho',
         JSON.stringify(p1 && [p1.marcador, p1.marcador_cor]));
  checar('anotacao separa texto, autor e data',
         p1 && p1.anotacao === 'Aguardando parecer da PROJUR'
           && p1.anotacao_autor === 'fulano.um' && p1.anotacao_data === '12/08/2026 09:14',
         JSON.stringify(p1 && [p1.anotacao, p1.anotacao_autor, p1.anotacao_data]));
  checar('o icone de exclamacao vira doc_incluido com rotulo',
         p1 && p1.doc_incluido === true && /outra unidade/i.test(p1.doc_incluido_rotulo || ''),
         JSON.stringify(p1 && [p1.doc_incluido, p1.doc_incluido_rotulo]));
  checar('sem aria-label e sem trD, tipo/especificacao saem do tooltip',
         p1 && p1.tipo_processo === 'Administrativo: Pagamento Indenizatorio'
           && p1.especificacao === 'Gil Farma - competencia 07/2026',
         JSON.stringify(p1 && [p1.tipo_processo, p1.especificacao]));
  checar('e o log DIZ que a visao lida foi a reduzida',
         saida.some(l => /visao R/.test(l)), saida.slice(-2).join(' | ').slice(0, 120));
  checar('nenhuma linha ficou sem tipo (o alerta nao dispara a toa)',
         !saida.some(l => /sem tipo\/especificacao/.test(l)));
}

console.log('\nB. SEI 4.0, VISAO DETALHADA PELO ICONE — trD manda no tipo');
{
  const { caixa, saida } = ambiente((url, o) => {
    if (!o || o.method !== 'POST') {
      // O GET so acontece quando o coletor segue o icone.
      return /hdnTipoVisualizacao=D/.test(url) ? tela40({ detalhe: true, comIcone: true }) : null;
    }
    return tela40({ detalhe: true, comIcone: true,
                    pagRec: o.body.get('hdnRecebidosPaginaAtual') });
  });
  caixa.SEIAuto.perfil(FESF);
  const lista = await caixa.SEIAuto.listar(documento(tela40({ comIcone: true })));
  checar('a visao detalhada foi ativada pelo ICONE e registrada como D',
         saida.some(l => /visao D/.test(l)), saida.slice(-1)[0]);
  const p2 = lista.find(r => r.id === '4002');
  checar('tipo e especificacao saem dos pares da linha trD, e nao do tooltip',
         p2 && p2.tipo_processo === 'Gestao de Pessoas: Ferias'
           && p2.especificacao === 'Escala de ferias 2026 (veio do trD)',
         JSON.stringify(p2 && [p2.tipo_processo, p2.especificacao]));
  checar('e a linha de detalhe nao vira processo',
         lista.length === 4, String(lista.length));
}

console.log('\nC. O TOTAL DECLARADO PELA TELA FECHA A CONTA');
{
  const { caixa, saida } = ambiente((url, o) => (o && o.method === 'POST')
    ? tela40({ pagRec: o.body.get('hdnRecebidosPaginaAtual'), declaraRec: 9 }) : null);
  caixa.SEIAuto.perfil(FESF);
  await caixa.SEIAuto.listar(documento(tela40({ declaraRec: 9 })));
  checar('ler menos do que a tela declara vira alerta com a palavra INCOMPLETA',
         saida.some(l => /incompleta/i.test(l) && /declara 9/.test(l)),
         saida.filter(l => /declara/.test(l)).join(' | ').slice(0, 140));
}

console.log('\nD. SELETOR QUE NAO CASA = RECUSA DECLARADA, NUNCA MESA VAZIA');
{
  const quebrada = () => tela40({ tabelaRecebidos: 'tblProcessosRecebidosNOVO' })
    .replace(/id="tblProcessosGerados"/, 'id="tblProcessosGeradosNOVO"');
  const { caixa } = ambiente((url, o) => (o && o.method === 'POST') ? quebrada() : null);
  caixa.SEIAuto.perfil(FESF);
  let subiu = null, lista = null;
  try { lista = await caixa.SEIAuto.listar(documento(quebrada())); }
  catch (e) { subiu = String(e.message || e); }
  checar('lanca em vez de devolver lista vazia',
         subiu !== null && lista === null, String(subiu));
  checar('e a mensagem diz que ha processos na tela',
         /recuso dar a mesa por vazia/.test(subiu || ''), String(subiu));
}

console.log('\nE. MESA SEM PROCESSO NENHUM CONTINUA SENDO MESA VAZIA');
{
  // A conta da SESAB tem 5 mesas assim todo dia: transformar isso em falha
  // seria trocar um modo de falha por outro.
  const vazia = `<html><body id="__body__"><form id="frmProcedimentoControlar" action="${ACAO}">
    <input type="hidden" id="hdnRecebidosNroItens" name="hdnRecebidosNroItens" value="0">
    </form></body></html>`;
  const { caixa, saida } = ambiente((url, o) => (o && o.method === 'POST') ? vazia : null);
  caixa.SEIAuto.perfil(FESF);
  const lista = await caixa.SEIAuto.listar(documento(vazia));
  checar('devolve lista vazia sem lancar', Array.isArray(lista) && lista.length === 0);
  checar('e o log diz que a mesa nao tem processos',
         saida.some(l => /nao tem processos/.test(l)), saida.slice(-2).join(' | '));
}

console.log('\nF. O PARSER DA SESAB (SEI 5.0.4) NAO MUDOU');
{
  const { caixa, saida } = ambiente((url, o) => (o && o.method === 'POST') ? tela50() : null);
  caixa.SEIAuto.perfil(SESAB);
  const lista = await caixa.SEIAuto.listar(documento(tela50()));
  const p = lista[0];
  checar('leu a tabela Detalhada', lista.length === 1, String(lista.length));
  checar('tipo e especificacao continuam saindo do aria-label',
         p && p.tipo_processo === 'Administrativo: Pagamento'
           && p.especificacao === 'Del Mar 06/2026',
         JSON.stringify(p && [p.tipo_processo, p.especificacao]));
  checar('marcador e cor pelo aria-label e pelo .svg',
         p && p.marcador === 'PRIORIDADE' && p.marcador_cor === 'verde_amazonas',
         JSON.stringify(p && [p.marcador, p.marcador_cor]));
  checar('anotacao com autor e data separados',
         p && p.anotacao_autor === 'fulano.dois@saude.ba.gov.br'
           && p.anotacao_data === '22/11/2024 08:41',
         JSON.stringify(p && [p.anotacao_autor, p.anotacao_data]));
  checar('atribuicao pelo td[3]', p && p.atribuido_nome === 'Fulano 2',
         JSON.stringify(p && p.atribuido_nome));
  checar('doc_incluido pelo icone de exclamacao', p && p.doc_incluido === true);
  checar('a instancia padrao e a SESAB', p && p.instancia === 'SEI-SESAB',
         String(p && p.instancia));
  checar('e a visao lida foi a Detalhada', saida.some(l => /visao D/.test(l)),
         saida.slice(-1)[0]);
  checar('na Detalhada a origem NAO vem da tabela (ela consolida as duas listas)',
         p && p.origem_tabela === null, String(p && p.origem_tabela));
}

console.log('\nG. DESCOBRIR MESAS NO 4.0 — title do radio, hdnInfraItens e paginacao');
{
  const doc = {
    getElementById: id => (id === 'lnkInfraUnidade'
      ? { getAttribute: n => (n === 'onclick'
          ? "window.location.href='/sei/controlador.php?acao=infra_trocar_unidade&infra_hash=uu'"
          : null), textContent: 'FESF/DIGAS/HECC' }
      : null),
    querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({ setAttribute() {}, click() {}, remove() {}, style: {} }),
    body: { appendChild() {} },
  };
  const { caixa, saida } = ambiente(
    url => telaUnidades(/hdnInfraPaginaAtual=1/.test(url) ? 1 : 0), { document: doc });
  caixa.SEIAuto.perfil(FESF);
  const mesas = await caixa.SEIAuto.descobrirMesas();
  checar('atravessou as duas paginas da tela de selecao',
         mesas.length === 4, mesas.map(m => m.sigla).join(', '));
  checar('a sigla sai do `title` do proprio radio',
         mesas[0].sigla === 'FESF/DIGAS/HECC' && mesas[0].id === '110000001',
         JSON.stringify(mesas[0]));
  checar('unidade raiz SEM barra entra porque o hdnInfraItens a declara',
         mesas.some(m => m.sigla === 'FESF'), mesas.map(m => m.sigla).join(', '));
  checar('e o total declarado bate — nenhum alerta de mesa fora',
         !saida.some(l => /ficou de fora/.test(l)),
         saida.filter(l => /fora/.test(l)).join(' | '));
}

console.log('\nG2. "PROXIMA" SEM URL VIRA RECUSA DECLARADA');
{
  const doc = {
    getElementById: id => (id === 'lnkInfraUnidade'
      ? { getAttribute: n => (n === 'onclick'
          ? "window.location.href='/sei/controlador.php?acao=infra_trocar_unidade&infra_hash=uu'"
          : null), textContent: 'FESF/DIGAS/HECC' }
      : null),
    querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({ setAttribute() {}, click() {}, remove() {}, style: {} }),
    body: { appendChild() {} },
  };
  const semUrl = telaUnidades(0)
    .replace(/<a href="[^"]*" title="Pr/, '<a onclick="infraPaginar(1)" title="Pr');
  const { caixa, saida } = ambiente(() => semUrl, { document: doc });
  caixa.SEIAuto.perfil(FESF);
  const mesas = await caixa.SEIAuto.descobrirMesas();
  checar('para na primeira pagina', mesas.length === 2, String(mesas.length));
  checar('mas GRITA que pode haver mesa de fora',
         saida.some(l => /ficou de fora/.test(l)),
         saida.filter(l => /fora|declara/.test(l)).join(' | ').slice(0, 140));
  checar('e o total declarado tambem acusa (2 de 4)',
         saida.some(l => /declara 4 unidade/.test(l)),
         saida.filter(l => /declara/.test(l)).join(' | '));
}

console.log('\nH. A INSTANCIA CHEGA AO JSON EXPORTADO');
{
  const { caixa, guardado, saida } = ambiente(() => null);
  caixa.SEIAuto.perfil(FESF);
  guardado['__SEI_DATAS'] = JSON.stringify({
    '4001': { autuacao: '01/07/2026 10:00', mov_custodia: [], mesa_derivada: 'FESF/DIGAS/HECC' },
  });
  const saidaJson = caixa.SEIAuto.exportar([
    { id: '4001', protocolo: '0016.000251/2026-62', mesa_coleta: 'FESF/DIGAS/HECC',
      instancia: 'SEI-FESF', origem_tabela: 'Recebidos' },
  ]);
  checar('cada processo exportado carrega a instancia',
         saidaJson[0].instancia === 'SEI-FESF', JSON.stringify(saidaJson[0].instancia));
  checar('e a origem vem da TABELA, nao da derivacao',
         saidaJson[0].origem === 'Recebidos' && !('origem_tabela' in saidaJson[0]),
         JSON.stringify([saidaJson[0].origem, 'origem_tabela' in saidaJson[0]]));
  void saida;
}

console.log('\nI. SEM PERFIL, TUDO CONTINUA SENDO A SESAB');
{
  const { caixa } = ambiente(() => null);
  checar('a instancia padrao e SEI-SESAB',
         caixa.SEIAuto.instanciaAtual() === 'SEI-SESAB',
         caixa.SEIAuto.instanciaAtual());
  checar('e um perfil sem instancia nao substitui o padrao',
         caixa.SEIAuto.perfil({ versao: '4.0.x' }).instancia === 'SEI-SESAB');
}

console.log('\n' + '='.repeat(62));
console.log(ok + ' ok, ' + mau + ' falha(s)');
process.exit(mau ? 1 : 0);

})().catch(e => { console.log('ERRO NO TESTE: ' + (e && e.stack || e)); process.exit(1); });
