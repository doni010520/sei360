# -*- coding: utf-8 -*-
"""
Gera templates/painel.html a partir do painel autocontido do projeto.

QUAL PAINEL, E POR QUÊ
----------------------
`painel_v2.html` — o que traz rail retrátil de filtros, agrupamento, seletor de
colunas, densidade, tema, menu de conta e estado na URL. É o painel do usuário;
eu não escrevo tela por cima da dele. O `painel_sesab.html` continua existindo e
sendo regerado pelo Task Scheduler como ARQUIVO SOLTO: é o plano B para quando o
servidor estiver fora, e trocar um pelo outro não é decisão de implementação.

O contrato de dados é o mesmo nos dois — as quatro linhas `const` que o gerador
substitui —, então o servidor injeta a carteira já filtrada por unidade sem
tocar em nada do layout.

O que muda em relação ao arquivo solto, e só isso:
  1. as 4 linhas `const`      -> injeção do Jinja, já filtrada por unidade no SQL
  2. o menu de conta          -> quem está logado, configuração, admin, sair
  3. abaixo dos indicadores   -> idade do snapshot POR UNIDADE

Todo o resto entra dentro de {% raw %}: o CSS e o JS usam chaves aos milhares e
não podem passar pelo interpretador de template.

DOIS TEMPLATES, UM GERADOR
--------------------------
`painel.html`        o painel SERVIDO, com moldura, login e as portas do sistema;
`painel_solto.html`  a CÓPIA ESTÁTICA que a rota `/painel.html` entrega como
                     arquivo — o mesmo painel, a mesma carteira, sem servidor.

Dois arquivos e não um template com `{% if solto %}`: o `painel.html` servido
tem de sair byte a byte igual ao de hoje, e um condicional espalhado por dez
pontos do arquivo é a forma mais barata de fazê-lo mudar sem ninguém ver. Cada
diferença do modo solto está listada em `montar(solto=True)`, num lugar só.

O que a cópia estática perde, e por quê:
  * a moldura lateral e o menu de conta — não há sistema para navegar nem sessão
    para encerrar; no lugar entra a FAIXA DE PROCEDÊNCIA, no topo;
  * `lateral.css` sai junto com a moldura (ele declara `body{margin-left:256px}`:
    inlinado sem o `<aside>`, empurraria o painel 256px para o lado por nada);
  * `fontes.css` entra INLINE, com os arquivos em `data:` URI — o arquivo abre de
    `file://`, onde `/estatico/...` não é caminho nenhum.

O que ela NÃO perde: a régua. `COLETA_EM` continua sendo a data da COLETA, então
a cópia aberta três semanas depois mede os mesmos dias que media no dia em que
saiu — ela não envelhece sozinha, ela só fica velha e diz que está.

    python montar_painel.py
"""
import base64
from pathlib import Path


def _achar_origem():
    """Onde está `painel_v2.html`. Caminho relativo, não absoluto fixo — um
    absoluto (`C:\\Claude\\sei_sistema\\...`) já sobreviveu à separação deste
    repositório da árvore antiga: o script continuava lendo a fonte de LÁ, e
    uma edição aqui nunca aparecia no gerado, sem erro nenhum avisando disso
    (achado ao adicionar o favicon, 09/09/2026). `painel_sesab/` é irmã de
    `sei360/`, duas pastas acima deste arquivo.
    """
    aqui = Path(__file__).resolve().parent
    candidatos = (aqui.parent.parent / "painel_sesab" / "painel_v2.html",
                 Path(r"C:\Claude\sei_sistema\painel_sesab\painel_v2.html"))
    for c in candidatos:
        if c.exists():
            return c
    return candidatos[0]


ORIGEM = _achar_origem()
DESTINO = Path(__file__).resolve().parent / "templates" / "painel.html"
DESTINO_SOLTO = Path(__file__).resolve().parent / "templates" / "painel_solto.html"
VENDOR = Path(__file__).resolve().parent / "estatico" / "vendor"

CONSTS = ("const DADOS = ", "const MESAS_CONTA = ", "const COLETA_EM = ", "const MESAS_FALHAS = ")

# Itens do menu de conta. O painel solto não tem login, então o menu dele fala da
# MESA; no servidor, quem está vendo importa mais que onde o dado foi colhido —
# com fronteira por unidade, "com que conta" é a pergunta que decide a tela.
# ---------------------------------------------------------------------------
# MENU LATERAL — a mesma marcação do `_nav.html` das telas de serviço, montada
# aqui porque o painel não passa pelo `include` do Jinja: o HTML dele é gerado a
# partir do painel autocontido do projeto.
#
# Antes, a navegação do painel morava no dropdown da conta, misturada com as
# ações da tela. O resultado era o painel — a tela inicial e a mais usada — ser a
# ÚNICA sem navegação visível: quem entrava nele só saía pelo dropdown ou pelo
# link "configure a sua coleta" na faixa de coleta.
#
# Barra de TOPO não servia aqui: o painel já tem uma `.barra` sticky em `top:0`,
# e duas barras disputando o topo deslocam `.cols` e `.grupo-cab`, que grudam em
# offsets calculados a partir da altura da `.barra`. Na lateral não há disputa.
# ---------------------------------------------------------------------------
def _lateral():
    """LÊ o `_nav.html` — não repete a marcação dele.

    O `<aside>` do menu estava escrito à mão aqui e lá, e as duas cópias já
    tinham divergido: só a do `_nav.html` emitia `aria-current="page"`, então na
    tela mais usada do sistema o leitor de tela não anunciava em que porta a
    pessoa estava, embora o olho visse a barrinha ciano. É a mesma armadilha que
    `portas.py` resolveu para a LISTA, reaparecendo uma camada acima.

    Duas diferenças reais entre os contextos, e só duas:
      * as telas de serviço recebem a porta ativa como `pagina`, num `{% with %}`
        em volta do include; o painel recebe `pagina_atual` direto do
        `render_template`, porque não passa por include nenhum;
      * o `<script>` de recolher/expandir já vai no corpo do painel por outro
        caminho, então o que vem do arquivo é só a marcação.
    """
    import re as _re

    fonte = (Path(__file__).resolve().parent / "templates" / "_nav.html")
    bruto = fonte.read_text(encoding="utf-8")
    # TODOS os comentários saem, não só o do topo. O painel embrulha a marcação em
    # `{% raw %}` — porque o CSS e o JS dele usam chaves aos milhares e não podem
    # passar pelo interpretador —, e dentro do raw um `{# … #}` deixa de ser
    # comentário e vira texto impresso na tela. Chegaram a aparecer em cima do
    # menu. Eles existem para quem edita o arquivo, não para quem abre a página.
    bruto = _re.sub(r"\{#.*?#\}", "", bruto, flags=_re.S)
    return bruto.replace("pagina ==", "pagina_atual ==").strip() + "\n"


LATERAL = _lateral()

# O <link> entra DEPOIS do <style> do painel, de propósito: o painel declara
# `body{margin:0}` e a lateral precisa de `margin-left`. Mesma especificidade, o
# último vence — invertida a ordem, a moldura ficaria por cima do conteúdo.
CABECA = (
    '<link rel="stylesheet" href="/estatico/lateral.css">\n'
    # Só grava o atributo se HOUVER escolha guardada. Gravando sempre, a media
    # query da tela estreita nunca casava e a moldura ficava com 256px num
    # notebook de 1366px — onde a coluna principal da lista cai de 457 para 269px.
    "<script>try{var _l=localStorage.getItem('sei360-lateral');"
    "if(_l!==null)document.documentElement.dataset.lateral="
    "_l==='1'?'recolhido':'aberto'}catch(e){}</script>"
)


# A LISTA POR UNIDADE, escrita UMA vez. Ela aparece na faixa do painel servido e
# na faixa de procedência da cópia estática. Escrita duas vezes, as duas cópias
# divergiriam com o tempo — foi exatamente o que aconteceu com a marcação do menu
# lateral, e o preço foi o `aria-current` sumir da tela mais usada do sistema.
UNIDADES_COLETA = """  {% for c in coleta.unidades %}
    <span class="coleta-un {{ '' if c.minha else 'emprestada' }}"
      title="{{ c.instancia }} · {{ c.unidade }} — {{ c.texto }}{{ '' if c.minha else ' · coleta COMPARTILHADA: este número não veio do seu login no SEI' }}">
      <i class="pt pt-{{ c.cor }}"></i>{% if coleta.multi_instancia %}<b class="inst">{{ c.rotulo }}</b>{% endif %}{{ c.curta }}
      <b class="num">{{ c.processos }}</b>
      <em>{{ c.texto }}{% if not c.minha %} · compartilhada{% endif %}</em></span>
  {% else %}
    <span class="coleta-un"><i class="pt pt-vazio"></i>nenhuma unidade vinculada a esta conta</span>
  {% endfor %}"""

# Idade do snapshot POR UNIDADE. O painel solto mostra uma idade só, do arquivo
# inteiro; o servidor sabe a de cada unidade, e é isso que revela a mesa que
# parou de ser coletada enquanto as outras seguem em dia.
FAIXA = """
<div class="coleta-faixa" data-pior="{{ coleta.pior }}">
  <span class="coleta-rot">Sua coleta</span>
""" + UNIDADES_COLETA + """
  {# Cada pessoa coleta a própria carteira. Enquanto ela não rodou a dela, o que
     aparece é a coleta compartilhada — o que é honesto e é a ponte que evita a
     tela vazia, mas precisa estar DITO, e com o caminho para sair disso. #}
  {% if coleta.compartilhadas %}<a class="coleta-un alerta" href="/configuracao"
    style="text-decoration:none">⚙ {{ coleta.compartilhadas }} unidade(s) ainda com coleta
    compartilhada — configure a sua</a>{% endif %}
  {% if coleta.candidatos %}<span class="coleta-un alerta">
    <i class="pt pt-vermelho"></i>{{ coleta.candidatos }} snapshot(s) retido(s) para conferência</span>{% endif %}
  {# `not coleta.unidades` ANTES de `nao_configurado`, e nao so ele: os dois
     nao sao a mesma pergunta. `nao_configurado` olha o assistente (sistema,
     acesso, mesas, horarios); ZERO UNIDADE olha o resultado. Conta que
     terminou o assistente e mesmo assim nao tem vinculo nenhum caia num vao:
     a faixa dizia "nenhuma unidade vinculada a esta conta" e nao oferecia
     saida nenhuma — justamente na tela onde a pessoa mais precisa dela.
     Vista em producao com a conta de administracao, 09/09/2026. #}
  {% if not coleta.unidades %}<a class="coleta-un alerta" href="/configuracao"
    style="text-decoration:none">⚙ configure a sua coleta</a>
  {% elif nao_configurado %}<a class="coleta-un alerta" href="/configuracao"
    style="text-decoration:none">⚙ configure a sua coleta</a>{% endif %}
</div>
"""

# ---------------------------------------------------------------------------
# FAIXA DE PROCEDÊNCIA — só no modo solto.
#
# O arquivo sai do sistema e passa a circular por e-mail, pen drive e pasta de
# rede, onde ninguém pode perguntar de onde ele veio. Então ele responde sozinho,
# na primeira linha: de quando é o dado, quem exportou, quando, quantos processos
# e de quais unidades. É o mesmo raciocínio da folha de rosto do `.xlsx` em
# `relatorios.para_xlsx` — número sem procedência não se defende numa reunião.
#
# E o aviso de que a cópia não se atualiza vai JUNTO, não em rodapé: quem abre um
# painel espera um painel, e a diferença entre "o retrato de 20/08" e "a tela de
# hoje" é a diferença entre acertar e errar a decisão.
#
# `{{ unidades }}` e não `{{ mesas }}`: são as unidades do VÍNCULO desta conta —
# a fronteira. `mesas` é a lista das que tinham snapshot, e uma unidade vinculada
# sem coleta some dela; dizer só "as que vieram" esconderia justamente a que
# faltou.
# ---------------------------------------------------------------------------
FAIXA_SOLTA = """
<div class="proc">
  <div class="proc-l1">
    <span class="proc-sel">Cópia estática do SEI360</span>
    <span>exportada em <b>{{ exportado_em }}</b> por <b>{{ u.nome or u.email }}</b></span>
    <span>dado medido em <b>{{ coleta_em or '—' }}</b></span>
    <span><b class="num">{{ dados|length }}</b> processo(s)</span>
    <span>unidades: <b>{{ unidades|join(' · ') if unidades else 'nenhuma vinculada a esta conta' }}</b></span>
  </div>
  <div class="coleta-faixa" data-pior="{{ coleta.pior }}">
    <span class="coleta-rot">Coleta</span>
""" + UNIDADES_COLETA + """
    {% if coleta.compartilhadas %}<span class="coleta-un alerta">{{ coleta.compartilhadas }}
      unidade(s) com coleta compartilhada — o número não veio do login desta conta</span>{% endif %}
    {% if coleta.candidatos %}<span class="coleta-un alerta">
      <i class="pt pt-vermelho"></i>{{ coleta.candidatos }} snapshot(s) retido(s) para conferência</span>{% endif %}
  </div>
  <div class="proc-aviso">Este arquivo <b>não se atualiza</b>: ele é o retrato da carteira
    no momento acima e continuará dizendo o mesmo daqui a um mês. Os dias contados nas
    colunas são medidos contra a data da coleta, nunca contra o relógio de quem abre.
    Para o dado de hoje, abra o SEI360.</div>
</div>
"""

ESTILO_SOLTO = """
<style>
/* --- faixa de procedência: só a cópia estática a tem --- */
/* Tokens do painel, não paleta nova: `--panel`, `--line`, `--cyan`, `--mono`. A
   faixa é a primeira coisa que se lê no arquivo, e uma placa de cor estranha
   sobre o fundo #0A0E27 seria lida como erro de renderização, não como aviso. */
.proc{margin:0 0 18px;padding:11px 14px;background:var(--panel);
  border:1px solid var(--line-2);border-radius:10px;font-size:12px}
.proc-l1{display:flex;flex-wrap:wrap;align-items:center;gap:5px 14px}
.proc-l1 b{color:var(--text)}
.proc-l1 b.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
.proc-sel{font-family:var(--mono);font-size:9.5px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--cyan);border:1px solid var(--line-2);border-radius:99px;padding:2px 8px}
/* A faixa por unidade vira uma FILEIRA DENTRO da procedência: aqui ela não é um
   bloco à parte com moldura própria, senão a caixa ganharia duas bordas
   concêntricas e o olho leria dois avisos onde há um. */
.proc .coleta-faixa{background:none;border:0;border-top:1px solid var(--line);
  border-radius:0;margin:9px 0 0;padding:8px 0 0}
.proc-aviso{margin-top:8px;color:var(--muted);font-size:11.5px;line-height:1.5}
.proc-aviso b{color:var(--amber)}
</style>
"""

ESTILO = """
<style>
/* --- acréscimos do modo servidor (o arquivo solto não tem login nem unidade) --- */
/* `--panel` e `--line`, não `--card`/`--linha`: o painel nomeia assim as suas
   superfícies (painel_v2.html, bloco :root). Os nomes errados faziam os
   fallbacks CLAROS valerem sempre — e o tema padrão do painel é o escuro, então
   esta faixa era uma placa branca de 63px pousada sobre o fundo #0A0E27, o
   objeto mais luminoso da tela, para repetir seis vezes o mesmo carimbo de data. */
.coleta-faixa{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;margin:0 0 16px;
  padding:9px 14px;background:var(--panel);border:1px solid var(--line);
  border-radius:10px;font-size:12px}
/* Tokens do painel, não literais de papel branco. Medido sobre o fundo escuro:
   #a3391f dava 2,87:1 e #8a6d1f dava 3,88:1 — o estado GRAVE aparecia MENOS que
   o de atenção, com a hierarquia de gravidade invertida na tela. */
.coleta-faixa[data-pior="vermelho"]{border-color:var(--rose)}
.coleta-faixa[data-pior="amarelo"]{border-color:var(--amber)}
.coleta-rot{font-size:9.5px;letter-spacing:.18em;text-transform:uppercase;opacity:.6}
.coleta-un{display:inline-flex;align-items:center;gap:7px;opacity:.85}
.coleta-un b{font-variant-numeric:tabular-nums}
.coleta-un em{font-style:normal;opacity:.7;font-size:11px}
/* Este texto é o link "configure a sua coleta" — a ÚNICA porta para
   /configuracao de quem ainda não configurou. Estava a 2,87:1: a mensagem
   que mais precisa ser vista era a menos visível da faixa. */
.coleta-un.alerta{color:var(--rose);opacity:1;font-weight:600}
/* Unidade cujo número veio da coleta de outro. Não é erro — é a ponte até a
   pessoa rodar a dela —, mas quem lê precisa saber que aquele 625 não saiu
   do login dele. Fio pontilhado embaixo: distingue sem gritar. */
.coleta-un.emprestada{opacity:.72}
.coleta-un.emprestada b.num{border-bottom:1px dotted currentColor}
/* DE QUAL INSTALAÇÃO. A faixa mostra a sigla CURTA da unidade ("GABINETE"), e
   ela não distingue SESAB de FESF — duas mesas homônimas de órgãos diferentes
   apareciam idênticas. O rótulo só entra quando a pessoa tem vínculo em mais de
   uma instalação: carimbar "SESAB" em toda linha de quem só tem SESAB é ruído
   que ensina a não ler o carimbo. */
.coleta-un b.inst{font-size:9px;letter-spacing:.1em;padding:1px 5px;border-radius:4px;
  border:1px solid var(--line);opacity:.75;font-weight:600}
/* `pt-vazio`, e NÃO `pt vazio` em duas classes. O painel já usa `.vazio` para
   OUTRA coisa: o bloco de "nenhum processo encontrado" da lista, que tem
   `padding:54px 20px` (painel_v2.html). Com `box-sizing:border-box`, esse
   padding vencia o `width:7px;height:7px` daqui — o ponto de 7px virava uma
   caixa de 42x109px e, com `border-radius:50%`, uma ELIPSE cinza gigante no
   meio da faixa "Sua coleta". Aparecia exatamente para quem ainda não tem
   unidade vinculada: a primeira tela de toda conta nova.
   É a mesma armadilha de `.lateral` x `.moldura` que lateral.css documenta —
   dois componentes diferentes não podem ter o mesmo nome. O ESTADO continua
   se chamando "vazio" no Python (`c.cor`); o que ganha prefixo é a classe. */
.pt{width:7px;height:7px;border-radius:50%;flex:0 0 auto}
/* Cores de estado com brilho suficiente para o fundo ESCURO do painel, que é o
   padrão dele. As anteriores (#2f6b41, #8a6d1f) foram escolhidas para papel
   branco e ficavam quase invisíveis sobre #0A0E27. */
.pt-verde{background:#37b56d}.pt-amarelo{background:#d4a72c}
.pt-vermelho{background:#e5624a}.pt-vazio{background:#5b6478}
html[data-tema="claro"] .pt-verde{background:#2f6b41}
html[data-tema="claro"] .pt-amarelo{background:#8a6d1f}
html[data-tema="claro"] .pt-vermelho{background:#a3391f}
html[data-tema="claro"] .pt-vazio{background:#c8ccd2}
</style>
"""

# O painel solto monta o cabeçalho da conta a partir da MESA. Aqui ele passa a
# falar de quem está logado. Roda depois do script original, de propósito.
SCRIPT = """
<script>
(() => {
  const p = i => document.getElementById(i);
  const cs = document.cookie.match(/sei360_csrf=([^;]+)/);
  if (p('csrfSair')) p('csrfSair').value = cs ? cs[1] : '';
  const nome = {{ u.email.split('@')[0]|tojson }};
  const papel = {{ u.papel|tojson }};
  const unidades = {{ unidades|length }};
  if (p('contaAv')) p('contaAv').textContent = nome.slice(0, 2).toUpperCase();
  if (p('contaNome')) p('contaNome').textContent = nome;
  if (p('contaSub')) p('contaSub').textContent = papel + ' · ' + unidades + ' unidade(s)';
  if (p('menuS')) p('menuS').textContent = {{ u.email|tojson }};
})();
</script>
"""

# ---------------------------------------------------------------------------
# EXPORTAR O PAINEL — item do menu, só no painel SERVIDO.
#
# Ele vai junto de "Exportar planilha do recorte" porque é a mesma pergunta com
# duas respostas: a planilha leva os números para o Excel, o HTML leva a TELA —
# com os filtros, o agrupamento, a gaveta de detalhe e a régua — para quem não
# tem conta no SEI360 nem vai ter.
#
# O ESTADO VIAJA PELO `?`, e não pelo `#`. O painel guarda o recorte no hash, e
# hash o navegador NÃO manda ao servidor: exportar "meus parados +90d" traria o
# arquivo com a lista inteira, sem erro nenhum e sem ninguém notar. A conversão é
# de uma linha e é aqui que ela mora.
#
# O tema vai junto porque ele mora no `localStorage`, e `file://` é outra origem:
# sem carimbá-lo na URL, quem trabalha no claro receberia um arquivo escuro.
# ---------------------------------------------------------------------------
ITEM_ANCORA = "          Exportar planilha do recorte</button>"
LIGA_ANCORA = "  $('miXls').onclick=()=>{abre(false); exportar();};"

ITEM_EXPORTAR = """
        <button class="mi" id="miHtml" role="menuitem">
          <svg viewBox="0 0 14 14" aria-hidden="true"><path d="M2.4 2.4h9.2v9.2H2.4z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M2.4 5.2h9.2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M5.6 8.6l1.4 1.4 1.4-1.4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          Exportar painel (HTML)</button>"""

LIGA_EXPORTAR = """
  /* O recorte da tela vira query string: ver ITEM_EXPORTAR. `location.href` e
     nao `window.open` — a resposta vem como anexo, entao o navegador baixa e
     nao sai da pagina; abrir aba deixaria uma aba em branco por download. */
  $('miHtml').onclick=()=>{
    abre(false);
    const p=new URLSearchParams(location.hash.slice(1));
    p.set('tema',document.documentElement.getAttribute('data-tema')||'escuro');
    location.href='/painel.html?'+p.toString();
  };"""

# ---------------------------------------------------------------------------
# O que o modo solto TIRA do painel de origem.
#
# A marcação do menu de conta sai inteira, mas a função que a comanda continua no
# arquivo — ela é do painel do usuário, e o gerador não reescreve a tela dele. Sem
# a guarda, `$('contaAv').textContent` estoura na primeira linha e leva junto TUDO
# o que vem depois no mesmo `<script>`: o tema, o rail, o estado na URL e o
# `render()` inicial. O arquivo abriria com o cabeçalho e uma lista vazia.
# ---------------------------------------------------------------------------
CONTA_ABRE = '    <div class="conta" id="conta">'
CONTA_FECHA = '    <div class="seg" id="tema">'
CONTA_ORIGEM = "(function conta(){\n  const bt=$('contaBt'), menu=$('contaMenu');\n"
CONTA_GUARDA = (CONTA_ORIGEM
                + "  /* Copia estatica: nao ha conta nem menu — a procedencia esta na\n"
                  "     faixa do topo. Sair daqui, e nao estourar, porque o resto deste\n"
                  "     bloco (tema, rail, estado na URL, render inicial) vem depois. */\n"
                  "  if(!bt||!menu) return;\n")

# O ATALHO DE TECLADO TAMBÉM MEXE NO MENU, e de fora da função que o comanda.
# Sem tirá-lo, o primeiro Escape na cópia estática estoura em `null.hidden` e o
# `return` some junto com as DUAS coisas que a linha seguinte faz: fechar a
# gaveta de detalhe e limpar os filtros. Um menu que não existe custaria ao
# arquivo a tecla mais usada dele.
ESCAPE_ORIGEM = ("    if(!$('contaMenu').hidden){$('contaMenu').hidden=true;"
                 "$('contaBt').setAttribute('aria-expanded','false');return;}\n")
ESCAPE_SOLTO = ("    /* Sem menu de conta para fechar: aqui o Escape so fecha a gaveta e\n"
                "       limpa os filtros. O ramo sai inteiro em vez de ganhar guarda —\n"
                "       guardado, ele deixaria o botao do menu orfao la dentro. */\n")

# Os ids que somem junto com o menu de conta. Depois de removê-lo, NENHUM deles
# pode continuar sendo lido de fora da função `conta()` — foi assim que o Escape
# apareceu, e é assim que o próximo aparece. A conferência é do gerador porque é
# ele que corta; quem escreve o painel de origem não tem como saber disso.
IDS_CONTA = ("conta", "contaBt", "contaAv", "contaNome", "contaSub", "contaMenu",
             "menuS", "menuMesas", "miCtrl", "miSei", "miXls", "miImprimir", "miSair")

# O recorte que veio na URL, aplicado na abertura. O arquivo aberto do disco não
# tem query string nenhuma — quem a tinha era a requisição que o gerou —, então o
# estado é gravado no HASH antes de o painel ler, que é de onde ele já lê hoje.
SCRIPT_SOLTO = """
<script>
/* ESTADO DA EXPORTACAO. Roda ANTES do painel: `urlEstado.ler()` le
   `location.hash`, e o tema le o `localStorage` — os dois precisam do valor ja
   posto. Nao sobrescreve escolha de quem ja mexeu no arquivo aberto. */
(() => {
  const s = {{ estado_url|tojson }};
  if (!s) return;
  try {
    const p = new URLSearchParams(s);
    const t = p.get('tema');
    if (t === 'claro' || t === 'escuro') {
      document.documentElement.setAttribute('data-tema', t);
      try { localStorage.setItem('painel-tema', t); } catch (e) {}
      p.delete('tema');
    }
    const h = p.toString();
    if (h && !location.hash) location.hash = h;
  } catch (e) { /* URL malformada nao pode impedir o painel de abrir */ }
})();
</script>
"""


def _orfaos_da_conta(texto):
    """Recusa a cópia estática que ainda leia um id do menu de conta POR FORA.

    Dentro de `conta()` a leitura é inofensiva: a guarda devolve antes. Fora
    dela, `$('contaMenu')` é `null` e a próxima propriedade lida derruba o bloco
    inteiro — e o sintoma não é um erro na tela, é uma tecla que deixa de
    responder, ou uma lista que não desenha. Só se vê abrindo o arquivo.
    """
    ini = texto.index(CONTA_ORIGEM)
    fim = texto.index("\n})();", ini) + len("\n})();")
    fora = texto[:ini] + texto[fim:]
    orfaos = sorted(i for i in IDS_CONTA
                    if f"$('{i}')" in fora or f'id="{i}"' in fora)
    if orfaos:
        raise SystemExit(
            "a cópia estática tira o menu de conta, mas o painel ainda lê "
            f"{', '.join(orfaos)} fora de `conta()`. Em `file://` isso é `null`, e o "
            "bloco morre em silêncio: trate cada um em montar(solto=True), como o "
            "ESCAPE_SOLTO trata o atalho de teclado.")


def _fontes_embutidas():
    """`fontes.css` com os arquivos DENTRO, em `data:` URI. Só o subset latin.

    O arquivo exportado abre de `file://`, onde `/estatico/vendor/...` não é
    caminho nenhum: o `<link>` falha em silêncio e a página cai na fonte do
    sistema — sem erro visível, só feia, que é o pior modo de falhar.

    LATIN, E SÓ. O `latin-ext` cobre U+0100 em diante, e o português inteiro cabe
    em U+0000-00FF: acento, cedilha, til, o travessão e o "·" da faixa. Levá-lo
    junto dobraria a fonte embutida para servir caractere que não aparece. Cada
    família já declara a sua pilha de reserva no `:root` do painel
    (`system-ui`, `ui-monospace`, `Consolas`), então o resíduo tem para onde cair.
    """
    import re as _re

    css = (VENDOR / "fontes.css").read_text(encoding="utf-8")
    faces, arquivos = [], []
    # Um bloco por `@font-face`; o primeiro pedaço é o comentário do topo e não
    # tem `url()`, então cai fora sozinho.
    for bloco in _re.split(r"(?=@font-face)", css):
        m = _re.search(r"url\(/estatico/vendor/([^)]+)\)", bloco)
        if not m or not m.group(1).endswith("-latin.woff2"):
            continue
        dados = (VENDOR / m.group(1)).read_bytes()
        faces.append(bloco.replace(
            m.group(0), "url(data:font/woff2;base64,"
                        + base64.b64encode(dados).decode() + ")"))
        arquivos.append(m.group(1))
    if not faces:
        raise SystemExit("nenhuma face latin encontrada em estatico/vendor/fontes.css: "
                         "a cópia estática sairia sem fonte, e sem dizer que saiu")
    return ("<style>\n/* Fontes EMBUTIDAS (Google Fonts, SIL OFL), subset latin.\n"
            f"   {len(arquivos)} faces: {', '.join(sorted(arquivos))}\n"
            "   Em data: URI porque este arquivo abre de file://, sem servidor e\n"
            "   sem rede — ver montar_painel._fontes_embutidas. */\n"
            + "".join(faces) + "</style>")


# DATA IMPOSSÍVEL: as duas contas têm de recusar a mesma coisa.
#
# `new Date(2026, 1, 31)` não dá erro em JavaScript — rola para 03/03. Com isso,
# `31/02/2026 10:00` sai do painel como "170 dias na unidade" e de
# `relatorios._dias` como nada (`quando_br` devolve None): 170 contra vazio, para
# o mesmo processo, nas duas telas do mesmo sistema. É a MESMA classe de defeito
# que fez o painel dizer "432 parados +90d" e o relatório dizer 526, e é por isso
# que `conferir_dias.js` existe — foi ele que apontou esta.
#
# O conserto vai aqui, e não no painel de origem, porque o painel de origem é do
# usuário: a regeneração aplica a checagem sem reescrever a tela dele. O teste é
# o round-trip — se a data construída não devolve o dia e o mês que entraram, ela
# não existia no calendário.
REGUA_EMMS_ORIGEM = (
    "const emMs=s=>{const m=(s||'').match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})(?:\\s+(\\d{2}):(\\d{2}))?/);\n"
    "  return m?new Date(+m[3],+m[2]-1,+m[1],+(m[4]||0),+(m[5]||0)).getTime():null;};"
)
REGUA_EMMS_NOVO = (
    "const emMs=s=>{const m=(s||'').match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})(?:\\s+(\\d{2}):(\\d{2}))?/);\n"
    "  if(!m)return null;\n"
    "  /* DATA IMPOSSIVEL NAO VIRA DATA. new Date(2026,1,31) nao da erro: rola para\n"
    "     03/03, e 31/02 saia daqui como 170 dias enquanto relatorios._dias devolvia\n"
    "     nada para o mesmo processo. O round-trip e a unica conferencia que pega. */\n"
    "  const x=new Date(+m[3],+m[2]-1,+m[1],+(m[4]||0),+(m[5]||0));\n"
    "  return (x.getFullYear()===+m[3]&&x.getMonth()===+m[2]-1&&x.getDate()===+m[1])\n"
    "    ?x.getTime():null;};"
)

# Chave única de tema. O painel guardava em `sesab.tema` e as sete telas de
# serviço liam `painel-tema`: escolher claro no painel e ir para /relatorios
# devolvia escuro, e a pessoa concluía — com razão — que o botão não funciona.
# A migração lê a chave antiga uma vez para ninguém perder a escolha.
TEMA_ANTIGO = "sesab.tema"
TEMA = "painel-tema"

# Fontes SERVIDAS DAQUI. O painel solto pode buscar no Google porque roda no
# navegador de quem o abriu; a versão servida, não: a estação está atrás da rede
# do órgão, onde `fonts.googleapis.com` pode simplesmente não resolver — e aí a
# tela abre com a fonte do sistema, sem erro visível, só feia. Além disso, cada
# abertura contaria ao Google quem abriu o painel e quando.
FONTES_LOCAIS = ('<link rel="stylesheet" href="/estatico/vendor/fontes.css">')

CABECALHO = """<!-- ARQUIVO GERADO por montar_painel.py a partir de
     painel_sesab/painel_v2.html. NÃO EDITE AQUI: a próxima remontagem apaga a
     alteração sem diff e sem aviso. Conserto vai no painel de origem. -->
"""


def montar(solto=False):
    """Gera `painel.html` (servido) ou `painel_solto.html` (cópia estática).

    As diferenças do modo solto estão TODAS neste corpo, marcadas por `if solto`.
    Espalhá-las pelo arquivo em condicionais do Jinja seria o mesmo que não ter
    lista: o painel servido mudaria de bytes no dia em que alguém mexesse num
    ramo que julgava ser só do outro modo.
    """
    linhas = ORIGEM.read_text(encoding="utf-8").split("\n")
    texto = "\n".join(l for l in linhas if not l.startswith(CONSTS))

    faltando = [a for a in ("</style></head>", '<div class="menu-mesas" id="menuMesas"></div>',
                            '<div class="kpis" id="kpis"></div>', "</body>")
                if texto.count(a) != 1]
    if faltando:
        raise SystemExit("o painel de origem mudou; âncoras não encontradas: " + str(faltando))

    # Injeções ANTES do embrulho em {% raw %}. Fazer depois exigiria casar com o
    # texto '{% raw %}</head>', que nunca existe — o bloco raw começa lá no topo.
    # Foi exatamente esse o erro que deixou a tela de login sem o script de
    # autenticação, passando em todas as conferências.
    #
    # No solto, `CABECA` inteira sai: ela é o <link> do `lateral.css` mais o
    # script que grava `data-lateral`. Sem o <aside>, o primeiro pinta uma margem
    # de 256px em volta do nada e o segundo grava um atributo que ninguém lê.
    texto = texto.replace("</style></head>",
                          "</style>" + ("" if solto else CABECA)
                          + ESTILO.strip() + (ESTILO_SOLTO.strip() if solto else "")
                          + "</head>", 1)
    # A lateral entra logo depois do <body>, antes do .wrap. Ela é `position:fixed`
    # e o conteúdo ganha `margin-left` — NUNCA um shell com `overflow:hidden`, que
    # é como o painel de referência monta a dele. Ancestral com overflow vira o
    # contêiner de rolagem e quebra TODO o `position:sticky` do painel: o rail de
    # filtros, o cabeçalho de colunas e o agrupador param de grudar, em silêncio.
    if "<body" not in texto:
        raise SystemExit("não achei <body> no painel de origem")
    if solto:
        # A procedência é a PRIMEIRA coisa dentro do `.wrap`, acima do título: ela
        # responde "de quando é isto?" antes de o olho chegar em qualquer número.
        # Dentro do `.wrap` e não solta no `<body>` para herdar a largura máxima e
        # o respiro do painel — fora dele, ela sairia colada na borda da janela.
        texto = texto.replace('<div class="wrap">',
                              '<div class="wrap">\n' + FAIXA_SOLTA.strip(), 1)
        # O menu de conta sai INTEIRO: os dois links dele vão para o SEI (que a
        # cópia continua alcançando pelo protocolo de cada linha) e o resto —
        # identidade e "sair" — virou faixa de procedência ou deixou de existir.
        i, f = texto.index(CONTA_ABRE), texto.index(CONTA_FECHA)
        texto = texto[:i] + texto[f:]
        if texto.count(CONTA_ORIGEM) != 1:
            raise SystemExit("não achei o `conta()` do painel de origem: sem a guarda, "
                             "a cópia estática abre com a lista vazia (ver CONTA_GUARDA)")
        texto = texto.replace(CONTA_ORIGEM, CONTA_GUARDA, 1)
        if texto.count(ESCAPE_ORIGEM) != 1:
            raise SystemExit("não achei o ramo do Escape que fecha o menu de conta: "
                             "confira antes de exportar, senão a tecla Escape para de "
                             "fechar a gaveta no arquivo (ver ESCAPE_SOLTO)")
        texto = texto.replace(ESCAPE_ORIGEM, ESCAPE_SOLTO, 1)
        _orfaos_da_conta(texto)
    else:
        corte = texto.index(">", texto.index("<body")) + 1
        texto = texto[:corte] + "\n" + LATERAL.strip() + "\n" + texto[corte:]
        texto = texto.replace('<div class="kpis" id="kpis"></div>',
                              '<div class="kpis" id="kpis"></div>\n' + FAIXA.strip(), 1)
        # O item "Exportar painel (HTML)" só existe onde há servidor para servi-lo.
        for alvo, novo in ((ITEM_ANCORA, ITEM_ANCORA + ITEM_EXPORTAR),
                           (LIGA_ANCORA, LIGA_ANCORA + LIGA_EXPORTAR)):
            if texto.count(alvo) != 1:
                raise SystemExit(f"âncora do menu de exportação não encontrada: {alvo!r}")
            texto = texto.replace(alvo, novo, 1)
    texto = texto.replace("</body>", (SCRIPT_SOLTO if solto else SCRIPT).strip()
                          + "\n</body>", 1)

    # Fontes locais no lugar do Google. Três linhas viram uma — e no solto viram
    # as próprias fontes, porque `file://` não tem `/estatico`.
    import re as _re
    texto, n_fontes = _re.subn(
        r'\s*<link rel="preconnect" href="https://fonts\.googleapis\.com">'
        r'\s*<link rel="preconnect" href="https://fonts\.gstatic\.com" crossorigin>'
        r'\s*<link href="https://fonts\.googleapis\.com/[^"]*"[^>]*>',
        lambda _m: "\n" + (_fontes_embutidas() if solto else FONTES_LOCAIS),
        texto, count=1)
    if not n_fontes:
        raise SystemExit("as linhas de fonte do Google não foram encontradas no painel "
                         "de origem — confira antes de servir, senão a tela sai sem fonte")

    # A régua recusa data impossível dos DOIS lados (ver REGUA_EMMS_NOVO).
    if texto.count(REGUA_EMMS_ORIGEM) != 1:
        raise SystemExit("não achei o `emMs` do painel de origem (ou ele mudou): "
                         "sem a checagem de data impossível, painel e relatório "
                         "divergem em 31/02 e `conferir_dias.js` reprova")
    texto = texto.replace(REGUA_EMMS_ORIGEM, REGUA_EMMS_NOVO, 1)

    # Chave de tema única entre o painel e as telas de serviço.
    velho = "const K='" + TEMA_ANTIGO + "';"
    if velho not in texto:
        raise SystemExit(f"não achei {velho!r} no painel de origem: a unificação da "
                         "chave de tema depende dela")
    texto = texto.replace(
        velho,
        "const K='" + TEMA + "';\n"
        "  /* Migra a escolha guardada sob a chave antiga, uma vez. Trocar a chave\n"
        "     sem isto devolveria todo mundo ao tema escuro sem explicação. */\n"
        "  try{ if(localStorage.getItem(K)===null){\n"
        "    const v=localStorage.getItem('" + TEMA_ANTIGO + "');\n"
        "    if(v) localStorage.setItem(K,v);\n"
        "  } }catch(e){}", 1)

    # As 4 consts entram como injeção própria, logo antes do script do painel.
    # `COLETA_EM` é a MESMA nos dois modos, e de propósito: é a data da coleta, a
    # régua contra a qual o painel mede "dias na unidade". A cópia estática
    # carrega a régua junto com o dado — é isso que a impede de envelhecer sozinha
    # quando alguém a abre três semanas depois.
    dados = ("<script>\nconst DADOS = {{ dados|tojson }};\n"
             "const MESAS_CONTA = {{ mesas|tojson }};\n"
             "const COLETA_EM = {{ coleta_em|tojson }};\n"
             "const COLETA_FRASE = {{ coleta_frase|tojson }};\n"
             "const MESAS_FALHAS = {{ falhas|tojson }};\n</script>\n")
    i = texto.index("<script>\n", texto.index('id="kpis"'))
    texto = texto[:i] + dados + texto[i:]

    if solto:
        # NADA de caminho absoluto do servidor. `file://` resolve `/estatico/...`
        # como raiz do DISCO: o arquivo abriria com 404 mudo no console, sem
        # fonte e sem folha. A conferência é sobre o efeito, não sobre a intenção.
        for proibido in ('href="/', 'src="/', "/estatico/"):
            if proibido in texto:
                trecho = texto[max(0, texto.index(proibido) - 60):
                               texto.index(proibido) + 80]
                raise SystemExit(f"a cópia estática ainda tem {proibido!r} — ela abre de "
                                 f"file://, onde isso não é caminho nenhum:\n  ...{trecho}...")

    import re
    # Comentário de Jinja não sobrevive ao `{% raw %}`: lá dentro ele deixa de ser
    # comentário e vira texto impresso na tela. Já chegou a aparecer em cima do
    # menu lateral. Some AQUI, uma vez, para todo bloco injetado — o conserto
    # anterior era por bloco, e voltou no primeiro comentário novo que escrevi.
    texto = re.sub(r"\{#.*?#\}", "", texto, flags=re.S)
    padrao = re.compile(r"(\{\{[^}]*\}\}|\{%[^%]*%\})")
    partes = []
    for pedaco in padrao.split(texto):
        if padrao.fullmatch(pedaco):
            partes.append(pedaco)
        elif pedaco:
            partes.append("{% raw %}" + pedaco + "{% endraw %}")
    saida = CABECALHO + "".join(partes)
    destino = DESTINO_SOLTO if solto else DESTINO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(saida, encoding="utf-8")
    return saida


if __name__ == "__main__":
    s = montar()
    solta = montar(solto=True)
    print(f"template gerado: {DESTINO}  ({len(s)/1024:.0f} KB)")
    print(f"cópia estática : {DESTINO_SOLTO}  ({len(solta)/1024:.0f} KB, fontes embutidas)")
    grudado = [c for c in CONSTS if (c + "[{") in s or (c + '"') in s]
    print("dados embutidos removidos:", "ok" if not grudado else f"AINDA PRESENTES: {grudado}")
    for proibido, porque in (("fonts.googleapis.com", "a rede do órgão pode não resolver"),
                             ("fonts.gstatic.com", "idem"),
                             ("'" + TEMA_ANTIGO + "';", "chave de tema divergente das telas")):
        if proibido in s:
            print(f"  ATENÇÃO  ainda há {proibido} no template ({porque})")
    for rot, alvo in (("rail de filtros", 'id="rail"'), ("menu de conta", 'id="contaMenu"'),
                      ("link de configuração", "/configuracao"), ("sair por POST", 'action="/sair"'),
                      ("faixa por unidade", "coleta-faixa"), ("injeção de dados", "{{ dados|tojson }}"),
                      ("fontes servidas daqui", "/estatico/vendor/fontes.css"),
                      ("cabeçalho de arquivo gerado", "NÃO EDITE AQUI"),
                      ("menu lateral", 'class="moldura"'),
                      ("folha da lateral", "/estatico/lateral.css"),
                      ("botão de recolher", 'id="latDobrar"'),
                      ("exportar painel em HTML", 'id="miHtml"'),
                      ("painel marcado como porta ativa", "pagina_atual")):
        print(f"  {'ok     ' if alvo in s else 'AUSENTE'} {rot}")
    # A cópia estática se confere pelo AVESSO: o que nela é defeito é justamente
    # o que no painel servido é obrigatório.
    print("  cópia estática:")
    for rot, alvo, quer in (("faixa de procedência", "Cópia estática do SEI360", True),
                            ("aviso de que não se atualiza", "não se atualiza", True),
                            ("fontes embutidas", "data:font/woff2;base64,", True),
                            ("estado da exportação embutido", "{{ estado_url|tojson }}", True),
                            ("a régua continua sendo a coleta", "{{ coleta_em|tojson }}", True),
                            ("exportar planilha do recorte", "function exportar()", True),
                            ("rail de filtros", 'id="rail"', True),
                            ("SEM moldura lateral", 'class="moldura"', False),
                            ("SEM menu de conta", 'id="contaMenu"', False),
                            ("SEM caminho de servidor", "/estatico/", False)):
        viu = alvo in solta
        print(f"    {'ok     ' if viu == quer else 'FALHOU '} {rot}")
