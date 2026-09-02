# -*- coding: utf-8 -*-
"""
Primeira carga: banco, ingestão da coleta mais recente, contas e agente.

Idempotente no que importa: rodar de novo NÃO recria conta existente nem duplica
agente. A ingestão, sim, cria snapshot novo — é o comportamento certo, porque
cada execução da coleta é um snapshot com data própria.

    python semear.py
    python semear.py --coleta _coletas/sei_sesab_2026-08-17.json
"""
import json, secrets, sys
from pathlib import Path

import banco, seguranca as seg
from banco import conectar, agora
from ingestao import ingerir

ADMIN = "admin@sei360.local"
GESTOR = "gestor@sei360.local"


def conta(cx, email, nome, papel, unidades, origem="admin"):
    """Cria a conta se não existir. Devolve (senha_provisoria|None, id)."""
    ja = cx.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
    if ja:
        return None, ja["id"]
    provisoria = secrets.token_urlsafe(9)
    h, sal = seg.hash_senha(provisoria)
    cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,criado_em,ativo)
                  VALUES(?,?,?,?,?,?,?,1)""", (email, nome, h, sal, papel, origem, agora()))
    uid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
    for i, un in enumerate(unidades):
        cx.execute("""INSERT INTO usuario_unidade(usuario_id,unidade,principal,concedida_em)
                      VALUES(?,?,?,?)""", (uid, un, 1 if i == 0 else 0, agora()))
    return provisoria, uid


def main():
    banco.migrar()
    alvo = None
    if "--coleta" in sys.argv:
        alvo = sys.argv[sys.argv.index("--coleta") + 1]
    # No container nao existe C:\Claude\...\_coletas, e *.json esta no
    # .dockerignore: se criar o primeiro admin dependesse de ingerir uma coleta,
    # nao haveria como entrar num deploy novo. Bootstrap de conta e ingestao sao
    # coisas separadas, e a primeira nao pode depender da segunda.
    if "--so-contas" in sys.argv:
        rel = {"arquivo": "(nenhuma — bootstrap só de contas)", "unidades": [], "resumos": 0}
    else:
        try:
            rel = ingerir(alvo)
        except SystemExit as e:
            print(f"sem coleta para ingerir ({e}); seguindo só com as contas")
            rel = {"arquivo": "(nenhuma)", "unidades": [], "resumos": 0}
    print(f"ingestão: {rel['arquivo']}")
    for u in rel["unidades"]:
        print("   ", u["unidade"], "->", u.get("processos", "FALHOU"), u["estado"])

    cx = conectar()
    unidades = [r["unidade"] for r in cx.execute(
        "SELECT DISTINCT unidade FROM snapshot WHERE estado='corrente' ORDER BY unidade")]

    senhas = {}
    s, _ = conta(cx, ADMIN, "Administração SEI360", "admin", [])   # admin não lê carteira
    if s: senhas[ADMIN] = s

    # Conta de DEMONSTRAÇÃO só quando explicitamente pedida. `--so-contas` é o
    # modo de bootstrap de produção: criar ali um "gestor@sei360.local" com senha
    # provisória seria plantar uma conta de e-mail previsível numa instalação
    # real, e ninguém lembraria de apagá-la.
    demo = "--demo" in sys.argv
    if demo and unidades:
        s, _ = conta(cx, GESTOR, "Gestor (demonstração)", "gestor", unidades)
        if s: senhas[GESTOR] = s
        # Uma conta amarrada a UMA unidade torna a fronteira verificável na tela,
        # em vez de declarada no documento.
        uma = next((u for u in unidades if u.endswith("CESS")), unidades[0])
        s, _ = conta(cx, "servidor@sei360.local", "Servidor (demonstração)", "servidor", [uma])
        if s: senhas["servidor@sei360.local"] = s
    elif demo:
        print("--demo pedido, mas não há snapshot: contas de demonstração não criadas")
    if not unidades:
        print("nenhum snapshot no banco: criando apenas a conta de administração")

    # Semeia as contas dos atribuídos reais como INATIVAS: elas aparecem para o
    # admin aprovar. Semear ativo seria criar acesso para gente que não pediu.
    #
    # E SEMEIA O VÍNCULO JUNTO. O SELECT já faz `processo JOIN snapshot`: a
    # unidade em que a pessoa está atribuída chega na MESMA linha, e era
    # descartada. Criar a conta sem o vínculo não adianta nada — `snapshots_de`
    # recorta a carteira por vínculo, então a pessoa entra e vê uma tela vazia.
    # O único outro caminho para dar escopo é cada uma digitar a senha do SEI em
    # /configuracao, e isso não escala para dezenas de pessoas.
    #
    # `ativo` e `senha_hash` continuam INTOCADOS: aprovar segue sendo ato do
    # admin. Dar escopo não é dar acesso — a conta permanece inativa e sem senha
    # até alguém decidir o contrário.
    #
    # O `continue` de quem já existe também sumiu: as contas semeadas antes desta
    # correção existem e estão sem vínculo nenhum, e pular a linha as deixaria
    # assim para sempre.
    novos, vinculos = 0, 0
    for r in cx.execute("""SELECT DISTINCT atribuido_login AS login,
                                  atribuido_nome AS nome,
                                  s.unidade AS unidade,
                                  COALESCE(s.instancia,'SEI-SESAB') AS instancia
                           FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
                           WHERE s.estado='corrente' AND atribuido_login IS NOT NULL"""):
        email = (r["login"] or "").strip().lower()
        if not email or "@" not in email:
            continue
        ja = cx.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
        if ja:
            uid = ja["id"]
        else:
            cx.execute("""INSERT INTO usuarios(email,nome,papel,origem,criado_em,ativo)
                          VALUES(?,?,'servidor','auto_snapshot',?,0)""",
                       (email, r["nome"], agora()))
            uid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
            novos += 1
        # `OR IGNORE` sobre a chave (usuario_id, instancia, unidade): rodar de
        # novo não duplica, e vínculo concedido à mão pelo admin não é
        # sobrescrito — a `origem` dele fica como está, que é o que distingue
        # "derivei do snapshot" de "alguém decidiu".
        vinculos += cx.execute("""INSERT OR IGNORE INTO usuario_unidade
                                  (usuario_id,instancia,unidade,origem,concedida_em)
                                  VALUES(?,?,?,'snapshot',?)""",
                               (uid, r["instancia"], r["unidade"], agora())).rowcount

    # Agente da estação que hoje roda a coleta. Nome e titular são metadado; a
    # credencial NÃO passa por aqui e não existe coluna para ela.
    ag = cx.execute("SELECT id FROM agentes WHERE nome_estacao=?", ("ESTACAO-COLETA",)).fetchone()
    codigo = None
    if not ag:
        cx.execute("""INSERT INTO agentes(nome_estacao,unidades_esperadas,ativo,criado_em,
                      credencial_titular,credencial_login_mascarado)
                      VALUES(?,?,1,?,?,?)""",
                   ("ESTACAO-COLETA", json.dumps(unidades, ensure_ascii=False), agora(),
                    "titular a preencher", "z****@saude.ba.gov.br"))
        aid = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
        cx.execute("""INSERT INTO agendamento(agente_id,janelas,dias,tolerancia_min,ativo)
                      VALUES(?,?,'uteis',90,1)""", (aid, json.dumps(["07:30"])))
        import hashlib
        codigo = secrets.token_urlsafe(12)
        from datetime import timedelta, datetime
        cx.execute("""INSERT INTO enrolamentos(codigo_sha256,agente_id,criado_em,expira_em)
                      VALUES(?,?,?,?)""",
                   (hashlib.sha256(codigo.encode()).digest(), aid, agora(),
                    (datetime.now(banco.TZ) + timedelta(hours=2)).isoformat(timespec="seconds")))
    cx.commit(); cx.close()

    print(f"\nunidades correntes: {len(unidades)}")
    print(f"contas semeadas do snapshot (inativas, aguardando aprovação): {novos}")
    print(f"vínculos de unidade derivados do snapshot: {vinculos}"
          "  — escopo, não acesso: as contas seguem inativas")
    if senhas:
        print("\n--- SENHAS PROVISÓRIAS (aparecem só agora) ---")
        for e, s in senhas.items():
            print(f"  {e:28} {s}")
        print("  Todas exigem troca no primeiro acesso, antes de qualquer tela.")
    else:
        print("\ncontas já existiam — nenhuma senha nova gerada")
    if codigo:
        print(f"\ncódigo de vínculo do agente (2 h, uso único): {codigo}")


if __name__ == "__main__":
    main()
