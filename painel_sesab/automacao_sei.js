/* ============================================================================
   AUTOMACAO SEI — DUAS INSTALACOES, UM COLETOR
     * SESAB / seibahia.ba.gov.br  (SEI 5.0.4)
     * FESF-SUS / sei.fesfsus.ba.gov.br  (SEI 4.0.x)
   Coleta o Controle de Processos com datas do historico.

   QUAL INSTALACAO E ESTA
   ----------------------
   Quem diz e o PERFIL, entregue por quem chama (ver "O PERFIL DA INSTALACAO"
   abaixo). Sem perfil vale a SESAB, que e o que sempre valeu. A versao escolhe
   UMA VEZ uma tabela de seletores — nao ha `if (versao === ...)` espalhado pelo
   parser, porque isso e o comeco de dois parsers dentro de um arquivo so.

   COMO USAR
   ---------
   1) Informe a credencial de UMA das duas formas:
        (a) preencha o bloco CONFIG logo abaixo, ou
        (b) rode uma vez no console:
            SEIAuto.credencial('seu.login@saude.ba.gov.br', 'suaSenha')

      Onde ela esta agora:  SEIAuto.ondeEstaACredencial()

   2) A cada execucao, com o SEI aberto (logado ou nao):
        SEIAuto.rodar()              -- a mesa atual
        SEIAuto.rodarTodasAsMesas()  -- todas as unidades da conta

   O script cuida de: login quando cair, coleta com checkpoint, retomada de
   onde parou, correcao dos historicos truncados e exportacao.

   ONDE DEIXAR A SENHA
   -------------------
   (a) CONFIG neste arquivo: pratico, mas a senha viaja junto com o arquivo.
       Use so se este .js ficar na sua maquina e nao for compartilhado.
   (b) localStorage: fica so neste navegador e neste perfil; o arquivo
       continua limpo e pode ser versionado ou agendado.
   (b) e mais seguro. (a) existe porque foi pedido.

   LIMITE CONHECIDO
   ----------------
   Se a instancia pedir 2FA, o script para e avisa: o segundo fator e seu.
   Ele nao tenta adivinhar nem contornar codigo de verificacao.
   ========================================================================== */
(() => {
'use strict';

/* ===========================================================================
   PREENCHA AQUI  --  usuario e senha do SEI

   ATENCAO: depois de preencher, ESTE ARQUIVO CONTEM SUA SENHA.
     - nao versione, nao anexe em e-mail, nao mande em chat
     - nao copie para pasta compartilhada nem para o worktree
     - ao trocar a senha no SEI, atualize aqui tambem

   Se preferir NAO deixar a senha no arquivo, deixe os campos vazios e
   rode uma vez no console:  SEIAuto.credencial('login', 'senha')
   =========================================================================== */
const CONFIG = {
  usuario: '',
  senha:   '',        // <<< DIGITE A SENHA AQUI, entre as aspas
};


/* ===========================================================================
   O PERFIL DA INSTALACAO — o que e DESTA instalacao, e nao do SEI

   O coletor nasceu falando com uma instalacao so e ela estava escrita nas
   entranhas: a raiz, a tabela da listagem, o jeito de ligar a visualizacao
   Detalhada. Habilitar a FESF nao e acrescentar uma opcao — e tirar do codigo o
   que so vale para uma instalacao e transformar em DADO. E a mesma regra de
   `perfil_sei.py` no servidor: UMA lista, N leitores.

   POR QUE POR `window.__SEI_PERFIL` E NAO POR ARGUMENTO
   Pelo mesmo motivo de `__SEI_IGNORAR_CONFIG`: quem entrega e o
   `add_init_script` do `coletor_sesab.py`, e a navegacao do submit do login
   destroi o contexto da pagina — a marca precisa RENASCER com ele. Argumento de
   funcao morreria na primeira navegacao.

   O perfil NAO carrega credencial. So o que descreve a instalacao: instancia,
   versao, raiz.
   =========================================================================== */
const PERFIL_PADRAO = {
  instancia: 'SEI-SESAB', versao: '5.0.4', raiz: 'https://seibahia.ba.gov.br/',
};
function perfilAtual() {
  const p = window.__SEI_PERFIL;
  // `instancia` e o que distingue perfil de sobra de objeto: sem ela nao da para
  // carimbar a linha, e carimbar errado e pior que nao carimbar.
  return (p && p.instancia) ? p : PERFIL_PADRAO;
}
/* Trocar o perfil em tempo de execucao — para o console e para a conferencia. */
function perfil(p) {
  window.__SEI_PERFIL = p || null;
  const a = perfilAtual();
  log(`instalacao: ${a.instancia} (SEI ${a.versao}) — ${familia(a).nome}`);
  return a;
}
const instanciaAtual = () => perfilAtual().instancia || null;
const raizAtual      = () => perfilAtual().raiz || PERFIL_PADRAO.raiz;


// Unidade corrente. NAO e fixa: um usuario do SEI pode estar lotado em varias
// unidades ("mesas"), e a coleta percorre todas. Lida da propria tela a cada troca.
let UNIDADE = '';
function unidadeAtual() {
  const lnk = document.getElementById('lnkInfraUnidade');
  if (lnk) return N(lnk.textContent);
  const sel = document.getElementById('selInfraUnidades');          // SEI antigo
  if (sel && sel.options[sel.selectedIndex]) return N(sel.options[sel.selectedIndex].text);
  return '';
}
const CONC    = 4;        // concorrencia; 6 funciona, 4 e mais gentil com o servidor
const PAGINA_HISTORICO = 100;   // o SEI pagina o historico em 100 linhas

const dec  = new TextDecoder('iso-8859-1');         // o SEI responde em ISO-8859-1
const N    = s => (s || '').replace(/\s+/g, ' ').trim();
const log  = (m, cor = '#0f5257') => console.log('%c[SEI] ' + m, `color:${cor};font-weight:bold`);
const erro = m => log(m, '#a3391f');
const dorme = ms => new Promise(r => setTimeout(r, ms));

// ---------------------------------------------------------------- credencial
const CHAVE = '__SEI_CRED';
function credencial(usuario, senha) {
  if (!usuario || !senha) { erro('uso: SEIAuto.credencial("login", "senha")'); return; }
  localStorage.setItem(CHAVE, btoa(unescape(encodeURIComponent(JSON.stringify({ usuario, senha })))));
  log('credencial guardada neste navegador. Nao fica no arquivo do script.');
}
function esquecer() { localStorage.removeItem(CHAVE); log('credencial apagada'); }
// A ORDEM ESTAVA INVERTIDA, E O PRECO ERA IDENTIDADE.
// O CONFIG deste arquivo vencia a credencial ENTREGUE para esta execucao. Como o
// servidor entrega a credencial de quem pediu a busca via SEIAuto.credencial()
// — que grava no localStorage, o nivel 2 — o CONFIG preenchido fazia TODA busca
// entrar no SEI com a conta do CONFIG, qualquer que fosse quem pediu. O SEI
// registrava os acessos com o nome dela, e ninguem comparava: falha silenciosa.
//
// Credencial entregue explicitamente vence constante escrita no arquivo.
// Sempre. E quando alguem entrega uma, o CONFIG some por completo: melhor
// RECUSAR o login do que entrar com a conta errada.
//
// `window.__SEI_IGNORAR_CONFIG` e ligada por quem chama, via add_init_script, e
// nao por variavel deste modulo — a navegacao do submit do login destroi o
// contexto da pagina, e a marca precisa renascer com ele.
function lerCredencial() {
  // ARMADILHA DE PRECEDENCIA. Chegar aqui com o CONFIG preenchido E credencial
  // entregue significa que alguem repreencheu o bloco depois do conserto: nao e
  // mais perigoso (o entregue vence), mas e uma senha em texto puro num arquivo
  // que viaja. O aviso sai pelo console porque quem chama ja escuta o console e
  // ja acumula alertas — e porque este arquivo nao pode ser lido de fora sem
  // desfazer a razao de ele existir.
  if (window.__SEI_IGNORAR_CONFIG && CONFIG.usuario && CONFIG.senha) {
    erro('ALERTA: ha credencial no bloco CONFIG deste arquivo e credencial ' +
         'entregue para esta execucao. A entregue vence, mas o CONFIG precisa ' +
         'ser esvaziado (ARQUITETURA_ACESSO.md 6.2).');
  }
  // 1) o que foi entregue para ESTA execucao (ou semeado uma vez pelo console)
  const b = localStorage.getItem(CHAVE);
  if (b) {
    try { return JSON.parse(decodeURIComponent(escape(atob(b)))); } catch { /* cai adiante */ }
  }
  // 2) o CONFIG e a RESERVA — e nao existe quando alguem entregou credencial.
  if (window.__SEI_IGNORAR_CONFIG) return null;
  if (CONFIG.usuario && CONFIG.senha) return { usuario: CONFIG.usuario, senha: CONFIG.senha };
  return null;
}
function ondeEstaACredencial() {
  // Reflete a MESMA ordem de lerCredencial. Diagnostico que mente sobre de onde
  // a credencial veio e pior que diagnostico nenhum.
  if (localStorage.getItem(CHAVE))    return 'localStorage deste navegador';
  if (window.__SEI_IGNORAR_CONFIG)    return 'NENHUMA — o CONFIG esta desligado nesta execucao';
  if (CONFIG.usuario && CONFIG.senha) return 'bloco CONFIG deste arquivo';
  return 'NENHUMA — preencha o CONFIG no topo ou rode SEIAuto.credencial(...)';
}
// Nota: btoa nao e criptografia, e so ofuscacao. Quem tem acesso ao perfil do
// Chrome tem acesso a credencial. Trate como o gerenciador de senhas do navegador.

// ------------------------------------------------------------------- sessao
const naLogin = () => /login\.php/.test(location.href) || !!document.querySelector('input[type=password]');
const logado  = () => !!document.getElementById('lnkControleProcessos') ||
                      !!document.getElementById('frmProcedimentoControlar') ||
                      // No 4.0 o pouso do login e a propria tela de controle e o
                      // link de menu pode nao existir. A barra de unidade existe
                      // em TODA tela logada das duas versoes (e do irmao desta
                      // casa, que a usa como ancora unica). Guardada por naLogin
                      // porque a tela de login nao tem barra nenhuma — e um
                      // "logado" falso ali faria o coletor nem tentar entrar.
                      (!naLogin() && !!document.getElementById('lnkInfraUnidade'));

async function logar() {
  const c = lerCredencial();
  if (!c) { erro('sem credencial. Rode SEIAuto.credencial("login","senha") uma vez.'); return false; }

  // descobre os campos em tempo de execucao, em vez de fixar ids
  const senha = document.querySelector('input[type=password]');
  if (!senha) { erro('nao achei campo de senha nesta tela'); return false; }
  const form = senha.form || document;
  const usuario = Array.from(form.querySelectorAll('input'))
      .filter(i => /text|email/i.test(i.type) && i.offsetParent !== null)[0];
  if (!usuario) { erro('nao achei campo de usuario'); return false; }

  usuario.focus(); usuario.value = c.usuario;
  usuario.dispatchEvent(new Event('input', { bubbles: true }));

  /* O SEI Bahia usa um PAR de campos de senha:
       - input[name=pwdSenha] type=password OCULTO  -> e o que vai no POST
       - input#pwdSenha       type=text     VISIVEL -> so para digitacao
     O JS da pagina copia o visivel para o oculto no envio. Preencher apenas o
     oculto faz o valor ser sobrescrito por vazio e o login volta sem erro. */
  const camposSenha = Array.from(document.querySelectorAll('input'))
      .filter(i => /senha|pwd|password/i.test((i.id || '') + ' ' + (i.name || '')));
  (camposSenha.length ? camposSenha : [senha]).forEach(campo => {
    campo.value = c.senha;
    campo.dispatchEvent(new Event('input',  { bubbles: true }));
    campo.dispatchEvent(new Event('change', { bubbles: true }));
  });

  const botao = Array.from(form.querySelectorAll('button,input[type=submit],input[type=button]'))
      .find(b => /acessar|entrar|login/i.test(b.value || b.textContent || ''));
  log('enviando login…');
  if (botao) botao.click(); else if (senha.form) senha.form.submit();

  for (let i = 0; i < 30; i++) {                     // espera ate 15s
    await dorme(500);
    if (logado()) { log('sessao restabelecida'); return true; }
    if (pedindoCodigo(senha, usuario)) {
      erro('2FA: digite o codigo na tela. Depois rode SEIAuto.rodar() de novo.');
      return false;
    }
  }
  erro('login nao concluiu em 15s (captcha, 2FA ou credencial invalida)');
  return false;
}

/* Deteccao de 2FA por ESTRUTURA, nao por texto.
   A tela de login do SEI Bahia menciona "Autenticacao em dois fatores" como texto
   informativo — casar por texto dava falso positivo em TODO login e abortava sempre.
   O sinal confiavel e um campo de codigo NOVO, que nao e o usuario nem a senha. */
function pedindoCodigo(campoSenha, campoUsuario) {
  const candidatos = Array.from(document.querySelectorAll('input'))
    .filter(i => i !== campoSenha && i !== campoUsuario
                 && i.offsetParent !== null
                 && /text|tel|number|password/i.test(i.type || '')
                 && !i.value);
  return candidatos.some(i => {
    const ctx = ((i.id || '') + ' ' + (i.name || '') + ' ' + (i.placeholder || '') + ' ' +
                 (i.getAttribute('aria-label') || '') + ' ' +
                 ((i.closest('label,div,fieldset') || {}).textContent || '').slice(0, 120));
    return /c.digo|token|verifica|autentica|OTP|2FA|segundo fator/i.test(ctx);
  });
}

// NUNCA navega a aba do usuario. Navegar aqui destroi o contexto do script e,
// se a URL nao tiver infra_hash valido, o SEI invalida a sessao de trabalho real.
// Sem sessao: avisa e para. Quem decide navegar e a pessoa.
async function garantirSessao() {
  if (logado()) return true;
  if (naLogin()) return await logar();
  erro('sem sessao do SEI nesta aba. Abra ' + raizAtual() + ' e rode de novo.');
  return false;
}

/* Disjuntor: duas quedas de sessao numa execucao e sinal de que algo esta
   sistematicamente errado (hash morto, unidade trocada, 2FA). Insistir so
   multiplica requisicoes invalidas contra o SEI. */
let quedas = 0;
function contarQueda() { return ++quedas >= 2; }

// Keep-alive DESLIGADO por padrao, de proposito.
// A coleta inteira leva ~45s e faz centenas de requisicoes: ela mesma mantem a
// sessao viva. Um ping periodico so faria barulho DEPOIS que o trabalho acabou.
// So faz sentido se voce for deixar a aba parada esperando entre operacoes.
let KA = null;
function keepAlive(ligar = true, minutos = 4) {
  if (KA) { clearInterval(KA); KA = null; }
  if (!ligar) return;
  KA = setInterval(() => fetch(location.href, { method: 'HEAD', credentials: 'same-origin' })
      .catch(() => {}), minutos * 60000);
  log(`keep-alive ligado (${minutos} min). Desligue com SEIAuto.keepAlive(false)`);
}

// --------------------------------------------------------------------- rede
async function pegar(url) {
  const r = await fetch(url, { credentials: 'same-origin' });
  if (/login\.php/.test(r.url)) throw new Error('SESSAO');
  return dec.decode(await r.arrayBuffer());
}
async function postar(action, sp) {
  const r = await fetch(action, { method: 'POST', body: sp, credentials: 'same-origin' });
  if (/login\.php/.test(r.url)) throw new Error('SESSAO');
  return new DOMParser().parseFromString(dec.decode(await r.arrayBuffer()), 'text/html');
}

// ------------------------------------------------ 1) lista de processos
/* ---------------------------------------------- a tela, por familia de versao

   O QUE MUDA ENTRE AS DUAS INSTALACOES, e so isso:

     * SEI 5.x — tem a visualizacao DETALHADA, que consolida "Recebidos" e
       "Gerados" numa tabela so (`#tblProcessosDetalhado`) e entrega tipo e
       especificacao no `aria-label` do link. Liga-se repostando o formulario com
       `hdnTipoVisualizacao='D'`.
     * SEI 4.0 — mostra as DUAS tabelas (`#tblProcessosRecebidos`,
       `#tblProcessosGerados`), paginadas separadamente, sem `aria-label`. E a
       troca de visualizacao NAO e a funcao global `trocarVisualizacao`: ela nao
       existe la (medido pelo irmao desta casa, `sei_extractor.py:2765-2870`) —
       repostar `hdnTipoVisualizacao='D'` devolve a tela antiga SEM ERRO, que e
       exatamente o motivo de a coleta da FESF ter ficado desabilitada. O caminho
       e o ICONE.

   A versao e consultada UMA vez e vira esta tabela. O resto do parser nao sabe
   em que SEI esta.

   MEDIDO x SUPOSTO
   Medidos (irmao + `referencia-seipro.md` secao S, campo 04/08/2026): os nomes
   das tabelas, `tr[id^="P"]` como linha, `a.processoVisualizado /
   .processoNaoVisualizado`, atribuicao por `procedimento_atribuicao_listar`
   (texto = login, `title` = nome), marcador por `andamento_marcador_gerenciar` +
   cor no nome do arquivo do icone, anotacao por `anotacao_registrar`,
   `img[src*="exclamacao"]`, paginacao por `hdn<Tipo>PaginaAtual` com os `value`
   das options 0-based, e `#hdn<Tipo>NroItens` como total.
   Supostos: que a Detalhada do 4.0 produza `#tblProcessosDetalhado` (por isso a
   tabela e DETECTADA na resposta, nunca assumida) e a ordem dos argumentos do
   tooltip de onde saem tipo/especificacao no 4.0. */
const FAMILIAS = {
  '5': { nome: 'SEI 5.x',  campo_visao: 'hdnTipoVisualizacao', valor_visao: 'D',
         linha: linha5 },
  '4': { nome: 'SEI 4.0',  campo_visao: null, valor_visao: null,
         linha: linha4 },
};
function familia(p) {
  const v = String((p || perfilAtual()).versao || '');
  // Uma versao desconhecida cai na familia 5, que e a instalacao de referencia —
  // e o log diz qual familia foi usada, para ninguem descobrir isso pelo dado.
  return FAMILIAS[v.split('.')[0]] || FAMILIAS['5'];
}

/* As tres listas que a tela pode ter, e os quatro elementos de cada uma. Os
   nomes derivam do tipo, e a busca e por LISTA DE CANDIDATOS, como em
   `pesquisa_sei.js`: o que nao casa vira recusa declarada, nunca campo
   preenchido em silencio. */
const LISTAS = ['Detalhado', 'Recebidos', 'Gerados'];
const IDS_LISTA = tipo => ({
  tabela:    ['tblProcessos' + tipo],
  paginacao: ['sel' + tipo + 'PaginacaoSuperior'],
  pagina:    'hdn' + tipo + 'PaginaAtual',
  total:     ['hdn' + tipo + 'NroItens'],
});

/* O primeiro id da lista que existir no documento. */
function acha(doc, ids) {
  for (const id of ids || []) {
    const el = (id.startsWith('#') || id.includes('['))
      ? doc.querySelector(id) : doc.getElementById(id);
    if (el) return el;
  }
  return null;
}

const numeroDe = el => {
  if (!el) return null;
  const v = String(el.value != null ? el.value : (el.textContent || '')).replace(/\D/g, '');
  return v === '' ? null : parseInt(v, 10);
};

/* Quais listas ESTA tela realmente tem.
   A Detalhada CONSOLIDA as outras duas: quando ela existe, ler tambem Recebidos
   e Gerados seria contar a mesma linha duas vezes. */
function listasPresentes(doc) {
  const achadas = LISTAS.filter(t => acha(doc, IDS_LISTA(t).tabela));
  return achadas.includes('Detalhado') ? ['Detalhado'] : achadas;
}

/* QUAL VISAO ESTA TELA MOSTRA, pela evidencia e nao pelo que se pediu.
   Duas evidencias, porque as duas versoes exibem o detalhe de formas
   diferentes: o 5 troca a tabela por `#tblProcessosDetalhado`; o 4.0 mantem as
   duas tabelas e acrescenta uma linha `trD<id>` sob cada processo. Perguntar so
   pela tabela do 5 faria a tela detalhada do 4.0 ser registrada como reduzida —
   e o registro existe justamente para nao mentir sobre o que foi lido. */
const visaoDe = doc => (acha(doc, IDS_LISTA('Detalhado').tabela)
                     || doc.querySelector('tr[id^="trD"]')) ? 'D' : 'R';

/* O tooltip do SEI: onmouseover="infraTooltipMostrar('<texto>','<titulo>')".
   E de onde o 4.0 tira o que o 5 entrega pronto no `aria-label`. */
function tooltip(el) {
  const m = el && (el.getAttribute('onmouseover') || '')
    .match(/infraTooltipMostrar\('([\s\S]*?)','([\s\S]*?)'\)/);
  return m ? [N(m[1]), N(m[2])] : [null, null];
}

/* O SEI entrega autor e data grudados: "fulano@dominio em 22/11/2024 08:41".
   Guardar a string inteira em anotacao_autor deixava anotacao_data inexistente —
   e com ela morriam a regra de anotacao desatualizada, a linha da gaveta e a
   coluna AnotadoEm do CSV. */
function partirAnotacao(cred) {
  const pa = cred && cred.match(/^(.*?)\s+em\s+(\d{2}\/\d{2}\/\d{4}[^]*)$/i);
  return { autor: pa ? N(pa[1]) : (cred || null), data: pa ? N(pa[2]) : null };
}

const arquivoDoIcone = img =>
  ((img && img.getAttribute('src')) || '').split('/').pop().split('?')[0];

/* A LINHA DE DETALHE do 4.0 (`trD<id>`), em pares `chave: valor`.
   Lida do `innerHTML` e nao do `innerText`: aqui o documento vem do DOMParser e
   nunca e renderizado — `innerText` num documento sem layout devolve o mesmo que
   `textContent`, com as quebras de linha PERDIDAS, e os pares viram uma linha
   so. O irmao le por `innerText` porque roda na pagina viva. */
function paresDoDetalhe(tr) {
  if (!tr || !/^trD/.test(tr.id || '')) return {};
  const out = {};
  ((tr.innerHTML || '').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]*>/g, '\n'))
    .split('\n').forEach(l => {
      const m = l.match(/^\s*([^:]{2,60}?)\s*:\s*(.+?)\s*$/);
      if (!m) return;
      // \u0300-\u036f = os acentos que o NFD separou. Escrito por escape, e nao
      // pelos caracteres: eles ficam fora do Latin-1 e este arquivo atravessa
      // ferramentas que ainda leem em Latin-1.
      const k = N(m[1]).toLowerCase().normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');
      if (k && !(k in out)) out[k] = N(m[2]);
    });
  return out;
}

/* A LINHA NO SEI 5, visualizacao Detalhada. E o parser que roda na SESAB desde
   13/08/2026: as posicoes de celula valem NESTA visualizacao e so nela. */
function linha5(tr) {
  const td = tr.querySelectorAll('td');
  const a  = td[2] && td[2].querySelector('a[href*="procedimento_trabalhar"]');
  if (!a) return null;
  const aria = a.getAttribute('aria-label') || '';
  const k = aria.indexOf(' / ');
  const reg = {
    id: tr.id.replace('P', ''), href: a.getAttribute('href').replace(/&amp;/g, '&'),
    protocolo: N(a.textContent),
    tipo_processo: k > 0 ? aria.slice(0, k).trim() : (N(aria) || null),
    especificacao: k > 0 ? aria.slice(k + 3).trim() : null,
    visualizado: !/processoNaoVisualizado/.test(a.className),
    marcador: null, marcador_cor: null, anotacao: null,
    anotacao_autor: null, retorno: null, doc_incluido: false,
    doc_incluido_rotulo: null
  };
  const aAtr = td[3] && td[3].querySelector('a');
  reg.atribuido_login = aAtr ? N(aAtr.textContent) : null;
  reg.atribuido_nome  = aAtr ? N((aAtr.getAttribute('title') || '')
                          .replace(/^Atribu.do para\s*/i, '')) : null;
  // celula de icones: TODOS os links, nao so o primeiro
  [td[1], td[4]].filter(Boolean).forEach(cel =>
    cel.querySelectorAll('a').forEach(x => {
      const al = N(x.getAttribute('aria-label')) || '';
      const tt = tooltip(x);
      const arq = arquivoDoIcone(x.querySelector('img'));
      if (/^Marcador/i.test(al)) {
        reg.marcador = al.replace(/^Marcador\s*\/\s*/i, '').trim();
        const m = arq.match(/marcador_(.+)\.svg/); reg.marcador_cor = m ? m[1] : null;
      } else if (/^Anota/i.test(al)) {
        reg.anotacao = tt[0] || al.replace(/^Anota..o\s*\/\s*/i, '').trim();
        const pa = partirAnotacao(tt[1]);
        reg.anotacao_autor = pa.autor;
        reg.anotacao_data  = pa.data;
      } else if (/Devolver|Retorno/i.test(al)) {
        reg.retorno = al.replace(/^Para Devolver\s*\/\s*/i, '').trim();
      }
      if (/exclamacao/.test(arq)) {
        reg.doc_incluido = true;
        // O QUE o icone diz. Sem isto nao da para saber se "novo" e novo para
        // a MESA (documento incluido por outra unidade) ou novo para a PESSOA
        // (desde o ultimo acesso dela) — e disso depende se o campo pode ou
        // nao ser reaproveitado entre colegas.
        reg.doc_incluido_rotulo = al || tt[0] || null;
      }
    }));
  return reg;
}

/* A LINHA NO SEI 4.0. ANCORADA PELO LINK, nunca pela posicao da celula: o mapa
   td[1]/td[2]/td[3] vale na tela do 5 e o proprio irmao avisa que ancorar por
   posicao quebra aqui (`referencia-seipro.md` S.1). */
function linha4(tr) {
  const a = tr.querySelector('a.processoVisualizado, a.processoNaoVisualizado')
         || tr.querySelector('a[href*="procedimento_trabalhar"]');
  if (!a) return null;
  const reg = {
    id: tr.id.replace('P', ''),
    href: (a.getAttribute('href') || '').replace(/&amp;/g, '&'),
    protocolo: N(a.textContent),
    tipo_processo: null, especificacao: null,
    visualizado: !/processoNaoVisualizado/.test(a.className || ''),
    marcador: null, marcador_cor: null, anotacao: null,
    anotacao_autor: null, anotacao_data: null, retorno: null,
    doc_incluido: false, doc_incluido_rotulo: null,
    atribuido_login: null, atribuido_nome: null,
  };

  // ATRIBUICAO: o texto e o login, o `title` e o nome completo (confirmado em
  // campo). O login vem entre parenteses na tela.
  const aAtr = tr.querySelector('a[href*="procedimento_atribuicao_listar"]');
  if (aAtr) {
    reg.atribuido_login = N(aAtr.textContent).replace(/^\(|\)$/g, '') || null;
    reg.atribuido_nome  = N((aAtr.getAttribute('title') || '')
                          .replace(/^Atribu.do para\s*/i, '')) || null;
  }

  // MARCADOR: o link diz que existe; a COR sai do nome do arquivo do icone. Ela
  // e nativa — o `style` colorido que a extensao SEI Pro mostra NAO existe no
  // HTML que o servidor devolve, e descartar o campo por causa disso jogaria
  // fora metade dos marcadores (615 de 1.137, medido em 13/08/2026).
  const aMar = tr.querySelector('a[href*="andamento_marcador_gerenciar"]');
  const imgMar = tr.querySelector('img[src*="marcador"]');
  if (aMar || imgMar) {
    const tt = tooltip(aMar);
    // No SEI real o marcador chega com o PRIMEIRO argumento vazio e o nome no
    // segundo — infraTooltipMostrar('', 'PARA ANÁLISE E ASSINATURA') — ao
    // contrário da anotação, onde o primeiro argumento e o texto. Confirmado
    // em campo (id_procedimento=1169355, FESF/DIGAS/HECC/GAF, 08/09/2026):
    // marcador_cor saia certo (vem do arquivo do icone) e marcador saia nulo
    // porque so o primeiro argumento era lido.
    reg.marcador = tt[1] || tt[0] || N(imgMar && imgMar.getAttribute('title'))
                || N(imgMar && imgMar.getAttribute('alt')) || null;
    const m = arquivoDoIcone(imgMar).match(/marcador_(.+)\.(?:svg|png|gif)/);
    reg.marcador_cor = m ? m[1] : null;
  }

  const aAnot = tr.querySelector('a[href*="anotacao_registrar"]');
  if (aAnot) {
    const tt = tooltip(aAnot);
    reg.anotacao = tt[0] || N(aAnot.getAttribute('title')) || null;
    const pa = partirAnotacao(tt[1]);
    reg.anotacao_autor = pa.autor;
    reg.anotacao_data  = pa.data;
  }

  const imgExc = tr.querySelector('img[src*="exclamacao"]');
  if (imgExc) {
    reg.doc_incluido = true;
    reg.doc_incluido_rotulo = N(imgExc.getAttribute('alt'))
                           || N(imgExc.getAttribute('title')) || null;
  }

  // RETORNO PROGRAMADO: no 5 ele vem rotulado no `aria-label`; aqui e uma
  // varredura pelos rotulos da linha. SUPOSTO — nao foi visto em campo.
  Array.from(tr.querySelectorAll('a')).some(x => {
    const img = x.querySelector && x.querySelector('img');
    const rot = N((x.getAttribute('aria-label') || '') + ' '
                + (x.getAttribute('title') || '') + ' '
                + (img ? (img.getAttribute('alt') || '') : ''));
    if (!/Devolver|Retorno/i.test(rot)) return false;
    reg.retorno = rot.replace(/^Para Devolver\s*\/?\s*/i, '').trim() || rot;
    return true;
  });

  /* TIPO E ESPECIFICACAO — tres fontes, em ordem, e nulo DECLARADO quando
     nenhuma casa (quem le precisa saber que a tela nao mostrava, e nao que o
     processo nao tem):
       1) `aria-label` — existe em alguns 4.0.x; e o formato do 5;
       2) a linha de detalhe `trD<id>`, quando a visao Detalhada esta ligada
          (o irmao le exatamente estes pares);
       3) o tooltip do link — SUPOSTO que o titulo seja o tipo e o texto a
          especificacao. Se estiver invertido, os dois campos saem TROCADOS, e
          nao vazios: e o que a rodada de campo tem de conferir primeiro. */
  const aria = a.getAttribute('aria-label') || '';
  if (aria) {
    const k = aria.indexOf(' / ');
    reg.tipo_processo = k > 0 ? aria.slice(0, k).trim() : (N(aria) || null);
    reg.especificacao = k > 0 ? aria.slice(k + 3).trim() : null;
  }
  if (!reg.tipo_processo) {
    const det = paresDoDetalhe(tr.nextElementSibling);
    reg.tipo_processo = det.tipo || det.tipo_do_processo || det.tipo_de_processo || null;
    reg.especificacao = reg.especificacao || det.especificacao || det.descricao || null;
  }
  if (!reg.tipo_processo) {
    const tt = tooltip(a);
    reg.tipo_processo = tt[1] || null;
    reg.especificacao = reg.especificacao || tt[0] || null;
  }
  return reg;
}

/* LIGAR A VISUALIZACAO DETALHADA — e DIZER qual visao foi lida.

   Falhar aqui nao e motivo para parar: a visao reduzida tem as MESMAS linhas, so
   sem o detalhe. O que nao pode e ninguem ficar sabendo — sem o registro, um
   `tipo_processo` vazio fica indistinguivel de processo sem tipo. */
async function abrirDetalhada(form, action, fam, fonteDoc) {
  if (fam.campo_visao) {
    const sp = new URLSearchParams(new FormData(form));
    sp.set(fam.campo_visao, fam.valor_visao);
    const doc = await postar(action, sp);
    return { doc, visao: visaoDe(doc) };
  }
  const url = urlDaDetalhada(fonteDoc);
  if (url) {
    try {
      const doc = new DOMParser().parseFromString(await pegar(url), 'text/html');
      if (listasPresentes(doc).length) return { doc, visao: visaoDe(doc) };
      erro('o icone da Visualizacao Detalhada abriu uma tela sem lista de '
         + 'processos — seguindo na visao reduzida');
    } catch (e) {
      if (String(e).includes('SESSAO')) throw e;
      erro(`a Visualizacao Detalhada nao abriu (${String(e).slice(0, 40)}) — `
         + 'seguindo na visao reduzida');
    }
  } else {
    log('sem icone de Visualizacao Detalhada nesta tela — visao reduzida');
  }
  // Sem detalhada, reposta o proprio formulario: o documento que a paginacao usa
  // tem de ser a RESPOSTA, porque e nela que vivem os hidden de pagina.
  const doc = await postar(action, new URLSearchParams(new FormData(form)));
  return { doc, visao: 'R' };
}

/* O caminho para a Detalhada no 4.0, tirado da propria tela.
   Nunca montado a mao: `infra_hash` morto nao devolve erro — o SEI INVALIDA a
   sessao de quem esta trabalhando. */
function urlDaDetalhada(doc) {
  for (const a of Array.from(doc.querySelectorAll('a'))) {
    const img = a.querySelector && a.querySelector('img');
    const rot = N((a.getAttribute('aria-label') || '') + ' '
               + (a.getAttribute('title') || '') + ' '
               + (img ? (img.getAttribute('alt') || '') + ' '
                      + (img.getAttribute('title') || '') : '') + ' '
               + (a.textContent || ''));
    if (!/detalhad|ver detalhes/i.test(rot)) continue;
    const href = a.getAttribute('href') || '';
    if (/controlador/.test(href)) return href.replace(/&amp;/g, '&');
    const oc = (a.getAttribute('onclick') || '').match(/'([^']*controlador[^']*)'/);
    if (oc) return oc[1].replace(/&amp;/g, '&');
    // Achou o icone e nenhuma URL nele: dizer, em vez de seguir calado.
    erro('achei o icone da Visualizacao Detalhada e nenhuma URL nele — a '
       + 'listagem vai sair da visao reduzida');
    return null;
  }
  return null;
}

/* `fonte` e o documento de onde sai o form inicial. Existe por causa da troca de
   mesa: a unidade da sessao muda por fetch, mas o DOM VIVO continua na unidade
   antiga — e o action do form vivo carrega infra_unidade_atual da unidade errada.
   Quem troca de mesa passa aqui o documento devolvido pelo POST da troca. */
async function listar(fonte) {
  const doc0 = fonte || document;
  const form = doc0.getElementById('frmProcedimentoControlar');
  if (!form) throw new Error('nao estamos no Controle de Processos');
  const action = form.getAttribute('action');
  const fam = familia();

  const { doc: d0, visao } = await abrirDetalhada(form, action, fam, doc0);

  const f2 = d0.getElementById('frmProcedimentoControlar') || form;
  const base = new URLSearchParams();                // campos vem do form DA RESPOSTA:
  f2.querySelectorAll('input,select').forEach(e => { // e la que existe hdn<Tipo>PaginaAtual
    if (!e.name) return;
    if ((e.type === 'checkbox' || e.type === 'radio') && !e.checked) return;
    base.set(e.name, e.value);
  });
  if (fam.campo_visao) base.set(fam.campo_visao, fam.valor_visao);

  const listas = listasPresentes(d0);
  const out = [], vistos = new Set();
  let semTipo = 0;

  for (const tipo of listas) {
    const ids = IDS_LISTA(tipo);
    const sel = acha(d0, ids.paginacao);
    const pgs = sel && sel.options ? Array.from(sel.options).map(o => o.value) : ['0'];
    const decl = numeroDe(acha(d0, ids.total));       // o total que a TELA declara
    let nesta = 0;
    for (const pg of pgs) {                           // os `value` sao 0-based
      const sp = new URLSearchParams(base);
      sp.set(ids.pagina, pg);
      const doc = await postar(action, sp);
      const tbl = acha(doc, ids.tabela);
      if (tbl) tbl.querySelectorAll('tbody tr[id^="P"]').forEach(tr => {
        nesta++;
        const id = tr.id.replace('P', '');
        if (vistos.has(id)) return;                   // o mesmo processo nas duas listas
        vistos.add(id);
        const reg = fam.linha(tr);
        if (!reg) return;
        if (!reg.tipo_processo) semTipo++;
        // De qual LISTA a linha veio. No 4.0 a tela responde "Gerados x
        // Recebidos" e nao ha o que derivar; na Detalhada do 5 as duas viraram
        // uma e a origem sai de quem gerou (ver exportar()).
        reg.origem_tabela = (tipo === 'Detalhado') ? null : tipo;
        // De qual INSTALACAO. Sem isto a ingestao carimba SESAB por falta de
        // opcao, e o dado de uma fundacao entra na carteira de um orgao do
        // estado, em silencio (`ingestao.py:233-235`).
        reg.instancia = instanciaAtual();
        reg.mesa_coleta = UNIDADE;    // marcado AQUI: o exportar() le do localStorage,
        out.push(reg);                // entao marcar depois de salvar nao teria efeito
      });
      await dorme(240);
    }
    // O TOTAL DECLARADO PELA PROPRIA TELA fecha a conta. Sem ele, uma paginacao
    // que para no meio devolve metade com cara de tudo.
    if (decl != null && nesta < decl) {
      erro(`${tipo}: a tela declara ${decl} processo(s) e a leitura trouxe `
         + `${nesta} — leitura INCOMPLETA desta lista`);
    }
    log(`  ${tipo}: ${nesta} linha(s) em ${pgs.length} pagina(s)`
      + (decl != null ? ` (a tela declara ${decl})` : ''));
  }

  if (!listas.length) {
    /* NENHUMA TABELA CONHECIDA CASOU. Duas coisas muito diferentes se parecem
       aqui, e confundi-las e o modo de falha que este projeto persegue:
       mesa sem processo nenhum (rotina — a conta da SESAB tem 5 assim) e
       seletor quebrado por mudanca de versao. O que separa as duas e a
       EVIDENCIA de que ha processos na tela. */
    const soltas = d0.querySelectorAll('tr[id^="P"]').length;
    const declara = LISTAS.some(t => (numeroDe(acha(d0, IDS_LISTA(t).total)) || 0) > 0);
    if (soltas || declara) {
      throw new Error(`nenhuma tabela de processos casou (${fam.nome}, visao `
        + `${visao}) e ha processos nesta tela (${soltas} linha(s)) — recuso `
        + 'dar a mesa por vazia');
    }
    log(`nenhuma tabela de processos nesta tela (${fam.nome}, visao ${visao}) — `
      + 'esta mesa nao tem processos');
  }
  if (semTipo) {
    log(`${semTipo} de ${out.length} linha(s) sem tipo/especificacao `
      + `(${fam.nome}, visao ${visao})`);
  }
  localStorage.setItem('__SEI_LISTA', JSON.stringify(out));
  log(`lista: ${out.length} processos (${fam.nome}, visao ${visao}, `
    + `${listas.join('+') || 'nenhuma lista'})`);
  return out;
}

// -------------------------------------- 2) historico -> datas (com retomada)
const paraData = s => {                      // "DD/MM/AAAA HH:MM" -> Date
  const m = (s || '').match(/(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
  return m ? new Date(+m[3], +m[2] - 1, +m[1], +(m[4] || 0), +(m[5] || 0)) : null;
};

/* Numa linha de REMESSA, a coluna "Unidade" e o DESTINO; quem remeteu esta escrito
   na descricao ("Processo remetido pela unidade X"). Verificado em campo 13/08/2026:
   em 56 remessas de 3 processos, a coluna nunca coincidiu com o remetente. */
const REMESSA = /^Processo remetido pela unidade\s+(.+)$/i;
const remetente = de => { const m = (de || '').match(REMESSA); return m ? N(m[1]) : null; };

/* Mesas: em quais unidades o processo esta ABERTO hoje.
   Maquina de estados sobre o andamento. O andamento vem do mais recente para o
   mais antigo, entao percorremos ao contrario.

   DOIS ERROS JA PAGOS AQUI — nao reintroduzir:

   1) Fechar `m.un` na remessa fecha QUEM ACABOU DE RECEBER e deixa o remetente
      aberto para sempre. Efeito medido: divergencia com a arvore em 100% dos
      processos com 20+ movimentos (e 74% da base). O fechamento tem de usar a
      unidade escrita na DESCRICAO.

   2) O padrao de abertura trazia `gerado` SEM ancora, entao casava tambem
      "Documento X gerado na unidade Y" e abria unidade que so gerou documento —
      e documento nunca fecha. Ancorar em "Processo ... gerado".

   Mesmo corrigida, esta funcao e CONFERENCIA: a fonte de `mesas` e a arvore. */
function mesasPorAndamento(mov) {
  const aberto = new Map();                  // unidade -> datahora da abertura
  for (let i = mov.length - 1; i >= 0; i--) {   // percorre do mais antigo para o mais novo
    const m = mov[i];
    const rem = remetente(m.de);
    if (rem) {
      aberto.delete(rem);                    // quem remeteu deixa de ter o processo
    } else if (/^Conclus.o do processo na unidade/i.test(m.de)) {
      aberto.delete(m.un);
    } else if (/^Processo recebido na unidade|^Reabertura do processo na unidade/i.test(m.de) ||
               /^Processo\b.*\bgerado\b/i.test(m.de)) {
      aberto.set(m.un, m.dh);
    }
  }
  return [...aberto.entries()].map(([unidade, desde]) => ({ unidade, desde }));
}

/* Fonte independente: a arvore publica as unidades abertas em Nos[0].html.
   Serve para conferir a maquina de estados. */
function mesasPorArvore(htmlArvore) {
  let linha = '';
  (htmlArvore.split('\n') || []).forEach(l => {
    if (l.indexOf('Nos[0].html = ') !== -1) linha = l.split("'")[1] || '';
  });
  if (!linha) return null;
  const div = document.createElement('div');
  return linha.split('<br />').map(p => {
    div.innerHTML = p;
    const siglas = div.querySelectorAll('a.ancoraSigla');
    const txt = N(div.textContent);
    if (!txt) return null;
    // o primeiro fragmento e o rotulo ("Processo aberto nas unidades:"), nao uma unidade
    if (!siglas.length && /aberto nas unidades|^Processo /i.test(txt)) return null;
    return { unidade: N(siglas[0] ? siglas[0].textContent : txt),
             atribuido: siglas.length > 1 ? N(siglas[1].textContent) : null };
  }).filter(Boolean);
}

/* As linhas do historico que mudam a CUSTODIA do processo: geracao, recebimento,
   reabertura, remessa e conclusao. Sao as unicas de que os cinco campos por mesa
   dependem, e as unicas que se persiste — o historico inteiro traria texto livre
   (que pode citar paciente) sem responder a nenhuma pergunta do painel. */
const CUSTODIA = /^Processo\b.*\bgerado\b|^Processo recebido na unidade|^Reabertura do processo na unidade|^Processo remetido pela unidade|^Conclus.o do processo na unidade/i;

/* Os CINCO campos do bloco caro que dependem de QUEM le, derivados para `unidade`.

   Chamada com a unidade da sessao durante a coleta e com a unidade do LEITOR na
   hora de montar a linha de outra mesa. E o que torna o reaproveitamento correto
   por construcao: recalcular, nunca copiar.

   Sem linha nenhuma da unidade pedida, devolve os cinco NULOS e `derivada_para`
   nulo — ausencia significa "nao sei", e quem consome tem de exigir leitura real,
   nunca ler isso como "sem divergencia". */
function camposDaMesa(mov, unidade) {
  const vazio = { recebimento: null, recebimento_por: null, envio: null,
                  unidade_envio: null, marco_unidade: null, derivada_para: null };
  if (!unidade || !Array.isArray(mov)) return vazio;
  const rec = mov.find(m => m.un === unidade &&
              /^Processo recebido na unidade|^Reabertura do processo na unidade/i.test(m.de));
  // A saida e a linha em que a unidade aparece como REMETENTE (na descricao).
  // Procurar por m.un === unidade achava a linha em que ela e o DESTINO — ou seja,
  // a CHEGADA. Os campos envio/unidade_envio vinham invertidos por causa disso.
  const env = mov.find(m => remetente(m.de) === unidade);
  const marco = rec || mov.find(m => m.un === unidade && /^Processo\b.*\bgerado\b/i.test(m.de));
  if (!rec && !env && !marco) return vazio;
  return {
    recebimento: rec ? rec.dh : null,
    recebimento_por: rec ? rec.us : null,
    // envio = quando a unidade remeteu; unidade_envio = para ONDE foi (a coluna da
    // linha de remessa e o destino). Antes gravava a chegada e quem mandou.
    envio: env ? env.dh : null,
    unidade_envio: env ? env.un : null,
    // NAO se persiste "dias_na_unidade": numero de tempo gravado congela e o painel
    // passa a mentir conforme o snapshot envelhece. Guarda-se a DATA-MARCO.
    marco_unidade: marco ? marco.dh : null,
    derivada_para: unidade,
  };
}

function derivar(doc, htmlArvore) {
  const mov = Array.from(doc.querySelectorAll('#tblHistorico tr')).map(tr => {
    const td = tr.querySelectorAll('td');
    if (td.length < 4) return null;
    return { dh: N(td[0].textContent), un: N(td[1].textContent),
             us: N(td[2].textContent), de: N(td[3].textContent) };
  }).filter(x => x && x.un);

  const ger = mov.find(m => /Processo p.blico gerado|Processo restrito gerado/i.test(m.de));
  const daMesa = camposDaMesa(mov, UNIDADE);

  // Quantas paginas o historico tem. Sai do mesmo documento que ja esta parseado —
  // custo zero — e e o que separa "li 100" de "sao 100".
  const selPag = doc.getElementById && doc.getElementById('selInfraPaginacaoSuperior');
  const paginas = selPag && selPag.options.length ? selPag.options.length : 1;


  const mesasA = mesasPorAndamento(mov);
  const mesasT = htmlArvore ? mesasPorArvore(htmlArvore) : null;
  // a arvore e a fonte direta; a maquina de estados fica como conferencia
  const mesas = (mesasT && mesasT.length) ? mesasT : mesasA;

  /* Os quatro campos abaixo custam ZERO requisicao: saem do andamento e da arvore
     que ja foram baixados. Estavam sendo lidos e jogados fora. */

  // nivel de acesso e a hipotese legal vem do proprio movimento de geracao:
  // "Processo restrito gerado, Violacao da Intimidade..." — antes so a data era usada
  let nivel = null, hipotese = null;
  if (ger) {
    nivel = /restrito/i.test(ger.de) ? 'Restrito'
          : /sigiloso/i.test(ger.de) ? 'Sigiloso'
          : /p.blico/i.test(ger.de)  ? 'Público' : null;
    const h = ger.de.match(/gerado,\s*(.+)$/i);
    if (h) hipotese = N(h[1]).replace(/\s*\(autuado em.*$/i, '') || null;
  }

  // tamanho do processo: cada no da arvore alem da raiz e um documento.
  // Serve de proxy de esforco — processo de 28 documentos nao se tria como um de 2.
  const nos = htmlArvore
    ? new Set(Array.from(htmlArvore.matchAll(/Nos\[(\d+)\]/g), m => m[1])).size : 0;

  /* SOBRESTAMENTO e URGENCIA sao pares abre/fecha no andamento. Valem o estado do
     evento MAIS RECENTE de cada par — nao a mera existencia do evento.
     (mov vem do mais novo para o mais antigo, entao o primeiro que casar manda.)

     Medido em 13/08/2026: 63 processos tem "Remocao de sobrestamento" como ultimo
     movimento. Uma amostra anterior de 54 processos nao pegou NENHUM e me levou a
     concluir que sobrestamento nao era usado aqui — conclusao errada, de amostra
     pequena. Estado raro exige a base inteira, nao amostra. */
  const ultimo = re => (mov.find(m => re.test(m.de)) || {}).de || '';
  const uSob = ultimo(/sobrestam/i);
  const uUrg = ultimo(/marca de urg.ncia/i);

  return {
    sobrestado: uSob ? !/remo..o|remov/i.test(uSob) : false,
    urgente:    uUrg ? !/removid/i.test(uUrg) : false,
    nivel_acesso: nivel,
    hipotese_legal: hipotese,
    documentos: nos ? nos - 1 : null,          // -1: o no raiz e o processo
    emails_enviados: mov.filter(m => /correspond.ncia eletr.nica/i.test(m.de)).length,
    anexados: mov.map(m => (m.de.match(/^Processo\s+(\S+)\s+anexado/i) || [])[1]).filter(Boolean),
    assinatura_externa: mov.filter(m => /assinatura externa/i.test(m.de)).length,
    autuacao: ger ? ger.dh : null,
    gerador_unidade: ger ? ger.un : null,          // QUEM abriu o processo
    gerador_usuario: ger ? ger.us : null,
    // Os CINCO campos por mesa saem daqui. Sao os unicos do bloco caro que
    // dependem de quem le, e por isso os unicos que precisam de recalculo.
    ...daMesa,
    // As transicoes de custodia, guardadas para PERMITIR esse recalculo noutra
    // mesa. Sem elas, "recalcular" vira copiar.
    // Para QUAL mesa os cinco campos acima foram derivados. Diferente de
    // daMesa.derivada_para, que fica nulo quando a unidade nao aparece no
    // historico: aqui interessa saber sob que sessao o bloco foi lido.
    mesa_derivada: UNIDADE,
    mov_custodia: mov.filter(m => CUSTODIA.test(m.de)),
    movimentos: mov.length,                    // o que se LEU (teto de 100 por pagina)
    movimentos_paginas: paginas,
    // exato so quando cabe numa pagina; nas outras, quem le tem de dizer "ao menos N"
    movimentos_exato: paginas <= 1 ? mov.length : null,
    // buraco no custodia: paginas do meio nunca lidas. Comeca falso e so vira
    // verdadeiro em consertarTruncados, que e quem descobre quantas paginas ha.
    mov_parcial: false,
    mesas,                                          // onde esta aberto hoje
    mesas_fonte: (mesasT && mesasT.length) ? 'arvore' : 'andamento',
    mesas_divergem: !!(mesasT && mesasT.length &&
      mesasT.map(x => x.unidade).sort().join('|') !== mesasA.map(x => x.unidade).sort().join('|')),
    ultimo_movimento: mov[0] ? { dh: mov[0].dh, un: mov[0].un, de: mov[0].de } : null,
    truncado: mov.length >= PAGINA_HISTORICO
  };
}

// devolve a URL do historico, o HTML da arvore E o mapa de acoes do processo.
// A arvore ja foi baixada de qualquer forma: dela saem as mesas (Nos[0].html) e as
// acoes (Nos[0].acoes), cada uma com infra_hash proprio. Custo zero a mais.
async function urlHistorico(href) {
  const h1 = await pegar(href);
  const src = (h1.match(/id="ifrArvore"[^>]*src="([^"]+)"/) || [])[1];
  if (!src) throw new Error('sem arvore');
  const arvore = await pegar(src.replace(/&amp;/g, '&'));
  const uh = (arvore.match(/['"]([^'"]*acao=procedimento_consultar_historico[^'"]*)['"]/) || [])[1];
  if (!uh) throw new Error('sem historico');
  return { url: uh.replace(/&amp;/g, '&'), arvore, acoes: acoesDaArvore(arvore) };
}

/* Acoes do processo, indexadas por `acao=`. Sao os itens da barra de icones
   (Anotacoes, Acompanhamento Especial, Consultar/Alterar, ...) e cada href ja vem
   carimbado com infra_hash valido — nunca montar essas URLs a mao. */
function acoesDaArvore(arvore) {
  const acoes = {};
  arvore.split('\n').forEach(l => {
    if (l.indexOf('Nos[0].acoes') === -1) return;
    const m = l.match(/'([\s\S]*)'/);
    if (!m) return;
    const d = document.createElement('div');
    d.innerHTML = m[1];
    d.querySelectorAll('a').forEach(a => {
      const h = (a.getAttribute('href') || '').replace(/&amp;/g, '&');
      const ac = (h.match(/acao=([a-z_]+)/) || [])[1];
      if (ac && !acoes[ac]) acoes[ac] = h;
    });
  });
  return acoes;
}

/* Acompanhamento Especial: GRUPO + OBSERVACAO + quem e quando.
   O "grupo" e a categorizacao que a unidade realmente usa (PAGAMENTO, CASOS
   ESPECIAIS, RELATORIOS, nome de hospital...) e NAO sai da lista de processos.
   Nem sempre coincide com o marcador: ha processo com grupo e sem marcador.
   Medido em 13/08/2026: preenchido em 49% da amostra. */
async function acompanhamento(url) {
  const d = new DOMParser().parseFromString(await pegar(url), 'text/html');
  return Array.from(d.querySelectorAll('table tr'))
    .map(tr => Array.from(tr.querySelectorAll('td')).map(c => N(c.textContent)))
    .filter(c => c.length >= 5 && c[1])
    .map(c => ({ grupo: c[1], observacao: c[2], usuario: c[3], data: c[4] }));
}

/* Consultar/Alterar: assuntos (classificacao) e interessados.
   NAO se submete nada aqui — e um GET numa tela de formulario.
   Medido: assuntos 98%, interessados 20%. Ja "Observacoes" (txaObservacoes),
   prioridade e grau de sigilo vieram VAZIOS em 100% da amostra — nao valem a
   requisicao, e por isso nao sao lidos. */
async function dadosCadastro(url) {
  const d = new DOMParser().parseFromString(await pegar(url), 'text/html');
  const opcoes = id => {
    const s = d.getElementById(id);
    return s ? Array.from(s.options).map(o => N(o.text)).filter(Boolean) : [];
  };
  return { assuntos: opcoes('selAssuntos'),
           interessados: opcoes('selInteressadosProcedimento') };
}

async function coletarDatas(lista, opts = {}) {
  const feito = JSON.parse(localStorage.getItem('__SEI_DATAS') || '{}');
  // pendente = nunca coletado OU coletado com erro (falha transitoria tem de ser
  // reprocessada; antes ela virava permanente porque {erro} contava como feito)
  const fila = lista.filter(h => opts.tudo || !feito[h.id] || feito[h.id].erro);
  if (!fila.length) { log('nada pendente'); return feito; }
  const reprocessando = fila.filter(h => feito[h.id] && feito[h.id].erro).length;
  if (reprocessando) log(`${reprocessando} com erro anterior serao refeitos`);

  const t0 = Date.now();
  let i = 0, buf = 0, caiu = false, falhas = 0;
  const total = fila.length;

  async function worker() {
    while (i < fila.length && !caiu) {
      const h = fila[i++];
      try {
        const { url, arvore, acoes } = await urlHistorico(h.href);
        const doc = new DOMParser().parseFromString(await pegar(url), 'text/html');
        const d = derivar(doc, arvore);
        // +2 requisicoes por processo. Pagas porque trazem o que a LISTA nao tem:
        // o grupo do acompanhamento e a classificacao por assunto. As duas em
        // paralelo — sao independentes, e serializa-las dobraria a latencia.
        const [ac, cad] = await Promise.all([
          acoes.acompanhamento_gerenciar ? acompanhamento(acoes.acompanhamento_gerenciar) : [],
          acoes.procedimento_alterar     ? dadosCadastro(acoes.procedimento_alterar)      : null,
        ]);
        d.acompanhamento = ac;
        d.acomp_grupos   = ac.map(x => x.grupo).filter(Boolean);
        // PARA QUAL MESA. O bloco e do processo e vale para todas; o
        // acompanhamento e da mesa (e da pessoa) e nao vale para nenhuma outra.
        d.acomp_mesa     = UNIDADE;
        d.assuntos       = cad ? cad.assuntos : [];
        d.interessados   = cad ? cad.interessados : [];
        // [] por AUSENCIA DA TELA e diferente de [] por processo sem assunto. Sem
        // esta marca, o banco nao sabe distinguir os dois, e reaproveitar um valor
        // cheio sobre o primeiro caso mostraria o que o SEI negaria a quem le.
        d.alterar_disponivel  = !!acoes.procedimento_alterar;
        d.acomp_disponivel    = !!acoes.acompanhamento_gerenciar;
        // Lida DE VERDADE nesta execucao — e `EXEC` e a identidade DESTA execucao,
        // nao um booleano. Com booleano persistido, um SEIAuto.rodar() manual pelo
        // console reexportava com _fresco=true blocos lidos dias antes (o Python e
        // quem zera __SEI_DATAS, nao o .js) e o poco rejuvenescia sobre leitura que
        // nao houve — a corrente de re-carimbo que o teto de 72 h existe para impedir.
        d._fresco = EXEC;
        feito[h.id] = d;
        // NAO guarda a URL: ela carrega infra_hash, que expira. Reusar hash morto
        // nao devolve erro — o SEI INVALIDA A SESSAO de trabalho do usuario.
        // Foi essa reutilizacao que derrubou a sessao repetidamente nos testes.
      } catch (e) {
        if (String(e).includes('SESSAO')) { caiu = true; if (contarQueda()) log('disjuntor: 2a queda, parando'); break; }
        feito[h.id] = { erro: String(e).slice(0, 40) }; falhas++;
      }
      if (++buf >= 5) { buf = 0; localStorage.setItem('__SEI_DATAS', JSON.stringify(feito)); }
      // progresso pelo indice da fila, nao pelo tamanho do objeto: com varios
      // workers o mesmo multiplo de 25 era atingido mais de uma vez e duplicava o log
      if (i % 50 === 0) log(`${i}/${total}…`);
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  localStorage.setItem('__SEI_DATAS', JSON.stringify(feito));

  const seg = Math.round((Date.now() - t0) / 1000);
  if (caiu) { erro(`sessao caiu apos ${Object.keys(feito).length}/${total}. Progresso salvo — rode SEIAuto.rodar() de novo.`); }
  else log(`datas: ${total} em ${seg}s (${falhas} falhas)`);
  // A queda ficava so no log: quem chama recebia `feito` e dava a mesa por completa,
  // entao a execucao terminava com codigo 0 publicando processos sem historico.
  // Lancar aqui e o que faz a mesa cair no catch e entrar em mesas_falhas.
  if (caiu) throw new Error('SESSAO caiu durante a coleta de datas');
  return feito;
}

// ------------------------------- 3) conserta os historicos truncados em 100
async function consertarTruncados(lista) {
  const feito = JSON.parse(localStorage.getItem('__SEI_DATAS') || '{}');
  const alvos = Object.entries(feito).filter(([, v]) => v.truncado && !v.autuacao);
  if (!alvos.length) { log('nenhum historico truncado pendente'); return feito; }
  log(`consertando ${alvos.length} historicos truncados…`);
  const porId = Object.fromEntries((lista || JSON.parse(localStorage.getItem('__SEI_LISTA') || '[]'))
                  .map(r => [r.id, r]));

  for (const [id, v] of alvos) {
    try {
      // SEMPRE redescobre a URL. Nunca reusa hash: hash expirado nao da erro,
      // invalida a sessao de trabalho do usuario.
      if (!porId[id]) continue;
      const { url } = await urlHistorico(porId[id].href);
      const doc = new DOMParser().parseFromString(await pegar(url), 'text/html');
      const form = doc.getElementById('frmProcedimentoHistorico');
      if (!form) continue;
      const sp = new URLSearchParams();
      form.querySelectorAll('input[type=hidden]').forEach(e => { if (e.name) sp.set(e.name, e.value); });
      sp.set('hdnTipoHistorico', 'P');
      const sel = doc.getElementById('selInfraPaginacaoSuperior');
      const ultima = sel ? sel.options.length - 1 : 1;
      sp.set('hdnInfraPaginaAtual', String(ultima));
      const nPag = sel ? sel.options.length : 1;
      const d2 = await postar(form.getAttribute('action'), sp);
      const extra = derivar(d2);
      // A pagina completa do historico traz a linha de GERACAO do processo, e dela
      // saem seis campos — nao so a autuacao. Copiar apenas `autuacao` e limpar a
      // marca `truncado` apagava o sinal de que os outros cinco continuavam vazios.
      if (extra.autuacao) {
        ['autuacao','gerador_unidade','gerador_usuario',
         'nivel_acesso','hipotese_legal'].forEach(k => { if (extra[k] != null) v[k] = extra[k]; });
        // A CONTA CERTA. `extra.movimentos` e a ultima PAGINA, nao o total: gravar
        // isso como "contagem real" fazia um processo de 250 movimentos declarar 50
        // — menos que os 100 que ele ja tinha. O total sai da paginacao.
        v.movimentos_paginas = nPag;
        v.movimentos_exato = (nPag - 1) * PAGINA_HISTORICO + extra.movimentos;
        v.movimentos = v.movimentos_exato;
        v.truncado = false;
        // As paginas do MEIO nunca foram lidas. Um recebimento escondido ali faria
        // o recalculo dos cinco campos por mesa devolver uma data plausivel e
        // errada — com duas paginas nao ha meio, com tres ou mais ha.
        v.mov_parcial = nPag > 2;
        // Uniao das custodias das duas pontas, sem repetir linha.
        const vistos = new Set((v.mov_custodia || []).map(m => m.dh + '|' + m.un + '|' + m.de));
        (extra.mov_custodia || []).forEach(m => {
          const k = m.dh + '|' + m.un + '|' + m.de;
          if (!vistos.has(k)) { vistos.add(k); (v.mov_custodia = v.mov_custodia || []).push(m); }
        });
        // mais antigo por ultimo, como vem do SEI
        (v.mov_custodia || []).sort((a, b) => (paraData(b.dh) || 0) - (paraData(a.dh) || 0));
        // E os cinco campos da mesa refeitos sobre a custodia completada: era isto
        // que o conserto NAO fazia, e por isso 26% da base passava pela trava com
        // marco_unidade em branco e cara de leitura inteira.
        if (!v.mov_parcial) Object.assign(v, camposDaMesa(v.mov_custodia, UNIDADE));
      }
      await dorme(200);
    } catch (e) { if (String(e).includes('SESSAO')) break; }
  }
  localStorage.setItem('__SEI_DATAS', JSON.stringify(feito));
  const restam = Object.values(feito).filter(x => x.truncado && !x.autuacao).length;
  log(`truncados restantes: ${restam}`);
  return feito;
}

// -------------------------------------------- 3b) MESAS: unidades da conta
/* Um usuario do SEI pode estar lotado em varias unidades ("mesas"). O Controle
   de Processos mostra UMA por vez. Para cobrir a conta inteira e preciso
   percorrer todas — e cada troca refaz a lista, porque a carteira e por unidade.

   COMO O SEI 5 REALMENTE EXPOE ISSO (verificado no seibahia, 13/08/2026)
   ----------------------------------------------------------------------
   #lnkInfraUnidade nao tem href: tem onclick com a URL de acao=infra_trocar_unidade
   ja carimbada com infra_hash valido. Essa tela e uma TABELA onde cada unidade e
   uma linha com <input type=radio name=chkInfraItem value=ID> — nao ha um link por
   unidade. A troca se faz por POST no form frmInfraSelecaoUnidade com um campo
   selInfraUnidades=ID (foi assim que a propria funcao selecionarUnidade() do SEI
   fez; nao inventamos o nome do campo, lemos dela).

   ARMADILHA JA PAGA: a versao anterior varria a[href*="infra_unidade_atual"].
   Esse parametro esta em PRATICAMENTE TODA URL do SEI — na tela de controle ele
   casa com 97 links. O resultado era "mesas da conta: Controle de Processos",
   um item de menu tratado como unidade. Pior que falhar: a coleta seguia e dava
   numeros certos por acidente, porque caia na unidade corrente. */
async function descobrirMesas() {
  // (a) SEI antigo: <select> de verdade na barra. Confere o tagName — no SEI 5
  //     'selInfraUnidades' e o nome do hidden do POST, nao um select.
  const sel = document.getElementById('selInfraUnidades');
  if (sel && sel.tagName === 'SELECT' && sel.options.length > 1) {
    return Array.from(sel.options).filter(o => o.value)
      .map(o => ({ id: o.value, sigla: N(o.text), via: 'select' }));
  }
  // (b) SEI 4/5: a URL da tela de selecao sai do onclick — ja vem com hash valido
  const url = urlTrocaUnidade();
  if (!url) {
    erro('nao achei o seletor de unidade — a conta pode ter uma unidade so');
    return [{ id: null, sigla: unidadeAtual(), via: 'atual' }];
  }
  /* A LISTA DE UNIDADES PODE TER MAIS DE UMA PAGINA. A conta da FESF alcanca 33
     mesas; ler so a primeira pagina devolveria uma lista curta com cara de
     completa — e as mesas de fora sumiriam do painel sem uma linha de log. O
     irmao pagina clicando em "Proxima"; aqui a tela e lida por fetch, entao o
     que serve e a URL do proprio link. */
  const mesas = [], vistos = new Set();
  let pagina = url, voltas = 0, declarado = null;
  while (pagina && voltas < 20) {
    voltas++;
    const doc = new DOMParser().parseFromString(await pegar(pagina), 'text/html');
    if (declarado == null) declarado = totalDeUnidades(doc);
    let novas = 0;
    mesasDaTela(doc).forEach(m => {
      if (vistos.has(m.id)) return;
      vistos.add(m.id); mesas.push(m); novas++;
    });
    // Pagina que nao traz nada novo nao paga a proxima requisicao.
    pagina = novas ? proximaPaginaDeUnidades(doc) : null;
  }
  /* O TOTAL QUE A PROPRIA TELA DECLARA fecha a conta ("Lista de Unidades com
     Permissao (N registros)"). Mesa que some da descoberta nao aparece como
     falha em lugar nenhum: ela simplesmente deixa de existir para a coleta. */
  if (declarado != null && mesas.length < declarado) {
    erro(`a tela declara ${declarado} unidade(s) e eu li ${mesas.length} — `
       + 'pode haver mesa que ficou de fora da coleta');
  }
  log(`mesas da conta (${mesas.length}): ${mesas.map(m => m.sigla).join(', ') || '(so a atual)'}`);
  return mesas.length ? mesas : [{ id: null, sigla: unidadeAtual(), via: 'atual' }];
}

/* As mesas de UMA pagina da tela de selecao de unidade.
   O `title` do proprio radio e a sigla no 4.0 (medido pelo irmao); a celula e a
   alternativa, e e o que sempre funcionou no 5. */
function mesasDaTela(doc) {
  const csv = (doc.getElementById('hdnInfraItens') || {}).value || '';
  const declarados = new Set(String(csv).split(',').map(s => N(s)).filter(Boolean));
  return Array.from(doc.querySelectorAll('input[name="chkInfraItem"]'))
    .map(inp => {
      const tr = inp.closest ? inp.closest('tr') : null;
      const td = tr ? tr.querySelectorAll('td') : [];
      return { id: N(inp.value),
               sigla: N(inp.getAttribute('title')) || N(td[1] && td[1].textContent),
               descricao: N(td[2] && td[2].textContent), via: 'selecao' };
    })
    /* Sigla de unidade tem barra — e foi esse filtro que impediu 97 itens de
       menu de virarem "mesas". A excecao legitima e a unidade raiz de uma
       instalacao de orgao unico, e para ela o id declarado em `hdnInfraItens`
       serve de prova de que a linha e mesmo uma unidade. */
    .filter(m => m.id && m.sigla && (/\//.test(m.sigla) || declarados.has(m.id)));
}

/* "Lista de Unidades com Permissao (33 registros)" — o total que a tela declara. */
function totalDeUnidades(doc) {
  const t = N(doc.body ? doc.body.textContent : '');
  const m = t.match(/unidades?[^()]{0,60}\((\d[\d.]*)\s*registros?/i)
         || t.match(/\((\d[\d.]*)\s*registros?\)/i);
  return m ? parseInt(m[1].replace(/\./g, ''), 10) : null;
}

/* A proxima pagina da tela de selecao, quando houver.
   Link de "Proxima" SEM URL (so `onclick` de submit) e recusa DECLARADA: melhor
   dizer que pode ter ficado mesa de fora do que devolver lista curta calada. */
function proximaPaginaDeUnidades(doc) {
  const cand = Array.from(doc.querySelectorAll('a')).find(a => {
    const img = a.querySelector && a.querySelector('img');
    const rot = N((a.textContent || '') + ' ' + (a.getAttribute('title') || '')
              + ' ' + (img ? (img.getAttribute('alt') || '') : ''));
    return /pr.xima|>>/i.test(rot);
  });
  if (!cand) return null;
  const href = cand.getAttribute('href') || '';
  if (/controlador/.test(href)) return href.replace(/&amp;/g, '&');
  const oc = (cand.getAttribute('onclick') || '').match(/'([^']*controlador[^']*)'/);
  if (oc) return oc[1].replace(/&amp;/g, '&');
  erro('a tela de unidades tem "Proxima" e nenhuma URL nele — pode haver mesa '
     + 'que ficou de fora da coleta');
  return null;
}

/* Ultimo documento que sabidamente reflete a unidade ATIVA da sessao.
   Existe porque a troca e feita por fetch: o DOM vivo congela na unidade em que a
   aba foi aberta, e a URL do link dele carrega infra_unidade_atual da unidade
   velha. Reusa-la depois da primeira troca devolve uma tela sem o formulario —
   erro observado como "tela de troca de unidade sem frmInfraSelecaoUnidade". */
let DOC_ATUAL = null;

/* URL da tela "Trocar Unidade", extraida do onclick do link da unidade.
   Nunca montada a mao: sem o infra_hash correto o SEI nao da erro — ele INVALIDA
   a sessao e joga pro login. */
function urlTrocaUnidade() {
  const lnk = (DOC_ATUAL || document).getElementById('lnkInfraUnidade');
  const oc = lnk && lnk.getAttribute('onclick');
  const u = oc && (oc.match(/'([^']*controlador[^']*)'/) || [])[1];
  return u ? u.replace(/&amp;/g, '&') : null;
}

/* Troca a unidade ativa da sessao e CONFIRMA que trocou.
   Confirmar nao e zelo: o POST responde 200 e devolve a tela de controle mesmo
   quando o campo vai errado — foi assim que 'hdnInfraItemId' passou silencioso.

   Devolve o documento do Controle de Processos JA na unidade nova (o proprio SEI
   redireciona pra la), que e o que listar() precisa como ponto de partida. */
async function trocarMesa(mesa) {
  const url = urlTrocaUnidade();
  if (!url || !mesa.id) return null;
  const doc = new DOMParser().parseFromString(await pegar(url), 'text/html');
  const f = doc.getElementById('frmInfraSelecaoUnidade');
  if (!f) { erro('tela de troca de unidade sem frmInfraSelecaoUnidade'); return null; }
  const sp = new URLSearchParams(new FormData(f));
  sp.set('selInfraUnidades', mesa.id);
  const d2 = await postar(f.getAttribute('action'), sp);
  const agora = N((d2.getElementById('lnkInfraUnidade') || {}).textContent);
  if (agora !== mesa.sigla) {
    erro(`troca para ${mesa.sigla} nao pegou (unidade continua ${agora || '?'})`);
    return null;
  }
  DOC_ATUAL = d2;              // a proxima troca sai DAQUI, nao do DOM vivo
  ULTIMA_MESA = mesa.sigla;    // onde a conta esta AGORA, para o alerta da volta
  // Trocar para a unidade em que a sessao JA esta nao redireciona pro Controle de
  // Processos — o SEI devolve outra tela. Como o perfil e persistente, a conta
  // pode comecar a execucao em qualquer mesa, entao esse caso e rotina, nao borda.
  if (!d2.getElementById('frmProcedimentoControlar')) {
    const ir = d2.querySelector('a[href*="acao=procedimento_controlar"]');
    if (!ir) { erro(`${mesa.sigla}: sem caminho para o Controle de Processos`); return null; }
    const d3 = new DOMParser().parseFromString(
                 await pegar(ir.getAttribute('href').replace(/&amp;/g, '&')), 'text/html');
    if (!d3.getElementById('frmProcedimentoControlar')) {
      erro(`${mesa.sigla}: Controle de Processos nao abriu`); return null;
    }
    DOC_ATUAL = d3;
    return d3;
  }
  return d2;
}

/* Inventario da execucao: quais mesas a conta TEM e quais falharam. Carimbado em
   cada registro por exportar(). Redundante de proposito — a saida e um array plano,
   e um envelope quebraria os dois consumidores (coletor e gerador). */
let INVENTARIO = null;
// A unidade em que a sessao estava quando a coleta comecou. Fora da funcao
// porque listar e detalhar agora sao duas chamadas: e a segunda que devolve a
// conta para a mesa de origem, e ela nao veria uma variavel local da primeira.
let ORIGEM = null;
// A unidade da ULTIMA troca bem-sucedida. Serve para dizer, quando a volta
// falhar, ONDE a conta ficou — sem isso o alerta diz que falhou e nao diz onde.
let ULTIMA_MESA = null;
// A volta ja foi feita? `restaurarOrigem` e chamada explicitamente no fim do
// caminho feliz (para o carimbo existir antes de exportar) e de novo no
// `finally`. Sem esta marca, o caminho feliz trocaria de unidade duas vezes.
let RESTAURADA = false;


/* A ORIGEM E DECLARADA POR QUEM CHAMA, nunca herdada do DOM vivo.

   Ela vinha de `unidadeAtual()`, que le o DOM da aba — e o DOM da aba, numa
   estacao de perfil persistente, e o RESIDUO da execucao de ontem. O efeito
   medido em 27/08/2026: as 13 execucoes com dados de 13/08 a 27/08 terminaram
   TODAS em SESAB/SAIS/DGGUP/UMA-CMA, mesa onde a titular praticou ZERO atos nos
   31 meses anteriores. A restauracao "restaurava" para o desvio e o confirmava
   todo dia, com EXIT=0 e sem uma linha de log — um ponto fixo.

   Devolve false quando nao da para prosseguir SEM deslocar a conta. Nesse caso
   nada foi trocado ainda: o unico momento em que abortar sai de graca. */
function definirOrigem(mesas, declarada) {
  ORIGEM = null; ULTIMA_MESA = null; RESTAURADA = false;
  const decl = N(declarada || '');
  const atual = unidadeAtual();
  if (!decl) {
    // DEGRADA para o comportamento antigo, mas dizendo em voz alta. Recusar aqui
    // trocaria "unidade errada em silencio" por "sem dado nenhum", que e o outro
    // modo de falha que este projeto persegue.
    ORIGEM = atual;
    erro('sem unidade de origem declarada: ela sera lida do DOM vivo '
       + `(${atual || '?'}), que e o residuo da execucao anterior — `
       + 'defina SEI_UNIDADE_ORIGEM');
    return true;
  }
  const m = (mesas || []).find(x => x.sigla === decl);
  if (!m || !m.id) {
    erro(`a unidade de origem declarada (${decl}) nao esta entre as mesas da conta`
       + ` — abortando ANTES de deslocar a conta`);
    return false;
  }
  ORIGEM = decl;
  if (atual && atual !== decl) {
    log(`a conta estava em ${atual}; a unidade de origem declarada e ${decl}`);
  }
  return true;
}


/* Devolve a conta para a unidade de origem. NUNCA LANCA e NUNCA e no-op mudo.

   Nao lanca porque e chamada de dentro de `finally`: uma excecao aqui
   substituiria a excecao original e trocaria uma queda de sessao diagnosticavel
   por um erro de restauracao. Devolve boolean; quem quiser saber, pergunta.

   E CONFERE O RETORNO. `trocarMesa` ja compara a unidade do documento devolvido
   pelo POST com a pedida (e a unica leitura de unidade que nao vem do DOM
   congelado) e devolve null quando nao bate. A versao anterior descartava esse
   retorno e ainda engolia a excecao com `.catch(() => {})`. */
async function restaurarOrigem(mesas) {
  if (RESTAURADA) return true;
  if (!ORIGEM) {
    erro('nao consigo devolver a conta: nenhuma unidade de origem definida');
    return false;
  }
  const volta = (mesas || []).find(m => m.sigla === ORIGEM);
  if (!volta || !volta.id) {
    erro(`nao consigo devolver a conta para a unidade ${ORIGEM}: ela nao esta na `
       + 'lista de mesas desta execucao');
    return false;
  }
  try {
    if (!await trocarMesa(volta)) {
      erro(`a unidade NAO voltou para ${ORIGEM}: a conta pode ter ficado em `
         + `${ULTIMA_MESA || '?'}`);
      return false;
    }
  } catch (e) {
    erro(`a unidade NAO voltou para ${ORIGEM} (${String(e).slice(0, 40)}): a conta `
       + `pode ter ficado em ${ULTIMA_MESA || '?'}`);
    return false;
  }
  RESTAURADA = true;
  log(`unidade devolvida para ${ORIGEM}`);
  return true;
}


/* O inventario carimba ONDE A CONTA FICOU. Nenhuma coluna, log ou tabela do
   projeto registrava isso: era impossivel auditar, do dado colhido, se a conta
   voltou. `coletor_sesab.py` le `restaurada` e alerta. */
function carimbarInventario(mesas, falhas) {
  INVENTARIO = {
    mesas_conta: mesas.map(m => m.sigla), mesas_falhas: falhas,
    // DE QUAL INSTALACAO e esta execucao. Fica no inventario para o caso de
    // alguem exportar do console depois, com o perfil ja trocado.
    instancia: instanciaAtual(),
    unidade_origem: ORIGEM,
    unidade_final: RESTAURADA ? ORIGEM : (ULTIMA_MESA || null),
    restaurada: RESTAURADA,
  };
  localStorage.setItem('__SEI_INV', JSON.stringify(INVENTARIO));
  return INVENTARIO;
}
// Identidade DESTA execucao do script. Serve para distinguir "lido agora" de
// "lido numa execucao anterior que deixou o checkpoint no localStorage".
const EXEC = new Date().toISOString();

/* Coleta a conta inteira: uma passada por mesa, dados marcados com a mesa de origem.
   ATENCAO ao volume: cada mesa custa ~3 requisicoes por processo. Quatro mesas de
   200 processos = ~2400 requisicoes. Rode com parcimonia. */
/* METADE 1: as listas. ~13 requisicoes por mesa, e e o que NUNCA se reaproveita
   entre pessoas — marcador, anotacao, atribuido, visualizado e retorno sao da
   mesa que os mostrou, e o custo e proximo de zero. */
async function listarTodasAsMesas(opts = {}) {
  if (!await garantirSessao()) return null;
  // DESCOBRIR ANTES DE DEFINIR: a origem declarada so vale se estiver entre as
  // mesas da conta, e conferir isso exige a lista.
  const todas = await descobrirMesas();
  if (!definirOrigem(todas, opts.origem)) return null;
  /* opts.somente: coleta SO estas siglas. Existe para a prova de campo de um
     parser novo (2 mesas em 2 min, nao 33 em 30) e para a estacao que so quer
     parte da conta. A origem e conferida contra a conta INTEIRA acima, porque a
     volta no fim vai para ela. Sigla pedida que a conta nao tem e ERRO nomeado,
     nunca "0 processos" com cara de mesa vazia. */
  let mesas = todas;
  if (Array.isArray(opts.somente) && opts.somente.length) {
    const pedidas = new Set(opts.somente);
    mesas = todas.filter(m => pedidas.has(m.sigla));
    const faltam = opts.somente.filter(s => !todas.some(m => m.sigla === s));
    if (faltam.length) {
      erro(`--somente pede mesa(s) que esta conta nao tem: ${faltam.join(', ')}`);
      return null;
    }
    log(`somente ${mesas.length} de ${todas.length} mesa(s): ${opts.somente.join(', ')}`);
  }
  const tudo = [], feitas = [], falhas = [];
  try {
  for (const mesa of mesas) {
    // A sigla vem da MESA, nao de unidadeAtual(): a troca e por fetch, entao o
    // DOM vivo ainda mostra a unidade anterior. Foi o que zerou marco_unidade.
    UNIDADE = mesa.sigla || unidadeAtual();
    try {
      let fonte = null;
      if (mesa.id) {
        // trocarMesa DENTRO do try: ela usa pegar(), que lanca em queda de sessao.
        log(`trocando para ${UNIDADE}…`);
        fonte = await trocarMesa(mesa);
        if (!fonte) throw new Error('troca de unidade nao confirmada');
      }
      const lista = await listar(fonte);
      /* CADA MESA GUARDA A PROPRIA LINHA. Um processo aberto em duas unidades
         aparece nas duas listas, e as duas linhas sao DIFERENTES. Guardar uma so
         e escreve-la nos dois snapshots — que era o que se fazia — poe o marcador
         de uma mesa na tela da outra, plausivel e em silencio. */
      lista.forEach(r => { r.mesa_coleta = UNIDADE; });
      tudo.push(...lista);
      feitas.push(`${UNIDADE}:${lista.length}`);
    } catch (e) {
      // Registrar a falha no DADO, nao so no log: sem isso a mesa perdida some do
      // painel e a tela anuncia "5 mesas" como se fosse a conta inteira.
      falhas.push(UNIDADE);
      erro(`mesa ${UNIDADE} falhou ao listar: ${String(e).slice(0, 60)}`);
      if (String(e).includes('SESSAO') && contarQueda()) break;
    }
  }
  // Em que mesas da conta cada processo apareceu. So da para saber DEPOIS de
  // percorrer todas — antes isto era montado durante o laco, o que so funcionava
  // porque havia uma linha unica por processo.
  const porId = new Map();
  tudo.forEach(r => { const a = porId.get(r.id) || []; a.push(r); porId.set(r.id, a); });
  porId.forEach(linhas => {
    const onde = linhas.map(r => r.mesa_coleta);
    linhas.forEach(r => { r.mesas_coleta = onde.slice(); });
  });

  // A VOLTA ACONTECE AQUI, e nao so no `finally`: o retorno desta funcao vai
  // para o servidor, e o carimbo precisa existir quando ele for montado. O
  // `finally` e a rede de seguranca dos outros caminhos de saida.
  await restaurarOrigem(mesas);
  carimbarInventario(mesas, falhas);
  localStorage.setItem('__SEI_LISTA', JSON.stringify(tudo));
  log(`listas: ${tudo.length} linhas em ${feitas.length}/${mesas.length} mesa(s)`);
  log(`por mesa: ${feitas.join(' | ')}`);
  if (falhas.length) erro(`ATENCAO: ${falhas.length} mesa(s) falhou: ${falhas.join(', ')}`);
  // O que o servidor precisa para decidir. So os campos da GUARDA — quem hasheia
  // e o servidor, para nao haver duas implementacoes do mesmo hash divergindo.
  return {
    // A INSTANCIA VAI NO ENVELOPE, e nao so nas linhas: o servidor decide a
    // trava por `(instancia, conta)` antes de olhar processo nenhum.
    instancia: instanciaAtual(),
    mesas: INVENTARIO.mesas_conta, falhas,
    itens: tudo.map(r => ({
      id: r.id, mesa: r.mesa_coleta,
      atribuido_login: r.atribuido_login, marcador: r.marcador,
      marcador_cor: r.marcador_cor, anotacao_data: r.anotacao_data,
      retorno: r.retorno, doc_incluido: r.doc_incluido,
    })),
  };
  } finally {
    // TODA SAIDA DEVOLVE A CONTA. No modo --plano esta metade termina e o
    // coletor fica ate 12 x 120 s perguntando o plano ao servidor: sem isto a
    // conta esperava esse tempo inteiro parada na ultima mesa percorrida.
    await restaurarOrigem(mesas);
  }
}

/* METADE 2: o detalhe. `veredito` e chaveado por MESA e processo —
   "<mesa>\x1f<id>" -> 'completa'|'so_acompanhamento'|'pular'|'canario'|'em_leitura'.
   Por mesa porque a guarda e o acompanhamento sao por mesa: o mesmo processo
   recebe vereditos diferentes nas duas, legitimamente. Chave ausente vale
   'completa'; plano vazio = ler tudo, o comportamento de antes do poco. */
async function detalharTodasAsMesas(veredito, opts = {}) {
  veredito = veredito || {};
  let mesas = [];
  try {
  const tudo = JSON.parse(localStorage.getItem('__SEI_LISTA') || '[]');
  if (!tudo.length) { erro('nenhuma lista guardada — rode listarTodasAsMesas() antes'); return null; }
  INVENTARIO = JSON.parse(localStorage.getItem('__SEI_INV') || 'null') || INVENTARIO;
  const falhas = (INVENTARIO && INVENTARIO.mesas_falhas) || [];
  // DENTRO DO try: `descobrirMesas` usa `pegar()`, que lanca em queda de sessao.
  // Fora dele, a excecao subia por `rodarTodasAsMesas` (que nao tem try),
  // atravessava o `pg.evaluate` e caia no except generico do coletor — exit 4,
  // sem restauracao e sem `ctx.close()`.
  mesas = await descobrirMesas();
  // A metade 2 roda noutro `pg.evaluate`: redefine a origem em vez de confiar
  // no estado deixado pela metade 1.
  if (!definirOrigem(mesas, opts.origem)) return null;
  const jaLido = new Set();                 // detalhe e por PROCESSO, nao por mesa
  let devidos = 0, lidos = 0, pulados = 0;

  const visitadas = new Set();
  for (const mesa of mesas) {
    const sigla = mesa.sigla;
    if (falhas.includes(sigla)) continue;   // a lista dela nem existe
    const daMesa = tudo.filter(r => r.mesa_coleta === sigla);
    if (!daMesa.length) { visitadas.add(sigla); continue; }

    const cheia = [], soAcomp = [];
    daMesa.forEach(r => {
      const v = veredito[sigla + '\x1f' + r.id] || 'completa';
      if (v === 'pular' || v === 'em_leitura') { r._pulado = true; pulados++; return; }
      /* O detalhe e do PROCESSO: lido uma vez, e os cinco campos por mesa saem do
         mov_custodia em exportar(). Reler as 5 requisicoes para a segunda mesa
         seria pagar pela mesma resposta.

         O ACOMPANHAMENTO nao: ele e da mesa (e da pessoa). A segunda mesa cai no
         caminho barato — 3 requisicoes — em vez de herdar o da primeira, que era o
         unico campo que o desenho do poco declara nao cruzar. Na conta real sao 9
         processos, ~27 requisicoes por dia. */
      if (jaLido.has(r.id)) { soAcomp.push(r); r._pulado = true; devidos++; return; }
      if (v === 'so_acompanhamento') { soAcomp.push(r); r._pulado = true; }
      else cheia.push(r);
      devidos++;
    });
    if (!cheia.length && !soAcomp.length) { visitadas.add(sigla); continue; }

    UNIDADE = sigla;
    try {
      if (mesa.id) {
        log(`trocando para ${sigla}…`);
        if (!await trocarMesa(mesa)) throw new Error('troca de unidade nao confirmada');
      }
      if (cheia.length) {
        log(`detalhando ${cheia.length} processo(s) em ${sigla}`);
        await coletarDatas(cheia, opts);
        // Conserto AQUI, ainda nesta mesa: consertarTruncados precisa do href da
        // listagem, que so vale enquanto a sessao esta na unidade que o produziu.
        await consertarTruncados(cheia);
        cheia.forEach(r => jaLido.add(r.id));
        lidos += cheia.length;
      }
      if (soAcomp.length) {
        log(`${soAcomp.length} processo(s) so precisam do acompanhamento em ${sigla}`);
        lidos += await somenteAcompanhamento(soAcomp);
      }
      visitadas.add(sigla);
    } catch (e) {
      falhas.push(sigla);
      erro(`mesa ${sigla} falhou no detalhe: ${String(e).slice(0, 60)}`);
      if (String(e).includes('SESSAO') && contarQueda()) break;
    }
  }

  /* O DISJUNTOR SAI DO LACO. As mesas que ele nunca chegou a visitar tem lista
     (a metade 1 rodou) e nao tem detalhe nenhum — e, sem entrarem em mesas_falhas,
     nascem como snapshot CORRENTE com o historico todo em branco e sem alerta,
     porque a contagem de processos nao caiu. Coleta parcial com cara de completa,
     que e o modo de falha que este projeto persegue. */
  mesas.forEach(m => {
    if (m.sigla && !visitadas.has(m.sigla) && !falhas.includes(m.sigla)) falhas.push(m.sigla);
  });
  await restaurarOrigem(mesas);
  carimbarInventario(mesas, falhas);
  log(`detalhe: ${lidos}/${devidos} lido(s), ${pulados} linha(s) servida(s) pelo poco`);
  if (falhas.length) erro(`ATENCAO: ${falhas.length} mesa(s) ficou de fora: ${falhas.join(', ')}`);
  // As marcas de pulado vivem em `tudo`. Persistir E passar adiante: o arquivo
  // guardado serve a um exportar() manual depois; o argumento e o que garante que
  // esta execucao exporte o que ela mesma decidiu.
  localStorage.setItem('__SEI_LISTA', JSON.stringify(tudo));
  return exportar(tudo);
  } finally {
    await restaurarOrigem(mesas);
  }
}

/* O caminho barato: o bloco do processo vale, so o ACOMPANHAMENTO e meu.
   3 requisicoes em vez de 5 — e o acompanhamento nao atravessa pessoa porque
   nao esta provado que a tela do SEI nao recorta por usuario. */
async function somenteAcompanhamento(fila) {
  /* GAVETA PROPRIA, chaveada por (id, MESA). Gravar isto em __SEI_DATAS parecia
     natural e fazia duas coisas erradas de uma vez: o processo passava a contar
     como JA FEITO para coletarDatas() — cujo filtro e `!feito[h.id]` —, de modo
     que a leitura completa dele noutra mesa era pulada em silencio; e, como a
     chave era so o id, a ultima mesa a escrever apagava o acompanhamento das
     outras. */
  const acomps = JSON.parse(localStorage.getItem('__SEI_ACOMP') || '{}');
  let n = 0;
  for (const h of fila) {
    try {
      const { acoes } = await urlHistorico(h.href);
      const ac = acoes.acompanhamento_gerenciar
        ? await acompanhamento(acoes.acompanhamento_gerenciar) : [];
      // NAO carimba _fresco: o bloco nao foi lido. Carimbar aqui faria o poco
      // rejuvenescer sobre uma leitura que nao houve.
      acomps[h.id + '@' + UNIDADE] = {
        acompanhamento: ac, acomp_grupos: ac.map(x => x.grupo).filter(Boolean),
        acomp_disponivel: !!acoes.acompanhamento_gerenciar, exec: EXEC };
      n++;
      await dorme(200);
    } catch (e) {
      if (String(e).includes('SESSAO')) { contarQueda(); break; }
    }
  }
  localStorage.setItem('__SEI_ACOMP', JSON.stringify(acomps));
  return n;
}

/* A composicao, para quem chama uma coisa so. Sem plano: le tudo. */
async function rodarTodasAsMesas(opts = {}) {
  const r = await listarTodasAsMesas(opts);
  if (!r) return;
  return detalharTodasAsMesas(opts.veredito || {}, opts);
}

// ----------------------------------------------------- 4) junta e exporta
/* `lista` opcional: quem acabou de decidir o que foi pulado passa o proprio array,
   em vez de faze-lo voltar do localStorage. Sem isso, as marcas `_pulado` feitas em
   detalharTodasAsMesas() se perdiam no reparse e TODO processo servido pelo poco
   saia carimbado como "ninguem conseguiu ler". O fallback ao localStorage fica,
   porque SEIAuto.exportar() chamado do console depois precisa dele. */
function exportar(lista) {
  lista = lista || JSON.parse(localStorage.getItem('__SEI_LISTA') || '[]');
  const datas = JSON.parse(localStorage.getItem('__SEI_DATAS') || '{}');
  // Duas gavetas: BLOCO (por processo) e ACOMPANHAMENTO (por processo E mesa).
  const acomps = JSON.parse(localStorage.getItem('__SEI_ACOMP') || '{}');
  const saida = lista.map(r => {
    const d = datas[r.id] || {};
    const ac = acomps[r.id + '@' + r.mesa_coleta];
    const o = { ...r };
    delete o.href;
    // ATENCAO: esta lista e copia campo a campo. Campo derivado que nao esteja
    // aqui e calculado e jogado fora em silencio — foi o que aconteceu com
    // marco_unidade quando ele substituiu dias_na_unidade.
    ['autuacao','gerador_unidade','gerador_usuario','movimentos','mesas','mesas_fonte',
     'mesas_divergem','ultimo_movimento','truncado',
     'acompanhamento','acomp_grupos','assuntos','interessados',
     'nivel_acesso','hipotese_legal','documentos','emails_enviados',
     'anexados','assinatura_externa','sobrestado','urgente',
     // marcas novas: sem elas o servidor nao consegue distinguir leitura inteira
     // de leitura com buraco, nem valor vazio de tela indisponivel.
     'mov_custodia','mov_parcial','movimentos_exato','movimentos_paginas',
     'mesa_derivada','alterar_disponivel','acomp_disponivel','acomp_mesa'
    ].forEach(k => o[k] = d[k] ?? null);
    // Lida de verdade nesta execucao? Falso tambem quando o detalhe nao veio.
    o._fresco = d._fresco === EXEC;

    /* O ACOMPANHAMENTO NAO ATRAVESSA MESA. Ele vinha junto no bloco copiado acima,
       o que fazia a linha da mesa B mostrar o grupo do Acompanhamento Especial da
       mesa A — e o servidor gravava esse conteudo sob mesa=B, contaminando o poco
       de forma persistente. Aqui ele e reposto pela leitura DESTA mesa, ou apagado. */
    const doBloco = d.acomp_mesa && d.acomp_mesa === r.mesa_coleta && d._fresco === EXEC;
    if (ac && ac.exec === EXEC) {
      o.acompanhamento = ac.acompanhamento;
      o.acomp_grupos = ac.acomp_grupos;
      o.acomp_disponivel = ac.acomp_disponivel;
      o._acomp_fresco = true;
    } else if (doBloco) {
      o._acomp_fresco = true;               // veio da leitura completa DESTA mesa
    } else {
      // Nem lido aqui, nem lido para esta mesa: a tela dira "nao lido nesta coleta",
      // que e verdade, em vez de mostrar o de outra unidade.
      o.acompanhamento = null;
      o.acomp_grupos = null;
      o.acomp_disponivel = null;
      o._acomp_fresco = false;
    }

    /* OS CINCO CAMPOS POR MESA. Derivados para a mesa DESTA linha, nunca copiados
       da mesa que leu o detalhe.

       Se o bloco foi lido sob esta mesma mesa, o que derivar() ja calculou vale e
       nao ha o que refazer. Se veio de outra, o mov_custodia responde — o
       historico do SEI e global, entao a resposta e a mesma que uma releitura
       daria; releitura aqui seria gasto sem informacao nova.

       Com mov_parcial (paginas do meio nunca lidas) o recalculo para outra mesa e
       RECUSADO: um recebimento escondido no buraco produziria uma data plausivel e
       velha, que e o pior desfecho possivel numa tela de triagem. */
    const CINCO = ['recebimento','recebimento_por','envio','unidade_envio','marco_unidade'];
    let daMesa;
    if (d.mesa_derivada && d.mesa_derivada === r.mesa_coleta) {
      daMesa = { derivada_para: d.mesa_derivada };
      CINCO.forEach(k => { daMesa[k] = d[k] ?? null; });
    } else if (d.mov_parcial) {
      daMesa = { derivada_para: null };
      CINCO.forEach(k => { daMesa[k] = null; });
    } else {
      daMesa = camposDaMesa(d.mov_custodia, r.mesa_coleta);
    }
    CINCO.forEach(k => { o[k] = daMesa[k] ?? null; });
    // Nao e "sem divergencia": e "nao sei". Quem consome tem de exigir leitura real.
    o.mesa_indeterminada = !!(d.mov_custodia && !daMesa.derivada_para);
    // Sem inventario, uma coleta parcial fica indistinguivel de uma completa.
    o.mesas_conta  = INVENTARIO ? INVENTARIO.mesas_conta  : [r.mesa_coleta].filter(Boolean);
    o.mesas_falhas = INVENTARIO ? INVENTARIO.mesas_falhas : [];
    /* DE QUAL INSTALACAO DO SEI E ESTA LINHA. Sem o campo, `ingestao.py:233-235`
       carimba 'SEI-SESAB' — que era ler o que existia enquanto so havia uma
       instalacao, e vira invencao no dia em que ha duas. A ordem e: o que a
       linha trouxe da coleta, senao o inventario da execucao, senao o perfil
       de agora. */
    o.instancia = r.instancia
               || (INVENTARIO && INVENTARIO.instancia)
               || instanciaAtual();
    // ONDE A CONTA FICOU. Nenhuma coluna, log ou tabela do projeto registrava
    // isso: era impossivel auditar, do dado colhido, se a sessao voltou para a
    // unidade da titular. Sem este carimbo o desvio de 13/08 a 27/08 ficou
    // invisivel por 14 dias, com EXIT=0 todo dia.
    o.unidade_origem = INVENTARIO ? (INVENTARIO.unidade_origem || null) : null;
    o.unidade_final  = INVENTARIO ? (INVENTARIO.unidade_final  || null) : null;
    o.unidade_restaurada = INVENTARIO ? !!INVENTARIO.restaurada : null;
    // datas ausentes = historico nao coletado; sem esta marca a linha parece um
    // processo sem movimento, em vez de um processo que ninguem conseguiu ler.
    // Linha PULADA nao e linha sem historico: o bloco dela vem do poco. Sem esta
    // distincao, todo processo reaproveitado entraria com a marca de "ninguem
    // conseguiu ler" e acenderia o alarme errado.
    o._pulado = !!r._pulado;
    o._acomp_fresco = !!d._acomp_fresco;
    o.sem_historico = !r._pulado && (!datas[r.id] || !!datas[r.id].erro);
    /* origem nao existe na visualizacao detalhada (ela consolida as duas listas):
       deriva-se de quem gerou o processo.

       A comparacao e contra as mesas da CONTA, nao contra mesas_coleta. mesas_coleta
       lista onde o processo aparece HOJE; um processo gerado na CESS e ja remetido
       para outra unidade nao consta mais na CESS, e era classificado como "Recebido"
       — quando a propria conta o gerou. */
    const nossas = (INVENTARIO && INVENTARIO.mesas_conta && INVENTARIO.mesas_conta.length)
      ? INVENTARIO.mesas_conta
      : (r.mesas_coleta || [r.mesa_coleta].filter(Boolean));
    /* No 4.0 nao ha o que derivar: a tela tem UMA TABELA PARA CADA e a linha
       sabe de qual veio. Derivar quando a resposta esta escrita na tela e
       trocar o que o SEI diz por uma inferencia nossa. */
    delete o.origem_tabela;
    o.origem = r.origem_tabela || (o.gerador_unidade
      ? (nossas.includes(o.gerador_unidade) ? 'Gerados' : 'Recebidos')
      : null);
    return o;
  });
  const b = new Blob([JSON.stringify(saida, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = 'sei_sesab_' + new Date().toISOString().slice(0, 10) + '.json';
  document.body.appendChild(a); a.click(); a.remove();
  log(`exportado: ${saida.length} processos`);
  return saida;
}

// ------------------------------------------------------------------ rodar
async function rodar(opts = {}) {
  // NAO liga keep-alive: a propria coleta e trafego constante e mantem a sessao.
  // Se voce for deixar a aba parada entre execucoes, ligue manualmente.
  try {
    if (!await garantirSessao()) return;              // loga; se pedir 2FA, avisa e para

    // encadeia sozinho ate chegar no Controle de Processos, sem exigir nova execucao
    for (let t = 0; t < 12 && !document.getElementById('frmProcedimentoControlar'); t++) {
      const lnk = document.getElementById('lnkControleProcessos');
      if (lnk && t === 0) { log('abrindo Controle de Processos…'); lnk.click(); }
      await dorme(500);
    }
    if (!document.getElementById('frmProcedimentoControlar')) {
      erro('nao cheguei ao Controle de Processos. Abra a tela e rode de novo.');
      return;
    }

    // Sem isto, UNIDADE fica '' e NENHUM movimento casa: marco_unidade sai nulo em
    // todos os processos e os "dias na unidade" somem sem erro nenhum.
    UNIDADE = unidadeAtual();
    if (!UNIDADE) { erro('nao consegui ler a unidade atual — abortando'); return; }
    log(`unidade: ${UNIDADE}`);

    const lista = await listar();
    lista.forEach(r => { r.mesa_coleta = UNIDADE; });
    await coletarDatas(lista, opts);
    await consertarTruncados(lista);
    return exportar();
  } catch (e) {
    if (String(e).includes('SESSAO')) erro('sessao caiu. Progresso salvo — rode de novo.');
    else erro('falhou: ' + e);
  } finally {
    keepAlive(false);                                 // garante que nada fica pingando
  }
}

// Resumo do custo de rede de uma execucao completa, para decidir a periodicidade.
function custo() {
  const n = JSON.parse(localStorage.getItem('__SEI_LISTA') || '[]').length || 219;
  // 5, nao 3: procedimento_trabalhar + arvore + historico + acompanhamento_gerenciar
  // + procedimento_alterar. A conta antiga subestimava a rede em 40%.
  const req = 12 + n * 5;
  console.table([
    { etapa: 'listar paginas',        requisicoes: 12 },
    { etapa: 'detalhe (5 por proc)',  requisicoes: n * 5 },
    { etapa: 'TOTAL por execucao',     requisicoes: req },
    { etapa: 'se rodar de hora em hora (24x)', requisicoes: req * 24 },
    { etapa: 'se rodar 2x por dia',    requisicoes: req * 2 },
  ]);
  log('2x por dia e suficiente para triagem. De hora em hora sao ~16 mil requisicoes/dia.');
}

function limparCache() {
  ['__SEI_LISTA','__SEI_DATAS','__SEI_ACOMP','__SEI_HREFS','__SEI_INV'].forEach(k => localStorage.removeItem(k));
  log('cache de coleta limpo (credencial preservada)');
}

// ------------------------------------------------------------ acompanhamento
/* ACOMPANHAMENTO — ler UM processo por numero, fora de qualquer mesa.

   E COMPOSICAO, nao leitura nova: a pesquisa por numero (`SEIBusca.pesquisar`)
   devolve o link, `urlHistorico` traz a arvore e a URL do andamento, `pegar`
   traz o andamento e `derivar` produz o registro inteiro. Tres requisicoes por
   processo, alem do POST da propria pesquisa.

   O RESULTADO E FILTRADO, E A LISTA DE CAMPOS E EXPLICITA. `derivar` tambem
   calcula os cinco campos de custodia (`marco_unidade`, `recebimento`,
   `recebimento_por`, `envio`, `unidade_envio`) por `camposDaMesa(mov, UNIDADE)`
   — derivados para a mesa em que a estacao esta parada, que NAO e a mesa deste
   processo. Manda-los ao servidor seria mandar o dado de outra mesa com o nome
   deste processo. Junto com eles viria `mov_custodia`, que carrega nome e login
   de quem movimentou. Por isso a lista aqui e escrita a mao, e nunca um
   espalhamento do objeto: campo novo em `derivar` nao vaza por acidente.

   OS ESTADOS, E NENHUM SILENCIOSO
     'lido'           — leu, e os quatro campos vao junto;
     'nao_encontrado' — a pesquisa por numero nao devolveu linha;
     'sem_acesso'     — o SEI devolveu a pagina SEM o conteudo que so aparece
                        para quem pode ver o processo. E o que os `throw` de
                        `urlHistorico` significam aqui.
   Ficha vazia com cara de "processo sem novidade" seria pior que os tres.

   FALHA TECNICA NAO E ESTADO. Rede que caiu, sessao que morreu, pagina que nao
   parseou: nenhuma delas vira 'sem_acesso'. O item volta com `falha` e SEM
   estado, e quem monta o envelope o deixa de fora — o servidor grava zero para
   ele e ele continua pendente. Carimbar 'sem_acesso' numa falha de rede mentiria
   na tela ("o SEI recusou") E queimaria a chance do dia, porque o servidor
   atualiza `lido_em` em toda recusa. */
async function acompanhar(protocolo, campos) {
  if (!window.SEIBusca) return { protocolo, falha: 'pesquisa_sei.js nao carregado' };
  // `pesquisar` NAO lanca: ele devolve `motivo` preenchido. Tratar excecao aqui e
  // deixar de tratar o caso que acontece.
  const env = await SEIBusca.pesquisar({
    filtros: { numero_sei: protocolo },
    // SEM `tramitacao_unidade`: o processo acompanhado esta, por definicao, fora
    // das mesas de quem procura. Com o filtro ligado, a busca voltaria vazia e o
    // modulo inteiro diria "nao encontrado" para tudo que existe.
    campos: campos || {}, paginas_teto: 1,
    // O href, so aqui e so agora — ver o comentario de `linhas()` em
    // `pesquisa_sei.js`. Ele morre no fim desta funcao.
    com_link: true,
  });
  if (env.motivo) return { protocolo, falha: 'busca: ' + env.motivo };
  const item = (env.itens || [])[0];
  if (!item || !item.link) return { protocolo, estado: 'nao_encontrado' };
  let url, arvore;
  try {
    ({ url, arvore } = await urlHistorico(item.link));
  } catch (e) {
    const m = String(e && e.message ? e.message : e);
    // SO estas duas mensagens sao recusa do SEI. Qualquer outra e falha nossa ou
    // da rede, e nao pode virar afirmacao sobre o acesso da pessoa.
    if (m === 'sem arvore' || m === 'sem historico') {
      return { protocolo, estado: 'sem_acesso' };
    }
    return { protocolo, falha: m.slice(0, 80) };
  }
  let d;
  try {
    d = derivar(new DOMParser().parseFromString(await pegar(url), 'text/html'), arvore);
  } catch (e) {
    return { protocolo, falha: String(e && e.message ? e.message : e).slice(0, 80) };
  }
  return {
    // O PROTOCOLO QUE ENTROU, nunca o que o SEI imprime. O servidor casa a
    // resposta por TEXTO (`receber`, em `acompanhamento.py`), porque foi ele quem
    // mandou este numero; devolver a forma pontuada da tela faria a leitura
    // inteira ser ignorada em silencio quando a pessoa tivesse colado sem ponto.
    protocolo, estado: 'lido', id_sei: item.id_sei || null,
    aberto_em: (d.mesas || []).map(x => x.unidade),
    aberto_em_fonte: d.mesas_fonte || 'andamento',
    ultimo_movimento: d.ultimo_movimento || null,
    documentos: d.documentos, movimentos: d.movimentos,
  };
}

/* A lista inteira, UM DE CADA VEZ. Devolve o envelope que o servidor espera.

   EM SERIE, NUNCA EM PARALELO. A coleta usa `CONC = 4` porque la o que se lê e a
   carteira da propria pessoa e o custo de uma queda e um checkpoint; aqui a
   rajada seria contra processos de outras unidades, e o SEI derruba sessao sob
   rajada — a sessao de TRABALHO da pessoa, que e a mesma. A pausa e a mesma
   `dorme(240)` da paginacao da busca.

   TETO DE RELOGIO PROPRIO, e nao o do agente. O agente mata o coletor por relogio
   de parede e nao fica com nada; aqui, parar sozinho devolve o que JA foi lido, e
   o resto continua pendente para a proxima volta. Cem processos a tres
   requisicoes cada nao cabem num numero que alguem adivinhe: o teto existe para o
   envelope chegar, nao para a lista acabar. */
async function acompanharLista(pedido) {
  const protocolos = (pedido && pedido.protocolos) || [];
  const campos = (pedido && pedido.campos) || {};
  // 9 min, debaixo do teto de 10 do agente: o objetivo e RESPONDER antes de ser
  // morto, porque morto nao devolve envelope nenhum.
  const teto = (pedido && pedido.teto_ms) || 9 * 60 * 1000;
  const saida = { instancia: (pedido && pedido.instancia) || null,
                  leituras: [], falhas: [], motivo: null, pedidos: protocolos.length };
  const t0 = Date.now();
  for (let i = 0; i < protocolos.length; i++) {
    if (i) await dorme(240);
    const r = await acompanhar(protocolos[i], campos);
    if (r.falha) {
      saida.falhas.push({ protocolo: r.protocolo, motivo: r.falha });
      // SESSAO CAIDA PARA TUDO. Insistir so multiplica requisicao invalida contra
      // o SEI, e — pior — todo processo seguinte falharia do mesmo jeito, o que
      // encheria `falhas` de ruido escondendo qual foi a causa.
      if (/SESSAO/i.test(r.falha)) {
        saida.motivo = `sessao caiu apos ${saida.leituras.length} de ${protocolos.length}`;
        break;
      }
    } else {
      saida.leituras.push(r);
    }
    if (Date.now() - t0 > teto) {
      saida.motivo = `teto de tempo da estacao (${Math.round(teto / 60000)} min): `
                   + `${i + 1} de ${protocolos.length}`;
      break;
    }
  }
  log(`acompanhamento: ${saida.leituras.length} lido(s), ${saida.falhas.length} falha(s)`
      + (saida.motivo ? ` — ${saida.motivo}` : ''));
  return saida;
}

window.SEIAuto = { rodar, rodarTodasAsMesas, listarTodasAsMesas, detalharTodasAsMesas,
                   acompanhar, acompanharLista,
                   descobrirMesas, trocarMesa, listar, coletarDatas,
                   consertarTruncados, exportar, credencial, esquecer, limparCache,
                   mesasPorArvore, mesasPorAndamento, camposDaMesa,  // expostos para conferencia
                   perfil, perfilAtual, instanciaAtual,
                   // o parser da tela, exposto para a conferencia sem navegador
                   listasPresentes, paresDoDetalhe, linha4, linha5, mesasDaTela,
                   totalDeUnidades, urlDaDetalhada,
                   keepAlive, custo, logado, garantirSessao, unidadeAtual,
                   ondeEstaACredencial };
log(`SEIAuto pronto (${perfilAtual().instancia}, ${familia().nome}). `
  + 'Primeiro uso: SEIAuto.credencial("login","senha") — depois SEIAuto.rodar()');
log('SEIAuto.custo() mostra o volume de rede por execucao.', '#666a72');
})();
