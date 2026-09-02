# -*- coding: utf-8 -*-
"""
A migração que troca CHAVE, e não só acrescenta coluna.

POR QUE ISTO NÃO CABIA EM `banco.migrar()`
------------------------------------------
`migrar()` compara o DDL com o banco coluna a coluna e faz `ALTER TABLE ADD
COLUMN`. Isso resolve coluna nova e não resolve nada de chave: `CREATE TABLE IF
NOT EXISTS` não reescreve tabela existente, e o SQLite não tem `ALTER TABLE` que
mude PRIMARY KEY.

Num banco já criado, a PK de `credencial` continuaria sendo `usuario_id`
sozinho — e cadastrar a segunda instância apagaria a primeira em silêncio, que é
exatamente o defeito que a chave nova existe para impedir. Migração de chave é
reconstrução de tabela, e reconstrução de tabela merece arquivo próprio, com
teste próprio.

O QUE ELA FAZ
-------------
Para cada tabela cuja chave mudou: cria a nova a partir do DDL vigente, copia as
linhas carimbando `instancia`/`sistema` com 'SEI-SESAB', derruba a antiga e
renomeia. Guardada por `PRAGMA user_version`: roda uma vez e nunca mais.

O backfill é 'SEI-SESAB' porque é o que existe — as unidades correntes do banco
são SESAB/* e a única configuração é SEI-SESAB. Não é chute: é o único valor que
o dado de hoje pode ter.

DEPOIS DELA, O DDL RODA DE NOVO
-------------------------------
`DROP TABLE` leva junto os índices e o GATILHO `resumo_exige_procedencia` — que é
o que impede resumo de IA entrar sem procedência. Quem sabe recriá-los é o DDL, e
ele é todo `IF NOT EXISTS`. Esquecer isso desarmaria uma trava sem que nada
falhasse.
"""
import re

# Versão do ESQUEMA, não do produto. Sobe quando alguma migração precisa correr
# uma vez e nunca mais. 3 = a instância entrou nas chaves.
ESQUEMA = 3

NL = "\n"

# (tabela, expressão do SELECT antigo). A ordem das colunas do INSERT sai do DDL,
# então nunca há duas listas para divergir — a única coisa escrita à mão aqui é
# de ONDE vem cada valor, e o literal 'SEI-SESAB' do backfill.
_DE = {
    "credencial": "usuario_id,sistema,login,segredo,nonce,algo,"
                  "criado_em,ultimo_uso_em,usos",
    # SEM funcao de SQL aqui: a lista e partida por virgula, e um COALESCE(a,b)
    # vira duas colunas na hora do split. O NULL e consertado depois do INSERT,
    # por UPDATE, que e legivel e nao depende de parser.
    "config_usuario": "usuario_id,sistema,sei_login,mesas_modo,"
                      "mesas,janelas,dias,modo_coleta,passo,decididos,"
                      "concluida_em,atualizado_em",
    "usuario_unidade": "usuario_id,'SEI-SESAB',unidade,principal,"
                       "concedida_por,concedida_em,origem",
    "poco_conferencia": "id_sei,'SEI-SESAB',mesa,hash,em",
    "poco_acompanhamento": "id_sei,'SEI-SESAB',mesa,dono_usuario_id,dados,grupos,em",
    "poco_reserva": "id_sei,'SEI-SESAB',execucao_id,reserva_ate",
    "resumo": "id_sei,'SEI-SESAB',curto,longo,descrito_em,gerado_em,gerado_por",
    # poco_processo tem 30+ colunas: a lista sai do DDL em tempo de execução.
    # Escrevê-la aqui seria uma segunda lista, a divergir na primeira coluna que
    # alguém acrescentasse.
    "poco_processo": None,
}


def restricoes_do_ddl(ddl, tabela):
    """PRIMARY KEY / UNIQUE do DDL — que `_colunas_do_ddl` descarta de propósito.

    Sem elas a tabela reconstruída nasceria SEM chave nenhuma: a migração
    "funcionaria", e a proteção que ela existe para instalar não estaria lá.
    """
    m = re.search(r"CREATE TABLE IF NOT EXISTS " + tabela + r"\s*\((.*?)\);", ddl, re.S)
    if not m:
        return ""
    corpo = re.sub(r"--[^" + NL + r"]*", "", m.group(1))
    fora, nivel, atual = [], 0, ""
    for ch in corpo + ",":
        if ch == "(":
            nivel += 1
        elif ch == ")":
            nivel -= 1
        if ch == "," and nivel == 0:
            item = " ".join(atual.split())
            atual = ""
            if item.upper().startswith(("PRIMARY KEY", "UNIQUE")):
                fora.append(item)
        else:
            atual += ch
    return ("," + NL + "  " + ("," + NL + "  ").join(fora)) if fora else ""


def precisa(cx):
    return cx.execute("PRAGMA user_version").fetchone()[0] < ESQUEMA


def migrar_instancia(cx, ddl, colunas_do_ddl):
    """Reconstrói as tabelas cuja CHAVE mudou. Devolve o que foi refeito."""
    if not precisa(cx):
        return []
    do_ddl = colunas_do_ddl(ddl)
    feitas = []
    # OFF durante a troca: as tabelas são recriadas e renomeadas, e uma FK
    # apontando para o nome antigo no meio do caminho abortaria a migração
    # inteira. O PRAGMA não vale dentro de transação — por isso fica aqui fora.
    cx.execute("PRAGMA foreign_keys=OFF")
    try:
        for tabela, de in _DE.items():
            if tabela not in do_ddl:
                continue
            info = list(cx.execute("PRAGMA table_info(" + tabela + ")"))
            if not info:
                continue                      # tabela nova: o DDL já a criou certa
            existentes = {r["name"] for r in info}
            pk = [r["name"] for r in info if r["pk"]]
            marca = next((c for c in ("instancia", "sistema") if c in do_ddl[tabela]), None)
            if marca and marca in pk:
                continue                      # já migrada
            cols = list(do_ddl[tabela])
            if de is None:                    # poco_processo: derivado do DDL
                de = ",".join("'SEI-SESAB'" if c == marca else c for c in cols)
            # Só copia coluna que existe nos DOIS lados: um banco antigo pode não
            # ter as colunas acrescentadas por ALTER em versões intermediárias.
            colunas_de = de.split(",")
            if len(colunas_de) != len(cols):
                raise RuntimeError(
                    tabela + ": a lista de origem tem " + str(len(colunas_de))
                    + " item(ns) e o DDL tem " + str(len(cols))
                    + ". As duas TEM de andar juntas — se alguem acrescentou "
                      "coluna ao DDL, acrescente aqui tambem.")
            pares = [(d.strip(), a) for d, a in zip(colunas_de, cols)
                     if d.strip().startswith("'") or d.strip() in existentes]
            defs = ("," + NL + "  ").join(c + " " + do_ddl[tabela][c] for c in cols)
            cx.execute("CREATE TABLE _n_" + tabela + "(" + NL + "  " + defs
                       + restricoes_do_ddl(ddl, tabela) + ")")
            cx.execute("INSERT INTO _n_" + tabela
                       + "(" + ",".join(a for _, a in pares) + ") SELECT "
                       + ",".join(d for d, _ in pares) + " FROM " + tabela)
            # O carimbo, para quem veio com a coluna vazia de um banco antigo.
            # Depois do INSERT e nao dentro dele: funcao de SQL na lista de
            # colunas quebra o split por virgula.
            if marca:
                cx.execute("UPDATE _n_" + tabela + " SET " + marca
                           + "='SEI-SESAB' WHERE " + marca + " IS NULL OR "
                           + marca + "=''")
            n = cx.execute("SELECT COUNT(*) FROM _n_" + tabela).fetchone()[0]
            cx.execute("DROP TABLE " + tabela)
            cx.execute("ALTER TABLE _n_" + tabela + " RENAME TO " + tabela)
            feitas.append(tabela + " (" + str(n) + " linha(s))")
        cx.execute("PRAGMA user_version=" + str(ESQUEMA))
        cx.commit()
    finally:
        cx.execute("PRAGMA foreign_keys=ON")
    return feitas
