# -*- coding: utf-8 -*-
"""
As instâncias do SEI, em UMA lista.

POR QUE ISTO EXISTE
-------------------
O sistema nasceu falando com uma instalação do SEI (a SESAB) e a instalação
estava escrita nas entranhas: a URL de login no coletor, o número do órgão no
`select`, o domínio na conferência de sessão, os ids do formulário no parser.
Habilitar a FESF não é acrescentar uma opção numa tela — é tirar do código tudo
o que só vale para uma instalação e transformar em dado.

A regra é a mesma de `portas.py`: UMA lista, N leitores. Duas listas divergem —
`configuracao.SISTEMAS` já descrevia as instâncias para a tela de configuração
enquanto o coletor tinha a URL da SESAB fixa no meio do arquivo, e as duas não
tinham como discordar porque nunca se falavam.

DUAS DISPONIBILIDADES, NÃO UMA
------------------------------
`disponivel_busca` e `disponivel_coleta` são separadas de propósito. São coisas
diferentes e chegam em datas diferentes:

  * a BUSCA usa a tela Pesquisa, que existe nas duas versões e cujos campos o
    motor encontra por lista de ids com alternativas;
  * a COLETA usa a visualização Detalhada do Controle de Processos
    (`hdnTipoVisualizacao='D'`, `#tblProcessosDetalhado`, tipo e especificação
    lidos do `aria-label`), que é do SEI 5. No SEI 4.0 a troca de visualização
    **falha em silêncio** — não dá erro, devolve a tela antiga —, e ninguém
    escreveu o parser da listagem do 4.0.

Uma flag só obrigaria a escolher entre mentir sobre a busca ou esconder o que
funciona.

OS IDS DO FORMULÁRIO SÃO LISTA, NÃO STRING
------------------------------------------
Cada campo tem VÁRIOS ids candidatos, tentados em ordem. Isso não é folclore
defensivo: é o que faz o mesmo motor atravessar o SEI 4.0 e o 5.0.4 sem um `if`
de versão espalhado pelo parser. O sistema irmão desta casa
(`sei_sistema/sei_extractor.py`) chegou a essa forma por tentativa e erro contra
o SEI de verdade, e é dela que vêm os nomes marcados 4.0 abaixo.

O QUE ESTÁ MEDIDO E O QUE NÃO ESTÁ
----------------------------------
Os ids marcados `# 4.0` foram exercitados contra a FESF pelo sistema irmão. Os
marcados `# 5.x` são a mesma família de nomes com o sufixo `Pesquisa`, que é o
padrão da versão — e NÃO foram exercitados contra a tela de Pesquisa da SESAB.
Enquanto não forem, `SEI-SESAB.busca_ids_medidos` fica falso e a tela diz isso a
quem for usar. Prometer campo que talvez não exista é pior que dizer que não se
sabe.
"""

# --------------------------------------------------------------------- campos
# Ordem importa: o motor tenta os ids na sequência e usa o primeiro que existir.
# Um campo que não casa com nada NÃO é preenchido em silêncio — vira recusa
# declarada no resultado, porque filtro que não pegou muda o universo da resposta
# sem mudar uma linha da tela.
CAMPOS_BUSCA = {
    # modo: só Processos por enquanto. O modo Documentos muda o universo do
    # resultado (documento, não processo) e exigiria outro parser de linha.
    "modo_processos": ["optProcessos",                       # 4.0 e 5.x
                       'input[name="rdoPesquisarEm"][value="P"]',
                       'input[name="rdoPesquisar"][value="P"]'],
    "tramitacao_unidade": ["chkSinTramitacao",               # 4.0
                           "chkSinTramitacaoUnidade"],
    "tipo_processo": ["selTipoProcedimentoPesquisa",         # 5.x
                      "selTipoProcedimento"],                # 4.0
    "especificacao": ["txtDescricaoPesquisa", "txtDescricao"],
    "contato": ["txtContato", "txtContatoPesquisa"],
    "assunto": ["txtAssunto", "txtAssuntoPesquisa"],
    "observacao": ["txtObservacaoPesquisa", "txtObservacao"],
    "numero_sei": ["txtProtocoloPesquisa", "txtProtocolo"],
    # Data é o ÚNICO filtro que limita o tamanho do resultado na origem. Sem ele,
    # "com tramitação na unidade" + campos vazios é uma varredura da mesa inteira
    # disparada por um clique — foi o que aconteceu no sistema irmão (718
    # processos, 72 páginas, 226 s numa busca sem critério nenhum).
    "data_de": ["txtDataInicio"],
    "data_ate": ["txtDataFim"],
    "tipo_data": ["selData"],
    "enviar": ["sbmPesquisar"],
}

# O que a data significa. `I` é quando o processo entrou no SEI; `G` é a data do
# próprio processo, que pode ser anterior.
TIPOS_DATA = {"I": "data de inclusão no SEI", "G": "data do processo"}


INSTANCIAS = {
    "SEI-SESAB": {
        "nome": "SEI · SESAB",
        "curto": "SEI da Bahia, órgão SESAB",
        "descricao": "Sistema Eletrônico de Informações do Governo da Bahia. "
                     "É onde estão os processos das mesas da SESAB.",
        "login_url": "https://sip.seibahia.ba.gov.br/login.php"
                     "?sigla_orgao_sistema=GOVBA&sigla_sistema=SEI",
        "host_sip": "sip.seibahia.ba.gov.br",
        "host_sei": "seibahia.ba.gov.br",
        "raiz": "https://seibahia.ba.gov.br/",
        # O login da SESAB tem TRÊS campos: usuário, senha e ÓRGÃO. O `23` é a
        # SESAB dentro das 77 opções do `#selOrgao` — é a instalação do governo
        # do estado, com vários órgãos dentro.
        "campo_orgao": "selOrgao",
        "valor_orgao": "23",
        "versao": "5.0.4",
        "exemplo_login": "nome.sobrenome@saude.ba.gov.br",
        "prefixo_unidade": "SESAB/",
        "disponivel_coleta": True,
        "disponivel_busca": True,
        # Os ids da família 5.x não foram exercitados contra a tela de Pesquisa
        # desta instância. A busca roda com a lista de alternativas e DECLARA o
        # que não casou.
        "busca_ids_medidos": False,
        "campos_busca": CAMPOS_BUSCA,
    },
    "SEI-FESF": {
        "nome": "SEI · FESF-SUS",
        "curto": "instância da Fundação Estatal Saúde da Família",
        "descricao": "SEI 4.0 da FESF-SUS. Instalação própria, de um órgão só — "
                     "o login não pede órgão.",
        "login_url": "https://sip.fesfsus.ba.gov.br/login.php"
                     "?sigla_orgao_sistema=FESF&sigla_sistema=SEI",
        "host_sip": "sip.fesfsus.ba.gov.br",
        "host_sei": "sei.fesfsus.ba.gov.br",
        "raiz": "https://sei.fesfsus.ba.gov.br/",
        # Instalação de órgão único: não há seletor de órgão no login.
        "campo_orgao": None,
        "valor_orgao": None,
        "versao": "4.0.x",
        "exemplo_login": "nome.sobrenome",
        "prefixo_unidade": "FESF/",
        # A COLETA continua indisponível, e o motivo é concreto: ela depende da
        # visualização Detalhada (`hdnTipoVisualizacao='D'`), que no SEI 4.0 não
        # dá erro — devolve a tela antiga. Habilitar sem um parser da listagem
        # do 4.0 produziria carteira vazia com cara de carteira vazia de verdade.
        "disponivel_coleta": False,
        "motivo_sem_coleta": "a coleta usa a visualização Detalhada do Controle "
                             "de Processos, que é do SEI 5. No 4.0 a troca de "
                             "visualização falha em silêncio, e o parser da "
                             "listagem do 4.0 ainda não existe.",
        # A BUSCA usa a tela Pesquisa, cujos ids foram exercitados contra esta
        # instância pelo sistema irmão desta casa.
        "disponivel_busca": True,
        "busca_ids_medidos": True,
        "campos_busca": CAMPOS_BUSCA,
    },
}

PADRAO = "SEI-SESAB"


def perfil(instancia):
    """O perfil, ou KeyError com o nome errado à mostra.

    Sem default de propósito: uma instância desconhecida virando SESAB em
    silêncio é como o dado de um órgão entra no outro.
    """
    if instancia not in INSTANCIAS:
        raise KeyError(f"instância desconhecida: {instancia!r} "
                       f"(conhecidas: {', '.join(sorted(INSTANCIAS))})")
    return INSTANCIAS[instancia]


def existe(instancia):
    return instancia in INSTANCIAS


def para_busca():
    """As instâncias em que a busca pode rodar hoje."""
    return sorted(k for k, v in INSTANCIAS.items() if v["disponivel_busca"])


def para_coleta():
    return sorted(k for k, v in INSTANCIAS.items() if v["disponivel_coleta"])


def envelope_do_coletor(instancia):
    """O que o coletor precisa saber para falar com esta instalação.

    É o único lugar que monta esse dicionário. O coletor recebe isto por stdin,
    junto da credencial, e deixa de ter URL nenhuma escrita nele.
    """
    p = perfil(instancia)
    return {
        "instancia": instancia,
        "login_url": p["login_url"],
        "host_sip": p["host_sip"],
        "host_sei": p["host_sei"],
        "raiz": p["raiz"],
        "campo_orgao": p["campo_orgao"],
        "valor_orgao": p["valor_orgao"],
        "versao": p["versao"],
        "campos_busca": p["campos_busca"],
    }
