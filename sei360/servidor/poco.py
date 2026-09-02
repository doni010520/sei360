# -*- coding: utf-8 -*-
"""
O POCO: o que e do PROCESSO, lido uma vez, valendo para todo mundo.

POR QUE ISTO EXISTE
-------------------
Cada pessoa entra no SEI com o login dela e traz a carteira dela. Duas pessoas
lotadas na CESS buscam os MESMOS 598 processos, cada uma a 5 requisicoes por
processo. Com dez pessoas na mesa, 90% do trabalho e repetido — ~156 mil
requisicoes por dia contra a PRODEB para produzir 1.165 processos-dia.

A LINHA QUE NAO SE CRUZA
------------------------
Reaproveitar o que e do PROCESSO e barato e seguro. Reaproveitar o que e da
VISAO de quem olha faz a tela de uma pessoa mostrar o estado de outra — com um
valor plausivel, em silencio, que ninguem notaria. Por isso:

  * a LISTA da mesa e SEMPRE relida por pessoa (marcador, anotacao, atribuido,
    visualizado, retorno, doc_incluido). Custa ~12 requisicoes por mesa: e de
    graca, e nao ha um grama de economia para pagar com esse risco;

  * o BLOCO CARO e compartilhado por id_sei — e devolve quase so campo do
    processo;

  * os CINCO campos que dependem da unidade (recebimento, recebimento_por,
    envio, unidade_envio, marco_unidade) sao RECALCULADOS do `mov_custodia`
    para a unidade de quem le. Nunca copiados. Sem o mov_custodia, "recalcular"
    viraria copiar, e o defeito temido aconteceria entre mesas em vez de entre
    pessoas;

  * o ACOMPANHAMENTO nao atravessa pessoa. E o unico campo caro sem detector
    gratuito, e nao esta provado que a tela do SEI nao recorta por usuario.

A INSTANCIA E OBRIGATORIA, E NAO TEM PADRAO
-------------------------------------------
`id_sei` e o id_procedimento do SEI: uma sequencia autoincremento POR INSTALACAO.
FESF e SESAB sao duas instalacoes, e as duas sequencias colidem por construcao.
A instancia entra na CHAVE (para o bloco de um orgao nao sobrescrever o do outro)
E em toda CONSULTA (para uma leitura sem ela nao trazer os dois e ficar com o
ultimo). Sem valor padrao de proposito: um 'SEI-SESAB' implicito seria o caminho
pelo qual a carteira de um orgao entra na do outro no dia em que alguem esquecer
o argumento — e o sintoma seria um bloco plausivel.

DOIS RELOGIOS
-------------
Cada entrada carrega `morno_em` (a hora que a estacao declarou) e `recebido_em`
(o relogio do servidor). A validade exige as DUAS dentro do prazo: relogio torto
na estacao nao estica nem encurta o cache.

O CARIMBO NAO REJUVENESCE
-------------------------
`morno_em` so avanca quando alguem LEU de verdade (linha com `_fresco`). Linha
servida pelo poco nunca toca a data do poco. Sem isso a corrente se realimenta e
as 17h50 alguem recebe dado de 10h20 marcado como fresco.
"""
import hashlib
import json
from datetime import timedelta

from banco import agora, TZ
from janelas import com_fuso            # datetime SEMPRE com fuso; ver o porque la

# Muda quando o COLETOR muda o que um campo QUER DIZER. Bloco de outra versao
# nunca e servido — e nada precisa ser apagado para isso valer.
PARSER_VERSAO = "2026-08-20"

# Serve entre pessoas sem releitura nenhuma. Nao e tolerancia nova: e a cadencia
# que o proprio projeto recomenda (2x por dia). Quem le as 09:00 um bloco de
# 07:31 recebe dado no maximo tao velho quanto o da propria coleta anterior.
MORNO_H = 12
# Teto ABSOLUTO. Sai da taxa medida de ~9% por dia util: 1 - 0,91^3 = 25% de
# chance de o processo ter se mexido sem ninguem ler. Acima disso a ordem da
# triagem e a regra "parado +90d" erram de forma indefensavel.
TETO_H = 72
# Acompanhamento, assuntos e interessados: mudaram 1,1%, 0,1% e 0,0% em 5 dias.
ACOMP_D = 7

# Fracao do poco relida por corrida, para que o teto de 72 h seja garantido por
# ARITMETICA e nao por regra de excecao.
FAXINA = 1 / 3
# Lido assim mesmo e comparado com o que o poco teria servido.
CANARIO = 0.02
# Uma leitura entregue nao pode ser entregue a outro agente ao mesmo tempo.
RESERVA_MIN = 20

# Nivel de acesso que o poco aceita. Sigiloso e liberado por credencial NOMINAL:
# seria a presenca da LINHA, nao um campo dela, a depender da pessoa. A guarda
# existe ANTES do primeiro caso, nao depois.
NIVEIS_OK = ("Público", "Publico", "Restrito")

# Campos da LISTA que denunciam que o processo se mexeu. `visualizado` fica de
# fora de proposito: e o campo mais volatil da base (6 false->true e 7
# true->false num dia) e nao diz nada sobre o processo — dentro do hash, forcaria
# releitura constante pelo motivo errado.
CAMPOS_GUARDA = ("atribuido_login", "marcador", "marcador_cor",
                 "anotacao_data", "retorno", "doc_incluido")


def hash_guarda(linha: dict) -> str:
    """Assinatura do que a lista da mesa mostra. Nunca e servida: so responde
    'mudou?'. Ela ve o BARULHO e e cega ao SILENCIO — um processo sem marcador,
    sem anotacao e sem troca de atribuicao pode se mexer sem mudar um bit aqui.
    E por isso que a faxina prioriza justamente esses."""
    cru = "|".join("" if linha.get(c) is None else str(linha.get(c))
                   for c in CAMPOS_GUARDA)
    return hashlib.sha256(cru.encode("utf-8")).hexdigest()[:32]


def guarda_cega(linha: dict) -> bool:
    """A guarda nao alcanca esta linha? Sem marcador, sem anotacao, sem retorno,
    sem atribuicao, ela nao muda quando o processo anda. Os dois piores casos
    medidos de inflacao de "dias na unidade" estavam exatamente aqui."""
    return not any(linha.get(c) for c in
                   ("marcador", "anotacao_data", "retorno", "atribuido_login"))


def _sorteio(id_sei: str, dia: str, sal: str) -> float:
    """Fatia estavel em [0,1). Deterministico de proposito: a mesma corrida
    escolhe os mesmos processos, entao o teste consegue prever o plano e o
    rodizio nao concentra sempre nos mesmos ids."""
    h = hashlib.sha256(f"{sal}|{dia}|{id_sei}".encode()).digest()
    return int.from_bytes(h[:4], "big") / 2**32


def _horas(desde_iso, ate_dt):
    if not desde_iso:
        return None
    return (ate_dt - com_fuso(desde_iso)).total_seconds() / 3600


def idade_h(linha, ate_dt):
    """Idade do bloco pela PIOR das duas datas. `morno_em` veio da estacao,
    `recebido_em` do servidor; exigir as duas dentro do prazo e o que impede um
    relogio torto de esticar a validade."""
    a = _horas(linha["morno_em"], ate_dt)
    b = _horas(linha["recebido_em"], ate_dt)
    vivos = [x for x in (a, b) if x is not None]
    return max(vivos) if vivos else None


# --------------------------------------------------------------- publicacao
def publicavel(d: dict):
    """Esta linha pode virar bloco compartilhado? Devolve (bool, motivo).

    A trava mais importante do arquivo. Numa segunda-feira de layout novo, dez
    coletas quebradas sao dez alarmes; sem esta funcao viram UM alarme e nove
    snapshots com cara de limpos.
    """
    if not d.get("_fresco"):
        return False, "nao foi lida de verdade nesta execucao"
    if d.get("sem_historico"):
        return False, "sem historico"
    if d.get("truncado"):
        return False, "historico truncado nao consertado"
    if d.get("mov_parcial"):
        return False, "historico com paginas nao lidas"
    if not d.get("alterar_disponivel"):
        # A tela Consultar/Alterar nao abriu para quem leu. `assuntos` e
        # `interessados` sairiam [] por ausencia da TELA, nao por ausencia de
        # assunto — e servir esse [] a um colega mostraria como "nao tem" o que o
        # SEI so nao abriu para o leitor. O coletor ja distingue os dois casos;
        # faltava alguem consumir a marca. Medido: a tela abre em ~98%.
        return False, "tela de cadastro nao abriu para quem leu"
    if not d.get("mov_custodia"):
        # Sem as transicoes de custodia nao ha como RECALCULAR os cinco campos por
        # mesa — so copiar, que e o erro que este cache existe para nao cometer.
        # Coleta anterior ao conserto do coletor cai aqui, e e assim que deve ser.
        return False, "sem mov_custodia (coleta anterior ao conserto do coletor)"
    if d.get("mesas_fonte") == "andamento":
        return False, "arvore nao parseou (mesas vieram do andamento)"
    if not d.get("documentos"):
        return False, "arvore sem documentos"
    if (d.get("nivel_acesso") or "") not in NIVEIS_OK:
        return False, f"nivel de acesso {d.get('nivel_acesso')!r} exige leitura propria"
    return True, None


def publicar(cx, linhas, dono_usuario_id, coletado_em, instancia, mesas_falhas=()):
    """Grava no poco as linhas LIMPAS desta coleta. Devolve o relatorio.

    `coletado_em` e a hora declarada pela estacao; `recebido_em` sai do relogio
    do servidor, aqui. Bloco mais VELHO nunca sobrescreve bloco mais novo.
    """
    falhas = set(mesas_falhas or ())
    pub, recusadas, acomps = 0, {}, 0
    canario_lidos = canario_div = 0
    for d in linhas:
        if d.get("mesa_coleta") in falhas:
            recusadas["mesa em falha"] = recusadas.get("mesa em falha", 0) + 1
            continue
        # O ACOMPANHAMENTO TEM VIDA PROPRIA e nao depende das travas de qualidade
        # do bloco (custodia, arvore, truncado). A linha que veio pelo caminho
        # barato tem acompanhamento fresco e bloco nenhum: gravado so junto com o
        # bloco, ele era jogado fora, o prazo de 7 dias nunca comecava a correr e a
        # mesma pessoa relia o mesmo acompanhamento todo dia, para sempre.
        if d.get("_acomp_fresco") and _guardar_acomp(cx, d, dono_usuario_id,
                                                     coletado_em, instancia):
            acomps += 1
        ok, motivo = publicavel(d)
        if not ok:
            recusadas[motivo] = recusadas.get(motivo, 0) + 1
            continue
        # O CANARIO COMPARA ANTES DE SOBRESCREVER. Depois nao da: o upsert apaga o
        # termo de comparacao. Quem e canario o servidor recomputa com o mesmo
        # sorteio deterministico, sem depender de a estacao contar.
        if _sorteio(d.get("id"), (coletado_em or "")[:10], "canario") < CANARIO:
            n_div = divergencia(cx, d, instancia)
            if n_div is not None:
                canario_lidos += 1
                canario_div += n_div
        _upsert(cx, d, dono_usuario_id, coletado_em, instancia)
        pub += 1
        # A guarda e por MESA: e a lista daquela mesa que ela fotografa.
        cx.execute("""INSERT INTO poco_conferencia(id_sei,instancia,mesa,hash,em)
                      VALUES(?,?,?,?,?)
                      ON CONFLICT(id_sei,instancia,mesa) DO UPDATE SET
                        hash=excluded.hash, em=excluded.em
                      WHERE excluded.em > poco_conferencia.em""",
                   (d.get("id"), instancia, d.get("mesa_coleta"),
                    hash_guarda(d), coletado_em))
        if not d.get("_acomp_fresco") and _guardar_acomp(cx, d, dono_usuario_id,
                                                         coletado_em, instancia):
            acomps += 1
    return {"publicados": pub, "recusados": recusadas, "acompanhamentos": acomps,
            "canario_lidos": canario_lidos, "canario_divergencias": canario_div}


def _guardar_acomp(cx, d, dono_usuario_id, coletado_em, instancia):
    """Acompanhamento POR (processo, MESA, DONO). Sem dono — estacao de bootstrap —
    nao se guarda: nao ha a quem devolver, e guardar sob NULL seria compartilhar
    justamente o unico campo que o desenho proibe de atravessar pessoa.

    A guarda de ordem (`WHERE excluded.em > ...`) espelha a do bloco. Sem ela,
    reingerir um arquivo antigo — caminho documentado neste projeto — rebobinava o
    acompanhamento corrente para a versao daquele dia, e servir() a devolvia com
    acomp_lido=1: observacao de um mes atras exibida como atual.
    """
    if not (dono_usuario_id and d.get("acomp_disponivel")
            and d.get("acompanhamento") is not None):
        return False
    cx.execute("""INSERT INTO poco_acompanhamento(id_sei,instancia,mesa,
                  dono_usuario_id,dados,grupos,em) VALUES(?,?,?,?,?,?,?)
                  ON CONFLICT(id_sei,instancia,mesa,dono_usuario_id) DO UPDATE SET
                    dados=excluded.dados, grupos=excluded.grupos, em=excluded.em
                  WHERE excluded.em > poco_acompanhamento.em""",
               (d.get("id"), instancia, d.get("mesa_coleta"), dono_usuario_id,
                json.dumps(d.get("acompanhamento") or [], ensure_ascii=False),
                json.dumps(d.get("acomp_grupos") or [], ensure_ascii=False),
                coletado_em))
    return True


_FRIO = ("autuacao", "gerador_unidade", "gerador_usuario", "nivel_acesso",
         "hipotese_legal", "protocolo", "tipo_processo")
_MORNO = ("movimentos", "movimentos_exato", "movimentos_paginas", "documentos",
          "emails_enviados", "assinatura_externa", "sobrestado", "urgente",
          "mesas_fonte")
_JSON = ("assuntos", "interessados", "anexados", "mesas", "ultimo_movimento",
         "mov_custodia")


# Campos MORNOS que o canario compara. Nao inclui os frios (que nao mudam) nem os
# cinco por mesa (que sao recalculados, nao servidos).
_CANARIO_CMP = ("movimentos_exato", "documentos", "emails_enviados",
                "assinatura_externa", "sobrestado", "urgente", "ultimo_movimento",
                "mov_custodia", "mesas")


def divergencia(cx, d, instancia):
    """Quantos campos do bloco guardado diferem do que acabou de ser lido.

    Chamada ANTES do upsert, senao a unica copia contra a qual comparar ja foi
    sobrescrita — que era o defeito: o canario lia, publicava por cima e destruia
    o proprio termo de comparacao.
    """
    ant = cx.execute("SELECT * FROM poco_processo WHERE id_sei=? AND instancia=? "
                     "AND parser_versao=?",
                     (d.get("id"), instancia, PARSER_VERSAO)).fetchone()
    if not ant:
        return None
    n = 0
    for c in _CANARIO_CMP:
        novo = d.get(c)
        if c in _JSON:
            novo = json.dumps(novo, ensure_ascii=False) if novo is not None else None
        elif isinstance(novo, bool):
            novo = int(novo)
        if (ant[c] if novo is not None or ant[c] is not None else None) != novo:
            n += 1
    return n


def _upsert(cx, d, dono, coletado_em, instancia):
    vals = {c: d.get(c) for c in _FRIO}
    vals.update({c: d.get(c) for c in _MORNO})
    for c in _JSON:
        v = d.get(c)
        vals[c] = json.dumps(v, ensure_ascii=False) if v is not None else None
    vals.update({
        "alterar_disponivel": int(bool(d.get("alterar_disponivel"))),
        "sobrestado": int(bool(d.get("sobrestado"))),
        "urgente": int(bool(d.get("urgente"))),
        "leitura_completa": 1,
        "truncado_na_origem": int(bool(d.get("truncado"))),
        "mov_parcial": int(bool(d.get("mov_parcial"))),
        "frio_em": coletado_em, "frio_dono": dono,
        "morno_em": coletado_em, "morno_dono": dono,
        "recebido_em": agora(),
    })
    cols = ["id_sei", "instancia", "parser_versao"] + sorted(vals)
    marc = ",".join("?" * len(cols))
    # O WHERE do UPDATE e o que impede bloco VELHO de sobrescrever bloco NOVO:
    # duas pessoas coletam em horas diferentes e a ordem de chegada nao decide.
    sets = ",".join(f"{c}=excluded.{c}" for c in sorted(vals))
    cx.execute(f"""INSERT INTO poco_processo({','.join(cols)}) VALUES({marc})
                   ON CONFLICT(id_sei,instancia,parser_versao) DO UPDATE SET {sets}
                   WHERE excluded.morno_em > poco_processo.morno_em""",
               [d.get("id"), instancia, PARSER_VERSAO] + [vals[c] for c in sorted(vals)])


# -------------------------------------------------------------------- plano
def plano(cx, mesa, itens, instancia, execucao_id=None, dono_usuario_id=None,
          agora_dt=None):
    """Veredito por processo, para UMA mesa. Nunca devolve a data do bloco: o
    relogio e do servidor, e a estacao nao decide validade.

    `itens` sao as linhas que a lista da pessoa acabou de mostrar, com os campos
    da guarda. QUEM HASHEIA E O SERVIDOR: com a estacao mandando o hash pronto
    haveria duas implementacoes do mesmo hash, e a primeira divergencia entre
    elas apareceria como "nada nunca vale" — silenciosa, so mais cara.

    Vereditos:
      completa          — ler tudo (5 requisicoes)
      so_acompanhamento — o bloco vale; falta so o acompanhamento DESTA pessoa
      pular             — o poco responde por inteiro
      canario           — ler mesmo podendo pular, para conferir o poco
      em_leitura        — outro agente esta RELENDO um bloco que ainda serve;
                          nao duplique. NUNCA aparece sobre bloco condenado ou
                          ausente: pular o que ninguem leu e entregar linha vazia.
    """
    from datetime import datetime
    agora_dt = agora_dt or datetime.now(TZ)
    dia = agora_dt.date().isoformat()
    limite = (agora_dt + timedelta(minutes=RESERVA_MIN)).isoformat(timespec="seconds")

    # Reserva vencida volta a fila sozinha: agente que morre no meio nao tranca.
    cx.execute("DELETE FROM poco_reserva WHERE reserva_ate < ?",
               (agora_dt.isoformat(timespec="seconds"),))

    ids = [i.get("id") for i in itens if i.get("id")]
    blocos, guardas, acomps, reservas = _carregar(cx, ids, mesa, dono_usuario_id,
                                                  instancia)

    veredito, motivos, servivel_de = {}, {}, {}
    for it in itens:
        pid = it.get("id")
        if not pid:
            continue
        v, motivo, servivel = _julgar(it, blocos.get(pid), guardas.get(pid),
                                      acomps.get(pid), agora_dt, dia)
        # Reserva de OUTRA execucao: nao duplique — MAS so quando o poco consegue
        # responder pelo processo enquanto isso. Sem essa condicao, "outro agente
        # esta lendo" virava "nao leia" sobre bloco condenado (acima do teto, guarda
        # acusando mudanca) ou inexistente, e a pessoa recebia dado velho ou linha
        # vazia. Duplicar uma leitura custa 5 requisicoes; servir bloco reprovado
        # custa um numero plausivel e errado numa tela de triagem.
        if v in ("completa", "canario") and servivel and pid in reservas \
           and reservas[pid] != execucao_id:
            v, motivo = "em_leitura", "outro agente esta relendo; o bloco anterior serve"
        veredito[pid] = v
        motivos[pid] = motivo
        servivel_de[pid] = servivel

    # ATRIBUI em transacao: quem pediu primeiro leva. Sem isto, as 31 pessoas da
    # CESS recebem o mesmo plano de 254 processos no mesmo minuto.
    if execucao_id is not None:
        for pid, v in veredito.items():
            # So se reserva o que outro agente poderia pular COM SEGURANCA. Reservar
            # leitura fria nao economiza nada: quem viesse depois teria de ler assim
            # mesmo, e a reserva so serviria para esconder isso.
            if v in ("completa", "canario") and servivel_de.get(pid):
                cx.execute("""INSERT INTO poco_reserva(id_sei,instancia,execucao_id,
                              reserva_ate) VALUES(?,?,?,?)
                              ON CONFLICT(id_sei,instancia) DO UPDATE SET
                              execucao_id=excluded.execucao_id,
                              reserva_ate=excluded.reserva_ate""",
                           (pid, instancia, execucao_id, limite))

    resumo = {}
    for v in veredito.values():
        resumo[v] = resumo.get(v, 0) + 1
    return {"veredito": veredito, "motivos": motivos, "resumo": resumo,
            "parser_versao": PARSER_VERSAO, "mesa": mesa, "instancia": instancia}


def _carregar(cx, ids, mesa, dono, instancia):
    if not ids:
        return {}, {}, {}, {}
    blocos, guardas, acomps, reservas = {}, {}, {}, {}
    # SQLite tem teto de variaveis por statement; em lotes de 400 nunca se chega
    # perto dele nem com a CESS inteira.
    for i in range(0, len(ids), 400):
        p = ids[i:i + 400]
        m = ",".join("?" * len(p))
        for r in cx.execute(f"""SELECT * FROM poco_processo
                                WHERE instancia=? AND parser_versao=? AND id_sei IN ({m})""",
                            [instancia, PARSER_VERSAO] + p):
            blocos[r["id_sei"]] = r
        for r in cx.execute(f"""SELECT * FROM poco_conferencia
                                WHERE instancia=? AND mesa=? AND id_sei IN ({m})""",
                            [instancia, mesa] + p):
            guardas[r["id_sei"]] = r
        for r in cx.execute(f"SELECT * FROM poco_reserva WHERE instancia=? AND id_sei IN ({m})",
                            [instancia] + p):
            reservas[r["id_sei"]] = r["execucao_id"]
        if dono:
            for r in cx.execute(f"""SELECT * FROM poco_acompanhamento
                                    WHERE instancia=? AND mesa=? AND dono_usuario_id=?
                                      AND id_sei IN ({m})""",
                                [instancia, mesa, dono] + p):
                acomps[r["id_sei"]] = r
    return blocos, guardas, acomps, reservas


def _julgar(item, bloco, guarda, acomp, agora_dt, dia):
    """Devolve (veredito, motivo, servivel).

    `servivel` diz se o poco CONSEGUE responder por este processo agora — bloco
    presente, inteiro, dentro do teto e com a guarda batendo. E diferente do
    veredito: um bloco pode ser servivel e ainda assim ser relido pela faxina.

    A distincao existe porque so quando o poco consegue responder e que pular a
    leitura e seguro. Sem ela, "outro agente esta lendo" virava "nao leia" sobre
    bloco condenado — ou inexistente — e a linha saia vazia ou velha.
    """
    pid = item.get("id")
    # A guarda ve o BARULHO e e cega ao SILENCIO. Saber de qual lado esta linha
    # cai muda a prioridade da faxina: e na faixa cega que estao 100% dos escapes
    # medidos, inclusive as duas piores inflacoes de "dias na unidade".
    cega = guarda_cega(item)
    if bloco is None:
        return "completa", "sem bloco no poco", False
    idade = idade_h(bloco, agora_dt)
    if idade is None:
        return "completa", "bloco sem data", False
    if idade > TETO_H:
        return "completa", f"bloco com {idade:.0f} h, acima do teto de {TETO_H} h", False
    if bloco["mov_parcial"] or not bloco["leitura_completa"]:
        return "completa", "bloco veio de leitura incompleta", False
    if (bloco["nivel_acesso"] or "") not in NIVEIS_OK:
        return "completa", "nivel de acesso exige leitura propria", False
    if guarda is None:
        return "completa", "sem guarda desta mesa", False
    if guarda["hash"] != (item.get("hash") or hash_guarda(item)):
        return "completa", "a lista mudou desde a leitura do bloco", False
    # FAXINA: 1/3 por dia garante o teto de 72 h por aritmetica. A prioridade e
    # invertida em relacao ao obvio — primeiro o que a GUARDA nao consegue ver,
    # porque e onde estao 100% dos escapes medidos.
    if idade > MORNO_H:
        # SORTEIO UNIFORME. A versao anterior priorizava a faixa "cega" (sem
        # marcador, sem anotacao, sem retorno, sem atribuicao) supondo que a guarda
        # so falhava ali. Medido nos 5 pares de dias desta base: dos 183 processos
        # que andaram e escaparam da guarda, 174 (95%) estao FORA da faixa cega —
        # a prioridade estava invertida e desprezava justamente onde os escapes
        # estao. Sem uma hipotese medida sobre ONDE reler primeiro, releitura
        # uniforme e a unica que nao concentra o erro num canto.
        if _sorteio(pid, dia, "faxina") < min(FAXINA, 1.0):
            # SERVIVEL: o bloco esta bom, so caiu na cota de releitura do dia.
            # E o unico "completa" em que outro agente lendo torna seguro pular.
            return "completa", "faxina do bloco morno", True
    # CANARIO: le mesmo podendo pular, so para conferir. Estratificado na faixa
    # cega, que e onde a guarda nao alcanca.
    if cega and _sorteio(pid, dia, "canario") < CANARIO:
        return "canario", "conferencia do poco", True
    # O acompanhamento e da PESSOA. O bloco pode valer e ele nao.
    if acomp is None or _horas(acomp["em"], agora_dt) > ACOMP_D * 24:
        return "so_acompanhamento", "bloco vale; acompanhamento desta pessoa vencido", True
    return "pular", f"bloco de {idade:.0f} h serve", True


# -------------------------------------------------------------------- servir
def servivel(bloco, agora_dt=None):
    """O poco pode responder por este bloco? (bool, motivo).

    MESMO gate de _julgar, aplicado na saida. Nao e redundancia: _julgar decide
    com a lista na mao, minutos antes; servir() e a ultima porta antes de o valor
    entrar na tela. Quando a primeira falhou — e ja falhou —, esta faz a linha
    cair no caminho de orfao, que existe e avisa.
    """
    from datetime import datetime
    agora_dt = agora_dt or datetime.now(TZ)
    if bloco is None:
        return False, "sem bloco"
    idade = idade_h(bloco, agora_dt)
    if idade is None:
        return False, "bloco sem data"
    if idade > TETO_H:
        return False, f"bloco com {idade:.0f} h, acima do teto de {TETO_H} h"
    if bloco["mov_parcial"] or not bloco["leitura_completa"]:
        return False, "bloco veio de leitura incompleta"
    if (bloco["nivel_acesso"] or "") not in NIVEIS_OK:
        return False, "nivel de acesso exige leitura propria"
    if not bloco["alterar_disponivel"]:
        # assuntos/interessados sairiam [] porque a tela de cadastro nao abriu para
        # quem leu — e [] por tela fechada e diferente de [] por nao ter assunto.
        return False, "tela de cadastro nao abriu para quem leu o bloco"
    return True, None


def servir(cx, ids, instancia, mesa=None, dono_usuario_id=None, agora_dt=None):
    """Blocos por id, para costurar na ingestao. Devolve dict id -> dict.

    So devolve bloco que passe por `servivel()`. Bloco reprovado simplesmente nao
    e devolvido, e quem chama trata como orfao.

    LISTA DE PERMISSAO de chaves, nunca lista de proibicao: chave nova
    acrescentada ao coletor no futuro entraria sozinha no cache se o filtro
    fosse negativo — e `href` carrega infra_hash de sessao, cujo reuso nao da
    erro: DERRUBA a sessao de quem esta trabalhando.
    """
    if not ids:
        return {}
    saida = {}
    # A MESA TEM DE TER VISTO O PROCESSO. Os ids vem do corpo publicado pelo
    # agente; sem este recorte, uma linha forjada com id_sei de outra unidade
    # devolveria o bloco inteiro daquele processo — protocolo, assuntos,
    # interessados, gerador_usuario e o mov_custodia com nome de quem movimentou.
    # Antes do poco forjar um id nao dava informacao nenhuma (o dado vinha do
    # proprio forjador); com o poco o servidor viraria oraculo. A resposta ja
    # existe em poco_conferencia, que e escrita por mesa.
    if mesa:
        vistos = set()
        for i in range(0, len(ids), 400):
            p = ids[i:i + 400]
            m = ",".join("?" * len(p))
            vistos |= {r[0] for r in cx.execute(
                f"""SELECT id_sei FROM poco_conferencia
                    WHERE instancia=? AND mesa=? AND id_sei IN ({m})""",
                [instancia, mesa] + p)}
        ids = [i for i in ids if i in vistos]
        if not ids:
            return {}
    for i in range(0, len(ids), 400):
        p = ids[i:i + 400]
        m = ",".join("?" * len(p))
        for r in cx.execute(f"""SELECT * FROM poco_processo
                                WHERE instancia=? AND parser_versao=? AND id_sei IN ({m})""",
                            [instancia, PARSER_VERSAO] + p):
            ok, _motivo = servivel(r, agora_dt)
            if not ok:
                continue
            saida[r["id_sei"]] = _desempacotar(r)
        if mesa and dono_usuario_id:
            for r in cx.execute(f"""SELECT * FROM poco_acompanhamento
                                    WHERE instancia=? AND mesa=? AND dono_usuario_id=?
                                      AND id_sei IN ({m})""",
                                [instancia, mesa, dono_usuario_id] + p):
                if r["id_sei"] in saida:
                    saida[r["id_sei"]]["acompanhamento"] = json.loads(r["dados"] or "[]")
                    saida[r["id_sei"]]["acomp_grupos"] = json.loads(r["grupos"] or "[]")
                    saida[r["id_sei"]]["acomp_lido"] = 1
    return saida


PERMITIDAS = tuple(sorted(set(_FRIO + _MORNO + _JSON) | {
    "alterar_disponivel", "leitura_completa", "truncado_na_origem", "mov_parcial",
    "morno_em", "morno_dono"}))


def _desempacotar(r):
    o = {c: r[c] for c in PERMITIDAS}
    for c in _JSON:
        o[c] = json.loads(o[c]) if o[c] else None
    o["acompanhamento"], o["acomp_grupos"], o["acomp_lido"] = None, None, 0
    return o


# ---------------------------------------------------------- recalculo por mesa
REMESSA = "processo remetido pela unidade "
RECEBE = ("processo recebido na unidade", "reabertura do processo na unidade")


def campos_da_mesa(mov_custodia, unidade):
    """Os CINCO campos que dependem de QUEM le, derivados para `unidade`.

    Gemea de camposDaMesa() em automacao_sei.js. Sao duas implementacoes da MESMA
    regra de proposito: o coletor precisa dela durante a coleta e o servidor
    precisa dela ao servir um bloco lido por outra mesa. `_teste_camposdamesa.js`
    e `teste_poco.py` rodam o MESMO caso sobre as duas — se divergirem, um dos
    dois quebra.

    Sem linha da unidade pedida, devolve os cinco NULOS e `derivada_para` nulo.
    Ausencia significa "nao sei", nunca "sem divergencia": quem consome tem de
    exigir leitura real.
    """
    vazio = {"recebimento": None, "recebimento_por": None, "envio": None,
             "unidade_envio": None, "marco_unidade": None, "derivada_para": None}
    if not unidade or not mov_custodia:
        return dict(vazio)
    # o SEI entrega o historico do mais NOVO para o mais antigo; o primeiro que
    # casar e o que vale
    rec = env = marco = None
    for m in mov_custodia:
        de = (m.get("de") or "").strip().lower()
        if rec is None and m.get("un") == unidade and de.startswith(RECEBE):
            rec = m
        # a saida e a linha em que a unidade aparece como REMETENTE (na descricao),
        # nao aquela em que ela e o DESTINO
        if env is None and de.startswith(REMESSA) \
           and (m.get("de") or "")[len(REMESSA):].strip() == unidade:
            env = m
        if marco is None and m.get("un") == unidade \
           and de.startswith("processo ") and " gerado" in de:
            marco = m
    marco = rec or marco
    if rec is None and env is None and marco is None:
        return dict(vazio)
    return {
        "recebimento": rec["dh"] if rec else None,
        "recebimento_por": rec["us"] if rec else None,
        "envio": env["dh"] if env else None,
        "unidade_envio": env["un"] if env else None,
        # data-marco, NUNCA dias_na_unidade: numero de tempo gravado congela
        "marco_unidade": marco["dh"] if marco else None,
        "derivada_para": unidade,
    }
