# -*- coding: utf-8 -*-
"""
O executor de COLETA DIÁRIA dentro do servidor, para quem está em modo
"servidor" (a senha cifrada no cofre, não no Gerenciador de Credenciais de
uma estação).

POR QUE ESTE ARQUIVO EXISTE
----------------------------
Desde 21/08/2026 o container executa a BUSCA avançada (`atendente.py`). A
coleta diária continuava de fora: `_motivo_servidor()` (app.py) documentava,
com o nome de quem decidiu, que não havia executor de coleta aqui — só
`coleta.py`, pensado para o operador chamar à mão (teste de acesso, amostra
de parser). Em 08/09/2026 a FESF (SEI 4.0) ganhou parser provado em campo
(ARQUITETURA_ACESSO.md, `perfil_sei.py`), e a pergunta deixou de ser "o
parser funciona" para virar "quem dispara a coleta sozinho". Este módulo é
essa resposta.

O QUE ELE FAZ
-------------
Um agente lógico "SERVIDOR/<login>" (criado por `aplicar_agendamento` em
app.py, um por pessoa em modo servidor) tem `agendamento` e `execucao` como
qualquer agente de estação — é a MESMA tabela, a mesma `janelas.janela_devida`.
Este laço pergunta, em processo, a mesma pergunta que `/api/agente/tarefa`
responderia por HTTP para uma estação: há janela devida? Se houver, grava a
`execucao` 'entregue' (o mesmo lock-por-INSERT que impede duas entregas da
mesma janela) e chama `coleta.coletar()` — a MESMA função já usada por
"Testar acesso agora" e pela amostra de parser — com `--mesas`. No sucesso,
localiza o JSON que o coletor escreveu e chama `ingestao.ingerir()` com o
mesmo formato de parâmetros que `/api/agente/resultado` usa para uma estação.

MEMÓRIA COMPARTILHADA COM atendente.py — LIDO ANTES DE MEXER AQUI
-------------------------------------------------------------------
Uma coleta usa o MESMO Chromium que uma busca e custa memória comparável,
por minutos em vez de segundos. Ninguém mediu as duas rodando juntas num VPS
de 2 GB (ARQUITETURA_ACESSO.md §3.7) — a defesa aqui é deliberadamente
conservadora, não uma medição:

  1. NASCE DESLIGADO. `SEI360_COLETA_SERVIDOR` tem de ser "1" — ao contrário
     de `atendente.py`, que liga sozinho. A busca já tinha decisão formal
     (§6.0) antes de existir; isto ainda não tem, e o primeiro dia em
     produção é decisão de quem administra, não deste módulo.
  2. SÓ COMEÇA COM A BUSCA OCIOSA (nenhuma execução em curso) — não rouba
     memória de quem está na tela esperando.
  3. ENQUANTO RODA, SEGURA UMA VAGA de `atendente._vagas` — o MESMO
     semáforo, não um teto paralelo que finge não saber do outro. Uma busca
     que chegue no meio vê a capacidade reduzida de verdade.
  4. NO MÁXIMO UMA COLETA por vez neste container (`LIMITE`, hoje fixo em 1
     — não é `SEI360_BUSCAS_SIMULTANEAS`, que é sobre pessoas diferentes
     pedindo busca ao mesmo tempo; aqui o motivo de não paralelizar é não ter
     medido, não é o mesmo motivo).

MESMO PROCESSO QUE O ATENDENTE, DE PROPÓSITO
----------------------------------------------
O semáforo de `atendente` é um `threading.Semaphore` — só coordena threads
DENTRO de um processo. Com `--workers 3`, uma eleição própria para este
laço poderia cair num worker DIFERENTE do que venceu a eleição da busca, e aí
os dois tetos de memória deixariam de se enxergar. Por isso este módulo não
disputa a própria vez: só sobe se `atendente.vivo()` já for verdadeiro NESTE
processo — pega carona no vencedor, nunca disputa a eleição.

O QUE ELE NÃO FAZ (dívida, escrita para não virar surpresa)
--------------------------------------------------------------
Não decide o parser nem a disponibilidade por instalação — isso é
`perfil_sei.disponivel_coleta`, conferido antes de cada tentativa, igual à
rota HTTP. Não substitui a decisão de arquitetura de custódia de senha
(§6.0/§6.3): quem prefere que a senha nunca toque o servidor continua tendo
o modo estação, e ele não passa por aqui. E não foi medido em produção sob
carga real de múltiplas contas em modo servidor simultâneas — o rollout
inicial deveria ser de poucas contas, observado, não geral.
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import atendente
import banco
import cofre
import ingestao
import janelas
import perfil_sei
from coleta import COLETOR, coletar as _coletar

# Nunca paralelizar coletas neste container na primeira versão: o motivo é
# "ninguém mediu", não um número calculado. Ver cabeçalho.
LIMITE = 1
# De quanto em quanto tempo o laço olha se há janela devida. Diferente do
# INTERVALO_S da busca (3 s: alguém está na tela) — aqui ninguém espera
# clique nenhum, e a consulta custa o mesmo todo minuto ou a cada 3 s.
INTERVALO_S = 60

_laco_vivo = threading.Event()
_thread = None
_reavaliados = False          # backfill de agentes SERVIDOR/* já criados


def ligado():
    """Liga só por variável explícita — ver "NASCE DESLIGADO" no cabeçalho."""
    return os.environ.get("SEI360_COLETA_SERVIDOR", "0") in ("1", "true", "sim")


def capacidade():
    """(pode, motivo). O requisito é o MESMO do atendente: mesmo coletor, mesmo
    Playwright, mesmo cofre — só muda quem pede a execução. Reaproveitar em
    vez de duplicar evita as duas respostas divergirem um dia."""
    return atendente.capacidade()


def vivo():
    """A thread deste laço está viva NESTE processo?"""
    return bool(_thread and _thread.is_alive())


def ha_executor():
    """Existe executor de coleta neste CONTAINER? (qualquer worker)

    A DIFERENÇA COM `vivo()` ERA UM DEFEITO COM CONSEQUÊNCIA, achado em
    12/09/2026: `_motivo_servidor()` (app.py) perguntava `vivo()`, que só sabe
    deste processo. Com `--workers 3`, dois dos três respondem False — então
    salvar /configuracao caindo num worker de painel gravava `pausado_motivo` =
    "o executor deveria estar rodando e não está" e **DESARMAVA o agendamento
    da conta**, por um fato verdadeiro sobre aquele processo e falso sobre o
    container. Dois terços das vezes, e com a mensagem culpando o servidor.

    E não voltava sozinho: `_reavaliar_existentes` roda uma vez por processo, na
    subida. Até o próximo redeploy, aquela conta não coletava — o modo de falha
    silencioso que este módulo inteiro foi escrito para não ter.

    Este laço só sobe onde `atendente.vivo()` é verdadeiro (ver `iniciar`), e o
    atendente já sabe responder pelo container inteiro através do arquivo de vez.
    Logo a pergunta certa é a dele.

    RESSALVA ESCRITA: se `coleta_servidor.iniciar()` tivesse levantado no worker
    vencedor (app.py o envolve em try/except para a busca não cair junto), um
    worker de painel responderia "há executor" sem haver. O worker vencedor
    responderia a verdade, e o log traria a linha da exceção.
    """
    return vivo() or atendente.ha_executor()


# ------------------------------------------------------------------ a fila
def _candidatos(cx):
    """Agentes lógicos SERVIDOR/* armados: com dono e sem pausa própria.

    `pausado_motivo` é a marca do agente lógico (app.aplicar_agendamento) —
    filtra aqui, não decide: quem decide se DEVE estar pausado é aquela
    função, chamada de novo em `_reavaliar_existentes()` na subida deste
    laço, para quem configurou antes de este módulo existir.
    """
    return [r["id"] for r in cx.execute(
        """SELECT id FROM agentes WHERE nome_estacao LIKE 'SERVIDOR/%'
           AND dono_usuario_id IS NOT NULL AND pausado_motivo IS NULL""")]


def _decidir(cx, agente_id, agora_dt=None):
    """Mesma pergunta de `/api/agente/tarefa` (app.py), para UM agente lógico.

    Devolve (execucao_id, janela, instancia, perfil) quando há o que coletar
    agora, ou (None, motivo, None, None) quando não há.

    DUPLICADA DE PROPÓSITO, não extraída da rota. Aquela rota atende toda
    estação de produção agora (inclusive a que já funciona, SESAB); reduzir
    o risco desta primeira versão valeu mais que eliminar a duplicação. Se
    este laço se provar em produção, as duas podem convergir para uma função
    só — não antes.
    """
    ag = cx.execute("SELECT * FROM agentes WHERE id=?", (agente_id,)).fetchone()
    if not ag or ag["pausado_motivo"]:
        return None, ag["pausado_motivo"] if ag else "agente removido", None, None
    cfg = cx.execute("SELECT * FROM agendamento WHERE agente_id=?", (agente_id,)).fetchone()
    if not cfg or not cfg["ativo"]:
        return None, (cfg["motivo_inativo"] if cfg else None) or "agendamento desarmado", None, None

    # A INSTALAÇÃO vem da configuração do dono em modo servidor — nunca de um
    # padrão escrito à mão (foi bug real: SESAB fixo fazia a FESF entrar no
    # SEI errado, com falha que parecia senha inválida).
    linha = cx.execute("""SELECT sistema FROM config_usuario
                          WHERE usuario_id=? AND modo_coleta='servidor'
                          ORDER BY atualizado_em DESC LIMIT 1""",
                       (ag["dono_usuario_id"],)).fetchone()
    if not linha:
        return None, "sem sistema configurado em modo servidor", None, None
    instancia = linha["sistema"]
    perfil = perfil_sei.perfil(instancia)
    if not perfil["disponivel_coleta"]:
        return None, f"coleta indisponível em {perfil['nome']}", None, None

    ocupada = cx.execute("""SELECT id FROM execucao WHERE agente_id=? AND estado='em_curso'
                            LIMIT 1""", (agente_id,)).fetchone()
    if ocupada:
        return None, f"execução {ocupada['id']} ainda em curso", None, None
    # RETOMA SÓ O QUE ESTE MOTOR ENTREGOU A SI MESMO. `gatilho='servidor'` é o
    # carimbo que o INSERT abaixo põe; `/api/agente/tarefa` põe outro.
    #
    # Sem a condição, uma janela que a ESTAÇÃO levou (`execucao` 'entregue',
    # dela) seria retomada aqui e coletada em paralelo — duas sessões do SEI na
    # mesma conta, gravando na mesma `execucao`. Não era alcançável enquanto um
    # agente era estação OU servidor pelo nome; passou a ser no dia em que
    # `aplicar_agendamento` começou a CONVERTER o agente de quem escolhe modo
    # servidor sem desfazer o pareamento (12/09/2026). Esta guarda é o que torna
    # a conversão segura.
    pendente = cx.execute("""SELECT * FROM execucao WHERE agente_id=? AND estado='entregue'
                             AND gatilho='servidor'
                             ORDER BY id DESC LIMIT 1""", (agente_id,)).fetchone()
    if pendente:
        return (pendente["id"], pendente["janela"], instancia,
                perfil_sei.envelope_do_coletor(instancia))

    agora_dt = agora_dt or datetime.now(janelas.TZ)
    hoje = agora_dt.date().isoformat()
    concluidas = {r["janela"] for r in cx.execute(
        "SELECT janela FROM execucao WHERE agente_id=? AND estado='concluida' AND janela LIKE ?",
        (agente_id, hoje + "%"))}
    devida, motivo = janelas.janela_devida(cfg, agora_dt=agora_dt, ja_concluidas=concluidas)
    if not devida:
        return None, motivo, None, None
    entregues = cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=? AND janela=?",
                           (agente_id, devida)).fetchone()[0]
    if entregues >= cfg["max_entregas_janela"]:
        return None, "teto de entregas desta janela atingido", None, None
    # A ESTAÇÃO LEVOU ESTA JANELA: sai daqui sem entregar. `max_entregas_janela`
    # é 3 por padrão, e ele existe para RETENTATIVA — não para dois executores
    # coletando a mesma mesa ao mesmo tempo, na mesma conta, com a mesma
    # credencial nominal. `IS NOT` e não `<>` porque `gatilho` aceita nulo, e em
    # SQL `NULL <> 'servidor'` não é verdadeiro: a entrega sem carimbo escaparia.
    da_estacao = cx.execute(
        """SELECT id FROM execucao WHERE agente_id=? AND janela=?
           AND gatilho IS NOT 'servidor'
           AND estado IN ('entregue','em_curso') LIMIT 1""",
        (agente_id, devida)).fetchone()
    if da_estacao:
        return None, f"a estação levou esta janela (execução {da_estacao['id']})", None, None

    # A ENTREGA É O LOCK, igual à rota HTTP: gravar antes de agir impede que
    # duas passadas do laço (ou uma passada e um pedido manual) peguem a
    # mesma janela duas vezes.
    cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em)
                  VALUES(?,?,'entregue','servidor',?)""",
               (agente_id, devida, banco.agora()))
    ex = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    return ex, devida, instancia, perfil_sei.envelope_do_coletor(instancia)


# --------------------------------------------------------------- a execução
_EXIT_PARA_ESTADO = {0: "concluida", 1: "concluida", 2: "sem_dados",
                     3: "bloqueada", 4: "infra", 5: "travada"}


def _achar_json(instancia, desde):
    """O arquivo que `coletor_sesab.py --mesas` acabou de escrever, ou None.

    Mesmo critério do agente de estação (`sei360_agente.py:rodar`): o mais
    novo `sei_*.json` (nunca `.anterior`) na pasta de coletas, e só serve se
    for mais novo que `desde` — sem isso, uma corrida sem dados aproveitaria
    por engano o arquivo de uma coleta manual de minutos atrás.
    """
    pasta = COLETOR.parent / "_coletas"
    if not pasta.is_dir():
        return None
    candidatos = sorted(
        (p for p in pasta.glob("sei_*.json") if ".anterior" not in p.name),
        key=lambda p: p.stat().st_mtime)
    if not candidatos:
        return None
    mais_novo = candidatos[-1]
    if mais_novo.stat().st_mtime < desde:
        return None
    return mais_novo


# DE QUANTO EM QUANTO TEMPO ESTE MÓDULO MANDA PULSO. Bem abaixo de
# `app.SEM_PULSO_MIN` (5 min) — a mesma varredura (`varrer_execucoes`) que
# destrava estação de verdade travada marcava, achada em campo em 08/09/2026,
# QUALQUER coleta de mais de 5 min como "travada" (exit_code 5), porque este
# módulo nunca escrevia `heartbeat_em`. A coleta em si tinha terminado bem —
# só o registro é que mentia, e mentia com a MESMA cara de uma trava real.
_PULSO_S = 60


def _pulsar(execucao_id, parar):
    """Atualiza `heartbeat_em` a cada `_PULSO_S`, com conexão própria — esta
    função roda numa thread separada, e conexão sqlite não se compartilha
    entre threads. Nunca deixa uma exceção de pulso derrubar a coleta: um
    pulso perdido é o pior caso que este laço já existe para evitar."""
    while not parar.wait(_PULSO_S):
        try:
            c = banco.conectar()
            try:
                c.execute("UPDATE execucao SET heartbeat_em=? WHERE id=? AND estado='em_curso'",
                         (banco.agora(), execucao_id))
                c.commit()
            finally:
                c.close()
        except Exception:                                          # noqa: BLE001
            pass


def _executar(agente_id, execucao_id, janela, instancia):
    """Roda uma coleta já reivindicada e publica o resultado. Nunca deixa a
    `execucao` presa em 'em_curso': todo caminho de saída grava um estado
    terminal, inclusive quando algo dá exceção no meio."""
    cx = banco.conectar()
    inicio = time.time()
    parar_pulso = threading.Event()
    pulso = None
    try:
        ag = cx.execute("SELECT dono_usuario_id FROM agentes WHERE id=?",
                        (agente_id,)).fetchone()
        uid = ag["dono_usuario_id"]
        cx.execute("UPDATE execucao SET estado='em_curso', iniciado_em=?, heartbeat_em=? WHERE id=?",
                   (banco.agora(), banco.agora(), execucao_id))
        cx.commit()
        # O PULSO SOBE ANTES DO SUBPROCESSO BLOQUEANTE. `coleta.coletar()` só
        # devolve quando o coletor termina — até 30 min — e não há ponto
        # nenhum no meio para escrever um heartbeat por conta própria; por
        # isso ele mora numa thread à parte, não numa chamada síncrona aqui.
        pulso = threading.Thread(target=_pulsar, args=(execucao_id, parar_pulso),
                                 name=f"pulso-coleta-{execucao_id}", daemon=True)
        pulso.start()

        codigo, saida = _coletar(uid, instancia)
        estado = _EXIT_PARA_ESTADO.get(codigo, "infra")
        publicado = None
        if codigo <= 1:
            arq = _achar_json(instancia, inicio)
            if not arq:
                estado, saida = "sem_dados", (saida or "") + "\n[sem arquivo de coleta para publicar]"
            else:
                colhido = datetime.fromtimestamp(arq.stat().st_mtime, janelas.TZ) \
                    .isoformat(timespec="seconds")
                unidades = json.loads(cx.execute(
                    "SELECT unidades_esperadas FROM agentes WHERE id=?",
                    (agente_id,)).fetchone()["unidades_esperadas"] or "[]")
                try:
                    # `ingerir()` é ferramenta de CLI: um lote vazio chama
                    # `sys.exit()`, que o Python não trata como Exception
                    # comum. Sem capturar SystemExit aqui, uma coleta vazia
                    # derrubaria o worker do gunicorn inteiro.
                    ingestao.ingerir(caminho=str(arq), agente_id=agente_id,
                                     execucao_id=execucao_id, coletado_em=colhido,
                                     escopo=unidades, dono=uid, instancia=instancia)
                    publicado = str(arq.name)
                except SystemExit as ex:
                    estado, saida = "sem_dados", (saida or "") + f"\n[ingestão recusou: {ex}]"
    except Exception as ex:                                        # noqa: BLE001
        # O TIPO, NÃO A MENSAGEM — mesma regra do atendente: mensagem de
        # exceção pode carregar caminho ou valor que falhou.
        estado, codigo, saida = "infra", None, f"falha no executor ({type(ex).__name__})"
        publicado = None
    finally:
        parar_pulso.set()
        if pulso is not None:
            pulso.join(timeout=5)          # nunca bloqueia pra sempre por um pulso preso
        duracao = round(time.time() - inicio)
        try:
            cx.execute("""UPDATE execucao SET estado=?, terminado_em=?, duracao_s=?,
                          exit_code=?, log_resumo=? WHERE id=?""",
                       (estado, banco.agora(), duracao, codigo,
                        (f"publicado {publicado}" if publicado else "não publicado")
                        + f" · {(saida or '')[-300:]}", execucao_id))
            banco.registrar(cx, None, "coleta_servidor",
                            alvo=f"agente {agente_id} · {instancia} · {estado}")
            cx.commit()
        except Exception:                                          # noqa: BLE001
            try:
                cx.rollback()
            except Exception:                                      # noqa: BLE001
                pass
        finally:
            cx.close()


# ------------------------------------------------------------------- o laço
def _reavaliar_existentes():
    """Roda uma vez, na subida do laço: destrava quem configurou modo servidor
    ANTES de este módulo existir. Sem isto, a conta ficaria com
    `pausado_motivo` escrito para sempre — verdadeiro no dia em que foi
    gravado, falso a partir de agora — até a pessoa reabrir e salvar
    `/configuracao` de novo por conta própria."""
    global _reavaliados
    if _reavaliados:
        return
    _reavaliados = True
    import app as _app                          # tardio: evita ciclo de import
    cx = banco.conectar()
    try:
        donos = [r["dono_usuario_id"] for r in cx.execute(
            """SELECT DISTINCT dono_usuario_id FROM agentes
               WHERE nome_estacao LIKE 'SERVIDOR/%' AND dono_usuario_id IS NOT NULL""")]
        for uid in donos:
            _app.aplicar_agendamento(cx, uid)
        cx.commit()
        if donos:
            print(f"coleta em modo servidor: reavaliados {len(donos)} agente(s) existente(s)",
                  flush=True)
    finally:
        cx.close()


def rodada(cx=None):
    """Uma passada: no máximo `LIMITE` coleta(s). Devolve quantas rodou.

    Separada do laço para o teste poder chamar sem thread e sem relógio —
    mesmo desenho de `atendente.rodada`.
    """
    proprio = cx is None
    cx = cx or banco.conectar()
    feitas = 0
    try:
        if feitas >= LIMITE:
            return feitas
        # SÓ COMEÇA COM A BUSCA OCIOSA. `vagas_livres() == LIMITE_atendente`
        # é "ninguém usando nenhuma vaga agora" — o mesmo teste que
        # `atendente.capacidade()` faz para detectar vaga perdida, aqui
        # usado para "está tudo livre".
        if atendente.vagas_livres() != atendente.LIMITE:
            return feitas
        if not atendente._vagas.acquire(blocking=False):
            return feitas                        # perdeu a corrida por uma vaga
        try:
            agora_dt = datetime.now(janelas.TZ)
            for agente_id in _candidatos(cx):
                ex, janela, instancia, _perfil = _decidir(cx, agente_id, agora_dt)
                cx.commit()
                if instancia is None:
                    continue                     # `janela` aqui é o motivo da recusa
                _executar(agente_id, ex, janela, instancia)
                feitas += 1
                break                            # uma por passada: LIMITE=1
        finally:
            atendente._vagas.release()
    finally:
        if proprio:
            cx.close()
    return feitas


def laco():
    _laco_vivo.set()
    _reavaliar_existentes()
    try:
        pode, motivo = capacidade()
    except Exception as ex:                                        # noqa: BLE001
        pode, motivo = False, f"a capacidade não pôde ser medida ({type(ex).__name__})"
    print(f"coleta em modo servidor: {'ligado' if pode else 'PARADO'} — "
          f"{motivo or 'aguardando janela devida'}", flush=True)
    while _laco_vivo.is_set():
        try:
            if capacidade()[0]:
                rodada()
        except Exception as ex:                                    # noqa: BLE001
            print(f"coleta em modo servidor: {type(ex).__name__}", flush=True)
        time.sleep(INTERVALO_S)


def iniciar():
    """Sobe o laço numa thread deste processo, se: ligado por variável, e
    este processo é quem já venceu a eleição do atendente de busca — ver
    "MESMO PROCESSO QUE O ATENDENTE" no cabeçalho. Idempotente.
    """
    global _thread
    if not ligado() or (_thread and _thread.is_alive()):
        return False
    if not atendente.vivo():
        # Não é erro: ou a busca está desligada (SEI360_ATENDENTE=0), ou este
        # processo é um worker de painel que não venceu a eleição dela.
        return False
    _thread = threading.Thread(target=laco, name="coleta-servidor", daemon=True)
    _thread.start()
    return True


if __name__ == "__main__":
    # Só faz sentido como parte do mesmo processo do atendente (ver
    # cabeçalho) — rodar isto sozinho não teria com quem compartilhar o
    # semáforo de memória, e por isso `laco()` aqui não chama `iniciar()`.
    laco()
