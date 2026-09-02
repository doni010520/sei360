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

    python montar_painel.py
"""
from pathlib import Path

ORIGEM = Path(r"C:\Claude\sei_sistema\painel_sesab\painel_v2.html")
DESTINO = Path(__file__).resolve().parent / "templates" / "painel.html"

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


# Idade do snapshot POR UNIDADE. O painel solto mostra uma idade só, do arquivo
# inteiro; o servidor sabe a de cada unidade, e é isso que revela a mesa que
# parou de ser coletada enquanto as outras seguem em dia.
FAIXA = """
<div class="coleta-faixa" data-pior="{{ coleta.pior }}">
  <span class="coleta-rot">Sua coleta</span>
  {% for c in coleta.unidades %}
    <span class="coleta-un {{ '' if c.minha else 'emprestada' }}"
      title="{{ c.unidade }} — {{ c.texto }}{{ '' if c.minha else ' · coleta COMPARTILHADA: este número não veio do seu login no SEI' }}">
      <i class="pt {{ c.cor }}"></i>{{ c.curta }}
      <b class="num">{{ c.processos }}</b>
      <em>{{ c.texto }}{% if not c.minha %} · compartilhada{% endif %}</em></span>
  {% else %}
    <span class="coleta-un"><i class="pt vazio"></i>nenhuma unidade vinculada a esta conta</span>
  {% endfor %}
  {# Cada pessoa coleta a própria carteira. Enquanto ela não rodou a dela, o que
     aparece é a coleta compartilhada — o que é honesto e é a ponte que evita a
     tela vazia, mas precisa estar DITO, e com o caminho para sair disso. #}
  {% if coleta.compartilhadas %}<a class="coleta-un alerta" href="/configuracao"
    style="text-decoration:none">⚙ {{ coleta.compartilhadas }} unidade(s) ainda com coleta
    compartilhada — configure a sua</a>{% endif %}
  {% if coleta.candidatos %}<span class="coleta-un alerta">
    <i class="pt vermelho"></i>{{ coleta.candidatos }} snapshot(s) retido(s) para conferência</span>{% endif %}
  {% if nao_configurado %}<a class="coleta-un alerta" href="/configuracao"
    style="text-decoration:none">⚙ configure a sua coleta</a>{% endif %}
</div>
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
.coleta-un.emprestada b{border-bottom:1px dotted currentColor}
/* Cores de estado com brilho suficiente para o fundo ESCURO do painel, que é o
   padrão dele. As anteriores (#2f6b41, #8a6d1f) foram escolhidas para papel
   branco e ficavam quase invisíveis sobre #0A0E27. */
.pt{width:7px;height:7px;border-radius:50%;flex:0 0 auto}
.pt.verde{background:#37b56d}.pt.amarelo{background:#d4a72c}
.pt.vermelho{background:#e5624a}.pt.vazio{background:#5b6478}
html[data-tema="claro"] .pt.verde{background:#2f6b41}
html[data-tema="claro"] .pt.amarelo{background:#8a6d1f}
html[data-tema="claro"] .pt.vermelho{background:#a3391f}
html[data-tema="claro"] .pt.vazio{background:#c8ccd2}
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


def montar():
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
    texto = texto.replace("</style></head>",
                          "</style>" + CABECA + ESTILO.strip() + "</head>", 1)
    # A lateral entra logo depois do <body>, antes do .wrap. Ela é `position:fixed`
    # e o conteúdo ganha `margin-left` — NUNCA um shell com `overflow:hidden`, que
    # é como o painel de referência monta a dele. Ancestral com overflow vira o
    # contêiner de rolagem e quebra TODO o `position:sticky` do painel: o rail de
    # filtros, o cabeçalho de colunas e o agrupador param de grudar, em silêncio.
    if "<body" not in texto:
        raise SystemExit("não achei <body> no painel de origem")
    corte = texto.index(">", texto.index("<body")) + 1
    texto = texto[:corte] + "\n" + LATERAL.strip() + "\n" + texto[corte:]
    texto = texto.replace('<div class="kpis" id="kpis"></div>',
                          '<div class="kpis" id="kpis"></div>\n' + FAIXA.strip(), 1)
    texto = texto.replace("</body>", SCRIPT.strip() + "\n</body>", 1)

    # Fontes locais no lugar do Google. Três linhas viram uma.
    import re as _re
    texto, n_fontes = _re.subn(
        r'\s*<link rel="preconnect" href="https://fonts\.googleapis\.com">'
        r'\s*<link rel="preconnect" href="https://fonts\.gstatic\.com" crossorigin>'
        r'\s*<link href="https://fonts\.googleapis\.com/[^"]*"[^>]*>',
        "\n" + FONTES_LOCAIS, texto, count=1)
    if not n_fontes:
        raise SystemExit("as linhas de fonte do Google não foram encontradas no painel "
                         "de origem — confira antes de servir, senão a tela sai sem fonte")

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
    dados = ("<script>\nconst DADOS = {{ dados|tojson }};\n"
             "const MESAS_CONTA = {{ mesas|tojson }};\n"
             "const COLETA_EM = {{ coleta_em|tojson }};\n"
             "const COLETA_FRASE = {{ coleta_frase|tojson }};\n"
             "const MESAS_FALHAS = {{ falhas|tojson }};\n</script>\n")
    i = texto.index("<script>\n", texto.index('id="kpis"'))
    texto = texto[:i] + dados + texto[i:]

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
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(saida, encoding="utf-8")
    return saida


if __name__ == "__main__":
    s = montar()
    print(f"template gerado: {DESTINO}  ({len(s)/1024:.0f} KB)")
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
                      ("painel marcado como porta ativa", "pagina_atual")):
        print(f"  {'ok     ' if alvo in s else 'AUSENTE'} {rot}")
