# -*- coding: utf-8 -*-
"""
Quem decide se ha coleta devida e o SERVIDOR — o agente so pergunta.

Por que a decisao mora aqui e nao na estacao: o Task Scheduler dispara a cada 30
minutos porque a maquina pode estar desligada no horario exato da janela. Se cada
disparo virasse uma coleta, seriam 20 coletas por dia contra a PRODEB a partir de
um unico login. A janela e um COMPROMISSO com tolerancia, nao um alarme.

O agente ainda assim guarda um teto local proprio (ver agente/): e o unico limite
que sobrevive ao comprometimento do servidor.
"""
import re
from datetime import datetime, date, timedelta

from banco import TZ

FERIADOS_FIXOS = {  # nacionais + Bahia
    (1, 1): "Confraternização Universal",
    (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalho",
    (7, 2): "Independência da Bahia",
    (9, 7): "Independência",
    (10, 12): "Nossa Senhora Aparecida",
    (11, 2): "Finados",
    (11, 15): "Proclamação da República",
    (11, 20): "Consciência Negra",
    (12, 25): "Natal",
}


def pascoa(ano: int) -> date:
    """Meeus/Jones/Butcher. Calculada, nao tabelada: lista chumbada de feriado
    vence sem avisar e o painel passa a cobrar coleta em ponto facultativo."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f, g = (b + 8) // 25, (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados(ano: int) -> dict:
    p = pascoa(ano)
    moveis = {
        p - timedelta(days=48): "Carnaval",
        p - timedelta(days=47): "Carnaval",
        p - timedelta(days=2): "Sexta-Feira Santa",
        p + timedelta(days=60): "Corpus Christi",
    }
    fixos = {date(ano, m, d): nome for (m, d), nome in FERIADOS_FIXOS.items()}
    return {**fixos, **moveis}


def dia_util(d: date) -> bool:
    return d.weekday() < 5 and d not in feriados(d.year)


def _campo(cfg, nome, padrao=None):
    """cfg tanto e um sqlite3.Row (producao) quanto um dict (teste). Row nao tem
    .get() e levanta IndexError; dict levanta KeyError."""
    try:
        v = cfg[nome]
    except (KeyError, IndexError):
        return padrao
    return padrao if v is None else v


# Ate 60 minutos, sempre dentro da tolerancia padrao de 90. Espalhar alem dela
# transformaria escalonamento em janela perdida.
DESVIO_MAX_MIN = 60


def desvio_do_agente(agente_id, teto=DESVIO_MAX_MIN):  # noqa: D401
    """Quantos minutos DEPOIS da janela esta estacao acorda.

    Derivado do id, nao sorteado: a mesma estacao acorda sempre no mesmo minuto.
    Sorteio a cada corrida faria a janela mudar de lugar todo dia e a tolerancia
    virar loteria. `hash()` do Python nao serve — ele e randomizado por processo
    desde a 3.3, entao dois workers do gunicorn discordariam sobre a mesma janela.
    """
    if agente_id is None:
        return 0
    import hashlib
    h = hashlib.sha256(str(agente_id).encode()).digest()
    return int.from_bytes(h[:2], "big") % max(1, teto)


def janelas_do_dia(cfg_janelas, quando: datetime, desvio_min: int = 0):
    """Pares (BASE, ACORDAR) das janelas configuradas para o dia de `quando`.

    BASE e a IDENTIDADE da janela — o horario configurado, que vai para
    `execucao.janela` e casa com o que ja esta gravado. ACORDAR e BASE mais o
    desvio do escalonamento, e serve so para comparacoes de TEMPO.

    Separar as duas nao e purismo. Enquanto a chave gravada era o horario
    deslocado, mudar a tolerancia no /admin movia a chave no meio do dia: a coleta
    ja feita deixava de casar, o servidor acusava "janela perdida" contra uma
    estacao que coletou e entregava a mesma carteira de novo.

    Entrada malformada e IGNORADA em vez de estourar: um "07h30" digitado num
    unico agendamento derrubava a varredura de TODOS os agentes — e a tela onde se
    conserta o horario e uma das que chamam a varredura.
    """
    saida = []
    for hhmm in cfg_janelas:
        m_ = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(hhmm or ""))
        if not m_:
            continue
        h, m = int(m_.group(1)), int(m_.group(2))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            continue
        base = quando.replace(hour=h, minute=m, second=0, microsecond=0)
        # O desvio nao pode atravessar a meia-noite: a janela cairia sempre no
        # futuro, nunca ficaria devida, nunca viraria perdida, e a tela diria
        # "proxima janela as 00:25" para sempre.
        limite = base.replace(hour=23, minute=59)
        saida.append((base, min(base + timedelta(minutes=desvio_min), limite)))
    return sorted(saida)


def janela_devida(cfg, agora_dt=None, ja_concluidas=()):
    """Devolve (janela_iso, motivo) da coleta devida, ou (None, motivo).

    `ja_concluidas` sao as janelas (ISO) que ja terminaram bem hoje.
    """
    agora_dt = agora_dt or datetime.now(TZ)
    if not cfg["ativo"]:
        return None, cfg["motivo_inativo"] or "agendamento desarmado"
    hoje = agora_dt.date()
    if cfg["dias"] == "uteis" and not dia_util(hoje):
        nome = feriados(hoje.year).get(hoje)
        return None, f"hoje não é dia útil ({nome or 'fim de semana'})"

    import json
    tol = timedelta(minutes=cfg["tolerancia_min"])
    candidata, motivo = None, "nenhuma janela vencida ainda hoje"
    # TETO FIXO, nao a tolerancia: com o cap por tolerancia, editar a tolerancia
    # no /admin mudava o desvio — e, quando o desvio entrava na chave, mudava a
    # identidade da janela no meio do dia.
    desvio = desvio_do_agente(_campo(cfg, "agente_id"))
    for base, acordar in janelas_do_dia(json.loads(cfg["janelas"]), agora_dt, desvio):
        iso = base.isoformat(timespec="seconds")     # a IDENTIDADE e a base
        if acordar > agora_dt:
            motivo = f"próxima janela às {acordar:%H:%M}"
            break
        if iso in ja_concluidas:
            motivo = f"janela de {base:%H:%M} já coletada"
            continue
        if agora_dt - acordar > tol:
            # Passou da tolerancia: nao adianta coletar as 11h o que era para as
            # 7h30 — o dado ja e outro e a janela seguinte esta perto. Vira alerta,
            # nao tarefa.
            motivo = (f"janela de {base:%H:%M} perdida "
                      f"(fora da tolerância de {cfg['tolerancia_min']} min)")
            continue
        candidata = iso
        motivo = (f"janela de {base:%H:%M} devida"
                  + (f" (esta estação acorda às {acordar:%H:%M})" if desvio else ""))
    return candidata, motivo


def com_fuso(iso: str):
    """datetime SEMPRE com fuso.

    `fromisoformat` aceita '2026-08-19T07:45:00' sem offset, e subtrair um naive
    de um aware levanta TypeError. Como `estado_coleta()` e chamada na tela de
    login, no painel, no admin e no /saude, UMA linha sem offset no banco
    derrubaria o sistema inteiro — inclusive a porta de entrada.
    """
    d = datetime.fromisoformat(iso)
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def idade(coletado_em: str, agora_dt=None):
    """Semaforo da idade do snapshot, em DIAS UTEIS.

    Contar em dias corridos pintaria de vermelho toda segunda-feira de manha, e
    quem opera aprenderia a ignorar o vermelho — que e o pior desfecho possivel
    para um alerta.
    """
    agora_dt = agora_dt or datetime.now(TZ)
    quando = com_fuso(coletado_em)
    uteis, d = 0, quando.date()
    while d < agora_dt.date():
        d += timedelta(days=1)
        if dia_util(d):
            uteis += 1
    horas = (agora_dt - quando).total_seconds() / 3600
    if uteis == 0:
        return "verde", f"coletado hoje às {quando:%H:%M}"
    if uteis == 1:
        return "amarelo", f"último dia útil ({quando:%d/%m %H:%M})"
    return "vermelho", f"{uteis} dias úteis atrás ({quando:%d/%m %H:%M}, {int(horas)}h)"
