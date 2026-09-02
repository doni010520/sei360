/* A CONTA DE DIAS DO PAINEL E A DO RELATÓRIO, LADO A LADO, SOBRE OS MESMOS CASOS.

   POR QUE ISTO EXISTE
   -------------------
   O painel e os relatórios respondem "há quantos dias este processo está na
   unidade" com dois códigos diferentes, em duas linguagens diferentes, sobre o
   mesmo dado. Enquanto ninguém comparou, eles divergiram: em 21/08/2026, sobre
   1.165 processos, o painel dizia "Parados +90d: 432" e /relatorios/triagem
   dizia 526 — 94 processos, +21,8%, nas duas telas do mesmo sistema no mesmo
   segundo. A causa era uma truncagem: o relatório jogava a hora fora dos dois
   lados e contava viradas de meia-noite; o painel contava o intervalo.

   Conferir isso lendo os dois códigos não funciona — foi o que se fez, e o
   comentário de `_dias()` já AFIRMAVA que a divergência tinha sido corrigida
   enquanto ela continuava lá, com outro tamanho.

   O QUE ELE FAZ
   -------------
   `teste_relatorios.py` escreve `_casos_dias.json` com casos tirados da BASE
   REAL mais as bordas que o SEI produz, e com a resposta que o Python deu para
   cada um. Este arquivo extrai as funções do `painel.html` SERVIDO, roda-as
   sobre os mesmos casos e compara número a número.

   Divergiu em um caso: falha, e imprime o caso. Não é "os dois parecem certos";
   é "os dois deram o mesmo número".

       node conferir_dias.js [caminho/painel.html] [caminho/_casos_dias.json]
*/
const fs = require('fs'), path = require('path');

const alvo = process.argv[2] || path.join(__dirname, 'templates', 'painel.html');
const casosArq = process.argv[3] || path.join(__dirname, '_casos_dias.json');

if (!fs.existsSync(casosArq)) {
  // Sem a tabela de casos não há comparação. Dizer isso é obrigatório: uma
  // conferência que se cala quando não pode rodar é pior que não ter nenhuma.
  console.log('FALHA: nao achei ' + casosArq + ' — rode teste_relatorios.py antes');
  process.exit(1);
}
const html = fs.readFileSync(alvo, 'utf8');
const casos = JSON.parse(fs.readFileSync(casosArq, 'utf8'));

/* O bloco da régua, tal como é SERVIDO. As âncoras são as próprias definições:
   se alguém renomear `emMs` ou `faixaDe`, isto falha em vez de passar calado. */
const ini = html.indexOf('const emMs=');
const fim = html.indexOf('const faixaDe=');
if (ini < 0 || fim < 0) {
  console.log('FALHA: nao achei o bloco da regua em ' + alvo);
  process.exit(1);
}
const bloco = html.slice(ini, html.indexOf('\n', fim));

/* `REGUA` e `REGUA_NOVA` dependem de COLETA_EM e DADOS, que só existem na página.
   Aqui todo caso traz o próprio `medido_em`, então basta um COLETA_EM inócuo —
   se algum caso cair no fallback, o valor sentinela faz a diferença explodir e o
   teste falhar, em vez de coincidir por acaso. */
const COLETA_EM = '1990-01-01T00:00:00-03:00';
const DADOS = [];
let diasDe;
try {
  diasDe = eval(bloco + '; diasDe');
} catch (e) {
  console.log('FALHA: o bloco da regua nao executa -> ' + e.message);
  process.exit(1);
}

let ok = 0, mau = 0;
const falhas = [];
for (const c of casos) {
  const js = diasDe(c.marco, { medido_em: c.medido_em });
  const py = c.dias;
  if (js === py || (js == null && py == null)) ok++;
  else {
    mau++;
    if (falhas.length < 8)
      falhas.push(`${c.rotulo || ''} marco=${c.marco} regua=${c.medido_em} ` +
                  `-> painel ${js}, relatorio ${py}`);
  }
}

console.log(`  ${ok} caso(s) com o MESMO numero nas duas contas`);
for (const f of falhas) console.log('  FALHA ' + f);
if (mau) console.log(`  FALHA ${mau} caso(s) divergiram entre painel e relatorio`);

/* A comparação só vale se os casos EXERCITAREM a diferença. Uma tabela em que
   todo marco tem 00:00 passaria com a truncagem de volta: sem hora, calendário e
   intervalo dão o mesmo número. */
const comHora = casos.filter(c => /\d{2}:\d{2}/.test(c.marco || '')).length;
if (comHora < 10) {
  console.log(`  FALHA a tabela tem so ${comHora} caso(s) com HORA no marco — ` +
              'sem hora, a truncagem que causou o defeito nao e exercitada');
  mau++;
}
process.exit(mau ? 1 : 0);
