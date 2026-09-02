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


def _rodar(argumentos, credencial, timeout):
    """Chama o coletor entregando a credencial por stdin."""
    if not COLETOR.exists():
        return 4, f"coletor não encontrado em {COLETOR}", ""
    proc = subprocess.Popen(
        [sys.executable, str(COLETOR), *argumentos, "--credencial-stdin"],
        cwd=str(COLETOR.parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env={"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **_ambiente()})
    try:
        saida, _ = proc.communicate(json.dumps(credencial, ensure_ascii=False) + "\n",
                                   timeout=timeout)
        return proc.returncode, saida, ""
    except subprocess.TimeoutExpired:
        proc.kill()
        # Exit 5 sintético: `page.evaluate` não obedece o timeout do Playwright
        # (medido: 887 s sob teto de 600 s), então quem mata é o relógio de parede.
        return 5, f"morto pelo relógio após {timeout // 60} min", ""


def _ambiente():
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
    return {k: v for k, v in os.environ.items()
            if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "APPDATA",
                     "LOCALAPPDATA", "HOME", "PLAYWRIGHT_BROWSERS_PATH",
                     "SEI_SEM_SANDBOX", "SEI_PERFIL_DIR")}


def sincronizar_unidades(cx, usuario_id, mesas, instancia="SEI-SESAB"):
    """Espelha no `usuario_unidade` o que o SEI mostrou a esta pessoa.

    Devolve (novas, tiradas). Mexe SÓ nos vínculos de origem 'sei': o que um
    admin concedeu à mão fica, porque pode ser acesso excepcional e desfazê-lo
    por um clique em "Testar acesso" seria revogar decisão alheia sem pedir.

    Tirar as que sumiram é tão importante quanto acrescentar as novas: quem foi
    removido de uma unidade no SEI tem de parar de vê-la aqui, e ninguém vai
    lembrar de avisar o sistema.
    """
    if not mesas:
        return [], []
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
        login, senha = cofre.abrir(cx, usuario_id, motivo="teste_de_acesso", ip=ip,
                                   sistema=_instancia_de(cx, usuario_id))
    except ValueError as ex:
        return False, str(ex)
    cx.commit(); cx.close()
    if not login:
        return False, "Nenhuma credencial guardada.", ""

    codigo, saida, _ = _rodar(["--testar-login"], {"usuario": login, "senha": senha},
                              TIMEOUT_TESTE_S)
    linha = next((l for l in saida.splitlines() if l.startswith("TESTE_OK ")), None)
    cx = conectar()
    if codigo == 0 and linha:
        quem = json.loads(linha[len("TESTE_OK "):])
        mesas = [m for m in (quem.get("mesas") or []) if m]
        # O QUE O SEI MOSTROU vira o vínculo. A fronteira do SEI360 passa a ser
        # a do SEI daquela pessoa, provada por ela ter entrado — e não uma lista
        # que um admin montou a partir da coleta de outro.
        novas, tiradas = sincronizar_unidades(cx, usuario_id, mesas,
                                              _instancia_de(cx, usuario_id)
                                              or "SEI-SESAB")
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
    registrar(cx, usuario_id, "teste_acesso_falhou", alvo=f"exit {codigo}", ip=ip)
    cx.commit(); cx.close()
    motivos = {
        3: "O SEI não aceitou o login. Confira o e-mail e a senha — e lembre que "
           "trocar a senha no SEI exige atualizá-la aqui também.",
        4: "Falha de infraestrutura: o navegador de automação não subiu nesta máquina.",
        5: "O SEI não respondeu a tempo. Pode ser a rede do órgão ou o próprio SEI fora do ar.",
        2: "Entrou, mas não devolveu dados.",
    }
    # As últimas linhas do log ajudam quem for diagnosticar; a senha não aparece
    # nelas porque o coletor nunca a imprime.
    cauda = " · ".join(l.strip() for l in saida.splitlines()[-3:] if l.strip())
    return False, motivos.get(codigo, f"Falhou com código {codigo}."), cauda[:300]
