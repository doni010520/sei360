# -*- coding: utf-8 -*-
"""
DIÁRIO DO SERVIDOR — o log que sobrevive ao console.

POR QUE ISTO EXISTE
-------------------
Tudo o que este sistema diz sobre si mesmo ia para o stdout: as linhas de
`atendente de busca:`, `coleta em modo servidor:`, `acompanhamento em modo
servidor:`, os avisos da ingestão e o log de acesso do gunicorn. Quem guarda
stdout é o Docker, e quem o lê é quem tem o painel do provedor na mão.

Isso tem dois preços, os dois pagos em 15/09/2026:

  * para saber por que a coleta não rodava em três dias úteis, foi preciso
    pedir a alguém que abrisse o painel e copiasse o log. O diagnóstico ficou
    esperando uma pessoa;
  * o log do Docker é volátil e sem recorte: um redeploy o corta, e não há como
    perguntar "o que este servidor disse hoje às 07:30".

Aqui o mesmo texto vai TAMBÉM para um arquivo por dia no volume — o mesmo
volume do banco, que é o que sobrevive a redeploy. Sem tirar nada do stdout: o
painel do provedor continua mostrando o que sempre mostrou.

O QUE ELE NÃO É
---------------
Não é auditoria. "Quem viu o quê" é o `log_acesso`, que é tabela, tem prazo e
sai no expurgo. Este arquivo é o diário da MÁQUINA: o que os laços decidiram e
por quê. Ele também tem prazo (`DIAS`), e o expurgo o aplica.

E NÃO CARREGA SEGREDO. Nada que passe por aqui pode ter senha, token, chave ou
`infra_hash` de sessão — `_sem_segredo` é a última linha de defesa, não a
primeira: quem imprime já não deve imprimir segredo.
"""
import os
import re
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from banco import DADOS_DIR, TZ

PASTA = DADOS_DIR / "log"
# Prazo do diário. Mais curto que o do `log_acesso` (180) de propósito: este
# arquivo existe para diagnosticar o que está acontecendo, não para provar o que
# aconteceu meses atrás.
DIAS = 14
# Teto por linha. Traceback inteiro cabe; despejo de HTML de página do SEI, não —
# e já houve print de página inteira num erro de parser.
LIMITE_LINHA = 4000

_trava = threading.Lock()
_instalado = False

_SEGREDOS = (
    (re.compile(r"(infra_hash=)[^&\s'\"]+", re.I), r"\1…"),
    (re.compile(r"((?:senha|password|pwd)\W{0,3})\S+", re.I), r"\1…"),
    (re.compile(r"((?:token|bearer|api[_-]?key|chave)\W{0,3})[A-Za-z0-9_\-\.=]{8,}", re.I), r"\1…"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"), "sk-…"),
)


def _sem_segredo(texto):
    for padrao, troca in _SEGREDOS:
        texto = padrao.sub(troca, texto)
    return texto


def arquivo(dia=None):
    dia = dia or datetime.now(TZ).date()
    return PASTA / f"sei360-{dia.isoformat()}.log"


def ligado():
    """O diário pode ser desligado — volume sem espaço, por exemplo."""
    return os.environ.get("SEI360_LOG_ARQUIVO", "1") not in ("0", "false", "nao", "não")


def escrever(texto):
    """Uma linha no diário de hoje. NUNCA levanta.

    Log que derruba o que ele deveria registrar é pior que log nenhum: este
    módulo é chamado de dentro dos laços de coleta e do `print` do processo.
    """
    if not ligado() or not texto:
        return False
    try:
        linha = _sem_segredo(str(texto).rstrip())[:LIMITE_LINHA]
        if not linha.strip():
            return False
        marca = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        with _trava:
            PASTA.mkdir(parents=True, exist_ok=True)
            with open(arquivo(), "a", encoding="utf-8", errors="replace") as f:
                f.write(f"{marca} [{os.getpid()}] {linha}\n")
        return True
    except Exception:                                          # noqa: BLE001
        return False


class _Eco:
    """Escreve no stream original E no diário. Só isso.

    Por que envolver o `sys.stdout` em vez de trocar os `print` por uma função:
    os `print` são dezenas, em seis módulos, e cada um que ficasse para trás
    seria uma linha que o diário não tem — justamente no dia em que ela importa.
    Envolver pega todos, inclusive os de biblioteca.
    """

    def __init__(self, original):
        self.original = original
        self._resto = ""

    def write(self, texto):
        try:
            self.original.write(texto)
        except Exception:                                      # noqa: BLE001
            pass
        try:
            self._resto += texto
            while "\n" in self._resto:
                linha, self._resto = self._resto.split("\n", 1)
                escrever(linha)
            if len(self._resto) > LIMITE_LINHA:                # linha sem fim
                escrever(self._resto)
                self._resto = ""
        except Exception:                                      # noqa: BLE001
            self._resto = ""
        return len(texto)

    def flush(self):
        try:
            self.original.flush()
        except Exception:                                      # noqa: BLE001
            pass

    def isatty(self):
        try:
            return self.original.isatty()
        except Exception:                                      # noqa: BLE001
            return False

    def __getattr__(self, nome):
        return getattr(self.original, nome)


def instalar():
    """Passa `stdout` e `stderr` a ecoar no diário. Idempotente."""
    global _instalado
    if _instalado or not ligado():
        return False
    sys.stdout = _Eco(sys.stdout)
    sys.stderr = _Eco(sys.stderr)
    _instalado = True
    escrever(f"diário do servidor ligado em {PASTA}")
    return True


def ler(linhas=200, dias=2):
    """As últimas `linhas` do diário, do dia de hoje para trás.

    É o que a rota de diagnóstico devolve. Em ordem cronológica, como um log se
    lê — não invertida.
    """
    fora = []
    hoje = datetime.now(TZ).date()
    for i in range(max(1, dias)):
        p = arquivo(hoje - timedelta(days=i))
        if not p.exists():
            continue
        try:
            fora = p.read_text(encoding="utf-8", errors="replace").splitlines() + fora
        except OSError:
            continue
        if len(fora) >= linhas:
            break
    return fora[-linhas:]


def arquivos():
    """Os arquivos do diário, do mais novo para o mais velho, com tamanho."""
    if not PASTA.exists():
        return []
    fora = []
    for p in sorted(PASTA.glob("sei360-*.log"), reverse=True):
        try:
            fora.append({"arquivo": p.name, "bytes": p.stat().st_size})
        except OSError:
            continue
    return fora


def limpar(dias=None, simular=False):
    """Apaga diário mais velho que `DIAS`. Devolve (quantos, bytes)."""
    dias = DIAS if dias is None else dias
    corte = (datetime.now(TZ).date() - timedelta(days=dias)).isoformat()
    n = tamanho = 0
    for p in PASTA.glob("sei360-*.log") if PASTA.exists() else []:
        dia = p.stem.replace("sei360-", "")
        if dia >= corte:
            continue
        try:
            tamanho += p.stat().st_size
            if not simular:
                p.unlink()
            n += 1
        except OSError:
            continue
    return n, tamanho
