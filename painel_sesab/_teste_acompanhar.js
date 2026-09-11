/* A LEITURA REDUZIDA DE UM PROCESSO POR NUMERO — sem navegador e sem SEI.

   O QUE DA PARA PROVAR AQUI
   -------------------------
   Que a composicao existe e monta o que o servidor espera: a pesquisa por numero
   devolve o link, `urlHistorico` traz arvore e historico, `derivar` produz o
   registro e a funcao FILTRA dele apenas os campos que podem subir. Que os cinco
   campos de custodia — e o `mov_custodia`, que carrega login de quem movimentou —
   NAO saem daqui. Que o protocolo volta literalmente igual ao que entrou. Que a
   lista e lida em SERIE, com a mesma pausa curta do resto do coletor. Que um
   processo que estoura nao derruba os outros, e que ele nao ganha estado
   inventado. Que a queda de sessao para o laco em vez de carimbar 'sem_acesso'
   no resto. E que o teto de tempo devolve o que ja foi lido, em vez de nada.

   O QUE NAO DA PARA PROVAR AQUI, E FICA DITO
   ------------------------------------------
   Nada abaixo prova que isto funciona contra o SEI. Falta, e so a estacao de uma
   pessoa com o segundo fator dela pode dizer:

     1. que `filtros.numero_sei` com a pontuacao que a pessoa COLOU encontra o
        processo — o 4.0 da FESF e o 5.0.4 da SESAB imprimem o mesmo numero com
        pontuacao diferente, e quem cola cola o que viu;
     2. que a Pesquisa devolve linha para processo que NAO esta em nenhuma mesa de
        quem procura — e essa e a premissa do modulo inteiro;
     3. que a recusa do SEI aparece mesmo como pagina SEM o iframe da arvore (o
        que aqui vira 'sem_acesso') e nao como erro visivel ou tela de login;
     4. que sao CINCO requisicoes por processo. Aqui isso e MEDIDO contra a
        fixture (ver o caso abaixo), e o formulario real pode trazer `hdnInicio`
        — e nesse caso `pesquisar` posta a segunda pagina antes de respeitar
        `paginas_teto: 1`, e sao seis;
     5. que a sessao aguenta N processos em serie a 240 ms, que e a pausa medida
        contra a paginacao da busca, nao contra esta leitura;
     6. que `id_sei` vem preenchido na linha do resultado nas DUAS instalacoes;
     7. A MAIS IMPORTANTE DA LISTA: que o `GET acao=procedimento_trabalhar` sobre
        processo que NAO esta em nenhuma mesa de quem le seja mesmo so leitura.
        No SEI 5.0.4 abrir um processo pode marca-lo como RECEBIDO na unidade
        ativa, e ai este modulo estaria ALTERANDO o SEI em vez de observa-lo —
        movimentando processo alheio em nome de quem acompanha, sem ninguem ter
        pedido. Nenhuma fixture responde isso: so a rodada de campo, conferindo o
        andamento do processo ANTES e DEPOIS da primeira leitura. Enquanto nao
        for conferido, e o risco aberto do modulo.

   node _teste_acompanhar.js
*/
const fs = require('fs'), path = require('path'), vm = require('vm');
const { documento, elementoSolto } = require('./_dom_de_bolso');

const SRC_AUTO = fs.readFileSync(path.join(__dirname, 'automacao_sei.js'), 'utf8');
const SRC_BUSCA = fs.readFileSync(path.join(__dirname, 'pesquisa_sei.js'), 'utf8');

let ok = 0, mau = 0;
const checar = (nome, cond, viu) => {
  if (cond) { ok++; console.log('  ok    ' + nome); }
  else { mau++; console.log('  FALHA ' + nome + (viu !== undefined ? '  -> ' + viu : '')); }
};

/* ============================================================== o ambiente == */
/* Os DOIS arquivos na MESMA caixa: `acompanhar` compoe `SEIBusca.pesquisar` com
   `urlHistorico` e `derivar`, e provar isso com um `SEIBusca` de mentira provaria
   a mentira. O que e de mentira aqui e a REDE, e so ela. */
function ambiente(resolver, opc = {}) {
  const guardado = {}, saida = [], pedidos = [], pausas = [];
  const caixa = {
    console: { log: (...a) => saida.push(a.join(' ')), table: () => {} },
    TextDecoder: function () { this.decode = x => x; },
    URLSearchParams, Date, Math, JSON,
    // A pausa e REGISTRADA e nao cumprida: dormir de verdade somaria segundos a
    // cada caso e nao provaria nada. Que ela existe, e de quanto e, o teste ve em
    // `pausas`.
    setTimeout: (f, ms) => { pausas.push(ms); f(); return 0; },
    setInterval: () => 0, clearInterval: () => {},
    Blob: function () {}, URL: { createObjectURL: () => 'x' },
    DOMParser: function () { this.parseFromString = s => documento(s); },
    document: Object.assign(documento(opc.pagina || PAGINA_VIVA),
                            { createElement: () => elementoSolto() }),
    location: { href: 'https://seibahia.ba.gov.br/sei/' },
    localStorage: {
      getItem: k => (k in guardado ? guardado[k] : null),
      setItem: (k, v) => { guardado[k] = v; },
      removeItem: k => { delete guardado[k]; },
    },
    async fetch(url, o) {
      pedidos.push(url);
      const r = resolver(url, o);
      if (r == null) throw new Error('fixture sem resposta para ' + url);
      // O SEI nao responde "sessao caiu": ele REDIRECIONA para o login, e e a URL
      // final da resposta que denuncia isso. E assim que `pegar()` descobre.
      if (r === LOGIN) return { url: '/sei/login.php', arrayBuffer: async () => '' };
      // Excecao com mensagem escolhida pelo caso — e como se exercita o que a
      // estacao faz com o TEXTO de um erro antes de manda-lo pela rede.
      if (r && r.erro) throw new Error(r.erro);
      return { url, arrayBuffer: async () => r };
    },
  };
  caixa.window = caixa;
  vm.createContext(caixa);
  vm.runInContext(SRC_AUTO, caixa);
  vm.runInContext(SRC_BUSCA, caixa);
  caixa.SEIAuto.perfil({ instancia: 'SEI-SESAB', versao: '5.0.4',
                         raiz: 'https://seibahia.ba.gov.br/' });
  return { caixa, saida, pedidos, pausas };
}

const LOGIN = { paraLogin: true };

/* ========================================================== as fixtures ===== */
/* A pagina VIVA em que a estacao esta parada. `abrirPesquisa` acha a tela de
   Pesquisa pelo MENU — nunca por URL montada —, e e daqui que sai o link. */
const PAGINA_VIVA = `
<div id="__body__">
  <a id="lnkInfraUnidade" href="#">SESAB/DGESS</a>
  <a id="lnkPesquisa" href="/sei/controlador.php?acao=protocolo_pesquisar&infra_hash=menu">Pesquisa</a>
</div>`;

const CAMPOS = {
  modo_processos: ['optProcessos'],
  tramitacao_unidade: ['chkSinTramitacao'],
  tipo_processo: ['selTipoProcedimentoPesquisa'],
  especificacao: ['txtDescricaoPesquisa'],
  numero_sei: ['txtProtocoloPesquisa'],
  enviar: ['sbmPesquisar'],
};

/* O formulario de Pesquisa. SEM `hdnInicio`: com ele, `proxima()` sempre acha
   uma proxima pagina e `pesquisar` posta de novo mesmo com `paginas_teto: 1` —
   ver o item 4 do bloco "o que nao da para provar". */
const FORMULARIO = `
<form id="frmProtocoloPesquisa" action="/sei/controlador.php?acao=protocolo_pesquisar">
  <input type="hidden" name="hdnFlag" value="1">
  <input type="radio" id="optProcessos" name="rdoPesquisarEm" value="P">
  <input type="checkbox" id="chkSinTramitacao" name="chkSinTramitacao" value="S">
  <input type="text" id="txtProtocoloPesquisa" name="txtProtocoloPesquisa" value="">
  <input type="submit" id="sbmPesquisar" name="sbmPesquisar" value="Pesquisar">
</form>`;

/* Uma pagina de resultado com UMA linha. O `protocolo` impresso e o do SEI — que
   pode nao ser, caractere a caractere, o que a pessoa colou. */
function RESULTADO(protocolo, idProc) {
  return `
<div id="__body__">
  <p>Lista de Processos (1 registros):</p>
  <table id="tblResultado">
    <tr><th>Processo</th><th>Tipo</th><th>Unidade</th><th>Data</th></tr>
    <tr>
      <td><a href="/sei/controlador.php?acao=procedimento_trabalhar&id_procedimento=${idProc}&infra_hash=res"
             aria-label="Contratação Direta / compra de insumos">${protocolo}</a></td>
      <td>Contratação Direta</td>
      <td>SESAB/SUPERH</td>
      <td>12/08/2026</td>
    </tr>
  </table>
</div>`;
}

const SEM_LINHA = `<div id="__body__"><p>Lista de Processos (0 registros):</p>
  <table id="tblResultado"><tr><th>Processo</th></tr></table></div>`;

/* A pagina do processo: o que importa dela e o iframe da arvore. */
const PROCESSO = `<div id="__body__">
  <iframe id="ifrArvore" name="ifrArvore" src="/sei/controlador.php?acao=arvore_visualizar&amp;infra_hash=arv"></iframe>
</div>`;

/* A pagina do processo SEM o iframe: e assim que o SEI devolve um processo que
   este login nao pode ver — sem erro, sem tela de login, sem o conteudo. */
const PROCESSO_SEM_ARVORE = '<div id="__body__"><p>&nbsp;</p></div>';

/* A arvore. Nao e HTML: e o JavaScript que o SEI escreve, e dele saem as mesas
   (`Nos[0].html`), as acoes (`Nos[0].acoes`), a URL do historico e a contagem de
   nos — que vira `documentos`. Tres nos: raiz + dois documentos. */
const ARVORE = [
  "Nos[0] = new infraArvoreNo();",
  "Nos[0].html = 'Processo aberto nas unidades: <br /><a class=\"ancoraSigla\">SESAB/SUPERH</a><br /><a class=\"ancoraSigla\">SESAB/DGESS</a> <a class=\"ancoraSigla\">fulano.um</a>';",
  "Nos[0].acoes = '<a href=\"controlador.php?acao=procedimento_consultar_historico&id_procedimento=91&infra_hash=hist\">Consultar Andamento</a>';",
  "Nos[1] = new infraArvoreNo();",
  "Nos[2] = new infraArvoreNo();",
].join('\n');

/* A arvore sem a URL do historico: o outro jeito de o SEI dizer "nao para voce". */
const ARVORE_SEM_HISTORICO = "Nos[0] = new infraArvoreNo();\nNos[0].html = 'x';";

/* O historico. A terceira coluna e o LOGIN de quem movimentou — e e por isso que
   `mov_custodia` nao pode subir para o servidor. */
const HISTORICO = `<div id="__body__">
<table id="tblHistorico">
  <tr><td>10/09/2026 14:22</td><td>SESAB/DGESS</td><td>fulano.um@saude.ba.gov.br</td><td>Processo recebido na unidade</td></tr>
  <tr><td>09/09/2026 08:10</td><td>SESAB/SUPERH</td><td>fulano.um@saude.ba.gov.br</td><td>Processo remetido pela unidade SESAB/SUPERH</td></tr>
  <tr><td>01/08/2026 10:00</td><td>SESAB/SUPERH</td><td>beltrana.dois@saude.ba.gov.br</td><td>Processo público gerado, Nenhuma</td></tr>
</table></div>`;

/* O resolvedor de rede padrao: um processo que existe e se deixa ler. */
function rede(opc = {}) {
  return (url) => {
    if (/acao=protocolo_pesquisar/.test(url) && !/id_procedimento/.test(url)) {
      return opc.formulario === null ? null : FORMULARIO;
    }
    if (/acao=procedimento_trabalhar/.test(url)) {
      return 'processo' in opc ? opc.processo : PROCESSO;
    }
    if (/acao=arvore_visualizar/.test(url)) {
      return 'arvore' in opc ? opc.arvore : ARVORE;
    }
    if (/acao=procedimento_consultar_historico/.test(url)) {
      return 'historico' in opc ? opc.historico : HISTORICO;
    }
    return null;
  };
}

/* O POST da pesquisa cai no mesmo `action` do formulario; quem distingue e o
   metodo. Devolve o resultado pedido para cada protocolo. */
function redeComResultado(porProtocolo, opc = {}) {
  const base = rede(opc);
  let i = 0;
  return (url, o) => {
    if (o && o.method === 'POST') {
      const qual = porProtocolo[Math.min(i++, porProtocolo.length - 1)];
      return typeof qual === 'function' ? qual() : qual;
    }
    return base(url, o);
  };
}

const PROTOCOLO = '019.5120.2026.0161681-50';

async function lerUm(resolvedor, protocolo = PROTOCOLO, opc = {}) {
  const amb = ambiente(resolvedor, opc);
  const r = await amb.caixa.SEIAuto.acompanhar(protocolo, CAMPOS);
  return { r, amb };
}

/* ================================================================ os casos == */
(async () => {

console.log('O CAMINHO BOM: CINCO REQUISICOES E QUATRO CAMPOS');
{
  const { r, amb } = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')]));
  checar('o estado e "lido"', r.estado === 'lido', JSON.stringify(r));
  checar('as unidades saem da ARVORE, nao do andamento',
         JSON.stringify(r.aberto_em) === JSON.stringify(['SESAB/SUPERH', 'SESAB/DGESS']),
         JSON.stringify(r.aberto_em));
  checar('e a fonte diz isso', r.aberto_em_fonte === 'arvore', r.aberto_em_fonte);
  checar('o ultimo movimento e o mais recente',
         (r.ultimo_movimento || {}).dh === '10/09/2026 14:22', JSON.stringify(r.ultimo_movimento));
  checar('documentos = nos da arvore menos a raiz', r.documentos === 2, String(r.documentos));
  checar('movimentos = linhas do historico', r.movimentos === 3, String(r.movimentos));
  checar('o id_sei vem da linha do resultado', r.id_sei === '91', String(r.id_sei));
  // O ORCAMENTO, MEDIDO E NAO ESTIMADO. A conta antiga dizia tres e esquecia o
  // par da pesquisa: a tela de Pesquisa e reaberta a cada protocolo, porque
  // `abrirPesquisa` sai do MENU vivo — reusar o formulario da vez anterior e
  // exatamente o risco de `infra_hash` morto. Este numero e publicado em
  // `acompanhamento.py` (TETO) e nos dois planos; se ele mudar aqui, tem de
  // mudar la.
  checar('sao CINCO requisicoes por processo', amb.pedidos.length === 5,
         `${amb.pedidos.length}: ${JSON.stringify(amb.pedidos)}`);
  checar('a arvore e o historico foram lidos',
         amb.pedidos.some(u => /arvore_visualizar/.test(u))
         && amb.pedidos.some(u => /consultar_historico/.test(u)),
         JSON.stringify(amb.pedidos));
  checar('e a tela de Pesquisa e reaberta, nunca reusada',
         amb.pedidos.filter(u => /acao=protocolo_pesquisar/.test(u)).length === 2,
         JSON.stringify(amb.pedidos));
}

console.log('\nOS CINCO CAMPOS DE CUSTODIA NAO SOBEM — E NEM O LOGIN DE QUEM MOVIMENTOU');
{
  const { r } = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')]));
  const CAMPOS_QUE_SOBEM = ['protocolo', 'estado', 'id_sei', 'aberto_em',
                            'aberto_em_fonte', 'ultimo_movimento', 'documentos',
                            'movimentos'];
  checar('a lista de campos e EXATA, nao um espalhamento de derivar()',
         JSON.stringify(Object.keys(r).sort()) === JSON.stringify(CAMPOS_QUE_SOBEM.slice().sort()),
         JSON.stringify(Object.keys(r)));
  // `derivar` calcula estes cinco para a mesa em que a estacao esta parada, que
  // NAO e a mesa deste processo. Manda-los seria mandar o dado de outra mesa com
  // o nome deste processo.
  for (const campo of ['marco_unidade', 'recebimento', 'recebimento_por', 'envio',
                       'unidade_envio', 'derivada_para', 'mesa_derivada']) {
    checar(`  ${campo} fica na estacao`, !(campo in r));
  }
  checar('  mov_custodia tambem — e ele carrega nome e e-mail', !('mov_custodia' in r));
  checar('nenhum login de quem movimentou atravessa o fio',
         !JSON.stringify(r).includes('@saude.ba.gov.br'), JSON.stringify(r).slice(0, 200));
}

console.log('\nO PROTOCOLO VOLTA LITERALMENTE IGUAL AO QUE ENTROU');
{
  // O servidor casa a resposta por TEXTO, nao por digitos (`receber`, em
  // `acompanhamento.py`): devolver a forma que o SEI imprime, e nao a que a
  // pessoa colou, faria a leitura inteira ser ignorada em silencio.
  const COLADO = '0195120202601616815 0'.replace(' ', '');   // sem pontuacao
  const { r } = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')]), COLADO);
  checar('volta o que a pessoa colou, nao o que o SEI imprime',
         r.protocolo === COLADO, `${r.protocolo} != ${COLADO}`);
  checar('e mesmo assim o processo foi lido', r.estado === 'lido', r.estado);
}

console.log('\nOS TRES ESTADOS, E NENHUM SILENCIOSO');
{
  const semLinha = await lerUm(redeComResultado([SEM_LINHA]));
  checar('pesquisa sem linha -> nao_encontrado',
         semLinha.r.estado === 'nao_encontrado', JSON.stringify(semLinha.r));

  const semArvore = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')],
                                                 { processo: PROCESSO_SEM_ARVORE }));
  checar('processo sem a arvore -> sem_acesso',
         semArvore.r.estado === 'sem_acesso', JSON.stringify(semArvore.r));

  const semHist = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')],
                                               { arvore: ARVORE_SEM_HISTORICO }));
  checar('arvore sem o historico -> sem_acesso',
         semHist.r.estado === 'sem_acesso', JSON.stringify(semHist.r));
}

console.log('\nFALHA TECNICA NAO VIRA "SEM ACESSO"');
{
  // 'sem arvore' e 'sem historico' sao a recusa do SEI. Rede que caiu, fixture
  // que faltou e pagina que nao parseou NAO sao — e carimbar 'sem_acesso' nelas
  // gravaria "o SEI recusou" na tela E queimaria a chance do dia (o servidor
  // atualiza `lido_em` em toda recusa). Sem estado, o item continua pendente.
  const { r } = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')],
                                             { historico: null }));
  checar('historico que nao respondeu nao ganha estado nenhum', !r.estado,
         JSON.stringify(r));
  checar('e a falha e nomeada', !!r.falha, JSON.stringify(r));
}

console.log('\nA LISTA E LIDA EM SERIE, COM A PAUSA DO RESTO DO COLETOR');
{
  const tres = ['019.1111.2026.0000001-11', '019.2222.2026.0000002-22',
                '019.3333.2026.0000003-33'];
  const amb = ambiente(redeComResultado(tres.map((p, i) => RESULTADO(p, String(90 + i)))));
  const env = await amb.caixa.SEIAuto.acompanharLista(
    { instancia: 'SEI-SESAB', protocolos: tres, campos: CAMPOS });
  checar('os tres voltam', (env.leituras || []).length === 3, JSON.stringify(env).slice(0, 200));
  checar('na ordem em que o servidor mandou',
         JSON.stringify(env.leituras.map(x => x.protocolo)) === JSON.stringify(tres),
         JSON.stringify(env.leituras.map(x => x.protocolo)));
  checar('a instalacao volta no envelope', env.instancia === 'SEI-SESAB', env.instancia);
  // EM SERIE, e nao em paralelo: o SEI derruba sessao sob rajada, e o coletor
  // inteiro e construido com essa premissa. Se fossem disparados juntos, a
  // primeira requisicao do segundo processo viria antes da terceira do primeiro.
  const arvores = amb.pedidos.map((u, i) => [u, i]).filter(([u]) => /arvore_visualizar/.test(u));
  const hists = amb.pedidos.map((u, i) => [u, i]).filter(([u]) => /consultar_historico/.test(u));
  checar('um processo inteiro antes do proximo comecar',
         arvores.length === 3 && hists.length === 3
         && hists[0][1] < arvores[1][1] && hists[1][1] < arvores[2][1],
         JSON.stringify(amb.pedidos));
  checar('com a pausa curta entre eles (240 ms, a mesma da paginacao)',
         amb.pausas.filter(ms => ms === 240).length === 2,
         JSON.stringify(amb.pausas));
}

console.log('\nUM PROCESSO QUE ESTOURA NAO DERRUBA OS OUTROS');
{
  const cinco = ['019.1111.2026.0000001-11', '019.2222.2026.0000002-22',
                 '019.3333.2026.0000003-33', '019.4444.2026.0000004-44',
                 '019.5555.2026.0000005-55'];
  // O TERCEIRO estoura: a pagina do processo nao responde. Nao e recusa do SEI.
  let n = 0;
  const amb = ambiente((url, o) => {
    if (o && o.method === 'POST') { n++; return RESULTADO(cinco[n - 1], String(90 + n)); }
    if (/acao=procedimento_trabalhar/.test(url) && n === 3) return null;
    return rede()(url, o);
  });
  const env = await amb.caixa.SEIAuto.acompanharLista(
    { instancia: 'SEI-SESAB', protocolos: cinco, campos: CAMPOS });
  checar('os outros quatro voltam', (env.leituras || []).length === 4,
         JSON.stringify((env.leituras || []).map(x => x.protocolo)));
  checar('e o terceiro nao esta entre eles',
         !(env.leituras || []).some(x => x.protocolo === cinco[2]),
         JSON.stringify((env.leituras || []).map(x => x.protocolo)));
  checar('ele volta na lista de falhas, nomeado',
         (env.falhas || []).length === 1 && env.falhas[0].protocolo === cinco[2],
         JSON.stringify(env.falhas));
  checar('sem estado nenhum — o item continua pendente para a proxima volta',
         !(env.leituras || []).some(x => !x.estado), JSON.stringify(env.leituras));
}

console.log('\nSESSAO QUE CAI PARA O LACO — NAO CARIMBA O RESTO');
{
  const cinco = ['019.1111.2026.0000001-11', '019.2222.2026.0000002-22',
                 '019.3333.2026.0000003-33', '019.4444.2026.0000004-44',
                 '019.5555.2026.0000005-55'];
  let n = 0;
  const amb = ambiente((url, o) => {
    if (o && o.method === 'POST') { n++; return RESULTADO(cinco[n - 1], String(90 + n)); }
    if (/acao=procedimento_trabalhar/.test(url) && n >= 3) return LOGIN;
    return rede()(url, o);
  });
  const env = await amb.caixa.SEIAuto.acompanharLista(
    { instancia: 'SEI-SESAB', protocolos: cinco, campos: CAMPOS });
  checar('o que foi lido antes da queda volta', (env.leituras || []).length === 2,
         JSON.stringify((env.leituras || []).map(x => x.protocolo)));
  checar('o laco para na queda, em vez de insistir', (env.falhas || []).length === 1,
         JSON.stringify(env.falhas));
  checar('e o motivo diz que foi a sessao', /sess/i.test(env.motivo || ''), env.motivo);
  checar('nenhum processo posterior ganhou "sem_acesso"',
         !(env.leituras || []).some(x => x.estado === 'sem_acesso'),
         JSON.stringify(env.leituras));
}

console.log('\nO TETO DE TEMPO DEVOLVE O QUE JA FOI LIDO');
{
  const cinco = ['019.1111.2026.0000001-11', '019.2222.2026.0000002-22',
                 '019.3333.2026.0000003-33', '019.4444.2026.0000004-44',
                 '019.5555.2026.0000005-55'];
  // A rede queima tempo de verdade: e o relogio que este teto le.
  let n = 0;
  const amb = ambiente((url, o) => {
    const ate = Date.now() + 40;
    while (Date.now() < ate) { /* o SEI demorando */ }
    if (o && o.method === 'POST') { n++; return RESULTADO(cinco[n - 1], String(90 + n)); }
    return rede()(url, o);
  });
  const env = await amb.caixa.SEIAuto.acompanharLista(
    { instancia: 'SEI-SESAB', protocolos: cinco, campos: CAMPOS, teto_ms: 150 });
  checar('parou antes do fim da lista', (env.leituras || []).length < 5,
         String((env.leituras || []).length));
  checar('mas devolveu o que leu', (env.leituras || []).length >= 1,
         String((env.leituras || []).length));
  checar('e disse que foi o teto', /teto/i.test(env.motivo || ''), env.motivo);
}

console.log('\nO MOTIVO DA FALHA NAO LEVA infra_hash PELA REDE');
{
  // `falhas[].motivo` e mensagem de excecao truncada, e excecao de `fetch` pode
  // carregar a URL que falhou — que leva `infra_hash` de sessao. O servidor nao
  // persiste este campo hoje, mas "hoje nao persiste" nao e lugar para guardar
  // segredo de sessao.
  const amb = ambiente(redeComResultado([RESULTADO(PROTOCOLO, '91')],
    { historico: { erro: 'caiu em /sei/x?infra_hash=SEGREDO123&id=9' } }));
  const env = await amb.caixa.SEIAuto.acompanharLista(
    { instancia: 'SEI-SESAB', protocolos: [PROTOCOLO], campos: CAMPOS });
  const texto = JSON.stringify(env);
  checar('a falha e relatada', (env.falhas || []).length === 1, texto.slice(0, 160));
  checar('o hash de sessao NAO atravessa o fio', !texto.includes('SEGREDO123'),
         texto.slice(0, 200));
  checar('mas o resto do motivo continua legivel', /caiu em/.test(env.falhas[0].motivo),
         env.falhas[0].motivo);
}

console.log('\nO LINK SO EXISTE PARA QUEM PEDIU — E NUNCA E PERSISTIDO');
{
  // `linhas()` esconde o href de proposito: ele carrega `infra_hash` de sessao, e
  // hash morto nao devolve erro — DERRUBA a sessao de quem esta trabalhando.
  // `com_link` e a excecao declarada, para quem usa o link na mesma passagem.
  const { caixa } = ambiente(rede());
  const doc = documento(RESULTADO(PROTOCOLO, '91'));
  const sem = caixa.SEIBusca.linhas(doc);
  const com = caixa.SEIBusca.linhas(doc, true);
  checar('sem a flag, a linha nao tem link', !('link' in sem[0]), JSON.stringify(sem[0]));
  checar('com a flag, tem', /id_procedimento=91/.test(com[0].link || ''),
         JSON.stringify(com[0]));
  checar('e o resto da linha e o mesmo', sem[0].protocolo === com[0].protocolo
         && sem[0].id_sei === com[0].id_sei, JSON.stringify([sem[0], com[0]]));
}

console.log(`\n${ok} verificacoes, ${mau} falha(s)`);
process.exit(mau ? 1 : 0);

})().catch(e => { console.error('EXPLODIU:', e); process.exit(1); });
