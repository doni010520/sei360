# -*- coding: utf-8 -*-
"""
Por que a coleta do servidor não roda? Diagnóstico SÓ DE LEITURA, para rodar no
console do container (EasyPanel → serviço → Console):

    python diagnostico_coleta.py

Não escreve no banco (abre em modo leitura), não abre o cofre, não fala com o SEI
e não imprime senha nem chave. A única ação além de ler é um teste de 1 ms na
trava da eleição do executor, solto na hora — é a única forma de saber, de fora de
um worker, se existe executor vivo no container.

A coleta do servidor só acontece se TODOS os elos abaixo estiverem de pé, nesta
ordem. O diagnóstico percorre os elos e aponta o primeiro que quebrou.
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

DADOS = os.environ.get("SEI360_DADOS", "/dados")
BANCO = os.path.join(DADOS, "sei360.db")
causas = []


def titulo(t):
    print(f"\n{t}\n" + "-" * len(t))


def q(cx, sql, args=()):
    try:
        return cx.execute(sql, args).fetchall()
    except sqlite3.Error as ex:
        print(f"   (consulta indisponível nesta versão do banco: {ex})")
        return []


titulo("1. INTERRUPTORES do container")
col = os.environ.get("SEI360_COLETA_SERVIDOR", "(não definida → 0)")
ate = os.environ.get("SEI360_ATENDENTE", "(não definida → 1)")
print(f"   SEI360_COLETA_SERVIDOR = {col}")
print(f"   SEI360_ATENDENTE       = {ate}")
print(f"   SEI360_CHAVE_MESTRA    = {'definida' if os.environ.get('SEI360_CHAVE_MESTRA') else 'NÃO DEFINIDA'}")
if os.environ.get("SEI360_COLETA_SERVIDOR", "0") not in ("1", "true", "sim"):
    causas.append("SEI360_COLETA_SERVIDOR não está ligado: o laço de coleta do servidor "
                  "nem sobe (nasce desligado por decisão registrada). Ligue com =1 e reinicie.")
if os.environ.get("SEI360_ATENDENTE", "1") in ("0", "nao", "não", "off"):
    causas.append("SEI360_ATENDENTE=0: sem executor de busca, e a coleta do servidor pega "
                  "carona nele — não sobe.")
if not os.environ.get("SEI360_CHAVE_MESTRA"):
    causas.append("SEI360_CHAVE_MESTRA ausente: o cofre não abre, a capacidade do executor "
                  "é negada e nenhuma senha do SEI pode ser usada.")

titulo("2. EXECUTOR — a trava da eleição")
trava = os.path.join(DADOS, ".atendente.lock")
if not os.path.exists(trava):
    print(f"   {trava} não existe: nenhum worker chegou a disputar a vez.")
    causas.append("Nenhum worker disputou a eleição do executor (arquivo de trava ausente): "
                  "o atendente não subiu — veja no log 'atendente de busca não subiu'.")
else:
    try:
        conteudo = open(trava, encoding="utf-8", errors="replace").read().strip()
    except OSError:
        conteudo = "?"
    pid = int(conteudo) if conteudo.isdigit() else None
    vivo_pid = False
    if pid:
        try:
            os.kill(pid, 0)
            vivo_pid = True
        except (ProcessLookupError, PermissionError) as ex:
            vivo_pid = isinstance(ex, PermissionError)
    segura = None
    try:
        import fcntl
        fd = os.open(trava, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            segura = False
        except OSError:
            segura = True
        finally:
            os.close(fd)
    except (ImportError, OSError) as ex:
        print(f"   (teste da trava indisponível: {type(ex).__name__})")
    print(f"   último PID que tomou a vez: {pid or '?'} · processo vivo: {vivo_pid}")
    print(f"   trava segurada por alguém agora: {segura}")
    if segura is False:
        causas.append("NINGUÉM segura a trava da eleição: não há executor vivo no container. "
                      "Na versão sem reeleição, os workers que perderam a vez na subida (por "
                      "exemplo, durante um redeploy com o container antigo de pé) nunca tentam "
                      "de novo — sem executor não há busca, coleta nem acompanhamento. "
                      "Reiniciar o serviço resolve na hora; a versão com reeleição resolve de vez.")

if not os.path.exists(BANCO):
    print(f"\nbanco não encontrado em {BANCO}")
    sys.exit(1)
cx = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True)
cx.row_factory = sqlite3.Row

titulo("3. AGENTES LÓGICOS do servidor (SERVIDOR/*) e agendamento")
agentes = q(cx, """SELECT a.id, a.nome_estacao, a.pausado_motivo, u.email,
                          g.ativo AS ag_ativo, g.janelas, g.dias, g.motivo_inativo
                   FROM agentes a
                   LEFT JOIN usuarios u ON u.id = a.dono_usuario_id
                   LEFT JOIN agendamento g ON g.agente_id = a.id
                   WHERE a.nome_estacao LIKE 'SERVIDOR/%'""")
if not agentes:
    causas.append("Não existe agente SERVIDOR/*: ninguém configurou modo servidor pela tela "
                  "(ou o agente continua com nome de estação — pareamento antigo).")
for a in agentes:
    print(f"   #{a['id']} {a['nome_estacao']} · dono {a['email']} · agendamento "
          f"{'ATIVO' if a['ag_ativo'] else 'INATIVO'} {a['janelas']} {a['dias']}")
    if a["pausado_motivo"]:
        print(f"      PAUSADO: {a['pausado_motivo']}")
        causas.append(f"Agente {a['nome_estacao']} pausado: {a['pausado_motivo']}")
    elif not a["ag_ativo"]:
        causas.append(f"Agendamento do {a['nome_estacao']} inativo: {a['motivo_inativo']}")
estacoes = q(cx, """SELECT a.nome_estacao, u.email, a.ultimo_contato_em FROM agentes a
                    LEFT JOIN usuarios u ON u.id = a.dono_usuario_id
                    WHERE a.nome_estacao NOT LIKE 'SERVIDOR/%'""")
for e in estacoes:
    print(f"   estação {e['nome_estacao']} · dono {e['email']} · último contato {e['ultimo_contato_em']}")

titulo("4. CONFIGURAÇÃO e senha guardada, por conta")
for c in q(cx, """SELECT u.email, c.sistema, c.modo_coleta,
                         (SELECT COUNT(*) FROM credencial k
                           WHERE k.usuario_id = c.usuario_id AND k.sistema = c.sistema) AS tem_senha
                  FROM config_usuario c JOIN usuarios u ON u.id = c.usuario_id
                  ORDER BY u.email"""):
    print(f"   {c['email']} · {c['sistema']} · modo {c['modo_coleta']} · "
          f"senha no cofre: {'sim' if c['tem_senha'] else 'NÃO'}")
    if c["modo_coleta"] == "servidor" and not c["tem_senha"]:
        causas.append(f"{c['email']} está em modo servidor em {c['sistema']} sem senha no cofre.")

titulo("5. ÚLTIMAS EXECUÇÕES de coleta")
sete = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
for r in q(cx, """SELECT e.id, a.nome_estacao, e.janela, e.estado, e.gatilho, e.entregue_em,
                         e.terminado_em, e.exit_code, e.log_resumo
                  FROM execucao e JOIN agentes a ON a.id = e.agente_id
                  ORDER BY e.id DESC LIMIT 12"""):
    print(f"   #{r['id']} {r['nome_estacao']} · janela {str(r['janela'])[:16]} · {r['estado']} · "
          f"{r['gatilho']} · código {r['exit_code']}")
    if r["log_resumo"]:
        print(f"      {str(r['log_resumo'])[-200:]}")
presas = q(cx, "SELECT COUNT(*) FROM execucao WHERE estado IN ('entregue','em_curso')")
if presas and presas[0][0]:
    causas.append(f"{presas[0][0]} execução(ões) presas em entregue/em_curso — retomada que "
                  "ninguém executa (ver também a janela extra do admin na versão antiga).")

titulo("6. ÚLTIMA COLETA publicada, por unidade")
for r in q(cx, """SELECT unidade, MAX(coletado_em) AS ultima FROM snapshot
                  WHERE estado = 'corrente' GROUP BY unidade ORDER BY ultima"""):
    print(f"   {r['ultima']} · {r['unidade']}")

titulo("7. ALERTAS dos últimos 7 dias")
for r in q(cx, """SELECT ts, tipo, severidade, texto FROM alerta WHERE ts >= ?
                  ORDER BY ts DESC LIMIT 15""", (sete,)):
    print(f"   {str(r['ts'])[:16]} · {r['severidade']} · {r['tipo']} · {str(r['texto'])[:160]}")

titulo("8. BUSCAS dos últimos 3 dias (o mesmo executor)")
tres = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
for r in q(cx, """SELECT estado, motivo, COUNT(*) AS n FROM busca WHERE pedida_em >= ?
                  GROUP BY estado, motivo ORDER BY n DESC LIMIT 10""", (tres,)):
    print(f"   {r['n']}× {r['estado']} · {str(r['motivo'] or '')[:140]}")

titulo("VEREDITO — primeiro elo quebrado primeiro")
if not causas:
    print("   Nenhum elo quebrado visível daqui. Confira o log do serviço pelas linhas "
          "'atendente de busca:' e 'coleta em modo servidor:' da última subida.")
for i, c in enumerate(causas, 1):
    print(f"   {i}. {c}")
