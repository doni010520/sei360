# -*- coding: utf-8 -*-
"""
Resumo de processo por IA — chave de API, o que vai no prompt, e o que não vai.

A DECISÃO QUE VEM ANTES DO CÓDIGO
---------------------------------
Resumir processo com IA significa mandar o conteúdo dele para fora. Nesta base,
o conteúdo inclui `especificacao` (88% preenchida) e `anotacao` (23%) — texto
livre escrito por servidor, em contexto de saúde, onde nome de paciente aparece.
Mandar isso para uma API de terceiro é tratamento de dado pessoal por operador, e
se o provedor estiver fora do país é transferência internacional (LGPD art. 33).

Por isso existem DOIS níveis, e o padrão é o restrito:

  * `estruturado` (padrão) — vão só campos que o próprio SEI já classifica: tipo,
    assunto, marcador, unidade, datas, contagens, situação. Nenhum texto livre.
    O resumo fica mais pobre e não vaza nome de ninguém.
  * `completo` — inclui especificação e anotação. Só liga com aceite explícito,
    registrado, e a tela diz exatamente o que passa a sair daqui.

O resumo NUNCA substitui o texto do órgão na tela: ele é leitura auxiliar, e a
interface tem de deixar isso claro. E todo resumo carrega `descrito_em` — a data
da COLETA que ele descreve —, porque um resumo de três dias atrás pode estar
falando de um processo que já saiu da unidade.
"""
import json
import re
import os
import urllib.error
import urllib.request

from banco import agora, registrar

# Um só provedor por enquanto. A estrutura existe para a tela não mentir dizendo
# "escolha o provedor" quando não há escolha, e para o dia em que houver não
# exigir reescrever nada.
PROVEDORES = {
    "anthropic": {
        "nome": "Anthropic (Claude)",
        "url": "https://api.anthropic.com/v1/messages",
        "modelos": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"],
        "padrao": "claude-haiku-4-5",
        "pais": "Estados Unidos",
        "doc": "https://console.anthropic.com/settings/keys",
        # Dólar por MILHÃO de tokens (entrada, saída). Serve para o teto de gasto
        # e para a tela dizer o preço ANTES de gastar. Estimativa declarada como
        # estimativa: a conta que vale é a do provedor.
        "preco": {"claude-haiku-4-5": (1.00, 5.00),
                  "claude-sonnet-5": (3.00, 15.00),
                  "claude-opus-5": (15.00, 75.00)},
    },
}

# Teto de gasto por rodada, em dólares. Existe porque um lote de 50 processos com
# o modelo errado escolhido por engano é a diferença entre centavos e dezenas de
# dólares — e o clique é o mesmo. O limite para a rodada; não bloqueia o sistema.
TETO_RODADA_USD = 2.00


def custo_usd(modelo, entrada, saida):
    """Custo estimado de uma chamada. Estimativa, e a tela diz que é."""
    preco = PROVEDORES["anthropic"]["preco"].get(modelo)
    if not preco:
        return None
    return entrada / 1e6 * preco[0] + saida / 1e6 * preco[1]

NIVEIS = {
    "estruturado": {
        "rotulo": "Somente campos estruturados",
        "descricao": "Tipo, assunto, marcador, unidade, datas e contagens. Nenhum texto "
                     "escrito por servidor, e nenhum nome de pessoa, sai do SEI360.",
        # `atribuido_nome` SAIU. Ele é o nome civil do servidor, e a descrição
        # logo acima promete que nenhum texto escrito por servidor sai daqui — a
        # frase e o código diziam coisas diferentes, e a frase é o que a pessoa lê
        # antes de aceitar a transferência internacional. O resumo não precisa
        # saber de QUEM é o processo para dizer DO QUE ele trata.
        # `visualizado`, `origem`, `mesa_coleta` e `marco_unidade` SAIRAM.
        #
        # Os quatro dependem de QUEM olha ou de QUAL mesa coletou, e o resumo
        # atravessa pessoas: `resumo` tem id_sei como chave, sem dono. Dentro de
        # uma frase, "processo novo, ainda nao visualizado" ou "gerado nesta
        # unidade" viram afirmacoes sobre a visao de OUTRA pessoa — plausiveis,
        # sem coluna nenhuma na tela que denuncie a procedencia.
        #
        # `origem` e o pior deles: e calculada contra as mesas da CONTA de quem
        # coletou. Para quem tivesse so a CESS, 263 dos 387 "Gerados" de 20/08
        # seriam "Recebidos" — 23% da base trocando de rotulo conforme quem roda.
        #
        # O que sobra descreve o PROCESSO, que e o que o resumo tem de dizer.
        "campos": ["tipo_processo", "assuntos", "marcador", "autuacao",
                   "documentos", "movimentos", "nivel_acesso"],
    },
    "completo": {
        "rotulo": "Estruturados + especificação e anotação",
        "descricao": "Inclui o texto livre escrito pelos servidores. É onde costuma estar "
                     "o que o processo realmente é — e também onde pode haver nome de "
                     "paciente. Exige aceite registrado.",
        # `acompanhamento` SAIU. E o unico campo que o desenho do poco proibe de
        # atravessar pessoa — nao esta provado que a tela do SEI nao recorta por
        # usuario, e na CESS ha grupos com nome de pessoa alimentados so por ela.
        # O resumo atravessa pessoas por construcao (`resumo` tem id_sei como chave,
        # sem dono), entao manda-lo ao provedor e depois exibi-lo a um colega e
        # exatamente o que o poco se recusa a fazer. O rotulo do aceite ja dizia
        # "especificacao e anotacao"; era o codigo que dizia outra coisa.
        "campos": ["especificacao", "anotacao"],
    },
}

INSTRUCAO = (
    "Você resume processos administrativos do SEI para uma tela de triagem. "
    "Escreva em português do Brasil, na voz de quem trabalha na unidade.\n"
    "Devolva JSON: {\"curto\": \"...\", \"longo\": \"...\"}.\n"
    "- curto: uma linha de até 120 caracteres dizendo do que o processo trata. "
    "Sem preâmbulo, sem repetir o número do processo.\n"
    "- longo: até 3 frases sobre o que está em jogo e o que parece pendente.\n"
    "Use SOMENTE os campos fornecidos. Não invente valor, prazo, nome ou conclusão "
    "que não esteja nos dados. Se os campos não permitirem dizer do que se trata, "
    "escreva exatamente: \"dados insuficientes para resumir\"."
)


def ler_config(cx):
    r = cx.execute("SELECT * FROM config_ia WHERE id=1").fetchone()
    if not r:
        return {"ativo": 0, "provedor": "anthropic", "modelo": PROVEDORES["anthropic"]["padrao"],
                "nivel": "estruturado", "tem_chave": False, "aceite_em": None,
                "aceite_por": None, "gerados": 0, "custo_centavos": 0}
    d = dict(r)
    d["tem_chave"] = bool(d.pop("chave", None))
    return d


def guardar_chave(cx, chave, usuario_id, ip=None):
    """A chave da API vai para o mesmo cofre da credencial do SEI.

    Mesma regra: cifrada com AES-256-GCM, chave mestra fora do banco. Chave de
    API é dinheiro — quem a rouba gasta no seu contrato — e por isso não fica em
    texto puro nem aparece de volta em tela nenhuma depois de salva.
    """
    import cofre
    if not cofre.disponivel():
        raise RuntimeError("cofre indisponível: defina SEI360_CHAVE_MESTRA")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64
    k = base64.urlsafe_b64decode(os.environ["SEI360_CHAVE_MESTRA"] + "===")[:32]
    nonce = os.urandom(12)
    blob = AESGCM(k).encrypt(nonce, chave.encode(), b"config_ia")
    cx.execute("""INSERT INTO config_ia(id,chave,nonce) VALUES(1,?,?)
                  ON CONFLICT(id) DO UPDATE SET chave=excluded.chave, nonce=excluded.nonce""",
               (blob, nonce))
    registrar(cx, usuario_id, "guardar_chave_ia", alvo="config_ia", ip=ip)


def abrir_chave(cx):
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    r = cx.execute("SELECT chave, nonce FROM config_ia WHERE id=1").fetchone()
    if not r or not r["chave"]:
        return None
    k = base64.urlsafe_b64decode(os.environ.get("SEI360_CHAVE_MESTRA", "") + "===")[:32]
    return AESGCM(k).decrypt(r["nonce"], r["chave"], b"config_ia").decode()


# Padrões de identificador direto. Não é anonimização — nome próprio escrito em
# prosa continua passando, e é por isso que o nível "completo" exige aceite. O que
# isto tira é o identificador ESTRUTURADO, que é o que transforma um texto em um
# registro apontando para uma pessoa determinada: CPF, cartão do SUS, matrícula,
# telefone, e-mail. Medido no corpus atual: dos 1.049 resumos, 17 citam "paciente"
# e 1 cita matrícula.
MASCARAS = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF]"),
    (re.compile(r"\b\d{3}\s?\d{4}\s?\d{4}\s?\d{4}\b"), "[CNS]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email]"),
    (re.compile(r"\b(?:\(\d{2}\)\s?)?9?\d{4}-?\d{4}\b"), "[telefone]"),
    (re.compile(r"(?i)\bmatr[íi]cula\s*:?\s*\d+"), "matrícula [n]"),
    (re.compile(r"(?i)\b(?:prontu[áa]rio|registro)\s*:?\s*n?[º°]?\s*\d+"), "prontuário [n]"),
]


def mascarar_texto(v):
    if not isinstance(v, str):
        return v
    for rx, troca in MASCARAS:
        v = rx.sub(troca, v)
    return v


def montar_prompt(processo, nivel):
    """O que sai daqui, campo a campo. Nada além disto.

    MINIMIZAÇÃO: o texto livre é truncado. Um resumo de três frases não precisa
    de 4 KB de anotação, e cada caractere a mais é dado saindo do órgão sem
    contrapartida. Corta em 1.200 caracteres — o suficiente para dizer do que se
    trata, e a marca de corte fica visível para ninguém achar que leu tudo.
    """
    campos = list(NIVEIS["estruturado"]["campos"])
    if nivel == "completo":
        campos += NIVEIS["completo"]["campos"]
    livres = set(NIVEIS["completo"]["campos"])
    dados = {}
    for c in campos:
        v = processo.get(c)
        if v in (None, "", "[]"):
            continue
        if c == "assuntos" and isinstance(v, str):
            try:
                v = "; ".join(json.loads(v))
            except ValueError:
                pass
        if c in livres:
            v = mascarar_texto(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
            if len(v) > LIMITE_TEXTO:
                v = v[:LIMITE_TEXTO] + " […cortado]"
        dados[c] = v
    return dados


LIMITE_TEXTO = 1200


# A pontuação de fechamento entra na classe: "Claro!" sem o "!" deixava a frase
# começando por exclamação, que é pior do que ter deixado o "Claro".
PREAMBULO = re.compile(
    r"(?i)^\s*(claro|certo|com certeza|aqui (?:est[áa]|vai|segue)|segue(?: o| a)?|"
    r"o resumo|resumo(?: do processo)?|em resumo)\b[\s:,.;!\-—]*")


def validar_saida(curto, longo, dados):
    """O que volta do provedor não entra no banco sem passar por aqui.

    Duas coisas, ambas medidas em resumo de verdade: o modelo às vezes devolve
    preâmbulo ("Aqui está o resumo:") e às vezes devolve um identificador que
    NÃO estava nos campos enviados — o que só pode ter vindo dele. Identificador
    inventado num campo que a tela apresenta como leitura do processo é o pior
    caso: parece dado do SEI e não é.
    """
    problemas = []
    curto = (curto or "").strip()
    longo = (longo or "").strip()
    # Repete até estabilizar: "Aqui está o resumo:" é DOIS preâmbulos encaixados,
    # e uma passada só deixava "o resumo:" na tela — pior que não ter mexido,
    # porque parece texto do processo.
    for _ in range(4):
        antes = curto
        curto = PREAMBULO.sub("", curto).lstrip(" :,-—")
        if curto == antes:
            break
        if "preâmbulo removido" not in problemas:
            problemas.append("preâmbulo removido")
    fonte = json.dumps(dados, ensure_ascii=False)
    for rx, rotulo in MASCARAS[:2]:            # CPF e CNS: identificador direto
        for achado in rx.findall(longo + " " + curto):
            if achado not in fonte:
                problemas.append(f"identificador ausente da fonte ({rotulo})")
    curto = mascarar_texto(curto)[:160]
    longo = mascarar_texto(longo)
    return curto, longo, problemas


def resumir(chave, modelo, dados, tempo_limite=45):
    """Uma chamada, um processo. Devolve (curto, longo, tokens) ou levanta."""
    corpo = json.dumps({
        "model": modelo,
        "max_tokens": 400,
        "system": INSTRUCAO,
        "messages": [{"role": "user",
                      "content": json.dumps(dados, ensure_ascii=False, indent=1)}],
    }).encode()
    req = urllib.request.Request(
        PROVEDORES["anthropic"]["url"], data=corpo,
        headers={"content-type": "application/json", "x-api-key": chave,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=tempo_limite) as r:
        resposta = json.loads(r.read().decode())
    texto = "".join(b.get("text", "") for b in resposta.get("content", []))
    uso = resposta.get("usage", {})
    try:
        # O modelo às vezes embrulha o JSON em cerca de código; extrair em vez de
        # falhar é a diferença entre 3% de perda e 3% de suporte.
        bruto = texto[texto.index("{"): texto.rindex("}") + 1]
        j = json.loads(bruto)
    except (ValueError, IndexError):
        j = {"curto": texto.strip()[:120], "longo": texto.strip()}
    return (j.get("curto", "").strip(), j.get("longo", "").strip(),
            {"entrada": uso.get("input_tokens", 0), "saida": uso.get("output_tokens", 0),
             "total": uso.get("input_tokens", 0) + uso.get("output_tokens", 0)})


def testar(cx, usuario_id, ip=None):
    """Uma chamada mínima, para provar que a chave funciona antes de gastar."""
    chave = abrir_chave(cx)
    if not chave:
        return False, "Nenhuma chave de API guardada."
    cfg = ler_config(cx)
    try:
        curto, _, uso = resumir(chave, cfg["modelo"],
                                {"tipo_processo": "Ofício", "assuntos": "Teste de conexão",
                                 "mesa_coleta": "TESTE"}, tempo_limite=30)
        registrar(cx, usuario_id, "testar_ia", alvo=cfg["modelo"], ip=ip)
        return True, (f"Chave válida. Modelo {cfg['modelo']} respondeu "
                      f"({uso['total']} tokens).")
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode()[:200]
        motivo = {401: "chave recusada pelo provedor", 429: "limite de uso atingido",
                  400: "requisição inválida"}.get(e.code, f"erro {e.code}")
        return False, f"{motivo}. {detalhe}"
    except Exception as e:                                   # noqa: BLE001
        return False, f"Não consegui falar com o provedor: {type(e).__name__}"
