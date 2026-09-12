# -*- coding: utf-8 -*-
"""
Agente SEI360 — roda NA ESTACAO de quem tem a credencial do SEI.

POR QUE ESTE PROGRAMA EXISTE
----------------------------
O servidor precisa saber quando a coleta rodou e receber o resultado. Ele NAO
pode, para isso, guardar a senha do SEI: credencial de terceiro num servidor
exposto e o unico item que transforma "vazou a base" em "agiram no SEI em nome
de alguem". Entao a direcao e sempre esta: a estacao PERGUNTA se ha coleta
devida, executa localmente e EMPURRA o resultado.

Efeito colateral desejado: o servidor nunca abre conexao para a estacao. Ele nao
tem como mandar a estacao executar coisa nenhuma alem de "colete agora", e mesmo
isso passa pelo teto local abaixo.

    python sei360_agente.py vincular --codigo <codigo> --servidor https://...
    python sei360_agente.py rodar --atender    # plantao de busca (interativa)
    python sei360_agente.py rodar                 # o que o Task Scheduler chama
    python sei360_agente.py rodar --simular       # exercita o protocolo sem abrir o SEI
    python sei360_agente.py status
    python sei360_agente.py instalar-tarefa       # imprime o comando do schtasks
"""
import argparse, hashlib, hmac, json, os, queue, socket, subprocess, sys, threading, time
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "agente.json"
TRAVA = BASE / "agente.lock"


def _achar_coletor():
    """Onde esta o `coletor_sesab.py`. Relativo, nao absoluto fixo.

    O absoluto (`C:\\Claude\\sei_sistema\\painel_sesab\\...`) JA SOBREVIVEU a
    separacao deste repositorio da arvore antiga — o mesmo defeito que
    `montar_painel._achar_origem` documenta ter sofrido, e aqui ele custava mais:
    o arquivo de la e de 7 de setembro e nao tem uma mencao a "acompanhar", entao
    todo o lado da estacao deste modulo nunca rodaria. E, pior, um coletor que nao
    conhece a flag nao a recusava: caia no caminho da COLETA, logava, colhia uma
    mesa so e gravava por cima da coleta boa do dia.

    `painel_sesab/` e irma de `sei360/`, duas pastas acima deste arquivo. O
    caminho antigo fica como ULTIMO candidato, para a estacao que ainda nao
    moveu a arvore continuar funcionando — mas so depois do daqui, e o aperto de
    mao (`coletor_conhece`) e quem diz se aquele serve para o que se vai pedir.
    """
    aqui = Path(__file__).resolve().parent
    candidatos = (aqui.parent.parent / "painel_sesab" / "coletor_sesab.py",
                  Path(r"C:\Claude\sei_sistema\painel_sesab\coletor_sesab.py"))
    for c in candidatos:
        if c.exists():
            return c
    return candidatos[0]


COLETOR = _achar_coletor()
COLETAS = COLETOR.parent / "_coletas"
VERSAO = "1.0.0"
TZ = timezone(timedelta(hours=-3), "America/Bahia")

# ---------------------------------------------------------------------------
# TETO LOCAL. Estes numeros valem MESMO que o servidor peca outra coisa: sao o
# unico limite que sobrevive ao comprometimento do servidor. Quem manda na
# maquina que detem a credencial e a maquina, nao o servico remoto.
# ---------------------------------------------------------------------------
MAX_POR_DIA = 3
FAIXA_HORARIA = (5, 22)          # so executa entre 05h e 22h locais
TIMEOUT_COLETA_S = 30 * 60       # 2x a duracao medida (14m47s em 18/08)
HEARTBEAT_S = 60


def agora():
    return datetime.now(TZ).isoformat(timespec="seconds")


def cfg_ler():
    if not CONFIG.exists():
        sys.exit("agente não vinculado. Rode: sei360_agente.py vincular --codigo <código> --servidor <url>")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def cfg_gravar(d):
    CONFIG.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    # O token do agente vale acesso de publicacao no servidor. Nao e a senha do
    # SEI — mas tambem nao e para ficar legivel para todo perfil da maquina.
    if os.name == "nt":
        subprocess.run(["icacls", str(CONFIG), "/inheritance:r", "/grant:r",
                        f"{os.environ.get('USERNAME')}:F"],
                       capture_output=True, text=True)


def chamar(cfg, caminho, corpo=None, metodo=None, timeout=120):
    """Bearer + HMAC do corpo. O HMAC sobrevive a proxy que termina o TLS."""
    dados = json.dumps(corpo).encode() if corpo is not None else b""
    ts = agora()
    req = urllib.request.Request(
        cfg["servidor"].rstrip("/") + caminho,
        data=dados if corpo is not None else None, method=metodo,
        headers={"Authorization": "Bearer " + cfg["token"],
                 "X-SEI360-Ts": ts,
                 "X-SEI360-Assinatura": hmac.new(cfg["token"].encode(),
                                                 ts.encode() + b"." + dados,
                                                 hashlib.sha256).hexdigest(),
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        return 0, {"erro": f"servidor inalcançável: {e}"}


# ------------------------------------------------------------------ trava
class Trava:
    """Duas execucoes sobre o MESMO perfil do Chromium o corrompem: perfil e
    escritor unico. A trava e por arquivo com o PID dentro, para que uma trava
    orfã (queda de energia) possa ser identificada em vez de travar para sempre."""

    def __enter__(self):
        if TRAVA.exists():
            try:
                dono = json.loads(TRAVA.read_text(encoding="utf-8"))
                viva = _processo_vivo(dono.get("pid"))
            except (ValueError, OSError):
                dono, viva = {}, False
            if viva:
                sys.exit(f"já há uma execução em curso (pid {dono.get('pid')}, desde {dono.get('em')})")
            print(f"trava órfã do pid {dono.get('pid')} removida")
        TRAVA.write_text(json.dumps({"pid": os.getpid(), "em": agora()}), encoding="utf-8")
        return self

    def __exit__(self, *a):
        TRAVA.unlink(missing_ok=True)


def _processo_vivo(pid):
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0); return True
        except OSError:
            return False
    saida = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                           capture_output=True, text=True).stdout
    return str(pid) in saida


def historico_hoje():
    """Contador local de execucoes do dia. Fica no disco da estacao de proposito:
    se o servidor for comprometido e pedir coleta em looping, este numero e o que
    para a maquina — e ele nao esta la."""
    arq = BASE / "execucoes.json"
    hoje = datetime.now(TZ).date().isoformat()
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return arq, d, d.get(hoje, 0), hoje


def contabilizar():
    arq, d, n, hoje = historico_hoje()
    d[hoje] = n + 1
    d = {k: v for k, v in d.items() if k >= (datetime.now(TZ).date() - timedelta(days=14)).isoformat()}
    arq.write_text(json.dumps(d), encoding="utf-8")


# ------------------------------------------------------------------ comandos
def vincular(args):
    corpo = json.dumps({"codigo": args.codigo, "versao": VERSAO}).encode()
    req = urllib.request.Request(args.servidor.rstrip("/") + "/api/agente/enrolar",
                                 data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"vínculo recusado ({e.code}): {e.read().decode()[:200]}")
    cfg_gravar({"servidor": args.servidor.rstrip("/"), "token": d["token"],
                "agente_id": d["agente_id"], "estacao": d["nome_estacao"],
                "unidades": d.get("unidades", []), "vinculado_em": agora()})
    print(f"vinculado como {d['nome_estacao']} (agente {d['agente_id']})")
    print(f"unidades autorizadas: {', '.join(d.get('unidades') or []) or '(nenhuma)'}")
    print(f"config em {CONFIG}")


def status(args):
    cfg = cfg_ler()
    _, _, n, hoje = historico_hoje()
    print(f"estação   : {cfg['estacao']}  (agente {cfg['agente_id']})")
    print(f"servidor  : {cfg['servidor']}")
    print(f"execuções : {n} hoje ({hoje}), teto local {MAX_POR_DIA}")
    print(f"trava     : {'presente' if TRAVA.exists() else 'livre'}")
    s, d = chamar(cfg, "/api/agente/tarefa", metodo="GET")
    if s != 200:
        print(f"servidor  : ERRO {s} {d.get('erro','')}")
        return
    print(f"tarefa    : coletar={d.get('coletar')}  motivo={d.get('motivo')}")
    if d.get("versao_disponivel") and d["versao_disponivel"] != VERSAO:
        # Sem autoatualizacao: baixar e executar codigo que o servidor mandou
        # transformaria o servidor em canal de execucao remota na unica maquina
        # que tem a credencial. O agente AVISA; a troca e manual.
        print(f"AVISO     : servidor anuncia versão {d['versao_disponivel']}, esta é {VERSAO}")


# De quanto em quanto tempo o agente pergunta se há busca, em modo de plantão.
# 15 s é curto o bastante para a pessoa não achar que travou, e longo o bastante
# para 60 estações darem 4 requisições por minuto cada — o servidor é o nosso.
INTERVALO_ATENDIMENTO_S = 15
# Por quanto tempo o plantão dura antes de sair. Processo eterno iniciado por
# script é processo que ninguém lembra de parar; sair e ser reiniciado pelo
# agendador é o mesmo desenho do resto do agente.
ATENDIMENTO_MIN = 60


def atender(cfg, minutos=ATENDIMENTO_MIN):
    """Plantão de busca: pergunta a cada 15 s por N minutos, e sai.

    O agendador padrão roda a cada 30 min, o que serve para a coleta (diária,
    ninguém espera) e não para a busca (alguém está olhando a tela). Sem este
    modo, a pessoa clica e espera até meia hora para a estação PERGUNTAR se há
    algo a fazer.
    """
    fim = time.time() + minutos * 60
    print(f"plantão de busca por {minutos} min — perguntando a cada "
          f"{INTERVALO_ATENDIMENTO_S}s. Ctrl+C para sair.")
    feitas = 0
    try:
        while time.time() < fim:
            try:
                with Trava():
                    if buscar(cfg):
                        feitas += 1
                        continue          # havia uma; pergunta de novo já
            except SystemExit:
                # A trava é de outra execução (uma coleta, por exemplo). Não é
                # erro: é o plantão esperando a vez.
                pass
            time.sleep(INTERVALO_ATENDIMENTO_S)
    except KeyboardInterrupt:
        print("\nplantão encerrado")
    print(f"plantão terminou: {feitas} busca(s) atendida(s)")
    return 0


class ColetorNaoConhece(Exception):
    """O coletor desta estação não conhece o modo que se ia pedir a ele.

    NÃO É FALHA DA EXECUÇÃO: é falha de INSTALAÇÃO, e por isso tem tipo próprio.
    Quem chama decide o que dizer ao servidor — a busca tem onde carimbar um
    motivo, o acompanhamento não —, mas nenhum dos dois pode mandar trabalho.
    """


# O que cada coletor respondeu ao `--modos`, por caminho. Cache de PROCESSO: o
# agente roda de 30 em 30 min e sai; guardar em disco seria guardar a resposta de
# uma versão que pode ter sido trocada no meio.
_MODOS_DO_COLETOR = {}


def coletor_conhece(modo):
    """Pergunta ao coletor se ele conhece o modo. Devolve (bool, texto).

    O APERTO DE MÃO EXISTE PORQUE O SILÊNCIO ERA O CAMINHO CARO. Um coletor que
    não conhece a flag não a recusava: ele a IGNORAVA e caía no caminho da
    COLETA — login no SEI, uma mesa colhida, e o arquivo do dia sobrescrito por
    cima da coleta boa. Não havia erro nenhum a ver; havia uma coleta pior.
    Perguntar antes custa um arranque de Python (~0,2 s, uma vez por modo por
    execução) e é a diferença entre "não fiz" e "fiz outra coisa".

    Coletor que não responde `MODOS_OK` é coletor anterior a este contrato — o
    da árvore antiga, por exemplo. Ele NÃO passa: quem não sabe dizer o que
    conhece não recebe trabalho.
    """
    chave = str(COLETOR)
    if chave not in _MODOS_DO_COLETOR:
        try:
            p = subprocess.run([sys.executable, str(COLETOR), "--modos"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            linha = next((l for l in (p.stdout or "").splitlines()
                          if l.startswith("MODOS_OK ")), None)
            _MODOS_DO_COLETOR[chave] = (json.loads(linha[len("MODOS_OK "):])
                                        if linha else {})
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            _MODOS_DO_COLETOR[chave] = {"erro": f"{type(e).__name__}: {str(e)[:120]}"}
    d = _MODOS_DO_COLETOR[chave]
    if not d or "erro" in d:
        return False, (f"{COLETOR} não respondeu que modos conhece"
                       + (f" ({d['erro']})" if d.get("erro") else "")
                       + " — é anterior ao contrato de modos")
    if modo in (d.get("modos") or []):
        return True, f"{COLETOR} (versão {d.get('versao')})"
    return False, (f"{COLETOR} (versão {d.get('versao')}) não conhece {modo}; "
                   f"conhece {', '.join(d.get('modos') or []) or '(nada)'}")


def _rodar_coletor(pedido, modo, marca, teto, varios=False):
    """Roda o coletor num modo de UMA tacada e devolve o envelope, ou None.

    `varios=True` devolve a LISTA de envelopes, para quem imprime em pedaços — ver
    `acompanhar()`. Com `varios=False` (o padrão, e o que `buscar()` usa) vale o
    ÚLTIMO envelope lido, que é o comportamento que sempre valeu.

    ERA O CORPO DE `buscar()`, e saiu de lá quando `acompanhar()` passou a
    precisar do mesmo laço. A alternativa — copiar as trinta linhas — é o defeito
    que este projeto documenta em meia dúzia de lugares: duas cópias do mesmo
    laço divergem na primeira correção que alguém fizer só numa delas, e aqui o
    que divergiria é o teto de relógio, que é justamente a parte que existe
    porque algo já deu errado uma vez.

    O CONTRATO, que é o dos dois modos: uma linha de stdin com o pedido, o
    coletor responde com logs em stdout e UMA linha começada por `marca` com o
    envelope em JSON. O que não é a marca é ecoado, indentado — é o log da
    estação, e quem está de plantão no prompt precisa vê-lo.

    `None` significa "a estação não devolveu envelope nenhum": o coletor morreu,
    ou o relógio o matou, ANTES de imprimir uma linha de marca legível. O relógio
    disparar não basta para dar `None` — o que já chegou volta, porque cada pedaço
    é um envelope inteiro que já passou por `json.loads`. Quem chama decide o que
    isso significa para o módulo dele — aqui não se inventa resultado.

    E ANTES DE QUALQUER COISA, O APERTO DE MÃO: `ColetorNaoConhece` sai daqui sem
    um único byte ter sido escrito no coletor. Ver `coletor_conhece`.
    """
    conhece, quem = coletor_conhece(modo)
    if not conhece:
        raise ColetorNaoConhece(quem)
    proc = subprocess.Popen(
        [sys.executable, str(COLETOR), modo],
        cwd=str(COLETOR.parent), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    proc.stdin.write(json.dumps(pedido) + "\n")
    proc.stdin.flush()
    proc.stdin.close()
    envelopes = []
    inicio = time.time()
    # O RELÓGIO É NOSSO, E NÃO O DO FILHO. `for linha in proc.stdout` BLOQUEIA:
    # com o teto testado dentro do laço, ele só era avaliado quando uma linha
    # chegava, e filho que emudece nunca era morto. Medido em 11/09/2026: teto de
    # 2 s, filho calado, `_rodar_coletor` ainda rodando aos 30 s — e a linha só
    # voltou porque o falso acordou.
    #
    # ISSO NÃO CUSTAVA "o acompanhamento do dia". O bloco roda dentro de `with
    # Trava():`; enquanto a função não voltava, o `__exit__` não rodava, o
    # `agente.lock` ficava com PID VIVO e a batida seguinte do agendador morria na
    # trava de `buscar()` — que vem ANTES da coleta. TODA coleta futura parava,
    # até alguém reparar. Mover o bloco para depois da coleta deslocou o
    # incidente; o que o fecha é o laço ter relógio próprio.
    #
    # A leitura vai para uma THREAD e as linhas chegam por FILA: `get(timeout=…)`
    # acorda sozinho, então o teto é avaliado mesmo no silêncio absoluto. A thread
    # é daemon e morre com o `kill()` do filho — ela só existe para transformar
    # uma leitura bloqueante em algo que se possa esperar com prazo.
    fila = queue.Queue()

    def _bombear(saida, fila):
        try:
            for linha in saida:
                fila.put(linha)
        finally:
            fila.put(None)                       # EOF, explícito

    leitor = threading.Thread(target=_bombear, args=(proc.stdout, fila), daemon=True)
    leitor.start()
    try:
        while True:
            resta = teto - (time.time() - inicio)
            if resta <= 0:
                raise TimeoutError
            try:
                # 1 s de teto por espera: o que decide é `resta`, e o mínimo só
                # garante que a fila seja reconsultada com frequência sã.
                linha = fila.get(timeout=min(resta, 1.0))
            except queue.Empty:
                continue                         # nada chegou; volta a olhar o relógio
            if linha is None:
                break                            # o filho fechou a saída
            linha = linha.rstrip()
            if linha.startswith(marca):
                # LINHA DE MARCA ILEGÍVEL NÃO DERRUBA O CICLO. `JSONDecodeError`
                # é `ValueError`, o `except` abaixo só pega timeout, e a exceção
                # subia por `rodar()` — a coleta do dia nunca chegava a ser
                # pedida. E o gatilho é real: `stderr=subprocess.STDOUT` funde os
                # dois fluxos, `PYTHONUNBUFFERED=1` manda cada escrita direto ao
                # pipe, e escrita de dezenas de KB (um envelope de 100 leituras)
                # não é atômica — uma linha de stderr do Chromium caindo no meio
                # do envelope produz exatamente isto.
                #
                # Descartar é o certo: envelope pela metade não é envelope, e
                # `None` já significa "a estação não devolveu resultado", que é a
                # verdade. Quem chama trata isso, e o item continua pendente.
                #
                # DESCARTA A LINHA, NÃO A EXECUÇÃO: o `continue` implícito aqui é
                # o que faz o envelope em pedaços valer a pena — com uma linha
                # corrompida, as outras ainda chegam.
                try:
                    envelopes.append(json.loads(linha[len(marca):]))
                except ValueError:
                    print(f"     (linha {marca.strip()} ilegível — descartada, "
                          f"{len(linha)} bytes)")
            else:
                print("   ", linha)
        proc.wait(timeout=max(1, teto - (time.time() - inicio)))
    except (TimeoutError, subprocess.TimeoutExpired):
        # O MESMO exit 5 sintético da coleta: `page.evaluate` não obedece o
        # timeout do Playwright, então quem mata é o relógio de parede.
        #
        # O QUE JÁ CHEGOU FICA, e isto é a correção de um defeito medido: três
        # fatias boas chegavam, o teto estourava na linha seguinte, e as três
        # eram descartadas — 60 leituras perdidas por causa da 61ª.
        #
        # A justificativa antiga era "`json.loads` aceita um envelope de 20
        # leituras truncado em 3 se o corte cair num lugar legal". Ela não vale
        # PARA ESTAS: cada uma já passou por `json.loads` inteira, uma a uma, e
        # cada pedaço é um envelope completo e independente (mesma instalação, sua
        # fatia). O corte que a frase teme cai numa linha SÓ — e essa linha, sim,
        # é descartada, no `except ValueError` do laço acima, com aviso.
        #
        # O que se perde ao matar o filho é o que ele ainda ia imprimir. Isso já
        # está pendente no servidor, e volta no ciclo seguinte; jogar fora o que
        # chegou não o traz de volta, só o acompanha.
        proc.kill()
        if envelopes:
            print(f"     (teto de {teto}s: {len(envelopes)} pedaço(s) já haviam "
                  "chegado e vão junto)")
    if varios:
        return envelopes
    return envelopes[-1] if envelopes else None


def buscar(cfg):
    """Uma busca, se houver. Devolve True se rodou alguma.

    Vem ANTES da coleta no ciclo: alguém está olhando a tela. Uma coleta de 13
    minutos na frente de uma busca de 20 segundos transforma "pesquisar" em
    "pesquisar amanhã".
    """
    s, tarefa = chamar(cfg, "/api/agente/busca", metodo="GET")
    if s != 200 or not tarefa.get("buscar"):
        return False
    bid = tarefa["busca_id"]
    print(f"busca {bid}: {tarefa.get('instancia')} · mesa {tarefa.get('mesa')}")
    # O PERFIL vai junto do pedido: é ele que diz em qual instalação do SEI
    # entrar. Sem ele o coletor cairia na constante interna — a SESAB — e uma
    # busca na FESF logaria no SEI errado, falhando de um jeito que parece
    # senha inválida.
    pedido = {"busca": {k: tarefa.get(k) for k in
                        ("busca_id", "instancia", "mesa", "filtros", "campos",
                         "paginas_teto")},
              "perfil": tarefa.get("perfil") or {}}
    teto = tarefa.get("segundos_teto") or 600
    try:
        envelope = _rodar_coletor(pedido, "--buscar", "BUSCA_OK ", teto)
    except ColetorNaoConhece as e:
        # O MOTIVO CERTO, e não o do relógio. Alguém está olhando a tela: dizer
        # "não devolveu resultado em 10 min" quando a estação nem tentou manda a
        # pessoa esperar de novo por algo que nunca vai acontecer.
        print(f"  a estação não sabe buscar: {e}")
        envelope = {"busca_id": bid, "itens": [], "total_declarado": None,
                    "motivo": f"o coletor desta estação não conhece o modo de "
                              f"busca ({e})"}
    if envelope is None:
        envelope = {"busca_id": bid, "itens": [], "total_declarado": None,
                    "motivo": f"a estação não devolveu resultado em {teto // 60} min"}
    s, r = chamar(cfg, f"/api/agente/busca/{bid}", envelope, timeout=120)
    print(f"  servidor respondeu {s}: {r.get('estado') or r.get('erro')}")
    return True


def acompanhar(cfg):
    """Os processos acompanhados fora da carteira, se houver algum.

    VEM POR ÚLTIMO NO CICLO, atrás da coleta — e o porquê está em `rodar()`, que
    é quem decide a ordem. Em resumo: estar na frente não comprava latência
    nenhuma (quem marca o compasso é o agendador, de 30 em 30 min, e não existe
    plantão de acompanhamento) e arriscava a janela da coleta diária.

    O QUE DESCE é só o que a estação precisa para procurar no SEI: a instalação e
    os números. A nota que a pessoa escreveu fica no servidor — é texto de gente,
    pode citar nome, e a estação não tem o que fazer com ela (ver
    `acompanhamento.pendentes`). O perfil desce junto porque é ele que diz em
    qual instalação entrar; sem ele o coletor cairia na constante interna, a
    SESAB, e uma leitura da FESF entraria no SEI errado.
    """
    s, tarefa = chamar(cfg, "/api/agente/acompanhamento", metodo="GET")
    if s != 200:
        return False
    # O RECUO FICA DITO, mesmo quando não há trabalho — é o único lugar em que
    # alguém vê que um processo parou de ser tentado. Sem esta linha, falha
    # sistemática num processo é indistinguível de processo em dia: ele some da
    # fila e ninguém fica sabendo. "3x hoje" o separa de falha passageira, que
    # não aparece aqui porque o item volta à fila no ciclo seguinte.
    parados = tarefa.get("descansando") or []
    if parados:
        print("acompanhamento: " + ", ".join(
            f"{p.get('protocolo')} ({p.get('tentativas')}x sem leitura hoje)"
            for p in parados[:5])
            + (f" e mais {len(parados) - 5}" if len(parados) > 5 else "")
            + " — descansam até amanhã")
    if not tarefa.get("ler"):
        return False
    protocolos = tarefa.get("protocolos") or []
    print(f"acompanhamento: {len(protocolos)} processo(s) em {tarefa.get('instancia')}")
    pedido = {"acompanhamento": {k: tarefa.get(k)
                                 for k in ("instancia", "protocolos")},
              "perfil": tarefa.get("perfil") or {}}
    # 600 s é o MESMO teto da busca, e aqui ele é o de fora: a estação tem teto
    # próprio de 9 min dentro do `.js` justamente para responder antes deste. Se
    # este disparar, o processo é morto e não sobra envelope nenhum.
    #
    # `varios=True`: A ESTAÇÃO IMPRIME EM PEDAÇOS, e por causa do tamanho. Medido
    # em 11/09/2026, depois da ficha completa: uma leitura passou de 277 para 825
    # bytes, e 100 leituras de 27 KB para 81 KB — numa linha só de stdout, com
    # stderr fundido nela (`stderr=STDOUT`) e sem buffer. Escrita desse tamanho
    # não é atômica, e foi exatamente assim que a linha-marca corrompida virou um
    # crítico. Em pedaços de 20, uma linha corrompida custa 20 leituras em vez de
    # 100, e as outras chegam.
    #
    # ISSO REDUZ A JANELA, NÃO A FECHA, e não vou dizer que fecha: 16 KB por linha
    # continua acima de qualquer garantia de atomicidade de pipe, e no Windows não
    # há garantia documentada para tamanho nenhum. O que o corte compra é raio, e
    # o que fecha a repetição é o recuo por `tentativas` no servidor. Pedaço menor
    # compraria cada vez menos (a perda já fica pendente) e multiplicaria POSTs.
    try:
        envelopes = _rodar_coletor(pedido, "--acompanhar", "ACOMP_OK ", 600,
                                   varios=True)
    except ColetorNaoConhece as e:
        # NADA FOI PEDIDO AO COLETOR, e é isso que precisa ser dito aqui. Esta
        # rota não tem onde carimbar motivo (ver abaixo), então o único lugar em
        # que a estação defasada aparece é este prompt — e sem esta linha o
        # sintoma seria "o acompanhamento nunca anda", sem causa à vista.
        print(f"  o coletor desta estação não sabe acompanhar: {e}")
        print(f"  os {len(protocolos)} item(ns) continuam pendentes")
        return True
    if not envelopes:
        # ENVELOPE VAZIO NÃO É PUBLICADO. O servidor gravaria zero e nada mais —
        # não há, nesta rota, onde registrar "a estação tentou e falhou" (ao
        # contrário da busca, que tem uma linha própria para carimbar o motivo).
        # Uma ida à rede para afirmar o nada é pior que não ir: `lido_em` não é
        # tocado, os itens continuam pendentes, e a próxima volta tenta de novo.
        # Quem precisa saber disto agora é quem está no prompt da estação.
        print("  a estação não devolveu leitura nenhuma — "
              f"os {len(protocolos)} item(ns) continuam pendentes")
        return True
    # AS RECUSAS QUE VALEM PARA TODOS OS PEDAÇOS, e só elas, param o laço:
    #   409 — "a instalação do dono mudou entre o pedido e a resposta". A
    #         instalação declarada é a MESMA nos cinco pedaços: insistir seriam
    #         cinco recusas idênticas no log;
    #   401/403 — o token do agente não muda entre um pedaço e o seguinte.
    # Qualquer outra é passageira ATÉ PROVA EM CONTRÁRIO, e o `break` por
    # `s != 200` custava caro: medido, 500 na primeira fatia dava 1 POST tentado
    # de 5 e 80 leituras boas perdidas na mão do agente — leituras que custaram
    # seis requisições ao SEI cada uma. E `chamar()` devolve 0 para servidor
    # inalcançável E para timeout, então um soluço de rede no primeiro POST
    # descartava o resto da mesma forma. O teto natural do laço são os cinco
    # pedaços: não há como isto virar martelada.
    PARA_TUDO = (401, 403, 409)
    gravadas, ignoradas, recusados = 0, 0, []
    for i, envelope in enumerate(envelopes, 1):
        s, r = chamar(cfg, "/api/agente/acompanhamento", envelope, timeout=120)
        if s != 200:
            print(f"  servidor recusou o pedaço {i}/{len(envelopes)} ({s}): "
                  f"{r.get('erro')}")
            recusados.append(i)
            if s in PARA_TUDO:
                print("    (essa recusa vale para todos os pedaços — a "
                      "instalação ou a credencial não mudam no meio; parando)")
                break
            continue
        gravadas += r.get("gravadas") or 0
        ignoradas += r.get("ignoradas") or 0
    # O RELATO DA ESTAÇÃO VEM REPETIDO EM TODO PEDAÇO, e é aqui que ele volta a
    # ser um só. `falhas`, `motivo` e `pedidos` viajavam só no pedaço 0 — que é
    # tão perdível quanto os outros —, e com ele sumiam a lista de falhas, a causa
    # e o número de reconciliação de uma vez. A duplicação é o preço, e o preço se
    # paga aqui: deduplicar por protocolo é uma linha; recuperar o que se perdeu
    # com o pedaço 0 não é lugar nenhum.
    #
    # Os pedaços RECUSADOS entram nesta conta na mesma: o que a estação não
    # conseguiu ler é verdade sobre o SEI, e não sobre o POST que falhou.
    falhas, vistas = [], set()
    for envelope in envelopes:
        for f in envelope.get("falhas") or []:
            chave = (f or {}).get("protocolo")
            if chave in vistas:
                continue
            vistas.add(chave)
            falhas.append(f)
    motivos = []
    for envelope in envelopes:
        m = envelope.get("motivo")
        if m and m not in motivos:
            motivos.append(m)
    # QUANTOS PEDAÇOS A ESTAÇÃO DISSE QUE ERAM, e não quantos chegaram: "em 2
    # pedaços" era o número dos RECEBIDOS, e por isso nunca acusava perda nenhuma.
    declarados = max([e.get("pedacos") or 0 for e in envelopes] + [len(envelopes)])
    conta = f"{len(envelopes)} de {declarados} pedaços recebidos"
    if recusados:
        conta += f", {len(recusados)} recusado(s) pelo servidor"
    print(f"  servidor gravou {gravadas}, ignorou {ignoradas}"
          + (f" ({conta})" if declarados > 1 or recusados else ""))
    if falhas:
        # FALHA SEM ESTADO é item que continua pendente. Ela não vira linha no
        # banco de propósito (ver `acompanhar()` em `automacao_sei.js`), então o
        # único lugar onde ela aparece é aqui.
        print(f"  {len(falhas)} processo(s) não puderam ser lidos: "
              + "; ".join(f"{f.get('protocolo')}: {f.get('motivo')}"
                          for f in falhas[:5]))
    for m in motivos:                     # sessão caída, teto de tempo da estação
        print(f"  {m}")
    # A RECONCILIAÇÃO, e só quando ela NÃO fecha. `pedidos` é quantos números
    # desceram para a estação; leitura publicada mais falha relatada tem de dar
    # nisso. O que sobra é pedaço perdido entre a estação e aqui — a escrita não
    # atômica do pipe —, e sem esta linha essa perda era invisível: os itens
    # continuavam pendentes, voltavam no ciclo seguinte, e ninguém sabia por quê.
    # Em execução boa ela cala: linha diária que sempre diz "tudo certo" é a linha
    # que ninguém lê no dia em que ela muda.
    pedidos_estacao = next((e.get("pedidos") for e in envelopes
                            if e.get("pedidos")), None)
    recebidas = sum(len(e.get("leituras") or []) for e in envelopes)
    if pedidos_estacao:
        sem_noticia = pedidos_estacao - recebidas - len(falhas)
        if sem_noticia > 0 or len(envelopes) < declarados:
            print(f"  reconciliação: {pedidos_estacao} número(s) desceram, "
                  f"{recebidas} leitura(s) e {len(falhas)} falha(s) voltaram — "
                  f"{max(sem_noticia, 0)} sem notícia "
                  f"({declarados - len(envelopes)} pedaço(s) perdido(s) "
                  "entre a estação e aqui)")
    return True


def rodar(args):
    cfg = cfg_ler()
    if getattr(args, "atender", False):
        return atender(cfg, getattr(args, "minutos", ATENDIMENTO_MIN))
    hora = datetime.now(TZ).hour
    if not (FAIXA_HORARIA[0] <= hora < FAIXA_HORARIA[1]) and not args.ignorar_teto:
        print(f"fora da faixa horária local {FAIXA_HORARIA[0]}h-{FAIXA_HORARIA[1]}h — nada a fazer")
        return 0
    _, _, feitas, _ = historico_hoje()
    if feitas >= MAX_POR_DIA and not args.ignorar_teto:
        print(f"teto local de {MAX_POR_DIA} execuções/dia já atingido — recusando mesmo se o servidor pedir")
        return 0

    # A BUSCA VEM PRIMEIRO: é interativa, e quem pediu está esperando na tela.
    with Trava():
        if buscar(cfg):
            return 0

    code = coletar(cfg, args)

    # O ACOMPANHAMENTO VEM POR ÚLTIMO, E ISSO É O CONSERTO DE UM DEFEITO.
    #
    # Ele esteve na frente da coleta, pelo argumento que `buscar()` faz: lista
    # curta, alguém pode estar olhando. O argumento não se sustenta aqui, e a
    # medição desmontou: não existe plantão de acompanhamento (`atender()` só
    # chama `buscar`), a latência é de 0 a 30 min de qualquer jeito porque quem
    # marca o compasso é o agendador, e há trava de uma leitura por dia por item.
    # A posição na frente comprava ZERO latência e arriscava a janela da coleta.
    #
    # O QUE ELA ARRISCAVA, medido: o laço de `_rodar_coletor` só olhava o relógio
    # de parede quando chegava uma linha, então filho que emudece — um
    # `ctx.close()` pendurado depois de já ter impresso `ACOMP_OK`, por exemplo —
    # nunca era morto (teto de 2 s, filho calado, ainda rodando aos 30 s). Com o
    # acompanhamento na frente, isso deixava o agente esperando EOF com a Trava na
    # mão e a coleta diária jamais pedida; a batida seguinte do agendador via o
    # PID vivo e ia embora.
    #
    # E O CUSTO DISSO NÃO ERA "o acompanhamento do dia", como esta linha já disse:
    # a Trava ficava presa com PID VIVO, e a batida seguinte morria na trava de
    # `buscar()` — que roda ANTES da coleta. TODA coleta futura parava. Estar
    # atrás da coleta deslocava o incidente em vez de fechá-lo; quem o fecha é o
    # relógio próprio do laço (ver `_rodar_coletor`), e é por isso que agora dá
    # para dizer, sem mentir, que o pior caso aqui é o acompanhamento do dia se
    # perder — a coleta já foi, e a trava volta.
    #
    # `except Exception` de propósito, e não uma lista de tipos: o que este bloco
    # protege não é o acompanhamento, é o CÓDIGO DE SAÍDA da coleta que já rodou.
    # Qualquer exceção daqui que subisse trocaria "coleta ok" por traceback.
    #
    # A TRAVA É OUTRA, e de propósito: duas execuções sobre o mesmo perfil do
    # Chromium o corrompem, então cada etapa toma e devolve a trava em vez de
    # segurá-la pelo ciclo inteiro — é o que deixa um plantão de busca entrar
    # entre elas.
    with Trava():
        try:
            acompanhar(cfg)
        except Exception as e:                                    # noqa: BLE001
            print(f"acompanhamento falhou ({type(e).__name__}: {str(e)[:120]}) — "
                  "os itens continuam pendentes; a coleta acima não foi afetada")
    return code


def coletar(cfg, args):
    """A coleta do dia, se houver janela devida. Devolve o código de saída.

    SAIU DE `rodar()` para o acompanhamento poder rodar DEPOIS dela em todos os
    caminhos — inclusive nos dois que saem cedo ("servidor não respondeu" e "sem
    coleta devida"), que antes eram `return 0` no meio do ciclo.
    """
    s, tarefa = chamar(cfg, "/api/agente/tarefa", metodo="GET")
    if s != 200:
        print(f"servidor não respondeu ({s}): {tarefa.get('erro','')}")
        return 0                      # sem tarefa nao e falha: o agendador roda a cada 30 min
    if not tarefa.get("coletar"):
        print(f"sem coleta devida — {tarefa.get('motivo')}")
        return 0

    ex = tarefa["execucao_id"]
    print(f"tarefa {ex}: {tarefa.get('motivo')}")

    with Trava():
        contabilizar()
        chamar(cfg, "/api/agente/evento", {"execucao_id": ex, "tipo": "inicio", "versao": VERSAO})
        inicio = time.time()
        parar = threading.Event()

        def pulsar():
            # O heartbeat acompanha o PROCESSO DO COLETOR, nao o do agente: o
            # agente pode estar vivissimo com o filho pendurado, e monitorar o
            # pai seria monitorar o processo errado.
            while not parar.wait(HEARTBEAT_S):
                chamar(cfg, "/api/agente/evento",
                       {"execucao_id": ex, "tipo": "heartbeat",
                        "coletor_vivo": proc is not None and proc.poll() is None}, timeout=30)

        proc = None
        alertas, png = [], None
        if args.simular:
            print("  [simulação] pulando o Chromium; publicando a última coleta do disco")
            code = 0
        else:
            # O PLANO. Entre listar e detalhar, o coletor pergunta ao servidor
            # o que ja foi lido por outra pessoa ha pouco. O servidor responde por
            # PROCESSO — nunca com a data do bloco: o relogio e dele.
            # O PERFIL DA INSTALAÇÃO viaja com a tarefa de coleta, pelo MESMO
            # mecanismo que `buscar()` já usa: uma chave a mais na única linha de
            # stdin que o coletor lê (`CREDENCIAL["perfil"]`). Sem ele o coletor
            # cai na constante interna — a SESAB — e uma coleta da FESF entraria
            # no SEI errado, falhando de um jeito que parece senha inválida.
            #
            # `or {}` porque servidor ANTIGO não manda o campo: chave ausente tem
            # de continuar significando "o de sempre", e não parar a coleta.
            conexao = {"plano": {"servidor": cfg["servidor"], "token": cfg["token"],
                                 "execucao_id": ex,
                                 "parser_versao": tarefa.get("parser_versao", "")},
                       "instancia": tarefa.get("instancia"),
                       "perfil": tarefa.get("perfil") or {}}
            if tarefa.get("instancia"):
                print(f"  instalação: {tarefa['instancia']}")
            proc = subprocess.Popen(
                [sys.executable, str(COLETOR), "--mesas", "--plano"],
                cwd=str(COLETOR.parent), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
            # Uma linha, e fecha. Sem o close o coletor esperaria por mais stdin
            # e a coleta ficaria pendurada sem exit code — o modo de falha que o
            # exit 5 sintetico existe para cobrir.
            proc.stdin.write(json.dumps(conexao) + "\n")
            proc.stdin.flush()
            proc.stdin.close()
            threading.Thread(target=pulsar, daemon=True).start()
            linhas = []
            try:
                for linha in proc.stdout:
                    linhas.append(linha.rstrip())
                    print("   ", linha.rstrip())
                    if time.time() - inicio > TIMEOUT_COLETA_S:
                        raise TimeoutError
                proc.wait(timeout=max(1, TIMEOUT_COLETA_S - (time.time() - inicio)))
                code = proc.returncode
            except (TimeoutError, subprocess.TimeoutExpired):
                # EXIT 5 SINTETICO. page.evaluate nao obedece o timeout do
                # Playwright (medido: 887 s sob teto de 600 s). Sem matar por
                # relogio de parede, a coleta pendurada nao produz exit code
                # nenhum e a execucao ficaria "em curso" para sempre.
                proc.kill()
                code = 5
                alertas.append(f"coleta morta pelo relógio de parede após {TIMEOUT_COLETA_S//60} min")
                print(f"   TRAVADA: morta após {TIMEOUT_COLETA_S//60} min")
            parar.set()
            alertas += [l for l in linhas if "ATENCAO" in l or "AVISO" in l or "alerta" in l.lower()]
            png = next((p.name for p in sorted(COLETAS.glob("falha_*.png"),
                                               key=lambda x: x.stat().st_mtime, reverse=True)[:1]), None)

        duracao = int(time.time() - inicio)
        publicado = None
        if code <= 1:
            # O ARQUIVO É O DA INSTALAÇÃO DESTA TAREFA. O coletor nomeia por
            # instalação (`sei_sesab_`, `sei_fesf_`) desde 07/09/2026; publicar
            # "o mais novo de qualquer prefixo" mandaria a carteira da FESF para
            # uma execução da SESAB no dia em que as duas rodassem.
            _slug = (tarefa.get("instancia") or "SEI-SESAB").split("-")[-1].lower()
            arq = sorted([c for c in COLETAS.glob(f"sei_{_slug}_*.json") if ".anterior" not in c.name])
            if arq:
                dados = json.loads(arq[-1].read_text(encoding="utf-8"))
                # O horario da COLETA viaja junto. O servidor recebe o corpo num
                # arquivo temporario criado no instante da chamada; sem este
                # carimbo, uma coleta das 07:45 chegaria ao painel como "coletado
                # agora", e a tela mentiria sobre o proprio frescor.
                colhido = datetime.fromtimestamp(arq[-1].stat().st_mtime, TZ).isoformat(timespec="seconds")
                print(f"  publicando {len(dados)} registros de {arq[-1].name} (coletado {colhido})…")
                sp, rp = chamar(cfg, "/api/agente/resultado",
                                {"execucao_id": ex, "dados": dados, "coletado_em": colhido},
                                timeout=300)
                publicado = (sp, rp.get("erro") or "ok")
                print(f"  servidor respondeu {sp}: {rp.get('erro') or 'ingerido'}")
                if sp != 200:
                    alertas.append(f"publicação recusada pelo servidor ({sp})")
            else:
                code = 2
                alertas.append("nenhum arquivo de coleta encontrado para publicar")

        chamar(cfg, "/api/agente/evento",
               {"execucao_id": ex, "tipo": "fim", "exit_code": code, "duracao_s": duracao,
                "alertas": alertas, "png_falha": png, "versao": VERSAO,
                "log_resumo": f"duração {duracao}s, exit {code}"
                              + (f", publicação {publicado}" if publicado else "")})
        print(f"fim: exit {code} em {duracao}s")
        return code


def instalar_tarefa(args):
    """Imprime o comando. NAO executa: criar tarefa agendada em nome de alguem e
    ato que a pessoa tem de ver e autorizar, nao efeito colateral de um script."""
    cmd = (f'schtasks /Create /TN "SEI360_Agente" /SC MINUTE /MO 30 '
           f'/TR "\\"{sys.executable}\\" \\"{Path(__file__).resolve()}\\" rodar" '
           f'/ST 05:00 /RL LIMITED /F')
    print("Rode uma vez, no prompt do usuário que tem a credencial:\n")
    print("   " + cmd + "\n")
    print("A cada 30 min o agente PERGUNTA se há janela devida; quem decide é o servidor,")
    print()
    print("Para a BUSCA AVANÇADA, que é interativa, deixe também um plantão rodando")
    print("durante o expediente — sem ele a busca espera a próxima batida de 30 min:")
    print()
    print(f'   "{sys.executable}" "{Path(__file__).resolve()}" rodar --atender')
    print()
    print(f"e o teto local ({MAX_POR_DIA}/dia, {FAIXA_HORARIA[0]}h-{FAIXA_HORARIA[1]}h) vale mesmo se ele pedir mais.")


def main():
    p = argparse.ArgumentParser(description="Agente de coleta do SEI360")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vincular"); v.add_argument("--codigo", required=True)
    v.add_argument("--servidor", required=True); v.set_defaults(f=vincular)
    r = sub.add_parser("rodar"); r.add_argument("--simular", action="store_true")
    r.add_argument("--atender", action="store_true",
                   help="plantão de busca: pergunta a cada 15 s por 60 min e sai")
    r.add_argument("--minutos", type=int, default=ATENDIMENTO_MIN,
                   help="duração do plantão (com --atender)")
    r.add_argument("--ignorar-teto", action="store_true",
                   help="só para diagnóstico; o teto existe por segurança")
    r.set_defaults(f=rodar)
    s = sub.add_parser("status"); s.set_defaults(f=status)
    i = sub.add_parser("instalar-tarefa"); i.set_defaults(f=instalar_tarefa)
    args = p.parse_args()
    sys.exit(args.f(args) or 0)


if __name__ == "__main__":
    main()
