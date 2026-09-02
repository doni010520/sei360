# -*- coding: utf-8 -*-
"""Extrai os resumos do resultado do workflow e VALIDA antes de gravar.

Validar nao e zelo: o resumo vai virar a linha principal do painel. Um id trocado
poe o resumo de um processo em cima de outro, e isso nao se percebe olhando a tela.
"""
import json, re, sys, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
SAIDA = BASE / "_resumos" / "resumos.json"
# Sem default: um caminho fixo faz da re-execucao silenciosa o caminho de menor
# esforco — rodar sem argumento reprocessaria a saida de agentes de outro dia.
if len(sys.argv) < 2:
    sys.exit("uso: python _extrair_resumos.py <caminho .output da rodada de resumos>")
ORIGEM = Path(sys.argv[1])

resumos = json.loads(ORIGEM.read_text(encoding="utf-8"))["result"]["resumos"]
COLETA = sorted(
    p for p in (BASE / "_coletas").glob("sei_sesab_*.json") if "anterior" not in p.name)[-1]
dados = json.loads(COLETA.read_text(encoding="utf-8"))

# A data exibida no painel e a da COLETA que o texto descreve, NAO a do dia em que a
# extracao rodou. Rodar a extracao dias depois nao pode rejuvenescer o resumo — 96%
# dos resumos longos afirmam estado ("aberto na X", "recebido em DD/MM").
# E a mesma regra que gerar_painel.py ja aplica a COLETA_EM; aqui ela faltava.
m = re.fullmatch(r"sei_sesab_(\d{4}-\d{2}-\d{2})", COLETA.stem)
COLETA_EM = m.group(1) if m else datetime.date.fromtimestamp(
    COLETA.stat().st_mtime).isoformat()

validos, ids = {d["id"]: d for d in dados}, set()
bons, problemas = [], []
for r in resumos:
    i = r.get("id")
    if i not in validos:
        problemas.append(f"id {i} nao existe na coleta"); continue
    if i in ids:
        problemas.append(f"id {i} duplicado"); continue
    curto, longo = (r.get("curto") or "").strip(), (r.get("longo") or "").strip()
    if not curto or not longo:
        problemas.append(f"{i}: resumo vazio"); continue
    # o protocolo ja esta na tela ao lado; repeti-lo no resumo e desperdicio de linha
    if validos[i].get("protocolo") and validos[i]["protocolo"] in curto:
        curto = curto.replace(validos[i]["protocolo"], "").strip(" —-·,")
    ids.add(i)
    # Carimbo obrigatorio: 91% dos resumos longos afirmam ESTADO ("aberto na DGESS",
    # "recebido em 13/08") e o painel roda todo dia enquanto o resumo nao. Sem a data,
    # o texto vira uma afirmacao desatualizada com cara de atual.
    bons.append({"id": i, "curto": curto, "longo": longo,
                 "coleta_em": COLETA_EM,                          # o que o texto descreve
                 "gerado_em": datetime.date.today().isoformat()})  # procedencia

SAIDA.parent.mkdir(exist_ok=True)
# FUNDE com o que ja existe, nao substitui. Sobrescrever o arquivo inteiro a partir de
# UMA saida de agentes apagaria resumos vindos de outras rodadas (o fluxo incremental
# --novos produz saidas separadas) — perda silenciosa de trabalho ja pago.
antes = {r["id"]: r for r in json.loads(SAIDA.read_text(encoding="utf-8"))} if SAIDA.exists() else {}
mantidos = len(antes)
for b in bons:
    antes[b["id"]] = b
SAIDA.write_text(json.dumps(list(antes.values()), ensure_ascii=False, indent=1), encoding="utf-8")
ids = set(antes)
faltam = [d["protocolo"] for d in dados if d["id"] not in ids]
print(f"(fundido com {mantidos} resumo(s) ja existentes -> {len(antes)} no total)")

print(f"resumos gravados : {len(bons)}/{len(dados)}")
print(f"sem resumo       : {len(faltam)}" + (f"  ex.: {faltam[:3]}" if faltam else ""))
if problemas:
    print(f"descartados      : {len(problemas)}")
    for p in problemas[:5]:
        print(f"   {p}")

comp = [len(b["curto"]) for b in bons]
comp.sort()
lon = [len(b["longo"]) for b in bons]; lon.sort()
print(f"\ncurto: mediana {comp[len(comp)//2]} car., max {comp[-1]}"
      f"  ({sum(1 for c in comp if c > 95)} acima de 95)")
print(f"longo: mediana {lon[len(lon)//2]} car., max {lon[-1]}")
print("\namostra:")
for b in bons[:3]:
    print(f"  · {b['curto']}")
