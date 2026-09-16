# -*- coding: utf-8 -*-
"""
O DIÁRIO E A ROTA DE DIAGNÓSTICO — saber como o servidor está rodando, de fora.

Em 15/09/2026 a coleta ficou três dias úteis sem rodar e descobrir o motivo
dependeu de alguém abrir o painel do provedor e copiar o log do container à mão:
o sistema não guardava log em lugar nenhum que sobrevivesse ao redeploy, e o
laço decidia não coletar em silêncio.

Esta suíte prende as três peças que consertam isso:

  * `diario.py` — o mesmo texto do stdout também num arquivo por dia no volume,
    sem segredo dentro, com prazo e com o expurgo aplicando o prazo;
  * `/diag?t=<token>` — o recorte operacional por HTTPS, que não existe sem
    token, não devolve valor de variável secreta e não devolve o texto que a
    pessoa digitou numa busca;
  * o motivo da decisão dos laços, impresso UMA VEZ por mudança.

    python teste_diagnostico.py
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from ambiente_teste import isolar

isolar(__file__, copiar=False)
import base64 as _b64
os.environ.setdefault("SEI360_CHAVE_MESTRA",
                      _b64.b64encode(b"chave-de-teste-32-bytes-!!!!!!!!").decode())
os.environ["SEI360_ATENDENTE"] = "0"
TOKEN = "token-de-teste-com-tamanho-suficiente-123456"
os.environ["SEI360_DIAG_TOKEN"] = TOKEN
sys.stdout.reconfigure(encoding="utf-8")

import banco                                                     # noqa: E402
banco.migrar()
import diario                                                    # noqa: E402
from banco import TZ, agora, conectar                            # noqa: E402

ok = mau = 0


def checar(nome, cond, viu=None):
    global ok, mau
    if cond:
        ok += 1
        print(f"  ok    {nome}")
    else:
        mau += 1
        print(f"  FALHA {nome}" + (f"  -> {viu}" if viu is not None else ""))


print("A. O DIÁRIO ESCREVE, LÊ E NÃO CARREGA SEGREDO")
diario.escrever("linha simples do diário")
checar("a linha vai para o arquivo do dia", diario.arquivo().exists())
checar("e volta na leitura, com hora e pid",
       any("linha simples do diário" in l for l in diario.ler(50)),
       diario.ler(3))
diario.escrever("GET /processo?infra_hash=abc123DEF456 — ecoado do coletor")
diario.escrever('senha: "minha-senha-do-sei" e token=abcdef0123456789')
diario.escrever("chave sk-ant-api03-ABCDEFGHIJKLMNOP")
texto = "\n".join(diario.ler(30))
checar("infra_hash de sessão não fica no diário", "abc123DEF456" not in texto, texto[-300:])
checar("senha não fica no diário", "minha-senha-do-sei" not in texto)
checar("token não fica no diário", "abcdef0123456789" not in texto)
checar("chave de API não fica no diário", "sk-ant-api03-ABCDEFGHIJKLMNOP" not in texto)
checar("mas o resto da linha continua legível", "ecoado do coletor" in texto)
# O QUE ELE NUNCA PODE FAZER: derrubar quem o chamou. É chamado de dentro dos
# laços e do `print` do processo.
_pasta = diario.PASTA
try:
    diario.PASTA = Path("Z:/nao/existe/mesmo")
    checar("pasta inacessível não levanta — devolve False", diario.escrever("x") is False)
finally:
    diario.PASTA = _pasta

print("\nB. O STDOUT ECOA NO DIÁRIO — sem trocar dezenas de prints por outra função")
_stdout, _stderr = sys.stdout, sys.stderr
try:
    diario.instalar()
    print("coleta(servidor): agente 9 — teste de eco")
    sys.stderr.write("erro de teste no diário\n")
finally:
    sys.stdout, sys.stderr = _stdout, _stderr
    diario._instalado = False
_eco = "\n".join(diario.ler(40))
checar("print do laço aparece no diário", "agente 9 — teste de eco" in _eco)
checar("e o stderr também", "erro de teste no diário" in _eco)

print("\nC. O DIÁRIO TEM PRAZO, E O EXPURGO O APLICA")
_velho = diario.PASTA / f"sei360-{(datetime.now(TZ).date() - timedelta(days=diario.DIAS + 3)).isoformat()}.log"
_velho.write_text("linha velha\n", encoding="utf-8")
_n, _bytes = diario.limpar(simular=True)
checar("simular NÃO apaga", _n == 1 and _velho.exists(), (_n, _velho.exists()))
import expurgo                                                   # noqa: E402
_plano = expurgo.expurgar(simular=True)
checar("o expurgo declara o diário no plano",
       any(t == "diario" for t, _n2, _m in _plano), str(_plano))
_n, _bytes = diario.limpar()
checar("e limpar apaga o que passou do prazo", _n == 1 and not _velho.exists())
checar("o arquivo de hoje fica", diario.arquivo().exists())
checar("e os arquivos são listados com tamanho",
       any(a["arquivo"] == diario.arquivo().name and a["bytes"] > 0
           for a in diario.arquivos()), diario.arquivos())

print("\nD. A ROTA DE DIAGNÓSTICO NÃO EXISTE SEM O TOKEN CERTO")
import app as A                                                  # noqa: E402
A.app.config["TESTING"] = True
c = A.app.test_client()
checar("sem token nenhum na URL: 404", c.get("/diag").status_code == 404)
checar("com token errado: 404, e não 403 — para quem não tem, a rota não existe",
       c.get("/diag?t=token-errado-mas-longo-o-suficiente-1").status_code == 404)
cx = conectar()
checar("e a tentativa fica registrada no log de acesso",
       cx.execute("SELECT COUNT(*) FROM log_acesso WHERE acao='diag_recusado'").fetchone()[0] >= 1)
cx.close()
_o_tok = A._DIAG_TOKEN
try:
    A._DIAG_TOKEN = "curto"
    checar("token curto é o mesmo que nenhum: 404",
           c.get("/diag?t=curto").status_code == 404)
finally:
    A._DIAG_TOKEN = _o_tok

print("\nE. COM O TOKEN, ELA DIZ COMO O SERVIDOR ESTÁ RODANDO")
r = c.get(f"/diag?t={TOKEN}&linhas=30")
checar("responde 200", r.status_code == 200, r.status_code)
d = r.get_json()
for secao in ("interruptores", "motor", "agentes", "configuracoes", "execucoes",
              "coleta_por_unidade", "alertas", "buscas", "acompanhamento",
              "travas_de_conta", "diario", "diario_arquivos"):
    checar(f"traz a seção {secao}", secao in d, list(d))
checar("o motor diz se há executor NO CONTAINER e neste worker",
       set(("executor_no_container", "executor_neste_worker", "vagas_livres")) <= set(d["motor"]),
       d["motor"])
checar("e se a coleta e o acompanhamento estão ligados",
       "ligado" in d["motor"]["coleta"] and "ligado" in d["motor"]["acompanhamento"])
checar("o diário vem em linhas, na ordem em que foi escrito", isinstance(d["diario"], list))
checar("e o pedido de linhas é respeitado", len(d["diario"]) <= 30, len(d["diario"]))
checar("o teto de linhas é 500, mesmo pedindo mais",
       len(c.get(f"/diag?t={TOKEN}&linhas=99999").get_json()["diario"]) <= 500)

print("\nF. E NÃO ENTREGA O QUE NÃO É DELA")
corpo = r.get_data(as_text=True)
checar("nenhum valor de variável secreta no corpo",
       os.environ["SEI360_CHAVE_MESTRA"] not in corpo and TOKEN not in corpo)
checar("a chave mestra aparece como 'definida', não como valor",
       d["interruptores"].get("SEI360_CHAVE_MESTRA") == "definida", d["interruptores"])
cx = conectar()
cx.execute("""INSERT INTO usuarios(email,nome,papel,ativo) VALUES('d@x','D','servidor',1)""")
_u = cx.execute("SELECT last_insert_rowid()").fetchone()[0]
cx.execute("""INSERT INTO busca(usuario_id,instancia,conta,mesa,filtros,estado,pedida_em)
              VALUES(?,'SEI-SESAB','d@x','SESAB/UMA',
                     '{"contato": "nome de paciente que nao pode sair"}','falhou',?)""",
           (_u, agora()))
cx.commit(); cx.close()
d2 = c.get(f"/diag?t={TOKEN}").get_json()
checar("o filtro que a pessoa digitou NÃO sai no diagnóstico",
       "nome de paciente que nao pode sair" not in c.get(f"/diag?t={TOKEN}").get_data(as_text=True))
checar("mas o veredito e o motivo da busca saem",
       any(b.get("estado") == "falhou" for b in d2["buscas"]), d2["buscas"][:2])
checar("e o acesso ao diagnóstico fica registrado",
       (lambda cx2: cx2.execute("SELECT COUNT(*) FROM log_acesso WHERE acao='diag'")
        .fetchone()[0] >= 1)(conectar()))

print("\nG. OS LAÇOS DIZEM POR QUE NÃO RODARAM — uma linha por MUDANÇA")
import coleta_servidor as cs                                     # noqa: E402
import acompanhamento_servidor as asv                            # noqa: E402
import contextlib                                              # noqa: E402
import io                                                        # noqa: E402
cs._ultimo_motivo.clear()
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    cs._dizer(7, "agendamento desarmado")
    cs._dizer(7, "agendamento desarmado")
    cs._dizer(7, "janela de 07:30 perdida")
_saida = [l for l in _buf.getvalue().splitlines() if l.strip()]
checar("o mesmo motivo não é repetido a cada passada", len(_saida) == 2, _saida)
checar("e a mudança de motivo é dita", "janela de 07:30" in _saida[-1], _saida)
checar("o acompanhamento tem o mesmo diário de decisão",
       callable(asv._dizer) and isinstance(asv._ultimo_motivo, dict))

print("\n" + "=" * 62)
print(f"{ok} verificações OK, {mau} falha(s)")
sys.exit(1 if mau else 0)
