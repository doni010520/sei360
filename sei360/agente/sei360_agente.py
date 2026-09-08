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
import argparse, hashlib, hmac, json, os, socket, subprocess, sys, threading, time
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "agente.json"
TRAVA = BASE / "agente.lock"
COLETOR = Path(r"C:\Claude\sei_sistema\painel_sesab\coletor_sesab.py")
COLETAS = Path(r"C:\Claude\sei_sistema\painel_sesab\_coletas")
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
    proc = subprocess.Popen(
        [sys.executable, str(COLETOR), "--buscar"],
        cwd=str(COLETOR.parent), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    proc.stdin.write(json.dumps(pedido) + "\n")
    proc.stdin.flush()
    proc.stdin.close()
    envelope, linhas = None, []
    teto = tarefa.get("segundos_teto") or 600
    inicio = time.time()
    try:
        for linha in proc.stdout:
            linha = linha.rstrip()
            linhas.append(linha)
            if linha.startswith("BUSCA_OK "):
                envelope = json.loads(linha[len("BUSCA_OK "):])
            else:
                print("   ", linha)
            if time.time() - inicio > teto:
                raise TimeoutError
        proc.wait(timeout=max(1, teto - (time.time() - inicio)))
    except (TimeoutError, subprocess.TimeoutExpired):
        # O MESMO exit 5 sintético da coleta: `page.evaluate` não obedece o
        # timeout do Playwright, então quem mata é o relógio de parede.
        proc.kill()
        envelope = None
    if envelope is None:
        envelope = {"busca_id": bid, "itens": [], "total_declarado": None,
                    "motivo": f"a estação não devolveu resultado em {teto // 60} min"}
    s, r = chamar(cfg, f"/api/agente/busca/{bid}", envelope, timeout=120)
    print(f"  servidor respondeu {s}: {r.get('estado') or r.get('erro')}")
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
