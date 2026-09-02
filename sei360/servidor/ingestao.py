# -*- coding: utf-8 -*-
"""
Ingestao do JSON da coleta -> snapshots por unidade.

REGRA QUE GOVERNA ESTE ARQUIVO
------------------------------
Coleta parcial NAO pode ser publicada com cara de completa. Foi o modo de falha
mais perigoso do sistema inteiro: uma mesa que falha simplesmente nao tem linha
nenhuma, some da uniao, e o painel anuncia "5 mesas" como se fosse a conta toda.

Por isso o snapshot e POR UNIDADE, com data propria. Uma mesa que falhou nao
recebe snapshot novo: o painel continua mostrando o dado ANTERIOR dela, com a
idade dele na tela. Melhor dado velho carimbado que dado ausente disfarcado.

    python ingestao.py                          # coleta mais recente de _coletas/
    python ingestao.py caminho.json --forcar     # promove mesmo com queda suspeita
"""
import json, hashlib, sys
from pathlib import Path

from banco import conectar, agora, registrar
import poco

# Caminhos da ESTAÇÃO, usados só na importação manual de um arquivo do disco.
# Ficam em variável de ambiente porque no container eles não existem: `Path()`
# com barra invertida vira nome relativo esquisito no Linux, que não quebra mas
# também não diz nada a quem for ler o log procurando o motivo.
import os
RAIZ_COLETAS = Path(os.environ.get("SEI360_COLETAS",
                                   r"C:\Claude\sei_sistema\painel_sesab\_coletas"))
RESUMOS = Path(os.environ.get("SEI360_RESUMOS",
                              r"C:\Claude\sei_sistema\painel_sesab\_resumos\resumos.json"))

# Queda de mais de 10% no numero de processos de uma mesa entre coletas nao e
# rotina: ou a mesa esvaziou de verdade (raro) ou a coleta pegou so parte. Na
# duvida o snapshot fica CANDIDATO e alguem confirma.
LIMIAR_QUEDA = 0.90

CAMPOS = [
    ("protocolo", "protocolo"), ("mesa_coleta", "mesa_coleta"),
    ("tipo_processo", "tipo_processo"), ("atribuido_login", "atribuido_login"),
    ("atribuido_nome", "atribuido_nome"), ("marco_unidade", "marco_unidade"),
    ("autuacao", "autuacao"), ("recebimento", "recebimento"),
    ("recebimento_por", "recebimento_por"), ("envio", "envio"), ("mesas_fonte", "mesas_fonte"),
    ("unidade_envio", "unidade_envio"), ("gerador_unidade", "gerador_unidade"),
    ("gerador_usuario", "gerador_usuario"), ("nivel_acesso", "nivel_acesso"),
    ("hipotese_legal", "hipotese_legal"), ("retorno", "retorno"),
    ("marcador", "marcador"), ("marcador_cor", "marcador_cor"), ("origem", "origem"),
]
BOOLS = [("visualizado", 1), ("doc_incluido", 0), ("urgente", 0), ("sobrestado", 0),
         ("sem_historico", 0), ("truncado", 0), ("mesas_divergem", 0),
         # procedencia da LEITURA, nao propriedade do processo
         ("servido_do_poco", 0), ("mov_parcial", 0), ("mesa_indeterminada", 0),
         ("acomp_lido", 0)]
INTS = ["documentos", "movimentos", "emails_enviados", "assinatura_externa",
        "movimentos_exato"]
# A REGUA DE CADA LINHA. `medido_em` e a hora da leitura que produziu ESTE
# detalhe — igual a da coleta quando foi lido agora, mais antiga quando veio do
# poco. Sem ela o painel mede uma data velha com o relogio de hoje.
EXTRAS = ["medido_em", "morno_em", "morno_dono", "doc_incluido_rotulo"]


def _b(v, padrao=0):
    """None vira o padrao declarado. `visualizado` ausente nao e 'nao visualizado':
    a regra 'ainda nao foi visto por ninguem' dispara em visualizado===False, e
    tratar ausencia como False marcaria a carteira inteira como nova."""
    return padrao if v is None else int(bool(v))


def carregar(caminho=None):
    if caminho:
        arq = Path(caminho)
    else:
        cand = sorted(RAIZ_COLETAS.glob("sei_sesab_*.json"))
        cand = [c for c in cand if ".anterior" not in c.name]
        if not cand:
            sys.exit("nenhuma coleta em _coletas/")
        arq = cand[-1]
    return arq, json.loads(arq.read_text(encoding="utf-8"))


def inventario(dados):
    """Mesas da conta e mesas que falharam vem do CARIMBO da coleta, nunca da
    uniao das mesas que trouxeram linhas — a uniao esconde exatamente a mesa que
    falhou, que e a informacao que interessa."""
    inv = next((d.get("mesas_conta") for d in dados if d.get("mesas_conta")), None)
    falhas = next((d.get("mesas_falhas") for d in dados if d.get("mesas_falhas")), []) or []
    if not inv:
        vistas = []
        for d in dados:
            for m in (d.get("mesas_coleta") or [d.get("mesa_coleta")]):
                if m and m not in vistas:
                    vistas.append(m)
        inv = vistas
    return sorted(inv), sorted(falhas)


# Os 1.138 resumos do arquivo legado nao dizem que maquina os escreveu, com que
# nivel de dado, em que versao. O gatilho `resumo_exige_procedencia` recusa NULL —
# e esta certo: texto de maquina numa tela de trabalho sem procedencia e
# exatamente o que ninguem consegue explicar um ano depois. Mas recusar em silencio
# quebrava `python ingestao.py` na PRIMEIRA linha, com IntegrityError.
#
# A resposta honesta nao e inventar um provedor nem apagar os resumos: e REGISTRAR
# que a procedencia nao foi registrada. Fica dito na tela, e quem for auditar le a
# verdade em vez de um nome plausivel.
SEM_PROCEDENCIA = "procedência não registrada (arquivo legado)"


def indexar_resumos():
    if not RESUMOS.exists():
        return {}
    fora = {}
    for r in json.loads(RESUMOS.read_text(encoding="utf-8")):
        if not (r.get("gerado_por") or "").strip():
            r["gerado_por"] = SEM_PROCEDENCIA
        fora[r["id"]] = r
    return fora


def _costurar(cx, linhas, unidade, coletado_em, dono, execucao_id, instancia):
    """(b) costura o que o plano mandou pular e (c) recalcula os cinco por mesa.

    Devolve o funil: quantos precisavam de leitura, quantos foram lidos de fato,
    quantos vieram do poco. Sem esses tres numeros, uma sessao que cai no terceiro
    processo com poco quente e indistinguivel de uma corrida normal.
    """
    pulados = [d for d in linhas if d.get("_pulado") and not d.get("_fresco")]
    blocos = (poco.servir(cx, [d.get("id") for d in pulados], instancia, unidade, dono)
              if pulados else {})
    servidos, orfaos = 0, []

    for d in linhas:
        if d.get("_fresco"):
            # Lida agora: a regua desta linha e a hora da coleta.
            d["medido_em"] = coletado_em
            d["morno_em"] = coletado_em
            d["morno_dono"] = dono
            # so conta como lido se o acompanhamento lido foi o DESTA mesa
            d["acomp_lido"] = 1 if (d.get("acomp_disponivel")
                                    and d.get("_acomp_fresco")) else 0
            continue
        if not d.get("_pulado"):
            continue                       # falha de leitura: ja vira sem_historico
        b = blocos.get(d.get("id"))
        if not b:
            # O plano disse pular e o poco nao tem. Nao se inventa: a linha fica
            # sem historico, dita, e o processo entra na proxima corrida.
            orfaos.append(d.get("id"))
            d["sem_historico"] = 1
            continue
        for k, v in b.items():
            if k in ("acompanhamento", "acomp_grupos", "acomp_lido",
                     "morno_em", "morno_dono"):
                continue
            d[k] = v
        # A LEITURA DE AGORA VENCE. E o caminho 'so_acompanhamento': o bloco vem do
        # poco e o acompanhamento e a unica coisa lida de verdade. Sobrescrever aqui
        # trocava o que a pessoa acabou de ler pela copia que o proprio veredito
        # declarou vencida — e ainda carimbava acomp_lido=1.
        if d.get("_acomp_fresco"):
            d["acomp_lido"] = 1 if d.get("acomp_disponivel") else 0
        else:
            d["acompanhamento"] = b.get("acompanhamento")
            d["acomp_grupos"] = b.get("acomp_grupos")
            # `acomp_lido=0` faz a tela dizer "nao lido nesta coleta". Mostrar vazio
            # sem esta marca seria afirmar que o processo NAO TEM acompanhamento.
            d["acomp_lido"] = b.get("acomp_lido") or 0
        d["servido_do_poco"] = 1
        # A REGUA DA LINHA e a hora da leitura que produziu o bloco, nao a de agora.
        d["medido_em"] = b.get("morno_em")
        d["morno_em"] = b.get("morno_em")
        d["morno_dono"] = b.get("morno_dono")
        d["sem_historico"] = 0
        d["truncado"] = b.get("truncado_na_origem") or 0
        servidos += 1

    if orfaos:
        cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,unidade,texto)
                      VALUES(?,?,?,?,?,?)""",
                   (agora(), "poco_sem_bloco", "media", execucao_id, unidade,
                    f"{len(orfaos)} processo(s) foram pulados na coleta e o poco nao "
                    f"tinha bloco para eles; entram sem historico nesta rodada"))

    # (c) OS CINCO CAMPOS POR MESA. Recalculados para a unidade DESTE snapshot,
    # nunca copiados da mesa que leu o bloco. Sem movimento algum dela na
    # custodia, a linha fica sem os cinco e marcada — "nao sei", nao "igual".
    for d in linhas:
        if d.get("mesa_derivada") == unidade and not d.get("servido_do_poco"):
            continue                       # ja derivada para esta mesa na leitura
        mov = d.get("mov_custodia")
        if d.get("mov_parcial") or not mov:
            if d.get("servido_do_poco"):
                _sem_cinco(d)
            continue
        c = poco.campos_da_mesa(mov, unidade)
        for k in ("recebimento", "recebimento_por", "envio", "unidade_envio",
                  "marco_unidade"):
            d[k] = c[k]
        d["mesa_indeterminada"] = 0 if c["derivada_para"] else 1

    devidos = sum(1 for d in linhas if not d.get("servido_do_poco"))
    lidos = sum(1 for d in linhas if d.get("_fresco"))
    return {"devidos": devidos, "lidos": lidos, "servidos": servidos}


def _sem_cinco(d):
    for k in ("recebimento", "recebimento_por", "envio", "unidade_envio",
              "marco_unidade"):
        d[k] = None
    d["mesa_indeterminada"] = 1


def ingerir(caminho=None, forcar=False, agente_id=None, execucao_id=None,
            coletado_em=None, escopo=None, dono=None, instancia=None):
    """`escopo` recorta as unidades que podem virar snapshot.

    Existe porque a coleta e o escopo são decididos em lugares diferentes: o
    agente coleta todas as mesas da conta (é o que o coletor sabe fazer) e o
    servidor sabe quais delas esta pessoa pode publicar. Sem o recorte, a
    única saída era recusar o lote inteiro — e aí escolher menos mesas
    significava não coletar nada.

    `None` quer dizer sem recorte (ingestão manual pelo operador).
    """
    arq, dados = carregar(caminho)
    if not dados:
        sys.exit("coleta vazia — nada a ingerir")
    # DE QUAL INSTALAÇÃO do SEI é esta coleta. Quem declara é o coletor, no
    # próprio dado; o argumento é para quem ingere à mão. As coletas que já estão
    # em disco não têm o campo e são todas da SESAB — ler isso como 'SEI-SESAB'
    # é ler o que existe, não presumir.
    instancia = (instancia
                 or next((d.get("instancia") for d in dados if d.get("instancia")), None)
                 or "SEI-SESAB")
    # Coleta ANTERIOR a marca `_fresco` (que diz se a linha foi lida de verdade
    # nesta execucao). Nela, toda linha com historico foi lida — nao havia poco
    # de onde pular. Sem esta normalizacao, cada arquivo do disco entraria com
    # "0 lidos de N devidos" e um alerta falso de leitura incompleta por unidade.
    if not any("_fresco" in d for d in dados):
        for d in dados:
            d["_fresco"] = not d.get("sem_historico")
    mesas, falhas = inventario(dados)
    if escopo is not None:
        permitidas = set(escopo)
        recortadas = [m for m in mesas if m not in permitidas]
        mesas = [m for m in mesas if m in permitidas]
        falhas = [m for m in falhas if m in permitidas]
    else:
        recortadas = []
    bruto = arq.read_bytes()
    sha = hashlib.sha256(bruto).hexdigest()
    # Data da COLETA, jamais a de agora. Quando o agente publica, o corpo chega
    # num arquivo temporario criado neste instante: usar o mtime dele carimbaria
    # a coleta das 07:45 de ontem como "coletado agora" — o painel passaria a
    # anunciar frescor que nao tem, que e o defeito que este projeto persegue.
    # Por isso quem publica DECLARA o horario, e a ausencia vira suspeita.
    from datetime import datetime
    from banco import TZ
    sem_carimbo = coletado_em is None
    if sem_carimbo:
        coletado_em = datetime.fromtimestamp(arq.stat().st_mtime, TZ).isoformat(timespec="seconds")

    cx = conectar()
    if execucao_id is None:
        cx.execute("""INSERT INTO execucao(agente_id,janela,estado,gatilho,entregue_em,
                      iniciado_em,terminado_em,exit_code,log_resumo)
                      VALUES(?,?,?,?,?,?,?,?,?)""",
                   (agente_id, coletado_em, "concluida", "importacao_manual",
                    agora(), agora(), agora(), 0, f"import de {arq.name}"))
        execucao_id = cx.execute("SELECT last_insert_rowid()").fetchone()[0]

    resumos = indexar_resumos()
    relatorio = {"arquivo": arq.name, "unidades": [], "falhas": falhas,
                 "execucao_id": execucao_id, "resumos": 0,
                 "resumos_sem_procedencia": 0, "recortadas": recortadas}
    if recortadas:
        # O que ficou de fora fica DITO. Recortar em silêncio seria a mesma classe
        # de erro que recusar tudo: em ambos os casos alguém acha que coletou o
        # que não coletou.
        cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,texto)
                      VALUES(?,?,?,?,?)""",
                   (agora(), "unidade_fora_do_escopo", "media", execucao_id,
                    "a coleta trouxe unidade fora do escopo deste agente e ela "
                    "NÃO foi ingerida: " + ", ".join(sorted(recortadas))))

    for unidade in mesas:
        if unidade in falhas:
            cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,unidade,texto)
                          VALUES(?,?,?,?,?,?)""",
                       (agora(), "mesa_falhou", "alta", execucao_id, unidade,
                        "a mesa nao foi coletada nesta execucao; o painel segue mostrando "
                        "o snapshot anterior desta unidade, com a idade dele"))
            relatorio["unidades"].append({"unidade": unidade, "estado": "falhou"})
            continue

        # A LINHA E DA MESA QUE A MOSTROU. Selecionar por membresia
        # (`unidade in mesas_coleta`) fazia a linha derivada para a ASTEC entrar
        # no snapshot da COMASUP com o marcador e o marco da ASTEC — plausivel,
        # silencioso, e exatamente o defeito que o poco multiplicaria por dez.
        linhas = [d for d in dados if d.get("mesa_coleta") == unidade]
        # Coleta ANTERIOR ao conserto do coletor: uma linha so, carimbada para a
        # primeira mesa. Fica dito, e a unidade fica com o snapshot anterior dela
        # em vez de receber o dado de outra.
        # `mesas_coleta` agora lista TODAS as mesas em que o processo aparece, entao
        # a linha da mesa B satisfaz "unidade in mesas_coleta" quando se ingere a A.
        # Sem excluir quem ja tem linha propria aqui, o alerta de severidade alta
        # disparava em toda coleta nova — e alarme falso repetido e como um detector
        # morre. So resta o caso legado de verdade: id que nao tem linha nenhuma
        # carimbada para esta unidade.
        proprios = {d.get("id") for d in linhas}
        herdadas = [d for d in dados
                    if d.get("mesa_coleta") != unidade
                    and unidade in (d.get("mesas_coleta") or [])
                    and d.get("id") not in proprios]
        if herdadas:
            cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,unidade,texto)
                          VALUES(?,?,?,?,?,?)""",
                       (agora(), "linha_de_outra_mesa", "alta", execucao_id, unidade,
                        f"{len(herdadas)} linha(s) desta coleta foram derivadas para outra "
                        f"mesa e NAO foram ingeridas aqui: os campos de lista (marcador, "
                        f"anotacao, atribuido) e os de custodia sao da mesa que os leu. "
                        f"Coleta anterior ao conserto do coletor."))
        unicos = len(linhas)

        # A comparação de queda é contra a MINHA coleta anterior desta unidade,
        # não contra a de outra pessoa. Comparar com a de outro dono produziria
        # "queda de 625 para 5" só porque duas pessoas alcançam quantidades
        # diferentes da mesma unidade — o que é normal e não é queda nenhuma.
        anterior = cx.execute(
            "SELECT unicos FROM snapshot WHERE unidade=? AND estado='corrente' "
            "AND dono_usuario_id IS ? ORDER BY coletado_em DESC LIMIT 1",
            (unidade, dono)).fetchone()
        suspeito, motivo, estado = 0, None, "corrente"
        if sem_carimbo and agente_id is not None:
            # Publicacao de agente sem horario declarado: o dado entra, mas
            # marcado. Silenciar isso seria transformar "não sei quando isto foi
            # coletado" em "coletado agora".
            suspeito = 1
            motivo = "publicado sem carimbo de coleta do agente"
        if anterior and anterior["unicos"] and unicos < anterior["unicos"] * LIMIAR_QUEDA:
            suspeito = 1
            motivo = f"queda de {anterior['unicos']} para {unicos} processos"
            estado = "corrente" if forcar else "candidato"
            cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,unidade,texto)
                          VALUES(?,?,?,?,?,?)""",
                       (agora(), "queda_suspeita", "alta", execucao_id, unidade,
                        motivo + ("" if forcar else " — snapshot retido como candidato")))

        # (a) PUBLICAR antes de costurar. A ordem importa: publicar depois faria
        # o bloco recem-servido ser republicado como se tivesse sido lido agora,
        # que e a corrente de re-carimbo que o teto de 72 h existe para impedir.
        rel_poco = poco.publicar(cx, linhas, dono, coletado_em, instancia,
                                 mesas_falhas=falhas)
        # (b) e (c): costurar o que o plano mandou pular e recalcular os cinco
        # campos por mesa. Devolve o funil da corrida.
        funil = _costurar(cx, linhas, unidade, coletado_em, dono, execucao_id, instancia)
        funil["publicados"] = rel_poco["publicados"]

        sem_hist = sum(1 for d in linhas if d.get("sem_historico"))
        trunc = sum(1 for d in linhas if d.get("truncado"))
        # `cur.lastrowid` do PROPRIO insert, nunca um `last_insert_rowid()` depois.
        # Com o SELECT separado, qualquer INSERT que caia no meio — foi o alerta de
        # leitura incompleta — passa a ser o id lido, e as linhas do processo vao
        # para o snapshot errado (ou a ingestao aborta em FOREIGN KEY).
        cur = cx.execute("""INSERT INTO snapshot(execucao_id,unidade,coletado_em,coletados,unicos,
                      sem_historico,truncado_restante,estado,suspeito,motivo,arquivo,sha256,bytes,
                      dono_usuario_id,devidos,lidos_de_fato,servidos_do_poco,
                      canario_divergencias,instancia)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   # coletados fica NULL de proposito: o numero que a mesa DECLARA
                   # so existe no envelope da coleta (Fatia 1). Preencher com a
                   # contagem de linhas faria o gate comparar o dado consigo mesmo.
                   (execucao_id, unidade, coletado_em, None, unicos, sem_hist, trunc,
                    estado, suspeito, motivo, arq.name, sha, len(bruto), dono,
                    funil["devidos"], funil["lidos"], funil["servidos"],
                    rel_poco.get("canario_divergencias"), instancia))
        snap = cur.lastrowid
        # O CANARIO FECHA O LACO. Ele le processos que o poco teria respondido e
        # compara. A DIRECAO importa e esta fixada aqui: divergencia ampla NAO
        # invalida o poco — numa segunda-feira de layout novo a leitura natural
        # ("o cache esta velho") e a inversa da verdadeira, e invalidar destruiria
        # o unico dado bom. Divergencia esparsa e cache velho pontual, esperado.
        if rel_poco.get("canario_lidos"):
            _lidos, _div = rel_poco["canario_lidos"], rel_poco["canario_divergencias"]
            if _div > _lidos:          # mais de um campo divergente por processo
                cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,unidade,texto)
                              VALUES(?,?,?,?,?,?)""",
                           (agora(), "canario_divergente", "alta", execucao_id, unidade,
                            f"o canario releu {_lidos} processo(s) que o poco teria "
                            f"respondido e achou {_div} campo(s) divergentes. Divergencia "
                            f"AMPLA acusa a leitura de HOJE, nao o poco: confira o parser "
                            f"antes de invalidar bloco nenhum."))

        # Sessao que cai no terceiro processo com poco quente produziria, sem
        # este alerta, um snapshot completo e sem alarme nenhum: 92,6% de
        # reaproveitamento, indistinguivel do regime normal.
        if funil["lidos"] < funil["devidos"]:
            cx.execute("""INSERT INTO alerta(ts,tipo,severidade,execucao_id,unidade,texto)
                          VALUES(?,?,?,?,?,?)""",
                       (agora(), "leitura_incompleta", "alta", execucao_id, unidade,
                        f"{funil['devidos']} processos precisavam de leitura e "
                        f"{funil['lidos']} foram lidos nesta corrida"))

        if estado == "corrente":
            # O NOVO só vira corrente se for mais RECENTE que o que está lá. Sem
            # esta comparação, reingerir um arquivo antigo — para reprocessar,
            # para conferir, por engano — fazia o dado velho tomar o lugar do
            # novo em silêncio. Foi o que aconteceu aqui: seis snapshots
            # `expirado` ficaram com data POSTERIOR à do corrente.
            # POR DONO. Sem o recorte, a coleta de uma pessoa expirava a de
            # outra na mesma unidade — e quem tivesse coletado de manhã perderia
            # a carteira dele porque um colega coletou à tarde.
            atual = cx.execute("""SELECT id, coletado_em FROM snapshot
                                  WHERE unidade=? AND estado='corrente' AND id<>?
                                    AND dono_usuario_id IS ?
                                  ORDER BY coletado_em DESC LIMIT 1""",
                               (unidade, snap, dono)).fetchone()
            if atual and atual["coletado_em"] > coletado_em:
                cx.execute("UPDATE snapshot SET estado='rejeitado', motivo=? WHERE id=?",
                           (f"coleta de {coletado_em[:16]} é anterior à corrente "
                            f"({atual['coletado_em'][:16]}); mantido o mais novo", snap))
                relatorio["unidades"].append(
                    {"unidade": unidade, "processos": unicos, "estado": "rejeitado",
                     "motivo": "mais antiga que a corrente"})
                continue
            cx.execute("UPDATE snapshot SET estado='expirado' WHERE unidade=? AND "
                       "estado='corrente' AND id<>? AND dono_usuario_id IS ?",
                       (unidade, snap, dono))

        for d in linhas:
            vals = [d.get(o) for _, o in CAMPOS]
            cx.execute(f"""INSERT INTO processo(snapshot_id,id_sei,{','.join(c for c,_ in CAMPOS)},
                           {','.join(c for c,_ in BOOLS)},{','.join(INTS)},{','.join(EXTRAS)},
                           ultimo_movimento,assuntos,anexados,mesas_coleta)
                           VALUES({','.join('?'*(2+len(CAMPOS)+len(BOOLS)+len(INTS)+len(EXTRAS)+4))})""",
                       [snap, d.get("id")] + vals
                       + [_b(d.get(c), p) for c, p in BOOLS]
                       + [d.get(c) for c in INTS]
                       + [d.get(c) for c in EXTRAS]
                       + [json.dumps(d.get("ultimo_movimento"), ensure_ascii=False) if d.get("ultimo_movimento") else None,
                          json.dumps(d.get("assuntos") or [], ensure_ascii=False),
                          json.dumps(d.get("anexados") or [], ensure_ascii=False),
                          json.dumps(d.get("mesas_coleta") or [x for x in [d.get("mesa_coleta")] if x],
                                     ensure_ascii=False)])
            for m in (d.get("mesas") or []):
                cx.execute("INSERT INTO processo_mesa(snapshot_id,id_sei,mesa,atribuido) VALUES(?,?,?,?)",
                           (snap, d.get("id"), m.get("unidade"), m.get("atribuido")))
            cx.execute("""INSERT INTO processo_texto(snapshot_id,id_sei,especificacao,anotacao,
                          anotacao_autor,anotacao_data,interessados,acompanhamento)
                          VALUES(?,?,?,?,?,?,?,?)""",
                       (snap, d.get("id"), d.get("especificacao"), d.get("anotacao"),
                        d.get("anotacao_autor"), d.get("anotacao_data"),
                        json.dumps(d.get("interessados") or [], ensure_ascii=False),
                        json.dumps(d.get("acompanhamento") or [], ensure_ascii=False)))
            r = resumos.get(d.get("id"))
            if r:
                cx.execute("""INSERT OR REPLACE INTO resumo(id_sei,instancia,curto,longo,
                              descrito_em,gerado_em,gerado_por) VALUES(?,?,?,?,?,?,?)""",
                           (d.get("id"), instancia, r.get("curto"), r.get("longo"),
                            r.get("coleta_em"), r.get("gerado_em"), r.get("gerado_por")))
                relatorio["resumos"] += 1
                if r.get("gerado_por") == SEM_PROCEDENCIA:
                    relatorio["resumos_sem_procedencia"] += 1

        relatorio["unidades"].append({"unidade": unidade, "processos": unicos,
                                      "estado": estado, "motivo": motivo})

    registrar(cx, None, "ingestao", alvo=arq.name)
    cx.commit()
    cx.close()
    return relatorio


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rel = ingerir(args[0] if args else None, forcar="--forcar" in sys.argv)
    print(f"arquivo : {rel['arquivo']}  (execucao {rel['execucao_id']})")
    for u in rel["unidades"]:
        if u["estado"] == "falhou":
            print(f"  FALHOU  {u['unidade']} — snapshot anterior mantido")
        else:
            marca = "  " if u["estado"] == "corrente" else "! "
            print(f"  {marca}{u['unidade']}: {u['processos']} processos [{u['estado']}]"
                  + (f" — {u['motivo']}" if u["motivo"] else ""))
    print(f"resumos costurados: {rel['resumos']}"
          + (f" ({rel['resumos_sem_procedencia']} sem procedência registrada)"
             if rel["resumos_sem_procedencia"] else ""))
