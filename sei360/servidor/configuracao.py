# -*- coding: utf-8 -*-
"""
Configuração de coleta por usuário — o assistente e as regras por trás dele.

A PERGUNTA QUE DEFINE ESTE MÓDULO
---------------------------------
"O SEI360 precisa guardar a senha? Como ele vai acessar pelo Playwright?"

Precisa. O SEI não tem API, não tem token, não tem OAuth: o Playwright preenche
usuário e senha no formulário, como uma pessoa faria. Logo a senha existe em
texto claro no instante da coleta, e alguém tem de guardá-la entre uma coleta e
outra. A escolha real é ONDE, e ela tem duas respostas defensáveis:

  * `servidor` — cifrada aqui (AES-256-GCM, chave fora do banco). A pessoa
    configura e esquece; funciona mesmo com a estação dela desligada. Preço:
    quem comprometer o servidor em execução decifra, e o log do SEI vai registrar
    os acessos com o nome dela.

  * `estacao` — na máquina da própria pessoa, no Gerenciador de Credenciais do
    Windows. O servidor nunca vê a senha. Preço: a coleta só acontece com aquela
    máquina ligada, e é preciso instalar o agente nela.

O padrão é `servidor` porque é o que faz o produto funcionar para gente que não
administra a própria máquina — que é a maioria. Quem precisar do outro modo
troca em um clique, e o assistente explica os dois em português, na hora da
escolha, e não num documento que ninguém abre.
"""
import json
from datetime import datetime

import perfil_sei
from banco import TZ


def _carimbo():
    """`agora()` com fração de segundo — só para ordenar ESTA tabela.

    `ler()` sem `sistema` devolve "a última configuração que a pessoa mexeu", e a
    ordem era `atualizado_em DESC, sistema`. Com `agora()` em segundo INTEIRO,
    trocar de instalação e salvar dentro do mesmo segundo dava EMPATE — e o
    desempate alfabético fazia 'SEI-FESF' vencer 'SEI-SESAB'. Medido: a pessoa
    escolhia a SESAB no passo 1, a tela dizia que avançou, e o passo 2 validava o
    login contra a FESF — recusando o e-mail CERTO com a mensagem da outra
    instalação. Enquanto houve uma instalação só isso era invisível.

    ISO com microssegundos continua ordenando certo, em texto, contra o ISO sem
    eles: no mesmo segundo compara-se '.' (0x2E) com '-' (0x2D) do offset, e o
    carimbo mais preciso fica DEPOIS — que é a ordem verdadeira.
    """
    return datetime.now(TZ).isoformat(timespec="microseconds")

# UMA lista de instâncias, em `perfil_sei.py`. Esta aqui é a projeção do que a
# TELA precisa saber — nome, exemplo de login, se dá para usar — derivada do
# mesmo perfil que o coletor consome. Duas listas divergem: esta descrevia a
# FESF como "não validada" enquanto o coletor tinha a URL da SESAB fixa no meio
# do arquivo, e nada no código sabia de nenhuma das duas coisas.
#
# `disponivel` quer dizer ESCOLHÍVEL: a instalação serve para busca OU para
# coleta. Antes ele era `disponivel_coleta`, e a tela desabilitava o rádio da
# FESF com "ainda não disponível" — falso, porque a busca já roda nela. Quem tem
# vínculo só na FESF não passava do passo 1 de um sistema que já sabia atendê-la.
#
# As duas disponibilidades continuam separadas e VÃO PARA A TELA, uma por
# instância ("coleta: sim/não · busca: sim/não"). Texto fixo mentiria na primeira
# vez que uma das duas mudasse; isto sai do perfil e acompanha o perfil.
SISTEMAS = {
    k: {
        "nome": v["nome"],
        "curto": v["curto"],
        "descricao": v["descricao"]
                     + ("" if v["disponivel_coleta"]
                        else " A coleta ainda não roda aqui: "
                             + v.get("motivo_sem_coleta", "motivo não registrado.")),
        "login_url": v["login_url"],
        "exemplo_login": v["exemplo_login"],
        "rotulo": v["rotulo"],
        "disponivel": perfil_sei.escolhivel(k),
        "disponivel_coleta": v["disponivel_coleta"],
        "disponivel_busca": v["disponivel_busca"],
    }
    for k, v in perfil_sei.INSTANCIAS.items()
}

# Quatro passos, não cinco. "Onde a senha fica" deixou de ser um passo próprio e
# virou uma escolha DENTRO do passo de acesso, que é onde ela faz sentido: a
# pergunta só existe porque há uma senha para guardar.
PASSOS = [
    ("sistema", "Sistema", "de onde vêm os processos"),
    ("acesso", "Acesso", "com qual conta a coleta entra"),
    ("mesas", "Mesas", "quais unidades coletar"),
    ("horarios", "Horários", "quando a coleta roda"),
]


def ler(cx, usuario_id, sistema=None):
    """Configuração do usuário, sempre um dicionário — nunca None.

    `sistema=None` devolve a configuração ATIVA: a última que a pessoa mexeu.
    Com um nome, devolve a daquela instalação — que pode não existir ainda, e aí
    volta o padrão, como sempre foi.

    Duas configurações coexistem de propósito. Antes, escolher a FESF no passo 1
    sobrescrevia a linha da SESAB (a chave era só `usuario_id`) e a coleta
    configurada sumia sem aviso.
    """
    if sistema:
        r = cx.execute("SELECT * FROM config_usuario WHERE usuario_id=? AND sistema=?",
                       (usuario_id, sistema)).fetchone()
    else:
        r = cx.execute("""SELECT * FROM config_usuario WHERE usuario_id=?
                          ORDER BY atualizado_em DESC, sistema LIMIT 1""",
                       (usuario_id,)).fetchone()
    if not r:
        return {"usuario_id": usuario_id, "sistema": sistema or perfil_sei.PADRAO,
                "sei_login": None,
                "mesas_modo": "todas", "mesas": [], "janelas": ["07:30"], "dias": "uteis",
                "modo_coleta": "servidor", "passo": 0, "decididos": [],
                "concluida_em": None, "nova": True}
    d = dict(r)
    d["mesas"] = json.loads(d["mesas"] or "[]")
    d["janelas"] = json.loads(d["janelas"] or "[]")
    d["decididos"] = json.loads(d.get("decididos") or "[]")
    d["nova"] = False
    return d


def gravar(cx, usuario_id, decidiu=None, **campos):
    """Grava a configuração. `decidiu` marca o passo como DECIDIDO pela pessoa.

    O upsert é por `(usuario_id, sistema)`. Trocar de instalação no passo 1 cria
    a configuração da outra em vez de sobrescrever a primeira — e a nova passa a
    ser a ativa por ser a mais recente.
    """
    atual = ler(cx, usuario_id, campos.get("sistema"))
    atual.update(campos)
    if decidiu and decidiu not in atual["decididos"]:
        atual["decididos"] = atual["decididos"] + [decidiu]
    cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,sei_login,mesas_modo,mesas,
                  janelas,dias,modo_coleta,passo,decididos,concluida_em,atualizado_em)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(usuario_id,sistema) DO UPDATE SET
                    sei_login=excluded.sei_login,
                    mesas_modo=excluded.mesas_modo, mesas=excluded.mesas,
                    janelas=excluded.janelas, dias=excluded.dias,
                    modo_coleta=excluded.modo_coleta, passo=excluded.passo,
                    decididos=excluded.decididos,
                    concluida_em=excluded.concluida_em, atualizado_em=excluded.atualizado_em""",
               (usuario_id, atual["sistema"], atual["sei_login"], atual["mesas_modo"],
                json.dumps(atual["mesas"], ensure_ascii=False),
                json.dumps(atual["janelas"], ensure_ascii=False),
                atual["dias"], atual.get("modo_coleta", "servidor"), atual["passo"],
                json.dumps(atual["decididos"], ensure_ascii=False),
                atual["concluida_em"], _carimbo()))
    return atual


def agente_do(cx, usuario_id):
    return cx.execute("""SELECT * FROM agentes WHERE dono_usuario_id=?
                         ORDER BY id DESC LIMIT 1""", (usuario_id,)).fetchone()


def diagnostico(cx, usuario_id):
    """O que falta, em ordem, e o que já está pronto."""
    import cofre
    c = ler(cx, usuario_id)
    ag = agente_do(cx, usuario_id)
    cred = cofre.estado(cx, usuario_id)
    # AS MESAS DESTA PESSOA, não as do banco. `SELECT DISTINCT unidade FROM
    # snapshot` devolve o que a coleta de OUTRA pessoa já trouxe — oferecer isso
    # como "suas mesas" foi o que fez a mesma faixa de seis unidades aparecer
    # para todo mundo. O vínculo é preenchido pelo teste de acesso, com o que o
    # SEI mostrou àquela conta.
    unidades = [r["unidade"] for r in cx.execute(
        "SELECT unidade FROM usuario_unidade WHERE usuario_id=? ORDER BY unidade",
        (usuario_id,))]
    sis = SISTEMAS.get(c["sistema"] or "", {})

    # O passo de acesso só está pronto quando existe o MEIO de entrar, e o meio
    # depende do modo: no servidor, credencial no cofre; na estação, agente
    # pareado. Marcar "pronto" só porque o login foi digitado seria dizer que
    # está configurado quando a coleta ainda não tem como acontecer.
    if c.get("modo_coleta", "servidor") == "servidor":
        acesso_ok = bool(cred)
    else:
        acesso_ok = bool(ag and ag["token_sha256"])

    # Um passo só está pronto quando a PESSOA decidiu E o valor é válido.
    # `mesas` e `horarios` nascem com padrão válido: sem a exigência de decisão,
    # a trilha ficava verde sozinha, o assistente dizia "tudo pronto" e ninguém
    # nunca via a pergunta sobre em que horário o robô entraria na conta dela.
    # `acesso` é a exceção: ali não basta decidir, tem de existir o meio de
    # entrar — credencial no cofre, ou estação pareada.
    decidiu = set(c["decididos"])
    estados = {
        "sistema": bool(c["sistema"] and sis.get("disponivel")) and "sistema" in decidiu,
        "acesso": acesso_ok,
        "mesas": ("mesas" in decidiu
                  and (c["mesas_modo"] == "todas" or bool(c["mesas"]))),
        "horarios": "horarios" in decidiu and bool(c["janelas"]),
    }
    passos, pendente = [], None
    for chave, titulo, sub in PASSOS:
        ok = estados[chave]
        if not ok and pendente is None:
            pendente = chave
        passos.append({"chave": chave, "titulo": titulo, "sub": sub, "ok": ok})

    ultima = cx.execute("""SELECT e.* FROM execucao e JOIN agentes a ON a.id=e.agente_id
                           WHERE a.dono_usuario_id=? ORDER BY e.id DESC LIMIT 1""",
                        (usuario_id,)).fetchone()
    return {
        "config": c, "agente": ag, "credencial": cred, "passos": passos,
        "unidades": unidades, "pendente": pendente, "completa": pendente is None,
        "sistema": sis, "ultima_execucao": ultima, "cofre_disponivel": cofre.disponivel(),
        "prontos": sum(1 for p in passos if p["ok"]), "total": len(PASSOS),
    }
