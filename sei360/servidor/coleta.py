# -*- coding: utf-8 -*-
"""
Execução da coleta a partir do servidor, com a credencial guardada no cofre.

COMO A SENHA CHEGA AO PLAYWRIGHT
--------------------------------
Esta é a resposta concreta à pergunta "se a senha fica cifrada, como o Playwright
usa?". A sequência é:

  1. o servidor decifra em memória, no instante da coleta, e registra o uso
  2. entrega ao processo do coletor por STDIN, uma linha JSON
  3. o coletor injeta no navegador pela API que o próprio `automacao_sei.js` já
     expõe (`SEIAuto.credencial`), e o Playwright preenche o formulário do SEI

Por STDIN, e não por argumento nem variável de ambiente: argumento aparece na
lista de processos para qualquer um logado na máquina, e variável de ambiente
vaza em `docker inspect` e no dump de qualquer filho. Por stdin, o valor vive no
buffer do processo e morre com ele.

A senha nunca é escrita em disco por este módulo, nunca aparece em log e nunca
volta para nenhuma tela.
"""
import json
import subprocess
import sys
from pathlib import Path

import cofre
import perfil_sei
from banco import agora, conectar, registrar

def _achar_coletor():
    """Onde está o coletor. Na estação é o irmão do repositório; na imagem, /app.

    A constante antiga apontava só para o irmão — um caminho que NÃO existe dentro
    do container, porque o Dockerfile copia apenas `servidor/`. Enquanto o
    servidor não executava nada isso era inofensivo; desde que ele executa, um
    caminho errado vira "coletor não encontrado" no meio de uma busca.
    """
    import os
    if os.environ.get("SEI360_COLETOR"):
        return Path(os.environ["SEI360_COLETOR"])
    aqui = Path(__file__).resolve().parent
    for c in (aqui.parent.parent / "painel_sesab" / "coletor_sesab.py",
              aqui / "painel_sesab" / "coletor_sesab.py",
              Path("/app/painel_sesab/coletor_sesab.py")):
        if c.exists():
            return c
    return aqui.parent.parent / "painel_sesab" / "coletor_sesab.py"


COLETOR = _achar_coletor()
TIMEOUT_TESTE_S = 120
TIMEOUT_COLETA_S = 30 * 60


def _rodar(argumentos, credencial, timeout, usuario_id=None, instancia=None):
    """Chama o coletor entregando a credencial por stdin."""
    if not COLETOR.exists():
        return 4, f"coletor não encontrado em {COLETOR}", ""
    proc = subprocess.Popen(
        [sys.executable, str(COLETOR), *argumentos, "--credencial-stdin"],
        cwd=str(COLETOR.parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env={"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
             **_ambiente(usuario_id, instancia)})
    try:
        saida, _ = proc.communicate(json.dumps(credencial, ensure_ascii=False) + "\n",
                                   timeout=timeout)
        return proc.returncode, saida, ""
    except subprocess.TimeoutExpired:
        proc.kill()
        # Exit 5 sintético: `page.evaluate` não obedece o timeout do Playwright
        # (medido: 887 s sob teto de 600 s), então quem mata é o relógio de parede.
        return 5, f"morto pelo relógio após {timeout // 60} min", ""


def _ambiente(usuario_id=None, instancia=None):
    import os
    # A credencial NÃO entra no ambiente do filho. O que passa é só o mínimo para
    # o Python e o Playwright acharem o que precisam.
    # `SEI_SEM_SANDBOX` e `SEI_PERFIL_DIR` PRECISAM passar. Sem a primeira, o
    # Chromium sobe com sandbox dentro do container e morre no start — e "Testar
    # acesso" falharia com uma mensagem que parece senha errada. Sem a segunda, o
    # perfil cai em `painel_sesab/_perfil_sei`, dentro da IMAGEM: some a cada
    # redeploy, e cada teste vira um login novo (que é onde o segundo fator
    # aparece). Nenhuma das duas é segredo — a primeira é um interruptor, a
    # segunda é um caminho.
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "APPDATA",
                    "LOCALAPPDATA", "HOME", "PLAYWRIGHT_BROWSERS_PATH",
                    "SEI_SEM_SANDBOX", "SEI_PERFIL_DIR")}
    if usuario_id is None:
        return env
    # UM PERFIL POR PESSOA E POR INSTALAÇÃO — a mesma correção que a BUSCA já
    # tinha e que esta função não recebeu, achada em 12/09/2026.
    #
    # `SEI_PERFIL_DIR` cru é `/dados/_perfil_sei`: UM perfil de Chromium para
    # todas as contas. O comentário de `atendente.executar` descreve o preço,
    # medido lá: "a busca de B reaproveitava a sessão do SEI de A — `goto(LOGIN)`
    # nem caía em login.php, e o SEI gravava as consultas de B com o nome de A. O
    # cofre registrava 'B usou a credencial' e o log do SEI dizia outra coisa".
    # Numa COLETA o efeito é maior: ela abre o Controle de Processos de seis
    # mesas, e desde 11/09/2026 sabe-se que abrir a mesa RECEBE os processos em
    # trânsito dela — ou seja, a coleta de B praticaria atos no SEI em nome de A.
    #
    # E DE GRAÇA VEM A ECONOMIA que este módulo não tinha: o acompanhamento e a
    # busca da MESMA pessoa na MESMA instalação passam a achar o cookie que a
    # coleta deixou. Um login por pessoa por instalação neste container, em vez
    # de um por execução — e login novo é exatamente onde o segundo fator
    # aparece, sem ninguém na tela para digitar.
    import atendente                                    # tardio: evita ciclo
    env["SEI_PERFIL_DIR"] = str(atendente._perfil_de(usuario_id, instancia))
    # A SENHA NÃO FICA NO PERFIL. Ela chega por stdin a cada execução daqui,
    # então o coletor pode apagá-la do `localStorage` depois de logar e o perfil
    # guarda só o cookie. Na ESTAÇÃO a variável não existe e a credencial fica,
    # porque lá a coleta agendada roda sem stdin e depende dela — e este módulo
    # é só do servidor (nenhum arquivo de `sei360/agente/` o importa).
    env["SEI_ESQUECER_APOS_LOGIN"] = "1"
    return env


def instancia_do_usuario(cx, usuario_id, registrar_aviso=None):
    """A instalação desta pessoa: a credencial única, senão a configuração ativa.

    O PADRÃO ESCRITO À MÃO ERA A FONTE DO ERRO. `"SEI-SESAB"` aparecia como valor
    default aqui e como `or "SEI-SESAB"` em `testar_acesso`: quem só tem conta na
    FESF teria as mesas dela gravadas como vínculos da SESAB — acesso à carteira
    de outro órgão, criado em silêncio por um argumento omitido.

    Deriva do que existe, nesta ordem: credencial guardada (se houver só uma, é
    dela que a coleta usa a senha), configuração ativa, e só então o padrão — com
    aviso no log, porque cair no padrão é um palpite, não uma leitura.
    """
    r = cx.execute("SELECT sistema FROM credencial WHERE usuario_id=?",
                   (usuario_id,)).fetchall()
    if len(r) == 1 and perfil_sei.existe(r[0]["sistema"]):
        return r[0]["sistema"]
    c = cx.execute("""SELECT sistema FROM config_usuario WHERE usuario_id=?
                      ORDER BY atualizado_em DESC, sistema LIMIT 1""",
                   (usuario_id,)).fetchone()
    if c and perfil_sei.existe(c["sistema"]):
        return c["sistema"]
    if registrar_aviso:
        registrar(cx, usuario_id, "instancia_presumida",
                  alvo=f"{registrar_aviso} · sem credencial nem configuração; "
                       f"assumido {perfil_sei.PADRAO}")
    return perfil_sei.PADRAO


def sincronizar_unidades(cx, usuario_id, mesas, instancia=None):
    """Espelha no `usuario_unidade` o que o SEI mostrou a esta pessoa.

    Devolve (novas, tiradas). Mexe SÓ nos vínculos de origem 'sei': o que um
    admin concedeu à mão fica, porque pode ser acesso excepcional e desfazê-lo
    por um clique em "Testar acesso" seria revogar decisão alheia sem pedir.

    Tirar as que sumiram é tão importante quanto acrescentar as novas: quem foi
    removido de uma unidade no SEI tem de parar de vê-la aqui, e ninguém vai
    lembrar de avisar o sistema.

    `instancia=None` DERIVA da pessoa em vez de assumir a SESAB — ver
    `instancia_do_usuario`. O default literal de antes gravava mesa da FESF como
    vínculo da SESAB toda vez que alguém esquecesse o argumento.
    """
    if not mesas:
        return [], []
    if not instancia:
        instancia = instancia_do_usuario(cx, usuario_id,
                                         registrar_aviso="sincronizar_unidades")
    # AS TRÊS CONSULTAS FILTRAM PELA INSTALAÇÃO. Nome de unidade não é único
    # entre instalações, e `usuario_unidade` tem a coluna desde a migração das
    # duas. Sem o filtro, sincronizar as mesas da SESAB APAGARIA os vínculos da
    # FESF — o DELETE não distinguia — e os novos nasceriam todos como
    # `SEI-SESAB`, pelo default do DDL. A pessoa perderia o acesso à carteira da
    # outra instalação, e nada na tela explicaria por quê.
    atuais = {r["unidade"]: r["origem"] for r in cx.execute(
        "SELECT unidade, COALESCE(origem,'admin') origem FROM usuario_unidade "
        "WHERE usuario_id=? AND instancia=?", (usuario_id, instancia))}
    desejadas = set(mesas)
    novas = [m for m in sorted(desejadas) if m not in atuais]
    for m in novas:
        cx.execute("""INSERT OR IGNORE INTO usuario_unidade
                      (usuario_id,instancia,unidade,concedida_em,origem)
                      VALUES(?,?,?,?,'sei')""", (usuario_id, instancia, m, agora()))
    tiradas = [u for u, o in atuais.items() if o == "sei" and u not in desejadas]
    for u in tiradas:
        cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=? AND instancia=? "
                   "AND unidade=? AND origem='sei'", (usuario_id, instancia, u))
    if novas or tiradas:
        registrar(cx, usuario_id, "unidades_do_sei",
                  alvo=f"{instancia} · +{len(novas)} -{len(tiradas)}")
    return novas, tiradas


def _instancia_de(cx, usuario_id):
    """A instalação do SEI desta pessoa, ou None quando não dá para escolher.

    NONE COM DUAS, de propósito. A versão anterior tinha um `if/else` cujos dois
    ramos devolviam `r[0]["sistema"]` — um erro de digitação que escolhia a
    PRIMEIRA credencial no escuro. Com credencial na SESAB e na FESF, "Testar
    acesso" testava a instalação errada, e o SEI respondia com o que parece senha
    inválida: a mensagem que manda a pessoa trocar uma senha que está certa.

    Devolvendo None, `cofre.abrir` recusa com a mensagem que ele já tem — "o
    usuário tem credencial em N instalações; diga qual" —, que é verdadeira.
    """
    r = cx.execute("SELECT sistema FROM credencial WHERE usuario_id=?",
                   (usuario_id,)).fetchall()
    return r[0]["sistema"] if len(r) == 1 else None


def testar_acesso(usuario_id, ip=None):
    """Entra no SEI com a credencial guardada, confere e sai. Não coleta nada.

    Devolve (ok, mensagem, detalhe). É o que transforma "configurei e torço" em
    "configurei e vi funcionar" — sem isso, a primeira notícia de senha errada
    chega às 7h31 do dia seguinte, com a janela já perdida.
    """
    cx = conectar()
    # COM `sistema=`: com duas instalações guardadas, `abrir` sem dizer qual
    # RECUSA (e com razão — a credencial de uma preencheria o login da outra,
    # falhando de um jeito que parece senha errada).
    # COM DUAS INSTALAÇÕES, `abrir` RECUSA — e recusar é o certo. O que não pode
    # é a recusa virar 500: `_instancia_de` devolve None de propósito nesse caso,
    # e `cofre.abrir` levanta ValueError com uma mensagem que já explica tudo.
    # Ela vira a resposta da tela, não um erro sem texto.
    try:
        instancia = _instancia_de(cx, usuario_id)
        login, senha = cofre.abrir(cx, usuario_id, motivo="teste_de_acesso", ip=ip,
                                   sistema=instancia)
    except ValueError as ex:
        # TRÊS valores, como todo retorno desta função: a rota desempacota três,
        # e com dois a recusa explicada virava 500.
        cx.close()
        return False, str(ex), ""
    if not login:
        cx.close()
        return False, "Nenhuma credencial guardada.", ""
    # O PERFIL DA INSTALAÇÃO VIAJA COM A CREDENCIAL. Sem ele o coletor cai na
    # constante interna — a SESAB — e o teste de uma credencial da FESF batia na
    # URL de login da SESAB, falhando de um jeito que parece senha errada (achado
    # de 07/09/2026, na porta do parser 4.0). A busca já mandava o envelope
    # (`atendente.py`); o teste de acesso era o único caminho que não mandava.
    instancia = instancia or instancia_do_usuario(cx, usuario_id, "teste_de_acesso")
    envelope = perfil_sei.envelope_do_coletor(instancia)
    cx.commit(); cx.close()

    # O PERFIL É DESTA PESSOA NESTA INSTALAÇÃO, e aqui isso vale mais que na
    # coleta: o que este teste lê — as mesas que o SEI mostrou — VIRA O VÍNCULO
    # da conta (logo abaixo). Num perfil compartilhado, o teste de B podia cair
    # na sessão de A e gravar as mesas de A como vínculos de B: acesso à carteira
    # de outra pessoa, criado em silêncio por um diretório.
    codigo, saida, _ = _rodar(["--testar-login"],
                              {"usuario": login, "senha": senha, "perfil": envelope},
                              TIMEOUT_TESTE_S,
                              usuario_id=usuario_id, instancia=instancia)
    linha = next((l for l in saida.splitlines() if l.startswith("TESTE_OK ")), None)
    cx = conectar()
    if codigo == 0 and linha:
        import diario
        diario.guardar_saida("teste", f"u{usuario_id}-{agora()[:19].replace(':', '')}", saida)
        quem = json.loads(linha[len("TESTE_OK "):])
        mesas = [m for m in (quem.get("mesas") or []) if m]
        # O QUE O SEI MOSTROU vira o vínculo. A fronteira do SEI360 passa a ser
        # a do SEI daquela pessoa, provada por ela ter entrado — e não uma lista
        # que um admin montou a partir da coleta de outro.
        #
        # A INSTALAÇÃO É A QUE FOI TESTADA. O `or "SEI-SESAB"` de antes era um
        # palpite disfarçado de default: quem tem credencial só na FESF teria as
        # mesas dela gravadas como SESAB. `instancia_do_usuario` lê a credencial
        # e, na falta dela, a configuração — e registra quando não achou nenhuma.
        novas, tiradas = sincronizar_unidades(
            cx, usuario_id, mesas,
            _instancia_de(cx, usuario_id)
            or instancia_do_usuario(cx, usuario_id, registrar_aviso="testar_acesso"))
        registrar(cx, usuario_id, "teste_acesso_ok",
                  alvo=f"{quem.get('unidade') or '-'} · {len(mesas)} mesa(s)", ip=ip)
        cx.commit(); cx.close()
        detalhe = f"Entrou como {quem.get('usuario') or login}"
        if quem.get("unidade"):
            detalhe += f" · unidade ativa: {quem['unidade']}"
        if mesas:
            detalhe += f" · o SEI mostra {len(mesas)} mesa(s) para esta conta"
            if novas:
                detalhe += f", {len(novas)} nova(s)"
            if tiradas:
                detalhe += f"; {len(tiradas)} deixaram de aparecer e saíram"
        else:
            # Login provado e nenhuma mesa listada é um estado real e ambíguo:
            # pode ser conta de unidade única, pode ser o seletor ter mudado de
            # forma. Dizer isso é melhor que deixar a tela vazia sem explicação.
            detalhe += " · não consegui listar as mesas desta conta"
        return True, "Acesso confirmado no SEI.", detalhe
    # O QUE O SEI RESPONDEU, e não a cauda do log. Em 15/09/2026 uma pessoa clicou
    # três vezes em três minutos e viu três vezes "O SEI não aceitou o login" com
    # a cauda — que era o banner do motor JS. A frase do SEI existia na tela de
    # login e não era lida.
    import diario
    import leitura_saida
    c = leitura_saida.causa(codigo, saida)
    arquivo = diario.guardar_saida("teste", f"u{usuario_id}-{agora()[:19].replace(':', '')}", saida)
    registrar(cx, usuario_id, "teste_acesso_falhou",
              alvo=f"exit {codigo} · {c['chave']} · {c['texto'][:160]}", ip=ip)
    if c["chave"] in leitura_saida.CAUSAS_DE_LOGIN and c["certeza"] and instancia:
        import cofre as _cofre
        _cofre.marcar_recusa(cx, usuario_id, instancia, c["texto"])
    cx.commit(); cx.close()
    print(f"teste de acesso: usuário {usuario_id} · {instancia} · código {codigo} · "
          f"{c['texto'][:240]}" + (f" · saída em log/execucoes/{arquivo}" if arquivo else ""),
          flush=True)
    motivos = {
        3: "O SEI não aceitou o login. Confira o e-mail e a senha — e lembre que "
           "trocar a senha no SEI exige atualizá-la aqui também.",
        4: "Falha de infraestrutura: o navegador de automação não subiu nesta máquina.",
        5: "O SEI não respondeu a tempo. Pode ser a rede do órgão ou o próprio SEI fora do ar.",
        2: "Entrou, mas não devolveu dados.",
    }
    detalhe = c["texto"][:1].upper() + c["texto"][1:]
    if c["chave"] in leitura_saida.CAUSAS_DE_LOGIN and c["certeza"]:
        detalhe += (" Antes de testar de novo, salve a senha outra vez em Acesso: cada "
                    "tentativa com a senha errada conta para o bloqueio da sua conta no SEI.")
    return False, motivos.get(codigo, f"Falhou com código {codigo}."), detalhe[:600]


# ---------------------------------------------------------------------------
# COLETA PELA ESTAÇÃO QUE TAMBÉM É O SERVIDOR — 07/09/2026
#
# Enquanto o servidor roda NA MESMA máquina da coleta (hoje: Flask local em
# 127.0.0.1), não há por que a credencial morar em dois lugares. O cofre
# (AES-256-GCM, chave fora do banco) é custódia MELHOR que o `btoa` do
# localStorage do perfil, e a pessoa só digita a senha num lugar: o passo
# "acesso" de /configuracao. O wrapper agendado (`_run_coleta.cmd`) chama
# `python coleta.py coletar <usuario_id> <instancia>`; a credencial vai por
# stdin ao mesmo `coletor_sesab.py` de sempre, com o perfil da instalação.
#
# NÃO é "o servidor coleta": no VPS este comando não roda — lá o executor da
# coleta continua sendo o agente na estação (ARQUITETURA_ACESSO §7.1). O que
# muda é só de onde sai a senha quando estação e servidor coincidem.
# ---------------------------------------------------------------------------
def coletar(usuario_id, instancia, somente=None, amostra=None, timeout=None):
    """Roda a coleta (ou uma amostra) da instalação com a credencial do cofre.

    Devolve (codigo, saida). Recusa, com motivo do perfil, instalação cujo
    parser ainda não foi provado (`disponivel_coleta: False`) — a menos que seja
    `amostra`, que é justamente a prova. Nunca imprime a credencial.
    """
    if not perfil_sei.existe(instancia):
        return 4, f"instalação desconhecida: {instancia!r}"
    p = perfil_sei.perfil(instancia)
    if not p["disponivel_coleta"] and not amostra:
        return 4, (f"{instancia}: coleta ainda indisponível — "
                   f"{p.get('motivo_sem_coleta') or 'sem parser provado'}")
    cx = conectar()
    try:
        login, senha = cofre.abrir(cx, usuario_id, motivo="coleta_estacao", sistema=instancia)
    except ValueError as ex:
        cx.close()
        return 3, f"cofre: {ex}"
    if not login:
        cx.close()
        return 3, f"nenhuma credencial guardada para o usuário {usuario_id} em {instancia}"
    registrar(cx, usuario_id, "coleta_estacao",
              alvo=f"{instancia} · {'amostra ' + amostra if amostra else 'coleta'}"
                   + (f" · somente {','.join(somente)}" if somente else ""))
    cx.commit(); cx.close()
    args = ["--testar-login", "--amostra", amostra] if amostra else ["--mesas"]
    if somente and not amostra:
        args += ["--somente", ",".join(somente)]
    cred = {"usuario": login, "senha": senha, "perfil": perfil_sei.envelope_do_coletor(instancia)}
    del senha
    return _rodar(args, cred,
                  timeout or (TIMEOUT_TESTE_S * 3 if amostra else TIMEOUT_COLETA_S),
                  usuario_id=usuario_id, instancia=instancia)[:2]


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="coleta pela estação que também é o servidor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coletar", help="coleta com a credencial do cofre")
    c.add_argument("usuario_id", type=int)
    c.add_argument("instancia")
    c.add_argument("--somente", help="siglas separadas por vírgula (prova curta)")
    c.add_argument("--amostra", help="lista UMA mesa e sai, sem gravar (prova do parser)")
    a = ap.parse_args()
    codigo, saida = coletar(a.usuario_id, a.instancia,
                            somente=a.somente.split(",") if a.somente else None,
                            amostra=a.amostra)
    print(saida if isinstance(saida, str) else "")
    print(f"coleta.py: {a.instancia} exit={codigo}")
    sys.exit(codigo)
