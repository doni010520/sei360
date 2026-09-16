# -*- coding: utf-8 -*-
"""
O QUE A SAÍDA DO COLETOR DIZ — lida por quem não estava olhando.

POR QUE ISTO EXISTE
-------------------
`coletor_sesab.py` escreve tudo o que sabe no stdout: o que o SEI respondeu ao
login, quantos processos cada mesa declarou e quantos foram lidos, que mesa
falhou e por quê. Quem o chama (`coleta.py`, `atendente.py`,
`acompanhamento_servidor.py`) guardava disso um código de saída e uma cauda de
300 caracteres — e em 16/09/2026 três perguntas sem resposta custavam uma manhã:

  * por que o login da Letícia falha? O código era 3 e a cauda era o banner do
    motor JS. O SEI tinha dito o motivo, e ninguém guardou;
  * a UMA-CMA caiu de 298 para 205 processos de verdade, ou a coleta veio pela
    metade? A saída trazia "a tela declara N", linha por linha, e foi jogada fora;
  * a execução "concluída" com código 1 terminou bem ou mal?

Este módulo não decide nada sobre o SEI: ele LÊ o texto que já existe e o
devolve em forma de causa (uma chave estável e uma frase), de linhas que
importam e de contagem por mesa. Quem decide é quem chama.

O QUE ELE NÃO FAZ
-----------------
Não adivinha. Login que não concluiu sem nenhuma mensagem do SEI é
`login_sem_resposta`, com `certeza=False` — pode ser senha, pode ser o SEI lento —
e quem chama trata os dois casos de forma diferente: recusa certa para de tentar
até a senha ser salva de novo; recusa incerta só não repete na mesma janela.
"""
import json
import re

# ----------------------------------------------------------------- limpeza
# O motor JS escreve com `console.log('%c[SEI] …', 'color:#…;font-weight:bold')`,
# e o Playwright entrega o texto com o `%c` e o estilo grudados.
_ESTILO = re.compile(r"%c|\s*color:#[0-9a-fA-F]{3,8};?\s*(?:font-weight:\s*\w+;?)?")
_COR_ERRO = "#a3391f"                                   # `erro()` de automacao_sei.js
_RELOGIO = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")


def limpa(linha):
    """A linha sem o `%c`, sem o estilo e sem espaço sobrando."""
    return " ".join(_ESTILO.sub(" ", str(linha or "")).split())


# ---------------------------------------------------------- o que o SEI disse
_DISSE = "LOGIN_SEI_DISSE "
_DIALOGO = re.compile(r"dialog>\s*(?:\w+:\s*)?(.+)$")


def mensagem_do_sei(saida):
    """(textos, sinais) do que a tela de login mostrou quando o login falhou.

    `textos` são as frases que o SEI escreveu (caixa de alerta do navegador ou
    aviso na página); `sinais` é o que a ESTRUTURA da tela mostrou — campo de
    código (segundo fator), CAPTCHA — e vem do coletor, que olhou a página.
    """
    textos, sinais = [], {}
    for bruta in (saida or "").splitlines():
        linha = bruta.strip()
        # PROCURA, não "começa com": o prefixo do relógio é do `log()` do coletor
        # hoje, e o dia em que ele mudar não pode apagar a resposta do SEI.
        i = linha.find(_DISSE)
        if i >= 0:
            try:
                d = json.loads(linha[i + len(_DISSE):])
                textos += [str(t) for t in (d.get("textos") or []) if t]
                sinais = {k: d.get(k) for k in ("captcha", "codigo", "url")}
            except (ValueError, AttributeError):
                continue
            continue
        m = _DIALOGO.search(linha)
        if m and m.group(1).strip():
            textos.append(m.group(1).strip())
    vistos, unicos = set(), []
    for t in textos:
        t = " ".join(t.split())[:240]
        if t.lower() not in vistos:
            vistos.add(t.lower())
            unicos.append(t)
    return unicos, sinais


# ------------------------------------------------------------------- a causa
# Chaves de causa em que o SEI NÃO deixou entrar. `coleta_servidor` as consulta
# para não repetir a mesma janela; as `certeza=True` também param os motores até
# a senha ser salva de novo (`cofre.marcar_recusa`).
CAUSAS_DE_LOGIN = ("login_recusado", "conta_bloqueada", "senha_expirada", "segundo_fator",
                   "captcha", "login_sem_resposta")

_EXPIRADA = re.compile(r"senha[^.]{0,40}expirad|expirad[^.]{0,40}senha|alter(?:e|ar) (?:a )?(?:sua )?senha",
                       re.I)
_BLOQUEIO = re.compile(r"bloquead|suspens|desativad|inativ", re.I)
_RECUSA = re.compile(r"inv[aá]lid|incorret|n[aã]o confere|n[aã]o encontrad|"
                     r"n[aã]o autorizad|tentativas|senha", re.I)
# SÓ EM FRASE QUE O SEI ESCREVEU NA HORA (alerta, aviso) — nunca no texto fixo da
# tela: a página de login do SEI Bahia fala de "Autenticação em dois fatores" em
# TODO acesso, e casar por ele dava segundo fator em todo login (a mesma
# armadilha que `pedindoCodigo`, em automacao_sei.js, já documenta).
_2FA = re.compile(r"\b2FA\b|segundo fator|c[oó]digo (?:de )?(?:acesso|verifica[cç][aã]o|"
                  r"autentica[cç][aã]o|seguran[cç]a)", re.I)
_ALERTA_OK = re.compile(r"ATENCAO|ATENÇÃO|falhou|ficou de fora|INCOMPLETA|MENOR que|"
                        r"leitura incompleta|disjuntor", re.I)


def _ultima_linha_util(saida):
    for linha in reversed((saida or "").splitlines()):
        t = limpa(_RELOGIO.sub("", linha.strip()))
        if t and "SEIAuto" not in t and not t.startswith(("page> [SEI] ▶", "page> [SEI] Comandos")):
            return t[:200]
    return ""


def causa(codigo, saida, estado=None):
    """{'chave', 'texto', 'certeza'} — a causa do fim desta execução.

    `texto` é para gente ler: no /admin, no alerta, na tela de configuração.
    Nunca carrega segredo — o coletor não imprime senha, e o que o SEI escreve na
    tela de login não repete a senha digitada.
    """
    s = saida or ""
    if codigo == 3:
        if "nenhuma credencial guardada" in s:
            return {"chave": "sem_credencial", "certeza": True,
                    "texto": "não há senha do SEI guardada no servidor para esta instalação"}
        if s.startswith("cofre:"):
            return {"chave": "cofre", "certeza": True,
                    "texto": "o cofre não abriu a credencial: " + s[len("cofre:"):].strip()[:160]}
        textos, sinais = mensagem_do_sei(s)
        disse = " / ".join(textos)
        citacao = f" O SEI disse: “{disse}”." if disse else ""
        if (sinais.get("codigo") or re.search(r"2FA: digite o codigo", s)
                or any(_2FA.search(t) for t in textos)):
            return {"chave": "segundo_fator", "certeza": True,
                    "texto": "o SEI pediu o código do segundo fator (2FA), e a coleta no "
                             "servidor não tem quem o digite." + citacao}
        if sinais.get("captcha") or any(re.search(r"captcha", t, re.I) for t in textos):
            return {"chave": "captcha", "certeza": True,
                    "texto": "o SEI pediu CAPTCHA no login — em geral depois de várias "
                             "tentativas erradas." + citacao}
        if any(_EXPIRADA.search(t) for t in textos):
            return {"chave": "senha_expirada", "certeza": True,
                    "texto": "o SEI diz que a senha expirou: ela precisa ser trocada no "
                             "próprio SEI e salva de novo aqui." + citacao}
        if any(_BLOQUEIO.search(t) for t in textos):
            return {"chave": "conta_bloqueada", "certeza": True,
                    "texto": "o SEI diz que a conta está bloqueada ou inativa." + citacao}
        if any(_RECUSA.search(t) for t in textos):
            return {"chave": "login_recusado", "certeza": True,
                    "texto": "o SEI recusou o usuário ou a senha." + citacao}
        return {"chave": "login_sem_resposta", "certeza": False,
                "texto": "o login não concluiu em 60 s e o SEI não mostrou mensagem — "
                         "senha errada, segundo fator ou SEI lento." + citacao}
    if codigo == 5:
        return {"chave": "relogio", "certeza": True,
                "texto": "o coletor foi encerrado pelo relógio (tempo máximo da coleta)"}
    if codigo is not None and (codigo < 0 or codigo == 137):
        return {"chave": "memoria", "certeza": True,
                "texto": "o navegador foi encerrado pelo sistema — provável falta de "
                         "memória no servidor"}
    if codigo == 4:
        return {"chave": "infra", "certeza": True,
                "texto": "falha de infraestrutura (navegador, rede ou arquivo do motor)"
                         + (f": {_ultima_linha_util(s)}" if _ultima_linha_util(s) else "")}
    if codigo == 2 or estado == "sem_dados":
        extra = ""
        m = re.search(r"\[(sem arquivo de coleta para publicar|ingestão recusou:[^\]]*)\]", s)
        if m:
            extra = f": {m.group(1)}"
        return {"chave": "sem_dados", "certeza": True,
                "texto": "entrou no SEI, mas a coleta não produziu o que publicar" + extra}
    if codigo in (0, 1):
        alertas = [l for l in linhas_chave(s, limite=80) if _ALERTA_OK.search(l)]
        if alertas:
            return {"chave": "ok_com_alerta", "certeza": True,
                    "texto": "coletou com alerta: " + " · ".join(alertas[-3:])[:300]}
        return {"chave": "ok", "certeza": True, "texto": "coletou sem alerta"}
    if codigo is None:
        return {"chave": "executor", "certeza": True,
                "texto": (s or "o executor falhou antes do coletor")[:200]}
    return {"chave": "desconhecida", "certeza": False,
            "texto": f"o coletor saiu com código {codigo}"
                     + (f": {_ultima_linha_util(s)}" if _ultima_linha_util(s) else "")}


# ------------------------------------------------------- as linhas que importam
# SEM "credencial recebida": aquela linha traz o login do SEI por extenso, e o
# /admin mostra login mascarado. O arquivo inteiro (só admin) continua com ela.
_CHAVE = re.compile(
    r"LOGIN|login ok|dialog>|instalacao:|orgao selecionado|"
    r"trocando para|a tela declara|INCOMPLETA|lista: \d+|listas: |por mesa:|detalhe: |"
    r"ATENCAO|ATENÇÃO|falhou|ficou de fora|MENOR que|exportado|registros ->|com mesas:|"
    r"Traceback|Error|erro|morto pelo|sem arquivo|ingestão recusou|MESA_ORIGEM|"
    + re.escape(_COR_ERRO), re.I)


def linhas_chave(saida, limite=40):
    """As linhas que contam a história, limpas e na ordem — sem o banner, sem o ruído."""
    fora = []
    for bruta in (saida or "").splitlines():
        if not _CHAVE.search(bruta):
            continue
        if bruta.lstrip().startswith(("BUSCA_OK ", "ACOMP_OK ", "TESTE_OK ")):
            continue
        t = limpa(bruta)
        if t and (not fora or fora[-1] != t):
            fora.append(t[:300])
    return fora[-limite:]


# ------------------------------------------------------------ por mesa
_TROCA = re.compile(r"trocando para (.+?)(?:…|\.\.\.)")
_LISTA = re.compile(r"\b(Detalhado|Recebidos|Gerados): (\d+) linha\(s\) em (\d+) pagina\(s\)"
                    r"(?: \(a tela declara (\d+)\))?")
_INCOMPLETA = re.compile(r"\b(Detalhado|Recebidos|Gerados): a tela declara (\d+) processo\(s\) "
                         r"e a leitura trouxe (\d+)")


def por_mesa(saida):
    """{mesa: {'lidas', 'declaradas', 'incompleta', 'listas'}} da fase de LISTAGEM.

    É a prova que decide um snapshot retido por queda: se a própria tela do SEI
    declara 205 e a coleta leu 205, a unidade esvaziou mesmo; se declara 298 e
    leu 205, a leitura veio pela metade. Só a primeira passada por mesa conta —
    na fase de detalhe o coletor troca de mesa de novo, sem listar.
    """
    mesas, atual = {}, None
    for bruta in (saida or "").splitlines():
        t = limpa(bruta)
        m = _TROCA.search(t)
        if m:
            nome = m.group(1).strip()
            atual = nome if nome not in mesas else None      # 2ª passada: detalhe
            if atual:
                mesas[atual] = {"lidas": 0, "declaradas": None, "incompleta": False,
                                "listas": []}
            continue
        if not atual:
            continue
        m = _LISTA.search(t)
        if m:
            reg = mesas[atual]
            lidas = int(m.group(2))
            decl = int(m.group(4)) if m.group(4) else None
            reg["lidas"] += lidas
            if decl is not None:
                reg["declaradas"] = (reg["declaradas"] or 0) + decl
                if lidas < decl:
                    reg["incompleta"] = True
            reg["listas"].append({"lista": m.group(1), "lidas": lidas, "declaradas": decl,
                                  "paginas": int(m.group(3))})
            continue
        if _INCOMPLETA.search(t):
            mesas[atual]["incompleta"] = True
    return mesas


def resumo(publicado, c, saida, limite=1800):
    """O texto de `execucao.log_resumo`: o que foi publicado, a causa e as linhas-chave.

    A causa vem PRIMEIRO. O /admin mostra o começo desta coluna, e o começo era
    "não publicado · " seguido de banner.
    """
    cabeca = (f"publicado {publicado}" if publicado else "não publicado") + f" · {c['texto']}"
    corpo = " | ".join(linhas_chave(saida, limite=25))
    return (cabeca + (f" ‖ {corpo}" if corpo else ""))[:limite]
