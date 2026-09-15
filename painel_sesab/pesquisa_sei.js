/* ===========================================================================
   PESQUISA NO SEI — o motor da busca avançada do SEI360.

   COMO ELE CHEGA À TELA
   ---------------------
   Pelo MENU, nunca por URL montada. A regra dura do projeto: requisição com
   `infra_hash` morto não devolve erro — o SEI DERRUBA a sessão de quem está
   trabalhando. Aqui a URL da Pesquisa sai do próprio link do menu, e o POST sai
   do `action` + dos `hidden` do formulário VIVO. Nada é guardado entre execuções.

   POR QUE POR `fetch` E NÃO POR CLIQUE
   ------------------------------------
   O sistema irmão desta casa pagina clicando em "Próxima" e dorme 3 s entre as
   páginas. Medido nos logs dele: 718 processos em 72 páginas levaram 226 s, dos
   quais ~213 s foram o próprio `sleep` — o SEI respondeu em ~30 ms. Aqui a
   paginação é POST direto no mesmo formulário, com a pausa curta que o resto do
   coletor já usa.

   OS IDS SÃO LISTA, E A RECUSA É DECLARADA
   ----------------------------------------
   Cada campo tem vários ids candidatos (o SEI 4.0 e o 5.0.4 divergem), tentados
   em ordem. Campo que não casa com nenhum NÃO é preenchido em silêncio: entra em
   `filtros_recusados`, e quem pediu vê na tela. Filtro que não pegou muda o
   universo da resposta sem mudar uma linha do resultado — no sistema irmão, o
   tipo de processo é casado por `String.includes` sensível a maiúscula e o log
   diz "Filtro aplicado" mesmo quando nada casou.

   O TOTAL DECLARADO É O QUE FECHA A CONTA
   ---------------------------------------
   O SEI escreve "N registros" na própria página. Sem comparar isso com o que
   veio, uma paginação que falha no meio devolve metade com cara de tudo. Aqui o
   total volta no envelope e quem julga é o SERVIDOR.
   =========================================================================== */
(function () {
  if (window.SEIBusca) return;

  const N = s => (s || '').replace(/\s+/g, ' ').trim();
  /* O HASH DE SESSÃO NÃO SAI DAQUI POR NENHUMA PORTA, nem pela do erro. Mensagem
     de exceção de `fetch` pode carregar a URL que falhou, e `saida.motivo` vai
     para DOIS lugares: o envelope, que o servidor guarda, e o `console.log`, que
     o coletor ecoa para o stdout da estação. Hash morto não devolve erro — ele
     DERRUBA a sessão de quem está trabalhando —, então ele não pode ficar em log,
     em anexo nem em banco. Não há caminho conhecido em que isto aconteça hoje; a
     porta é que não fica aberta. O mesmo `semHash` de `acompanharLista`, em
     `automacao_sei.js`. */
  const semHash = m => String(m == null ? '' : m)
    .replace(/infra_hash=[^&\s'"]*/gi, 'infra_hash=…');
  const log = (m, cor = '#0f5257') =>
    console.log('%c[BUSCA] ' + m, `color:${cor};font-weight:bold`);
  const dorme = ms => new Promise(r => setTimeout(r, ms));
  const dec = new TextDecoder('iso-8859-1');       // o SEI responde em ISO-8859-1

  /* O SEI fala ISO-8859-1 nos dois sentidos. Mandar UTF-8 no corpo faz o acento
     virar outra coisa DO LADO DE LÁ, e a busca devolve zero sem erro nenhum.
     NÃO é para tirar o acento do termo (o sistema irmão faz isso e é workaround
     com perda): é para codificar certo. */
  function corpoLatin1(pares) {
    const partes = [];
    for (const [k, v] of pares) {
      partes.push(enc(k) + '=' + enc(v));
    }
    return partes.join('&');
  }
  function enc(s) {
    let fora = '';
    for (const ch of String(s == null ? '' : s)) {
      const c = ch.codePointAt(0);
      if (/[A-Za-z0-9*\-._]/.test(ch)) fora += ch;
      else if (ch === ' ') fora += '+';
      else if (c <= 0xff) fora += '%' + c.toString(16).toUpperCase().padStart(2, '0');
      else fora += encodeURIComponent(ch);        // fora do Latin-1: melhor que perder
    }
    return fora;
  }

  /* FALHA PASSAGEIRA NÃO É RESPOSTA DO SEI, e não pode encerrar a busca.

     Até 15/09/2026 a primeira oscilação de rede — um `fetch` que estoura, um 502
     do balanceador da PRODEB no meio da paginação — virava `motivo`, e o servidor
     a transformava em "falhou" definitivo, com as páginas já lidas descartadas e
     a pessoa tendo de pedir tudo de novo. Repetir a MESMA requisição com o MESMO
     hash vivo é o que alguém faz ao clicar de novo: não derruba sessão.

     O QUE NÃO SE REPETE: sessão caída. Com a sessão morta, repetir só multiplica
     requisição inválida contra o SEI do órgão — e o motivo precisa chegar ao
     servidor como está, porque é outra ação (logar de novo), não esperar. */
  const ESPERAS_REDE_MS = [1500, 4000];

  /* "Failed to fetch" TAMBÉM É SESSÃO CAÍDA, disfarçada. Quando a sessão morre, o
     SEI redireciona para o login do SIP, que é OUTRA origem e não manda CORS: o
     `fetch` lança TypeError em vez de mostrar login.php na URL. Sem esta pergunta,
     a queda de sessão era tratada como rede e repetida duas vezes contra a sessão
     morta. A pergunta é um GET da própria página aberta, sem seguir redirecionamento:
     sessão viva responde 200; morta, redireciona. */
  async function sessaoCaiu() {
    try {
      const r = await fetch(location.href, { credentials: 'same-origin', redirect: 'manual' });
      return r.type === 'opaqueredirect';
    } catch (e) {
      return false;
    }
  }

  async function comRetentativa(o_que, fn) {
    for (let i = 0; ; i++) {
      try {
        return await fn();
      } catch (e) {
        const msg = String(e && e.message ? e.message : e);
        if (/SESSAO caiu/.test(msg) || i >= ESPERAS_REDE_MS.length) throw e;
        if (/Failed to fetch|NetworkError|Load failed/i.test(msg) && await sessaoCaiu()) {
          throw new Error('SESSAO caiu durante a busca');
        }
        log(`${o_que}: ${semHash(msg).slice(0, 80)} — nova tentativa em `
            + `${ESPERAS_REDE_MS[i]} ms`, '#a36b1f');
        await dorme(ESPERAS_REDE_MS[i]);
      }
    }
  }

  /* 5xx é o servidor do SEI (ou o balanceador) dizendo "agora não", e `fetch` não
     o transforma em exceção sozinho — sem esta linha, a página de erro seria lida
     como resultado sem linhas, e a paginação pararia calada. */
  function conferirStatus(r) {
    if (r.status >= 500) throw new Error(`o SEI respondeu ${r.status}`);
  }

  async function pegar(url) {
    return comRetentativa('pagina', async () => {
      const r = await fetch(url, { credentials: 'same-origin' });
      conferirStatus(r);
      const t = dec.decode(await r.arrayBuffer());
      if (/login\.php|Acesso negado|sessão expirad/i.test(t) && !/frmProtocoloPesquisa/i.test(t)) {
        throw new Error('SESSAO caiu durante a busca');
      }
      return t;
    });
  }

  async function postar(action, corpo) {
    return comRetentativa('pesquisa', async () => {
      const r = await fetch(action, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: corpo,
      });
      conferirStatus(r);
      const t = dec.decode(await r.arrayBuffer());
      if (/login\.php/i.test(r.url)) throw new Error('SESSAO caiu durante a busca');
      return new DOMParser().parseFromString(t, 'text/html');
    });
  }

  /* A tela de Pesquisa, alcançada pelo MENU. Devolve o documento. */
  async function abrirPesquisa() {
    const alvos = Array.from(document.querySelectorAll('a[href]'))
      .filter(a => /acao=protocolo_pesquisar|acao=pesquisa/i.test(a.getAttribute('href') || '')
                || /^pesquisa$/i.test(N(a.textContent)));
    if (!alvos.length) throw new Error('nao achei o item Pesquisa no menu');
    const href = alvos[0].getAttribute('href').replace(/&amp;/g, '&');
    const html = await pegar(href);
    return new DOMParser().parseFromString(html, 'text/html');
  }

  /* O primeiro id da lista que existir no documento. */
  function acha(doc, ids) {
    for (const id of ids || []) {
      const el = id.startsWith('#') || id.includes('[')
        ? doc.querySelector(id) : doc.getElementById(id);
      if (el) return el;
    }
    return null;
  }

  /* Monta o corpo do POST a partir do formulário VIVO, preenchendo o que der.
     Devolve {pares, aplicados, recusados, action}. */
  function montar(doc, campos, filtros) {
    const form = doc.getElementById('frmProtocoloPesquisa')
              || doc.querySelector('form[action*="protocolo_pesquisar"]')
              || doc.querySelector('#seiSearch')
              || doc.forms[0];
    if (!form) throw new Error('formulario de pesquisa nao encontrado');

    // Tudo que o form já traz vai junto: hidden de estado, tokens, paginação.
    // Reconstruir o POST "só com o que interessa" é como se perde um hidden que
    // o SEI usa para saber em que tela está.
    const pares = [];
    form.querySelectorAll('input,select,textarea').forEach(e => {
      if (!e.name) return;
      if (e.type === 'checkbox' || e.type === 'radio') {
        if (e.checked) pares.push([e.name, e.value || 'on']);
      } else if (e.tagName === 'SELECT') {
        const o = e.options[e.selectedIndex];
        pares.push([e.name, o ? o.value : '']);
      } else if (e.type !== 'submit' && e.type !== 'button') {
        pares.push([e.name, e.value || '']);
      }
    });
    const por = n => pares.filter(x => x[0] === n);
    const set = (nome, valor) => {
      const j = pares.findIndex(x => x[0] === nome);
      if (j >= 0) pares[j][1] = valor; else pares.push([nome, valor]);
    };
    const tira = nome => {
      for (let j = pares.length - 1; j >= 0; j--) if (pares[j][0] === nome) pares.splice(j, 1);
    };

    const aplicados = {}, recusados = [];
    const recusa = (campo, valor, motivo, extra) =>
      recusados.push(Object.assign({ campo, valor, motivo }, extra || {}));

    // modo Processos
    const modo = acha(doc, campos.modo_processos);
    if (modo && modo.name) set(modo.name, modo.value || 'P');

    // "com tramitação na unidade"
    const chk = acha(doc, campos.tramitacao_unidade);
    if (chk) {
      if (filtros.tramitacao_unidade) { set(chk.name, chk.value || 'on'); aplicados.tramitacao_unidade = true; }
      else tira(chk.name);
    } else if (filtros.tramitacao_unidade) {
      recusa('tramitacao_unidade', true, 'a caixa nao existe nesta versao do SEI');
    }

    // texto simples
    for (const chave of ['especificacao', 'contato', 'assunto', 'observacao',
                         'numero_sei', 'data_de', 'data_ate']) {
      const v = filtros[chave];
      if (!v) continue;
      const el = acha(doc, campos[chave]);
      if (!el || !el.name) { recusa(chave, v, 'campo nao existe nesta versao do SEI'); continue; }
      set(el.name, v);
      aplicados[chave] = v;
    }

    // tipo do processo: é um SELECT, e o valor tem de CASAR com uma option.
    // Casar por `includes` sensível a maiúscula — como o sistema irmão faz — faz
    // "dispensa" não casar com "Dispensa" e a busca voltar sem o filtro, cheia.
    if (filtros.tipo_processo) {
      const sel = acha(doc, campos.tipo_processo);
      if (!sel || !sel.options) {
        recusa('tipo_processo', filtros.tipo_processo, 'campo nao existe nesta versao do SEI');
      } else {
        const alvo = N(filtros.tipo_processo).toLowerCase();
        const op = Array.from(sel.options).find(o => N(o.text).toLowerCase() === alvo)
                || Array.from(sel.options).find(o => N(o.text).toLowerCase().includes(alvo));
        if (op && op.value) { set(sel.name, op.value); aplicados.tipo_processo = N(op.text); }
        else recusa('tipo_processo', filtros.tipo_processo,
                    'nenhuma opcao do SEI casa com esse texto',
                    { options_vistas: sel.options.length });
      }
    }

    // tipo de data
    if (filtros.tipo_data) {
      const sel = acha(doc, campos.tipo_data);
      if (sel && sel.name) { set(sel.name, filtros.tipo_data); aplicados.tipo_data = filtros.tipo_data; }
    }

    // o botão de enviar precisa ir no corpo: alguns forms do SEI decidem a ação por ele
    const bt = acha(doc, campos.enviar);
    if (bt && bt.name) set(bt.name, bt.value || 'Pesquisar');
    void por;
    return { pares, aplicados, recusados, action: form.getAttribute('action') || location.href };
  }

  /* "N registros" na página. É com esse número que o servidor fecha a conta. */
  function totalDeclarado(doc) {
    const txt = N(doc.body ? doc.body.textContent : '');
    const m = txt.match(/(\d[\d.]*)\s*(?:registros?|resultados?|itens?)\s*(?:encontrad|localizad)/i)
           || txt.match(/(?:encontrad\w*|localizad\w*)\s*(\d[\d.]*)\s*registros?/i)
           || txt.match(/Lista de .{0,40}?\((\d[\d.]*)\s*registros?/i);
    // NENHUM REGISTRO É UM TOTAL: zero. Sem esta linha a pesquisa que não acha
    // nada voltava com total nulo, e o servidor a julgava "falhou · o SEI não
    // declarou o total de registros" — o estado `vazia` existia no veredito e era
    // inalcançável. A pessoa lia falha onde o SEI tinha respondido.
    if (!m) {
      return /nenhum\s+(?:registro|resultado|processo)\s+(?:foi\s+)?(?:encontrad|localizad)/i.test(txt)
        ? 0 : null;
    }
    return parseInt(m[1].replace(/\./g, ''), 10);
  }

  /* As linhas do resultado. O SEI 5 entrega tipo e especificação no `aria-label`
     do link; o 4.0 não — daí a leitura por célula como alternativa.

     `comReservados` é a ÚNICA porta pela qual DOIS campos saem daqui, e é fechada
     por omissão. Eles têm razões diferentes que dão no mesmo lugar — nenhum dos
     dois pode entrar no envelope que a busca guarda:

       * `link` — carrega `infra_hash` de sessão, e hash morto não dá erro:
         derruba a sessão de quem está trabalhando;
       * `especificacao` — é o sufixo do mesmo `aria-label` de onde já sai o tipo,
         e é texto que um servidor escreveu, que pode citar paciente. `busca.py`
         a exclui do envelope da busca com motivo escrito, e essa exclusão
         continua valendo: é outra superfície, com outro alcance.

     A porta existe para `SEIAuto.acompanhar()`, que usa os dois na mesma passagem
     do navegador: o link morre no fim da função, e a especificação sobe porque o
     usuário autorizou explicitamente para ESTE módulo em 11/09/2026 (seção 11.2
     do plano). Quem liga isto assume o contrato: usar AGORA, e só onde há
     autorização.

     O agente da estação não tem como ligá-la numa busca: `buscar()`, em
     `sei360_agente.py`, repassa uma lista FIXA de seis chaves do pedido, e
     `com_reservados` não é uma delas. Servidor comprometido não pede nem o href
     nem o texto livre. */
  function linhas(doc, comReservados) {
    const fora = [];
    const tabelas = Array.from(doc.querySelectorAll('table'))
      .filter(t => t.querySelector('a[href*="procedimento_trabalhar"], a[href*="protocolo_visualizar"], a[href*="id_procedimento"]'));
    const tab = tabelas.sort((a, b) => b.rows.length - a.rows.length)[0];
    if (!tab) return fora;
    Array.from(tab.rows).forEach(tr => {
      const a = tr.querySelector('a[href*="id_procedimento"], a[href*="procedimento_trabalhar"], a[href*="protocolo_visualizar"]');
      if (!a) return;
      const href = a.getAttribute('href') || '';
      const idm = href.match(/id_procedimento=(\d+)/) || href.match(/id_protocolo=(\d+)/);
      const aria = a.getAttribute('aria-label') || '';
      const k = aria.indexOf(' / ');
      const cel = Array.from(tr.cells).map(c => N(c.textContent));
      const linha = {
        // O HREF NÃO SAI DAQUI POR PADRÃO. Ele carrega infra_hash de sessão, e
        // hash morto não dá erro: derruba a sessão de quem está trabalhando. Só
        // `comReservados` o entrega, e só para uso imediato — nunca para guardar.
        id_sei: idm ? idm[1] : null,
        protocolo: N(a.textContent),
        tipo_processo: k > 0 ? aria.slice(0, k).trim() : (cel[1] || null),
        unidade_geradora: cel.find(x => /\//.test(x) && !/\d{2}\/\d{2}\/\d{4}/.test(x)) || null,
        usuario_gerador: cel.find(x => /@/.test(x)) || null,
        data_inclusao: (cel.find(x => /^\d{2}\/\d{2}\/\d{4}/.test(x)) || '').slice(0, 10) || null,
      };
      if (comReservados) {
        linha.link = href.replace(/&amp;/g, '&');
        // O MESMO `aria-label` de onde saiu o tipo, do outro lado do ' / '. No
        // SEI 5 ele traz "tipo / especificação" (medido — é o que o cabeçalho
        // desta função já dizia); no 4.0 não há aria-label nenhum, e aí o campo
        // simplesmente NÃO É POSTO. Ausente e vazio são coisas diferentes para
        // quem recebe, e inventar texto num campo que pode citar paciente é pior
        // que não ter o campo.
        const espec = k > 0 ? N(aria.slice(k + 3)) : '';
        if (espec) linha.especificacao = espec;
      }
      fora.push(linha);
    });
    return fora;
  }

  /* O botão/elemento de "próxima página", e o campo de offset se houver. */
  function proxima(doc, pares) {
    const sel = doc.getElementById('selInfraPaginacaoSuperior')
             || doc.querySelector('select[name*="Pagina"]');
    if (sel && sel.options && sel.options.length > 1) {
      const i = sel.selectedIndex;
      if (i + 1 < sel.options.length) return { nome: sel.name, valor: sel.options[i + 1].value };
    }
    // offset: o SEI pagina por `hdnInicio` em múltiplos de 10 em algumas telas
    const off = pares.find(x => /hdnInicio/i.test(x[0]));
    if (off) return { nome: off[0], valor: String((parseInt(off[1] || '0', 10) || 0) + 10) };
    return null;
  }

  /* ------------------------------------------------------------------ pesquisar */
  async function pesquisar(pedido) {
    const t0 = Date.now();
    const { filtros, campos, paginas_teto } = pedido;
    const teto = paginas_teto || 200;
    const saida = {
      envelope: 1, busca_id: pedido.busca_id, instancia: pedido.instancia,
      mesa_confirmada: null, filtros_aplicados: {}, filtros_recusados: [],
      total_declarado: null, paginas_lidas: 0, paginas_teto: teto,
      itens: [], motivo: null,
    };
    try {
      // A MESA ATIVA É LIDA, não suposta. O filtro "com tramitação na unidade"
      // faz o resultado ser função da unidade ativa da SESSÃO — se ela não for a
      // pedida, o resultado é de outra mesa, e o servidor recusa.
      const lnk = document.getElementById('lnkInfraUnidade');
      saida.mesa_confirmada = lnk ? N(lnk.textContent) : null;

      const doc = await abrirPesquisa();
      const m = montar(doc, campos, filtros);
      saida.filtros_aplicados = m.aplicados;
      saida.filtros_recusados = m.recusados;

      let pares = m.pares;
      let d = await postar(m.action, corpoLatin1(pares));
      saida.total_declarado = totalDeclarado(d);
      const vistos = new Set();

      for (let pg = 1; pg <= teto; pg++) {
        saida.paginas_lidas = pg;
        // `com_reservados` vem do PEDIDO e só é ligado por quem roda no mesmo
        // navegador — ver o comentário de `linhas()`.
        const desta = linhas(d, pedido.com_reservados);
        let novos = 0;
        desta.forEach(x => {
          const chave = x.id_sei || x.protocolo;
          if (!chave || vistos.has(chave)) return;
          vistos.add(chave);
          saida.itens.push(Object.assign({ ordem: saida.itens.length + 1 }, x));
          novos++;
        });
        if (saida.total_declarado == null) saida.total_declarado = totalDeclarado(d);
        const prox = proxima(d, pares);
        // PARAR PORQUE ACABOU e parar porque a paginação não andou são coisas
        // diferentes. Quem decide o estado é o servidor, comparando com o total
        // declarado — aqui só se registra o que houve.
        if (!prox || novos === 0) break;
        // O PRAZO É DO MOTOR, e ele devolve o que já leu. Antes, o relógio de fora
        // matava o coletor aos 10 min e a busca grande terminava sem item nenhum;
        // agora ela para antes, com motivo, e o servidor a julga 'parcial'.
        if (pedido.prazo_ms && Date.now() - t0 > pedido.prazo_ms) {
          saida.motivo = `prazo da busca: ${pg} pagina(s) lidas, a pesquisa tinha mais`;
          break;
        }
        const j = pares.findIndex(x => x[0] === prox.nome);
        if (j >= 0) pares[j][1] = prox.valor; else pares.push([prox.nome, prox.valor]);
        await dorme(240);
        d = await postar(m.action, corpoLatin1(pares));
      }
      log(`${saida.itens.length} item(ns) em ${saida.paginas_lidas} pagina(s)`);
    } catch (e) {
      // `semHash` ANTES do corte, e não depois: cortar primeiro poderia deixar
      // meio hash de pé, e meio hash ainda é hash o bastante para quem o coletou.
      saida.motivo = semHash(e && e.message ? e.message : e).slice(0, 200);
      log('falhou: ' + saida.motivo, '#a3391f');
    }
    saida.duracao_s = Math.round((Date.now() - t0) / 1000);
    return saida;
  }

  window.SEIBusca = { pesquisar, totalDeclarado, linhas, montar, corpoLatin1,
                      comRetentativa };
  log('SEIBusca pronto');
})();
