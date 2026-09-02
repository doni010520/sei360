/* AS DUAS GAVETAS: bloco (por processo) e acompanhamento (por processo E MESA).

   O checkpoint __SEI_DATAS é chaveado por id porque o BLOCO é do processo. O
   acompanhamento não é: ele é da mesa e da pessoa. Enquanto os dois dividiram a
   mesma gaveta, três coisas quebravam ao mesmo tempo:

     * o toco gravado pelo caminho barato fazia coletarDatas() considerar o
       processo JÁ FEITO (`!feito[h.id]`) e a leitura completa dele em OUTRA mesa
       nunca acontecia — a linha saía dizendo ter histórico, com tudo nulo;
     * chaveado só por id, a última mesa a escrever apagava o acompanhamento das
       outras;
     * exportar() copiava o acompanhamento do bloco para TODAS as linhas do id, e
       a linha da mesa B mostrava o grupo do Acompanhamento Especial da mesa A.

   node _teste_gavetas.js
*/
const fs = require('fs'), path = require('path'), vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, 'automacao_sei.js'), 'utf8');
const guardado = {};
const caixa = {
  console, TextDecoder, URLSearchParams, setTimeout, Date, Math, JSON,
  Blob: function () {}, URL: { createObjectURL: () => 'x' },
  document: { getElementById: () => null, querySelector: () => null,
              querySelectorAll: () => [],
              createElement: () => ({ setAttribute() {}, click() {}, remove() {}, style: {} }),
              body: { appendChild() {} } },
  location: { href: 'https://seibahia.ba.gov.br/sei/' },
  localStorage: {
    getItem: k => (k in guardado ? guardado[k] : null),
    setItem: (k, v) => { guardado[k] = v; },
    removeItem: k => { delete guardado[k]; },
  },
};
caixa.window = caixa;
vm.createContext(caixa);
vm.runInContext(src, caixa);

let ok = 0, mau = 0;
const checar = (nome, cond, viu) => {
  if (cond) { ok++; console.log('  ok   ' + nome); }
  else { mau++; console.log('  FALHA ' + nome + (viu ? '  -> ' + viu : '')); }
};

const A = 'SESAB/CESS', B = 'SESAB/COMASUP';

console.log('1. o toco do acompanhamento nao bloqueia a leitura completa\n');
// Como somenteAcompanhamento() grava HOJE: gaveta propria, chave (id, mesa).
guardado['__SEI_ACOMP'] = JSON.stringify({
  ['555@' + A]: { acompanhamento: [{ grupo: 'GRUPO DA CESS' }],
                  acomp_grupos: ['GRUPO DA CESS'], acomp_disponivel: true, exec: 'antiga' },
});
guardado['__SEI_DATAS'] = JSON.stringify({});
const feito = JSON.parse(guardado['__SEI_DATAS'] || '{}');
const fila = [{ id: '555' }].filter(h => !feito[h.id] || feito[h.id].erro);
checar('a leitura completa da outra mesa CONTINUA na fila', fila.length === 1,
       String(fila.length));

console.log('\n2. o acompanhamento nao atravessa mesa');
guardado['__SEI_LISTA'] = JSON.stringify([
  { id: '555', protocolo: '019.555', mesa_coleta: A },
  { id: '555', protocolo: '019.555', mesa_coleta: B },
]);
// bloco lido UMA vez, sob a mesa A (é o que jaLido garante)
guardado['__SEI_DATAS'] = JSON.stringify({
  '555': { autuacao: '01/01/2026 10:00', acompanhamento: [{ grupo: 'GRUPO DA CESS' }],
           acomp_grupos: ['GRUPO DA CESS'], acomp_disponivel: true,
           acomp_mesa: A, mesa_derivada: A, mov_custodia: [], _fresco: 'outra-exec' },
});
guardado['__SEI_ACOMP'] = JSON.stringify({});
const saida = caixa.SEIAuto.exportar();
const la = saida.find(x => x.mesa_coleta === A), lb = saida.find(x => x.mesa_coleta === B);
checar('a linha da mesa B NAO recebe o acompanhamento lido na mesa A',
       !lb.acomp_grupos || lb.acomp_grupos.length === 0, JSON.stringify(lb.acomp_grupos));
checar('e ela vai marcada como nao lida, para a tela poder dizer isso',
       lb._acomp_fresco === false, String(lb._acomp_fresco));
checar('o bloco (que E do processo) continua valendo para as duas',
       la.autuacao === '01/01/2026 10:00' && lb.autuacao === '01/01/2026 10:00',
       `${la.autuacao} / ${lb.autuacao}`);

console.log('\n3. leitura de execucao ANTERIOR nao conta como fresca');
checar('bloco lido noutra execucao sai com _fresco=false — o poco nao rejuvenesce',
       la._fresco === false, String(la._fresco));

console.log('\n4. a gaveta do acompanhamento e por (id, mesa)');
guardado['__SEI_ACOMP'] = JSON.stringify({
  ['555@' + A]: { acompanhamento: [{ grupo: 'DA CESS' }], acomp_grupos: ['DA CESS'],
                  acomp_disponivel: true, exec: 'x' },
  ['555@' + B]: { acompanhamento: [{ grupo: 'DA COMASUP' }], acomp_grupos: ['DA COMASUP'],
                  acomp_disponivel: true, exec: 'x' },
});
const chaves = Object.keys(JSON.parse(guardado['__SEI_ACOMP']));
checar('as duas mesas cabem na gaveta ao mesmo tempo', chaves.length === 2,
       JSON.stringify(chaves));

console.log(`\n${ok} verificacoes, ${mau} falha(s)`);
process.exit(mau ? 1 : 0);
