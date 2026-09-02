/* A RÉGUA POR LINHA, EXECUTADA — não procurada como texto.

   O teste anterior só verificava se certos trechos apareciam em painel.html.
   Trocando `const reguaDe=d=>{... return t==null?REGUA:t;}` por `... return REGUA;`
   a régua por linha some inteira — e as seis verificações continuavam passando,
   porque as strings procuradas ainda estavam no arquivo (em outras linhas).

   Aqui as funções são EXTRAÍDAS do template servido e RODADAS sobre dados
   sintéticos: uma linha lida na coleta e uma servida pelo poço, medida três dias
   antes. Se a régua por linha for desligada, a contagem de dias das duas passa a
   ser igual e este arquivo falha.

   node conferir_regua.js [caminho/painel.html]
*/
const fs = require('fs'), path = require('path');

const alvo = process.argv[2] ||
  path.join(__dirname, 'templates', 'painel.html');
const html = fs.readFileSync(alvo, 'utf8');

// O bloco da régua, tal como é servido. Recortado por âncoras que são as próprias
// definições — se alguém renomear, o teste falha em vez de passar em silêncio.
const ini = html.indexOf('const emMs=');
const fimAnc = 'const faixaDe=';
const fim = html.indexOf(fimAnc);
if (ini < 0 || fim < 0) {
  console.log('FALHA: nao achei o bloco da regua em ' + alvo);
  process.exit(1);
}
// Até o fim da LINHA de faixaDe, e não um ';' adiante: passar dela entra no
// código que monta o cabeçalho, que toca no DOM.
const bloco = html.slice(ini, html.indexOf('\n', fim));

let ok = 0, mau = 0;
const checar = (nome, cond, viu) => {
  if (cond) { ok++; console.log('  ok   ' + nome); }
  else { mau++; console.log('  FALHA ' + nome + (viu ? '  -> ' + viu : '')); }
};

/* Dois processos com o MESMO marco_unidade e leituras diferentes:
   - fresca : detalhe lido na coleta (18/08 07:45)
   - do poco: detalhe lido tres dias antes (15/08 07:45)
   Com régua por linha, "dias na unidade" TEM de diferir em 3. Com régua única,
   os dois dão o mesmo número — que é a mentira que a mudança existe para impedir. */
const MARCO = '01/08/2026 09:00';
const DADOS = [
  { id: 'fresca', marco_unidade: MARCO, autuacao: MARCO,
    medido_em: '2026-08-18T07:45:00-03:00', ultimo_movimento: { dh: MARCO } },
  { id: 'poco', marco_unidade: MARCO, autuacao: MARCO,
    medido_em: '2026-08-15T07:45:00-03:00', ultimo_movimento: { dh: MARCO } },
  { id: 'sem_data', marco_unidade: MARCO, autuacao: MARCO,
    medido_em: null, ultimo_movimento: { dh: MARCO } },
];
const COLETA_EM = '15/08/2026 07:45';   // o marco mais atrasado, como o servidor manda
const esc = s => String(s == null ? '' : s);
const MESAS_CONTA = [], MESAS_FALHAS = [];

const ctx = { DADOS, COLETA_EM, esc, MESAS_CONTA, MESAS_FALHAS, console, Date, Math, JSON };
const vm = require('vm');
vm.createContext(ctx);
// `const` no topo de um script do vm fica no escopo lexico, nao vira propriedade
// do contexto: sem esta linha, so as `function` declaradas seriam alcancaveis.
vm.runInContext(bloco + '\n;globalThis.__r={diasDe,reguaDe,atrasoDe,naUnidade,REGUA,'
  + 'tarjaResumo,resumoAtrasado,reguaTexto};', ctx);

const { diasDe, reguaDe, atrasoDe, naUnidade, REGUA } = ctx.__r;
const [fresca, poco, semData] = DADOS;

console.log('A REGUA E DA LINHA, e nao da carteira\n');
const dF = naUnidade(fresca), dP = naUnidade(poco);
checar('as duas linhas tem o mesmo marco e datas de leitura diferentes',
       fresca.marco_unidade === poco.marco_unidade);
checar(`a linha lida na coleta e a servida pelo poco NAO dao o mesmo numero de dias (${dF} x ${dP})`,
       dF !== dP, `${dF} x ${dP}`);
checar('e a diferenca e exatamente a diferenca entre as leituras (3 dias)',
       dF - dP === 3, String(dF - dP));
checar('a linha do poco mede contra a leitura DELA, nao contra o retrato mais novo',
       dP === 13, String(dP));

console.log('\nquem nao tem data propria cai na regua da carteira');
checar('linha sem medido_em usa REGUA', reguaDe(semData) === REGUA);
checar('e o numero dela bate com o da coleta mais atrasada',
       naUnidade(semData) === naUnidade(poco), `${naUnidade(semData)} x ${naUnidade(poco)}`);

console.log('\no atraso e medido contra o retrato mais NOVO da carteira');
checar('a linha mais nova tem atraso zero', atrasoDe(fresca) === 0, String(atrasoDe(fresca)));
checar('e a do poco, tres dias', atrasoDe(poco) === 3, String(atrasoDe(poco)));

console.log('\nnenhuma dessas contas mede contra o relogio');
const ontem = { id: 'x', marco_unidade: MARCO, medido_em: '2026-08-18T07:45:00-03:00' };
checar('o numero nao muda quando o relogio anda (mesmo dado, duas leituras)',
       naUnidade(ontem) === naUnidade(fresca), `${naUnidade(ontem)} x ${naUnidade(fresca)}`);

console.log(`\n${ok} verificacoes, ${mau} falha(s)`);
process.exit(mau ? 1 : 0);
