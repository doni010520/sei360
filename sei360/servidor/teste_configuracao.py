# -*- coding: utf-8 -*-
"""
Percorre o assistente de configuração como um usuário faria, ponta a ponta.

Por que separado do testes.py: aquele prova regra de negócio e fronteira; este
prova o CAMINHO de quem chega sem nada configurado e precisa sair daqui com a
coleta agendada. É o percurso que decide se o sistema serve para várias pessoas
ou continua sendo a automação de uma estação só.

Cobre também o cofre: guardar, decifrar, trocar de modo e apagar. O que ele NÃO
faz é entrar no SEI de verdade — isso é o botão "Testar acesso", que gasta uma
tentativa de login real e não cabe numa suíte automática.

    python teste_configuracao.py
"""

# ---------------------------------------------------------------------------
# ISOLAMENTO — antes de qualquer import do projeto.
# Esta suíte roda contra uma CÓPIA do banco e contra um servidor próprio, em
# porta própria. Antes ela escrevia no banco de trabalho, e o efeito foi medido:
# a procedência dos seis snapshots correntes passou a apontar para um arquivo
# temporário de teste em vez da coleta real, além de dezenas de contas `t.*`
# residuais. Teste não suja o banco de quem trabalha.
#
# A ordem importa: `banco.py` resolve o caminho do arquivo no import. Chamar
# `isolar()` depois disso não isola nada — por isso a própria função recusa.
# ---------------------------------------------------------------------------
import base64 as _b64, os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from ambiente_teste import isolar, subir_servidor          # noqa: E402
_dir = isolar(__file__)
_chave = _os.environ.get("SEI360_CHAVE_MESTRA") or _b64.urlsafe_b64encode(
    _os.urandom(32)).decode().rstrip("=")
_os.environ["SEI360_CHAVE_MESTRA"] = _chave
BASE, _parar = subir_servidor(_dir, chave_mestra=_chave)
import atexit as _atexit                                    # noqa: E402
_atexit.register(_parar)
print(f"banco isolado : {_dir}")
print(f"servidor      : {BASE}")

import http.cookiejar, json, os, re, sys, urllib.error, urllib.parse, urllib.request
sys.stdout.reconfigure(encoding="utf-8")

CONTA, SENHA_PAINEL = "gestor@sei360.local", "painel-sesab-2026"
SENHA_SEI_FALSA = "senha-de-teste-do-sei-9137"
ok, falhas = 0, []


def checar(nome, cond, det=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {det}")


jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def pegar(caminho, dados=None):
    corpo = urllib.parse.urlencode(dados, doseq=True).encode() if dados else None
    try:
        r = op.open(urllib.request.Request(BASE + caminho, data=corpo), timeout=25)
        return r.status, r.read().decode("utf-8", "replace"), r.url
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), caminho


def csrf():
    return next((c.value for c in jar if c.name == "sei360_csrf"), "")


def prosa(html):
    """HTML com o espaço em branco colapsado.

    Procurar frase no HTML cru dá falso negativo toda vez que ela cai numa quebra
    de linha do template — foi o que aconteceu com "nunca chega ao servidor",
    partido entre "ao" e "servidor". Teste que acusa erro onde não há é pior que
    teste nenhum: ensina a ignorar a falha.
    """
    return re.sub(r"\s+", " ", html)


# Zera a configuração DESTE usuário. Sem isso a suíte só passa na primeira
# execução: a segunda encontra tudo pronto e nunca exercita o caminho de quem
# chega sem nada — que é justamente o que ela existe para provar.
from banco import agora, conectar                                     # noqa: E402
import cofre                                                   # noqa: E402


# A suíte decifra o que o SERVIDOR cifrou, então precisa da MESMA chave mestra.
# Sem isso ela testaria dois cofres diferentes e acusaria falha onde não há.
if not cofre.disponivel():
    sys.exit("defina SEI360_CHAVE_MESTRA com a MESMA chave do servidor antes de rodar")
_cx = conectar()
_u = _cx.execute("SELECT id FROM usuarios WHERE email=?", (CONTA,)).fetchone()
UID = _u["id"] if _u else None
if UID:
    _cx.execute("DELETE FROM config_usuario WHERE usuario_id=?", (UID,))
    _cx.execute("DELETE FROM credencial WHERE usuario_id=?", (UID,))
    _cx.execute("DELETE FROM enrolamentos WHERE agente_id IN "
                "(SELECT id FROM agentes WHERE dono_usuario_id=?)", (UID,))
    _cx.execute("DELETE FROM agentes WHERE dono_usuario_id=?", (UID,))
    _cx.commit()
_cx.close()

print(f"cofre: {'disponível' if cofre.disponivel() else 'INDISPONÍVEL (falta SEI360_CHAVE_MESTRA)'}\n")

# A senha é DEFINIDA na cópia, não presumida do banco de trabalho. Antes, trocar
# a senha do gestor por qualquer motivo derrubava 15 verificações com "E-mail ou
# senha incorretos" — uma mensagem que não aponta para a causa.
import seguranca as _seg_cfg                                     # noqa: E402
_cx = conectar()
_h, _s = _seg_cfg.hash_senha(SENHA_PAINEL)
_n = _cx.execute("""UPDATE usuarios SET senha_hash=?, senha_sal=?, senha_trocada_em=?,
                    falhas_seq=0, bloqueado_ate=NULL, ativo=1 WHERE email=?""",
                 (_h, _s, agora(), CONTA)).rowcount
if not _n:
    _cx.execute("""INSERT INTO usuarios(email,nome,senha_hash,senha_sal,papel,origem,
                   criado_em,ativo,senha_trocada_em) VALUES(?,?,?,?,'gestor','teste',?,1,?)""",
                (CONTA, "Gestor de teste", _h, _s, agora(), agora()))
_cx.commit(); _cx.close()

print("1. chegar sem nada configurado")
pegar("/entrar")
s, corpo, _ = pegar("/entrar", {"email": CONTA, "pw": SENHA_PAINEL, "csrf": csrf()})
checar("login do gestor", s == 200, corpo[:120])
s, cfg, _ = pegar("/configuracao")
checar("assistente abre", s == 200, f"status {s}")
checar("trilha de 4 passos", cfg.count('<li class=') == 4 or cfg.count('class="n"') == 4,
       str(cfg.count('class="n"')))
# Nada decidido ainda: o assistente abre no primeiro passo. Ter valor PADRÃO não
# conta como decidido — senão a trilha ficaria verde sozinha e a pessoa nunca
# veria a pergunta sobre em que horário o robô entra na conta dela.
checar("abre no primeiro passo quando nada foi decidido",
       'name="passo" value="sistema"' in cfg, "não abriu no passo de sistema")
checar("diz em que passo está", "Passo 1 de 4" in cfg, "sem indicador de progresso")

print("\n2. sistema")
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "sistema", "sistema": "SEI-FESF"})
checar("recusa sistema indisponível", "ainda não está disponível" in cfg)
s, cfg, _ = pegar("/configuracao?passo=sistema")
checar("a trilha leva a qualquer passo já resolvido", 'name="passo" value="sistema"' in cfg)
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "sistema", "sistema": "SEI-SESAB"})
checar("aceita SEI-SESAB e volta ao passo pendente",
       'name="passo" value="acesso"' in cfg, "não avançou")

print("\n3. acesso — a pergunta da senha")
s, cfg, _ = pegar("/configuracao?passo=acesso")
checar("explica por que a senha é necessária", "preenchendo login e senha" in cfg)
checar("oferece guardar no servidor", 'value="servidor"' in cfg)
checar("oferece guardar só no computador do usuário", 'value="estacao"' in cfg)
checar("diz o preço de cada opção",
       "mesmo com o seu computador desligado" in prosa(cfg)
       and "nunca chega ao servidor" in prosa(cfg))

s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "acesso",
                                    "modo_coleta": "servidor", "sei_login": "sem-arroba",
                                    "sei_senha": SENHA_SEI_FALSA})
checar("recusa login mal formado", "e-mail institucional completo" in cfg)
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "acesso",
                                    "modo_coleta": "servidor",
                                    "sei_login": "zaine.lima@saude.ba.gov.br"})
checar("no modo servidor, recusa salvar sem senha", "Informe a senha do SEI" in cfg)

s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "acesso",
                                    "modo_coleta": "servidor",
                                    "sei_login": "Zaine.Lima@saude.ba.gov.br",
                                    "sei_senha": SENHA_SEI_FALSA})
checar("aceita e avança para as mesas", 'name="passo" value="mesas"' in cfg, "não avançou")

print("\n4. o cofre por dentro")
cx = conectar()
linha = cx.execute("SELECT * FROM credencial WHERE usuario_id=?", (UID,)).fetchone()
checar("credencial gravada", bool(linha))
if linha:
    checar("segredo NÃO está em texto puro no banco",
           SENHA_SEI_FALSA.encode() not in bytes(linha["segredo"]), "senha legível no blob!")
    checar("algoritmo é AES-256-GCM", linha["algo"] == "AES-256-GCM", str(linha["algo"]))
    checar("nonce de 12 bytes por registro", len(bytes(linha["nonce"])) == 12)
    checar("login normalizado para minúsculas", linha["login"] == "zaine.lima@saude.ba.gov.br",
           str(linha["login"]))
login, senha = cofre.abrir(cx, UID, motivo="teste_automatico")
cx.commit()          # solta o lock antes de qualquer chamada HTTP seguinte
checar("decifra de volta ao valor exato", senha == SENHA_SEI_FALSA)
checar("uso da credencial fica registrado no log de acesso",
       cx.execute("SELECT COUNT(*) FROM log_acesso WHERE acao='usar_credencial' AND usuario_id=?",
                  (UID,)).fetchone()[0] >= 1)
# A cifra é amarrada ao dono: mover o blob para outra conta tem de falhar.
outro = cx.execute("SELECT id FROM usuarios WHERE id<>? AND ativo=1 LIMIT 1", (UID,)).fetchone()
if outro:
    cx.execute("""INSERT INTO credencial(usuario_id,sistema,login,segredo,nonce,algo,criado_em,usos)
                  VALUES(?,?,?,?,?,?,?,0)
                  ON CONFLICT(usuario_id,sistema) DO UPDATE SET segredo=excluded.segredo,
                  nonce=excluded.nonce, login=excluded.login, algo=excluded.algo""",
               (outro["id"], linha["sistema"], linha["login"], linha["segredo"],
                linha["nonce"], linha["algo"], linha["criado_em"]))
    try:
        cofre.abrir(cx, outro["id"], motivo="teste_roubo")
        roubou = True
    except Exception:
        roubou = False
    cx.execute("DELETE FROM credencial WHERE usuario_id=?", (outro["id"],))
    checar("blob copiado para outra conta NÃO decifra (AAD amarra o dono)", not roubou,
           "decifrou credencial de outro usuário!")
cx.commit(); cx.close()

print("\n5. mesas e horários")
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "mesas",
                                    "mesas_modo": "selecionadas"})
checar("recusa 'selecionadas' sem nenhuma marcada", "Escolha ao menos uma mesa" in cfg)
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "mesas", "mesas_modo": "todas"})
checar("aceita todas e avança para horários", 'name="passo" value="horarios"' in cfg)
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "horarios", "janelas": "25:99"})
checar("recusa horário inválido", "Horário inválido" in cfg)
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "horarios",
                                    "janelas": "07:30, 12:00, 19:00"})
checar("recusa mais de dois por dia", "No máximo dois horários" in cfg)
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "horarios",
                                    "janelas": "7:30 19:00", "dias": "uteis"})
checar("aceita, normaliza e conclui", "Tudo pronto" in cfg, "não caiu no resumo")

print("\n6. o que a configuração produziu")
cx = conectar()
ag = cx.execute("SELECT * FROM agentes WHERE dono_usuario_id=?", (UID,)).fetchone()
checar("criou o agente lógico do usuário", bool(ag), "nenhum agente")
if ag:
    checar("agente carrega o login MASCARADO, nunca a senha",
           (ag["credencial_login_mascarado"] or "").startswith("z*"),
           str(ag["credencial_login_mascarado"]))
    agd = cx.execute("SELECT * FROM agendamento WHERE agente_id=?", (ag["id"],)).fetchone()
    checar("agendamento reflete os horários escolhidos",
           agd and json.loads(agd["janelas"]) == ["07:30", "19:00"],
           str(dict(agd)) if agd else "sem agendamento")
    checar("escopo do agente é o das mesas configuradas",
           len(json.loads(ag["unidades_esperadas"] or "[]")) >= 1)
cx.close()

s, cfg, _ = pegar("/configuracao")
checar("resumo mostra onde a senha ficou", "cifrada no SEI360" in cfg)
checar("resumo oferece testar acesso de verdade", "Testar acesso agora" in cfg)
checar("senha NUNCA volta para a tela", SENHA_SEI_FALSA not in cfg)

print("\n7. trocar para o modo estação apaga a senha do servidor")
s, cfg, _ = pegar("/configuracao", {"csrf": csrf(), "passo": "acesso",
                                    "modo_coleta": "estacao",
                                    "sei_login": "zaine.lima@saude.ba.gov.br"})
cx = conectar()
resta = cx.execute("SELECT COUNT(*) FROM credencial WHERE usuario_id=?", (UID,)).fetchone()[0]
apagou = cx.execute("""SELECT COUNT(*) FROM log_acesso WHERE acao='apagar_credencial'
                       AND usuario_id=?""", (UID,)).fetchone()[0]
cx.close()
checar("credencial some do servidor ao escolher a estação", resta == 0)
checar("e o apagamento fica registrado", apagou >= 1)
checar("passa a pedir o pareamento da estação", "Falta parear o seu computador" in cfg)

# E PAREAR TEM DE DESPAUSAR O AGENTE. Quem termina o assistente no modo padrao
# (servidor) ganha um agente logico com `pausado_motivo` preenchido — e o texto
# da pausa manda fazer exatamente uma coisa: instalar o agente na estacao. A
# pessoa fazia, o pareamento emitia o codigo, e o motivo continuava la:
# `aplicar_agendamento` mantinha o agendamento inativo, a coleta das 07h30 nunca
# rodava, e nem alerta havia — janela de agente pausado nao conta como perdida.
cx = conectar()
_ag_antes = cx.execute("SELECT pausado_motivo FROM agentes WHERE dono_usuario_id=?",
                       (UID,)).fetchone()
cx.execute("UPDATE agentes SET pausado_motivo='pausa de teste' WHERE dono_usuario_id=?", (UID,))
cx.commit(); cx.close()
s, _cfg_e, _ = pegar("/configuracao/estacao", {"csrf": csrf(), "nome_estacao": "PC-DA-ZAINE"})
cx = conectar()
_ag = cx.execute("SELECT nome_estacao, pausado_motivo FROM agentes WHERE dono_usuario_id=?",
                 (UID,)).fetchone()
_agd = cx.execute("""SELECT ativo FROM agendamento WHERE agente_id=
                     (SELECT id FROM agentes WHERE dono_usuario_id=?)""", (UID,)).fetchone()
cx.close()
checar("parear a estação renomeia o agente",
       _ag and _ag["nome_estacao"] == "PC-DA-ZAINE", str(dict(_ag)) if _ag else "sem agente")
checar("e TIRA a pausa — senão a coleta diária nunca roda",
       _ag and not _ag["pausado_motivo"],
       f"pausa continua: {_ag['pausado_motivo']!r}" if _ag else "sem agente")

print("\n8. o painel reflete a configuração")
s, painel, _ = pegar("/")
checar("painel abre com o rail de filtros", 'id="rail"' in painel)
checar("menu de conta leva à configuração", 'href="/configuracao"' in painel)

# ---------------------------------------------------------------------------
# AS MESAS SÃO DESCOBERTAS NO SEI, não escolhidas de uma lista do banco.
#
# O modelo estava invertido: a tela oferecia `SELECT DISTINCT unidade FROM
# snapshot` — as unidades que a coleta de OUTRA pessoa já tinha trazido — e o
# vínculo, que é a fronteira do que cada um enxerga, era um ato manual do admin.
# Medido: as 57 contas semeadas tinham ZERO vínculo (ativadas, não veriam nada) e
# a mesma faixa de seis unidades aparecia para todo mundo.
#
# Quais mesas alguém alcança é propriedade da conta DELE no SEI, e só se sabe
# depois que ele entra lá. É o que o projeto já diz de si: o painel é espelho —
# se o SEI não mostraria aquela mesa àquela pessoa, o SEI360 não mostra.
print("\n7. as mesas vêm do SEI, não do banco")
import coleta as _col                                            # noqa: E402
from pathlib import Path as _P                                   # noqa: E402

cx = conectar()
_uid = cx.execute("SELECT id FROM usuarios WHERE email=?", (CONTA,)).fetchone()[0]
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=?", (_uid,))
cx.commit()

# O SEI mostrou três mesas para esta conta.
_novas, _tiradas = _col.sincronizar_unidades(cx, _uid, ["SESAB/A", "SESAB/B", "SESAB/C"])
cx.commit()
_agora = {r["unidade"]: r["origem"] for r in cx.execute(
    "SELECT unidade, origem FROM usuario_unidade WHERE usuario_id=?", (_uid,))}
checar("o que o SEI mostrou vira vínculo", set(_agora) == {"SESAB/A", "SESAB/B", "SESAB/C"},
       str(_agora))
checar("e fica marcado como vindo do SEI",
       all(o == "sei" for o in _agora.values()), str(_agora))

# Um admin concede uma unidade excepcional, à mão.
cx.execute("""INSERT INTO usuario_unidade(usuario_id,unidade,concedida_em,origem)
              VALUES(?,?,?,'admin')""", (_uid, "SESAB/EXCECAO", agora()))
cx.commit()

# Na visita seguinte o SEI já não mostra a B — a pessoa saiu daquela unidade.
_novas, _tiradas = _col.sincronizar_unidades(cx, _uid, ["SESAB/A", "SESAB/C", "SESAB/D"])
cx.commit()
_depois = {r["unidade"]: r["origem"] for r in cx.execute(
    "SELECT unidade, origem FROM usuario_unidade WHERE usuario_id=?", (_uid,))}
checar("unidade nova entra sozinha", "SESAB/D" in _depois, str(sorted(_depois)))
# Quem saiu da unidade no SEI tem de parar de vê-la aqui, e ninguém vai lembrar
# de avisar o sistema.
checar("unidade que sumiu do SEI sai do vínculo", "SESAB/B" not in _depois,
       str(sorted(_depois)))
# E o acesso excepcional do admin NÃO é desfeito por um clique em "Testar acesso":
# seria revogar decisão de outro sem pedir.
checar("o que o admin concedeu à mão permanece",
       _depois.get("SESAB/EXCECAO") == "admin", str(_depois))

# A tela oferece as mesas DA PESSOA — não as que o banco conhece.
import configuracao as _cfg2                                     # noqa: E402
_d = _cfg2.diagnostico(cx, _uid)
_do_banco = {r[0] for r in cx.execute("SELECT DISTINCT unidade FROM snapshot")}
checar("a configuração oferece as mesas do vínculo, não as do snapshot",
       set(_d["unidades"]) == set(_depois) and set(_d["unidades"]) != _do_banco,
       f'oferecidas={sorted(_d["unidades"])} banco={sorted(_do_banco)}')

# Sem descoberta nenhuma, a tela diz POR QUE está vazia e para onde ir.
cx.execute("DELETE FROM usuario_unidade WHERE usuario_id=?", (_uid,))
cx.commit(); cx.close()
s, tela, _ = pegar("/configuracao?passo=mesas")
checar("sem mesas descobertas, a tela explica que elas vêm do SEI",
       "Ainda não sei quais são as suas mesas" in tela
       and "passo=acesso" in tela, f"status {s}")

# E o coletor precisa DEVOLVER as mesas no teste de login — sem isso nada disso
# acontece. O `descobrirMesas` já existia e só era usado na coleta inteira.
_coletor = _P(r"C:\Claude\sei_sistema\painel_sesab\coletor_sesab.py").read_text(
    encoding="utf-8")
checar("o teste de login pede as mesas da conta ao SEI",
       "SEIAuto.descobrirMesas()" in _coletor and '"mesas"' in _coletor)

print(f"\n{'='*58}\n{ok} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
sys.exit(1 if falhas else 0)
