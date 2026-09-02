# -*- coding: utf-8 -*-
"""
Expurgo. O que não se apaga, se acumula — e aqui o que se acumula é dado pessoal.

POR QUE ISTO PRECISA EXISTIR
----------------------------
Medido nesta base: ~1.169 linhas de processo por coleta e ~1,3 KB de banco por
linha. Com duas coletas por dia útil, são ~745 MB por ano de snapshot histórico.
O tamanho é o menor dos problemas: são nome completo, e-mail institucional e
especificação de processo que pode citar paciente, retidos por prazo
indeterminado — o oposto do que a LGPD chama de necessidade e do que o próprio
ARQUITETURA_ACESSO.md §7.7 promete.

O QUE NÃO SE APAGA, NUNCA
-------------------------
O snapshot CORRENTE de cada unidade, mesmo velho. Se a coleta parou há um mês, o
painel tem de continuar mostrando o último estado conhecido COM A IDADE dele na
tela — apagar deixaria a unidade em branco, e branco lê-se como "não há processo
parado", que é a mentira mais cara que este sistema pode contar.

    python expurgo.py --simular    # mostra o que faria, não apaga nada
    python expurgo.py              # apaga
"""
import sys
from datetime import datetime, timedelta

from banco import conectar, agora, registrar, TZ

# Prazos. Cada um responde a uma pergunta concreta, não a um número redondo.
DIAS = {
    # histórico de snapshot: serve para reconstruir o que o painel mostrava numa
    # data. 30 dias cobrem a janela em que alguém ainda contesta uma triagem.
    "snapshot": 30,
    # log de acesso: prazo de investigação de incidente. É o registro que responde
    # "quem viu o quê" — some por último e some depois de todo o resto.
    "log_acesso": 180,
    # tentativa de login: só serve para o bloqueio, que olha 24 h para trás.
    "tentativas_login": 7,
    # sessão encerrada ou vencida: não serve para nada depois de morta.
    "sessoes": 7,
    # alerta reconhecido: quem leu, leu.
    "alerta": 90,
    # alerta NÃO reconhecido: sem prazo próprio ele era eterno, e a fila só
    # crescia — 78 abertos, dos quais 77 eram do mesmo defeito. Fila que nunca
    # esvazia deixa de ser lida, e aí o alerta que importa some no meio. Prazo
    # longo de propósito: é mais tempo do que qualquer investigação real precisa.
    "alerta_aberto": 365,
    # execução: o histórico de coleta é barato e conta a história da automação.
    "execucao": 180,
    # resumo de IA: texto GERADO sobre um retrato de uma data. Passado o prazo do
    # snapshot que ele descreve, não sobra nada com que conferir se o texto está
    # certo — e resumo velho que ninguém pode auditar é a pior forma de dado
    # pessoal: parece fonte, não é, e não tem como ser contestado. Vive um pouco
    # mais que o snapshot (60 > 30) porque a rodada de descrição é semanal e não
    # pode perder o texto no meio do ciclo.
    "resumo": 60,
    # poço: o bloco compartilhado do processo. Não morre com o snapshot — é essa
    # a razão de ele existir —, então precisa de prazo PRÓPRIO, senão vira a
    # primeira tabela permanente do sistema. E ela tem nome e e-mail de quem
    # movimentou (`mov_custodia`, `gerador_usuario`), concentrados.
    #
    # 7 dias, e não 90. O prazo tem de responder à pergunta que o CÓDIGO faz, e o
    # código nunca serve bloco com mais de 72 h (`poco.TETO_H`). Guardar 90 dias
    # era ~29x mais retenção do que a função precisa — sobre a tabela que
    # concentra nome e e-mail de quem movimentou (`mov_custodia`,
    # `gerador_usuario`) e que, por desenho, NÃO morre com o snapshot.
    #
    # Por que 7 e não 3: a folga cobre o fim de semana prolongado em que ninguém
    # coleta, para que a segunda-feira ainda encontre o bloco e o rediscuta em vez
    # de relê-lo inteiro. Acima disso o dado só acumula risco.
    "poco": 7,
    # busca: lista de trabalho, não acervo. 30 dias é mais do que a memória de
    # quem pesquisou e menos do que o tempo em que o resultado ainda descreve o
    # SEI — a carteira anda ~7% por dia útil. Ela guarda protocolo, unidade e
    # quem gerou; texto livre não entra (é o que pode citar paciente, e vive em
    # `processo_texto`, com consentimento por unidade).
    "busca": 30,
    # reserva de leitura: vive 20 minutos por desenho. Uma semana já é folga
    # enorme para o caso de a execução que a criou nunca ter sido apagada.
    "poco_reserva": 7,
}


def _corte(dias):
    return (datetime.now(TZ) - timedelta(days=dias)).isoformat(timespec="seconds")


# De quanto em quanto tempo a faxina roda sozinha. Um dia: os prazos são de
# 30/60/180 dias, então rodar mais vezes não apaga nada a mais — só gasta.
INTERVALO_H = 20


def devido(cx, agora_dt=None):
    """Está na hora de expurgar? (e ninguém já está fazendo)

    A marca é uma linha em `log_acesso`, que é onde este sistema registra o que
    aconteceu — não uma tabela nova para guardar um carimbo. Assim a última
    faxina aparece no mesmo lugar em que se audita todo o resto.
    """
    from datetime import datetime, timedelta

    from banco import TZ
    from janelas import com_fuso
    agora_dt = agora_dt or datetime.now(TZ)
    r = cx.execute("""SELECT ts FROM log_acesso WHERE acao IN ('expurgo','expurgo_auto')
                      ORDER BY id DESC LIMIT 1""").fetchone()
    if not r:
        return True
    try:
        return com_fuso(r["ts"]) < agora_dt - timedelta(hours=INTERVALO_H)
    except (TypeError, ValueError):
        return True


def reivindicar(cx):
    """Marca a faxina como iniciada. Devolve False se outro worker chegou antes.

    A marca é gravada ANTES de expurgar, e por isso mesmo: com três workers, a
    varredura roda nos três quase ao mesmo tempo. Quem grava primeiro leva; os
    outros veem a marca fresca em `devido()` e vão embora. Marcar depois seria
    deixar a janela inteira aberta.
    """
    from banco import agora, registrar
    if not devido(cx):
        return False
    registrar(cx, None, "expurgo_auto", alvo="iniciado")
    cx.commit()
    return True


def expurgar(simular=False, usuario_id=None):
    cx = conectar()
    plano = []

    # 1. Snapshots velhos, JAMAIS o corrente de cada unidade. `processo`,
    #    `processo_texto` e `processo_mesa` caem junto por ON DELETE CASCADE —
    #    daí a FK ter sido acrescentada: sem ela o texto livre ficaria órfão,
    #    fora de qualquer filtro por unidade e invisível para o expurgo seguinte.
    #    Só `expirado` e `rejeitado` saem. `corrente` é o último estado conhecido
    #    da unidade e `candidato` é uma decisão pendente de alguém — apagar o
    #    primeiro deixa a unidade em branco, apagar o segundo descarta em silêncio
    #    uma conferência que ninguém fez. A primeira versão desta consulta ainda
    #    tinha uma guarda de "preservar o mais recente de cada unidade", que se
    #    sobrepunha à regra e impedia o expurgo de fazer o próprio trabalho.
    alvo_snap = cx.execute("""
        SELECT id FROM snapshot
        WHERE estado IN ('expirado','rejeitado') AND coletado_em < ?
    """, (_corte(DIAS["snapshot"]),)).fetchall()
    ids = [r["id"] for r in alvo_snap]
    if ids:
        marc = ",".join("?" * len(ids))
        linhas = cx.execute(f"SELECT COUNT(*) FROM processo WHERE snapshot_id IN ({marc})",
                            ids).fetchone()[0]
        plano.append(("snapshot", len(ids), f"{linhas} linhas de processo em cascata"))
        if not simular:
            cx.execute(f"DELETE FROM processo WHERE snapshot_id IN ({marc})", ids)
            cx.execute(f"DELETE FROM processo_texto WHERE snapshot_id IN ({marc})", ids)
            cx.execute(f"DELETE FROM processo_mesa WHERE snapshot_id IN ({marc})", ids)
            cx.execute(f"DELETE FROM snapshot WHERE id IN ({marc})", ids)

    # 2. Filhos órfãos, de QUALQUER origem.
    #    A FK com ON DELETE CASCADE entrou no DDL depois que este banco nasceu, e
    #    `CREATE TABLE IF NOT EXISTS` não reescreve tabela existente: em toda
    #    instalação anterior à mudança o cascade simplesmente não vale. Quem
    #    apagar um snapshot por fora — pela mão, por script, por engano — deixa
    #    para trás justamente `processo_texto`, que é onde pode haver nome de
    #    paciente, agora fora de qualquer filtro por unidade. Varrer por órfão
    #    cobre o caso sem depender de a FK existir.
    for tabela in ("processo", "processo_texto", "processo_mesa"):
        n = cx.execute(f"""SELECT COUNT(*) FROM {tabela}
                           WHERE snapshot_id NOT IN (SELECT id FROM snapshot)""").fetchone()[0]
        if n:
            plano.append((tabela + " (órfão)", n, "snapshot já não existe"))
            if not simular:
                cx.execute(f"""DELETE FROM {tabela}
                               WHERE snapshot_id NOT IN (SELECT id FROM snapshot)""")

    # 3. Resumo de IA: órfão, e velho demais para ser conferido.
    orfaos = cx.execute("""SELECT COUNT(*) FROM resumo WHERE id_sei NOT IN
                           (SELECT DISTINCT id_sei FROM processo)""").fetchone()[0]
    if orfaos:
        plano.append(("resumo", orfaos, "sem processo correspondente"))
        if not simular:
            cx.execute("""DELETE FROM resumo WHERE id_sei NOT IN
                          (SELECT DISTINCT id_sei FROM processo)""")

    # Token de recuperação e código de segundo fator vencidos há mais de 30 dias.
    # São hashes, não segredo em texto — mas guardá-los para sempre é acumular
    # linha que ninguém vai consultar, e a auditoria de um pedido de recuperação
    # interessa por semanas.
    import acesso as _ac
    if simular:
        from datetime import datetime as _dt, timedelta as _td
        # NAO chamar isto de _corte: o modulo ja tem uma FUNCAO com esse nome,
        # e a atribuicao aqui a transformaria em variavel local da funcao
        # inteira — inclusive nas linhas ACIMA, que a chamam. O sintoma foi
        # UnboundLocalError num expurgo que nao tinha nada a ver com e-mail.
        _corte30 = (_dt.now(TZ) - _td(days=30)).isoformat(timespec="seconds")
        _r = cx.execute("SELECT COUNT(*) FROM recuperacao WHERE criado_em < ?",
                        (_corte30,)).fetchone()[0]
        _d = cx.execute("SELECT COUNT(*) FROM desafio WHERE criado_em < ?",
                        (_corte30,)).fetchone()[0]
    else:
        _r, _d = _ac.faxina(cx)
    if _r:
        plano.append(("recuperacao", _r, "link vencido há mais de 30 dias"))
    if _d:
        plano.append(("desafio", _d, "código vencido há mais de 30 dias"))
    # `descrito_em` é data pura (AAAA-MM-DD); o corte é ISO com hora. Comparar
    # como texto funciona porque o prefixo é o mesmo — e o recorte de 10 deixa
    # isso explícito em vez de depender de sorte lexicográfica.
    velhos = cx.execute("SELECT COUNT(*) FROM resumo WHERE substr(descrito_em,1,10) < ?",
                        (_corte(DIAS["resumo"])[:10],)).fetchone()[0]
    if velhos:
        plano.append(("resumo", velhos, f"descrevem coleta de mais de {DIAS['resumo']} dias"))
        if not simular:
            cx.execute("DELETE FROM resumo WHERE substr(descrito_em,1,10) < ?",
                       (_corte(DIAS["resumo"])[:10],))

    # 4. Sessões mortas. A viva de hoje fica, custe o que custar ao contador.
    mortas = cx.execute("""SELECT COUNT(*) FROM sessoes
                           WHERE (revogada_em IS NOT NULL AND revogada_em < ?)
                              OR expira_em < ?""",
                        (_corte(DIAS["sessoes"]), _corte(0))).fetchone()[0]
    if mortas:
        plano.append(("sessoes", mortas, "revogadas ou vencidas"))
        if not simular:
            cx.execute("""DELETE FROM sessoes
                          WHERE (revogada_em IS NOT NULL AND revogada_em < ?)
                             OR expira_em < ?""", (_corte(DIAS["sessoes"]), _corte(0)))

    # 5. Tabelas simples, por data.
    for tabela, coluna, cond in (("tentativas_login", "ts", ""),
                                 ("log_acesso", "ts", ""),
                                 ("execucao", "terminado_em", " AND terminado_em IS NOT NULL"),
                                 ("alerta", "ts", " AND reconhecido_em IS NOT NULL")):
        n = cx.execute(f"SELECT COUNT(*) FROM {tabela} WHERE {coluna} < ?{cond}",
                       (_corte(DIAS[tabela]),)).fetchone()[0]
        if n:
            plano.append((tabela, n, f"mais de {DIAS[tabela]} dias"))
            if not simular:
                cx.execute(f"DELETE FROM {tabela} WHERE {coluna} < ?{cond}",
                           (_corte(DIAS[tabela]),))

    # 5-poço. O bloco compartilhado, a guarda dele e o acompanhamento por dono.
    # Os três saem juntos: guarda sem bloco só responde "mudou?" sobre um bloco
    # que não existe mais, e acompanhamento sem bloco é dado pessoal sem uso.
    # `busca_item` cai por CASCADE junto da busca — não precisa de varredura
    # própria, e ter uma seria um segundo prazo para divergir do primeiro.
    n = cx.execute("SELECT COUNT(*) FROM busca WHERE pedida_em < ?",
                   (_corte(DIAS["busca"]),)).fetchone()[0]
    if n:
        plano.append(("busca", n, f"pedidas há mais de {DIAS['busca']} dias"))
        if not simular:
            cx.execute("DELETE FROM busca WHERE pedida_em < ?", (_corte(DIAS["busca"]),))

    for tabela, coluna in (("poco_processo", "morno_em"),
                           ("poco_conferencia", "em"),
                           ("poco_acompanhamento", "em"),
                           ("poco_reserva", "reserva_ate")):
        prazo = DIAS["poco_reserva"] if tabela == "poco_reserva" else DIAS["poco"]
        n = cx.execute(f"SELECT COUNT(*) FROM {tabela} WHERE {coluna} < ?",
                       (_corte(prazo),)).fetchone()[0]
        if n:
            plano.append((tabela, n, f"sem leitura há mais de {prazo} dias"))
            if not simular:
                cx.execute(f"DELETE FROM {tabela} WHERE {coluna} < ?", (_corte(prazo),))

    # 5b. Alerta que ninguém reconheceu. Fica muito mais tempo que o reconhecido,
    # mas não fica para sempre.
    n_ab = cx.execute("SELECT COUNT(*) FROM alerta WHERE ts < ? AND reconhecido_em IS NULL",
                      (_corte(DIAS["alerta_aberto"]),)).fetchone()[0]
    if n_ab:
        plano.append(("alerta", n_ab, f"abertos há mais de {DIAS['alerta_aberto']} dias"))
        if not simular:
            cx.execute("DELETE FROM alerta WHERE ts < ? AND reconhecido_em IS NULL",
                       (_corte(DIAS["alerta_aberto"]),))

    # 6. Órfãos DE NOVO, agora que execuções e snapshots já foram apagados.
    #    A varredura do passo 2 roda ANTES do passo 5; apagar `execucao` leva
    #    junto os snapshots que apontam para ela, e os filhos desses snapshots
    #    ficariam órfãos até a próxima rodada. `processo_texto` é onde pode
    #    haver nome de paciente: passar o expurgo e continuar com ele no banco
    #    é exatamente o que o expurgo existe para impedir.
    for tabela in ('processo', 'processo_texto', 'processo_mesa'):
        sobra = (f'FROM {tabela} WHERE snapshot_id NOT IN (SELECT id FROM snapshot)')
        n = cx.execute('SELECT COUNT(*) ' + sobra).fetchone()[0]
        if n:
            plano.append((tabela, n, 'órfão depois de apagar execução'))
            if not simular:
                cx.execute('DELETE ' + sobra)

    if not simular and plano:
        # O expurgo entra no log de acesso: apagar dado pessoal é tratamento, e
        # tratamento sem registro é exatamente o que o art. 37 cobra.
        registrar(cx, usuario_id, "expurgo",
                  alvo="; ".join(f"{t}:{n}" for t, n, _ in plano))
        cx.commit()
        # VACUUM devolve o espaço ao disco. Sem ele o arquivo só cresce, mesmo
        # depois de apagar — e o volume do EasyPanel é pago por tamanho.
        cx.execute("VACUUM")
    cx.close()
    return plano


if __name__ == "__main__":
    simular = "--simular" in sys.argv
    from banco import BANCO
    antes = BANCO.stat().st_size
    plano = expurgar(simular=simular)
    print(("SIMULAÇÃO — nada foi apagado" if simular else "EXPURGO") + f"  ({BANCO})")
    if not plano:
        print("  nada a apagar")
    for tabela, n, motivo in plano:
        print(f"  {tabela:18} {n:>6}  ({motivo})")
    if not simular:
        depois = BANCO.stat().st_size
        print(f"  banco: {antes/1024/1024:.1f} MB -> {depois/1024/1024:.1f} MB")
    print("\nprazos vigentes:", ", ".join(f"{k}={v}d" for k, v in DIAS.items()))
