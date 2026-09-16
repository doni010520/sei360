# -*- coding: utf-8 -*-
"""
BUSCA AVANÇADA — pedir ao SEI uma pesquisa filtrada, com o login de quem pediu.

O QUE ELA É
-----------
Uma pergunta ao SEI, feita com a credencial da própria pessoa, cujo resultado é
uma lista com estado honesto: completa, parcial, vazia ou falhou. Ela mostra o
que o SEI mostraria àquela pessoa — nem mais, nem menos.

O QUE ELA NÃO É
---------------
Um caminho de ingestão. O resultado não vira `snapshot`, não entra no poço, não
cria linha em `processo` e não é servido a mais ninguém. O motivo não é excesso
de zelo: a tela de resultado do SEI responde à pergunta que foi feita, e não
prova que aquele processo pertence à mesa de quem buscou. A fronteira inteira do
produto se apoia em `mesa_coleta`, que é campo autodeclarado pela coleta —
deixar uma busca escrever ali seria sancionar a forja que as travas do poço
existem para impedir.

O ESTADO É CALCULADO AQUI, NUNCA ACEITO DO AGENTE
-------------------------------------------------
O SEI declara "N registros" na própria página do resultado. Guardar esse número
ao lado do que veio é o que separa "607 de 607" de "607 e ninguém conferiu". O
sistema irmão desta casa captura o total e nunca o compara — e por isso uma
paginação que falha no meio devolve metade com cara de tudo, sem erro nenhum.

UMA BUSCA POR CONTA DO SEI, DE CADA VEZ
---------------------------------------
Medido, não suposto: a troca de mesa no SEI é por USUÁRIO, não por sessão. Duas
buscas simultâneas da mesma conta em mesas diferentes devolvem a carteira errada
SEM ERRO. A trava é por `(instancia, conta)` — quem tem conta nas duas
instalações pode buscar nas duas ao mesmo tempo, porque são sessões de servidores
diferentes.
"""
import hashlib
import json
from datetime import timedelta

import perfil_sei
from banco import agora, registrar, TZ
from janelas import com_fuso

# Uma busca não pode ficar presa para sempre porque a estação morreu no meio.
# 20 minutos é o mesmo teto da reserva do poço, e pela mesma razão: é mais do que
# qualquer busca medida leva (a maior observada foi de 226 s) e menos do que a
# paciência de quem está olhando a tela.
TRAVA_MIN = 20
# Teto de páginas. O sistema irmão usa 200 e, ao estourar, apenas loga um aviso —
# o valor de retorno não carrega bandeira, então quem consome não tem como saber
# que a lista foi cortada. Aqui o teto vira estado `parcial`, com o motivo dito.
PAGINAS_TETO = 200
# Teto de relógio, para o agente matar o filho. O padrão do projeto é o exit 5
# sintético: `page.evaluate` não obedece o timeout do Playwright.
SEGUNDOS_TETO = 10 * 60
# Teto para ALGUÉM PEGAR o pedido — diferente do teto para EXECUTAR. Uma busca
# parada em `pedida` significa que nada está perguntando ao servidor; esperar dez
# minutos por isso é dez minutos dizendo "pesquisando" sobre uma fila que ninguém
# drena. Noventa segundos é mais do que qualquer estação em atendimento leva.
PEGAR_TETO_S = 90
# Quanto tempo de silêncio da estação ainda conta como "viva". O agendador padrão
# pergunta a cada 30 min; 45 dá folga de uma batida perdida sem deixar passar uma
# estação desligada ontem.
ESTACAO_SILENCIO_MIN = 45
# Prazo do resultado. É lista de trabalho, não acervo.
DIAS = 30
# NOVA TENTATIVA, só no modo servidor e só para falha PASSAGEIRA. Três execuções
# no total: a primeira e duas repetições, com espera crescente. Até 15/09/2026
# não havia nenhuma — a primeira oscilação de rede, o navegador morto por falta
# de memória ou a sessão do SEI caindo no meio viravam 'falhou' definitivo, e a
# pessoa tinha de refazer o pedido sem saber se valia a pena.
MAX_EXECUCOES = 3
ESPERAS_S = (30, 120)
# Folga da varredura sobre o teto do executor. Com os dois prazos iguais, a
# varredura marcava 'falhou' segundos antes de o executor terminar pelo próprio
# relógio — e o resultado que chegava em seguida era descartado como "busca já
# encerrada". O executor tem de ser quem encerra a própria execução.
FOLGA_VARREDURA_S = 120
# Quanto uma busca pode esperar na fila quando HÁ executor vivo neste processo
# com vaga livre. Ele a pega em segundos; se não pegou em 15 min, a fila está
# presa por outro motivo e dizer isso vale mais que esperar para sempre.
FILA_TETO_S = 15 * 60

# Os filtros que a tela oferece. `tipo` diz como o valor é validado aqui — o que
# chega ao SEI é decidido pelo perfil da instância, que sabe os ids de cada versão.
FILTROS = {
    "tramitacao_unidade": "bool",
    "tipo_processo": "texto",
    "especificacao": "texto",
    "contato": "texto",
    "assunto": "texto",
    "observacao": "texto",
    "numero_sei": "texto",
    "data_de": "data",
    "data_ate": "data",
    "tipo_data": "escolha:I,G",
}
# Só estes campos vêm de volta. `especificacao` fica de fora de propósito: é
# texto que um servidor escreveu, pode citar paciente, e o consentimento para
# tratá-lo é por unidade.
CAMPOS_ITEM = ("id_sei", "protocolo", "tipo_processo",
               "unidade_geradora", "usuario_gerador", "data_inclusao")


def sha_dos_filtros(filtros):
    """Seis hex do JSON canônico. Serve para responder "foi a mesma busca?" sem
    expor o quê: o texto de um filtro pode citar nome próprio, e o `log_acesso` é
    lido por gestor e admin."""
    cru = json.dumps(filtros, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(cru.encode("utf-8")).hexdigest()[:6]


def validar(filtros, instancia):
    """Devolve (limpos, erro). Filtro que não dá para aplicar RECUSA a busca.

    Não é rigor por rigor: filtro que não pegou muda o universo da resposta sem
    mudar uma linha da tela. No sistema irmão, o tipo de processo é casado por
    `String.includes` sensível a maiúscula e o log diz "Filtro aplicado" mesmo
    quando nada casou — digitar "dispensa" em vez de "Dispensa" devolve o acervo
    inteiro, e a tela não tem como saber.
    """
    if not perfil_sei.existe(instancia):
        return None, f"instância desconhecida: {instancia}"
    if not perfil_sei.perfil(instancia)["disponivel_busca"]:
        return None, f"a busca não está disponível em {instancia}"
    limpos = {}
    for k, v in (filtros or {}).items():
        if k not in FILTROS:
            return None, f"filtro desconhecido: {k}"
        tipo = FILTROS[k]
        if tipo == "bool":
            limpos[k] = bool(v)
        elif tipo.startswith("escolha:"):
            opcoes = tipo.split(":", 1)[1].split(",")
            if v and v not in opcoes:
                return None, f"{k} tem de ser um de {', '.join(opcoes)}"
            limpos[k] = v or opcoes[0]
        elif tipo == "data":
            s = (v or "").strip()
            if s and not _data_ok(s):
                return None, f"{k} tem de ser DD/MM/AAAA"
            if s:
                limpos[k] = s
        else:
            s = (v or "").strip()
            if len(s) > 200:
                return None, f"{k} passa de 200 caracteres"
            if s:
                limpos[k] = s
    # Uma busca SEM critério nenhum, com "tramitação na unidade" marcado, é uma
    # varredura da mesa inteira disparada por um clique. No sistema irmão foi
    # exatamente isso que rodou: 718 processos, 72 páginas, 226 s — sem ninguém
    # ter digitado nada. A data é o único filtro que limita o tamanho na origem.
    tem_criterio = any(k for k in limpos
                       if k not in ("tramitacao_unidade", "tipo_data"))
    if not tem_criterio:
        return None, ("informe pelo menos um critério além de 'com tramitação na "
                      "unidade' — sem nenhum, a busca varre a mesa inteira")
    if limpos.get("data_de") and limpos.get("data_ate"):
        if _para_ord(limpos["data_de"]) > _para_ord(limpos["data_ate"]):
            return None, "a data inicial é posterior à final"
    return limpos, None


def _data_ok(s):
    import re
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    if not m:
        return False
    d, mes, a = (int(x) for x in m.groups())
    return 1 <= d <= 31 and 1 <= mes <= 12 and 1900 <= a <= 2999


def _para_ord(s):
    d, m, a = s.split("/")
    return (a, m, d)


# ---------------------------------------------------------- quem executa
def quem_executa(cx, usuario_id, agora_dt=None, instancia=None):
    """Quem pode rodar uma busca desta pessoa, ou (None, motivo, como).

    Chamado ANTES de aceitar o pedido. Enfileirar trabalho que ninguém tem como
    pegar é o pior desfecho possível para uma tela interativa: a pessoa fica
    olhando uma frase que afirma um trabalho que não existe.

    HÁ DOIS EXECUTORES, e a configuração da pessoa diz qual. Em modo `estacao`, a
    busca roda no computador dela e a pergunta é "há estação viva?". Em modo
    `servidor`, roda aqui, e a pergunta passa a ser "há navegador nesta imagem?" —
    que é uma propriedade do build, não da configuração. Quem responde é
    `atendente.capacidade()`, olhando o que existe de fato no disco.
    """
    from datetime import datetime
    agora_dt = agora_dt or datetime.now(TZ)
    if _modo_servidor(cx, usuario_id, instancia):
        # O IMPORT PODE FALHAR, e falhar aqui não pode virar 500. `app.py` já
        # protege a SUBIDA do laço com try/except e isso dá a impressão de que a
        # falha está tratada — mas era este import, dentro da função, que
        # derrubava /busca e /configuracao inteiras. Recusa explicada é a resposta
        # que este sistema tem para "não há quem execute"; 500 não é.
        try:
            import atendente
            pode, motivo = atendente.capacidade()
        except Exception as ex:                                # noqa: BLE001
            pode, motivo = False, (f"o executor de busca deste servidor não "
                                   f"carregou ({type(ex).__name__})")
        # SEM A SENHA DESTA INSTALAÇÃO NO COFRE, O SERVIDOR NÃO TEM COM QUE
        # ENTRAR — e aceitar o pedido era travar a conta e mostrar "pesquisando"
        # até o executor descobrir o óbvio. Recusar aqui diz a coisa certa na
        # hora, e diz o que fazer.
        if pode and instancia and not cx.execute(
                "SELECT 1 FROM credencial WHERE usuario_id=? AND sistema=?",
                (usuario_id, instancia)).fetchone():
            pode, motivo = False, (f"a senha do SEI para {instancia} não está "
                                   "guardada no servidor")
            if not _estacao_viva(cx, usuario_id, agora_dt):
                return None, motivo, (
                    "Guarde a senha do SEI desta instalação em Configuração → "
                    "Acesso. A busca roda com o seu login, e sem ele o servidor "
                    "não tem como entrar.")
        # O SEI JÁ RECUSOU ESTA SENHA (e ela não foi salva de novo): aceitar o
        # pedido seria mais um login errado na conta da pessoa, 60 s de espera na
        # tela e a mesma recusa no fim. Diz agora, com o que o SEI respondeu.
        if pode and instancia:
            import cofre as _cofre
            _rec = _cofre.recusa(cx, usuario_id, instancia)
            if _rec:
                return None, (f"o SEI recusou a senha guardada para {instancia} em "
                              f"{str(_rec['recusada_em'])[:16].replace('T', ' ')}"), (
                    f"{_rec['recusa_motivo']} Salve a senha de novo em Configuração → "
                    "Acesso: enquanto isso o servidor não tenta entrar com ela, porque "
                    "cada tentativa errada conta para o bloqueio da sua conta no SEI.")
        if pode:
            return ({"nome_estacao": "este servidor", "servidor": True,
                     "id": None, "token_sha256": None}, None, None)
        # NÃO devolve erro ainda: uma estação pareada continua sendo um executor
        # legítimo, e recusar aqui seria esconder o caminho que funciona. Só se
        # não houver estação é que o motivo do servidor vira a resposta.
        de_reserva = _estacao_viva(cx, usuario_id, agora_dt)
        if not de_reserva:
            # A RECUSA FALA A LÍNGUA DE QUEM LÊ. O texto técnico — caminho de
            # arquivo, nome de variável de ambiente, "rebuild da imagem" — é
            # acionável por quem administra e por mais ninguém. Mandá-lo para um
            # servidor da SESAB transforma um ajuste de infraestrutura em culpa
            # dele, e a saída que o texto oferecia ("passe para o modo estação")
            # pede instalar um agente e rodar comando de terminal: não é
            # exequível para quem só quer triar processo.
            #
            # 57 das 60 contas têm papel `servidor`. O texto técnico é, na
            # prática, o texto errado para quase todo mundo.
            r = cx.execute("SELECT papel FROM usuarios WHERE id=?",
                           (usuario_id,)).fetchone()
            if r and r["papel"] in ("admin", "gestor"):
                return None, f"a busca está em modo servidor e {motivo}", (
                    "Ou a imagem sobe com o navegador (veja o Dockerfile e o "
                    "ARQUITETURA_ACESSO.md §6), ou esta pessoa passa para o modo "
                    "estação em /configuracao, com um agente vinculado.")
            return None, "a busca avançada está indisponível neste momento", (
                "É um ajuste do servidor, não da sua conta — quem administra o "
                "SEI360 precisa concluir a configuração da busca. O painel e os "
                "relatórios seguem funcionando normalmente enquanto isso.")
        return de_reserva, None, None
    ag = cx.execute("""SELECT * FROM agentes WHERE dono_usuario_id=? AND ativo=1
                       ORDER BY id DESC LIMIT 1""", (usuario_id,)).fetchone()
    if not ag:
        return None, "nenhuma estação vinculada a você", (
            "A busca roda no computador onde está a sua credencial do SEI. "
            "Peça a um administrador para vincular a sua estação em /admin.")
    if not ag["token_sha256"]:
        return None, f"a estação {ag['nome_estacao']} ainda não foi pareada", (
            "Ela existe no cadastro mas nunca se apresentou ao servidor. "
            "Gere o código em /admin e rode `sei360_agente.py vincular` na estação.")
    if ag["pausado_motivo"]:
        return None, f"a estação {ag['nome_estacao']} está pausada", ag["pausado_motivo"]
    if not ag["ultimo_contato_em"]:
        return None, f"a estação {ag['nome_estacao']} nunca falou com o servidor", (
            "Ela foi pareada mas o agente não está rodando. Inicie-o na estação.")
    calado = _horas_desde(ag["ultimo_contato_em"], agora_dt) * 60
    if calado > ESTACAO_SILENCIO_MIN:
        return None, (f"a estação {ag['nome_estacao']} não fala com o servidor "
                      f"há {int(calado)} min"), (
            "O agente não está rodando, ou o computador está desligado. "
            "A busca precisa dele para acontecer.")
    return ag, None, None


def _modo_servidor(cx, usuario_id, instancia=None):
    """Esta pessoa pediu que a coleta/busca rode no servidor?

    Sem `instancia`, basta qualquer instalação em modo servidor: a tela de busca
    sempre sabe a instância, mas `pedir()` é chamado de mais de um lugar.

    SEM LINHA NENHUMA, a resposta é SERVIDOR — porque é o padrão declarado no DDL
    (`config_usuario.modo_coleta DEFAULT 'servidor'`) e o que `configuracao.ler()`
    devolve a quem nunca abriu o assistente. Responder "estação" aqui mandaria as
    59 pessoas que ainda não configuraram para uma tela dizendo "nenhuma estação
    vinculada a você" — culpando-as por não terem uma máquina que este desenho
    não pede mais que elas tenham.
    """
    if instancia:
        r = cx.execute("SELECT modo_coleta FROM config_usuario "
                       "WHERE usuario_id=? AND sistema=?",
                       (usuario_id, instancia)).fetchone()
    else:
        r = cx.execute("SELECT modo_coleta FROM config_usuario WHERE usuario_id=? "
                       "ORDER BY (modo_coleta='servidor') DESC LIMIT 1",
                       (usuario_id,)).fetchone()
    return r["modo_coleta"] == "servidor" if r else True


def _estacao_viva(cx, usuario_id, agora_dt):
    """A estação desta pessoa, se estiver em condições de executar. Ou None."""
    ag = cx.execute("""SELECT * FROM agentes WHERE dono_usuario_id=? AND ativo=1
                       AND token_sha256 IS NOT NULL AND pausado_motivo IS NULL
                       AND ultimo_contato_em IS NOT NULL
                       ORDER BY id DESC LIMIT 1""", (usuario_id,)).fetchone()
    if not ag:
        return None
    calado = _horas_desde(ag["ultimo_contato_em"], agora_dt) * 60
    return ag if calado <= ESTACAO_SILENCIO_MIN else None


def _fila_pode_estar_cheia():
    """Este processo pode AFIRMAR que a fila do executor está livre?

    Devolve True quando NÃO PODE — e aí a busca em `pedida` não é morta.

    Com `--workers 3`, dois workers servem painel e têm o próprio semáforo
    intacto: para eles a fila nunca está cheia. Como a varredura é chamada pela
    rota que a tela poleia a cada 2 s, e o pedido cai em qualquer worker, a
    terceira busca de uma fila de duas vagas morria quase sempre — com a frase
    errada, acusando um agente que não existe no modo servidor.

    Três situações, três respostas:
      * sou o executor  -> sei de verdade: as vagas deste processo são as vagas;
      * há executor, mas não sou eu -> NÃO SEI, e não decido;
      * não há executor nenhum -> a busca não vai ser pega mesmo; pode morrer.
    """
    try:
        import threading

        import atendente
        if atendente.vivo():
            return (atendente.vagas_livres() == 0
                    and any(t.name.startswith("busca-") and t.is_alive()
                            for t in threading.enumerate()))
        return atendente.ha_executor()
    except Exception:                                          # noqa: BLE001
        return False


def _horas_desde(iso, ate_dt):
    try:
        return (ate_dt - com_fuso(iso)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 1e9


# ------------------------------------------------------------------ a trava
def trava_viva(cx, instancia, conta, agora_dt=None):
    """A busca em curso desta conta, se houver. Trava vencida é apagada NA
    LEITURA — agente que morre no meio não tranca a conta para sempre."""
    from datetime import datetime
    agora_dt = agora_dt or datetime.now(TZ)
    cx.execute("DELETE FROM busca_trava WHERE ate < ?",
               (agora_dt.isoformat(timespec="seconds"),))
    return cx.execute("SELECT * FROM busca_trava WHERE instancia=? AND conta=?",
                      (instancia, conta)).fetchone()


def _travar(cx, instancia, conta, busca_id, agora_dt=None, minutos=None, dono=None):
    """Toma (ou renova) a trava da conta. Devolve True se ela ficou COM ESTE DONO.

    O dono é a busca (`busca_id`) ou um motor (`dono`, com `busca_id` None: coleta
    ou acompanhamento). As três execuções usam a mesma conta do SEI, e a unidade
    ativa lá é estado POR USUÁRIO — uma trava só, por conta, para os três.

    NUNCA TOMA A TRAVA DE OUTRO DONO VIVO. A versão anterior fazia upsert cego:
    a varredura, reenfileirando uma busca órfã, trocava a trava de uma coleta em
    curso pela da busca — e a busca era entregue e trocava a mesa no meio da
    coleta. Trava vencida continua podendo ser tomada; é para isso que ela vence.
    """
    from datetime import datetime
    agora_dt = agora_dt or datetime.now(TZ)
    agora_iso = agora_dt.isoformat(timespec="seconds")
    ate = (agora_dt + timedelta(minutes=minutos or TRAVA_MIN)).isoformat(timespec="seconds")
    cx.execute("""INSERT INTO busca_trava(instancia,conta,busca_id,ate,dono) VALUES(?,?,?,?,?)
                  ON CONFLICT(instancia,conta) DO UPDATE SET
                    busca_id=excluded.busca_id, ate=excluded.ate, dono=excluded.dono
                  WHERE busca_trava.ate < ?
                     OR (busca_trava.busca_id IS excluded.busca_id
                         AND busca_trava.dono IS excluded.dono)""",
               (instancia, conta, busca_id, ate, dono, agora_iso))
    r = cx.execute("SELECT busca_id, dono FROM busca_trava WHERE instancia=? AND conta=?",
                   (instancia, conta)).fetchone()
    return bool(r) and r["busca_id"] == busca_id and r["dono"] == dono


def _destravar(cx, instancia, conta, busca_id=None, dono=None):
    """Solta a trava da conta SE ela for deste dono. Devolve quantas soltou.

    Pelo dono, e não pela conta: `receber()` de uma busca apagava a trava da conta
    inteira — inclusive a de uma coleta que tinha começado depois —, e o resto da
    coleta seguia sem trava, aceitando busca na mesma conta.
    """
    return cx.execute("""DELETE FROM busca_trava WHERE instancia=? AND conta=?
                         AND busca_id IS ? AND dono IS ?""",
                      (instancia, conta, busca_id, dono)).rowcount


def trava_de_outro(cx, instancia, conta, busca_id=None, dono=None, agora_dt=None):
    """A trava viva desta conta, se o dono não for este. Ou None."""
    t = trava_viva(cx, instancia, conta, agora_dt)
    if not t or (t["busca_id"] == busca_id and t["dono"] == dono):
        return None
    return t


def soltar_conta(instancia, conta, busca_id=None, dono=None, tentativas=5):
    """`_destravar` com conexão própria e insistência. Para quem solta num `finally`.

    "database is locked" é o caso ordinário neste banco (a faxina faz VACUUM de
    ~8,5 s; a ingestão escreve mil linhas num commit), e o destravar sem
    repetição levantava, a exceção era engolida, e a conta ficava recusando busca
    por 35 min depois de a coleta já ter terminado.
    """
    import time as _t

    import banco as _banco
    for i in range(tentativas):
        cx = None
        try:
            cx = _banco.conectar()
            _destravar(cx, instancia, conta, busca_id, dono)
            cx.commit()
            return True
        except Exception:                                      # noqa: BLE001
            _t.sleep(1 + 2 * i)
        finally:
            if cx is not None:
                try:
                    cx.close()
                except Exception:                              # noqa: BLE001
                    pass
    return False


def limpar_travas_de_motor(cx, token_vivo):
    """Apaga trava de coleta/acompanhamento deixada por um processo que MORREU.

    Só o processo executor do container roda coleta e acompanhamento, e ele carimba
    a trava com o próprio token (`atendente.TOKEN`). Trava de motor com outro token
    é de um executor anterior — morto por redeploy, falta de memória ou reinício
    —, e nenhum `finally` a soltou. Sem esta limpeza ela segurava a retomada da
    própria coleta e recusava a busca da pessoa com "a coleta está rodando", o que
    era falso desde a morte.
    """
    return cx.execute("""DELETE FROM busca_trava WHERE dono LIKE 'motor:%'
                         AND dono NOT LIKE ?""", (f"motor:{token_vivo}:%",)).rowcount


# ------------------------------------------------------------------- pedir
def pedir(cx, usuario_id, instancia, conta, mesa, filtros, ip=None):
    """Enfileira uma busca. Devolve (busca_id, erro, id_em_curso)."""
    limpos, erro = validar(filtros, instancia)
    if erro:
        return None, erro, None
    if not conta:
        return None, ("nenhuma conta do SEI configurada para esta instalação — "
                      "a busca roda com o SEU login, e sem ele não há como buscar"), None
    # QUEM VAI EXECUTAR? Sem estação capaz, o pedido não entra na fila. Aceitar
    # aqui e travar a conta por 20 minutos, com a tela dizendo "pesquisando", foi
    # o defeito relatado — e é o modo de falha que este projeto persegue: parecer
    # que funciona enquanto nada acontece.
    _ag, _motivo, _como = quem_executa(cx, usuario_id, instancia=instancia)
    if not _ag:
        return None, f"{_motivo}. {_como}", None
    em_curso = trava_viva(cx, instancia, conta)
    if em_curso and em_curso["busca_id"] is None:
        # A CONTA ESTÁ COM A COLETA OU O ACOMPANHAMENTO no SEI. Dizer "já há uma
        # busca em curso" mandava a pessoa procurar uma busca que não existe.
        oque = ("o acompanhamento" if (em_curso["dono"] or "").endswith(":acompanhamento")
                else "a coleta")
        return None, (f"{oque} desta conta está rodando no SEI agora — peça a "
                      "busca de novo em alguns minutos"), None
    if em_curso:
        # DEGRADA, não bloqueia: devolve qual busca está em curso, para a tela
        # mostrar o progresso dela em vez de um erro sem saída.
        return None, "já há uma busca em curso nesta conta", em_curso["busca_id"]
    sha = sha_dos_filtros(limpos)
    cur = cx.execute("""INSERT INTO busca(usuario_id,instancia,conta,mesa,filtros,
                        filtros_sha,estado,paginas_teto,pedida_em)
                        VALUES(?,?,?,?,?,?,'pedida',?,?)""",
                     (usuario_id, instancia, conta, mesa,
                      json.dumps(limpos, ensure_ascii=False), sha, PAGINAS_TETO, agora()))
    bid = cur.lastrowid
    _travar(cx, instancia, conta, bid)
    # O TEXTO DOS FILTROS NÃO ENTRA NO LOG. O log é lido por gestor e admin, e o
    # filtro de uma pessoa pode citar nome próprio. O sha responde "foi a mesma
    # busca?" sem dizer qual; o texto fica em `busca.filtros`, que é dela e tem prazo.
    registrar(cx, usuario_id, "busca_pedida",
              alvo=f"{instancia} · busca {bid} · {len(limpos)} filtro(s) · sha {sha}",
              unidade=mesa, ip=ip)
    return bid, None, None


def entregar(cx, agente_dono_id, instancia):
    """A próxima busca desta pessoa nesta instalação, ou None. Marca 'entregue'."""
    r = cx.execute("""SELECT * FROM busca WHERE usuario_id=? AND instancia=?
                      AND estado='pedida' ORDER BY id LIMIT 1""",
                   (agente_dono_id, instancia)).fetchone()
    if not r:
        return None
    # A REIVINDICAÇÃO É O PRÓPRIO UPDATE, com `AND estado='pedida'`. Sem essa
    # guarda, o SELECT e o UPDATE eram duas operações separadas: o agente da
    # estação lia a busca como 'pedida', o atendente do servidor a reivindicava
    # no meio, e o agente completava o UPDATE assim mesmo e levava a tarefa. Os
    # dois executavam a MESMA busca com a MESMA conta do SEI ao mesmo tempo — e a
    # troca de mesa no SEI é por USUÁRIO, não por sessão: as duas voltam com zero
    # linha, e o veredito culpa o SEI.
    #
    # `rowcount == 0` significa que outro executor chegou primeiro. Devolver None
    # é o certo: quem perdeu a corrida não tem tarefa.
    if cx.execute("UPDATE busca SET estado='entregue', entregue_em=? "
                  "WHERE id=? AND estado='pedida'",
                  (agora(), r["id"])).rowcount != 1:
        return None
    p = perfil_sei.perfil(instancia)
    return {
        "busca_id": r["id"], "instancia": instancia, "mesa": r["mesa"],
        "filtros": json.loads(r["filtros"]),
        "campos": p["campos_busca"], "versao": p["versao"],
        "paginas_teto": r["paginas_teto"] or PAGINAS_TETO,
        "segundos_teto": SEGUNDOS_TETO,
    }


def veredito(total_declarado, colhidos, paginas, teto, motivo_agente):
    """O estado, calculado do que foi medido — nunca aceito do agente.

    A ordem importa. `falhou` vem primeiro porque um agente que morreu no meio
    não sabe quantos registros existiam; e a ausência do total declarado é
    `falhou`, não `completa`: sem ele não há com o que reconciliar, e chamar isso
    de completo é afirmar o que ninguém mediu.
    """
    if motivo_agente:
        # MOTIVO COM ITENS JÁ COLHIDOS É PARCIAL, não falha: as páginas lidas antes
        # do problema são resultado do SEI, e jogá-las fora como "falhou" fazia a
        # pessoa refazer o que já tinha vindo.
        if colhidos:
            return "parcial", f"{motivo_agente} — vieram {colhidos} antes disso"
        return "falhou", motivo_agente
    if total_declarado is None:
        if colhidos:
            return "parcial", (f"o SEI não declarou o total de registros; vieram "
                               f"{colhidos}, sem como conferir se é tudo")
        return "falhou", "o SEI não declarou o total de registros"
    if total_declarado == 0 and not colhidos:
        return "vazia", None
    if colhidos == total_declarado:
        return "completa", None
    if paginas and teto and paginas >= teto:
        return "parcial", f"teto de {teto} páginas"
    return "parcial", f"o SEI declarou {total_declarado} e vieram {colhidos}"


def receber(cx, busca_id, envelope, ip=None):
    """Grava o resultado. Devolve (estado, motivo)."""
    r = cx.execute("SELECT * FROM busca WHERE id=?", (busca_id,)).fetchone()
    if not r:
        return None, "busca não encontrada"
    # RESULTADO QUE CHEGA DEPOIS DA VARREDURA É RESULTADO. A varredura marca
    # 'falhou' pelo prazo; se o executor ainda assim devolveu, o SEI respondeu, e
    # descartar isso como "busca já encerrada" jogava fora exatamente o que a
    # pessoa pediu. Só vale para a falha POR PRAZO — cancelada continua cancelada.
    tardio = (r["estado"] == "falhou"
              and "não devolveu resultado em" in (r["motivo"] or ""))
    if r["estado"] in ("completa", "parcial", "vazia", "falhou", "cancelada") and not tardio:
        # DESTRAVA MESMO ASSIM. A busca acabou — cancelada, ou morta pela
        # varredura — e o coletor só agora devolveu. É exatamente aqui que se
        # sabe que ninguém está mais logado naquela conta. Sem isto, todo
        # cancelamento deixaria a conta presa os 20 min inteiros de TRAVA_MIN.
        _destravar(cx, r["instancia"], r["conta"], busca_id)
        return r["estado"], "esta busca já foi encerrada"

    itens = envelope.get("itens") or []
    total = envelope.get("total_declarado")
    paginas = envelope.get("paginas_lidas")
    motivo_ag = envelope.get("motivo")
    confirmada = envelope.get("mesa_confirmada")

    # A MESA CONFIRMADA É FATO OBSERVADO, não intenção. O filtro "com tramitação
    # na unidade" faz o resultado ser função da unidade ATIVA da sessão, e a
    # unidade ativa é estado de servidor. Se o que o SEI relatou não é o que foi
    # pedido, o resultado é de outra mesa — e isso é falha, não um detalhe.
    # SEM ITENS E COM MOTIVO DO COLETOR, o motivo dele é o verdadeiro: é o caso da
    # troca de mesa que falhou ("nao consegui ativar a mesa pedida"), e trocá-lo
    # pela divergência de mesa devolvia à pessoa exatamente a frase enganosa que a
    # troca existe para eliminar. Com itens, a divergência continua mandando: são
    # itens de outra mesa.
    if r["mesa"] and confirmada and confirmada != r["mesa"] and (itens or not motivo_ag):
        estado, motivo = "falhou", (f"a mesa ativa no SEI é {confirmada}, e a busca "
                                    f"foi pedida para {r['mesa']}")
        itens = []
    else:
        estado, motivo = veredito(total, len(itens), paginas,
                                  r["paginas_teto"] or PAGINAS_TETO, motivo_ag)
        # FILTRO QUE O SEI NÃO ACEITOU MUDA A PERGUNTA. O motor declara em
        # `filtros_recusados` o campo que não casou, e a busca rodava SEM o
        # critério — devolvendo a resposta a outra pergunta com cara de completa.
        recusados = [f.get("campo") if isinstance(f, dict) else str(f)
                     for f in (envelope.get("filtros_recusados") or [])]
        if recusados and estado in ("completa", "vazia"):
            estado, motivo = "parcial", (
                "o SEI não aceitou o(s) filtro(s) " + ", ".join(filter(None, recusados))
                + " — o resultado NÃO aplica esse critério")

    # OS ITENS PRIMEIRO, O VEREDITO POR ÚLTIMO. A ordem inversa publicava
    # "completa · 5 de 5" com dois itens gravados quando um INSERT do laço
    # levantava no meio — e "database is locked" é o caso ordinário, não o
    # exótico: a ingestão escreve 1.165 linhas num commit só, no mesmo processo
    # em que este código roda. O veredito é a última coisa que este sistema
    # afirma sobre uma busca; afirmá-lo antes de ter o que ele descreve é
    # exatamente o "607 de 607 e ninguém conferiu" que o cabeçalho deste arquivo
    # existe para impedir.
    for i, it in enumerate(itens, 1):
        cx.execute(f"""INSERT OR REPLACE INTO busca_item(busca_id,ordem,
                       {','.join(CAMPOS_ITEM)})
                       VALUES(?,?,{','.join('?' * len(CAMPOS_ITEM))})""",
                   [busca_id, i] + [it.get(c) for c in CAMPOS_ITEM])
    cx.execute("""UPDATE busca SET estado=?, motivo=?, mesa_confirmada=?,
                  total_declarado=?, colhidos=?, paginas_lidas=?,
                  terminada_em=?, duracao_s=? WHERE id=?""",
               (estado, motivo, confirmada, total, len(itens), paginas,
                agora(), envelope.get("duracao_s"), busca_id))
    _destravar(cx, r["instancia"], r["conta"], busca_id)
    registrar(cx, r["usuario_id"], "busca_resultado",
              alvo=(f"busca {busca_id} · {estado} · {len(itens)}/{total} · "
                    f"{paginas} pág · {envelope.get('duracao_s')} s"),
              unidade=confirmada or r["mesa"], ip=ip)
    return estado, motivo


def pode_repetir(cx, busca_id):
    """Esta busca ainda tem direito a outra execução? (só modo servidor)"""
    r = cx.execute("SELECT usuario_id, instancia, tentativas, estado FROM busca "
                   "WHERE id=?", (busca_id,)).fetchone()
    if not r or r["estado"] in ("completa", "parcial", "vazia", "cancelada", "pedida"):
        return False
    if not _modo_servidor(cx, r["usuario_id"], r["instancia"]):
        return False
    return (r["tentativas"] or 0) + 1 < MAX_EXECUCOES


def reenfileirar(cx, busca_id, motivo, agora_dt=None):
    """Devolve a busca à fila com espera crescente. Devolve True se voltou.

    A TRAVA DA CONTA CONTINUA COM ELA, renovada: soltar entre uma tentativa e
    outra deixaria a coleta — ou um segundo pedido — entrar na mesma conta do
    SEI no intervalo, e a troca de mesa lá é por usuário.

    O MOTIVO FICA VISÍVEL enquanto espera. Sem ele a tela diria "aguardando" sobre
    uma busca que já falhou uma vez, e a pessoa não saberia que o sistema está
    tentando de novo — nem por quê.
    """
    from datetime import datetime
    agora_dt = agora_dt or datetime.now(TZ)
    r = cx.execute("SELECT * FROM busca WHERE id=?", (busca_id,)).fetchone()
    if not r:
        return False
    n = (r["tentativas"] or 0) + 1
    espera = ESPERAS_S[min(n - 1, len(ESPERAS_S) - 1)]
    apos = (agora_dt + timedelta(seconds=espera)).isoformat(timespec="seconds")
    texto = (f"nova tentativa {n + 1} de {MAX_EXECUCOES} em {espera} s — "
             f"a anterior falhou: {motivo}")[:300]
    ok = cx.execute("""UPDATE busca SET estado='pedida', tentativas=?, tentar_apos=?,
                       motivo=?, entregue_em=NULL
                       WHERE id=? AND estado IN ('entregue','em_curso','falhou')""",
                    (n, apos, texto, busca_id)).rowcount == 1
    if ok:
        # Se a conta está com OUTRO dono vivo (uma coleta que começou no meio), a
        # busca volta para a fila SEM trava e espera: `atendente.pegar` não entrega
        # busca cuja conta está com outro. Tomar à força era o defeito.
        _travar(cx, r["instancia"], r["conta"], busca_id, agora_dt,
                minutos=TRAVA_MIN + espera // 60 + 1)
        registrar(cx, r["usuario_id"], "busca_nova_tentativa",
                  alvo=f"busca {busca_id} · tentativa {n + 1}/{MAX_EXECUCOES} · {motivo[:120]}",
                  unidade=r["mesa"])
    return ok


def registrar_origem(cx, busca_id, sigla):
    """A unidade em que a conta estava antes da PRIMEIRA troca. Só a primeira vale."""
    if sigla:
        cx.execute("UPDATE busca SET mesa_origem=COALESCE(mesa_origem, ?) WHERE id=?",
                   (sigla, busca_id))


def cancelar(cx, busca_id, usuario_id, ip=None):
    # O LOCK DE ESCRITA ANTES DA LEITURA. Ler o estado e só depois escrever deixava
    # uma janela: o executor reenfileirava a busca (estado 'pedida', trava renovada)
    # entre as duas operações, o cancelamento gravava 'cancelada' por cima e não
    # soltava a conta, porque o estado que ele tinha lido era 'entregue'. A conta
    # ficava presa ~21 min por uma busca cancelada. O UPDATE neutro toma o lock.
    cx.execute("UPDATE busca SET estado=estado WHERE id=? AND usuario_id=?",
               (busca_id, usuario_id))
    r = cx.execute("SELECT * FROM busca WHERE id=? AND usuario_id=?",
                   (busca_id, usuario_id)).fetchone()
    if not r:
        return False
    if r["estado"] in ("completa", "parcial", "vazia", "falhou", "cancelada"):
        return False
    cx.execute("UPDATE busca SET estado='cancelada', motivo=?, terminada_em=? WHERE id=?",
               ("cancelada por quem pediu", agora(), busca_id))
    # SO DESTRAVA SE NINGUEM PEGOU. Cancelar uma busca ja ENTREGUE soltava a
    # conta enquanto o coletor continuava logado no SEI: a pessoa pedia outra na
    # hora, e dois Chromium entravam na MESMA conta. A troca de mesa no SEI e por
    # USUARIO, nao por sessao — as duas voltam com zero linha, e o veredito culpa
    # o SEI. Quando ja pegaram, a trava cai em `receber()`, que e o instante em
    # que se sabe que ninguem esta mais logado naquela conta.
    if r["estado"] == "pedida":
        _destravar(cx, r["instancia"], r["conta"], busca_id)
    registrar(cx, usuario_id, "busca_cancelada", alvo=f"busca {busca_id}",
              unidade=r["mesa"], ip=ip)
    return True


def ler(cx, busca_id, usuario_id, com_itens=True, ip=None):
    """A busca e seus itens — SÓ para quem pediu.

    Não há leitura por gestor nem por admin. Uma busca é a pergunta de uma
    pessoa, feita com o login dela; abrir isso para terceiros seria transformar
    uma ferramenta de trabalho em registro de comportamento.
    """
    r = cx.execute("SELECT * FROM busca WHERE id=? AND usuario_id=?",
                   (busca_id, usuario_id)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["filtros"] = json.loads(d["filtros"] or "{}")
    d["itens"] = []
    if com_itens:
        d["itens"] = [dict(x) for x in cx.execute(
            "SELECT * FROM busca_item WHERE busca_id=? ORDER BY ordem", (busca_id,))]
        if d["itens"]:
            registrar(cx, usuario_id, "busca_lida",
                      alvo=f"busca {busca_id} · {len(d['itens'])} itens",
                      unidade=d.get("mesa_confirmada") or d.get("mesa"), ip=ip)
    return d


def minhas(cx, usuario_id, limite=20):
    return [dict(r) for r in cx.execute(
        """SELECT id,instancia,mesa,mesa_confirmada,filtros_sha,estado,motivo,
                  total_declarado,colhidos,pedida_em,terminada_em,duracao_s
           FROM busca WHERE usuario_id=? ORDER BY id DESC LIMIT ?""",
        (usuario_id, limite))]


def varrer(cx, agora_dt=None):
    """Busca que empacou. DOIS prazos, porque são dois problemas diferentes.

    `pedida` sem ninguém pegar significa que NADA está perguntando ao servidor —
    e isso se sabe em segundos, não em dez minutos. `entregue` sem voltar
    significa que a estação pegou e morreu no meio, e aí o prazo é o da execução.

    Um prazo só para os dois casos faz a tela dizer "pesquisando" por dez minutos
    sobre uma fila que ninguém drena.
    """
    from datetime import datetime
    agora_dt = agora_dt or datetime.now(TZ)
    n = 0
    corte_pegar = (agora_dt - timedelta(seconds=PEGAR_TETO_S)).isoformat(timespec="seconds")
    fila_cheia = _fila_pode_estar_cheia()
    corte_fila = (agora_dt - timedelta(seconds=FILA_TETO_S)).isoformat(timespec="seconds")
    try:
        import atendente as _at
        executor_aqui = _at.vivo()
    except Exception:                                          # noqa: BLE001
        executor_aqui = False
    # O PRAZO CONTA DE QUANDO A BUSCA PODIA COMEÇAR: numa nova tentativa, é
    # `tentar_apos`, e não o pedido original — senão toda repetição nasceria vencida.
    for b in cx.execute("""SELECT * FROM busca WHERE estado='pedida'
                           AND COALESCE(tentar_apos, pedida_em) < ?""",
                        (corte_pegar,)).fetchall():
        no_servidor = _modo_servidor(cx, b["usuario_id"], b["instancia"])
        # O EXECUTOR ESTÁ NESTE PROCESSO e a busca esperou por uma vaga: ele a
        # pega na próxima volta do laço, em segundos. Matá-la aqui era o defeito
        # medido: a vaga se soltava, a busca que tinha esperado mais de 90 s na
        # fila morria na janela de até 3 s antes da rodada seguinte. Só quando a
        # espera passa de FILA_TETO_S a fila está presa de verdade.
        if no_servidor and executor_aqui and (b["tentar_apos"] or b["pedida_em"]) >= corte_fila:
            continue
        # FILA CHEIA NÃO É PEDIDO ABANDONADO. No modo servidor, `pedida` com as
        # vagas todas ocupadas significa que a busca está na fila — ela nem
        # chegou a ser tentada. Matá-la aos 90 s manda a pessoa procurar um
        # agente que não existe nesse modo, e a própria tela é quem dispara a
        # varredura (ela poleia a cada 2 s, e a rota chama `varrer`): o ato de
        # esperar mataria a espera. A maior busca medida neste projeto levou
        # 226 s, então uma vaga ocupada não abre em 90 s.
        if no_servidor and fila_cheia:
            continue
        # E QUANDO MATAR, DIZER QUEM FALTOU. No modo servidor não há estação; a
        # frase do agente só é verdadeira no modo estação.
        motivo = (f"o executor de busca deste servidor não pegou o pedido em "
                  f"{PEGAR_TETO_S} s" if no_servidor else
                  f"nenhuma estação pegou o pedido em {PEGAR_TETO_S} s — "
                  f"o agente não está rodando")
        # COM GUARDA DE ESTADO: outra varredura (outro worker, ou o laço do
        # executor) pode ter agido sobre esta linha entre o SELECT e aqui.
        if cx.execute("""UPDATE busca SET estado='falhou', motivo=?, terminada_em=?
                         WHERE id=? AND estado='pedida'""",
                      (motivo, agora(), b["id"])).rowcount == 1:
            _destravar(cx, b["instancia"], b["conta"], b["id"])
            n += 1
    corte_exec = (agora_dt - timedelta(seconds=SEGUNDOS_TETO + FOLGA_VARREDURA_S)
                  ).isoformat(timespec="seconds")
    for b in cx.execute("""SELECT * FROM busca WHERE estado IN ('entregue','em_curso')
                           AND COALESCE(entregue_em, pedida_em) < ?""",
                        (corte_exec,)).fetchall():
        # ÓRFÃ DE UM EXECUTOR QUE MORREU (redeploy, falta de memória, reinício do
        # worker) no modo servidor: o SEI nunca recusou nada. Volta para a fila, se
        # ainda houver tentativa, em vez de virar falha por um motivo que não é da
        # busca.
        if (_modo_servidor(cx, b["usuario_id"], b["instancia"])
                and pode_repetir(cx, b["id"])
                and reenfileirar(cx, b["id"], "o executor parou no meio da execução",
                                 agora_dt)):
            n += 1
            continue
        # COM GUARDA DE ESTADO, pelo mesmo motivo de cima e com um efeito pior sem
        # ela: medido na revisão, a segunda varredura simultânea desfazia a nova
        # tentativa que a primeira acabara de agendar, gravando 'falhou' por cima.
        if cx.execute("""UPDATE busca SET estado='falhou', motivo=?, terminada_em=?
                         WHERE id=? AND estado IN ('entregue','em_curso')""",
                      ((f"o executor de busca deste servidor não devolveu resultado "
                        f"em {SEGUNDOS_TETO // 60} min"
                        if _modo_servidor(cx, b["usuario_id"], b["instancia"]) else
                        f"a estação pegou o pedido e não devolveu resultado em "
                        f"{SEGUNDOS_TETO // 60} min"), agora(), b["id"])).rowcount == 1:
            _destravar(cx, b["instancia"], b["conta"], b["id"])
            n += 1
    return n
