# -*- coding: utf-8 -*-
"""O que o `.dockerignore` deixa entrar na imagem — antes de gastar um build.

POR QUE ISTO EXISTE
-------------------
O contexto de build do SEI360 é `sei_sistema/`, uma pasta com gigabytes de
coletas, PDFs e bancos. O `.dockerignore` nega tudo e reabre duas pastas. Essa
inversão é a forma segura, e é também a forma em que um erro passa despercebido
das duas maneiras possíveis:

  - reabriu de menos -> o build falha, e você descobre em 3 minutos;
  - reabriu de MAIS  -> o build funciona, e o banco de produção, o `_perfil_sei`
    (que é material de credencial) ou a chave do cofre entram na imagem. Isso
    não falha nunca. Só vaza.

Este script responde a segunda pergunta, que o `docker build` não responde.

O QUE ELE NÃO É
---------------
Não é o matcher do Docker. É uma reimplementação das regras que o Docker
documenta — última linha que casa decide, `!` reabre, `**` atravessa barras —
suficiente para pegar o erro de reabrir demais. Se ele e o Docker discordarem,
quem manda é o Docker; mas a discordância em si já é motivo para simplificar o
arquivo até os dois concordarem.

    python conferir_contexto.py            # resumo
    python conferir_contexto.py --tudo     # lista arquivo por arquivo
    python conferir_contexto.py --empacotar   # ZIP para upload direto no EasyPanel

O MODO --empacotar EXISTE PORQUE "zipar a pasta e arrastar" É EXATAMENTE O ERRO
QUE ESTE ARQUIVO INTEIRO EXISTE PARA IMPEDIR. O `.dockerignore` só protege o que
entra na IMAGEM; um ZIP feito à mão do Explorer leva a pasta inteira — banco de
produção com nome e processo de servidor público, `_perfil_sei` com sessão do
SEI, e o `automacao_sei.js` com a senha em texto puro — para o armazenamento do
EasyPanel, num host de terceiro, antes de o Docker sequer entrar em cena. Um
upload não tem como ser "desfeito": o arquivo já viajou.

`--empacotar` usa a MESMA lista que decide o que entraria na imagem (`dentro`) e
SÓ escreve o ZIP se o portão de hoje já fecha limpo (sem `FALTA`, sem `VAZANDO`).
Do contrário ele recusa e imprime o mesmo "como resolver" de sempre — porque
empacotar sobre um vazamento seria automatizar o vazamento.
"""
import fnmatch
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent          # sei_sistema/
IGNORE = RAIZ / ".dockerignore"
# O que NUNCA pode entrar, dito por extenso. Não é a mesma lista do
# `.dockerignore`: é a verificação independente dela. Duas listas iguais
# escritas duas vezes não conferem nada — esta olha o RESULTADO.
# PADRÃO DE PASTA CASA PASTA. `*_resumos*` acusava `preparar_resumos.py` e
# `_extrair_resumos.py` — código-fonte, não coleta —, e o conferidor saía 1 para
# sempre: o passo "rode até sair 0" da receita de deploy nunca terminava. E quem
# vê duas acusações falsas aprende a ignorar a terceira, que era a senha em texto
# puro. A barra nos dois lados é o que separa "a pasta `_resumos`" de "qualquer
# arquivo com `_resumos` no nome".
PROIBIDO = [
    ("banco de dados", ("*.db", "*.db-wal", "*.db-shm")),
    ("sessão do SEI (credencial)", ("*/_perfil_sei/*", "_perfil_sei/*")),
    ("segredo em arquivo", ("*.env", "*.env.local")),
    ("coleta bruta", ("*/_coletas/*", "*/_dados/*", "*/_resumos/*", "*/_logs/*",
                      "_coletas/*", "_dados/*", "_resumos/*", "_logs/*")),
    # O DERIVADO CARREGA O MESMO DADO. Barrar o banco e esquecer o painel
    # estático gerado a partir dele é barrar a porta e deixar a janela: o
    # `painel_sesab.html` e a planilha têm a carteira inteira em texto — número
    # de processo, interessado, unidade. Esta lista existe para NÃO depender do
    # `.dockerignore`; se ela repetisse só o que ele diz, não conferiria nada.
    ("carteira em artefato derivado",
     ("*painel_sesab.html", "*painel_v2.html", "*processos_sesab.xlsx",
      "*.xlsx", "*.csv")),
]
# Segredo que não está no NOME do arquivo, e sim DENTRO dele. `automacao_sei.js`
# é obrigatório na imagem — o coletor não roda sem ele —, então barrar pelo nome
# não é opção: ou entra limpo, ou não há build.
CONTEUDO_PROIBIDO = [
    ("painel_sesab/automacao_sei.js", "config_preenchido",
     "o bloco CONFIG tem usuário e senha em texto puro (§6.2 mandou esvaziar). "
     "Na imagem, isso vive na camada do COPY, de onde `RUN` nenhum apaga."),
]


def config_preenchido(caminho):
    """O CONFIG do automacao_sei.js está preenchido? Sem NUNCA ler o valor.

    Devolve só a linha, para o relatório poder apontar sem publicar a senha em
    log, terminal ou transcrição.
    """
    import re
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"\b(usuario|senha)\s*:\s*([\"\'])(.*?)\2", texto):
        if m.group(3).strip():
            return texto[:m.start()].count("\n") + 1
    return None


def regras(avisar=None):
    """As regras COMO O DOCKER AS LÊ, não como quem escreveu quis que fossem.

    `#` só é comentário quando ABRE a linha. A versão anterior fazia
    `bruta.split("#")[0]` e assim removia comentário do fim — medindo a intenção
    em vez do efeito. Com isso, cinco padrões inertes (`**/_dados   # o banco` e
    companhia) passavam como se estivessem valendo, e este script certificava
    como segura uma imagem que levava o banco de produção, as coletas brutas, a
    sessão do SEI e a chave do cofre.

    Linha com `#` no meio é sempre engano: ela vira um padrão literal que não
    casa com nada. Em vez de adivinhar o que a pessoa quis, o conferidor RECUSA
    e diz o que fazer.
    """
    linhas, suspeitas = [], []
    for n, bruta in enumerate(IGNORE.read_text(encoding="utf-8").splitlines(), 1):
        linha = bruta.rstrip()
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        if "#" in linha:
            # Não corrige em silêncio: um padrão inerte que "parece certo" é o
            # modo de falha que este arquivo inteiro existe para impedir.
            suspeitas.append((n, linha))
            continue
        linhas.append(linha.strip())
    if avisar is not None:
        avisar.extend(suspeitas)
    return linhas


def _casa(padrao, caminho):
    """O padrão casa com este caminho, ou com um ancestral dele?

    O "ou com um ancestral" é o ponto que faz a forma escalonada funcionar:
    negar `sei360/*` exclui `sei360/servidor`, e é a reabertura do ancestral
    (`!sei360/servidor`) que traz de volta tudo o que está dentro dele.
    """
    partes = caminho.split("/")
    for i in range(1, len(partes) + 1):
        if fnmatch.fnmatchcase("/".join(partes[:i]), padrao):
            return True
    if padrao.startswith("**/"):
        alvo = padrao[3:]
        return any(fnmatch.fnmatchcase(p, alvo) for p in partes)
    return False


def entra(caminho, rs):
    incluido = True
    for r in rs:
        neg = r.startswith("!")
        p = r[1:] if neg else r
        if _casa(p, caminho):
            incluido = neg
    return incluido


def avaliar():
    """Uma vez só: o que entra, o que falta, o que vaza, o que é inerte.

    `main()` e `empacotar()` chamam ESTA função — nunca cada uma a sua conta. A
    lista que decide o ZIP tem de ser, por construção, a mesma lista que decide
    o veredito impresso; duas contagens que deveriam concordar são o defeito de
    classe que este arquivo já teve uma vez (`.dockerignore` de duas fontes).
    """
    inertes = []
    rs = regras(avisar=inertes)
    dentro, fora, bytes_dentro = [], 0, 0
    for f in RAIZ.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(RAIZ).as_posix()
        if entra(rel, rs):
            dentro.append(rel)
            try:
                bytes_dentro += f.stat().st_size
            except OSError:
                pass
        else:
            fora += 1

    # O QUE O BUILD PRECISA. Reabrir de menos falha rápido, mas falha depois de
    # baixar o Chromium — 3 minutos e ~700 MB por engano de uma linha.
    exigidos = ["sei360/servidor/app.py", "sei360/servidor/requisitos.txt",
                "sei360/servidor/Dockerfile", "painel_sesab/coletor_sesab.py",
                "painel_sesab/automacao_sei.js", "painel_sesab/pesquisa_sei.js"]
    faltando = [e for e in exigidos if e not in dentro]
    vazando = []
    for rotulo, padroes in PROIBIDO:
        for c in dentro:
            if any(fnmatch.fnmatchcase(c, p) for p in padroes):
                vazando.append(f"{rotulo}: {c}")
    for alvo, teste, porque in CONTEUDO_PROIBIDO:
        if alvo in dentro:
            linha = globals()[teste](RAIZ / alvo)
            if linha:
                vazando.append(f"SEGREDO EM CONTEÚDO: {alvo}:{linha} — {porque}")
    return {"inertes": inertes, "dentro": dentro, "fora": fora,
            "bytes_dentro": bytes_dentro, "faltando": faltando, "vazando": vazando}


def _como_resolver():
    print()
    print("  COMO RESOLVER, sem quebrar a coleta agendada da estação:")
    print("   1. Rotacione a senha no SEI. A atual esteve em texto puro em disco;")
    print("      trocar depois de subir para o VPS é trocar tarde.")
    print("   2. Semeie a nova no PERFIL do navegador da estação, uma vez:")
    print("      no console do SEI, com o perfil _perfil_sei aberto,")
    print("      SEIAuto.credencial('login', 'senha')")
    print("      — é isso que faz o CONFIG deixar de ser necessário; hoje o perfil")
    print("        não tem a chave __SEI_CRED, e por isso esvaziar o CONFIG faria a")
    print("        coleta das 07h30 falhar no login, amanhã, em silêncio.")
    print("   3. Só então esvazie o CONFIG do automacao_sei.js e rode este script.")


def empacotar(destino=None):
    """O ZIP para arrastar no Upload do EasyPanel — só se o portão fechar limpo.

    Zipar a pasta pelo Explorer leva tudo: o banco de produção com nome e
    processo de servidor público, `_perfil_sei` com sessão do SEI, a senha em
    texto puro do `automacao_sei.js`. Isso vai para o armazenamento de um
    terceiro (EasyPanel/HostGator) ANTES de o Docker sequer existir — e um
    upload não tem "desfazer": o arquivo já viajou.

    Escreve fora de `RAIZ` de propósito (o padrão é ao lado dela, não dentro):
    um ZIP de 2,4 MB pousado dentro de `sei_sistema/` viraria, ele mesmo, um
    arquivo a mais para a PRÓXIMA rodada considerar — e cresceria a cada rodada.
    """
    r = avaliar()
    if r["inertes"] or r["faltando"] or r["vazando"]:
        print("RECUSADO: o portão de hoje não fecha limpo (veja abaixo). "
              "Empacotar em cima disso automatizaria o vazamento.")
        print()
        return r, None
    destino = Path(destino) if destino else RAIZ.parent / "sei360_upload_easypanel.zip"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(r["dentro"]):
            z.write(RAIZ / rel, rel)
        # O `.dockerignore` NUNCA casa com a própria regra (`*` no topo se
        # exclui primeiro), e é exatamente por isso que `docker build` não trata
        # essa exclusão como real: o CLI lê o `.dockerignore` direto da raiz do
        # contexto, ANTES de aplicar filtro nenhum — ele não precisa "entrar" em
        # lugar algum para valer. O EasyPanel, ao construir a partir do ZIP
        # extraído, faz a mesma leitura. Sem o arquivo aqui dentro, o build do
        # ZIP rodaria com um conjunto de regras DIFERENTE do que este script
        # acabou de auditar — mesmo resultado hoje (o ZIP já saiu pré-filtrado),
        # mas o tipo de garantia que um COPY mais largo, amanhã, deixaria de ter.
        if IGNORE.exists():
            z.write(IGNORE, IGNORE.relative_to(RAIZ).as_posix())
    n = len(r["dentro"]) + (1 if IGNORE.exists() else 0)
    print(f"ZIP pronto: {destino}  ({destino.stat().st_size / 1e6:.1f} MB, {n} arquivo(s))")
    print("No EasyPanel: Source -> Upload -> solte este arquivo. Build path '.', "
          "Dockerfile 'sei360/servidor/Dockerfile' (ver §3.6-bis).")
    return r, destino


def main():
    if "--empacotar" in sys.argv:
        i = sys.argv.index("--empacotar")
        alvo = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("--") else None
        r, caminho = empacotar(alvo)
    else:
        r = avaliar()
    inertes, dentro, fora = r["inertes"], r["dentro"], r["fora"]
    bytes_dentro, faltando, vazando = r["bytes_dentro"], r["faltando"], r["vazando"]

    if inertes:
        print("  PADRÃO INERTE no .dockerignore — o Docker NÃO aceita comentário")
        print("  no fim da linha; a linha inteira vira um padrão que não casa com nada:")
        for n, linha in inertes:
            print(f"     linha {n}: {linha[:90]}")
        print("  Ponha o comentário na linha DE CIMA. Enquanto isso, o que essa")
        print("  linha deveria barrar ESTÁ ENTRANDO na imagem.")
        print()

    print(f"contexto: {len(dentro)} arquivo(s), {bytes_dentro / 1e6:.1f} MB "
          f"({fora} arquivo(s) barrados)")
    if "--tudo" in sys.argv:
        for c in sorted(dentro):
            print("  ", c)
    else:
        pastas = {}
        for c in dentro:
            pastas[c.rsplit("/", 1)[0] if "/" in c else "."] = \
                pastas.get(c.rsplit("/", 1)[0] if "/" in c else ".", 0) + 1
        for p, n in sorted(pastas.items()):
            print(f"   {n:>4}  {p}")

    print()
    for f in faltando:
        print(f"  FALTA    {f} — o build quebraria")
    for v in vazando:
        print(f"  VAZANDO  {v} — NÃO pode entrar na imagem")
    if not faltando and not vazando:
        print("  ok: entra o que o build precisa, e nada do que não pode")
    elif vazando:
        _como_resolver()
    return 1 if (faltando or vazando or inertes) else 0


if __name__ == "__main__":
    sys.exit(main())
