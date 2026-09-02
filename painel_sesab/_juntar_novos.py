# -*- coding: utf-8 -*-
"""Funde _resumos/novos.json em _resumos/resumos.json, validando por id.

Existe porque a coleta diaria traz processos novos e regerar 1138 resumos por causa
de 4 seria desperdicio. Fundir sem validar seria pior: id errado poe o resumo de um
processo em cima de outro, e isso nao se percebe olhando a tela.
"""
import json, datetime, re, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
NOVOS = BASE / "_resumos" / "novos.json"
ALVO = BASE / "_resumos" / "resumos.json"

if not NOVOS.exists():
    sys.exit("sem _resumos/novos.json")

COLETA = sorted(
    p for p in (BASE / "_coletas").glob("sei_sesab_*.json") if "anterior" not in p.name)[-1]
dados = json.loads(COLETA.read_text(encoding="utf-8"))
validos = {d["id"] for d in dados}
# data da COLETA que o resumo descreve, nao a do dia em que este script rodou
m = re.fullmatch(r"sei_sesab_(\d{4}-\d{2}-\d{2})", COLETA.stem)
COLETA_EM = m.group(1) if m else datetime.date.fromtimestamp(
    COLETA.stat().st_mtime).isoformat()

atual = json.loads(ALVO.read_text(encoding="utf-8")) if ALVO.exists() else []
indice = {r["id"]: r for r in atual}
hoje = datetime.date.today().isoformat()

add = ignorados = 0
for r in json.loads(NOVOS.read_text(encoding="utf-8")):
    i = r.get("id")
    if i not in validos:
        print(f"  ignorado: id {i} nao existe na coleta"); ignorados += 1; continue
    if not (r.get("curto") or "").strip() or not (r.get("longo") or "").strip():
        print(f"  ignorado: {i} com resumo vazio"); ignorados += 1; continue
    indice[i] = {"id": i, "curto": r["curto"].strip(), "longo": r["longo"].strip(),
                 "coleta_em": COLETA_EM, "gerado_em": hoje}
    add += 1

ALVO.write_text(json.dumps(list(indice.values()), ensure_ascii=False, indent=1), encoding="utf-8")
NOVOS.unlink()
sem = sum(1 for d in dados if d["id"] not in indice)
print(f"fundidos {add} (ignorados {ignorados}) -> {len(indice)} resumos")
print(f"processos sem resumo agora: {sem}/{len(dados)}")
