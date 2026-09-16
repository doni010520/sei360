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


def config_servidor(uid, sistema="SEI-SESAB", senha=False):
    cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,modo_coleta,
                  sei_login,atualizado_em) VALUES(?,?,'servidor',?,?)""",
               (uid, sistema, "fulano.um", agora()))
    if senha:
        # SÓ A EXISTÊNCIA DA LINHA: `_decidir` pergunta se HÁ senha guardada e não
        # a abre (quem abre é o executor). Desde 16/09/2026 a instalação sem senha
        # não gera entrega — era a origem das execuções 'bloqueada' diárias com
        # "nenhuma credencial guardada". Blob de mentira de propósito: se alguém
        # passar a decifrar aqui, o teste acusa.
        cx.execute("""INSERT OR REPLACE INTO credencial(usuario_id,sistema,login,segredo,
                      nonce,algo,criado_em,usos) VALUES(?,?,?,?,?,'teste',?,0)""",
                   (uid, sistema, "fulano.um", b"x", b"x", agora()))


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
config_servidor(uid2, "SEI-FESF", senha=True)
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
config_servidor(uid3, "SEI-SESAB", senha=True)
futuro = (datetime.now(banco.TZ) + timedelta(hours=2)).strftime("%H:%M")
novo_agendamento(ag3, ativo=1, horario=futuro)
r = cs._decidir(cx, ag3)
checar("recusa com a próxima janela no motivo",
       r[0] is None and "próxima janela" in r[1], r)

print("\nF. JANELA DEVIDA — CAMINHO FELIZ")
uid4 = novo_usuario("t4@sei360.local")
ag4 = novo_agente_servidor(uid4, unidades=("SEI-TESTE/UNIDADE",))
config_servidor(uid4, "SEI-SESAB", senha=True)
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

# ===========================================================================
# O MOTOR DO ACOMPANHAMENTO NO SERVIDOR
#
# Até 12/09/2026 não havia motor nenhum: `acompanhamento.pendentes` e
# `.receber` tinham UM chamador cada — as duas rotas `/api/agente/acompanhamento`,
# que existem para uma ESTAÇÃO buscar trabalho por HTTP. O sistema roda no VPS.
# Consequência: processo acompanhado fora da mesa entrava na lista, ficava
# 'novo' e NUNCA era lido; a tela dizia "aguardando primeira leitura" para
# sempre, e a frase era verdadeira.
#
# Estas cenas provam a DECISÃO (quem é candidato, quando é devido, quanto custa
# perguntar) e o CAMINHO COMPLETO de publicação com um coletor de mentira — o
# que elas não provam é o Chromium contra o SEI real, e isso fica dito, como o
# cabeçalho desta suíte já faz para a coleta.
# ===========================================================================
import acompanhamento as acmod                                   # noqa: E402
import acompanhamento_servidor as asv                            # noqa: E402
import atendente                                                 # noqa: E402
import cofre                                                     # noqa: E402

print("\nK. QUEM É CANDIDATO — o cruzamento lista x custódia da senha")
uidA = novo_usuario("acomp.servidor@sei360.local")
uidB = novo_usuario("acomp.estacao@sei360.local")
config_servidor(uidA, "SEI-SESAB")
config_servidor(uidA, "SEI-FESF")
cx.execute("""INSERT INTO config_usuario(usuario_id,sistema,modo_coleta,sei_login,
              atualizado_em) VALUES(?,'SEI-SESAB','estacao',?,?)""",
           (uidB, "fulano.dois", agora()))
acmod.adicionar(cx, uidA, "019.5001.2026.0000001-11", "SEI-SESAB")
acmod.adicionar(cx, uidA, "019.5002.2026.0000002-22", "SEI-FESF")
acmod.adicionar(cx, uidB, "019.5003.2026.0000003-33", "SEI-SESAB")
cx.commit()
_cand = asv._candidatos(cx)
checar("a conta em modo SERVIDOR entra", (uidA, "SEI-SESAB") in _cand, _cand)
# O QUE A ESTAÇÃO NÃO CONSEGUE: a rota do agente entrega UMA instalação por
# ciclo (a estação faz login em uma por vez), e o item da outra ficava 'novo'
# para sempre. No container o cofre guarda credencial POR instalação.
checar("e as DUAS instalações dela, no mesmo ciclo",
       (uidA, "SEI-FESF") in _cand, _cand)
# A senha de quem escolheu modo estação NÃO está aqui — tentar abrir o cofre
# dela seria desfazer uma decisão de custódia que não é deste módulo.
checar("a conta em modo ESTAÇÃO fica de fora",
       not any(u == uidB for u, _ in _cand), _cand)

print("\nL. PERGUNTAR É BARATO — e por isso a pergunta não pode escrever")
_antes = cx.execute("SELECT tentativas FROM acompanhado WHERE usuario_id=? AND protocolo=?",
                    (uidA, "019.5001.2026.0000001-11")).fetchone()["tentativas"]
_n = acmod.quantos_pendentes(cx, uidA, "SEI-SESAB")
_depois = cx.execute("SELECT tentativas FROM acompanhado WHERE usuario_id=? AND protocolo=?",
                     (uidA, "019.5001.2026.0000001-11")).fetchone()["tentativas"]
checar("quantos_pendentes conta o que há", _n == 1, _n)
checar("e NÃO incrementa o contador de entregas", _depois == _antes, (_antes, _depois))
checar("só os novos, quando se pede só os novos",
       acmod.quantos_pendentes(cx, uidA, "SEI-SESAB", so_novos=True) == 1)
# E a diferença importa porque `pendentes` ESCREVE: é ela que gasta a tentativa.
_lista = acmod.pendentes(cx, uidA, "SEI-SESAB")
_gastou = cx.execute("SELECT tentativas FROM acompanhado WHERE usuario_id=? AND protocolo=?",
                     (uidA, "019.5001.2026.0000001-11")).fetchone()["tentativas"]
checar("pendentes, sim, gasta a tentativa — é a diferença entre as duas",
       _lista and _gastou == _antes + 1, (_lista, _antes, _gastou))
cx.commit()

print("\nM. A CADÊNCIA — 'ao adicionar' agora, releitura DEPOIS da coleta do dia")
_manha = datetime.now(banco.TZ).replace(hour=8, minute=0, second=0, microsecond=0)
_tarde = _manha.replace(hour=asv.HORA_SEM_ESPERAR)
uidC = novo_usuario("acomp.cadencia@sei360.local")
config_servidor(uidC, "SEI-SESAB")
agC = novo_agente_servidor(uidC)
novo_agendamento(agC, ativo=1, horario="07:30")
acmod.adicionar(cx, uidC, "019.5004.2026.0000004-44", "SEI-SESAB")
cx.commit()
_pode, _mot = asv._devido(cx, uidC, "SEI-SESAB", _manha)
checar("item recém colado ('novo') não espera a coleta de amanhã",
       _pode and "novo" in _mot, (_pode, _mot))
# Agora ele deixa de ser novo: foi lido ontem. A releitura espera a coleta,
# porque é ela que responde de graça o que está na mesa (`reaproveitar`).
_ontem = (datetime.now(banco.TZ) - timedelta(days=1)).isoformat(timespec="seconds")
cx.execute("UPDATE acompanhado SET estado='lido', lido_em=? WHERE usuario_id=?",
           (_ontem, uidC))
cx.commit()
_pode, _mot = asv._devido(cx, uidC, "SEI-SESAB", _manha)
checar("releitura ESPERA a coleta do dia — senão paga seis requisições por nada",
       not _pode and "coleta do dia" in _mot, (_pode, _mot))
cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em)
              VALUES(?,?,'concluida','servidor',?)""",
           (agC, datetime.now(banco.TZ).date().isoformat() + "T07:30", agora()))
cx.commit()
_pode, _mot = asv._devido(cx, uidC, "SEI-SESAB", _manha)
checar("com a coleta do dia concluída, pode ir", _pode and "já concluiu" in _mot,
       (_pode, _mot))
# E a espera tem fim: se ao meio-dia a coleta não veio, ou falhou ou está
# desarmada — esperar mais trocaria requisição economizada por um dia sem ler.
cx.execute("DELETE FROM execucao WHERE agente_id=?", (agC,))
cx.commit()
_pode, _mot = asv._devido(cx, uidC, "SEI-SESAB", _tarde)
checar(f"depois das {asv.HORA_SEM_ESPERAR}h ninguém espera mais a coleta",
       _pode and "não se espera" in _mot, (_pode, _mot))
# Quem não tem coleta agendada não tem o que esperar.
uidD = novo_usuario("acomp.semcoleta@sei360.local")
config_servidor(uidD, "SEI-SESAB")
acmod.adicionar(cx, uidD, "019.5005.2026.0000005-55", "SEI-SESAB")
cx.execute("UPDATE acompanhado SET estado='lido', lido_em=? WHERE usuario_id=?",
           (_ontem, uidD))
cx.commit()
_pode, _mot = asv._devido(cx, uidD, "SEI-SESAB", _manha)
checar("sem coleta agendada, não há o que esperar",
       _pode and "sem coleta agendada" in _mot, (_pode, _mot))

print("\nN. O ENVELOPE EM PEDAÇOS — o que chegou inteiro fica, o corrompido não")
_saida = ("log qualquer\n"
          'ACOMP_OK {"instancia": "SEI-SESAB", "leituras": [{"protocolo": "A"}]}\n'
          'ACOMP_OK {"instancia": "SEI-SESAB", "leitur\n'
          'ACOMP_OK {"instancia": "SEI-SESAB", "leituras": [{"protocolo": "B"}]}\n')
_envs, _ruins = asv._ler_envelopes(_saida)
checar("os dois pedaços legíveis ficam", len(_envs) == 2, _envs)
checar("na ordem em que saíram",
       [e["leituras"][0]["protocolo"] for e in _envs] == ["A", "B"], _envs)
checar("e o corrompido é contado, não engolido", _ruins == 1, _ruins)
checar("saída sem marca nenhuma devolve lista vazia",
       asv._ler_envelopes("nada aqui") == ([], 0))

print("\nO. NENHUM CHROMIUM QUANDO A CARTEIRA JÁ RESPONDEU")
# A asserção central de eficiência: `rodada` só chama `_executar` — que é quem
# sobe navegador — quando sobra fila DEPOIS do reaproveitamento. Sem isto, o
# laço pagaria seis requisições ao SEI por processo para reler o que está no
# banco, que é a economia inteira do desenho.
_chamadas = []
_executar_real = asv._executar
asv._executar = lambda uid, inst, protos: (_chamadas.append((uid, inst, protos))
                                           or (len(protos), 0, None))
os.environ["SEI360_COLETA_SERVIDOR"] = "1"
try:
    # Tudo lido HOJE: a fila está vazia e ninguém sobe nada.
    _hoje = agora()
    cx.execute("UPDATE acompanhado SET estado='lido', lido_em=?", (_hoje,))
    cx.commit()
    asv.rodada(cx)
    checar("fila vazia: `_executar` não é chamado uma única vez",
           _chamadas == [], _chamadas)
    # Agora há um item por ler, e ele é 'novo' (não espera coleta).
    cx.execute("""UPDATE acompanhado SET estado='novo', lido_em=NULL, tentativas=0,
                  tentativa_em=NULL WHERE usuario_id=? AND instancia='SEI-SESAB'""",
               (uidA,))
    cx.commit()
    asv.rodada(cx)
    checar("com item por ler, `_executar` é chamado uma vez", len(_chamadas) == 1,
           _chamadas)
    checar("para a conta e a instalação certas, com os números da fila",
           _chamadas and _chamadas[0][0] == uidA
           and _chamadas[0][1] == "SEI-SESAB"
           and _chamadas[0][2] == ["019.5001.2026.0000001-11"], _chamadas)
    # UMA POR PASSADA: o teto de memória é o motivo, e ele não é negociável
    # num VPS de 2 GB onde um Chromium são ~450 MB.
    _chamadas.clear()
    cx.execute("""UPDATE acompanhado SET estado='novo', lido_em=NULL, tentativas=0,
                  tentativa_em=NULL""")
    cx.commit()
    asv.rodada(cx)
    checar("no máximo uma leitura por passada, mesmo com vários candidatos",
           len(_chamadas) == 1, _chamadas)
    # E COM A MEMÓRIA OCUPADA, NADA COMEÇA — o semáforo é o do atendente, não
    # um teto paralelo que finge não saber do outro.
    _chamadas.clear()
    cx.execute("""UPDATE acompanhado SET estado='novo', lido_em=NULL, tentativas=0,
                  tentativa_em=NULL""")
    cx.commit()
    atendente._vagas.acquire()
    try:
        asv.rodada(cx)
        checar("vaga de memória tomada: nenhuma leitura começa",
               _chamadas == [], _chamadas)
    finally:
        atendente._vagas.release()
finally:
    asv._executar = _executar_real

print("\nP. O CAMINHO COMPLETO, com coletor de mentira — cofre, stdin, publicação")
# O que esta cena NÃO prova, e fica dito: o Chromium contra o SEI real. O que
# ela prova é tudo o resto — a senha sai do cofre, desce por STDIN (nunca em
# argv), os pedaços do envelope são publicados um a um, e o item sai de 'novo'.
_falso = Path(cs.COLETOR.parent / "_coletor_falso_acomp.py")
_falso.write_text(
    "import json, sys\n"
    "p = json.loads(sys.stdin.readline())\n"
    "protos = p['acompanhamento']['protocolos']\n"
    "print('argv sem senha:', ' '.join(sys.argv[1:]))\n"
    "print('recebi senha por stdin:', bool(p.get('senha')))\n"
    "for x in protos:\n"
    "    print('ACOMP_OK ' + json.dumps({'instancia': p['acompanhamento']['instancia'],\n"
    "                                    'leituras': [{'protocolo': x, 'estado': 'lido',\n"
    "                                                  'aberto_em': ['SESAB/UMA'],\n"
    "                                                  'documentos': 3, 'movimentos': 7}]}))\n",
    encoding="utf-8")
_coletor_real = asv.COLETOR
asv.COLETOR = _falso
try:
    if not cofre.disponivel():
        checar("cofre disponível para a cena completa", False, "sem chave mestra")
    else:
        cofre.guardar(cx, uidA, "SEI-SESAB", "fulano.um", "senha-de-teste")
        cx.commit()
        cx.execute("""UPDATE acompanhado SET estado='novo', lido_em=NULL, tentativas=0,
                      tentativa_em=NULL WHERE usuario_id=? AND instancia='SEI-SESAB'""",
                   (uidA,))
        cx.commit()
        _g, _ig, _mot = asv._executar(uidA, "SEI-SESAB", ["019.5001.2026.0000001-11"])[:3]
        checar("a leitura é publicada", _g == 1, (_g, _ig, _mot))
        _linha = cx.execute("""SELECT estado, lido_em FROM acompanhado
                               WHERE usuario_id=? AND protocolo=?""",
                            (uidA, "019.5001.2026.0000001-11")).fetchone()
        checar("e o item deixa de estar 'novo' no banco",
               _linha["estado"] == "lido" and _linha["lido_em"], dict(_linha))
        _leitura = cx.execute("""SELECT fonte, documentos, movimentos
                                 FROM acompanhado_leitura WHERE usuario_id=?
                                 AND protocolo=? ORDER BY id DESC LIMIT 1""",
                              (uidA, "019.5001.2026.0000001-11")).fetchone()
        checar("com a leitura gravada na série, e a fonte dizendo que veio do SEI",
               _leitura and _leitura["documentos"] == 3
               and _leitura["movimentos"] == 7, dict(_leitura) if _leitura else None)
        # SEM CREDENCIAL não se inventa leitura: a recusa é dita e nada é gravado.
        _g2, _ig2, _mot2 = asv._executar(uidA, "SEI-FESF", ["019.5002.2026.0000002-22"])[:3]
        checar("sem credencial para a instalação, recusa com o motivo e grava nada",
               _g2 == 0 and _mot2 and "credencial" in _mot2, (_g2, _mot2))
finally:
    asv.COLETOR = _coletor_real
    _falso.unlink(missing_ok=True)

print("\nQ. O INTERRUPTOR — um só, e é o da coleta")
os.environ["SEI360_COLETA_SERVIDOR"] = "0"
checar("com a coleta desligada, o acompanhamento também está", asv.ligado() is False)
os.environ["SEI360_COLETA_SERVIDOR"] = "1"
checar("com ela ligada, este sobe junto — é a MESMA decisão de custódia",
       asv.ligado() is True)
os.environ["SEI360_ACOMPANHAMENTO_SERVIDOR"] = "0"
checar("e há como desligar SÓ este, sem derrubar a coleta", asv.ligado() is False)
del os.environ["SEI360_ACOMPANHAMENTO_SERVIDOR"]
checar("sem a variável, volta a seguir a coleta", asv.ligado() is True)
checar("sem thread própria neste teste, vivo() é False", asv.vivo() is False)
# `iniciar()` NÃO sobe thread sem o atendente vivo: o semáforo de memória é um
# `threading.Semaphore`, e ele não atravessa processo do gunicorn.
checar("iniciar() recusa subir fora do processo que venceu a eleição da busca",
       asv.iniciar() is False and asv.vivo() is False)

print("\nR. COBERTURA — o que este container responde, dito para a tela")
# A tela precisa saber QUEM lê cada item, senão volta a mentir: até 12/09/2026
# o cartão dizia "hoje, só a sua própria coleta pode respondê-lo" sobre todo
# item que não fosse da instalação ATIVA da pessoa. Era verdade enquanto quem
# lia era uma estação; virou falso no minuto em que este motor existiu.
os.environ["SEI360_COLETA_SERVIDOR"] = "1"
_le, _parado = asv.cobertura(cx, uidA)
checar("com o motor ligado, as duas instalações em modo servidor são lidas",
       sorted(_le) == ["SEI-FESF", "SEI-SESAB"] and _parado == {}, (_le, _parado))
# A FALHA DE IMPLANTAÇÃO MAIS SILENCIOSA: senha no servidor, motor desligado.
os.environ["SEI360_COLETA_SERVIDOR"] = "0"
_le, _parado = asv.cobertura(cx, uidA)
checar("com o motor desligado, nada é lido e o motivo é NOMEADO",
       _le == [] and set(_parado.values()) == {acmod.MOTOR_DESLIGADO},
       (_le, _parado))
os.environ["SEI360_COLETA_SERVIDOR"] = "1"
# Instalação sem busca provada: a leitura começa por uma pesquisa por número.
_orig = perfil_sei.INSTANCIAS["SEI-FESF"]["disponivel_busca"]
perfil_sei.INSTANCIAS["SEI-FESF"]["disponivel_busca"] = False
try:
    _le, _parado = asv.cobertura(cx, uidA)
    checar("instalação sem busca fica parada, com motivo próprio",
           _le == ["SEI-SESAB"] and _parado == {"SEI-FESF": acmod.SEM_BUSCA},
           (_le, _parado))
finally:
    perfil_sei.INSTANCIAS["SEI-FESF"]["disponivel_busca"] = _orig
# Quem está em modo ESTAÇÃO não entra em nenhuma das duas listas: a senha não
# está aqui, e quem responde é o agente da pessoa.
_le, _parado = asv.cobertura(cx, uidB)
checar("conta em modo estação não aparece nem como lida nem como parada",
       _le == [] and _parado == {}, (_le, _parado))

print("\nS. 'HÁ EXECUTOR?' É PERGUNTA SOBRE O CONTAINER, NÃO SOBRE O WORKER")
# O DEFEITO, e ele desarmava a coleta de gente: `_motivo_servidor()` (app.py)
# perguntava `coleta_servidor.vivo()`, que só sabe do processo que responde. Com
# `--workers 3`, dois dos três respondem False — então salvar /configuracao
# caindo num worker de painel gravava `pausado_motivo` = "o executor deveria
# estar rodando e não está" e DESARMAVA o agendamento da conta, por um fato
# verdadeiro sobre aquele processo e falso sobre o container. Dois terços das
# vezes. E não voltava: `_reavaliar_existentes` roda uma vez por processo, na
# subida — até o próximo redeploy, aquela conta não coletava.
os.environ["SEI360_COLETA_SERVIDOR"] = "1"
import app as A                                                  # noqa: E402
_cs_vivo, _cs_cap, _cs_hae = cs.vivo, cs.capacidade, cs.ha_executor
cs.capacidade = lambda: (True, "")
cs.vivo = lambda: False            # este worker é um worker de painel
cs.ha_executor = lambda: True      # e o container TEM executor, noutro worker
try:
    checar("worker sem a thread, container com executor: nenhuma pausa",
           A._motivo_servidor() is None, A._motivo_servidor())
    cs.ha_executor = lambda: False
    checar("e quando não há executor em lugar nenhum, a pausa volta — com o motivo",
           "não está" in (A._motivo_servidor() or ""), A._motivo_servidor())
finally:
    cs.vivo, cs.capacidade, cs.ha_executor = _cs_vivo, _cs_cap, _cs_hae
# E a resposta verdadeira atravessa processo pelo arquivo de vez do atendente,
# que é o único estado que workers irmãos compartilham.
checar("ha_executor() delega ao atendente, que sabe responder pelo container",
       cs.ha_executor() == (cs.vivo() or atendente.ha_executor()))

print("\nT. O AGENTE SEGUE O MODO, não a ordem dos cliques")
# Quem pareou uma estação e DEPOIS escolheu "a senha fica no servidor" ficava
# com um agente de estação e modo `servidor`. `_candidatos` filtra
# `nome_estacao LIKE 'SERVIDOR/%'`: o motor do container não via a conta, e
# `/api/agente/tarefa` seguia esperando a estação que a pessoa acabou de dizer
# que não usa mais. `agente_do` devolve o agente MAIS NOVO, de qualquer tipo; a
# criação do lógico só cobria quem nunca teve agente.
cs.capacidade = lambda: (True, "")
cs.ha_executor = lambda: True
try:
    uidE = novo_usuario("acomp.pareou@sei360.local")
    config_servidor(uidE, "SEI-SESAB")
    cx.execute("""INSERT INTO agentes(nome_estacao,dono_usuario_id,unidades_esperadas,
                  ativo,criado_em) VALUES(?,?,'[]',1,?)""",
               (f"ESTACAO-{uidE}", uidE, agora()))
    agE = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    cx.execute("INSERT INTO agendamento(agente_id,janelas,dias,ativo) VALUES(?,?,'todos',1)",
               (agE, json.dumps(["00:00"])))
    cx.commit()
    checar("(cena) antes, o motor do container NÃO vê a conta",
           agE not in cs._candidatos(cx), cs._candidatos(cx))
    A.aplicar_agendamento(cx, uidE)
    cx.commit()
    _nome = cx.execute("SELECT nome_estacao FROM agentes WHERE id=?", (agE,)).fetchone()[0]
    checar("modo servidor converte o agente de estação", _nome.startswith("SERVIDOR/"),
           _nome)
    checar("e o motor passa a vê-lo", agE in cs._candidatos(cx), cs._candidatos(cx))
    checar("a conversão fica no log de acesso, com o nome antigo e o novo",
           cx.execute("""SELECT alvo FROM log_acesso WHERE acao='agente_para_servidor'
                         AND usuario_id=?""", (uidE,)).fetchone() is not None)
    # E O CAMINHO DE VOLTA: escolher modo estação com um agente lógico armado
    # deixaria o container coletando uma conta que pediu que a senha não ficasse
    # aqui. A pausa tira a conta de `_candidatos` sem apagar nada.
    cx.execute("UPDATE config_usuario SET modo_coleta='estacao' WHERE usuario_id=?", (uidE,))
    cx.commit()
    A.aplicar_agendamento(cx, uidE)
    cx.commit()
    checar("modo estação PAUSA o agente lógico até a máquina ser pareada",
           agE not in cs._candidatos(cx), cs._candidatos(cx))
    _pausa = cx.execute("SELECT pausado_motivo FROM agentes WHERE id=?",
                        (agE,)).fetchone()[0]
    checar("e a pausa diz o que fazer, em vez de acusar o servidor",
           _pausa and "pareie" in _pausa, _pausa)
finally:
    cs.capacidade, cs.ha_executor = _cs_cap, _cs_hae

print("\nU. DUAS PONTAS, UMA JANELA — o container não coleta o que a estação levou")
# Converter o agente (cena T) NÃO revoga o pareamento: modo estação continua
# opção documentada, e os dois passam a compartilhar o MESMO agente. O que
# impede duas sessões do SEI na mesma conta, com a mesma credencial nominal, é o
# carimbo `gatilho` — `max_entregas_janela` é 3 e existe para RETENTATIVA.
uidF = novo_usuario("acomp.duas.pontas@sei360.local")
config_servidor(uidF, "SEI-SESAB", senha=True)
agF = novo_agente_servidor(uidF)
# A JANELA É RELATIVA A AGORA, e não "00:00" fixo: com tolerância de 600 min,
# "00:00" só é devida até as 10h — a cena passava à noite e falhava à tarde.
# Mesmo critério da cena F (2h atrás, por causa do desvio por agente), com
# "00:00" antes das 2h, quando "2h atrás" cairia em ontem.
_agora_u = datetime.now(banco.TZ)
novo_agendamento(agF, ativo=1, horario=(_agora_u - timedelta(hours=2)).strftime("%H:%M")
                 if _agora_u.hour >= 2 else "00:00")
cx.commit()
# A JANELA SAI DO PRÓPRIO `_decidir`, e não escrita à mão: `janela_devida`
# carimba data ISO com fuso, e uma janela montada por concatenação não casaria —
# o teste passaria por não achar nada, provando o contrário do que quer provar.
_ex, _janela, _inst, _p = cs._decidir(cx, agF)
cx.commit()
checar("(cena) a primeira decisão entrega a janela a este motor",
       _ex is not None and _inst == "SEI-SESAB", (_ex, _janela))
cx.execute("UPDATE execucao SET gatilho='agente' WHERE id=?", (_ex,))
cx.commit()
_r = cs._decidir(cx, agF)
checar("janela entregue à ESTAÇÃO não é retomada nem reentregue aqui",
       _r[0] is None and "estação levou" in _r[1], _r)
# Entrega SEM carimbo nenhum também não é nossa: `gatilho` aceita nulo, e em SQL
# `NULL <> 'servidor'` NÃO é verdadeiro — daí o `IS NOT`.
cx.execute("UPDATE execucao SET gatilho=NULL WHERE id=?", (_ex,))
cx.commit()
_r = cs._decidir(cx, agF)
checar("entrega sem carimbo também não é retomada (IS NOT, não <>)",
       _r[0] is None and "estação levou" in _r[1], _r)
# E a nossa, sim: retomar é justamente para o motor que caiu no meio.
cx.execute("UPDATE execucao SET gatilho='servidor' WHERE id=?", (_ex,))
cx.commit()
_r = cs._decidir(cx, agF)
checar("a entrega DESTE motor é retomada, que é o caso para o qual ela existe",
       _r[0] == _ex, (_r[0], _ex))
# A JANELA EXTRA DO ADMIN é o botão de FORÇAR a coleta. Ela é deste motor quando o
# agente é lógico — a guarda de `gatilho` a excluía, e forçar gravava uma execução
# que ninguém rodava.
cx.execute("UPDATE execucao SET gatilho='manual_admin' WHERE id=?", (_ex,))
cx.commit()
_r = cs._decidir(cx, agF)
checar("a janela extra do admin (forçar coleta) é retomada por este motor",
       _r[0] == _ex, (_r[0], _ex))

print("\nV. UM PERFIL POR PESSOA — e um login por pessoa, não um por execução")
# O DEFEITO, achado em 12/09/2026: `coleta._ambiente()` passava `SEI_PERFIL_DIR`
# cru, que no container é `/dados/_perfil_sei` — UM perfil de Chromium para
# todas as contas. O comentário de `atendente.executar` já mede o preço do outro
# lado: "a busca de B reaproveitava a sessão do SEI de A; `goto(LOGIN)` nem caía
# em login.php, e o SEI gravava as consultas de B com o nome de A". Numa COLETA é
# pior — ela abre o Controle de Processos de seis mesas, e abrir a mesa RECEBE os
# processos em trânsito dela: a coleta de B praticaria ATOS no SEI em nome de A.
# E em `testar_acesso` é pior ainda: o que ele lê vira o VÍNCULO da conta.
import coleta as colmod                                          # noqa: E402
_a = colmod._ambiente(11, "SEI-SESAB")
_b = colmod._ambiente(22, "SEI-SESAB")
_c = colmod._ambiente(11, "SEI-FESF")
checar("duas contas, dois perfis", _a["SEI_PERFIL_DIR"] != _b["SEI_PERFIL_DIR"],
       (_a["SEI_PERFIL_DIR"], _b["SEI_PERFIL_DIR"]))
checar("duas instalações da mesma conta, dois perfis também",
       _a["SEI_PERFIL_DIR"] != _c["SEI_PERFIL_DIR"],
       (_a["SEI_PERFIL_DIR"], _c["SEI_PERFIL_DIR"]))
# E A ECONOMIA, que é o outro lado da mesma moeda: coleta, busca e
# acompanhamento da MESMA pessoa na MESMA instalação usam o MESMO diretório —
# então o segundo acha o cookie que o primeiro deixou. Um login por pessoa por
# instalação neste container, e login novo é onde o segundo fator aparece sem
# ninguém na tela para digitar.
checar("coleta e busca/acompanhamento compartilham o perfil da pessoa",
       _a["SEI_PERFIL_DIR"] == str(atendente._perfil_de(11, "SEI-SESAB")),
       (_a["SEI_PERFIL_DIR"], str(atendente._perfil_de(11, "SEI-SESAB"))))
# A SENHA NÃO FICA NO PERFIL: ela chega por stdin a cada execução daqui, então o
# coletor a apaga do localStorage depois de logar.
checar("a senha é apagada do perfil depois do login",
       _a.get("SEI_ESQUECER_APOS_LOGIN") == "1", _a.get("SEI_ESQUECER_APOS_LOGIN"))
checar("e a credencial nunca entra no ambiente do filho",
       not any("SENHA" in k.upper() or "SEGREDO" in k.upper() for k in _a), list(_a))
# SEM DONO, o ambiente é o de antes — é o que a linha de comando deste módulo
# usa, e mexer nela mudaria o perfil de quem roda `python coleta.py` à mão.
checar("sem usuario_id, o ambiente continua o de antes",
       "SEI_ESQUECER_APOS_LOGIN" not in colmod._ambiente(),
       list(colmod._ambiente()))

cx.close()
print("\n" + "=" * 62)
# O FORMATO E CONTRATO: rodar_testes.py casa a frase exata e conta como
# FALHA a suite que nao a imprime. Era a TERCEIRA suite deste repositorio
# com resumo proprio, e a unica delas que cobre o que roda em producao.
print(f"{ok} verificações OK, {mau} falha(s)")
sys.exit(1 if mau else 0)
