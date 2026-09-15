# -*- coding: utf-8 -*-
"""
O executor do ACOMPANHAMENTO dentro do servidor — o motor que faltava.

POR QUE ESTE ARQUIVO EXISTE
----------------------------
O módulo de Acompanhamento (`acompanhamento.py`) nasceu em 11/09/2026 com UM
caminho para a metade caro — a leitura no SEI de processo que não está em mesa
nenhuma da pessoa: as duas rotas `/api/agente/acompanhamento`, que existem
para uma ESTAÇÃO buscar trabalho por HTTP.

E o sistema não roda em estação nenhuma. Roda no VPS: `atendente.py` executa a
busca avançada aqui desde 21/08/2026, e `coleta_servidor.py` executa a coleta
diária aqui desde 08/09/2026 — ambos com Chromium na própria imagem e a senha
saindo do cofre. Medido pela leitura do código em 12/09/2026:
`acompanhamento.pendentes` e `acompanhamento.receber` tinham UM chamador cada,
as duas rotas do agente, e `coleta_servidor.py` não conhecia o módulo.

A consequência não era um defeito de borda: **no VPS, um processo acompanhado
fora da mesa entrava na lista e nunca era lido.** Ficava `estado='novo'`, e a
tela dizia "aguardando primeira leitura" para sempre — a frase é verdadeira, e
é por isso que o silêncio ia durar. O módulo inteiro estava morto na
arquitetura real, sem uma linha vermelha em nenhum lugar.

O QUE ELE FAZ
-------------
O mesmo trabalho da estação, sem a estação e sem HTTP: para cada par
(pessoa, instalação) com item na lista, chama `acompanhamento.pendentes` (que
antes de tudo REAPROVEITA a carteira, de graça), e o que sobrar vai ao
`coletor_sesab.py --acompanhar --credencial-stdin`, com a senha vinda do cofre
por stdin. Cada pedaço do envelope é publicado por `acompanhamento.receber`,
em processo.

TRÊS COISAS QUE ELE FAZ MELHOR QUE A ESTAÇÃO, e não por elegância
-------------------------------------------------------------------
1. **AS DUAS INSTALAÇÕES, no mesmo ciclo.** A rota do agente entrega UMA
   instalação por vez, e está certa: a estação faz login numa por ciclo, e
   pedir outra é pedir credencial que ela não tem. O preço foi medido em
   11/09/2026 — três ciclos e o item da outra instalação nunca é oferecido. No
   container a limitação não existe: o cofre guarda credencial POR instalação
   (`credencial(usuario_id, sistema)`), `config_usuario` é por
   `(usuario_id, sistema)` com `modo_coleta` próprio, e o atendente já mantém
   um perfil de navegador por pessoa E por instalação. Herdar aqui a restrição
   da estação deixaria o item da FESF dizendo "aguardando primeira leitura"
   com a resposta pronta do outro lado.

2. **NA ORDEM QUE CUSTA MENOS.** `pendentes` chama `reaproveitar` primeiro:
   processo que a coleta do dia trouxe é respondido sem UMA requisição ao SEI.
   Logo, rodar o acompanhamento ANTES da coleta do dia é pagar seis
   requisições por processo para ler o que ia chegar de graça minutos depois.
   Este laço espera a coleta do dia concluir — ver `_devido`, e o corte ao
   meio-dia para o dia não se perder quando a coleta falha.

3. **SEM CHROMIUM PARA NADA.** A pergunta "há trabalho?" é um `COUNT(*)`
   (`acompanhamento.quantos_pendentes`), e só depois dela se gasta uma vaga de
   memória. A estação subia o navegador a cada 30 min por conta própria.

MEMÓRIA — A MESMA DISCIPLINA DE `coleta_servidor.py`, LIDA ANTES DE MEXER AQUI
--------------------------------------------------------------------------------
Uma leitura de acompanhamento é o MESMO Chromium de uma busca (~450 MB de um
VPS de 2 GB), por minutos em vez de segundos. As defesas são as de lá, não
inventadas de novo:

  1. Um só interruptor, e é o da coleta (`SEI360_COLETA_SERVIDOR`). A decisão
     é a mesma — "este container lê o SEI sozinho, com senha guardada" — e um
     segundo interruptor seria uma segunda coisa para esquecer, com falha
     silenciosa: item parado para sempre, sem linha vermelha. Quem precisar
     desligar SÓ isto tem `SEI360_ACOMPANHAMENTO_SERVIDOR=0`.
  2. SÓ COMEÇA COM TUDO OCIOSO (nenhuma busca e nenhuma coleta em curso) e,
     enquanto roda, SEGURA UMA VAGA do MESMO semáforo `atendente._vagas`.
  3. NO MÁXIMO UMA leitura por vez neste container, e UM par por passada.
  4. MESMO PROCESSO QUE O ATENDENTE, pelo motivo que `coleta_servidor.py`
     documenta: `threading.Semaphore` não atravessa processo do gunicorn, e com
     `--workers 3` uma eleição própria poderia cair num worker onde os dois
     tetos de memória não se enxergam. Este laço não disputa a própria vez —
     pega carona em quem venceu a eleição do atendente.

O QUE ELE NÃO FAZ (dívida escrita, para não virar surpresa)
--------------------------------------------------------------
Não roda dentro do POST de "adicionar": o clique da pessoa não pode esperar
minutos de Chromium, e uma falha de leitura não pode derrubar a inserção. O
gatilho "ao adicionar" é atendido pelo intervalo do laço (ver `INTERVALO_S`),
não por sincronia. Não substitui o modo estação: quem prefere que a senha
nunca toque o servidor continua tendo `modo_coleta='estacao'`, e este laço
ignora essas contas de propósito — a senha delas não está aqui.
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

import acompanhamento as acmod
import atendente
import banco
from banco import agora
import cofre
import janelas
import perfil_sei
from coleta import COLETOR

# Uma leitura por vez neste container, e um par (pessoa, instalação) por
# passada. Não é `SEI360_BUSCAS_SIMULTANEAS`: aquele é sobre pessoas diferentes
# pedindo busca ao mesmo tempo, e aqui o motivo de não paralelizar é não ter
# medido duas leituras concorrentes num VPS de 2 GB.
LIMITE = 1

# De quanto em quanto tempo o laço olha se há o que ler.
#
# ESTE NÚMERO É A LATÊNCIA DO "AO ADICIONAR". A cadência decidida pelo usuário
# em 11/09/2026 foi "ao adicionar + na coleta diária"; o segundo gatilho é
# `_devido`, e o primeiro é este intervalo. Dois minutos porque a pergunta
# custa um `COUNT(*)` sobre uma tabela de no máximo 100 linhas por pessoa —
# ninguém está na tela esperando (ao contrário dos 3 s da busca), e quem acabou
# de colar um número aceita dois minutos muito melhor que um clique que
# bloqueia por nove.
INTERVALO_S = 120

# Teto de parede da execução, o de FORA. O `.js` tem teto próprio de 9 min
# (`acompanharLista`) justamente para responder antes deste; se este disparar,
# o processo morre e o que já chegou é publicado do mesmo jeito — ver
# `_ler_envelopes`.
SEGUNDOS_TETO = 10 * 60

# Depois desta hora local, o acompanhamento deixa de esperar a coleta do dia.
#
# A espera existe para economizar requisição (ver o item 2 do cabeçalho), não
# para ser regra moral: a janela padrão é 07:30, e se ao meio-dia a coleta não
# concluiu, ou ela falhou ou está desarmada. Continuar esperando trocaria "seis
# requisições por processo evitadas" por "um dia inteiro sem ler", que é um
# câmbio ruim — e silencioso, porque a tela diria a verdade ("aguardando
# primeira leitura") enquanto o motivo real era outro.
HORA_SEM_ESPERAR = 12

# Depois de uma volta em que NADA foi lido, o par espera antes da próxima: 15 min,
# dobrando a cada falha seguida, até 2 h. Sem isto, a falha sistemática (senha
# errada, SEI fora do ar) era repetida a cada 2 min.
ESPERA_APOS_FALHA_S = 15 * 60
ESPERA_MAXIMA_S = 2 * 60 * 60
_falhas_seguidas = {}          # (usuario_id, instancia) -> (quantas, até quando, dia, desde)

_laco_vivo = threading.Event()
_thread = None


def ligado():
    """O interruptor é o da coleta — ver o item 1 de MEMÓRIA, no cabeçalho."""
    if os.environ.get("SEI360_ACOMPANHAMENTO_SERVIDOR", "1") in ("0", "false", "nao"):
        return False
    return os.environ.get("SEI360_COLETA_SERVIDOR", "0") in ("1", "true", "sim")


def capacidade():
    """(pode, motivo). O MESMO requisito do atendente: mesmo coletor, mesmo
    Playwright, mesmo cofre — só muda quem pede a execução. Reaproveitar em vez
    de duplicar evita as duas respostas divergirem um dia."""
    return atendente.capacidade()


def vivo():
    """A thread deste laço está viva NESTE processo?"""
    return bool(_thread and _thread.is_alive())


# ------------------------------------------------------------------ a fila
def _candidatos(cx):
    """Pares (usuario_id, instancia) que este container pode ler. Ordenados.

    O CRUZAMENTO É O PONTO. Item na lista (`acompanhado`) diz o que a pessoa
    quer seguir; `config_usuario.modo_coleta='servidor'` diz que a senha
    daquela instalação está AQUI, no cofre. Sem a segunda metade, este laço
    tentaria abrir o cofre de quem escolheu modo estação — e a decisão de
    custódia de senha (§6.0/§6.3 do ARQUITETURA_ACESSO.md) é de quem a tomou,
    não deste módulo. A conta em modo estação continua sendo atendida pela
    rota HTTP, com o agente dela.

    POR PAR, não por pessoa: alguém pode estar em modo servidor na SESAB e em
    modo estação na FESF. O recorte de `acompanhamento` é sempre
    (usuario_id, instancia), e é ele que manda aqui.
    """
    return [(r["usuario_id"], r["instancia"]) for r in cx.execute(
        """SELECT DISTINCT a.usuario_id, a.instancia
           FROM acompanhado a
           JOIN config_usuario c
             ON c.usuario_id = a.usuario_id AND c.sistema = a.instancia
           WHERE c.modo_coleta = 'servidor'
           ORDER BY a.usuario_id, a.instancia""")]


def _devido(cx, usuario_id, instancia, agora_dt=None):
    """(pode, motivo) — a CADÊNCIA, e ela é sobre custo, não sobre relógio.

    Decidida pelo usuário em 11/09/2026: "ao adicionar + na coleta diária".

      * item `novo` — acabou de ser colado, e é o gatilho "ao adicionar". Não
        espera a coleta de amanhã: quem colou um número está esperando por ele.
      * o resto — releitura. Espera a coleta do dia CONCLUIR, porque é ela que
        responde de graça o que está na carteira (`reaproveitar`, chamado por
        `pendentes`). Rodar antes é pagar seis requisições ao SEI por processo
        para ler o que ia chegar sozinho minutos depois.

    Quem não tem agendamento ativo não espera nada — não há coleta para
    esperar, e esperar por ela seria esperar para sempre. E depois de
    `HORA_SEM_ESPERAR` ninguém espera mais.
    """
    agora_dt = agora_dt or datetime.now(janelas.TZ)
    if acmod.quantos_pendentes(cx, usuario_id, instancia, so_novos=True):
        return True, "item novo na lista"
    if agora_dt.hour >= HORA_SEM_ESPERAR:
        return True, f"depois das {HORA_SEM_ESPERAR}h não se espera mais a coleta"
    # O AGENTE DESTA PESSOA EM MODO SERVIDOR. `coleta_servidor` cria um por
    # pessoa, com o nome 'SERVIDOR/<login>'; é nele que a `execucao` do dia é
    # gravada. Sem agente armado não há coleta do dia para esperar.
    ag = cx.execute(
        """SELECT a.id FROM agentes a
           JOIN agendamento g ON g.agente_id = a.id AND g.ativo = 1
           WHERE a.nome_estacao LIKE 'SERVIDOR/%' AND a.dono_usuario_id = ?
             AND a.pausado_motivo IS NULL LIMIT 1""",
        (usuario_id,)).fetchone()
    if not ag:
        return True, "sem coleta agendada para esperar"
    hoje = agora_dt.date().isoformat()
    feita = cx.execute(
        """SELECT id FROM execucao WHERE agente_id=? AND estado='concluida'
           AND janela LIKE ? LIMIT 1""", (ag["id"], hoje + "%")).fetchone()
    if feita:
        return True, "a coleta do dia já concluiu"
    return False, "esperando a coleta do dia, que responde de graça o que está na mesa"


def cobertura(cx, usuario_id):
    """(le, parado) — o que ESTE container responde por esta conta, e o que não.

    `le` é a lista de instalações que ele lê hoje; `parado` um mapa
    {instalação: motivo} das que ele deveria ler e não lê, com o motivo em
    rótulo (`acompanhamento.MOTOR_DESLIGADO`, `.SEM_BUSCA`) — a frase é do
    módulo de regra, não daqui.

    A TELA DEPENDE DISTO PARA NÃO MENTIR. Até 12/09/2026 o cartão dizia "hoje,
    só a sua própria coleta pode respondê-lo" sobre todo item de instalação que
    não fosse a configuração ATIVA da pessoa — verdade enquanto quem lia era uma
    estação, falso no minuto em que este motor existiu. E o contrário também
    precisa ser dito: senha no servidor com o motor desligado é a falha de
    implantação mais silenciosa deste módulo.

    Só instalação em `modo_coleta='servidor'` entra em qualquer das duas listas:
    em modo estação a senha não está aqui, e quem responde é o agente da pessoa.
    """
    import acompanhamento as _ac
    le, parado = [], {}
    de_pe = ligado()
    for r in cx.execute("""SELECT sistema FROM config_usuario
                           WHERE usuario_id=? AND modo_coleta='servidor'
                           ORDER BY sistema""", (usuario_id,)):
        inst = r["sistema"]
        if not perfil_sei.existe(inst):
            continue
        if not de_pe:
            parado[inst] = _ac.MOTOR_DESLIGADO
        elif not perfil_sei.perfil(inst)["disponivel_busca"]:
            parado[inst] = _ac.SEM_BUSCA
        else:
            le.append(inst)
    return le, parado


def _conta(cx, usuario_id, instancia):
    """O login do SEI desta pessoa nesta instalação — a chave da trava de conta."""
    r = cx.execute("SELECT sei_login FROM config_usuario WHERE usuario_id=? AND sistema=?",
                   (usuario_id, instancia)).fetchone()
    return ((r["sei_login"] if r else "") or "").strip() or None


# --------------------------------------------------------------- a execução
def _ler_envelopes(saida):
    """Os pedaços legíveis de `ACOMP_OK `, na ordem em que saíram.

    O QUE JÁ CHEGOU FICA, e o corrompido não — a mesma doutrina que o agente
    da estação aprendeu por medição em 11/09/2026: cada pedaço é um envelope
    completo e independente, que já passou por `json.loads` inteiro; o corte
    que derruba uma escrita não atômica cai numa linha SÓ, e é essa linha que
    se descarta. Descartar o resto custaria 60 leituras por causa da 61ª, a
    seis requisições ao SEI cada uma.
    """
    envelopes, ruins = [], 0
    for linha in (saida or "").splitlines():
        if not linha.startswith("ACOMP_OK "):
            continue
        try:
            envelopes.append(json.loads(linha[len("ACOMP_OK "):]))
        except ValueError:
            ruins += 1
    return envelopes, ruins


def _executar(usuario_id, instancia, protocolos):
    """Lê os `protocolos` no SEI e publica. Devolve (gravadas, ignoradas, motivo).

    `motivo` é None quando houve leitura publicada; texto curto quando não —
    e ele NÃO vai para tela nenhuma: a tela deste módulo fala por cartão, a
    partir do que está gravado. Este texto é para o log do container.
    """
    cx = banco.conectar()
    inicio = time.time()
    gravadas = ignoradas = 0
    motivo = None
    try:
        login, senha = cofre.abrir(cx, usuario_id,
                                   motivo=f"acompanhamento {instancia}",
                                   sistema=instancia)
        # FECHA A TRANSAÇÃO ANTES DE ABRIR O NAVEGADOR — a mesma medição de
        # `atendente.executar`: `cofre.abrir` ESCREVE (o `UPDATE credencial` e
        # o `registrar()` do uso), e no WAL escritor não bloqueia leitor mas
        # bloqueia OUTRO ESCRITOR. Toda requisição autenticada deste sistema
        # escreve (`usuario_atual` faz `UPDATE sessoes`), e o `busy_timeout` é
        # de 5 s contra uma janela de até 600. Sem este commit, ninguém
        # conseguiria clicar no painel enquanto isto roda.
        #
        # E o registro do USO tem de ficar gravado de qualquer jeito: ele é a
        # procedência de "esta senha foi aberta, nesta hora, para isto" —
        # inclusive quando a leitura falha depois.
        cx.commit()
        if not senha:
            return 0, 0, f"não há credencial guardada para {instancia}", False
        pedido = {
            "usuario": login, "senha": senha,
            "perfil": perfil_sei.envelope_do_coletor(instancia),
            "acompanhamento": {"instancia": instancia, "protocolos": protocolos},
        }
        # ALLOWLIST DE AMBIENTE, perfil por pessoa+instalação e a senha por
        # stdin: as três decisões são do atendente, e são reaproveitadas em vez
        # de reescritas — cada uma delas foi um defeito medido lá.
        env = {k: v for k, v in os.environ.items()
               if k in atendente._AMBIENTE_DO_FILHO}
        env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   SEI_PERFIL_DIR=str(atendente._perfil_de(usuario_id, instancia)),
                   SEI_ESQUECER_APOS_LOGIN="1")
        proc = subprocess.Popen(
            [sys.executable, str(COLETOR), "--acompanhar", "--credencial-stdin"],
            cwd=str(COLETOR.parent), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env)
        # A SENHA SAI POR STDIN E MORRE COM O BUFFER. Nunca em argv (aparece em
        # `ps` para qualquer um no container), nunca em ambiente (vaza em
        # `docker inspect` e no dump de qualquer filho).
        try:
            saida, _ = proc.communicate(
                json.dumps(pedido, ensure_ascii=False) + "\n", timeout=SEGUNDOS_TETO)
        except subprocess.TimeoutExpired:
            proc.kill()
            saida, _ = proc.communicate()
            # NÃO devolve daqui: o que já chegou vale, e só o que ainda ia vir
            # se perdeu. Ver `_ler_envelopes`.
            motivo = f"morto pelo relógio em {SEGUNDOS_TETO // 60} min"
        del pedido, senha
        envelopes, ruins = _ler_envelopes(saida)
        if ruins:
            print(f"acompanhamento(servidor): {ruins} pedaço(s) ilegível(is) "
                  "descartado(s)", flush=True)
        if not envelopes:
            # ENVELOPE VAZIO NÃO É PUBLICADO, pelo motivo que o agente da
            # estação documenta: não há nesta gravação onde carimbar "tentou e
            # falhou", então publicar o nada gravaria zero e nada mais. Os
            # itens continuam pendentes e a próxima volta tenta de novo — o
            # recuo por `tentativas` é o que impede isso de virar martelada.
            return 0, 0, motivo or "o coletor não devolveu leitura nenhuma", False
        # PEDAÇO POR PEDAÇO, e cada um comitado por si. Publicar só o último
        # gravaria 20 de 100 sem erro nenhum; comitar só no fim perderia tudo
        # se o terceiro pedaço fosse recusado.
        for i, envelope in enumerate(envelopes, 1):
            try:
                g, ig = acmod.receber(cx, usuario_id, instancia, envelope)
                cx.commit()
                gravadas += g
                ignoradas += ig
            except ValueError as ex:
                # A instalação do dono mudou entre o pedido e a resposta. Vale
                # para TODOS os pedaços (a instalação declarada é a mesma nos
                # cinco): insistir seriam recusas idênticas no log.
                cx.rollback()
                motivo = f"pedaço {i}/{len(envelopes)} fora do escopo: {ex}"
                break
            except Exception as ex:                            # noqa: BLE001
                # O TIPO, NÃO A MENSAGEM — mesma regra do atendente: mensagem
                # de exceção carrega caminho e, às vezes, o valor que falhou.
                # Passageira ATÉ PROVA EM CONTRÁRIO: o pedaço seguinte pode
                # gravar, e descartá-lo custaria leituras que já custaram seis
                # requisições ao SEI cada uma.
                cx.rollback()
                motivo = f"pedaço {i}/{len(envelopes)} recusado ({type(ex).__name__})"
        return gravadas, ignoradas, (None if gravadas else motivo), True
    except Exception as ex:                                    # noqa: BLE001
        return gravadas, ignoradas, f"falha no executor ({type(ex).__name__})", False
    finally:
        try:
            banco.registrar(cx, usuario_id, "acompanhamento_servidor",
                            alvo=f"{instancia} · {len(protocolos)} pedido(s) · "
                                 f"{gravadas} gravada(s) · {round(time.time() - inicio)}s"
                                 + (f" · {motivo}" if motivo else ""))
            cx.commit()
        except Exception:                                      # noqa: BLE001
            try:
                cx.rollback()
            except Exception:                                  # noqa: BLE001
                pass
        finally:
            cx.close()


# ------------------------------------------------------------------- o laço
def rodada(cx=None):
    """Uma passada: no máximo `LIMITE` leitura(s). Devolve quantas rodou.

    Separada do laço para o teste chamar sem thread e sem relógio — mesmo
    desenho de `atendente.rodada` e `coleta_servidor.rodada`.
    """
    proprio = cx is None
    cx = cx or banco.conectar()
    feitas = 0
    try:
        agora_dt = datetime.now(janelas.TZ)
        for usuario_id, instancia in _candidatos(cx):
            if feitas >= LIMITE:
                break
            # A PERGUNTA BARATA PRIMEIRO, e nesta ordem de propósito: nenhuma
            # das três condições abaixo custa Chromium, e a última delas
            # (`pendentes`) ESCREVE.
            if not perfil_sei.perfil(instancia)["disponivel_busca"]:
                # A leitura começa por uma pesquisa por número; numa instalação
                # sem busca ela devolveria "não encontrado" para TODO processo,
                # e a tela afirmaria sobre os processos o que é verdade sobre a
                # instalação. É a mesma trava da rota do agente.
                continue
            if not acmod.quantos_pendentes(cx, usuario_id, instancia):
                continue
            pode, _motivo = _devido(cx, usuario_id, instancia, agora_dt)
            if not pode:
                continue
            _fs = _falhas_seguidas.get((usuario_id, instancia))
            if _fs and _fs[2] != agora_dt.date():
                # O CONTADOR É DO DIA: a falha de ontem não faz a primeira volta de
                # hoje esperar duas horas.
                _falhas_seguidas.pop((usuario_id, instancia), None)
                _fs = None
            # SÓ O ITEM COLADO DEPOIS DA FALHA fura a espera. Um 'novo' que estava na
            # volta que falhou é justamente o que falha — deixá-lo furar fazia a
            # espera nunca valer para ele, e o Chromium subia a cada 2 min.
            if (_fs and time.time() < _fs[1]
                    and not cx.execute("""SELECT 1 FROM acompanhado WHERE usuario_id=?
                                          AND instancia=? AND estado='novo'
                                          AND adicionado_em > ? LIMIT 1""",
                                       (usuario_id, instancia, _fs[3])).fetchone()):
                # esperando depois de uma volta vazia — mas item recém colado não
                # espera: o gatilho "ao adicionar" não pode ficar refém de uma falha
                # de outro item do mesmo par.
                continue
            # A CONTA DO SEI É UMA SÓ para busca, coleta e acompanhamento, e a
            # unidade ativa lá é estado por usuário. Com a conta ocupada, este
            # par espera — e sem ter cobrado tentativa de ninguém.
            conta = _conta(cx, usuario_id, instancia)
            dono = f"motor:{atendente.TOKEN}:acompanhamento"
            import busca as _bmod
            if conta:
                _bmod.limpar_travas_de_motor(cx, atendente.TOKEN)
                if _bmod.trava_de_outro(cx, instancia, conta, None, dono):
                    cx.commit()
                    continue
            # SÓ COMEÇA COM TUDO OCIOSO — nem busca nem coleta em curso. É o
            # mesmo teste de `coleta_servidor.rodada`: `vagas_livres()` igual
            # ao `LIMITE` do atendente é "ninguém usando nenhuma vaga agora".
            if atendente.vagas_livres() != atendente.LIMITE:
                break
            # TRABALHO PESADO UM POR VEZ: sem este lock, coleta e acompanhamento
            # passavam juntos pelo teste de cima e tomavam as duas vagas.
            if not atendente._pesado.acquire(blocking=False):
                break
            if not atendente._vagas.acquire(blocking=False):
                atendente._pesado.release()
                break                            # perdeu a corrida por uma vaga
            lista = []
            try:
                if conta:
                    if not _bmod._travar(cx, instancia, conta, None,
                                         minutos=SEGUNDOS_TETO // 60 + 2, dono=dono):
                        cx.commit()
                        continue
                    cx.commit()
                # `pendentes` ESCREVE (incrementa `tentativas`) e chama
                # `reaproveitar` — então só é chamada aqui, com a vaga na mão,
                # e o commit vem ANTES de decidir: o que a carteira respondeu
                # de graça fica gravado mesmo quando sobra zero para o SEI. É
                # justamente o caso bom.
                lista = acmod.pendentes(cx, usuario_id, instancia)
                parados = acmod.descansando(cx, usuario_id, instancia, na_fila=lista)
                cx.commit()
                if parados:
                    print("acompanhamento(servidor): "
                          + ", ".join(f"{p['protocolo']} ({p['tentativas']}x)"
                                      for p in parados[:5])
                          + f" — descansam até amanhã (conta {usuario_id})",
                          flush=True)
                if not lista:
                    # A carteira respondeu tudo. Nenhum Chromium subiu, e este
                    # é o caminho que se quer comum.
                    continue
                print(f"acompanhamento(servidor): conta {usuario_id} · {instancia} · "
                      f"{len(lista)} processo(s) no SEI", flush=True)
                _res = _executar(usuario_id, instancia, lista)
                g, ig, motivo = _res[0], _res[1], _res[2]
                # CHEGOU AO SEI? Envelope que voltou — mesmo só com falhas por
                # processo — é o SEI respondendo sobre aqueles processos, e aí a
                # tentativa cobrada vale: o item que falha sempre descansa depois de
                # três. Só a volta que NÃO trouxe envelope nenhum é falha da volta.
                chegou = bool(_res[3]) if len(_res) > 3 else bool(g or ig)
                feitas += 1
                print(f"acompanhamento(servidor): {g} gravada(s), {ig} ignorada(s)"
                      + (f" — {motivo}" if motivo else ""), flush=True)
                if chegou:
                    _falhas_seguidas.pop((usuario_id, instancia), None)
                else:
                    # NADA LIDO: a falha foi da volta, não dos processos. A
                    # tentativa cobrada na entrega volta, e o par espera.
                    devolvidas = acmod.devolver_tentativas(cx, usuario_id, instancia, lista)
                    cx.commit()
                    n = (_fs[0] if _fs else 0) + 1
                    espera = min(ESPERA_APOS_FALHA_S * 2 ** (n - 1), ESPERA_MAXIMA_S)
                    _falhas_seguidas[(usuario_id, instancia)] = (n, time.time() + espera,
                                                                 agora_dt.date(), agora())
                    print(f"acompanhamento(servidor): volta sem leitura — {devolvidas} "
                          f"tentativa(s) devolvida(s), próxima em {espera // 60} min",
                          flush=True)
            except Exception as ex:                        # noqa: BLE001
                # UM PAR QUE LEVANTA NÃO DERRUBA A PASSADA dos outros. Antes, a
                # exceção subia até o laço, e com a ordem fixa dos candidatos o
                # mesmo par levantava primeiro em toda volta, para sempre.
                try:
                    cx.rollback()
                    if lista:
                        acmod.devolver_tentativas(cx, usuario_id, instancia, lista)
                        cx.commit()
                except Exception:                          # noqa: BLE001
                    pass
                _falhas_seguidas[(usuario_id, instancia)] = (
                    (_fs[0] if _fs else 0) + 1, time.time() + ESPERA_APOS_FALHA_S,
                    agora_dt.date(), agora())
                print(f"acompanhamento(servidor): conta {usuario_id} · {instancia} "
                      f"levantou {type(ex).__name__}", flush=True)
            finally:
                if conta:
                    try:
                        cx.rollback()                      # nada pendente desta volta
                    except Exception:                      # noqa: BLE001
                        pass
                    _bmod.soltar_conta(instancia, conta, None, dono)
                atendente._vagas.release()
                atendente._pesado.release()
    finally:
        if proprio:
            cx.close()
    return feitas


def laco():
    _laco_vivo.set()
    try:
        pode, motivo = capacidade()
    except Exception as ex:                                    # noqa: BLE001
        pode, motivo = False, f"a capacidade não pôde ser medida ({type(ex).__name__})"
    print(f"acompanhamento em modo servidor: {'ligado' if pode else 'PARADO'} — "
          f"{motivo or 'aguardando item fora da carteira'}", flush=True)
    while _laco_vivo.is_set():
        try:
            if capacidade()[0]:
                rodada()
        except Exception as ex:                                # noqa: BLE001
            print(f"acompanhamento em modo servidor: {type(ex).__name__}", flush=True)
        time.sleep(INTERVALO_S)


def iniciar():
    """Sobe o laço numa thread deste processo, se: ligado, e este processo é
    quem venceu a eleição do atendente — ver MEMÓRIA, item 4. Idempotente."""
    global _thread
    if not ligado() or (_thread and _thread.is_alive()):
        return False
    if not atendente.vivo():
        # Não é erro: ou a busca está desligada (SEI360_ATENDENTE=0), ou este
        # processo é um worker de painel que não venceu a eleição dela.
        return False
    _thread = threading.Thread(target=laco, name="acompanhamento-servidor",
                               daemon=True)
    _thread.start()
    return True


if __name__ == "__main__":
    # Só faz sentido no mesmo processo do atendente (ver MEMÓRIA, item 4):
    # rodar isto sozinho não teria com quem compartilhar o semáforo de memória,
    # e por isso `laco()` aqui não chama `iniciar()`.
    laco()
