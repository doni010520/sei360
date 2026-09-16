# -*- coding: utf-8 -*-
"""
O executor de buscas DENTRO do servidor.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
Até 21/08/2026 o servidor não executava nada: quem tinha navegador era a estação
da pessoa, e o container servia painel. O dono do sistema decidiu hospedar em VPS
próprio (EasyPanel/HostGator) e rodar a busca AQUI. Isso revoga o §6.1 e o §3.7 do
ARQUITETURA_ACESSO.md — a revogação está escrita lá, com o nome de quem decidiu e
o que ela custa. Este módulo é a consequência técnica dela, não a decisão.

O QUE ELE FAZ
-------------
Um laço que pega uma busca `pedida` de quem está em modo `servidor`, decifra a
credencial no instante do uso, chama o mesmo `coletor_sesab.py --buscar` que a
estação chamaria, e devolve o resultado por `busca.receber` — a MESMA função que
recebe o resultado do agente. O veredito continua sendo calculado do que foi
medido, e não aceito de quem executou: quem roda a busca não decide se ela foi
completa, aqui ou lá.

O QUE ELE NÃO FAZ
-----------------
Não decide se PODE rodar. `capacidade()` responde isso olhando o que existe de
fato — coletor no disco, Playwright importável, chave do cofre — e a tela usa a
mesma resposta para desligar o botão ANTES de a pessoa preencher dez campos. Um
servidor sem navegador que aceita buscas é o defeito que já aconteceu com a
estação, com outro nome.

O TETO É DE MEMÓRIA, NÃO DE FILA
--------------------------------
Cada busca custa ~0,45 GB (medido em produção no sistema irmão). `LIMITE` existe
para o container não morrer por OOM no meio de dez pedidos — e o padrão é
deliberadamente baixo. Duas buscas da MESMA conta já eram impossíveis antes deste
módulo: a troca de mesa no SEI é por USUÁRIO, não por sessão, e `busca_trava`
guarda isso. `LIMITE` é sobre pessoas diferentes ao mesmo tempo.
"""
import json
import os
import subprocess
import sys
import threading
import time

import banco
import busca as bmod
import cofre
import perfil_sei
from coleta import COLETOR

# Quantas buscas de pessoas DIFERENTES podem correr ao mesmo tempo neste
# container. ~0,45 GB cada. Dois cabem em 2 GB junto com o painel; acima disso o
# OOM killer escolhe a vítima, e ele costuma escolher o gunicorn.
LIMITE = max(1, int(os.environ.get("SEI360_BUSCAS_SIMULTANEAS", "2")))
# De quanto em quanto tempo o laço olha a fila. 3 s porque alguém está na tela
# esperando; a consulta é um índice sobre uma tabela pequena.
INTERVALO_S = 3
# Teto de parede da execução. O mesmo de `busca.SEGUNDOS_TETO`, repetido aqui
# porque quem mata o processo é este módulo: `page.evaluate` não obedece o
# timeout do Playwright (medido: 887 s sob teto de 600 s).
_vagas = threading.BoundedSemaphore(LIMITE)
# TRABALHO PESADO — coleta diária e acompanhamento —, UM POR VEZ neste container.
#
# Os dois só começavam com "tudo ocioso" (`vagas_livres() == LIMITE`), e o teste
# era leitura seguida de `acquire`: com LIMITE=2 as duas threads passavam juntas
# pela leitura e tomavam as duas vagas, e toda busca ficava sem vaga por até 30
# min. Um lock sem espera fecha a janela: quem não o toma não começa.
#
# E ele é o que permite a `capacidade()` distinguir "vagas perdidas" de "vaga
# segurada por uma coleta legítima" — as threads dessas não se chamam `busca-*`.
_pesado = threading.Lock()
# QUEM É ESTE PROCESSO, para as travas de conta que a coleta e o acompanhamento
# tomam. Só o executor do container roda os dois; trava de motor com outro token é
# de um executor que morreu sem soltar (ver `busca.limpar_travas_de_motor`).
import secrets as _secrets
TOKEN = _secrets.token_hex(6)
# De quantas em quantas voltas o laço varre as buscas presas por conta própria.
# A varredura só rodava quando alguém poleava a tela: fechar a aba deixava busca
# 'entregue' órfã e a conta travada até outra pessoa abrir a busca.
VARRER_A_CADA = 20
_laco_vivo = threading.Event()
# A thread do laço, quando ela existe. Declarada aqui, e não só junto de
# `iniciar()`, para `vivo()` poder ser chamada antes de qualquer subida.
_thread = None


# --------------------------------------------------------------- capacidade
def capacidade():
    """(pode, motivo). Por que este servidor pode ou não executar uma busca.

    Chamado pela tela ANTES do botão e por `busca.quem_executa` antes de
    enfileirar. Responde do que EXISTE — não de configuração —, porque a pergunta
    é "há navegador aqui?", e configuração não instala navegador.
    """
    # DEFEITO DO SERVIDOR VEM PRIMEIRO. Falta de configuração se
    # resolve configurando; vaga perdida não se resolve de fora, e
    # esconder isso atrás de "falta a chave" manda procurar no lugar errado.
    livres = vagas_livres()
    if livres == 0 and not _pesado.locked() and not any(
            t.name.startswith("busca-") and t.is_alive() for t in threading.enumerate()):
        # ZERO VAGAS E NENHUMA BUSCA RODANDO é estado impossível de fora: ou
        # alguém está executando, ou as vagas deveriam estar livres. Era o
        # sintoma do vazamento, e não aparecia em lugar nenhum — a pessoa via
        # "o agente não está rodando", que aponta para o componente errado.
        return False, ("as vagas de busca deste servidor se perderam "
                       f"({LIMITE} ocupadas, nenhuma execução em curso). "
                       "É um defeito do servidor, não da sua estação: "
                       "reinicie o serviço e relate.")
    if not COLETOR.exists():
        return False, f"o coletor não está nesta imagem ({COLETOR})"
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False, "o Playwright não está instalado nesta imagem"
    if not cofre.disponivel():
        return False, f"o cofre está indisponível (falta {cofre.VAR_CHAVE})"
    vazando = _segredo_na_imagem()
    if vazando:
        # RECUSA EM VEZ DE FUNCIONAR. Uma imagem que carrega a senha em texto puro
        # de alguém funciona perfeitamente — é esse o problema. Recusar aqui é o
        # único momento em que a falha vira visível antes de o segredo já estar no
        # host alugado há semanas.
        return False, vazando
    return True, None


def _segredo_na_imagem():
    """Credencial em texto puro no que veio junto do coletor, ou None.

    O `automacao_sei.js` aceita a credencial de duas formas: o bloco CONFIG do
    arquivo, ou o localStorage do perfil. A primeira transforma o arquivo em
    material de credencial — e este servidor entrega a credencial por stdin
    justamente para não depender dela. CONFIG preenchido aqui significa que a
    senha de alguém subiu junto com a imagem.

    Nunca lê o valor: devolve arquivo e linha, e mais nada.
    """
    import re
    js = COLETOR.parent / "automacao_sei.js"
    if not js.exists():
        return None
    try:
        texto = js.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for m in re.finditer(r"\b(usuario|senha)\s*:\s*([\"\'])(.*?)\2", texto):
        if m.group(3).strip():
            linha = texto[:m.start()].count("\n") + 1
            return (f"há credencial em texto puro em automacao_sei.js:{linha} — "
                    f"esta imagem carrega a senha de alguém. Esvazie o bloco CONFIG "
                    f"(ARQUITETURA_ACESSO.md §6.2) e rebuild; a busca entrega a "
                    f"credencial por stdin e não precisa dele.")
    return None


def vagas_livres():
    """Quantas vagas estão livres agora. Só para diagnóstico e para a tela.

    `_value` é atributo interno do `BoundedSemaphore`; ler é seguro, e a
    alternativa (contar threads `busca-*`) mente enquanto uma thread está
    terminando. Se um dia sumir, a função devolve None e quem chama diz "não sei"
    em vez de estourar.
    """
    try:
        return _vagas._value
    except AttributeError:
        return None


def ha_executor():
    """Existe um executor de busca vivo NESTE CONTAINER? (qualquer worker)

    Diferente de `vivo()`, que só sabe deste processo. Com `--workers 3`, dois
    workers servem painel e nada sabem do executor — mas precisam saber que ele
    EXISTE, para não matarem a fila dele.

    A fonte é o mesmo arquivo de vez que `_tomar_a_vez()` cria: é o único estado
    que processos irmãos compartilham.
    """
    if vivo() or _fd_vez is not None:
        return True
    # A PERGUNTA É FEITA AO SISTEMA OPERACIONAL: se conseguimos travar, ninguém
    # segurava — logo não há executor. Se não conseguimos, há. Nada é lido do
    # conteúdo, e um processo morto não deixa resposta errada para trás.
    trava = banco.DADOS_DIR / ".atendente.lock"
    if not trava.exists():
        return False
    try:
        fd = os.open(str(trava), os.O_CREAT | os.O_RDWR)
    except OSError:
        return False
    try:
        if _travar_fd(fd):
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            return False                         # estava livre: não há executor
        return True
    finally:
        os.close(fd)


def vivo():
    """A thread do laço está viva NESTE processo?

    Diferente de `capacidade()`: aquela responde "há navegador aqui?" e é
    recalculada a cada requisição; esta responde "há quem drene a fila?". A
    thread pode ter morrido — `capacidade()` levantando na primeira chamada, por
    exemplo — e a capacidade continuar dizendo que sim, com toda busca ficando em
    `pedida` até morrer aos 90 s enquanto a tela promete execução.
    """
    return bool(_thread and _thread.is_alive())


def ligado():
    """O laço deve rodar neste processo?

    Desligar por variável é o que permite subir um container só de painel e outro
    só de execução, sem duas imagens. Ligado por padrão: quem escolheu hospedar
    a execução aqui não deveria ter de lembrar de mais um interruptor.
    """
    return os.environ.get("SEI360_ATENDENTE", "1") not in ("0", "nao", "não", "off")


# ------------------------------------------------------------------ a fila
def pegar(cx):
    """Reivindica UMA busca de quem está em modo servidor, ou None.

    A reivindicação é o próprio UPDATE com `AND estado='pedida'`: se dois
    processos lerem a mesma linha, só um vê `rowcount == 1`. Sem isso, dois
    workers do gunicorn — ou um segundo container — executariam a mesma busca com
    o mesmo login, que é exatamente a corrida que a troca de mesa do SEI não
    tolera.
    """
    # `tentar_apos`: a nova tentativa espera a sua vez. Sem a condição, a repetição
    # começaria no mesmo segundo da falha — e a falha passageira (rede, SEI lento)
    # ainda estaria lá.
    for r in cx.execute("""SELECT b.* FROM busca b
                           JOIN config_usuario c
                             ON c.usuario_id=b.usuario_id AND c.sistema=b.instancia
                           WHERE b.estado='pedida' AND c.modo_coleta='servidor'
                             AND (b.tentar_apos IS NULL OR b.tentar_apos <= ?)
                           ORDER BY b.id LIMIT 20""", (banco.agora(),)).fetchall():
        # A CONTA COM OUTRO DONO — uma coleta, um acompanhamento, outra busca da
        # mesma conta — não recebe esta busca agora. A troca de mesa no SEI é por
        # usuário: entregar aqui trocaria a mesa debaixo de quem está lá.
        if bmod.trava_de_outro(cx, r["instancia"], r["conta"], r["id"]):
            continue
        cur = cx.execute("UPDATE busca SET estado='entregue', entregue_em=? "
                         "WHERE id=? AND estado='pedida'", (banco.agora(), r["id"]))
        if cur.rowcount != 1:
            cx.commit()
            continue
        # A TRAVA É RENOVADA NA ENTREGA, contada da execução e não do pedido. Com a
        # trava de 20 min contada do pedido, uma busca que esperou 12 min na fila
        # começava com 8 min de trava para 10 de execução — e a conta ficava livre
        # para outro pedido e para a coleta no meio da pesquisa.
        bmod._travar(cx, r["instancia"], r["conta"], r["id"],
                     minutos=bmod.SEGUNDOS_TETO // 60 + 4)
        cx.commit()
        return r
    cx.commit()
    return None


# --------------------------------------------------------------- a execução
def executar(cx, r):
    """Roda uma busca e grava o resultado. Devolve (estado, motivo).

    Só sai daqui por `busca.receber`, inclusive quando o processo morre: uma
    busca marcada `entregue` que nunca volta fica presa até a varredura, e a
    conta fica travada junto. O `finally` é o que garante que a pessoa sempre
    recebe uma resposta, mesmo que a resposta seja "falhou".
    """
    bid = r["id"]
    envelope = {"busca_id": bid, "itens": [], "total_declarado": None,
                "motivo": "o servidor não chegou a executar a busca"}
    # PASSAGEIRA OU PERMANENTE — é isso que decide se há nova tentativa. Nasce
    # permanente: só o que foi reconhecido como oscilação ganha outra execução.
    passageira = False
    saida = ""
    inicio = time.time()
    try:
        p = perfil_sei.perfil(r["instancia"])
        login, senha = cofre.abrir(cx, r["usuario_id"],
                                   motivo=f"busca {bid}", sistema=r["instancia"])
        # FECHA A TRANSAÇÃO ANTES DE ABRIR O NAVEGADOR. `cofre.abrir` escreve —
        # `UPDATE credencial` mais o `registrar()` do uso —, e com o
        # `isolation_level` padrão isso deixa uma transação de ESCRITA aberta.
        # Sem este commit ela só fecharia depois do `communicate()`, isto é,
        # depois de até 10 minutos de Chromium.
        #
        # No WAL, escritor não bloqueia leitor — mas bloqueia OUTRO ESCRITOR. E
        # toda requisição autenticada deste sistema escreve: `usuario_atual()`
        # faz `UPDATE sessoes SET ultimo_uso_em` a cada clique. Medido: em 11 s
        # de contenção, 2 de 3 escritas morreram com `database is locked`, e o
        # `busy_timeout` é de 5 s contra uma janela de até 600.
        #
        # E o registro do USO da credencial tem de ficar gravado de qualquer
        # jeito: ele é a procedência de "esta senha foi aberta, nesta hora, para
        # esta busca" — inclusive quando a busca falha depois.
        cx.commit()
        if not senha:
            envelope["motivo"] = ("não há credencial guardada para "
                                  f"{r['instancia']} — configure o acesso")
            return None
        pedido = {
            "usuario": login, "senha": senha,
            "perfil": perfil_sei.envelope_do_coletor(r["instancia"]),
            "busca": {"busca_id": bid, "instancia": r["instancia"],
                      "mesa": r["mesa"], "filtros": json.loads(r["filtros"]),
                      "campos": p["campos_busca"],
                      "paginas_teto": r["paginas_teto"] or bmod.PAGINAS_TETO,
                      # Para onde devolver a conta depois — a origem da PRIMEIRA
                      # execução, quando houver. Ver `busca.mesa_origem`.
                      "volta_para": r["mesa_origem"] if "mesa_origem" in r.keys() else None,
                      # O motor JS para de paginar antes do teto de fora e devolve
                      # o que já leu: busca grande vira 'parcial' com itens, e não
                      # 'falhou' sem nada depois de 10 min de SEI.
                      "prazo_ms": max(60, bmod.SEGUNDOS_TETO - 90) * 1000},
        }
        # ALLOWLIST, não denylist. Negar por prefixo deixa passar tudo o que
        # ninguém lembrou de negar — `SEI360_SEGREDO`, `SMTP_PASS`, tokens, e o
        # que quer que o EasyPanel injete no container amanhã. O processo do
        # Chromium não precisa de nada disso, e o que ele não recebe não aparece
        # em dump de processo nem em log de queda. `coleta._ambiente()` já fazia
        # assim, no mesmo repositório.
        env = {k: v for k, v in os.environ.items() if k in _AMBIENTE_DO_FILHO}
        env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   # UM PERFIL POR PESSOA E POR INSTALAÇÃO. Com um perfil só, a
                   # busca de B reaproveitava a sessão do SEI de A: `goto(LOGIN)`
                   # nem caía em login.php, e o SEI gravava as consultas de B com
                   # o nome de A. O cofre registrava "B usou a credencial" e o
                   # log do SEI dizia outra coisa — a atribuição nominal, que é o
                   # custo que o §6.0 assumiu, quebrada por dentro.
                   #
                   # Por instalação também: SESAB e FESF são sessões diferentes,
                   # e misturá-las faria o login de uma cair na sessão da outra.
                   SEI_PERFIL_DIR=str(_perfil_de(r["usuario_id"], r["instancia"])),
                   # A senha chega por stdin a cada execução aqui, então o
                   # coletor pode apagá-la do localStorage depois de logar — o
                   # perfil guarda só o cookie. Na estação a variável não existe
                   # e a credencial fica, porque lá a coleta agendada roda sem
                   # stdin e depende dela.
                   SEI_ESQUECER_APOS_LOGIN="1")
        proc = subprocess.Popen(
            [sys.executable, str(COLETOR), "--buscar", "--credencial-stdin"],
            cwd=str(COLETOR.parent), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env)
        # A SENHA SAI DAQUI POR STDIN E MORRE COM O BUFFER. Nunca em argv (aparece
        # em `ps` para qualquer um no container), nunca em ambiente (vaza em
        # `docker inspect` e no dump de qualquer filho).
        teto = bmod.SEGUNDOS_TETO
        try:
            saida, _ = proc.communicate(json.dumps(pedido, ensure_ascii=False) + "\n",
                                        timeout=teto)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                saida, _ = proc.communicate(timeout=30)
            except Exception:                          # noqa: BLE001
                pass
            envelope["motivo"] = f"o servidor não devolveu resultado em {teto // 60} min"
            # UMA repetição só. O motor JS agora devolve o que leu antes do teto, então
            # estourar o relógio de fora é requisição pendurada — passageira. Mas se
            # já estourou numa tentativa anterior, é o tamanho da pergunta, e repetir
            # seriam mais 10 min de pesquisa pesada no SEI do órgão para o mesmo fim.
            passageira = not (r["tentativas"] if "tentativas" in r.keys() else 0)
            return None
        del pedido, senha
        veio = ilegivel = False
        for linha in (saida or "").splitlines():
            if linha.startswith("BUSCA_OK "):
                try:
                    envelope = json.loads(linha[len("BUSCA_OK "):])
                    veio = True
                except ValueError:
                    ilegivel = True
        if veio and "itens" not in envelope:
            envelope.setdefault("itens", [])
        if not veio and ilegivel:
            # A LINHA CHEGOU CORTADA — escrita grande no pipe não é atômica. É
            # passageira, e o motivo diz isso em vez de "saiu sem resultado" citando
            # a linha de log que conta os itens que se perderam.
            envelope["motivo"], passageira = "o coletor devolveu um envelope ilegível", True
        elif not veio:
            # A CAUSA REAL, e não "o servidor não chegou a executar a busca". Esse
            # texto era o do envelope inicial, que já nascia com a chave 'itens' —
            # então o ramo que usaria o código de saída e o log nunca rodava, e
            # senha recusada, SEI fora do ar e navegador morto por falta de
            # memória saíam todos como uma busca que nem começou.
            envelope["motivo"], passageira = _causa(proc.returncode, saida)
            if proc.returncode == 3:
                # O QUE O SEI DISSE vira o motivo na tela de quem pesquisou, e a
                # recusa CERTA marca a senha: a coleta da madrugada não tenta de
                # novo com ela (cada tentativa conta para o bloqueio da conta).
                import leitura_saida as _ls
                _c = _ls.causa(3, saida)
                envelope["motivo"] = f"{_c['texto']} Confira a senha guardada em Configuração."
                if _c["chave"] in _ls.CAUSAS_DE_LOGIN and _c["certeza"]:
                    try:
                        cofre.marcar_recusa(cx, r["usuario_id"], r["instancia"], _c["texto"])
                        cx.commit()
                    except Exception:                      # noqa: BLE001
                        try:
                            cx.rollback()
                        except Exception:                  # noqa: BLE001
                            pass
            print(f"atendente: busca {bid} sem envelope (código {proc.returncode}): "
                  f"{_sem_hash(_ultima_linha(saida) or '-')}", flush=True)
        elif envelope.get("motivo") and not envelope.get("itens"):
            passageira = (not envelope.get("motivo_permanente")
                          and bool(_PASSAGEIRA.search(envelope["motivo"])))
    except Exception as ex:                                    # noqa: BLE001
        # O TIPO, NÃO A MENSAGEM. Mensagem de exceção carrega caminho, host e —
        # em erro de login — às vezes o valor que falhou. O tipo diz o bastante
        # para investigar no log, sem publicar nada na tela de ninguém.
        envelope["motivo"] = f"falha no servidor ao executar a busca ({type(ex).__name__})"
        # BANCO OCUPADO É PASSAGEIRO; o resto (cofre ilegível, perfil ausente) não.
        passageira = type(ex).__name__ == "OperationalError"
    finally:
        envelope.setdefault("duracao_s", round(time.time() - inicio, 1))
        # A SAÍDA INTEIRA NO VOLUME — sem o envelope (resultado da pessoa) e sem
        # segredo. `guardar_saida` nunca levanta.
        if saida:
            import diario as _diario
            _diario.guardar_saida("busca", bid, saida)
        # A ORIGEM DA MESA, gravada assim que o coletor a anuncia — antes de
        # qualquer veredito, e mesmo quando ele morre depois.
        try:
            for _l in (saida or "").splitlines():
                if _l.startswith("MESA_ORIGEM "):
                    bmod.registrar_origem(cx, bid, _l[len("MESA_ORIGEM "):].strip())
                    break
        except Exception:                                      # noqa: BLE001
            pass
        # NOVA TENTATIVA, antes de gravar o veredito. Só para o que foi reconhecido
        # como passageiro e só enquanto houver execução sobrando; a última falha
        # sai como 'falhou', com o motivo dela e o número de tentativas.
        try:
            if (passageira and not envelope.get("itens")
                    and bmod.pode_repetir(cx, bid)
                    and bmod.reenfileirar(cx, bid, envelope.get("motivo") or "falha passageira")):
                cx.commit()
                return "pedida", envelope.get("motivo")
        except Exception:                                      # noqa: BLE001
            try:
                cx.rollback()
            except Exception:                                  # noqa: BLE001
                pass
        # COMMIT SÓ NO SUCESSO. `finally: cx.commit()` era incondicional: uma
        # exceção no meio de `receber()` gravava o que já tinha sido escrito —
        # meio resultado, com o veredito por cima. Desfazer devolve a busca ao
        # estado 'entregue', e a varredura a marca como falhou pelo prazo de
        # execução, com um motivo verdadeiro. Meio resultado nunca é 'completa'.
        # "DATABASE IS LOCKED" É O CASO ORDINÁRIO, não o exótico: a ingestão da
        # coleta escreve mais de mil linhas num commit, e o `busy_timeout` é de 5 s.
        # Desistir na primeira deixava a busca 'entregue' por 12 min, a conta
        # travada, e o resultado — já lido no SEI — jogado fora.
        for _i in range(3):
            try:
                saida = bmod.receber(cx, bid, envelope)
                cx.commit()
                return saida
            except Exception as _ex:                           # noqa: BLE001
                try:
                    cx.rollback()
                except Exception:                              # noqa: BLE001
                    pass
                if type(_ex).__name__ != "OperationalError" or _i == 2:
                    raise
                time.sleep(2 * (_i + 1))


# O QUE O NAVEGADOR PRECISA, e nada além. Cada nome aqui é uma decisão: PATH e
# os de sistema para o Python e o Chromium acharem o que carregam;
# PLAYWRIGHT_BROWSERS_PATH porque o navegador vive fora do $HOME na imagem;
# SEI_SEM_SANDBOX e SEI_PERFIL_DIR porque são o interruptor e o caminho que o
# coletor lê. `SEI_ESQUECER_APOS_LOGIN` entra por `env.update`, junto do perfil.
_AMBIENTE_DO_FILHO = frozenset((
    "PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "HOME", "LANG", "LC_ALL", "TZ", "PLAYWRIGHT_BROWSERS_PATH",
    "SEI_SEM_SANDBOX", "PYTHONUNBUFFERED", "PYTHONIOENCODING",
))


def _perfil_de(usuario_id, instancia):
    """O diretório de perfil DESTA pessoa nesta instalação do SEI.

    Sob a raiz que o Dockerfile define (`SEI_PERFIL_DIR`), que passa a ser a
    PASTA-MÃE e não o perfil. Nome só com dígitos e letras: o `id` é inteiro e a
    instância vem de `perfil_sei.INSTANCIAS`, mas o caminho é construído por
    concatenação e não é lugar de confiar em quem chamou.
    """
    from pathlib import Path as _P
    raiz = _P(os.environ.get("SEI_PERFIL_DIR") or (COLETOR.parent / "_perfil_sei"))
    limpo = "".join(c for c in str(instancia) if c.isalnum() or c in "-_")
    return raiz / f"u{int(usuario_id)}-{limpo or 'sei'}"


# O QUE CONTA COMO PASSAGEIRO no motivo que o motor JS devolve. Sessão caída entra:
# a próxima execução é um processo novo, que loga de novo. Filtro recusado, mesa que
# a conta não tem e login recusado NÃO entram — repetir só repete a recusa.
import re as _re
_PASSAGEIRA = _re.compile(r"SESSAO caiu|Failed to fetch|NetworkError|net::ERR|"
                          r"o SEI respondeu 5\d\d|Timeout|timed out|ECONN|"
                          r"Target (?:page|closed)|Browser has been closed", _re.I)


def _sem_hash(texto):
    return _re.sub(r"infra_hash=[^&\s'\"]*", "infra_hash=…", str(texto))


def _causa(codigo, saida):
    """(motivo legível, passageira?) para o coletor que saiu SEM envelope.

    Os códigos são os de `coletor_sesab.py`: 3 é login que não concluiu, 4 é falha
    de infraestrutura (navegador, rede, arquivo ausente), 5 é o relógio. Código
    negativo ou 137 é processo morto por sinal — no container, quase sempre o
    kernel matando por falta de memória.
    """
    ultima = _sem_hash(_ultima_linha(saida) or "")
    if codigo == 3:
        return ("o login no SEI não concluiu (senha recusada, segundo fator ou SEI "
                "lento) — confira a senha guardada em Configuração"), False
    if codigo is not None and (codigo < 0 or codigo == 137):
        return ("o navegador foi encerrado pelo sistema no meio da busca "
                "(provável falta de memória no servidor)"), True
    if codigo == 4:
        # NEM TODO 4 É OSCILAÇÃO. O coletor também sai 4 quando falta um arquivo
        # do motor ou o pedido veio malformado — defeito da imagem ou de quem
        # chamou, que se repetiria igual nas três tentativas.
        permanente = _re.search(r"nao achei|exige|stdin|instalacao desconhecida|"
                                r"credencial em stdin", ultima, _re.I)
        return ("falha de infraestrutura no navegador ou na rede"
                + (f": {ultima[:120]}" if ultima else "")), not permanente
    if codigo == 5:
        return "o coletor foi morto pelo relógio", True
    return (f"o coletor saiu com código {codigo} sem resultado"
            + (f": {ultima[:120]}" if ultima else "")), False


def _ultima_linha(saida):
    linhas = [x.strip() for x in (saida or "").splitlines() if x.strip()]
    return linhas[-1][:200] if linhas else None


# ------------------------------------------------------------------- o laço
def rodada(cx=None):
    """Uma passada: pega o que couber nas vagas e executa. Devolve quantas rodou.

    Separada do laço para o teste poder chamá-la sem thread e sem relógio.
    """
    proprio = cx is None
    cx = cx or banco.conectar()
    feitas = 0
    try:
        # NO MÁXIMO `LIMITE` POR PASSADA. `while _vagas.acquire()` é um laço
        # sem fundo: a vaga que uma thread devolve é re-adquirida na mesma
        # volta, e com uma execução que falha rápido — credencial recusada,
        # coletor ausente, banco fora do ar — isto vira criação de thread em
        # laço quente. Medido: o processo abriu centenas de threads `busca-1` em
        # segundos e travou no `invoke_excepthook`.
        #
        # Uma passada oferece as vagas que existem, e nada além disso. O laço de
        # 3 s volta logo; não há pressa que justifique um laço sem teto.
        for _ in range(LIMITE):
            if not _vagas.acquire(blocking=False):
                break
            # UM ÚNICO LUGAR DEVOLVE A VAGA. A versão anterior a devolvia no
            # `if not r` e no finally da thread, e deixava DUAS janelas abertas:
            # `pegar()` levantando (o UPDATE dele disputa o lock de escrita com a
            # ingestão, que segura por mais que o busy_timeout de 5 s) e
            # `Thread.start()` levantando. Em qualquer das duas, a vaga sumia.
            # Duas ocorrências e `_vagas` chega a zero PARA SEMPRE: o laço segue
            # vivo, `capacidade()` segue True, a tela segue oferecendo o botão, e
            # toda busca morre em 90 s acusando um agente que não existe.
            nossa = True
            try:
                r = pegar(cx)
                if not r:
                    break                       # o finally devolve a vaga
                threading.Thread(target=_executar_e_liberar, args=(r,),
                                 name=f"busca-{r['id']}", daemon=True).start()
                nossa = False                   # daqui em diante é da thread
                feitas += 1
            finally:
                if nossa:
                    _vagas.release()
    finally:
        if proprio:
            cx.close()
    return feitas


def _executar_e_liberar(r):
    # A VAGA É O ÚLTIMO A SAIR, e não depende de nada dar certo. Antes, o
    # `banco.conectar()` ficava FORA do try: se ele levantasse — volume cheio,
    # disco em leitura, o PRAGMA do WAL batendo no lock — o finally nunca era
    # entrado e a vaga sumia. E `cx.close()` vinha ANTES do release, no mesmo
    # finally: bastava o close levantar para a vaga sumir também.
    try:
        cx = None
        try:
            cx = banco.conectar()
            executar(cx, r)
        finally:
            if cx is not None:
                try:
                    cx.close()
                except Exception:               # noqa: BLE001
                    pass
    finally:
        _vagas.release()


def laco():
    _laco_vivo.set()
    try:
        pode, motivo = capacidade()
    except Exception as ex:                                    # noqa: BLE001
        # A PRIMEIRA CHAMADA TAMBÉM PODE LEVANTAR. Ela ficava fora de qualquer
        # try: leitura do .js falhando ou import do playwright estourando matava
        # a thread ANTES do laço começar. `iniciar()` já tinha devolvido True, a
        # tela continuava com o botão ligado (ela recalcula a capacidade a cada
        # requisição), e toda busca morria aos 90 s acusando um agente.
        pode, motivo = False, f"a capacidade não pôde ser medida ({type(ex).__name__})"
    print(f"atendente de busca: {'ligado' if pode else 'PARADO'} — "
          f"{motivo or f'até {LIMITE} busca(s) simultânea(s)'}", flush=True)
    if not pode:
        # Não morre: a capacidade pode aparecer num redeploy, e um laço morto
        # silenciosamente é a mesma armadilha do agente que nunca foi pareado.
        pass
    voltas = 0
    while _laco_vivo.is_set():
        voltas += 1
        if voltas % VARRER_A_CADA == 0:
            # A VARREDURA NÃO DEPENDE DE ALGUÉM OLHAR. Ver `VARRER_A_CADA`.
            try:
                _cxv = banco.conectar()
                try:
                    bmod.varrer(_cxv)
                    bmod.limpar_travas_de_motor(_cxv, TOKEN)
                    _cxv.commit()
                finally:
                    _cxv.close()
            except Exception as ex:                            # noqa: BLE001
                print(f"atendente: varredura falhou ({type(ex).__name__})", flush=True)
        try:
            if capacidade()[0]:
                rodada()
        except Exception as ex:                                # noqa: BLE001
            # O TIPO E AS VAGAS. Só o tipo produzia uma linha por 3 s sem nada
            # que apontasse para o semáforo — que é onde o dano fica.
            print(f"atendente: {type(ex).__name__} · {vagas_livres()}/{LIMITE} vaga(s)",
                  flush=True)
        time.sleep(INTERVALO_S)


# O DESCRITOR FICA ABERTO ENQUANTO ESTE PROCESSO FOR O EXECUTOR. É ele que
# segura o lock — fechá-lo, ou morrer, devolve a vez. Guardado em módulo para o
# coletor de lixo não o fechar por engano.
_fd_vez = None


def _tomar_a_vez():
    """Este processo é o executor de busca deste container?

    UM LOCK DO SISTEMA OPERACIONAL, e não um arquivo com o PID dentro. A versão
    anterior escrevia quem era, lia quem estava e decidia se aquele havia
    morrido — e entre ler e decidir há sempre um intervalo em que dois processos
    julgam o mesmo estado. Remendei três vezes (esperar o vazio, exigir o
    terminador, contar tentativas) e a cada remendo fechava uma janela e abria
    outra: medido, 4 falhas em 8 execuções com cinco processos, sempre com dois
    ou três vencedores.

    Dois executores fazem `SEI360_BUSCAS_SIMULTANEAS` — o teto de memória, única
    defesa contra o OOM killer em 2 GB — deixar de valer para o container.

    O lock exclusivo sobre um arquivo aberto é atômico, não interpreta conteúdo
    e **morre com o processo**, inclusive num `kill -9`. Não há PID para ler, nem
    dono morto para detectar, nem trava velha para vencer por tempo.
    """
    global _fd_vez
    if _fd_vez is not None:
        return True                              # já é nosso
    trava = banco.DADOS_DIR / ".atendente.lock"
    try:
        fd = os.open(str(trava), os.O_CREAT | os.O_RDWR)
    except OSError as ex:
        # Volume somente leitura ou sem espaço: sem lock não há como garantir
        # unicidade, e é melhor ficar sem executor do que ter vários. DITO no log:
        # antes este caso imprimia "outro processo já é o executor" — falso, e
        # mandava procurar um executor que não existia.
        print(f"atendente de busca: não consegui abrir {trava} ({type(ex).__name__}) "
              "— sem executor neste container até o volume aceitar escrita", flush=True)
        return False
    if not _travar_fd(fd):
        os.close(fd)
        return False
    try:
        os.write(fd, f"{os.getpid()}\n".encode())   # só para quem for ler o log
    except OSError:
        pass
    _fd_vez = fd
    return True


def _travar_fd(fd):
    """Lock exclusivo NÃO BLOQUEANTE sobre o descritor. True se pegou."""
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _soltar_a_vez():
    """Devolve a vez. Só para teste e para desligamento explícito — o caminho
    normal é o processo morrer, e o sistema operacional soltar sozinho."""
    global _fd_vez
    if _fd_vez is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            os.lseek(_fd_vez, 0, os.SEEK_SET)
            msvcrt.locking(_fd_vez, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(_fd_vez, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(_fd_vez)
    except OSError:
        pass
    _fd_vez = None


# QUEM PERDE A VEZ CONTINUA CANDIDATO. De quanto em quanto tempo ele pergunta.
#
# O DEFEITO, medido em produção em 15/09/2026: 15 de 15 consultas a /saude
# responderam `laco_vivo: false` — com 3 workers, a chance de isso ser azar de
# amostragem é 0,2%. Não havia executor de busca no container. A eleição acontecia
# UMA vez, no import de cada worker: se naquele instante a trava estava com outro
# processo — o container ANTIGO ainda de pé durante um redeploy sem parada, que
# divide o mesmo volume, ou um worker que o gunicorn estava reciclando —, os três
# workers novos desistiam, e ninguém tentava de novo quando a trava se soltava
# segundos depois. Toda busca aceita morria em 90 s com "o executor de busca deste
# servidor não pegou o pedido", e a coleta e o acompanhamento do servidor, que
# pegam carona no executor, também nunca subiam.
CANDIDATO_S = 30
_candidato = None
_ao_assumir = []


def ao_assumir(fn):
    """Registra quem sobe junto quando este processo vira o executor.

    `coleta_servidor.iniciar` e `acompanhamento_servidor.iniciar` exigem
    `atendente.vivo()`; chamados no import de um worker que ainda não é o
    executor, eles desistiam para sempre. Registrados aqui, sobem no instante
    em que a vez é tomada — na subida ou na reeleição.
    """
    if fn not in _ao_assumir:
        _ao_assumir.append(fn)
    if vivo():
        try:
            fn()
        except Exception as ex:                                # noqa: BLE001
            print(f"atendente: {getattr(fn, '__module__', fn)} não subiu "
                  f"({type(ex).__name__})", flush=True)


def _assumir():
    global _thread
    _thread = threading.Thread(target=laco, name="atendente", daemon=True)
    _thread.start()
    for fn in list(_ao_assumir):
        try:
            fn()
        except Exception as ex:                                # noqa: BLE001
            print(f"atendente: {getattr(fn, '__module__', fn)} não subiu "
                  f"({type(ex).__name__})", flush=True)


def _candidatar():
    """Laço do worker que não é o executor: tenta a vez de tempos em tempos."""
    while ligado() and not vivo():
        time.sleep(CANDIDATO_S)
        try:
            if _tomar_a_vez():
                print(f"atendente de busca: este processo ({os.getpid()}) assumiu a "
                      "vez — o executor anterior saiu", flush=True)
                _assumir()
                return
        except Exception as ex:                                # noqa: BLE001
            print(f"atendente: candidatura falhou ({type(ex).__name__})", flush=True)


def iniciar():
    """Sobe o laço numa thread deste processo, se este for o processo da vez.

    Idempotente, e seguro com vários workers: só um pega a vez. Quem não pega fica
    CANDIDATO — ver `CANDIDATO_S`.
    """
    global _candidato
    if not ligado() or (_thread and _thread.is_alive()):
        return False
    if not _tomar_a_vez():
        # Não é erro: é um worker de painel — por enquanto. Dizer, para o log não
        # sugerir que o executor não subiu em lugar nenhum; e ficar candidato.
        print("atendente de busca: outro processo deste container já é o executor "
              f"— este fica candidato a cada {CANDIDATO_S} s", flush=True)
        if not (_candidato and _candidato.is_alive()):
            _candidato = threading.Thread(target=_candidatar, name="atendente-candidato",
                                          daemon=True)
            _candidato.start()
        return False
    _assumir()
    return True


if __name__ == "__main__":
    # Como PROCESSO próprio: serve para um segundo serviço do EasyPanel, com a
    # mesma imagem e o mesmo volume, quando o painel não deve dividir memória com
    # o Chromium. A reivindicação atômica em `pegar()` é o que torna isso seguro.
    laco()
