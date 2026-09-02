# -*- coding: utf-8 -*-
"""
Isolamento de banco para as suítes.

POR QUE ISTO EXISTE
-------------------
Três das quatro suítes escreviam direto no banco de trabalho. O resultado foi
medido: os seis snapshots `corrente` do sistema ficaram com `arquivo` apontando
para `sei360_3.json` — um temporário criado e apagado por um teste — em vez do
`sei_sesab_2026-08-18.json` que a coleta de verdade produziu. A procedência do
dado que o painel mostra passou a ser um arquivo que não existe mais.

Além da procedência, as suítes deixavam para trás dezenas de contas `t.*`,
sessões e snapshots de teste no mesmo banco que a instalação usa.

A regra que este módulo impõe: **teste não escreve no banco de quem trabalha.**
Cada suíte roda contra uma CÓPIA, num diretório temporário que some no fim.

    from ambiente_teste import isolar
    isolar(__file__)      # antes de qualquer import de banco/app
"""
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ORIGEM = Path(__file__).resolve().parent / "_dados" / "sei360.db"


def _destrancar(funcao, caminho, _exc):
    """Apaga arquivo somente-leitura em vez de desistir dele.

    No Windows, `rmtree` não remove arquivo com o atributo de somente-leitura, e
    `ignore_errors=True` fazia pior que falhar: engolia o erro e deixava a sobra
    da execução anterior no lugar. A cópia seguinte então batia em
    PermissionError, ou — pior — a suíte rodava contra o banco velho achando que
    era novo. Tirar o atributo e tentar de novo resolve o caso e só o caso.
    """
    import os as _o
    try:
        _o.chmod(caminho, stat.S_IWRITE)
        funcao(caminho)
    except OSError:
        pass


def _pid_vivo(pid):
    """Este PID ainda existe? Sem matar nada, sem depender de psutil."""
    import ctypes
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError) as e:
            return isinstance(e, PermissionError)
    # 0x1000 = PROCESS_QUERY_LIMITED_INFORMATION
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    saida = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(saida))
    ctypes.windll.kernel32.CloseHandle(h)
    return saida.value == 259          # STILL_ACTIVE


# Trava mais velha que isto perdeu o dono: processo morto sem `atexit`, máquina
# reiniciada, ou PID reciclado. Uma suíte inteira leva menos de um minuto.
TRAVA_VELHA_S = 30 * 60


def _dono_da_trava(trava):
    """(pid, timestamp) de quem tomou a trava. (0, None) quando ilegível.

    Formato novo é "PID EPOCH"; o antigo era só o PID. Ler os dois evita que uma
    trava escrita pela versão anterior fique sem dono nem idade — e portanto
    imortal.
    """
    import time
    try:
        partes = trava.read_text().split()
    except OSError:
        return 0, None
    try:
        pid = int(partes[0]) if partes else 0
    except ValueError:
        return 0, None
    try:
        quando = int(partes[1]) if len(partes) > 1 else None
    except ValueError:
        quando = None
    if quando is None:
        # Sem hora escrita, vale a do arquivo — melhor que "idade desconhecida".
        try:
            quando = int(trava.stat().st_mtime)
        except OSError:
            quando = int(time.time())
    return pid, quando


def _travar(nome, destino):
    """Uma execução por suíte. Quem chega segundo é RECUSADO.

    POR QUE ISTO EXISTE, e por que não é preciosismo: o diretório de trabalho
    tem nome FIXO e `isolar()` começa apagando-o. Duas execuções ao mesmo tempo
    — a suíte rodando enquanto um segundo processo também a roda — e a segunda
    apaga o banco que a primeira tem aberto, no meio. Toda suíte cai, cada uma
    num ponto diferente, e o relatório mostra "0 verificações, FALHOU" para
    tudo: indistinguível de o sistema ter quebrado de verdade.

    Medido: cinco rodadas concorrentes deram 267, 340, 351, 453 e 744
    verificações, com 0 a 12 falhas, todas diferentes. Horas de investigação
    atrás de um defeito que não existia.

    Trava de execução MORTA é tomada — Ctrl+C no meio de uma suíte não pode
    trancar o diretório para sempre.
    """
    import atexit
    import time
    trava = Path(tempfile.gettempdir()) / f"sei360_teste_{nome}.lock"
    # TENTATIVAS CONTADAS. A versão anterior era `while True` com o `unlink`
    # dentro de um `except OSError: pass` — no Windows, arquivo ainda aberto por
    # outro processo dá PermissionError, e o laço repetia sem teto, sem espera e
    # sem mensagem. A suíte não começava, e não havia nada na tela dizendo isso.
    for tentativa in range(5):
        try:
            fd = os.open(str(trava), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            # PID **E** HORA. PID sozinho não basta: o sistema recicla número, e
            # um PID reusado por qualquer processo trancaria a suíte para sempre.
            # O "\n" no fim é o terminador do registro: quem lê no meio da
            # escrita precisa saber que está vendo uma escrita em curso, e não um
            # dono morto — senão rouba a trava de quem acabou de pegá-la.
            os.write(fd, f"{os.getpid()} {int(time.time())}\n".encode())
            os.close(fd)
            break
        except FileExistsError:
            # A MESMA JANELA da trava do atendente: entre o `O_EXCL` e a escrita
            # do PID o arquivo existe e está vazio. Quem lê isso como "sem dono"
            # rouba a trava de quem acabou de pegá-la — e as duas execuções
            # apagam o banco uma da outra, que é justamente o que esta trava
            # existe para impedir.
            # ESPERA POR QUEM ESTÁ ESCREVENDO — MAS SÓ NAS PRIMEIRAS VOLTAS.
            # O terminador distingue "escrita em curso" de "registro pronto";
            # sem esse limite, um arquivo deixado por uma versão anterior (ou por
            # um processo morto no meio da escrita) nunca teria o terminador, e a
            # trava viraria imortal — a suíte pararia de rodar mandando apagar um
            # arquivo à mão. Depois das duas primeiras voltas vale o critério de
            # sempre: dono vivo manda, dono morto ou trava velha cede.
            try:
                if not trava.read_text().endswith("\n") and tentativa < 2:
                    time.sleep(0.05)
                    continue
            except OSError:
                pass
            dono, quando = _dono_da_trava(trava)
            velha = quando and (time.time() - quando) > TRAVA_VELHA_S
            if dono and dono != os.getpid() and _pid_vivo(dono) and not velha:
                raise SystemExit(
                    f"outra execução de {nome} está em curso (pid {dono}).\n"
                    f"Duas ao mesmo tempo apagam o banco uma da outra: o "
                    f"diretório de trabalho tem nome fixo e é recriado no início.\n"
                    f"Espere a outra terminar — ou, se ela morreu, apague "
                    f"{trava}")
            # Dono morto, trava velha, ou somos nós: toma e segue.
            try:
                trava.unlink()
            except OSError as ex:
                if tentativa == 4:
                    raise SystemExit(
                        f"não consegui tomar a trava de {nome} ({type(ex).__name__}).\n"
                        f"Apague {trava} à mão e rode de novo.")
                time.sleep(0.2)
    else:
        raise SystemExit(f"não consegui travar {nome} em 5 tentativas — apague {trava}")
    atexit.register(lambda: trava.unlink(missing_ok=True))


def isolar(quem, copiar=True):
    """Aponta SEI360_DADOS para um diretório temporário.

    `copiar=True` leva uma cópia do banco atual — é o que permite às suítes
    contarem com os 1.165 processos reais sem tocar neles. `copiar=False` começa
    do zero, para quem testa instalação nova.

    Devolve o diretório. O chamador não precisa limpar: o diretório fica em
    TEMP, e a próxima execução o recria.
    """
    nome = Path(quem).stem
    destino = Path(tempfile.gettempdir()) / f"sei360_teste_{nome}"
    _travar(nome, destino)
    shutil.rmtree(destino, onerror=_destrancar)
    destino.mkdir(parents=True, exist_ok=True)
    if copiar and ORIGEM.exists():
        shutil.copy(ORIGEM, destino / "sei360.db")
        # O WAL guarda escritas que ainda não foram para o .db principal; sem
        # copiar, a cópia pode nascer sem as últimas transações.
        # O `-shm` NÃO SE COPIA. A documentação do SQLite é explícita: ele é
        # estado de memória compartilhada, específico da máquina e do momento, e
        # é recriado sozinho na primeira abertura. Copiar um `-shm` de outro
        # processo é oferecer ao SQLite uma versão do mundo que já não existe.
        # O `-wal`, sim: ele guarda escritas que ainda não foram para o `.db`.
        for extra in ("-wal",):
            p = ORIGEM.with_name(ORIGEM.name + extra)
            if p.exists():
                shutil.copy(p, destino / (ORIGEM.name + extra))
        # `shutil.copy` leva os bits de permissão junto — e no Windows isso
        # inclui o atributo SOMENTE-LEITURA. A cópia herdava o atributo e a suíte
        # morria com "attempt to write a readonly database", parecendo um teste
        # escrevendo no banco de trabalho quando era o contrário: o isolamento
        # tinha funcionado e a cópia é que nascia trancada. A cópia é o rascunho
        # da suíte; ela é gravável por definição, venha de onde vier.
        for arq in destino.iterdir():
            arq.chmod(arq.stat().st_mode | stat.S_IWRITE)
    os.environ["SEI360_DADOS"] = str(destino)
    # Se `banco` já tiver sido importado, o caminho está congelado no módulo —
    # e o teste escreveria no banco de trabalho achando que está isolado.
    if "banco" in sys.modules:
        raise SystemExit(
            f"{nome}: isolar() precisa vir ANTES de 'import banco'/'import app'.\n"
            f"       O caminho do banco é resolvido no import e não muda depois.")
    return destino


def servidor_isolado():
    """Diretório em uso, para a suíte poder dizer onde está escrevendo."""
    return os.environ.get("SEI360_DADOS", "(padrão do projeto)")


def porta_livre():
    """Uma porta que o sistema operacional garante estar livre AGORA.

    Porta fixa por suíte parecia organizado e criou um problema pior: um servidor
    pendurado de uma execução anterior continua escutando naquele número, e a
    execução seguinte conversa com o processo velho — que responde com o banco
    velho, ou não responde. Pedir ao sistema resolve na origem.
    """
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def subir_servidor(dados_dir, porta=None, chave_mestra=None, espera=40,
                   atendente=False):
    porta = porta or porta_livre()
    """Sobe um servidor SÓ para esta suíte, contra o banco isolado.

    Por que não usar o `test_client` do Flask e pronto: os defeitos que este
    sistema tem histórico de produzir são de COOKIE, REDIRECT e FRONTEIRA —
    coisas que só aparecem com socket, cookie jar e um cliente seguindo 302. O
    cliente de teste esconde exatamente essa classe.

    Por que não usar o servidor que já está rodando: ele escreve no banco de
    trabalho. Foi assim que a procedência dos snapshots correntes virou um
    arquivo temporário de teste.

    Devolve (base_url, parar). `parar()` encerra o processo.
    """
    import subprocess
    import time
    import urllib.error
    import urllib.request

    # O LAÇO DO ATENDENTE FICA DESLIGADO NO TESTE, salvo pedido explícito. Todo
    # servidor de teste importa `app.py` e, com isso, armaria o executor de busca
    # contra o banco ISOLADO da suíte: ele sondaria a fila a cada 3 s e poderia
    # reivindicar — e executar — buscas que a própria suíte acabou de criar,
    # mudando o estado por baixo das asserções. A falha apareceria como
    # intermitência, em lugares diferentes a cada rodada, parecendo defeito do
    # produto. Quem quer exercitar o laço liga com `atendente=True`.
    env = {**os.environ, "SEI360_DADOS": str(dados_dir), "PORT": str(porta),
           "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
           "SEI360_ATENDENTE": "1" if atendente else "0"}
    if chave_mestra:
        env["SEI360_CHAVE_MESTRA"] = chave_mestra
    # O log vai para ARQUIVO, nunca para PIPE. Com PIPE e ninguém lendo, o
    # buffer do sistema (64 KB) enche depois de algumas centenas de requisições
    # e o servidor TRAVA na própria escrita de log — a suíte fica pendurada sem
    # erro nenhum, que foi exatamente o que aconteceu aqui.
    log = Path(dados_dir) / "servidor.log"
    saida_log = open(log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve().parent / "app.py")],
        cwd=str(Path(__file__).resolve().parent), env=env,
        stdout=saida_log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(espera):
        if proc.poll() is not None:
            saida_log.flush()
            raise SystemExit("o servidor de teste morreu ao subir:\n"
                             + log.read_text(encoding="utf-8", errors="replace")[-900:])
        try:
            urllib.request.urlopen(base + "/saude", timeout=2).read()
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    else:
        proc.kill()
        raise SystemExit(f"servidor de teste não respondeu em {espera // 2}s")

    def parar():
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:                                     # noqa: BLE001
            pass
        try:
            saida_log.close()
        except Exception:                                     # noqa: BLE001
            pass

    return base, parar
