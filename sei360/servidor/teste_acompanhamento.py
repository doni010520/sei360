# -*- coding: utf-8 -*-
"""O módulo de Acompanhamento: lista por pessoa, lida com o login dela.

`copiar=False`: esta suíte semeia tudo o que usa. Copiar o banco de trabalho a
faria depender de uma carteira que pode não existir na árvore — foi o que deixou
`teste_relatorios.py` sem rodar depois da separação do repositório.

    python teste_acompanhamento.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Nenhum teste aqui importa `app` ainda, mas uma tarefa adiante desta suíte vai
# importar — e o laço de fundo do atendente correria contra o banco isolado do
# teste. Desligar já evita a corrida quando esse dia chegar.
os.environ["SEI360_ATENDENTE"] = "0"

from ambiente_teste import isolar          # noqa: E402

isolar(__file__, copiar=False)

import banco                               # noqa: E402
import janelas                             # noqa: E402
from banco import agora, conectar          # noqa: E402
from datetime import timedelta             # noqa: E402

# O "dia seguinte" das cenas de segunda leitura sai do RELÓGIO, não de literal:
# com data fixa, a cena passaria a depender do dia em que a suíte roda — e a
# guarda que ela testa é justamente por DIA.
_ONTEM = (janelas.com_fuso(agora()) - timedelta(days=1)).isoformat(timespec="seconds")

ok, falhas = 0, []


def checar(nome, cond, det=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {det}")


banco.migrar()

print("1. esquema")
_cx = conectar()
_tabelas = {r["name"] for r in _cx.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
checar("a tabela da lista existe", "acompanhado" in _tabelas, str(sorted(_tabelas))[:200])
checar("a tabela do histórico existe", "acompanhado_leitura" in _tabelas)
# `fonte` e `medido_em` são a armadilha do reaproveitamento: dado vindo da
# carteira pode ser de dias atrás, e gravá-lo como "lido hoje" seria mentir no
# carimbo. `aberto_em_fonte` diz se as unidades vieram da ÁRVORE ou da máquina
# de estados do andamento — a segunda errou em 100% dos 1.278 casos observáveis
# medidos em 10/09/2026. "Árvore" aqui é a linha "Processo aberto nas
# unidades: ..." que o próprio SEI publica no topo da árvore, e NÃO a lista
# histórica de unidades dos metadados — que é a que o projeto irmão
# `sei_sistema` corrige computando do andamento.
_cols = {r[1] for r in _cx.execute("PRAGMA table_info(acompanhado_leitura)")}
checar("o histórico sabe de ONDE e de QUANDO é o dado",
       {"fonte", "medido_em", "aberto_em_fonte"} <= _cols, str(sorted(_cols)))
_cx.close()

print("\n1-bis. o que o esquema garante")
import sqlite3                                                   # noqa: E402

_cx = conectar()
_cx.execute("INSERT INTO usuarios(id,email,papel,criado_em,ativo) "
            "VALUES(90,'esquema@teste.local','servidor',?,1)", (agora(),))
_cx.execute("""INSERT INTO acompanhado(usuario_id,instancia,protocolo,origem,
               adicionado_em,estado) VALUES(90,'SEI-SESAB','019.1.2026.1-11',
               'manual',?,'novo')""", (agora(),))
_cx.commit()
try:
    _cx.execute("""INSERT INTO acompanhado(usuario_id,instancia,protocolo,origem,
                   adicionado_em,estado) VALUES(90,'SEI-SESAB','019.1.2026.1-11',
                   'manual',?,'novo')""", (agora(),))
    checar("o mesmo processo não entra duas vezes na lista da pessoa", False,
           "a chave composta deixou duplicar")
except sqlite3.IntegrityError:
    checar("o mesmo processo não entra duas vezes na lista da pessoa", True)
_cx.rollback()

# Estado fora do enum é dado sem sentido; o CHECK existe para ele não entrar.
try:
    _cx.execute("""INSERT INTO acompanhado(usuario_id,instancia,protocolo,origem,
                   adicionado_em,estado) VALUES(90,'SEI-SESAB','019.9.2026.9-99',
                   'manual',?,'inventado')""", (agora(),))
    checar("estado fora do enum é recusado", False, "o CHECK não pegou")
except sqlite3.IntegrityError:
    checar("estado fora do enum é recusado", True)
_cx.rollback()

# A leitura morre com a lista, e a lista morre com a conta.
_cx.execute("""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
               lido_em,fonte) VALUES(90,'SEI-SESAB','019.1.2026.1-11',?,'sei')""",
            (agora(),))
_cx.commit()
_cx.execute("DELETE FROM usuarios WHERE id=90")
_cx.commit()
_sobrou_lista = _cx.execute(
    "SELECT COUNT(*) FROM acompanhado WHERE usuario_id=90").fetchone()[0]
_sobrou_leitura = _cx.execute(
    "SELECT COUNT(*) FROM acompanhado_leitura WHERE usuario_id=90").fetchone()[0]
checar("apagar a conta leva a lista junto", _sobrou_lista == 0, str(_sobrou_lista))
checar("e leva as leituras junto", _sobrou_leitura == 0, str(_sobrou_leitura))
_cx.commit(); _cx.close()

print("\n2. normalizar o número colado")
import acompanhamento as ac                                      # noqa: E402

checar("espaço em volta sai", ac.normalizar("  019.5120.2026.0161681-50 ")
       == "019.5120.2026.0161681-50")
checar("linha vazia é recusada", ac.normalizar("   ") is None)
checar("texto que não é número é recusado", ac.normalizar("processo da Laisa") is None)
# O SEI 4.0 da FESF e o 5.0.4 da SESAB imprimem o mesmo número com pontuação
# diferente; quem cola, cola o que viu.
checar("número sem pontuação passa", ac.normalizar("019512020260161681") is not None)
checar("número curto demais é recusado", ac.normalizar("123") is None)
# O caso que corrompia a chave em silêncio: pontuação colada na ponta.
checar("ponto final colado é recusado, não aceito com o ponto dentro",
       ac.normalizar("019.5120.2026.0161681-50.") is None)
checar("e o mesmo número sem o ponto continua passando",
       ac.normalizar("019.5120.2026.0161681-50") == "019.5120.2026.0161681-50")

# A PONTUAÇÃO É APRESENTAÇÃO, A IDENTIDADE É O DÍGITO. Os dois SEIs imprimem o
# mesmo número com pontuação diferente, e quem cola, cola o que viu.
checar("dígitos são a identidade: pontuação diferente, mesmo processo",
       ac.digitos("019.1111.2026.0000001-11")
       == ac.digitos("01911112026000000111") == "01911112026000000111")
checar("a barra também é pontuação", ac.digitos("019/2403-24") == "019240324")
# `\d` do Python casa dígito Unicode (١٢٣) e `isdigit()` casa até '²'; o espelho
# em SQL não faz nem uma coisa nem outra — ele só tira pontuação. Aceitar número
# que a régua não representa produziria duas linhas com o mesmo `digitos()`
# (vazio), e nenhuma casaria com carteira nenhuma.
checar("dígito que não é ASCII não é número de processo",
       ac.normalizar("١٢٣٤٥٦٧٨٩٠١٢") is None)

print("\n3. adicionar, listar, remover")
_cx = conectar()
_cx.execute("INSERT INTO usuarios(id,email,papel,criado_em,ativo) "
            "VALUES(7,'seguidora@teste.local','servidor',?,1)", (agora(),))
_cx.execute("INSERT INTO usuarios(id,email,papel,criado_em,ativo) "
            "VALUES(8,'outra@teste.local','servidor',?,1)", (agora(),))
_cx.commit()

_aceitos, _recusados = ac.adicionar(_cx, 7, "019.5120.2026.0161681-50", "SEI-SESAB")
checar("um número entra", _aceitos == ["019.5120.2026.0161681-50"] and not _recusados)

_aceitos, _recusados = ac.adicionar(
    _cx, 7, "019.9393.2026.0163871-16\nprocesso da Laisa\n019.2403.2024.0013423-96",
    "SEI-SESAB")
checar("lista de vários: as válidas entram", len(_aceitos) == 2, str(_aceitos))
checar("e a inválida volta com o texto que a pessoa colou",
       _recusados == ["processo da Laisa"], str(_recusados))

_aceitos, _ = ac.adicionar(_cx, 7, "019.5120.2026.0161681-50", "SEI-SESAB")
checar("repetido não duplica nem estoura", _aceitos == [], str(_aceitos))

# O MESMO processo em forma diferente é o mesmo processo. A chave primária é o
# texto do protocolo e não tem como impedir as duas formas de coexistirem; quem
# impede é `adicionar`, comparando os dígitos.
_aceitos, _ = ac.adicionar(_cx, 7, ac.digitos("019.9393.2026.0163871-16"), "SEI-SESAB")
checar("o mesmo número colado sem pontuação não duplica a linha",
       _aceitos == [], str(_aceitos))

_lista = ac.listar(_cx, 7)
checar(f"a lista tem os três ({len(_lista)})", len(_lista) == 3)
checar("todos nascem 'novo'", all(x["estado"] == "novo" for x in _lista))
checar("a lista é da PESSOA: a outra conta vê vazio", ac.listar(_cx, 8) == [])

ac.remover(_cx, 7, "SEI-SESAB", "019.5120.2026.0161681-50")
checar("remover tira da lista", len(ac.listar(_cx, 7)) == 2)

# O teto recusa com o número atual, em vez de descartar em silêncio.
_muitos = "\n".join(f"019.0000.2026.{i:07d}-11" for i in range(ac.TETO + 5))
_aceitos, _recusados = ac.adicionar(_cx, 7, _muitos, "SEI-SESAB")
checar(f"o teto de {ac.TETO} corta", len(ac.listar(_cx, 7)) == ac.TETO,
       str(len(ac.listar(_cx, 7))))
checar("e o que não caber volta como recusado, não some",
       len(_recusados) >= 5, str(len(_recusados)))

# Fronteira entre contas — hoje só testada para `listar`. `remover` e o teto
# também precisam respeitá-la: são as duas outras portas por onde uma conta
# poderia enxergar ou travar a lista de outra.
checar("uma conta não remove da lista de outra",
       (ac.remover(_cx, 8, "SEI-SESAB", "019.9393.2026.0163871-16") or True)
       and any(x["protocolo"] == "019.9393.2026.0163871-16"
               for x in ac.listar(_cx, 7)))
_aceitos8, _recusados8 = ac.adicionar(_cx, 8, "019.8888.2026.0000008-88", "SEI-SESAB")
checar("o teto cheio de uma conta não impede outra de adicionar",
       _aceitos8 == ["019.8888.2026.0000008-88"], str((_aceitos8, _recusados8)))
_cx.commit(); _cx.close()

print("\n4. o delta")
_a = {"aberto_em": ["SESAB/DGESS"], "ultimo_movimento": {"dh": "01/08/2026 10:00"},
      "documentos": 10, "movimentos": 20}
_b = {"aberto_em": ["SESAB/CIR-IBOT"], "ultimo_movimento": {"dh": "09/09/2026 16:00"},
      "documentos": 12, "movimentos": 23}

checar("primeira leitura não tem delta", ac.delta(None, _b) is None)
checar("leitura igual não inventa mudança", ac.delta(_a, dict(_a)) is None)

_d = ac.delta(_a, _b)
checar("saiu de uma unidade e entrou em outra",
       _d["saiu_de"] == ["SESAB/DGESS"] and _d["entrou_em"] == ["SESAB/CIR-IBOT"], str(_d))
checar("documento novo é contado", _d["documentos"] == 2, str(_d))
checar("movimento novo é contado", _d["movimentos"] == 3, str(_d))
checar("o texto da tela sai do delta, não da mão",
       "CIR-IBOT" in ac.texto_do_delta(_d), ac.texto_do_delta(_d))

# A armadilha do desenho: trocar de fonte não é mudança NO PROCESSO.
_c = dict(_a); _c["fonte"] = "sei"
checar("mudar de fonte não aparece como mudança", ac.delta(_a, _c) is None)

# AUSÊNCIA NÃO É CONJUNTO VAZIO. As contagens já eram comparadas com
# `is not None`; as unidades usavam `or []`, e então leitura relatada SEM o campo
# — árvore que não parseou, JSON truncado, campo que a estação não soube
# preencher — dizia que o processo saiu de TODAS as unidades. A estação relata o
# que leu; o que ela não leu não pode virar afirmação.
_sem_campo = {"ultimo_movimento": {"dh": "01/08/2026 10:00"}, "documentos": 10,
              "movimentos": 20}
checar("leitura sem `aberto_em` não afirma que o processo saiu de tudo",
       ac.delta(_a, _sem_campo) is None, str(ac.delta(_a, _sem_campo)))
checar("e anterior sem o campo não inventa entrada em unidade",
       ac.delta(_sem_campo, _a) is None, str(ac.delta(_sem_campo, _a)))
# Mas ausência de unidade não pode calar a mudança que FOI observada.
_sem_campo_mudou = dict(_sem_campo, documentos=12)
checar("ausência de unidades não cala a contagem que mudou",
       ac.delta(_a, _sem_campo_mudou) == {"documentos": 2},
       str(ac.delta(_a, _sem_campo_mudou)))

# `texto_do_delta` existe para o texto nunca ser escrito à mão; ficar muda
# sobre uma mudança real é o mesmo que não existir.
checar("contagem que CAIU também vira texto",
       ac.texto_do_delta({"documentos": -2}) != "")
checar("mudança só de movimentos também vira texto",
       ac.texto_do_delta({"movimentos": 5}) != "")

print("\n5. reaproveitar a carteira")
_cx = conectar()
# A cena do teto, acima, deixou a lista da conta 7 com os 100 itens de
# enchimento. Tirá-los aqui em vez de trocar de conta: é esta conta que tem
# vínculo, coleta e mesa alheia montadas abaixo, e com o teto batido `adicionar`
# recusaria em silêncio tudo o que esta cena precisa ter na lista.
_cx.execute("DELETE FROM acompanhado WHERE usuario_id=7 "
            "AND protocolo LIKE '019.0000.2026.%'")
# Uma coleta plausível: snapshot corrente de uma unidade, com dono, e um processo
# dentro. `medido_em` deliberadamente ANTIGO — é o caso real medido em 10/09/2026,
# em que as 12 unidades estavam com coleta de nove dias úteis antes.
_cx.execute("""INSERT INTO snapshot(id,unidade,coletado_em,estado,dono_usuario_id,
               instancia) VALUES(900,'SESAB/MINHA','2026-08-27T07:45:00-03:00',
               'corrente',7,'SEI-SESAB')""")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,ultimo_movimento,
               documentos,movimentos,medido_em,mesas_fonte)
               VALUES(900,'111','019.1111.2026.0000001-11',
               '{"dh":"20/08/2026 09:00","un":"SESAB/MINHA","de":"Processo recebido"}',
               9,14,'2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'111','SESAB/MINHA',NULL)""")
_cx.execute("INSERT INTO usuario_unidade(usuario_id,unidade,concedida_em) "
            "VALUES(7,'SESAB/MINHA',?)", (agora(),))
# A MESMA coleta, mas de unidade que a conta 7 NÃO alcança.
_cx.execute("""INSERT INTO snapshot(id,unidade,coletado_em,estado,dono_usuario_id,
               instancia) VALUES(901,'SESAB/ALHEIA','2026-08-27T07:45:00-03:00',
               'corrente',8,'SEI-SESAB')""")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,
               movimentos,medido_em,mesas_fonte)
               VALUES(901,'222','019.2222.2026.0000002-22',3,4,
               '2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(901,'222','SESAB/ALHEIA',NULL)""")
_cx.commit()

ac.adicionar(_cx, 7, "019.1111.2026.0000001-11", "SEI-SESAB")
ac.adicionar(_cx, 7, "019.2222.2026.0000002-22", "SEI-SESAB")
_cx.commit()

_n = ac.reaproveitar(_cx, 7, "SEI-SESAB")
_cx.commit()
checar("o processo da minha mesa é respondido pela carteira", _n == 1, str(_n))

_itens = {x["protocolo"]: x for x in ac.listar(_cx, 7)}
_meu = _itens["019.1111.2026.0000001-11"]
checar("e fica com estado lido", _meu["estado"] == "lido", str(_meu["estado"]))
checar("com a fonte dita", _meu["fonte"] == "carteira", str(_meu["fonte"]))
# A armadilha 2: a data é a da MEDIÇÃO, não a de agora.
checar("e com a data da COLETA, não a de agora",
       (_meu["medido_em"] or "").startswith("2026-08-27"), str(_meu["medido_em"]))
checar("as unidades abertas vieram da árvore",
       _meu["aberto_em"] == ["SESAB/MINHA"] and _meu["aberto_em_fonte"] == "arvore",
       str(_meu["aberto_em"]))

# O TESTE QUE MAIS IMPORTA: processo que existe no banco, mas em unidade fora do
# vínculo desta conta, NÃO é reaproveitado. Se este passar a falhar, o módulo
# virou porta lateral na fronteira do sistema.
_alheio = _itens["019.2222.2026.0000002-22"]
checar("processo de mesa ALHEIA não é reaproveitado",
       _alheio["estado"] == "novo" and _alheio["fonte"] is None,
       f"{_alheio['estado']} / {_alheio['fonte']}")
_cx.commit(); _cx.close()

print("\n5-bis. duas mesas minhas, um quadro só")
_cx = conectar()
# `processo_mesa` é a ÁRVORE INTEIRA por linha, não o ângulo da mesa que coletou:
# `ingestao.py` a preenche de `d["mesas"]`, que em `automacao_sei.js` é
# `mesas, // onde esta aberto hoje` — a linha "Processo aberto nas unidades: ..."
# que o SEI publica no topo da árvore. Logo, a linha MAIS FRESCA já tem o quadro
# completo, e somar as linhas não acrescenta unidade: importa bolor.
#
# Aqui a coleta de 28/08 vê o processo em duas unidades; a de 27/08 ainda o via
# numa terceira, de onde ele já saiu. Somar ressuscitaria essa terceira sob a
# contagem e a régua de 28/08 — retrato que nunca existiu — e, pior, calaria o
# `saiu_de` enquanto o snapshot velho vivesse: nove dias úteis, no caso medido em
# 10/09/2026. O evento mais valioso do módulo nunca sairia.
_cx.execute("""INSERT INTO snapshot(id,unidade,coletado_em,estado,dono_usuario_id,
               instancia) VALUES(903,'SESAB/OUTRA-MINHA','2026-08-28T07:45:00-03:00',
               'corrente',7,'SEI-SESAB')""")
_cx.execute("INSERT INTO usuario_unidade(usuario_id,unidade,concedida_em) "
            "VALUES(7,'SESAB/OUTRA-MINHA',?)", (agora(),))
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(903,'444','019.4444.2026.0000004-44',
               5,6,'2026-08-28T07:45:00-03:00','arvore')""")
for _mesa in ("SESAB/MINHA", "SESAB/OUTRA-MINHA"):
    _cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
                   VALUES(903,'444',?,NULL)""", (_mesa,))
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(900,'444','019.4444.2026.0000004-44',
               4,5,'2026-08-27T07:45:00-03:00','arvore')""")
for _mesa in ("SESAB/MINHA", "SESAB/OUTRA-MINHA", "SESAB/JA-SAIU"):
    _cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
                   VALUES(900,'444',?,NULL)""", (_mesa,))
# E um processo da minha carteira cuja coleta não listou mesa NENHUMA: acontece
# quando a linha da árvore não parseou. A leitura existe; a lista é que é vazia.
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(900,'555','019.5555.2026.0000005-55',
               1,2,'2026-08-27T07:45:00-03:00','andamento')""")
_cx.commit()

ac.adicionar(_cx, 7, "019.4444.2026.0000004-44\n019.5555.2026.0000005-55", "SEI-SESAB")
_cx.commit()
_n = ac.reaproveitar(_cx, 7, "SEI-SESAB")
_cx.commit()
checar("os dois novos são respondidos pela carteira", _n == 2, str(_n))

_itens = {x["protocolo"]: x for x in ac.listar(_cx, 7)}
_duas = _itens["019.4444.2026.0000004-44"]
_quantas = _cx.execute(
    "SELECT COUNT(*) FROM acompanhado_leitura WHERE usuario_id=7 AND "
    "protocolo='019.4444.2026.0000004-44'").fetchone()[0]
# Duas leituras da mesma passada fariam a segunda medir o delta contra a
# primeira, recém-inserida: a tela anunciaria movimentação de um processo parado.
checar("processo em duas mesas minhas grava UMA leitura", _quantas == 1, str(_quantas))
checar("o quadro é o da linha escolhida, SEM a unidade de onde o processo saiu",
       _duas["aberto_em"] == ["SESAB/MINHA", "SESAB/OUTRA-MINHA"],
       str(_duas["aberto_em"]))
checar("e contagem e régua vêm da MESMA linha que deu as mesas",
       (_duas["documentos"], _duas["movimentos"]) == (5, 6)
       and (_duas["medido_em"] or "").startswith("2026-08-28"),
       f"{_duas['documentos']}/{_duas['movimentos']} em {_duas['medido_em']}")

# `[]` e `null` NÃO são a mesma coisa aqui: `listar()` devolve None tanto para
# JSON null quanto para item sem leitura nenhuma, então null seria
# indistinguível de "aguardando primeira leitura".
_sem_mesa = _itens["019.5555.2026.0000005-55"]
checar("coleta sem mesa nenhuma deixa aberto_em vazio, não nulo",
       _sem_mesa["aberto_em"] == [] and _sem_mesa["estado"] == "lido",
       f"{_sem_mesa['aberto_em']!r} / {_sem_mesa['estado']}")
checar("e a procedência da lista vazia continua dita",
       _sem_mesa["aberto_em_fonte"] == "andamento", str(_sem_mesa["aberto_em_fonte"]))

# A economia só existe se a segunda passada do dia não refizer o trabalho — e
# reler o mesmo dado gravaria leitura repetida com delta nulo.
checar("rodar de novo no mesmo dia não relê nada",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") == 0)
_cx.commit(); _cx.close()

print("\n5-ter. a instalação não se mistura")
_cx = conectar()
# Vínculo na FESF, com coleta da FESF: unidade que esta conta ALCANÇA. O que não
# se pode é responder com ela um item que a pessoa colou na lista da SESAB — a
# leitura sairia sob `instancia='SEI-SESAB'` com as mesas da FESF dentro, que é o
# carimbo errado que `acompanhado.instancia` nasceu sem DEFAULT para evitar.
_cx.execute("""INSERT INTO snapshot(id,unidade,coletado_em,estado,dono_usuario_id,
               instancia) VALUES(902,'FESF/GABINETE','2026-08-27T07:45:00-03:00',
               'corrente',7,'SEI-FESF')""")
_cx.execute("INSERT INTO usuario_unidade(usuario_id,instancia,unidade,concedida_em) "
            "VALUES(7,'SEI-FESF','FESF/GABINETE',?)", (agora(),))
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(902,'333','019.3333.2026.0000003-33',
               7,8,'2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(902,'333','FESF/GABINETE',NULL)""")
_cx.commit()

ac.adicionar(_cx, 7, "019.3333.2026.0000003-33", "SEI-SESAB")
_cx.commit()
_n = ac.reaproveitar(_cx, 7, "SEI-SESAB")
_cx.commit()
checar("coleta da FESF não responde item da lista da SESAB", _n == 0, str(_n))
_na_sesab = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.3333.2026.0000003-33"]
checar("e o item da SESAB segue esperando leitura",
       _na_sesab["estado"] == "novo" and _na_sesab["fonte"] is None,
       f"{_na_sesab['estado']} / {_na_sesab['fonte']}")

# O contrapeso: o filtro por instalação não pode ser um "nunca responde nada".
ac.adicionar(_cx, 7, "019.3333.2026.0000003-33", "SEI-FESF")
_cx.commit()
checar("a mesma coleta responde a lista da instalação certa",
       ac.reaproveitar(_cx, 7, "SEI-FESF") == 1)
_cx.commit()
_na_fesf = [x for x in ac.listar(_cx, 7)
            if x["protocolo"] == "019.3333.2026.0000003-33"
            and x["instancia"] == "SEI-FESF"][0]
checar("com a mesa da FESF, não a da SESAB",
       _na_fesf["aberto_em"] == ["FESF/GABINETE"], str(_na_fesf["aberto_em"]))
_cx.commit(); _cx.close()

print("\n5-quater. colado sem pontuação, respondido pela carteira")
_cx = conectar()
# A carteira guarda a forma PONTUADA que o SEI imprime; a pessoa colou o número
# corrido, que é o que ela tinha na mão. Casar por texto puro deixava este item
# para sempre no caminho caro do SEI — três requisições por dia — por um dado que
# já estava no banco, medido na coleta da própria mesa dela.
#
# ESTA CENA TEM SÓ A FORMA CORRIDA NA LISTA, de propósito: com a forma pontuada
# também lá, a linha da carteira casaria pelo texto e a comparação por dígitos
# passaria sem ser exercida — foi o que aconteceu na primeira versão deste teste.
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(900,'666','019.6666.2026.0000006-66',
               2,3,'2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'666','SESAB/MINHA',NULL)""")
_cx.commit()

_corrido = "01966662026000000666"
checar("é o mesmo número da carteira, sem a pontuação",
       ac.digitos("019.6666.2026.0000006-66") == _corrido, _corrido)
_aceitos, _ = ac.adicionar(_cx, 7, _corrido, "SEI-SESAB")
checar("o número corrido entra na lista", _aceitos == [_corrido], str(_aceitos))

_n = ac.reaproveitar(_cx, 7, "SEI-SESAB")
_cx.commit()
checar("a carteira responde, apesar de guardar a forma pontuada", _n == 1, str(_n))

_itens = {x["protocolo"]: x for x in ac.listar(_cx, 7)}
_sem_ponto = _itens[_corrido]
checar("o corrido é respondido pela CARTEIRA, não pelo caminho do SEI",
       _sem_ponto["fonte"] == "carteira" and _sem_ponto["estado"] == "lido",
       f"{_sem_ponto['fonte']} / {_sem_ponto['estado']}")
checar("com a mesa e as contagens da linha pontuada",
       _sem_ponto["aberto_em"] == ["SESAB/MINHA"]
       and (_sem_ponto["documentos"], _sem_ponto["movimentos"]) == (2, 3),
       f"{_sem_ponto['aberto_em']} / {_sem_ponto['documentos']}")
# O protocolo guardado continua sendo o que a pessoa colou: é a forma que ela
# reconhece na tela, e é a chave de `acompanhado` — gravar a leitura sob a forma
# da CARTEIRA faria a FK composta recusar, e com razão.
checar("e a lista segue guardando a forma que a pessoa colou",
       _sem_ponto["protocolo"] == _corrido, str(_sem_ponto["protocolo"]))
checar("o id_sei da carteira chega à linha da lista",
       _sem_ponto["id_sei"] == "666", str(_sem_ponto["id_sei"]))
_cx.commit(); _cx.close()

print("\n5-quinquies. as duas formas na mesma lista")
_cx = conectar()
# `adicionar` impede as duas formas de entrarem, mas a chave primária é o TEXTO:
# linha anterior a esta regra, ou inserida fora de `adicionar` (expurgo, shell,
# semeadura), ainda consegue coexistir com a outra forma. Quando coexistem, as
# DUAS são respondidas — ficar com uma deixaria a outra 'novo' para sempre, que é
# justamente o silêncio que este módulo existe para não produzir.
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(900,'777','019.7777.2026.0000007-77',
               4,4,'2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'777','SESAB/MINHA',NULL)""")
_pontuado = "019.7777.2026.0000007-77"
ac.adicionar(_cx, 7, ac.digitos(_pontuado), "SEI-SESAB")
_cx.execute("""INSERT INTO acompanhado(usuario_id,instancia,protocolo,origem,
               adicionado_em,estado) VALUES(7,'SEI-SESAB',?,'manual',?,'novo')""",
            (_pontuado, agora()))
_cx.commit()

_n = ac.reaproveitar(_cx, 7, "SEI-SESAB")
_cx.commit()
checar("as duas formas da mesma linha da carteira são respondidas", _n == 2, str(_n))
_itens = {x["protocolo"]: x for x in ac.listar(_cx, 7)}
checar("e nenhuma das duas fica esperando leitura",
       all(_itens[f]["fonte"] == "carteira" and _itens[f]["estado"] == "lido"
           for f in (_pontuado, ac.digitos(_pontuado))),
       str({f: _itens[f]["estado"] for f in (_pontuado, ac.digitos(_pontuado))}))
_cx.commit(); _cx.close()

print("\n5-sexies. a linha escolhida é a que tem mesa, e a fonte é a DELA")
_cx = conectar()
# Dia em que a árvore não parseou: a coleta mais fresca gravou o processo sem uma
# única linha em `processo_mesa`. A linha de 27/08 tem mesa, vinda da máquina de
# estados do andamento. O quadro é a linha que TEM mesa, INTEIRA — mesa,
# contagem, régua e fonte.
#
# Preferir 'arvore' sobre 'andamento' ENTRE LINHAS diferentes juntaria a mesa de
# uma com a contagem da outra, que é exatamente o defeito que "um momento, um
# quadro" conserta. Se a linha escolhida veio do andamento — que a medição de
# 10/09/2026 mostrou errar em 100% dos 1.278 casos observáveis —, a fonte é
# 'andamento' e a tela marca "não confirmado pela árvore". É para isso que o
# campo existe.
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(903,'888','019.8888.2026.0000008-88',
               9,9,'2026-08-28T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(900,'888','019.8888.2026.0000008-88',
               7,8,'2026-08-27T07:45:00-03:00','andamento')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'888','SESAB/MINHA',NULL)""")
_cx.commit()
ac.adicionar(_cx, 7, "019.8888.2026.0000008-88", "SEI-SESAB")
_cx.commit()
checar("a linha sem mesa não cala a que tem",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") == 1)
_cx.commit()

_escolhida = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.8888.2026.0000008-88"]
checar("a mesa vem da linha que a tinha", _escolhida["aberto_em"] == ["SESAB/MINHA"],
       str(_escolhida["aberto_em"]))
checar("a fonte é a da linha escolhida, sem preferir a árvore de outra",
       _escolhida["aberto_em_fonte"] == "andamento",
       str(_escolhida["aberto_em_fonte"]))
checar("e contagem e régua são as DELA, não as da linha mais fresca sem mesa",
       (_escolhida["documentos"], _escolhida["movimentos"]) == (7, 8)
       and (_escolhida["medido_em"] or "").startswith("2026-08-27"),
       f"{_escolhida['documentos']}/{_escolhida['movimentos']} em {_escolhida['medido_em']}")
_cx.commit(); _cx.close()

print("\n5-septies. a régua é a da LINHA, não a do snapshot")
_cx = conectar()
# O REGIME NORMAL, não a exceção: 92,6% dos processos de uma coleta são servidos
# do poço, então a lista é de hoje e o detalhe é de dias atrás. Aqui a coleta de
# 12/09 traz detalhe medido em 20/08, e a coleta de 27/08 traz detalhe medido em
# 10/09 — a ordem dos snapshots e a ordem das MEDIÇÕES discordam.
#
# Quem responde é a medição mais fresca (10/09), porque é ela que diz onde o
# processo está. Ordenar por `snapshot.coletado_em` pegaria o detalhe de 20/08 sob
# uma lista nova, que é o defeito que `medido_em` existe para não deixar
# acontecer (ver `banco.py`, coluna `medido_em`).
_cx.execute("""INSERT INTO snapshot(id,unidade,coletado_em,estado,dono_usuario_id,
               instancia) VALUES(904,'SESAB/TERCEIRA','2026-09-12T07:45:00-03:00',
               'corrente',7,'SEI-SESAB')""")
_cx.execute("INSERT INTO usuario_unidade(usuario_id,unidade,concedida_em) "
            "VALUES(7,'SESAB/TERCEIRA',?)", (agora(),))
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(904,'999','019.9999.2026.0000009-99',
               1,1,'2026-08-20T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(904,'999','SESAB/TERCEIRA',NULL)""")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(900,'999','019.9999.2026.0000009-99',
               3,3,'2026-09-10T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'999','SESAB/MINHA',NULL)""")
_cx.commit()
ac.adicionar(_cx, 7, "019.9999.2026.0000009-99", "SEI-SESAB")
_cx.commit()
checar("o processo com duas medições é respondido uma vez",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") == 1)
_cx.commit()

_regua = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.9999.2026.0000009-99"]
checar("responde a MEDIÇÃO mais fresca, não o snapshot mais fresco",
       _regua["aberto_em"] == ["SESAB/MINHA"]
       and (_regua["documentos"], _regua["movimentos"]) == (3, 3),
       f"{_regua['aberto_em']} / {_regua['documentos']}")
checar("e o carimbo é a data da medição, não a da coleta",
       (_regua["medido_em"] or "").startswith("2026-09-10"), str(_regua["medido_em"]))
_cx.commit(); _cx.close()

print("\n5-octies. a segunda leitura, com mudança de verdade")
_cx = conectar()
# A FIAÇÃO INTEIRA, de ponta a ponta: `reaproveitar` -> `gravar_leitura` ->
# `delta` -> coluna `mudou` -> `texto_do_delta`. Sem uma cena com SEGUNDA leitura
# e mudança real, `gravar_leitura` podia parar de ler a leitura anterior — delta
# sempre nulo — sem uma única checagem ficar vermelha.
#
# O "dia seguinte" é simulado recuando `lido_em`, que é a guarda de uma leitura
# por dia. As datas saem do relógio (`_ONTEM`/`agora()`) e não de literal: com
# literal, a cena passaria a depender do dia em que a suíte roda.
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,ultimo_movimento,
               documentos,movimentos,medido_em,mesas_fonte)
               VALUES(900,'1212','019.1212.2026.0000012-12',
               '{"dh":"05/09/2026 08:00","un":"SESAB/MINHA","de":"Processo recebido"}',
               5,7,?,'arvore')""", (_ONTEM,))
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'1212','SESAB/MINHA',NULL)""")
_cx.commit()
ac.adicionar(_cx, 7, "019.1212.2026.0000012-12", "SEI-SESAB")
_cx.commit()
checar("a primeira leitura acontece", ac.reaproveitar(_cx, 7, "SEI-SESAB") == 1)
_cx.commit()
_primeira = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.1212.2026.0000012-12"]
checar("e não anuncia mudança, porque não houve observação anterior",
       _primeira["mudou"] is None, str(_primeira["mudou"]))

# A coleta de hoje: o processo saiu da minha mesa para a outra, ganhou dois
# documentos e três movimentos. Mexer na linha em vez de ingerir um snapshot novo
# é de propósito — a ingestão tem suíte própria; aqui o que está sob teste é a
# SEGUNDA leitura.
_cx.execute("UPDATE acompanhado SET lido_em=? WHERE usuario_id=7 AND protocolo=?",
            (_ONTEM, "019.1212.2026.0000012-12"))
_cx.execute("DELETE FROM processo_mesa WHERE snapshot_id=900 AND id_sei='1212'")
_cx.execute("DELETE FROM processo WHERE snapshot_id=900 AND id_sei='1212'")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,ultimo_movimento,
               documentos,movimentos,medido_em,mesas_fonte)
               VALUES(903,'1212','019.1212.2026.0000012-12',
               '{"dh":"11/09/2026 09:30","un":"SESAB/OUTRA-MINHA","de":"Processo recebido"}',
               7,10,?,'arvore')""", (agora(),))
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(903,'1212','SESAB/OUTRA-MINHA',NULL)""")
_cx.commit()
checar("a segunda leitura acontece", ac.reaproveitar(_cx, 7, "SEI-SESAB") == 1)
_cx.commit()

_segunda = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.1212.2026.0000012-12"]
_quantas = _cx.execute("SELECT COUNT(*) FROM acompanhado_leitura WHERE usuario_id=7 "
                       "AND protocolo='019.1212.2026.0000012-12'").fetchone()[0]
checar("a série temporal ganhou a segunda linha", _quantas == 2, str(_quantas))
# O evento mais valioso do módulo, e o que a soma de mesas calava.
checar("o `saiu_de` sai", (_segunda["mudou"] or {}).get("saiu_de") == ["SESAB/MINHA"],
       str(_segunda["mudou"]))
checar("e o `entrou_em` também",
       (_segunda["mudou"] or {}).get("entrou_em") == ["SESAB/OUTRA-MINHA"],
       str(_segunda["mudou"]))
checar("com as contagens medidas, não escritas à mão",
       (_segunda["mudou"] or {}).get("documentos") == 2
       and (_segunda["mudou"] or {}).get("movimentos") == 3, str(_segunda["mudou"]))
checar("e o texto da tela sai desse delta",
       "OUTRA-MINHA" in ac.texto_do_delta(_segunda["mudou"])
       and "+2 documentos" in ac.texto_do_delta(_segunda["mudou"]),
       ac.texto_do_delta(_segunda["mudou"]))
_cx.commit(); _cx.close()

print("\n5-novies. medição que anda para trás não vira perda")
_cx = conectar()
# O CENÁRIO MEDIDO: o processo saiu da mesa de OUTRA-MINHA, e sobra a linha velha
# de MINHA. Sem guarda, a leitura de hoje seria comparada com a de ontem por
# ORDEM DE INSERÇÃO, e a tela anunciaria "saiu de OUTRA-MINHA · -2 documentos ·
# -3 movimentos" — perda que nunca houve, só dado mais velho respondendo.
#
# Pior com fonte mista, que é como a leitura no SEI vai chamar: leitura do SEI
# hoje e, amanhã, a carteira de nove dias atrás responde primeiro, porque a
# guarda de "não lido hoje" é por DIA e não por frescor. O processo voltaria no
# tempo na tela, com movimentação inventada nas duas direções.
#
# A doutrina é a que `delta()` já aplica à primeira leitura: não anunciar mudança
# onde não houve observação NOVA. A leitura é gravada — a tela precisa saber que
# o dado é de ontem —, mas `mudou` fica nulo.
_cx.execute("UPDATE acompanhado SET lido_em=? WHERE usuario_id=7 AND protocolo=?",
            (_ONTEM, "019.1212.2026.0000012-12"))
_cx.execute("DELETE FROM processo_mesa WHERE snapshot_id=903 AND id_sei='1212'")
_cx.execute("DELETE FROM processo WHERE snapshot_id=903 AND id_sei='1212'")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,ultimo_movimento,
               documentos,movimentos,medido_em,mesas_fonte)
               VALUES(900,'1212','019.1212.2026.0000012-12',
               '{"dh":"05/09/2026 08:00","un":"SESAB/MINHA","de":"Processo recebido"}',
               5,7,?,'arvore')""", (_ONTEM,))
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'1212','SESAB/MINHA',NULL)""")
_cx.commit()
checar("a leitura mais velha ainda é gravada",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") == 1)
_cx.commit()

_terceira = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.1212.2026.0000012-12"]
checar("mas não anuncia mudança nenhuma", _terceira["mudou"] is None,
       str(_terceira["mudou"]))
checar("e o texto da tela fica em silêncio", ac.texto_do_delta(_terceira["mudou"]) == "",
       ac.texto_do_delta(_terceira["mudou"]))
# A guarda é sobre ANUNCIAR, não sobre esconder: a data volta a ser a de ontem, e
# é assim que a tela diz de quando é o dado que está mostrando.
checar("a procedência mostra que o dado voltou a ser o de ontem",
       (_terceira["medido_em"] or "")[:10] == _ONTEM[:10], str(_terceira["medido_em"]))
_cx.commit(); _cx.close()

print("\n5-decies. barra e espaço no número da carteira")
_cx = conectar()
# O NÚMERO DA FESF TEM BARRA: `0016.000251/2026-62`. Se o espelho em SQL deixar
# de tirar a barra, a instalação inteira sai do caminho da carteira em silêncio —
# todo item da FESF passaria a gastar requisição no SEI por um dado já coletado.
# O espaço é o outro caso: a pessoa não consegue colar um (o regex recusa), mas
# ele aparece no texto que o SEI imprime.
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(902,'251','0016.000251/2026-62',
               1,1,'2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(902,'251','FESF/GABINETE',NULL)""")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(902,'252','0016.000252/2026 -63',
               2,2,'2026-08-27T07:45:00-03:00','arvore')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(902,'252','FESF/GABINETE',NULL)""")
_cx.commit()
_com_barra, _com_espaco = "0016000251202662", "0016000252202663"
checar("os dois números corridos são os da carteira",
       ac.digitos("0016.000251/2026-62") == _com_barra
       and ac.digitos("0016.000252/2026 -63") == _com_espaco,
       f"{_com_barra} / {_com_espaco}")
ac.adicionar(_cx, 7, f"{_com_barra}\n{_com_espaco}", "SEI-FESF")
_cx.commit()
checar("a carteira da FESF responde os dois",
       ac.reaproveitar(_cx, 7, "SEI-FESF") == 2)
_cx.commit()
_fesf = {x["protocolo"]: x for x in ac.listar(_cx, 7)}
checar("o de barra veio da carteira",
       _fesf[_com_barra]["fonte"] == "carteira"
       and _fesf[_com_barra]["aberto_em"] == ["FESF/GABINETE"],
       f"{_fesf[_com_barra]['fonte']} / {_fesf[_com_barra]['aberto_em']}")
checar("e o de espaço também",
       _fesf[_com_espaco]["fonte"] == "carteira"
       and _fesf[_com_espaco]["aberto_em"] == ["FESF/GABINETE"],
       f"{_fesf[_com_espaco]['fonte']} / {_fesf[_com_espaco]['aberto_em']}")
_cx.commit(); _cx.close()

print("\n5-undecies. empate na medição, e o desempate")
_cx = conectar()
# A OUTRA METADE DA ORDEM — a primeira está em 5-septies. Com "a primeira linha
# vence", empate em `medido_em` (duas coletas no mesmo segundo é plausível)
# deixaria o quadro INDETERMINADO: a mesma pessoa recarregando a tela veria
# contagens diferentes sem nada ter mudado no SEI. O desempate por `s.id` é o que
# faz a resposta ser a mesma toda vez, e o id maior é a coleta mais nova.
_empate = "2026-09-05T07:45:00-03:00"
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(900,'1313','019.1313.2026.0000013-13',
               1,1,?,'arvore')""", (_empate,))
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'1313','SESAB/MINHA',NULL)""")
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,movimentos,
               medido_em,mesas_fonte) VALUES(903,'1313','019.1313.2026.0000013-13',
               2,2,?,'arvore')""", (_empate,))
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(903,'1313','SESAB/OUTRA-MINHA',NULL)""")
_cx.commit()
ac.adicionar(_cx, 7, "019.1313.2026.0000013-13", "SEI-SESAB")
_cx.commit()
checar("o empate é respondido uma vez", ac.reaproveitar(_cx, 7, "SEI-SESAB") == 1)
_cx.commit()

_desempate = {x["protocolo"]: x
              for x in ac.listar(_cx, 7)}["019.1313.2026.0000013-13"]
checar("no empate vence o snapshot de id maior, e vence sempre",
       _desempate["aberto_em"] == ["SESAB/OUTRA-MINHA"]
       and (_desempate["documentos"], _desempate["movimentos"]) == (2, 2),
       f"{_desempate['aberto_em']} / {_desempate['documentos']}")
_cx.commit(); _cx.close()

print("\n6. a porta no menu")
import portas                                                    # noqa: E402

_ids = [p["id"] for p in portas.PORTAS]
checar("existe a porta de acompanhamento", "acompanhamento" in _ids, str(_ids))
checar("ela vem depois da busca e antes dos relatórios",
       _ids.index("busca") < _ids.index("acompanhamento") < _ids.index("relatorios"),
       str(_ids))
checar("todo papel logado a vê",
       all("acompanhamento" in [p["id"] for p in portas.visiveis(pap)]
           for pap in ("servidor", "gestor", "admin")))
checar("e ela tem ícone próprio", bool(portas._ICONES.get("acompanhamento")))

print("\n7. a tela")
import app as A                                                  # noqa: E402
A.app.config["TESTING"] = True
_c = A.app.test_client()

# Sessão da conta 7, direto no banco: o caminho de login já tem suíte própria.
# `senha_trocada_em` não é detalhe — sem ele `exige_login` manda a pessoa para
# `/primeiro_acesso`, e toda rota responderia 302 em vez de abrir. É o mesmo
# cuidado que `teste_busca.py` já toma ao montar sessão pela tabela.
import secrets as _sec                                           # noqa: E402
import seguranca as _seg                                         # noqa: E402
_tok = _sec.token_urlsafe(32)
_cx = conectar()
_cx.execute("""INSERT INTO sessoes(usuario_id,token_sha256,criado_em,ultimo_uso_em,
               expira_em) VALUES(7,?,?,?,'2099-01-01T00:00:00-03:00')""",
            (_seg.hash_token(_tok), agora(), agora()))
_cx.execute("UPDATE usuarios SET senha_trocada_em=? WHERE id=7", (agora(),))
_cx.commit(); _cx.close()
_c.set_cookie("sei360_sess", _tok, domain="localhost")

_r = _c.get("/acompanhamento")
checar("a tela abre", _r.status_code == 200, str(_r.status_code))
_corpo = _r.data.decode("utf-8", "replace")
# O CSRF sai da PRÓPRIA tela, que é de onde o script dela o tira: um token
# pescado de outra rota testaria um caminho que o navegador não percorre.
#
# E TEM DE SER RELIDO a cada resposta: toda renderização da tela rotaciona o
# cookie, então guardar o primeiro e reusá-lo faz o POST seguinte levar token
# velho e levar 400 — um caminho que o navegador nunca percorre, porque o script
# da tela lê o cookie na hora de enviar.
def _csrf_do(resp, atual):
    bruto = resp.headers.get("Set-Cookie") or ""
    if "sei360_csrf=" in bruto:
        return bruto.split("sei360_csrf=")[1].split(";")[0]
    return atual


_csrf = _csrf_do(_r, "")
checar("e deixa o CSRF da tela no cookie", bool(_csrf),
       (_r.headers.get("Set-Cookie") or "")[:60])

checar("lista o que a pessoa segue", "019.1111.2026.0000001-11" in _corpo)
checar("mostra a procedência do dado da carteira, não 'lido hoje'",
       "27/08" in _corpo, "a data da coleta tem de aparecer")
checar("NÃO mostra o processo de mesa alheia como lido",
       "019.2222.2026.0000002-22" in _corpo
       and "aguardando primeira leitura" in _corpo)
# Sem isto a pessoa perde a única pista de onde está — é o que `_nav.html`
# documenta sobre `pagina`.
checar("o menu marca a porta de acompanhamento",
       'class="lat-i on" href="/acompanhamento"' in _corpo,
       "a porta ativa não ficou marcada")

# A LISTA É DAS DUAS INSTALAÇÕES, e `reaproveitar` é POR instalação. A
# configuração ativa da conta 7 é a SESAB (é o padrão de `cfgmod.ler`): se a tela
# reaproveitasse só a ativa, o item da FESF ficaria "aguardando primeira leitura"
# com a resposta pronta na coleta da FESF — dizer que não se leu o que está no
# banco é o defeito que este módulo existe para não cometer.
_cx = conectar()
_cx.execute("""UPDATE acompanhado SET estado='novo', lido_em=NULL
               WHERE usuario_id=7 AND instancia='SEI-FESF'
                 AND protocolo='019.3333.2026.0000003-33'""")
_cx.commit(); _cx.close()
_r = _c.get("/acompanhamento")
_csrf = _csrf_do(_r, _csrf)
_da_fesf = [x for x in ac.listar(conectar(), 7)
            if x["instancia"] == "SEI-FESF"
            and x["protocolo"] == "019.3333.2026.0000003-33"][0]
checar("a tela reaproveita também a instalação que NÃO é a ativa",
       _da_fesf["estado"] == "lido" and _da_fesf["fonte"] == "carteira",
       f"{_da_fesf['estado']} / {_da_fesf['fonte']}")

# NÚMERO NOVO, não um que a suíte já usou: com `019.7777...` — que entra na
# lista na cena 5-quinquies — a checagem "e o processo entrou" ficava VERDE antes
# de a rota existir, e a de remoção falhava por já haver a outra forma do mesmo
# número. Fixture reaproveitado de outra cena testa a outra cena.
_r = _c.post("/acompanhamento/adicionar",
             data={"csrf": _csrf, "numeros": "019.1414.2026.0000014-14"})
checar("adicionar pela tela funciona", _r.status_code in (200, 302), str(_r.status_code))
checar("e o processo entrou", any(
    x["protocolo"] == "019.1414.2026.0000014-14" for x in ac.listar(conectar(), 7)))

_csrf = _csrf_do(_r, _csrf)
_r = _c.post("/acompanhamento/remover",
             data={"csrf": _csrf, "protocolo": "019.1414.2026.0000014-14",
                   "instancia": "SEI-SESAB"})
checar("remover pela tela funciona", _r.status_code in (200, 302))
checar("e o processo saiu", not any(
    x["protocolo"] == "019.1414.2026.0000014-14" for x in ac.listar(conectar(), 7)))

# A FRONTEIRA DA ROTA: `usuario_id` só pode vir da SESSÃO. A camada de regra
# confia no chamador de propósito — ela recebe o `usuario_id` e obedece —, então
# a porta é aqui. Se um campo de formulário pudesse dizer de quem é a lista,
# qualquer conta logada apagaria a lista de qualquer outra.
#
# As duas contas seguem o MESMO número (a 8 desde a cena 3, a 7 desde a
# 5-sexies), então a checagem distingue de verdade quem foi tocado.
_csrf = _csrf_do(_r, _csrf)
_r = _c.post("/acompanhamento/remover",
             data={"csrf": _csrf, "usuario_id": "8", "usuario": "8",
                   "protocolo": "019.8888.2026.0000008-88", "instancia": "SEI-SESAB"})
checar("usuario_id no formulário não toca na lista de outra conta",
       any(x["protocolo"] == "019.8888.2026.0000008-88"
           for x in ac.listar(conectar(), 8)),
       "a rota leu o usuario_id do cliente")
checar("e quem perdeu a linha foi a conta da SESSÃO",
       not any(x["protocolo"] == "019.8888.2026.0000008-88"
               for x in ac.listar(conectar(), 7)))

# ESCRITA NO CAMINHO DE UMA LEITURA. `reaproveitar` roda dentro do GET para a
# tela não dizer "aguardando primeira leitura" sobre processo que a coleta já
# leu. Se ele tropeçar — banco travado, snapshot meio ingerido —, a pessoa tem
# de ver a lista de qualquer jeito: a lista é o produto, o reaproveitamento é o
# atalho.
_reaproveitar_real = ac.reaproveitar


def _explode(*a, **k):
    raise RuntimeError("coleta ruim")


ac.reaproveitar = _explode
try:
    _r = _c.get("/acompanhamento")
finally:
    ac.reaproveitar = _reaproveitar_real
checar("reaproveitamento que falha não deixa a tela em branco",
       _r.status_code == 200
       and "019.1111.2026.0000001-11" in _r.data.decode("utf-8", "replace"),
       str(_r.status_code))

print("\n7-bis. o módulo não invadiu a carteira")
import relatorios as _rel                                        # noqa: E402

_cx = conectar()
_uns7 = A.unidades_do(7)
_cart = A.carteira(_uns7, 7)
checar("processo acompanhado de FORA não entra na carteira",
       not any(x.get("protocolo") == "019.2222.2026.0000002-22" for x in _cart),
       "o modulo virou carteira")
_dados_rel = _rel.carregar(_uns7, 7)
checar("nem em relatorios.carregar()",
       not any(d["protocolo"] == "019.2222.2026.0000002-22" for d in _dados_rel))
checar("e a carteira continua trazendo o que é dela",
       any(x.get("protocolo") == "019.1111.2026.0000001-11" for x in _cart))

# Checagem 13 do desenho: processo que SAI da mesa não é mais respondido pela
# carteira — fica esperando quem vá ao SEI. Com `ac.pendentes` (tarefa 8) isto
# se diz numa linha; até lá, o fato se prova pelo que existe: a carteira devolve
# zero e o item continua 'novo'.
_cx.execute("UPDATE snapshot SET estado='expirado' WHERE id=900")
_cx.execute("""UPDATE acompanhado SET lido_em=NULL, estado='novo'
               WHERE protocolo='019.1111.2026.0000001-11'""")
_cx.commit()
checar("processo que saiu da mesa não é mais respondido pela carteira",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") == 0)
_item_fora = {x["protocolo"]: x
              for x in ac.listar(_cx, 7)}["019.1111.2026.0000001-11"]
checar("e fica esperando a leitura de quem for ao SEI",
       _item_fora["estado"] == "novo", str(_item_fora["estado"]))
_cx.execute("UPDATE snapshot SET estado='corrente' WHERE id=900")
_cx.commit(); _cx.close()

print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
