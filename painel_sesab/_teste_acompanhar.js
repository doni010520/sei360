/* A LEITURA REDUZIDA DE UM PROCESSO POR NUMERO — sem navegador e sem SEI.

   O QUE DA PARA PROVAR AQUI
   -------------------------
   Que a composicao existe e monta o que o servidor espera: a pesquisa por numero
   devolve o link, `urlHistorico` traz arvore e historico, `derivar` produz o
   registro e a funcao FILTRA dele apenas os campos que podem subir. Que a ficha
   DO PROCESSO sobe inteira e que NENHUM dos vinte termos da ficha DA MESA sai
   daqui — os catorze `CAMPOS_DA_MESA` do servidor mais os internos de `derivar`,
   incluindo `mov_custodia`, que carrega login de quem movimentou; e que o login
   de quem GEROU sobe, porque e campo declarado, enquanto o de quem so movimentou
   nao. Que a tela Consultar/Alterar ausente da `null` e a tela vazia da `[]`. Que
   a queda da sexta requisicao nao leva a leitura inteira junto. Que sem
   `aria-label` a especificacao fica ausente em vez de inventada. Que o protocolo
   volta literalmente igual ao que entrou. QUE A FICHA QUE SOBE E A DO PROCESSO
   PEDIDO: busca que saiu sem o filtro do numero e recusada, e a linha escolhida
   entre varias e a que casa por DIGITOS — nao `itens[0]`, que era o que estava
   escrito e o que deixava a ficha de outro processo entrar com o numero certo,
   marcada 'lido'. Que linha SEM link — que e o que a estacao com o
   `pesquisa_sei.js` de 20/08 produz — e falha de implantacao, e nao a afirmacao
   'nao_encontrado' sobre o SEI. Que a
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
     4. que sao SEIS requisicoes por processo. Aqui isso e MEDIDO contra a
        fixture (ver o caso abaixo), e o formulario real pode trazer `hdnInicio`
        — e nesse caso `pesquisar` posta a segunda pagina antes de respeitar
        `paginas_teto: 1`, e sao sete;
     5. que a sessao aguenta N processos em serie a 240 ms, que e a pausa medida
        contra a paginacao da busca, nao contra esta leitura;
     6. que `id_sei` vem preenchido na linha do resultado nas DUAS instalacoes;
     7. que a tela Consultar/Alterar real traga mesmo `selAssuntos` e
        `selInteressadosProcedimento` — `dadosCadastro` ja rodava contra ela na
        coleta, entao a medicao existe para a SESAB; para a FESF (SEI 4.0), nao;
     8. o ID DO CAMPO DE ESPECIFICACAO na tela Consultar/Alterar. E o caminho
        certo para o SEI 4.0, onde nao ha `aria-label` de onde tira-la, e ninguem
        aqui nunca leu aquele campo. NAO ADIVINHE O ID: adivinhar id de campo do
        SEI ja custou quatro erros nesta entrega, e um id errado aqui poe o texto
        de OUTRO campo num campo que pode citar paciente — pior que campo nulo. O
        jeito seguro, quando alguem for olhar, e DETECTAR pelo rotulo que o SEI
        imprime, como `linhas()` detecta a tabela em vez de assumi-la;
     9. A MAIS IMPORTANTE DA LISTA: que o `GET acao=procedimento_trabalhar` sobre
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

/* O `pesquisa_sei.js` QUE ESTA IMPLANTADO NA ESTACAO, e nao o deste diretorio.
   O de 20/08 nao conhece o parametro `comReservados`: ele monta a linha SEM o
   href, sempre. Nao e hipotese — e o arquivo que roda hoje, e por isso a leitura
   de todo processo seguido voltava sem link.

   A defasagem e simulada apagando o efeito do parametro na fonte real, em vez de
   guardar uma copia velha do arquivo: copia velha envelhece de novo, e um dia
   passaria a provar outra coisa. O que se prova aqui e o comportamento do
   `acompanhar()` diante de uma busca que nao entrega o reservado — venha ela de
   onde vier. */
const SRC_BUSCA_ANTIGO = SRC_BUSCA.replace(
  'function linhas(doc, comReservados) {',
  'function linhas(doc, comReservados) { comReservados = false;');
if (SRC_BUSCA_ANTIGO === SRC_BUSCA) {
  console.error('EXPLODIU: a assinatura de linhas() mudou e a simulacao da '
              + 'estacao defasada nao pegou — o caso da linha sem link estaria '
              + 'passando a vazio');
  process.exit(1);
}

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
  const guardado = {}, saida = [], pedidos = [], pausas = [], corpos = [];
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
      // O CORPO DO POST E GUARDADO porque e nele que se ve se o numero pedido
      // chegou mesmo ao SEI. Medido em 11/09/2026 com o mapa de campos vazio:
      // `hdnFlag=1&txtProtocoloPesquisa=` — o campo existe no formulario e vai
      // VAZIO, entao o SEI responde a busca sem filtro nenhum e a primeira linha
      // e um processo qualquer. Sem olhar o corpo, o caso passaria so por olhar o
      // resultado, que e onde o defeito NAO aparece.
      if (o && o.method === 'POST') corpos.push(String(o.body || ''));
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
  vm.runInContext(opc.buscaAntiga ? SRC_BUSCA_ANTIGO : SRC_BUSCA, caixa);
  caixa.SEIAuto.perfil({ instancia: 'SEI-SESAB', versao: '5.0.4',
                         raiz: 'https://seibahia.ba.gov.br/' });
  return { caixa, saida, pedidos, pausas, corpos };
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

/* Uma pagina de resultado com VARIAS linhas. Duas maneiras de chegar nela, e as
   duas acontecem: a busca sem o filtro do numero (o mapa de campos do perfil nao
   veio, e o POST sai com `txtProtocoloPesquisa=` vazio) devolve a mesa inteira; e
   a busca COM o filtro pode casar mais de um processo, porque o campo de numero
   do SEI nao promete linha unica. Nos dois casos, `itens[0]` e um processo
   qualquer — nao o pedido. */
function RESULTADO_VARIOS(linhas) {
  const tr = linhas.map(l => `
    <tr>
      <td><a href="/sei/controlador.php?acao=procedimento_trabalhar&id_procedimento=${l.id}&infra_hash=res"
             aria-label="${l.tipo} / ${l.espec}">${l.protocolo}</a></td>
      <td>${l.tipo}</td>
      <td>SESAB/SUPERH</td>
      <td>12/08/2026</td>
    </tr>`).join('');
  return `
<div id="__body__">
  <p>Lista de Processos (${linhas.length} registros):</p>
  <table id="tblResultado">
    <tr><th>Processo</th><th>Tipo</th><th>Unidade</th><th>Data</th></tr>${tr}
  </table>
</div>`;
}

/* O PROCESSO DE OUTRA GENTE que a busca sem filtro devolve em primeiro lugar. Os
   valores sao os medidos na auditoria de 11/09/2026: id 777, uma especificacao
   que fala de apuracao sobre servidor e um interessado com nome de pessoa. Sao
   TEXTO LIVRE de um processo de unidade nenhuma de quem pediu — o que atravessou
   para a tela quando `itens[0]` foi tomado como resposta. */
const OUTRO = { protocolo: '019.7777.2026.0000777-77', id: '777',
                tipo: 'Apuração Preliminar', espec: 'apuracao sobre servidor' };
const OUTRO_AINDA = { protocolo: '019.8888.2026.0000888-88', id: '888',
                      tipo: 'Sindicância', espec: 'outra apuracao qualquer' };
const PEDIDO_NA_LISTA = { protocolo: '019.5120.2026.0161681-50', id: '91',
                          tipo: 'Contratação Direta', espec: 'compra de insumos' };

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
const ACOES = '<a href=\\"controlador.php?acao=procedimento_consultar_historico&id_procedimento=91&infra_hash=hist\\">Consultar Andamento</a>'
            + '<a href=\\"controlador.php?acao=procedimento_alterar&id_procedimento=91&infra_hash=alt\\">Consultar/Alterar</a>';
const ARVORE = [
  "Nos[0] = new infraArvoreNo();",
  "Nos[0].html = 'Processo aberto nas unidades: <br /><a class=\"ancoraSigla\">SESAB/SUPERH</a><br /><a class=\"ancoraSigla\">SESAB/DGESS</a> <a class=\"ancoraSigla\">fulano.um</a>';",
  "Nos[0].acoes = '" + ACOES.replace(/\\"/g, '"') + "';",
  "Nos[1] = new infraArvoreNo();",
  "Nos[2] = new infraArvoreNo();",
].join('\n');

/* A arvore SEM a acao Consultar/Alterar. Acontece de verdade — o coletor ja
   distingue os dois casos na coleta, com `alterar_disponivel` —, e e o que separa
   "processo sem assunto" de "nao deu para olhar". */
const ARVORE_SEM_ALTERAR = ARVORE.split('\n')
  .map(l => l.indexOf('Nos[0].acoes') === -1 ? l
    : "Nos[0].acoes = '<a href=\"controlador.php?acao=procedimento_consultar_historico&id_procedimento=91&infra_hash=hist\">Consultar Andamento</a>';")
  .join('\n');

/* A arvore sem a URL do historico: o outro jeito de o SEI dizer "nao para voce". */
const ARVORE_SEM_HISTORICO = "Nos[0] = new infraArvoreNo();\nNos[0].html = 'x';";

/* A tela Consultar/Alterar. E um GET numa tela de formulario — NADA e submetido.
   Dela saem `assuntos` e `interessados`, e so eles: `dadosCadastro` mede que
   observacoes, prioridade e grau de sigilo vieram vazios em 100% da amostra. */
const CADASTRO = `<div id="__body__">
  <select id="selAssuntos" name="selAssuntos" multiple>
    <option value="1">065.03 - Contratação de serviços</option>
    <option value="2">029.11 - Aquisição de insumos</option>
  </select>
  <select id="selInteressadosProcedimento" name="selInteressadosProcedimento" multiple>
    <option value="9">FESF-SUS</option>
  </select>
</div>`;

/* A mesma tela, com os dois selects VAZIOS: processo que existe e nao tem assunto
   cadastrado. `[]` aqui, e nao null — a diferenca que a ficha mostra. */
const CADASTRO_VAZIO = `<div id="__body__">
  <select id="selAssuntos" name="selAssuntos" multiple></select>
  <select id="selInteressadosProcedimento" name="selInteressadosProcedimento" multiple></select>
</div>`;

/* O historico. A terceira coluna e o LOGIN de quem movimentou. O de QUEM GEROU o
   processo sobe (`gerador_usuario` e campo declarado da ficha); o de quem apenas
   movimentou, nao — e e por isso que `mov_custodia` nao pode subir junto. Por
   isso os dois papeis tem logins DIFERENTES nesta fixture. */
const HISTORICO = `<div id="__body__">
<table id="tblHistorico">
  <tr><td>10/09/2026 14:22</td><td>SESAB/DGESS</td><td>fulano.um@saude.ba.gov.br</td><td>Processo recebido na unidade</td></tr>
  <tr><td>10/09/2026 11:00</td><td>SESAB/DGESS</td><td>fulano.um@saude.ba.gov.br</td><td>Envio de correspondência eletrônica</td></tr>
  <tr><td>09/09/2026 16:40</td><td>SESAB/SUPERH</td><td>ciclano.tres@saude.ba.gov.br</td><td>Assinatura externa do documento 0012345</td></tr>
  <tr><td>09/09/2026 08:10</td><td>SESAB/SUPERH</td><td>ciclano.tres@saude.ba.gov.br</td><td>Processo remetido pela unidade SESAB/SUPERH</td></tr>
  <tr><td>05/08/2026 09:00</td><td>SESAB/SUPERH</td><td>ciclano.tres@saude.ba.gov.br</td><td>Processo 019.9999.2026.0000099-99 anexado ao processo 019.5120.2026.0161681-50</td></tr>
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
    if (/acao=procedimento_alterar/.test(url)) {
      return 'cadastro' in opc ? opc.cadastro : CADASTRO;
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

console.log('O CAMINHO BOM: SEIS REQUISICOES E A FICHA DO PROCESSO');
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
  checar('movimentos = linhas do historico', r.movimentos === 6, String(r.movimentos));
  checar('o id_sei vem da linha do resultado', r.id_sei === '91', String(r.id_sei));
  // O ORCAMENTO, MEDIDO E NAO ESTIMADO. Eram cinco; a tela Consultar/Alterar —
  // de onde saem `assuntos` e `interessados` — faz a sexta. A tela de Pesquisa e
  // reaberta a cada protocolo porque `abrirPesquisa` sai do MENU vivo, e reusar o
  // formulario da vez anterior e exatamente o risco de `infra_hash` morto. Este
  // numero e publicado em `acompanhamento.py` (TETO), no cabecalho de
  // `acompanhar` e nos dois planos; se mudar aqui, tem de mudar la.
  checar('sao SEIS requisicoes por processo', amb.pedidos.length === 6,
         `${amb.pedidos.length}: ${JSON.stringify(amb.pedidos)}`);
  checar('a arvore, o historico e o cadastro foram lidos',
         amb.pedidos.some(u => /arvore_visualizar/.test(u))
         && amb.pedidos.some(u => /consultar_historico/.test(u))
         && amb.pedidos.some(u => /procedimento_alterar/.test(u)),
         JSON.stringify(amb.pedidos));
  checar('e a tela de Pesquisa e reaberta, nunca reusada',
         amb.pedidos.filter(u => /acao=protocolo_pesquisar/.test(u)).length === 2,
         JSON.stringify(amb.pedidos));
}

console.log('\nA FICHA DO PROCESSO — a que vale dentro E fora da mesa');
{
  const { r } = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')]));
  checar('tipo_processo vem da linha do resultado, sem requisicao nova',
         r.tipo_processo === 'Contratação Direta', String(r.tipo_processo));
  checar('autuacao e a data do movimento de geracao',
         r.autuacao === '01/08/2026 10:00', String(r.autuacao));
  checar('gerador_unidade e gerador_usuario saem do mesmo movimento',
         r.gerador_unidade === 'SESAB/SUPERH'
         && r.gerador_usuario === 'beltrana.dois@saude.ba.gov.br',
         `${r.gerador_unidade} / ${r.gerador_usuario}`);
  checar('nivel_acesso e hipotese_legal saem do texto da geracao',
         r.nivel_acesso === 'Público' && r.hipotese_legal === 'Nenhuma',
         `${r.nivel_acesso} / ${r.hipotese_legal}`);
  checar('emails_enviados conta as correspondencias eletronicas',
         r.emails_enviados === 1, String(r.emails_enviados));
  checar('assinatura_externa conta as assinaturas externas',
         r.assinatura_externa === 1, String(r.assinatura_externa));
  checar('anexados traz o numero do processo anexado',
         JSON.stringify(r.anexados) === JSON.stringify(['019.9999.2026.0000099-99']),
         JSON.stringify(r.anexados));
  checar('assuntos vem da tela Consultar/Alterar',
         (r.assuntos || []).length === 2
         && /Contratação de serviços/.test(r.assuntos[0]), JSON.stringify(r.assuntos));
  checar('interessados tambem', JSON.stringify(r.interessados) === JSON.stringify(['FESF-SUS']),
         JSON.stringify(r.interessados));
  // A ESPECIFICACAO SAI DO `aria-label` DA LINHA DO RESULTADO, que e onde o SEI 5
  // publica "tipo / especificacao" — a mesma leitura que `linhas()` ja faz para
  // pegar o tipo. Nao foi adivinhada da arvore: campo que pode citar paciente
  // preenchido com texto de procedencia desconhecida e pior que campo nulo.
  checar('especificacao sai do mesmo aria-label de onde ja saia o tipo',
         r.especificacao === 'compra de insumos', String(r.especificacao));
}

console.log('\nA FICHA DA MESA NAO SOBE — NEM UM CAMPO, NEM UM TERMO');
{
  const { r } = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')]));
  const CAMPOS_QUE_SOBEM = [
    'protocolo', 'estado', 'id_sei', 'aberto_em', 'aberto_em_fonte',
    'ultimo_movimento', 'documentos', 'movimentos',
    'tipo_processo', 'especificacao', 'autuacao', 'gerador_unidade',
    'gerador_usuario', 'nivel_acesso', 'hipotese_legal', 'assuntos',
    'interessados', 'anexados', 'emails_enviados', 'assinatura_externa'];
  checar('a lista de campos e EXATA, nao um espalhamento de derivar()',
         JSON.stringify(Object.keys(r).sort())
         === JSON.stringify(CAMPOS_QUE_SOBEM.slice().sort()),
         JSON.stringify(Object.keys(r).filter(k => !CAMPOS_QUE_SOBEM.includes(k))));
  /* OS VINTE TERMOS PROIBIDOS. Os catorze `CAMPOS_DA_MESA` do servidor, mais os
     internos que `derivar()` devolve e que so fazem sentido dentro de uma mesa.
     Todos saem da LINHA da tabela de Controle de Processos daquela mesa — que
     para processo fora das mesas da conta NAO EXISTE —, ou de
     `camposDaMesa(mov, UNIDADE)`, derivado para a mesa em que a estacao esta
     parada. Qualquer um deles aqui seria o dado de outra mesa com o nome deste
     processo. */
  for (const campo of ['marcador', 'marcador_cor', 'atribuido_nome', 'atribuido_login',
                       'visualizado', 'marco_unidade', 'recebimento', 'recebimento_por',
                       'envio', 'unidade_envio', 'mesa_indeterminada', 'anotacao',
                       'anotacao_autor', 'anotacao_data', 'derivada_para',
                       'mesa_derivada', 'mov_custodia', 'sobrestado', 'urgente',
                       'truncado']) {
    checar(`  ${campo} fica na estacao`, !(campo in r));
  }
  // O LOGIN DE QUEM GEROU sobe, porque `gerador_usuario` e campo declarado da
  // ficha. O de quem apenas MOVIMENTOU, nao — e e essa a diferenca que
  // `mov_custodia` apagaria se subisse junto.
  checar('o login de quem GEROU sobe (e campo declarado)',
         JSON.stringify(r).includes('beltrana.dois'), JSON.stringify(r).slice(0, 200));
  for (const quem of ['fulano.um', 'ciclano.tres']) {
    checar(`  o login de quem so movimentou (${quem}) nao atravessa o fio`,
           !JSON.stringify(r).includes(quem), JSON.stringify(r).slice(0, 240));
  }
}

console.log('\nA TELA CONSULTAR/ALTERAR PODE NAO EXISTIR — E ISSO NAO E CAMPO VAZIO');
{
  // O coletor ja distingue os dois na coleta, com `alterar_disponivel`. Aqui a
  // distincao cabe no proprio valor: `null` e "nao deu para olhar", `[]` e "a
  // tela existia e nao havia assunto nenhum". Sao coisas diferentes na ficha.
  const semTela = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')],
                                               { arvore: ARVORE_SEM_ALTERAR }));
  checar('sem a tela, assuntos e interessados ficam NULOS (nao observado)',
         semTela.r.assuntos === null && semTela.r.interessados === null,
         JSON.stringify([semTela.r.assuntos, semTela.r.interessados]));
  checar('e o resto da ficha continua vindo', semTela.r.estado === 'lido'
         && semTela.r.gerador_unidade === 'SESAB/SUPERH', JSON.stringify(semTela.r));
  checar('sem a tela sao CINCO requisicoes, nao seis', semTela.amb.pedidos.length === 5,
         JSON.stringify(semTela.amb.pedidos));

  const telaVazia = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')],
                                                 { cadastro: CADASTRO_VAZIO }));
  checar('com a tela vazia, ficam LISTAS VAZIAS (observado, e nao havia)',
         JSON.stringify(telaVazia.r.assuntos) === '[]'
         && JSON.stringify(telaVazia.r.interessados) === '[]',
         JSON.stringify([telaVazia.r.assuntos, telaVazia.r.interessados]));
}

console.log('\nO CADASTRO QUE FALHA NAO LEVA A LEITURA INTEIRA JUNTO');
{
  // A arvore e o historico ja vieram: o processo FOI lido. Descartar tudo porque
  // a sexta requisicao caiu jogaria fora cinco requisicoes de trabalho e deixaria
  // o item pendente — para, no ciclo seguinte, provavelmente falhar de novo no
  // mesmo lugar. Relata-se o que se leu, e os dois campos ficam "nao observado".
  const { r } = await lerUm(redeComResultado([RESULTADO(PROTOCOLO, '91')],
                                             { cadastro: null }));
  checar('a leitura sobrevive a queda do cadastro', r.estado === 'lido',
         JSON.stringify(r));
  checar('e os dois campos dele ficam nulos, nao inventados',
         r.assuntos === null && r.interessados === null,
         JSON.stringify([r.assuntos, r.interessados]));
  checar('o resto da ficha esta inteiro', r.documentos === 2 && r.movimentos === 6
         && r.tipo_processo === 'Contratação Direta', JSON.stringify(r));
}

console.log('\nSEI 4.0: SEM aria-label, A ESPECIFICACAO FICA AUSENTE — NAO INVENTADA');
{
  // O 4.0 nao entrega tipo e especificacao no `aria-label` (esta medido no
  // cabecalho de `linhas()`), e ali o tipo se recupera da celula. A especificacao
  // nao tem de onde sair, e o certo e ficar nula: o item se identifica pela nota
  // que a propria pessoa escreveu.
  const SEM_ARIA = RESULTADO(PROTOCOLO, '91').replace(/ aria-label="[^"]*"/, '');
  const { r } = await lerUm(redeComResultado([SEM_ARIA]));
  checar('sem aria-label, especificacao fica nula', !r.especificacao,
         String(r.especificacao));
  checar('o tipo ainda vem, da celula', r.tipo_processo === 'Contratação Direta',
         String(r.tipo_processo));
  checar('e a leitura continua completa no resto', r.estado === 'lido'
         && r.movimentos === 6, JSON.stringify(r));
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

console.log('\nA FICHA DE OUTRO PROCESSO NAO ENTRA COM O NUMERO PEDIDO');
{
  /* O DEFEITO MEDIDO EM 11/09/2026, e o mais caro do modulo: `montar()` recusa em
     silencio o campo `numero_sei` quando o mapa de ids nao casa, e o coletor
     entrega `PERFIL_SEI.get("campos_busca") or {}` — vazio quando o perfil nao
     traz o mapa. O POST entao sai com `txtProtocoloPesquisa=` VAZIO, o SEI
     devolve a mesa inteira, e `itens[0]` era tomado como resposta:

       corpo do POST : hdnFlag=1&txtProtocoloPesquisa=
       estado        : lido
       protocolo     : 019.5120.2026.0161681-50   (o pedido, carimbado)
       id_sei        : 777   ("apuracao sobre servidor")

     Ficha falsa com o numero certo, `lido_em` queimado, e TEXTO LIVRE de um
     processo de unidade nenhuma da pessoa atravessando para a tela dela. */
  const OUTRO_CADASTRO = `<div id="__body__">
    <select id="selAssuntos" multiple><option value="1">024.2 - Sindicância</option></select>
    <select id="selInteressadosProcedimento" multiple>
      <option value="9">PACIENTE FULANO DE TAL</option></select></div>`;
  const comCadastroDoOutro = opc => (url, o) => {
    if (/acao=procedimento_alterar/.test(url) && /id_procedimento=777/.test(url)) {
      return OUTRO_CADASTRO;
    }
    return redeComResultado([RESULTADO_VARIOS([OUTRO, PEDIDO_NA_LISTA, OUTRO_AINDA])],
                            opc || {})(url, o);
  };

  const amb = ambiente(comCadastroDoOutro());
  const r = await amb.caixa.SEIAuto.acompanhar(PROTOCOLO, {});   // o mapa nao veio
  checar('o numero NAO foi ao SEI (e o corpo do POST prova)',
         amb.corpos.length === 1 && /txtProtocoloPesquisa=(&|$)/.test(amb.corpos[0]),
         JSON.stringify(amb.corpos));
  checar('sem o filtro do numero, a leitura RECUSA em vez de carimbar', !r.estado,
         JSON.stringify(r));
  checar('e a falha diz que foi o filtro, nao o processo',
         /filtro/i.test(r.falha || ''), String(r.falha));
  // FALHA TECNICA NAO E ESTADO, e este e o caso mais tentador de errar: a busca
  // respondeu, so que a outra pergunta. 'nao_encontrado' aqui manda a pessoa
  // conferir um digito que esta certo E queima a chance do dia.
  checar('nao vira "nao_encontrado" — isso seria afirmar sobre o SEI',
         r.estado !== 'nao_encontrado', String(r.estado));
  const texto = JSON.stringify(r);
  checar('nenhum campo do outro processo atravessa',
         !texto.includes('777') && !texto.includes('apuracao sobre servidor')
         && !texto.includes('PACIENTE FULANO'), texto.slice(0, 240));
  // Seis requisicoes por processo e o orcamento; recusar na primeira poupa cinco.
  checar('e a leitura para na busca, sem gastar as outras cinco requisicoes',
         !amb.pedidos.some(u => /arvore_visualizar|consultar_historico/.test(u)),
         JSON.stringify(amb.pedidos));

  /* COM O FILTRO APLICADO, a busca ainda pode devolver mais de uma linha — o
     campo de numero do SEI nao promete linha unica. A linha certa e escolhida
     por DIGITOS, que e a regua de identidade do projeto (`digitos()`, em
     `acompanhamento.py`): as duas instalacoes imprimem o mesmo numero com
     pontuacao diferente. */
  const amb2 = ambiente(comCadastroDoOutro());
  const r2 = await amb2.caixa.SEIAuto.acompanhar(PROTOCOLO, CAMPOS);
  checar('com varias linhas, a escolhida e a do numero pedido, nao a primeira',
         r2.id_sei === '91', `${r2.id_sei} / ${r2.especificacao}`);
  checar('e a ficha lida e a dela', r2.estado === 'lido'
         && r2.especificacao === 'compra de insumos'
         && r2.tipo_processo === 'Contratação Direta', JSON.stringify(r2));
  checar('nem a primeira nem a ultima linha foram abertas',
         !amb2.pedidos.some(u => /id_procedimento=777|id_procedimento=888/.test(u)),
         JSON.stringify(amb2.pedidos));
  checar('e o texto livre das outras duas nao atravessa',
         !JSON.stringify(r2).includes('apuracao') && !JSON.stringify(r2).includes('PACIENTE'),
         JSON.stringify(r2).slice(0, 240));

  // O QUE A PESSOA COLOU nao tem a pontuacao que o SEI imprime, e a comparacao e
  // por digitos exatamente por isso. Sem ela, este caso — que e o caso comum de
  // quem digita — cairia na recusa por "nenhuma linha e a pedida".
  const COLADO = '01951202026016168150';
  const amb3 = ambiente(comCadastroDoOutro());
  const r3 = await amb3.caixa.SEIAuto.acompanhar(COLADO, CAMPOS);
  checar('a pontuacao nao decide: colado sem ponto casa com a linha pontuada',
         r3.id_sei === '91' && r3.estado === 'lido', JSON.stringify(r3));
  checar('e o protocolo volta como a pessoa colou', r3.protocolo === COLADO, r3.protocolo);

  // Linhas vieram, nenhuma e a pedida. A busca respondeu OUTRA coisa — e dizer
  // "nao encontrado" seria afirmar, sobre o SEI, o que so se sabe sobre a nossa
  // pergunta. O item continua pendente, que e a verdade.
  const amb4 = ambiente(redeComResultado([RESULTADO_VARIOS([OUTRO, OUTRO_AINDA])]));
  const r4 = await amb4.caixa.SEIAuto.acompanhar(PROTOCOLO, CAMPOS);
  checar('linhas que nao sao a pedida nao viram estado nenhum', !r4.estado,
         JSON.stringify(r4));
  checar('e a falha conta quantas vieram', /2 linha/.test(r4.falha || ''),
         String(r4.falha));

  // Sem linha nenhuma o estado CONTINUA sendo `nao_encontrado`: ai a busca
  // respondeu a pergunta certa, e a resposta foi "nao ha".
  const amb5 = ambiente(redeComResultado([SEM_LINHA]));
  const r5 = await amb5.caixa.SEIAuto.acompanhar(PROTOCOLO, CAMPOS);
  checar('zero linha com o filtro aplicado continua sendo "nao_encontrado"',
         r5.estado === 'nao_encontrado', JSON.stringify(r5));
}

console.log('\nLINHA SEM LINK E FALHA DE IMPLANTACAO — NAO "NUMERO NAO ENCONTRADO"');
{
  /* Medido com o `pesquisa_sei.js` implantado hoje na estacao (de 20/08, sem o
     parametro reservado): TODO processo seguido voltava `nao_encontrado`, e a
     tela imprime isso como "numero nao encontrado neste SEI — confira o digito".
     Falha de implantacao virando afirmacao definitiva sobre o SEI, e mandando a
     pessoa conferir um digito que esta certo. */
  const amb = ambiente(redeComResultado([RESULTADO(PROTOCOLO, '91')]), { buscaAntiga: true });
  const r = await amb.caixa.SEIAuto.acompanhar(PROTOCOLO, CAMPOS);
  checar('a linha existe, entao NAO e "nao_encontrado"', r.estado !== 'nao_encontrado',
         JSON.stringify(r));
  checar('e nao ganha estado nenhum: o item continua pendente', !r.estado,
         JSON.stringify(r));
  checar('a falha aponta para a estacao, que e onde esta o defeito',
         /link/i.test(r.falha || ''), String(r.falha));
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

console.log('\nO MOTIVO DA BUSCA TAMBEM NAO LEVA infra_hash — NEM NO LOG');
{
  /* SEM GATILHO CONHECIDO, e fechado assim mesmo. `saida.motivo`, em
     `pesquisar()`, e mensagem de excecao truncada — e excecao de `fetch` pode
     carregar a URL que falhou. Dali ele vai para DOIS lugares: o envelope, que
     o servidor guarda, e o `console.log`, que o coletor ecoa para o stdout da
     estacao (`on_console`), que vira log e anexo. Hash de sessao morto nao
     devolve erro: ele DERRUBA a sessao de quem esta trabalhando. */
  const amb = ambiente(url =>
    (/acao=protocolo_pesquisar/.test(url)
      ? { erro: 'caiu em /sei/x?infra_hash=SEGREDO123&id=9' }
      : rede()(url)));
  const env = await amb.caixa.SEIBusca.pesquisar(
    { filtros: { numero_sei: PROTOCOLO }, campos: CAMPOS, paginas_teto: 1 });
  checar('a busca falhou, e disse por que', !!env.motivo, String(env.motivo));
  checar('o hash de sessao nao entra no envelope',
         !JSON.stringify(env).includes('SEGREDO123'), String(env.motivo));
  checar('nem no que o console imprime — que o coletor ecoa para o stdout',
         !amb.saida.join(' ').includes('SEGREDO123'), amb.saida.join(' ').slice(0, 200));
  checar('e o resto do motivo continua legivel', /caiu em/.test(env.motivo || ''),
         String(env.motivo));
}

console.log('\nOS RESERVADOS SO EXISTEM PARA QUEM PEDIU — E NAO ENTRAM NA BUSCA');
{
  /* `linhas()` esconde DUAS coisas de proposito, e por razoes diferentes que dao
     no mesmo lugar:
       * o href carrega `infra_hash` de sessao, e hash morto nao devolve erro —
         DERRUBA a sessao de quem esta trabalhando;
       * a especificacao e texto que um servidor escreveu e pode citar paciente, e
         `busca.py` a exclui do envelope da busca com motivo escrito.
     Nenhuma das duas pode entrar no envelope que a busca guarda. `com_reservados`
     e a excecao declarada, para quem usa as duas na mesma passagem do navegador
     e nao guarda nenhuma. */
  const { caixa } = ambiente(rede());
  const doc = documento(RESULTADO(PROTOCOLO, '91'));
  const sem = caixa.SEIBusca.linhas(doc);
  const com = caixa.SEIBusca.linhas(doc, true);
  checar('sem a flag, a linha nao tem link', !('link' in sem[0]), JSON.stringify(sem[0]));
  checar('sem a flag, a linha nao tem especificacao',
         !('especificacao' in sem[0]), JSON.stringify(sem[0]));
  checar('com a flag, tem link', /id_procedimento=91/.test(com[0].link || ''),
         JSON.stringify(com[0]));
  checar('com a flag, tem especificacao', com[0].especificacao === 'compra de insumos',
         JSON.stringify(com[0]));
  checar('e o resto da linha e o mesmo', sem[0].protocolo === com[0].protocolo
         && sem[0].id_sei === com[0].id_sei && sem[0].tipo_processo === com[0].tipo_processo,
         JSON.stringify([sem[0], com[0]]));
}

console.log(`\n${ok} verificacoes, ${mau} falha(s)`);
process.exit(mau ? 1 : 0);

})().catch(e => { console.error('EXPLODIU:', e); process.exit(1); });
