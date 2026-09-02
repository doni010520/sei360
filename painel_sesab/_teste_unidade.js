/* A CONTA TEM DE VOLTAR PARA A UNIDADE DE ORIGEM — em toda saída.

   A coleta troca a unidade ativa da sessão nominal da titular a cada mesa e fica
   ~15 min fora da unidade dela. Quem estiver com o SEI aberto naquele momento vê
   a tela CONGELADA na unidade antiga (o DOM vivo não acompanha a troca por
   fetch — ver o comentário de `DOC_ATUAL`), clica nela, e o POST sai com
   `infra_unidade_atual` da unidade errada: ato praticado na unidade errada, em
   nome de pessoa nomeada, dentro da trilha de auditoria do SEI.

   Medido em 27/08/2026, no dado já colhido: as 13 execuções com dados de 13/08 a
   27/08 terminaram TODAS em SESAB/SAIS/DGGUP/UMA-CMA, uma mesa onde a titular
   praticou ZERO atos nos 31 meses anteriores (contra 43 na CESS e 38 na
   COMASUP). A causa é que `ORIGEM` era lida do DOM VIVO — isto é, do resíduo da
   coleta de ontem: a restauração "restaurava" para o desvio e o confirmava todo
   dia, com EXIT=0 e sem uma linha de log.

   O SERVIDOR DESTE TESTE MORA FORA DO REALM DO `vm`. É o análogo do estado preso
   ao cookie: o script sob teste não consegue "restaurar" mexendo numa variável
   dele mesmo — ele precisa mesmo emitir o POST de troca. E o `automacao_sei.js`
   é embrulhado, então não há como trocar função interna: tudo aqui é dirigido
   pelas MESMAS portas que a produção usa (fetch, DOM, localStorage).

   node _teste_unidade.js
*/
const fs = require('fs'), path = require('path'), vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, 'automacao_sei.js'), 'utf8');

const ORIGEM_REAL = 'SESAB/SAIS/DGGUP/DGESS';
const DESVIO = 'SESAB/SAIS/DGGUP/UMA-CMA';
const MESAS = [
  { id: '110000001', sigla: 'SESAB/SAIS/DGGUP/DGESS' },
  { id: '110000002', sigla: 'SESAB/SAIS/DGGUP/DGESS/CESS' },
  { id: '110000003', sigla: 'SESAB/SAIS/DGGUP/DGESS/COMASUP' },
  { id: '110000004', sigla: 'SESAB/SAIS/DGGUP/UMA-CMA' },
];

let ok = 0, mau = 0;
const checar = (nome, cond, viu) => {
  if (cond) { ok++; console.log('  ok    ' + nome); }
  else { mau++; console.log('  FALHA ' + nome + (viu !== undefined ? '  -> ' + viu : '')); }
};

/* ------------------------------------------------------------------ o servidor
   Fora do vm, como o estado da sessão fica fora do navegador. `morrerApos` deixa
   a sessão cair num ponto escolhido — é o único jeito honesto de simular queda
   num arquivo embrulhado. */
function novoServidor(unidadeInicial, opc = {}) {
  return {
    unidade: unidadeInicial, viva: true, trocas: [], req: 0,
    mesas: MESAS.slice(),
    morrerApos: opc.morrerApos || 0,
    postDesobedece: !!opc.postDesobedece,
    semSeletor: !!opc.semSeletor,
    // Quantas voltas para a origem o servidor ainda vai RECUSAR (soluco), e se o
    // localStorage ja estourou a cota.
    recusarVoltas: opc.recusarVoltas || 0,
    // A recusa so vale DEPOIS de N trocas. Sem isto ela era gasta na primeira
    // troca do laco, porque a origem e a primeira mesa da conta — e o caso
    // testado deixava de ser o da volta.
    recusarApos: opc.recusarApos || 0,
    origem: opc.origem || null,
    cotaEstourada: !!opc.cotaEstourada,
  };
}

/* --------------------------------------------------------------- os documentos
   Não parseia HTML: despacha sobre uma string-token. O que importa é o CONTRATO
   que automacao_sei.js exige de um documento, não o parser. */
const el = p => Object.assign({ getAttribute: () => null, querySelector: () => null,
                                querySelectorAll: () => [] }, p);

const ONCLICK = "infraAbrirJanela('controlador.php?acao=infra_unidade_alterar"
              + "&id_orgao=23&infra_hash=abc','x')";

const linkUnidade = (sigla, comOnclick = true) => el({
  textContent: sigla,
  getAttribute: n => (n === 'onclick' && comOnclick ? ONCLICK : null),
});

const formControlar = () => el({
  getAttribute: n => (n === 'action' ? '/sei/controlador.php?acao=procedimento_controlar' : null),
  querySelectorAll: sel => (/input,select/.test(sel) ? [] : []),
});

function documento(token, srv) {
  const sigla = token.startsWith('CONTROLE:') ? token.slice(9) : null;
  return {
    getElementById(id) {
      if (sigla) {
        if (id === 'lnkInfraUnidade') return linkUnidade(sigla, !srv.semSeletor);
        if (id === 'lnkControleProcessos') return el({});
        if (id === 'frmProcedimentoControlar') return formControlar();
      }
      if (id === 'frmInfraSelecaoUnidade' && token === 'TROCA') {
        return el({ getAttribute: n => (n === 'action' ? '/sei/controlador.php?acao=troca' : null) });
      }
      return null;
    },
    querySelector: () => null,
    querySelectorAll(sel) {
      if (token === 'TROCA' && /chkInfraItem/.test(sel)) {
        return srv.mesas.map(m => el({
          value: m.id,
          closest: () => ({
            querySelectorAll: () => [el({ textContent: '' }), el({ textContent: m.sigla }),
                                     el({ textContent: 'desc' })],
          }),
        }));
      }
      return [];                       // nenhuma linha de processo: a lista sai vazia
    },
  };
}

/* ------------------------------------------------------------------- o ambiente */
function montar(srv) {
  const guardado = {};
  const avisos = [];
  const caixa = {
    console: { log: (...a) => avisos.push(a.join(' ')) },
    TextDecoder: function () { this.decode = x => x; },
    URLSearchParams, setTimeout, clearInterval, setInterval, Date, Math, JSON,
    Blob: function () {}, URL: { createObjectURL: () => 'x' },
    FormData: function () { this[Symbol.iterator] = function* () { yield ['hdn', '1']; }; },
    DOMParser: function () { this.parseFromString = s => documento(s, srv); },
    // O DOM VIVO CONGELA na unidade de t0. É o defeito que este teste cerca: ele
    // NUNCA reflete as trocas feitas por fetch.
    document: (() => {
      const t0 = srv.unidade;
      return {
        getElementById: id => (id === 'lnkInfraUnidade' ? linkUnidade(t0, !srv.semSeletor)
                             : id === 'lnkControleProcessos' ? el({})
                             : id === 'frmProcedimentoControlar' ? formControlar() : null),
        querySelector: () => null, querySelectorAll: () => [],
        createElement: () => ({ setAttribute() {}, click() {}, remove() {}, style: {} }),
        body: { appendChild() {} },
      };
    })(),
    location: { href: 'https://seibahia.ba.gov.br/sei/' },
    localStorage: {
      getItem: k => (k in guardado ? guardado[k] : null),
      setItem: (k, v) => {
        if (srv.cotaEstourada && k === '__SEI_LISTA') {
          throw new Error('QuotaExceededError');   // 5,48 MB contra 10 MB de cota
        }
        guardado[k] = v;
      },
      removeItem: k => { delete guardado[k]; },
    },
    async fetch(url, o) {
      srv.req++;
      if (srv.morrerApos && srv.req > srv.morrerApos) srv.viva = false;
      if (!srv.viva) {
        return { url: 'https://seibahia.ba.gov.br/sei/login.php', arrayBuffer: async () => 'LOGIN' };
      }
      if (o && o.method === 'POST') {
        const id = o.body && o.body.get && o.body.get('selInfraUnidades');
        let m = id && srv.mesas.find(x => x.id === id);
        // O servidor RECUSA as primeiras voltas para a origem: soluco transitorio,
        // que e o caso em que a segunda tentativa do `finally` vale alguma coisa.
        if (m && srv.origem && m.sigla === srv.origem && srv.recusarVoltas > 0
            && srv.trocas.length >= srv.recusarApos) {
          srv.recusarVoltas--;
          m = null;
        }
        if (m) {
          srv.unidade = srv.postDesobedece ? DESVIO : m.sigla;
          srv.trocas.push(srv.unidade);
        }
        return { url, arrayBuffer: async () => 'CONTROLE:' + srv.unidade };
      }
      if (/infra_unidade_alterar/.test(url)) return { url, arrayBuffer: async () => 'TROCA' };
      return { url, arrayBuffer: async () => 'CONTROLE:' + srv.unidade };
    },
  };
  caixa.window = caixa;
  vm.createContext(caixa);
  vm.runInContext(SRC, caixa);
  // O carimbo é lido pelo MESMO canal que o coletor lê: o inventário persistido.
  const inv = () => JSON.parse(guardado['__SEI_INV'] || 'null');
  return { caixa, inv, avisos, guardado };
}

const gritou = av => av.some(t => /unidade/i.test(t) && /falh|nao volt|nao consig|fora/i.test(t));

/* ============================================================== os casos ==== */
(async () => {

console.log('C0. a origem e DECLARADA, nao herdada do DOM vivo');
{
  const srv = novoServidor(DESVIO);            // a conta amanheceu no desvio de ontem
  const { caixa, inv } = montar(srv);
  await caixa.SEIAuto.rodarTodasAsMesas({ origem: ORIGEM_REAL });
  checar('a conta termina na unidade DECLARADA, nao onde amanheceu',
         srv.unidade === ORIGEM_REAL, srv.unidade);
  checar('o inventario carimba a origem declarada',
         (inv() || {}).unidade_origem === ORIGEM_REAL, JSON.stringify(inv()));
  checar('e diz que restaurou', (inv() || {}).restaurada === true,
         JSON.stringify(inv() && { f: inv().unidade_final, r: inv().restaurada }));
}

console.log('\nC1. origem declarada que nao existe na conta ABORTA antes de deslocar');
{
  const srv = novoServidor(ORIGEM_REAL);
  const { caixa, avisos } = montar(srv);
  const r = await caixa.SEIAuto.listarTodasAsMesas({ origem: 'SESAB/NAO/EXISTE' });
  checar('nao devolve lista', !r, JSON.stringify(r && Object.keys(r)));
  checar('e NAO deslocou a conta nenhuma vez', srv.trocas.length === 0, srv.trocas.join(' > '));
  checar('a conta continua onde estava', srv.unidade === ORIGEM_REAL, srv.unidade);
  checar('e alguem foi avisado', avisos.some(t => /origem/i.test(t)), avisos.length + ' log(s)');
}

console.log('\nC2. so a listagem (modo --plano) tambem devolve a conta');
{
  const srv = novoServidor(ORIGEM_REAL);
  const { caixa } = montar(srv);
  await caixa.SEIAuto.listarTodasAsMesas({ origem: ORIGEM_REAL });
  checar('percorreu as mesas (o caso exercita algo)', srv.trocas.length >= 3,
         srv.trocas.length + ' trocas');
  checar('e a metade 1 nao deixa a conta na ultima mesa',
         srv.unidade === ORIGEM_REAL, srv.unidade);
}

console.log('\nC3. queda de sessao no meio: a excecao SESSAO continua subindo');
{
  const srv = novoServidor(ORIGEM_REAL, { morrerApos: 6 });
  const { caixa } = montar(srv);
  let subiu = null;
  try { await caixa.SEIAuto.rodarTodasAsMesas({ origem: ORIGEM_REAL }); }
  catch (e) { subiu = String(e); }
  checar('nenhuma excecao de restauracao substitui a original',
         subiu === null || /SESSAO/.test(subiu), String(subiu));
}

console.log('\nC4. sessao morta na volta: a falha nao pode ser muda');
{
  const srv = novoServidor(DESVIO, { morrerApos: 14 });
  const { caixa, inv, avisos } = montar(srv);
  await caixa.SEIAuto.rodarTodasAsMesas({ origem: ORIGEM_REAL }).catch(() => {});
  checar('o inventario NAO afirma ter restaurado',
         !(inv() || {}).restaurada, String((inv() || {}).restaurada));
  checar('e o log grita que a conta pode ter ficado fora', gritou(avisos),
         avisos.slice(-2).join(' | ').slice(0, 110) || '(nada)');
}

console.log('\nC5. POST da restauracao que cai noutra unidade tem de gritar');
{
  const srv = novoServidor(ORIGEM_REAL, { postDesobedece: true });
  const { caixa, inv, avisos } = montar(srv);
  await caixa.SEIAuto.rodarTodasAsMesas({ origem: ORIGEM_REAL });
  checar('o inventario NAO diz que restaurou', !(inv() || {}).restaurada,
         String((inv() || {}).restaurada));
  checar('e o log avisa', gritou(avisos), avisos.slice(-2).join(' | ').slice(0, 110) || '(nada)');
}

console.log('\nC6. o finally da metade 1 e a SEGUNDA CHANCE da volta');
{
  // A volta falha uma vez e, logo depois, o checkpoint estoura a cota do
  // localStorage. Sem o `finally`, a excecao sobe com a conta deslocada.
  const srv = novoServidor(ORIGEM_REAL, {
    recusarVoltas: 1, recusarApos: MESAS.length,   // so a VOLTA e recusada
    cotaEstourada: true, origem: ORIGEM_REAL,
  });
  const { caixa } = montar(srv);
  let subiu = null;
  try { await caixa.SEIAuto.listarTodasAsMesas({ origem: ORIGEM_REAL }); }
  catch (e) { subiu = String(e); }
  checar('a excecao da cota continua subindo (nao e engolida)',
         subiu !== null && /Quota/.test(subiu), String(subiu));
  checar('mas a conta VOLTOU mesmo assim, na segunda tentativa',
         srv.unidade === ORIGEM_REAL, srv.unidade);
}

console.log('\nC7. o mesmo, na METADE 2 — que e onde a conta terminava deslocada');
{
  const srv = novoServidor(ORIGEM_REAL, {
    recusarVoltas: 1, recusarApos: 2, cotaEstourada: true, origem: ORIGEM_REAL,
  });
  const { caixa, guardado } = montar(srv);
  // A metade 2 le a lista do localStorage: semear e o suficiente para ela ter
  // mesas a visitar, e nenhuma linha de processo precisa existir no DOM.
  guardado['__SEI_LISTA'] = JSON.stringify([
    { id: '1', mesa_coleta: 'SESAB/SAIS/DGGUP/DGESS/CESS' },
    { id: '2', mesa_coleta: 'SESAB/SAIS/DGGUP/UMA-CMA' },
  ]);
  let subiu = null;
  try { await caixa.SEIAuto.detalharTodasAsMesas({}, { origem: ORIGEM_REAL }); }
  catch (e) { subiu = String(e); }
  checar('a metade 2 chegou a deslocar a conta', srv.trocas.length >= 2,
         srv.trocas.join(' > ') || 'nenhuma');
  checar('a excecao continua subindo', subiu !== null, String(subiu));
  checar('e a conta VOLTOU pelo finally da metade 2',
         srv.unidade === ORIGEM_REAL, srv.unidade);
}

console.log('\n' + '='.repeat(62));
console.log(ok + ' ok, ' + mau + ' falha(s)');
process.exit(mau ? 1 : 0);

})();
