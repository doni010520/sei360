# -*- coding: utf-8 -*-
"""
Gera o painel HTML e a planilha a partir do JSON da coleta.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
As duas primeiras versoes do painel tiveram os dados colados a mao dentro do HTML.
Isso fez o painel envelhecer em silencio: ele seguia mostrando a carteira de uma
mesa so, coletada dias antes, com cara de atual. Aqui a regeneracao e um comando.

O HTML e TEMPLATE e DADO no mesmo arquivo: trocamos apenas as duas linhas que
declaram os dados (`const DADOS` e `const MESAS_CONTA`), preservando byte a byte
todo o resto — layout, regras e estilos.

    python gerar_painel.py                  # usa a coleta mais recente
    python gerar_painel.py _coletas/x.json  # usa um arquivo especifico
"""
import json, re, sys, datetime
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

BASE   = Path(__file__).resolve().parent
HTML   = BASE / "painel_sesab.html"
XLSX   = BASE / "processos_sesab.xlsx"
COLETAS = BASE / "_coletas"


def carregar():
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        arq = Path(sys.argv[1])
        if not arq.is_absolute():
            arq = BASE / arq
    else:
        cand = sorted(COLETAS.glob("sei_sesab_*.json"))
        if not cand:
            sys.exit("nenhuma coleta em _coletas/")
        arq = cand[-1]
    return arq, json.loads(arq.read_text(encoding="utf-8"))


def juntar_resumos(dados, arq_atual):
    """Costura os resumos de IA (_resumos/resumos.json) ao dado, por id.

    Ficam FORA do JSON da coleta de proposito: a coleta e reprodutivel e verificavel
    contra o SEI; o resumo e derivado e opcional. Guardar junto faria uma re-coleta
    apagar resumos que custaram uma rodada inteira de geracao.
    """
    arq = BASE / "_resumos" / "resumos.json"
    if not arq.exists():
        print("sem _resumos/resumos.json — painel sai sem resumo de IA")
        return 0
    idx = {r["id"]: r for r in json.loads(arq.read_text(encoding="utf-8"))}
    n = 0
    for d in dados:
        r = idx.get(d["id"])
        if r:
            d["resumo_curto"], d["resumo_longo"] = r.get("curto"), r.get("longo")
            # a data que interessa ao leitor e a da COLETA descrita, nao a da execucao
            # do script de extracao (fallback so para resumos.json antigo)
            d["resumo_em"] = r.get("coleta_em") or r.get("gerado_em")
            n += 1
    faltam = len(dados) - n
    print(f"resumos de IA: {n}/{len(dados)}" + (f"  ({faltam} sem resumo)" if faltam else ""))
    # Resumo que descreve uma coleta ANTERIOR afirma um estado que ja mudou. O painel
    # carimba a data, mas quem opera precisa ver isso no log tambem.
    coletas = {r.get("coleta_em") for r in idx.values() if r.get("coleta_em")}
    atual = re.fullmatch(r"sei_sesab_(\d{4}-\d{2}-\d{2})", arq_atual.stem)
    if atual and coletas and any(c < atual.group(1) for c in coletas):
        velhas = sorted(c for c in coletas if c < atual.group(1))
        print(f"  ATENCAO: resumos descrevem a coleta de {', '.join(velhas)}; "
              f"a coleta atual e {atual.group(1)} — o estado descrito pode ter mudado")
    if faltam:
        # Avisar alto: o painel nao gera resumo sozinho (depende de uma rodada de
        # agentes), entao sem este aviso os processos novos ficariam sem resumo
        # indefinidamente e ninguem notaria.
        print(f"  -> para cobri-los: python preparar_resumos.py --novos  e nova rodada de resumos")
    return n


def mesas_da_conta(dados):
    """Mesas da conta e mesas que falharam.

    Prefere o INVENTARIO carimbado pela coleta (`mesas_conta`). A uniao das mesas
    que trouxeram linhas so serve de fallback para coletas antigas: se uma mesa
    falha, ela nao tem linha nenhuma e simplesmente DESAPARECE da uniao — o painel
    entao anuncia "5 mesas" como se fosse a conta inteira, sem nada indicando a
    perda. E o modo de falha mais perigoso deste sistema: parcial com cara de completo.
    """
    inv = next((d.get("mesas_conta") for d in dados if d.get("mesas_conta")), None)
    falhas = next((d.get("mesas_falhas") for d in dados if d.get("mesas_falhas")), []) or []
    if inv:
        return sorted(inv), sorted(falhas)
    vistas = []
    for d in dados:
        for m in (d.get("mesas_coleta") or [d.get("mesa_coleta")]):
            if m and m not in vistas:
                vistas.append(m)
    return sorted(vistas), []


def gerar_html(dados, mesas, falhas, arq_origem):
    # Hora da COLETA (mtime do JSON, escrito no fim da coleta), nao a hora de gerar
    # o HTML. Regenerar o painel sem coletar rejuvenescia o dado na tela.
    quando = datetime.datetime.fromtimestamp(
        arq_origem.stat().st_mtime).strftime("%d/%m/%Y às %H:%M")
    linhas = HTML.read_text(encoding="utf-8").split("\n")
    achou = {"dados": False, "mesas": False, "data": False, "falhas": False}
    for i, ln in enumerate(linhas):
        if ln.startswith("const DADOS = "):
            linhas[i] = "const DADOS = " + json.dumps(dados, ensure_ascii=False) + ";"
            achou["dados"] = True
        elif ln.startswith("const MESAS_CONTA = "):
            linhas[i] = "const MESAS_CONTA = " + json.dumps(mesas, ensure_ascii=False) + ";"
            achou["mesas"] = True
        elif ln.startswith("const MESAS_FALHAS = "):
            linhas[i] = "const MESAS_FALHAS = " + json.dumps(falhas, ensure_ascii=False) + ";"
            achou["falhas"] = True
        elif ln.startswith("const COLETA_EM = "):
            linhas[i] = "const COLETA_EM = " + json.dumps(quando, ensure_ascii=False) + ";"
            achou["data"] = True
    faltando = [k for k, v in achou.items() if not v]
    if faltando:
        # Falhar alto: gravar sem substituir produziria um painel com dados velhos
        # e aparencia de recem-gerado — exatamente o problema que este script resolve.
        sys.exit(f"ERRO: nao achei a(s) linha(s) de {', '.join(faltando)} no HTML")
    HTML.write_text("\n".join(linhas), encoding="utf-8")


COLUNAS = [
    ("protocolo",        "Processo",            26),
    ("resumo_curto",     "Resumo (IA)",         52),
    ("tipo_processo",    "Tipo",                30),
    ("especificacao",    "Especificacao",       46),
    ("resumo_longo",     "Resumo detalhado (IA)", 80),
    ("origem",           "Origem",               11),
    ("mesa_coleta",      "Mesa (1a vista)",      30),
    ("_mesas_coleta",    "Mesas da conta",       34),
    ("_mesas",           "Aberto em",            40),
    ("gerador_unidade",  "Unidade geradora",     28),
    ("gerador_usuario",  "Usuario gerador",      24),
    ("autuacao",         "Autuacao",             12),
    ("marco_unidade",    "Nesta unidade desde",  19),
    ("_dias",            "Dias na unidade",      15),
    ("atribuido_login",  "Atribuido a",          18),
    ("marcador",         "Marcador",             22),
    ("marcador_cor",     "Cor do marcador",      15),
    ("_acomp_grupos",    "Grupo (acompanhamento)", 30),
    ("_acomp_obs",       "Observacao (acompanhamento)", 52),
    ("_assuntos",        "Assuntos",             40),
    ("_interessados",    "Interessados",         34),
    ("anotacao",         "Anotacao",             40),
    ("anotacao_autor",   "Anotado por",          26),
    ("anotacao_data",    "Anotado em",           17),
    ("recebimento",      "Recebido em",          17),
    ("envio",            "Enviado em",           17),
    # DESTINO da remessa: na linha do SEI a coluna Unidade e quem recebeu, nao quem enviou
    ("unidade_envio",    "Enviado para",         28),
    ("sobrestado",       "Sobrestado",           12),
    ("nivel_acesso",     "Nivel de acesso",      14),
    ("hipotese_legal",   "Hipotese legal",       34),
    ("documentos",       "Documentos",           11),
    ("emails_enviados",  "E-mails enviados",     14),
    ("visualizado",      "Visualizado",          11),
    ("movimentos",       "Movimentos",           11),
    ("truncado",         "Historico truncado",   18),
    ("_mov_dh",          "Ultimo movimento",     17),
    ("_mov_un",          "Ultimo mov. unidade",  26),
    ("_mov_de",          "Ultimo mov. descricao",42),
    ("mesas_fonte",      "Fonte das mesas",      14),
    ("mesas_divergem",   "Mesas divergem",       14),
    ("sem_historico",    "Sem historico",        14),
    ("id",               "ID",                   12),
]

# Colunas que carregam data/hora: precisam de formato, senao o Excel mostra o serial.
COLUNAS_DATA = {"autuacao", "marco_unidade", "anotacao_data",
                "recebimento", "envio", "_mov_dh"}


def _data(s):
    """'DD/MM/AAAA HH:MM' -> datetime. Devolve o texto original se nao casar —
    perder o valor por causa de um formato inesperado seria pior que exibi-lo."""
    if not isinstance(s, str):
        return s
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return s


def _regua_de(d):
    """A data contra a qual os dias DESTA linha sao contados.

    `medido_em` e a hora da leitura que produziu o DETALHE dela — que pode ser
    anterior a coleta, quando o servidor reaproveitou o bloco de outra pessoa.
    Sem data propria, cai no relogio: e o comportamento antigo, e continua sendo o
    unico disponivel para coleta anterior ao poco.
    """
    m = d.get("medido_em")
    if isinstance(m, str) and len(m) >= 10:
        try:
            return datetime.date.fromisoformat(m[:10])
        except ValueError:
            pass
    return datetime.date.today()


def achatar(d):
    o = dict(d)
    o["_mesas_coleta"] = " · ".join(d.get("mesas_coleta") or
                                    [x for x in [d.get("mesa_coleta")] if x])
    o["_mesas"] = " · ".join(
        m.get("unidade", "") + (f" ({m['atribuido']})" if m.get("atribuido") else "")
        for m in (d.get("mesas") or []))
    marco = d.get("marco_unidade")
    o["_dias"] = None
    if marco:
        try:
            dt = datetime.datetime.strptime(marco[:10], "%d/%m/%Y").date()
            # A REGUA E A DA LINHA, nao o relogio de quem roda o gerador. Este
            # arquivo ficou de fora quando o painel do servidor passou a medir por
            # linha, e agora recebe JSON com linhas `_pulado` cujo detalhe vem do
            # poco (ou nao vem): medir a data velha contra hoje imprime "dias na
            # unidade" inflado, que e a regra dura que este projeto persegue.
            o["_dias"] = (_regua_de(o) - dt).days
        except ValueError:
            pass
    # ultimo_movimento e um objeto {dh, un, de}. Em planilha vira TRES colunas:
    # concatenar num texto so impediria filtrar por unidade ou ordenar por data.
    # Acompanhamento especial: grupo e observacao em colunas proprias. Varios
    # acompanhamentos no mesmo processo viram linhas dentro da celula.
    ac = d.get("acompanhamento") or []
    o["_acomp_grupos"] = "\n".join(x.get("grupo", "") for x in ac if x.get("grupo"))
    o["_acomp_obs"] = "\n".join(x.get("observacao", "") for x in ac if x.get("observacao"))
    o["_assuntos"] = "\n".join(d.get("assuntos") or [])
    o["_interessados"] = "\n".join(d.get("interessados") or [])
    mv = d.get("ultimo_movimento") or {}
    o["_mov_dh"], o["_mov_un"], o["_mov_de"] = mv.get("dh"), mv.get("un"), mv.get("de")
    # Datas viram datetime de verdade: como texto "13/08/2026" ordena depois de
    # "02/01/2027", e a coluna Autuacao ordenada dava a ordem errada em silencio.
    for campo in ("autuacao", "recebimento", "envio", "marco_unidade",
                  "anotacao_data", "_mov_dh"):
        o[campo] = _data(o.get(campo))
    o["visualizado"] = "sim" if d.get("visualizado") else "nao"
    o["mesas_divergem"] = "sim" if d.get("mesas_divergem") else "nao"
    o["sem_historico"] = "SIM" if d.get("sem_historico") else ""
    o["truncado"] = "SIM" if d.get("truncado") else ""
    o["sobrestado"] = "SIM" if d.get("sobrestado") else ""
    return o


def gerar_xlsx(dados, mesas, falhas, arq_origem):
    wb = Workbook()
    ws = wb.active
    ws.title = "Processos"

    cab = Font(bold=True, color="FFFFFF")
    fundo = PatternFill("solid", fgColor="0F5257")
    for c, (_, rotulo, larg) in enumerate(COLUNAS, 1):
        cel = ws.cell(1, c, rotulo)
        cel.font, cel.fill = cab, fundo
        cel.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(c)].width = larg
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUNAS))}{len(dados) + 1}"

    # Rede de seguranca: campo novo com objeto/lista derrubava o script DEPOIS dos
    # ~6 min de coleta (foi o que 'ultimo_movimento' fez). Serializa e avisa, em vez
    # de estourar — mas AVISA, para a coluna nao virar JSON cru sem ninguem notar.
    avisos = set()
    for r, d in enumerate(map(achatar, dados), 2):
        for c, (campo, _, _) in enumerate(COLUNAS, 1):
            v = d.get(campo)
            if isinstance(v, (dict, list)):
                avisos.add(campo)
                v = json.dumps(v, ensure_ascii=False)
            cel = ws.cell(r, c, "" if v is None else v)
            if campo in COLUNAS_DATA and isinstance(v, datetime.datetime):
                cel.number_format = "DD/MM/YYYY HH:MM"
    for campo in sorted(avisos):
        print(f"AVISO: '{campo}' nao e escalar; foi serializado como JSON na planilha")

    resumo = wb.create_sheet("Resumo")
    resumo["A1"], resumo["A1"].font = "Coleta", Font(bold=True)
    por_mesa = {}
    for d in dados:
        for m in (d.get("mesas_coleta") or [d.get("mesa_coleta")]):
            if m:
                por_mesa[m] = por_mesa.get(m, 0) + 1
    coletado_em = datetime.datetime.fromtimestamp(arq_origem.stat().st_mtime)
    linhas = [("Arquivo de origem", arq_origem.name),
              ("Coletado em", coletado_em.strftime("%d/%m/%Y %H:%M")),
              ("Planilha gerada em", datetime.datetime.now().strftime("%d/%m/%Y %H:%M")),
              ("Processos unicos", len(dados)),
              ("Mesas da conta", len(mesas))]
    if falhas:
        linhas.append(("MESAS QUE FALHARAM", ", ".join(falhas)))
        linhas.append(("ATENCAO", "coleta INCOMPLETA — os numeros abaixo nao cobrem a conta"))
    linhas.append(("", ""))
    linhas += [(m + ("  [FALHOU]" if m in falhas else ""), por_mesa.get(m, 0)) for m in mesas]
    for i, (k, v) in enumerate(linhas, 2):
        resumo.cell(i, 1, k).font = Font(bold=(v == ""))
        resumo.cell(i, 2, v)
    resumo.column_dimensions["A"].width = 38
    resumo.column_dimensions["B"].width = 26
    wb.save(XLSX)


arq, dados = carregar()
juntar_resumos(dados, arq)
mesas, falhas = mesas_da_conta(dados)
gerar_html(dados, mesas, falhas, arq)
gerar_xlsx(dados, mesas, falhas, arq)
print(f"origem : {arq.name}  ({len(dados)} processos unicos)")
print(f"mesas  : {len(mesas)} -> {', '.join(mesas)}")
if falhas:
    print(f"ATENCAO: coleta INCOMPLETA — {len(falhas)} mesa(s) falhou: {', '.join(falhas)}")
print(f"painel : {HTML.name}  ({HTML.stat().st_size/1024:.0f} KB)")
print(f"planilha: {XLSX.name}  ({XLSX.stat().st_size/1024:.0f} KB)")
