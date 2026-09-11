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
from banco import agora, conectar          # noqa: E402

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

print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
