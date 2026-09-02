# =============================================================================
# SEI360 — imagem do SERVIDOR, COM navegador.
#
# ATENÇÃO AO CONTEXTO DE BUILD: é `sei_sistema/`, não `sei360/servidor/`. O
# coletor e os dois .js vivem em `painel_sesab/`, que é IRMÃO de `sei360/` — e
# `COPY` não enxerga fora do contexto. Quem controla o tamanho disso é o
# `.dockerignore` da raiz, que nega tudo e libera só estas duas pastas.
#
#   docker build -f sei360/servidor/Dockerfile -t sei360 .        (de sei_sistema/)
#   EasyPanel: Build context = sei_sistema, Dockerfile = sei360/servidor/Dockerfile
#
# POR QUE HÁ CHROMIUM AQUI, se o Dockerfile anterior dizia que nunca haveria:
# porque a arquitetura mudou por decisão do dono do sistema, em 21/08/2026, ao
# escolher hospedar em VPS próprio (EasyPanel/HostGator) e executar a busca no
# servidor. O §6.1 e o §3.7 do ARQUITETURA_ACESSO.md estão REVOGADOS, com a data,
# o autor e o custo escritos lá — inclusive o custo que continua de pé: a
# credencial do SEI é NOMINAL, e tudo que este container fizer o SEI registra com
# o nome da pessoa. Quem tiver o painel do EasyPanel, root no host, um snapshot
# do disco ou uma falha nesta aplicação consegue agir como ela.
#
# Se algum dia alguém quiser REMOVER o navegador daqui, o documento a mudar
# continua sendo o ARQUITETURA_ACESSO.md, não este arquivo.
# =============================================================================
FROM python:3.12-slim

# UMA INSTRUÇÃO POR VARIÁVEL, com o comentário ACIMA e não dentro. O parser do
# Docker remove comentário antes de juntar as continuações `\`, então comentário
# no meio de um `ENV` multi-linha costuma funcionar — e "costuma" não serve para
# um build que roda pela primeira vez direto no VPS.
# SEM `PORT` AQUI. O CMD do gunicorn tem `--bind 0.0.0.0:8000` cravado, então
# uma variável `PORT` seria letra morta: quem a mudasse no EasyPanel acharia que
# mudou a porta, o gunicorn continuaria em 8000, e o healthcheck e o roteamento
# cairiam sem explicação. A porta é 8000, e é fixa — mapeie por fora.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SEI360_DADOS=/dados

# Fora do $HOME: o Chromium é instalado como root e USADO como sei360. No caminho
# padrão (~/.cache/ms-playwright) ele ficaria no home do root, que o usuário sem
# privilégio não lê — e o erro aparece só na primeira busca.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# O coletor mora fora de /app/servidor; sem isto o `_achar_coletor()` cai no
# caminho da estação, que não existe aqui.
ENV SEI360_COLETOR=/app/painel_sesab/coletor_sesab.py

# O perfil do navegador no VOLUME, não na imagem: é ele que guarda a sessão do
# SEI. Na imagem, cada redeploy exigiria login novo — e login novo é exatamente
# onde o segundo fator aparece, sem ninguém na tela para digitar.
ENV SEI_PERFIL_DIR=/dados/_perfil_sei

# O SANDBOX DO CHROMIUM, DESLIGADO — só aqui dentro. O sandbox do Chromium usa
# namespaces de usuário; em container sem SYS_ADMIN, e com
# `unprivileged_userns_clone` desligado (padrão em muito host), ele falha no
# start. E a falha apareceria só na PRIMEIRA BUSCA: o build passa, o healthcheck
# fica verde, e a pessoa é quem descobre.
# Junto vai `--disable-dev-shm-usage`: o /dev/shm padrão do Docker tem 64 MB, e é
# ali que o Chromium põe memória compartilhada — página pesada mata a aba.
# Quem isola aqui é o CONTAINER, e a página carregada é o SEI. Na estação a
# variável não existe e o sandbox continua ligado, como deve ser.
ENV SEI_SEM_SANDBOX=1

WORKDIR /app

COPY sei360/servidor/requisitos.txt .
RUN pip install --no-cache-dir -r requisitos.txt

# O NAVEGADOR. `--with-deps` puxa as bibliotecas de sistema do Chromium (fontes,
# nss, libdrm...) e precisa de root e apt — por isso vem ANTES de criar o usuário.
# Só chromium: firefox e webkit dobrariam a imagem para nada.
RUN playwright install --with-deps chromium && \
    rm -rf /var/lib/apt/lists/* /root/.cache/pip

COPY sei360/servidor/ /app/
COPY painel_sesab/ /app/painel_sesab/

# Usuário sem privilégio: se a aplicação for comprometida, o atacante não herda
# root dentro do container. Isso importa MAIS agora do que antes — a partir desta
# imagem há credencial de terceiros passando por aqui.
# O /dados criado AQUI, com este dono, é o que faz um volume nomeado do EasyPanel
# nascer gravável — bind mount de diretório do host chega como root:root e precisa
# de chown (o banco.py avisa em vez de quebrar no meio de um login).
RUN useradd -r -u 10001 sei360 && mkdir -p /dados && \
    chown -R sei360:sei360 /dados /app && chmod -R a+rX /ms-playwright
USER sei360

VOLUME ["/dados"]
EXPOSE 8000

# Sonda: sem curl na imagem slim, quem checa é o próprio Python. Uma linha só —
# continuação com barra invertida DENTRO de string entre aspas é fonte clássica
# de Dockerfile que passa no build e falha na execução.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["python","-c","import urllib.request,json,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:8000/saude',timeout=4)).get('ok') else 1)"]

# TRÊS WORKERS, DUAS THREADS — e a razão é medida, não herdada.
#
# A versão anterior era `--workers 1 --threads 8`, e a justificativa escrita era o
# lock do SQLite: "a ingestão escreve milhares de linhas e seguraria o lock além
# do busy_timeout, devolvendo 'database is locked' a quem só queria abrir o
# painel". MEDIDO, isso não acontece: 2.000 linhas num commit só, segurando o
# lock por 0,5 s, com três leitores batendo no painel ao mesmo tempo — ZERO
# erros. É o WAL fazendo o que existe para fazer: leitor não espera escritor.
#
# O que pesa é outra coisa: 93% do tempo do painel é CPU deste processo (134 ms
# de parede, 125 ms de CPU). Trabalho de CPU em Python não se divide entre
# threads — o GIL serializa. Com N pessoas ao mesmo tempo, medido:
#
#     1 ..... 98 ms       4 .....   466 ms      16 ..... 3.241 ms
#     2 .... 123 ms       8 ..... 1.417 ms      (pior caso: 5.497 ms)
#
# Com processos, o mesmo trabalho escala quase linear: 4 processos fazendo 4× o
# trabalho levaram 997 ms contra 826 ms de um processo fazendo 1×.
#
# E cabe: 45 MB por worker, sem vazamento (+1 MB depois de 42 relatórios). Três
# workers são 135 MB — ao lado dos ~450 MB de um Chromium, é ruído. Três, e não
# oito, porque o VPS tem 2 GB e a busca precisa do resto.
#
# SEGURO COM VÁRIOS WORKERS porque duas coisas foram consertadas antes: o
# `atendente._tomar_a_vez()` garante UM executor de busca por container (senão
# SEI360_BUSCAS_SIMULTANEAS viraria um teto POR WORKER, e 3×2 Chromium não cabem
# em 2 GB), e a sonda de escrita do `banco.py` deixou de derrubar o vizinho.
#
# --forwarded-allow-ips faz o gunicorn confiar no X-Forwarded-Proto do Traefik —
# sem isso o cookie de sessão sai sem Secure mesmo com o site em HTTPS.
# `-c gunicorn_conf.py` NÃO É OPCIONAL. O log de acesso registra o caminho da
# requisição, e o caminho de `/recuperar/<token>` carrega o token que dá acesso à
# conta sem senha. A classe de log de lá omite só o segredo, mantendo o resto da
# linha — que é o que a auditoria precisa. Sem ela, o token fica em texto no log
# do container, legível pelo painel do provedor e por qualquer backup dele.
CMD ["gunicorn", "-c", "gunicorn_conf.py", \
     "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", \
     "--timeout", "120", "--forwarded-allow-ips", "*", \
     "--access-logfile", "-", "--error-logfile", "-", "app:app"]
