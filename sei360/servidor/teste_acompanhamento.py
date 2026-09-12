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
# A cena da tela IMPORTA `app`, e importar `app` acende os laços de fundo: o do
# atendente e o de `coleta_servidor`. Os dois correriam contra o banco isolado
# desta suíte — que é temporário e some no fim —, então ficam desligados aqui.
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
_ANTEONTEM = (janelas.com_fuso(agora()) - timedelta(days=2)).isoformat(timespec="seconds")

ok, falhas = 0, []


def checar(nome, cond, det=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {det}")


def cartao(corpo, protocolo):
    """O trecho do cartão DAQUELE processo, do número dele até o próximo cartão.

    Checagem por página é conjunção de fatos soltos, e engana: "não mostra o
    alheio como lido" ficava VERDE com a etiqueta de espera aplicada a TODO
    item, porque as duas metades da conjunção eram verdade em cartões
    diferentes. Afirmação sobre a linha se faz sobre a linha.
    """
    alvo = f'<span class="mono" style="font-size:13px">{protocolo}</span>'
    i = corpo.find(alvo)
    if i < 0:
        return ""
    fim = corpo.find('<div class="cartao"', i)
    return corpo[i:fim] if fim > 0 else corpo[i:]


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

_aceitos, _recusados, _sem_espaco = ac.adicionar(
    _cx, 7, "019.5120.2026.0161681-50", "SEI-SESAB")
checar("um número entra", _aceitos == ["019.5120.2026.0161681-50"]
       and not _recusados and not _sem_espaco)

_aceitos, _recusados, _sem_espaco = ac.adicionar(
    _cx, 7, "019.9393.2026.0163871-16\nprocesso da Laisa\n019.2403.2024.0013423-96",
    "SEI-SESAB")
checar("lista de vários: as válidas entram", len(_aceitos) == 2, str(_aceitos))
checar("e a inválida volta com o texto que a pessoa colou",
       _recusados == ["processo da Laisa"], str(_recusados))

_aceitos, _, _ = ac.adicionar(_cx, 7, "019.5120.2026.0161681-50", "SEI-SESAB")
checar("repetido não duplica nem estoura", _aceitos == [], str(_aceitos))

# O MESMO processo em forma diferente é o mesmo processo. A chave primária é o
# texto do protocolo e não tem como impedir as duas formas de coexistirem; quem
# impede é `adicionar`, comparando os dígitos.
_aceitos, _, _ = ac.adicionar(_cx, 7, ac.digitos("019.9393.2026.0163871-16"),
                              "SEI-SESAB")
checar("o mesmo número colado sem pontuação não duplica a linha",
       _aceitos == [], str(_aceitos))

_lista = ac.listar(_cx, 7)
checar(f"a lista tem os três ({len(_lista)})", len(_lista) == 3)
checar("todos nascem 'novo'", all(x["estado"] == "novo" for x in _lista))
checar("a lista é da PESSOA: a outra conta vê vazio", ac.listar(_cx, 8) == [])

_saiu = ac.remover(_cx, 7, "SEI-SESAB", "019.5120.2026.0161681-50")
checar("remover tira da lista", len(ac.listar(_cx, 7)) == 2)
# Quem escreve o log precisa saber se houve ato: `registrar` é a resposta de
# "quem fez o quê" num incidente, e gravar remoção de protocolo que não estava
# na lista afirma um ato que não aconteceu.
checar("e diz quantas linhas saíram", _saiu == 1, str(_saiu))
checar("remover o que não está na lista devolve zero",
       ac.remover(_cx, 7, "SEI-SESAB", "019.0000.0000.0000000-00") == 0)

# O teto recusa com o número atual, em vez de descartar em silêncio.
_muitos = "\n".join(f"019.0000.2026.{i:07d}-11" for i in range(ac.TETO + 5))
_aceitos, _recusados, _sem_espaco = ac.adicionar(_cx, 7, _muitos, "SEI-SESAB")
checar(f"o teto de {ac.TETO} corta", len(ac.listar(_cx, 7)) == ac.TETO,
       str(len(ac.listar(_cx, 7))))
# MOTIVO SEPARADO, não um balde só. A linha barrada pelo teto voltava junto
# das malformadas, e a tela carimbava nela "não parecem número de processo":
# a pessoa ia conferir o dígito de um número correto em vez de abrir espaço.
checar("e o que não caber volta como SEM ESPAÇO, não some",
       len(_sem_espaco) >= 5, str(len(_sem_espaco)))
checar("número válido barrado pelo teto não vira número inválido",
       _recusados == [], str(_recusados))

# Fronteira entre contas — hoje só testada para `listar`. `remover` e o teto
# também precisam respeitá-la: são as duas outras portas por onde uma conta
# poderia enxergar ou travar a lista de outra.
checar("uma conta não remove da lista de outra",
       (ac.remover(_cx, 8, "SEI-SESAB", "019.9393.2026.0163871-16") or True)
       and any(x["protocolo"] == "019.9393.2026.0163871-16"
               for x in ac.listar(_cx, 7)))
_aceitos8, _recusados8, _ = ac.adicionar(_cx, 8, "019.8888.2026.0000008-88",
                                         "SEI-SESAB")
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

print("\n4-bis. a procedência em texto")
# A tela dizia "Nada foi lido" e, embaixo, "pela sua coleta de 11/09" — duas
# afirmações contrárias no mesmo cartão. E imprimia dia/mês sem ano: dado de
# 11/09/2025 saía idêntico ao de hoje, que não é hipótese remota com uma coleta
# parada. A procedência é texto gerado do dado, como `texto_do_delta`.
_proc = {"estado": "lido", "fonte": "carteira",
         "medido_em": "2026-08-27T07:45:00-03:00",
         "leitura_em": "2026-09-11T09:00:00-03:00"}
checar("dado da carteira diz a data da COLETA",
       ac.texto_da_procedencia(_proc, "2026") == "pela sua coleta de 27/08",
       ac.texto_da_procedencia(_proc, "2026"))
checar("leitura no SEI diz a data da LEITURA",
       ac.texto_da_procedencia(dict(_proc, fonte="sei"), "2026")
       == "lido no SEI em 11/09")
checar("ano que não é o corrente aparece",
       ac.texto_da_procedencia(_proc, "2027") == "pela sua coleta de 27/08/2026",
       ac.texto_da_procedencia(_proc, "2027"))
checar("estado de recusa não ganha procedência",
       ac.texto_da_procedencia(dict(_proc, estado="sem_acesso"), "2026") == "")
checar("sem data não se inventa procedência",
       ac.texto_da_procedencia(dict(_proc, medido_em=None), "2026") == "")
checar("e item nunca lido também não",
       ac.texto_da_procedencia({"estado": "novo"}, "2026") == "")

# `medido_em` é documentado como obrigatório desde que a reserva silenciosa em
# `agora()` saiu. Promessa que o código não impõe é comentário, não regra — e o
# leitor do SEI da fase 2 é o chamador natural de um `medido_em` vazio.
_cx = conectar()
try:
    ac.gravar_leitura(_cx, 90, "SEI-SESAB", "019.1.2026.1-11", {}, "sei", None)
    checar("gravar_leitura recusa medido_em vazio", False, "aceitou")
except ValueError:
    checar("gravar_leitura recusa medido_em vazio", True)
_cx.rollback(); _cx.close()

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
# `mudou` nulo cobria TRÊS situações e a tela afirmava a terceira para todas:
# primeira leitura, medição que não avançou, e comparação sem mudança. A
# coluna diz qual foi — é o mesmo motivo de `fonte` e `medido_em` existirem.
checar("a primeira leitura se declara primeira, e não sem mudança",
       _meu["comparacao"] == "primeira" and _meu["mudou"] is None,
       str(_meu["comparacao"]))

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
_aceitos, _, _ = ac.adicionar(_cx, 7, _corrido, "SEI-SESAB")
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
               5,7,?,'arvore')""", (_ANTEONTEM,))
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
checar("e a leitura se declara PRIMEIRA",
       _primeira["comparacao"] == "primeira", str(_primeira["comparacao"]))

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
               7,10,?,'arvore')""", (_ONTEM,))
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
checar("e a leitura se declara COMPARADA",
       _segunda["comparacao"] == "comparada", str(_segunda["comparacao"]))

# A TERCEIRA leitura: medição mais nova (hoje) e dado IDÊNTICO. É o único caso em
# que "sem mudança" é verdade — e era a frase que a tela imprimia para os quatro.
_cx.execute("UPDATE acompanhado SET lido_em=? WHERE usuario_id=7 AND protocolo=?",
            (_ONTEM, "019.1212.2026.0000012-12"))
_cx.execute("UPDATE processo SET medido_em=? WHERE snapshot_id=903 AND id_sei='1212'",
            (agora(),))
_cx.commit()
checar("a terceira leitura acontece", ac.reaproveitar(_cx, 7, "SEI-SESAB") == 1)
_cx.commit()
_igual = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.1212.2026.0000012-12"]
checar("comparou de novo e nada mudou — aqui 'sem mudança' é verdade",
       _igual["comparacao"] == "comparada" and _igual["mudou"] is None,
       f"{_igual['comparacao']} / {_igual['mudou']}")
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
checar("e a leitura diz que a medição NÃO AVANÇOU, que é outra coisa",
       _terceira["comparacao"] == "sem_avanco", str(_terceira["comparacao"]))
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

# UM ITEM COM MUDANÇA DE VERDADE na tela. A linha do delta é o produto do
# módulo, e apagar `{{ x.texto_mudou }}` do template passava sem uma checagem
# vermelha. A "coleta de hoje" traz três documentos novos no processo da cena
# 5-undecies, e é o reaproveitamento DA PRÓPRIA TELA que vai medir isso.
_cx = conectar()
_cx.execute("UPDATE acompanhado SET lido_em=? WHERE usuario_id=7 AND protocolo=?",
            (_ONTEM, "019.1313.2026.0000013-13"))
_cx.execute("UPDATE processo SET documentos=5, medido_em=? "
            "WHERE snapshot_id=903 AND id_sei='1313'", (agora(),))
_cx.commit(); _cx.close()

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
# POR CARTÃO, não por página. A versão anterior desta checagem era a conjunção
# de dois fatos da PÁGINA — o número aparece, e a etiqueta de espera aparece —,
# e ficava verde mesmo se a etiqueta fosse aplicada a todos os itens, inclusive
# aos lidos. Dez mutações do template sobreviviam a este bloco, entre elas
# apagar as unidades onde o processo está aberto, que é o produto do módulo.
_meu_cartao = cartao(_corpo, "019.1111.2026.0000001-11")
_alheio_cartao = cartao(_corpo, "019.2222.2026.0000002-22")
checar("o cartão do processo da minha mesa existe", bool(_meu_cartao))
checar("e diz EM QUE UNIDADES o processo está aberto",
       "aberto em" in _meu_cartao and "MINHA" in _meu_cartao, _meu_cartao[:160])
checar("com a procedência no próprio cartão",
       "pela sua coleta de 27/08" in _meu_cartao, _meu_cartao[:160])
checar("e sem afirmar que não mudou, porque foi a primeira observação",
       "nada a comparar ainda" in _meu_cartao and "sem mudança" not in _meu_cartao,
       _meu_cartao[:160])

checar("o cartão do processo de mesa alheia aguarda leitura",
       "aguardando primeira leitura" in _alheio_cartao, _alheio_cartao[:160])
checar("e NÃO afirma unidade nenhuma sobre ele",
       "aberto em" not in _alheio_cartao, _alheio_cartao[:160])
checar("nem procedência, porque não houve leitura",
       "pela sua coleta" not in _alheio_cartao, _alheio_cartao[:160])

# As outras três formas de cartão, cada uma com a razão de existir:
_mudou_cartao = cartao(_corpo, "019.1313.2026.0000013-13")
checar("o cartão de quem mudou mostra o texto do delta",
       "+3 documentos" in _mudou_cartao, _mudou_cartao[:200])
_vazio_cartao = cartao(_corpo, "019.5555.2026.0000005-55")
checar("leitura sem unidade nenhuma diz isso, em vez de parecer nunca lida",
       "não trouxe unidade nenhuma" in _vazio_cartao, _vazio_cartao[:200])
_andamento_cartao = cartao(_corpo, "019.8888.2026.0000008-88")
checar("unidade vinda do andamento vem com o aviso da árvore",
       "não confirmado pela árvore" in _andamento_cartao, _andamento_cartao[:200])

# A leitura da lista entra no log: `registrar` é o que responde "quem viu o quê"
# num incidente, e é promessa da docstring dele em `banco.py`.
_viu = conectar().execute(
    "SELECT alvo FROM log_acesso WHERE usuario_id=7 AND acao='ver_acompanhamento' "
    "ORDER BY id DESC LIMIT 1").fetchone()
checar("abrir a tela fica registrado no log de acesso",
       _viu is not None and "processo(s)" in (_viu["alvo"] or ""),
       str(_viu["alvo"] if _viu else None))
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
# AS QUATRO SITUAÇÕES NA TELA, com frases distintas. A ambiguidade era de
# afirmação: "sem mudança" para item que nunca foi comparado com nada.
checar("item nunca lido continua dizendo que aguarda leitura",
       "aguardando primeira leitura" in _corpo)
checar("primeira observação diz que não há com o que comparar",
       "nada a comparar ainda" in _corpo, "a frase da primeira leitura sumiu")
checar("medição que não avançou diz que não há dado novo",
       "sem dado novo" in _corpo, "a frase do dado que não avançou sumiu")

# TETO NA TELA. A recusa por falta de espaço tem de dizer ISSO — o teto mandava
# conferir o dígito de um número correto. `ac.TETO` baixado ao tamanho atual da
# lista em vez de semear 100 linhas: o que está sob teste é a MENSAGEM.
_teto_real = ac.TETO
ac.TETO = len(ac.listar(conectar(), 7))
try:
    _r = _c.post("/acompanhamento/adicionar",
                 data={"csrf": _csrf, "numeros": "019.1616.2026.0000016-16"})
finally:
    ac.TETO = _teto_real
_cheio = _r.data.decode("utf-8", "replace")
checar("a recusa por teto diz que a lista está cheia",
       "a lista está cheia" in _cheio, "sem a frase do teto")
checar("e não carimba número válido como número inválido",
       "não parecem número de processo" not in _cheio, "carimbou o motivo errado")
checar("e o número não entrou",
       not any(x["protocolo"] == "019.1616.2026.0000016-16"
               for x in ac.listar(conectar(), 7)))
_csrf = _csrf_do(_r, _csrf)

# O LOG RESPONDE "quem fez o quê": remoção que não removeu nada não pode entrar
# como remoção feita.
_r = _c.post("/acompanhamento/remover",
             data={"csrf": _csrf, "protocolo": "019.0000.0000.0000000-00",
                   "instancia": "SEI-SESAB"})
_no_log = conectar().execute(
    "SELECT alvo FROM log_acesso WHERE usuario_id=7 AND acao='parar_acompanhar' "
    "ORDER BY id DESC LIMIT 1").fetchone()
checar("remoção que não achou linha fica dita assim no log",
       "nada a remover" in ((_no_log["alvo"] if _no_log else "") or ""),
       str(_no_log["alvo"] if _no_log else None))

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

print("\n7-bis. o CSRF das duas rotas")
# As duas rotas mudam dado e as duas chamam `confere_csrf()`. Apagar as duas
# chamadas deixava a suíte inteira verde — e sem elas qualquer página de fora
# posta formulário na sessão de quem estiver logado, que é o ataque que o token
# existe para impedir.
_antes_csrf = len(ac.listar(conectar(), 7))
_r = _c.post("/acompanhamento/adicionar", data={"numeros": "019.1717.2026.0000017-17"})
checar("adicionar sem token é recusado", _r.status_code == 400, str(_r.status_code))
_r = _c.post("/acompanhamento/adicionar",
             data={"csrf": _seg.novo_csrf(), "numeros": "019.1717.2026.0000017-17"})
checar("e com token que não é o do cookie também", _r.status_code == 400,
       str(_r.status_code))
checar("nada entrou na lista por esses dois caminhos",
       len(ac.listar(conectar(), 7)) == _antes_csrf,
       f"{len(ac.listar(conectar(), 7))} contra {_antes_csrf}")

_r = _c.post("/acompanhamento/remover",
             data={"protocolo": "019.1111.2026.0000001-11", "instancia": "SEI-SESAB"})
checar("remover sem token é recusado", _r.status_code == 400, str(_r.status_code))
_r = _c.post("/acompanhamento/remover",
             data={"csrf": _seg.novo_csrf(), "instancia": "SEI-SESAB",
                   "protocolo": "019.1111.2026.0000001-11"})
checar("e com token de outra sessão também", _r.status_code == 400, str(_r.status_code))
checar("e a linha continua lá",
       any(x["protocolo"] == "019.1111.2026.0000001-11"
           for x in ac.listar(conectar(), 7)))

print("\n7-ter. a instalação fica dita")


# O PADRÃO FICA DITO. A configuração ativa é "a última que a pessoa mexeu": depois
# de tocar na FESF, número colado entra como SEI-FESF e a tela não dizia nada.
# Item carimbado na instalação errada fica "aguardando primeira leitura" para
# sempre — os dígitos nunca casam com a coleta daquela instalação — e, na fase 2,
# é lido no SEI errado. É a doutrina de `ingestao.py`, de `coleta.py` e do próprio
# DDL de `acompanhado.instancia`.
_r = _c.get("/acompanhamento")
_csrf = _csrf_do(_r, _csrf)
_corpo = _r.data.decode("utf-8", "replace")
checar("o formulário diz em que instalação o número vai entrar",
       "vai entrar em" in _corpo, "o destino do que se cola não está dito")

# A conta 7 tem item nas DUAS instalações, e é aí que o rótulo por cartão informa.
# Com uma só, ele não aparece: carimbar "SESAB" em toda linha de quem só tem SESAB
# é ruído que ensina a não ler o carimbo — a mesma regra do `multi_instancia` do
# painel.
_cart_fesf = cartao(_corpo, "0016000251202662")
_cart_sesab = cartao(_corpo, "019.1111.2026.0000001-11")
# O RÓTULO VISÍVEL, não o `value` do campo escondido: a instalação já estava no
# formulário de remoção de todo cartão, então procurar "FESF" no cartão passava
# sem que a tela mostrasse nada a ninguém.
checar("o cartão da FESF diz que é da FESF", ">FESF</span>" in _cart_fesf,
       _cart_fesf[:160] or "cartão não encontrado")
checar("e o da SESAB diz que é da SESAB", ">SESAB</span>" in _cart_sesab,
       _cart_sesab[:160] or "cartão não encontrado")

_no_log = conectar().execute(
    "SELECT alvo FROM log_acesso WHERE usuario_id=7 AND acao='acompanhar' "
    "ORDER BY id DESC LIMIT 1").fetchone()
checar("o log de quem acompanha diz em qual instalação foi",
       "SEI-" in ((_no_log["alvo"] if _no_log else "") or ""),
       str(_no_log["alvo"] if _no_log else None))

# SEM RESERVA SILENCIOSA NA REMOÇÃO. O `or "SEI-SESAB"` reencenava o idioma que a
# tabela nasceu sem: formulário sem `instancia` apagava a linha da SESAB, que
# pode não ser a linha que a pessoa estava vendo.
_r = _c.post("/acompanhamento/remover",
             data={"csrf": _csrf, "protocolo": "019.1111.2026.0000001-11"})
checar("remover sem instalação não apaga a linha da SESAB por padrão",
       _r.status_code in (200, 302)
       and any(x["protocolo"] == "019.1111.2026.0000001-11"
               for x in ac.listar(conectar(), 7)),
       f"HTTP {_r.status_code} — ou caiu na reserva silenciosa")
_csrf = _csrf_do(_r, _csrf)

print("\n7-quater. o módulo não invadiu a carteira")
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
# carteira — fica esperando quem vá ao SEI. A carteira devolve zero, o item
# continua 'novo', e `pendentes` o entrega à estação: é a passagem de um caminho
# para o outro, e é o caso que motivou o módulo inteiro.
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
checar("e é a estação quem passa a ter de lê-lo",
       "019.1111.2026.0000001-11" in ac.pendentes(_cx, 7, "SEI-SESAB"))
_cx.execute("UPDATE snapshot SET estado='corrente' WHERE id=900")
# A coleta volta, e com ela a resposta de graça: o item sai da conta da estação
# sem ninguém mandar. É a economia central do desenho, dita de dentro de
# `pendentes` — que chama `reaproveitar` antes de listar justamente para isto.
_cx.execute("""UPDATE acompanhado SET lido_em=NULL, estado='novo'
               WHERE protocolo='019.1111.2026.0000001-11'""")
_cx.commit()
checar("com a coleta de volta, a carteira o tira da conta da estação",
       "019.1111.2026.0000001-11" not in ac.pendentes(_cx, 7, "SEI-SESAB"))
_cx.commit(); _cx.close()

print("\n7-quinquies. a ficha completa")
# O PEDIDO, de 11/09/2026: "deve aparecer as informações completas do processo,
# como aparece no controle de processo, para que possa entender qual é cada
# processo". Lista de números de 25 dígitos é ilegível — nenhum deles diz qual
# processo é qual.
#
# A DISPONIBILIDADE TEM TRÊS CAMADAS (seção 11.1 do desenho), e só uma era
# escolha de desenho: (a) o que vale dentro e fora da mesa; (b) o que SÓ existe
# na LINHA da mesa — marcador, anotação, responsável, visualizado e os cinco de
# custódia —, que para processo de fora não existe porque o SEI não tem essa
# linha; (c) o texto livre, que a decisão de privacidade do usuário, de
# 11/09/2026, perguntado explicitamente, autorizou mostrar NESTE módulo.
#
# A COLUNA TEM DE CHEGAR AO BANCO QUE JÁ EXISTE, e é o primeiro bloco por isso:
# `CREATE TABLE IF NOT EXISTS` não altera tabela existente, e o defeito do `);`
# dentro de comentário (ver 8-nonies) acabou de custar duas colunas que só
# nasciam em banco novo. Aqui a checagem é a de verdade: DERRUBA as colunas do
# banco já criado e manda a migração recriá-las — comparar o DDL com ele mesmo
# não prova nada sobre o banco.
_CAMPOS_NOVOS = set(ac.CAMPOS_FICHA)
_COLS_FICHA_DDL = banco._colunas_do_ddl(banco.DDL).get("acompanhado_leitura", {})
checar("o DDL declara a ficha inteira no histórico",
       _CAMPOS_NOVOS <= set(_COLS_FICHA_DDL),
       str(sorted(_CAMPOS_NOVOS - set(_COLS_FICHA_DDL))))
_cx = conectar()
for _col in sorted(_CAMPOS_NOVOS):
    _cx.execute(f"ALTER TABLE acompanhado_leitura DROP COLUMN {_col}")
_cx.commit()
_sem = {r[1] for r in _cx.execute("PRAGMA table_info(acompanhado_leitura)")}
_cx.close()
checar("(cena) o banco ficou sem as colunas da ficha",
       not (_CAMPOS_NOVOS & _sem), str(sorted(_CAMPOS_NOVOS & _sem)))
banco.migrar()
_cx = conectar()
_voltaram = {r[1] for r in _cx.execute("PRAGMA table_info(acompanhado_leitura)")}
checar("a migração recria a ficha em banco JÁ EXISTENTE, não só em banco novo",
       _CAMPOS_NOVOS <= _voltaram, str(sorted(_CAMPOS_NOVOS - _voltaram)))

# ---- a carteira responde a ficha inteira, e o texto de gente vem com ela.
# Texto com `<script>` de propósito: especificação, anotação e interessados são
# texto que um servidor escreveu, e vão para HTML. O Jinja escapa por padrão — o
# que este bloco prova é que ninguém pôs `|safe` no caminho.
_ESPEC = ('Contratação de lavanderia hospitalar <script>alert(1)</script> '
          + "para o HECC " + "x" * 300)
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,tipo_processo,
               autuacao,gerador_unidade,gerador_usuario,nivel_acesso,hipotese_legal,
               assuntos,anexados,emails_enviados,assinatura_externa,
               marcador,marcador_cor,atribuido_nome,atribuido_login,visualizado,
               marco_unidade,recebimento,recebimento_por,envio,unidade_envio,
               mesa_indeterminada,documentos,movimentos,medido_em,mesas_fonte,
               ultimo_movimento)
               VALUES(900,'1616','019.1616.2026.0000016-16',
               'Administrativo: Contratação de Serviços',
               '12/03/2026','SESAB/DGESS','ana.souza','Restrito',
               'Informação Pessoal (Art. 31 da Lei 12.527/2011)',
               '["Contratação de serviços","Saúde"]','["019.9.2026.1-10"]',
               4,1,'Urgente <b>','vermelho','Ana <Souza>','ana.souza',0,
               '15/08/2026','15/08/2026 08:10','carlos.lima','20/08/2026 17:02',
               'SESAB/CIR-IBOT',0,12,31,'2026-08-27T07:45:00-03:00','arvore',
               '{"dh":"20/08/2026 17:02","un":"SESAB/MINHA","de":"Processo enviado"}')""")
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'1616','SESAB/MINHA',NULL)""")
_cx.execute("""INSERT INTO processo_texto(snapshot_id,id_sei,especificacao,anotacao,
               anotacao_autor,anotacao_data,interessados,acompanhamento)
               VALUES(900,'1616',?,'cobrar a nota <b>hoje</b>','ana.souza',
               '26/08/2026','["Hospital & Cia","Maria <M> Silva"]',NULL)""",
            (_ESPEC,))
# A MESMA armadilha da fronteira, agora com o JOIN de `processo_texto`: o texto
# do processo de mesa ALHEIA existe no banco, e um JOIN mal escopado o traria.
_cx.execute("""INSERT INTO processo_texto(snapshot_id,id_sei,especificacao)
               VALUES(901,'222','SEGREDO DA MESA ALHEIA')""")
_cx.commit()
ac.adicionar(_cx, 7, "019.1616.2026.0000016-16", "SEI-SESAB")
_cx.commit()
checar("o processo da ficha cheia é respondido pela carteira",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") == 1)
_cx.commit()

_fichas = {x["protocolo"]: x for x in ac.listar(_cx, 7)}
_f = _fichas["019.1616.2026.0000016-16"]
checar("tipo e especificação chegam à ficha",
       _f["tipo_processo"] == "Administrativo: Contratação de Serviços"
       and _f["especificacao"] == _ESPEC, str(_f["tipo_processo"]))
checar("autuação e quem gerou também",
       (_f["autuacao"], _f["gerador_unidade"], _f["gerador_usuario"])
       == ("12/03/2026", "SESAB/DGESS", "ana.souza"), str(_f["autuacao"]))
checar("nível de acesso com a hipótese legal",
       _f["nivel_acesso"] == "Restrito" and "12.527" in (_f["hipotese_legal"] or ""),
       str(_f["nivel_acesso"]))
# JSON volta como LISTA, como `aberto_em` e `ultimo_movimento` já voltavam: a
# tela não pode receber string de JSON para iterar caractere por caractere.
checar("assuntos, interessados e anexados voltam como lista",
       _f["assuntos"] == ["Contratação de serviços", "Saúde"]
       and _f["interessados"] == ["Hospital & Cia", "Maria <M> Silva"]
       and _f["anexados"] == ["019.9.2026.1-10"],
       f"{_f['assuntos']!r} / {_f['interessados']!r} / {_f['anexados']!r}")
checar("as contagens do processo chegam",
       (_f["emails_enviados"], _f["assinatura_externa"]) == (4, 1),
       f"{_f['emails_enviados']} / {_f['assinatura_externa']}")
# OS CAMPOS DA MESA: aqui eles EXISTEM, porque o processo está numa mesa desta
# conta. É a diferença que a ficha tem de dizer.
checar("o marcador da mesa chega", _f["marcador"] == "Urgente <b>", str(_f["marcador"]))
checar("a anotação chega com autor e data",
       (_f["anotacao"], _f["anotacao_autor"], _f["anotacao_data"])
       == ("cobrar a nota <b>hoje</b>", "ana.souza", "26/08/2026"),
       str(_f["anotacao"]))
checar("o responsável atribuído chega", _f["atribuido_nome"] == "Ana <Souza>")
checar("visualizado chega como 0, e 0 não é ausência", _f["visualizado"] == 0,
       repr(_f["visualizado"]))
checar("os cinco de custódia chegam",
       (_f["marco_unidade"], _f["recebimento_por"], _f["unidade_envio"])
       == ("15/08/2026", "carlos.lima", "SESAB/CIR-IBOT"), str(_f["marco_unidade"]))
# A FRONTEIRA NÃO MUDOU. O texto de mesa alheia está no banco e não pode entrar.
_alheio = _fichas["019.2222.2026.0000002-22"]
checar("o texto da mesa ALHEIA não entra na ficha",
       (_alheio.get("especificacao") or "") != "SEGREDO DA MESA ALHEIA",
       str(_alheio.get("especificacao")))

# UMA CONSULTA, não 101. O comentário de `listar()` se orgulha disso, e a ficha
# inteira é justamente o que tentaria virar uma consulta por item.
_sqls = []
_cx.set_trace_callback(_sqls.append)
ac.listar(_cx, 7)
_cx.set_trace_callback(None)
checar("a ficha inteira continua saindo de UMA consulta",
       len(_sqls) == 1, f"{len(_sqls)}: {[s[:50] for s in _sqls]}")

# ---- o item DE FORA: a mesa não existe, e isso não é "não tem marcador".
ac.adicionar(_cx, 7, "019.1515.2026.0000015-15", "SEI-SESAB")
_cx.commit()
ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.1515.2026.0000015-15", "aberto_em": ["SESAB/CIR-IBOT"],
     "aberto_em_fonte": "arvore", "documentos": 7, "movimentos": 9}]})
_cx.commit()
_fora = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.1515.2026.0000015-15"]
checar("o item de fora foi lido pelo SEI", _fora["fonte"] == "sei", str(_fora["fonte"]))
checar("e a ficha dele diz que a MESA não existe, em vez de campo vazio",
       "NÃO existem" in ac.texto_sem_mesa(_fora), repr(ac.texto_sem_mesa(_fora)))
checar("já o da carteira não diz isso — ali vazio é vazio mesmo",
       ac.texto_sem_mesa(_f) == "", repr(ac.texto_sem_mesa(_f)))
# A PROCEDÊNCIA VALE PARA A FICHA INTEIRA, não só para as unidades: se a linha é
# da coleta de 27/08, o MARCADOR também é de 27/08.
checar("a procedência da ficha da carteira é a da medição, e cobre tudo",
       "27/08" in ac.texto_da_ficha(_f) and "campos" in ac.texto_da_ficha(_f),
       repr(ac.texto_da_ficha(_f)))
checar("e a do item lido no SEI diz que foi lido no SEI",
       "SEI" in ac.texto_da_ficha(_fora), repr(ac.texto_da_ficha(_fora)))
# Leitura sem data de medição NÃO pode render ficha sem carimbo: a coluna aceita
# nulo, e ficha sem procedência passa por ficha de agora.
checar("ficha sem data de medição diz que não sabe de quando é",
       "de quando" in ac.texto_da_ficha(
           {"fonte": "carteira", "estado": "lido", "medido_em": None}),
       repr(ac.texto_da_ficha({"fonte": "carteira", "estado": "lido"})))
_cx.commit(); _cx.close()

# ---- a tela: linha enxuta, ficha no expandir, e nenhum texto de gente cru.
_r = _c.get("/acompanhamento")
_csrf = _csrf_do(_r, _csrf)
_corpo = _r.data.decode("utf-8", "replace")
checar("a tela com ficha abre", _r.status_code == 200, str(_r.status_code))
_cheio = cartao(_corpo, "019.1616.2026.0000016-16")
_sem_mesa = cartao(_corpo, "019.1515.2026.0000015-15")
_magro = cartao(_corpo, "019.1111.2026.0000001-11")
checar("o cartão da ficha cheia existe", bool(_cheio))
# A LINHA FECHADA tem de dizer QUAL processo é, que era o pedido: a especificação
# entra nela, não só no expandir. Quem varre 100 números precisa reconhecer o
# processo sem abrir cada um.
_i_det = _cheio.find("<details")
checar("a linha fechada já diz qual processo é",
       0 < _cheio.find("Contratação de lavanderia") < _i_det,
       f"{_cheio.find('Contratação de lavanderia')} vs {_i_det}")
checar("e a ficha completa fica atrás de um expandir na própria linha",
       "<details" in _cheio and "ficha completa" in _cheio, _cheio[:200])
checar("a ficha traz os campos do processo",
       all(t in _cheio for t in ("Autuação", "12/03/2026", "SESAB/DGESS",
                                 "Nível de acesso", "Restrito")), "faltou campo")
checar("e os campos da mesa, que para este processo existem",
       all(t in _cheio for t in ("Marcador", "Anotação", "ana.souza",
                                 "15/08/2026")), "faltou campo da mesa")
checar("a procedência carimba a FICHA INTEIRA, não só as unidades",
       "27/08" in _cheio and "campos desta ficha" in _cheio, _cheio[-400:])
# TEXTO DE GENTE ESCAPADO. Sem isto a especificação que um servidor escreveu
# executa no navegador de quem abre a lista.
checar("texto de gente sai escapado, nunca cru",
       "<script>alert(1)</script>" not in _cheio
       and "&lt;script&gt;" in _cheio, "o texto saiu cru")
checar("o marcador e a anotação também",
       "Urgente <b>" not in _cheio and "Urgente &lt;b&gt;" in _cheio)
checar("e o interessado também",
       "Maria <M> Silva" not in _cheio and "Maria &lt;M&gt; Silva" in _cheio)
# TEXTO LONGO NÃO ARREBENTA A LINHA: a linha fechada corta em uma linha só (CSS)
# e guarda o texto inteiro no `title`.
checar("a especificação longa é cortada na linha fechada, com o todo no title",
       'class="acomp-titulo"' in _cheio and _ESPEC[:30] in _cheio, _cheio[:400])
# O ITEM DE FORA: a ficha diz que a mesa não existe, e NÃO imprime um marcador
# vazio como se o processo não tivesse marcador.
checar("o cartão de fora da carteira diz que a mesa não existe",
       "NÃO existem" in _sem_mesa, _sem_mesa[:400])
checar("e não imprime campo de mesa em branco",
       "Marcador" not in _sem_mesa, _sem_mesa[:400])
# O ITEM DA CARTEIRA SEM MARCADOR NEM ANOTAÇÃO: ali o branco é branco de
# verdade, e a ficha o mostra como ausente — sem a frase do item de fora.
checar("o cartão da carteira sem marcador mostra o campo vazio, não a frase de fora",
       "Marcador" in _magro and "NÃO existem" not in _magro, _magro[:400])
# SEM OS COMENTÁRIOS do próprio template: eles falam de `|safe` para dizer que
# ele não está aqui, e a checagem crua dava vermelho por causa da explicação.
import re as _re                                                 # noqa: E402
_tpl = Path(__file__).resolve().parent / "templates" / "acompanhamento.html"
_tpl_sem_comentario = _re.sub(r"\{#.*?#\}", "", _tpl.read_text("utf-8"), flags=_re.S)
checar("nenhum `|safe` no caminho do texto de gente",
       "safe" not in _tpl_sem_comentario,
       "alguém desligou o escape do Jinja")

print("\n8. o que a estação pega")
import hashlib as _hash                                          # noqa: E402
import json as _json                                             # noqa: E402

# A NOTA É TEXTO DE GENTE, e pode citar nome. Ela fica na tela de quem escreveu;
# a estação só precisa do número para procurar no SEI. Este item é o que prova
# que ela não viaja.
_cx = conectar()
_cx.execute("""UPDATE acompanhado SET nota='cobrar a Laisa sobre o pagamento'
               WHERE usuario_id=7 AND protocolo='019.2222.2026.0000002-22'""")
_cx.execute("DELETE FROM agentes")
_TOKEN_AG = "token-da-estacao-7"
_cx.execute("""INSERT INTO agentes(id,nome_estacao,dono_usuario_id,ativo,
               token_sha256,unidades_esperadas,ultimo_contato_em,criado_em)
               VALUES(70,'ESTACAO-7',7,1,?,'["SESAB/MINHA"]',?,?)""",
            (_hash.sha256(_TOKEN_AG.encode()).digest(), agora(), agora()))
# A SEGUNDA ESTAÇÃO, da outra conta: é ela que prova que o dono sai do TOKEN.
_TOKEN_AG8 = "token-da-estacao-8"
_cx.execute("""INSERT INTO agentes(id,nome_estacao,dono_usuario_id,ativo,
               token_sha256,unidades_esperadas,ultimo_contato_em,criado_em)
               VALUES(80,'ESTACAO-8',8,1,?,'[]',?,?)""",
            (_hash.sha256(_TOKEN_AG8.encode()).digest(), agora(), agora()))
# E a estação SEM DONO: sem dono não há credencial do SEI de quem abrir, e é o
# mesmo motivo pelo qual `/api/agente/tarefa` recusa entregar coleta.
_cx.execute("""INSERT INTO agentes(id,nome_estacao,dono_usuario_id,ativo,
               token_sha256,unidades_esperadas,ultimo_contato_em,criado_em)
               VALUES(81,'ESTACAO-ORFA',NULL,1,?,'[]',?,?)""",
            (_hash.sha256(b"token-orfao").digest(), agora(), agora()))
_cx.commit(); _cx.close()

_cx = conectar()
# UM NÚMERO DA FESF QUE A CARTEIRA NÃO RESPONDE: os outros itens da FESF desta
# suíte estão todos na coleta da FESF, e por isso saem da conta da estação de
# graça — que é o desenho funcionando. Para provar o recorte POR INSTALAÇÃO é
# preciso um que sobre.
ac.adicionar(_cx, 7, "019.3030.2026.0000030-30", "SEI-FESF")
_cx.commit()
_pend = ac.pendentes(_cx, 7, "SEI-SESAB")
_pend_fesf = ac.pendentes(_cx, 7, "SEI-FESF")
_cx.commit()
checar("o de mesa alheia está pendente de leitura no SEI",
       "019.2222.2026.0000002-22" in _pend, str(_pend))
checar("o da minha carteira NÃO está — já foi respondido de graça",
       "019.1111.2026.0000001-11" not in _pend, str(_pend))
# `pendentes` é POR instalação: mandar a estação procurar na SESAB um número que
# a pessoa colou na lista da FESF é procurar no SEI errado — o item nunca casaria,
# e viraria 'nao_encontrado' para sempre.
checar("a lista da outra instalação não entra nesta",
       "019.3030.2026.0000030-30" not in _pend, str(_pend))
checar("e a da FESF traz o dela",
       "019.3030.2026.0000030-30" in _pend_fesf, str(_pend_fesf))
# SÓ O NÚMERO. A estação recebe o que precisa para procurar, e nada do que a
# pessoa escreveu.
checar("o que sai são números, não fichas", all(isinstance(p, str) for p in _pend),
       str(_pend)[:120])
_cx.commit(); _cx.close()


def _do_agente(caminho, corpo_obj=None, metodo="POST", tok=None):
    """Requisição como a estação faz: Bearer MAIS HMAC do corpo exato enviado.

    O corpo é serializado UMA vez e os mesmos bytes são assinados e enviados —
    assinar um `json.dumps` diferente do que vai no fio passa no teste e falha em
    produção, que é o defeito que `seguranca.assinar` existe para pegar.
    """
    corpo = (_json.dumps(corpo_obj, ensure_ascii=False).encode()
             if corpo_obj is not None else b"")
    ts = agora()
    tok = tok or _TOKEN_AG
    cab = {"Authorization": f"Bearer {tok}", "X-SEI360-Ts": ts,
           "X-SEI360-Assinatura": _seg.assinar(tok, ts, corpo),
           "Content-Type": "application/json"}
    if metodo == "GET":
        return _c.get(caminho, headers=cab)
    return _c.post(caminho, data=corpo, headers=cab)


# O CONTADOR DE ENTREGAS É ZERADO AQUI, DE PROPÓSITO. `pendentes` conta cada vez
# que entrega um item à estação e só zera quando uma leitura volta; esta suíte
# chamou `pendentes` duas vezes acima sem nunca publicar leitura nenhuma, e isso é
# exatamente o que o recuo existe para barrar (ver a seção 8-nonies). Aqui o que
# se quer provar é o ENVELOPE, então a fila começa limpa.
_cx = conectar()
_cx.execute("UPDATE acompanhado SET tentativas=0, tentativa_em=NULL")
_cx.commit(); _cx.close()

_r = _do_agente("/api/agente/acompanhamento", metodo="GET")
checar("a estação autenticada recebe a tarefa", _r.status_code == 200,
       str(_r.status_code))
_tarefa = _r.get_json() or {}
checar("com o aviso de que há o que ler", _tarefa.get("ler") is True, str(_tarefa)[:200])
checar("e com a instalação em que procurar",
       _tarefa.get("instancia") == "SEI-SESAB", str(_tarefa.get("instancia")))
checar("o processo de fora da carteira está na tarefa",
       "019.2222.2026.0000002-22" in (_tarefa.get("protocolos") or []),
       str(_tarefa.get("protocolos"))[:200])
# O PERFIL VIAJA COM A TAREFA, como já viaja com a busca e com a coleta: sem ele
# a estação cai em URL escrita nela e entra na instalação errada.
checar("o perfil da instalação vai junto",
       bool((_tarefa.get("perfil") or {}).get("login_url")),
       str(_tarefa.get("perfil"))[:120])
# O ENVELOPE É FECHADO, e é isto que a tarefa 9 vai consumir. Campo a mais aqui é
# campo que a estação passa a poder usar — e a nota é texto de gente.
#
# `descansando` entrou depois, e passa pelo mesmo crivo: carrega NÚMERO DE
# PROCESSO e uma contagem, a mesma classe de dado que `protocolos` já leva. Ele
# existe porque recuo silencioso é indistinguível de processo em dia, e o log da
# estação é o único lugar onde alguém veria isso.
checar("e o envelope não manda nada além do necessário",
       set(_tarefa) == {"ler", "instancia", "protocolos", "perfil", "descansando"},
       str(sorted(_tarefa)))
checar("a nota da pessoa NÃO viaja para a estação",
       "Laisa" not in _r.data.decode("utf-8", "replace"),
       "o texto que a pessoa escreveu saiu do servidor")

_r = _c.get("/api/agente/acompanhamento")
checar("sem token não há tarefa nenhuma", _r.status_code == 401, str(_r.status_code))
_r = _do_agente("/api/agente/acompanhamento", metodo="GET", tok="token-inventado")
checar("e com token que não é de agente nenhum também", _r.status_code == 401,
       str(_r.status_code))
_r = _do_agente("/api/agente/acompanhamento", metodo="GET", tok="token-orfao")
checar("estação sem dono não recebe tarefa, e ouve por quê",
       _r.status_code == 200 and (_r.get_json() or {}).get("ler") is False
       and "dono" in ((_r.get_json() or {}).get("motivo") or ""),
       str(_r.get_json())[:160])

print("\n8-bis. o que a estação relata")
_cx = conectar()
_leitura = {"protocolo": "019.2222.2026.0000002-22", "id_sei": "222",
            "aberto_em": ["SESAB/ALHEIA"], "aberto_em_fonte": "arvore",
            "ultimo_movimento": {"dh": "01/09/2026 10:00", "un": "SESAB/ALHEIA",
                                 "de": "Processo recebido na unidade"},
            "documentos": 3, "movimentos": 4}
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB",
                         {"instancia": "SEI-SESAB", "leituras": [_leitura]})
_cx.commit()
checar("a leitura da estação é aceita", (_grav, _ign) == (1, 0), f"{_grav}/{_ign}")
_it = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.2222.2026.0000002-22"]
checar("com fonte 'sei'", _it["fonte"] == "sei", str(_it["fonte"]))
checar("e estado lido", _it["estado"] == "lido", str(_it["estado"]))
checar("com as unidades que a estação leu",
       _it["aberto_em"] == ["SESAB/ALHEIA"], str(_it["aberto_em"]))
# A MEDIÇÃO É AGORA, e aqui isso é verdade: quem lê no SEI mede no instante da
# leitura. É o oposto do dado da carteira, que pode ser de nove dias antes.
checar("a medição é a de agora, porque a leitura no SEI mede agora",
       (_it["medido_em"] or "")[:10] == agora()[:10], str(_it["medido_em"]))
checar("e a procedência diz que foi lido no SEI",
       ac.texto_da_procedencia(_it).startswith("lido no SEI"),
       ac.texto_da_procedencia(_it))
checar("a primeira leitura no SEI também se declara primeira",
       _it["comparacao"] == "primeira" and _it["mudou"] is None, str(_it["comparacao"]))
# UMA LEITURA POR DIA vale para o caminho caro também: sem isto a estação releria
# o mesmo processo a cada ciclo do agente, três requisições ao SEI por vez.
checar("lido hoje sai da conta da estação",
       "019.2222.2026.0000002-22" not in ac.pendentes(_cx, 7, "SEI-SESAB"))
_cx.commit(); _cx.close()

print("\n8-ter. recusa do SEI não é ficha vazia")
_cx = conectar()
_antes = _cx.execute("SELECT COUNT(*) FROM acompanhado_leitura WHERE usuario_id=7 "
                     "AND protocolo='019.2222.2026.0000002-22'").fetchone()[0]
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.2222.2026.0000002-22", "estado": "sem_acesso"}]})
_cx.commit()
checar("a recusa é relatada e aceita", (_grav, _ign) == (1, 0), f"{_grav}/{_ign}")
_it = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.2222.2026.0000002-22"]
checar("recusa do SEI vira estado próprio, não ficha vazia",
       _it["estado"] == "sem_acesso", str(_it["estado"]))
# RECUSA NÃO É OBSERVAÇÃO. Gravar uma linha vazia na série diria "em 11/09 este
# processo não estava aberto em lugar nenhum e tinha zero documento" — e, pior,
# a linha vazia passaria a ser a ÚLTIMA leitura, apagando da tela o que se sabia.
_depois = _cx.execute("SELECT COUNT(*) FROM acompanhado_leitura WHERE usuario_id=7 "
                      "AND protocolo='019.2222.2026.0000002-22'").fetchone()[0]
checar("e não entra como observação na série temporal", _depois == _antes,
       f"{_antes} -> {_depois}")
checar("a última leitura de verdade continua na tela",
       _it["aberto_em"] == ["SESAB/ALHEIA"] and _it["documentos"] == 3,
       f"{_it['aberto_em']} / {_it['documentos']}")
checar("e a procedência cala, porque nada foi lido",
       ac.texto_da_procedencia(_it) == "", ac.texto_da_procedencia(_it))
_cx.commit(); _cx.close()

print("\n8-quater. a estação é relator não confiável")
_cx = conectar()
ac.adicionar(_cx, 7, "019.2020.2026.0000020-20\n019.2121.2026.0000021-21", "SEI-SESAB")
_cx.commit()


def _ninguem_escreveu(protocolo):
    """O item continua como estava: nem leitura, nem estado mexido."""
    x = {i["protocolo"]: i for i in ac.listar(_cx, 7)}.get(protocolo) or {}
    return x.get("estado") == "novo" and x.get("fonte") is None


# CORPO QUE NÃO É ENVELOPE. `request.get_json` devolve o que veio: lista, texto,
# número. `envelope.get` sobre isso é AttributeError, e AttributeError numa rota
# é 500 — a estação não sabe o que fazer com 500 e volta a tentar para sempre.
for _lixo in ([], "texto", 7, None, {"leituras": "nao e lista"},
              {"leituras": {"protocolo": "019.2020.2026.0000020-20"}}):
    _grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", _lixo)
    checar(f"corpo sem forma de envelope não grava nada ({type(_lixo).__name__})",
           (_grav, _ign) == (0, 0), f"{_lixo!r} -> {_grav}/{_ign}")

# LINHA QUE NÃO É LEITURA, e número que não é número. Cada uma volta CONTADA: a
# estação que relata dez e vê 'gravadas: 0' precisa saber se a lista chegou vazia
# ou se tudo foi recusado — é o mesmo motivo de `adicionar` devolver os recusados.
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    "019.2020.2026.0000020-20", None, 7, {}, {"protocolo": None},
    {"protocolo": 19202020}, {"protocolo": "processo da Laisa"},
    {"protocolo": "019.2020.2026.0000020-20."}]})
_cx.commit()
checar("linha que não é leitura é recusada, uma a uma",
       (_grav, _ign) == (0, 8), f"{_grav}/{_ign}")
checar("e nada foi escrito por esse caminho",
       _ninguem_escreveu("019.2020.2026.0000020-20"))

# PROTOCOLO QUE NÃO ESTÁ NA LISTA não entra por relato de estação: quem decide o
# que se acompanha é a pessoa, na tela dela.
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.7070.2026.0000070-70", "aberto_em": ["SESAB/MINHA"],
     "documentos": 1, "movimentos": 1}]})
_cx.commit()
checar("número fora da lista não vira item novo", (_grav, _ign) == (0, 1),
       f"{_grav}/{_ign}")
checar("e nem leitura solta no histórico", _cx.execute(
    "SELECT COUNT(*) FROM acompanhado_leitura WHERE protocolo=?",
    ("019.7070.2026.0000070-70",)).fetchone()[0] == 0)

# ESTADO INVENTADO NÃO VIRA 'lido'. Traduzi-lo para o caso bom carimbaria "lido no
# SEI" sobre uma ficha vazia que a estação nunca disse ter lido — e a tela passaria
# a afirmar que o processo não está aberto em lugar nenhum.
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.2020.2026.0000020-20", "estado": "erro_de_rede"},
    {"protocolo": "019.2020.2026.0000020-20", "estado": {"x": 1}}]})
_cx.commit()
checar("estado que o servidor não conhece é recusado, não traduzido",
       (_grav, _ign) == (0, 2), f"{_grav}/{_ign}")
checar("e o item continua esperando leitura",
       _ninguem_escreveu("019.2020.2026.0000020-20"))

# O MESMO PROTOCOLO DUAS VEZES no mesmo envelope. A segunda compararia contra a
# primeira, recém-inserida no mesmo instante: duas linhas na única série temporal
# do produto, e delta medido entre a leitura e ela mesma.
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.2020.2026.0000020-20", "aberto_em": ["SESAB/UMA"],
     "documentos": 2, "movimentos": 2},
    {"protocolo": "019.2020.2026.0000020-20", "aberto_em": ["SESAB/OUTRA"],
     "documentos": 9, "movimentos": 9}]})
_cx.commit()
checar("protocolo repetido no envelope conta uma vez", (_grav, _ign) == (1, 1),
       f"{_grav}/{_ign}")
checar("e grava UMA linha na série", _cx.execute(
    "SELECT COUNT(*) FROM acompanhado_leitura WHERE usuario_id=7 AND protocolo=?",
    ("019.2020.2026.0000020-20",)).fetchone()[0] == 1)
_repetido = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.2020.2026.0000020-20"]
checar("sem delta inventado entre a leitura e ela mesma",
       _repetido["mudou"] is None and _repetido["comparacao"] == "primeira",
       f"{_repetido['mudou']} / {_repetido['comparacao']}")

# CAMPO COM O TIPO ERRADO. `aberto_em` como TEXTO é o pior deles: `set("SESAB/X")`
# é um conjunto de LETRAS, e a tela anunciaria o processo entrando em sete
# unidades chamadas 'S', 'E', 'A', 'B'... Contagem em texto não estoura na hora —
# estoura na leitura seguinte, quando o delta subtrai texto de número.
#
# Campo que não veio em forma de campo é campo NÃO OBSERVADO, e ausência não é
# conjunto vazio: é a mesma doutrina de `delta()`, que se recusa a anunciar
# mudança onde não houve observação.
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.2121.2026.0000021-21", "aberto_em": "SESAB/MINHA",
     "aberto_em_fonte": {"x": 1}, "ultimo_movimento": "01/09/2026",
     "documentos": "3", "movimentos": True, "id_sei": ["222"]}]})
_cx.commit()
checar("leitura com campos deformados é aceita sem estourar", (_grav, _ign) == (1, 0),
       f"{_grav}/{_ign}")
_torto = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.2121.2026.0000021-21"]
checar("texto no lugar da lista de unidades não vira unidade nenhuma",
       _torto["aberto_em"] is None, str(_torto["aberto_em"]))
checar("nem contagem em texto vira contagem",
       (_torto["documentos"], _torto["movimentos"]) == (None, None),
       f"{_torto['documentos']} / {_torto['movimentos']}")
checar("nem movimento em texto vira movimento",
       _torto["ultimo_movimento"] is None, str(_torto["ultimo_movimento"]))
checar("e o id_sei deformado não é gravado", _torto["id_sei"] is None,
       str(_torto["id_sei"]))
checar("mas a leitura conta como lida, que foi o que a estação disse",
       _torto["estado"] == "lido" and _torto["fonte"] == "sei",
       f"{_torto['estado']} / {_torto['fonte']}")

# UNIDADE QUE NÃO É TEXTO dentro da lista: `sorted` sobre tipos misturados estoura
# no delta seguinte, e a tela renderiza `u.split('/')` sobre um dicionário.
_cx.execute("UPDATE acompanhado SET lido_em=? WHERE usuario_id=7 AND protocolo=?",
            (_ONTEM, "019.2121.2026.0000021-21"))
_cx.commit()
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.2121.2026.0000021-21", "aberto_em": ["SESAB/MINHA", {"u": 1}],
     "documentos": 1, "movimentos": 1}]})
_cx.commit()
_misto = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.2121.2026.0000021-21"]
checar("lista de unidades com coisa que não é unidade não é lista de unidades",
       (_grav, _ign) == (1, 0) and _misto["aberto_em"] is None,
       f"{_grav}/{_ign} / {_misto['aberto_em']}")
checar("e as contagens boas do mesmo envelope continuam valendo",
       (_misto["documentos"], _misto["movimentos"]) == (1, 1),
       f"{_misto['documentos']} / {_misto['movimentos']}")

# ENVELOPE VAZIO é o caso NORMAL: a estação rodou, não achou nada para ler, e diz
# isso. Não pode ser erro nem escrever nada.
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"instancia": "SEI-SESAB",
                                               "leituras": []})
checar("envelope sem leitura nenhuma é resposta legítima", (_grav, _ign) == (0, 0),
       f"{_grav}/{_ign}")
_cx.commit(); _cx.close()

print("\n8-quinquies. a instalação não vem do envelope")
_cx = conectar()
# O NÚMERO QUE EXISTE NAS DUAS LISTAS. A pessoa segue `019.3333...` na SESAB e na
# FESF, e são DUAS linhas, com histórico próprio. Se o envelope pudesse dizer a
# instalação, a leitura feita na FESF entraria na linha da SESAB — o carimbo
# falso que `acompanhado.instancia` nasceu sem DEFAULT para evitar.
_cx.execute("""UPDATE acompanhado SET lido_em=NULL, estado='novo'
               WHERE usuario_id=7 AND protocolo='019.3333.2026.0000003-33'""")
_cx.commit()
_antes_fesf = [x for x in ac.listar(_cx, 7) if x["instancia"] == "SEI-FESF"
               and x["protocolo"] == "019.3333.2026.0000003-33"][0]
try:
    ac.receber(_cx, 7, "SEI-SESAB", {"instancia": "SEI-FESF", "leituras": [
        {"protocolo": "019.3333.2026.0000003-33", "aberto_em": ["FESF/GABINETE"],
         "documentos": 7, "movimentos": 8}]})
    checar("envelope que fala de outra instalação é recusado inteiro", False,
           "aceitou a instalação do corpo")
except ValueError:
    checar("envelope que fala de outra instalação é recusado inteiro", True)
_cx.rollback()
_depois_fesf = [x for x in ac.listar(_cx, 7) if x["instancia"] == "SEI-FESF"
                and x["protocolo"] == "019.3333.2026.0000003-33"][0]
checar("e nenhuma das duas linhas foi tocada",
       _depois_fesf["leitura_em"] == _antes_fesf["leitura_em"]
       and not any(x["fonte"] == "sei" for x in ac.listar(_cx, 7)
                   if x["protocolo"] == "019.3333.2026.0000003-33"),
       str(_depois_fesf["leitura_em"]))
# O CONTRAPESO: sem o campo, a estação é acreditada — a instalação é a que o
# servidor mandou ler, e o envelope não precisa repeti-la.
_grav, _ign = ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.3333.2026.0000003-33", "aberto_em": ["SESAB/ALGUMA"],
     "documentos": 1, "movimentos": 1}]})
_cx.commit()
checar("envelope sem instalação é gravado na que o servidor mandou ler",
       (_grav, _ign) == (1, 0), f"{_grav}/{_ign}")
_na_sesab = [x for x in ac.listar(_cx, 7) if x["instancia"] == "SEI-SESAB"
             and x["protocolo"] == "019.3333.2026.0000003-33"][0]
_na_fesf = [x for x in ac.listar(_cx, 7) if x["instancia"] == "SEI-FESF"
            and x["protocolo"] == "019.3333.2026.0000003-33"][0]
checar("a linha da SESAB recebeu a leitura",
       _na_sesab["fonte"] == "sei" and _na_sesab["aberto_em"] == ["SESAB/ALGUMA"],
       f"{_na_sesab['fonte']} / {_na_sesab['aberto_em']}")
checar("e a da FESF continua com o dado dela",
       _na_fesf["fonte"] == "carteira", str(_na_fesf["fonte"]))
_cx.commit(); _cx.close()

print("\n8-sexies. a fronteira: o dono sai do TOKEN")
# O TESTE QUE MAIS IMPORTA DESTA TAREFA. A regra recebe o `usuario_id` e obedece —
# é a camada de regra, e ela confia no chamador de propósito. A fronteira é a
# ROTA: se o dono pudesse vir de dentro do corpo, um agente escreveria leitura na
# lista de qualquer conta, e o dono do token deixaria de significar alguma coisa.
#
# `019.8888...` está na lista da conta 8 e NÃO na da 7 (a conta 7 perdeu a dela na
# cena da tela). A estação da conta 7 relata leitura dele, dizendo no corpo que é
# da conta 8 — de todas as formas que um corpo tem de dizer isso.
_r = _do_agente("/api/agente/acompanhamento", {
    "instancia": "SEI-SESAB", "usuario_id": 8, "dono_usuario_id": 8, "usuario": 8,
    "leituras": [{"protocolo": "019.8888.2026.0000008-88",
                  "aberto_em": ["SESAB/INVENTADA"], "documentos": 99,
                  "movimentos": 99}]})
checar("a estação da outra conta não é recusada com erro, mas não grava nada",
       _r.status_code == 200 and (_r.get_json() or {}).get("gravadas") == 0,
       f"{_r.status_code} {_r.get_json()}")
_da_8 = {x["protocolo"]: x for x in ac.listar(conectar(), 8)}["019.8888.2026.0000008-88"]
checar("a lista da conta 8 ficou intacta",
       _da_8["estado"] == "novo" and _da_8["fonte"] is None,
       f"{_da_8['estado']} / {_da_8['fonte']}")
checar("e nenhuma leitura foi escrita sob a conta 8", conectar().execute(
    "SELECT COUNT(*) FROM acompanhado_leitura WHERE usuario_id=8").fetchone()[0] == 0)
checar("nem sob a conta 7, que não segue esse número", not any(
    x["protocolo"] == "019.8888.2026.0000008-88" for x in ac.listar(conectar(), 7)))

# O ESPELHO: o mesmo corpo mentiroso sobre um número que É da conta 7 grava na
# conta 7. Sem esta metade, a checagem acima passaria com uma rota que não grava
# nunca.
_cx = conectar()
_cx.execute("""UPDATE acompanhado SET lido_em=NULL, estado='novo'
               WHERE usuario_id=7 AND protocolo='019.2020.2026.0000020-20'""")
_cx.commit(); _cx.close()
_r = _do_agente("/api/agente/acompanhamento", {
    "usuario_id": 8, "leituras": [{"protocolo": "019.2020.2026.0000020-20",
                                   "aberto_em": ["SESAB/MINHA"], "documentos": 4,
                                   "movimentos": 5}]})
checar("e o dono do token é quem recebe a leitura",
       _r.status_code == 200 and (_r.get_json() or {}).get("gravadas") == 1,
       f"{_r.status_code} {_r.get_json()}")
_do_7 = {x["protocolo"]: x for x in ac.listar(conectar(), 7)}["019.2020.2026.0000020-20"]
checar("na conta do TOKEN, não na que o corpo disse",
       _do_7["fonte"] == "sei" and _do_7["documentos"] == 4,
       f"{_do_7['fonte']} / {_do_7['documentos']}")

print("\n8-septies. as portas do agente")
_r = _c.post("/api/agente/acompanhamento", json={"leituras": []})
checar("relatar sem token é recusado", _r.status_code == 401, str(_r.status_code))
_r = _do_agente("/api/agente/acompanhamento", {"leituras": []}, tok="token-orfao")
checar("estação sem dono não relata leitura nenhuma", _r.status_code == 400,
       str(_r.status_code))
# A ROTA TRANSPORTA, e a recusa de instalação vira estado HTTP — 409, o mesmo que
# `/api/poco/plano` usa para "fora do escopo deste agente".
_r = _do_agente("/api/agente/acompanhamento",
                {"instancia": "SEI-FESF", "leituras": [
                    {"protocolo": "019.3333.2026.0000003-33", "documentos": 1}]})
checar("instalação que não é a do dono é recusada pela rota", _r.status_code == 409,
       f"{_r.status_code} {_r.get_json()}")
# CORPO QUE NÃO É JSON não pode virar 500: a estação não sabe o que fazer com 500
# e volta a tentar o mesmo para sempre.
_ts = agora()
_r = _c.post("/api/agente/acompanhamento", data=b"isto nao e json",
             headers={"Authorization": f"Bearer {_TOKEN_AG}", "X-SEI360-Ts": _ts,
                      "X-SEI360-Assinatura": _seg.assinar(_TOKEN_AG, _ts,
                                                          b"isto nao e json"),
                      "Content-Type": "application/json"})
checar("corpo que não é JSON não derruba a rota",
       _r.status_code == 200 and (_r.get_json() or {}).get("gravadas") == 0,
       f"{_r.status_code} {_r.data[:80]}")
# A ESTAÇÃO PEGA, o servidor não empurra: é o contrato dos outros `/api/agente/*`,
# e o que permite a estação rodar atrás do firewall do órgão.
_r = _do_agente("/api/agente/acompanhamento", metodo="GET", tok=_TOKEN_AG8)
checar("cada estação só enxerga a lista do próprio dono",
       _r.status_code == 200
       and "019.2222.2026.0000002-22" not in str((_r.get_json() or {}).get("protocolos")),
       str(_r.get_json())[:200])

print("\n8-octies. o cartão depois de uma recusa")
# A COMBINAÇÃO QUE SÓ AGORA EXISTE: item com delta medido na leitura de ontem e
# recusa do SEI hoje. Até a fase 2 nada escrevia 'sem_acesso', então o cartão
# nunca tinha as duas coisas ao mesmo tempo — e a etiqueta de mudança vinha na
# FRENTE do estado de recusa, contra o que o próprio comentário do template diz.
# O resultado era "saiu de X · +5 documentos" em cima de "Nada foi lido".
_cx = conectar()
_cx.execute("""UPDATE acompanhado_leitura SET medido_em=?
               WHERE usuario_id=7 AND protocolo='019.2020.2026.0000020-20'""",
            (_ANTEONTEM,))
_cx.execute("""UPDATE acompanhado SET lido_em=?
               WHERE usuario_id=7 AND protocolo='019.2020.2026.0000020-20'""",
            (_ONTEM,))
_cx.commit()
ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.2020.2026.0000020-20", "aberto_em": ["SESAB/OUTRA"],
     "aberto_em_fonte": "arvore", "documentos": 9, "movimentos": 9}]})
_cx.commit()
_com_delta = {x["protocolo"]: x for x in ac.listar(_cx, 7)}["019.2020.2026.0000020-20"]
checar("a leitura de hoje mediu mudança de verdade",
       (_com_delta["mudou"] or {}).get("documentos") == 5, str(_com_delta["mudou"]))
_cx.execute("""UPDATE acompanhado SET lido_em=?
               WHERE usuario_id=7 AND protocolo='019.2020.2026.0000020-20'""",
            (_ONTEM,))
_cx.commit()
ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": "019.2020.2026.0000020-20", "estado": "sem_acesso"}]})
_cx.commit(); _cx.close()

_r = _c.get("/acompanhamento")
_cart_recusa = cartao(_r.data.decode("utf-8", "replace"), "019.2020.2026.0000020-20")
checar("o cartão diz que o SEI recusou", "sem acesso" in _cart_recusa,
       _cart_recusa[:200] or "cartão não encontrado")
checar("e não anuncia mudança de ontem em cima de 'Nada foi lido'",
       "+5 documentos" not in _cart_recusa, _cart_recusa[:200])
# O delta NÃO é apagado do histórico — ele foi medido e é verdade sobre a leitura
# de ontem. O que muda é o que o cartão AFIRMA hoje.
checar("mas o delta continua gravado na série, porque foi medido",
       (ac.listar(conectar(), 7) and {x["protocolo"]: x for x in ac.listar(
           conectar(), 7)}["019.2020.2026.0000020-20"]["mudou"] or {}
        ).get("documentos") == 5)

print("\n8-decies. a ficha que a estação pode relatar — e a que ela não pode")
# AS TRÊS CAMADAS da seção 11 do plano, agora no conferidor do envelope:
#   * campo DO PROCESSO — vale dentro e fora da mesa, e a estação preenche;
#   * campo DA MESA — sai da LINHA do Controle de Processos daquela mesa, que para
#     processo fora das mesas da conta NÃO EXISTE. A estação não tem de onde tirar,
#     e o que ela mandasse seria da mesa em que ela está parada, não deste
#     processo;
#   * texto livre (`especificacao`, `interessados`) — existe, e o usuário
#     autorizou explicitamente em 11/09/2026 (seção 11.2).
_FICHA_DO_SEI = {
    "protocolo": "019.2222.2026.0000002-22",
    "tipo_processo": "Contratação Direta", "especificacao": "compra de insumos",
    "autuacao": "01/08/2026 10:00", "gerador_unidade": "SESAB/SUPERH",
    "gerador_usuario": "beltrana.dois", "nivel_acesso": "Público",
    "hipotese_legal": "Nenhuma", "assuntos": ["Compras"],
    "interessados": ["FESF-SUS"], "anexados": ["019.9.2026.9-99"],
    "emails_enviados": 2, "assinatura_externa": 1,
    "aberto_em": ["SESAB/ALHEIA"], "aberto_em_fonte": "arvore",
    "documentos": 7, "movimentos": 9,
}
_quadro = ac._quadro_relatado(_FICHA_DO_SEI)
for _campo, _esperado in (("tipo_processo", "Contratação Direta"),
                          ("especificacao", "compra de insumos"),
                          ("autuacao", "01/08/2026 10:00"),
                          ("gerador_unidade", "SESAB/SUPERH"),
                          ("gerador_usuario", "beltrana.dois"),
                          ("nivel_acesso", "Público"),
                          ("hipotese_legal", "Nenhuma"),
                          ("emails_enviados", 2),
                          ("assinatura_externa", 1)):
    checar(f"  {_campo} do processo chega", _quadro.get(_campo) == _esperado,
           repr(_quadro.get(_campo)))
for _campo in ("assuntos", "interessados", "anexados"):
    checar(f"  {_campo} chega como LISTA", isinstance(_quadro.get(_campo), list),
           repr(_quadro.get(_campo)))
# O QUE NÃO PODE ENTRAR, nem que a estação mande. `derivar()` calcula os cinco de
# custódia para a mesa em que a estação está parada — que não é a mesa deste
# processo —, e o marcador/anotação/atribuído saem de uma linha que não existe
# fora da mesa. Aceitar qualquer um deles seria gravar o dado de outra mesa com o
# nome deste processo.
_MENTIRA = dict(_FICHA_DO_SEI)
for _da_mesa in ac.CAMPOS_DA_MESA:
    _MENTIRA[_da_mesa] = "DA MESA ERRADA"
_quadro_mentira = ac._quadro_relatado(_MENTIRA)
checar("nenhum campo DA MESA entra pelo envelope",
       not [c for c in ac.CAMPOS_DA_MESA if _quadro_mentira.get(c) is not None],
       str([c for c in ac.CAMPOS_DA_MESA if _quadro_mentira.get(c) is not None]))
checar("e o texto da mesa errada não aparece em lugar nenhum do quadro",
       "DA MESA ERRADA" not in str(_quadro_mentira), str(_quadro_mentira)[:200])

# TIPO ERRADO VIRA None, e a leitura é gravada com o que sobrou — a mesma
# doutrina dos cinco campos antigos. Lista com elemento que não é texto não passa:
# a tela faz `u.split('/')` sobre cada item.
_torto = ac._quadro_relatado({
    "tipo_processo": {"x": 1}, "emails_enviados": "2", "assuntos": "Compras",
    "interessados": [{"nome": "alguém"}], "anexados": ["ok"], "autuacao": 7})
for _campo in ("tipo_processo", "emails_enviados", "assuntos", "interessados",
               "autuacao"):
    checar(f"  {_campo} com tipo errado vira None", _torto.get(_campo) is None,
           repr(_torto.get(_campo)))
checar("  e o campo bem formado ao lado sobrevive", _torto.get("anexados") == ["ok"],
       repr(_torto.get("anexados")))

# LISTA VAZIA NÃO É AUSÊNCIA. `[]` é "a tela existia e não tinha assunto nenhum";
# None é "não observado" — a tela Consultar/Alterar pode não existir para aquele
# processo, e o coletor já distingue os dois na coleta com `alterar_disponivel`.
_vazio = ac._quadro_relatado({"assuntos": [], "interessados": []})
checar("lista vazia passa, e é diferente de não observado",
       _vazio.get("assuntos") == [] and _vazio.get("interessados") == [],
       str(_vazio))
_ausente = ac._quadro_relatado({})
checar("campo que a estação não mandou fica None, não []",
       _ausente.get("assuntos") is None and _ausente.get("especificacao") is None,
       str(_ausente))

# E A FICHA CHEGA AO BANCO, pela ponta de verdade: `receber` -> `gravar_leitura`
# -> `listar`. Sem isto, o conferidor poderia estar certo e a coluna errada.
_cx = conectar()
_cx.execute("UPDATE acompanhado SET lido_em=NULL, tentativas=0, tentativa_em=NULL")
_cx.commit()
ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [_FICHA_DO_SEI]})
_cx.commit()
_ficha_gravada = {x["protocolo"]: x for x in ac.listar(_cx, 7)}[
    "019.2222.2026.0000002-22"]
checar("a ficha do processo fica gravada na leitura",
       _ficha_gravada["tipo_processo"] == "Contratação Direta"
       and _ficha_gravada["gerador_unidade"] == "SESAB/SUPERH",
       str({k: _ficha_gravada.get(k) for k in ("tipo_processo", "gerador_unidade")}))
checar("as listas voltam como lista, não como string de JSON",
       _ficha_gravada["assuntos"] == ["Compras"]
       and _ficha_gravada["interessados"] == ["FESF-SUS"],
       repr(_ficha_gravada.get("assuntos")))
checar("e os campos da mesa ficam NULOS para item de fora",
       not [c for c in ac.CAMPOS_DA_MESA if _ficha_gravada.get(c) is not None],
       str([c for c in ac.CAMPOS_DA_MESA if _ficha_gravada.get(c) is not None]))
_cx.commit(); _cx.close()

print("\n8-nonies. falha técnica repetida recua, em vez de insistir 34x por dia")
# O QUE ESTE BLOCO DEFENDE, em número: falha técnica não carimba `lido_em` — de
# propósito, para o item continuar pendente —, e sem recuo `pendentes` reoferecia
# o mesmo processo a cada batida do agendador. 34 ciclos x 100 itens x 5
# requisições ≈ 17 mil requisições por dia contra o SEI do órgão, três vezes a
# coleta inteira, cada ciclo abrindo um Chromium, e nada percebendo.
#
# Queda de sessão já era barata (a estação para no primeiro `SESSAO`). O caro era
# a falha sistemática que NÃO é sessão: parse, DOMException, rede intermitente.

# A COLUNA TEM DE CHEGAR AO BANCO QUE JÁ EXISTE. `CREATE TABLE IF NOT EXISTS` não
# altera tabela existente, então quem acrescenta coluna nova é a migração — e ela
# lê o próprio DDL. Este par de checagens existe porque a armadilha foi paga:
# `_colunas_do_ddl` recortava a tabela com uma expressão não-gulosa que para no
# PRIMEIRO `);`, e um `);` escrito DENTRO de um comentário do DDL truncava a
# lista de colunas ali. `tentativas` e `tentativa_em` não eram criadas em banco
# existente, e o sintoma seria "no such column" no meio de uma tela, em produção.
_COLS_DDL = banco._colunas_do_ddl(banco.DDL)
checar("a migração enxerga as colunas novas no DDL",
       {"tentativas", "tentativa_em"} <= set(_COLS_DDL.get("acompanhado", {})),
       str(list(_COLS_DDL.get("acompanhado", {}))))
checar("e nenhuma tabela do DDL é lida sem coluna nenhuma (o sinal do `);` no comentário)",
       not [t for t, c in _COLS_DDL.items() if not c],
       str([t for t, c in _COLS_DDL.items() if not c]))

_cx = conectar()
_cx.execute("UPDATE acompanhado SET tentativas=0, tentativa_em=NULL, lido_em=NULL")
_cx.commit()
_ALVO_RECUO = "019.2222.2026.0000002-22"
_ofertas = []
for _volta in range(5):
    _ofertas.append(_ALVO_RECUO in ac.pendentes(_cx, 7, "SEI-SESAB"))
    _cx.commit()
checar("as três primeiras voltas oferecem o item", _ofertas[:3] == [True] * 3,
       str(_ofertas))
checar("da quarta em diante, não mais — ele descansa até amanhã",
       _ofertas[3:] == [False, False], str(_ofertas))
_parados = ac.descansando(_cx, 7, "SEI-SESAB")
checar("e o recuo é dito, com o número e a contagem",
       any(p["protocolo"] == _ALVO_RECUO and p["tentativas"] >= 3 for p in _parados),
       str(_parados)[:200])

# LEITURA ZERA O CONTADOR, de qualquer fonte. É a resposta que o contador mede.
ac.receber(_cx, 7, "SEI-SESAB", {"leituras": [
    {"protocolo": _ALVO_RECUO, "aberto_em": ["SESAB/ALHEIA"],
     "aberto_em_fonte": "arvore", "documentos": 3, "movimentos": 4}]})
_cx.commit()
checar("leitura que chega zera a contagem",
       _cx.execute("SELECT tentativas FROM acompanhado WHERE usuario_id=7 "
                   "AND instancia='SEI-SESAB' AND protocolo=?",
                   (_ALVO_RECUO,)).fetchone()[0] == 0)
checar("e o item sai do descanso", not any(p["protocolo"] == _ALVO_RECUO
                                           for p in ac.descansando(_cx, 7, "SEI-SESAB")))

# RECUSA DO SEI TAMBÉM ZERA: a estação chegou ao processo e o SEI respondeu.
# "não é para você" é resposta, não falha técnica — e deixar o contador subir aqui
# faria o item descansar por ter sido lido.
_cx.execute("UPDATE acompanhado SET tentativas=9, lido_em=NULL WHERE usuario_id=7 "
            "AND instancia='SEI-SESAB' AND protocolo=?", (_ALVO_RECUO,))
_cx.commit()
ac.receber(_cx, 7, "SEI-SESAB",
           {"leituras": [{"protocolo": _ALVO_RECUO, "estado": "sem_acesso"}]})
_cx.commit()
checar("recusa do SEI é resposta, e também zera",
       _cx.execute("SELECT tentativas FROM acompanhado WHERE usuario_id=7 "
                   "AND instancia='SEI-SESAB' AND protocolo=?",
                   (_ALVO_RECUO,)).fetchone()[0] == 0)

# É RECUO, NÃO DESISTÊNCIA: contagem alta de ONTEM não barra nada hoje. Sem a
# comparação de data, um item que falhasse três vezes numa terça ficaria parado
# para sempre — e desistir em silêncio é pior que insistir.
_cx.execute("UPDATE acompanhado SET tentativas=9, tentativa_em=?, lido_em=NULL "
            "WHERE usuario_id=7 AND instancia='SEI-SESAB' AND protocolo=?",
            (_ONTEM, _ALVO_RECUO))
_cx.commit()
checar("contagem de ontem não barra o item hoje",
       _ALVO_RECUO in ac.pendentes(_cx, 7, "SEI-SESAB"), "não foi oferecido")
checar("e a contagem recomeça do 1, não continua de 9",
       _cx.execute("SELECT tentativas FROM acompanhado WHERE usuario_id=7 "
                   "AND instancia='SEI-SESAB' AND protocolo=?",
                   (_ALVO_RECUO,)).fetchone()[0] == 1)
_cx.commit(); _cx.close()

print("\n9. o laço que roda o coletor na estação")
# O QUE DÁ PARA PROVAR AQUI: que `_rodar_coletor` lê a linha-marca, ecoa o resto
# como log e mata pelo relógio de parede — que é o corpo que `buscar()` tinha e
# que `acompanhar()` passou a compartilhar. O coletor de mentira abaixo é um
# script Python de três linhas: ele prova o LAÇO, não o SEI.
#
# O QUE NÃO DÁ PARA PROVAR AQUI, e fica dito: que o coletor de verdade abre o
# Chromium, entra no SEI com a sessão de uma pessoa e devolve a marca. Isso exige
# a estação dela, com o segundo fator, e nenhuma fixture substitui.
import tempfile                                                  # noqa: E402
import time                                                      # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agente"))
import sei360_agente as _ag                                      # noqa: E402

_tmp = Path(tempfile.mkdtemp(prefix="sei360_coletor_"))


# O APERTO DE MÃO, que veio depois desta suíte: `_rodar_coletor` pergunta ao
# coletor quais modos ele conhece (`--modos` -> `MODOS_OK {...}`) e recusa
# trabalhar com quem não responde. O coletor de mentira aqui existe para provar o
# LAÇO, não o contrato — então ele passa o aperto de mão e o resto da cena
# continua sendo sobre o que sempre foi. É o mesmo `coletor_que_conhece` que
# `_teste_agente.py` monta do outro lado.
_APERTO_DE_MAO = (
    "import json, sys\n"
    "if '--modos' in sys.argv:\n"
    "    print('MODOS_OK ' + json.dumps({'versao': 'falso', 'modos': "
    "['--modo-falso', '--buscar', '--acompanhar']}))\n"
    "    sys.exit(0)\n")


def _coletor_falso(corpo):
    """Grava um coletor de mentira e aponta o agente para ele.

    O agente roda `[sys.executable, COLETOR, modo]` com `cwd=COLETOR.parent`, e é
    só isso que precisa ser verdade para o laço ser exercitado.
    """
    arq = _tmp / "coletor_falso.py"
    arq.write_text(_APERTO_DE_MAO + corpo, encoding="utf-8")
    _ag.COLETOR = arq
    # O CAMINHO É O MESMO A CADA CENA, e a resposta do aperto de mão fica em
    # cache POR CAMINHO: sem limpar, o coletor da cena seguinte herdaria o que o
    # anterior respondeu.
    _ag._MODOS_DO_COLETOR.clear()
    return arq


# 1) O caminho bom: log, marca, e o processo termina.
_coletor_falso(
    "import json, sys\n"
    "pedido = json.loads(sys.stdin.readline())\n"
    "print('abrindo o SEI...')\n"
    "print('MARCA_OK ' + json.dumps({'eco': pedido}))\n"
    "print('fim')\n")
_env = _ag._rodar_coletor({"a": 1}, "--modo-falso", "MARCA_OK ", 30)
checar("o envelope sai da linha-marca", (_env or {}).get("eco") == {"a": 1}, str(_env))

# 2) A marca NÃO é ecoada como log, e o resto é. Sem isso o envelope inteiro —
#    que numa busca real tem centenas de linhas — vira ruído no prompt de quem
#    está de plantão, e a linha que importa some no meio.
import io                                                        # noqa: E402
import contextlib                                                # noqa: E402
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    _ag._rodar_coletor({"a": 1}, "--modo-falso", "MARCA_OK ", 30)
_saida = _buf.getvalue()
checar("o log da estação é ecoado", "abrindo o SEI" in _saida and "fim" in _saida,
       _saida[:120])
checar("e a linha-marca não entra no log", "MARCA_OK" not in _saida, _saida[:120])

# 3) Sem marca nenhuma o envelope é None — e None é "a estação não devolveu
#    resultado", nunca um envelope vazio inventado aqui.
_coletor_falso("import sys\nsys.stdin.readline()\nprint('nada aconteceu')\n")
checar("coletor que não imprime a marca devolve None",
       _ag._rodar_coletor({}, "--modo-falso", "MARCA_OK ", 30) is None)

# 4) O TETO DE RELÓGIO. `page.evaluate` não obedece o timeout do Playwright
#    (medido: 887 s sob teto de 600 s), então quem mata é o relógio de parede.
#    O coletor de mentira fala sem parar, como o de verdade fala: é assim que o
#    teto chega a ser avaliado — o laço só olha o relógio quando uma linha chega.
_coletor_falso(
    "import sys, time\n"
    "sys.stdin.readline()\n"
    "while True:\n"
    "    print('ainda aqui'); sys.stdout.flush(); time.sleep(0.02)\n")
_t0 = time.time()
with contextlib.redirect_stdout(io.StringIO()):
    _pendurado = _ag._rodar_coletor({}, "--modo-falso", "MARCA_OK ", 1)
_gasto = time.time() - _t0
checar("coletor pendurado é morto pelo relógio e devolve None", _pendurado is None)
checar("e morre perto do teto, não depois da paciência de alguém", _gasto < 20,
       f"{_gasto:.1f}s")

# 5) E `buscar()` continua fazendo o que fazia: pergunta, monta o pedido com as
#    SEIS chaves de sempre, roda o coletor e publica o envelope na busca certa.
#    A extração não podia mudar nada disto — é o que este bloco prova.
_visto = {}


def _chamar_falso(cfg, caminho, corpo=None, metodo=None, timeout=120):
    _visto.setdefault("chamadas", []).append((caminho, metodo, corpo))
    if metodo == "GET":
        return 200, {"buscar": True, "busca_id": 77, "instancia": "SEI-SESAB",
                     "mesa": "SESAB/DGESS", "filtros": {"numero_sei": "1"},
                     "campos": {"numero_sei": ["txtProtocoloPesquisa"]},
                     "paginas_teto": 3, "segundos_teto": 30,
                     "perfil": {"instancia": "SEI-SESAB"}}
    return 200, {"estado": "concluida"}


_chamar_real = _ag.chamar
_ag.chamar = _chamar_falso
_coletor_falso(
    "import json, sys\n"
    "pedido = json.loads(sys.stdin.readline())\n"
    "print('BUSCA_OK ' + json.dumps({'busca_id': 77, 'itens': [], 'eco': pedido}))\n")
with contextlib.redirect_stdout(io.StringIO()):
    _rodou = _ag.buscar({"servidor": "http://x", "token": "t"})
_ag.chamar = _chamar_real
_posts = [c for c in _visto["chamadas"] if c[1] != "GET"]
checar("buscar() ainda roda a busca que o servidor ofereceu", _rodou is True)
checar("e publica na busca certa", bool(_posts) and _posts[0][0] == "/api/agente/busca/77",
       str(_posts[:1])[:160])
_eco = (_posts[0][2] or {}).get("eco") if _posts else {}
checar("o pedido continua levando as seis chaves da busca, e só elas",
       sorted((_eco or {}).get("busca", {})) == sorted(
           ["busca_id", "campos", "filtros", "instancia", "mesa", "paginas_teto"]),
       str(_eco)[:200])
checar("e o perfil continua viajando junto",
       ((_eco or {}).get("perfil") or {}).get("instancia") == "SEI-SESAB", str(_eco)[:200])

# 6) Envelope nenhum vira MOTIVO declarado, não silêncio: a busca fica registrada
#    como não respondida, que é o que a tela de quem pesquisou precisa dizer.
_visto["chamadas"] = []
_ag.chamar = _chamar_falso
_coletor_falso("import sys\nsys.stdin.readline()\nprint('morri')\n")
with contextlib.redirect_stdout(io.StringIO()):
    _ag.buscar({"servidor": "http://x", "token": "t"})
_ag.chamar = _chamar_real
_corpo_post = [c for c in _visto["chamadas"] if c[1] != "GET"][0][2]
checar("estação muda vira motivo declarado na busca",
       "não devolveu resultado" in (_corpo_post or {}).get("motivo", ""),
       str(_corpo_post)[:200])

print("\n9-bis. o ciclo do acompanhamento na estação")
# A ORDEM NO CICLO é o que este bloco não consegue provar sozinho, e fica dito:
# que `acompanhar` roda DEPOIS de `buscar` e ANTES da coleta é propriedade de
# `rodar()`, que abre o Chromium. O que se prova aqui é o contrato de cada ponta.
_visto["chamadas"] = []
_ag.chamar = _chamar_acomp = None


def _servidor_falso(resposta_get):
    def _f(cfg, caminho, corpo=None, metodo=None, timeout=120):
        _visto.setdefault("chamadas", []).append((caminho, metodo, corpo))
        if metodo == "GET":
            return 200, resposta_get
        return 200, {"gravadas": len(((corpo or {}).get("leituras") or [])),
                     "ignoradas": 0}
    return _f


_TAREFA = {"ler": True, "instancia": "SEI-SESAB",
           "protocolos": ["019.5120.2026.0161681-50", "019.9393.2026.0163871-16"],
           "perfil": {"instancia": "SEI-SESAB", "login_url": "https://x/",
                      "campos_busca": {"numero_sei": ["txtProtocoloPesquisa"]}}}

# 1) Nada a ler: o agente não abre o Chromium e não empurra nada.
_visto["chamadas"] = []
_ag.chamar = _servidor_falso({"ler": False, "motivo": "nada acompanhado fora da carteira"})
with contextlib.redirect_stdout(io.StringIO()):
    _fez = _ag.acompanhar({"servidor": "http://x", "token": "t"})
checar("sem trabalho, o agente não roda o coletor", _fez is False)
checar("e não escreve no servidor",
       not [c for c in _visto["chamadas"] if c[1] != "GET"], str(_visto["chamadas"]))

# 2) O caminho bom: o pedido leva número e perfil, e o que a estação leu sobe.
_visto["chamadas"] = []
_ag.chamar = _servidor_falso(_TAREFA)
_coletor_falso(
    "import json, sys\n"
    "pedido = json.loads(sys.stdin.readline())\n"
    "leituras = [{'protocolo': p, 'estado': 'lido'}\n"
    "            for p in pedido['acompanhamento']['protocolos']]\n"
    "print('ACOMP_OK ' + json.dumps({'instancia': 'SEI-SESAB',\n"
    "                               'leituras': leituras, 'eco': pedido}))\n")
with contextlib.redirect_stdout(io.StringIO()):
    _fez = _ag.acompanhar({"servidor": "http://x", "token": "t"})
_post = [c for c in _visto["chamadas"] if c[1] != "GET"]
checar("com trabalho, o agente roda", _fez is True)
checar("e publica no endpoint do acompanhamento",
       bool(_post) and _post[0][0] == "/api/agente/acompanhamento", str(_post[:1])[:160])
_eco = (_post[0][2] or {}).get("eco") if _post else {}
checar("o pedido leva a instalação e os números, e SÓ isso",
       sorted(((_eco or {}).get("acompanhamento") or {})) == ["instancia", "protocolos"],
       str(_eco)[:220])
checar("o perfil viaja junto — é ele que diz em qual SEI entrar",
       ((_eco or {}).get("perfil") or {}).get("instancia") == "SEI-SESAB", str(_eco)[:220])
# A NOTA DA PESSOA não desce, e o envelope do servidor nem a manda: este bloco
# confere que o agente não acrescenta campo nenhum por conta própria.
checar("nenhuma nota, nenhum estado, nada além do combinado",
       "nota" not in str(_eco), str(_eco)[:220])
checar("o que a estação leu sobe inteiro",
       len(((_post[0][2] or {}).get("leituras") or [])) == 2, str(_post[0][2])[:200])
checar("e a instalação vai no envelope, para o servidor CONFERIR",
       (_post[0][2] or {}).get("instancia") == "SEI-SESAB", str(_post[0][2])[:200])

# 3) A estação morreu no meio: NADA é publicado. Envelope vazio não diz nada ao
#    servidor (grava zero), e mandá-lo seria uma ida à rede para afirmar o nada.
#    O item continua pendente porque `lido_em` não foi tocado — que é o certo.
_visto["chamadas"] = []
_ag.chamar = _servidor_falso(_TAREFA)
_coletor_falso("import sys\nsys.stdin.readline()\nprint('o Chromium morreu')\n")
_log = io.StringIO()
with contextlib.redirect_stdout(_log):
    _fez = _ag.acompanhar({"servidor": "http://x", "token": "t"})
checar("estação muda não publica envelope vazio",
       not [c for c in _visto["chamadas"] if c[1] != "GET"], str(_visto["chamadas"]))
checar("mas a falha é dita em voz alta, não engolida",
       "pendente" in _log.getvalue(), _log.getvalue()[-200:])

# 4) O RECUO CHEGA AO LOG DA ESTAÇÃO. É o único lugar em que alguém vê que um
#    processo parou de ser tentado — o servidor o tira da fila em silêncio, e
#    item que some da fila é indistinguível de item que foi lido. Aparece mesmo
#    quando não há mais nada a ler, que é justamente quando importa.
_ag.chamar = _servidor_falso(
    {"ler": False, "motivo": "1 processo(s) descansam até amanhã",
     "descansando": [{"protocolo": "019.2222.2026.0000002-22", "tentativas": 3}]})
_log = io.StringIO()
with contextlib.redirect_stdout(_log):
    _fez = _ag.acompanhar({"servidor": "http://x", "token": "t"})
checar("sem trabalho o agente não roda, mas DIZ quem está descansando",
       _fez is False and "019.2222.2026.0000002-22" in _log.getvalue(),
       _log.getvalue()[-200:])
checar("e distingue recuo de falha passageira, com a contagem",
       "3x sem leitura hoje" in _log.getvalue(), _log.getvalue()[-200:])

_ag.chamar = _chamar_real

print("\n9-ter-bis. o envelope em pedaços, e o pedaço que se perde")
# POR QUE EM PEDAÇOS. Medido em 11/09/2026, depois da ficha completa: uma leitura
# passou de 277 para 825 bytes, e 100 leituras de 27 KB para 81 KB — numa linha só
# de stdout, com stderr fundido nela e sem buffer. Escrita desse tamanho não é
# atômica, e foi assim que a linha-marca corrompida virou um crítico.
#
# O corte REDUZ O RAIO: uma linha corrompida custa 20 leituras em vez de 100. Não
# fecha a janela — 16 KB por linha continua acima de qualquer garantia de
# atomicidade de pipe, e no Windows não há garantia documentada para tamanho
# nenhum. O que fecha a repetição é o recuo por `tentativas`.
_coletor_falso(
    "import json, sys\n"
    "sys.stdin.readline()\n"
    "def env(ps, extra=None):\n"
    "    d = {'instancia': 'SEI-SESAB',\n"
    "         'leituras': [{'protocolo': p, 'estado': 'lido'} for p in ps]}\n"
    "    if extra: d.update(extra)\n"
    "    return 'ACOMP_OK ' + json.dumps(d)\n"
    "print(env(['019.1111.2026.0000001-11'], {'falhas': [], 'motivo': None}))\n"
    "print('ACOMP_OK {\\\"instancia\\\": \\\"SEI-SESAB\\\", \\\"leitur')\n"
    "print(env(['019.3333.2026.0000003-33']))\n")
_vistos = _ag._rodar_coletor({}, "--modo-falso", "ACOMP_OK ", 30, varios=True)
checar("os pedaços legíveis chegam, o corrompido não", len(_vistos) == 2,
       str(_vistos))
checar("e são os dois que estavam inteiros",
       [x["leituras"][0]["protocolo"] for x in _vistos]
       == ["019.1111.2026.0000001-11", "019.3333.2026.0000003-33"], str(_vistos))
# `varios=False` é o que `buscar()` usa, e o comportamento dele não podia mudar:
# vale o ÚLTIMO envelope lido, como sempre valeu.
checar("com varios=False continua valendo um envelope só",
       (_ag._rodar_coletor({}, "--modo-falso", "ACOMP_OK ", 30) or {})
       .get("leituras", [{}])[0].get("protocolo") == "019.3333.2026.0000003-33")

# O AGENTE PUBLICA PEDAÇO POR PEDAÇO, e soma. Publicar só o último gravaria 20 de
# 100 sem erro nenhum.
_visto["chamadas"] = []
_ag.chamar = _servidor_falso(_TAREFA)
with contextlib.redirect_stdout(io.StringIO()) as _log_ped:
    _ag.acompanhar({"servidor": "http://x", "token": "t"})
_posts_ped = [c for c in _visto["chamadas"] if c[1] != "GET"]
checar("os dois pedaços legíveis são publicados", len(_posts_ped) == 2,
       str(len(_posts_ped)))
checar("e o log soma as duas gravações, dizendo que foram pedaços",
       "gravou 2" in _log_ped.getvalue() and "pedaços" in _log_ped.getvalue(),
       _log_ped.getvalue()[-200:])

# NÃO-200 NUM PEDAÇO PARA O RESTO. O 409 é "a instalação do dono mudou", e vale
# para todos os pedaços — a instalação declarada é a mesma nos três. Insistir
# seria N recusas iguais no log.
_visto["chamadas"] = []


def _servidor_que_recusa(cfg, caminho, corpo=None, metodo=None, timeout=120):
    _visto.setdefault("chamadas", []).append((caminho, metodo, corpo))
    if metodo == "GET":
        return 200, _TAREFA
    return 409, {"erro": "a estação relata leitura de outra instalação"}


_ag.chamar = _servidor_que_recusa
with contextlib.redirect_stdout(io.StringIO()) as _log_409:
    _ag.acompanhar({"servidor": "http://x", "token": "t"})
checar("recusa num pedaço para os seguintes",
       len([c for c in _visto["chamadas"] if c[1] != "GET"]) == 1,
       str(_visto["chamadas"]))
checar("e a recusa diz qual pedaço foi", "pedaço 1/2" in _log_409.getvalue(),
       _log_409.getvalue()[-200:])

# COLETOR MORTO PELO RELÓGIO joga fora o que já veio, de propósito: não há como
# saber se a última linha estava completa, e `json.loads` aceita um envelope de 20
# leituras truncado em 3 se o corte cair num lugar legal. Quem para sozinho,
# dentro do `.js`, devolve envelope inteiro com `motivo` — é esse o caminho para
# entregar leitura parcial.
_coletor_falso(
    "import json, sys, time\n"
    "sys.stdin.readline()\n"
    "print('ACOMP_OK ' + json.dumps({'instancia': 'SEI-SESAB', 'leituras': []}))\n"
    "sys.stdout.flush()\n"
    "while True:\n"
    "    print('ainda aqui'); sys.stdout.flush(); time.sleep(0.02)\n")
with contextlib.redirect_stdout(io.StringIO()):
    _morto = _ag._rodar_coletor({}, "--modo-falso", "ACOMP_OK ", 1, varios=True)
checar("morto pelo relógio não entrega pedaço nenhum", _morto == [], str(_morto))

_ag.chamar = _chamar_real

print("\n9-quater. o acompanhamento NÃO pode impedir a coleta do dia")
# OS DOIS DEFEITOS são a mesma família, e os dois foram herdados de `buscar()` —
# o que os tornou perigosos foi o acompanhamento ter ficado na FRENTE da coleta,
# rodando sozinho a cada 30 min. Em `buscar()` isso só acontecia depois de alguém
# clicar em "pesquisar".
#
#   C1 — `json.loads` da linha-marca levantava `ValueError` e a exceção subia por
#        `rodar()`: a coleta nunca chegava a ser pedida. O gatilho é real —
#        stdout e stderr fundidos, sem buffer, e envelope de dezenas de KB: uma
#        linha do Chromium no meio do `ACOMP_OK` basta.
#   C2 — o teto de relógio só é avaliado quando CHEGA uma linha; filho que
#        emudece nunca é morto. Com o acompanhamento na frente, isso segurava a
#        Trava e a coleta jamais era pedida.
#
# A ASSERÇÃO QUE IMPORTA, nos dois cenários: a coleta é pedida mesmo assim.
_ag.TRAVA = _tmp / "agente.lock"
_ag.cfg_ler = lambda: {"servidor": "http://x", "token": "t"}


class _Args:
    simular = False
    atender = False
    ignorar_teto = True          # a suíte pode rodar fora da faixa 5h-22h
    minutos = 1


def _servidor_do_ciclo(coletar=False):
    """Um servidor que oferece acompanhamento e NÃO oferece coleta.

    "Sem coleta devida" é o caminho mais curto até o fim do ciclo — e era
    justamente um dos dois `return 0` no meio de `rodar()` que faziam o
    acompanhamento, quando estava na frente, ficar antes de tudo.
    """
    def _f(cfg, caminho, corpo=None, metodo=None, timeout=120):
        _visto.setdefault("chamadas", []).append((caminho, metodo, corpo))
        if caminho == "/api/agente/busca":
            return 200, {"buscar": False}
        if caminho == "/api/agente/acompanhamento" and metodo == "GET":
            return 200, _TAREFA
        if caminho == "/api/agente/tarefa":
            return 200, {"coletar": coletar, "motivo": "fora da janela"}
        return 200, {"gravadas": 0, "ignoradas": 0}
    return _f


def _caminhos():
    return [c[0] for c in _visto.get("chamadas", [])]


# C1 — a linha-marca chega truncada no meio do JSON.
_visto["chamadas"] = []
_ag.chamar = _servidor_do_ciclo()
_coletor_falso(
    "import sys\n"
    "sys.stdin.readline()\n"
    "print('ACOMP_OK {\\\"instancia\\\": \\\"SEI-SESAB\\\", \\\"leitur')\n")
checar("marca ilegível não levanta: o ajudante devolve None",
       _ag._rodar_coletor({}, "--modo-falso", "ACOMP_OK ", 30) is None)
_visto["chamadas"] = []
_log = io.StringIO()
with contextlib.redirect_stdout(_log):
    _saiu = _ag.rodar(_Args())
checar("o ciclo termina em vez de estourar", _saiu == 0, str(_saiu))
checar("C1: A COLETA É PEDIDA mesmo com o envelope corrompido",
       "/api/agente/tarefa" in _caminhos(), str(_caminhos()))
checar("e a linha ilegível fica dita no log, não engolida",
       "ilegível" in _log.getvalue(), _log.getvalue()[-200:])

# C2 — o filho imprime o envelope e PENDURA (é o `ctx.close()` que não volta).
#      O laço só olha o relógio quando chega linha, então ele espera o EOF.
_visto["chamadas"] = []
_ag.chamar = _servidor_do_ciclo()
_coletor_falso(
    "import json, sys, time\n"
    "sys.stdin.readline()\n"
    "print('ACOMP_OK ' + json.dumps({'instancia': 'SEI-SESAB', 'leituras': []}))\n"
    "sys.stdout.flush()\n"
    "time.sleep(2)\n")                # o pendurado de verdade nunca volta
_t0 = time.time()
with contextlib.redirect_stdout(io.StringIO()):
    _ag.rodar(_Args())
_gasto = time.time() - _t0
_cam = _caminhos()
checar("o filho pendurado de fato segurou o agente", _gasto >= 1.5, f"{_gasto:.1f}s")
checar("C2: a coleta foi PEDIDA antes de o acompanhamento pendurar",
       "/api/agente/tarefa" in _cam
       and _cam.index("/api/agente/tarefa") < _cam.index("/api/agente/acompanhamento"),
       str(_cam))
checar("e o acompanhamento ainda rodou — atrás, não em vez de",
       "/api/agente/acompanhamento" in _cam, str(_cam))

# E uma exceção qualquer do acompanhamento não troca o código de saída da coleta
# que já rodou por um traceback.
_visto["chamadas"] = []
_ag.chamar = _servidor_do_ciclo()
_ag_acomp_real = _ag.acompanhar
_ag.acompanhar = lambda cfg: (_ for _ in ()).throw(RuntimeError("disco cheio"))
_log = io.StringIO()
with contextlib.redirect_stdout(_log):
    _saiu = _ag.rodar(_Args())
_ag.acompanhar = _ag_acomp_real
checar("acompanhamento que explode não derruba o ciclo", _saiu == 0, str(_saiu))
checar("e a explosão fica registrada, dizendo que a coleta não foi afetada",
       "não foi afetada" in _log.getvalue(), _log.getvalue()[-220:])

_ag.chamar = _chamar_real
import shutil                                                    # noqa: E402
shutil.rmtree(_tmp, ignore_errors=True)

print("\n9-ter. a única perda irreversível da tela fica dita")
# O botão apaga a lista E o histórico daquele processo (FK em cascata, decisão do
# desenho). Recolar o número restaura o item, não a série. Até aqui a tela não
# dizia isso em lugar nenhum, e é a única coisa que ela faz sem volta.
_html_tela = _c.get("/acompanhamento").data.decode("utf-8", "replace")
_i_bt = _html_tela.find("Parar de acompanhar")
_trecho = _html_tela[max(0, _i_bt - 400):_i_bt]
checar("o botão avisa que o histórico vai junto",
       "apaga o histórico" in _trecho, _trecho[-160:])
checar("e que recolar não o traz de volta",
       "não o histórico" in _trecho, _trecho[-160:])

print("\n10. o expurgo: a série envelhece, a lista não")
import expurgo                                                   # noqa: E402

checar("a série tem prazo próprio, e é de 180 dias",
       expurgo.DIAS.get("acompanhado_leitura") == 180,
       str(expurgo.DIAS.get("acompanhado_leitura")))
# A LISTA NÃO TEM PRAZO, e isso é afirmação, não esquecimento: ela é escolha da
# pessoa. Um prazo que aparecesse aqui um dia apagaria item que alguém ainda
# quer seguir — e processo parado há um ano é exatamente o caso.
checar("e a LISTA não tem prazo nenhum no dicionário",
       "acompanhado" not in expurgo.DIAS, str(sorted(expurgo.DIAS)))

_cx = conectar()
# A INSTALAÇÃO SAI DA MESMA LINHA do item. `listar()` devolve a lista das duas
# juntas, e a chave de `acompanhado` é o TRIO (dono, instalação, protocolo):
# semear a leitura sob 'SEI-SESAB' para um item da FESF é a FK recusando — com
# razão, porque não existe leitura sem a linha da lista.
_item = ac.listar(_cx, 7)[0]
_alvo, _inst_alvo = _item["protocolo"], _item["instancia"]
_cx.execute("""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
               lido_em,fonte,medido_em) VALUES(7,?,?,
               '2020-01-01T00:00:00-03:00','sei','2020-01-01T00:00:00-03:00')""",
            (_inst_alvo, _alvo))
_cx.commit()
_itens_antes = len(ac.listar(_cx, 7))
_recentes_antes = _cx.execute(
    "SELECT COUNT(*) FROM acompanhado_leitura WHERE lido_em > '2021-01-01'").fetchone()[0]
_cx.close()

_plano = expurgo.expurgar(simular=True)
checar("o expurgo conhece a série de leituras",
       any(t == "acompanhado_leitura" for t, _, _ in _plano), str(_plano))
checar("e a SIMULAÇÃO não apaga",
       conectar().execute("SELECT COUNT(*) FROM acompanhado_leitura "
                          "WHERE lido_em < '2021-01-01'").fetchone()[0] == 1)

expurgo.expurgar()
_cx = conectar()
_velhas = _cx.execute("SELECT COUNT(*) FROM acompanhado_leitura "
                      "WHERE lido_em < '2021-01-01'").fetchone()[0]
_recentes = _cx.execute("SELECT COUNT(*) FROM acompanhado_leitura "
                        "WHERE lido_em > '2021-01-01'").fetchone()[0]
_itens = ac.listar(_cx, 7)
checar("leitura velha sai", _velhas == 0, str(_velhas))
# A RÉGUA É A DATA, não a tabela: apagar a série inteira "porque é série" levaria
# junto a leitura de ontem, que é o que a tela mostra.
checar("e a leitura recente do MESMO item fica",
       _recentes == _recentes_antes, f"{_recentes} != {_recentes_antes}")
checar("a LISTA não é apagada por idade", len(_itens) == _itens_antes,
       f"{len(_itens)} != {_itens_antes}")
checar("nem por cascata: a FK corre de acompanhado PARA leitura, não ao contrário",
       any(x["protocolo"] == _alvo for x in _itens),
       str([x["protocolo"] for x in _itens])[:200])

# E A CASCATA EXISTE MESMO — na direção certa. É dela que o botão "Parar de
# acompanhar" depende, e é por isso que o histórico daquele processo é perda
# IRREVERSÍVEL: recolar o número devolve o item, nunca a série.
_cx.execute("""INSERT INTO acompanhado(usuario_id,instancia,protocolo,origem,
               adicionado_em,estado) VALUES(7,'SEI-SESAB','019.7777.2026.0000077-77',
               'manual',?,'novo')""", (agora(),))
_cx.execute("""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
               lido_em,fonte,medido_em) VALUES(7,'SEI-SESAB',
               '019.7777.2026.0000077-77',?,'sei',?)""", (agora(), agora()))
_cx.execute("""DELETE FROM acompanhado WHERE usuario_id=7 AND instancia='SEI-SESAB'
               AND protocolo='019.7777.2026.0000077-77'""")
_cx.commit()
checar("apagar o item da lista leva o histórico dele junto",
       _cx.execute("""SELECT COUNT(*) FROM acompanhado_leitura
                      WHERE protocolo='019.7777.2026.0000077-77'""").fetchone()[0] == 0)
_cx.close()

print("\n11. a leitura estagnada não vira base de comparação")
# O DEFEITO MEDIDO EM 11/09/2026, e o que a guarda de monotonicidade NÃO cobria.
# `gravar_leitura` cala o delta quando a medição anda para trás ('sem_avanco'),
# mas a linha estagnada continuava sendo a ÚLTIMA INSERIDA — e a leitura fresca
# seguinte comparava contra ela, ressuscitando inteiro o delta que a guarda tinha
# acabado de suprimir:
#
#   t1 (10/09): aberto=[A,B]    docs=10 movs=20   comparacao=primeira
#   t2 (02/09): aberto=[A,B,C]  docs=8  movs=14   comparacao=sem_avanco (mudou=None)
#   t3 (hoje) : aberto=[B]      docs=11 movs=21
#       dizia   -> saiu de A, C · +3 documentos · +7 movimentos
#       verdade -> saiu de A    · +1 documento  · +1 movimento
#
# A verdade é contra t1, a última observação FRESCA — nunca contra t2, que a
# própria guarda declarou não ser observação nova.
_cx = conectar()
_ALVO_C1 = "019.1717.2026.0000017-17"
_OITO_DIAS = (janelas.com_fuso(agora()) - timedelta(days=8)).isoformat(timespec="seconds")
ac.adicionar(_cx, 7, _ALVO_C1, "SEI-SESAB")
_cx.commit()


def _ler_c1(protocolo, unidades, docs, movs, medido, fonte="carteira"):
    """Uma leitura crua, direto em `gravar_leitura`: é ELE que está sob teste."""
    return ac.gravar_leitura(_cx, 7, "SEI-SESAB", protocolo,
                             {"aberto_em": unidades, "aberto_em_fonte": "arvore",
                              "documentos": docs, "movimentos": movs},
                             fonte=fonte, medido_em=medido)


_ler_c1(_ALVO_C1, ["SESAB/A", "SESAB/B"], 10, 20, _ONTEM)
_d_estagnada = _ler_c1(_ALVO_C1, ["SESAB/A", "SESAB/B", "SESAB/C"], 8, 14, _OITO_DIAS)
_cx.commit()
checar("(cena) a medição que andou para trás não anuncia mudança",
       _d_estagnada is None, str(_d_estagnada))
_d_fresca = _ler_c1(_ALVO_C1, ["SESAB/B"], 11, 21, agora(), fonte="sei")
_cx.commit()
checar("a leitura fresca compara contra a última FRESCA, não contra a estagnada",
       (_d_fresca or {}).get("saiu_de") == ["SESAB/A"], str(_d_fresca))
checar("e as contagens são as de verdade, não as ressuscitadas",
       ((_d_fresca or {}).get("documentos"), (_d_fresca or {}).get("movimentos"))
       == (1, 1), str(_d_fresca))
checar("o texto da tela sai dessa verdade",
       ac.texto_do_delta(_d_fresca) == "saiu de A · +1 documento · +1 movimento",
       ac.texto_do_delta(_d_fresca))
_c1 = {x["protocolo"]: x for x in ac.listar(_cx, 7)}[_ALVO_C1]
checar("e a leitura de hoje se declara COMPARADA", _c1["comparacao"] == "comparada",
       str(_c1["comparacao"]))

# `medido_em` ACEITA NULO na coluna (linha anterior à régua, ou gravada fora de
# `gravar_leitura`), e linha sem carimbo não tem lugar na linha do tempo: ela não
# pode ser a base de comparação enquanto houver uma datada. Em SQLite, NULL é
# menor que tudo e `DESC` já a joga para o fim — a ordem escreve isso à mão para
# não depender do padrão do banco.
_ALVO_C1_NULO = "019.1818.2026.0000018-18"
ac.adicionar(_cx, 7, _ALVO_C1_NULO, "SEI-SESAB")
_cx.commit()
_ler_c1(_ALVO_C1_NULO, ["SESAB/A"], 5, 5, _ONTEM)
_cx.execute("""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
               lido_em,fonte,medido_em,aberto_em,documentos,movimentos)
               VALUES(7,'SEI-SESAB',?,?,'carteira',NULL,'["SESAB/Z"]',99,99)""",
            (_ALVO_C1_NULO, agora()))
_cx.commit()
_d_sem_carimbo = _ler_c1(_ALVO_C1_NULO, ["SESAB/A"], 6, 5, agora())
_cx.commit()
checar("leitura sem carimbo não vira base: compara-se com a última DATADA",
       (_d_sem_carimbo or {}).get("documentos") == 1, str(_d_sem_carimbo))
checar("e o `saiu_de` de uma linha sem carimbo não é inventado",
       "saiu_de" not in (_d_sem_carimbo or {}), str(_d_sem_carimbo))

# E QUANDO TODAS AS ANTERIORES ESTÃO SEM CARIMBO, o lado seguro do erro: sem
# frescor estabelecido não se anuncia mudança nenhuma.
_ALVO_C1_SO_NULO = "019.1919.2026.0000019-19"
ac.adicionar(_cx, 7, _ALVO_C1_SO_NULO, "SEI-SESAB")
_cx.execute("""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
               lido_em,fonte,medido_em,aberto_em,documentos,movimentos)
               VALUES(7,'SEI-SESAB',?,?,'carteira',NULL,'["SESAB/Z"]',99,99)""",
            (_ALVO_C1_SO_NULO, agora()))
_cx.commit()
_d_tudo_nulo = _ler_c1(_ALVO_C1_SO_NULO, ["SESAB/A"], 1, 1, agora())
_cx.commit()
_so_nulo = {x["protocolo"]: x for x in ac.listar(_cx, 7)}[_ALVO_C1_SO_NULO]
checar("só linhas sem carimbo: nada é anunciado, e a leitura diz por quê",
       _d_tudo_nulo is None and _so_nulo["comparacao"] == "sem_avanco",
       f"{_d_tudo_nulo} / {_so_nulo['comparacao']}")
_cx.commit(); _cx.close()

print("\n12. coleta que não trouxe mesa nenhuma não é 'saiu de'")
# O CENÁRIO MEDIDO EM 11/09/2026: o MESMO processo, na MESMA unidade, em duas
# coletas — a segunda sem nenhuma linha em `processo_mesa`, que é o que acontece
# quando a árvore não parseia (o comentário de `reaproveitar` já dizia que
# acontece de verdade). `reaproveitar` entregava `aberto_em: []`, `delta`
# guardava com `is not None`, e o conjunto vazio passava como OBSERVAÇÃO: a
# subtração devolvia todas as unidades anteriores.
#
#   mudou = {'saiu_de': ['SESAB/MINHA']}   texto = 'saiu de MINHA'
#
# O processo não se moveu. E o cartão saía autocontraditório: a etiqueta dizia
# "saiu de MINHA" e três linhas abaixo o template dizia "a leitura não trouxe
# unidade nenhuma".
_cx = conectar()
_ALVO_C2 = "019.2424.2026.0000024-24"
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,
               movimentos,medido_em,mesas_fonte)
               VALUES(900,'2424',?,4,6,?,'arvore')""", (_ALVO_C2, _ANTEONTEM))
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'2424','SESAB/MINHA',NULL)""")
_cx.commit()
ac.adicionar(_cx, 7, _ALVO_C2, "SEI-SESAB")
_cx.commit()
checar("(cena) a primeira coleta responde, com a unidade da árvore",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") >= 1)
_cx.commit()
_c2_um = {x["protocolo"]: x for x in ac.listar(_cx, 7)}[_ALVO_C2]
checar("(cena) e a leitura registra a unidade",
       _c2_um["aberto_em"] == ["SESAB/MINHA"], str(_c2_um["aberto_em"]))

# A COLETA SEGUINTE, mais fresca e SEM linha de mesa: a árvore não parseou.
_cx.execute("DELETE FROM processo_mesa WHERE snapshot_id=900 AND id_sei='2424'")
_cx.execute("UPDATE processo SET medido_em=? WHERE snapshot_id=900 AND id_sei='2424'",
            (_ONTEM,))
_cx.execute("UPDATE acompanhado SET lido_em=? WHERE usuario_id=7 AND protocolo=?",
            (_ONTEM, _ALVO_C2))
_cx.commit()
checar("(cena) a segunda coleta também responde",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") >= 1)
_cx.commit()
_c2 = {x["protocolo"]: x for x in ac.listar(_cx, 7)}[_ALVO_C2]
# A COMPARAÇÃO ACONTECEU — não é a guarda de monotonicidade calando tudo, é o
# conjunto vazio deixando de virar afirmação.
checar("a segunda leitura foi comparada de verdade",
       _c2["comparacao"] == "comparada", str(_c2["comparacao"]))
checar("coleta sem linha de mesa NÃO anuncia saída de unidade",
       "saiu_de" not in (_c2["mudou"] or {}), str(_c2["mudou"]))
checar("e a tela não escreve 'saiu de MINHA' sobre processo que não se moveu",
       "saiu de" not in ac.texto_do_delta(_c2["mudou"]),
       ac.texto_do_delta(_c2["mudou"]))
# O OUTRO CANAL, que o conserto óbvio (`mesas or None`) matava: a lista VAZIA
# continua chegando à coluna, porque é ela que deixa a tela dizer "a leitura não
# trouxe unidade nenhuma" em vez de o item parecer nunca lido.
checar("a lista vazia continua chegando à leitura, e não vira 'nunca lido'",
       _c2["aberto_em"] == [] and _c2["fonte"] == "carteira",
       f"{_c2['aberto_em']!r} / {_c2['fonte']}")
_cx.commit(); _cx.close()

_r = _c.get("/acompanhamento")
_csrf = _csrf_do(_r, _csrf)
_cart_c2 = cartao(_r.data.decode("utf-8", "replace"), _ALVO_C2)
checar("o cartão diz que a leitura não trouxe unidade",
       "não trouxe unidade nenhuma" in _cart_c2, _cart_c2[:300])
checar("e não afirma, na mesma linha, que o processo saiu da unidade",
       "saiu de" not in _cart_c2, _cart_c2[:300])

# A REGRA, no nível do delta: conjunto vazio não é observação — nem do lado novo
# (que dizia "saiu de tudo") nem do lado anterior (que diria "foi recebido em
# tudo"). É o que o próprio template afirma sobre `[]`: "a coleta daquele dia não
# disse onde o processo está", nunca "não está aberto em lugar nenhum".
_com_unidade = {"aberto_em": ["SESAB/MINHA"], "documentos": 4, "movimentos": 6}
_sem_unidade = {"aberto_em": [], "documentos": 4, "movimentos": 6}
checar("conjunto novo vazio não vira 'saiu de todas'",
       ac.delta(_com_unidade, _sem_unidade) is None,
       str(ac.delta(_com_unidade, _sem_unidade)))
checar("conjunto anterior vazio não vira 'foi recebido em todas'",
       ac.delta(_sem_unidade, _com_unidade) is None,
       str(ac.delta(_sem_unidade, _com_unidade)))
checar("mas o conjunto vazio não cala a contagem que mudou",
       ac.delta(_com_unidade, dict(_sem_unidade, documentos=6))
       == {"documentos": 2},
       str(ac.delta(_com_unidade, dict(_sem_unidade, documentos=6))))

print("\n13. a ficha que sobrevive à recusa do SEI tem de dizer de quando é")
# O CENÁRIO MEDIDO EM 11/09/2026: item lido pela carteira, e HOJE o SEI recusa o
# processo àquele login. A recusa não insere leitura (certo — recusa não é
# observação), mas `listar()` traz a leitura ANTERIOR pelo LEFT JOIN, `fonte`
# fica preenchida e o expandir abre a ficha inteira: marcador URGENTE, anotação,
# responsável — sem uma palavra dizendo de quando é. `texto_da_ficha` devolvia
# "" porque `_dia_da_medicao` cala em estado de recusa, e a docstring dela promete
# o contrário: "NUNCA VAZIA quando houve leitura... ficha sem carimbo passa por
# ficha de agora".
#
# As duas frases têm alcances OPOSTOS e por isso a regra de recusa não pode viver
# na função que fatia a data: o rodapé do cartão TEM de calar (senão sai "Nada foi
# lido" e, embaixo, "pela sua coleta de 09/09") e a ficha TEM de carimbar.
_cx = conectar()
_ALVO_I1 = "019.2525.2026.0000025-25"
_DIA_I1 = f"{_ANTEONTEM[8:10]}/{_ANTEONTEM[5:7]}"
_cx.execute("""INSERT INTO processo(snapshot_id,id_sei,protocolo,documentos,
               movimentos,medido_em,mesas_fonte,tipo_processo,marcador,
               marcador_cor,atribuido_nome,visualizado)
               VALUES(900,'2525',?,3,3,?,'arvore','Administrativo: Pagamento',
               'URGENTE','vermelho','Ana Souza',1)""", (_ALVO_I1, _ANTEONTEM))
_cx.execute("""INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido)
               VALUES(900,'2525','SESAB/MINHA',NULL)""")
_cx.execute("""INSERT INTO processo_texto(snapshot_id,id_sei,anotacao,anotacao_autor)
               VALUES(900,'2525','cobrar a nota','ana.souza')""")
_cx.commit()
ac.adicionar(_cx, 7, _ALVO_I1, "SEI-SESAB")
_cx.commit()
checar("(cena) a carteira responde a ficha inteira",
       ac.reaproveitar(_cx, 7, "SEI-SESAB") >= 1)
_cx.commit()
# E HOJE O SEI RECUSA. A leitura não entra na série; o estado do item, sim.
ac.receber(_cx, 7, "SEI-SESAB",
           {"leituras": [{"protocolo": _ALVO_I1, "estado": "sem_acesso"}]})
_cx.commit()
_i1 = {x["protocolo"]: x for x in ac.listar(_cx, 7)}[_ALVO_I1]
checar("(cena) o item está em recusa e ainda tem a ficha da leitura anterior",
       _i1["estado"] == "sem_acesso" and _i1["marcador"] == "URGENTE",
       f"{_i1['estado']} / {_i1['marcador']}")
checar("a ficha em recusa NÃO fica sem carimbo — é a promessa da docstring",
       ac.texto_da_ficha(_i1) != "", repr(ac.texto_da_ficha(_i1)))
checar("e o carimbo diz de QUANDO ela é",
       _DIA_I1 in ac.texto_da_ficha(_i1), ac.texto_da_ficha(_i1))
checar("e diz que a leitura de hoje não aconteceu",
       "hoje nada foi lido" in ac.texto_da_ficha(_i1), ac.texto_da_ficha(_i1))
# OS CAMPOS DA MESA são os que alguém lê para decidir o que fazer HOJE — o
# carimbo tem de alcançá-los pelo nome, porque é sob o título "da sua mesa" que
# eles aparecem para um processo que já não está em mesa nenhuma da conta.
checar("o carimbo alcança também os campos da mesa, pelo nome",
       "marcador" in ac.texto_da_ficha(_i1), ac.texto_da_ficha(_i1))
# O RODAPÉ DO CARTÃO CONTINUA CALADO: é a outra metade da mesma regra, e ela não
# pode ter mudado de lado no caminho.
checar("o rodapé do cartão continua sem procedência em recusa",
       ac.texto_da_procedencia(_i1) == "", repr(ac.texto_da_procedencia(_i1)))
# E a régua normal, fora de recusa, não mudou.
checar("fora de recusa a ficha continua dizendo o que sempre disse",
       "campos desta ficha" in ac.texto_da_ficha(
           {"fonte": "carteira", "estado": "lido", "medido_em": _ANTEONTEM}),
       ac.texto_da_ficha({"fonte": "carteira", "estado": "lido",
                          "medido_em": _ANTEONTEM}))
checar("e item nunca lido continua sem ficha nenhuma",
       ac.texto_da_ficha({"estado": "novo"}) == "",
       repr(ac.texto_da_ficha({"estado": "novo"})))
# RECUSA SEM DATA DE MEDIÇÃO: a coluna aceita nulo, e ficha sem carimbo passa por
# ficha de agora — que é exatamente o que esta função existe para impedir.
_i1_sem_data = {"fonte": "carteira", "estado": "sem_acesso", "medido_em": None}
checar("recusa sem data de medição também não fica sem carimbo",
       "de quando" in ac.texto_da_ficha(_i1_sem_data),
       repr(ac.texto_da_ficha(_i1_sem_data)))
# `texto_sem_mesa` falava no PRESENTE a partir da linha VELHA: em recusa, o que a
# leitura anterior viu não é o que vale hoje.
checar("em recusa, a frase da mesa fala da leitura anterior, não do hoje",
       "leitura anterior" in ac.texto_sem_mesa({"fonte": "sei",
                                                "estado": "sem_acesso"})
       and "NÃO existem" not in ac.texto_sem_mesa({"fonte": "sei",
                                                   "estado": "sem_acesso"}),
       repr(ac.texto_sem_mesa({"fonte": "sei", "estado": "sem_acesso"})))
checar("fora de recusa ela continua a mesma",
       "NÃO existem" in ac.texto_sem_mesa({"fonte": "sei", "estado": "lido"}),
       repr(ac.texto_sem_mesa({"fonte": "sei", "estado": "lido"})))
_cx.commit(); _cx.close()

_r = _c.get("/acompanhamento")
_csrf = _csrf_do(_r, _csrf)
_cart_i1 = cartao(_r.data.decode("utf-8", "replace"), _ALVO_I1)
checar("o cartão em recusa diz que nada foi lido", "Nada foi lido" in _cart_i1,
       _cart_i1[:200])
checar("a ficha continua aberta com o que já se sabia", "URGENTE" in _cart_i1,
       _cart_i1[:300])
checar("mas agora ela sai carimbada com o dia da leitura anterior",
       _DIA_I1 in _cart_i1 and "hoje nada foi lido" in _cart_i1, _cart_i1[:600])

print("\n14. item de instalação que não é a ativa: a tela diz que ele não será lido")
# O QUE FOI MEDIDO EM 11/09/2026: três ciclos completos do agente e o item da
# FESF nunca é oferecido — a rota pede `instancia_do_agente`, que é a
# configuração ATIVA do dono, e a estação entra numa instalação só. O item fica
# 'novo' para sempre e a tela diz "aguardando primeira leitura", indistinguível
# de "vai ser lido hoje à noite". Nada avisava a pessoa.
#
# A fila continua sendo de UMA instalação (é onde a estação faz login); o que não
# pode continuar é o silêncio.
import configuracao as cfg                                       # noqa: E402

_cx = conectar()
_ALVO_I2 = "019.3030.2026.0000030-30"
_cx.execute("""DELETE FROM acompanhado_leitura WHERE usuario_id=7
               AND instancia='SEI-FESF' AND protocolo=?""", (_ALVO_I2,))
_cx.execute("""UPDATE acompanhado SET estado='novo', lido_em=NULL, tentativas=0,
               tentativa_em=NULL WHERE usuario_id=7 AND instancia='SEI-FESF'
               AND protocolo=?""", (_ALVO_I2,))
_cx.commit()
_ativa_i2 = cfg.ler(_cx, 7)["sistema"]
_cx.close()
checar("(cena) a configuração ativa da conta é a outra instalação",
       _ativa_i2 == "SEI-SESAB", str(_ativa_i2))
_ciclos = []
for _volta in range(3):
    _ciclos.append(((_do_agente("/api/agente/acompanhamento", metodo="GET")
                     .get_json() or {}).get("protocolos")) or [])
checar("(cena) três ciclos, e o item da outra instalação nunca é oferecido",
       not any(_ALVO_I2 in c for c in _ciclos), str(_ciclos)[:200])

_i2 = {x["protocolo"]: x for x in ac.listar(conectar(), 7)}[_ALVO_I2]
checar("o item continua 'novo' — a fila não passa por ele",
       _i2["estado"] == "novo", str(_i2["estado"]))
checar("e o módulo sabe dizer por que ele não vai ser lido",
       "configuração ativa" in ac.texto_fora_da_fila(_i2, "SEI-SESAB"),
       repr(ac.texto_fora_da_fila(_i2, "SEI-SESAB")))
checar("a frase nomeia as DUAS instalações, que é o que a pessoa precisa comparar",
       all(t in ac.texto_fora_da_fila(_i2, "SEI-SESAB", rotulo_do_item="FESF",
                                      rotulo_ativa="SESAB")
           for t in ("FESF", "SESAB")),
       repr(ac.texto_fora_da_fila(_i2, "SEI-SESAB", rotulo_do_item="FESF",
                                  rotulo_ativa="SESAB")))
# NADA DE RUÍDO NOS DOIS CASOS EM QUE O ITEM ESTÁ EM DIA: carimbar o aviso em
# toda linha da outra instalação ensina a não ler o carimbo — é a mesma regra do
# `multi_instancia` do painel.
checar("item da instalação ativa não ganha aviso nenhum",
       ac.texto_fora_da_fila({"instancia": "SEI-SESAB", "estado": "novo"},
                             "SEI-SESAB") == "")
checar("nem o da outra instalação que a PRÓPRIA coleta já respondeu hoje",
       ac.texto_fora_da_fila({"instancia": "SEI-FESF", "estado": "lido",
                              "lido_em": agora()}, "SEI-SESAB") == "",
       repr(ac.texto_fora_da_fila({"instancia": "SEI-FESF", "estado": "lido",
                                   "lido_em": agora()}, "SEI-SESAB")))
# Mas o que foi lido ONTEM e não é da instalação ativa está parado, e isso conta.
checar("o que ficou para trás desde ontem ganha o aviso",
       ac.texto_fora_da_fila({"instancia": "SEI-FESF", "estado": "lido",
                              "lido_em": _ONTEM}, "SEI-SESAB") != "")

_r = _c.get("/acompanhamento")
_csrf = _csrf_do(_r, _csrf)
_cart_i2 = cartao(_r.data.decode("utf-8", "replace"), _ALVO_I2)
checar("o cartão para de dizer só 'aguardando primeira leitura'",
       "não entra na fila da estação" in _cart_i2, _cart_i2[:400])
checar("e diz em qual instalação a estação está lendo hoje",
       "SESAB" in _cart_i2 and "FESF" in _cart_i2, _cart_i2[:400])
_cart_normal = cartao(_r.data.decode("utf-8", "replace"),
                      "019.1111.2026.0000001-11")
checar("o cartão da instalação ativa continua sem o aviso",
       "não entra na fila" not in _cart_normal, _cart_normal[:200])
# A cena mexeu no contador de entregas de TODA a fila da SESAB; as cenas
# seguintes contam a partir do zero.
_cx = conectar()
_cx.execute("UPDATE acompanhado SET tentativas=0, tentativa_em=NULL")
_cx.commit(); _cx.close()

print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
