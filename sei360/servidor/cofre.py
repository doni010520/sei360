# -*- coding: utf-8 -*-
"""
Cofre de credenciais do SEI.

RESPOSTA À PERGUNTA QUE ORIGINOU ESTE ARQUIVO
---------------------------------------------
Sim: o Playwright preenche usuário e senha no formulário do SEI, então a senha
precisa existir em texto claro NO MOMENTO da coleta. Não há como fugir disso —
o SEI não tem API, não tem token, não tem OAuth. A única pergunta real é ONDE
ela fica guardada entre uma coleta e outra, e quem consegue lê-la.

Este módulo implementa a guarda NO SERVIDOR. É uma escolha com preço, e o preço
está escrito aqui para quem vier depois não achar que foi de graça:

  * a chave mestra NÃO fica no banco. Ela vem da variável de ambiente
    SEI360_CHAVE_MESTRA. Backup do volume, cópia do .db, snapshot do disco —
    nada disso carrega a chave. É o que separa "vazou o banco" de "vazaram as
    senhas do SEI de todo mundo".
  * quem controla o PROCESSO, controla tudo. Um invasor com execução de código
    no container lê a variável de ambiente e decifra. Contra esse cenário não
    existe criptografia que salve: o robô precisa decifrar sozinho às 7h30, logo
    a chave está ao alcance dele — e de quem tomar o lugar dele.
  * cada abertura do cofre é REGISTRADA. Se um dia alguém perguntar "quem usou a
    minha credencial e quando", a resposta existe.

O que a cifra protege de verdade: banco vazado, backup roubado, disco descartado,
volume copiado, e leitura por quem tem acesso ao arquivo mas não ao processo.
O que ela NÃO protege: comprometimento do servidor em execução.
"""
import base64
import os

from banco import agora, registrar

ALGO = "AES-256-GCM"
VAR_CHAVE = "SEI360_CHAVE_MESTRA"


def _chave():
    """32 bytes vindos do ambiente, ou None.

    Sem chave o cofre fica INDISPONÍVEL — e não "degradado para texto puro".
    Guardar senha em claro porque a chave não foi configurada seria transformar
    um erro de operação em vazamento silencioso.
    """
    cru = os.environ.get(VAR_CHAVE, "").strip()
    if not cru:
        return None
    try:
        k = base64.urlsafe_b64decode(cru + "=" * (-len(cru) % 4))
    except (ValueError, TypeError):
        return None
    return k if len(k) == 32 else None


def disponivel():
    """Chave presente E biblioteca instalada.

    Conferir só a variável de ambiente fazia a tela anunciar "cofre ligado" num
    ambiente onde `cryptography` não estava instalada — e o erro só aparecia no
    instante de guardar a senha, com 500. Foi exatamente o que aconteceria no
    primeiro container: `requisitos.txt` não declarava a dependência.
    Disponibilidade que não testa o caminho inteiro é promessa, não verificação.
    """
    if _chave() is None:
        return False
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    except ImportError:
        return False
    return True


def gerar_chave():
    """Para o operador criar a dele: `python cofre.py --nova-chave`."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


def _aad(usuario_id, sistema, login):
    """Amarra o texto cifrado ao dono, ao sistema e ao login.

    Sem isso, quem tivesse escrita no banco copiaria o blob de outra pessoa para
    a própria linha e a coleta rodaria com a credencial alheia. Com AAD, o blob
    só decifra no contexto exato em que foi criado.
    """
    return f"{usuario_id}|{sistema}|{login}".encode()


def guardar(cx, usuario_id, sistema, login, senha, ip=None):
    k = _chave()
    if not k:
        raise RuntimeError(f"cofre indisponível: defina {VAR_CHAVE}")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    blob = AESGCM(k).encrypt(nonce, senha.encode("utf-8"), _aad(usuario_id, sistema, login))
    cx.execute("""INSERT INTO credencial(usuario_id,sistema,login,segredo,nonce,algo,
                  criado_em,usos) VALUES(?,?,?,?,?,?,?,0)
                  ON CONFLICT(usuario_id,sistema) DO UPDATE SET
                    login=excluded.login,
                    segredo=excluded.segredo, nonce=excluded.nonce, algo=excluded.algo,
                    criado_em=excluded.criado_em, usos=0, ultimo_uso_em=NULL""",
               (usuario_id, sistema, login, blob, nonce, ALGO, agora()))
    # O REGISTRO guarda o fato, nunca o segredo — nem o tamanho dele.
    registrar(cx, usuario_id, "guardar_credencial", alvo=sistema, ip=ip)
    return True


def abrir(cx, usuario_id, motivo, ip=None, sistema=None):
    """Devolve (login, senha) e REGISTRA o uso.

    `motivo` é obrigatório de propósito: toda abertura tem de poder ser explicada
    depois. `sistema` diz de QUAL instalação — com duas guardadas, abrir "a
    credencial da pessoa" é escolher uma no escuro, e a escolhida vai preencher o
    formulário de login da outra, falhando de um jeito que parece senha errada.

    Sem `sistema`, devolve a única que houver; havendo mais de uma, RECUSA em vez
    de escolher.
    """
    k = _chave()
    if not k:
        raise RuntimeError(f"cofre indisponível: defina {VAR_CHAVE}")
    if sistema:
        r = cx.execute("SELECT * FROM credencial WHERE usuario_id=? AND sistema=?",
                       (usuario_id, sistema)).fetchone()
    else:
        todas = cx.execute("SELECT * FROM credencial WHERE usuario_id=?",
                           (usuario_id,)).fetchall()
        if len(todas) > 1:
            raise ValueError(
                f"o usuário {usuario_id} tem credencial em {len(todas)} instalações "
                f"({', '.join(x['sistema'] for x in todas)}); diga qual com `sistema=`")
        r = todas[0] if todas else None
    if not r:
        return None, None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    senha = AESGCM(k).decrypt(r["nonce"], r["segredo"],
                              _aad(usuario_id, r["sistema"], r["login"])).decode("utf-8")
    cx.execute("UPDATE credencial SET ultimo_uso_em=?, usos=usos+1 "
               "WHERE usuario_id=? AND sistema=?", (agora(), usuario_id, r["sistema"]))
    # O registro diz a instalação: "usou a credencial" sem dizer qual não responde
    # a pergunta que se faz num incidente.
    registrar(cx, usuario_id, "usar_credencial", alvo=f"{r['sistema']} · {motivo}", ip=ip)
    return r["login"], senha


def esquecer(cx, usuario_id, ip=None):
    n = cx.execute("DELETE FROM credencial WHERE usuario_id=?", (usuario_id,)).rowcount
    if n:
        registrar(cx, usuario_id, "apagar_credencial", ip=ip)
    return n


def estado(cx, usuario_id):
    """O que a tela pode dizer sobre a credencial sem nunca tocar no segredo."""
    r = cx.execute("""SELECT sistema,login,algo,criado_em,ultimo_uso_em,usos
                      FROM credencial WHERE usuario_id=?""", (usuario_id,)).fetchone()
    return dict(r) if r else None


if __name__ == "__main__":
    import sys
    if "--nova-chave" in sys.argv:
        print("Ponha isto no ambiente do serviço (EasyPanel > Environment):\n")
        print(f"  {VAR_CHAVE}={gerar_chave()}\n")
        print("Guarde uma cópia FORA do servidor. Perder a chave é perder todas as")
        print("credenciais guardadas — elas não são recuperáveis, e cada pessoa terá")
        print("de digitar a senha do SEI de novo.")
    else:
        print(f"cofre {'DISPONÍVEL' if disponivel() else 'indisponível'} "
              f"({VAR_CHAVE} {'definida' if os.environ.get(VAR_CHAVE) else 'ausente'})")
        print(f"algoritmo: {ALGO}; chave de 32 bytes fora do banco; AAD amarra dono+sistema+login")
