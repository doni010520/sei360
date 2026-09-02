# -*- coding: utf-8 -*-
"""
O POCO — reaproveitar o que e do processo sem vazar a visao de ninguem.

O QUE ESTA SUITE PROTEGE
------------------------
O reaproveitamento entre pessoas tem um modo de falha unico e caro: a tela de
uma pessoa mostrando o estado de outra, com um valor plausivel, em silencio, que
ninguem notaria. Nenhuma das travas abaixo produz erro visivel quando falha —
todas produzem um NUMERO PLAUSIVEL E ERRADO. Por isso cada uma tem teste proprio:

  T3  os cinco campos por mesa sao RECALCULADOS, nunca copiados
  T4  o carimbo do poco nao rejuvenesce sem leitura
  T5  sessao caida nao parece coleta boa
  T6  dez agentes as 07:30 nao recebem o mesmo plano
  T7  acompanhamento nao atravessa pessoa
  T9  bloco de leitura degradada nao e publicado
  T11 o poco nunca CRIA linha (regra do espelho)
  T12 a guarda ve o barulho e e cega ao silencio — e a faxina sabe disso

    python teste_poco.py
"""
import os as _os                                            # noqa: E402
from ambiente_teste import isolar

isolar(__file__, copiar=False)                            # banco proprio, do zero

import json                                               # noqa: E402
import sys                                                # noqa: E402
from datetime import datetime, timedelta                  # noqa: E402

import banco                                              # noqa: E402
banco.migrar()
import poco                                               # noqa: E402
from banco import conectar, TZ                            # noqa: E402

ok = falhas = 0


def checar(nome, cond, viu=""):
    global ok, falhas
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        falhas += 1
        print(f"  FALHA {nome}" + (f"   -> {viu}" if viu else ""))


def iso(dt):
    return dt.isoformat(timespec="seconds")


# Duas contas de verdade: morno_dono e uma FK, e o poco recusa dono inventado —
# o que e correto, porque "de quem e esta leitura" nao pode apontar para ninguem.
_cx = conectar()
for _uid, _mail in ((7, "t.sete@exemplo"), (99, "t.noventa@exemplo")):
    # INSERT simples, nao OR IGNORE: com OR IGNORE, o papel 'usuario' (que nao
    # existe no CHECK) era engolido em silencio e a FK so estourava 200 linhas
    # depois, num lugar que nao tinha nada a ver.
    _cx.execute("INSERT INTO usuarios(id,email,nome,papel,ativo) "
                "VALUES(?,?,?,'servidor',1)", (_uid, _mail, _mail))
_cx.commit(); _cx.close()

# A instancia e explicita em TODA chamada. Um teste que confia num padrao prova
# o padrao, nao a regra.
INST = "SEI-SESAB"

AGORA = datetime.now(TZ)
CESS = "SESAB/SAIS/DGGUP/DGESS/CESS"
COMASUP = "SESAB/SAIS/DGGUP/DGESS/COMASUP"

MOV = [
    {"dh": "19/08/2026 07:30", "un": COMASUP, "us": "ana.souza",
     "de": "Processo recebido na unidade"},
    {"dh": "18/08/2026 16:10", "un": CESS, "us": "willian.damascena",
     "de": f"Processo remetido pela unidade {CESS}"},
    {"dh": "07/08/2026 15:39", "un": CESS, "us": "willian.damascena",
     "de": "Processo recebido na unidade"},
    {"dh": "28/07/2025 08:58", "un": "SESAB/SAIS/DGGUP/DGESS/ASTEC", "us": "joao.lima",
     "de": "Processo público gerado"},
]


def linha(pid="99001", mesa=CESS, **extra):
    """Uma linha de coleta LIMPA — a que o poco aceita publicar."""
    d = {
        "id": pid, "protocolo": "019.5120.2026.0000000-00", "mesa_coleta": mesa,
        "tipo_processo": "Ofício", "especificacao": "assunto qualquer",
        "atribuido_login": "willian.damascena", "marcador": "PAGAMENTO",
        "marcador_cor": "azul", "anotacao_data": None, "retorno": None,
        "doc_incluido": False, "visualizado": True,
        "autuacao": "28/07/2025 08:58", "gerador_unidade": "SESAB/SAIS/DGGUP/DGESS/ASTEC",
        "gerador_usuario": "joao.lima", "nivel_acesso": "Público", "hipotese_legal": None,
        "mov_custodia": MOV, "mesas_fonte": "arvore", "documentos": 12,
        "movimentos": 27, "movimentos_exato": 27, "movimentos_paginas": 1,
        "emails_enviados": 1, "assinatura_externa": 0, "anexados": [],
        "sobrestado": False, "urgente": False, "mesas": [], "ultimo_movimento": None,
        "assuntos": ["06.01.02.02"], "interessados": [],
        "alterar_disponivel": True, "acomp_disponivel": True,
        "acompanhamento": [{"grupo": "PAGAMENTO", "observacao": "", "usuario": "x", "data": ""}],
        "acomp_grupos": ["PAGAMENTO"],
        "sem_historico": False, "truncado": False, "mov_parcial": False,
        "_fresco": True,
    }
    d.update(extra)
    return d


def item(d):
    """O que a estacao manda ao /plano: so os campos da guarda."""
    return {k: d.get(k) for k in
            ("id", "atribuido_login", "marcador", "marcador_cor",
             "anotacao_data", "retorno", "doc_incluido")}


print("\n1. o que pode e o que nao pode virar bloco compartilhado")
casos = [
    ("linha limpa publica", linha(), True),
    ("sem _fresco NAO publica (ninguem leu de verdade)", linha(_fresco=False), False),
    ("sem historico NAO publica", linha(sem_historico=True), False),
    ("truncado NAO publica", linha(truncado=True), False),
    ("historico com buraco NAO publica", linha(mov_parcial=True), False),
    ("arvore que nao parseou NAO publica", linha(mesas_fonte="andamento"), False),
    ("arvore sem documentos NAO publica", linha(documentos=0), False),
    ("sigiloso NAO publica (credencial e NOMINAL no SEI)",
     linha(nivel_acesso="Sigiloso"), False),
    ("nivel desconhecido NAO publica", linha(nivel_acesso=None), False),
    ("sem mov_custodia NAO publica (so daria para COPIAR os cinco campos)",
     linha(mov_custodia=None), False),
]
for nome, d, esperado in casos:
    pode, motivo = poco.publicavel(d)
    checar(nome, pode is esperado, motivo or "publicavel")

print("\n2. T3 — os cinco campos sao recalculados para a mesa de quem le")
c = poco.campos_da_mesa(MOV, CESS)
k = poco.campos_da_mesa(MOV, COMASUP)
checar("CESS recebe em 07/08", c["marco_unidade"] == "07/08/2026 15:39", str(c))
checar("COMASUP recebe em 19/08 — nao herda a data da CESS",
       k["marco_unidade"] == "19/08/2026 07:30", str(k))
checar("nem herda quem recebeu na CESS",
       k["recebimento_por"] == "ana.souza" != c["recebimento_por"], str(k))
vazio = poco.campos_da_mesa(MOV, "SESAB/OUTRA")
checar("unidade ausente da custodia devolve os cinco NULOS",
       vazio["marco_unidade"] is None and vazio["derivada_para"] is None, str(vazio))
checar("e diz explicitamente que nao derivou — 'nao sei', nao 'sem divergencia'",
       "derivada_para" in vazio, str(vazio))

# ---------------------------------------------------------------- PARIDADE
# Duas implementacoes da MESMA regra so se justificam se alguem conferir que elas
# continuam sendo a mesma regra. Antes, a "conferencia" lia o exit code de um teste
# em JS com fixture diferente e assercoes disjuntas: uma implementacao podia zerar
# envio/unidade_envio e as duas suites continuavam verdes. Agora ha UMA tabela de
# casos e a comparacao e campo a campo.
import subprocess                                          # noqa: E402
from pathlib import Path                                   # noqa: E402

_js = Path(r"C:\Claude\sei_sistema\painel_sesab\_teste_camposdamesa.js")
_tab = Path(r"C:\Claude\sei_sistema\painel_sesab\_casos_camposdamesa.json")
_node = next((e for e in (r"C:\Program Files\nodejs\node.exe", "node")
              if __import__("shutil").which(e)), None)
if _js.exists() and _tab.exists() and _node:
    _r = subprocess.run([_node, str(_js), "--casos"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=60)
    checar("o lado JS respondeu a tabela de casos", _r.returncode == 0 and _r.stdout,
           (_r.stderr or "")[-200:])
    _casos = json.loads(_tab.read_text(encoding="utf-8"))
    # o SEIAuto escreve o banner dele em stdout ao carregar; a sentinela separa
    _saida_js = json.loads(_r.stdout.split("--CASOS--", 1)[-1])
    _divs = []
    for _c, _js_out in zip(_casos["casos"], _saida_js):
        _py = poco.campos_da_mesa(_casos[_c["mov"]], _c["unidade"])
        for _k in sorted(_py):
            if _py[_k] != _js_out["saida"].get(_k):
                _divs.append(f'{_c["nome"]}.{_k}: py={_py[_k]!r} js={_js_out["saida"].get(_k)!r}')
    checar(f"as duas implementacoes concordam nos {len(_casos['casos'])} casos, campo a campo",
           not _divs, "; ".join(_divs[:3]))
    # e a tabela tem de exercitar os cinco campos, senao a concordancia e vazia
    _naonulos = {_k for _o in _saida_js for _k, _v in _o["saida"].items() if _v is not None}
    for _k in ("recebimento", "recebimento_por", "envio", "unidade_envio", "marco_unidade"):
        checar(f"a tabela exercita {_k} com valor real", _k in _naonulos, str(sorted(_naonulos)))
else:
    checar("paridade com o JS conferida", False,
           "node, o teste ou a tabela de casos nao foram encontrados")

print("\n3. T4 — o carimbo do poco NAO rejuvenesce sem leitura")
cx = conectar()
manha = iso(AGORA - timedelta(hours=2))
poco.publicar(cx, [linha()], dono_usuario_id=None, coletado_em=manha, instancia=INST)
antes = cx.execute("SELECT morno_em, recebido_em FROM poco_processo").fetchone()
checar("o bloco entrou com a hora declarada pela estacao", antes["morno_em"] == manha)
# a mesma linha, publicada de novo 45 min depois, SEM leitura nova
poco.publicar(cx, [linha()], dono_usuario_id=None, coletado_em=manha, instancia=INST)
depois = cx.execute("SELECT morno_em FROM poco_processo").fetchone()["morno_em"]
checar("republicar a MESMA leitura nao avanca o carimbo", depois == manha, depois)
# leitura DE VERDADE mais nova avanca
agora_s = iso(AGORA)
poco.publicar(cx, [linha()], dono_usuario_id=None, coletado_em=agora_s, instancia=INST)
checar("leitura mais nova avanca",
       cx.execute("SELECT morno_em FROM poco_processo").fetchone()["morno_em"] == agora_s)
# leitura mais VELHA nunca sobrescreve a mais nova
poco.publicar(cx, [linha()], dono_usuario_id=None, coletado_em=manha, instancia=INST)
checar("bloco VELHO nunca sobrescreve bloco novo (ordem de chegada nao decide)",
       cx.execute("SELECT morno_em FROM poco_processo").fetchone()["morno_em"] == agora_s)

print("\n4. os dois relogios")
cx.execute("UPDATE poco_processo SET morno_em=?", (iso(AGORA - timedelta(minutes=5)),))
b = cx.execute("SELECT * FROM poco_processo").fetchone()
checar("bloco novo pelos dois relogios e novo", poco.idade_h(b, AGORA) < 1)
# relogio da estacao adiantado tres dias: o do servidor e que manda
cx.execute("UPDATE poco_processo SET recebido_em=?", (iso(AGORA - timedelta(hours=100)),))
b = cx.execute("SELECT * FROM poco_processo").fetchone()
checar("relogio torto na estacao nao estica a validade (vale a PIOR das duas datas)",
       poco.idade_h(b, AGORA) > poco.TETO_H, f"{poco.idade_h(b, AGORA):.0f} h")
cx.close()

print("\n5. o veredito, campo a campo")


def novo_banco():
    cx = conectar()
    for t in ("poco_processo", "poco_conferencia", "poco_acompanhamento", "poco_reserva"):
        cx.execute(f"DELETE FROM {t}")
    cx.commit()
    return cx


cx = novo_banco()
d = linha()
poco.publicar(cx, [d], dono_usuario_id=7, coletado_em=iso(AGORA - timedelta(hours=1)), instancia=INST)
r = poco.plano(cx, CESS, [item(d)], INST, dono_usuario_id=7)
checar("bloco de 1 h, guarda igual, acompanhamento meu: PULAR",
       r["veredito"]["99001"] == "pular", r["motivos"]["99001"])

mudou = dict(item(d), marcador="OUTRO MARCADOR")
r = poco.plano(cx, CESS, [mudou], INST, dono_usuario_id=7)
checar("marcador novo na lista: LER TUDO",
       r["veredito"]["99001"] == "completa", r["motivos"]["99001"])

r = poco.plano(cx, CESS, [dict(item(d), atribuido_login="outra.pessoa")], dono_usuario_id=7, instancia=INST)
checar("troca de atribuicao: LER TUDO", r["veredito"]["99001"] == "completa")

r = poco.plano(cx, CESS, [item(d)], INST, dono_usuario_id=99)
checar("T7 — outra PESSOA nao herda o acompanhamento: SO_ACOMPANHAMENTO",
       r["veredito"]["99001"] == "so_acompanhamento", r["motivos"]["99001"])

r = poco.plano(cx, COMASUP, [item(d)], INST, dono_usuario_id=7)
checar("outra MESA nao tem guarda propria: LER TUDO",
       r["veredito"]["99001"] == "completa", r["motivos"]["99001"])

r = poco.plano(cx, CESS, [{"id": "00000"}], INST, dono_usuario_id=7)
checar("processo que o poco nunca viu: LER TUDO", r["veredito"]["00000"] == "completa")

cx.execute("UPDATE poco_processo SET morno_em=?, recebido_em=?",
           (iso(AGORA - timedelta(hours=poco.TETO_H + 1)),) * 2)
r = poco.plano(cx, CESS, [item(d)], INST, dono_usuario_id=7)
checar(f"bloco acima do teto de {poco.TETO_H} h: LER TUDO",
       r["veredito"]["99001"] == "completa", r["motivos"]["99001"])
cx.close()

print("\n6. T6 — dez agentes as 07:30, e o que a reserva pode ou nao poupar")
cx = novo_banco()
# poco_reserva referencia execucao: a reserva morre junto com a corrida que a fez,
# entao o teste precisa de execucoes de verdade.
cx.execute("INSERT INTO agentes(nome_estacao,ativo) VALUES('t.estacao',1)")
_aid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
for _n in list(range(100, 111)) + [999]:
    cx.execute("INSERT INTO execucao(id,agente_id,estado) VALUES(?,?,'em_curso')", (_n, _aid))
cx.commit()

print("  (a) poco VAZIO — nao ha o que poupar")
frios = [item(linha(pid=f"{9000+i}")) for i in range(40)]
planos = [poco.plano(cx, CESS, frios, INST, execucao_id=100 + n, dono_usuario_id=7)
          for n in range(10)]
tam = [sum(1 for v in pl["veredito"].values() if v == "completa") for pl in planos]
checar("com o poco vazio TODO agente le tudo — pular seria entregar linha vazia",
       tam == [40] * 10, str(tam))
checar("e ninguem recebe 'em_leitura' sobre bloco que nao existe",
       all("em_leitura" not in pl["resumo"] for pl in planos),
       str([pl["resumo"] for pl in planos[:2]]))

cx.close()
print("  (b) bloco ACIMA DO TETO — reserva nao pode disfarcar")
cx2 = novo_banco()
cx2.execute("INSERT INTO agentes(nome_estacao,ativo) VALUES('t2',1)")
_a2 = cx2.execute("SELECT last_insert_rowid()").fetchone()[0]
for _n in (200, 201):
    cx2.execute("INSERT INTO execucao(id,agente_id,estado) VALUES(?,?,'em_curso')", (_n, _a2))
velho = linha(pid="8001")
poco.publicar(cx2, [velho], dono_usuario_id=7,
              coletado_em=iso(AGORA - timedelta(hours=poco.TETO_H + 1)), instancia=INST)
cx2.commit()
p1 = poco.plano(cx2, CESS, [item(velho)], INST, execucao_id=200, dono_usuario_id=7)
p2 = poco.plano(cx2, CESS, [item(velho)], INST, execucao_id=201, dono_usuario_id=7)
checar("o 1o le porque o bloco venceu", p1["veredito"]["8001"] == "completa",
       p1["motivos"]["8001"])
checar("e o 2o TAMBEM le — a reserva nao transforma bloco condenado em 'pular'",
       p2["veredito"]["8001"] == "completa", p2["motivos"]["8001"])
# e mesmo que alguem force o veredito, servir() recusa: duas camadas.
b = cx2.execute("SELECT * FROM poco_processo WHERE id_sei='8001'").fetchone()
ok_s, motivo_s = poco.servivel(b, AGORA)
checar("servir() tem gate proprio: bloco vencido nao sai do poco nem forcado",
       ok_s is False and "teto" in (motivo_s or ""), str(motivo_s))
checar("e a costura devolve dicionario vazio para ele",
       poco.servir(cx2, ["8001"], INST, CESS, 7) == {}, "algo foi servido")
cx2.close()

print("  (c) bloco SERVIVEL relido pela faxina — aqui sim a reserva poupa")
cx3 = novo_banco()
cx3.execute("INSERT INTO agentes(nome_estacao,ativo) VALUES('t3',1)")
_a3 = cx3.execute("SELECT last_insert_rowid()").fetchone()[0]
for _n in (300, 301):
    cx3.execute("INSERT INTO execucao(id,agente_id,estado) VALUES(?,?,'em_curso')", (_n, _a3))
# bloco morno: dentro do teto, fora das 12 h, entao entra no rodizio da faxina
mornos = [linha(pid=f"{4000+i}", marcador=None, atribuido_login=None) for i in range(200)]
poco.publicar(cx3, mornos, dono_usuario_id=7,
              coletado_em=iso(AGORA - timedelta(hours=poco.MORNO_H + 1)), instancia=INST)
cx3.commit()
itens_m = [item(d) for d in mornos]
q1 = poco.plano(cx3, CESS, itens_m, INST, execucao_id=300, dono_usuario_id=7)
q2 = poco.plano(cx3, CESS, itens_m, INST, execucao_id=301, dono_usuario_id=7)
faxina1 = {p for p, v in q1["veredito"].items() if v in ("completa", "canario")}
emleitura2 = {p for p, v in q2["veredito"].items() if v == "em_leitura"}
checar("o 1o pega a cota de faxina do dia", 0 < len(faxina1) < 200, str(len(faxina1)))
checar("o 2o nao releg o que o 1o ja esta relendo", emleitura2 == faxina1,
       f"{len(emleitura2)} x {len(faxina1)}")
checar("e o motivo diz que o bloco anterior serve",
       "serve" in q2["motivos"][sorted(emleitura2)[0]], q2["motivos"][sorted(emleitura2)[0]])
# reserva vencida volta a fila sozinha: agente que morre no meio nao tranca nada
cx3.execute("UPDATE poco_reserva SET reserva_ate=?", (iso(AGORA - timedelta(minutes=1)),))
q3 = poco.plano(cx3, CESS, itens_m, INST, execucao_id=301, dono_usuario_id=7)
checar("reserva vencida volta a fila (agente que morre no meio nao tranca)",
       not any(v == "em_leitura" for v in q3["veredito"].values()))
cx3.close()

print("\n7. T12 — a faxina garante o teto de 72 h por aritmetica")
checar("linha com marcador: a guarda alcanca",
       poco.guarda_cega(linha()) is False)
checar("linha sem marcador, sem anotacao, sem retorno, sem atribuicao: guarda CEGA",
       poco.guarda_cega(linha(marcador=None, atribuido_login=None)) is True)
cx = novo_banco()
cegas = [linha(pid=f"{7000+i}", marcador=None, atribuido_login=None) for i in range(300)]
vistas = [linha(pid=f"{8000+i}") for i in range(300)]
poco.publicar(cx, cegas + vistas, dono_usuario_id=7,
              coletado_em=iso(AGORA - timedelta(hours=poco.MORNO_H + 1)), instancia=INST)
rc = poco.plano(cx, CESS, [item(d) for d in cegas], INST, dono_usuario_id=7)
rv = poco.plano(cx, CESS, [item(d) for d in vistas], INST, dono_usuario_id=7)
frac_c = sum(1 for v in rc["veredito"].values() if v != "pular") / 300
frac_v = sum(1 for v in rv["veredito"].values() if v != "pular") / 300
# A FRACAO E O QUE IMPORTA, e ela tem de ser ~FAXINA nas duas faixas: e assim que o
# teto de 72 h e garantido por aritmetica (1/3 por dia) em vez de por excecao.
# A versao anterior priorizava a faixa cega supondo que os escapes estavam la; a
# medicao sobre 5 pares de dias desta base diz o contrario — 174 dos 183 escapes
# (95%) estao FORA dela. Sem hipotese medida, releitura uniforme.
for nome, frac in (("cega", frac_c), ("vigiada", frac_v)):
    checar(f"a faxina rele ~1/3 da faixa {nome} por dia ({frac:.0%})",
           0.25 <= frac <= 0.45, f"{frac:.0%}")
checar("e as duas faixas sao relidas na MESMA proporcao — nenhum canto do poco "
       "fica sem releitura", abs(frac_c - frac_v) < 0.10, f"{frac_c:.0%} x {frac_v:.0%}")
# 1/3 por dia = todo bloco relido em ~3 dias, que e de onde sai o teto de 72 h.
checar(f"1/3 por dia cobre o poco inteiro dentro do teto de {poco.TETO_H} h",
       3 * 24 <= poco.TETO_H, f"{poco.TETO_H} h")
cx.close()

print("\n7b. o canario audita o poco — e a direcao esta fixada no codigo")
cx = novo_banco()
# um bloco publicado, e a MESMA leitura de novo: nada mudou
antes = linha(pid="5100")
poco.publicar(cx, [antes], dono_usuario_id=7, coletado_em=iso(AGORA - timedelta(hours=2)), instancia=INST)
cx.commit()
checar("releitura identica nao acusa divergencia nenhuma",
       poco.divergencia(cx, antes, INST) == 0, str(poco.divergencia(cx, antes, INST)))
# agora uma releitura em que o processo ANDOU
andou = linha(pid="5100", movimentos_exato=31, documentos=14,
              ultimo_movimento={"dh": "20/08/2026 10:00", "un": CESS, "de": "Conclusao"})
n = poco.divergencia(cx, andou, INST)
checar("releitura de processo que andou acusa os campos que mudaram", n >= 3, str(n))
checar("processo que o poco nunca viu nao tem com o que comparar",
       poco.divergencia(cx, linha(pid="9999"), INST) is None)
# e a comparacao TEM de acontecer antes do upsert, senao o termo de comparacao some
poco.publicar(cx, [andou], dono_usuario_id=7, coletado_em=iso(AGORA), instancia=INST)
checar("depois de publicar, a copia antiga ja nao existe — por isso a comparacao "
       "vem antes", poco.divergencia(cx, andou, INST) == 0, str(poco.divergencia(cx, andou, INST)))
# a coluna do snapshot deixa de ser decorativa
_cols = [r[1] for r in cx.execute("PRAGMA table_info(snapshot)")]
checar("snapshot.canario_divergencias existe", "canario_divergencias" in _cols)
cx.close()

print("\n8. a saida do poco e por LISTA DE PERMISSAO")
checar("href NUNCA sai do poco (hash de sessao morto DERRUBA a sessao de quem trabalha)",
       "href" not in poco.PERMITIDAS)
for proibido in ("visualizado", "marcador", "anotacao", "atribuido_login", "retorno",
                 "origem", "mesa_coleta", "mesas_coleta", "mesas_conta", "mesas_falhas",
                 "doc_incluido", "recebimento", "marco_unidade", "envio",
                 "sem_historico", "acompanhamento"):
    checar(f"{proibido} nao atravessa pessoa pelo poco", proibido not in poco.PERMITIDAS)

print("\n9. T5 e T11 — a costura na ingestao")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import ingestao                                            # noqa: E402

cx = novo_banco()
poco.publicar(cx, [linha()], dono_usuario_id=7, coletado_em=iso(AGORA - timedelta(hours=3)), instancia=INST)
cx.commit()
# a corrida de agora: uma linha lida, uma pulada (o poco responde por ela)
lida = linha(pid="99002")
pulada = linha(pid="99001", _fresco=False, _pulado=True, autuacao=None,
               gerador_unidade=None, mov_custodia=None, documentos=None)
funil = ingestao._costurar(cx, [lida, pulada], CESS, iso(AGORA), 7, None, INST)
checar("T11 — o poco nao CRIA linha: entram as duas que a lista trouxe",
       funil["devidos"] + funil["servidos"] == 2, str(funil))
checar("a linha lida conta como devida e lida", funil["devidos"] == 1 == funil["lidos"], str(funil))
checar("a pulada conta como servida", funil["servidos"] == 1, str(funil))
checar("a linha servida recebeu o bloco", pulada["autuacao"] == "28/07/2025 08:58")
checar("e NAO parece sem historico", pulada["sem_historico"] == 0)
checar("a REGUA dela e a da leitura que produziu o bloco, nao a de agora",
       pulada["medido_em"] < lida["medido_em"], f"{pulada['medido_em']} x {lida['medido_em']}")
checar("os cinco campos foram RECALCULADOS para a mesa desta linha",
       pulada["marco_unidade"] == "07/08/2026 15:39", str(pulada.get("marco_unidade")))
checar("e a linha vai marcada como servida pelo poco", pulada["servido_do_poco"] == 1)

# A MESA QUE NUNCA VIU O PROCESSO NAO RECEBE BLOCO NENHUM. Os ids servidos saem do
# corpo que o agente publicou; sem este recorte, uma linha forjada com o id de um
# processo de outra unidade devolveria o bloco inteiro dele — protocolo, assuntos,
# interessados, gerador_usuario e o mov_custodia com nome de quem movimentou. Antes
# do poco, forjar um id nao dava informacao nenhuma; com o poco o servidor viraria
# oraculo.
outra = linha(pid="99001", mesa="SESAB/OUTRA", _fresco=False, _pulado=True,
              autuacao=None, mov_custodia=None)
ingestao._costurar(cx, [outra], "SESAB/OUTRA", iso(AGORA), 7, None, INST)
checar("mesa que nunca mostrou o processo nao recebe o bloco",
       not outra.get("autuacao") and outra.get("servido_do_poco") != 1, str(outra)[:180])
checar("e a linha cai no caminho de orfao, dita, em vez de sair meio preenchida",
       outra.get("sem_historico") == 1, str(outra.get("sem_historico")))

# Agora a mesma prova para uma mesa que VIU o processo mas nao consta na custodia:
# ai o bloco e servido e sao os cinco campos que saem nulos, marcados.
cx.execute("INSERT INTO poco_conferencia(id_sei,mesa,hash,em) VALUES('99001','SESAB/VIU','x',?)",
           (iso(AGORA),))
cx.commit()
viu = linha(pid="99001", mesa="SESAB/VIU", _fresco=False, _pulado=True,
            autuacao=None, mov_custodia=None)
ingestao._costurar(cx, [viu], "SESAB/VIU", iso(AGORA), 7, None, INST)
checar("mesa ausente da custodia: os cinco saem NULOS, nao copiados",
       viu["marco_unidade"] is None and viu["mesa_indeterminada"] == 1, str(viu)[:180])
checar("mas o resto do bloco (que e do processo) vale",
       viu.get("autuacao") == "28/07/2025 08:58", str(viu.get("autuacao")))

# T5: o poco quente nao pode disfarcar uma sessao que caiu
mortas = [linha(pid=f"{6000+i}", _fresco=False, _pulado=False, sem_historico=True)
          for i in range(41)]
funil = ingestao._costurar(cx, mortas + [linha(pid="6100")], CESS, iso(AGORA), 7, None, INST)
checar("T5 — sessao caida: 42 devidos, 1 lido (o funil denuncia)",
       funil["devidos"] == 42 and funil["lidos"] == 1, str(funil))

# acompanhamento nao atravessa pessoa nem pela costura
cx2 = novo_banco()
poco.publicar(cx2, [linha()], dono_usuario_id=7, coletado_em=iso(AGORA - timedelta(hours=3)), instancia=INST)
cx2.commit()
alheia = linha(pid="99001", _fresco=False, _pulado=True, acompanhamento=None, acomp_grupos=None)
ingestao._costurar(cx2, [alheia], CESS, iso(AGORA), 99, None, INST)
checar("T7 — o acompanhamento de outra pessoa nao vem junto",
       not alheia["acompanhamento"] and alheia["acomp_lido"] == 0, str(alheia.get("acompanhamento")))
minha = linha(pid="99001", _fresco=False, _pulado=True, acompanhamento=None)
ingestao._costurar(cx2, [minha], CESS, iso(AGORA), 7, None, INST)
checar("e o da propria pessoa vem, com a marca de lido",
       minha["acomp_lido"] == 1 and minha["acompanhamento"], str(minha.get("acompanhamento")))
cx2.close()
cx.close()

print("\n10. versao do parser")
cx = novo_banco()
poco.publicar(cx, [linha()], dono_usuario_id=7, coletado_em=iso(AGORA), instancia=INST)
cx.execute("UPDATE poco_processo SET parser_versao='outra'")
r = poco.plano(cx, CESS, [item(linha())], INST, dono_usuario_id=7)
checar("bloco de outra versao do parser nao e servido",
       r["veredito"]["99001"] == "completa", r["motivos"]["99001"])
cx.close()

print("\n11. o ciclo inteiro: duas pessoas na mesma mesa")
import tempfile                                            # noqa: E402
from ingestao import ingerir                               # noqa: E402

cx = novo_banco()
cx.execute("DELETE FROM processo"); cx.execute("DELETE FROM snapshot")
cx.commit(); cx.close()

TMP = Path(tempfile.mkdtemp(prefix="poco_"))


def gravar(nome, linhas):
    arq = TMP / nome
    arq.write_text(json.dumps(linhas, ensure_ascii=False), encoding="utf-8")
    return str(arq)


# ANA coleta as 07:30 e le tudo.
ana = [dict(linha(pid=f"{5000+i}"), mesas_conta=[CESS], mesas_falhas=[]) for i in range(5)]
ingerir(gravar("ana.json", ana), agente_id=None,
        coletado_em=iso(AGORA - timedelta(hours=1)), dono=7)
cx = conectar()
n = cx.execute("SELECT COUNT(*) FROM poco_processo").fetchone()[0]
checar("a coleta de Ana publicou os 5 blocos no poco", n == 5, str(n))

# BRUNO coleta as 09:00. O plano diz o que ele precisa ler.
itens = [item(d) for d in ana]
pl = poco.plano(cx, CESS, itens, INST, dono_usuario_id=99)
so_acomp = sum(1 for v in pl["veredito"].values() if v == "so_acompanhamento")
checar("Bruno so precisa do proprio acompanhamento nos 5",
       so_acomp == 5, str(pl["resumo"]))
cx.close()

# ...e coleta so isso: bloco pulado, acompanhamento proprio lido.
bruno = [dict(linha(pid=f"{5000+i}", _fresco=False, _pulado=True, autuacao=None,
                    gerador_unidade=None, mov_custodia=None, documentos=None,
                    movimentos=None, acompanhamento=[], acomp_grupos=[],
                    _acomp_fresco=True),
              mesas_conta=[CESS], mesas_falhas=[]) for i in range(5)]
rel = ingerir(gravar("bruno.json", bruno), agente_id=None, coletado_em=iso(AGORA), dono=99)
cx = conectar()
linhas_b = cx.execute("""SELECT p.* FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
                         WHERE s.dono_usuario_id=99""").fetchall()
checar("Bruno tem as 5 linhas da carteira dele", len(linhas_b) == 5, str(len(linhas_b)))
checar("todas vieram do poco", all(l["servido_do_poco"] for l in linhas_b))
checar("e todas tem o detalhe (autuacao) que ele nao leu",
       all(l["autuacao"] == "28/07/2025 08:58" for l in linhas_b))
checar("com os cinco campos derivados para a mesa DELE",
       all(l["marco_unidade"] == "07/08/2026 15:39" for l in linhas_b))
checar("a REGUA das linhas dele e a leitura de Ana, nao a coleta dele",
       all(l["medido_em"] < l["morno_em"] or l["medido_em"] != iso(AGORA)
           for l in linhas_b), str(linhas_b[0]["medido_em"]))
snap = cx.execute("SELECT * FROM snapshot WHERE dono_usuario_id=99").fetchone()
checar("o funil registra 5 servidos e 0 devidos",
       snap["servidos_do_poco"] == 5 and snap["devidos"] == 0,
       f"servidos={snap['servidos_do_poco']} devidos={snap['devidos']}")
checar("e a coleta de Bruno NAO reescreveu o carimbo do poco",
       cx.execute("SELECT COUNT(*) FROM poco_processo WHERE morno_em=?",
                  (iso(AGORA),)).fetchone()[0] == 0)
cx.close()

print("\n12. T1 — a linha de uma mesa nao entra no snapshot de outra")
cx = novo_banco()
cx.execute("DELETE FROM processo"); cx.execute("DELETE FROM snapshot")
cx.execute("DELETE FROM alerta"); cx.commit(); cx.close()
# Coleta ANTIGA, do jeito que o coletor deduplicava: UMA linha, carimbada para a
# primeira mesa, declarando estar aberta nas duas.
antiga = [dict(linha(pid="4001", mesa=CESS), mesas_coleta=[CESS, COMASUP],
               mesas_conta=[CESS, COMASUP], mesas_falhas=[], _fresco=True)]
ingerir(gravar("antiga.json", antiga), coletado_em=iso(AGORA), dono=7)
cx = conectar()
fora = cx.execute("""SELECT COUNT(*) FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
                     WHERE p.mesa_coleta <> s.unidade""").fetchone()[0]
checar("nenhuma linha entra num snapshot de mesa diferente da que a leu",
       fora == 0, str(fora))
checar("e a unidade que ficou sem a linha recebe alerta, em vez de dado alheio",
       cx.execute("SELECT COUNT(*) FROM alerta WHERE tipo='linha_de_outra_mesa'"
                  ).fetchone()[0] == 1)
cx.close()

print("\n13. escalonamento: sessenta contas nao cabem todas as 07:30")
import janelas as _j                                       # noqa: E402
desvios = [_j.desvio_do_agente(i) for i in range(1, 61)]
checar("cada agente tem um desvio proprio, sempre o mesmo",
       _j.desvio_do_agente(7) == _j.desvio_do_agente(7) and len(set(desvios)) > 30,
       f"{len(set(desvios))} desvios distintos em 60")
checar("nenhum desvio ultrapassa a tolerancia (atraso nao vira janela perdida)",
       max(desvios) < _j.DESVIO_MAX_MIN <= 90, str(max(desvios)))
# O DESVIO NAO PODE DEPENDER DO PROCESSO QUE CALCULA.  do Python e
# randomizado por processo desde a 3.3: dois workers do gunicorn discordariam da
# mesma janela. O valor abaixo e o golden do sha256 — se alguem trocar a funcao por
# hash(), ele muda a cada corrida e este teste cai. (Antes havia um
#  aqui que fazia a asserção nunca poder falhar.)
checar("o desvio e o mesmo em qualquer processo (sha256, nao hash())",
       _j.desvio_do_agente(42) == 51, str(_j.desvio_do_agente(42)))
import subprocess as _sp, sys as _sy                                # noqa: E402
_outro = _sp.run([_sy.executable, "-c",
                  "import sys; sys.path.insert(0, r'" + str(Path(__file__).resolve().parent)
                  + "'); import janelas; print(janelas.desvio_do_agente(42))"],
                 capture_output=True, text=True, env={**_os.environ,
                 "PYTHONHASHSEED": "random", "SEI360_DADOS": _os.environ["SEI360_DADOS"]})
checar("e OUTRO processo, com PYTHONHASHSEED aleatorio, chega ao mesmo numero",
       (_outro.stdout or "").strip() == str(_j.desvio_do_agente(42)),
       (_outro.stdout or _outro.stderr)[-120:])
_cfg = {"ativo": 1, "dias": "todos", "tolerancia_min": 90,
        "janelas": '["07:30"]', "motivo_inativo": None, "agente_id": 3}
_dt = datetime.now(TZ).replace(hour=9, minute=0, second=0, microsecond=0)
_devida, _motivo = _j.janela_devida(_cfg, agora_dt=_dt)
# A IDENTIDADE da janela e o horario CONFIGURADO. Quando ela era o horario
# deslocado, `execucao.janela` mudava de valor sem migracao: a coleta ja feita
# deixava de casar, o servidor acusava "janela perdida" contra uma estacao que
# coletou certo, e entregava a mesma carteira de novo.
checar("a janela entregue e a CONFIGURADA — a chave nao se move",
       _devida and _devida[11:16] == "07:30", str(_devida))
checar("e o desvio aparece no motivo, que e onde ele importa",
       "acorda" in (_motivo or ""), str(_motivo))
# ...mas o RELOGIO respeita o desvio: as 07:40 o agente 3 (desvio 20) ainda dorme.
_cedo = datetime.now(TZ).replace(hour=7, minute=31, second=0, microsecond=0)
_d3 = _j.desvio_do_agente(3)
_dev_cedo, _mot_cedo = _j.janela_devida(_cfg, agora_dt=_cedo)
checar(f"as 07:31 o agente de desvio {_d3} min ainda nao e devido",
       (_dev_cedo is None) if _d3 > 1 else (_dev_cedo is not None),
       f"{_dev_cedo} — {_mot_cedo}")
# A TOLERANCIA NAO PODE MOVER A JANELA. Era ela que reabria coleta ja feita.
_tol45 = dict(_cfg, tolerancia_min=45)
checar("mudar a tolerancia NAO muda a identidade da janela",
       _j.janela_devida(_tol45, agora_dt=_dt)[0] == _devida,
       f"{_j.janela_devida(_tol45, agora_dt=_dt)[0]} x {_devida}")
# JANELA NOTURNA: o desvio nao pode empurrar para o dia seguinte, senao ela nunca
# fica devida, nunca vira perdida, e a tela diz "proxima janela" para sempre.
_noite = dict(_cfg, janelas='["23:45"]')
_pares = _j.janelas_do_dia(["23:45"], _dt, 59)
checar("desvio nao atravessa a meia-noite",
       _pares[0][1].date() == _dt.date() and _pares[0][1].hour == 23, str(_pares))
# HORARIO PODRE NAO DERRUBA A VARREDURA DOS OUTROS.
checar("item de horario invalido e ignorado, nao estoura",
       _j.janelas_do_dia(["07h30", "07:30", "", "99:99"], _dt, 0) ==
       _j.janelas_do_dia(["07:30"], _dt, 0), "estourou ou nao filtrou")
_semid = dict(_cfg); _semid.pop("agente_id")
checar("cfg sem agente_id nao quebra (desvio zero)",
       _j.janela_devida(_semid, agora_dt=_dt)[0][11:16] == "07:30")

print("\n14. o poco tem prazo proprio (nao herda o CASCADE do snapshot)")
import expurgo as _exp                                     # noqa: E402
checar("o expurgo conhece o poco", "poco" in _exp.DIAS and "poco_reserva" in _exp.DIAS)
cx = novo_banco()
_velho = iso(AGORA - timedelta(days=_exp.DIAS["poco"] + 10))
poco.publicar(cx, [linha(pid="3001")], dono_usuario_id=7, coletado_em=_velho, instancia=INST)
poco.publicar(cx, [linha(pid="3002")], dono_usuario_id=7, coletado_em=iso(AGORA), instancia=INST)
cx.commit(); cx.close()
_alvos = {linha_[0] for linha_ in _exp.expurgar(simular=True)}
checar("bloco sem leitura ha mais de 90 dias entra no plano de expurgo",
       "poco_processo" in _alvos, str(sorted(_alvos)))
cx = conectar()
checar("simular NAO apaga",
       cx.execute("SELECT COUNT(*) FROM poco_processo").fetchone()[0] == 2)
cx.close()
_exp.expurgar()
cx = conectar()
_restam = [r[0] for r in cx.execute("SELECT id_sei FROM poco_processo ORDER BY id_sei")]
checar("o bloco velho sai e o novo fica", _restam == ["3002"], str(_restam))
checar("a guarda do velho sai junto (sem bloco ela nao responde nada)",
       cx.execute("SELECT COUNT(*) FROM poco_conferencia WHERE id_sei='3001'"
                  ).fetchone()[0] == 0)
checar("e o acompanhamento dele tambem (dado pessoal sem uso)",
       cx.execute("SELECT COUNT(*) FROM poco_acompanhamento WHERE id_sei='3001'"
                  ).fetchone()[0] == 0)
cx.close()

print("\n15. os alertas que cumprem a regra dura")
cx = novo_banco()
cx.execute("DELETE FROM processo"); cx.execute("DELETE FROM snapshot")
cx.execute("DELETE FROM alerta"); cx.commit(); cx.close()

# (a) SESSAO QUE CAI com poco quente: sem o alerta, o snapshot sai com cara de
#     completo. Foi o cenario T5, que ate agora so media o dict do funil.
_mesa_ok = [dict(linha(pid=f"{2000+i}"), mesas_conta=[CESS], mesas_falhas=[])
            for i in range(10)]
ingerir(gravar("t15_ok.json", _mesa_ok), coletado_em=iso(AGORA - timedelta(hours=2)), dono=7)
# agora uma corrida em que so 2 das 10 foram lidas e as outras 8 falharam
_caiu = [dict(linha(pid=f"{2000+i}", _fresco=(i < 2), sem_historico=(i >= 2),
                    autuacao=None if i >= 2 else "28/07/2025 08:58"),
              mesas_conta=[CESS], mesas_falhas=[]) for i in range(10)]
ingerir(gravar("t15_caiu.json", _caiu), coletado_em=iso(AGORA), dono=7)
cx = conectar()
_al = [r["tipo"] for r in cx.execute("SELECT tipo FROM alerta")]
checar("sessao que cai com poco quente ACENDE leitura_incompleta",
       "leitura_incompleta" in _al, str(_al))
_s = cx.execute("""SELECT devidos,lidos_de_fato,servidos_do_poco FROM snapshot
                   WHERE dono_usuario_id=7 ORDER BY id DESC LIMIT 1""").fetchone()
checar("e o funil vai para o snapshot, nao so para o log",
       _s["devidos"] == 10 and _s["lidos_de_fato"] == 2, str(dict(_s)))
cx.close()

# (b) O PLANO MANDOU PULAR E O POCO NAO TEM: nao se inventa linha, e fica dito.
cx = novo_banco()
cx.execute("DELETE FROM processo"); cx.execute("DELETE FROM snapshot")
cx.execute("DELETE FROM alerta"); cx.commit()
_orfaos = [linha(pid=f"{2500+i}", _fresco=False, _pulado=True, autuacao=None,
                 mov_custodia=None) for i in range(3)]
_f = ingestao._costurar(cx, _orfaos, CESS, iso(AGORA), 7, None, INST)
cx.commit()
_al = [r["tipo"] for r in cx.execute("SELECT tipo FROM alerta")]
checar("pulado sem bloco no poco ACENDE poco_sem_bloco", "poco_sem_bloco" in _al, str(_al))
checar("e as linhas entram DITAS como sem historico, nao meio preenchidas",
       all(d.get("sem_historico") == 1 and not d.get("autuacao") for d in _orfaos))
cx.close()

# (c) LEITURA DEGRADADA NAO PUBLICA — a trava que impede uma segunda-feira de
#     layout novo virar 1 alarme e nove snapshots com cara de limpos.
cx = novo_banco()
_ruins = [linha(pid="2900", mesas_fonte="andamento"),
          linha(pid="2901", truncado=True),
          linha(pid="2902", mov_parcial=True),
          linha(pid="2903", documentos=0),
          linha(pid="2904", nivel_acesso="Sigiloso"),
          linha(pid="2905", alterar_disponivel=False)]
_rel = poco.publicar(cx, _ruins, dono_usuario_id=7, coletado_em=iso(AGORA), instancia=INST)
checar("nenhuma leitura degradada vira bloco compartilhado",
       _rel["publicados"] == 0, str(_rel["recusados"]))
checar("e cada recusa tem motivo proprio, nao um balde so",
       len(_rel["recusados"]) == 6, str(sorted(_rel["recusados"])))
cx.close()

print("\n" + "=" * 58)
print(f"{ok} verificações OK, {falhas} falha(s)")
sys.exit(1 if falhas else 0)
