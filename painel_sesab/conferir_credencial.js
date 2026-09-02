/* Extrai as funcoes de credencial do automacao_sei.js e prova a PRECEDENCIA.
 *
 * O arquivo inteiro nao roda fora do navegador (DOM, fetch, SEI). Mas a decisao
 * "de qual fonte sai a credencial" e pura logica, e e a decisao que, invertida,
 * fazia a busca de uma pessoa entrar no SEI com a conta de outra.
 *
 *   node conferir_credencial.js
 *
 * Sai 0 se todos os casos passam, 1 se algum falha.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ARQ = path.join(__dirname, 'automacao_sei.js');
const fonte = fs.readFileSync(ARQ, 'utf8');

// Recorta do `const CHAVE` ate o fim de ondeEstaACredencial().
const ini = fonte.indexOf("const CHAVE = '__SEI_CRED'");
const marca = 'function ondeEstaACredencial()';
const fim = fonte.indexOf('}', fonte.indexOf('return \'NENHUMA — preencha o CONFIG', fonte.indexOf(marca))) + 1;
if (ini < 0 || fim <= ini) {
  console.error('nao achei o bloco da credencial em automacao_sei.js');
  process.exit(1);
}
const bloco = fonte.slice(ini, fim);

let ok = 0;
const falhas = [];
function checar(nome, cond, detalhe) {
  if (cond) { ok++; console.log('  OK    ' + nome); }
  else { falhas.push(nome); console.log('  FALHA ' + nome + (detalhe ? '  ' + detalhe : '')); }
}

function montar({ config, guardado, ignorar }) {
  const loja = {};
  if (guardado) {
    loja['__SEI_CRED'] = Buffer.from(JSON.stringify(guardado), 'utf8').toString('base64');
  }
  const janela = {};
  if (ignorar) janela.__SEI_IGNORAR_CONFIG = true;
  const avisos = [];
  const ctx = {
    CONFIG: config,
    window: janela,
    localStorage: {
      getItem: (k) => (k in loja ? loja[k] : null),
      setItem: (k, v) => { loja[k] = v; },
      removeItem: (k) => { delete loja[k]; },
    },
    log: () => {},
    erro: (m) => avisos.push(String(m)),
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
    unescape, escape, JSON, console,
  };
  vm.createContext(ctx);
  vm.runInContext(bloco, ctx);
  return { ctx, avisos, loja };
}

// Valores DISTINTIVOS: uma senha curta como 'ARQ' casa por acidente com
// 'ARQUITETURA' na mensagem de aviso e reprova o teste sem defeito nenhum.
const CFG = { usuario: 'do.arquivo@zzz', senha: 'senha-do-arquivo-9271' };
const VAZIO = { usuario: '', senha: '' };
const ENTREGUE = { usuario: 'quem.pediu@x', senha: 'STDIN' };

console.log('A PRECEDENCIA DA CREDENCIAL\n');

// 1. O caso que quebrava identidade.
{
  const { ctx } = montar({ config: CFG, guardado: ENTREGUE, ignorar: true });
  const c = ctx.lerCredencial();
  checar('credencial ENTREGUE vence o bloco CONFIG',
    c && c.usuario === ENTREGUE.usuario, JSON.stringify(c));
  checar('e o diagnostico nao diz "bloco CONFIG"',
    !/bloco CONFIG/.test(ctx.ondeEstaACredencial()), ctx.ondeEstaACredencial());
}

// 2. Entregou a flag mas nao a credencial: recusa, nunca cai no CONFIG.
{
  const { ctx } = montar({ config: CFG, guardado: null, ignorar: true });
  checar('flag ligada e nada entregue -> NENHUMA credencial (recusa o login)',
    ctx.lerCredencial() === null, JSON.stringify(ctx.lerCredencial()));
}

// 3. A ESTACAO nao pode quebrar: sem flag e sem localStorage, o CONFIG vale.
{
  const { ctx } = montar({ config: CFG, guardado: null, ignorar: false });
  const c = ctx.lerCredencial();
  checar('a estacao continua viva: sem flag, o CONFIG e usado',
    c && c.usuario === CFG.usuario, JSON.stringify(c));
  checar('e o diagnostico diz de onde veio',
    /bloco CONFIG/.test(ctx.ondeEstaACredencial()), ctx.ondeEstaACredencial());
}

// 4. Semeado pelo console, sem flag: o semeado vence (era o caso 2 do desenho).
{
  const { ctx } = montar({ config: CFG, guardado: ENTREGUE, ignorar: false });
  const c = ctx.lerCredencial();
  checar('semeado no perfil vence o arquivo mesmo sem a flag',
    c && c.usuario === ENTREGUE.usuario, JSON.stringify(c));
}

// 5. Nada em lugar nenhum.
{
  const { ctx } = montar({ config: VAZIO, guardado: null, ignorar: false });
  checar('sem nada configurado, devolve null', ctx.lerCredencial() === null);
  checar('e o diagnostico diz NENHUMA', /NENHUMA/.test(ctx.ondeEstaACredencial()));
}

// 6. localStorage corrompido nao pode derrubar nem cair no CONFIG por acidente.
{
  const { ctx, loja } = montar({ config: CFG, guardado: ENTREGUE, ignorar: true });
  loja['__SEI_CRED'] = 'isto-nao-e-base64-valido!!!';
  checar('localStorage corrompido com a flag ligada -> null, nao o CONFIG',
    ctx.lerCredencial() === null, JSON.stringify(ctx.lerCredencial()));
}

// 7. A armadilha avisa quando os dois existem.
{
  const { ctx, avisos } = montar({ config: CFG, guardado: ENTREGUE, ignorar: true });
  ctx.lerCredencial();
  checar('avisa que ha credencial no arquivo E entregue',
    avisos.some((a) => /bloco CONFIG/i.test(a)), JSON.stringify(avisos));
  checar('e a frase casa com a palavra que o coletor trata como alerta',
    avisos.some((a) => a.toLowerCase().includes('bloco config')));
}

// 8. E nao avisa quando nao ha o que avisar.
{
  const { ctx, avisos } = montar({ config: VAZIO, guardado: ENTREGUE, ignorar: true });
  ctx.lerCredencial();
  checar('nao avisa quando o CONFIG esta vazio', avisos.length === 0, JSON.stringify(avisos));
}

// 9. O valor do CONFIG nunca aparece no aviso.
{
  const { ctx, avisos } = montar({ config: CFG, guardado: ENTREGUE, ignorar: true });
  ctx.lerCredencial();
  checar('o aviso NAO reproduz a senha nem o login do arquivo',
    !avisos.some((a) => a.includes(CFG.senha) || a.includes(CFG.usuario)),
    JSON.stringify(avisos));
}

console.log('\n' + '='.repeat(56));
console.log(ok + ' verificacoes OK, ' + falhas.length + ' falha(s)');
falhas.forEach((f) => console.log('  FALHOU: ' + f));
process.exit(falhas.length ? 1 : 0);
