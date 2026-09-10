# -*- coding: utf-8 -*-
"""
Gera templates/login.html a partir da tela SEI360 original.

POR QUE GERAR, E NAO REESCREVER
-------------------------------
A tela de acesso e do projeto, nao minha. Reescrevi uma na primeira versao e foi
decisao errada: o desenho (partículas, teia, demo de extração, tipografia) e
identidade, e identidade nao se troca por conveniencia de implementacao.

Aqui o original entra inteiro e sofre exatamente quatro classes de mudanca, cada
uma com motivo que sobrevive a discussao:

  1. DEPENDENCIA EXTERNA VIRA LOCAL. unpkg e fonts.gstatic.com nao respondem numa
     rede de orgao que bloqueia saida — e a memoria do projeto registra que
     .ba.gov.br ja cai por causa disso. Sem rede, a tela perde fonte, teia e
     animacao logo na porta de entrada. d3, gsap e as fontes agora sao servidos
     por /estatico/vendor.
  2. NUMERO INVENTADO VIRA NUMERO REAL. "847.392 processos", "R$ 4,21 bi",
     "3.218 sessões ativas", "98,7% de acurácia" sao declaracao factual falsa numa
     tela de autenticacao de orgao publico — e a primeira coisa que alguem de
     dentro confere. Os lugares sao os mesmos; os valores passam a vir do banco.
  3. O FORMULARIO PASSA A FUNCIONAR. CSRF, `name` no "lembrar" (o original so
     tinha `id`, entao o campo nunca era enviado), estados de erro 401/423/429,
     submit travado durante o envio.
  4. AVISO DA SENHA DO SEI. Sem ele alguem digita a senha do SEI aqui por habito,
     e a tela vira exatamente o campo que a arquitetura reprovou.

    python montar_login.py
"""
from pathlib import Path

ORIGEM = Path(__file__).resolve().parent.parent / "SEI360.original.html"
DESTINO = Path(__file__).resolve().parent / "templates" / "login.html"

# ----------------------------------------------------------- 1. dependencias
EXTERNOS = [
    ('<link rel="preconnect" href="https://fonts.googleapis.com" />\n', ""),
    ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n', ""),
    ('<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700'
     '&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" '
     'rel="stylesheet" />',
     '<link rel="stylesheet" href="/estatico/vendor/fontes.css" />'),
    ('<script src="https://unpkg.com/d3@7.9.0/dist/d3.min.js"></script>',
     '<script src="/estatico/vendor/d3.min.js"></script>'),
    ('<script src="https://unpkg.com/gsap@3.12.5/dist/gsap.min.js"></script>',
     '<script src="/estatico/vendor/gsap.min.js"></script>'),
]

# ----------------------------------------------------------- 2. numeros reais
NUMEROS = [
    ('<span>Sistema integrado · <b id="cntProc">847.392</b> processos · '
     '<b id="cntVal">R$ 4,21 bi</b> mapeados</span>',
     '<span>Carteira coberta · <b id="cntProc">{{ n_processos }}</b> processos · '
     '<b id="cntVal">{{ n_unidades }}</b> unidades</span>'),

    ('<div class="stat"><div class="v" id="sExt">128.4k</div><div class="l">extrações / dia</div></div>\n'
     '        <div class="stat"><div class="v neon" id="sConn">2.347</div><div class="l">conexões novas</div></div>\n'
     '        <div class="stat"><div class="v" id="sAcc">98,7%</div><div class="l">acurácia média</div></div>',
     # DOIS cartoes, nao tres: o de "ultima coleta" saiu junto com o resto
     # da operacao (ver o bloco abaixo). `testes.py` cobra a ausencia dele.
     '<div class="stat"><div class="v" id="sExt">{{ n_processos }}</div>'
     '<div class="l">processos na base</div></div>\n'
     '        <div class="stat"><div class="v neon" id="sConn">{{ n_unidades }}</div>'
     '<div class="l">unidades cobertas</div></div>'),

    ('<div class="st"><div class="l">Sessões ativas</div><div class="v" id="sessAct">3.218</div></div>\n'
     '        <div class="st"><div class="l">Status do sistema</div><div class="v neon">● operacional</div></div>',
     # SAI INTEIRO, e a ausencia e a decisao. Quem esta na porta ainda nao
     # entrou: "Sessoes ativas" conta quanta gente do orgao esta trabalhando
     # agora, e "Estado da coleta" diz de fora se o sistema esta atrasado.
     # Os dois viraram teste em `testes.py` ("a porta NAO conta ... para quem
     # esta fora"), e `entrar()` deixou de passar as variaveis. O gerador
     # ficou para tras: regenerar a tela devolvia 500 `'coleta' is undefined`
     # na porta do sistema. Medido em 10/09/2026.
     ''),

    ('<span class="build">v 3.6 · 2026.05.23</span>',
     '<span class="build">v {{ versao }} · {{ hoje }}</span>'),
]

# Afirmacoes sobre ESTE sistema dentro do JS do showcase. A demo de extracao de
# documento fica como esta — documento de exemplo em animacao rotulada como demo
# e ilustracao, nao afirmacao. Ja "monitora 847.392 processos", "23 órgãos",
# "24/7 ATIVO" e "acurácia 98,7%" sao declaracoes sobre o proprio sistema, e
# nenhuma delas e verdade aqui: a coleta e 1x por dia util, sobre 6 unidades, e
# nao existe medicao de acuracia nenhuma.
AFIRMACOES = [
    ("""const corners = [
    {label:'PROCESSOS',  value:'847.392',     x:12, y:38, anchor:'start'},
    {label:'MESAS',      value:'23 órgãos',   x:VB_W-12, y:38, anchor:'end'},
    {label:'COBERTURA',  value:'24/7 ATIVO',  x:12, y:VB_H-26, anchor:'start'},
    {label:'ACURÁCIA',   value:'98,7%',       x:VB_W-12, y:VB_H-26, anchor:'end'}
  ];""",
     """const R = window.SEI360_REAIS || {};
  const corners = [
    {label:'PROCESSOS',  value:R.processos || '—',  x:12, y:38, anchor:'start'},
    {label:'UNIDADES',   value:R.unidades  || '—',  x:VB_W-12, y:38, anchor:'end'},
    {label:'COLETA',     value:R.janela    || '—',  x:12, y:VB_H-26, anchor:'start'},
    {label:'ATUALIZADO', value:R.coleta    || '—',  x:VB_W-12, y:VB_H-26, anchor:'end'}
  ];"""),

    ("""    outLbl.innerHTML = 'CÓRTEX · <b>IA monitora todo o SEI</b>';""",
     """    outLbl.innerHTML = 'CÓRTEX · <b>IA resume a carteira</b>';"""),

    ("""    setHead('cortex', '● VERIFICAÇÃO 24/7', '#00D4FF');
    outFootR.innerHTML = 'IA monitora <b>847.392</b> processos em tempo real';""",
     """    setHead('cortex', '● RESUMO POR IA', '#00D4FF');
    outFootR.innerHTML = 'resumo gerado para <b>' +
      ((window.SEI360_REAIS || {}).resumos || '—') + '</b> processos da carteira';"""),

    # O bloco `counters` inventava numero em tempo real: os processos "nunca param
    # de subir", as sessoes oscilam ±1 a cada 1,5 s e a acuracia sorteia entre
    # 98,4% e 98,9%. Ele SOBRESCREVIA os valores reais que o servidor renderiza —
    # o numero certo aparecia por meio segundo e virava ficcao. Sai inteiro.
    ("""(function counters(){
  const elP=document.getElementById('cntProc');
  const elV=document.getElementById('cntVal');
  let n=847392, v=4.21;
  setInterval(()=>{
    // sempre crescente — nunca para de subir
    n += 1 + Math.floor(Math.random()*4);
    v += Math.abs((Math.random()-.3))*0.003;
    elP.textContent = n.toLocaleString('pt-BR');
    elV.textContent = 'R$ '+v.toFixed(2).replace('.',',')+' bi';
  },500);

  // login-foot session counter
  const sa=document.getElementById('sessAct');
  let s=3218;
  setInterval(()=>{ s += (Math.random()<.5?1:-1); sa.textContent = s.toLocaleString('pt-BR'); }, 1500);

  // slogan footer stats jitter
  const ex=document.getElementById('sExt'), conn=document.getElementById('sConn'), acc=document.getElementById('sAcc');
  let xn=128400, cn=2347;
  setInterval(()=>{
    xn += Math.floor(Math.random()*7);
    if(Math.random()<.4) cn += 1;
    ex.textContent = (xn/1000).toFixed(1).replace('.',',')+'k';
    conn.textContent = cn.toLocaleString('pt-BR');
    const a = 98.4 + Math.random()*0.5;
    acc.textContent = a.toFixed(1).replace('.',',')+'%';
  }, 1400);
})();""",
     """/* Os contadores animados foram removidos na montagem do template.
   Eles nao liam nada: partiam de constantes (processos, valor mapeado, sessoes,
   acuracia sorteada) e subiam sozinhos a cada meio segundo — sobrescrevendo os
   valores reais que o servidor renderiza nesses mesmos elementos.
   Numero que sobe sozinho numa tela de autenticacao de orgao publico e
   declaracao falsa animada. Os valores agora vem do banco, no HTML, e ficam
   parados ate a proxima carga da pagina. Ver montar_login.py. */"""),
]

# "R$ 3.218,40" continua no arquivo e deve continuar: e o valor de um DOCUMENTO DE
# EXEMPLO dentro da animacao rotulada como demonstracao, no mesmo espirito de um
# texto de preenchimento. Afirmacao sobre o sistema e uma coisa; ilustracao de
# como ele le um documento e outra.
DEMO_TOLERADO = ("3.218",)

# ----------------------------------------------------------- 3. formulario
FORM_ANTIGO = '''      <form class="form" id="loginForm" autocomplete="off">
        <div class="field-in">
          <label for="email">E-mail institucional</label>
          <input id="email" name="email" type="email" placeholder="nome.sobrenome@orgao.gov.br" autocomplete="username" required />
        </div>
        <div class="field-in">
          <label for="pw">Senha</label>
          <input id="pw" name="pw" type="password" placeholder="••••••••••" autocomplete="current-password" required minlength="4" />
          <button class="toggle-pw" type="button" id="togglePw">ver</button>
        </div>

        <div class="row-opts">
          <label><input type="checkbox" id="remember" /> Lembrar este dispositivo</label>
          <a href="#" tabindex="0">Esqueci a senha</a>
        </div>

        <button class="submit" type="submit">
          Entrar no SEI360 <span class="ar">▸</span>
        </button>
      </form>

      <div class="request">
        Servidor sem cadastro? <a href="#">Solicitar acesso institucional</a>
      </div>'''

FORM_NOVO = '''      <div class="erro-acesso" id="erro" role="alert" aria-live="assertive"></div>

      <form class="form" id="loginForm" autocomplete="on" novalidate>
        <input type="hidden" name="csrf" id="csrf" />
        <input type="hidden" name="proximo" value="{{ request.args.get('proximo','') }}" />
        <div class="field-in">
          <label for="email">E-mail institucional</label>
          <input id="email" name="email" type="email" placeholder="nome.sobrenome@saude.ba.gov.br" autocomplete="username" required />
        </div>
        <div class="field-in">
          <label for="pw">Senha do SEI360</label>
          <input id="pw" name="pw" type="password" placeholder="••••••••••••" autocomplete="current-password" required minlength="12" />
          <button class="toggle-pw" type="button" id="togglePw">ver</button>
        </div>
        <div class="aviso-sei">Esta <b>não</b> é a sua senha do SEI. O SEI360 nunca pede a senha do SEI.</div>

        <div class="row-opts">
          <label><input type="checkbox" id="remember" name="remember" /> Lembrar este dispositivo</label>
          <span class="dica-acesso">Esqueceu? Fale com a administração — só ela redefine.</span>
        </div>

        <button class="submit" type="submit" id="enviar">
          Entrar no SEI360 <span class="ar">▸</span>
        </button>
      </form>

      <div class="request">
        Servidor sem cadastro? A conta é criada pela administração da unidade.
      </div>'''

# ----------------------------------------------------------- 4. estilo e script
ESTILO = """
<style>
/* --- acréscimos do modo servidor, no vocabulário visual da própria tela --- */
.erro-acesso{display:none;margin:0 0 14px;padding:10px 13px;border-radius:10px;
  border:1px solid rgba(255,90,60,.55);background:rgba(255,90,60,.10);
  color:#ff8b6e;font-size:13px;line-height:1.45}
.erro-acesso.on{display:block}
.aviso-sei{font-size:11.5px;line-height:1.45;opacity:.62;margin:-4px 0 14px}
.aviso-sei b{opacity:.95}
.dica-acesso{font-size:11.5px;opacity:.55}
.field-in input[aria-invalid="true"]{border-color:rgba(255,90,60,.6)!important}
.submit[disabled]{opacity:.6;cursor:progress}
</style>
"""

SCRIPT = """
<script>
/* Ligação da tela ao servidor. O desenho é o original; o que muda é que o
   formulário agora autentica de verdade. */
(() => {
  const $ = i => document.getElementById(i);
  const form = $('loginForm'), erro = $('erro'), botao = $('enviar');
  // CSRF por double-submit: o cookie é legível de propósito e o valor volta no
  // corpo. Sem isto, um formulário hospedado em outro site posta login usando o
  // cookie de quem visita.
  $('csrf').value = (document.cookie.match(/sei360_csrf=([^;]+)/) || [])[1] || '';

  $('togglePw').onclick = () => {
    const c = $('pw');
    c.type = c.type === 'password' ? 'text' : 'password';
    $('togglePw').textContent = c.type === 'password' ? 'ver' : 'ocultar';
  };

  form.onsubmit = async e => {
    e.preventDefault();
    // travar o botão durante o envio: sem isso o duplo clique dispara duas
    // autenticações e gasta duas das cinco tentativas antes do bloqueio.
    botao.disabled = true;
    const rotulo = botao.innerHTML;
    botao.innerHTML = 'Entrando…';
    erro.classList.remove('on');
    $('email').removeAttribute('aria-invalid');
    $('pw').removeAttribute('aria-invalid');
    try {
      const r = await fetch('/entrar', { method: 'POST', body: new FormData(form) });
      const j = await r.json().catch(() => ({}));
      // só caminho interno: o servidor já saneia, isto é a segunda barreira.
      if (r.ok && typeof j.destino === 'string' && j.destino.startsWith('/')
          && !j.destino.startsWith('//')) {
        location.href = j.destino;
        return;
      }
      erro.textContent = j.erro || (r.status >= 500
        ? 'O servidor não respondeu. Tente de novo em instantes.'
        : 'Não foi possível entrar.');
      erro.classList.add('on');
      $('email').setAttribute('aria-invalid', 'true');
      $('pw').setAttribute('aria-invalid', 'true');
      $('pw').value = '';
      $('pw').focus();
    } catch (err) {
      erro.textContent = 'Sem conexão com o servidor.';
      erro.classList.add('on');
    } finally {
      botao.disabled = false;
      botao.innerHTML = rotulo;
    }
  };
})();
</script>
"""


def montar():
    t = ORIGEM.read_text(encoding="utf-8")
    faltando = []

    for antigo, novo in EXTERNOS + NUMEROS + AFIRMACOES:
        if t.count(antigo) != 1:
            faltando.append(antigo[:60])
            continue
        t = t.replace(antigo, novo)

    if t.count(FORM_ANTIGO) != 1:
        faltando.append("bloco do formulário")
    else:
        t = t.replace(FORM_ANTIGO, FORM_NOVO)

    if faltando:
        raise SystemExit("a tela original mudou; estes trechos não casaram:\n  - "
                         + "\n  - ".join(faltando))

    # ORDEM IMPORTA: injetar estilo e script ANTES de embrulhar em {% raw %}.
    # Na primeira versao a injecao vinha depois e procurava "{% raw %}</head>" —
    # que nunca existe, porque o bloco raw comeca la no topo do arquivo. O
    # resultado passava em todas as conferencias e chegava ao navegador sem o
    # script de login: a tela abria bonita e o formulario nao autenticava.
    # O ICONE DA ABA entra aqui, e com caminho LITERAL. Escrito a mao no
    # `login.html` gerado, ele sobrevivia so ate a proxima regeneracao (foi o
    # que aconteceu); e escrito como url_for sairia literal no HTML, porque
    # tudo que este gerador nao injetou vai para dentro de raw — o navegador
    # pedia o proprio texto do template como URL e levava 404 na tela de
    # acesso, a primeira que qualquer pessoa ve. Visto no log em 10/09/2026.
    ICONE = '<link rel="icon" type="image/svg+xml" href="/estatico/favicon.svg">'
    for marca, conteudo in (("</head>", ICONE + chr(10) + ESTILO.strip()
                             + "\n<script>window.SEI360_REAIS = {{ reais|tojson }};</script>"),
                            ("</body>", SCRIPT.strip())):
        if t.count(marca) != 1:
            raise SystemExit(f"nao achei um unico {marca} para injetar")
        t = t.replace(marca, conteudo + "\n" + marca, 1)

    # Jinja so pode enxergar o que EU injetei. O CSS e o JS da tela usam chaves
    # aos milhares e o interpretador de template engasgaria no primeiro seletor.
    import re
    padrao = re.compile(r"(\{\{[^}]*\}\})")
    partes = []
    for pedaco in padrao.split(t):
        if padrao.fullmatch(pedaco):
            partes.append(pedaco)
        elif pedaco:
            partes.append("{% raw %}" + pedaco + "{% endraw %}")
    saida = "".join(partes)

    DESTINO.write_text(saida, encoding="utf-8")
    return saida


ATRASADO = """
ESTE GERADOR ESTA DEFASADO DO `templates/login.html` EM USO. Nao rode sem
reconciliar primeiro — medido em 10/09/2026, regenerando e comparando:

  1. as mensagens de "senha definida" e "codigo esgotado" ({% if trocada %} /
     {% if esgotado %}, mais o estilo .ok-acesso) NAO existem aqui;
  2. o {% if recuperacao_ativa %} que troca "Esqueci a minha senha" por "fale
     com a administracao" NAO existe aqui;
  3. os rotulos 'COLETA' e 'ATUALIZADO' do SVG voltam a aparecer, e `testes.py`
     cobra a ausencia dos dois na tela de acesso;
  4. o cartao "Estado da coleta" volta a usar `coleta.pior`, `resumo_coleta` e
     `selo_coleta`, que `entrar()` nao passa mais — o efeito e 500
     `'coleta' is undefined` NA PORTA DO SISTEMA.

Regenerar hoje troca a tela que funciona por uma que nao abre. O caminho certo
e trazer 1 e 2 para ca (e o icone da aba, ja injetado acima), rodar `testes.py`
e so entao regenerar. Ate lá, editar `templates/login.html` direto e o menor
dos males — e este aviso existe para que a escolha seja consciente.

Para regenerar de proposito, sabendo do acima:  python montar_login.py --forcar
"""


if __name__ == "__main__":
    import sys as _sys
    if "--forcar" not in _sys.argv:
        raise SystemExit(ATRASADO)
    s = montar()
    print(f"template gerado: {DESTINO}  ({len(s)/1024:.0f} KB)")
    print("dependência externa restante:",
          "nenhuma" if "https://unpkg" not in s and "fonts.googleapis" not in s else "AINDA HÁ")
    for n in ("847.392", "R$ 4,21 bi", "98,7%", "128.4k", "2.347", "23 órgãos", "24/7 ATIVO"):
        if n in s:
            print(f"  ATENÇÃO: afirmação fictícia sobre o sistema ainda presente: {n}")
    print("toleradas por serem conteúdo de demonstração:", ", ".join(DEMO_TOLERADO))
    print("injeções Jinja:", s.count("{{"), "| blocos raw:", s.count("{% raw %}"))
