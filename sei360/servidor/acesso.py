# -*- coding: utf-8 -*-
"""
Recuperação de senha e segundo fator — a política, sem HTML e sem rota.

A DIFERENÇA ENTRE ESTE ARQUIVO E `email_saida.py`
-------------------------------------------------
Lá é o transporte: manda e-mail e devolve se deu certo. Aqui é a decisão: quem
pode pedir, o que vale por quanto tempo, quantas tentativas, e o que acontece
com as sessões vivas quando a senha muda. Separados porque trocar de provedor de
e-mail não pode encostar em regra de acesso, e mudar regra de acesso não pode
exigir mexer em requisição HTTP.

AS DUAS COISAS QUE ESTE ARQUIVO EXISTE PARA IMPEDIR
---------------------------------------------------
1. TRANCAR TODO MUNDO. Um segundo fator por e-mail é a única peça capaz de
   fechar o sistema para todos ao mesmo tempo — Resend fora do ar, chave
   revogada, domínio sem verificação, filtro do órgão barrando. Por isso ele
   nasce DESLIGADO, só arma depois de um envio de teste que chegou, recusa-se a
   armar para conta cujo domínio não recebe correio, e tem uma saída de
   emergência que funciona sem painel e sem e-mail (`emergencia.py`).
2. VIRAR A PORTA DOS FUNDOS. Recuperação de senha é, por definição, um caminho
   de entrada que dispensa a senha. Token de uso único, curto, guardado como
   hash, que morre ao ser usado, quando outro é pedido, quando a senha muda, e
   quando a pessoa entra normalmente.

O QUE NUNCA APARECE NO LOG
--------------------------
O token e o código. São eles que dão acesso — registrá-los é guardar a chave
junto com a fechadura. O log guarda que houve pedido, de quem, de que IP e o que
aconteceu.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta

import seguranca as seg
from banco import TZ, agora, registrar

# ---------------------------------------------------------------- os números
#
# RECUPERAÇÃO — 30 min. O e-mail institucional do órgão às vezes demora minutos
# para entregar, então 5 min viraria "o link já venceu quando chegou". Mais que
# uma hora e o link fica vivo numa caixa de entrada aberta na mesa de alguém.
VALIDADE_RECUPERACAO_MIN = 30
# Três pedidos por hora por conta. O custo de um pedido é um e-mail enviado em
# nome do órgão: sem teto, qualquer um inunda a caixa de qualquer servidor
# usando o nosso remetente, e quem paga a reputação do domínio somos nós.
PEDIDOS_POR_HORA = 3

# SEGUNDO FATOR — 6 dígitos. Quatro seriam 10 mil combinações, adivinháveis
# dentro do limite de tentativas em algumas contas; oito, ninguém digita sem
# errar. Seis com 5 tentativas dá 1 chance em 200 mil por desafio.
DIGITOS = 6
VALIDADE_CODIGO_MIN = 10
TENTATIVAS_CODIGO = 5


def _hash(v: str) -> bytes:
    return hashlib.sha256(v.encode("utf-8")).digest()


def _daqui(minutos):
    return (datetime.now(TZ) + timedelta(minutes=minutos)).isoformat(timespec="seconds")


# ------------------------------------------------------------------ política
def ler_politica(cx):
    # LER NÃO ESCREVE. O `INSERT OR IGNORE` que abria esta função tomava a trava
    # de escrita única do SQLite mesmo sem nada a inserir — e ela é chamada em
    # TODO `GET /entrar`, que é a única página exposta sem sessão. A tela de
    # acesso virava escritora do banco a cada visita e disputava o escritor com
    # quem estivesse ingerindo coleta.
    r = cx.execute("SELECT * FROM config_acesso WHERE id=1").fetchone()
    if not r:
        cx.execute("INSERT OR IGNORE INTO config_acesso(id) VALUES(1)")
        r = cx.execute("SELECT * FROM config_acesso WHERE id=1").fetchone()
    try:
        papeis = json.loads(r["fator2_papeis"] or "[]")
    except ValueError:
        papeis = []
    return {"recuperacao_ativa": bool(r["recuperacao_ativa"]),
            "fator2_papeis": [p for p in papeis if isinstance(p, str)],
            "atualizado_em": r["atualizado_em"]}


def salvar_politica(cx, recuperacao_ativa, fator2_papeis, usuario_id, ip=None):
    """Liga e desliga. RECUSA ligar o que o e-mail ainda não sustenta.

    Ligar segundo fator com o envio quebrado não é uma configuração errada: é
    uma porta trancada com a chave do lado de dentro, e o único caminho de volta
    passa por alguém com acesso ao servidor. A recusa aqui é o que impede isso
    de acontecer por um clique.
    """
    import os

    import email_saida
    papeis = sorted({p for p in (fator2_papeis or []) if p in ("admin", "gestor", "servidor")})
    cfg = email_saida.ler_config(cx)
    if recuperacao_ativa and not (os.environ.get("SEI360_BASE_URL") or "").strip():
        # O E-MAIL DE RECUPERAÇÃO CARREGA UM LINK, e link precisa de endereço.
        # Montá-lo do `Host` da requisição entrega ao atacante a escolha do
        # destino (ver a nota em `app.py`, função `montar`). O segundo fator não
        # cai nesta regra: o e-mail dele leva um número, não um endereço.
        raise RuntimeError(
            "defina SEI360_BASE_URL (o endereço público do painel, por exemplo "
            "https://sei360.seudominio.com.br) antes de ligar a recuperação — "
            "sem ela o link do e-mail seria montado a partir de um cabeçalho que "
            "quem faz a requisição controla")
    if (recuperacao_ativa or papeis) and not cfg["pronto"]:
        raise RuntimeError(
            "o envio de e-mail ainda não foi testado com sucesso — configure a "
            "chave e o remetente e mande um teste antes de ligar qualquer um dos dois")
    if papeis:
        # QUEM VAI PRECISAR DO CÓDIGO CONSEGUE RECEBÊ-LO? A conta cujo domínio
        # não existe nunca receberia, e ligar mesmo assim é trancá-la para
        # sempre. Este sistema nasceu com três contas em `@sei360.local`.
        marc = ",".join("?" * len(papeis))
        presas = []
        for r in cx.execute(f"""SELECT email FROM usuarios
                                WHERE ativo=1 AND papel IN ({marc})""", papeis):
            ok, porque = email_saida.entregavel(r["email"])
            if not ok:
                presas.append(f"{r['email']} ({porque})")
        if presas:
            raise RuntimeError(
                "estas contas ATIVAS ficariam trancadas para sempre, porque o "
                "código nunca chegaria nelas: " + "; ".join(presas[:5])
                + ("…" if len(presas) > 5 else "")
                + ". Corrija o e-mail delas antes de ligar o segundo fator.")
    # A LINHA PRECISA EXISTIR ANTES DO UPDATE. Numa instalação nova a tabela
    # nasce vazia, e `UPDATE ... WHERE id=1` sobre zero linhas não é erro: é um
    # silêncio. A tela dizia "política salva" e nada tinha sido salvo — que é o
    # pior desfecho possível para um interruptor de segurança.
    cx.execute("INSERT OR IGNORE INTO config_acesso(id) VALUES(1)")
    cx.execute("""UPDATE config_acesso SET recuperacao_ativa=?, fator2_papeis=?,
                  atualizado_em=?, atualizado_por=? WHERE id=1""",
               (1 if recuperacao_ativa else 0, json.dumps(papeis), agora(), usuario_id))
    registrar(cx, usuario_id, "configurar_acesso",
              alvo=f"recuperacao={'on' if recuperacao_ativa else 'off'} fator2={papeis or 'nenhum'}",
              ip=ip)


def derrubar_acesso(cx, usuario_id, motivo):
    """Tira a pessoa de dentro — TUDO o que dá acesso, de uma vez.

    Existe porque a regra estava copiada em três lugares e faltando em três. Um
    desafio de segundo fator PENDENTE é acesso em trânsito: quem tem o cookie e o
    código conclui `/verificar` e ganha uma sessão nova depois de o administrador
    ter revogado as sessões. No caminho de "gerar senha provisória" é pior — a
    sessão nasce, cai em `/primeiro-acesso` (que não pede a senha antiga) e o
    portador do código define a própria senha sem nunca ter conhecido a provisória
    que o administrador acabou de gerar. A conta fica com ele.

    Três coisas, sempre juntas: sessões vivas, desafios pendentes e links de
    recuperação em aberto. Devolve quantos de cada.
    """
    ag = agora()
    s = cx.execute("""UPDATE sessoes SET revogada_em=? WHERE usuario_id=?
                      AND revogada_em IS NULL""", (ag, usuario_id)).rowcount
    d = cx.execute("""UPDATE desafio SET cancelado_em=? WHERE usuario_id=?
                      AND usado_em IS NULL AND cancelado_em IS NULL""",
                   (ag, usuario_id)).rowcount
    r = cx.execute("""UPDATE recuperacao SET invalidado_em=?, motivo_invalidacao=?
                      WHERE usuario_id=? AND usado_em IS NULL
                      AND invalidado_em IS NULL""", (ag, motivo[:60], usuario_id)).rowcount
    registrar(cx, None, "derrubar_acesso",
              alvo=f"usuario={usuario_id} {motivo}: {s} sessão(ões), {d} desafio(s), "
                   f"{r} link(s)")
    return s, d, r


def exige_fator2(cx, usuario):
    """Esta pessoa precisa de código nesta entrada? SÓ A POLÍTICA DECIDE.

    A versão anterior desta função também perguntava se o e-mail estava
    saudável, e desligava o segundo fator quando não estava. Parecia prudente e
    era um buraco: `guardar_chave` zera `teste_ok` de propósito, então ROTACIONAR
    A CHAVE DO RESEND desligava o segundo fator de todo mundo em silêncio — até
    alguém lembrar de mandar um teste. Quem consegue derrubar a entrega de
    e-mail ganhava, de brinde, um caminho para pular o segundo fator, que é
    exatamente o ataque.

    Agora vale o contrário: armado é armado. Se o código não puder ser enviado, a
    entrada FALHA, com o motivo na tela — e quem administra desliga de propósito,
    pelo painel ou por `emergencia.py desligar-fator2`, que funciona sem e-mail e
    sem painel. Armar já exige um teste bem-sucedido (`salvar_politica`), então
    esta política nunca nasce sobre um envio que nunca funcionou.
    """
    pol = ler_politica(cx)
    return bool(pol["fator2_papeis"]) and usuario["papel"] in pol["fator2_papeis"]


# ------------------------------------------------------- recuperação de senha
MESMA_RESPOSTA = ("Se houver uma conta com esse e-mail, enviamos um link de "
                  "recuperação. Ele vale por 30 minutos.")


def pedir_recuperacao(cx, email, ip, montar_link):
    """Sempre devolve a MESMA frase. Devolve (enviado_de_fato, frase).

    O primeiro valor é para o log e para os testes — nunca para a tela. Dizer
    "não existe conta com esse e-mail" transforma a tela de recuperação num
    verificador de quem trabalha no órgão, que é justamente a lista que um
    atacante quer antes de tentar senha.

    `montar_link` recebe o token e devolve a URL. Quem sabe montar URL é a
    aplicação, não este módulo.
    """
    import email_saida
    email = (email or "").strip().lower()
    pol = ler_politica(cx)
    if not pol["recuperacao_ativa"]:
        return False, ("A recuperação por e-mail não está ligada nesta instalação. "
                       "Peça a quem administra para gerar uma senha provisória.")

    # `senha_hash IS NOT NULL` ALÉM de `ativo=1`. As 57 contas semeadas a partir
    # do snapshot do SEI nascem sem senha; se uma for ativada e ficar sem senha,
    # ela vira destino de e-mail automático em nome do órgão sem nunca ter havido
    # conta de verdade. E endereço extraído de tela do SEI que não existe mais
    # vira devolução — bounce acima de ~4% suspende a chave do provedor, e aí o
    # segundo fator para para todo mundo.
    # A BASE É CONFERIDA AQUI TAMBÉM. A exigência em `salvar_politica` vale no
    # instante de LIGAR, e a política mora no banco: ela sobrevive ao container, a
    # variável não. Um redeploy que perca `SEI360_BASE_URL` faria o link sair como
    # `/recuperar/<token>` — texto que nenhum cliente de e-mail transforma em link
    # — enquanto a tela dizia que enviou.
    import os as _os
    if not (_os.environ.get("SEI360_BASE_URL") or "").strip():
        seg.gastar_tempo_isca()
        registrar(cx, None, "recuperacao_recusada", alvo="SEI360_BASE_URL ausente", ip=ip)
        return False, MESMA_RESPOSTA

    u = cx.execute("""SELECT * FROM usuarios
                      WHERE email=? AND ativo=1 AND senha_hash IS NOT NULL""",
                   (email,)).fetchone()
    if not u:
        # O MESMO CUSTO DO CAMINHO VÁLIDO. Sem isto a latência responde o que a
        # frase se recusa a responder: existe ou não existe.
        seg.gastar_tempo_isca()
        registrar(cx, None, "recuperacao_pedida", alvo="conta inexistente", ip=ip)
        return False, MESMA_RESPOSTA

    # A ISCA TAMBÉM AQUI. Ela só era gasta no ramo "conta não existe"; todos os
    # ramos de conta EXISTENTE que saem cedo voltavam em ~1,5 ms contra ~93 ms, e
    # o relógio respondia o que a frase se recusa a responder.
    entregavel, porque = email_saida.entregavel(u["email"])
    if not entregavel:
        seg.gastar_tempo_isca()
        registrar(cx, u["id"], "recuperacao_recusada", alvo=porque, ip=ip)
        return False, MESMA_RESPOSTA

    corte = (datetime.now(TZ) - timedelta(hours=1)).isoformat(timespec="seconds")
    recentes = cx.execute("""SELECT COUNT(*) FROM recuperacao
                             WHERE usuario_id=? AND criado_em>=?""",
                          (u["id"], corte)).fetchone()[0]
    if recentes >= PEDIDOS_POR_HORA:
        seg.gastar_tempo_isca()
        registrar(cx, u["id"], "recuperacao_recusada", alvo="teto por hora", ip=ip)
        return False, MESMA_RESPOSTA

    # UM POR VEZ. Pedir de novo mata o anterior: dois links vivos dobram a
    # janela em que um e-mail vazado ainda abre a conta.
    cx.execute("""UPDATE recuperacao SET invalidado_em=?, motivo_invalidacao='outro pedido'
                  WHERE usuario_id=? AND usado_em IS NULL AND invalidado_em IS NULL""",
               (agora(), u["id"]))
    token = secrets.token_urlsafe(32)
    cx.execute("""INSERT INTO recuperacao(usuario_id,token_sha256,criado_em,expira_em,ip_pedido)
                  VALUES(?,?,?,?,?)""",
               (u["id"], _hash(token), agora(), _daqui(VALIDADE_RECUPERACAO_MIN), ip))
    # FECHA A TRANSAÇÃO ANTES DE FALAR COM A REDE. O `sqlite3` abre transação no
    # primeiro DML, e o SQLite tem UM escritor: manter essa trava durante um POST
    # de até 10 s ao provedor faz TODA escrita do painel esperar — e como cada
    # requisição carimba `ultimo_uso_em` da sessão, o painel inteiro trava junto.
    # Foi a mesma correção que o executor de busca precisou.
    cx.commit()

    link = montar_link(token)
    ok, erro = email_saida.enviar(
        cx, u["email"], "SEI360 — recuperação de senha",
        f"Olá, {u['nome'] or ''}\n\n"
        f"Alguém pediu para redefinir a senha da sua conta no SEI360.\n\n"
        f"Para escolher uma senha nova, abra:\n{link}\n\n"
        f"O link vale por {VALIDADE_RECUPERACAO_MIN} minutos e serve uma vez só.\n\n"
        "SE NÃO FOI VOCÊ que pediu, ignore esta mensagem: a sua senha continua a "
        "mesma e ninguém entrou na sua conta. Vale avisar quem administra o "
        "sistema.\n\n"
        "Esta não é a sua senha do SEI. O SEI360 nunca pede a senha do SEI.",
        motivo="recuperação de senha", usuario_id=u["id"], ip=ip)
    if not ok:
        # O token nasceu e o e-mail não saiu: mata o token. Deixá-lo vivo é uma
        # chave emitida que ninguém recebeu, válida por meia hora.
        cx.execute("""UPDATE recuperacao SET invalidado_em=?, motivo_invalidacao='envio falhou'
                      WHERE usuario_id=? AND usado_em IS NULL AND invalidado_em IS NULL""",
                   (agora(), u["id"]))
        registrar(cx, u["id"], "recuperacao_falhou", alvo=(erro or "")[:150], ip=ip)
        return False, MESMA_RESPOSTA
    registrar(cx, u["id"], "recuperacao_enviada", ip=ip)
    return True, MESMA_RESPOSTA


def ler_recuperacao(cx, token):
    """A linha viva desse token, ou None. Não carimba nada."""
    if not token:
        return None
    r = cx.execute("""SELECT r.*, u.email, u.nome, u.ativo FROM recuperacao r
                      JOIN usuarios u ON u.id=r.usuario_id
                      WHERE r.token_sha256=?""", (_hash(token),)).fetchone()
    if not r or r["usado_em"] or r["invalidado_em"] or not r["ativo"]:
        return None
    if r["expira_em"] <= agora():
        return None
    return r


def usar_recuperacao(cx, token, nova, ip=None):
    """Redefine a senha. Devolve (ok, erro).

    O que ACONTECE JUNTO importa tanto quanto a troca: todas as sessões vivas
    caem, todo desafio pendente morre e todo outro token de recuperação morre.
    Se a senha foi redefinida porque a conta estava comprometida, deixar a sessão
    do invasor viva anula o gesto inteiro.
    """
    r = ler_recuperacao(cx, token)
    if not r:
        return False, "Este link não vale mais. Peça outro na tela de acesso."
    critica = seg.criticar_senha(nova, r["email"])
    if critica:
        return False, critica
    h, sal = seg.hash_senha(nova)
    cx.execute("""UPDATE usuarios SET senha_hash=?, senha_sal=?, senha_trocada_em=?,
                  falhas_seq=0, bloqueado_ate=NULL WHERE id=?""",
               (h, sal, agora(), r["usuario_id"]))
    cx.execute("UPDATE recuperacao SET usado_em=?, ip_uso=? WHERE id=?",
               (agora(), ip, r["id"]))
    derrubar_acesso(cx, r["usuario_id"], "senha redefinida")
    registrar(cx, r["usuario_id"], "senha_redefinida", alvo="por link de recuperação", ip=ip)
    return True, None


# ------------------------------------------------------------- segundo fator
def abrir_desafio(cx, usuario, ip=None, user_agent=None, lembrar=False):
    """Cria a sessão PENDENTE e manda o código. Devolve (token, erro).

    O token devolvido vai num cookie próprio, separado do cookie de sessão, e a
    única coisa que ele abre é a tela do código. Não é uma linha em `sessoes`
    com uma marca de "ainda não vale": marca é coluna que alguém esquece de
    conferir numa consulta nova, e o preço desse esquecimento é entrar sem o
    segundo fator.
    """
    import email_saida
    # Um desafio por vez: o código anterior deixa de valer quando outro é
    # pedido, senão dois códigos vivos dobram a janela de adivinhação.
    cx.execute("""UPDATE desafio SET cancelado_em=? WHERE usuario_id=?
                  AND usado_em IS NULL AND cancelado_em IS NULL""",
               (agora(), usuario["id"]))
    codigo = "".join(secrets.choice("0123456789") for _ in range(DIGITOS))
    token = secrets.token_urlsafe(32)
    cx.execute("""INSERT INTO desafio(usuario_id,token_sha256,codigo_sha256,criado_em,
                  expira_em,lembrar,ip,user_agent) VALUES(?,?,?,?,?,?,?,?)""",
               (usuario["id"], _hash(token), _hash(codigo), agora(),
                _daqui(VALIDADE_CODIGO_MIN), 1 if lembrar else 0, ip,
                (user_agent or "")[:200]))
    # Ver a nota em `pedir_recuperacao`: nada de segurar o escritor único do
    # SQLite durante a requisição ao provedor.
    cx.commit()
    ok, erro = email_saida.enviar(
        cx, usuario["email"], f"SEI360 — seu código: {codigo}",
        f"Seu código de acesso ao SEI360 é:\n\n    {codigo}\n\n"
        f"Ele vale por {VALIDADE_CODIGO_MIN} minutos e serve uma vez só.\n\n"
        "SE VOCÊ RECEBEU MAIS DE UM CÓDIGO, vale o mais recente: cada tentativa "
        "de entrar gera um novo e cancela o anterior.\n\n"
        "SE NÃO FOI VOCÊ que tentou entrar, alguém digitou a sua senha "
        "corretamente — troque-a agora e avise quem administra o sistema.\n\n"
        "Esta não é a sua senha do SEI. O SEI360 nunca pede a senha do SEI.",
        motivo="código de acesso", usuario_id=usuario["id"], ip=ip,
        prioridade="acesso")
    if not ok:
        cx.execute("UPDATE desafio SET cancelado_em=? WHERE token_sha256=?",
                   (agora(), _hash(token)))
        return None, erro
    return token, None


def ler_desafio(cx, token):
    if not token:
        return None
    r = cx.execute("""SELECT d.*, u.email, u.nome, u.papel, u.ativo
                      FROM desafio d JOIN usuarios u ON u.id=d.usuario_id
                      WHERE d.token_sha256=?""", (_hash(token),)).fetchone()
    if not r or r["usado_em"] or r["cancelado_em"] or not r["ativo"]:
        return None
    if r["expira_em"] <= agora():
        return None
    return r


def conferir_desafio(cx, token, codigo, ip=None):
    """Devolve (linha_do_usuario | None, erro).

    A tentativa é contada ANTES da comparação. Contá-la depois deixa o caminho
    do acerto sem custo e o do erro com custo — e um atacante que interrompe a
    requisição no meio ficaria com tentativas infinitas.
    """
    r = ler_desafio(cx, token)
    if not r:
        return None, "O código venceu ou já foi usado. Entre de novo para receber outro."
    # O TETO É CONFERIDO NO PRÓPRIO UPDATE. Ler e depois escrever deixa a janela
    # em que várias requisições leem o mesmo `tentativas` e todas passam — o
    # limite de cinco vira "cinco por requisição simultânea".
    n = cx.execute("""UPDATE desafio SET tentativas=tentativas+1
                      WHERE id=? AND tentativas < ? AND usado_em IS NULL
                        AND cancelado_em IS NULL""",
                   (r["id"], TENTATIVAS_CODIGO)).rowcount
    if not n:
        # O UPDATE não pegou por um de DOIS motivos, e eles têm consertos
        # diferentes para quem está na tela: ou as tentativas acabaram, ou o
        # código já foi consumido (duplo clique, duas abas, um cliente que
        # repete). Dizer "tentativas esgotadas" no segundo caso faz a pessoa
        # achar que queimou as cinco quando ela acertou de primeira.
        atual = cx.execute("SELECT usado_em, tentativas FROM desafio WHERE id=?",
                           (r["id"],)).fetchone()
        if atual and atual["usado_em"]:
            registrar(cx, r["usuario_id"], "fator2_corrida", ip=ip)
            return None, ("Este código já foi usado. Se a tela não avançou, "
                          "entre de novo para receber outro.")
        cx.execute("UPDATE desafio SET cancelado_em=? WHERE id=? AND usado_em IS NULL",
                   (agora(), r["id"]))
        registrar(cx, r["usuario_id"], "fator2_esgotado", ip=ip)
        return None, "Tentativas esgotadas. Entre de novo para receber outro código."
    digitado = "".join(ch for ch in (codigo or "") if ch.isdigit())
    if not secrets.compare_digest(_hash(digitado), bytes(r["codigo_sha256"])):
        restam = TENTATIVAS_CODIGO - (r["tentativas"] + 1)
        registrar(cx, r["usuario_id"], "fator2_errado", alvo=f"restam {restam}", ip=ip)
        if restam <= 0:
            cx.execute("UPDATE desafio SET cancelado_em=? WHERE id=?", (agora(), r["id"]))
            return None, "Tentativas esgotadas. Entre de novo para receber outro código."
        return None, f"Código incorreto. Restam {restam} tentativa(s)."
    # QUEM CONSOME É O UPDATE, e ele só consome uma vez.
    #
    # QUEM JÁ FECHA A PORTA é o `AND usado_em IS NULL` do contador, lá em cima:
    # a segunda requisição não passa nem do contador. Esta condição aqui é a
    # mesma invariante dita LOCALMENTE, e cobre a janela estreita entre as duas
    # escritas — duas requisições que passem juntas pelo contador (tentativas 0→1
    # e 1→2, ambas abaixo do teto) chegariam juntas aqui.
    #
    # MEDIDO com mutação: soltar SÓ uma das duas não reintroduz o defeito — a
    # outra segura, e a suíte passa com razão. Soltando AS DUAS, a suíte falha.
    # Ou seja: a propriedade está coberta; a redundância é deliberada, e nenhuma
    # das duas é código morto disfarçado de proteção.
    usou = cx.execute("""UPDATE desafio SET usado_em=? WHERE id=?
                         AND usado_em IS NULL AND cancelado_em IS NULL""",
                      (agora(), r["id"])).rowcount
    if not usou:
        registrar(cx, r["usuario_id"], "fator2_corrida", ip=ip)
        return None, "Este código já foi usado. Entre de novo para receber outro."
    registrar(cx, r["usuario_id"], "fator2_ok", ip=ip)
    return r, None


def cancelar_desafio(cx, token):
    if token:
        cx.execute("""UPDATE desafio SET cancelado_em=? WHERE token_sha256=?
                      AND usado_em IS NULL AND cancelado_em IS NULL""",
                   (agora(), _hash(token)))


def faxina(cx):
    """Apaga o que venceu há muito. Chamado pelo expurgo.

    Guardar por 30 dias e não para sempre: a auditoria de um pedido de
    recuperação interessa por semanas, não por anos, e cada linha antiga é um
    hash a mais em backup sem ninguém para consultá-lo.
    """
    corte = (datetime.now(TZ) - timedelta(days=30)).isoformat(timespec="seconds")
    n1 = cx.execute("DELETE FROM recuperacao WHERE criado_em < ?", (corte,)).rowcount
    n2 = cx.execute("DELETE FROM desafio WHERE criado_em < ?", (corte,)).rowcount
    return n1, n2
