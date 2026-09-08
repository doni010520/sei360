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

A FORMA DO LOGIN E A FORMA DA SIGLA TAMBÉM SÃO DADO
---------------------------------------------------
As duas estavam escritas no meio de `app.py`: a validação exigia `@` no login
(`app.py:1070`) porque a única instalação conhecida era a SESAB, e o login da
FESF é `nome.sobrenome`. Uma pessoa da FESF não conseguia passar do passo 2 do
assistente, com uma mensagem que mandava corrigir um login que estava certo.
O mesmo vale para a sigla da unidade: `FESF/…` e `SESAB/…` dizem de qual
instalação a unidade é, e essa é a única fonte que existe antes do primeiro
snapshot.
"""
import re

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
        # O rótulo curto é o que cabe numa linha do painel ao lado da sigla da
        # unidade. `nome` e `curto` são frases; aqui é a etiqueta.
        "rotulo": "SESAB",
        # O login desta instalação é o e-mail institucional.
        "login_regex": r"[^@\s]+@[^@\s]+\.[^@\s]+",
        "login_dica": "Informe o e-mail institucional completo com o qual você "
                      "entra no SEI.",
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
        "rotulo": "FESF",
        # Instalação de órgão único: o login NÃO é e-mail. Exigir `@` aqui — como
        # `app.py` fazia para todo mundo — recusava o login correto com uma
        # mensagem que mandava a pessoa consertar o que não estava quebrado.
        # `nome.sobrenome` E TAMBÉM o login de uma palavra só (`lucaskaram`): a
        # FESF aceita os dois, e a primeira versão desta regra exigia o ponto —
        # recusaria o login real do dono da instalação na porta do passo 2
        # (07/09/2026). O que a regra barra é o que quebra o login: `@`, espaço,
        # maiúscula.
        "login_regex": r"[a-z0-9]+(?:[.\-][a-z0-9]+)*",
        "login_dica": "Nesta instalação o login é nome.sobrenome — sem @, sem "
                      "espaço e em minúsculas.",
        "prefixo_unidade": "FESF/",
        # A COLETA foi ligada em 08/09/2026, depois de uma amostra real (não
        # simulada) contra FESF/DIGAS/HECC/GAF: login, descoberta de 10 mesas
        # e leitura de 12 processos, com id/protocolo/tipo/especificação 100%
        # preenchidos (`coleta.py coletar <uid> SEI-FESF --amostra <mesa>`).
        # Antes disso o parser da listagem do 4.0 nunca tinha sido exercitado
        # contra o HTML real — só contra uma fixture sintética
        # (`_teste_parser40.js`), que essa mesma amostra corrigiu num ponto
        # (marcador: o SEI real manda o nome no SEGUNDO argumento do tooltip,
        # não no primeiro — ver comentário em `automacao_sei.js`).
        "disponivel_coleta": True,
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


def escolhivel(instancia):
    """Dá para escolher esta instalação no assistente?

    BUSCA **OU** COLETA, e não só coleta. O passo 1 lia `disponivel_coleta` e
    recusava a FESF (`app.py:1058`), embora a busca já rodasse nela — quem tem
    vínculo só na FESF não passava da primeira tela de um sistema que já sabia
    atendê-la. Escolher a instalação é dizer ONDE se trabalha; o que cada uma
    oferece hoje a tela mostra ao lado, instância por instância.
    """
    p = INSTANCIAS.get(instancia)
    return bool(p and (p["disponivel_busca"] or p["disponivel_coleta"]))


def rotulo(instancia):
    """Etiqueta curta ("SESAB", "FESF"). Instância desconhecida devolve ela mesma."""
    p = INSTANCIAS.get(instancia)
    return p["rotulo"] if p else (instancia or "")


def login_valido(instancia, login):
    """(ok, dica) — a forma do login DESTA instalação.

    Só a forma: conferir se a conta existe exigiria tentar autenticar, e é
    exatamente isso que o botão "Testar acesso" faz, de propósito.
    """
    login = (login or "").strip()
    if not login:
        return False, "Informe o login com o qual você entra no SEI."
    if instancia not in INSTANCIAS:
        # Instalação que não conhecemos: não há regra para aplicar, e inventar
        # uma recusaria login correto. Aceita a forma mínima e diz o que fez.
        return bool(re.fullmatch(r"\S+", login)), "O login não pode ter espaço."
    p = INSTANCIAS[instancia]
    if re.fullmatch(p["login_regex"], login):
        return True, ""
    return False, p["login_dica"]


# A FORMA DA SIGLA. `ORGAO/…`, maiúsculas, sem espaço — é como o SEI escreve
# unidade nas duas instalações (`SESAB/SAIS/DGGUP/DGESS/CESS`,
# `FESF/DIGAS/HECC/GAF/ADM`). Serve para o admin poder vincular unidade numa
# instalação que ainda não tem snapshot nenhum: antes, `app.py:1809` só aceitava
# sigla já vista em `snapshot`, e como a FESF nunca coletou, nenhuma unidade dela
# podia ser vinculada — o laço que fechava a FESF fora do produto.
FORMA_SIGLA = re.compile(r"[A-Z0-9][A-Z0-9.\-]*(?:/[A-Z0-9][A-Z0-9.\-]*)+")


def sigla_valida(unidade):
    return bool(unidade) and bool(FORMA_SIGLA.fullmatch(unidade.strip()))


def instancia_da_sigla(unidade):
    """De qual instalação é esta sigla, pelo prefixo — ou None.

    É a única fonte que existe antes do primeiro snapshot. Devolver None em vez
    de cair no padrão é de propósito: gravar vínculo com a instalação errada é
    dar acesso à carteira de outro órgão, e o erro é silencioso.
    """
    if not unidade:
        return None
    u = unidade.strip()
    for chave, p in INSTANCIAS.items():
        if p["prefixo_unidade"] and u.startswith(p["prefixo_unidade"]):
            return chave
    return None


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
