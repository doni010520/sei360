# -*- coding: utf-8 -*-
"""
Senha, sessao, CSRF e assinatura do agente — tudo com a biblioteca padrao.

POR QUE STDLIB E NAO passlib/bcrypt
-----------------------------------
hashlib.scrypt resolve, e cada dependencia a menos e uma superficie a menos para
manter atualizada num servidor que hospeda dado pessoal de saude.

A CONTA DO PAINEL NAO E A CONTA DO SEI. Este modulo nunca ve, guarda ou valida
senha do SEI — ele so conhece a senha do proprio SEI360.
"""
import hashlib, hmac, secrets, re
from datetime import datetime, timedelta

from banco import agora, TZ

# maxmem NAO e enfeite: n=2**15 e r=8 pedem 128*n*r = 32 MiB, exatamente o teto
# padrao do OpenSSL — e o teto e exclusivo, entao sem isto TODA chamada levanta
# "memory limit exceeded" e ninguem consegue nem criar conta.
SCRYPT = dict(n=2**15, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)
ALGO = "scrypt-n15-r8-p1"

# Hash-isca: e-mail inexistente roda contra um hash real para gastar o MESMO
# tempo do caminho valido. Sem isso, a diferenca de latencia responde "esta conta
# existe?" a quem so tem a lista de e-mails.
_SAL_ISCA = b"isca-sei360-0123"
_HASH_ISCA = hashlib.scrypt(b"isca", salt=_SAL_ISCA, **SCRYPT)

MIN_SENHA = 12
# As piores senhas nao sao "as 200 mais comuns do mundo" e sim as obvias DAQUI.
# Lista curta e local vale mais que arquivo de 200 linhas que ninguem revisa.
PROIBIDAS = {
    "123456789012", "senha12345678", "sei360sei360", "administrador",
    "qwertyuiop12", "12345678", "password", "senha123", "sesab2026",
    "sei360@2026", "fesfsus2026", "mudar@123456",
}


def hash_senha(senha: str):
    sal = secrets.token_bytes(16)
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, **SCRYPT), sal


def conferir_senha(senha: str, esperado: bytes, sal: bytes) -> bool:
    if not esperado or not sal:
        # conta sem senha definida: gasta o tempo da isca e recusa
        hmac.compare_digest(_HASH_ISCA, _HASH_ISCA)
        return False
    calc = hashlib.scrypt(senha.encode("utf-8"), salt=sal, **SCRYPT)
    return hmac.compare_digest(calc, esperado)


def gastar_tempo_isca():
    hashlib.scrypt(b"isca", salt=_SAL_ISCA, **SCRYPT)


def criticar_senha(senha: str, email: str = "") -> str | None:
    """Devolve o motivo da recusa, ou None se a senha serve."""
    if len(senha) < MIN_SENHA:
        return f"A senha precisa de pelo menos {MIN_SENHA} caracteres."
    if senha.lower() in PROIBIDAS:
        return "Essa senha é previsível demais. Escolha outra."
    if email and email.split("@")[0].lower() in senha.lower():
        return "A senha não pode conter o seu login."
    if re.fullmatch(r"(.)\1+", senha):
        return "A senha não pode ser um único caractere repetido."
    return None


# ---------------------------------------------------------------- sessao
def novo_token():
    """Token opaco. O banco guarda so o SHA-256: quem ler o banco nao consegue
    se passar por ninguem com o que encontrou la."""
    t = secrets.token_urlsafe(32)
    return t, hashlib.sha256(t.encode()).digest()


def hash_token(t: str) -> bytes:
    return hashlib.sha256(t.encode()).digest()


ABS_PADRAO_H = 12        # expiracao absoluta
ABS_LEMBRAR_D = 30       # "lembrar este dispositivo"
INATIVIDADE_MIN = 30


def validade(lembrar: bool):
    base = datetime.now(TZ)
    fim = base + (timedelta(days=ABS_LEMBRAR_D) if lembrar else timedelta(hours=ABS_PADRAO_H))
    return fim.isoformat(timespec="seconds")


def sessao_viva(linha) -> bool:
    """Vence por expiracao absoluta OU por inatividade. Só a absoluta deixaria
    uma aba esquecida num computador compartilhado valendo o dia inteiro."""
    if linha["revogada_em"]:
        return False
    ag = datetime.fromisoformat(agora())
    if datetime.fromisoformat(linha["expira_em"]) <= ag:
        return False
    ultimo = linha["ultimo_uso_em"] or linha["criado_em"]
    if ultimo and ag - datetime.fromisoformat(ultimo) > timedelta(minutes=INATIVIDADE_MIN):
        return False
    return True


# ---------------------------------------------------------------- CSRF
def novo_csrf():
    return secrets.token_urlsafe(24)


def csrf_ok(cookie: str, enviado: str) -> bool:
    if not cookie or not enviado:
        return False
    return hmac.compare_digest(cookie, enviado)


# ---------------------------------------------------------------- agente
# Bearer sobre HTTPS MAIS HMAC do corpo: se um proxy do orgao terminar o TLS, o
# HMAC continua provando que o corpo nao foi trocado no caminho.
JANELA_ASSINATURA_S = 300


def assinar(token: str, ts: str, corpo: bytes) -> str:
    return hmac.new(token.encode(), ts.encode() + b"." + (corpo or b""), hashlib.sha256).hexdigest()


def assinatura_ok(token: str, ts: str, corpo: bytes, assinatura: str) -> tuple[bool, str]:
    if not ts or not assinatura:
        return False, "faltam cabecalhos de assinatura"
    try:
        quando = datetime.fromisoformat(ts)
    except ValueError:
        return False, "timestamp invalido"
    delta = abs((datetime.now(TZ) - quando).total_seconds())
    if delta > JANELA_ASSINATURA_S:
        return False, f"timestamp fora da janela ({int(delta)}s)"
    return hmac.compare_digest(assinar(token, ts, corpo), assinatura), "assinatura nao confere"


# ------------------------------------------------------ segredo no caminho
#
# Caminhos cujo ÚLTIMO segmento é segredo. O log de acesso — do gunicorn em
# produção, do werkzeug no desenvolvimento — registra o caminho da requisição, e
# `/recuperar/<token>` carrega justamente o que dá acesso à conta sem a senha.
# Em texto no log do container, ele é legível pelo painel do provedor e por
# qualquer backup dele, durante os 30 minutos em que vale.
#
# LISTA, e não expressão regular geral: o custo de errar para menos aqui é vazar
# credencial, então cada caminho novo que carregar segredo entra aqui de
# propósito, por alguém que pensou nisso.
SEGREDO_NO_CAMINHO = ("/recuperar/",)


def atomos_sem_segredo(a: dict) -> dict:
    """Os átomos do log de acesso, sem o segredo. Muda o dicionário no lugar.

    O ÁTOMO QUE IMPORTA É `r`, NÃO `U` — e errar isso é escrever uma proteção que
    não protege. O formato PADRÃO do gunicorn é

        %(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"

    e ele não usa `%(U)s` em lugar nenhum: quem imprime o caminho ali é `%(r)s`,
    montado do RAW_URI como "GET /recuperar/<token> HTTP/1.1". Uma primeira versão
    reescrevia só `U`, passava num teste que olhava `U`, e deixava o token intacto
    na linha que era realmente impressa.

    Mora aqui, e não em `gunicorn_conf.py`, porque o `gunicorn` não instala no
    Windows — deixar a regra lá a tornaria impossível de testar na máquina onde o
    projeto é desenvolvido, que foi exatamente como o erro passou.
    """
    limpo = caminho_sem_segredo(a.get("U") or "")
    if limpo == (a.get("U") or ""):
        return a
    a["U"] = limpo
    # `r` é "MÉTODO caminho PROTOCOLO", e o caminho dele traz a query string.
    partes = (a.get("r") or "").split(" ")
    a["r"] = f"{partes[0]} {limpo} {partes[-1]}" if len(partes) >= 3 else limpo
    return a


def caminho_sem_segredo(caminho: str) -> str:
    """O caminho com o segredo trocado por `<omitido>`; os outros, intactos.

    O PREFIXO FICA. Saber que houve um pedido de recuperação, de que IP e com que
    resposta é exatamente o que a auditoria precisa; o que sai é só o segredo.
    """
    c = caminho or ""
    for prefixo in SEGREDO_NO_CAMINHO:
        if c.startswith(prefixo):
            return prefixo + "<omitido>"
    return c


# ---------------------------------------------------------------- bloqueio
LIMITE_FALHAS = 5
JANELA_FALHAS_MIN = 15
BLOQUEIO_MIN = 15
BLOQUEIO_REINCIDENTE_MIN = 60
LIMITE_IP_MIN = 20


def bloqueio_ativo(usuario) -> int:
    """Minutos restantes de bloqueio, 0 se liberado."""
    if not usuario or not usuario["bloqueado_ate"]:
        return 0
    falta = datetime.fromisoformat(usuario["bloqueado_ate"]) - datetime.now(TZ)
    return max(0, int(falta.total_seconds() // 60) + 1) if falta.total_seconds() > 0 else 0


def ip_excedeu(cx, ip) -> bool:
    """Conta so as tentativas QUE FALHARAM.

    Contando tambem os acertos, uma unidade inteira atras de um mesmo NAT — que
    e a topologia normal de orgao publico — estoura o limite na segunda-feira de
    manha por uso legitimo, e o painel tranca para todo mundo. Login que deu
    certo nao e sinal de ataque nenhum; o que se limita e a tentativa e erro.
    """
    corte = (datetime.now(TZ) - timedelta(minutes=1)).isoformat(timespec="seconds")
    n = cx.execute("SELECT COUNT(*) FROM tentativas_login WHERE ip=? AND ts>? AND sucesso=0",
                   (ip, corte)).fetchone()[0]
    return n >= LIMITE_IP_MIN


def _corte_de_falhas(cx, usuario, email, desde_minutos):
    """De quando contar as falhas: nem antes do ultimo ACERTO, nem antes da
    ultima TROCA DE SENHA.

    A janela de tempo sozinha nao bastava. `registrar_sucesso` zera `falhas_seq`
    na linha do usuario, mas quem decide o bloqueio le a tabela
    `tentativas_login` — e as falhas de antes da entrada correta continuavam
    contando. Medido em producao: a conta bloqueou na 2a falha DEPOIS de um login
    bem-sucedido e de uma troca de senha, porque tres falhas de meia hora antes
    ainda estavam na janela. O efeito para quem usa e o pior possivel: a senha
    que a pessoa acabou de definir e recusada, com a mesma mensagem de senha
    errada.

    Entrar certo e definir senha nova sao as duas provas de posse da conta que o
    sistema aceita. Depois de qualquer uma delas, o passado nao acusa mais.
    """
    corte = (datetime.now(TZ) - timedelta(minutes=desde_minutos)).isoformat(timespec="seconds")
    ultimo_ok = cx.execute(
        "SELECT MAX(ts) FROM tentativas_login WHERE email=? AND sucesso=1",
        (email,)).fetchone()[0]
    for marco in (ultimo_ok, usuario["senha_trocada_em"] if usuario else None):
        # Comparacao de texto: os dois lados saem de `agora()`, mesmo formato e
        # mesmo fuso, e e assim que o resto do arquivo ja compara.
        if marco and marco > corte:
            corte = marco
    return corte


def registrar_falha(cx, usuario, email, ip):
    cx.execute("INSERT INTO tentativas_login(email,ip,ts,sucesso) VALUES(?,?,?,0)",
               (email, ip, agora()))
    if not usuario:
        return 0
    corte = _corte_de_falhas(cx, usuario, email, JANELA_FALHAS_MIN)
    # `>=`, NAO `>`. O carimbo tem precisao de SEGUNDO: com `>`, toda falha
    # ocorrida no mesmo segundo do ultimo acerto era descartada — e uma rajada de
    # tentativas cabe folgada dentro de um segundo. Medido: cinco falhas seguidas
    # depois de um login certo devolviam 401 cinco vezes e nunca bloqueavam. O
    # limite ficou valendo so para quem erra devagar, que e o contrario do alvo.
    recentes = cx.execute(
        "SELECT COUNT(*) FROM tentativas_login WHERE email=? AND sucesso=0 AND ts>=?",
        (email, corte)).fetchone()[0]
    if recentes < LIMITE_FALHAS:
        cx.execute("UPDATE usuarios SET falhas_seq=falhas_seq+1 WHERE id=?", (usuario["id"],))
        return 0
    # reincidencia em 24h dobra a pena: a primeira pode ser dedo trocado, a
    # segunda seguida ja parece alguem tentando adivinhar
    # A pena dobrada tambem para no ultimo acerto: sem isso, quem errou seis
    # vezes de manha, entrou, e errou de novo a tarde pegava 60 minutos por
    # causa da manha.
    dia = _corte_de_falhas(cx, usuario, email, 24 * 60)
    antes = cx.execute(
        "SELECT COUNT(*) FROM tentativas_login WHERE email=? AND sucesso=0 AND ts>=?",
        (email, dia)).fetchone()[0]
    minutos = BLOQUEIO_REINCIDENTE_MIN if antes > LIMITE_FALHAS * 2 else BLOQUEIO_MIN
    ate = (datetime.now(TZ) + timedelta(minutes=minutos)).isoformat(timespec="seconds")
    cx.execute("UPDATE usuarios SET bloqueado_ate=?, falhas_seq=falhas_seq+1 WHERE id=?",
               (ate, usuario["id"]))
    return minutos


def registrar_sucesso(cx, usuario_id, email, ip):
    cx.execute("INSERT INTO tentativas_login(email,ip,ts,sucesso) VALUES(?,?,?,1)",
               (email, ip, agora()))
    cx.execute("UPDATE usuarios SET falhas_seq=0, bloqueado_ate=NULL, ultimo_login_em=? WHERE id=?",
               (agora(), usuario_id))
