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
# carimbo. `aberto_em_fonte` diz se as unidades vieram da ÁRVORE do SEI ou da
# máquina de estados do andamento — a segunda errou em 100% dos 1.278 casos
# observáveis medidos em 10/09/2026.
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

print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
