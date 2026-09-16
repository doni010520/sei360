# -*- coding: utf-8 -*-
"""
Roda todas as suítes e resume. Um comando, uma resposta.

Cada suíte sobe o PRÓPRIO servidor, contra a PRÓPRIA cópia do banco, numa porta
que o sistema operacional escolhe. Nenhuma delas toca no banco de trabalho — isso
já não foi verdade, e o preço foi a procedência dos snapshots do sistema passar a
apontar para um arquivo temporário de teste.

    python rodar_testes.py            # tudo
    python rodar_testes.py rapido     # pula o teste de container (exige Docker)
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
SUITES = [
    ("testes.py", "login, fronteira, agente, expurgo"),
    ("teste_configuracao.py", "assistente de configuração e cofre"),
    ("teste_relatorios.py", "relatórios, navegação, IA e usuários"),
    ("teste_multiusuario.py", "várias pessoas ao mesmo tempo"),
    ("teste_deploy_novo.py", "primeiro deploy, do volume vazio"),
    ("teste_poco.py", "poço: reaproveitar sem vazar a visão de ninguém"),
    ("teste_busca.py", "busca avançada, instância e cofre por instalação"),
    ("teste_acompanhamento.py", "acompanhamento: lista por pessoa, fora da mesa"),
    ("teste_recebimento_coleta.py", "o que a coleta FAZ ao SEI, nao so o que le"),
    ("teste_coleta_servidor.py", "o motor do VPS: coleta e acompanhamento"),
    ("teste_busca_servidor.py", "busca no VPS: causa, nova tentativa, conta"),
    ("teste_diagnostico.py", "diário no volume e a rota /diag com token"),
    ("../agente/_teste_agente.py", "o laco do agente na estacao"),
    ("teste_acesso.py", "recuperação de senha e segundo fator por e-mail"),
]
CONTAINER = ("teste_container.py", "imagem Docker (exige Docker instalado)")

alvos = list(SUITES)
if "rapido" not in sys.argv and (BASE / CONTAINER[0]).exists():
    tem_docker = subprocess.run(["docker", "version"], capture_output=True,
                                shell=True).returncode == 0
    if tem_docker:
        alvos.append(CONTAINER)
    else:
        print("(Docker ausente — teste de imagem pulado)\n")

# ---------------------------------------------------------------------------
# O banco de trabalho é lacrado antes e conferido depois.
#
# Não é zelo abstrato: as suítes já escreveram nele, e o preço foi a procedência
# dos seis snapshots correntes passar a apontar para `sei360_3.json` — um
# temporário de teste — em vez da coleta real, além de dezenas de contas `t.*`
# residuais. O isolamento existe desde então; isto é o que impede de ele voltar
# a ser furado sem ninguém perceber, porque o sintoma é silencioso.
#
# Compara o CONTEÚDO, não a data: o SQLite mexe em mtime só de abrir para leitura
# em WAL, e assinar por data daria alarme falso a cada execução.
def _lacre():
    import hashlib
    fora = {}
    for extra in ("", "-wal", "-shm"):
        p = BASE / "_dados" / ("sei360.db" + extra)
        fora[p.name] = (hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                        if p.exists() else "(ausente)")
    return fora


def ler_saida(saida, returncode):
    """(estado, verificações, falhas) a partir do que a suíte imprimiu.

    TRÊS ESTADOS, não dois. A versão anterior tinha dois e fazia
    `total_falhas += max(0, n_falha)`: quando a suíte morria antes de imprimir o
    resumo, `n_falha` era -1, o `max` o transformava em ZERO, e a linha final —
    que é a que se lê — anunciava "0 falha(s)" sobre uma suíte que não chegou ao
    fim. Medido hoje: rodadas de 267, 340 e 602 verificações declarando sucesso.

    O total nunca mentiu sobre um número; mentiu sobre uma AUSÊNCIA. É o modo de
    falha que este projeto inteiro existe para não deixar passar, e ele estava no
    próprio verificador.
    """
    if "está em curso (pid" in saida:
        # Não rodou: outra execução da mesma suíte segurava a trava de
        # `ambiente_teste.isolar`. Não é falha do sistema, e não é sucesso.
        return "BLOQUEADA", 0, 0
    if "sem banco de trabalho para copiar" in saida:
        # Também não rodou, e por outro motivo: a suíte mede contra os dados de
        # uma coleta REAL (`isolar(copiar=True)`) e esta máquina não tem o banco
        # de trabalho. Quatro das doze suítes caem aqui numa máquina de
        # desenvolvimento — contá-las como falha punha quatro linhas vermelhas
        # que não são defeito ao lado das que são, que é como se ensina alguém a
        # ignorar o verificador.
        return "SEM DADOS", 0, 0
    m = re.search(r"(\d+) verificações OK, (\d+) falha", saida)
    if not m:
        return "FALHOU", 0, 1          # morreu antes do resumo — conta como falha
    n_ok, n_falha = int(m.group(1)), int(m.group(2))
    if n_falha or returncode != 0:
        return "FALHOU", n_ok, max(1, n_falha)
    return "ok", n_ok, 0


def conferir_contagem(silencioso=False):
    """A contagem do arnês, conferida pelo arnês. Devolve (ok, falhas).

    Roda SEMPRE, não só sob flag: verificador que só se confere quando alguém
    lembra de pedir é verificador que não se confere. São 5 casos e custam 0 ms.
    Sem isto, o defeito volta na primeira vez que alguém achar o -1 estranho e
    "simplificar" de volta para `max(0, n_falha)`.
    """
    casos = [
        ("suíte que passou", "12 verificações OK, 0 falha(s)", 0, ("ok", 12, 0)),
        ("suíte que reprovou", "10 verificações OK, 3 falha(s)", 1, ("FALHOU", 10, 3)),
        ("MORREU sem imprimir o resumo", "Traceback...\nZeroDivisionError", 1,
         ("FALHOU", 0, 1)),
        ("saiu != 0 dizendo 0 falhas", "5 verificações OK, 0 falha(s)", 1,
         ("FALHOU", 5, 1)),
        ("bloqueada por outra execução",
         "outra execução de teste_x está em curso (pid 42).", 1, ("BLOQUEADA", 0, 0)),
        ("sem o banco de trabalho para copiar",
         "teste_x: sem banco de trabalho para copiar (C:\\...\\sei360.db) — esta "
         "suíte mede contra os dados de uma coleta real.", 3, ("SEM DADOS", 0, 0)),
    ]
    mau = 0
    for nome, saida, rc, esperado in casos:
        viu = ler_saida(saida, rc)
        ok = viu == esperado
        mau += not ok
        if not ok or not silencioso:
            print(("  ok    " if ok else "  FALHA ") + nome
                  + ("" if ok else f"  -> {viu} != {esperado}"))
    return len(casos) - mau, mau


if __name__ == "__main__" and "--conferir-contagem" in sys.argv:
    _ok, _mau = conferir_contagem()
    print(f"\n{_ok} verificações OK, {_mau} falha(s)")
    sys.exit(1 if _mau else 0)


# A PRIMEIRA COISA CONFERIDA É O CONFERIDOR. Se `ler_saida` estiver errada, todo
# o resto do relatório é opinião.
_ok_c, _mau_c = conferir_contagem(silencioso=True)
if _mau_c:
    print(f"FALHOU    a CONTAGEM do próprio arnês está errada ({_mau_c} caso(s)) — "
          "o relatório abaixo não vale nada até isso ser consertado")

lacre_antes = _lacre()

total_ok, total_falhas, tempo_total = _ok_c, _mau_c, 0.0
# Suíte que NÃO RODOU não é suíte que passou. Contada à parte porque a ação é
# outra: falha manda ler o código, bloqueio manda esperar a outra execução.
nao_rodaram = []
detalhes = []
for arquivo, sobre in alvos:
    t0 = time.time()
    # PYTHONIOENCODING no FILHO. Sem ele o Python da suite escreve no cano com
    # o codepage do Windows e morre com UnicodeEncodeError no primeiro print
    # que tenha um caractere fora dele. A suite virava "0 verificacoes,
    # FALHOU" por causa de um sinal de aproximacao numa mensagem.
    r = subprocess.run([sys.executable, str(BASE / arquivo)], cwd=str(BASE),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    dt = time.time() - t0
    tempo_total += dt
    saida = (r.stdout or "") + (r.stderr or "")
    estado, n_ok, n_falha = ler_saida(saida, r.returncode)
    total_ok += n_ok
    if estado == "BLOQUEADA":
        nao_rodaram.append((arquivo, "outra execução desta suíte está em curso"))
    elif estado == "SEM DADOS":
        # AÇÃO DIFERENTE DA DO BLOQUEIO, e por isso o motivo vem escrito: bloqueio
        # manda esperar a outra execução; este manda rodar onde o banco de
        # trabalho existe (o servidor, ou uma cópia dele aqui).
        nao_rodaram.append((arquivo, "precisa do banco de trabalho, que não existe "
                                     "nesta máquina — rode onde ele está"))
    else:
        total_falhas += n_falha
    print(f"{estado:9} {arquivo:26} {n_ok:>4} verificações  {dt:>5.0f}s   {sobre}")
    if estado == "FALHOU":
        for l in saida.splitlines():
            if l.startswith("  FALHA") or "Traceback" in l or "Error" in l:
                print(f"          {l.strip()[:110]}")
        detalhes.append((arquivo, saida[-1500:]))

def _servidor_de_pe():
    """Há um servidor atendendo contra o banco de TRABALHO agora?

    Precisa existir porque ele também escreve nesse arquivo — `ultimo_uso_em` da
    sessão muda a cada requisição. Sem esta pergunta, usar o sistema no navegador
    enquanto a suíte roda produzia a acusação errada.
    """
    import os
    import socket
    porta = int(os.environ.get("PORT") or 8360)
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", porta)) == 0


lacre_depois = _lacre()
mexeram = [k for k in lacre_antes if lacre_antes[k] != lacre_depois.get(k)]
# O `-wal` e o `-shm` mudam com leitura concorrente e não provam escrita; o
# arquivo principal, não. Alarme só no que é conclusivo.
if "sei360.db" in mexeram:
    if _servidor_de_pe():
        # Não dá para separar as duas causas daqui, e escolher a mais dramática
        # seria mandar procurar no lugar errado. Alarme falso repetido é como um
        # verificador morre: as pessoas aprendem a ignorá-lo.
        print("INCONCLUSIVO  o banco de trabalho mudou, mas havia um servidor "
              "atendendo contra ele — pode ter sido uso normal do sistema.")
        print("              Para conferir de verdade: pare o servidor e rode de novo.")
    else:
        total_falhas += 1
        print("FALHOU  o banco de TRABALHO mudou durante os testes, e não havia "
              "servidor rodando — alguma suíte escreveu fora do isolamento "
              "(ver ambiente_teste.isolar)")

print("=" * 78)
print(f"{total_ok} verificações, {total_falhas} falha(s), {tempo_total:.0f}s"
      + (f", {len(nao_rodaram)} suíte(s) NÃO RODARAM" if nao_rodaram else ""))
for arquivo, porque in nao_rodaram:
    print(f"  NÃO RODOU  {arquivo} — {porque}")
if nao_rodaram:
    print("  Nenhuma conclusão sobre o que elas cobrem: rode de novo sozinho.")
print("banco de trabalho: intacto" if "sei360.db" not in mexeram else
      ("banco de trabalho: alterado (servidor no ar — inconclusivo)"
       if _servidor_de_pe() else "banco de trabalho: ALTERADO"))
if detalhes:
    print("\nsaída das suítes que falharam:")
    for arquivo, saida in detalhes:
        # o relatorio tambem tem de sobreviver a um console cp1252
        texto = f"\n--- {arquivo} ---\n{saida}"
        cod = sys.stdout.encoding or "utf-8"
        print(texto.encode(cod, "replace").decode(cod, "replace"))
# "Passou" só quando TODAS rodaram. Sair 0 com suíte bloqueada faria a próxima
# pessoa — ou o próximo agente — ler silêncio como aprovação.
sys.exit(1 if (total_falhas or nao_rodaram) else 0)
