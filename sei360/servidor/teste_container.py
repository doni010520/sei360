# -*- coding: utf-8 -*-
"""
Constrói a imagem, sobe o container e testa o que SÓ aparece no container.

O testes.py e o teste_deploy_novo.py rodam com o Python da estação e provam a
lógica. Nenhum dos dois prova o que quebra em produção por causa do EMPACOTAMENTO:

  * a imagem tem tudo o que precisa? (o `.dockerignore` pode ter comido demais)
  * o esquema nasce com `gunicorn app:app`, que IMPORTA o módulo e nunca executa
    o `__main__`? (era o defeito nº 1 da auditoria)
  * o volume é gravável para o uid 10001, que não é root?
  * o cookie sai `Secure` quando o Traefik manda `X-Forwarded-Proto: https`?
  * o HEALTHCHECK fica `healthy` — é o que o EasyPanel observa
  * o dado sobrevive a destruir e recriar o container? (é o que um redeploy faz)

    python teste_container.py            # constrói e testa
    python teste_container.py --manter   # deixa o container de pé no fim
"""
import json, re, subprocess, sys, time
from pathlib import Path
import urllib.error
import urllib.request

IMAGEM = "sei360:teste"
NOME = "sei360-teste"
VOLUME = "sei360-dados-teste"
PORTA = 8361
BASE = f"http://127.0.0.1:{PORTA}"
ok_total, falhas = 0, []


def checar(nome, cond, detalhe=""):
    global ok_total
    if cond:
        ok_total += 1
        print(f"  OK    {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}  {detalhe}")


# A RAIZ DO REPOSITÓRIO, que é o contexto de build. `rodar_testes.py` roda este
# arquivo com `cwd=servidor/`, e de lá o contexto não alcança `painel_sesab/` —
# onde vivem o coletor e os dois `.js` que a imagem precisa.
RAIZ = Path(__file__).resolve().parents[2]          # .../sei_sistema


def docker(*args, checar_erro=True, entrada=None):
    r = subprocess.run(["docker", *args], cwd=str(RAIZ),
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", input=entrada)
    if checar_erro and r.returncode != 0:
        print(f"    (docker {' '.join(args[:3])}… saiu {r.returncode})")
        print("   ", (r.stderr or r.stdout).strip()[-600:])
    return r


def limpar():
    docker("rm", "-f", NOME, checar_erro=False)


def esperar_http(caminho="/saude", tentativas=40):
    for _ in range(tentativas):
        try:
            with urllib.request.urlopen(BASE + caminho, timeout=3) as r:
                return r.status, json.loads(r.read().decode())
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(1)
    return None, None


print("SEI360 — teste da imagem de container\n")

r = docker("version", "--format", "{{.Server.Version}}", checar_erro=False)
if r.returncode != 0:
    sys.exit("Docker não respondeu. O daemon está rodando?\n" + (r.stderr or "")[-300:])
print(f"docker engine {r.stdout.strip()}\n")

# ---------------------------------------------------------------- 1. build
print("1. construção da imagem")
t0 = time.time()
# CONTEXTO NA RAIZ, DOCKERFILE APONTADO. Sem o `-f`, o Docker procura
# `./Dockerfile` na raiz — que não existe desde que o contexto mudou de lugar em
# 21/08. E sem o contexto na raiz, `COPY painel_sesab/` não acha nada. Sem os
# dois, o build morre na primeira linha e as outras 29 verificações — as únicas
# que provam o EMPACOTAMENTO — nunca executam.
b = docker("build", "-f", "sei360/servidor/Dockerfile", "-t", IMAGEM, ".")
checar(f"imagem constrói ({time.time()-t0:.0f}s)", b.returncode == 0,
       (b.stderr or "")[-400:])
if b.returncode != 0:
    sys.exit(1)

r = docker("image", "inspect", IMAGEM, "--format",
           "{{.Config.User}}|{{.Config.ExposedPorts}}|{{.Size}}")
usuario, portas, tamanho = (r.stdout.strip().split("|") + ["", "", "0"])[:3]
checar("roda como usuário sem privilégio (10001)", usuario.strip() == "10001", f"user={usuario!r}")
checar("porta 8000 exposta", "8000" in portas, portas)
print(f"        tamanho da imagem: {int(tamanho)/1024/1024:.0f} MB")

r = docker("run", "--rm", "--entrypoint", "python", IMAGEM, "-c",
           "import os,json;print(json.dumps(sorted(os.listdir('/app'))))")
dentro = json.loads(r.stdout.strip() or "[]")
checar("templates e estáticos entraram na imagem",
       "templates" in dentro and "estatico" in dentro, str(dentro))
checar("testes.py NÃO entrou (tem senha em claro e escreve no banco)",
       "testes.py" not in dentro, str(dentro))
r = docker("run", "--rm", "--entrypoint", "python", IMAGEM, "-c",
           "import os;print(len(os.listdir('/app/estatico/vendor')))")
checar("fontes e bibliotecas locais na imagem", int(r.stdout.strip() or 0) >= 20,
       f"{r.stdout.strip()} arquivos em estatico/vendor")

# O teste que teria pegado o defeito mais caro deste projeto: `requisitos.txt`
# declarava só Flask e gunicorn enquanto o código importava `cryptography` e
# `openpyxl`. Rodava na estação, dava 500 no container ao guardar a senha do SEI
# e em toda exportação de planilha.
r = docker("run", "--rm", "--entrypoint", "python", IMAGEM, "-c",
           "import app, cofre, ia, relatorios, expurgo, coleta, configuracao, "
           "ingestao, semear, janelas, seguranca, banco; print('imports ok')")
checar("TODO módulo do servidor importa dentro da imagem",
       "imports ok" in r.stdout, (r.stdout + r.stderr).strip()[-300:])
r = docker("run", "--rm", "--entrypoint", "python", IMAGEM, "-c",
           "import os; os.environ['SEI360_CHAVE_MESTRA']='x'*43; import cofre; "
           "print('cofre_ok' if cofre.disponivel() else 'cofre_indisponivel')")
checar("o cofre se declara disponível de verdade na imagem",
       "cofre_ok" in r.stdout, r.stdout.strip())
r = docker("run", "--rm", "--entrypoint", "python", IMAGEM, "-c",
           "import openpyxl, cryptography; print(openpyxl.__version__)")
checar("openpyxl e cryptography presentes (exportação e cofre)",
       r.returncode == 0, (r.stdout + r.stderr).strip()[-200:])

# ---------------------------------------------------------------- 2. subida
print("\n2. container de pé, com volume vazio")
limpar()
docker("volume", "rm", VOLUME, checar_erro=False)
r = docker("run", "-d", "--name", NOME, "-p", f"{PORTA}:8000",
           "-v", f"{VOLUME}:/dados", "-e", "SEI360_SEGREDO=teste-de-container",
           IMAGEM)
checar("container inicia", r.returncode == 0, (r.stderr or "")[-300:])
status, saude = esperar_http()
checar("/saude responde 200 com volume VAZIO (o esquema nasce no import)",
       status == 200, f"status={status}")
checar("banco vazio, mas coerente",
       bool(saude) and saude.get("ok") and saude.get("unidades_correntes") == 0, str(saude))

logs = docker("logs", NOME).stdout + docker("logs", NOME).stderr
checar("nenhum erro de migração no log", "migração falhou" not in logs, logs[-300:])
checar("gunicorn no comando", "gunicorn" in logs.lower() or "Booting worker" in logs,
       logs[-200:])

r = docker("exec", NOME, "id", "-u")
checar("processo roda como uid 10001 dentro do container", r.stdout.strip() == "10001",
       r.stdout.strip())
r = docker("exec", NOME, "sh", "-c", "touch /dados/.proba && rm /dados/.proba && echo ok")
checar("volume é gravável pelo usuário sem privilégio", "ok" in r.stdout, r.stderr[-200:])

# ---------------------------------------------------------------- 3. healthcheck
print("\n3. HEALTHCHECK (é o que o EasyPanel observa)")
estado = "?"
for _ in range(45):
    r = docker("inspect", "--format", "{{.State.Health.Status}}", NOME, checar_erro=False)
    estado = r.stdout.strip()
    if estado in ("healthy", "unhealthy"):
        break
    time.sleep(2)
checar(f"container fica 'healthy' (estado: {estado})", estado == "healthy", estado)

# ---------------------------------------------------------------- 4. bootstrap
print("\n4. bootstrap da administração dentro do container")
r = docker("exec", NOME, "python", "semear.py", "--so-contas")
saida = r.stdout + r.stderr
checar("semear --so-contas roda no container", r.returncode == 0, saida[-300:])
senha = None
for linha in saida.splitlines():
    if "admin@sei360.local" in linha:
        senha = linha.split()[-1]
checar("senha provisória do admin foi impressa", bool(senha), saida[-200:])

# ---------------------------------------------------------------- 5. HTTP real
print("\n5. autenticação pela rede (gunicorn, não test client)")
import http.cookiejar
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def pegar(caminho, dados=None, cab=None):
    import urllib.parse
    corpo = urllib.parse.urlencode(dados).encode() if dados else None
    req = urllib.request.Request(BASE + caminho, data=corpo, headers=cab or {})
    try:
        r = op.open(req, timeout=15)
        return r.status, r.read().decode("utf-8", "replace"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers


s, corpo, cab = pegar("/entrar")
checar("tela de acesso servida pelo gunicorn", s == 200, f"status {s}")
checar("é a tela SEI360 original (d3 local, sem unpkg)",
       "/estatico/vendor/d3.min.js" in corpo and "unpkg.com" not in corpo)
checar("cabeçalhos de segurança presentes",
       cab.get("Cache-Control") == "no-store, private" and cab.get("X-Frame-Options") == "DENY",
       f"{cab.get('Cache-Control')} / {cab.get('X-Frame-Options')}")

s, corpo, cab = pegar("/estatico/vendor/fontes.css")
checar("fontes locais servidas", s == 200 and "@font-face" in corpo, f"status {s}")

csrf = next((c.value for c in jar if c.name == "sei360_csrf"), "")
s, corpo, cab = pegar("/entrar", {"email": "admin@sei360.local", "pw": senha or "x", "csrf": csrf})
checar("login pela rede funciona", s == 200 and "primeiro-acesso" in corpo, f"{s} {corpo[:120]}")

# Traefik termina o TLS e avisa por cabeçalho. Sem --forwarded-allow-ips o
# gunicorn ignora o aviso e o cookie de sessão sai SEM Secure num site https.
jar2 = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar2))
s, corpo, cab = pegar("/entrar", cab={"X-Forwarded-Proto": "https"})
sc = cab.get("Set-Cookie", "")
checar("com X-Forwarded-Proto=https o cookie sai Secure", "Secure" in sc, sc[:120])
s, corpo, cab = pegar("/entrar")
checar("em http puro o cookie NÃO exige Secure (senão o login nunca fecha)",
       "Secure" not in cab.get("Set-Cookie", ""), cab.get("Set-Cookie", "")[:120])

# ---------------------------------------------------------------- 6. suites
print("\n6. as suítes de lógica, executadas DENTRO da imagem")
r = docker("exec", NOME, "python", "teste_deploy_novo.py", checar_erro=False)
saida = r.stdout + r.stderr
achou = re.search(r"(\d+) verificações OK, (\d+) falha", saida)
checar(f"teste de primeiro deploy passa dentro do container ({achou.group(0) if achou else '?'})",
       bool(achou) and achou.group(2) == "0", saida[-400:])

# ---------------------------------------------------------------- 7. redeploy
print("\n7. redeploy: o dado sobrevive a destruir e recriar o container")
r = docker("exec", NOME, "python", "-c",
           "from banco import conectar;cx=conectar();"
           "print(cx.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0])")
antes = r.stdout.strip()
docker("rm", "-f", NOME)
r = docker("run", "-d", "--name", NOME, "-p", f"{PORTA}:8000",
           "-v", f"{VOLUME}:/dados", "-e", "SEI360_SEGREDO=teste-de-container", IMAGEM)
status, _ = esperar_http()
r = docker("exec", NOME, "python", "-c",
           "from banco import conectar;cx=conectar();"
           "print(cx.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0])")
depois = r.stdout.strip()
checar(f"contas sobrevivem ao redeploy ({antes} -> {depois})",
       antes == depois and antes not in ("", "0"), f"{antes!r} vs {depois!r}")

# ---------------------------------------------------------------- 8. bind mount
print("\n8. bind mount de diretório root (o erro clássico do EasyPanel)")
r = docker("run", "--rm", "--user", "0:0", "-v", f"{VOLUME}:/dados", IMAGEM,
           "sh", "-c", "chown -R 0:0 /dados && echo pronto", checar_erro=False)
if "pronto" in r.stdout:
    r = docker("run", "--rm", "-v", f"{VOLUME}:/dados", "--entrypoint", "python", IMAGEM,
               "-c", "import banco; banco.migrar()", checar_erro=False)
    msg = r.stdout + r.stderr
    checar("volume não gravável falha ALTO e explica o motivo",
           "nao consigo escrever" in msg.lower() or "não consigo escrever" in msg.lower(),
           msg[-300:])
    docker("run", "--rm", "--user", "0:0", "-v", f"{VOLUME}:/dados", IMAGEM,
           "sh", "-c", "chown -R 10001:10001 /dados", checar_erro=False)
else:
    print("  (pulado: não consegui simular o volume root)")

# ---------------------------------------------------------------- fim
print(f"\n{'='*58}\n{ok_total} verificações OK, {len(falhas)} falha(s)")
for f in falhas:
    print("  FALHOU:", f)
if "--manter" in sys.argv:
    print(f"\ncontainer de pé em {BASE} (docker rm -f {NOME} para derrubar)")
else:
    limpar()
    docker("volume", "rm", VOLUME, checar_erro=False)
    print("\ncontainer e volume de teste removidos")
sys.exit(1 if falhas else 0)
