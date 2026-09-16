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
import diario
import ingestao
import janelas
import leitura_saida
import perfil_sei
import busca as bmod
import coleta as coleta_mod
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
# O MOTIVO DE NÃO COLETAR, dito UMA VEZ por mudança. Sem isto, o laço decidia em
# silêncio a cada minuto: a coleta não rodava e o log não dizia por quê — foi o
# que custou três dias úteis em 15/09/2026. Imprimir a cada passada seriam 1.440
# linhas iguais por dia, que é a outra forma de não dizer nada.
_ultimo_motivo = {}


def _dizer(agente_id, motivo):
    if _ultimo_motivo.get(agente_id) != motivo:
        _ultimo_motivo[agente_id] = motivo
        print(f"coleta(servidor): agente {agente_id} — {motivo}", flush=True)
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


def _instancia_do_dono(cx, dono):
    """(instância, motivo) — a instalação que este motor coleta para esta pessoa.

    A INSTALAÇÃO vem da configuração do dono em modo servidor — nunca de um
    padrão escrito à mão (foi bug real: SESAB fixo fazia a FESF entrar no SEI
    errado, com falha que parecia senha inválida).

    E ENTRE AS CONFIGURADAS, A QUE TEM SENHA. A versão anterior pegava a mais
    RECENTE, tivesse ou não senha guardada. Em 15/09/2026 uma conta com a coleta
    da FESF funcionando abriu o passo "sistema" da SESAB na Configuração — a linha
    da SESAB nasceu em modo servidor, sem senha, e virou a mais recente: a coleta
    da FESF parou, e toda manhã gravava duas execuções 'bloqueada' com "nenhuma
    credencial guardada". Nada na tela dizia que um clique tinha trocado a
    instalação coletada.
    """
    linhas = cx.execute("""SELECT c.sistema,
                                  EXISTS(SELECT 1 FROM credencial k
                                          WHERE k.usuario_id = c.usuario_id
                                            AND k.sistema = c.sistema) AS tem_senha
                           FROM config_usuario c
                           WHERE c.usuario_id=? AND c.modo_coleta='servidor'
                           ORDER BY c.atualizado_em DESC""", (dono,)).fetchall()
    if not linhas:
        return None, "sem sistema configurado em modo servidor"
    com_senha = [l["sistema"] for l in linhas if l["tem_senha"]]
    if not com_senha:
        # NÃO GRAVA EXECUÇÃO. "Não há senha" é estado da configuração, não falha
        # de uma coleta — antes eram duas linhas 'bloqueada' por dia por conta, e a
        # lista de execuções do /admin virava ruído que esconde a falha de verdade.
        return None, (f"sem senha do SEI guardada no servidor para {linhas[0]['sistema']}"
                      " — a pessoa salva em Configuração → Acesso")
    return com_senha[0], None


def _avaliar(cx, agente_id, agora_dt=None):
    """A decisão, SEM ESCREVER: ('pendente', id, janela, instância),
    ('devida', None, janela, instância) ou ('nao', None, motivo, instância|None).

    Separada de `_decidir` para o /admin poder perguntar "por que este agente não
    coleta?" sem gravar entrega nenhuma — a mesma resposta que o laço usa, e não
    uma segunda implementação que um dia diverge.
    """
    ag = cx.execute("SELECT * FROM agentes WHERE id=?", (agente_id,)).fetchone()
    if not ag or ag["pausado_motivo"]:
        return "nao", None, ag["pausado_motivo"] if ag else "agente removido", None
    cfg = cx.execute("SELECT * FROM agendamento WHERE agente_id=?", (agente_id,)).fetchone()
    if not cfg or not cfg["ativo"]:
        return "nao", None, (cfg["motivo_inativo"] if cfg else None) or "agendamento desarmado", None

    instancia, motivo = _instancia_do_dono(cx, ag["dono_usuario_id"])
    if not instancia:
        return "nao", None, motivo, None
    perfil = perfil_sei.perfil(instancia)
    if not perfil["disponivel_coleta"]:
        return "nao", None, f"coleta indisponível em {perfil['nome']}", instancia

    ocupada = cx.execute("""SELECT id FROM execucao WHERE agente_id=? AND estado='em_curso'
                            LIMIT 1""", (agente_id,)).fetchone()
    if ocupada:
        return "nao", None, f"execução {ocupada['id']} ainda em curso", instancia
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
    #
    # E A JANELA EXTRA DO ADMIN (`gatilho='manual_admin'`, /admin → "janela extra")
    # É DESTE MOTOR TAMBÉM, quando o agente é lógico. Sem ela na lista, o único
    # jeito de FORÇAR a coleta de uma conta em modo servidor gravava uma execução
    # 'entregue' que ninguém executava: a guarda acima, escrita para não roubar a
    # janela da estação, pegou junto o botão do admin (achado em 15/09/2026, ao
    # ir forçar uma coleta). A estação carimba 'janela' — é só essa que não é nossa.
    pendente = cx.execute("""SELECT * FROM execucao WHERE agente_id=? AND estado='entregue'
                             AND gatilho IN ('servidor','manual_admin')
                             ORDER BY id DESC LIMIT 1""", (agente_id,)).fetchone()
    if pendente:
        # A JANELA EXTRA DO ADMIN PASSA pelas guardas abaixo (escopo, senha
        # recusada) de propósito: forçar é decisão de quem administra, tomada
        # olhando a tela — inclusive para conferir se a conta já foi destravada
        # no SEI.
        return "pendente", pendente["id"], pendente["janela"], instancia

    # SEM ESCOPO, A COLETA SÓ TEM EFEITO COLATERAL. Nada do que ela ler pode ser
    # publicado (a ingestão recorta tudo), mas abrir a mesa no SEI RECEBE os
    # processos em trânsito em nome da conta — medido em 11/09/2026. O escopo de
    # quem está em modo servidor nasce do vínculo, e o vínculo nasce do "Testar
    # acesso" que deu certo: sem ele, não há o que coletar.
    if not json.loads(ag["unidades_esperadas"] or "[]"):
        return "nao", None, ("sem escopo: nenhuma unidade que este agente possa publicar "
                             "(o vínculo nasce do 'Testar acesso' que deu certo)"), instancia

    # O SEI RECUSOU ESTA SENHA e ela não foi salva de novo: não se tenta outra vez.
    # Cada tentativa conta para o bloqueio da conta da pessoa no SEI.
    rec = cofre.recusa(cx, ag["dono_usuario_id"], instancia)
    if rec:
        return "nao", None, (f"o SEI recusou a senha em {str(rec['recusada_em'])[:16].replace('T', ' ')}"
                             f" — {rec['recusa_motivo']} Não tento de novo até a senha ser "
                             f"salva outra vez em Configuração."), instancia

    agora_dt = agora_dt or datetime.now(janelas.TZ)
    hoje = agora_dt.date().isoformat()
    concluidas = {r["janela"] for r in cx.execute(
        "SELECT janela FROM execucao WHERE agente_id=? AND estado='concluida' AND janela LIKE ?",
        (agente_id, hoje + "%"))}
    devida, motivo = janelas.janela_devida(cfg, agora_dt=agora_dt, ja_concluidas=concluidas)
    if not devida:
        return "nao", None, motivo, instancia
    entregues = cx.execute("SELECT COUNT(*) FROM execucao WHERE agente_id=? AND janela=?",
                           (agente_id, devida)).fetchone()[0]
    if entregues >= cfg["max_entregas_janela"]:
        return "nao", None, "teto de entregas desta janela atingido", instancia
    # LOGIN QUE FALHOU NESTA JANELA NÃO SE REPETE NELA. A segunda entrega existe
    # para o que é passageiro — rede, SEI fora, navegador morto —, e login não é:
    # a recusa de 16/09/2026 04:08 se repetiu às 04:10, com a mesma senha, um
    # minuto depois. Mesmo quando a recusa é incerta (sem mensagem do SEI), a
    # próxima tentativa é a janela seguinte, não o minuto seguinte.
    # SALVAR A SENHA DE NOVO reabre a janela: quem corrigiu às 08:00 a senha que
    # falhou às 07:48 espera a coleta ainda nesta manhã, não amanhã.
    ultima = cx.execute("""SELECT id, causa, terminado_em FROM execucao
                           WHERE agente_id=? AND janela=?
                           ORDER BY id DESC LIMIT 1""", (agente_id, devida)).fetchone()
    if ultima and (ultima["causa"] or "") in leitura_saida.CAUSAS_DE_LOGIN:
        salva = cx.execute("SELECT criado_em FROM credencial WHERE usuario_id=? AND sistema=?",
                           (ag["dono_usuario_id"], instancia)).fetchone()
        if not (salva and salva["criado_em"] and ultima["terminado_em"]
                and str(salva["criado_em"]) > str(ultima["terminado_em"])):
            return "nao", None, (f"o login falhou nesta janela (execução {ultima['id']}, "
                                 f"{ultima['causa']}) — não repito na mesma janela"), instancia
    # A ESTAÇÃO LEVOU ESTA JANELA: sai daqui sem entregar. `max_entregas_janela`
    # é 3 por padrão, e ele existe para RETENTATIVA — não para dois executores
    # coletando a mesma mesa ao mesmo tempo, na mesma conta, com a mesma
    # credencial nominal. `IS NOT` e não `<>` porque `gatilho` aceita nulo, e em
    # SQL `NULL <> 'servidor'` não é verdadeiro: a entrega sem carimbo escaparia.
    da_estacao = cx.execute(
        """SELECT id FROM execucao WHERE agente_id=? AND janela=?
           AND gatilho IS NOT 'servidor' AND gatilho IS NOT 'manual_admin'
           AND estado IN ('entregue','em_curso') LIMIT 1""",
        (agente_id, devida)).fetchone()
    if da_estacao:
        return "nao", None, f"a estação levou esta janela (execução {da_estacao['id']})", instancia
    return "devida", None, devida, instancia


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
    tipo, ex, janela_ou_motivo, instancia = _avaliar(cx, agente_id, agora_dt)
    if tipo == "nao":
        return None, janela_ou_motivo, None, None
    if tipo == "pendente":
        return ex, janela_ou_motivo, instancia, perfil_sei.envelope_do_coletor(instancia)
    # A ENTREGA É O LOCK, igual à rota HTTP: gravar antes de agir impede que
    # duas passadas do laço (ou uma passada e um pedido manual) peguem a
    # mesma janela duas vezes.
    cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em)
                  VALUES(?,?,'entregue','servidor',?)""",
               (agente_id, janela_ou_motivo, banco.agora()))
    ex = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    return ex, janela_ou_motivo, instancia, perfil_sei.envelope_do_coletor(instancia)


def motivo_parado(cx, agente_id):
    """Por que este agente lógico NÃO PODE coletar hoje — ou None se pode.

    Diferente de "por que não coletou agora" (`_avaliar`): "a janela ainda não
    chegou" não é parada, é espera. É o que a varredura de janelas perdidas
    pergunta antes de acusar: janela que fechou de agente PARADO não é janela
    perdida — o motivo já está dito na linha do agente, e repeti-lo como alerta
    todo dia é como um detector morre.
    """
    if not ligado():
        return "coleta em modo servidor desligada neste container (SEI360_COLETA_SERVIDOR)"
    ag = cx.execute("SELECT * FROM agentes WHERE id=?", (agente_id,)).fetchone()
    if not ag:
        return "agente removido"
    if ag["pausado_motivo"]:
        return ag["pausado_motivo"]
    instancia, motivo = _instancia_do_dono(cx, ag["dono_usuario_id"])
    if not instancia:
        return motivo
    if not perfil_sei.perfil(instancia)["disponivel_coleta"]:
        return f"coleta indisponível em {instancia}"
    if not json.loads(ag["unidades_esperadas"] or "[]"):
        return "sem escopo: nenhuma unidade que este agente possa publicar"
    rec = cofre.recusa(cx, ag["dono_usuario_id"], instancia)
    if rec:
        return f"o SEI recusou a senha em {str(rec['recusada_em'])[:16].replace('T', ' ')}"
    return None


def situacao(cx, agente_id, agora_dt=None):
    """O que o /admin mostra na linha do agente: {'estado', 'texto', 'instancia'}.

    `estado` é 'coletando', 'pronto' (espera a janela), 'feito', 'parado'
    (não pode coletar até alguém agir), 'perdida' ou 'falhou' (a janela de hoje
    não rende mais; a próxima tenta de novo). Lê a MESMA decisão do laço
    (`_avaliar`), sem escrever.
    """
    try:
        tipo, ex, texto, instancia = _avaliar(cx, agente_id, agora_dt)
    except Exception as e:                                         # noqa: BLE001
        return {"estado": "parado", "texto": f"não consegui avaliar ({type(e).__name__})",
                "instancia": None}
    if tipo == "pendente":
        return {"estado": "coletando", "instancia": instancia,
                "texto": f"execução {ex} entregue a este motor (janela {str(texto)[:16].replace('T', ' ')})"}
    if tipo == "devida":
        return {"estado": "coletando", "instancia": instancia,
                "texto": f"janela {str(texto)[11:16]} devida agora — o laço a pega na próxima passada"}
    parado = motivo_parado(cx, agente_id)
    if parado:
        # O texto da DECISÃO é o mais completo (diz o que fazer); só o
        # interruptor desligado não passa por ela.
        return {"estado": "parado", "texto": str(texto) if ligado() else parado,
                "instancia": instancia}
    t = str(texto)
    if "em curso" in t or "estação levou" in t:
        return {"estado": "coletando", "texto": t, "instancia": instancia}
    if "perdida" in t:
        return {"estado": "perdida", "texto": t, "instancia": instancia}
    if "teto de entregas" in t or "não repito" in t:
        return {"estado": "falhou", "texto": t, "instancia": instancia}
    if "já coletada" in t:
        return {"estado": "feito", "texto": t, "instancia": instancia}
    return {"estado": "pronto", "texto": t, "instancia": instancia}


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
    uid = None
    codigo, saida, estado, publicado = None, "", "infra", None
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
        # exceção pode carregar caminho ou valor que falhou. E A SAÍDA DO
        # COLETOR FICA: a exceção pode ter vindo DEPOIS dele (na ingestão), e
        # trocá-la pela frase do executor apagava a única prova do que houve.
        estado, codigo = "infra", None
        saida = (saida or "") + f"\n[falha no executor ({type(ex).__name__})]"
        publicado = None
    finally:
        parar_pulso.set()
        if pulso is not None:
            pulso.join(timeout=5)          # nunca bloqueia pra sempre por um pulso preso
        duracao = round(time.time() - inicio)
        # A SAÍDA INTEIRA VAI PARA O VOLUME, e a causa vira chave e frase. Antes,
        # `log_resumo` era a cauda de 300 caracteres — numa senha recusada, o
        # banner do motor JS —, e o resto morria com o processo.
        # NADA AQUI PODE IMPEDIR O UPDATE ABAIXO: ler a causa e gravar o arquivo
        # são extras, e uma exceção neles deixaria a execução 'em_curso' — o
        # estado que este `finally` inteiro existe para nunca deixar.
        try:
            c = leitura_saida.causa(codigo, saida, estado)
        except Exception as _e:                                    # noqa: BLE001
            c = {"chave": "desconhecida", "certeza": False,
                 "texto": f"não consegui ler a saída ({type(_e).__name__})"}
        arquivo = diario.guardar_saida("coleta", execucao_id, saida)
        try:
            print(f"coleta(servidor): execução {execucao_id} · agente {agente_id} · {instancia} · "
                  f"{estado} · código {codigo} · {duracao} s · {c['texto'][:240]}"
                  + (f" · saída em log/execucoes/{arquivo}" if arquivo else ""), flush=True)
        except Exception:                                          # noqa: BLE001
            pass
        try:
            cx.execute("""UPDATE execucao SET estado=?, terminado_em=?, duracao_s=?,
                          exit_code=?, log_resumo=?, causa=? WHERE id=?""",
                       (estado, banco.agora(), duracao, codigo,
                        leitura_saida.resumo(publicado, c, saida), c["chave"], execucao_id))
            if c["chave"] in leitura_saida.CAUSAS_DE_LOGIN and uid:
                _alertar_login(cx, agente_id, execucao_id, uid, instancia, c)
            banco.registrar(cx, None, "coleta_servidor",
                            alvo=f"agente {agente_id} · {instancia} · {estado} · {c['chave']}")
            cx.commit()
        except Exception:                                          # noqa: BLE001
            try:
                cx.rollback()
            except Exception:                                      # noqa: BLE001
                pass
        finally:
            cx.close()


def _alertar_login(cx, agente_id, execucao_id, uid, instancia, c):
    """O login falhou: marca a senha (se a recusa é certa) e diz ao /admin, uma vez.

    UMA VEZ, e não um alerta por tentativa: com a recusa certa não há outra
    tentativa (`_avaliar` para); com a incerta há no máximo uma por janela.
    """
    nome = (cx.execute("SELECT nome_estacao FROM agentes WHERE id=?", (agente_id,))
            .fetchone() or {"nome_estacao": f"agente {agente_id}"})["nome_estacao"]
    if c["certeza"]:
        cofre.marcar_recusa(cx, uid, instancia, c["texto"])
        consequencia = ("A coleta desta conta está PARADA até a senha ser salva de novo em "
                        "Configuração — cada tentativa errada conta para o bloqueio da conta "
                        "no SEI, e ela não é repetida.")
    else:
        consequencia = ("Não repito nesta janela; a próxima tentativa é na janela seguinte. "
                        "Se a senha mudou no SEI, salve a nova em Configuração.")
    cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,texto)
                  VALUES(?,?,?,?,?)""",
               (banco.agora(), "login_falhou", "alta", execucao_id,
                f"{nome} não entrou no {instancia}: {c['texto']} {consequencia}"))


def _conta_do_agente(cx, agente_id, instancia):
    """O login do SEI do dono deste agente nesta instalação."""
    r = cx.execute("""SELECT c.sei_login FROM agentes a
                      JOIN config_usuario c ON c.usuario_id = a.dono_usuario_id
                                           AND c.sistema = ?
                      WHERE a.id = ?""", (instancia, agente_id)).fetchone()
    return ((r["sei_login"] if r else "") or "").strip() or None


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
        # TRABALHO PESADO UM POR VEZ — ver `atendente._pesado`.
        if not atendente._pesado.acquire(blocking=False):
            return feitas
        if not atendente._vagas.acquire(blocking=False):
            atendente._pesado.release()
            return feitas                        # perdeu a corrida por uma vaga
        try:
            agora_dt = datetime.now(janelas.TZ)
            for agente_id in _candidatos(cx):
                ex, janela, instancia, _perfil = _decidir(cx, agente_id, agora_dt)
                cx.commit()
                if instancia is None:
                    _dizer(agente_id, janela)    # `janela` aqui é o motivo da recusa
                    continue
                # A CONTA DO SEI OCUPADA POR UMA BUSCA: a coleta espera. A execução
                # continua 'entregue' e é retomada na próxima passada — e a busca
                # não vê a mesa trocada debaixo dela, que desde 15/09/2026 é real:
                # a busca passou a ativar a mesa pedida.
                _dizer(agente_id, f"vou coletar {instancia} (janela {janela})")
                conta = _conta_do_agente(cx, agente_id, instancia)
                dono = f"motor:{atendente.TOKEN}:coleta"
                if conta:
                    # Trava de motor de um executor que já morreu não segura nada.
                    bmod.limpar_travas_de_motor(cx, atendente.TOKEN)
                    if not bmod._travar(cx, instancia, conta, None,
                                        minutos=coleta_mod.TIMEOUT_COLETA_S // 60 + 5,
                                        dono=dono):
                        cx.commit()
                        continue                 # conta com outro dono: retomada depois
                    cx.commit()
                try:
                    _executar(agente_id, ex, janela, instancia)
                finally:
                    if conta:
                        # COM INSISTÊNCIA e pelo dono: um "database is locked" aqui
                        # deixava a conta recusando busca por 35 min depois de a
                        # coleta já ter terminado.
                        bmod.soltar_conta(instancia, conta, None, dono)
                feitas += 1
                break                            # uma por passada: LIMITE=1
        finally:
            atendente._vagas.release()
            atendente._pesado.release()
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
