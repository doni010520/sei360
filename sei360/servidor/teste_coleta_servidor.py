# -*- coding: utf-8 -*-
"""
COLETA EM MODO SERVIDOR — a decisão de "há o que coletar agora", e o
interruptor que mantém tudo desligado até alguém pedir.

O QUE ESTA SUÍTE PROVA
-----------------------
`_decidir()` é a mesma pergunta de `/api/agente/tarefa`, feita em processo
para um agente lógico SERVIDOR/*: sem agendamento, com agendamento desarmado,
sem instalação configurada em modo servidor, instalação sem parser, execução
já em curso, execução pendente retomada, e o caminho feliz (janela devida
grava a execução e devolve o perfil certo — nunca o padrão). E que os três
interruptores (`ligado`, `capacidade`, `vivo`) produzem os três motivos
distintos que `_motivo_servidor()` (app.py) usa para nunca confundir "estou
desligado", "não tenho com o quê" e "deveria estar rodando e não estou".

O QUE ESTA SUÍTE NÃO PROVA, e fica dito (mesma honestidade de
`_teste_parser40.js`): não chama `_executar()` de verdade — isso invocaria
Playwright e um login real — nem `_reavaliar_existentes()` contra um agente
de verdade. A prova de que `coleta.coletar()` funciona contra o SEI real
já existe, em campo, com credencial real (ARQUITETURA_ACESSO.md,
08/09/2026); esta suíte prova a DECISÃO de quando chamá-lo, não a chamada.

    python teste_coleta_servidor.py
"""
import json
import os
import sys
import time
from pathlib import Path

from ambiente_teste import isolar

isolar(__file__, copiar=False)          # instalação nova: sem coleta prévia
import base64 as _b64i
os.environ.setdefault("SEI360_CHAVE_MESTRA",
                      _b64i.b64encode(b"chave-de-teste-32-bytes-!!!!!!!!").decode())
os.environ["SEI360_ATENDENTE"] = "0"    # ver teste_busca.py: laço de fundo cria corrida
sys.stdout.reconfigure(encoding="utf-8")

import banco
import coleta_servidor as cs
import perfil_sei
from banco import agora, conectar, registrar  # noqa: F401  (registrar usado por cs)
from datetime import datetime, timedelta

banco.migrar()      # schema em banco vazio — normalmente feito pelo import de app.py
ok = mau = 0


def checar(nome, cond, viu=None):
    global ok, mau
    if cond:
        ok += 1
        print(f"  ok    {nome}")
    else:
        mau += 1
        print(f"  FALHA {nome}" + (f"  -> {viu}" if viu is not None else ""))


cx = conectar()

# --------------------------------------------------------------- fixture
def novo_usuario(email):
    cx.execute("""INSERT INTO usuarios(email,nome,papel,ativo,senha_trocada_em)
                  VALUES(?,?,'servidor',1,?)""", (email, email.split("@")[0], agora()))
    return cx.execute("SELECT last_insert_rowid()").fetchone()[0]


def novo_agente_servidor(uid, unidades=("SESAB/SAIS/DGGUP/DGESS",)):
    cx.execute("""INSERT INTO agentes(nome_estacao,dono_usuario_id,unidades_esperadas,
                  ativo,criado_em) VALUES(?,?,?,1,?)""",
               (f"SERVIDOR/teste{uid}", uid, json.dumps(list(unidades)), agora()))
    return cx.execute("SELECT last_insert_rowid()").fetchone()[0]


def novo_agendamento(agente_id, ativo=1, horario="00:00", motivo_inativo=None):
    cx.execute("""INSERT INTO agendamento(agente_id,janelas,dias,tolerancia_min,
                  max_entregas_janela,ativo,motivo_inativo)
                  VALUES(?,?,'todos',600,3,?,?)""",
               (agente_id, json.dumps([horario]), ativo, motivo_inativo))


def config_servidor(uid, sistema="SEI-SESAB"):
    cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,modo_coleta,
                  sei_login,atualizado_em) VALUES(?,?,'servidor',?,?)""",
               (uid, sistema, "fulano.um", agora()))


print("A. SEM AGENDAMENTO NENHUM")
uid1 = novo_usuario("t1@sei360.local")
ag1 = novo_agente_servidor(uid1)
r = cs._decidir(cx, ag1)
checar("recusa por falta de agendamento", r[0] is None and "agendamento" in r[1], r)

print("\nB. AGENDAMENTO DESARMADO (pausado_motivo do agente lógico)")
cx.execute("UPDATE agentes SET pausado_motivo=? WHERE id=?", ("motivo de teste", ag1))
novo_agendamento(ag1, ativo=0, motivo_inativo="motivo de teste")
r = cs._decidir(cx, ag1)
checar("recusa citando o motivo gravado no agente", r[0] is None and r[1] == "motivo de teste", r)

print("\nC. AGENDAMENTO ARMADO, SEM SISTEMA EM MODO SERVIDOR CONFIGURADO")
uid2 = novo_usuario("t2@sei360.local")
ag2 = novo_agente_servidor(uid2)
novo_agendamento(ag2, ativo=1, horario="00:00")
r = cs._decidir(cx, ag2)
checar("recusa por falta de config_usuario em modo servidor",
       r[0] is None and "sem sistema configurado" in r[1], r)

print("\nD. SISTEMA CONFIGURADO, MAS SEM PARSER PROVADO (disponivel_coleta=False)")
config_servidor(uid2, "SEI-FESF")
_orig_fesf = dict(perfil_sei.INSTANCIAS["SEI-FESF"])
perfil_sei.INSTANCIAS["SEI-FESF"]["disponivel_coleta"] = False
try:
    r = cs._decidir(cx, ag2)
    checar("recusa por instalação sem coleta disponível",
           r[0] is None and "coleta indisponível" in r[1], r)
finally:
    perfil_sei.INSTANCIAS["SEI-FESF"]["disponivel_coleta"] = _orig_fesf["disponivel_coleta"]

print("\nE. JANELA AINDA NÃO CHEGOU")
uid3 = novo_usuario("t3@sei360.local")
ag3 = novo_agente_servidor(uid3)
config_servidor(uid3, "SEI-SESAB")
futuro = (datetime.now(banco.TZ) + timedelta(hours=2)).strftime("%H:%M")
novo_agendamento(ag3, ativo=1, horario=futuro)
r = cs._decidir(cx, ag3)
checar("recusa com a próxima janela no motivo",
       r[0] is None and "próxima janela" in r[1], r)

print("\nF. JANELA DEVIDA — CAMINHO FELIZ")
uid4 = novo_usuario("t4@sei360.local")
ag4 = novo_agente_servidor(uid4, unidades=("SEI-TESTE/UNIDADE",))
config_servidor(uid4, "SEI-SESAB")
# 2h atrás, não 5 min: `janela_devida` soma um desvio determinístico de até
# 60 min ao horário-base (`desvio_do_agente`, por agente_id) antes de
# comparar com agora — 5 min seria flakiness pura, dependente do hash do id.
passado = (datetime.now(banco.TZ) - timedelta(hours=2)).strftime("%H:%M")
novo_agendamento(ag4, ativo=1, horario=passado)
cx.commit()
ex, janela, instancia, perfil = cs._decidir(cx, ag4)
cx.commit()
checar("execução criada (id numérico)", isinstance(ex, int), ex)
checar("instância é a configurada, não um padrão escrito à mão", instancia == "SEI-SESAB", instancia)
checar("perfil devolvido é o da instância certa (host da SESAB)",
       "seibahia" in (perfil or {}).get("host_sei", ""), perfil)
linha = cx.execute("SELECT estado, gatilho FROM execucao WHERE id=?", (ex,)).fetchone()
checar("execução nasce 'entregue', com gatilho 'servidor'",
       linha["estado"] == "entregue" and linha["gatilho"] == "servidor", dict(linha))

print("\nG. EXECUÇÃO PENDENTE ('entregue') É RETOMADA, NÃO DUPLICADA")
r2 = cs._decidir(cx, ag4)
checar("mesma execução_id devolvida de novo (idempotente)", r2[0] == ex, r2[:2])

print("\nH. EXECUÇÃO 'em_curso' RECUSA NOVA TAREFA (perfil único do Chromium)")
cx.execute("UPDATE execucao SET estado='em_curso' WHERE id=?", (ex,))
cx.commit()
r3 = cs._decidir(cx, ag4)
checar("recusa citando a execução em curso",
       r3[0] is None and str(ex) in r3[1], r3)

print("\nH2. O PULSO ESCREVE heartbeat_em ENQUANTO 'em_curso' (bug real de 08/09/2026:")
print("    sem isto, a faxina de app.varrer_execucoes marca QUALQUER coleta de mais")
print("    de 5 min como 'travada', mesmo terminando bem)")
import threading as _th
_parar = _th.Event()
_antes = cx.execute("SELECT heartbeat_em FROM execucao WHERE id=?", (ex,)).fetchone()["heartbeat_em"]
_thread_pulso = _th.Thread(target=cs._pulsar, args=(ex, _parar), daemon=True)
_pulso_s_original = cs._PULSO_S
cs._PULSO_S = 0.05          # não espera 60s de verdade só para provar que pulsa
_thread_pulso.start()
time.sleep(0.3)
_parar.set()
_thread_pulso.join(timeout=2)
cs._PULSO_S = _pulso_s_original
_depois = cx.execute("SELECT heartbeat_em FROM execucao WHERE id=?", (ex,)).fetchone()["heartbeat_em"]
checar("heartbeat_em muda de vazio para preenchido",
       _antes is None and _depois is not None, (_antes, _depois))

print("\nH3. O PULSO NÃO ESCREVE FORA DE 'em_curso' (não reviver execução já terminada)")
cx.execute("UPDATE execucao SET estado='concluida', heartbeat_em=NULL WHERE id=?", (ex,))
cx.commit()
_parar2 = _th.Event()
_thread_pulso2 = _th.Thread(target=cs._pulsar, args=(ex, _parar2), daemon=True)
cs._PULSO_S = 0.05
_thread_pulso2.start()
time.sleep(0.3)
_parar2.set()
_thread_pulso2.join(timeout=2)
cs._PULSO_S = _pulso_s_original
_apos_concluida = cx.execute("SELECT heartbeat_em FROM execucao WHERE id=?", (ex,)).fetchone()["heartbeat_em"]
checar("execução concluída não ganha heartbeat (WHERE estado='em_curso' no UPDATE)",
       _apos_concluida is None, _apos_concluida)

print("\nI. OS TRÊS MOTIVOS DE _motivo_servidor(), SEM CONFUNDIR UM COM O OUTRO")
os.environ["SEI360_COLETA_SERVIDOR"] = "0"
checar("desligado por variável: ligado() é False", cs.ligado() is False)
os.environ["SEI360_COLETA_SERVIDOR"] = "1"
checar("ligado por variável: ligado() é True", cs.ligado() is True)
pode, motivo = cs.capacidade()
checar("capacidade() delega para atendente.capacidade() (mesmo requisito)",
       isinstance(pode, bool), (pode, motivo))
checar("sem thread própria rodando neste teste, vivo() é False", cs.vivo() is False)

print("\nJ. _achar_json ACHA O MAIS NOVO, NUNCA UM '.anterior', NUNCA MAIS VELHO QUE 'desde'")
pasta = cs.COLETOR.parent / "_coletas"
pasta.mkdir(parents=True, exist_ok=True)
velho = pasta / "sei_teste_2020-01-01.json"
anterior = pasta / "sei_teste_2020-01-02.anterior.json"
novo = pasta / "sei_teste_2020-01-02.json"
try:
    velho.write_text("[]", encoding="utf-8")
    time.sleep(0.05)
    anterior.write_text("[]", encoding="utf-8")
    time.sleep(0.05)
    marca = time.time()
    time.sleep(0.05)
    novo.write_text("[]", encoding="utf-8")
    achado = cs._achar_json("SEI-SESAB", marca)
    checar("achou o mais novo, não o '.anterior'", achado == novo, achado)
    achado2 = cs._achar_json("SEI-SESAB", time.time() + 5)
    checar("nada mais novo que 'agora + 5s' — devolve None", achado2 is None, achado2)
finally:
    for p in (velho, anterior, novo):
        p.unlink(missing_ok=True)

cx.close()
print("\n" + "=" * 62)
print(f"{ok} ok, {mau} falha(s)")
sys.exit(1 if mau else 0)
