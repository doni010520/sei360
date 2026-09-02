# -*- coding: utf-8 -*-
"""Monta os lotes de entrada para os resumos de IA.

O resumo sai dos METADADOS que a coleta ja tem (especificacao, assunto, marcador,
acompanhamento, anotacao, trajetoria) — NAO do conteudo dos documentos, que a coleta
nao baixa. Isso limita o que o resumo pode afirmar, e o painel diz isso ao usuario.

    python preparar_resumos.py            # todos os processos
    python preparar_resumos.py --novos    # so os que ainda nao tem resumo
"""
import json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SAIDA = BASE / "_resumos"
POR_LOTE = 60
NOVOS = "--novos" in sys.argv

arqs = sorted((BASE / "_coletas").glob("sei_sesab_*.json"))
arqs = [a for a in arqs if "anterior" not in a.name]
if not arqs:
    sys.exit("nenhuma coleta em _coletas/")
dados = json.loads(arqs[-1].read_text(encoding="utf-8"))

SAIDA.mkdir(exist_ok=True)
for a in SAIDA.glob("lote_*.json"):
    a.unlink()


def enxuto(d):
    """So o que ajuda a dizer O QUE E o processo. Campos de controle (mesas_conta,
    cores, ids internos) sao ruido para o modelo e custam token."""
    ac = d.get("acompanhamento") or []
    mv = d.get("ultimo_movimento") or {}
    return {
        "id": d["id"],
        "protocolo": d.get("protocolo"),
        "tipo": d.get("tipo_processo"),
        "especificacao": d.get("especificacao"),
        "assuntos": (d.get("assuntos") or [])[:2],
        "interessados": (d.get("interessados") or [])[:2],
        "marcador": d.get("marcador"),
        "grupo_acompanhamento": [x.get("grupo") for x in ac if x.get("grupo")][:2],
        "observacao_acompanhamento": next((x.get("observacao") for x in ac if x.get("observacao")), None),
        "anotacao": d.get("anotacao"),
        "unidade_geradora": d.get("gerador_unidade"),
        "autuacao": d.get("autuacao"),
        "mesa": d.get("mesa_coleta"),
        # Cortar em 6 sem dizer o total fez o resumo afirmar "aberto em seis unidades"
        # para processo aberto em 22 ou 50. O total vai junto, e o corte fica explicito.
        "aberto_em": [m.get("unidade") for m in (d.get("mesas") or [])][:6],
        "aberto_em_total": len(d.get("mesas") or []),
        "ultimo_movimento": f"{mv.get('de','')} — {mv.get('un','')} em {mv.get('dh','')}".strip(" —"),
        "documentos": d.get("documentos"),
        "nivel_acesso": d.get("nivel_acesso"),
    }


if NOVOS:
    # Incremental: cada execucao diaria traz processos novos, e regerar os 1138
    # resumos por causa de 4 seria desperdicio. O resumo CURTO (o que o processo e)
    # nao muda; o longo envelhece, mas isso e tratado pelo carimbo de data no painel.
    ja = BASE / "_resumos" / "resumos.json"
    tem = {r["id"] for r in json.loads(ja.read_text(encoding="utf-8"))} if ja.exists() else set()
    antes = len(dados)
    dados = [d for d in dados if d["id"] not in tem]
    print(f"--novos: {antes - len(dados)} ja tem resumo; {len(dados)} a gerar")
    if not dados:
        print("nada a fazer")
        raise SystemExit(0)

lotes = [dados[i:i + POR_LOTE] for i in range(0, len(dados), POR_LOTE)]
for i, lote in enumerate(lotes):
    (SAIDA / f"lote_{i:02d}.json").write_text(
        json.dumps([enxuto(d) for d in lote], ensure_ascii=False, indent=1), encoding="utf-8")

print(f"origem: {arqs[-1].name}  ({len(dados)} processos)")
print(f"lotes : {len(lotes)} de ate {POR_LOTE} -> {SAIDA.name}/lote_NN.json")
