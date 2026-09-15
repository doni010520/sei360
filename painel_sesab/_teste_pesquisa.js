/* O motor da busca, exercitado sem navegador e sem SEI.

   O que dá para provar aqui: a montagem do POST a partir do formulário vivo, a
   lista de ids com alternativas (a mesma regra atravessando o SEI 4.0 e o 5.0.4),
   a recusa DECLARADA de filtro que não casa, a leitura do total declarado, a
   extração das linhas e a codificação ISO-8859-1 do corpo.

   O que NÃO dá para provar aqui, e fica dito: que os nomes de campo abaixo são os
   da tela real de Pesquisa de cada instância. Os do SEI 4.0 vêm do sistema irmão
   desta casa, que os exercitou contra a FESF; os do 5.0.4 são a mesma família com
   o sufixo `Pesquisa` e NÃO foram vistos na tela da SESAB. Enquanto não forem, o
   perfil marca `busca_ids_medidos: false` e a recusa aparece na tela de quem buscou.

   node _teste_pesquisa.js
*/
const fs = require('fs'), path = require('path'), vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, 'pesquisa_sei.js'), 'utf8');
const { JSDOM } = (() => { try { return require('jsdom'); } catch { return {}; } })();

/* Sem jsdom no ambiente: um DOM mínimo, escrito à mão, que é o bastante para as
   funções puras. Prefiro isto a pular o teste — teste que não roda não prova nada. */
function domSimples(html) {
  const doc = { _html: html };
  const tags = {};
  // parser bobo, suficiente para o fixture: id="x" e name="x"
  const el = (m) => {
    const attr = n => (m.match(new RegExp(n + '="([^"]*)"')) || [])[1];
    const tag = (m.match(/^<(\w+)/) || [])[1] || '';
    return {
      _m: m, tagName: tag.toUpperCase(), id: attr('id') || '', name: attr('name') || '',
      value: attr('value') || '', type: attr('type') || (tag === 'select' ? 'select-one' : 'text'),
      checked: /checked/.test(m),
      getAttribute: n => attr(n) || null,
      options: null, selectedIndex: 0,
    };
  };
  const achados = html.match(/<(input|select|textarea|a|button)[^>]*>/g) || [];
  const elementos = achados.map(el);
  // options dos selects
  const selects = html.match(/<select[\s\S]*?<\/select>/g) || [];
  selects.forEach(bloco => {
    const idm = (bloco.match(/id="([^"]*)"/) || [])[1];
    const alvo = elementos.find(e => e.id === idm && e.tagName === 'SELECT');
    if (!alvo) return;
    alvo.options = (bloco.match(/<option[^>]*>[^<]*<\/option>/g) || []).map(o => ({
      value: (o.match(/value="([^"]*)"/) || [])[1] || '',
      text: o.replace(/<[^>]*>/g, ''),
    }));
    alvo.selectedIndex = 0;
  });
  tags.elementos = elementos;
  doc.getElementById = id => elementos.find(e => e.id === id) || null;
  doc.querySelector = sel => {
    const m = sel.match(/^#([\w-]+)$/);
    if (m) return doc.getElementById(m[1]);
    const nm = sel.match(/\[name="([^"]+)"\]/);
    if (nm) return elementos.find(e => e.name === nm[1]) || null;
    if (sel.startsWith('form')) return doc.forms[0];
    return null;
  };
  doc.querySelectorAll = () => ({ forEach: f => elementos.forEach(f) });
  const form = {
    getAttribute: n => n === 'action' ? '/controlador.php?acao=protocolo_pesquisar' : null,
    querySelectorAll: () => elementos.filter(e => ['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName)),
  };
  form.querySelectorAll = (() => {
    const lista = elementos.filter(e => ['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName));
    return () => ({ forEach: f => lista.forEach(f) });
  })();
  doc.forms = [form];
  doc.body = { textContent: html.replace(/<[^>]*>/g, ' ') };
  return doc;
}

const caixa = { console, TextDecoder, window: {}, document: { getElementById: () => null },
                fetch: () => { throw new Error('sem rede no teste'); },
                DOMParser: function () {}, setTimeout, Date, Math, JSON, location: { href: '/' } };
caixa.window = caixa;
vm.createContext(caixa);
vm.runInContext(src, caixa);
const B = caixa.SEIBusca;

let ok = 0, mau = 0;
const checar = (n, c, v) => { if (c) { ok++; console.log('  ok   ' + n); }
  else { mau++; console.log('  FALHA ' + n + (v ? '  -> ' + v : '')); } };

const CAMPOS = {
  modo_processos: ['optProcessos', 'input[name="rdoPesquisarEm"][value="P"]'],
  tramitacao_unidade: ['chkSinTramitacao', 'chkSinTramitacaoUnidade'],
  tipo_processo: ['selTipoProcedimentoPesquisa', 'selTipoProcedimento'],
  especificacao: ['txtDescricaoPesquisa', 'txtDescricao'],
  contato: ['txtContato', 'txtContatoPesquisa'],
  assunto: ['txtAssunto', 'txtAssuntoPesquisa'],
  observacao: ['txtObservacaoPesquisa', 'txtObservacao'],
  numero_sei: ['txtProtocoloPesquisa', 'txtProtocolo'],
  data_de: ['txtDataInicio'], data_ate: ['txtDataFim'], tipo_data: ['selData'],
  enviar: ['sbmPesquisar'],
};

/* SEI 5.0.4: nomes com o sufixo `Pesquisa`. */
const HTML_5 = `
<form id="frmProtocoloPesquisa" action="/controlador.php?acao=protocolo_pesquisar">
  <input type="hidden" name="hdnFlag" value="1">
  <input type="radio" id="optProcessos" name="rdoPesquisarEm" value="P">
  <input type="checkbox" id="chkSinTramitacao" name="chkSinTramitacao" value="S">
  <select id="selTipoProcedimentoPesquisa" name="selTipoProcedimentoPesquisa">
    <option value="">Todos</option>
    <option value="12">Dispensa: Menor Valor/Emergencial</option>
    <option value="30">Contratação Direta</option>
  </select>
  <input type="text" id="txtDescricaoPesquisa" name="txtDescricaoPesquisa" value="">
  <input type="text" id="txtContato" name="txtContato" value="">
  <input type="text" id="txtAssunto" name="txtAssunto" value="">
  <input type="text" id="txtObservacaoPesquisa" name="txtObservacaoPesquisa" value="">
  <input type="text" id="txtProtocoloPesquisa" name="txtProtocoloPesquisa" value="">
  <input type="text" id="txtDataInicio" name="txtDataInicio" value="">
  <input type="text" id="txtDataFim" name="txtDataFim" value="">
  <select id="selData" name="selData"><option value="I">Inclusao</option><option value="G">Processo</option></select>
  <input type="submit" id="sbmPesquisar" name="sbmPesquisar" value="Pesquisar">
</form>`;

/* SEI 4.0: sem o sufixo, e sem o campo de observação. */
const HTML_4 = HTML_5
  .replace(/txtDescricaoPesquisa/g, 'txtDescricao')
  .replace(/selTipoProcedimentoPesquisa/g, 'selTipoProcedimento')
  .replace(/chkSinTramitacao"/g, 'chkSinTramitacaoUnidade"')
  .replace(/id="chkSinTramitacao"/, 'id="chkSinTramitacaoUnidade"')
  .replace(/<input type="text" id="txtObservacaoPesquisa"[^>]*>/, '');

console.log('A MESMA REGRA ATRAVESSA AS DUAS VERSOES DO SEI\n');
for (const [nome, html] of [['SEI 5.0.4', HTML_5], ['SEI 4.0', HTML_4]]) {
  const doc = domSimples(html);
  const m = B.montar(doc, CAMPOS, {
    tramitacao_unidade: true, especificacao: 'Gil Farma',
    tipo_processo: 'contratação direta', tipo_data: 'I',
    data_de: '01/05/2026', data_ate: '20/08/2026',
  });
  const val = k => (m.pares.find(x => x[0] === k) || [])[1];
  console.log(' ' + nome);
  checar('  a especificacao chega ao campo certo',
         val('txtDescricaoPesquisa') === 'Gil Farma' || val('txtDescricao') === 'Gil Farma',
         JSON.stringify(m.pares.slice(0, 4)));
  checar('  a caixa de tramitacao entra no POST',
         !!(val('chkSinTramitacao') || val('chkSinTramitacaoUnidade')));
  checar('  o tipo casa SEM depender de maiuscula',
         m.aplicados.tipo_processo === 'Contratação Direta', JSON.stringify(m.aplicados));
  checar('  as datas vao junto',
         val('txtDataInicio') === '01/05/2026' && val('txtDataFim') === '20/08/2026');
  checar('  os hidden do formulario vivo sobrevivem', val('hdnFlag') === '1');
}

console.log('\nFILTRO QUE NAO CASA E RECUSADO, NAO SILENCIADO');
{
  const doc = domSimples(HTML_4);
  const m = B.montar(doc, CAMPOS, { observacao: 'algo', tipo_processo: 'inexistente' });
  const camposRec = m.recusados.map(r => r.campo);
  checar('campo ausente nesta versao vira recusa',
         camposRec.includes('observacao'), JSON.stringify(m.recusados));
  checar('tipo que nao casa com opcao nenhuma vira recusa',
         camposRec.includes('tipo_processo'), JSON.stringify(m.recusados));
  checar('e a recusa diz quantas opcoes foram vistas',
         (m.recusados.find(r => r.campo === 'tipo_processo') || {}).options_vistas === 3,
         JSON.stringify(m.recusados));
  checar('o valor recusado NAO entra no POST',
         !m.pares.some(x => x[1] === 'inexistente'));
}

console.log('\nO TOTAL DECLARADO PELO SEI');
for (const [txt, esperado] of [
  ['<div>Lista de Processos (607 registros):</div>', 607],
  ['<p>1.133 registros encontrados</p>', 1133],
  ['<p>Encontrados 42 registros</p>', 42],
  ['<p>Nada por aqui</p>', null],
  // A pesquisa que nao acha nada TEM total: zero. Nulo aqui virava 'falhou'.
  ['<p>Nenhum registro encontrado.</p>', 0],
  ['<td>Nenhum resultado foi localizado</td>', 0],
]) {
  checar(`"${txt.replace(/<[^>]*>/g, '').trim().slice(0, 34)}" -> ${esperado}`,
         B.totalDeclarado(domSimples(txt)) === esperado,
         String(B.totalDeclarado(domSimples(txt))));
}

console.log('\nO CORPO VAI EM ISO-8859-1');
{
  const c = B.corpoLatin1([['txtDescricao', 'Licitação'], ['x', 'a b']]);
  checar('acento vira %E7%E3 (Latin-1), nao %C3%A7 (UTF-8)',
         c.includes('%E7%E3') && !c.includes('%C3%A7'), c);
  checar('espaco vira +', c.includes('a+b'), c);
  checar('e o acento NAO e removido do termo', !/Licitacao/.test(c), c);
}

console.log('\nFALHA PASSAGEIRA GANHA NOVA TENTATIVA; SESSAO CAIDA NAO');
(async () => {
  let n = 0;
  const volta = await B.comRetentativa('teste', async () => {
    n++;
    if (n < 3) throw new Error('Failed to fetch');
    return 'ok';
  });
  checar('duas quedas de rede e a terceira passa', volta === 'ok' && n === 3, `${volta} ${n}`);
  let m = 0, lancou = null;
  try {
    await B.comRetentativa('teste', async () => { m++; throw new Error('SESSAO caiu durante a busca'); });
  } catch (e) { lancou = e.message; }
  checar('sessao caida NAO e repetida (uma tentativa so)', m === 1 && /SESSAO/.test(lancou), `${m} ${lancou}`);
  let k = 0, fim = null;
  try {
    await B.comRetentativa('teste', async () => { k++; throw new Error('o SEI respondeu 502'); });
  } catch (e) { fim = e.message; }
  checar('falha que persiste desiste depois de 3 tentativas e diz o motivo',
         k === 3 && /502/.test(fim), `${k} ${fim}`);
  // "Failed to fetch" com a pagina redirecionando para o login: sessao caida disfarcada.
  caixa.fetch = async () => ({ type: 'opaqueredirect', status: 0 });
  let q = 0, virou = null;
  try {
    await B.comRetentativa('teste', async () => { q++; throw new TypeError('Failed to fetch'); });
  } catch (e) { virou = e.message; }
  checar('Failed to fetch com a sessao morta vira SESSAO caiu, sem repetir',
         q === 1 && /SESSAO/.test(virou), `${q} ${virou}`);
  caixa.fetch = () => { throw new Error('sem rede no teste'); };
  console.log(`\n${ok} verificacoes, ${mau} falha(s)`);
  process.exit(mau ? 1 : 0);
})();
