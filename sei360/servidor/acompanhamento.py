# -*- coding: utf-8 -*-
"""Acompanhamento: processos que a pessoa segue, onde eles estiverem.

REGRA PURA, SEM ROTA E SEM HTML. `app.py` só transporta — é o mesmo arranjo de
`busca.py`, `ingestao.py` e `poco.py`, e é o que torna esta suíte possível sem
subir servidor.

O QUE ESTE MÓDULO NÃO FAZ, E É DESENHO
--------------------------------------
Não escreve em `snapshot`, `processo` nem `poco_*`. Processo acompanhado não é
carteira: não soma indicador do painel e não entra em relatório. A fronteira que o
resto do sistema defende continua sendo a da carteira, e este módulo não abre porta
lateral nela — o reaproveitamento da carteira (`reaproveitar`, no fim deste
arquivo) sai de `snapshots_de`, o MESMO recorte por unidade que o painel usa,
nunca de um SELECT direto em `processo` que enxergaria mesa de qualquer dono.
"""
import json
import re

import janelas
from banco import agora

# Teto por pessoa. Com o reaproveitamento da carteira, só o que está fora das
# mesas custa requisição ao SEI.
#
# SÃO SEIS REQUISIÇÕES POR PROCESSO, medido em 11/09/2026: GET da tela de
# Pesquisa, POST da pesquisa, GET do processo, GET da árvore, GET do andamento,
# GET da tela Consultar/Alterar — esta última é a da FICHA (`assuntos` e
# `interessados`), e cai fora quando o processo não tem aquela ação, deixando
# cinco. A conta original dizia três e esquecia o par da pesquisa: a tela de
# Pesquisa é reaberta a cada protocolo, e CORRETAMENTE — reusar o formulário da
# vez anterior é exatamente o risco de `infra_hash` morto, que não devolve erro,
# derruba a sessão de quem está trabalhando.
#
# Pior caso: ~600 numa lista cheia inteiramente de fora — contra as ~5.900 que a
# coleta de 1.182 processos já faz, ou ~10% a mais, uma vez por dia por pessoa
# (há trava de uma leitura por dia por item). Continua seguro; o que não
# continuava era o número. O teto existe para a lista não virar uma segunda
# coleta sem ninguém ter decidido isso.
#
# A contagem é lida uma vez por chamada, e sob concorrência (3 workers x 2
# threads) duas colagens simultâneas da mesma conta podem passar do teto —
# medido, chega a 101. Aceito de propósito: este teto é ORÇAMENTO de requisição
# ao SEI, não fronteira de acesso, e três itens a mais custam dezoito requisições
# uma vez. Serializar a leitura+escrita da contagem para isso seria cerimônia
# desproporcional numa lista pessoal.
TETO = 100

# Só dígitos e a pontuação que o SEI usa. Linha que não casa NÃO é descartada em
# silêncio: volta como recusada, com o texto que a pessoa colou. É o princípio de
# `filtros_recusados` em `pesquisa_sei.js` — entrada que não pegou muda o universo
# da resposta sem mudar uma linha do resultado.
#
# Dígito nas DUAS PONTAS, não `^[\d.\-/]+$`. O ponto é separador legítimo DENTRO
# do número, e o regex antigo não distinguia isso de ponto final de frase: um
# número copiado de citação ("... conforme o SEI 019.5120.2026.0161681-50.")
# entrava com o ponto dentro do protocolo e nunca casava com o SEI — aceito na
# tela, eternamente "não encontrado" na leitura, e duplicado no dia em que a
# pessoa colasse de novo sem o ponto.
#
# `[0-9]`, NÃO `\d`: em Python `\d` casa dígito Unicode — '١٢٣' passa —, e o
# espelho em SQL (`_SQL_DIGITOS`, abaixo) não converte nada disso: ele só tira
# pontuação. Número que a régua de identidade não consegue representar entraria
# na lista com `digitos()` vazio, colidindo com qualquer outro igualmente
# exótico e não casando com carteira nenhuma. O alfabeto da identidade é ASCII
# nas duas pontas, ou não é o mesmo alfabeto.
_SO_NUMERO = re.compile(r"^[0-9][0-9.\-/]*[0-9]$")
_MIN_DIGITOS = 10


def normalizar(texto):
    """O que a pessoa colou -> protocolo, ou None se não é número de processo."""
    t = (texto or "").strip()
    if not t or not _SO_NUMERO.match(t):
        return None
    if sum(c.isdigit() for c in t) < _MIN_DIGITOS:
        return None
    return t


def digitos(protocolo):
    """Só os dígitos. É a IDENTIDADE do processo; a pontuação é apresentação.

    O SEI 4.0 da FESF e o 5.0.4 da SESAB imprimem o mesmo número com pontuação
    diferente, e quem cola cola o que viu. Comparar o texto puro fazia duas
    coisas erradas ao mesmo tempo: o número colado sem pontuação nunca casava
    com a carteira (que guarda a forma pontuada), caindo para sempre no caminho
    caro do SEI por um dado que já estava no banco; e a mesma pessoa colando o
    mesmo processo em duas formas ganhava duas linhas na lista.

    O `protocolo` continua GUARDADO como a pessoa colou — é a forma que ela
    reconhece na tela, e é a chave de `acompanhado`. Isto aqui é só a régua de
    comparação.
    """
    # `'0' <= c <= '9'`, não `isdigit()`: `isdigit()` é verdadeiro para '²' e
    # para dígito árabe-índico, e o espelho em SQL não trata nenhum dos dois —
    # ele só tira pontuação. A régua tem de ser a MESMA nas duas pontas, senão
    # a lista e a carteira passam a comparar coisas diferentes.
    return "".join(c for c in (protocolo or "") if "0" <= c <= "9")


# O espelho de `digitos()` em SQL, que é o que permite casar a lista com a
# carteira sem coluna nova nem mudança de esquema. Remove a pontuação que
# `_SO_NUMERO` aceita, mais o espaço — que a pessoa não consegue colar (o regex
# recusa), mas que pode vir no texto que o SEI imprime.
#
# NÃO HÁ ÍNDICE NISSO, e não precisa: `p.snapshot_id IN (...)` já restringe pelo
# PREFIXO da chave primária de `processo` — `(snapshot_id, id_sei)` —, então a
# expressão só é avaliada sobre as linhas da carteira daquela pessoa, ordem de
# 1.200 por coleta, nunca sobre a tabela inteira. Índice em expressão aqui seria
# custo de escrita em toda ingestão para economizar microssegundo em consulta que
# já está restrita.
_SQL_DIGITOS = ("REPLACE(REPLACE(REPLACE(REPLACE(p.protocolo,'.',''),'-',''),"
                "'/',''),' ','')")


# ------------------------------------------------------------------ a ficha
#
# A FICHA COMPLETA, campo a campo e em UMA lista só. É a mesma escolha de
# `relatorios.COLUNAS`, e pelo mesmo motivo: a lista paralela envelhece no
# primeiro dia em que alguém acrescenta um campo e esquece de atualizar a outra
# ponta — e aqui há TRÊS pontas (o SELECT da carteira, o INSERT da leitura e o
# SELECT da tela). Derivadas da mesma tupla, elas não têm como divergir.
#
# A ORDEM É A DO INSERT, e por isso `_DE_PROCESSO + _DE_TEXTO`: os nomes são
# iguais aos das colunas de `acompanhado_leitura` de propósito, para o SELECT da
# carteira, o INSERT e o SELECT da tela serem a MESMA lista com prefixo
# diferente.
#
# ONDE O CAMPO MORA NA CARTEIRA. `processo` e `processo_texto` são tabelas
# separadas de propósito — a segunda é "onde estão os campos que podem citar
# paciente" —, e é essa separação que decide o prefixo de cada um no SELECT.
_DE_PROCESSO = ("tipo_processo", "autuacao", "gerador_unidade", "gerador_usuario",
                "nivel_acesso", "hipotese_legal", "assuntos", "anexados",
                "emails_enviados", "assinatura_externa",
                "marcador", "marcador_cor", "atribuido_nome", "atribuido_login",
                "visualizado", "marco_unidade", "recebimento", "recebimento_por",
                "envio", "unidade_envio", "mesa_indeterminada")
_DE_TEXTO = ("especificacao", "interessados", "anotacao", "anotacao_autor",
             "anotacao_data")
CAMPOS_FICHA = _DE_PROCESSO + _DE_TEXTO

# QUAIS SÓ EXISTEM DENTRO DA MESA — classificação por DISPONIBILIDADE, que não é
# a mesma coisa que por tabela: `anotacao` mora em `processo_texto` e é da mesa;
# `nivel_acesso` mora em `processo` e vale em qualquer lugar. Medido no coletor:
# `linha5`/`linha4` tiram estes campos da LINHA da tabela de Controle de
# Processos daquela mesa, e para processo fora das mesas da conta essa linha não
# existe. Esta tupla é o que permite a tela dizer "não existe" em vez de imprimir
# um marcador em branco — a diferença que o pedido de 11/09/2026 exige.
CAMPOS_DA_MESA = ("marcador", "marcador_cor", "atribuido_nome", "atribuido_login",
                  "visualizado", "marco_unidade", "recebimento", "recebimento_por",
                  "envio", "unidade_envio", "mesa_indeterminada",
                  "anotacao", "anotacao_autor", "anotacao_data")

# OS QUE SÃO JSON. Entram e saem como LISTA, como `aberto_em` e
# `ultimo_movimento` já faziam: a tela que recebesse a string crua iteraria
# caractere por caractere — o mesmo defeito que `_unidades()` documenta ter
# transformado "SESAB/X" em seis unidades chamadas 'S','E','A','B','/','X'.
CAMPOS_JSON = ("assuntos", "anexados", "interessados")

# As colunas da LEITURA que a tela lê. Montadas da tupla acima para o SELECT de
# `listar()` não virar uma segunda lista de nomes escrita à mão.
_COLUNAS_LEITURA = ("fonte", "medido_em", "aberto_em", "aberto_em_fonte",
                    "ultimo_movimento", "documentos", "movimentos", "mudou",
                    "comparacao") + CAMPOS_FICHA
_SQL_LEITURA = ("l.lido_em AS leitura_em, "
                + ", ".join(f"l.{c}" for c in _COLUNAS_LEITURA))


def _lista_json(bruto):
    """JSON que era para ser lista -> lista, ou None quando não deu.

    None e `[]` são coisas diferentes aqui, como em `aberto_em`: `[]` é "a coleta
    leu e não havia assunto nenhum", None é "não observado".

    NÃO LEVANTA. `reaproveitar` roda dentro de `pendentes`, que é o corpo de uma
    rota do agente — e ali uma exceção é 500, que a estação responde tentando o
    mesmo envelope para sempre. A carteira grava estes campos com `json.dumps`,
    então JSON quebrado aqui é improvável; improvável não é impossível, e o preço
    do engano é a fila do agente parar.
    """
    if not bruto:
        return None
    try:
        v = json.loads(bruto)
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, list) else None


def _movimento_json(bruto):
    """JSON que era para ser o objeto {dh, un, de} -> dict, ou None quando não deu.

    O IRMÃO DE `_lista_json`, e existe pelo mesmo motivo com outro tipo: o módulo
    conferia o tipo de tudo o que vem da ESTAÇÃO (`_texto`, `_contagem`,
    `_lista_texto`, e a doutrina do relator não confiável) e de NADA do que vem da
    carteira. Medido em 11/09/2026 com `ultimo_movimento` guardando uma string em
    vez de um objeto: `delta()` faz `(anterior.get("ultimo_movimento") or {})
    .get("dh")`, e sobre string isso é AttributeError na SEGUNDA leitura — 500 na
    rota do agente (que não tem `except`, e a estação repete o ciclo para
    sempre), e na tela o `except` de melhor-esforço engolindo o erro com o
    reaproveitamento MORTO para aquela conta inteira, porque o laço morre no
    primeiro item.

    A coluna é TEXT e o SQLite não impede nada; quem escreve é a ingestão, e
    "improvável" não é "impossível" — é a mesma conta que `_lista_json` já fez.
    """
    if not bruto:
        return None
    try:
        v = json.loads(bruto)
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def adicionar(cx, usuario_id, texto, instancia, origem="manual", nota=None):
    """Uma ou várias linhas -> (aceitos, recusados, sem_espaco).

    Os dois motivos de recusa vêm SEPARADOS, e não num balde só: `recusados` é
    "isto não parece número de processo" e `sem_espaco` é "a lista está cheia".
    A ação de quem colou é outra em cada caso — conferir o dígito contra parar
    de acompanhar algo —, e a tela mandava conferir o dígito de número correto
    porque os dois chegavam juntos.

    As duas listas levam o texto ORIGINAL da linha, não a versão normalizada:
    quem colou precisa reconhecer o que não entrou para poder corrigir.
    """
    quantos = cx.execute(
        "SELECT COUNT(*) FROM acompanhado WHERE usuario_id=?", (usuario_id,)
    ).fetchone()[0]
    # UMA consulta para o conjunto já seguido, não uma por linha: colar 60
    # números fazia 61 SELECTs (e colar os mesmos 60 de novo, 61 SELECTs para
    # zero aceite) — o mesmo N+1 que o comentário de `listar()`, duas funções
    # abaixo, existe para evitar. Idioma da casa: `poco.py`, função `_carregar`.
    # Sem `IN (...)` em lotes porque aqui o universo já é o da PESSOA inteira,
    # sempre <= TETO — não uma lista de candidatos que pode passar dos limites
    # de variável por statement do SQLite.
    # O CONJUNTO É DE DÍGITOS, não do texto do protocolo. A pontuação é
    # apresentação: colar `019.5120.2026.0161681-50` e depois o mesmo número
    # corrido é seguir o MESMO processo duas vezes, e a chave primária — que é o
    # texto — não tem como impedir. Quem impede é esta comparação.
    ja_seguidos = {digitos(r["protocolo"]) for r in cx.execute(
        "SELECT protocolo FROM acompanhado WHERE usuario_id=? AND instancia=?",
        (usuario_id, instancia))}
    aceitos, recusados, sem_espaco = [], [], []
    for linha in (texto or "").replace(",", "\n").splitlines():
        if not linha.strip():
            continue
        p = normalizar(linha)
        if not p:
            recusados.append(linha.strip())
            continue
        if digitos(p) in ja_seguidos:
            continue
        if quantos >= TETO:
            sem_espaco.append(linha.strip())
            continue
        # `OR IGNORE` PORQUE `ja_seguidos` É UMA FOTO, e a linha pode nascer
        # depois dela. Medido em 11/09/2026, e basta um duplo clique: a segunda
        # requisição comita o mesmo número entre o SELECT e o INSERT desta, o
        # INSERT levanta IntegrityError, a rota devolve 500 — e os OUTROS números
        # válidos da mesma colagem NÃO ENTRAM, porque o laço morre no do meio.
        # Quem colou perde o trabalho por causa de um número que já estava lá.
        #
        # O `OR IGNORE` alcança só a chave primária desta tabela: FK não obedece
        # a cláusula (é o SQLite que decide isso, não nós) e continua levantando,
        # e os outros valores são desta função, não do cliente. Logo, `rowcount`
        # zero aqui significa UMA coisa — a linha já existe —, que é o mesmo caso
        # de `ja_seguidos` acima e recebe o mesmo tratamento: não conta como
        # aceita, e não devolve erro para quem não errou.
        entrou = cx.execute(
            """INSERT OR IGNORE INTO acompanhado(usuario_id,instancia,protocolo,
               origem,nota,adicionado_em,estado) VALUES(?,?,?,?,?,?,'novo')""",
            (usuario_id, instancia, p, origem, nota, agora())).rowcount
        if not entrou:
            ja_seguidos.add(digitos(p))
            continue
        quantos += 1
        ja_seguidos.add(digitos(p))
        aceitos.append(p)
    return aceitos, recusados, sem_espaco


def remover(cx, usuario_id, instancia, protocolo):
    """Sai da lista, e o histórico sai com ela — foi a pessoa que desistiu.

    Devolve QUANTAS linhas saíram, que é zero quando não havia o que remover.
    Quem escreve o log precisa disso: `registrar` é a resposta de "quem fez o
    quê" num incidente, e gravar `parar_acompanhar` sobre protocolo que não
    estava na lista afirma um ato que não aconteceu.
    """
    n = cx.execute("""DELETE FROM acompanhado
                  WHERE usuario_id=? AND instancia=? AND protocolo=?""",
               (usuario_id, instancia, protocolo)).rowcount
    cx.execute("""DELETE FROM acompanhado_leitura
                  WHERE usuario_id=? AND instancia=? AND protocolo=?""",
               (usuario_id, instancia, protocolo))
    return n


def listar(cx, usuario_id):
    """A lista da pessoa, cada item com a ÚLTIMA leitura já embutida.

    Uma consulta, não N+1: a tela mostra lista com ficha, e uma consulta por item
    transformaria 100 processos em 101 idas ao banco a cada abertura.

    CONTINUA SENDO UMA depois da ficha completa, e isso não é acaso: a ficha foi
    guardada em `acompanhado_leitura`, coluna a coluna, em vez de ser buscada em
    `processo` na hora de pintar. Ir buscar custaria um JOIN por item — ou, pior,
    um SELECT por item — e devolveria o marcador de HOJE numa ficha carimbada
    "pela sua coleta de 27/08". Guardar custa colunas; não guardar custaria as
    duas coisas que este módulo mais defende, o custo e a procedência.
    """
    linhas = cx.execute(f"""
        SELECT a.*, {_SQL_LEITURA}
        FROM acompanhado a
        LEFT JOIN acompanhado_leitura l ON l.id = (
            SELECT id FROM acompanhado_leitura
            WHERE usuario_id=a.usuario_id AND instancia=a.instancia
              AND protocolo=a.protocolo
            ORDER BY id DESC LIMIT 1)
        WHERE a.usuario_id=?
        ORDER BY a.adicionado_em DESC""", (usuario_id,)).fetchall()
    saida = []
    for r in linhas:
        d = dict(r)
        for campo in ("aberto_em", "ultimo_movimento", "mudou"):
            d[campo] = json.loads(d[campo]) if d.get(campo) else None
        for campo in CAMPOS_JSON:
            d[campo] = _lista_json(d.get(campo))
        saida.append(d)
    return saida


def instancias(cx, usuario_id):
    """As instalações em que esta pessoa tem item na lista.

    `listar()` devolve a lista INTEIRA, das duas instalações juntas, mas
    `reaproveitar` é POR instalação — o recorte da fronteira depende disso.
    Quem chama precisa saber quais percorrer, e a resposta é o que a lista diz,
    não a configuração ativa: reaproveitar só a ativa deixaria o item da FESF
    dizendo "aguardando primeira leitura" com a resposta pronta na coleta da
    FESF, que é o defeito que este módulo inteiro existe para não cometer.
    """
    return [r["instancia"] for r in cx.execute(
        "SELECT DISTINCT instancia FROM acompanhado WHERE usuario_id=? "
        "ORDER BY instancia", (usuario_id,))]


def delta(anterior, atual):
    """O que mudou entre duas leituras. None quando nada mudou, e na primeira.

    Compara só QUATRO campos: `aberto_em`, `ultimo_movimento`, `documentos` e
    `movimentos`. `fonte` e `medido_em` ficam fora de propósito: trocar de
    "respondido pela carteira" para "lido no SEI" não é mudança NO PROCESSO, e
    apareceria como se fosse — exatamente o ruído que o selo de divergência
    árvore/andamento já produziu uma vez neste produto.

    None na PRIMEIRA leitura, nunca "mudou tudo": não há com o que comparar, e
    anunciar mudança onde não houve observação é a mesma falsidade do aviso de
    divergência que a auditoria de 10/09/2026 mediu como 100% falso positivo.
    """
    if not anterior:
        return None
    d = {}
    # AUSÊNCIA NÃO É CONJUNTO VAZIO. Com `or []`, leitura relatada SEM o campo
    # (árvore que não parseou, JSON truncado, campo que a estação não soube
    # preencher) virava "não está aberto em lugar nenhum", e a tela dizia que o
    # processo saiu de TODAS as unidades. A estação relata o que leu; o que ela
    # não leu não pode virar afirmação — e é a docstring desta função que promete
    # não anunciar mudança onde não houve observação.
    #
    # E LISTA VAZIA TAMBÉM NÃO É OBSERVAÇÃO — não aqui, onde se AFIRMA. `[]` é o
    # que a carteira entrega quando a coleta não gravou nenhuma linha em
    # `processo_mesa` (árvore que não parseou), e é o que a estação relata quando
    # a árvore não trouxe a linha "Processo aberto nas unidades". O produto já
    # diz isso por escrito na tela: "a leitura não trouxe unidade nenhuma", NUNCA
    # "não está aberto em lugar nenhum". Com `is not None` sozinho, o vazio
    # passava como conjunto observado e a subtração devolvia TODAS as unidades
    # anteriores — medido em 11/09/2026, mesmo processo e mesma unidade em duas
    # coletas: `mudou = {'saiu_de': ['SESAB/MINHA']}` para processo que não se
    # moveu. E o cartão saía autocontraditório, com "saiu de MINHA" três linhas
    # acima de "a leitura não trouxe unidade nenhuma".
    #
    # A REGRA VALE NOS DOIS LADOS: anterior vazio geraria o espelho da mesma
    # falsidade, "foi recebido em" todas as unidades da leitura nova.
    #
    # O VAZIO NÃO SOME DO PRODUTO por causa disto: ele continua indo para a
    # coluna e para a tela (ver `reaproveitar`, que entrega LISTA e nunca None) —
    # são dois canais, e é só o de AFIRMAR que emudece. Trocar `mesas` por
    # `mesas or None` na origem calaria os dois, e o item voltaria a parecer nunca
    # lido.
    antes_un, agora_un = anterior.get("aberto_em"), atual.get("aberto_em")
    if antes_un and agora_un:
        antes_un, agora_un = set(antes_un), set(agora_un)
        if antes_un - agora_un:
            d["saiu_de"] = sorted(antes_un - agora_un)
        if agora_un - antes_un:
            d["entrou_em"] = sorted(agora_un - antes_un)
    mov_antes = (anterior.get("ultimo_movimento") or {}).get("dh")
    mov_agora = (atual.get("ultimo_movimento") or {}).get("dh")
    if mov_agora and mov_agora != mov_antes:
        d["movimentou_em"] = mov_agora
    for contagem in ("documentos", "movimentos"):
        a, b = anterior.get(contagem), atual.get(contagem)
        if a is not None and b is not None and b != a:
            d[contagem] = b - a
    return d or None


def texto_do_delta(d):
    """O delta em português. Gerado do dado — nunca escrito à mão na tela."""
    if not d:
        return ""
    partes = []
    if d.get("saiu_de"):
        partes.append("saiu de " + ", ".join(u.split("/")[-1] for u in d["saiu_de"]))
    if d.get("entrou_em"):
        partes.append("foi recebido em "
                      + ", ".join(u.split("/")[-1] for u in d["entrou_em"]))
    for campo, rotulo in (("documentos", "documento"), ("movimentos", "movimento")):
        n = d.get(campo)
        if not n:
            continue
        # COM SINAL. Documento cancelado no SEI faz a contagem CAIR, e a versão
        # anterior desta função só falava de aumento — o item aparecia marcado
        # como alterado, sem uma palavra dizendo o que mudou.
        plural = "" if abs(n) == 1 else "s"
        partes.append(f"{n:+d} {rotulo}{plural}")
    if not partes and d.get("movimentou_em"):
        partes.append(f"movimentou em {d['movimentou_em']}")
    return " · ".join(partes)


# OS DOIS ESTADOS EM QUE O SEI RESPONDEU "NÃO". Não há leitura de hoje neles — e
# a leitura que a tela mostra é a ANTERIOR, o que muda o que cada frase pode
# afirmar. Ver `texto_da_procedencia` (que cala) e `texto_da_ficha` (que carimba).
_ESTADOS_DE_RECUSA = ("sem_acesso", "nao_encontrado")


def _dia_da_medicao(item, ano=None):
    """(fonte, dia) desta linha, ou (None, None) quando não há o que declarar.

    Extraído de `texto_da_procedencia` quando a ficha completa passou a precisar
    da MESMA régua com outra frase: duas funções fatiando a data por conta
    própria são duas regras de ano que divergem no primeiro remendo.

    A REGRA DE RECUSA NÃO MORA MAIS AQUI, e a mudança foi medida em 11/09/2026:
    os dois chamadores precisam de políticas OPOSTAS sobre o mesmo estado. O
    rodapé do cartão tem de calar (senão sai "Nada foi lido" e, embaixo, "pela
    sua coleta de 11/09", duas afirmações contrárias na mesma linha) e a ficha
    tem de CARIMBAR — a recusa não apaga a leitura anterior, que continua aberta
    no expandir com marcador, anotação e responsável de nove dias atrás. Sem
    carimbo, aquilo passa por ficha de agora, e o marcador é justamente o campo
    que alguém lê para decidir o que fazer hoje. Uma régua de data, duas
    políticas de recusa, cada uma na função que faz a afirmação.

    O ANO aparece quando não é o corrente. `11/09` de 2025 renderizava idêntico
    ao de hoje, e com uma coleta parada isso não é hipótese remota: é o mesmo
    cuidado de sempre neste módulo, não deixar dado velho passar por recente.

    Sem data não há dia a declarar — `medido_em` é coluna que aceita nulo, e
    fatiar nulo no template derrubava a tela INTEIRA, não a linha. A fonte volta
    mesmo assim, porque quem chama precisa distinguir "não houve leitura" de
    "houve leitura e ela não diz de quando é".
    """
    fonte = item.get("fonte")
    if not fonte:
        return None, None
    # A carteira fala da MEDIÇÃO (que pode ser de dias atrás); a leitura no SEI
    # fala da LEITURA, porque ali as duas são o mesmo instante.
    quando = item.get("medido_em") if fonte == "carteira" else item.get("leitura_em")
    if not quando or len(quando) < 10:
        return fonte, None
    dia = f"{quando[8:10]}/{quando[5:7]}"
    if quando[:4] != (ano or agora()[:4]):
        dia += f"/{quando[:4]}"
    return fonte, dia


def texto_da_procedencia(item, ano=None):
    """De ONDE e de QUANDO é o dado desta linha, em português. Gerado do dado.

    CALA EM ESTADO DE RECUSA, e é o único lugar onde essa regra vive: esta frase
    fica logo abaixo de "Nada foi lido", e ali "pela sua coleta de 11/09" são
    duas afirmações contrárias na mesma linha. A ficha, que fala do que está
    ABERTO no expandir, faz o contrário — ver `texto_da_ficha`.
    """
    if item.get("estado") in _ESTADOS_DE_RECUSA:
        return ""
    fonte, dia = _dia_da_medicao(item, ano)
    if not dia:
        return ""
    return (f"pela sua coleta de {dia}" if fonte == "carteira"
            else f"lido no SEI em {dia}")


def texto_da_ficha(item, ano=None):
    """A procedência que vale para a FICHA INTEIRA, e não só para as unidades.

    Existe porque a ficha completa mudou o alcance da afirmação. Enquanto o
    cartão mostrava unidades e contagens, "pela sua coleta de 27/08" no rodapé
    bastava. Com marcador, anotação, responsável e dias na unidade dentro dele, a
    mesma frase discreta deixa a ficha inteira parecendo de agora — e o marcador
    de nove dias atrás é exatamente o campo que alguém lê para decidir o que
    fazer hoje. Se a linha é de 27/08, TODO campo dela é de 27/08.

    NUNCA VAZIA quando houve leitura, mesmo sem data: `medido_em` aceita nulo, e
    ficha sem carimbo nenhum passa por ficha de agora — que é a afirmação falsa
    que esta função existe para impedir.

    E NEM EM RECUSA, que era onde a promessa acima estava sendo quebrada. Medido
    em 11/09/2026: cartão `sem_acesso` dizendo "Nada foi lido" e, no expandir, a
    ficha inteira da coleta anterior — marcador URGENTE, anotação, responsável —
    sem uma palavra dizendo de quando era. A recusa não insere leitura (certo:
    recusa não é observação), mas `listar()` traz a ANTERIOR pelo LEFT JOIN e o
    expandir abre com ela. Aqui o carimbo NOMEIA os campos da mesa, porque é sob
    o título "da sua mesa" que eles aparecem — para um processo que, tendo ido
    parar na fila da estação, já não está em mesa nenhuma da conta.
    """
    fonte, dia = _dia_da_medicao(item, ano)
    if not fonte:
        return ""
    if item.get("estado") in _ESTADOS_DE_RECUSA:
        quando = f", de {dia}" if dia else " e não diz de quando é"
        return (f"esta ficha é a leitura ANTERIOR{quando} — inclusive o marcador, "
                "a anotação e o responsável: hoje nada foi lido (o motivo está no "
                "alto do cartão)")
    if not dia:
        return ("esta ficha não diz de quando é: a leitura foi gravada sem data "
                "de medição")
    if fonte == "carteira":
        return (f"todos os campos desta ficha são da sua coleta de {dia} — não do "
                "momento em que você abriu esta tela")
    # "TODOS OS CAMPOS FORAM LIDOS" seria falso do lado do SEI: a leitura direta
    # ainda não traz a ficha inteira (é outra tarefa), e com essa frase os vinte
    # traços da ficha passariam a afirmar que o SEI não tem aqueles campos. A
    # frase diz o que a ficha é — uma leitura — e o que o vazio significa nela.
    return (f"esta ficha é a leitura feita no SEI em {dia}: o que está vazio é o "
            "que ela não trouxe")


def texto_sem_mesa(item):
    """Por que a ficha não traz os campos da mesa. Vazio quando ela traz.

    O DEFEITO QUE ESTA FUNÇÃO IMPEDE: imprimir "Marcador —" para processo que
    não está em mesa nenhuma da conta. Ali o traço diria "este processo não tem
    marcador", e a verdade é outra — o SEI não tem LINHA DE MESA para ele, então
    marcador, anotação, responsável e dias na unidade não têm onde ser lidos. As
    duas coisas se parecem na tela e levam a decisões opostas.

    A régua é `fonte`, e não uma coluna nova: `reaproveitar` só responde o que
    está numa mesa da conta (`snapshots_de`), e o que sobra para a estação ler no
    SEI é, por construção, o que não está em mesa nenhuma. Uma coluna que
    repetisse isso seria uma segunda verdade para manter — e a primeira a ficar
    velha. Ver `CAMPOS_DA_MESA`, no topo.
    """
    if item.get("fonte") != "sei":
        return ""
    # EM RECUSA A FRASE MUDA DE TEMPO, porque a linha é velha. Esta função fala
    # da `fonte` da ÚLTIMA leitura, e em estado de recusa essa leitura é a de
    # ontem: afirmar no presente ("o SEI não tem linha de mesa para ele") é dizer
    # de hoje o que se observou antes — no dia em que o SEI recusou o processo e
    # não se observou nada. É a mesma correção que o carimbo da ficha recebeu.
    if item.get("estado") in _ESTADOS_DE_RECUSA:
        return ("na leitura anterior este processo estava fora das suas mesas: "
                "marcador, anotação, responsável e dias na unidade não existiam "
                "para ele — e hoje nada foi lido")
    return ("fora das suas mesas: marcador, anotação, responsável e dias na "
            "unidade NÃO existem para este processo — não estão em branco, é o "
            "SEI que não tem linha de mesa para ele")


# O QUE O SERVIDOR RESPONDE POR ESTA CONTA, dito em código e não em prosa: o
# motivo chega aqui como rótulo e a FRASE é montada neste módulo, junto das
# outras. Fato é de quem administra o container (`acompanhamento_servidor`);
# palavra é de quem escreve a tela.
MOTOR_DESLIGADO = "motor_desligado"
SEM_BUSCA = "sem_busca"


def texto_fora_da_fila(item, instancia_ativa, rotulo_do_item=None,
                       rotulo_ativa=None, servidor_le=(), servidor_parado=None):
    """Por que este item NÃO vai ser lido no SEI hoje. Vazio quando vai.

    `servidor_le` são as instalações que ESTE container lê por esta conta hoje, e
    `servidor_parado` um mapa {instalação: motivo} das que ele deveria ler e não
    lê. Os dois entram por parâmetro porque são fato de implantação — quem os
    conhece é `acompanhamento_servidor.cobertura`.

    SEM ELES ESTA FUNÇÃO PASSOU A MENTIR, em 12/09/2026: no dia em que o
    container ganhou motor próprio de acompanhamento, a frase "hoje, só a sua
    própria coleta pode respondê-lo" continuou sendo impressa sobre item que o
    motor lê dois minutos depois. Aviso falso é pior que silêncio — ele ensina a
    não ler o aviso, e o aviso existia justamente para o item parado não se
    parecer com o item na fila.

    O DEFEITO QUE ESTA FUNÇÃO IMPEDE, medido em 11/09/2026: a rota do agente pede
    `instancia_do_agente`, que é a configuração ATIVA do dono, e a estação entra
    em UMA instalação por vez — então o item colado na outra nunca é oferecido.
    Três ciclos completos, e o item da FESF continuou 'novo', com a tela dizendo
    "aguardando primeira leitura": a mesma frase de quem vai ser lido hoje à
    noite. Item parado e item na fila ficavam idênticos, e nada avisava a pessoa.

    NÃO É A FILA QUE MUDA — a estação faz login numa instalação só, e mandá-la
    ler noutra seria pedir credencial que ela não tem. O que muda é o silêncio.

    CALA NOS DOIS CASOS EM QUE NÃO HÁ O QUE AVISAR: item da instalação ativa (vai
    para a fila normalmente) e item que a PRÓPRIA coleta daquela instalação já
    respondeu hoje — quem acompanha processo da própria carteira não depende da
    estação, que é o desenho de `reaproveitar` funcionando. Carimbar o aviso em
    toda linha da outra instalação seria ruído que ensina a não ler o carimbo, a
    mesma razão do `multi_instancia` do painel.

    Os RÓTULOS entram por parâmetro em vez de `perfil_sei` aqui dentro: este
    módulo é regra pura, e quem pinta a tela já resolve rótulo (`app.py`).
    """
    instancia = item.get("instancia")
    # LIDO HOJE, de qualquer fonte, é item em dia: `lido_em` é a mesma coluna que
    # `reaproveitar` e `pendentes` usam para a trava de uma leitura por dia.
    if (item.get("lido_em") or "")[:10] == agora()[:10]:
        return ""
    dele = rotulo_do_item or instancia
    # O SERVIDOR LÊ ESTA INSTALAÇÃO: não há o que avisar. Vem antes de tudo
    # porque o motor do container não depende da configuração ATIVA da pessoa —
    # ele lê as duas instalações no mesmo ciclo, que é justamente o que a
    # estação não consegue.
    if instancia in set(servidor_le or ()):
        return ""
    parado = (servidor_parado or {}).get(instancia)
    if parado == MOTOR_DESLIGADO:
        # A FALHA DE IMPLANTAÇÃO MAIS SILENCIOSA QUE ESTE MÓDULO TEM: a senha
        # está no servidor, ninguém precisa de estação nenhuma, e o interruptor
        # do motor está desligado. Sem esta frase o sintoma é o de sempre —
        # "aguardando primeira leitura", para sempre, e verdadeiro.
        return (f"não entra na fila: a senha desta conta para o {dele} está neste "
                "servidor, mas o motor de acompanhamento dele não está ligado — "
                "quem administra o SEI360 precisa ligá-lo "
                "(SEI360_COLETA_SERVIDOR)")
    if parado == SEM_BUSCA:
        # A leitura começa por uma pesquisa por número; sem busca provada na
        # instalação, ela devolveria "não encontrado" para TODO processo — e a
        # tela afirmaria sobre os processos o que é verdade sobre a instalação.
        return (f"não entra na fila: a busca por número ainda não roda no {dele}, "
                "e é por ela que a leitura de processo fora da carteira começa — "
                f"hoje, só a sua própria coleta do {dele} pode respondê-lo")
    if not instancia_ativa or instancia == instancia_ativa:
        return ""
    return (f"não entra na fila da estação: ela lê na instalação da sua "
            f"configuração ativa ({rotulo_ativa or instancia_ativa}), e este item "
            f"é do {dele} — hoje, só a sua própria coleta do {dele} pode "
            "respondê-lo")


def _medicao_avancou(nova, anterior):
    """A medição nova é ESTRITAMENTE mais nova que a da leitura anterior?

    Sobre `medido_em`, que é ISO com offset — nunca sobre `ultimo_movimento.dh`,
    que é `dd/mm/yyyy` e como texto põe 05/09 depois de 11/08.

    Data faltando, ou ilegível, responde NÃO: sem frescor estabelecido não se
    anuncia mudança. É o lado seguro do erro — o outro lado é imprimir perda de
    documento na tela de quem confia no número.
    """
    if not nova or not anterior:
        return False
    try:
        return janelas.com_fuso(nova) > janelas.com_fuso(anterior)
    except (TypeError, ValueError):
        return False


def gravar_leitura(cx, usuario_id, instancia, protocolo, dados, fonte, medido_em,
                   estado="lido", id_sei=None):
    """Uma leitura, com o delta contra a anterior já calculado.

    O delta é calculado AQUI, no servidor, e nunca chega pronto de fora: a
    estação relata o que leu, não o que concluiu.

    `medido_em` é OBRIGATÓRIO. Era opcional, com reserva silenciosa em
    `agora()` — e reserva silenciosa é exatamente o defeito que este campo
    existe para não ter: chamador que esquecesse carimbava "medido agora" sobre
    dado de nove dias atrás. Quem lê no SEI passa `agora()`, explicitamente,
    porque ali a medição É agora.
    """
    # EXIGIDO DE VERDADE, não só documentado: promessa que o código não impõe é
    # comentário, e o chamador que esquecesse gravaria leitura sem procedência —
    # a coluna aceita nulo, e quem fatiasse a data derrubaria a tela inteira.
    if not medido_em:
        raise ValueError("gravar_leitura exige medido_em: é a data da MEDIÇÃO, "
                         "e quem lê no SEI passa agora() explicitamente")
    # A ANTERIOR É A ÚLTIMA MEDIDA, NÃO A ÚLTIMA INSERIDA. Com `ORDER BY id DESC`
    # a guarda de monotonicidade abaixo silenciava o delta da medição que andou
    # para trás — e depois a leitura estagnada FICAVA sendo a base da próxima
    # leitura fresca, que ressuscitava inteiro o delta suprimido. Medido em
    # 11/09/2026:
    #
    #   t1 (10/09): aberto=[A,B]   docs=10 movs=20   -> primeira
    #   t2 (02/09): aberto=[A,B,C] docs=8  movs=14   -> sem_avanco, mudou=None
    #   t3 (hoje) : aberto=[B]     docs=11 movs=21
    #       dizia   'saiu de A, C · +3 documentos · +7 movimentos'
    #       verdade 'saiu de A · +1 documento · +1 movimento' (contra t1)
    #
    # A guarda não estava errada; estava incompleta. Suprimir o anúncio e deixar
    # a linha suprimida como referência é adiar a falsidade um dia, não impedi-la.
    #
    # `medido_em` ACEITA NULO nesta coluna (linha anterior à régua, ou gravada
    # fora daqui), e linha sem carimbo não tem lugar na linha do tempo: enquanto
    # houver uma datada, é ela a base. Em SQLite NULL é menor que tudo e `DESC`
    # já a jogaria para o fim, mas a ordem diz isso à mão — depender do padrão de
    # NULL do banco é o tipo de silêncio que este módulo paga caro. Com TODAS as
    # anteriores sem carimbo, sobra a última inserida e `_medicao_avancou`
    # responde NÃO, que é o lado seguro do erro.
    anterior = cx.execute("""SELECT medido_em, aberto_em, ultimo_movimento,
                             documentos, movimentos
                             FROM acompanhado_leitura
                             WHERE usuario_id=? AND instancia=? AND protocolo=?
                             ORDER BY medido_em IS NULL, medido_em DESC, id DESC
                             LIMIT 1""",
                          (usuario_id, instancia, protocolo)).fetchone()
    prev = None
    # AS TRÊS RAZÕES DE `mudou` FICAR NULO, ditas em `comparacao`. Antes eram
    # indistinguíveis, e a tela afirmava "sem mudança" para as três — inclusive
    # para a primeira observação de um processo, onde não houve comparação
    # nenhuma. Nomear os três casos aqui é o que deixa a tela dizer a verdade.
    #
    # SÓ SE COMPARA CONTRA OBSERVAÇÃO MAIS VELHA QUE ESTA. `ORDER BY id DESC` dá
    # a última INSERIDA, não a última MEDIDA, e as duas divergem no caso comum: o
    # processo sai da mesa de B, sobra a linha velha de A, e a medição anda para
    # trás. Sem esta guarda a tela anunciava "saiu de B · -5 documentos · -9
    # movimentos" — perda que nunca houve, só dado mais velho respondendo.
    #
    # Com a leitura no SEI na jogada fica pior: a guarda de "não lido hoje" é por
    # DIA, não por frescor, então amanhã a carteira de nove dias atrás responde
    # antes e o processo VOLTA NO TEMPO na tela, com movimentação inventada nas
    # duas direções.
    #
    # A doutrina é a que `delta()` já aplica à primeira leitura: não anunciar
    # mudança onde não houve observação nova. A leitura é gravada — a tela precisa
    # saber de quando é o dado que está mostrando —, mas `mudou` fica nulo.
    if not anterior:
        comparacao = "primeira"
    elif not _medicao_avancou(medido_em, anterior["medido_em"]):
        comparacao = "sem_avanco"
    else:
        comparacao = "comparada"
        # A LEITURA ANTERIOR SAI DO BANCO, e o banco guarda o que gravaram ontem
        # — inclusive antes de haver conferidor. `json.loads` cru aqui devolvia o
        # que estivesse lá: `aberto_em` como STRING vira, no `set()` do delta, um
        # conjunto de LETRAS (o defeito que `_unidades` descreve, entrando pela
        # porta de dentro), e `ultimo_movimento` como string estoura no `.get`.
        # Conferir na volta é o que impede a linha velha de derrubar a leitura
        # nova para sempre — apagá-la não é opção, e ela não some sozinha.
        prev = {"aberto_em": _lista_json(anterior["aberto_em"]),
                "ultimo_movimento": _movimento_json(anterior["ultimo_movimento"]),
                "documentos": _contagem(anterior["documentos"]),
                "movimentos": _contagem(anterior["movimentos"])}
    d = delta(prev, dados)
    # A FICHA ENTRA PELA TUPLA, não por uma segunda lista de nomes escrita aqui.
    # São 26 campos; escrevê-los à mão nas três pontas (colunas, `?` e valores)
    # é o tipo de lista que fica desalinhada num remendo de sexta e grava o
    # marcador na coluna do responsável sem erro nenhum.
    #
    # `dados.get` E NÃO `dados[...]`: quem lê no SEI ainda não preenche estes
    # campos (é outra tarefa), e ausência aqui é o caso NORMAL — não erro.
    ficha = [json.dumps(dados.get(c), ensure_ascii=False) if c in CAMPOS_JSON
             and dados.get(c) is not None else dados.get(c)
             for c in CAMPOS_FICHA]
    colunas = ",".join(CAMPOS_FICHA)
    marcas = ",".join("?" * len(CAMPOS_FICHA))
    cx.execute(f"""INSERT INTO acompanhado_leitura(usuario_id,instancia,protocolo,
                  lido_em,fonte,medido_em,aberto_em,aberto_em_fonte,
                  ultimo_movimento,documentos,movimentos,mudou,comparacao,
                  {colunas})
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,{marcas})""",
               [usuario_id, instancia, protocolo, agora(), fonte, medido_em,
                json.dumps(dados.get("aberto_em"), ensure_ascii=False),
                dados.get("aberto_em_fonte"),
                json.dumps(dados.get("ultimo_movimento"), ensure_ascii=False),
                dados.get("documentos"), dados.get("movimentos"),
                json.dumps(d, ensure_ascii=False) if d else None, comparacao]
               + ficha)
    # `tentativas=0`: CHEGOU LEITURA, de qualquer fonte. O contador existe para
    # medir entregas SEM resposta, e esta é a resposta. Zerar aqui cobre as duas
    # fontes de uma vez — a carteira (`reaproveitar`) e o SEI (`receber`) —
    # porque as duas passam por esta função.
    cx.execute("""UPDATE acompanhado SET estado=?, lido_em=?,
                  id_sei=COALESCE(?, id_sei), tentativas=0
                  WHERE usuario_id=? AND instancia=? AND protocolo=?""",
               (estado, agora(), id_sei, usuario_id, instancia, protocolo))
    return d


def reaproveitar(cx, usuario_id, instancia):
    """Responde da CARTEIRA o que a carteira já sabe.

    Devolve quantos ITENS DA LISTA respondeu — que é o mesmo que processos,
    exceto quando a lista guarda o mesmo número em duas formas (ver
    `por_digitos`, no fim desta função).

    A economia é a do poço, aplicada dentro de uma conta só — e aqui é integral,
    porque os quatro campos de que o módulo vive já estão guardados: as unidades
    da árvore em `processo_mesa`, e `ultimo_movimento`/`documentos`/`movimentos`
    em `processo`. Quem acompanha processo da própria carteira não gera nenhuma
    requisição ao SEI.

    A FRONTEIRA MORA AQUI. O recorte sai de `snapshots_de`, a MESMA função que o
    painel usa — nunca de um `SELECT` por protocolo em `processo`, que acharia a
    linha de qualquer unidade do banco, inclusive de mesa que esta conta não
    alcança. Sem isto o módulo seria a porta lateral que contorna a fronteira que
    o resto do sistema inteiro defende.
    """
    from app import snapshots_de, unidades_do

    # UMA LEITURA POR DIA, seja de qual fonte for. `lido_em` é atualizado por
    # `gravar_leitura`, então o que foi lido no SEI hoje não é REBAIXADO em
    # seguida para o dado da carteira, que pode ser de nove dias antes; e a
    # segunda passada do mesmo dia não grava leitura repetida de delta nulo, que
    # encheria a única série temporal do produto com linhas sem observação nova.
    pendentes = [r["protocolo"] for r in cx.execute(
        """SELECT protocolo FROM acompanhado
           WHERE usuario_id=? AND instancia=?
             AND (lido_em IS NULL OR substr(lido_em,1,10) <> substr(?,1,10))""",
        (usuario_id, instancia, agora()))]
    if not pendentes:
        return 0
    # DÍGITO -> as formas em que a pessoa colou aquele número. É por ele que a
    # lista casa com a carteira, e é LISTA de formas porque a chave primária de
    # `acompanhado` é o texto: linha anterior a esta regra, ou inserida fora de
    # `adicionar`, pode ter as duas formas do mesmo processo. Quando tem, as duas
    # são respondidas — ficar com uma deixaria a outra 'novo' para sempre.
    por_digitos = {}
    for p in pendentes:
        por_digitos.setdefault(digitos(p), []).append(p)
    unidades = unidades_do(usuario_id)
    if not unidades:
        return 0
    escolhidos = snapshots_de(cx, usuario_id, unidades)
    # SÓ OS SNAPSHOTS DESTA INSTALAÇÃO. `unidades_do` devolve as unidades das duas
    # instalações juntas, e `snapshots_de` responde por todas elas. Sem este
    # filtro, um protocolo que existe na coleta da FESF responderia o item que a
    # pessoa colou na lista da SESAB, e a leitura sairia gravada sob
    # `instancia='SEI-SESAB'` com as mesas da FESF dentro — o mesmo defeito que
    # `coleta.py`, `configuracao.py` e `ingestao.py` documentam ter carimbado dado
    # da FESF como SESAB, e o motivo de `acompanhado.instancia` ter nascido sem
    # DEFAULT. Não é furo de fronteira (o vínculo existe nas duas), é carimbo
    # falso — e a chave de `snapshots_de` já é o par (instalação, unidade): basta
    # não jogar a instalação fora.
    ids = [sid for (inst, _unidade), (sid, _dono) in escolhidos.items()
           if inst == instancia]
    if not ids:
        return 0
    marc_s = ",".join("?" * len(ids))
    marc_p = ",".join("?" * len(por_digitos))
    linhas = cx.execute(f"""
        SELECT p.protocolo, p.id_sei, p.ultimo_movimento, p.documentos, p.movimentos,
               p.medido_em, p.mesas_fonte, s.coletado_em,
               {", ".join(f"p.{c}" for c in _DE_PROCESSO)},
               {", ".join(f"t.{c}" for c in _DE_TEXTO)},
               (SELECT GROUP_CONCAT(m.mesa, char(31)) FROM processo_mesa m
                 WHERE m.snapshot_id=p.snapshot_id AND m.id_sei=p.id_sei) AS mesas
        FROM processo p JOIN snapshot s ON s.id=p.snapshot_id
        -- O TEXTO LIVRE ENTRA POR JOIN NOS MESMOS `snapshot_id`, nunca por uma
        -- consulta própria por protocolo. Um `SELECT ... FROM processo_texto
        -- WHERE id_sei=?` acharia o texto de QUALQUER unidade do banco,
        -- inclusive de mesa que esta conta não alcança — e seria a porta lateral
        -- que a docstring desta função promete não abrir, aberta pelo campo
        -- justamente mais sensível. Aqui o recorte é o mesmo `p.snapshot_id IN
        -- (...)`, que já saiu de `snapshots_de`; a junção é pela chave primária
        -- de `processo_texto`, e não alarga nada.
        --
        -- `relatorios.py` TIROU este JOIN com motivo medido (11,8 ms contra 3,6,
        -- e 137 KB de texto livre atravessando o processo à toa) — e o motivo
        -- não vale aqui: lá são 1.165 linhas por requisição e nenhuma tela lê o
        -- texto; aqui são as linhas dos <=100 protocolos da lista, e o texto É o
        -- produto do pedido (é ele que responde "qual é esse processo").
        LEFT JOIN processo_texto t
               ON t.snapshot_id=p.snapshot_id AND t.id_sei=p.id_sei
        WHERE p.snapshot_id IN ({marc_s})
          -- POR DÍGITOS nas duas pontas, não pelo texto. A carteira guarda a
          -- forma pontuada que o SEI imprime, e a lista guarda a forma que a
          -- pessoa colou; casar texto com texto deixava o número corrido
          -- eternamente no caminho caro do SEI por um dado que já estava aqui.
          -- `_SQL_DIGITOS` é o espelho de `digitos()`, e o comentário dele diz
          -- por que não há índice nisso.
          AND {_SQL_DIGITOS} IN ({marc_p})
        -- DA MEDIÇÃO MAIS FRESCA PARA A MAIS VELHA. O mesmo processo aparece em
        -- toda coleta de unidade onde ele está aberto, e é a MEDIÇÃO — não a hora
        -- da coleta — que diz qual dessas linhas descreve o processo hoje: 92,6%
        -- dos processos de uma coleta são servidos do poço, então lista nova com
        -- detalhe de dias atrás é o REGIME NORMAL, e é por isso que `medido_em`
        -- existe (ver a coluna em `banco.py`).
        --
        -- A régua de MEDIR é a mesma do painel e de `relatorios.carregar`
        -- (`medido_em or coletado_em`). O que difere é a ORDEM DE ESCOLHA entre
        -- linhas: lá é `s.coletado_em`, aqui é a medição, e a diferença é
        -- deliberada. Lá a ordem decide qual linha sobrevive à dedup entre as
        -- unidades de uma carteira coletada na mesma passada; aqui ela decide
        -- qual MEDIÇÃO responde por um processo que pode ter detalhe de 20/08
        -- sob coleta de 12/09.
        ORDER BY COALESCE(p.medido_em, s.coletado_em) DESC, s.id DESC""",
        ids + list(por_digitos)).fetchall()
    # UM MOMENTO, UM QUADRO. Tudo sai da MESMA linha — contagem, régua, mesas e
    # fonte. A escolhida é a mais fresca que TENHA lista de mesas; se nenhuma
    # tiver, a mais fresca, com `aberto_em` vazio.
    #
    # `processo_mesa` é a ÁRVORE INTEIRA por linha, NÃO o ângulo da mesa que
    # coletou: `ingestao.py` a preenche de `d["mesas"]`, que em
    # `automacao_sei.js` é `mesas, // onde esta aberto hoje` — a linha "Processo
    # aberto nas unidades: ..." do topo da árvore, com a máquina de estados do
    # andamento como reserva. `relatorios.py` já dizia isso por escrito.
    #
    # A versão anterior SOMAVA as mesas de todas as linhas, e fazia três danos:
    #
    #   1. importava bolor — mesa de 27/08 sob contagem e régua de 12/09,
    #      carimbada 'arvore' para unidade que a árvore fresca já não lista:
    #      retrato que não existiu em momento nenhum;
    #   2. calava o `saiu_de` ESTRUTURALMENTE — união só cresce, então enquanto o
    #      snapshot velho vivesse (nove dias úteis, no caso medido em 10/09/2026)
    #      o evento mais valioso do módulo nunca sairia: a tela diria "+2
    #      documentos" para um processo que saiu da unidade da pessoa;
    #   3. misturava lista medida errada com lista medida certa — a árvore bateu
    #      com a mesa em 1.278 de 1.278 casos observáveis, o andamento em 0.
    #
    # E NÃO se prefere 'arvore' sobre 'andamento' entre linhas diferentes: isso
    # juntaria a mesa de uma linha com a contagem de outra, que é o mesmo defeito
    # com outra roupa. Linha escolhida vinda do andamento => fonte 'andamento', e
    # a tela marca "não confirmado pela árvore" — é para isso que o campo existe.
    escolhida = {}
    for r in linhas:                     # já vêm da medição mais fresca
        # A CHAVE É O DÍGITO, não o texto: é ele que liga a linha da carteira
        # (pontuada, como o SEI imprime) ao item da lista (como a pessoa colou).
        chave = digitos(r["protocolo"])
        mesas = sorted(set((r["mesas"] or "").split(chr(31))) - {""})
        atual = escolhida.get(chave)
        # Fica com a primeira vista, que é a mais fresca; só troca quando ela não
        # trouxe mesa nenhuma e esta trouxe.
        if atual is None or (not atual[1] and mesas):
            escolhida[chave] = (r, mesas)
    feitos = 0
    for chave, (r, mesas) in escolhida.items():
        dados = {
            # LISTA, nunca None — e vazia quando a linha escolhida não listou
            # mesa alguma, que acontece de verdade: `processo_mesa` nasce da
            # linha "Processo aberto nas unidades" da árvore, e coleta cuja
            # árvore não parseou grava o processo sem uma única linha de mesa.
            # `listar()` devolve None tanto para JSON null quanto para item que
            # nunca foi lido, então `[]` é o único valor que a tela consegue
            # distinguir de "aguardando primeira leitura" — e vazio aqui
            # significa "a coleta não disse", nunca "não está aberto em lugar
            # nenhum".
            #
            # E É POR ISSO QUE CONTINUA SENDO `mesas`, e não `mesas or None`: o
            # conserto óbvio do "saiu de" falso (medido em 11/09/2026, mesmo
            # processo e mesma unidade em duas coletas) calaria também a tela, e
            # o item voltaria a parecer nunca lido. Quem emudece é `delta()`, que
            # não deriva saída de conjunto vazio — a afirmação e a exibição são
            # canais separados.
            "aberto_em": mesas,
            # `mesas_fonte` vem da coleta e pode valer 'andamento', que a medição
            # de 10/09/2026 mostrou errar em 100% dos 1.278 casos observáveis.
            # Não se relê por isso — seria uma requisição por dia para trocar
            # dado velho por dado novo do mesmo campo —, mas a tela marca como
            # não confirmado pela árvore, e para isso a fonte tem de chegar lá.
            "aberto_em_fonte": _texto(r["mesas_fonte"]) or "andamento",
            # PELO CONFERIDOR, como o envelope da estação — ver `_movimento_json`.
            # A carteira não é relator confiável por ser nossa: ela é o resultado
            # de um parse de HTML do SEI, e o tipo errado aqui só aparece na
            # SEGUNDA leitura, longe do envelope que o produziu.
            "ultimo_movimento": _movimento_json(r["ultimo_movimento"]),
            "documentos": _contagem(r["documentos"]),
            "movimentos": _contagem(r["movimentos"]),
        }
        # A FICHA SAI DA MESMA LINHA que deu as mesas, a contagem e a régua. É a
        # regra "um momento, um quadro" do comentário acima, e ela vale para o
        # marcador tanto quanto para as unidades: juntar o marcador de uma linha
        # com a contagem de outra produz um retrato que não existiu em momento
        # nenhum — e a tela o carimba com UMA data de medição.
        for campo in CAMPOS_FICHA:
            dados[campo] = (_lista_json(r[campo]) if campo in CAMPOS_JSON
                            else r[campo])
        # O PROTOCOLO DA LISTA, nunca o da carteira. A chave de `acompanhado` é a
        # forma que a pessoa colou; gravar a leitura sob a forma pontuada da
        # carteira faria a FK composta recusar — e com razão, porque não existe
        # leitura sem a linha da lista. São VÁRIAS formas só quando a lista já
        # tinha as duas (ver `por_digitos`); no caso normal, uma — e é por isso
        # que `feitos` conta ITEM DA LISTA respondido, não processo distinto.
        for protocolo in por_digitos.get(chave, ()):
            gravar_leitura(cx, usuario_id, instancia, protocolo, dados,
                           fonte="carteira",
                           # A DATA DA MEDIÇÃO, nunca `agora()`: em 10/09/2026 as
                           # 12 unidades estavam com coleta de nove dias úteis
                           # antes, e carimbar "lido hoje" sobre dado de 27/08 é
                           # mentir na procedência. `coletado_em` é a reserva
                           # porque `medido_em` é nulo em linha de coleta
                           # anterior à régua.
                           medido_em=r["medido_em"] or r["coletado_em"],
                           id_sei=r["id_sei"])
            feitos += 1
    return feitos


# ---------------------------------------------------------------- a estação
#
# O CAMINHO CARO, e o único que existe para processo fora das mesas. Daqui para
# baixo é a conversa com a estação: `pendentes` diz o que falta ler, `receber`
# grava o que ela leu. A estação PEGA o trabalho — o servidor não empurra —, que
# é o mesmo contrato de `/api/agente/busca` e o que permite a estação rodar atrás
# do firewall do órgão.
#
# A ESTAÇÃO É RELATOR NÃO CONFIÁVEL, e não por desconfiança dela: ela relata o
# que LEU numa página do SEI que muda de versão, com iframe que às vezes não
# carrega e árvore que às vezes não parseia. Envelope truncado, campo ausente e
# campo com o tipo errado são o regime normal, não o ataque — e nenhum deles pode
# virar afirmação na tela de quem confia no número.


# Quantas entregas sem resposta antes de o item descansar até amanhã. Três, e não
# uma: rede intermitente e Chromium que não subiu naquela batida são falhas
# passageiras, e desistir na primeira faria o módulo perder o dia por um soluço.
# Acima de três, o que há é falha sistemática — e aí insistir 31 vezes mais só
# multiplica requisição inválida contra o SEI do órgão.
TENTATIVAS_ATE_DESCANSAR = 3


# A FILA, ESCRITA UMA VEZ.
#
# `pendentes` ESCREVE: cada item que ela devolve sai com `tentativas`
# incrementado. Logo, quem só quer saber SE há trabalho — o motor do VPS, antes
# de gastar um Chromium de 450 MB — não pode chamá-la, e precisa da MESMA
# condição. Duas cópias divergiriam no primeiro ajuste, e a divergência seria
# silenciosa nos dois sentidos: o motor acordando para fila vazia, ou dormindo
# com fila cheia.
#
# As duas metades da condição:
#   * UMA LEITURA POR DIA — a mesma guarda que `reaproveitar` aplica, e pelo
#     mesmo motivo: sem ela o mesmo processo seria relido a cada ciclo;
#   * O RECUO — três entregas sem resposta HOJE e o item sai da fila até amanhã.
#     A comparação de DATA é o que torna isso recuo e não desistência:
#     `tentativas` alto de ontem não barra nada.
_FILA_ONDE = """FROM acompanhado
           WHERE usuario_id=? AND instancia=?
             AND (lido_em IS NULL OR substr(lido_em,1,10) <> substr(?,1,10))
             AND NOT (tentativas >= ?
                      AND substr(COALESCE(tentativa_em,''),1,10) = substr(?,1,10))"""


def _fila_params(usuario_id, instancia, hoje):
    """Os cinco parâmetros de `_FILA_ONDE`, na ordem. Tupla para somar com o
    resto sem quem chama ter de saber quantos são."""
    return (usuario_id, instancia, hoje, TENTATIVAS_ATE_DESCANSAR, hoje)


def quantos_pendentes(cx, usuario_id, instancia, so_novos=False):
    """Quantos itens a fila entregaria agora. NÃO ESCREVE NADA.

    Existe para o motor do servidor (`acompanhamento_servidor.py`) decidir se
    vale subir um Chromium, sem pagar o preço de perguntar com `pendentes` —
    que incrementaria o contador de entregas de itens que talvez nem sejam
    lidos.

    PODE CONTAR PARA MAIS, e é de propósito. Ao contrário de `pendentes`, não
    chama `reaproveitar`: itens que a coleta do dia responderia de graça ainda
    aparecem aqui. Quem chama trata isso na ordem certa — pega a vaga de
    memória, chama `pendentes` (que reaproveita), e se sobrar lista vazia
    devolve a vaga sem ter aberto navegador nenhum. Reaproveitar aqui tornaria
    esta função uma escritora, e ela deixaria de servir para a pergunta que
    motivou a sua existência.

    `so_novos` responde ao gatilho "ao adicionar": item `novo` é o que ninguém
    leu nem uma vez, e ele não espera a coleta do dia.
    """
    return cx.execute(
        "SELECT COUNT(*) " + _FILA_ONDE + (" AND estado='novo'" if so_novos else ""),
        _fila_params(usuario_id, instancia, agora())).fetchone()[0]


def devolver_tentativas(cx, usuario_id, instancia, protocolos):
    """Desfaz a cobrança de uma entrega que NÃO CHEGOU AO SEI. Devolve quantas.

    `pendentes` cobra a tentativa na ENTREGA — de propósito, para cobrir a
    estação que morre sem relatar nada. Mas no servidor sabe-se quando a volta
    falhou antes de ler um processo sequer (sem credencial, navegador que não
    subiu, coletor morto): medido em 15/09/2026, três voltas assim gastavam as
    três tentativas do dia em seis minutos e a lista INTEIRA do par descansava
    até a meia-noite, por uma falha que não era de processo nenhum.

    Só devolve para o que continua sem leitura hoje — o que foi lido não deve
    nada — e nunca abaixo de zero.
    """
    if not protocolos:
        return 0
    hoje = agora()
    marc = ",".join("?" * len(protocolos))
    return cx.execute(
        f"""UPDATE acompanhado SET tentativas = MAX(COALESCE(tentativas,0) - 1, 0)
            WHERE usuario_id=? AND instancia=? AND protocolo IN ({marc})
              AND (lido_em IS NULL OR substr(lido_em,1,10) <> substr(?,1,10))""",
        [usuario_id, instancia] + list(protocolos) + [hoje]).rowcount


def descansando(cx, usuario_id, instancia, na_fila=()):
    """Os itens que o servidor parou de oferecer HOJE, e quantas vezes falharam.

    Existe para o recuo não ser silencioso. Item que some da fila sem ninguém
    dizer por quê é indistinguível de item que foi lido — e o custo do engano é
    alguém olhando a tela achar que o processo está em dia.

    `na_fila` É O QUE ESTA MESMA RESPOSTA ESTÁ ENTREGANDO, e sai daqui. Sem ele,
    o mesmo protocolo saía nas duas listas: `pendentes` INCREMENTA o contador
    antes de esta função LER, então na entrega em que o item completa a terceira
    tentativa a estação recebia "leia este" e "este descansa até amanhã" sobre o
    mesmo número. Recuo é o que ficou FORA da fila; o que está sendo entregue
    agora não descansa, por definição.

    Filtrar aqui, e não na rota, porque a regra é do módulo — `app.py` só
    transporta. E em Python, não em SQL: a lista tem no máximo `TETO` itens, e
    um `NOT IN` de cem marcadores custaria mais para ler do que para rodar.
    """
    fila = set(na_fila or ())
    return [{"protocolo": r["protocolo"], "tentativas": r["tentativas"]}
            for r in cx.execute(
                """SELECT protocolo, tentativas FROM acompanhado
                   WHERE usuario_id=? AND instancia=? AND tentativas>=?
                     AND substr(COALESCE(tentativa_em,''),1,10)=substr(?,1,10)
                     AND (lido_em IS NULL OR substr(lido_em,1,10)<>substr(?,1,10))
                   ORDER BY tentativas DESC, protocolo""",
                (usuario_id, instancia, TENTATIVAS_ATE_DESCANSAR, agora(), agora()))
            if r["protocolo"] not in fila]


def pendentes(cx, usuario_id, instancia):
    """O que a estação precisa ler no SEI: os protocolos, e só eles.

    ESCREVE: cada item devolvido sai daqui com `tentativas` incrementado, e o
    contador só é zerado quando uma leitura chega (`gravar_leitura`, e a recusa
    em `receber`). Três entregas sem resposta e o item descansa até amanhã.

    O CONTADOR É DE ENTREGA, não de falha relatada. A estação que morre com o
    Chromium aberto depois de ler 100 processos não relata falha nenhuma — e é
    exatamente esse o caso que custa 500 requisições por ciclo. Contar o que foi
    ENTREGUE cobre também o caso em que ela relata, e não depende de campo novo
    vindo de fora.

    Chama `reaproveitar` primeiro de propósito. Sem isso a estação leria no SEI
    processo que a coleta já trouxe de graça — e a economia do desenho existiria
    só no papel: cinco requisições por processo por dia para reler o que está no
    banco.

    SÓ O NÚMERO SOBE. A estação vai procurar cada um no SEI, então precisa do
    número e da instalação (que quem chama já sabe, porque foi ela quem escolheu).
    Não precisa da NOTA — texto que a pessoa escreveu, que pode citar nome de
    gente e não tem o que fazer numa estação —, nem do tamanho da lista, nem do
    estado de cada item. Campo que sobe é campo que a estação passa a poder usar,
    e este envelope atravessa a rede do órgão.

    O `LIMIT` é ORÇAMENTO DE REQUISIÇÃO, não fronteira: o teto já limita a lista,
    mas ele é lido uma vez por chamada e sob concorrência passa (medido: 101), e
    linha inserida fora de `adicionar` não passa por ele. Ver `TETO`, no topo.
    """
    reaproveitar(cx, usuario_id, instancia)
    hoje = agora()
    lista = [r["protocolo"] for r in cx.execute(
        "SELECT protocolo " + _FILA_ONDE
        # O 'novo' na frente para a primeira leitura de um item recém colado não
        # ficar atrás de 99 releituras quando o orçamento apertar.
        + " ORDER BY estado='novo' DESC, adicionado_em LIMIT ?",
        _fila_params(usuario_id, instancia, hoje) + (TETO,))]
    if lista:
        # CONTA HOJE, NÃO DESDE SEMPRE. Entrega de ontem que falhou não soma com a
        # de hoje: o `CASE` reinicia a contagem quando o dia vira, senão um item
        # com três falhas na terça ganharia UMA tentativa por dia dali em diante,
        # que é um recuo que ninguém pediu e que é difícil de explicar olhando a
        # tabela.
        marc = ",".join("?" * len(lista))
        cx.execute(f"""UPDATE acompanhado
                       SET tentativas = CASE
                             WHEN substr(COALESCE(tentativa_em,''),1,10)=substr(?,1,10)
                             THEN tentativas + 1 ELSE 1 END,
                           tentativa_em = ?
                       WHERE usuario_id=? AND instancia=? AND protocolo IN ({marc})""",
                   [hoje, hoje, usuario_id, instancia] + lista)
    return lista


# O que a estação relata quando o SEI recusou ou não achou. Traduzido AQUI, e não
# na estação: a estação relata o que viu; o significado é do servidor.
#
# Estado fora desta lista é RECUSADO, nunca rebaixado para 'lido'. Traduzir o
# desconhecido para o caso bom carimbaria "lido no SEI" sobre uma ficha vazia que
# a estação nunca disse ter lido — e a tela passaria a afirmar que o processo não
# está aberto em lugar nenhum. É a mesma doutrina de `delta()`: não afirmar onde
# não houve observação.
_ESTADOS_ACEITOS = ("lido", "sem_acesso", "nao_encontrado")


def _texto(v):
    """Texto não vazio, ou None.

    Dicionário e lista não são texto — e o driver do SQLite LEVANTA ao receber um
    deles num parâmetro, o que numa rota é 500. A estação não sabe o que fazer com
    500: ela volta a tentar o mesmo envelope, para sempre.
    """
    v = v.strip() if isinstance(v, str) else None
    return v or None


def _contagem(v):
    """Inteiro de verdade, ou None.

    `"3"` NÃO vira 3. Contagem em texto não estoura na hora: estoura na leitura
    seguinte, quando `delta()` faz `b - a` entre texto e número — e o rastro
    aponta para o delta, não para o envelope que o produziu dias antes.

    `bool` fora, apesar de ser `int` em Python: `True` documentos não é uma
    contagem, é um campo preenchido errado.
    """
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _lista_texto(v):
    """Lista de textos, ou None. A mecânica que `_unidades` e a ficha dividem.

    Lista VAZIA passa e é DIFERENTE de None. `[]` é "a tela existia e não havia
    assunto nenhum"; None é "não observado" — e para `assuntos`/`interessados`
    isso acontece de verdade, porque a tela Consultar/Alterar pode não existir
    para aquele processo (o coletor já distingue os dois na coleta, com
    `alterar_disponivel`). Sem os dois valores, "processo sem interessado" e
    "não deu para olhar" ficariam idênticos na ficha.
    """
    if not isinstance(v, list) or not all(isinstance(u, str) for u in v):
        return None
    return v


def _unidades(v):
    """Lista de unidades, ou None quando não veio em forma de lista de unidades.

    O CAMPO MAIS PERIGOSO DO ENVELOPE. `delta()` faz `set(aberto_em)`, e sobre
    TEXTO isso é um conjunto de LETRAS: `"SESAB/X"` viraria seis "unidades"
    chamadas 'S', 'E', 'A', 'B', '/' e 'X', e a tela anunciaria o processo
    entrando em todas elas. Com elemento que não é texto, o `sorted` do delta
    seguinte estoura, e a tela renderiza `u.split('/')` sobre um dicionário.

    Lista VAZIA passa e é diferente de None: `[]` é "li e a árvore não listou
    unidade nenhuma" — o que acontece de verdade quando a árvore não parseia — e
    None é "não observado". A tela distingue as duas, e é por isso que o vazio
    chega inteiro até a coluna.

    O QUE O VAZIO NÃO FAZ é virar afirmação: `delta()` não deriva `saiu_de` nem
    `entrou_em` de conjunto vazio, porque "a leitura não trouxe unidade nenhuma"
    não é "o processo não está aberto em lugar nenhum". São dois canais, e só um
    deles emudece.
    """
    return _lista_texto(v)


def _quadro_relatado(leitura):
    """O que a estação diz ter lido, campo a campo e com o tipo conferido.

    LISTA EXPLÍCITA, não espalhamento do objeto — a mesma escolha que a função
    `acompanhar()` da estação faz do outro lado, e pela razão simétrica: lá para
    não mandar os cinco campos de custódia derivados da mesa errada, aqui para não
    gravar o que a estação não tinha por que mandar.

    Campo deformado vira None, e a leitura é gravada com o que sobrou. Recusar a
    leitura inteira por causa de um campo custaria a observação toda — e ausência,
    aqui, já tem significado próprio e honesto: não observado.

    A FICHA DO PROCESSO ENTRA; A FICHA DA MESA, NÃO — e a segunda metade é o
    ponto. Cada campo abaixo tem uma linha e um conferidor de tipo, e os
    `CAMPOS_DA_MESA` simplesmente NÃO ESTÃO AQUI. Não por esquecimento: eles saem
    da LINHA da tabela de Controle de Processos daquela mesa (`linha5` por
    `aria-label`, `linha4` por tooltip), e para processo que não está em mesa
    nenhuma da conta essa linha não existe. O que a estação mandasse com esses
    nomes seria o dado da mesa em que ELA está parada — em particular os cinco de
    custódia, que `derivar()` calcula por `camposDaMesa(mov, UNIDADE)`. Gravar
    isso seria gravar o dado de outra mesa com o nome deste processo.
    `gravar_leitura` faz `dados.get(c)` sobre `CAMPOS_FICHA`, então campo que não
    está nesta lista vira NULL na coluna — e a tela diz "não existe fora da mesa"
    em vez de imprimir um marcador em branco.

    NÃO VALE espalhar `leitura` no dicionário, nem montar isto por compreensão
    sobre `CAMPOS_FICHA`: as duas formas deixariam a estação escrever em qualquer
    coluna da ficha, e é justamente essa porta que a lista escrita à mão fecha.

    `especificacao` e `interessados` são TEXTO LIVRE, que pode citar paciente, e
    estão aqui por decisão explícita do usuário em 11/09/2026 — registrada na
    seção 11.2 do plano e em `SPECS.md` §5-quindecies, com data e autor. O alcance
    é só deste módulo: a exclusão que a busca avançada faz continua valendo.
    """
    mov = leitura.get("ultimo_movimento")
    return {
        "aberto_em": _unidades(leitura.get("aberto_em")),
        "aberto_em_fonte": _texto(leitura.get("aberto_em_fonte")),
        "ultimo_movimento": mov if isinstance(mov, dict) else None,
        "documentos": _contagem(leitura.get("documentos")),
        "movimentos": _contagem(leitura.get("movimentos")),
        # --- do PROCESSO: vale dentro e fora da mesa ---
        "tipo_processo": _texto(leitura.get("tipo_processo")),
        "autuacao": _texto(leitura.get("autuacao")),
        "gerador_unidade": _texto(leitura.get("gerador_unidade")),
        "gerador_usuario": _texto(leitura.get("gerador_usuario")),
        "nivel_acesso": _texto(leitura.get("nivel_acesso")),
        "hipotese_legal": _texto(leitura.get("hipotese_legal")),
        "assuntos": _lista_texto(leitura.get("assuntos")),
        "anexados": _lista_texto(leitura.get("anexados")),
        "emails_enviados": _contagem(leitura.get("emails_enviados")),
        "assinatura_externa": _contagem(leitura.get("assinatura_externa")),
        # --- texto livre, autorizado em 11/09/2026 (ver a docstring) ---
        "especificacao": _texto(leitura.get("especificacao")),
        "interessados": _lista_texto(leitura.get("interessados")),
    }


def receber(cx, usuario_id, instancia, envelope):
    """Leituras vindas da estação -> (gravadas, ignoradas).

    O `usuario_id` vem do DONO DO AGENTE autenticado, nunca do envelope: aceitar
    o dono de dentro do corpo deixaria um agente escrever na lista de outra conta.
    Esta função recebe os dois e obedece — a fronteira é a rota, como na tela.

    A `instancia` vem pelo MESMO caminho, e por um motivo próprio: a pessoa pode
    seguir o mesmo número nas duas instalações, e são duas linhas com histórico
    próprio. Se o envelope pudesse escolher, a leitura feita na FESF entraria na
    linha da SESAB — o carimbo falso que `acompanhado.instancia` nasceu sem
    DEFAULT para evitar, e que `coleta.py`, `configuracao.py` e `ingestao.py` cada
    um documenta ter cometido uma vez.

    O envelope AINDA PODE dizer a instalação, e aí ela é CONFERIDA, não obedecida:
    a estação leu onde o `pendentes` mandou, e discordância significa que a
    configuração da pessoa mudou entre o pedido e a resposta. Aí o envelope inteiro
    é recusado com `ValueError` — gravar metade dele seria carimbar leitura de uma
    instalação como sendo da outra, que é exatamente o que a conferência evita.

    AS DUAS CONTAGENS VOLTAM SEPARADAS. Só `gravadas` deixava a estação que
    relatou dez e viu zero sem saber se a lista chegou vazia ou se tudo foi
    recusado — é o mesmo motivo de `adicionar` devolver os recusados em vez de
    descartá-los em silêncio.
    """
    if not isinstance(envelope, dict):
        # Corpo que não é envelope: lista, texto, número, ou nada — `get_json`
        # devolve o que veio. `envelope.get` sobre isso é AttributeError, e numa
        # rota AttributeError é 500.
        envelope = {}
    dita = envelope.get("instancia")
    if dita and dita != instancia:
        raise ValueError(
            f"a estação relata leitura de {dita} e o dono deste agente lê em "
            f"{instancia}: envelope recusado para não carimbar uma instalação "
            "como sendo a outra")
    leituras = envelope.get("leituras")
    if not isinstance(leituras, list):
        leituras = []
    gravadas, ignoradas, vistos = 0, 0, set()
    for leitura in leituras:
        if not isinstance(leitura, dict):
            ignoradas += 1
            continue
        bruto = leitura.get("protocolo")
        p = normalizar(bruto) if isinstance(bruto, str) else None
        # O MESMO PROTOCOLO DUAS VEZES no mesmo envelope grava duas linhas na
        # única série temporal do produto, e a segunda compara contra a primeira,
        # inserida no mesmo instante: delta medido entre a leitura e ela mesma.
        if not p or p in vistos:
            ignoradas += 1
            continue
        vistos.add(p)
        # SÓ O QUE ESTÁ NA LISTA DESTA CONTA, e casado pelo TEXTO do protocolo —
        # não pelos dígitos, como faz `reaproveitar`. Lá a régua de dígitos existe
        # porque os dois lados foram escritos por gente diferente (a pessoa colou
        # de um jeito, o SEI imprime de outro); aqui a estação devolve o protocolo
        # que NÓS mandamos em `pendentes`, que é a própria chave de `acompanhado`.
        # Casar por dígitos alargaria o alvo da escrita com base em texto do
        # cliente, e um relato só passaria a poder escrever em DUAS linhas quando
        # a lista tem as duas formas do mesmo número. Forma que não bate não
        # escreve nada — e volta contada, para a divergência não ser silenciosa.
        seguido = cx.execute("""SELECT 1 FROM acompanhado
                                WHERE usuario_id=? AND instancia=? AND protocolo=?""",
                             (usuario_id, instancia, p)).fetchone()
        if not seguido:
            ignoradas += 1
            continue
        estado = leitura.get("estado") or "lido"
        if estado not in _ESTADOS_ACEITOS:
            ignoradas += 1
            continue
        if estado != "lido":
            # RECUSA NÃO É OBSERVAÇÃO, e por isso não entra na série. Uma linha
            # vazia em `acompanhado_leitura` diria "neste dia o processo não
            # estava aberto em lugar nenhum e tinha zero documento" — e, pior,
            # passaria a ser a ÚLTIMA leitura, apagando da tela o que já se sabia.
            # O estado no item é o que a tela mostra, e `texto_da_procedencia`
            # cala nele de propósito.
            # `tentativas=0` TAMBÉM AQUI: recusa do SEI não é falha técnica. A
            # estação chegou ao processo e o SEI respondeu — "não é para você" ou
            # "não existe" são respostas. O contador mede entrega sem resposta, e
            # deixá-lo subir aqui faria o item descansar por ter sido lido.
            cx.execute("""UPDATE acompanhado SET estado=?, lido_em=?, tentativas=0
                          WHERE usuario_id=? AND instancia=? AND protocolo=?""",
                       (estado, agora(), usuario_id, instancia, p))
            gravadas += 1
            continue
        gravar_leitura(cx, usuario_id, instancia, p, _quadro_relatado(leitura),
                       fonte="sei",
                       # AGORA, explicitamente: no caminho do SEI a medição É o
                       # instante da leitura, ao contrário do dado da carteira,
                       # que pode ser de nove dias antes. `gravar_leitura` exige o
                       # campo justamente para este chamador não o esquecer.
                       medido_em=agora(), id_sei=_texto(leitura.get("id_sei")))
        gravadas += 1
    return gravadas, ignoradas
