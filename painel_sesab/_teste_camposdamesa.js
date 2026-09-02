/* Prova, em node, que os cinco campos por mesa saem CERTOS para cada mesa.

   E o teste T3 do desenho: o mesmo processo, aberto em duas unidades, tem de
   devolver o recebimento de CADA uma — nunca o de uma delas nas duas.

   Roda sem navegador: carrega automacao_sei.js com um `document` de mentira e
   chama SEIAuto.camposDaMesa direto. `node _teste_camposdamesa.js`
*/
const fs = require('fs'), path = require('path'), vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, 'automacao_sei.js'), 'utf8');
const caixa = {
  console, TextDecoder, URLSearchParams, setTimeout, Date, Math, JSON,
  document: { getElementById: () => null, querySelector: () => null,
              querySelectorAll: () => [], createElement: () => ({}) },
  location: { href: 'https://seibahia.ba.gov.br/sei/' },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
};
caixa.window = caixa;
vm.createContext(caixa);
vm.runInContext(src, caixa);
const { camposDaMesa } = caixa.SEIAuto;

let ok = 0, mau = 0;
const checar = (nome, cond, viu) => {
  if (cond) { ok++; console.log('  ok   ' + nome); }
  else { mau++; console.log('  FALHA ' + nome + '  -> ' + viu); }
};

// Historico como o SEI entrega: mais NOVO primeiro.
const mov = [
  { dh: '19/08/2026 07:30', un: 'COMASUP', us: 'ana.souza',
    de: 'Processo recebido na unidade' },
  { dh: '18/08/2026 16:10', un: 'CESS', us: 'willian.damascena',
    de: 'Processo remetido pela unidade CESS' },
  { dh: '07/08/2026 15:39', un: 'CESS', us: 'willian.damascena',
    de: 'Processo recebido na unidade' },
  { dh: '28/07/2025 08:58', un: 'ASTEC', us: 'joao.lima',
    de: 'Processo publico gerado' },
];

console.log('T3 — recalculo por mesa, nao copia');
const cess = camposDaMesa(mov, 'CESS');
checar('CESS recebe em 07/08 e quem recebeu foi willian.damascena',
       cess.marco_unidade === '07/08/2026 15:39' &&
       cess.recebimento_por === 'willian.damascena', JSON.stringify(cess));
checar('CESS remeteu em 18/08 (a saida e a linha em que ela e a REMETENTE)',
       cess.envio === '18/08/2026 16:10', JSON.stringify(cess));

const com = camposDaMesa(mov, 'COMASUP');
checar('COMASUP recebe em 19/08 — NAO herda a data da CESS',
       com.marco_unidade === '19/08/2026 07:30', JSON.stringify(com));
checar('COMASUP nao herda quem recebeu na CESS',
       com.recebimento_por === 'ana.souza' &&
       com.recebimento_por !== cess.recebimento_por, JSON.stringify(com));
checar('COMASUP nunca remeteu: envio nulo',
       com.envio === null && com.unidade_envio === null, JSON.stringify(com));

const ast = camposDaMesa(mov, 'ASTEC');
checar('a unidade que GEROU tem a geracao como marco',
       ast.marco_unidade === '28/07/2025 08:58', JSON.stringify(ast));

console.log('\nausencia significa "nao sei", nunca "sem divergencia"');
const nada = camposDaMesa(mov, 'UMA-CMA');
checar('unidade que nao aparece no historico devolve os cinco NULOS',
       nada.marco_unidade === null && nada.recebimento === null, JSON.stringify(nada));
checar('e diz que nao derivou para ninguem',
       nada.derivada_para === null, JSON.stringify(nada));
checar('sem custodia nenhuma, tambem devolve vazio (nao explode)',
       camposDaMesa(null, 'CESS').derivada_para === null, 'null');
checar('sem unidade, idem', camposDaMesa(mov, '').derivada_para === null, 'vazio');

console.log('\nreabertura conta como chegada nova na mesma mesa');
const reab = [
  { dh: '19/08/2026 07:30', un: 'CESS', us: 'ana', de: 'Reabertura do processo na unidade' },
  { dh: '28/07/2025 08:58', un: 'CESS', us: 'joao', de: 'Processo recebido na unidade' },
];
checar('vale a REABERTURA (19/08), nao o recebimento de um ano atras',
       camposDaMesa(reab, 'CESS').marco_unidade === '19/08/2026 07:30',
       JSON.stringify(camposDaMesa(reab, 'CESS')));

/* ------------------------------------------------------------------------
   PARIDADE COM O PYTHON. Com `--casos`, imprime em stdout o JSON do resultado
   de camposDaMesa() para cada caso da tabela COMPARTILHADA — e e o teste do
   Python que compara campo a campo. Antes, a "conferencia de paridade" lia so o
   exit code deste arquivo, que nem conhece o outro lado: uma implementacao podia
   zerar envio/unidade_envio e as duas suites continuavam verdes.
------------------------------------------------------------------------ */
if (process.argv.includes('--casos')) {
  const T = JSON.parse(fs.readFileSync(path.join(__dirname, '_casos_camposdamesa.json'), 'utf8'));
  const fora = T.casos.map(c => ({
    nome: c.nome, unidade: c.unidade,
    saida: camposDaMesa(T[c.mov], c.unidade),
  }));
  // sentinela: o proprio SEIAuto escreve o banner dele em stdout ao carregar
  process.stdout.write('\n--CASOS--\n' + JSON.stringify(fora, null, 1));
  process.exit(0);
}

console.log(`\n${ok} verificacoes, ${mau} falha(s)`);
process.exit(mau ? 1 : 0);
