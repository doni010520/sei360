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

  async function pegar(url) {
    const r = await fetch(url, { credentials: 'same-origin' });
    const t = dec.decode(await r.arrayBuffer());
    if (/login\.php|Acesso negado|sessão expirad/i.test(t) && !/frmProtocoloPesquisa/i.test(t)) {
      throw new Error('SESSAO caiu durante a busca');
    }
    return t;
  }

  async function postar(action, corpo) {
    const r = await fetch(action, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: corpo,
    });
    const t = dec.decode(await r.arrayBuffer());
    if (/login\.php/i.test(r.url)) throw new Error('SESSAO caiu durante a busca');
    return new DOMParser().parseFromString(t, 'text/html');
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
    if (!m) return null;
    return parseInt(m[1].replace(/\./g, ''), 10);
  }

  /* As linhas do resultado. O SEI 5 entrega tipo e especificação no `aria-label`
     do link; o 4.0 não — daí a leitura por célula como alternativa.

     `comLink` é a ÚNICA porta pela qual o href sai daqui, e é fechada por
     omissão. Ela existe para `SEIAuto.acompanhar()`, que abre o processo na mesma
     passagem do navegador e joga o link fora em seguida: o envelope que ele manda
     ao servidor tem lista de campos explícita, e `link` não está nela. Quem liga
     isto assume o contrato do comentário abaixo — usar AGORA e não guardar.

     O agente da estação não tem como ligá-la numa busca: `buscar()`, em
     `sei360_agente.py`, repassa uma lista FIXA de seis chaves do pedido, e
     `com_link` não é uma delas. Servidor comprometido não pede href. */
  function linhas(doc, comLink) {
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
        // `comLink` o entrega, e só para uso imediato — nunca para guardar.
        id_sei: idm ? idm[1] : null,
        protocolo: N(a.textContent),
        tipo_processo: k > 0 ? aria.slice(0, k).trim() : (cel[1] || null),
        unidade_geradora: cel.find(x => /\//.test(x) && !/\d{2}\/\d{2}\/\d{4}/.test(x)) || null,
        usuario_gerador: cel.find(x => /@/.test(x)) || null,
        data_inclusao: (cel.find(x => /^\d{2}\/\d{2}\/\d{4}/.test(x)) || '').slice(0, 10) || null,
      };
      if (comLink) linha.link = href.replace(/&amp;/g, '&');
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
        // `com_link` vem do PEDIDO e só é ligado por quem roda no mesmo navegador
        // — ver o comentário de `linhas()`.
        const desta = linhas(d, pedido.com_link);
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
        const j = pares.findIndex(x => x[0] === prox.nome);
        if (j >= 0) pares[j][1] = prox.valor; else pares.push([prox.nome, prox.valor]);
        await dorme(240);
        d = await postar(m.action, corpoLatin1(pares));
      }
      log(`${saida.itens.length} item(ns) em ${saida.paginas_lidas} pagina(s)`);
    } catch (e) {
      saida.motivo = String(e && e.message ? e.message : e).slice(0, 200);
      log('falhou: ' + saida.motivo, '#a3391f');
    }
    saida.duracao_s = Math.round((Date.now() - t0) / 1000);
    return saida;
  }

  window.SEIBusca = { pesquisar, totalDeclarado, linhas, montar, corpoLatin1 };
  log('SEIBusca pronto');
})();
