# -*- coding: utf-8 -*-
"""
Envio de e-mail pelo Resend — o transporte, e só ele.

POR QUE EXISTE
--------------
Duas portas de entrada precisam de um canal fora da tela: recuperar senha (quem
esqueceu não tem como provar quem é pelo painel) e o segundo fator (um código que
só chega a quem tem a caixa de correio). As duas dependem de o e-mail SAIR, e é
essa a única coisa que este arquivo faz.

O QUE ELE NÃO FAZ, DE PROPÓSITO
-------------------------------
Não decide quem recebe, não monta política, não sabe o que é token nem o que é
código. Quem sabe disso é `acesso.py`. Aqui só entra destinatário, assunto e
corpo — e sai `(ok, erro)`.

SEM DEPENDÊNCIA NOVA
--------------------
`urllib.request` da biblioteca padrão resolve uma requisição POST com JSON. O
projeto já recusou `flask-compress` por quinze linhas que o `gzip` padrão fazia;
um SDK inteiro para um POST seria a mesma troca, pior.

O SEGREDO NUNCA APARECE
-----------------------
A chave da API vai cifrada para `config_email`, com AES-256-GCM e a chave mestra
fora do banco — o mesmo cofre da credencial do SEI e da chave de IA. E o CORPO do
e-mail nunca é registrado: ele carrega justamente o código e o link que dariam
acesso à conta de alguém. O log guarda destinatário mascarado, assunto e
resultado, e nada mais.
"""
import json
import os
import re
import urllib.error
import urllib.request

from banco import agora, registrar

API = "https://api.resend.com/emails"
# 10 s: o envio acontece DENTRO da requisição de quem clicou "entrar". Mais que
# isso e a pessoa acha que a tela travou; menos, e um pico normal do provedor
# vira falha de acesso.
TEMPO_LIMITE_S = 10

# TETO DIARIO PROPRIO, ABAIXO DO TETO DO PROVEDOR. O plano gratuito do Resend
# entrega 100 mensagens por dia; estourar devolve `429 daily_quota_exceeded` e o
# sistema descobre isso no meio do expediente, com o segundo fator ligado e
# ninguem conseguindo entrar. Medido nesta instalacao: 441 eventos de `login` em
# oito dias (~55/dia) com TRES contas em desenvolvimento — e a sessao morre com
# 30 min de inatividade, entao o numero cresce com o uso, nao com o cadastro.
#
# 60 e deliberadamente folgado em relacao ao uso real e apertado em relacao ao
# teto do provedor: bater no NOSSO limite grava alerta e para de enviar; bater no
# DELE seria descobrir pelo 429, sem aviso e sem registro.
TETO_DIARIO = int(os.environ.get("SEI360_EMAIL_TETO_DIA") or 60)

# RESERVA PARA QUEM ESTÁ ENTRANDO. O orçamento diário é um só, e /esqueci é uma
# porta ABERTA, sem sessão: alguém de fora pede recuperação para vinte endereços
# do órgão, três vezes cada, e queima o orçamento antes do meio-dia. Como o login
# com segundo fator é fail-closed, o efeito seria ninguém — nem admin, nem
# gestor — conseguir entrar até a meia-noite, com a volta passando por
# `emergencia.py` no servidor.
#
# Os últimos 20 envios do dia são só do código de acesso. A recuperação para
# antes; entrar continua funcionando.
RESERVA_ACESSO = int(os.environ.get("SEI360_EMAIL_RESERVA") or 20)

# O nome do provedor fica em coluna, não em código: trocar de transporte não
# pode exigir mexer no fluxo de acesso.
PROVEDOR = "resend"

# Ver a nota em `_postar`: o padrão do urllib é banido pelo Cloudflare da Resend.
USER_AGENT = "sei360-mailer/1.0"

# A CAIXA FALSA. `SEI360_EMAIL_FALSO=<arquivo>` faz o envio GRAVAR uma linha JSON
# nesse arquivo em vez de sair pela rede. Existe porque o servidor de teste roda
# em outro processo — trocar a função no processo da suíte não alcançaria ele —
# e porque um teste que dependesse do Resend estar no ar mediria o Resend.
#
# É deliberadamente barulhenta: `ler_config` devolve `falso=True` e a tela de
# administração estampa um aviso. Um sistema que acha que está mandando e-mail e
# não está é pior que um sistema sem e-mail nenhum, e a diferença entre os dois
# é justamente esta variável ligada onde não devia.
def caixa_falsa():
    return os.environ.get("SEI360_EMAIL_FALSO") or None


# --------------------------------------------------------------- configuração
def ler_config(cx):
    """O estado do envio, sem nunca devolver a chave.

    `pronto` é a única coisa que o resto do sistema deveria perguntar: ele já
    junta "tem chave", "tem remetente" e "alguém testou e funcionou". Ligar
    segundo fator sem os três é trancar todo mundo do lado de fora.
    """
    # LER NÃO ESCREVE. O `INSERT OR IGNORE` que abria esta função tomava a trava
    # de escrita única do SQLite mesmo quando não havia nada a inserir — e esta
    # função é chamada na tela de administração e em todo envio. Ler primeiro e
    # só criar a linha quando ela FALTA tira a trava do caminho comum.
    r = cx.execute("SELECT * FROM config_email WHERE id=1").fetchone()
    if not r:
        cx.execute("INSERT OR IGNORE INTO config_email(id) VALUES(1)")
        r = cx.execute("SELECT * FROM config_email WHERE id=1").fetchone()
    tem_chave = bool(r["chave"])
    remetente = (r["remetente"] or "").strip()
    return {
        "provedor": r["provedor"] or PROVEDOR,
        "falso": caixa_falsa(),
        "tem_chave": tem_chave,
        "remetente": remetente,
        "responder_para": (r["responder_para"] or "").strip(),
        "testado_em": r["testado_em"],
        "teste_ok": bool(r["teste_ok"]),
        "teste_erro": r["teste_erro"],
        "envio_em": r["envio_em"],
        "envio_erro": r["envio_erro"],
        "atualizado_em": r["atualizado_em"],
        # PRONTO exige o teste ter passado E A CHAVE AINDA ABRIR. "Configurado" e
        # "funciona" são coisas diferentes, e a diferença entre as duas é uma
        # conta que não entra mais.
        #
        # A abertura da chave entra aqui porque ela é a única parte de `pronto`
        # que mora FORA do banco: num redeploy que preserve o volume mas perca
        # `SEI360_CHAVE_MESTRA`, os bytes cifrados continuam na coluna e
        # `teste_ok` continua 1 — a tela estampava "pronto" em verde e
        # `salvar_politica` deixava armar o segundo fator sobre um envio que já
        # não funcionava. Custa uma decifragem de 32 bytes por leitura.
        "pronto": bool(tem_chave and remetente and r["teste_ok"]
                       and abrir_chave(cx) is not None),
    }


def guardar_chave(cx, chave, usuario_id, ip=None):
    """A chave da API vai para o mesmo cofre da credencial do SEI.

    Mesma regra da chave de IA: cifrada com AES-256-GCM, chave mestra fora do
    banco, e nunca de volta em tela. Chave de e-mail é reputação e é dinheiro —
    quem a rouba manda mensagem em nome do órgão.
    """
    import base64

    import cofre
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not cofre.disponivel():
        raise RuntimeError("cofre indisponível: defina SEI360_CHAVE_MESTRA")
    chave = (chave or "").strip()
    if not chave:
        raise RuntimeError("informe a chave da API")
    k = base64.urlsafe_b64decode(os.environ["SEI360_CHAVE_MESTRA"] + "===")[:32]
    nonce = os.urandom(12)
    blob = AESGCM(k).encrypt(nonce, chave.encode(), b"config_email")
    cx.execute("INSERT OR IGNORE INTO config_email(id) VALUES(1)")
    # TROCAR A CHAVE DESARMA O TESTE. A chave nova pode ser de outra conta, de
    # outro plano, ou simplesmente errada — e o "teste ok" de ontem passaria a
    # atestar uma chave que já não existe.
    cx.execute("""UPDATE config_email SET chave=?, nonce=?, atualizado_em=?,
                  teste_ok=0, teste_erro=NULL, testado_em=NULL WHERE id=1""",
               (blob, nonce, agora()))
    registrar(cx, usuario_id, "guardar_chave_email", alvo="config_email", ip=ip)


def abrir_chave(cx):
    import base64

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    r = cx.execute("SELECT chave, nonce FROM config_email WHERE id=1").fetchone()
    if not r or not r["chave"]:
        return None
    mestra = os.environ.get("SEI360_CHAVE_MESTRA", "")
    if not mestra:
        return None
    k = base64.urlsafe_b64decode(mestra + "===")[:32]
    try:
        return AESGCM(k).decrypt(r["nonce"], r["chave"], b"config_email").decode()
    except Exception:
        # Chave mestra trocada sem migrar o cofre. Devolver None faz o envio
        # falhar com mensagem clara em vez de derrubar a tela de acesso.
        return None


def esquecer_chave(cx, usuario_id, ip=None):
    cx.execute("""UPDATE config_email SET chave=NULL, nonce=NULL, teste_ok=0,
                  teste_erro=NULL, testado_em=NULL, atualizado_em=? WHERE id=1""",
               (agora(),))
    registrar(cx, usuario_id, "apagar_chave_email", alvo="config_email", ip=ip)


def guardar_remetente(cx, remetente, responder_para, usuario_id, ip=None):
    """O remetente é texto livre porque o Resend aceita `Nome <caixa@dominio>`.

    A validação aqui é mínima de propósito: quem diz se o endereço serve é o
    Resend, na hora do teste, e é a resposta DELE que vale — não uma expressão
    regular nossa dizendo que um endereço válido é inválido.
    """
    remetente = (remetente or "").strip()
    responder_para = (responder_para or "").strip()
    if remetente and "@" not in remetente:
        raise RuntimeError("o remetente precisa de um endereço de e-mail")
    cx.execute("INSERT OR IGNORE INTO config_email(id) VALUES(1)")
    cx.execute("""UPDATE config_email SET remetente=?, responder_para=?, atualizado_em=?,
                  teste_ok=0, teste_erro=NULL, testado_em=NULL WHERE id=1""",
               (remetente, responder_para, agora()))
    registrar(cx, usuario_id, "configurar_remetente", alvo=remetente or "(vazio)", ip=ip)


# ------------------------------------------------------------------- endereço
_ENDERECO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Domínios que NÃO existem no mundo: `.local` é reservado para rede local (RFC
# 6762) e `.invalid` é reservado para nunca resolver (RFC 2606). As três contas
# de administração deste sistema nasceram em `@sei360.local`, e mandar um código
# de acesso para lá é trancar a conta para sempre — o e-mail não volta, não dá
# erro visível, e a pessoa fica olhando um campo de código que nunca vai chegar.
DOMINIOS_MORTOS = (".local", ".localhost", ".invalid", ".test", ".example")


def entregavel(endereco):
    """(bool, motivo). Se o endereço nem pode receber, isso se sabe ANTES.

    Chamado pelas telas que armam algo dependente de e-mail: melhor uma frase
    dizendo "esta conta não recebe correio" do que um código enviado para o
    nada e uma conta trancada.
    """
    e = (endereco or "").strip().lower()
    if not _ENDERECO.match(e):
        return False, "endereço de e-mail inválido"
    dominio = e.rsplit("@", 1)[-1]
    if any(dominio == d.lstrip(".") or dominio.endswith(d) for d in DOMINIOS_MORTOS):
        return False, f"o domínio '{dominio}' não recebe correio (reservado para uso local)"
    return True, None


def mascarar(endereco):
    """`zaine.lima@saude.ba.gov.br` -> `z********a@saude.ba.gov.br`.

    Para o log e para a tela. O endereço inteiro no log de auditoria é lista de
    e-mails do órgão para quem ler o banco.
    """
    e = (endereco or "").strip()
    if "@" not in e:
        return "(sem endereço)"
    caixa, dominio = e.rsplit("@", 1)
    if len(caixa) <= 2:
        return "*" * len(caixa) + "@" + dominio
    return caixa[0] + "*" * (len(caixa) - 2) + caixa[-1] + "@" + dominio


# --------------------------------------------------------------------- envio
def enviados_hoje(cx):
    """Quantas mensagens ACEITAS pelo provedor hoje."""
    return cx.execute("""SELECT COUNT(*) FROM log_acesso
                         WHERE acao='email_aceito' AND substr(ts,1,10)=substr(?,1,10)""",
                      (agora(),)).fetchone()[0]


def _postar(chave, corpo):
    """A requisição, isolada numa função para o teste poder substituí-la.

    Devolve (status, dicionário). É o ÚNICO ponto que fala com a rede — a suíte
    desvia por `SEI360_EMAIL_FALSO` e exercita todo o resto de verdade, sem
    mandar e-mail para ninguém e sem depender de o Resend estar no ar.

    SEM `Idempotency-Key`, e isso é decisão. O Resend oferece o cabeçalho, e ele
    servia para uma coisa: um reenvio da MESMA requisição não virar duas
    mensagens. Aqui não há reenvio — cada chamada nasce de uma linha nova no
    banco, com um código novo, então uma chave derivada dessa linha nunca
    colidiria com nada e o cabeçalho seria enfeite. Enfeite em código de
    autenticação é pior que ausência: alguém lê o nome, supõe proteção e para de
    procurar. Se um dia houver repetição automática no tempo esgotado, a chave
    volta — derivada do id da linha, que é o que a torna útil.
    """
    arquivo = caixa_falsa()
    if arquivo:
        with open(arquivo, "a", encoding="utf-8") as f:
            f.write(json.dumps(corpo, ensure_ascii=False) + "\n")
        return 200, {"id": "caixa-falsa"}

    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=dados, method="POST")
    req.add_header("Authorization", f"Bearer {chave}")
    req.add_header("Content-Type", "application/json")
    # USER-AGENT PRÓPRIO, E ISSO NÃO É CORTESIA. Medido contra a API real em
    # 27/08/2026: o Cloudflare que fica na frente da Resend BANEIA a string
    # padrão do urllib (`Python-urllib/3.12`) — devolve 403 com corpo
    # `text/plain` "error code: 1010", e a requisição nunca chega na Resend.
    # Qualquer outro valor passa (testados: curl/8.0, python-urllib,
    # sei360-mailer/1.0 — todos chegaram ao 401 real da API).
    #
    # Sem esta linha o envio falha SEMPRE, com um erro que não está na tabela de
    # erros da Resend porque não é dela. É a diferença entre integração que
    # funciona e integração que nunca funcionou.
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE_S) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        bruto = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(bruto or "{}")
        except ValueError:
            return e.code, {"message": bruto[:300]}
    except Exception as e:
        # Rede sem saída, DNS, TLS, tempo esgotado. Status 0 = nem chegou lá.
        return 0, {"message": f"{type(e).__name__}: {e}"}


def _explicar(status, resposta):
    """A frase que a pessoa lê. O erro cru do provedor não serve para a tela.

    Cada uma destas descreve uma AÇÃO diferente de quem administra: comprar
    plano, verificar domínio, trocar chave, esperar. "Erro 403" não descreve
    nenhuma.
    """
    # `name` é o código ESTÁVEL do erro; `message` é texto livre e muda. Ler
    # `message` para decidir é escrever um parser contra prosa de outra empresa.
    nome = (resposta or {}).get("name") or ""
    msg = (resposta or {}).get("message") or ""
    if status == 0:
        return f"o servidor não conseguiu falar com o Resend ({msg})"
    if "error code: 1010" in msg:
        # Não é a Resend respondendo: é o Cloudflare na frente dela recusando a
        # assinatura do cliente HTTP. Se voltar a aparecer, a regra endureceu e o
        # `User-Agent` precisa mudar — e ninguém adivinharia isso lendo "403".
        return ("o Cloudflare na frente do Resend recusou a assinatura do nosso "
                "cliente HTTP (error code 1010) — o User-Agent precisa ser revisto")
    if status in (401, 403) and "api" in (nome + msg).lower() and "key" in (nome + msg).lower():
        return "a chave da API foi recusada — gere outra no Resend e salve aqui"
    if status == 403 or "not verified" in msg.lower() or "domain" in nome.lower():
        return ("o domínio do remetente não está verificado no Resend — "
                "publique os registros de DNS que ele pede e verifique lá")
    if nome == "daily_quota_exceeded":
        return "a cota diária de e-mails do plano acabou"
    if status == 429:
        return "o Resend recusou por excesso de envios; tente daqui a pouco"
    if status == 422 or nome == "validation_error":
        return f"o Resend recusou os dados do envio: {msg or 'campo inválido'}"
    if status >= 500:
        return "o Resend está com problema no lado dele; tente daqui a pouco"
    return f"o Resend respondeu {status}: {msg or nome or 'sem detalhe'}"


def enviar(cx, para, assunto, texto, html=None, motivo="", usuario_id=None,
           ip=None, prioridade="normal"):
    """Manda um e-mail. Devolve (ok, erro_para_a_tela).

    NUNCA levanta exceção: quem chama está no meio de uma tela de acesso, e uma
    falha de e-mail não pode virar erro 500 numa porta de entrada.

    O CORPO NÃO É REGISTRADO. Ele carrega o código ou o link que dão acesso à
    conta — o log guarda destinatário mascarado, assunto e resultado.
    """
    cfg = ler_config(cx)
    if not cfg["tem_chave"]:
        return False, "o envio de e-mail não está configurado (falta a chave da API)"
    if not cfg["remetente"]:
        return False, "o envio de e-mail não está configurado (falta o remetente)"
    ok_dest, porque = entregavel(para)
    if not ok_dest:
        return False, porque
    chave = abrir_chave(cx)
    if not chave:
        return False, ("a chave guardada não pôde ser aberta — a chave mestra "
                       "(SEI360_CHAVE_MESTRA) mudou desde que ela foi salva")

    corpo = {"from": cfg["remetente"], "to": [para], "subject": assunto,
             "text": texto}
    if html:
        corpo["html"] = html
    if cfg["responder_para"]:
        corpo["reply_to"] = cfg["responder_para"]

    gastos = enviados_hoje(cx)
    # Quem está ENTRANDO usa o orçamento inteiro; o resto para antes, deixando a
    # reserva de pé. Ver a nota em `RESERVA_ACESSO`.
    teto = TETO_DIARIO if prioridade == "acesso" else max(0, TETO_DIARIO - RESERVA_ACESSO)
    if gastos >= teto:
        registrar(cx, usuario_id, "email_teto_diario",
                  alvo=f"{gastos} de {teto} ({prioridade})", ip=ip)
        return False, (f"o teto diário de e-mails desta instalação foi atingido "
                       f"({gastos} de {teto}) — ele existe para o provedor não "
                       "cortar o envio sem aviso. Volta a zero à meia-noite")

    status, resposta = _postar(chave, corpo)
    ok = 200 <= status < 300
    erro = None if ok else _explicar(status, resposta)
    # `email_aceito`, e nao `enviar_email`. O 200 do provedor diz que ele ACEITOU
    # a mensagem — nao que alguem recebeu. O filtro do Microsoft 365 da SESAB
    # pode engolir depois, e o provedor segue dizendo "entregue". Chamar isso de
    # "enviado" no log é afirmar o que o 200 não prova.
    #
    # E o `id` devolvido VAI JUNTO: é um UUID opaco (não é dado pessoal) e é a
    # única chave que correlaciona uma reclamação de "não chegou" com o painel do
    # provedor e com o rastreamento do Exchange. Descartá-lo é jogar fora a única
    # forma de investigar.
    ident = (resposta or {}).get("id") if ok else None
    marca = f"{mascarar(para)} · {motivo or assunto}"
    if ident:
        marca += f" · id={ident}"
    registrar(cx, usuario_id, "email_aceito" if ok else "email_recusado",
              alvo=marca[:200], ip=ip)
    # O ÚLTIMO ENVIO NÃO É O ÚLTIMO TESTE. Uma falha momentânea no envio de um
    # código carimbava `testado_em` — a coluna que a tela rotula "último teste" —
    # e deixava um erro vermelho ao lado da tag verde "pronto", permanentemente,
    # descrevendo um teste que nunca houve. E um sucesso posterior não limpava.
    # Colunas separadas: uma conta a saúde do ENVIO, outra o TESTE deliberado.
    cx.execute("""UPDATE config_email SET envio_erro=?, envio_em=? WHERE id=1""",
               (None if ok else (erro or "")[:300], agora()))
    return ok, erro


def testar(cx, para, usuario_id, ip=None):
    """Envia um e-mail de teste e GRAVA o resultado.

    É este resultado que arma o resto: `pronto` só vira verdadeiro depois de um
    teste que chegou. Sem isso, "configurei" e "funciona" viram a mesma coisa, e
    a diferença entre elas é uma conta que não entra mais.
    """
    ok, erro = enviar(
        cx, para,
        "SEI360 — teste de envio",
        "Este é um teste de configuração do SEI360.\n\n"
        "Se você recebeu esta mensagem, o envio de e-mail está funcionando: a "
        "recuperação de senha e o código de acesso já podem ser ligados.\n\n"
        "Não é preciso responder.",
        motivo="teste de configuração", usuario_id=usuario_id, ip=ip)
    cx.execute("""UPDATE config_email SET teste_ok=?, teste_erro=?, testado_em=?
                  WHERE id=1""", (1 if ok else 0, None if ok else (erro or "")[:300],
                                  agora()))
    registrar(cx, usuario_id, "testar_email", alvo=mascarar(para), ip=ip)
    return ok, erro
