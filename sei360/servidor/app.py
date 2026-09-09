# -*- coding: utf-8 -*-
"""
SEI360 — servidor.

O QUE ESTE PROCESSO NAO FAZ, DE PROPOSITO
-----------------------------------------
Nao abre navegador, nao fala com o SEI, nao guarda senha do SEI. Ele recebe o
resultado da coleta de um agente que roda na estacao de quem tem a credencial.
Quem tomar este servidor leva a base coletada — grave e notificavel — e nao leva
a capacidade de agir no SEI em nome de ninguem.

    python app.py            # 127.0.0.1:8360
    python app.py --publico  # 0.0.0.0, para container
"""
import json, logging, os, secrets, sys, hashlib
import threading
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, request, render_template, redirect, url_for,
                   make_response, jsonify, abort)

from werkzeug.middleware.proxy_fix import ProxyFix

import banco, seguranca as seg, janelas, poco, perfil_sei, busca as buscamod
import acesso
import configuracao as cfgmod
from banco import conectar, agora, registrar, TZ

# O CMD do container e "gunicorn app:app": ele IMPORTA este modulo e nunca executa
# o bloco __main__. Sem migrar aqui, volume novo sobe "verde" e devolve 500 em toda
# rota — inclusive a de login e a de saude, que e justamente a que o EasyPanel olha.
# O DDL inteiro e CREATE TABLE IF NOT EXISTS, entao chamar sempre e barato.
try:
    banco.migrar()
except Exception as _e:                                    # noqa: BLE001
    print(f"AVISO: migração falhou no import: {_e}", file=sys.stderr)

# static_folder em portugues para o projeto inteiro falar a mesma lingua; o
# endpoint continua sendo "static", que e o nome que o Flask expoe ao url_for.
app = Flask(__name__, static_folder="estatico", static_url_path="/estatico")


# `estatico/vendor/` NAO MUDA NUNCA: sao as bibliotecas e as fontes, com a versao
# no proprio conteudo (d3.min.js, gsap.min.js, os .woff2 do Inter/JetBrains/Space
# Grotesk) — 1,34 MB ao todo. O padrao do Flask e `no-cache`, que nao quer dizer
# "nao guarde": quer dizer "guarde e PERGUNTE a cada vez". Resultado medido: uma
# ida ao servidor por arquivo por abertura de tela, so para receber 304.
#
# A tela de acesso e a mais cara: sozinha ela puxa d3 (273 KB) e gsap (70 KB),
# que existem para a animacao e SAO parte do desenho — o conserto certo nao e
# tirar a animacao, e fazer o arquivo descer uma vez so.
#
# O CSS DO PROJETO fica de fora de proposito: `sei360.css`, `nav.css` e
# `lateral.css` mudam a cada correcao, somam 36 KB e o caminho nao tem versao.
# Um ano de cache neles seria consertar uma cor e a pessoa seguir vendo a antiga
# — caro do jeito que importa.
_ANO_S = 60 * 60 * 24 * 365


# `vendor/fontes.css` E NOSSO, apesar da pasta: ele declara os @font-face, e
# mexer num `unicode-range` ou acrescentar um peso e edicao normal do projeto.
# Com um ano de `immutable` e caminho sem versao, a correcao ficaria invisivel
# para quem ja abriu a tela — e nem o F5 traria, porque `immutable` dispensa ate
# a revalidacao manual. Os .woff2 e os .min.js carregam a versao no conteudo e
# nunca mudam sem trocar de nome; esses ficam.
_VENDOR_NOSSO = ("vendor/fontes.css",)


def _idade_do_estatico(nome):
    caminho = (nome or "").replace("\\", "/")
    if caminho in _VENDOR_NOSSO:
        return None
    return _ANO_S if caminho.startswith("vendor/") else None


# Atribuicao na INSTANCIA, nao subclasse: `send_static_file` chama
# `self.get_send_file_max_age(filename)`, e o atributo de instancia vence.
app.get_send_file_max_age = _idade_do_estatico
# OS DOIS NOMES, porque o ARQUITETURA_ACESSO.md pediu `SEI360_SECRET_KEY` por
# meses enquanto o código lia `SEI360_SEGREDO` — quem seguiu o documento
# configurou uma variável que o processo ignorava, sem sintoma nenhum.
#
# E o que ela protege, dito por extenso para ninguém superestimar: NADA hoje.
# Não há `session[...]` nem `flash()` nesta aplicação. A sessão é um token
# aleatório guardado como SHA-256 na tabela `sessoes`, e o CSRF é um token
# aleatório em cookie comparado com o do formulário (`seguranca.novo_csrf`).
# `secret_key` existe porque o Flask quer uma; sortear por processo é inofensivo
# hoje e deixaria de ser no dia em que alguém usar `session` — e é esse dia que
# a variável antecipa.
app.secret_key = (os.environ.get("SEI360_SEGREDO")
                  or os.environ.get("SEI360_SECRET_KEY")
                  or secrets.token_hex(32))
# Atras do Traefik, request.remote_addr e o IP do proxy e o X-Forwarded-For e
# texto que o cliente escreve. Confiar no PRIMEIRO elemento do XFF deixa qualquer
# um envenenar o rate limit (basta mandar 20 requisicoes dizendo ser o IP do
# orgao para trancar o painel inteiro) e sujar o log de acesso. ProxyFix usa o
# ultimo salto, que e o unico que o proxy realmente escreveu.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
# O template guarda a lista de unidades do agente como JSON. Sem este filtro a
# tela imprimiria o texto cru '["A","B"]' na caixa de edicao.
app.jinja_env.filters["fromjson"] = lambda s: json.loads(s or "[]")


def _iniciais(nome, email):
    """Iniciais do avatar de 26px na lateral (`.lat-av`) — da PESSOA, não do
    login. Até 09/09/2026 vinham sempre de `email[:2]`, o mesmo defeito do
    rótulo ao lado (ver `_nav.html`): a conta tem `usuarios.nome` desde a
    criação, mas a marcação nunca olhava para ele.

    Nome com duas palavras ou mais usa a primeira letra da primeira e da
    última ('Laisa Menezes' -> 'LM'). Nome de uma palavra só, ou conta sem
    nome (bootstrap, contas antigas), cai no comportamento de antes."""
    partes = (nome or "").split()
    if len(partes) >= 2:
        return (partes[0][0] + partes[-1][0]).upper()
    if partes and len(partes[0]) >= 2:
        return partes[0][:2].upper()
    return (email or "??")[:2].upper()


app.jinja_env.filters["iniciais"] = _iniciais
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024      # coleta chega a ~2,5 MB
COOKIE = "sei360_sess"
COOKIE_CSRF = "sei360_csrf"
# COOKIE PRÓPRIO, separado do de sessão. A sessão pendente do segundo fator não
# é uma sessão com uma marca de "ainda não vale": marca é coluna que alguém
# esquece de conferir numa consulta nova, e o preço desse esquecimento é entrar
# sem o segundo fator. Aqui, quem só tem este cookie não tem sessão nenhuma — a
# única porta que ele abre é a tela do código.
COOKIE_DESAFIO = "sei360_2fa"
VERSAO_AGENTE = "1.0.0"

def cookie_seguro():
    """Secure sai do PROTOCOLO da requisicao, nao de variavel de ambiente.

    Marcar Secure numa resposta http:// nao protege nada — o navegador
    simplesmente descarta o cookie e o login nunca fecha, que foi exatamente o
    que aconteceu no primeiro teste ponta a ponta. Atras do Traefik a origem
    chega em X-Forwarded-Proto.
    """
    if os.environ.get("SEI360_FORCAR_HTTPS") == "1":
        return True
    return request.is_secure or         request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() == "https"


# --------------------------------------------------------------- sessao
def usuario_atual():
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    cx = conectar()
    linha = cx.execute("""SELECT s.*, u.email, u.nome, u.papel, u.ativo, u.senha_trocada_em
                          FROM sessoes s JOIN usuarios u ON u.id=s.usuario_id
                          WHERE s.token_sha256=?""", (seg.hash_token(tok),)).fetchone()
    if not linha or not linha["ativo"] or not seg.sessao_viva(linha):
        cx.close()
        return None
    cx.execute("UPDATE sessoes SET ultimo_uso_em=? WHERE id=?", (agora(), linha["id"]))
    cx.commit()
    cx.close()
    return linha


@app.context_processor
def _portas_da_tela():
    """Toda tela recebe as portas que ESTE papel pode abrir.

    Injetar no contexto em vez de passar em cada `render_template` é o que
    impede o caso já visto: uma tela nova entra sem a barra, ou entra com a
    barra de outro papel porque quem a escreveu copiou a chamada errada.
    """
    import portas
    u = getattr(request, "usuario", None)
    return {"portas": portas.visiveis(u["papel"]) if u else []}


def exige_login(f):
    @wraps(f)
    def interno(*a, **kw):
        u = usuario_atual()
        if not u:
            return redirect(url_for("entrar", proximo=request.path))
        # Primeiro acesso bloqueia TODAS as rotas: senha provisoria que continua
        # valendo enquanto a pessoa usa o sistema e senha permanente na pratica.
        if not u["senha_trocada_em"] and request.endpoint != "primeiro_acesso":
            return redirect(url_for("primeiro_acesso"))
        request.usuario = u
        return f(*a, **kw)
    return interno


def exige_admin(f):
    @wraps(f)
    @exige_login
    def interno(*a, **kw):
        if request.usuario["papel"] != "admin":
            abort(403)
        return f(*a, **kw)
    return interno


def confere_csrf():
    enviado = request.headers.get("X-CSRF") or request.form.get("csrf")
    if not seg.csrf_ok(request.cookies.get(COOKIE_CSRF), enviado):
        abort(400, "CSRF")


def ip_cliente():
    """IP de verdade. Com ProxyFix instalado, remote_addr JA e o ultimo salto —
    ler o cabecalho de novo reintroduziria o valor que o cliente escreve."""
    return request.remote_addr or "?"


def destino_interno(p):
    """Caminho do proprio app, ou None.

    `location.href = j.destino` (login.html) executa o que vier: um `proximo`
    valendo `javascript:...` roda no origin JA autenticado, e o cookie CSRF e
    legivel por JS de proposito (double-submit) — o payload forjaria POST
    autenticado. A decisao fica no servidor; a checagem no cliente e reforco.
    """
    if not p or not p.startswith("/") or p.startswith("//") or p.startswith("/\\"):
        return None
    if ":" in p.split("/")[0]:
        return None
    return p


def unidades_do(usuario_id, com_instancia=False):
    """As unidades desta pessoa. Nomes por padrão; pares com `com_instancia`.

    A COLUNA `instancia` EXISTE E ERA DESCARTADA AQUI. Nome de unidade não é
    único entre instalações — "GABINETE" existe na SESAB e na FESF —, e quem
    precisa saber DE QUAL instalação é cada vínculo (o rótulo do painel, o
    recorte da carteira) não tinha como perguntar.

    O padrão continua sendo a lista de nomes porque é o que os dezoito usos
    existentes consomem, e porque o recorte por instalação já é resolvido no SQL
    de `snapshots_de` (o JOIN é por `(usuario_id, instancia, unidade)`).
    """
    cx = conectar()
    linhas = cx.execute(
        "SELECT COALESCE(instancia,'SEI-SESAB') AS instancia, unidade "
        "FROM usuario_unidade WHERE usuario_id=? ORDER BY principal DESC, unidade",
        (usuario_id,)).fetchall()
    cx.close()
    if com_instancia:
        return [(r["instancia"], r["unidade"]) for r in linhas]
    return [r["unidade"] for r in linhas]


# --------------------------------------------------------------- login
def mil(n):
    """1165 -> "1.165".

    Sem `locale`: setlocale e global ao processo, nao e thread-safe e mudaria o
    formato de tudo por causa de um numero na tela de login. E `{:n}` sem
    setlocale nao poe separador nenhum — parece funcionar e nao funciona.
    """
    return f"{n:,}".replace(",", ".")


# RESUMOS DA CARTEIRA CORRENTE, nao linhas da tabela. `resumo` guarda o texto por
# `id_sei` e nao e apagado quando o processo sai da carteira: entre a coleta de
# 18/08 e a de 26/08 sobraram 113 resumos de processos que nao estao em nenhum
# snapshot corrente. Conta-los inflava a cobertura de IA em /admin — "1.054 com
# resumo, 256 sem", que somava 1.310 sobre uma base real de 1.197 — e e esse o
# numero que decide se vale mandar gerar mais e quanto isso custa.
SQL_COM_RESUMO = """SELECT COUNT(DISTINCT p.id_sei) FROM processo p
                    JOIN snapshot s ON s.id=p.snapshot_id
                    JOIN resumo r ON r.id_sei=p.id_sei
                    WHERE s.estado='corrente'"""


def _recuperacao_ligada():
    """A tela de acesso precisa saber se o link de recuperação existe.

    Numa página exposta sem sessão, a conexão tem de abrir e FECHAR: um descritor
    por visita esperando o coletor de lixo é vazamento com nome bonito.
    """
    cx = conectar()
    try:
        return acesso.ler_politica(cx)["recuperacao_ativa"]
    finally:
        cx.close()


def numeros_da_tela():
    """Os números da tela de acesso saem do BANCO.

    A tela original trazia "847.392 processos", "R$ 4,21 bi mapeados", "3.218
    sessões ativas" e "98,7% de acurácia". Número inventado numa tela de
    autenticação de órgão público é declaração falsa — e é a primeira coisa que
    alguém de dentro confere. Os lugares continuam os mesmos; os valores, não.

    Nada aqui exige sessão: são agregados sem nome de pessoa e sem protocolo.
    """
    cx = conectar()
    n_proc = cx.execute("""SELECT COUNT(DISTINCT p.id_sei) FROM processo p
                           JOIN snapshot s ON s.id=p.snapshot_id
                           WHERE s.estado='corrente'""").fetchone()[0]
    n_uni = cx.execute("SELECT COUNT(*) FROM snapshot WHERE estado='corrente'").fetchone()[0]
    n_res = cx.execute(SQL_COM_RESUMO).fetchone()[0]
    # Contagem no SQL, não em Python. A versão anterior trazia TODA sessão não
    # revogada para a memória e chamava sessao_viva() em cada uma — a cada carga
    # da tela de acesso, que é a página exposta. Como sessão morta nunca era
    # apagada (agora o expurgo apaga), o custo crescia com o uso do sistema.
    corte_inativo = (datetime.now(TZ) - timedelta(minutes=seg.INATIVIDADE_MIN)).isoformat(timespec="seconds")
    vivas = cx.execute("""SELECT COUNT(*) FROM sessoes
                          WHERE revogada_em IS NULL AND expira_em > ?
                            AND COALESCE(ultimo_uso_em, criado_em) > ?""",
                       (agora(), corte_inativo)).fetchone()[0]
    janelas_cfg = cx.execute("SELECT janelas, dias FROM agendamento WHERE ativo=1 LIMIT 1").fetchone()
    cx.close()
    quantas = len(json.loads(janelas_cfg["janelas"])) if janelas_cfg else 0
    janela = (f"{quantas}x/{'dia útil' if not janelas_cfg or janelas_cfg['dias'] == 'uteis' else 'dia'}"
              if quantas else "sem agendamento")
    return n_proc, n_uni, n_res, vivas, janela


@app.get("/entrar")
def entrar():
    if usuario_atual():
        return redirect(url_for("painel"))
    # A TELA DA PORTA NAO FALA DA OPERACAO. Estado da coleta e contagem de
    # sessoes ativas sao informacao de dentro: a primeira diz a quem esta fora se
    # e uma boa hora para tentar de novo, e a segunda diz quanta gente esta
    # trabalhando agora — nenhuma das duas ajuda quem so quer entrar. Sairam da
    # tela E do payload: esconder no template deixaria o numero no fonte da
    # pagina, que e onde quem procura ia olhar.
    #
    # De quebra, `estado_coleta()` era uma varredura de `snapshots_de` mais a
    # tabela `snapshot` em cada carregamento da unica pagina exposta sem sessao.
    n_proc, n_uni, n_res, _vivas, _janela = numeros_da_tela()
    resp = make_response(render_template(
        "login.html",
        n_processos=mil(n_proc), n_unidades=n_uni,
        # Depois de definir a senha, a pessoa e trazida para ca de proposito (a
        # troca derruba todas as sessoes). Sem esta marca, a tela ficava muda.
        trocada=bool(request.args.get("trocada")),
        esgotado=bool(request.args.get("esgotado")),
        # A TELA NAO PODE PROMETER O QUE NAO EXISTE — nem esconder o que existe.
        # Com a recuperacao desligada a frase e "fale com a administracao"; com
        # ela ligada, vira um link. Uma so das duas aparece.
        recuperacao_ativa=_recuperacao_ligada(),
        # AGREGADO, sem sigla. Esta tela é vista por quem ainda NÃO entrou, e a
        # lista de unidades com a idade da coleta de cada uma é inventário do
        # órgão — o `/saude` recusa publicar exatamente isso, e aqui saía de
        # graça. A quem está na porta interessa se o sistema tem dado fresco, não
        # quais mesas existem.
        versao=VERSAO_AGENTE, hoje=datetime.now(TZ).strftime("%Y.%m.%d"),
        reais={"processos": mil(n_proc), "unidades": str(n_uni),
               "resumos": mil(n_res)}))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax", secure=cookie_seguro(), path="/")
    return resp


@app.post("/entrar")
def entrar_post():
    confere_csrf()
    email = (request.form.get("email") or "").strip().lower()
    # `.strip()` NA SENHA TAMBEM. A primeira entrada de toda conta e com uma
    # senha provisoria COLADA — de um terminal, de um chat, de um e-mail — e a
    # colagem carrega espaco ou quebra de linha no fim com frequencia. Sem isto
    # a pessoa recebe "senha incorreta" com a senha certa na mao, e gasta as
    # cinco tentativas antes do bloqueio tentando entender.
    #
    # E casado com o `.strip()` de quem DEFINE a senha: os dois lados aparam do
    # mesmo jeito, entao ninguem fica trancado fora por um espaco que ele nem
    # sabia ter digitado.
    senha = (request.form.get("pw") or "").strip()
    lembrar = request.form.get("remember") == "on"
    ip = ip_cliente()

    cx = conectar()
    if seg.ip_excedeu(cx, ip):
        cx.close()
        return jsonify(erro="Muitas tentativas deste endereço. Aguarde um minuto."), 429

    u = cx.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
    espera = seg.bloqueio_ativo(u)
    if espera:
        cx.close()
        return jsonify(erro=f"Conta bloqueada por {espera} min após tentativas erradas."), 423

    if not u or not u["ativo"]:
        # gasta o mesmo tempo do caminho valido: sem isso a latencia responde
        # "esta conta existe?" para quem so tem a lista de e-mails
        seg.gastar_tempo_isca()
        seg.registrar_falha(cx, None, email, ip)
        cx.commit(); cx.close()
        return jsonify(erro="E-mail ou senha incorretos."), 401

    if not seg.conferir_senha(senha, u["senha_hash"], u["senha_sal"]):
        minutos = seg.registrar_falha(cx, u, email, ip)
        cx.commit(); cx.close()
        if minutos:
            return jsonify(erro=f"Conta bloqueada por {minutos} min após tentativas erradas."), 423
        return jsonify(erro="E-mail ou senha incorretos."), 401

    # admin nunca recebe sessao de 30 dias: e a conta que administra todas as outras
    lembrar = lembrar and u["papel"] != "admin"

    # SEGUNDO FATOR, quando a política pede. A SESSÃO NÃO NASCE AQUI: ela nasce
    # em `/verificar`, depois do código. É o que separa "a senha confere" de
    # "esta pessoa entrou".
    #
    # O acerto da senha JÁ FOI REGISTRADO como sucesso: sem isso, quem digita a
    # senha certa e não conclui o código carrega para sempre as falhas anteriores
    # na janela de bloqueio, e a próxima digitação errada tranca a conta.
    if acesso.exige_fator2(cx, u):
        # O ACERTO DA SENHA É REGISTRADO, mas `ultimo_login_em` NÃO: quem digita a
        # senha certa e nunca conclui o código não entrou, e a coluna "Último
        # acesso" da tela de pessoas estaria afirmando que sim. O que precisa ser
        # zerado aqui é o contador de bloqueio — senão as falhas anteriores
        # somariam com a próxima digitação errada.
        cx.execute("INSERT INTO tentativas_login(email,ip,ts,sucesso) VALUES(?,?,?,1)",
                   (email, ip, agora()))
        cx.execute("UPDATE usuarios SET falhas_seq=0, bloqueado_ate=NULL WHERE id=?",
                   (u["id"],))
        tok2, erro2 = acesso.abrir_desafio(
            cx, u, ip, request.headers.get("User-Agent"), lembrar)
        cx.commit(); cx.close()
        if not tok2:
            # O E-MAIL NÃO SAIU. Não abrimos a porta assim mesmo: quem consegue
            # derrubar a entrega passaria a ter um caminho para pular o segundo
            # fator, que é exatamente o ataque. Quem administra tem a chave
            # reserva — `emergencia.py desligar-fator2`, no servidor, sem
            # depender de e-mail nem de painel.
            registrar(cx0 := conectar(), u["id"], "fator2_sem_envio",
                      alvo=(erro2 or "")[:150], ip=ip)
            cx0.commit(); cx0.close()
            return jsonify(erro="Não foi possível enviar o seu código de acesso: "
                                f"{erro2}. Avise quem administra o SEI360."), 503
        resp = jsonify(ok=True, destino=url_for("verificar"))
        # SEM `max_age`: morre ao fechar o navegador. Ele vale dez minutos e uma
        # tela; não há motivo para sobreviver à sessão do navegador.
        resp.set_cookie(COOKIE_DESAFIO, tok2, httponly=True, samesite="Lax",
                        secure=cookie_seguro(), path="/")
        return resp

    token, th = seg.novo_token()
    cx.execute("""INSERT INTO sessoes(usuario_id,token_sha256,criado_em,expira_em,
                  ultimo_uso_em,ip,user_agent,lembrar) VALUES(?,?,?,?,?,?,?,?)""",
               (u["id"], th, agora(), seg.validade(lembrar), agora(), ip,
                (request.headers.get("User-Agent") or "")[:200], int(lembrar)))
    seg.registrar_sucesso(cx, u["id"], email, ip)
    registrar(cx, u["id"], "login", ip=ip)
    cx.commit(); cx.close()

    destino = url_for("primeiro_acesso") if not u["senha_trocada_em"] else \
        (destino_interno(request.form.get("proximo")) or url_for("painel"))
    resp = jsonify(ok=True, destino=destino)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="Lax", secure=cookie_seguro(), path="/",
                    max_age=int(timedelta(days=30).total_seconds()) if lembrar else None)
    return resp


# ------------------------------------------------- segundo fator
@app.get("/verificar")
def verificar():
    """A tela do código. Só existe para quem tem um desafio vivo."""
    cx = conectar()
    d = acesso.ler_desafio(cx, request.cookies.get(COOKIE_DESAFIO))
    cx.close()
    if not d:
        return redirect(url_for("entrar"))
    import email_saida
    resp = make_response(render_template(
        "verificar.html", destino=email_saida.mascarar(d["email"]),
        digitos=acesso.DIGITOS, minutos=acesso.VALIDADE_CODIGO_MIN, erro=None))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax",
                    secure=cookie_seguro(), path="/")
    return resp


@app.post("/verificar")
def verificar_post():
    confere_csrf()
    ip = ip_cliente()
    tok2 = request.cookies.get(COOKIE_DESAFIO)
    cx = conectar()
    d = acesso.ler_desafio(cx, tok2)
    if not d:
        cx.close()
        return redirect(url_for("entrar"))
    u, erro = acesso.conferir_desafio(cx, tok2, request.form.get("codigo"), ip)
    if not u:
        cx.commit()
        import email_saida
        mascarado = email_saida.mascarar(d["email"])
        cx.close()
        cx2 = conectar()
        vivo = acesso.ler_desafio(cx2, tok2)
        cx2.close()
        if not vivo:
            # Esgotou ou venceu. O cookie não serve mais e deixá-lo no navegador
            # faz a próxima visita cair numa tela morta — mas A EXPLICAÇÃO VAI
            # JUNTO. Antes, quem errava a quinta vez era jogado na tela de acesso
            # sem uma palavra: o desafio tinha acabado de ser cancelado, o ramo do
            # redirect não carregava a frase, e a pessoa ficava sem saber se a
            # senha estava errada, se a conta bloqueou, ou o quê.
            r = make_response(redirect(url_for("entrar", esgotado=1)))
            r.delete_cookie(COOKIE_DESAFIO, path="/")
            return r
        return render_template("verificar.html", destino=mascarado,
                               digitos=acesso.DIGITOS,
                               minutos=acesso.VALIDADE_CODIGO_MIN, erro=erro)
    # Passou. A sessão nasce agora, e o cookie do desafio some.
    alvo = cx.execute("SELECT * FROM usuarios WHERE id=?", (u["usuario_id"],)).fetchone()
    lembrar = bool(d["lembrar"]) and alvo["papel"] != "admin"
    token, th = seg.novo_token()
    cx.execute("""INSERT INTO sessoes(usuario_id,token_sha256,criado_em,expira_em,
                  ultimo_uso_em,ip,user_agent,lembrar) VALUES(?,?,?,?,?,?,?,?)""",
               (alvo["id"], th, agora(), seg.validade(lembrar), agora(), ip,
                (request.headers.get("User-Agent") or "")[:200], int(lembrar)))
    registrar(cx, alvo["id"], "login", alvo="com segundo fator", ip=ip)
    cx.commit(); cx.close()
    destino = (url_for("primeiro_acesso") if not alvo["senha_trocada_em"]
               else url_for("painel"))
    resp = make_response(redirect(destino))
    resp.set_cookie(COOKIE, token, httponly=True, samesite="Lax",
                    secure=cookie_seguro(), path="/",
                    max_age=int(timedelta(days=30).total_seconds()) if lembrar else None)
    resp.delete_cookie(COOKIE_DESAFIO, path="/")
    return resp


# ------------------------------------------------- recuperação de senha
@app.route("/esqueci", methods=["GET", "POST"])
def esqueci():
    """Pede o link. A resposta é a MESMA exista a conta ou não."""
    cx = conectar()
    pol = acesso.ler_politica(cx)
    if request.method == "GET":
        cx.close()
        resp = make_response(render_template("esqueci.html",
                                             ativa=pol["recuperacao_ativa"], recado=None))
        resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax",
                        secure=cookie_seguro(), path="/")
        return resp
    confere_csrf()
    ip = ip_cliente()
    if seg.ip_excedeu(cx, ip):
        cx.close()
        return render_template("esqueci.html", ativa=pol["recuperacao_ativa"],
                               recado=acesso.MESMA_RESPOSTA)
    def montar(tok):
        # DA CONFIGURAÇÃO, NUNCA DO `Host` DA REQUISIÇÃO. `url_for(_external=True)`
        # monta a URL a partir do host que chegou — e com `ProxyFix(x_host=1)` esse
        # host vem do cabeçalho `X-Forwarded-Host`, que quem faz a requisição
        # controla. Um POST em /esqueci com `Host: exemplo-do-atacante` faria sair,
        # do NOSSO remetente, um e-mail legítimo com um link para o servidor dele:
        # a pessoa clica, digita a senha nova lá, e ele fica com a senha e com o
        # token. É o ataque de envenenamento de host, e ele é gratuito.
        #
        # `salvar_politica` só arma a recuperação com `SEI360_BASE_URL` definida,
        # então este caminho nunca roda sem base configurada.
        base = (os.environ.get("SEI360_BASE_URL") or "").rstrip("/")
        return f"{base}/recuperar/{tok}"
    _enviado, recado = acesso.pedir_recuperacao(
        cx, request.form.get("email"), ip, montar)
    cx.commit(); cx.close()
    return render_template("esqueci.html", ativa=pol["recuperacao_ativa"], recado=recado)


@app.route("/recuperar/<token>", methods=["GET", "POST"])
def recuperar(token):
    cx = conectar()
    r = acesso.ler_recuperacao(cx, token)
    if request.method == "GET":
        email = r["email"] if r else None
        cx.close()
        resp = make_response(render_template("recuperar.html", valido=bool(r),
                                             email=email, erro=None))
        resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax",
                        secure=cookie_seguro(), path="/")
        return resp
    confere_csrf()
    if not r:
        cx.close()
        return render_template("recuperar.html", valido=False, email=None, erro=None)
    nova = (request.form.get("nova") or "").strip()
    conf = (request.form.get("confirma") or "").strip()
    if nova != conf:
        cx.close()
        return render_template("recuperar.html", valido=True, email=r["email"],
                               erro="As duas senhas não são iguais.")
    ok, erro = acesso.usar_recuperacao(cx, token, nova, ip_cliente())
    cx.commit(); cx.close()
    if not ok:
        return render_template("recuperar.html", valido=True, email=r["email"], erro=erro)
    # Não emite sessão: a pessoa entra com a senha que acabou de escolher, e aí
    # o segundo fator (se houver) acontece como em qualquer outra entrada.
    return redirect(url_for("entrar", trocada=1))


@app.post("/sair")
@exige_login
def sair():
    confere_csrf()
    cx = conectar()
    cx.execute("UPDATE sessoes SET revogada_em=? WHERE id=?", (agora(), request.usuario["id"]))
    registrar(cx, request.usuario["usuario_id"], "logout")
    cx.commit(); cx.close()
    resp = redirect(url_for("entrar"))
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.route("/primeiro-acesso", methods=["GET", "POST"])
@exige_login
def primeiro_acesso():
    u = request.usuario
    # A rota so existe enquanto a senha provisoria vale. Aberta para sessao ja
    # regularizada, ela vira "trocar senha sem provar a antiga": quem pegasse uma
    # sessao emprestada trocaria a senha e ficaria com a conta. exige_login
    # apenas REDIRECIONA para ca, nunca fecha a porta.
    if u["senha_trocada_em"]:
        abort(404)
    if request.method == "GET":
        return render_template("primeiro_acesso.html", u=u)
    confere_csrf()
    # Apara dos dois lados, como o login apara — ver a nota em `entrar_post`.
    nova = (request.form.get("nova") or "").strip()
    conf = (request.form.get("confirma") or "").strip()
    if nova != conf:
        return render_template("primeiro_acesso.html", u=u, erro="As duas senhas não são iguais.")
    critica = seg.criticar_senha(nova, u["email"])
    if critica:
        return render_template("primeiro_acesso.html", u=u, erro=critica)
    h, sal = seg.hash_senha(nova)
    cx = conectar()
    # DESTRAVA JUNTO. Definir senha nova e uma prova de posse da conta tao boa
    # quanto entrar: deixar um bloqueio de tentativas antigas em pe faz a senha
    # recem-definida ser recusada por causa de erros contra a senha ANTIGA — e a
    # tela diz "conta bloqueada" para quem acabou de fazer tudo certo.
    cx.execute("""UPDATE usuarios SET senha_hash=?, senha_sal=?, senha_trocada_em=?,
                  falhas_seq=0, bloqueado_ate=NULL WHERE id=?""",
               (h, sal, agora(), u["usuario_id"]))
    # troca de senha derruba TODAS as sessoes, inclusive a de quem esta trocando:
    # se a senha foi trocada por suspeita, deixar a sessao do invasor viva anula o gesto
    cx.execute("UPDATE sessoes SET revogada_em=? WHERE usuario_id=?", (agora(), u["usuario_id"]))
    registrar(cx, u["usuario_id"], "troca_senha")
    cx.commit(); cx.close()
    # A TELA PRECISA DIZER O QUE ACONTECEU. Voltar muda para o acesso, depois de
    # derrubar a sessao de proposito, faz a pessoa tentar de novo a senha
    # PROVISORIA — que acabou de deixar de valer. Foi assim que uma conta bateu
    # no limite de tentativas logo apos a troca dar certo.
    resp = redirect(url_for("entrar", trocada=1))
    resp.delete_cookie(COOKIE, path="/")
    return resp


# --------------------------------------------------------------- painel
def _blocos_velhos(cx, ids):
    """Bloco mais antigo e quantas linhas vieram do poco, por snapshot.

    Duas perguntas de uma consulta so porque as duas sao a MESMA pergunta vista
    de angulos diferentes: "de quando e o retrato de verdade".
    """
    if not ids:
        return {}
    marc = ",".join("?" * len(ids))
    # `sem_medida` conta o que MIN() nao ve: linha sem detalhe lido tem medido_em
    # NULL, e NULL nao entra no MIN. Sem esta contagem, a coleta em que TUDO falhou
    # — poco vazio, sessao caida no terceiro processo — pintava VERDE "coletado
    # hoje", porque a lista veio inteira e a contagem de processos nao caiu.
    return {r["snapshot_id"]: {"mais_velho": r["mais_velho"], "do_poco": r["do_poco"],
                               "sem_medida": r["sem_medida"]}
            for r in cx.execute(
                f"""SELECT snapshot_id, MIN(medido_em) AS mais_velho,
                           SUM(COALESCE(servido_do_poco,0)) AS do_poco,
                           SUM(medido_em IS NULL) AS sem_medida
                    FROM processo WHERE snapshot_id IN ({marc})
                    GROUP BY snapshot_id""", ids)}


def estado_coleta(unidades=None, usuario_id=None):
    """Idade do snapshot POR UNIDADE. E o que impede o painel de mostrar dado de
    tres dias atras com cara de hoje — a pergunta que o usuario nao faz sozinho.

    `unidades` recorta o resultado. Sem recorte, o semaforo e o contador de
    snapshots retidos falariam de mesas que aquele usuario nem enxerga: alarme
    sobre o invisivel e alarme que se aprende a ignorar.
    """
    cx = conectar()
    # `is not None`, e NÃO `if unidades`. Os dois casos são diferentes:
    #   None = sem recorte, a visão do sistema (tela de saúde, tela de acesso);
    #   []   = esta pessoa não alcança unidade nenhuma.
    # Tratados como iguais, uma conta sem vínculo — a de admin, por exemplo —
    # recebia a lista INTEIRA de unidades na faixa, enquanto o painel dela
    # mostrava zero processos. Era a mesma faixa de seis unidades aparecendo para
    # todo mundo, inclusive para quem não enxerga nenhuma delas.
    if unidades is not None:
        if not unidades:
            cx.close()
            return {"unidades": [], "candidatos": 0, "compartilhadas": 0,
                    "multi_instancia": False, "pior": "vazio"}
        marc = ",".join("?" * len(unidades))
        # A MESMA regra do painel e dos relatórios: a minha coleta vence, e onde
        # não tenho a minha vale a compartilhada. Se a faixa contasse por unidade,
        # ela diria um número e a lista mostraria outro — na mesma tela.
        escolhidos = snapshots_de(cx, usuario_id, unidades)
        ids = [sid for sid, _ in escolhidos.values()] or [-1]
        m2 = ",".join("?" * len(ids))
        linhas = cx.execute(f"""SELECT unidade, coletado_em, unicos, suspeito, motivo,
                                       dono_usuario_id, id,
                                       COALESCE(instancia,'SEI-SESAB') AS instancia
                                FROM snapshot WHERE id IN ({m2})
                                ORDER BY unidade""", ids).fetchall()
        blocos = _blocos_velhos(cx, ids)
        # OS RETIDOS SÃO OS DELA. Sem o filtro de dono, a pessoa via "N
        # snapshot(s) retido(s) para conferência" contando candidatos da coleta
        # de OUTRA pessoa nas mesmas unidades — algo que ela não pode conferir
        # nem resolver, e que some da tela quando a outra resolver. Alarme sobre
        # o que não é meu é alarme que se aprende a ignorar.
        pend = cx.execute(f"""SELECT COUNT(*) FROM snapshot
                              WHERE estado='candidato' AND unidade IN ({marc})
                                AND (dono_usuario_id IS NULL OR dono_usuario_id = ?)""",
                          list(unidades) + [usuario_id]).fetchone()[0]
    else:
        linhas = cx.execute("""SELECT unidade, coletado_em, unicos, suspeito, motivo,
                                      dono_usuario_id, id,
                                      COALESCE(instancia,'SEI-SESAB') AS instancia
                               FROM snapshot WHERE estado='corrente' ORDER BY unidade""").fetchall()
        pend = cx.execute("SELECT COUNT(*) FROM snapshot WHERE estado='candidato'").fetchone()[0]
        blocos = _blocos_velhos(cx, [l["id"] for l in linhas])
    cx.close()
    saida = []
    for l in linhas:
        # O PIOR dos dois. A lista pode ser de hoje e metade dos detalhes de
        # anteontem: anunciar verde por causa do carimbo da lista seria prometer
        # um frescor que a maioria das linhas nao tem.
        b = blocos.get(l["id"]) or {}
        marco = min(x for x in (l["coletado_em"], b.get("mais_velho")) if x)
        cor, texto = janelas.idade(marco)
        if b.get("do_poco"):
            texto += f" · {b['do_poco']} linha(s) com detalhe de leitura anterior"
        # NUNCA VERDE quando ha linha sem detalhe. A cor e o que se olha antes de
        # decidir se o dado serve; um snapshot cheio de linhas que ninguem
        # conseguiu ler nao pode anunciar frescor.
        if b.get("sem_medida"):
            cor = "vermelho" if cor == "verde" else cor
            texto += f" · {b['sem_medida']} linha(s) SEM detalhe lido nesta coleta"
        # `minha` decide o que a tela diz sobre a PROCEDÊNCIA do número. "625
        # coletados por você às 7h30" e "625 de uma coleta compartilhada de
        # anteontem" levam a decisões diferentes, e apareciam idênticos.
        minha = usuario_id is not None and l["dono_usuario_id"] == usuario_id
        saida.append({"unidade": l["unidade"], "curta": l["unidade"].split("/")[-1],
                      "cor": cor, "texto": texto, "processos": l["unicos"],
                      "coletado_em": l["coletado_em"], "minha": minha,
                      # DE QUAL INSTALAÇÃO. A sigla curta ("GABINETE") não
                      # distingue SESAB de FESF, e a faixa mostra justamente a
                      # sigla curta: sem isto, duas mesas homônimas de órgãos
                      # diferentes aparecem como se fossem a mesma.
                      "instancia": l["instancia"],
                      "rotulo": perfil_sei.rotulo(l["instancia"]),
                      "medido_ate": marco, "do_poco": b.get("do_poco") or 0,
                      "suspeito": bool(l["suspeito"]), "motivo": l["motivo"]})
    return {"unidades": saida, "candidatos": pend,
            # O rótulo da instalação só aparece na tela quando há MAIS DE UMA:
            # carimbar "SESAB" em toda linha de quem só tem SESAB é ruído que
            # ensina a não ler o carimbo — e é justamente ele que precisa ser
            # lido no dia em que a segunda instalação chegar.
            "multi_instancia": len({u["instancia"] for u in saida}) > 1,
            # Quantas destas unidades ainda dependem da coleta de outro. É o que a
            # tela usa para dizer "configure a sua" com um motivo em vez de um
            # pedido solto.
            "compartilhadas": sum(1 for u in saida if not u["minha"]),
            "pior": ("vermelho" if any(u["cor"] == "vermelho" for u in saida)
                     else "amarelo" if any(u["cor"] == "amarelo" for u in saida)
                     else "verde" if saida else "vazio")}


class PorUnidade(dict):
    """{(instancia, unidade): (snapshot_id, dono)} que ainda se deixa ler por nome.

    A CHAVE PASSOU A SER O PAR. Ela era só o nome da unidade, e o laço que monta
    este dicionário guardava a primeira linha vista e descartava as demais: com
    vínculo em `FESF/GABINETE` e `SESAB/GABINETE`, uma das duas sumia da carteira
    sem alerta nenhum. A chave protegia contra misturar (o SQL já filtra por
    instalação); o dicionário, não.

    Ler por nome continua funcionando enquanto o nome pertencer a UMA instalação
    só — que é o caso de todos os usos de hoje. Nome ambíguo levanta KeyError
    dizendo as instalações em que ele existe, em vez de devolver a errada.
    """

    def _par(self, nome):
        pares = [k for k in self if k[1] == nome]
        if len(pares) == 1:
            return pares[0]
        if not pares:
            return None
        raise KeyError(f"{nome!r} existe em mais de uma instalação "
                       f"({', '.join(sorted(i for i, _ in pares))}): "
                       f"leia pelo par (instancia, unidade)")

    def __missing__(self, chave):
        if isinstance(chave, str):
            p = self._par(chave)
            if p is not None:
                return dict.__getitem__(self, p)
        raise KeyError(chave)

    def __contains__(self, chave):
        if dict.__contains__(self, chave):
            return True
        return isinstance(chave, str) and self._par(chave) is not None

    def get(self, chave, padrao=None):
        try:
            return self[chave]
        except KeyError:
            return padrao


def snapshots_de(cx, usuario_id, unidades):
    """Os ids de snapshot que ESTA pessoa pode ler, um por (instalação, unidade).

    A regra é uma só, e mora aqui: **a minha coleta vence; onde eu não tenho a
    minha, vale a compartilhada da unidade**.

    "Compartilhada" é o snapshot sem dono — o da estação de bootstrap, que é como
    toda instalação começa, antes de qualquer pessoa configurar a própria coleta.
    Sem essa ponte, a manhã seguinte à mudança seria de telas vazias para todo
    mundo; com ela, cada pessoa migra para o próprio dado no dia em que roda a
    primeira coleta dela, sem ninguém coordenar nada.

    Devolve {unidade: (snapshot_id, dono_usuario_id)} — o dono vai junto porque a
    tela precisa dizer QUAL das duas o número veio.
    """
    if not unidades:
        return {}
    marc = ",".join("?" * len(unidades))
    # A INSTALAÇÃO ENTRA NO PAREAMENTO. Nome de unidade não é único entre
    # instalações — "GABINETE" existe na SESAB e na FESF —, e `usuario_unidade`
    # guarda `instancia` desde a migração das duas. Sem ler essa coluna, quem tem
    # vínculo só na FESF recebia o snapshot compartilhado da SESAB com o mesmo
    # nome: processos de uma instalação onde a pessoa não tem vínculo nenhum.
    #
    # `JOIN` em vez de `IN`: é o vínculo que decide, e ele é (usuário, instância,
    # unidade). A lista de nomes continua chegando aqui como lista de nomes — o
    # recorte por instalação é resolvido no SQL, e nenhuma assinatura muda.
    # O VÍNCULO SÓ EXISTE QUANDO HÁ PESSOA. Com `usuario_id=None` — a visão do
    # sistema, usada na tela de acesso e por ferramenta de linha de comando — não
    # há a quem pedir vínculo, e o recorte é o que veio na chamada. Note que esse
    # caso já só enxerga snapshot SEM dono: `dono = NULL` nunca é verdadeiro.
    if usuario_id is None:
        linhas = cx.execute(f"""
            SELECT id, unidade, dono_usuario_id, coletado_em,
                   COALESCE(instancia,'SEI-SESAB') AS instancia FROM snapshot
            WHERE estado='corrente' AND unidade IN ({marc})
              AND dono_usuario_id IS NULL
            ORDER BY unidade, coletado_em DESC, id DESC""",
            list(unidades)).fetchall()
    else:
        linhas = cx.execute(f"""
            SELECT s.id, s.unidade, s.dono_usuario_id, s.coletado_em,
                   COALESCE(s.instancia,'SEI-SESAB') AS instancia
            FROM snapshot s
            JOIN usuario_unidade uu
              ON uu.unidade = s.unidade
             AND uu.instancia = COALESCE(s.instancia, 'SEI-SESAB')
             AND uu.usuario_id = ?
            WHERE s.estado='corrente' AND s.unidade IN ({marc})
              AND (s.dono_usuario_id IS NULL OR s.dono_usuario_id = ?)
            ORDER BY s.unidade,
                     -- a MINHA primeiro; entre iguais, a mais recente
                     CASE WHEN s.dono_usuario_id IS NULL THEN 1 ELSE 0 END,
                     s.coletado_em DESC, s.id DESC""",
            [usuario_id] + list(unidades) + [usuario_id]).fetchall()
    fora = PorUnidade()
    for l in linhas:
        chave = (l["instancia"], l["unidade"])
        # `dict.__contains__` direto: o `in` da classe resolve nome ambíguo e
        # levantaria KeyError no meio do laço que está justamente montando o
        # dicionário. Aqui a pergunta é literal — "esta chave já está lá?".
        if not dict.__contains__(fora, chave):
            dict.__setitem__(fora, chave, (l["id"], l["dono_usuario_id"]))
    return fora



def carteira(unidades, usuario_id=None):
    """Monta os registros no MESMO formato que o painel ja consome.

    A fronteira e aplicada AQUI, no servidor. Filtrar no navegador seria
    decorativo — o dado ja teria saido.

    E ela tem DUAS camadas desde que cada pessoa coleta a própria carteira:
    a unidade (o que eu posso alcançar) e o DONO da coleta (de quem é este dado).
    `snapshots_de()` resolve as duas de uma vez e devolve um snapshot por unidade;
    daqui para baixo tudo parte desses ids.

    Filtrar por unidade, como antes, traria as DUAS coletas correntes de uma
    unidade onde eu tenho a minha e existe a compartilhada — e a dedup escolheria
    uma pelo id, critério que não significa nada.
    """
    if not unidades:
        return []
    cx = conectar()
    escolhidos = snapshots_de(cx, usuario_id, unidades)
    ids = [sid for sid, _ in escolhidos.values()]
    if not ids:
        cx.close()
        return []
    marc = ",".join("?" * len(ids))
    unidades = ids          # daqui para baixo o recorte é por snapshot, não por unidade
    # ORDER BY nao e enfeite: um processo aberto em duas mesas aparece uma vez por
    # snapshot, e sem ordem o vencedor da dedup era o alfabeticamente menor — que
    # pode ser o snapshot mais VELHO. O dado exibido tem de vir do mais fresco.
    proc = cx.execute(f"""SELECT p.*, s.unidade AS snap_unidade, s.coletado_em,
                                 COALESCE(s.instancia,'SEI-SESAB') AS instancia
                          FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
                          WHERE s.id IN ({marc})
                          ORDER BY s.coletado_em DESC, s.id DESC""",
                      unidades).fetchall()
    textos = {(r["snapshot_id"], r["id_sei"]): r for r in cx.execute(
        f"""SELECT t.* FROM processo_texto t
            WHERE t.snapshot_id IN ({marc})""", unidades)}
    mesas = {}
    for r in cx.execute(f"""SELECT m.* FROM processo_mesa m
                            WHERE m.snapshot_id IN ({marc})""", unidades):
        mesas.setdefault((r["snapshot_id"], r["id_sei"]), []).append(
            {"unidade": r["mesa"], "atribuido": r["atribuido"]})
    # Junta pela MESMA fronteira das outras três consultas. `SELECT * FROM resumo`
    # trazia a tabela inteira para a memória de cada requisição, incluindo texto
    # de unidade que este usuário não pode ver. Hoje o dicionário só é consultado
    # por processo visível, então nada vaza — mas a proteção fica dependendo de um
    # detalhe do laço lá embaixo, e não da consulta. Uma consulta que carrega o que
    # não pode ser mostrado é um vazamento esperando por um bug.
    # A CHAVE É (INSTALAÇÃO, ID), a MESMA do laço lá embaixo. Quando a dedup do
    # laço passou a ser a tupla (07/09/2026), este dicionário continuou indexado
    # só por `id_sei`: `resumos.get((instancia, id))` devolvia None em 100% das
    # linhas e NENHUM dos 927 resumos aparecia no painel — sem erro, sem log, com
    # `/admin` anunciando "927 com resumo" na mesma hora. Chave montada aqui tem
    # de ser lida com a mesma forma lá; por isso as duas vêm do mesmo par.
    resumos = {(r["instancia"], r["id_sei"]): r for r in cx.execute(
        f"""SELECT DISTINCT r.* FROM resumo r
            JOIN processo p ON p.id_sei = r.id_sei
            JOIN snapshot s2 ON s2.id = p.snapshot_id
                            AND COALESCE(s2.instancia,'SEI-SESAB') = r.instancia
            WHERE p.snapshot_id IN ({marc})""", unidades)}
    cx.close()

    saida, visto = [], {}
    for p in proc:
        # A CHAVE DA DEDUP É (INSTALAÇÃO, ID). `id_sei` sozinho é único DENTRO de
        # uma instalação; entre duas, nada garante isso. Com a chave antiga, um
        # processo da FESF com o mesmo id de um da SESAB desapareceria da tela e
        # ainda herdaria as mesas do outro órgão na união abaixo.
        chave = (p["instancia"], p["id_sei"])
        t = textos.get((p["snapshot_id"], p["id_sei"]))
        ac = json.loads(t["acompanhamento"]) if t and t["acompanhamento"] else []
        r = resumos.get(chave)
        d = {
            "id": p["id_sei"], "protocolo": p["protocolo"], "tipo_processo": p["tipo_processo"],
            # DE QUAL INSTALAÇÃO É ESTA LINHA. Vai no registro — e não só na
            # faixa — porque quem tem carteira nas duas precisa saber, olhando a
            # linha, em qual SEI aquele processo está.
            "instancia": p["instancia"],
            "instancia_rotulo": perfil_sei.rotulo(p["instancia"]),
            "especificacao": t["especificacao"] if t else None,
            "anotacao": t["anotacao"] if t else None,
            "anotacao_autor": t["anotacao_autor"] if t else None,
            "anotacao_data": t["anotacao_data"] if t else None,
            "interessados": json.loads(t["interessados"]) if t and t["interessados"] else [],
            "acompanhamento": ac, "acomp_grupos": [a.get("grupo") for a in ac if a.get("grupo")],
            "visualizado": bool(p["visualizado"]), "marcador": p["marcador"],
            "marcador_cor": p["marcador_cor"], "retorno": p["retorno"],
            "doc_incluido": bool(p["doc_incluido"]), "urgente": bool(p["urgente"]),
            "sobrestado": bool(p["sobrestado"]), "sem_historico": bool(p["sem_historico"]),
            "truncado": bool(p["truncado"]), "mesas_divergem": bool(p["mesas_divergem"]),
            "atribuido_login": p["atribuido_login"], "atribuido_nome": p["atribuido_nome"],
            "mesa_coleta": p["mesa_coleta"],
            "mesas_coleta": json.loads(p["mesas_coleta"]) if p["mesas_coleta"] else [],
            "mesas": mesas.get((p["snapshot_id"], p["id_sei"]), []),
            "mesas_fonte": p["mesas_fonte"], "marco_unidade": p["marco_unidade"],
            "autuacao": p["autuacao"], "recebimento": p["recebimento"],
            "recebimento_por": p["recebimento_por"], "envio": p["envio"],
            "unidade_envio": p["unidade_envio"], "gerador_unidade": p["gerador_unidade"],
            "gerador_usuario": p["gerador_usuario"], "nivel_acesso": p["nivel_acesso"],
            "hipotese_legal": p["hipotese_legal"], "origem": p["origem"],
            "documentos": p["documentos"], "movimentos": p["movimentos"],
            "emails_enviados": p["emails_enviados"], "assinatura_externa": p["assinatura_externa"],
            "assuntos": json.loads(p["assuntos"]) if p["assuntos"] else [],
            "anexados": json.loads(p["anexados"]) if p["anexados"] else [],
            "ultimo_movimento": json.loads(p["ultimo_movimento"]) if p["ultimo_movimento"] else None,
            # A REGUA DESTA LINHA, e a procedencia dela. Sem estes campos o
            # painel media uma data velha com o relogio de hoje.
            "medido_em": p["medido_em"] or p["coletado_em"],
            "servido_do_poco": bool(p["servido_do_poco"]),
            "mesa_indeterminada": bool(p["mesa_indeterminada"]),
            "mov_parcial": bool(p["mov_parcial"]),
            "movimentos_exato": p["movimentos_exato"],
            # acompanhamento vazio POR NAO TER SIDO LIDO e diferente de vazio por
            # nao existir. Sem esta marca, a tela afirma a segunda coisa.
            "acomp_lido": bool(p["acomp_lido"]),
            # O ROTULO DO ICONE. Ele existe para responder um experimento aberto —
            # "novo" e novo para a MESA ou para a PESSOA? —, e estava sendo
            # acumulado onde ninguem ia olhar: coletado, ingerido, gravado, e lido
            # por nada. Na tela, quem opera pode ler o que o SEI escreveu.
            "doc_incluido_rotulo": p["doc_incluido_rotulo"],
            "resumo_curto": r["curto"] if r else None,
            "resumo_longo": r["longo"] if r else None,
            "resumo_em": r["descrito_em"] if r else None,
        }
        # Um processo aberto em duas mesas da conta vem duas vezes (uma por
        # snapshot). Deduplicar unindo as mesas de coleta, senao a mesma linha
        # aparece repetida e todas as contagens do painel inflam.
        if chave in visto:
            alvo = visto[chave]
            alvo["mesas_coleta"] = sorted(set(alvo["mesas_coleta"]) | set(d["mesas_coleta"]))
            continue
        visto[chave] = d
        saida.append(d)
    return saida



def _marco_coleta(coleta, linhas=None):
    """Data do retrato MAIS ATRASADO, em DD/MM/AAAA HH:MM — o formato do painel.

    Mais velha, e não mais nova: quem soma seis unidades num total só tem de
    medir todas contra o retrato mais atrasado, senão o número mistura momentos
    diferentes e ninguém consegue defendê-lo.

    Com o poço, "mais atrasado" deixou de ser só a hora da coleta: uma carteira
    pode ter lista de hoje e detalhe de três dias atrás. A mesma razão que fez
    esta função usar `min()` obriga a incluir o bloco mais velho — senão o
    cabeçalho anuncia um frescor que metade das linhas não tem.
    """
    if not coleta["unidades"]:
        return ""
    iso = min(c["coletado_em"] for c in coleta["unidades"])
    medidos = [d["medido_em"] for d in (linhas or []) if d.get("medido_em")]
    if medidos:
        iso = min(iso, min(medidos))
    try:
        return janelas.com_fuso(iso).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return ""


def _falhas_do_usuario(cx, unidades):
    """Mesas que falharam na última execução E são desta pessoa.

    Vive fora das rotas porque agora tem dois leitores — a tela e o arquivo
    exportado — e o aviso "COLETA INCOMPLETA" que aparece num tem de aparecer no
    outro. Já foi código morto uma vez (fixo em `[]`, com o dado existindo no
    banco); duas cópias da consulta seriam o caminho de volta.
    """
    return [r["unidade"] for r in cx.execute(
        """SELECT DISTINCT unidade FROM alerta WHERE tipo='mesa_falhou'
           AND reconhecido_em IS NULL AND unidade IS NOT NULL""")
        if r["unidade"] in unidades]


@app.get("/")
@exige_login
def painel():
    u = request.usuario
    unidades = unidades_do(u["usuario_id"])
    dados = carteira(unidades, u["usuario_id"])
    # UMA VEZ SO. A mesma chamada estava aqui (para carimbar a auditoria) e vinte
    # linhas abaixo (para a faixa do painel): duas passadas por `snapshots_de` e
    # pela tabela `snapshot` a cada abertura, pelo mesmo numero. E o estado da
    # coleta e recortado pelas unidades do usuario: o semaforo de um servidor da
    # CESS nao pode ficar vermelho por causa de uma mesa que ele nem ve.
    coleta = estado_coleta(unidades, u["usuario_id"])
    cx = conectar()
    registrar(cx, u["usuario_id"], "ver_carteira",
              alvo=f"snapshots={','.join(str(c['coletado_em'])[:10] for c in coleta['unidades'])}"
                   f" n={len(dados)}",
              unidade=";".join(unidades) or None,
              ip=ip_cliente())
    # Mesas que falharam na ultima execucao E sao do usuario. Estava fixo em []:
    # o aviso "COLETA INCOMPLETA" do painel era codigo morto, e o dado existia.
    falhas = _falhas_do_usuario(cx, unidades)
    cx.commit(); cx.close()
    # O painel avisa quem ainda não configurou a própria coleta. Sem isso, a
    # pessoa vê a carteira que a coleta de OUTRO trouxe e conclui que já está
    # tudo funcionando para ela — e descobre que não estava quando precisar.
    import configuracao as cfgmod
    cx2 = conectar()
    diag = cfgmod.diagnostico(cx2, u["usuario_id"])
    cx2.close()
    resp = make_response(render_template(
        "painel.html", dados=dados, unidades=unidades, coleta=coleta, u=u,
        # Qual porta da lateral fica marcada. As telas de serviço passam isto
        # como `pagina` no `{% with %}` do include; o painel não passa por
        # include nenhum, então vai explícito.
        pagina_atual="painel",
        nao_configurado=not diag["completa"],
        mesas=[c["unidade"] for c in coleta["unidades"]],
        # A idade exibida e a do snapshot MAIS VELHO entre os do usuario, comparada
        # por DATA. Comparar o texto ordenava por alfabeto: "coletado hoje" vencia
        # "3 dias úteis atrás", e o pior caso — o unico que importa — nunca aparecia.
        #
        # DATA, não frase. O painel usa `COLETA_EM` como RÉGUA: é contra ela que
        # todos os "dias na unidade" são medidos. Mandar "último dia útil (18/08
        # 07:45)" fazia a expressão de data não casar e a régua cair no relógio
        # sem avisar — o painel voltava a envelhecer sozinho, que é exatamente o
        # defeito que a régua existe para impedir. A frase legível continua
        # existindo, ao lado, em `coleta_frase`.
        coleta_em=_marco_coleta(coleta, dados),
        # Pela REGUA (medido_ate), nao pela hora da coleta. Com as seis unidades
        # coletadas no mesmo instante, o min() por coletado_em desempatava pela
        # ordem e devolvia a unidade sem poco — descartando justamente o texto que
        # carregava o aviso. O cabecalho anunciava "54h" ao lado de "ha 5 dias".
        coleta_frase=(min(coleta["unidades"],
                          key=lambda c: c.get("medido_ate") or c["coletado_em"])["texto"]
                      if coleta["unidades"] else "sem coleta"),
        falhas=falhas))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax", secure=cookie_seguro(), path="/")
    return resp


def _dia_iso(marco):
    """A data da coleta em AAAA-MM-DD, a partir do 'DD/MM/AAAA HH:MM' da régua.

    Sai da RÉGUA e não do banco de propósito: o nome do arquivo tem de dizer a
    mesma data que o arquivo carrega dentro. Derivar as duas de fontes diferentes
    é como se cria a divergência que se descobre na reunião.
    """
    try:
        d, m, a = marco[:10].split("/")
        return f"{a}-{m}-{d}"
    except (AttributeError, ValueError):
        # Conta sem unidade nenhuma: não há coleta, e o nome do arquivo diz isso
        # em vez de carimbar a data de hoje sobre uma carteira vazia.
        return "sem-coleta"


# Teto do estado que volta embutido no arquivo. O recorte do painel cabe em
# poucas centenas de caracteres; o que passa disso não é filtro, é alguém
# testando o que a rota aceita — e o que ela aceita ela devolve dentro de um HTML
# que vai circular. Cortar é mais honesto que rejeitar: o arquivo sai igual, só
# sem o recorte.
LIMITE_ESTADO = 2000


@app.get("/painel.html")
@exige_login
def painel_exportado():
    """O painel como ARQUIVO: abre sem servidor, sem rede e sem login.

    POR QUE ISTO EXISTE
    -------------------
    A carteira é discutida com quem não tem conta aqui — chefia, auditoria, a
    outra secretaria — e o que circulava era `.xlsx`: números certos, tela
    nenhuma. Perde-se o agrupamento, a gaveta de detalhe, a triagem por etapa e,
    sobretudo, a leitura visual do que está parado. Isto entrega a TELA.

    O QUE ELE CARREGA JUNTO
    -----------------------
    Nada aqui é o retrato de um sistema anônimo: o arquivo diz de quando é o
    dado, de quais unidades, quantos processos, quem exportou e quando — e avisa
    que não se atualiza. É a mesma folha de rosto do `.xlsx` de relatório
    (`relatorios.para_xlsx`), pelo mesmo motivo: número sem procedência não se
    defende, e a cópia sobrevive à conversa em que foi mostrada.

    A RÉGUA VAI JUNTO E NÃO SE MEXE. `COLETA_EM` continua sendo a data da COLETA.
    Fosse o relógio de quem abre, a cópia envelheceria sozinha e mostraria "94
    dias na unidade" para um processo que tinha 73 no dia em que saiu — número
    que ninguém consegue reproduzir nem defender.

    A FRONTEIRA É A MESMA DE `/`: `unidades_do` + `carteira`. O arquivo é a
    carteira de QUEM PEDIU. Filtrar no navegador seria entregar o dado dos outros
    junto e pedir para o JavaScript ter vergonha.
    """
    u = request.usuario
    unidades = unidades_do(u["usuario_id"])
    dados = carteira(unidades, u["usuario_id"])
    coleta = estado_coleta(unidades, u["usuario_id"])
    coleta_em = _marco_coleta(coleta, dados)
    gerado = datetime.now(TZ)
    cx = conectar()
    # Registrado com a CONTAGEM e com a data do DADO, como a exportação de
    # relatório. Depois que o arquivo circula por e-mail, é este par que responde
    # "de onde veio esse HTML que está rodando na reunião?".
    registrar(cx, u["usuario_id"], "exportar_painel",
              alvo=f"{len(dados)} processos · dado de {coleta_em or 'sem coleta'}",
              unidade=";".join(unidades) or None, ip=ip_cliente())
    falhas = _falhas_do_usuario(cx, unidades)
    cx.commit(); cx.close()
    corpo = render_template(
        "painel_solto.html", dados=dados, unidades=unidades, coleta=coleta, u=u,
        mesas=[c["unidade"] for c in coleta["unidades"]],
        coleta_em=coleta_em,
        coleta_frase=(min(coleta["unidades"],
                          key=lambda c: c.get("medido_ate") or c["coletado_em"])["texto"]
                      if coleta["unidades"] else "sem coleta"),
        falhas=falhas,
        exportado_em=f"{gerado:%d/%m/%Y %H:%M}",
        # O RECORTE DA TELA, de volta. O painel guarda filtros e agrupamento no
        # hash, que o navegador não manda ao servidor — por isso o botão os
        # converte em query string. Aqui a string volta para dentro do arquivo,
        # que a reaplica na abertura: sem isso, exportar "meus parados +90d"
        # entregaria a carteira inteira, sem erro e sem ninguém notar.
        estado_url=request.query_string.decode("utf-8", "replace")[:LIMITE_ESTADO])
    resp = make_response(corpo)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # AS DUAS DATAS NO NOME. Sem a do dado, duas exportações do mesmo dia sobre
    # coletas diferentes ficam indistinguíveis na pasta de downloads; sem a da
    # geração, não dá para saber qual das cópias é a mais nova.
    resp.headers["Content-Disposition"] = (
        'attachment; filename="sei360_painel'
        f'_dado-{_dia_iso(coleta_em)}_gerado-{gerado:%Y-%m-%d}.html"')
    # Carteira nominal por unidade: não fica em cache de proxy nem no disco do
    # navegador para o próximo que usar a mesma estação.
    resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------------------------------------------- configuração
def _tela_config(erro=None, teste=None, passo_forcado=None):
    """Monta a tela do assistente.

    O passo ATIVO é o pedido na URL, ou o primeiro pendente, ou nenhum (tela de
    resumo) quando está tudo pronto. Assim a pessoa cai sempre no que falta, em
    vez de ter de procurar num acordeão de cinco formulários abertos.
    """
    import configuracao as cfgmod
    cx = conectar()
    d = cfgmod.diagnostico(cx, request.usuario["usuario_id"])
    cx.close()
    pedido = passo_forcado or request.args.get("passo")
    validos = [p["chave"] for p in d["passos"]]
    ativo = pedido if pedido in validos else (None if d["completa"] else d["pendente"])
    resp = make_response(render_template(
        "configuracao.html", u=request.usuario, sistemas=cfgmod.SISTEMAS,
        erro=erro, teste=teste, ativo=ativo, passo_ativo=bool(pedido), **d))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax",
                    secure=cookie_seguro(), path="/")
    return resp


# As ações cujo `alvo` é um id de USUÁRIO. Qualquer outra que grave um id ali —
# snapshot, busca, execução — não pode aparecer na ficha de uma pessoa só porque
# o número coincide.
ACOES_SOBRE_USUARIO = ("criar_usuario", "alternar_ativo", "trocar_papel",
                       "vincular_unidade", "desvincular_unidade", "resetar_senha",
                       "excluir_usuario", "editar_usuario")


def _login_guardado(cx, usuario_id, sistema):
    """O login a que a credencial guardada está AMARRADA, ou None.

    Não é o login que a configuração mostra — é o que está dentro do AAD do
    cofre. Os dois divergirem é o defeito; esta função é como se pergunta.
    """
    r = cx.execute("SELECT login FROM credencial WHERE usuario_id=? AND sistema=?",
                   (usuario_id, sistema)).fetchone()
    return r["login"] if r else None


@app.get("/configuracao")
@exige_login
def configuracao():
    return _tela_config()


@app.post("/configuracao")
@exige_login
def configuracao_post():
    import configuracao as cfgmod
    import cofre
    confere_csrf()
    f = request.form
    passo = f.get("passo")
    uid = request.usuario["usuario_id"]
    cx = conectar()
    campos, erro = {}, None

    if passo == "sistema":
        s = f.get("sistema")
        # ESCOLHÍVEL = BUSCA OU COLETA. A recusa lia `disponivel_coleta` e
        # travava a FESF, embora a busca já rodasse nela: quem tem vínculo só na
        # FESF não passava do passo 1. O que cada instalação oferece a tela diz,
        # instância por instância, lendo do perfil.
        if s not in cfgmod.SISTEMAS or not cfgmod.SISTEMAS[s]["disponivel"]:
            erro = "Esse sistema ainda não está disponível."
        else:
            campos["sistema"] = s

    elif passo == "acesso":
        login = (f.get("sei_login") or "").strip().lower()
        senha = f.get("sei_senha") or ""
        modo = f.get("modo_coleta") or "servidor"
        c = cfgmod.ler(cx, uid)
        # Só o formato, E O FORMATO É DA INSTALAÇÃO. A regra estava escrita aqui
        # ("tem @ e ponto no domínio") porque a única instalação conhecida era a
        # SESAB; o login da FESF é `nome.sobrenome`, e esta linha recusava o
        # login CERTO mandando a pessoa consertar o que não estava quebrado.
        # Conferir se a conta EXISTE exigiria tentar autenticar — e é exatamente
        # isso que o botão "Testar acesso" faz, de propósito.
        login_ok, dica_login = perfil_sei.login_valido(c["sistema"], login)
        if not login_ok:
            erro = dica_login
        elif modo == "servidor" and not cofre.disponivel():
            erro = ("O cofre do servidor está desligado porque falta a chave mestra. "
                    "Escolha guardar no seu computador, ou peça a quem administra.")
        elif modo == "servidor" and not senha and not cofre.estado(cx, uid):
            erro = "Informe a senha do SEI, ou escolha guardá-la no seu computador."
        elif (modo == "servidor" and not senha
              and _login_guardado(cx, uid, c["sistema"]) not in (None, login)):
            # TROCAR O LOGIN EXIGE A SENHA. O AAD do cofre é
            # `usuario_id|sistema|login`: ele existe para o blob só decifrar no
            # contexto exato em que foi criado. Gravar o login novo sem reenviar
            # a senha deixaria o segredo amarrado ao login ANTIGO e a tela, a
            # trava da conta e o log mostrando o NOVO — a busca rodaria com uma
            # credencial que o sistema inteiro diz ser de outra conta. E a
            # decifragem falharia com "não há credencial guardada", que manda
            # procurar no lugar errado.
            erro = ("Você mudou o login do SEI. Informe a senha dele também — "
                    "a credencial guardada está amarrada ao login anterior e "
                    "deixaria de abrir.")
        else:
            campos["sei_login"] = login
            campos["modo_coleta"] = modo
            if modo == "servidor" and senha:
                cofre.guardar(cx, uid, c["sistema"], login, senha, ip=ip_cliente())
            if modo == "estacao":
                # Trocar para a estação APAGA o que estava guardado aqui. Manter
                # seria deixar no servidor justamente a senha que a pessoa acabou
                # de pedir para tirar dele.
                cofre.esquecer(cx, uid, ip=ip_cliente())

    elif passo == "mesas":
        modo = f.get("mesas_modo") or "todas"
        # As mesas escolhidas são recortadas pelo VÍNCULO. Sem isto, o campo do
        # formulário definia sozinho o escopo de publicação do agente — e como é
        # esse escopo que a publicação confere, a fronteira por unidade passava a
        # valer só para leitura: bastava digitar a sigla de outra unidade para
        # publicar a carteira dela.
        minhas = set(unidades_do(uid))
        escolhidas = [m for m in f.getlist("mesas") if m and m in minhas]
        pedidas = [m for m in f.getlist("mesas") if m]
        if modo == "selecionadas" and not escolhidas:
            erro = ("Escolha ao menos uma mesa das suas unidades, ou marque "
                    "“todas as mesas da conta”.")
        elif len(escolhidas) != len(pedidas):
            # Dizer o que foi descartado, e não descartar em silêncio: quem pediu
            # uma unidade que não é sua precisa saber que ela não entrou.
            erro = ("Estas unidades não estão vinculadas à sua conta e ficaram de "
                    "fora: " + ", ".join(sorted(set(pedidas) - minhas))
                    + ". Peça o vínculo à administração.")
            campos["mesas_modo"] = modo
            campos["mesas"] = escolhidas
        else:
            campos["mesas_modo"] = modo
            campos["mesas"] = escolhidas if modo == "selecionadas" else []

    elif passo == "horarios":
        cru = [x.strip() for x in (f.get("janelas") or "").replace(",", " ").split() if x.strip()]
        validos, ruins = [], []
        for h in cru:
            try:
                hh, mm = h.split(":")
                if 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59:
                    validos.append(f"{int(hh):02d}:{int(mm):02d}")
                else:
                    ruins.append(h)
            except ValueError:
                ruins.append(h)
        if ruins or not validos:
            erro = f"Horário inválido: {', '.join(ruins) or 'nenhum informado'}. Use HH:MM."
        elif len(validos) > 2:
            erro = "No máximo dois horários por dia — cada coleta são milhares de requisições."
        else:
            campos["janelas"] = sorted(set(validos))
            campos["dias"] = f.get("dias") or "uteis"

    if erro:
        cx.commit(); cx.close()
        return _tela_config(erro=erro, passo_forcado=passo)

    cfgmod.gravar(cx, uid, decidiu=passo, **campos)
    d = cfgmod.diagnostico(cx, uid)
    if d["completa"] and not d["config"]["concluida_em"]:
        cfgmod.gravar(cx, uid, concluida_em=agora())
    registrar(cx, uid, "configurar_coleta", alvo=passo)
    aplicar_agendamento(cx, uid)
    cx.commit(); cx.close()
    # Sem `passo` na URL, a tela leva sozinha ao próximo pendente — é o que faz o
    # assistente andar, em vez de devolver a pessoa ao mesmo lugar.
    return redirect(url_for("configuracao"))


def escopo_do_dono(cx, uid, cfg):
    """As unidades que este agente pode publicar. UMA definição, dois usos.

    "Todas" quer dizer todas as unidades DA PESSOA — nunca `SELECT DISTINCT
    unidade FROM snapshot`, que é todas as do banco. Era esse o buraco: o agente
    de qualquer conta nascia com escopo sobre a carteira inteira do órgão, e a
    publicação conferia exatamente esse campo.

    Recorta também o modo "selecionadas": vínculo revogado depois da configuração
    tem de encolher o escopo sozinho, sem depender de alguém reabrir a tela.
    """
    minhas = set(unidades_do(uid))
    if cfg["mesas_modo"] == "selecionadas":
        return sorted(set(cfg["mesas"] or []) & minhas)
    return sorted(minhas)


def _motivo_servidor():
    """Por que o agente lógico do modo servidor está pausado, ou None se não
    está (ver `coleta_servidor.py` para o que "estar" significa aqui).

    BUSCA E COLETA SÃO DUAS COISAS, e o navegador na imagem só resolve as duas
    desde 08/09/2026. Até essa data, o navegador (§6.0, 21/08/2026) só servia
    a BUSCA avançada; a COLETA diária dependia de a FESF ter parser provado
    (`perfil_sei.disponivel_coleta`) e de existir quem a rodasse aqui dentro.
    As duas condições passaram a valer nessa data — a primeira por medição em
    campo, a segunda por `coleta_servidor.py`.

    Continua existindo `SEI360_COLETA_SERVIDOR` como interruptor deliberado
    (nasce DESLIGADO — ver o cabeçalho daquele módulo): a busca já tinha
    decisão formal antes de existir; a coleta automática em modo servidor
    ainda não teve carga real medida, e ligar por padrão aqui repetiria o erro
    que este comentário já registrou uma vez — armar sem ter com quem cumprir.
    """
    import coleta_servidor
    if not coleta_servidor.ligado():
        return ("modo servidor: a coleta automática dentro do servidor existe, mas "
                "está desligada nesta instalação (SEI360_COLETA_SERVIDOR). A busca "
                "avançada continua funcionando; a coleta diária continua na estação, "
                "com o agente instalado, até alguém ligar essa chave.")
    pode, motivo = coleta_servidor.capacidade()
    if not pode:
        return (f"modo servidor: {motivo}. A coleta roda na estação com o agente "
                f"instalado enquanto isto não for resolvido.")
    if not coleta_servidor.vivo():
        # LIGADO, CAPAZ, E MESMO ASSIM NÃO RODANDO é defeito do servidor, não
        # da conta: o executor só sobe no processo que venceu a eleição do
        # atendente de busca (mesmo semáforo de memória — ver o cabeçalho de
        # `coleta_servidor.py`). Dizer isso em vez de "agendamento desarmado"
        # evita que a pessoa procure na própria configuração o que não é dela.
        return ("modo servidor: o executor de coleta deveria estar rodando neste "
                "container e não está — defeito do servidor, não da sua conta. "
                "Reinicie o serviço e, se persistir, relate.")
    return None


def aplicar_agendamento(cx, uid):
    """A configuração da pessoa vira o agendamento do agente dela.

    Sem isto o assistente seria um formulário bonito que não muda o comportamento
    de nada. No modo `servidor` o agente é lógico — não há estação pareada —, mas
    o agendamento é o mesmo objeto que a varredura de janelas lê.
    """
    import configuracao as cfgmod
    c = cfgmod.ler(cx, uid)
    ag = cfgmod.agente_do(cx, uid)
    unidades = escopo_do_dono(cx, uid, c)
    if not ag and c["modo_coleta"] == "servidor":
        u = cx.execute("SELECT nome,email FROM usuarios WHERE id=?", (uid,)).fetchone()
        # NASCE DESARMADO, e o motivo fica escrito na própria linha. O modo
        # "servidor" não tem executor: não há navegador nem Playwright na imagem,
        # e mudar isso mudaria a arquitetura de acesso, não o Dockerfile. Armado,
        # este agente produzia uma janela perdida por dia com o texto "estação
        # desligada, sem rede ou tarefa não agendada" — culpando a pessoa por uma
        # coleta que o sistema nunca teve como fazer. Foram 18 janelas perdidas e
        # 27 coletas travadas assim.
        cx.execute("""INSERT INTO agentes(nome_estacao,dono_usuario_id,unidades_esperadas,ativo,
                      criado_em,credencial_titular,credencial_login_mascarado,pausado_motivo)
                      VALUES(?,?,?,1,?,?,?,?)""",
                   ("SERVIDOR/" + (u["email"] or "").split("@")[0], uid,
                    json.dumps(unidades, ensure_ascii=False), agora(),
                    u["nome"], mascarar(c["sei_login"]), _motivo_servidor()))
        ag = cfgmod.agente_do(cx, uid)
    if not ag:
        return
    cx.execute("UPDATE agentes SET unidades_esperadas=?, credencial_login_mascarado=? WHERE id=?",
               (json.dumps(unidades, ensure_ascii=False), mascarar(c["sei_login"]), ag["id"]))
    # AGENTE LÓGICO JÁ CRIADO É RE-AVALIADO. Sem isto, quem configurou antes de a
    # imagem ganhar navegador ficaria pausado para sempre por um motivo que deixou
    # de ser verdade — e o texto da pausa continuaria afirmando que não há executor.
    if ag["nome_estacao"].startswith("SERVIDOR/"):
        novo = _motivo_servidor()
        if novo != ag["pausado_motivo"]:
            cx.execute("UPDATE agentes SET pausado_motivo=? WHERE id=?", (novo, ag["id"]))
            ag = cfgmod.agente_do(cx, uid)
    # O agendamento só nasce ARMADO se houver quem execute. `pausado_motivo`
    # preenchido é a marca do agente lógico; agendar horário para ele seria
    # marcar reunião com quem não existe e depois cobrar a falta.
    armado = 0 if ag["pausado_motivo"] else 1
    cx.execute("""INSERT INTO agendamento(agente_id,janelas,dias,ativo,motivo_inativo)
                  VALUES(?,?,?,?,?)
                  ON CONFLICT(agente_id) DO UPDATE SET
                    janelas=excluded.janelas, dias=excluded.dias,
                    ativo=excluded.ativo, motivo_inativo=excluded.motivo_inativo""",
               (ag["id"], json.dumps(c["janelas"]), c["dias"], armado,
                None if armado else ag["pausado_motivo"]))


@app.post("/configuracao/testar")
@exige_login
def configuracao_testar():
    """Entra no SEI de verdade, com a credencial guardada, e conta o que houve.

    É o que separa "configurei e torço" de "configurei e vi funcionar". Sem este
    botão, a primeira notícia de senha errada chega às 7h31 do dia seguinte, com
    a janela já perdida.
    """
    confere_csrf()
    from coleta import testar_acesso
    ok, mensagem, detalhe = testar_acesso(request.usuario["usuario_id"], ip=ip_cliente())
    return _tela_config(teste={"ok": ok, "mensagem": mensagem, "detalhe": detalhe})


@app.post("/configuracao/esquecer")
@exige_login
def configuracao_esquecer():
    confere_csrf()
    import cofre
    cx = conectar()
    n = cofre.esquecer(cx, request.usuario["usuario_id"], ip=ip_cliente())
    cx.commit(); cx.close()
    return _tela_config(teste={
        "ok": False,
        "mensagem": "Credencial apagada do servidor." if n else "Não havia credencial guardada.",
        "detalhe": "A coleta automática para até você guardar uma senha de novo."})


@app.post("/configuracao/estacao")
@exige_login
def configuracao_estacao():
    """Cria (ou recria) o agente da estação e devolve o código de pareamento.

    O código vale 2 h e uma vez só. Ele NÃO é a senha do SEI: autoriza aquela
    máquina a publicar a coleta desta conta.
    """
    import configuracao as cfgmod
    confere_csrf()
    uid = request.usuario["usuario_id"]
    nome = (request.form.get("nome_estacao") or "").strip() or ("ESTACAO-" + str(uid))
    cx = conectar()
    c = cfgmod.ler(cx, uid)
    ag = cfgmod.agente_do(cx, uid)
    unidades = escopo_do_dono(cx, uid, c)
    if not ag:
        cx.execute("""INSERT INTO agentes(nome_estacao,dono_usuario_id,unidades_esperadas,ativo,
                      criado_em,credencial_titular,credencial_login_mascarado)
                      VALUES(?,?,?,1,?,?,?)""",
                   (nome, uid, json.dumps(unidades, ensure_ascii=False), agora(),
                    request.usuario["nome"], mascarar(c["sei_login"])))
        aid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
        cx.execute("INSERT INTO agendamento(agente_id,janelas,dias,ativo) VALUES(?,?,?,1)",
                   (aid, json.dumps(c["janelas"]), c["dias"]))
    else:
        aid = ag["id"]
        # `pausado_motivo=NULL` JUNTO. Quem termina o assistente no modo padrao
        # (servidor) ganha um agente logico com a pausa preenchida — e o texto da
        # pausa manda fazer exatamente uma coisa: instalar o agente na estacao. A
        # pessoa fazia, o pareamento funcionava, e o motivo da pausa continuava
        # la: agendamento inativo, coleta diaria que nunca roda, e nenhum alerta,
        # porque janela de agente pausado nao conta como perdida.
        cx.execute("""UPDATE agentes SET nome_estacao=?, unidades_esperadas=?,
                      pausado_motivo=NULL WHERE id=?""",
                   (nome, json.dumps(unidades, ensure_ascii=False), aid))
    codigo = secrets.token_urlsafe(12)
    cx.execute("""INSERT INTO enrolamentos(codigo_sha256,agente_id,criado_por,criado_em,expira_em)
                  VALUES(?,?,?,?,?)""",
               (hashlib.sha256(codigo.encode()).digest(), aid, uid, agora(),
                (datetime.now(TZ) + timedelta(hours=2)).isoformat(timespec="seconds")))
    registrar(cx, uid, "parear_estacao", alvo=nome)
    cx.commit(); cx.close()
    return redirect(url_for("configuracao", passo="acesso", codigo=codigo))


def mascarar(login):
    """z****@saude.ba.gov.br — o bastante para a pessoa se reconhecer, e não o
    bastante para alguém aprender o login de outra olhando a tela."""
    if not login or "@" not in login:
        return None
    nome, dom = login.split("@", 1)
    return (nome[0] + "*" * max(1, len(nome) - 1)) + "@" + dom


# --------------------------------------------------------------- alertas
def exige_papel(*papeis):
    """Decorador de papel. Existia só `exige_admin`, e o efeito foi que o papel
    `gestor` não fazia nada: a palavra não aparecia uma vez sequer no app, e
    quem era gestor tinha exatamente os poderes de um servidor. Papel declarado
    e não testado é promessa que a tela não cumpre."""
    def fora(f):
        @wraps(f)
        @exige_login
        def interno(*a, **kw):
            if request.usuario["papel"] not in papeis:
                abort(403)
            return f(*a, **kw)
        return interno
    return fora


@app.get("/alertas")
@exige_papel("gestor", "admin")
def alertas():
    """O que precisa de decisão humana nas unidades de quem olha.

    Antes só existia dentro de /admin, e portanto só o admin via — mas quem sabe
    se a coleta de uma unidade falhou, ou se a queda de 40 para 4 processos é
    real, é quem trabalha nela. Gestor vê os alertas das SUAS unidades; admin vê
    todos, inclusive os que não têm unidade (falha de agente, execução travada).
    """
    u = request.usuario
    unidades = unidades_do(u["usuario_id"])
    cx = conectar()
    varrer_execucoes(cx)
    if u["papel"] == "admin":
        linhas = cx.execute("""SELECT * FROM alerta ORDER BY reconhecido_em IS NOT NULL,
                               id DESC LIMIT 100""").fetchall()
    elif unidades:
        marc = ",".join("?" * len(unidades))
        linhas = cx.execute(f"""SELECT * FROM alerta WHERE unidade IN ({marc})
                                ORDER BY reconhecido_em IS NOT NULL, id DESC LIMIT 100""",
                            unidades).fetchall()
    else:
        linhas = []
    quem = {r["id"]: r["email"] for r in cx.execute("SELECT id,email FROM usuarios")}
    # AGRUPADO por (tipo, unidade). 78 ocorrências em 4 grupos: a lista corrida
    # fazia 77 linhas do MESMO defeito empurrarem a única diferente para fora da
    # tela. Fila que não esvazia deixa de ser lida, e o alerta que importa some
    # no meio dos repetidos.
    grupos = {}
    for a in linhas:
        k = (a["tipo"], a["unidade"] or "")
        g = grupos.setdefault(k, {"tipo": a["tipo"], "unidade": a["unidade"],
                                  "severidade": a["severidade"], "n": 0, "abertos": [],
                                  "primeiro": a["ts"], "ultimo": a["ts"],
                                  "exemplo": a["texto"], "vistos": 0})
        g["n"] += 1
        if a["reconhecido_em"]:
            g["vistos"] += 1
        else:
            g["abertos"].append(a["id"])
            # O exemplo mostrado é de um ABERTO: mostrar o texto de um já
            # reconhecido faria o grupo parecer resolvido.
            g["exemplo"] = a["texto"]
        g["primeiro"] = min(g["primeiro"], a["ts"])
        g["ultimo"] = max(g["ultimo"], a["ts"])
        if a["severidade"] == "alta":
            g["severidade"] = "alta"
    grupos = sorted(grupos.values(), key=lambda g: (not g["abertos"], -len(g["abertos"]),
                                                   g["tipo"]))
    candidatos = cx.execute(f"""SELECT * FROM snapshot WHERE estado='candidato'
        {"" if u["papel"] == "admin" else "AND unidade IN (" + ",".join("?" * len(unidades)) + ")"}
        ORDER BY coletado_em DESC""",
        [] if u["papel"] == "admin" else unidades).fetchall() if (unidades or u["papel"] == "admin") else []
    cx.commit(); cx.close()
    resp = make_response(render_template("alertas.html", u=u, alertas=linhas, quem=quem,
                                         grupos=grupos, candidatos=candidatos,
                                         unidades=unidades))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax", secure=cookie_seguro(), path="/")
    return resp


@app.post("/alertas/lote")
@exige_papel("gestor", "admin")
def alertas_reconhecer_lote():
    """Dar por visto um GRUPO inteiro de uma vez.

    Sem isto, esvaziar 78 ocorrências do mesmo defeito custa 78 cliques — e o que
    acontece na prática não é a pessoa clicar 78 vezes: é ela parar de abrir a
    tela. A fronteira é a mesma da ação individual, conferida por alerta, um a um:
    reconhecer em lote não pode virar uma porta larga para unidade alheia.
    """
    confere_csrf()
    u = request.usuario
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    if not ids:
        return redirect(url_for("alertas"))
    minhas = set(unidades_do(u["usuario_id"]))
    cx = conectar()
    marc = ",".join("?" * len(ids))
    alvos = cx.execute(f"SELECT id, unidade FROM alerta WHERE id IN ({marc})", ids).fetchall()
    permitidos = [a["id"] for a in alvos
                  if u["papel"] == "admin" or (a["unidade"] or "") in minhas]
    if permitidos:
        m2 = ",".join("?" * len(permitidos))
        cx.execute(f"""UPDATE alerta SET reconhecido_por=?, reconhecido_em=?
                       WHERE id IN ({m2}) AND reconhecido_em IS NULL""",
                   [u["usuario_id"], agora()] + permitidos)
        registrar(cx, u["usuario_id"], "reconhecer_alerta_lote",
                  alvo=f"{len(permitidos)} de {len(ids)}", ip=ip_cliente())
    cx.commit(); cx.close()
    return redirect(url_for("alertas"))


@app.post("/alertas/<int:aid>")
@exige_papel("gestor", "admin")
def alerta_reconhecer(aid):
    confere_csrf()
    u = request.usuario
    cx = conectar()
    a = cx.execute("SELECT * FROM alerta WHERE id=?", (aid,)).fetchone()
    if not a:
        cx.close()
        abort(404)
    # Gestor só reconhece o que é da unidade dele. Sem esta conferência, o papel
    # daria acesso a decidir sobre coleta de unidade alheia — e a fronteira por
    # unidade valeria para ler e não para agir, o que não faz sentido nenhum.
    if u["papel"] != "admin" and a["unidade"] not in unidades_do(u["usuario_id"]):
        cx.close()
        abort(403)
    cx.execute("UPDATE alerta SET reconhecido_por=?, reconhecido_em=? WHERE id=?",
               (u["usuario_id"], agora(), aid))
    registrar(cx, u["usuario_id"], "reconhecer_alerta", alvo=str(aid), unidade=a["unidade"],
              ip=ip_cliente())
    cx.commit(); cx.close()
    return redirect(url_for("alertas"))


# --------------------------------------------------------------- relatórios
@app.get("/relatorios")
@exige_login
def relatorios_lista():
    import relatorios as rel
    u = request.usuario
    unidades = unidades_do(u["usuario_id"])
    # A COBERTURA VEM AGREGADA DO BANCO, não de 1.165 dicionários montados em
    # Python. Esta tela é um CATÁLOGO: ela não mostra um processo sequer, só a
    # fração de preenchimento de cada campo. Medido: 60 ms de tela, dos quais
    # 34,6 ms eram `carregar()` — para alimentar 2,4 ms de contagem.
    #
    # `carregar()` continua sendo a fonte quando a tela mostra DADO; aqui, o que
    # se pergunta é quantos têm o campo, e isso o SQLite responde sozinho.
    cobertura, total_base, cob_sem_zero = rel.cobertura_agregada(
        unidades, u["usuario_id"])
    catalogo = []
    # A lista mostra só o que este papel pode abrir. Não é cosmética: é a MESMA
    # chamada que as rotas fazem, de propósito. Cartão escondido com URL aberta é
    # a forma mais comum de fronteira falsa.
    # SEM BASE NÃO É SEM CAMPO. `cobertura()` devolve 0.0 sobre lista vazia, e
    # com isso quem ainda não coletou via os 14 relatórios marcados como
    # inviáveis — a tela culpando o preenchimento do SEI por uma coleta que
    # nunca houve. Os dois diagnósticos levam a ações opostas: um manda
    # configurar a coleta, o outro manda preencher o processo.
    sem_base = not total_base
    for r in rel.visiveis(u["papel"]):
        cobs = [{"campo": c, "pct": (None if sem_base
                                     else round(100 * cobertura.get(c, 0.0)))}
                for c in r["campos"]]
        pior = 0 if sem_base else min([c["pct"] for c in cobs], default=0)
        catalogo.append({**{k: v for k, v in r.items() if k != "fn"},
                         "cobertura": cobs, "pior": pior, "sem_base": sem_base,
                         # Abaixo de 30% o relatório não é oferecido: o dado não
                         # sustenta a pergunta, e oferecer seria convidar alguém
                         # a defender uma conclusão feita de lacuna. Sem base,
                         # ele continua fechado — mas pelo motivo certo.
                         "viavel": (not sem_base) and pior >= rel.COBERTURA_INVIAVEL * 100})
    cx = conectar()
    registrar(cx, u["usuario_id"], "abrir_relatorios", alvo=f"{total_base} processos",
              unidade=";".join(unidades) or None, ip=ip_cliente())
    cx.commit(); cx.close()
    resp = make_response(render_template("relatorios.html", u=u, catalogo=catalogo,
                                         inviaveis=rel.inviaveis_medidos_agregado(
                                             cob_sem_zero, total_base),
                                         unidades=unidades,
                                         total=total_base, coleta=estado_coleta(unidades, u["usuario_id"])))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax",
                    secure=cookie_seguro(), path="/")
    return resp


@app.get("/relatorios/<rid>")
@exige_login
def relatorio(rid):
    import relatorios as rel
    u = request.usuario
    unidades = unidades_do(u["usuario_id"])
    # 403, não 404: quem tem o link precisa saber que o relatório existe e que a
    # porta é o papel, senão vira caça ao fantasma com o suporte.
    if not rel.pode_ver(rel.por_id(rid), u["papel"]):
        abort(403)
    resultado = rel.montar(rid, unidades, quem=u["nome"], usuario_id=u["usuario_id"],
                           login=u["email"])
    if not resultado:
        abort(404)
    cx = conectar()
    registrar(cx, u["usuario_id"], "ver_relatorio", alvo=rid,
              unidade=";".join(unidades) or None, ip=ip_cliente())
    cx.commit(); cx.close()
    resp = make_response(render_template("relatorio.html", u=u, r=resultado,
                                         catalogo=rel.visiveis(u["papel"]),
                                         unidades=unidades))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax",
                    secure=cookie_seguro(), path="/")
    return resp


@app.get("/relatorios/<rid>.xlsx")
@exige_login
def relatorio_xlsx(rid):
    import io

    import relatorios as rel
    u = request.usuario
    unidades = unidades_do(u["usuario_id"])
    # A planilha é a rota que MAIS precisa da conferência: ela sai do sistema e
    # circula por e-mail. Fechar a tela e deixar o `.xlsx` aberto entregaria o
    # dado nominal inteiro num anexo, que é o pior dos dois mundos.
    if not rel.pode_ver(rel.por_id(rid), u["papel"]):
        abort(403)
    resultado = rel.montar(rid, unidades, quem=u["nome"], usuario_id=u["usuario_id"],
                           login=u["email"])
    if not resultado:
        abort(404)
    buf = io.BytesIO()
    rel.para_xlsx(resultado, buf)
    buf.seek(0)
    cx = conectar()
    # A exportação é registrada com a CONTAGEM de linhas: é o número que alguém
    # vai querer conferir depois de a planilha circular por e-mail.
    registrar(cx, u["usuario_id"], "exportar_relatorio",
              alvo=f"{rid}:{len(resultado['linhas'])} linhas",
              unidade=";".join(unidades) or None, ip=ip_cliente())
    cx.commit(); cx.close()
    from flask import send_file
    return send_file(buf, as_attachment=True,
                     download_name=f"sei360_{rid}_{datetime.now(TZ):%Y-%m-%d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --------------------------------------------------------------- usuários
FILTROS_USUARIO = {
    "todos": ("Todos", "1=1"),
    "ativos": ("Ativos", "u.ativo=1 AND u.senha_hash IS NOT NULL"),
    "aguardando": ("Aguardando aprovação", "u.ativo=0 AND u.origem='auto_snapshot'"),
    "sem_senha": ("Sem senha definida", "u.senha_hash IS NULL"),
    "provisoria": ("Com senha provisória", "u.senha_hash IS NOT NULL AND u.senha_trocada_em IS NULL"),
    # `?` e não `datetime('now')`: o valor foi gravado em ISO com offset
    # ('2026-08-19T08:15:00-03:00') e o SQLite devolve ' ' no lugar do 'T' e sem
    # offset. Como texto, 'T' > ' ', então todo bloqueio de HOJE passava no teste
    # mesmo já vencido — a tela dizia "bloqueada" para quem já podia entrar.
    "bloqueados": ("Bloqueados agora",
                   "u.bloqueado_ate IS NOT NULL AND u.bloqueado_ate > ?", True),
    "sem_unidade": ("Sem unidade vinculada",
                    "u.papel<>'admin' AND NOT EXISTS(SELECT 1 FROM usuario_unidade WHERE usuario_id=u.id)"),
    "inativos": ("Desativados", "u.ativo=0"),
}
POR_PAGINA = 25


@app.get("/admin/usuarios")
@exige_papel("gestor", "admin")
def admin_usuarios(aviso=None, provisorias=None):
    """Gestão de usuários em tela própria.

    Estava dentro de /admin, com uma linha por conta e um formulário de vínculo
    aninhado em cada uma: com 67 contas a página passava de 270 KB e ninguém
    achava nada. Aqui há busca, filtro por situação e uma página de cada vez —
    e o volume da tela deixa de crescer com o número de pessoas.
    """
    busca = (request.args.get("q") or "").strip().lower()
    filtro = request.args.get("f") if request.args.get("f") in FILTROS_USUARIO else "todos"
    pagina = max(1, int(request.args.get("p") or 1))
    cx = conectar()

    onde = [FILTROS_USUARIO[filtro][1]]
    # O filtro pode pedir um parâmetro (o 3º item da tupla marca isso). É o caso
    # de "bloqueados", que precisa comparar contra o AGORA no mesmo formato em que
    # a data foi gravada.
    params = [agora()] if len(FILTROS_USUARIO[filtro]) > 2 else []
    # FRONTEIRA: o gestor vê quem compartilha unidade com ele, e mais ninguém.
    # A tela existe para responder "por que fulano não vê nada", e essa pergunta
    # só faz sentido sobre gente da sua unidade. Sem o recorte, abrir a porta ao
    # gestor entregaria o quadro de pessoal inteiro do órgão.
    if request.usuario["papel"] != "admin":
        minhas = unidades_do(request.usuario["usuario_id"])
        if not minhas:
            onde.append("0")
        else:
            marc = ",".join("?" * len(minhas))
            onde.append(f"""u.id IN (SELECT usuario_id FROM usuario_unidade
                                     WHERE unidade IN ({marc}))""")
            params += list(minhas)
    if busca:
        onde.append("(LOWER(u.email) LIKE ? OR LOWER(COALESCE(u.nome,'')) LIKE ?)")
        params += [f"%{busca}%", f"%{busca}%"]
    filtro_sql = " AND ".join(onde)

    total = cx.execute(f"SELECT COUNT(*) FROM usuarios u WHERE {filtro_sql}", params).fetchone()[0]
    usuarios = cx.execute(f"""
        SELECT u.*, (SELECT COUNT(*) FROM usuario_unidade WHERE usuario_id=u.id) AS n_unidades
        FROM usuarios u WHERE {filtro_sql}
        ORDER BY u.ativo DESC, u.papel, u.email LIMIT ? OFFSET ?""",
        params + [POR_PAGINA, (pagina - 1) * POR_PAGINA]).fetchall()

    # Contagem por situação: é o que diz onde está o trabalho pendente sem
    # obrigar a pessoa a abrir cada filtro para descobrir que está vazio.
    # As contagens seguem a MESMA fronteira da lista. Contar sobre a base inteira
    # faria a tela dizer "8 admins" para quem só pode ver dois — e o número que
    # não bate com a lista é pior que número nenhum.
    if request.usuario["papel"] != "admin":
        minhas = unidades_do(request.usuario["usuario_id"])
        recorte = (" AND u.id IN (SELECT usuario_id FROM usuario_unidade WHERE unidade IN ("
                   + ",".join("?" * len(minhas)) + "))") if minhas else " AND 0"
        p_recorte = list(minhas) if minhas else []
    else:
        recorte, p_recorte = "", []
    contagens = {}
    for chave, spec in FILTROS_USUARIO.items():
        cond = spec[1]
        p_f = [agora()] if len(spec) > 2 else []
        contagens[chave] = cx.execute(
            f"SELECT COUNT(*) FROM usuarios u WHERE {cond}{recorte}",
            p_f + p_recorte).fetchone()[0]
    unidades = [r["unidade"] for r in cx.execute(
        "SELECT DISTINCT unidade FROM snapshot ORDER BY unidade")]
    cx.close()
    resp = make_response(render_template(
        "usuarios.html", u=request.usuario, usuarios=usuarios, unidades=unidades,
        filtros=FILTROS_USUARIO, contagens=contagens, filtro=filtro, busca=busca,
        pagina=pagina, total=total, por_pagina=POR_PAGINA, aviso=aviso,
        paginas=max(1, -(-total // POR_PAGINA)),
        novo=request.args.get("novo"), provisoria=request.args.get("_p"),
        # AS SENHAS DO LOTE, uma vez só, na própria resposta de quem clicou.
        # Nunca em query string e nunca no log — mesma disciplina da criação
        # individual.
        provisorias=provisorias or []))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax", secure=cookie_seguro(), path="/")
    return resp


@app.get("/admin/usuarios/<int:uid>")
@exige_papel("gestor", "admin")
def admin_usuario_detalhe(uid, aviso=None, provisoria=None):
    """Uma conta por vez: vínculos, papel, sessões e o histórico dela.

    O vínculo de unidade é a decisão mais consequente da administração — é ela
    que define o que a pessoa enxerga. Merece uma tela onde dá para ver o que
    está sendo concedido, e não uma linha de checkboxes espremida numa tabela.
    """
    cx = conectar()
    alvo = cx.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
    if not alvo:
        cx.close()
        abort(404)
    vinculos = [r["unidade"] for r in cx.execute(
        "SELECT unidade FROM usuario_unidade WHERE usuario_id=? ORDER BY unidade", (uid,))]
    # A fronteira da LISTA tem de valer também aqui. Filtrar só a listagem e
    # deixar `/admin/usuarios/42` aberto é a forma mais comum de fronteira falsa:
    # some da tela e continua servindo por URL.
    if request.usuario["papel"] != "admin":
        minhas = set(unidades_do(request.usuario["usuario_id"]))
        if not (minhas & set(vinculos)):
            cx.close()
            abort(403)
    unidades = [r["unidade"] for r in cx.execute(
        "SELECT DISTINCT unidade FROM snapshot ORDER BY unidade")]
    sessoes = cx.execute("""SELECT * FROM sessoes WHERE usuario_id=? AND revogada_em IS NULL
                            ORDER BY id DESC LIMIT 5""", (uid,)).fetchall()
        # AS AÇÕES DELE, E AS AÇÕES SOBRE ELE. `alvo` é texto livre e várias ações o
    # usam com sentidos diferentes — id de snapshot, de busca, de execução. Casar
    # só por `alvo = str(uid)` fazia a ficha do usuário 9 mostrar, como se
    # fossem dele, ações cujo alvo era o snapshot 9 ou a busca 9, feitas por
    # outra pessoa. A lista abaixo é o conjunto das ações que de fato carregam um
    # id de USUÁRIO em `alvo`.
    historico = cx.execute(f"""SELECT * FROM log_acesso
                               WHERE usuario_id=?
                                  OR (alvo=? AND acao IN
                                      ({','.join('?' * len(ACOES_SOBRE_USUARIO))}))
                               ORDER BY id DESC LIMIT 40""",
                           [uid, str(uid), *ACOES_SOBRE_USUARIO]).fetchall()
    import configuracao as cfgmod
    import cofre
    config = cfgmod.ler(cx, uid)
    cred = cofre.estado(cx, uid)
    cx.close()
    resp = make_response(render_template(
        "usuario.html", u=request.usuario, alvo=alvo, vinculos=vinculos, unidades=unidades,
        sessoes=sessoes, historico=historico, config=config, credencial=cred,
        aviso=aviso, provisoria=provisoria))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax", secure=cookie_seguro(), path="/")
    return resp


def instancia_para_vincular(cx, unidade):
    """De qual instalação é esta unidade — e se ela já foi coletada alguma vez.

    Devolve `(instancia, sem_snapshot, erro)`.

    O LAÇO QUE MANTINHA A FESF FORA DO PRODUTO. O vínculo só aceitava unidade que
    já existisse em `snapshot`; a FESF nunca coletou uma linha; e sem vínculo
    ninguém enxerga nada nela — nem a busca, que já funciona. Não havia primeira
    peça: a lista de unidades vinha do dado, e o dado dependia do vínculo.

    Fora do snapshot, a sigla é a única fonte que existe, e ela é informativa:
    `FESF/…` e `SESAB/…` dizem o órgão. Continua não sendo texto livre de
    verdade — a forma é conferida (`ORGAO/…`, maiúsculas, sem espaço) e o
    prefixo tem de ser de uma instalação conhecida —, e é o MESMO caminho que
    "Unidades que este agente pode publicar" já usa desde o primeiro deploy.
    """
    unidade = (unidade or "").strip()
    if not unidade:
        return None, False, "Informe a unidade a vincular."
    vistas = [r["instancia"] for r in cx.execute(
        "SELECT DISTINCT COALESCE(instancia,'SEI-SESAB') AS instancia "
        "FROM snapshot WHERE unidade=?", (unidade,))]
    if len(vistas) == 1:
        return vistas[0], False, None
    if len(vistas) > 1:
        # Mesma sigla coletada em duas instalações: escolher uma no escuro seria
        # dar acesso à carteira do outro órgão. Quem decide é quem sabe.
        return None, False, (f"“{unidade}” existe em mais de uma instalação "
                             f"({', '.join(sorted(vistas))}). Vincule pela tela da "
                             f"conta, onde a instalação é explícita.")
    if not perfil_sei.sigla_valida(unidade):
        return None, True, ("Unidade desconhecida. Para vincular uma unidade que "
                            "ainda não foi coletada, escreva a sigla como o SEI a "
                            "escreve: ORGAO/…, em maiúsculas e sem espaço "
                            "(ex.: FESF/DIGAS/HECC/GAF/ADM).")
    inst = perfil_sei.instancia_da_sigla(unidade)
    if not inst:
        prefixos = sorted(p["prefixo_unidade"] for p in perfil_sei.INSTANCIAS.values()
                          if p["prefixo_unidade"])
        return None, True, (f"Não dá para saber de qual instalação é “{unidade}”: "
                            f"a sigla precisa começar por {', '.join(prefixos)}.")
    return inst, True, None


@app.post("/admin/usuarios/lote")
@exige_admin
def admin_usuarios_lote():
    """Ações em lote para as contas semeadas do snapshot.

    São 57 contas nascidas da própria carteira, inativas e sem senha. Aprovar uma
    a uma é o tipo de trabalho que ninguém faz — e o resultado seria o sistema
    ficar com um usuário só, que é o oposto do que ele existe para ser.
    """
    confere_csrf()
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    acao = request.form.get("acao")
    eu = request.usuario["usuario_id"]
    if not ids:
        return admin_usuarios(aviso="Nenhuma conta marcada.")
    cx = conectar()
    feitos = 0
    # AS PROVISÓRIAS GERADAS AQUI VOLTAM PARA A TELA. Antes o laço sorteava a
    # senha, gravava o hash e descartava o valor: a conta ficava ATIVA E
    # INACESSÍVEL, e o aviso mandava "abra cada uma para copiar" — mas a ficha
    # não mostra senha nenhuma (`admin_usuario_detalhe` só renderiza o que
    # recebe, e o GET passa None). Com 57 contas isso eram 114 telas e nenhuma
    # senha na mão.
    provisorias = []
    if acao == "ativar":
        for uid in ids:
            if uid == eu:
                continue
            # Ativar conta SEM senha criaria acesso impossível: ela nasce sem
            # hash, então ninguém consegue entrar. Gera a provisória junto.
            r = cx.execute("SELECT senha_hash, email FROM usuarios WHERE id=?",
                           (uid,)).fetchone()
            if r and not r["senha_hash"]:
                nova = secrets.token_urlsafe(9)
                h, sal = seg.hash_senha(nova)
                cx.execute("""UPDATE usuarios SET ativo=1, senha_hash=?, senha_sal=?,
                              senha_trocada_em=NULL WHERE id=?""", (h, sal, uid))
                cx.execute("""INSERT INTO log_acesso(ts,usuario_id,acao,alvo)
                              VALUES(?,?,?,?)""",
                           (agora(), eu, "ativar_com_provisoria", str(uid)))
                provisorias.append({"email": r["email"], "senha": nova})
            else:
                cx.execute("UPDATE usuarios SET ativo=1 WHERE id=?", (uid,))
            feitos += 1
        aviso = (f"{feitos} conta(s) ativada(s)."
                 + (f" {len(provisorias)} não tinham senha e receberam uma provisória —"
                    " ela aparece abaixo, UMA vez." if provisorias else ""))
    elif acao == "desativar":
        for uid in ids:
            if uid == eu:
                continue
            cx.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (uid,))
            cx.execute("UPDATE sessoes SET revogada_em=? WHERE usuario_id=? AND revogada_em IS NULL",
                       (agora(), uid))
            feitos += 1
        aviso = f"{feitos} conta(s) desativada(s) e sessões encerradas."
    elif acao == "vincular":
        # A SIGLA DIGITADA VENCE A LISTA. A lista sai de `snapshot`, e instalação
        # que nunca coletou não tem snapshot nenhum — era por aqui que a FESF
        # ficava inalcançável. `instancia_para_vincular` resolve a instalação
        # pelo dado quando ele existe e pela sigla quando não existe.
        unidade = (request.form.get("unidade_livre")
                   or request.form.get("unidade") or "").strip()
        instancia, sem_snapshot, erro = instancia_para_vincular(cx, unidade)
        if erro:
            cx.close()
            return admin_usuarios(aviso=erro)
        for uid in ids:
            cx.execute("""INSERT OR IGNORE INTO usuario_unidade(usuario_id,instancia,unidade,
                          origem,concedida_por,concedida_em) VALUES(?,?,?,'admin',?,?)""",
                       (uid, instancia, unidade, eu, agora()))
            feitos += 1
        if sem_snapshot:
            # FICA DITO NO LOG. Vínculo nascido sem snapshot é o único cujo
            # escopo ninguém conferiu contra o SEI: a instalação saiu da sigla,
            # não do dado. Quem auditar precisa distinguir os dois.
            registrar(cx, eu, "vincular_sem_snapshot", alvo=f"{feitos} conta(s)",
                      unidade=f"{instancia} · {unidade}", ip=ip_cliente())
        aviso = (f"{unidade.split('/')[-1]} ({perfil_sei.rotulo(instancia)}) "
                 f"vinculada a {feitos} conta(s)."
                 + (" A unidade ainda não tem coleta nenhuma: o vínculo nasceu da "
                    "sigla, e ficou registrado assim." if sem_snapshot else ""))
    else:
        aviso = "Ação desconhecida."
    registrar(cx, eu, f"lote_{acao}", alvo=f"{feitos} contas", ip=ip_cliente())
    cx.commit(); cx.close()
    return admin_usuarios(aviso=aviso, provisorias=provisorias)


# --------------------------------------------------------------- admin
@app.get("/admin")
@exige_admin
def admin(novo=None, provisoria=None, aviso=None):
    cx = conectar()
    varrer_execucoes(cx)
    usuarios = cx.execute("""SELECT u.*, (SELECT GROUP_CONCAT(unidade,'; ') FROM usuario_unidade
                             WHERE usuario_id=u.id) AS unidades FROM usuarios u
                             ORDER BY u.papel, u.email""").fetchall()
    # Vinculo como CONJUNTO, nao como texto. A tela marcava a caixa com
    # `unidade in x.unidades`, teste de SUBSTRING sobre o GROUP_CONCAT: como
    # ".../DGESS" e prefixo de ".../DGESS/CESS", quem tinha CESS aparecia com
    # DGESS marcada — e salvar a tela concedia de verdade a unidade que ninguem
    # pediu, porque o POST faz DELETE+INSERT do que veio marcado.
    vinculos = {}
    for r in cx.execute("SELECT usuario_id, unidade FROM usuario_unidade"):
        vinculos.setdefault(r["usuario_id"], set()).add(r["unidade"])
    agentes = cx.execute("SELECT * FROM agentes ORDER BY nome_estacao").fetchall()
    agenda = {r["agente_id"]: r for r in cx.execute("SELECT * FROM agendamento")}
    execs = cx.execute("""SELECT e.*, a.nome_estacao FROM execucao e
                          LEFT JOIN agentes a ON a.id=e.agente_id
                          ORDER BY e.id DESC LIMIT 20""").fetchall()
    alertas = cx.execute("""SELECT * FROM alerta WHERE reconhecido_em IS NULL
                            ORDER BY id DESC LIMIT 20""").fetchall()
    unidades = [r["unidade"] for r in cx.execute(
        "SELECT DISTINCT unidade FROM snapshot ORDER BY unidade")]
    logs = cx.execute("""SELECT l.*, u.email FROM log_acesso l LEFT JOIN usuarios u ON u.id=l.usuario_id
                         ORDER BY l.id DESC LIMIT 25""").fetchall()
    # Snapshots retidos precisam de uma tela para serem decididos: sem ela,
    # `candidato` é beco sem saída — a ingestão marca e ninguém nunca resolve.
    candidatos = cx.execute("""SELECT * FROM snapshot WHERE estado='candidato'
                               ORDER BY coletado_em DESC""").fetchall()
    from banco import BANCO
    tamanho_banco = BANCO.stat().st_size / 1024 / 1024
    import ia as iamod
    cfg_ia = iamod.ler_config(cx)
    cfg_ia["provedores"] = iamod.PROVEDORES
    cfg_ia["niveis"] = iamod.NIVEIS
    cfg_ia["sem_resumo"] = cx.execute("""SELECT COUNT(DISTINCT p.id_sei) FROM processo p
        JOIN snapshot s ON s.id=p.snapshot_id WHERE s.estado='corrente'
        AND p.id_sei NOT IN (SELECT id_sei FROM resumo)""").fetchone()[0]
    cfg_ia["com_resumo"] = cx.execute(SQL_COM_RESUMO).fetchone()[0]
    # A tela mostra QUEM aderiu, com nome e data. Aceite que não aparece é aceite
    # que ninguém confere — e o ponto dele é justamente poder ser conferido.
    cfg_ia["aceites"] = [dict(r) for r in cx.execute(
        "SELECT * FROM aceite_ia ORDER BY revogado_em IS NOT NULL, unidade")]
    cfg_ia["unidades"] = [r[0] for r in cx.execute(
        "SELECT DISTINCT unidade FROM snapshot WHERE estado='corrente' ORDER BY unidade")]
    cfg_ia["quem"] = {r["id"]: r["email"] for r in cx.execute("SELECT id,email FROM usuarios")}
    cx.commit(); cx.close()
    # A senha provisoria e RENDERIZADA aqui, nunca redirecionada por query string:
    # o gunicorn grava a linha de acesso com a URL inteira, e o Referer levaria o
    # segredo tambem para o pedido do CSS. Um segredo em duas linhas de log deixa
    # de ser segredo.
    # O FUNIL DO POCO, dos ultimos 7 dias. Sem isto, `devidos`/`lidos_de_fato`/
    # `servidos_do_poco` sao gravados em toda ingestao e lidos por nada — e a
    # pergunta "quanto economizamos ontem?" nao tem resposta em lugar nenhum.
    cxf = conectar()
    corte = (datetime.now(TZ) - timedelta(days=7)).isoformat(timespec="seconds")
    funil = cxf.execute("""SELECT substr(coletado_em,1,10) AS dia,
                                  SUM(COALESCE(devidos,0))          AS devidos,
                                  SUM(COALESCE(lidos_de_fato,0))    AS lidos,
                                  SUM(COALESCE(servidos_do_poco,0)) AS servidos,
                                  SUM(COALESCE(canario_divergencias,0)) AS canario,
                                  COUNT(*)                          AS snapshots
                           FROM snapshot
                           WHERE coletado_em >= ? AND estado IN ('corrente','candidato')
                           GROUP BY dia ORDER BY dia DESC""", (corte,)).fetchall()
    poco_total = cxf.execute("SELECT COUNT(*) FROM poco_processo").fetchone()[0]
    cxf.close()
    funil = [dict(r) for r in funil]
    for r in funil:
        # 5 requisicoes por processo lido; a linha servida custa zero. E o unico
        # numero que responde "quanto economizamos" sem inventar.
        total = (r["devidos"] or 0) + (r["servidos"] or 0)
        r["poupado_pct"] = round(100 * (r["servidos"] or 0) / total) if total else 0
        r["nao_lidos"] = max(0, (r["devidos"] or 0) - (r["lidos"] or 0))

    import email_saida
    # Conexão PRÓPRIA: a de cima já foi fechada lá em cima (`cx.commit(); cx.close()`),
    # e `ler_config` escreve — ela faz `INSERT OR IGNORE` da linha 1 quando a
    # tabela ainda está vazia, que é o estado de toda instalação antes de alguém
    # configurar o e-mail pela primeira vez.
    cxe = conectar()
    try:
        cfg_email = email_saida.ler_config(cxe)
        politica = acesso.ler_politica(cxe)
        cxe.commit()
    finally:
        cxe.close()
    return render_template("admin.html", funil=funil, poco_total=poco_total,
                           usuarios=usuarios, agentes=agentes, agenda=agenda,
                           execs=execs, alertas=alertas, unidades=unidades, logs=logs,
                           vinculos=vinculos, novo=novo, provisoria=provisoria,
                           candidatos=candidatos, tamanho_banco=tamanho_banco, aviso=aviso,
                           ia=cfg_ia, em=cfg_email, pol=politica,
                           u=request.usuario, coleta=estado_coleta())


@app.post("/admin/usuario")
@exige_admin
def admin_usuario():
    confere_csrf()
    f = request.form
    acao = f.get("acao")
    cx = conectar()
    if acao == "criar":
        email = (f.get("email") or "").strip().lower()
        provisoria = secrets.token_urlsafe(9)
        h, sal = seg.hash_senha(provisoria)
        try:
            cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,criado_em)
                          VALUES(?,?,?,?,?,'admin',?)""",
                       (email, f.get("nome"), h, sal, f.get("papel") or "servidor", agora()))
        except Exception:
            cx.close()
            return redirect(url_for("admin", erro="e-mail já cadastrado"))
        uid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
        for un in f.getlist("unidades"):
            cx.execute("""INSERT INTO usuario_unidade(usuario_id,unidade,concedida_por,concedida_em)
                          VALUES(?,?,?,?)""", (uid, un, request.usuario["usuario_id"], agora()))
        registrar(cx, request.usuario["usuario_id"], "criar_usuario", alvo=email)
        cx.commit(); cx.close()
        # senha provisoria aparece UMA vez, na propria resposta de quem criou.
        # Nao vai por e-mail, nao fica em claro no banco e nao passa pela URL.
        return admin_usuarios(aviso=f"Conta {email} criada. Senha provisória: {provisoria}")
    uid = int(f.get("id"))
    eu = request.usuario["usuario_id"]
    if acao in ("ativar", "papel") and uid == eu:
        # Sem esta guarda, o unico admin se rebaixa ou se desativa e a instalacao
        # so volta com SQL no volume — o container nao tem tela para isso.
        cx.close()
        return admin_usuarios(aviso="Você não altera o próprio papel nem se desativa.")
    if acao in ("ativar", "papel"):
        restantes = cx.execute("""SELECT COUNT(*) FROM usuarios WHERE papel='admin'
                                  AND ativo=1 AND id<>?""", (uid,)).fetchone()[0]
        virando = f.get("papel") if acao == "papel" else None
        alvo_admin = cx.execute("SELECT papel,ativo FROM usuarios WHERE id=?", (uid,)).fetchone()
        if alvo_admin and alvo_admin["papel"] == "admin" and alvo_admin["ativo"] \
           and restantes == 0 and virando != "admin":
            cx.close()
            return admin_usuarios(aviso="Este é o último admin ativo — desativá-lo ou rebaixá-lo "
                                        "deixaria a instalação sem ninguém para administrar.")
    if acao == "ativar":
        cx.execute("UPDATE usuarios SET ativo=1-ativo WHERE id=?", (uid,))
        registrar(cx, request.usuario["usuario_id"], "alternar_ativo", alvo=str(uid))
    elif acao == "papel":
        cx.execute("UPDATE usuarios SET papel=? WHERE id=?", (f.get("papel"), uid))
        # A SESSÃO ANTIGA NÃO ACOMPANHA A PROMOÇÃO. `usuario_atual()` lê o papel
        # VIVO, então a autorização muda na hora — mas a autenticação não: quem
        # era 'servidor' entrou sem segundo fator (papel fora da política) e com
        # "continuar conectado" de 30 dias, e viraria admin dentro da mesma
        # sessão, sem nunca ter passado pelo código. Trocar o papel derruba o
        # acesso; a pessoa entra de novo, agora pelas regras do papel novo.
        acesso.derrubar_acesso(cx, uid, "papel alterado")
        registrar(cx, request.usuario["usuario_id"], "trocar_papel", alvo=str(uid))
    elif acao == "unidades":
        # So unidade que EXISTE em snapshot. Sem isso, um POST forjado concede
        # vinculo a qualquer texto, e a fronteira passa a depender do formulario.
        validas = {r["unidade"] for r in cx.execute("SELECT DISTINCT unidade FROM snapshot")}
        pedidas = {u for u in f.getlist("unidades") if u in validas}
        # O QUE JA EXISTIA E PRESERVADO. O formulario vem com as unidades atuais
        # marcadas, entao "Salvar vinculo" sem mudar nada era o clique mais
        # provavel — e ele apagava tudo e reinseria sem `origem`, `instancia` nem
        # `principal`, que caiam no DEFAULT do DDL. Efeito: todo vinculo
        # descoberto entrando no SEI ('sei') virava 'admin', e a reconciliacao do
        # "Testar acesso" — que so desfaz o que ELA mesma criou — perdia para
        # sempre a capacidade de tirar acesso a unidade que o SEI tirou.
        antigos = {}
        for r in cx.execute("SELECT * FROM usuario_unidade WHERE usuario_id=?", (uid,)):
            antigos[r["unidade"]] = r
        antes = set(antigos)
        cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=?", (uid,))
        for un in pedidas:
            # So o vinculo NOVO nasce 'admin', que e o que ele e de fato.
            v = antigos.get(un)
            # A INSTALAÇÃO É DERIVADA, não presumida. `"SEI-SESAB"` fixo aqui era
            # inofensivo enquanto só a SESAB existia e virava erro silencioso no
            # dia seguinte: recriar o vínculo de uma unidade da FESF o gravava
            # como SESAB, e a pessoa perdia a carteira sem nada na tela dizer por
            # quê. `instancia_para_vincular` pergunta ao snapshot e, na falta
            # dele, à sigla — as unidades aqui vieram todas de `snapshot`, então
            # o primeiro caminho é o que responde.
            inst_un = (v["instancia"] if v else None) or \
                instancia_para_vincular(cx, un)[0] or perfil_sei.PADRAO
            cx.execute("""INSERT INTO usuario_unidade(usuario_id,instancia,unidade,principal,
                          origem,concedida_por,concedida_em)
                          VALUES(?,?,?,?,?,?,?)""",
                       (uid, inst_un, un,
                        v["principal"] if v else 0,
                        v["origem"] if v else "admin",
                        v["concedida_por"] if v else eu,
                        v["concedida_em"] if v else agora()))
        # O log guarda a DIFERENCA, nao a lista final: numa auditoria a pergunta e
        # "quem ganhou acesso a que e quando", e a lista final nao responde isso.
        ganhou, perdeu = sorted(pedidas - antes), sorted(antes - pedidas)
        registrar(cx, eu, "vincular_unidade", alvo=str(uid),
                  unidade=("+" + ";".join(ganhou) if ganhou else "") +
                          (" -" + ";".join(perdeu) if perdeu else "") or "sem mudança")
    elif acao == "revogar":
        # DESAFIO PENDENTE TAMBÉM. Sem isso, quem está com o cookie do segundo
        # fator e o código em mãos conclui `/verificar` logo depois e ganha uma
        # sessão NOVA — o gesto do administrador some.
        acesso.derrubar_acesso(cx, uid, "sessões revogadas")
        registrar(cx, eu, "revogar_sessoes", alvo=str(uid))
    elif acao == "nova_senha":
        # As 57 contas semeadas do snapshot nascem com senha_hash NULL. Ativa-las
        # sem isto criava conta permanentemente inacessivel: nao ha senha para
        # conferir e nao havia caminho de reset pela aplicacao.
        nova = secrets.token_urlsafe(9)
        h, sal = seg.hash_senha(nova)
        cx.execute("""UPDATE usuarios SET senha_hash=?, senha_sal=?, senha_trocada_em=NULL,
                      bloqueado_ate=NULL, falhas_seq=0 WHERE id=?""", (h, sal, uid))
        # DESAFIO PENDENTE TAMBÉM, e aqui é pior do que em "revogar": a sessão
        # que ele viraria cai em `/primeiro-acesso`, que não pede a senha antiga.
        # Quem só tinha o código em trânsito definiria a PRÓPRIA senha e ficaria
        # com a conta, enquanto a provisória recém-gerada morria sem uso.
        acesso.derrubar_acesso(cx, uid, "senha provisória gerada")
        alvo = cx.execute("SELECT email FROM usuarios WHERE id=?", (uid,)).fetchone()
        registrar(cx, eu, "nova_senha_provisoria", alvo=str(uid))
        cx.commit(); cx.close()
        return admin_usuario_detalhe(uid, provisoria=nova)
    cx.commit(); cx.close()
    # Volta para a tela DE ONDE veio: quem editou um usuário quer continuar ali,
    # não ser jogado no painel de operação.
    volta = request.referrer or ""
    if f"/admin/usuarios/{uid}" in volta:
        return admin_usuario_detalhe(uid)
    return redirect(url_for("admin_usuarios"))


@app.post("/admin/agente")
@exige_admin
def admin_agente():
    confere_csrf()
    f = request.form
    cx = conectar()
    if f.get("acao") == "criar":
        cx.execute("""INSERT INTO agentes(nome_estacao,unidades_esperadas,ativo,criado_em,
                      credencial_titular,credencial_login_mascarado)
                      VALUES(?,?,1,?,?,?)""",
                   (f.get("nome_estacao"), json.dumps(f.getlist("unidades"), ensure_ascii=False),
                    agora(), f.get("titular"), f.get("login_mascarado")))
        aid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
        cx.execute("INSERT INTO agendamento(agente_id,janelas,ativo) VALUES(?,?,1)",
                   (aid, json.dumps(["07:30"])))
        codigo = secrets.token_urlsafe(12)
        cx.execute("""INSERT INTO enrolamentos(codigo_sha256,agente_id,criado_por,criado_em,expira_em)
                      VALUES(?,?,?,?,?)""",
                   (hashlib.sha256(codigo.encode()).digest(), aid, request.usuario["usuario_id"],
                    agora(), (datetime.now(TZ) + timedelta(hours=2)).isoformat(timespec="seconds")))
        registrar(cx, request.usuario["usuario_id"], "criar_agente", alvo=f.get("nome_estacao"))
        cx.commit(); cx.close()
        return redirect(url_for("admin", agente=f.get("nome_estacao"), codigo=codigo))
    aid = int(f.get("id"))
    if f.get("acao") == "agendar":
        # HORARIO E FORMATO, nao texto livre. Um "07h30" digitado aqui fazia
        # janelas_do_dia estourar ValueError no meio do laco que varre TODOS os
        # agendamentos: nenhum agente recebia tarefa, nenhuma janela perdida era
        # detectada — e /admin, a unica tela onde se conserta o horario, respondia
        # 500. Auto-tranca. (janelas_do_dia tambem ignora item invalido, para o
        # dado ja gravado em bases existentes.)
        _cru = json.loads(f.get("janelas") or "[]") if str(f.get("janelas") or "").startswith("[") \
            else [x for x in (f.get("janelas") or "").replace(";", ",").split(",")]
        _hs = []
        for _x in _cru:
            _m = __import__("re").fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(_x))
            if _m and 0 <= int(_m.group(1)) <= 23 and 0 <= int(_m.group(2)) <= 59:
                _hs.append(f"{int(_m.group(1)):02d}:{int(_m.group(2)):02d}")
        if not _hs:
            cx.close()
            return admin(aviso="Horário inválido. Use HH:MM, separados por vírgula "
                               "(ex.: 07:30, 14:00). Nada foi alterado.")
        janelas_txt = sorted(set(_hs))
        cx.execute("""UPDATE agendamento SET janelas=?, dias=?, tolerancia_min=?, ativo=?,
                      motivo_inativo=? WHERE agente_id=?""",
                   (json.dumps(janelas_txt), f.get("dias") or "uteis",
                    int(f.get("tolerancia") or 90), 1 if f.get("ativo") == "on" else 0,
                    None if f.get("ativo") == "on" else "desarmado pelo admin", aid))
        registrar(cx, request.usuario["usuario_id"], "editar_agendamento", alvo=str(aid))
    elif f.get("acao") == "escopo":
        # IMPASSE DO PRIMEIRO DEPLOY: agente nasce com escopo vazio, e escopo
        # vazio recusa toda publicacao (fail-closed, correto). Mas a lista de
        # unidades da tela vem de `snapshot`, que so existe DEPOIS da primeira
        # publicacao — sem esta acao, instalacao nova nunca sai do lugar.
        # Por isso aqui e texto livre: o admin conhece a sigla no SEI, e o
        # servidor ainda nao conhece nenhuma.
        cru = (f.get("unidades_texto") or "").replace(",", "\n")
        lista = sorted({l.strip() for l in cru.split("\n") if l.strip()})
        cx.execute("UPDATE agentes SET unidades_esperadas=? WHERE id=?",
                   (json.dumps(lista, ensure_ascii=False), aid))
        registrar(cx, request.usuario["usuario_id"], "editar_escopo_agente",
                  alvo=str(aid), unidade=";".join(lista) or "vazio")
    elif f.get("acao") == "dono":
        # DONO liga o agente a uma CONTA do sistema (banco.py: "sem dono, a
        # trilha do SEI carimba um nome que o painel não sabe de quem é"). No
        # modo servidor isso já nasce certo (`aplicar_agendamento` grava o uid
        # de quem configurou), mas "Novo agente" — a estação física, instalada
        # por um admin — nunca perguntou isso, e não existia tela para
        # corrigir depois. A primeira vez que precisou (FESF/Laisa,
        # 08/09/2026) só saiu com UPDATE direto no banco pelo shell do host.
        bruto = (f.get("dono_usuario_id") or "").strip()
        novo_dono = int(bruto) if bruto.isdigit() else None
        cx.execute("UPDATE agentes SET dono_usuario_id=? WHERE id=?", (novo_dono, aid))
        dono_email = None
        if novo_dono:
            r = cx.execute("SELECT email FROM usuarios WHERE id=?", (novo_dono,)).fetchone()
            dono_email = r["email"] if r else None
        registrar(cx, request.usuario["usuario_id"], "editar_dono_agente",
                  alvo=str(aid), unidade=dono_email or "nenhum")
    elif f.get("acao") == "janela_extra":
        # Janela extra e ATO DE ADMIN, com autor gravado. Sem gatilho e autor, a
        # unica coleta fora de horario da carteira ficaria indistinguivel de uma
        # janela normal no historico — e e justamente a que alguem vai auditar.
        aberta = cx.execute("""SELECT id FROM execucao WHERE agente_id=? AND
                               estado IN ('entregue','em_curso')""", (aid,)).fetchone()
        if not aberta:
            cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,gatilho_por,entregue_em)
                          VALUES(?,?,'entregue','manual_admin',?,?)""",
                       (aid, agora(), request.usuario["usuario_id"], agora()))
            registrar(cx, request.usuario["usuario_id"], "janela_extra", alvo=str(aid))
    elif f.get("acao") == "novo_codigo":
        codigo = secrets.token_urlsafe(12)
        cx.execute("""INSERT INTO enrolamentos(codigo_sha256,agente_id,criado_por,criado_em,expira_em)
                      VALUES(?,?,?,?,?)""",
                   (hashlib.sha256(codigo.encode()).digest(), aid, request.usuario["usuario_id"],
                    agora(), (datetime.now(TZ) + timedelta(hours=2)).isoformat(timespec="seconds")))
        registrar(cx, request.usuario["usuario_id"], "novo_codigo_agente", alvo=str(aid))
        cx.commit(); cx.close()
        return redirect(url_for("admin", codigo=codigo))
    cx.commit(); cx.close()
    return redirect(url_for("admin"))


@app.post("/admin/snapshot")
@exige_papel("gestor", "admin")
def admin_snapshot():
    """Promove ou rejeita snapshot retido.

    `candidato` era estado TERMINAL: a ingestão marcava quando a coleta caía mais
    de 10% e não havia nenhum caminho para promover ou descartar. O dado ficava
    preso para sempre e a unidade seguia mostrando o snapshot anterior sem que
    ninguém pudesse decidir. `rejeitado` existia no esquema e ninguém escrevia.
    """
    confere_csrf()
    sid = int(request.form.get("id"))
    acao = request.form.get("acao")
    cx = conectar()
    s = cx.execute("SELECT * FROM snapshot WHERE id=?", (sid,)).fetchone()
    if not s or s["estado"] != "candidato":
        cx.close()
        return redirect(url_for("alertas"))
    # QUEM DECIDE E QUEM TRABALHA NA UNIDADE. A tela /alertas ja mostrava estes
    # botoes ao gestor — ela existe para isso, e a docstring dela diz que "quem
    # sabe se a queda de 40 para 4 processos e real e quem trabalha nela". Mas os
    # dois formularios postavam numa rota `@exige_admin`: o gestor via a coleta
    # retida da propria unidade, clicava, levava 403, e o painel dele seguia com
    # o retrato velho sem saida nenhuma.
    #
    # A fronteira e conferida AQUI, no servidor: gestor so decide sobre unidade
    # que ele alcanca. Filtrar so na tela seria decorativo.
    if request.usuario["papel"] != "admin" \
       and s["unidade"] not in unidades_do(request.usuario["usuario_id"]):
        cx.close()
        abort(403)
    if acao == "promover":
        # RECORTADO PELA MESMA CHAVE QUE `snapshots_de` USA: (unidade, dono,
        # instalacao). Sem o recorte, promover o candidato de uma unidade
        # expirava a coleta corrente de TODOS os donos dela — inclusive a coleta
        # propria de quem ja tinha rodado a sua, que voltava a ver o retrato
        # compartilhado; e, quando o promovido era o de alguem, o compartilhado
        # morria junto e a unidade SUMIA do painel de quem nao tem coleta propria,
        # sem alerta, porque `snapshots_de` deixava de achar corrente para ela.
        cx.execute("""UPDATE snapshot SET estado='expirado'
                      WHERE unidade=? AND estado='corrente'
                        AND dono_usuario_id IS ?
                        AND COALESCE(instancia,'SEI-SESAB')=COALESCE(?,'SEI-SESAB')""",
                   (s["unidade"], s["dono_usuario_id"], s["instancia"]))
        cx.execute("UPDATE snapshot SET estado='corrente' WHERE id=?", (sid,))
        registrar(cx, request.usuario["usuario_id"], "promover_snapshot",
                  alvo=str(sid), unidade=s["unidade"])
    elif acao == "rejeitar":
        cx.execute("UPDATE snapshot SET estado='rejeitado' WHERE id=?", (sid,))
        registrar(cx, request.usuario["usuario_id"], "rejeitar_snapshot",
                  alvo=str(sid), unidade=s["unidade"])
    cx.commit(); cx.close()
    # De volta para a tela DE ONDE veio: o gestor decide em /alertas e nao tem
    # /admin para voltar.
    return redirect(url_for("alertas") if request.usuario["papel"] != "admin"
                    else url_for("admin"))


@app.post("/admin/expurgo")
@exige_admin
def admin_expurgo():
    confere_csrf()
    from expurgo import expurgar
    simular = request.form.get("simular") == "1"
    plano = expurgar(simular=simular, usuario_id=request.usuario["usuario_id"])
    return admin(aviso=("Simulação — nada foi apagado. " if simular else "Expurgo executado. ")
                 + ("; ".join(f"{t}: {n} ({m})" for t, n, m in plano) or "nada a apagar"))


@app.post("/admin/email")
@exige_admin
def admin_email():
    """Chave, remetente e teste de envio. A chave nunca volta para a tela."""
    import email_saida
    confere_csrf()
    f = request.form
    uid = request.usuario["usuario_id"]
    ip = ip_cliente()
    cx = conectar()
    aviso = None
    try:
        if f.get("acao") == "teste":
            para = (f.get("para") or request.usuario["email"] or "").strip()
            ok, erro = email_saida.testar(cx, para, uid, ip=ip)
            aviso = ("Teste enviado — confira a caixa de entrada. "
                     "A recuperação de senha e o segundo fator já podem ser ligados."
                     if ok else f"O teste NÃO saiu: {erro}")
        else:
            chave = (f.get("chave") or "").strip()
            if chave:
                email_saida.guardar_chave(cx, chave, uid, ip=ip)
            email_saida.guardar_remetente(cx, f.get("remetente"),
                                          f.get("responder_para"), uid, ip=ip)
            aviso = ("Salvo. Mande um teste antes de ligar qualquer coisa — "
                     "'configurado' e 'funciona' são coisas diferentes.")
    except RuntimeError as e:
        aviso = str(e)
    cx.commit(); cx.close()
    return admin(aviso=aviso)


@app.post("/admin/acesso")
@exige_admin
def admin_acesso():
    """Liga e desliga a recuperação e o segundo fator.

    A recusa quando o e-mail não está pronto mora em `acesso.salvar_politica`, e
    não aqui: ela precisa valer para qualquer caminho que mexa na política, não
    só para esta tela.
    """
    confere_csrf()
    cx = conectar()
    try:
        acesso.salvar_politica(cx, request.form.get("recuperacao") == "1",
                               request.form.getlist("fator2"),
                               request.usuario["usuario_id"], ip=ip_cliente())
        pol = acesso.ler_politica(cx)
        aviso = ("Política salva. Recuperação: "
                 + ("ligada" if pol["recuperacao_ativa"] else "desligada")
                 + "; segundo fator: "
                 + (", ".join(pol["fator2_papeis"]) or "ninguém") + ".")
    except RuntimeError as e:
        aviso = str(e)
    cx.commit(); cx.close()
    return admin(aviso=aviso)


@app.post("/admin/ia")
@exige_admin
def admin_ia():
    """Configura a integração de IA. A chave vai para o cofre; o nível decide o
    que sai do sistema, e o nível 'completo' exige aceite com nome e data."""
    import ia
    confere_csrf()
    f = request.form
    uid = request.usuario["usuario_id"]
    cx = conectar()
    aviso = None
    cx.execute("INSERT OR IGNORE INTO config_ia(id) VALUES(1)")

    if f.get("acao") == "chave":
        chave = (f.get("chave") or "").strip()
        if not chave:
            aviso = "Informe a chave de API."
        elif not ia.__dict__.get("PROVEDORES", {}).get(f.get("provedor") or "anthropic"):
            aviso = "Provedor desconhecido."
        else:
            try:
                ia.guardar_chave(cx, chave, uid, ip=ip_cliente())
                cx.execute("UPDATE config_ia SET provedor=?, modelo=?, atualizado_em=? WHERE id=1",
                           (f.get("provedor") or "anthropic",
                            f.get("modelo") or ia.PROVEDORES["anthropic"]["padrao"], agora()))
                aviso = "Chave guardada e cifrada. Ela não volta a aparecer em tela."
            except RuntimeError as e:
                aviso = str(e)

    elif f.get("acao") == "nivel":
        nivel = f.get("nivel") or "estruturado"
        if nivel == "completo":
            # Nível completo manda texto escrito por servidor — onde pode haver
            # nome de paciente — para fora. Isso não pode acontecer por clique
            # distraído: exige a caixa de aceite, e fica registrado com quem e
            # quando, porque é a pessoa que responde por essa decisão.
            if f.get("aceite") != "sim":
                aviso = ("Para incluir especificação e anotação é preciso marcar o aceite: "
                         "esse texto é escrito por servidor e pode citar paciente.")
            else:
                cx.execute("""UPDATE config_ia SET nivel='completo', aceite_em=?, aceite_por=?,
                              atualizado_em=? WHERE id=1""", (agora(), uid, agora()))
                registrar(cx, uid, "aceite_ia_completo", alvo="texto livre enviado ao provedor",
                          ip=ip_cliente())
                aviso = "Nível completo ligado, com aceite registrado."
        else:
            cx.execute("""UPDATE config_ia SET nivel='estruturado', aceite_em=NULL,
                          aceite_por=NULL, atualizado_em=? WHERE id=1""", (agora(),))
            aviso = "Voltou para o nível restrito: nenhum texto livre sai do SEI360."

    elif f.get("acao") == "ativar":
        cx.execute("UPDATE config_ia SET ativo=1-ativo, atualizado_em=? WHERE id=1", (agora(),))
        registrar(cx, uid, "alternar_ia", ip=ip_cliente())

    elif f.get("acao") == "testar":
        cx.commit()
        ok, msg = ia.testar(cx, uid, ip=ip_cliente())
        aviso = ("✓ " if ok else "✗ ") + msg

    elif f.get("acao") == "apagar":
        cx.execute("UPDATE config_ia SET chave=NULL, nonce=NULL, ativo=0, atualizado_em=? WHERE id=1",
                   (agora(),))
        registrar(cx, uid, "apagar_chave_ia", ip=ip_cliente())
        aviso = "Chave apagada. A geração de resumos para até alguém guardar outra."

    cx.commit(); cx.close()
    return admin(aviso=aviso)


@app.post("/admin/ia/aceite")
@exige_admin
def admin_ia_aceite():
    """Adesão de UMA unidade ao envio de dados à IA, com quem e quando.

    Por unidade, e não por sistema, porque o texto que sai é o que os servidores
    daquela unidade escreveram. Ligar uma chave global mandaria para fora o texto
    livre de seis unidades por decisão de quem não responde por nenhuma delas.

    A revogação não apaga a linha: ela carimba `revogado_em`. Quem revoga precisa
    conseguir provar depois que houve adesão no período em que houve envio.
    """
    confere_csrf()
    f = request.form
    uid = request.usuario["usuario_id"]
    unidade = (f.get("unidade") or "").strip()
    if not unidade:
        return admin(aviso="Escolha a unidade.")
    cx = conectar()
    if f.get("acao") == "revogar":
        cx.execute("UPDATE aceite_ia SET revogado_em=? WHERE unidade=? AND revogado_em IS NULL",
                   (agora(), unidade))
        registrar(cx, uid, "revogar_aceite_ia", alvo=unidade, unidade=unidade, ip=ip_cliente())
        aviso = f"Adesão de {unidade} revogada. Novos resumos dessa unidade param agora."
    else:
        nivel = "completo" if f.get("nivel") == "completo" else "estruturado"
        if nivel == "completo" and f.get("confirma") != "sim":
            cx.close()
            return admin(aviso=("Para o nível completo é preciso marcar a confirmação: "
                                "esse texto é escrito por servidor e pode citar paciente."))
        cx.execute("""INSERT INTO aceite_ia(unidade,nivel,aceito_por,aceito_em,revogado_em)
                      VALUES(?,?,?,?,NULL)
                      ON CONFLICT(unidade) DO UPDATE SET nivel=excluded.nivel,
                        aceito_por=excluded.aceito_por, aceito_em=excluded.aceito_em,
                        revogado_em=NULL""", (unidade, nivel, uid, agora()))
        registrar(cx, uid, "aceite_ia", alvo=f"{unidade}: {nivel}", unidade=unidade,
                  ip=ip_cliente())
        aviso = f"{unidade} aderiu no nível {nivel}, registrado com seu nome e a hora."
    cx.commit(); cx.close()
    return admin(aviso=aviso)


@app.post("/admin/ia/gerar")
@exige_admin
def admin_ia_gerar():
    """Gera resumo para os processos que ainda não têm.

    Em lote pequeno e SÍNCRONO de propósito: com fila e trabalhador em segundo
    plano, o custo vira invisível e a conta chega no fim do mês. Assim quem
    clica vê quantos foram, quanto custou em tokens e decide se clica de novo.
    """
    import ia
    confere_csrf()
    uid = request.usuario["usuario_id"]
    quantos = min(50, max(1, int(request.form.get("quantos") or 10)))
    cx = conectar()
    cfg = ia.ler_config(cx)
    chave = ia.abrir_chave(cx)
    if not chave or not cfg["ativo"]:
        cx.close()
        return admin(aviso="A integração de IA está desligada ou sem chave.")

    # A FRONTEIRA É AQUI, no SQL. Só entra processo de unidade que ADERIU, e no
    # nível que ela aderiu. Sem isto, uma chave global mandava para fora o texto
    # livre das seis unidades de uma vez, decidido por quem não responde por
    # nenhuma delas.
    aderidas = {r["unidade"]: r["nivel"] for r in cx.execute(
        "SELECT unidade, nivel FROM aceite_ia WHERE revogado_em IS NULL")}
    if not aderidas:
        cx.close()
        return admin(aviso="Nenhuma unidade aderiu ao envio de dados à IA. "
                           "A adesão é por unidade, em /admin, e fica registrada "
                           "com quem aceitou e quando.")
    marc = ",".join("?" * len(aderidas))
    pendentes = cx.execute(f"""
        SELECT p.*, t.especificacao, t.anotacao, t.acompanhamento, s.coletado_em,
               s.unidade AS snap_unidade
        FROM processo p
        JOIN snapshot s ON s.id = p.snapshot_id
        LEFT JOIN processo_texto t ON t.snapshot_id = p.snapshot_id AND t.id_sei = p.id_sei
        WHERE s.estado='corrente' AND s.unidade IN ({marc})
          AND p.id_sei NOT IN (SELECT id_sei FROM resumo)
          -- Linha com detalhe REAPROVEITADO nao gera resumo novo. O texto
          -- descreveria um estado que esta corrida nao mediu, e sairia com a data
          -- de hoje: a tarja "descreve 17/08" nunca dispararia, que e justamente
          -- o aviso que existe para impedir alguem de decidir sobre um retrato
          -- antigo achando que e o de agora.
          AND COALESCE(p.servido_do_poco,0) = 0
        GROUP BY p.id_sei LIMIT ?""", list(aderidas) + [quantos]).fetchall()

    feitos, tokens, custo, erros, recusados = 0, 0, 0.0, [], []
    for p in pendentes:
        # O nível é o da UNIDADE, nunca o global: unidade que aderiu só ao
        # estruturado não manda texto livre porque outra aderiu ao completo.
        nivel = aderidas.get(p["snap_unidade"], "estruturado")
        if nivel == "completo" and cfg["nivel"] != "completo":
            nivel = "estruturado"
        dados = ia.montar_prompt(dict(p), nivel)
        # TETO DE GASTO por rodada. Um lote de 50 com o modelo errado escolhido
        # por engano é a diferença entre centavos e dezenas de dólares, e o
        # clique é o mesmo.
        if custo >= ia.TETO_RODADA_USD:
            erros.append(f"teto de US$ {ia.TETO_RODADA_USD:.2f} da rodada atingido")
            break
        try:
            curto, longo, uso = ia.resumir(chave, cfg["modelo"], dados)
        except Exception as e:                               # noqa: BLE001
            erros.append(f"{p['protocolo']}: {type(e).__name__}")
            # Para no primeiro erro em vez de insistir 50 vezes: chave inválida
            # ou limite estourado não melhora na tentativa seguinte, só gasta.
            break
        curto, longo, problemas = ia.validar_saida(curto, longo, dados)
        if problemas:
            # O texto entra corrigido, e o que foi corrigido fica registrado: é o
            # que permite responder depois "o modelo inventou isso alguma vez?".
            recusados.append(f"{p['protocolo']}: {'; '.join(problemas)}")
        cx.execute("""INSERT OR REPLACE INTO resumo(id_sei,curto,longo,descrito_em,
                      gerado_em,gerado_por) VALUES(?,?,?,?,?,?)""",
                   # A data e a da MEDICAO da linha, nao a da coleta. Com detalhe
                   # reaproveitado as duas divergem, e e a primeira que diz de
                   # quando e o estado que o texto descreve.
                   (p["id_sei"], curto, longo,
                    (p["medido_em"] or p["coletado_em"] or "")[:10], agora(),
                    f"{cfg['provedor']}/{cfg['modelo']}/{nivel}"))
        feitos += 1
        tokens += uso["total"]
        custo += ia.custo_usd(cfg["modelo"], uso["entrada"], uso["saida"]) or 0.0
    cx.execute("""UPDATE config_ia SET gerados=gerados+?, tokens=tokens+?, ultimo_em=? WHERE id=1""",
               (feitos, tokens, agora()))
    # O registro guarda o QUE e o QUANTO, nunca o texto enviado nem o recebido.
    registrar(cx, uid, "gerar_resumos",
              alvo=f"{feitos} resumos, {tokens} tokens, US$ {custo:.4f}, "
                   f"unidades: {';'.join(aderidas)}", ip=ip_cliente())
    cx.commit(); cx.close()
    msg = f"{feitos} resumo(s) gerado(s), {tokens} tokens, custo estimado US$ {custo:.4f}."
    if recusados:
        msg += f" Saída corrigida em {len(recusados)}: " + "; ".join(recusados[:3])
    if erros:
        msg += " Parou em: " + "; ".join(erros)
    return admin(aviso=msg)


@app.post("/admin/alerta/<int:aid>")
@exige_admin
def reconhecer(aid):
    confere_csrf()
    cx = conectar()
    cx.execute("UPDATE alerta SET reconhecido_por=?, reconhecido_em=? WHERE id=?",
               (request.usuario["usuario_id"], agora(), aid))
    cx.commit(); cx.close()
    return redirect(url_for("admin"))


# --------------------------------------------------------------- agente
# Sem varredura, `heartbeat_em` era escrito e NUNCA lido, e os estados `travada`,
# `perdida` e `nao_executada` existiam no CHECK sem nunca serem atribuidos: uma
# estacao desligada no meio da coleta deixava a execucao `em_curso` para sempre,
# e como `em_curso` bloqueia a entrega, o agendamento morria calado. O destrave
# pela interface tambem nao existia — `janela_extra` cai na mesma trava.
SEM_PULSO_MIN = 5          # heartbeat e de 60s; 5 min sao 5 batidas perdidas
ENTREGUE_SEM_INICIO_MIN = 30


def janelas_perdidas(cx):
    """Janela que fechou sem NINGUÉM ter pedido a tarefa vira linha 'perdida'.

    Sem isto, estação desligada a manhã inteira não produz registro nenhum: o
    painel mostra o snapshot de ontem e o /admin mostra a última execução, que
    foi ontem. A falha aparece como AUSÊNCIA, e ausência ninguém vê. A taxa base
    medida em campo é de 1 janela perdida em 6 — não é hipótese.
    """
    novas = 0
    # Só entra na varredura o agendamento de agente que JÁ FOI PAREADO. Sem
    # `token_sha256` nenhuma estação se enrolou nele: não há o que chegar
    # atrasado, e "janela perdida" seria uma acusação sobre uma execução que
    # nunca teve como acontecer. Agente sem dono também fica de fora — não há a
    # quem pedir credencial, e portanto não há coleta possível.
    for cfg in cx.execute("""SELECT ag.* FROM agendamento ag JOIN agentes a ON a.id=ag.agente_id
                             WHERE ag.ativo=1 AND a.ativo=1
                               AND a.token_sha256 IS NOT NULL
                               AND a.dono_usuario_id IS NOT NULL""").fetchall():
        if cfg["dias"] == "uteis" and not janelas.dia_util(datetime.now(TZ).date()):
            continue
        tol = timedelta(minutes=cfg["tolerancia_min"])
        # O MESMO desvio da entrega, e a MESMA chave. A cobrança mede o tempo
        # contra o horário em que a estação acorda; a identidade da janela
        # continua sendo o horário configurado, que é o que está gravado em
        # `execucao.janela` desde antes do escalonamento.
        desvio = janelas.desvio_do_agente(cfg["agente_id"])
        for base, acordar in janelas.janelas_do_dia(json.loads(cfg["janelas"]),
                                                    datetime.now(TZ), desvio):
            if datetime.now(TZ) - acordar <= tol:
                continue                      # ainda dá tempo, ou nem venceu
            iso = base.isoformat(timespec="seconds")
            j = base
            ja = cx.execute("SELECT 1 FROM execucao WHERE agente_id=? AND janela=?",
                            (cfg["agente_id"], iso)).fetchone()
            if ja:
                continue
            cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,terminado_em)
                          VALUES(?,?,'perdida','janela',?)""", (cfg["agente_id"], iso, agora()))
            ex = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
            cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,texto)
                          VALUES(?,?,?,?,?)""",
                       (agora(), "janela_perdida", "alta", ex,
                        f"a janela de {j:%H:%M} de {j:%d/%m} fechou e o agente nunca "
                        f"pediu a tarefa — estação desligada, sem rede ou tarefa não agendada"))
            novas += 1
    return novas


def _faxina_se_devida(cx):
    """A retenção acontece, em vez de existir como botão.

    `expurgo.expurgar()` tem prazo escrito por tipo de dado e uma justificativa
    para cada um — e ninguém a chamava: os únicos chamadores eram o botão do
    /admin, a linha de comando e os testes. Medido: com 59 pessoas coletando, o
    banco cresce ~49 MB/dia e passa de 1 GB em três semanas. E uma política de
    retenção que ninguém executa é uma política que não existe.

    Pendurada AQUI, e não no `atendente`, porque o atendente só existe se
    `SEI360_ATENDENTE=1` e se ganhar a vez — um container só de painel nunca
    expurgaria. `varrer_execucoes` é o único ponto que roda em todo worker.

    Numa THREAD porque a faxina leva ~8,5 s medidos, e quem clicou no painel não
    pode pagar isso. E a decisão é reivindicada no banco, senão os três workers
    expurgariam juntos.
    """
    import expurgo
    try:
        if not expurgo.reivindicar(cx):
            return False
    except Exception as ex:                                    # noqa: BLE001
        print(f"faxina: nao consegui reivindicar ({type(ex).__name__})", flush=True)
        return False

    def _rodar():
        try:
            r = expurgo.expurgar()
            print(f"faxina automatica: {r}", flush=True)
        except Exception as ex:                                # noqa: BLE001
            print(f"faxina automatica falhou: {type(ex).__name__}", flush=True)

    threading.Thread(target=_rodar, name="faxina", daemon=True).start()
    return True


def varrer_execucoes(cx):
    # A FAXINA PEGA CARONA na varredura, que já roda a cada abertura de painel.
    # Ela decide sozinha se está na hora (uma vez por dia) e sai fora se outro
    # worker chegou antes.
    _faxina_se_devida(cx)
    janelas_perdidas(cx)
    limite_pulso = (datetime.now(TZ) - timedelta(minutes=SEM_PULSO_MIN)).isoformat(timespec="seconds")
    limite_entrega = (datetime.now(TZ) - timedelta(minutes=ENTREGUE_SEM_INICIO_MIN)).isoformat(timespec="seconds")
    travadas = cx.execute("""SELECT id FROM execucao WHERE estado='em_curso'
                             AND COALESCE(heartbeat_em, iniciado_em, entregue_em) < ?""",
                          (limite_pulso,)).fetchall()
    for t in travadas:
        cx.execute("UPDATE execucao SET estado='travada', terminado_em=?, exit_code=5 WHERE id=?",
                   (agora(), t["id"]))
        cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,texto) VALUES(?,?,?,?,?)""",
                   (agora(), "coleta_travada", "alta", t["id"],
                    f"execução {t['id']} sem pulso há mais de {SEM_PULSO_MIN} min — "
                    "marcada como travada para liberar a próxima janela"))
    perdidas = cx.execute("""SELECT id FROM execucao WHERE estado='entregue'
                             AND entregue_em < ?""", (limite_entrega,)).fetchall()
    for p in perdidas:
        cx.execute("UPDATE execucao SET estado='nao_executada', terminado_em=? WHERE id=?",
                   (agora(), p["id"]))
        cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,texto) VALUES(?,?,?,?,?)""",
                   (agora(), "tarefa_nao_executada", "media", p["id"],
                    f"execução {p['id']} foi entregue e o agente nunca começou "
                    f"(mais de {ENTREGUE_SEM_INICIO_MIN} min) — estação desligada?"))
    return len(travadas), len(perdidas)


def agente_autenticado():
    """Bearer sobre HTTPS MAIS HMAC do corpo.

    Honestidade sobre o que isto NAO faz: a chave do HMAC e o proprio token, que
    viaja no mesmo request — entao contra quem le o trafego a assinatura nao
    protege nada. O que ela entrega e integridade contra corrupcao no caminho e
    recusa de requisicao com relogio fora de ±5 min. Assinatura com chave separada
    (entregue no enrolamento) e o passo seguinte, e esta anotado como tal."""
    cab = request.headers.get("Authorization", "")
    if not cab.startswith("Bearer "):
        return None, "sem Bearer"
    token = cab[7:]
    cx = conectar()
    ag = cx.execute("SELECT * FROM agentes WHERE token_sha256=?",
                    (hashlib.sha256(token.encode()).digest(),)).fetchone()
    cx.close()
    if not ag or not ag["ativo"]:
        return None, "agente desconhecido ou inativo"
    # O TOKEN não é a conta: desativar a pessoa revogava as sessões dela e deixava
    # a estação publicando. Quem saiu do órgão seguia alimentando a carteira, e o
    # histórico de execução seguia carimbando o nome dele. `agentes.ativo` nunca
    # era escrito como 0 por caminho nenhum do sistema — a conferência existia e
    # não tinha quem a acionasse.
    if ag["dono_usuario_id"]:
        cxd = conectar()
        dono = cxd.execute("SELECT ativo FROM usuarios WHERE id=?",
                           (ag["dono_usuario_id"],)).fetchone()
        cxd.close()
        if not dono or not dono["ativo"]:
            return None, "o dono deste agente está desativado"
    ok, motivo = seg.assinatura_ok(token, request.headers.get("X-SEI360-Ts", ""),
                                   request.get_data(), request.headers.get("X-SEI360-Assinatura", ""))
    return (ag, None) if ok else (None, motivo)


@app.post("/api/agente/enrolar")
def enrolar():
    """Troca o codigo de uso unico (dado pelo admin) por um token permanente."""
    corpo = request.get_json(silent=True) or {}
    codigo = corpo.get("codigo") or ""
    cx = conectar()
    linha = cx.execute("SELECT * FROM enrolamentos WHERE codigo_sha256=?",
                       (hashlib.sha256(codigo.encode()).digest(),)).fetchone()
    if not linha or linha["usado_em"] or linha["expira_em"] < agora():
        cx.close()
        return jsonify(erro="código inválido, expirado ou já usado"), 401
    token = secrets.token_urlsafe(32)
    cx.execute("UPDATE agentes SET token_sha256=?, versao_agente=?, ultimo_contato_em=? WHERE id=?",
               (hashlib.sha256(token.encode()).digest(), corpo.get("versao"), agora(),
                linha["agente_id"]))
    cx.execute("UPDATE enrolamentos SET usado_em=? WHERE codigo_sha256=?",
               (agora(), linha["codigo_sha256"]))
    ag = cx.execute("SELECT * FROM agentes WHERE id=?", (linha["agente_id"],)).fetchone()
    registrar(cx, None, "enrolar_agente", alvo=ag["nome_estacao"])
    cx.commit(); cx.close()
    return jsonify(token=token, agente_id=ag["id"], nome_estacao=ag["nome_estacao"],
                   unidades=json.loads(ag["unidades_esperadas"] or "[]"))


def instancia_do_agente(cx, ag):
    """A instalação que este agente atende: a da configuração do DONO dele.

    UMA definição, três usos (tarefa de coleta, plano do poço, ingestão do
    resultado). Os três liam a mesma coluna de jeitos diferentes — dois com o
    padrão escrito à mão — e discordar aqui é gravar o dado de um órgão sob o
    nome do outro.

    Sem dono, sem configuração ou com instalação desconhecida, cai no padrão: é a
    única instalação que o sistema coletou até hoje, e o coletor sem perfil já se
    comporta assim.
    """
    if not ag or not ag["dono_usuario_id"]:
        return perfil_sei.PADRAO
    r = cx.execute("SELECT sistema FROM config_usuario WHERE usuario_id=? "
                   "ORDER BY atualizado_em DESC, sistema LIMIT 1",
                   (ag["dono_usuario_id"],)).fetchone()
    inst = (r["sistema"] if r else None) or perfil_sei.PADRAO
    return inst if perfil_sei.existe(inst) else perfil_sei.PADRAO


@app.get("/api/agente/tarefa")
def tarefa():
    ag, erro = agente_autenticado()
    if not ag:
        return jsonify(erro=erro), 401
    cx = conectar()
    varrer_execucoes(cx)          # libera janela presa por execucao morta
    buscamod.varrer(cx)           # e busca entregue que nunca voltou
    cx.execute("UPDATE agentes SET ultimo_contato_em=? WHERE id=?", (agora(), ag["id"]))
    # Agente sem DONO não tem credencial: o cofre guarda por `usuario_id`, e sem
    # dono não há de quem abrir. Entregar tarefa assim produz uma coleta que falha
    # no login e um alerta que sugere estação desligada — o motivo errado, e o
    # errado é pior que nenhum, porque manda a pessoa procurar no lugar errado.
    if not ag["dono_usuario_id"]:
        cx.commit(); cx.close()
        return jsonify(coletar=False, motivo=(
            "este agente não tem dono definido, então não há credencial do SEI "
            "para usar. Peça a um administrador para vincular o agente à pessoa "
            "titular da conta do SEI em /admin."))
    if ag["pausado_motivo"]:
        cx.commit(); cx.close()
        return jsonify(coletar=False, motivo=ag["pausado_motivo"])
    # A INSTALAÇÃO E O PERFIL VIAJAM COM A TAREFA DE COLETA, como já viajavam com
    # a de busca (`/api/agente/busca`). Sem eles o coletor cai na constante
    # interna — a SESAB — e uma coleta da FESF entraria no SEI errado, falhando
    # de um jeito que parece senha inválida. As duas metades do mesmo agente não
    # podem falar de instalações diferentes.
    inst_ag = instancia_do_agente(cx, ag)
    # E A INSTALAÇÃO TEM DE SABER COLETAR. Desde que o passo 1 aceita instalação
    # que só serve para BUSCAR, alguém pode configurar a coleta na FESF e parear
    # uma estação: o coletor entraria, a visualização Detalhada falharia EM
    # SILÊNCIO (é do SEI 5) e o painel publicaria carteira vazia com cara de
    # carteira vazia de verdade. Recusar aqui, com o motivo escrito no perfil, é
    # o oposto: não coleta e diz por quê. `disponivel_coleta` deixa de ser um
    # comentário no perfil e passa a ser a trava que ele promete ser.
    if not perfil_sei.perfil(inst_ag)["disponivel_coleta"]:
        cx.commit(); cx.close()
        return jsonify(coletar=False, instancia=inst_ag, motivo=(
            f"a coleta ainda não roda em {perfil_sei.INSTANCIAS[inst_ag]['nome']}: "
            + perfil_sei.INSTANCIAS[inst_ag].get(
                "motivo_sem_coleta", "instalação sem coletor.")
            + " A busca nesta instalação continua funcionando."),
            versao_disponivel=VERSAO_AGENTE)
    perfil_ag = perfil_sei.envelope_do_coletor(inst_ag)
    cfg = cx.execute("SELECT * FROM agendamento WHERE agente_id=?", (ag["id"],)).fetchone()
    if not cfg:
        cx.commit(); cx.close()
        return jsonify(coletar=False, motivo="sem agendamento configurado")
    if not cfg["ativo"]:
        cx.commit(); cx.close()
        return jsonify(coletar=False,
                       motivo=cfg["motivo_inativo"] or "agendamento desarmado")

    hoje = datetime.now(TZ).date().isoformat()
    concluidas = {r["janela"] for r in cx.execute(
        "SELECT janela FROM execucao WHERE agente_id=? AND estado='concluida' AND janela LIKE ?",
        (ag["id"], hoje + "%"))}
    # Em curso conta como ocupado: entregar outra poria duas coletas sobre o mesmo
    # perfil do Chromium, que e escritor unico e corrompe se duplicado.
    ocupada = cx.execute("""SELECT * FROM execucao WHERE agente_id=? AND estado='em_curso'
                            ORDER BY id DESC LIMIT 1""", (ag["id"],)).fetchone()
    if ocupada:
        cx.commit(); cx.close()
        return jsonify(coletar=False, motivo=f"execução {ocupada['id']} ainda em curso",
                       versao_disponivel=VERSAO_AGENTE)

    # Tarefa ENTREGUE e ainda nao iniciada volta igual, com o mesmo id. Se o
    # agente cair entre receber e comecar, a alternativa seria a janela morrer
    # esperando um agente que ja esqueceu dela.
    pendente = cx.execute("""SELECT * FROM execucao WHERE agente_id=? AND estado='entregue'
                             ORDER BY id DESC LIMIT 1""", (ag["id"],)).fetchone()
    if pendente:
        cx.commit(); cx.close()
        return jsonify(coletar=True, execucao_id=pendente["id"], janela=pendente["janela"],
                       motivo=f"retomando a execução {pendente['id']} ({pendente['gatilho']})",
                       unidades=json.loads(ag["unidades_esperadas"] or "[]"),
                       instancia=inst_ag, perfil=perfil_ag,
                       parser_versao=poco.PARSER_VERSAO,
                       versao_disponivel=VERSAO_AGENTE)

    devida, motivo = janelas.janela_devida(cfg, ja_concluidas=concluidas)
    if not devida:
        cx.commit(); cx.close()
        return jsonify(coletar=False, motivo=motivo, versao_disponivel=VERSAO_AGENTE)

    entregues = cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=? AND janela=?",
                           (ag["id"], devida)).fetchone()[0]
    if entregues >= cfg["max_entregas_janela"]:
        cx.commit(); cx.close()
        return jsonify(coletar=False, motivo="teto de entregas desta janela atingido",
                       versao_disponivel=VERSAO_AGENTE)

    # A ENTREGA E O LOCK: gravar a execucao antes de responder impede que dois
    # disparos simultaneos do Task Scheduler recebam a mesma janela.
    cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em)
                  VALUES(?,?,'entregue','janela',?)""", (ag["id"], devida, agora()))
    ex = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    cx.commit(); cx.close()
    return jsonify(coletar=True, execucao_id=ex, janela=devida, motivo=motivo,
                   unidades=json.loads(ag["unidades_esperadas"] or "[]"),
                   instancia=inst_ag, perfil=perfil_ag,
                   # A versao do parser viaja com a tarefa. Coletor que entende os
                   # campos de outro jeito recebe "leia tudo" em vez de bloco cujo
                   # significado mudou.
                   parser_versao=poco.PARSER_VERSAO,
                   versao_disponivel=VERSAO_AGENTE)


@app.post("/api/agente/evento")
def evento():
    """inicio | heartbeat | fim. O heartbeat monitora o PROCESSO DO COLETOR, nao
    o do agente: o agente pode estar vivissimo com o filho pendurado."""
    ag, erro = agente_autenticado()
    if not ag:
        return jsonify(erro=erro), 401
    c = request.get_json(silent=True) or {}
    ex = c.get("execucao_id")
    cx = conectar()
    linha = cx.execute("SELECT * FROM execucao WHERE id=? AND agente_id=?", (ex, ag["id"])).fetchone()
    if not linha:
        cx.close()
        return jsonify(erro="execução não é deste agente"), 404
    tipo = c.get("tipo")
    if tipo not in ("inicio", "heartbeat", "fim"):
        cx.close()
        return jsonify(erro=f"tipo desconhecido: {tipo!r}"), 400
    # Execução encerrada não volta atrás. Sem esta guarda, um 'fim' repetido —
    # de um agente com bug, de um retry cego ou de quem tenha o token — reescreve
    # o desfecho DEPOIS do fato, e o histórico de execução é justamente a peça
    # que alguém audita para saber se a coleta aconteceu.
    if linha["estado"] not in ("entregue", "em_curso"):
        cx.close()
        return jsonify(erro=f"execução já encerrada como {linha['estado']}"), 409
    if tipo == "inicio":
        cx.execute("UPDATE execucao SET estado='em_curso', iniciado_em=?, heartbeat_em=? WHERE id=?",
                   (agora(), agora(), ex))
    elif tipo == "heartbeat":
        cx.execute("UPDATE execucao SET heartbeat_em=? WHERE id=?", (agora(), ex))
    elif tipo == "fim":
        # exit 5 e o estado que nenhum desenho anterior tratava: coleta pendurada
        # nao produz exit code nenhum, entao o agente o sintetiza ao matar o filho.
        mapa = {0: "concluida", 1: "concluida", 2: "sem_dados", 3: "bloqueada",
                4: "infra", 5: "travada"}
        code = c.get("exit_code")
        estado = mapa.get(code, "infra")
        cx.execute("""UPDATE execucao SET estado=?, terminado_em=?, duracao_s=?, exit_code=?,
                      alertas=?, log_resumo=?, png_falha=? WHERE id=?""",
                   (estado, agora(), c.get("duracao_s"), code,
                    json.dumps(c.get("alertas") or [], ensure_ascii=False),
                    (c.get("log_resumo") or "")[:4000], c.get("png_falha"), ex))
        if estado != "concluida":
            cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,texto)
                          VALUES(?,?,?,?,?)""",
                       (agora(), "coleta_" + estado, "alta" if estado in ("travada", "bloqueada") else "media",
                        ex, f"execução {ex} terminou como {estado} (exit {code})"))
    cx.execute("UPDATE agentes SET ultimo_contato_em=?, versao_agente=? WHERE id=?",
               (agora(), c.get("versao") or ag["versao_agente"], ag["id"]))
    cx.commit(); cx.close()
    return jsonify(ok=True)


# ------------------------------------------------------------------ busca
def _conta_e_mesa(cx, uid, instancia):
    """A conta do SEI e a mesa desta pessoa nesta instalação.

    A busca roda com o login DELA — é isso que faz o resultado continuar sendo
    espelho: o SEI devolve o que devolveria a ela. Sem credencial cadastrada não
    há busca, e a mensagem diz isso em vez de devolver lista vazia.
    """
    cfg = cfgmod.ler(cx, uid, instancia)
    conta = (cfg.get("sei_login") or "").strip() or None
    mesas = [r["unidade"] for r in cx.execute(
        "SELECT unidade FROM usuario_unidade WHERE usuario_id=? AND instancia=? "
        "ORDER BY principal DESC, unidade", (uid, instancia))]
    return conta, mesas


@app.get("/busca")
@exige_login
def tela_busca():
    cx = conectar()
    uid = request.usuario["usuario_id"]
    inst = request.args.get("instancia") or cfgmod.ler(cx, uid)["sistema"]
    if not perfil_sei.existe(inst) or not perfil_sei.perfil(inst)["disponivel_busca"]:
        inst = perfil_sei.para_busca()[0]
    conta, mesas = _conta_e_mesa(cx, uid, inst)
    recentes = buscamod.minhas(cx, uid)
    # QUEM VAI EXECUTAR, dito ANTES do botão. Sem estação capaz não há busca, e
    # descobrir isso depois de preencher dez campos e esperar foi o defeito
    # relatado: a tela afirmava que a estação estava pesquisando quando não havia
    # estação nenhuma.
    ag, sem_estacao, como_resolver = buscamod.quem_executa(cx, uid, instancia=inst)
    cx.close()
    # O CSRF é COOKIE + campo, como nas outras telas: o script preenche todo
    # `.csrf` com o valor do cookie. Duas convenções para a mesma coisa é como
    # um formulário passa a falhar só numa tela.
    resp = make_response(render_template(
        "busca.html", pagina="busca", u=request.usuario,
        instancias=[{"id": k, "nome": perfil_sei.INSTANCIAS[k]["nome"],
                     "medidos": perfil_sei.INSTANCIAS[k]["busca_ids_medidos"]}
                    for k in perfil_sei.para_busca()],
        instancia=inst, conta=conta, mesas=mesas, recentes=recentes,
        estacao=(ag["nome_estacao"] if ag else None),
        sem_estacao=sem_estacao, como_resolver=como_resolver,
        espera_max_s=buscamod.PEGAR_TETO_S,
        tipos_data=perfil_sei.TIPOS_DATA))
    resp.set_cookie(COOKIE_CSRF, seg.novo_csrf(), samesite="Lax",
                    secure=cookie_seguro(), path="/")
    return resp


@app.post("/api/busca")
@exige_login
def busca_pedir():
    confere_csrf()
    c = request.get_json(silent=True) or {}
    uid = request.usuario["usuario_id"]
    inst = c.get("instancia") or perfil_sei.PADRAO
    cx = conectar()
    conta, mesas = _conta_e_mesa(cx, uid, inst)
    mesa = c.get("mesa") or (mesas[0] if mesas else None)
    if mesa and mesa not in mesas:
        cx.close()
        return jsonify(erro="essa mesa não é sua nesta instalação"), 403
    bid, erro, em_curso = buscamod.pedir(cx, uid, inst, conta, mesa,
                                         c.get("filtros"), ip=ip_cliente())
    cx.commit(); cx.close()
    if erro:
        # 409 DEGRADA: devolve qual busca está em curso, para a tela mostrar o
        # progresso dela em vez de um erro sem saída.
        return jsonify(erro=erro, em_curso=em_curso), (409 if em_curso else 400)
    return jsonify(busca_id=bid), 202


@app.get("/api/busca/<int:bid>")
@exige_login
def busca_estado(bid):
    cx = conectar()
    buscamod.varrer(cx)
    d = buscamod.ler(cx, bid, request.usuario["usuario_id"], ip=ip_cliente())
    cx.commit(); cx.close()
    if not d:
        return jsonify(erro="busca não encontrada"), 404
    return jsonify(**d)


@app.post("/api/busca/<int:bid>/cancelar")
@exige_login
def busca_cancelar(bid):
    confere_csrf()
    cx = conectar()
    ok = buscamod.cancelar(cx, bid, request.usuario["usuario_id"], ip=ip_cliente())
    cx.commit(); cx.close()
    return jsonify(ok=ok)


@app.get("/api/agente/busca")
def agente_busca():
    """A próxima busca do dono deste agente. Mesmo contrato da tarefa de coleta."""
    ag, erro = agente_autenticado()
    if not ag:
        return jsonify(erro=erro), 401
    if not ag["dono_usuario_id"]:
        return jsonify(buscar=False, motivo="agente sem dono não tem credencial do SEI")
    cx = conectar()
    buscamod.varrer(cx)
    inst = cfgmod.ler(cx, ag["dono_usuario_id"])["sistema"]
    tarefa = buscamod.entregar(cx, ag["dono_usuario_id"], inst)
    cx.commit(); cx.close()
    if not tarefa:
        return jsonify(buscar=False, motivo="nenhuma busca pedida")
    # O PERFIL DA INSTALAÇÃO vai junto: URL de login, órgão e domínio saem daqui,
    # não de constante no coletor. É o que faz a mesma estação atender as duas
    # instalações sem um `if` por instância espalhado pelo arquivo.
    tarefa["perfil"] = perfil_sei.envelope_do_coletor(tarefa["instancia"])
    return jsonify(buscar=True, **tarefa)


@app.post("/api/agente/busca/<int:bid>")
def agente_busca_resultado(bid):
    ag, erro = agente_autenticado()
    if not ag:
        return jsonify(erro=erro), 401
    cx = conectar()
    dona = cx.execute("SELECT usuario_id FROM busca WHERE id=?", (bid,)).fetchone()
    if not dona or dona["usuario_id"] != ag["dono_usuario_id"]:
        cx.close()
        return jsonify(erro="esta busca não é do dono deste agente"), 404
    estado, motivo = buscamod.receber(cx, bid, request.get_json(silent=True) or {},
                                      ip=ip_cliente())
    cx.commit(); cx.close()
    return jsonify(estado=estado, motivo=motivo)


@app.post("/api/poco/plano")
def poco_plano():
    """O que esta corrida precisa ler nesta mesa. Chamado ENTRE a listagem e a
    leitura do detalhe — e por isso que a coleta foi redividida em duas metades.

    Corpo: {execucao_id, mesa, parser_versao, itens:[{id,hash,cega}]}
    Resposta: {veredito: {id: completa|so_acompanhamento|pular|canario|em_leitura}}
    """
    ag, erro = agente_autenticado()
    if not ag:
        return jsonify(erro=erro), 401
    c = request.get_json(silent=True) or {}
    mesa, itens = c.get("mesa"), c.get("itens")
    if not mesa or not isinstance(itens, list):
        return jsonify(erro="corpo sem mesa ou sem itens"), 400
    # Coletor de outra versao entende os campos de outro jeito. Em vez de servir
    # bloco cujo significado mudou, manda ler tudo: degrada para o comportamento
    # de antes do poco, que e o pior caso aceitavel.
    if c.get("parser_versao") != poco.PARSER_VERSAO:
        return jsonify(veredito={i.get("id"): "completa" for i in itens if i.get("id")},
                       resumo={"completa": len(itens)},
                       parser_versao=poco.PARSER_VERSAO,
                       motivo="versao do parser diferente da do servidor: leitura completa")

    # O ESCOPO. Mesmo recorte da publicacao: a intencao gravada no agente E o
    # vinculo do dono. Sem isto, um agente perguntaria pelo estado de processos
    # de uma mesa em que a pessoa nao esta lotada — e a resposta ("pular" ou
    # "completa") ja e, por si, informacao sobre a carteira alheia.
    esperadas = set(json.loads(ag["unidades_esperadas"] or "[]"))
    if ag["dono_usuario_id"]:
        do_dono = set(unidades_do(ag["dono_usuario_id"]))
        if do_dono:
            esperadas &= do_dono
    # FALHA FECHADO, como o irmao /api/agente/resultado. Com `if esperadas`, o
    # conjunto VAZIO virava passe livre — e ha dois caminhos reais para vazio:
    # agente recem-criado para conta sem vinculo, e vinculo REVOGADO. Revogar o
    # acesso de alguem nao pode DESLIGAR a trava.
    if mesa not in esperadas:
        return jsonify(erro="mesa fora do escopo do agente", mesa=mesa), 409

    ex = c.get("execucao_id")
    cx = conectar()
    if ex is not None:
        linha = cx.execute("SELECT estado FROM execucao WHERE id=? AND agente_id=?",
                           (ex, ag["id"])).fetchone()
        if not linha:
            cx.close()
            return jsonify(erro="execução não é deste agente"), 404
        if linha["estado"] not in ("entregue", "em_curso"):
            cx.close()
            return jsonify(erro=f"execução já encerrada como {linha['estado']}"), 409
    # A instância vem do agente, não do corpo: quem publica não escolhe em qual
    # instalação o plano é lido. Sem `sistema` configurado, a leitura do que
    # existe é SESAB — a única instalação que o sistema coletou até hoje.
    # UMA definição para as três rotas do agente: a consulta estava escrita aqui
    # e o padrão em mais dois lugares, e discordar significa ler o poço de um
    # órgão para responder à coleta do outro.
    inst = instancia_do_agente(cx, ag)
    r = poco.plano(cx, mesa, itens, inst, execucao_id=ex,
                   dono_usuario_id=ag["dono_usuario_id"])
    cx.commit(); cx.close()
    return jsonify(**r)


@app.post("/api/agente/resultado")
def resultado():
    """Recebe o JSON da coleta e ingere. Publicacao fora das unidades esperadas
    do agente e recusada: uma unidade pertence a UM agente."""
    ag, erro = agente_autenticado()
    if not ag:
        return jsonify(erro=erro), 401
    c = request.get_json(silent=True) or {}
    dados, ex = c.get("dados"), c.get("execucao_id")
    if not isinstance(dados, list) or not dados:
        return jsonify(erro="corpo sem dados"), 400
    # O escopo gravado no agente é a INTENÇÃO; o vínculo do dono é a AUTORIDADE.
    # Reconferir aqui é o que faz revogar um vínculo fechar a porta também para o
    # agente já pareado — sem isso, quem foi desvinculado de uma unidade continua
    # publicando nela até alguém lembrar de reconfigurar a estação.
    esperadas = set(json.loads(ag["unidades_esperadas"] or "[]"))
    if ag["dono_usuario_id"]:
        do_dono = set(unidades_do(ag["dono_usuario_id"]))
        # Dono AINDA sem vínculo é instalação nova: as unidades só existem depois
        # da primeira coleta, e o escopo veio de um admin digitando a sigla à mão.
        # Não abre porta — o autosserviço já recorta pelo vínculo antes de gravar,
        # então escopo não-vazio com dono sem vínculo só pode ter vindo do admin.
        if do_dono:
            esperadas &= do_dono
    vistas = set()
    for d in dados:
        vistas |= set(d.get("mesas_coleta") or [d.get("mesa_coleta")] or [])
        # `mesas_conta` e `mesas_falhas` entram na conferência porque é DELAS que
        # `ingestao.inventario()` tira as unidades para as quais cria snapshot.
        # Conferir só `mesas_coleta` deixava passar a unidade que realmente
        # decide o que nasce no banco — a porta olhava um campo e a ingestão lia
        # outro.
        vistas |= set(d.get("mesas_conta") or [])
        vistas |= set(d.get("mesas_falhas") or [])
    # Sem o "if esperadas", escopo vazio virava passe livre: o agente configurado
    # como o MAIS restrito seria o unico sem limite nenhum.
    fora = {v for v in vistas if v} - esperadas
    # RECORTA, não recusa o lote inteiro. O agente coleta todas as mesas da conta
    # (é o que o coletor sabe fazer) e o servidor sabe quais delas esta pessoa
    # pode publicar. Recusar tudo fazia "só as que eu escolher" garantir 409 em
    # toda execução — a tela prometia coleta mais rápida e entregava coleta
    # nenhuma. O recorte é MAIS restritivo que a recusa, não menos: o dado fora do
    # escopo continua sem entrar, e agora o de dentro entra.
    if fora and not (esperadas & {v for v in vistas if v}):
        # Nada dentro do escopo: aí não há o que recortar, e recusar é o certo —
        # a publicação inteira é de outra pessoa.
        cx = conectar()
        cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,texto) VALUES(?,?,?,?,?)""",
                   (agora(), "unidade_inesperada", "alta", ex,
                    "agente publicou unidade fora do escopo: " + ", ".join(sorted(fora))))
        cx.commit(); cx.close()
        return jsonify(erro="unidade fora do escopo do agente", unidades=sorted(fora)), 409

    # A execucao tem de ser DESTE agente e estar aberta. Sem isso, um agente
    # publicava sobre a execucao de outro (procedencia falsa no historico) e um
    # execucao_id inexistente estourava a FK como 500 sem tratamento.
    cxv = conectar()
    dono = cxv.execute("SELECT * FROM execucao WHERE id=? AND agente_id=?",
                       (ex, ag["id"])).fetchone()
    cxv.close()
    if not dono:
        return jsonify(erro="execução não é deste agente"), 404
    # Uma execução publica UMA vez. Sem esta recusa, a segunda publicação tentava
    # recriar o mesmo (execucao_id, unidade) e estourava a chave única como 500 —
    # resposta que não diz ao agente se ele deve tentar de novo nem ao operador o
    # que houve. O caso legítimo de reenviar tem nome próprio: nova janela.
    cxj = conectar()
    ja = cxj.execute("SELECT COUNT(*) FROM snapshot WHERE execucao_id=?", (ex,)).fetchone()[0]
    cxj.close()
    if ja:
        return jsonify(erro="esta execução já publicou; peça uma nova tarefa",
                       snapshots=ja), 409
    if dono["estado"] not in ("entregue", "em_curso"):
        return jsonify(erro=f"execução já encerrada como {dono['estado']}"), 409

    import tempfile
    from ingestao import ingerir
    tmp = os.path.join(tempfile.gettempdir(), f"sei360_{ex}.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False)
    # coletado_em vem DECLARADO pelo agente (mtime do arquivo que ele coletou).
    # Sem isso, o mtime do temporario criado aqui carimbaria toda publicacao como
    # "coletado agora" — inclusive a republicacao de um arquivo de tres dias.
    carimbo = c.get("coletado_em")
    if carimbo:
        try:
            quando = janelas.com_fuso(carimbo)
            # Carimbo no futuro ficaria "coletado hoje" para sempre: o semaforo
            # nunca envelheceria e o painel jamais admitiria estar velho.
            if quando > datetime.now(TZ) + timedelta(minutes=10):
                carimbo = None
        except (TypeError, ValueError):
            carimbo = None
    # `escopo` recorta as unidades que podem virar snapshot. O agente coleta todas
    # as mesas da conta — é o que o coletor sabe fazer —, e é aqui que se decide
    # quais delas esta pessoa pode publicar.
    # `dono` é DE QUEM é esta coleta: o dono do agente que publicou. É o que faz o
    # dado desta pessoa ser dela — cada uma entra no SEI com o login dela e traz a
    # carteira dela, e ninguém consome a coleta de outro.
    #
    # NULL só na estação de bootstrap, que é como toda instalação começa: aquela
    # coleta fica marcada como COMPARTILHADA e vale para quem tem vínculo na
    # unidade, até a pessoa ter a própria.
    # `instancia` É DE QUEM PUBLICA, e o servidor sabe qual é: a configuração do
    # dono do agente. Sem este argumento a ingestão caía em 'SEI-SESAB' por
    # padrão — toda coleta da FESF nasceria carimbada como SESAB, misturada com a
    # de outro órgão nos índices e nos relatórios. Quando o coletor declarar a
    # instalação no próprio JSON, é a DECLARAÇÃO que vale: ela é a única que
    # esteve lá. Divergir das duas vira alerta, não escolha silenciosa.
    cxi = conectar()
    instancia_ag = instancia_do_agente(cxi, ag)
    cxi.close()
    rel = ingerir(tmp, forcar=False, agente_id=ag["id"], execucao_id=ex,
                  coletado_em=carimbo, escopo=sorted(esperadas),
                  dono=ag["dono_usuario_id"], instancia=instancia_ag)
    os.unlink(tmp)
    return jsonify(ok=True, relatorio=rel, carimbo=carimbo or "ausente — snapshots marcados")


@app.after_request
def cabecalhos(resp):
    """Sem isto o HTML com a carteira inteira fica no cache de disco e no bfcache:
    numa estacao compartilhada, o botao Voltar depois do logout devolve a tela
    com os processos. `no-store` e o unico valor que impede as duas coisas.

    A CSP e fechada porque a pagina nao carrega NADA de fora — nem fonte, nem
    script, nem imagem. 'unsafe-inline' fica so em script/style porque o painel e
    um artefato autocontido por decisao de projeto (ele tambem roda como arquivo
    solto, sem servidor nenhum).
    """
    # ATRIBUICAO, e nao `setdefault`, para tudo que nao seja estatico versionado.
    # `send_file` do Werkzeug ja escreve `Cache-Control: no-cache` sozinho — e ai
    # o `setdefault` abaixo virava no-op justamente na planilha, que e a resposta
    # com MAIS dado nominal do sistema. `no-cache` autoriza ARMAZENAR (so exige
    # revalidar) e nao traz `private`; e como o corpo vem de um BytesIO, a
    # resposta nao tem ETag nem Last-Modified para revalidar contra.
    if not (request.path.startswith("/estatico/") and resp.cache_control.max_age):
        resp.headers["Cache-Control"] = "no-store, private"
    if request.path.startswith("/estatico/vendor/") and resp.cache_control.max_age:
        # `immutable` poupa ate a revalidacao do F5: sem ele o navegador reconsulta
        # o arquivo a cada recarga manual, que e justamente o que se faz quando a
        # tela parece errada — e o vendor nunca e a causa.
        resp.cache_control.public = True
        resp.cache_control.immutable = True
    resp.headers.setdefault("Cache-Control", "no-store, private")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    return comprimir(resp)


# Limite: abaixo disto o gzip custa mais CPU do que economiza rede.
GZIP_MINIMO = 1400


def comprimir(resp):
    """Comprime a resposta quando o navegador aceita e vale a pena.

    O painel embute a carteira inteira no HTML — decisão de projeto, porque ele
    também roda como arquivo solto, sem servidor. O preço medido: **2.604 KB por
    abertura**, sem compressão nenhuma. Comprimido dá **306 KB**: 88% a menos.
    Com seis pessoas abrindo três vezes ao dia, são 915 MB por mês contra 108 MB —
    numa rede de órgão, e num painel que existe para ser aberto todo dia de manhã.

    Não é `flask-compress` de propósito: uma dependência a mais na imagem para
    quinze linhas que o `gzip` da biblioteca padrão já faz.

    O que a função NÃO toca:
      * resposta em streaming (`send_file` do XLSX) — `direct_passthrough`;
      * resposta já codificada, para não comprimir duas vezes;
      * status fora da faixa 200-299, que raramente tem corpo que compense.
    `Vary: Accept-Encoding` entra sempre que a decisão dependeu do cabeçalho do
    cliente: sem ele, um intermediário entregaria a versão comprimida a quem não
    a aceita. `Cache-Control: no-store` continua onde está — a proteção contra o
    botão Voltar depois do logout depende dele.
    """
    import gzip as _gzip

    aceita = request.headers.get("Accept-Encoding", "")
    resp.headers.add("Vary", "Accept-Encoding")
    if ("gzip" not in aceita
            or resp.direct_passthrough
            or resp.status_code < 200 or resp.status_code >= 300
            or "Content-Encoding" in resp.headers):
        return resp
    tipo = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    if not (tipo.startswith("text/") or tipo in (
            "application/json", "application/javascript", "image/svg+xml")):
        return resp
    corpo = resp.get_data()
    if len(corpo) < GZIP_MINIMO:
        return resp
    # NÍVEL 3, e não 6. Medido no painel do gestor: 143,6 ms contra 120,6 ms,
    # com 398,8 KB no fio em vez de 316,6 KB. Num processo em que 93% do tempo
    # da tela é CPU e o GIL serializa os workers, 23 ms de CPU custam mais que
    # 82 KB de rede — e a diferença aparece justamente quando várias pessoas
    # abrem o painel ao mesmo tempo, que é quando ela importa.
    resp.set_data(_gzip.compress(corpo, 3))
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Content-Length"] = str(len(resp.get_data()))
    return resp


# --------------------------------------------------------------- saude
@app.get("/saude")
def saude():
    """Sonda do orquestrador: diz se o processo responde e se o banco abre.

    NAO devolve o detalhe por unidade. Este endpoint fica exposto sem sessao, e
    sigla de unidade com contagem e data de coleta e inventario da carteira — o
    suficiente para alguem de fora saber onde ha processo parado e desde quando.
    Quem precisa do detalhe faz login; ele esta no painel e no /admin.
    """
    try:
        cx = conectar()
        n = cx.execute("SELECT COUNT(*) FROM snapshot WHERE estado='corrente'").fetchone()[0]
        cx.close()
        # O EXECUTOR DE BUSCA, se houver um. Booleano e número — nada sobre a
        # carteira, nada sobre quem está pesquisando: esta rota fica exposta sem
        # sessão. É a diferença entre "há navegador nesta imagem" (que a tela
        # pergunta a cada requisição) e "há quem drene a fila agora".
        try:
            import atendente as _at
            _busca = {"laco_vivo": _at.vivo(), "vagas_livres": _at.vagas_livres(),
                      "vagas": _at.LIMITE}
        except Exception:                                      # noqa: BLE001
            _busca = {"laco_vivo": False, "vagas_livres": None, "vagas": None}
    except Exception as e:                                  # noqa: BLE001
        return jsonify(ok=False, erro=type(e).__name__), 503
    return jsonify(ok=True, unidades_correntes=n, versao=VERSAO_AGENTE, busca=_busca)


# O EXECUTOR DE BUSCA SOBE COM A APLICAÇÃO. Aqui, e não dentro de `__main__`,
# porque em produção quem importa este módulo é o gunicorn, que nunca executa
# aquele bloco — foi assim que a varredura de janelas já deixou de rodar uma vez.
# `iniciar()` é idempotente e devolve False quando o laço está desligado por
# variável (SEI360_ATENDENTE=0), que é como se separa painel de execução em dois
# serviços do EasyPanel usando a mesma imagem.
try:
    import atendente as _atendente
    # NÃO SOBE NO PAI DO RELOADER. Com o reloader do Flask, este módulo é
    # importado duas vezes — no processo pai e no filho — e subiriam DOIS laços
    # sondando a mesma fila. A reivindicação é atômica, então não há execução
    # dupla; mas são duas conexões, o dobro das sondagens, e um comportamento em
    # desenvolvimento diferente do de produção sem nada dizendo isso.
    # O GUARDA LÊ O QUE ESTE PROJETO DE FATO USA. A versão anterior olhava só
    # `FLASK_DEBUG` — e o Flask 3 NUNCA escreve essa variável: quem a escreve é o
    # CLI (`flask run`), que este projeto não usa. Aqui o debug vem de
    # `app.run(debug="--debug" in sys.argv)`, então o guarda era inerte e os dois
    # laços subiam assim mesmo.
    _debug = ("--debug" in sys.argv
              or os.environ.get("FLASK_DEBUG", "").strip().lower()
              not in ("", "0", "false", "no"))
    if not (_debug and not os.environ.get("WERKZEUG_RUN_MAIN")):
        _atendente.iniciar()
except Exception as _ex:                                       # noqa: BLE001
    print(f"atendente de busca não subiu: {type(_ex).__name__}", flush=True)

# A COLETA EM MODO SERVIDOR SOBE JUNTO, no MESMO processo que venceu a
# eleição do atendente — nunca disputa eleição própria (ver o cabeçalho de
# `coleta_servidor.py`: os dois compartilham o teto de memória do Chromium, e
# isso só funciona se forem threads do mesmo processo). Bloco separado do de
# cima de propósito: uma falha aqui não deve ser confundida com falha da
# busca, nem impedi-la de subir.
try:
    import coleta_servidor as _coleta_servidor
    if not (_debug and not os.environ.get("WERKZEUG_RUN_MAIN")):
        _coleta_servidor.iniciar()
except Exception as _ex:                                       # noqa: BLE001
    print(f"coleta em modo servidor não subiu: {type(_ex).__name__}", flush=True)


class _SemSegredoNoLog(logging.Filter):
    """O servidor de desenvolvimento também registra o caminho da requisição.

    Em produção quem cuida disso é `gunicorn_conf.py`; aqui é o mesmo problema
    com outro dono. `/recuperar/<token>` no terminal de quem desenvolve é o token
    no histórico do terminal, no `screen`, no arquivo de log de quem redireciona
    a saída. Some só o segredo; o resto da linha fica.
    """

    def filter(self, registro):
        try:
            msg = registro.getMessage()
        except Exception:
            return True
        for prefixo in seg.SEGREDO_NO_CAMINHO:
            if prefixo not in msg:
                continue
            antes, _, resto = msg.partition(prefixo)
            fim = resto.find(" ")
            registro.msg = (antes + seg.caminho_sem_segredo(prefixo)
                            + (resto[fim:] if fim >= 0 else ""))
            registro.args = ()
            break
        return True


if __name__ == "__main__":
    logging.getLogger("werkzeug").addFilter(_SemSegredoNoLog())
    banco.migrar()
    host = "0.0.0.0" if "--publico" in sys.argv else "127.0.0.1"
    porta = int(os.environ.get("PORT", 8360))
    print(f"SEI360 em http://{host}:{porta}  (banco: {banco.BANCO})")
    app.run(host=host, port=porta, debug="--debug" in sys.argv, threaded=True)
