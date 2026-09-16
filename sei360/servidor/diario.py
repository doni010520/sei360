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
import time
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
    # SÓ COM SEPARADOR DE VALOR (`:` ou `=`). A versão anterior apagava a palavra
    # seguinte a qualquer "senha" — e "Usuário ou senha inválida", que é a frase
    # que o SEI devolve e o motivo inteiro de guardar a saída do login, virava
    # "Usuário ou senha …". O diário escondia justamente o diagnóstico.
    (re.compile(r"((?:senha|password|pwd)\w*[\"']?\s*[:=]\s*[\"']?)[^\s\"'&,;]+", re.I), r"\1…"),
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


# --------------------------------------------------------- saída por execução
# A SAÍDA INTEIRA DO COLETOR, uma por execução. Até 16/09/2026 ela era capturada
# por `subprocess.PIPE` e jogada fora: a coleta guardava os ÚLTIMOS 300
# caracteres em `execucao.log_resumo`, e o /admin mostrava 90. Numa senha
# recusada, esses 300 caracteres eram o banner do motor JS impresso ao recarregar
# a tela de login — e o que o SEI respondeu, a mesa que ficou incompleta e o total
# que a tela declarava ficavam só na memória de um processo que já tinha morrido.
# Ela não passa pelo `stdout` do servidor (é de um processo filho), então nem o
# log do Docker a tinha.
EXECUCOES = PASTA / "execucoes"
# Teto por arquivo. Uma coleta de 1.200 processos escreve na casa de centenas de
# KB; o teto existe para o dia em que um laço imprimir sem parar.
LIMITE_SAIDA = 1_500_000
# O ENVELOPE NÃO É LOG. `BUSCA_OK` e `ACOMP_OK` carregam o resultado — processos,
# especificações, o que a pessoa pesquisou — e isso tem dono e tela próprios. O
# arquivo guarda que o envelope veio e de que tamanho; o conteúdo, não.
_ENVELOPES = ("BUSCA_OK ", "ACOMP_OK ")


def _nome_limpo(texto):
    return "".join(c for c in str(texto) if c.isalnum() or c in "-_") or "x"


def arquivo_saida(tipo, ident):
    return EXECUCOES / f"{_nome_limpo(tipo)}-{_nome_limpo(ident)}.log"


def guardar_saida(tipo, ident, texto):
    """Grava a saída de uma execução do coletor, sem segredo e sem envelope.

    Devolve o nome do arquivo, ou None. NUNCA levanta: é chamada no `finally` de
    quem executa, e um log que derruba a execução que ele registra é pior que
    nenhum.
    """
    if not ligado() or not texto:
        return None
    try:
        linhas = []
        for linha in str(texto).splitlines():
            prefixo = next((p for p in _ENVELOPES if linha.startswith(p)), None)
            if prefixo:
                linha = f"{prefixo}<envelope omitido: {len(linha)} caracteres>"
            linhas.append(_sem_segredo(linha)[:LIMITE_LINHA])
        corpo = "\n".join(linhas)
        if len(corpo) > LIMITE_SAIDA:
            # O COMEÇO E O FIM. O começo diz em que instalação e com que login; o
            # fim diz como terminou. O meio é o que se perde.
            corpo = (corpo[:LIMITE_SAIDA // 5] + "\n[… saída cortada no meio …]\n"
                     + corpo[-(LIMITE_SAIDA * 4 // 5):])
        p = arquivo_saida(tipo, ident)
        with _trava:
            EXECUCOES.mkdir(parents=True, exist_ok=True)
            p.write_text(corpo + "\n", encoding="utf-8", errors="replace")
        return p.name
    except Exception:                                          # noqa: BLE001
        return None


def ler_saida(tipo, ident):
    """O texto guardado de uma execução, ou None se não houver (ou expirou)."""
    try:
        p = arquivo_saida(tipo, ident)
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
    except OSError:
        return None


def limpar(dias=None, simular=False):
    """Apaga diário e saída de execução mais velhos que `DIAS`.

    Devolve (quantos, bytes). A saída de execução tem o MESMO prazo do diário:
    as duas servem para diagnosticar o que está acontecendo, e nenhuma para
    provar o que aconteceu meses atrás.
    """
    dias = DIAS if dias is None else dias
    hoje = datetime.now(TZ).date()
    corte = (hoje - timedelta(days=dias)).isoformat()
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
    # Saída de execução não tem data no nome (o nome é a execução); o relógio é
    # o do próprio arquivo.
    limite = time.time() - dias * 86400
    for p in EXECUCOES.glob("*.log") if EXECUCOES.exists() else []:
        try:
            st = p.stat()
            if st.st_mtime >= limite:
                continue
            tamanho += st.st_size
            if not simular:
                p.unlink()
            n += 1
        except OSError:
            continue
    return n, tamanho
