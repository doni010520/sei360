# -*- coding: utf-8 -*-
"""
Coleta autonoma do Controle de Processos do SEI (SESAB).

POR QUE PLAYWRIGHT E NAO UM <script src> NA PAGINA
--------------------------------------------------
Carregar o coletor de um servidor local para dentro da pagina do SEI esbarra no
Local Network Access do Chrome (permissao de usuario desde o Chrome 142; sem
cabecalho que conceda). Aqui o problema nao e contornado — ele deixa de existir:
o Python le o .js do disco e injeta pelo protocolo de automacao. Nao ha
subrecurso de rede, logo nao ha LNA, nem conteudo misto, nem CORS.

Efeito colateral desejado: a credencial fica entre o arquivo .js e o navegador.
Este script apenas REFERENCIA o caminho do .js — nunca le nem imprime seu conteudo.

USO
---
    python coletor_sesab.py            # headless, para agendamento
    python coletor_sesab.py --ver      # com janela visivel, para diagnosticar
    python coletor_sesab.py --mesas    # todas as unidades da conta
    python coletor_sesab.py --mesas --plano   # pergunta ao SEI360 o que ja foi lido
    python coletor_sesab.py --buscar          # UMA busca avancada; pedido por stdin

SAIDAS
------
    _coletas/sei_sesab_AAAA-MM-DD.json
    _coletas/falha_*.png  (quando algo trava)

CODIGOS DE SAIDA
----------------
    0  coletou sem alertas
    1  coletou, mas houve alerta no console (2FA, sessao, etc.)
    2  rodou e nao devolveu dados  -> NADA e gravado
    3  login nao concluiu
    4  erro de infraestrutura (arquivo ausente, navegador, etc.)
"""
import json, os, sys, datetime, traceback
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("playwright nao instalado:  pip install playwright && playwright install chromium")
    sys.exit(4)

BASE   = Path(__file__).resolve().parent
JS     = BASE / "automacao_sei.js"          # so o CAMINHO; o conteudo nunca e lido aqui
# Perfil dedicado, isolado do Chrome do usuario. O caminho sai do ambiente quando
# alguem o define: no container ele precisa cair no VOLUME, e nao na imagem, senao
# a sessao do SEI morre a cada redeploy — e login novo e onde o segundo fator
# aparece, sem ninguem na tela para digitar o codigo.
PERFIL = Path(os.environ.get("SEI_PERFIL_DIR") or (BASE / "_perfil_sei"))
SAIDA  = BASE / "_coletas"
# A UNIDADE DE LOTACAO DA TITULAR, DECLARADA. Nao pode sair de `unidadeAtual()`:
# num perfil persistente o DOM vivo e o residuo da execucao anterior, entao um
# desvio unico vira o normal e se autoconfirma todo dia. Medido em 27/08/2026: as
# 13 execucoes com dados de 13/08 a 27/08 terminaram TODAS em
# SESAB/SAIS/DGGUP/UMA-CMA, mesa onde a titular praticou ZERO atos nos 31 meses
# anteriores — e a "restauracao" existia e devolvia a conta para o proprio desvio.
ARQ_ORIGEM = BASE / "unidade_origem.json"
# INSTALAÇÃO PADRÃO, e só isso. O valor real chega por stdin no envelope do
# perfil (ver PERFIL_SEI abaixo): o coletor não decide em qual SEI entra. Estes
# ficam para o uso manual, no console, sem servidor por trás.
LOGIN  = "https://sip.seibahia.ba.gov.br/login.php?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI"

ORGAO = "23"          # SESAB no #selOrgao (77 opcoes; 'null' = em branco)


def unidade_origem():
    """A unidade para onde a sessao TEM de voltar, ou None.

    Ambiente vence arquivo: no container a origem vem da configuracao do deploy,
    e no `.cmd` da estacao ela nao caberia — `_gravar_cmd.py` reescreve o arquivo
    inteiro a partir de uma lista chumbada, e qualquer `set` acrescentado ali some
    na proxima regeracao.

    None nao impede a coleta: `definirOrigem` degrada para o comportamento antigo
    com um alerta em voz alta. Recusar aqui trocaria "unidade errada em silencio"
    por "sem dado nenhum", que e o outro modo de falha que este projeto persegue.
    """
    v = (os.environ.get("SEI_UNIDADE_ORIGEM") or "").strip()
    if v:
        return v
    try:
        return (json.loads(ARQ_ORIGEM.read_text(encoding="utf-8")).get("origem") or "").strip() or None
    except (OSError, ValueError):
        return None

VER   = "--ver" in sys.argv
MESAS = "--mesas" in sys.argv
ENTRY = "SEIAuto.rodarTodasAsMesas()" if MESAS else "SEIAuto.rodar()"
# Lida UMA vez, na partida: se o arquivo sumir no meio da execucao, a volta ainda
# tem para onde ir.
ORIGEM = unidade_origem()

# --plano: consulta o SEI360 ENTRE a listagem e a leitura do detalhe, para nao
# reler o que outra pessoa ja leu ha pouco. Os dados de conexao chegam por STDIN
# junto da credencial — nunca por argumento (aparece em tasklist/ps para qualquer
# um logado) nem por variavel de ambiente (vaza em docker inspect e em dump de
# processo filho). Sem a opcao, a coleta le tudo, como sempre.
PLANO = "--plano" in sys.argv
# --buscar: roda UMA busca avançada e devolve o envelope. Não coleta, não publica,
# não escreve em _coletas. O pedido chega por stdin, junto da credencial e do perfil.
BUSCAR = "--buscar" in sys.argv
JS_BUSCA = BASE / "pesquisa_sei.js"

# --credencial-stdin: quem chama entrega {"usuario":..,"senha":..} numa linha de
# stdin. Por STDIN e nao por argumento porque argumento aparece na lista de
# processos (tasklist, ps, Process Explorer) para qualquer um logado na maquina —
# e tambem nao entra em variavel de ambiente, que vaza em `docker inspect` e no
# dump de um processo filho. Sem a opcao, nada muda: a credencial continua vindo
# do CONFIG do .js ou do localStorage do perfil, como sempre.
# --testar-login: entra, confere e sai. Sem coletar nada.
# Existe porque configurar credencial as cegas e o jeito mais rapido de descobrir
# que a senha estava errada as 07h31 do dia seguinte, com a coleta ja perdida.
# Custa ~20s e uma tentativa de login, contra ~15 min de uma coleta inteira.
TESTAR = "--testar-login" in sys.argv
CRED_STDIN = "--credencial-stdin" in sys.argv
CREDENCIAL = None
# UMA linha de stdin serve as duas coisas: a credencial do SEI e os dados de
# conexao do plano. Duas leituras de stdin seriam duas chances de o chamador
# travar esperando a segunda linha que nunca vem.
if CRED_STDIN or PLANO or BUSCAR:
    try:
        CREDENCIAL = json.loads(sys.stdin.readline() or "{}")
    except ValueError:
        print("stdin nao e JSON valido")
        sys.exit(4)
    if CRED_STDIN and not (CREDENCIAL.get("usuario") and CREDENCIAL.get("senha")):
        print("credencial em stdin sem usuario ou senha")
        sys.exit(4)
CONEXAO = (CREDENCIAL or {}).get("plano") or {}
# O PERFIL DA INSTALAÇÃO. Quando vem, ele MANDA: URL de login, domínio, órgão e
# raiz saem daqui, e não das constantes acima. Sem ele, o comportamento é o de
# sempre — a SESAB, para quem roda isto à mão.
PERFIL_SEI = (CREDENCIAL or {}).get("perfil") or {}
if PERFIL_SEI.get("login_url"):
    LOGIN = PERFIL_SEI["login_url"]
    ORGAO = PERFIL_SEI.get("valor_orgao") or None
# ARGUMENTOS DO NAVEGADOR. Em container, o sandbox do Chromium falha no start
# (namespaces de usuario sem SYS_ADMIN) e o /dev/shm de 64 MB mata a aba em
# pagina pesada. Quem liga o SEI_SEM_SANDBOX e o Dockerfile; na estacao a
# variavel nao existe e o sandbox continua ligado, que e onde ele serve.
ARGS_NAVEGADOR = ["--disable-blink-features=AutomationControlled"]
if os.environ.get("SEI_SEM_SANDBOX") == "1":
    ARGS_NAVEGADOR += ["--no-sandbox", "--disable-dev-shm-usage",
                       "--disable-gpu"]

PEDIDO_BUSCA = (CREDENCIAL or {}).get("busca") or {}
if BUSCAR and not PEDIDO_BUSCA:
    print("--buscar exige {\"busca\": {...}} em stdin")
    sys.exit(4)
# O ENVELOPE DO PLANO NAO E CREDENCIAL. Sem esta linha, `CREDENCIAL` ficava truthy
# com {"plano": {...}} e o caminho de login (`if CREDENCIAL:`) lia CREDENCIAL
# ["usuario"] -> KeyError -> exit 4. Como o agente e o unico que passa --plano e
# nunca passa --credencial-stdin, esse era o unico caso que roda em producao: a
# coleta morria exatamente quando a sessao do perfil expirava e era preciso logar.
if not CRED_STDIN:
    CREDENCIAL = None
if PLANO and not (CONEXAO.get("servidor") and CONEXAO.get("token")):
    print("--plano exige {\"plano\":{\"servidor\":...,\"token\":...}} em stdin")
    sys.exit(4)

SAIDA.mkdir(exist_ok=True)
alertas = []


def pedir_plano(itens_por_mesa):
    """Pergunta ao SEI360, mesa a mesa, o que precisa ser lido.

    Devolve {"<mesa>\x1f<id>": veredito}. A chave e por MESA, nao por processo: a
    guarda e o acompanhamento sao por mesa, entao o mesmo processo recebe vereditos
    diferentes legitimamente. Achatando por id, o veredito da ultima mesa consultada
    sobrescrevia o das outras e a ORDEM decidia o que seria relido.

    QUALQUER falha devolve plano vazio para aquela mesa: o pior caso e a coleta
    inteira, que e o que se fazia antes. Nunca o contrario — um erro nao pode virar
    "pule tudo", que produziria uma coleta vazia com cara de rapida.
    """
    import hashlib as _h, hmac as _hm, urllib.request as _u, urllib.error as _e
    import datetime as _dt, http.client as _hc
    plano, base = {}, CONEXAO["servidor"].rstrip("/")
    for mesa, itens in itens_por_mesa.items():
        corpo = json.dumps({"execucao_id": CONEXAO.get("execucao_id"), "mesa": mesa,
                            "parser_versao": CONEXAO.get("parser_versao", ""),
                            "itens": itens}).encode()
        ts = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        req = _u.Request(base + "/api/poco/plano", data=corpo, method="POST",
                         headers={"Authorization": "Bearer " + CONEXAO["token"],
                                  "X-SEI360-Ts": ts,
                                  "X-SEI360-Assinatura": _hm.new(
                                      CONEXAO["token"].encode(),
                                      ts.encode() + b"." + corpo, _h.sha256).hexdigest(),
                                  "Content-Type": "application/json"})
        try:
            with _u.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode() or "{}")
        # OSError cobre ConnectionReset/URLError/HTTPError/Timeout; HTTPException
        # cobre RemoteDisconnected e IncompleteRead. Sem os dois, um worker do
        # gunicorn reiniciando derrubava a coleta INTEIRA com exit 4, depois de ja
        # ter pago a listagem de todas as mesas — o oposto do que a funcao promete.
        except (OSError, _hc.HTTPException, ValueError) as ex:
            log(f"  plano de {mesa} indisponivel ({type(ex).__name__}) — lendo tudo desta mesa")
            alertas.append(f"plano indisponivel para {mesa}")
            continue
        for pid, ver in (d.get("veredito") or {}).items():
            plano[mesa + "\x1f" + pid] = ver
        resumo = d.get("resumo") or {}
        log(f"  plano {mesa}: " + ", ".join(f"{k}={n}" for k, n in sorted(resumo.items())))
    return plano

def log(m):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {m}", flush=True)

import re

# Sinais de que a coleta NAO cobriu o que deveria. Antes isto era so uma lista de
# palavras, e as falhas PARCIAIS escapavam: mesa pulada e processo sem historico
# nao casavam com nenhuma delas, entao a execucao saia com codigo 0 — "coletou sem
# alertas" — publicando um painel incompleto com cara de completo.
ALERTAS = (
    "2fa", "captcha", "codigo", "sem sessao", "sem credencial",
    "nao concluiu", "disjuntor", "falhou", "ficou de fora",
    "nao pegou", "nao abriu", "sem caminho", "incompleta",
    # A armadilha de precedencia: credencial no arquivo E credencial entregue.
    # Nao e mais perigoso (a entregue vence), mas e senha em texto puro num
    # arquivo que viaja — e alerta de execucao, nao linha de log a mais.
    "bloco config",
)
# "(N falhas)" so alerta com N > 0: o resumo normal diz "(0 falhas)" toda execucao.
FALHAS_N = re.compile(r"\((?!0\s)\d+\s+falhas?\)", re.IGNORECASE)


def _esquecer_credencial(pg):
    """Tira a senha do disco. Chamada no sucesso E na falha do login.

    `SEIAuto.credencial()` guarda {usuario,senha} com btoa no localStorage, e o
    localStorage vive no perfil — que no servidor vive no VOLUME. Base64 e
    ofuscacao, nao cifra: sem isto a senha de alguem fica legivel em
    <perfil>/Default/Local Storage/leveldb/*.log depois de cada busca, ao alcance
    de qualquer backup do volume.

    O COOKIE FICA. E ele que evita relogar — e relogar e onde o segundo fator
    aparece, sem ninguem na tela para digitar.

    So quando quem chamou pode reenviar a credencial (stdin). Na estacao a coleta
    agendada roda SEM stdin e depende do localStorage: apagar la quebraria a
    coleta das 07h30.
    """
    if not CREDENCIAL or os.environ.get("SEI_ESQUECER_APOS_LOGIN") != "1":
        return
    try:
        pg.evaluate("() => { SEIAuto.esquecer(); }")
        log("credencial apagada do perfil (o cookie de sessao fica)")
    except Exception as e:                                    # noqa: BLE001
        # Nao deixar o esquecimento derrubar a execucao — mas dizer, porque
        # falhar aqui significa senha em disco.
        log(f"NAO CONSEGUI apagar a credencial do perfil: {type(e).__name__}")


def on_console(msg):
    t = msg.text
    log(f"  page> {t}")
    baixo = t.lower()
    if any(k in baixo for k in ALERTAS) or FALHAS_N.search(t):
        alertas.append(t)

if not JS.exists():
    log(f"ERRO: nao achei {JS}")
    sys.exit(4)

try:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PERFIL), headless=not VER, accept_downloads=False,
            args=ARGS_NAVEGADOR,
        )
        ctx.set_default_timeout(60_000)

        # QUEM ENTREGA CREDENCIAL DESLIGA O CONFIG. Sem isto o bloco CONFIG do
        # .js vence a credencial entregue, e a busca de uma pessoa entra no SEI
        # com a conta de outra — em silencio. Vai por add_init_script, e nao por
        # evaluate, porque a marca precisa renascer depois da navegacao do submit
        # do login, que destroi o contexto da pagina.
        if (CREDENCIAL or {}).get("usuario") and (CREDENCIAL or {}).get("senha"):
            ctx.add_init_script("window.__SEI_IGNORAR_CONFIG = true;")

        # add_init_script re-injeta em TODO documento: o coletor renasce depois da
        # navegacao do login. Com page.evaluate(JS) o contexto morreria no submit.
        ctx.add_init_script(path=str(JS))

        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.on("console", on_console)
        pg.on("pageerror", lambda e: log(f"  pageerror> {e}"))

        log("abrindo o SEI…")
        pg.goto(LOGIN, wait_until="domcontentloaded")

        if "login.php" in pg.url:
            # O login do SEI Bahia tem TRES campos: usuario, senha e ORGAO.
            # O coletor so preenche os dois primeiros — o select fica em branco e o
            # SEI recusa em silencio, recarregando a tela. Preenchemos aqui.
            # (o campo submetido e o input[name=pwdSenha] OCULTO; o visivel,
            #  id=pwdSenha type=text, e so para digitacao humana)
            sel = pg.query_selector("#selOrgao")
            if sel:
                # A FESF é instalação de um órgão só: não há seletor. Escolher
                # órgão onde não há campo derruba o login com erro que parece
                # senha errada.
                if ORGAO:
                    pg.select_option("#selOrgao", ORGAO)
                escolhido = pg.evaluate(
                    "() => { const s=document.getElementById('selOrgao');"
                    "        return s.options[s.selectedIndex].text.trim(); }")
                log(f"orgao selecionado: {escolhido}")
                if not escolhido:
                    log("AVISO: orgao continua em branco — o login vai falhar")

            if CREDENCIAL:
                # Entrega pela API que o proprio .js ja expoe. O valor vai como
                # ARGUMENTO do evaluate, nao interpolado no codigo: senha com
                # aspas, barra ou acento quebraria o script — e um caractere de
                # escape bem colocado viraria injecao no contexto da pagina.
                pg.evaluate("([u, s]) => SEIAuto.credencial(u, s)",
                            [CREDENCIAL["usuario"], CREDENCIAL["senha"]])
                log(f"credencial recebida por stdin ({CREDENCIAL['usuario']})")
            log("acionando SEIAuto.garantirSessao()")
            # garantirSessao() e o que a API expoe; ela chama logar() internamente.
            # NAO devolve a promise: o click do submit navega e mataria o evaluate.
            pg.evaluate("() => { SEIAuto.garantirSessao(); }")
            # `finally`, E NAO SO NO SUCESSO. O caminho de falha saia por
            # sys.exit(3) ANTES de apagar, e a senha de quem pediu ficava em
            # base64 no leveldb do perfil — justamente no caso em que algo deu
            # errado e ninguem vai olhar. Login recusado e a hora em que mais
            # importa nao deixar credencial para tras.
            try:
                pg.wait_for_url(lambda u: "login.php" not in u, timeout=60_000)
            except PWTimeout:
                _esquecer_credencial(pg)
                pg.screenshot(path=str(SAIDA / "falha_login.png"), full_page=True)
                log("LOGIN NAO CONCLUIU em 60s — ver _coletas/falha_login.png")
                for a in alertas: log(f"  alerta: {a}")
                ctx.close(); sys.exit(3)
            except Exception:
                _esquecer_credencial(pg)
                raise
            log(f"login ok — {pg.url.split('?')[0]}")
            _esquecer_credencial(pg)
        else:
            log("sessao ja ativa neste perfil")

        if TESTAR:
            # So confere quem entrou e onde, e sai. O cabecalho do SEI carrega a
            # unidade ativa; ler dali e melhor que confiar em constante, que foi
            # justamente a regra dura #5 do SPECS.
            quem = pg.evaluate("""() => {
                const t = (s) => (document.querySelector(s)||{}).textContent || '';
                return {
                  usuario: (t('#lnkUsuarioSistema') || t('#lnkInfraUnidade') || '').trim(),
                  unidade: (t('#lnkInfraUnidade') || '').trim(),
                  titulo: document.title
                };
            }""")
            # AS MESAS DA CONTA, no mesmo teste. `descobrirMesas` ja existia e so
            # era usada na coleta inteira; o teste devolvia apenas a unidade
            # CORRENTE da sessao. Mas e aqui que se descobre o que ESTA pessoa
            # alcanca no SEI — e e isso que decide o que ela pode ver e coletar no
            # SEI360. Antes, a tela de configuracao oferecia as unidades que a
            # coleta de OUTRA pessoa ja tinha trazido, o que e a pergunta errada.
            try:
                mesas = pg.evaluate("() => SEIAuto.descobrirMesas()")
                quem["mesas"] = [m.get("sigla") for m in (mesas or []) if m.get("sigla")]
            except Exception as e:                                # noqa: BLE001
                # Falhar aqui nao invalida o login: o acesso esta provado. O que se
                # perde e a descoberta, e quem le precisa saber disso.
                log(f"login ok, mas nao consegui listar as mesas: {type(e).__name__}")
                quem["mesas"] = []
            log(f"LOGIN OK · usuario={quem.get('usuario')!r} "
                f"unidade={quem.get('unidade')!r} mesas={len(quem.get('mesas') or [])}")
            print("TESTE_OK " + json.dumps(quem, ensure_ascii=False))
            ctx.close()
            sys.exit(0)

        if BUSCAR:
            # UMA BUSCA, e nada mais. O motor é outro arquivo (pesquisa_sei.js):
            # a busca não compartilha estado com a coleta, e um erro nela não pode
            # deixar checkpoint de coleta pela metade.
            if not JS_BUSCA.exists():
                log(f"ERRO: nao achei {JS_BUSCA}")
                ctx.close(); sys.exit(4)
            pg.add_init_script(path=str(JS_BUSCA))
            pg.evaluate(JS_BUSCA.read_text(encoding="utf-8"))
            pg.set_default_timeout(600_000)
            log(f"buscando… (busca {PEDIDO_BUSCA.get('busca_id')})")
            env = pg.evaluate("(p) => SEIBusca.pesquisar(p)", PEDIDO_BUSCA)
            # O ENVELOPE VAI PARA STDOUT numa linha, com prefixo. Quem chama lê
            # isso; o log fica no resto das linhas, como sempre.
            print("BUSCA_OK " + json.dumps(env, ensure_ascii=False))
            log(f"busca: {len(env.get('itens') or [])} item(ns), "
                f"{env.get('paginas_lidas')} pagina(s), {env.get('duracao_s')}s"
                + (f" — {env['motivo']}" if env.get("motivo") else ""))
            ctx.close()
            sys.exit(1 if env.get("motivo") else 0)

        # Zera os checkpoints. Sem isso, um rodar() que falhe em silencio faria o
        # exportar() gravar a coleta anterior com a data de hoje.
        pg.evaluate("() => { localStorage.removeItem('__SEI_LISTA');"
                    "        localStorage.removeItem('__SEI_INV');"
                    "        localStorage.removeItem('__SEI_ACOMP');"
                    "        localStorage.removeItem('__SEI_DATAS'); }")

        pg.set_default_timeout(600_000)          # a coleta pode passar de 1 min
        if PLANO and MESAS:
            # A coleta em duas metades, com a pergunta ao servidor no meio.
            log("listando as mesas…")
            r = pg.evaluate("(o) => SEIAuto.listarTodasAsMesas(o)", {"origem": ORIGEM})
            if not r or not r.get("itens"):
                pg.screenshot(path=str(SAIDA / "falha_coleta.png"), full_page=True)
                log("listagem nao devolveu nada — NADA foi gravado")
                ctx.close(); sys.exit(2)
            por_mesa = {}
            for it in r["itens"]:
                por_mesa.setdefault(it.pop("mesa"), []).append(it)
            log(f"consultando o plano de {len(por_mesa)} mesa(s)…")
            veredito = pedir_plano(por_mesa)
            # LINHAS dos dois lados. Contando chaves do dicionario contra o numero
            # de itens, um processo em tres mesas contava 1 no numerador e 3 no
            # denominador — a economia saia sistematicamente subestimada, no mesmo
            # log que se usa para decidir se o poco vale a pena.
            poupados = sum(1 for v in veredito.values() if v in ("pular", "em_leitura"))
            log(f"plano: {poupados} de {sum(len(x) for x in por_mesa.values())} "
                f"linha(s) dispensam leitura")
            # A ORIGEM VIAJA COMO ARGUMENTO, nunca como estado de modulo: o
            # `add_init_script` reinjeta o .js a cada documento, e uma navegacao
            # entre as duas metades zeraria uma variavel de modulo. Hoje isso nao
            # acontece (medido: 2 injecoes por execucao, nenhum goto entre elas),
            # mas depender disso e depender de acidente.
            dados = pg.evaluate("(a) => SEIAuto.detalharTodasAsMesas(a.v, a.o)",
                                {"v": veredito, "o": {"origem": ORIGEM}})
        else:
            log(f"coletando… ({ENTRY})")
            if MESAS:
                dados = pg.evaluate("(o) => SEIAuto.rodarTodasAsMesas(o)", {"origem": ORIGEM})
            else:
                # `rodar()` fica numa mesa so e nunca troca de unidade.
                dados = pg.evaluate(f"() => {ENTRY}")

        # O dado vem do RETORNO. exportar() le do localStorage e mentiria em caso de falha.
        if not dados:
            pg.screenshot(path=str(SAIDA / "falha_coleta.png"), full_page=True)
            log("rodar() nao devolveu dados — NADA foi gravado")
            for a in alertas: log(f"  alerta: {a}")
            ctx.close(); sys.exit(2)

        out = SAIDA / f"sei_sesab_{datetime.date.today():%Y-%m-%d}.json"

        # O arquivo e por DIA: duas execucoes no mesmo dia disputam o mesmo nome.
        # Sem isto, uma coleta parcial (mesa caiu, sessao expirou) sobrescreve em
        # silencio uma coleta completa da manha, e o dado bom nao volta.
        if out.exists():
            try:
                antigo = json.loads(out.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                antigo = []
            reserva = SAIDA / (out.stem + ".anterior.json")
            out.replace(reserva)
            log(f"  execucao anterior de hoje ({len(antigo)} registros) -> {reserva.name}")
            if len(dados) < len(antigo) * 0.9:
                log(f"  ATENCAO: coleta atual ({len(dados)}) e MENOR que a anterior "
                    f"({len(antigo)}) — conferir antes de usar")
                alertas.append("coleta menor que a anterior")

        out.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"{len(dados)} registros -> {out.name}")

        # resumo util no log do agendador
        com_mesa = sum(1 for d in dados if d.get("mesas"))
        com_ger  = sum(1 for d in dados if d.get("gerador_unidade"))
        log(f"  com mesas: {com_mesa}/{len(dados)} | com unidade geradora: {com_ger}/{len(dados)}")
        falhou = (dados[0] or {}).get("mesas_falhas") or []
        if falhou:
            log(f"  ATENCAO: coleta INCOMPLETA — mesas fora: {', '.join(falhou)}")
        # A CONTA VOLTOU? A palavra "falhou" cai na tupla ALERTAS e vira exit 1 —
        # o wrapper ainda regera o painel (LEQ 1), entao o aviso nao custa o dado.
        marca = dados[0] or {}
        if marca.get("unidade_restaurada") is False:
            log(f"  ATENCAO: a unidade NAO voltou — a sessao falhou em retornar para "
                f"{marca.get('unidade_origem') or '?'} e a conta pode ter ficado em "
                f"{marca.get('unidade_final') or '?'}")
        elif marca.get("unidade_restaurada"):
            log(f"  unidade devolvida para {marca.get('unidade_origem')}")
        sem_hist = sum(1 for d in dados if d.get("sem_historico"))
        if sem_hist:
            log(f"  ATENCAO: {sem_hist} processo(s) sem historico lido (datas em branco)")

        ctx.close()

except Exception:
    log("ERRO DE INFRAESTRUTURA:")
    traceback.print_exc()
    sys.exit(4)

if alertas:
    log(f"concluido COM {len(alertas)} alerta(s)")
    sys.exit(1)
log("concluido")
sys.exit(0)
