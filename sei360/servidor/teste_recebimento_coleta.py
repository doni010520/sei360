# -*- coding: utf-8 -*-
"""O que a coleta FAZ ao SEI, e não só o que lê dele.

Em 11/09/2026 mediu-se, sobre 15 coletas do acervo e sem tocar no SEI, que a
coleta diária estava RECEBENDO processos: 38% dos recebimentos de fim de semana
caíam numa janela de 22 minutos (o acaso daria 1,5%), dois domingos tinham 100%
dos recebimentos do dia ali dentro, e dentro da janela 72 de 79 estavam no nome
da conta que roda a coleta. O mecanismo: 80 de 80 estavam EM TRÂNSITO, e no SEI
receber é abrir.

`ingestao.recebidos_pela_coleta` existe para esse efeito parar de ser invisível.
Esta suíte prende a detecção — que ela ache a assinatura real e, sobretudo, que
ela NÃO acuse movimento humano.

Não toca banco nenhum: a função é pura sobre a estrutura da coleta.

    python teste_recebimento_coleta.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingestao                                              # noqa: E402

ok, falhas = 0, []


def checar(nome, cond, det=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {det}")


MESA = "SESAB/SAIS/DGGUP/DGESS"
OUTRA = "SESAB/SAIS/DGGUP/DGESS/ASTEC"
COLETA = "2026-08-27T07:45:00-03:00"      # a coleta medida terminou ~07:45


def proc(protocolo, mov):
    """`mov_custodia` vem do mais NOVO para o mais antigo, como o coletor grava."""
    return {"protocolo": protocolo, "mov_custodia": list(reversed(mov))}


def remessa(dh, un, de_onde):
    return {"dh": dh, "un": un, "us": "humano@saude.ba.gov.br",
            "de": f"Processo remetido pela unidade {de_onde}"}


def recebimento(dh, un, us):
    return {"dh": dh, "un": un, "us": us, "de": "Processo recebido na unidade"}


print("1. a assinatura medida")
# Remetido às 17:59 de véspera, recebido às 07:30 pela coleta: é o caso real,
# reproduzido do processo 019.4982.2026.0132175-69.
_em_transito = proc("019.4982.2026.0132175-69", [
    remessa("26/08/2026 17:59", MESA, "SESAB/SAIS/DGGUP/DGESS/COMASUP"),
    recebimento("27/08/2026 07:30", MESA, "zaine.lima@saude.ba.gov.br")])
_r = ingestao.recebidos_pela_coleta([_em_transito], [MESA], COLETA)
checar("processo em trânsito recebido na janela é detectado", len(_r) == 1, str(_r))
checar("e o achado diz protocolo, unidade, hora e login",
       _r and _r[0][0] == "019.4982.2026.0132175-69" and _r[0][1] == MESA
       and _r[0][3] == "zaine.lima@saude.ba.gov.br", str(_r))

print("\n2. o que NÃO pode ser acusado")
# Recebimento humano no meio da tarde: mesma unidade, mesmo trânsito, outra hora.
_humano = proc("019.1111.2026.0000001-11", [
    remessa("26/08/2026 17:59", MESA, "SESAB/OUTRA"),
    recebimento("27/08/2026 14:22", MESA, "willian.damascena@saude.ba.gov.br")])
checar("recebimento humano fora da janela não é acusado",
       ingestao.recebidos_pela_coleta([_humano], [MESA], COLETA) == [])

# Recebimento DENTRO da janela, mas sem remessa antes: não estava em trânsito,
# então não é a assinatura. Sem esta exigência, o acaso entraria na conta.
_sem_transito = proc("019.2222.2026.0000002-22", [
    {"dh": "20/08/2026 09:00", "un": MESA, "us": "x@y",
     "de": "Processo público gerado na unidade"},
    recebimento("27/08/2026 07:31", MESA, "zaine.lima@saude.ba.gov.br")])
checar("recebimento na janela SEM trânsito antes não é acusado",
       ingestao.recebidos_pela_coleta([_sem_transito], [MESA], COLETA) == [])

# Unidade que não é desta coleta: o efeito é de quem coletou, não de quem leu.
checar("recebimento em unidade fora desta coleta não é acusado",
       ingestao.recebidos_pela_coleta([_em_transito], [OUTRA], COLETA) == [])

print("\n3. bordas que não podem derrubar a ingestão")
checar("coleta sem `coletado_em` não estoura",
       ingestao.recebidos_pela_coleta([_em_transito], [MESA], None) == [])
checar("data em formato estranho é ignorada, não levanta",
       ingestao.recebidos_pela_coleta(
           [proc("019.3", [remessa("26/08/2026 17:59", MESA, "X"),
                           {"dh": "ontem", "un": MESA, "us": "z",
                            "de": "Processo recebido na unidade"}])],
           [MESA], COLETA) == [])
checar("processo sem mov_custodia não estoura",
       ingestao.recebidos_pela_coleta([{"protocolo": "019.4"}], [MESA], COLETA) == [])
checar("lista vazia devolve lista vazia",
       ingestao.recebidos_pela_coleta([], [MESA], COLETA) == [])

print("\n4. várias unidades na mesma coleta")
# O gatilho medido é a ENTRADA NA MESA: os recebimentos saem agrupados por
# unidade, em minutos diferentes (DGESS às 07:30; ASTEC às 07:31).
_duas = [_em_transito,
         proc("019.4979.2025.0055118-72", [
             remessa("26/08/2026 16:40", OUTRA, "SESAB/OUTRA"),
             recebimento("27/08/2026 07:31", OUTRA, "zaine.lima@saude.ba.gov.br")])]
_r2 = ingestao.recebidos_pela_coleta(_duas, [MESA, OUTRA], COLETA)
checar("as duas unidades da coleta são detectadas", len(_r2) == 2, str(_r2))
checar("e cada achado carrega a unidade certa",
       {u for _, u, _, _ in _r2} == {MESA, OUTRA}, str(_r2))

print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
