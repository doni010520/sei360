# -*- coding: utf-8 -*-
"""
A saída quando o e-mail para de sair — e o painel não ajuda mais.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
O segundo fator por e-mail é a única peça do SEI360 capaz de fechar o sistema
para TODO MUNDO ao mesmo tempo: chave revogada, domínio sem verificação, cota
estourada, Resend fora do ar, ou o filtro do órgão barrando o remetente. Quando
isso acontece, ninguém entra — e a tela que desligaria o segundo fator está do
outro lado da porta trancada.

Este script é a chave reserva. Ele roda no SERVIDOR, com acesso ao disco, e não
precisa de e-mail, de sessão nem de painel.

    python emergencia.py estado
    python emergencia.py desligar-fator2
    python emergencia.py desligar-tudo
    python emergencia.py senha <email>

QUEM CONSEGUE RODAR ISTO já tem o banco na mão e a chave mestra no ambiente —
ou seja, não há poder novo sendo criado aqui. O que há é um caminho de volta
para quem administra, e a ausência dele é o que transforma um provedor fora do
ar num sistema perdido.

Toda ação fica em `log_acesso` com `usuario_id` nulo e o carimbo 'emergência',
porque quem age aqui não está autenticado por nenhuma sessão — e a auditoria
precisa distinguir isso de um clique na tela.
"""
import json
import secrets
import sys

import banco
import seguranca as seg


def _linha(cx):
    cx.execute("INSERT OR IGNORE INTO config_acesso(id) VALUES(1)")
    cx.execute("INSERT OR IGNORE INTO config_email(id) VALUES(1)")
    return (cx.execute("SELECT * FROM config_acesso WHERE id=1").fetchone(),
            cx.execute("SELECT * FROM config_email WHERE id=1").fetchone())


def estado(cx):
    a, e = _linha(cx)
    print("ACESSO")
    print(f"  recuperação por e-mail : {'ligada' if a['recuperacao_ativa'] else 'desligada'}")
    print(f"  segundo fator          : {a['fator2_papeis'] or '[]'}")
    print("\nE-MAIL")
    print(f"  provedor   : {e['provedor']}")
    print(f"  chave      : {'guardada' if e['chave'] else 'AUSENTE'}")
    print(f"  remetente  : {e['remetente'] or '(vazio)'}")
    print(f"  último teste: {e['testado_em'] or 'nunca'}"
          f"  {'OK' if e['teste_ok'] else 'FALHOU' if e['testado_em'] else ''}")
    if e["teste_erro"]:
        print(f"  último erro : {e['teste_erro']}")
    print("\nCONTAS ATIVAS")
    import email_saida
    for r in cx.execute("SELECT id,email,papel FROM usuarios WHERE ativo=1 ORDER BY id"):
        ok, porque = email_saida.entregavel(r["email"])
        print(f"  id={r['id']:<3} {r['email']:<32} {r['papel']:<9} "
              f"{'recebe e-mail' if ok else 'NAO RECEBE — ' + porque}")
    n = cx.execute("""SELECT COUNT(*) FROM desafio
                      WHERE usado_em IS NULL AND cancelado_em IS NULL""").fetchone()[0]
    print(f"\ndesafios pendentes agora: {n}")


def desligar_fator2(cx):
    a, _ = _linha(cx)
    antes = a["fator2_papeis"]
    cx.execute("""UPDATE config_acesso SET fator2_papeis='[]', atualizado_em=?,
                  atualizado_por=NULL WHERE id=1""", (banco.agora(),))
    # Os desafios pendentes morrem junto: quem estava com a tela do código
    # aberta precisa poder simplesmente entrar de novo, com a senha, e passar.
    n = cx.execute("""UPDATE desafio SET cancelado_em=? WHERE usado_em IS NULL
                      AND cancelado_em IS NULL""", (banco.agora(),)).rowcount
    banco.registrar(cx, None, "emergencia_desligar_fator2", alvo=f"era {antes}")
    print(f"segundo fator DESLIGADO (era {antes}); {n} desafio(s) pendente(s) cancelado(s).")
    print("Todo mundo volta a entrar só com a senha.")


def desligar_tudo(cx):
    desligar_fator2(cx)
    cx.execute("""UPDATE config_acesso SET recuperacao_ativa=0, atualizado_em=?
                  WHERE id=1""", (banco.agora(),))
    n = cx.execute("""UPDATE recuperacao SET invalidado_em=?,
                      motivo_invalidacao='emergência' WHERE usado_em IS NULL
                      AND invalidado_em IS NULL""", (banco.agora(),)).rowcount
    banco.registrar(cx, None, "emergencia_desligar_recuperacao")
    print(f"recuperação por e-mail DESLIGADA; {n} link(s) pendente(s) invalidado(s).")


def senha(cx, email):
    """Uma senha provisória, impressa aqui, para quem administra voltar a entrar.

    Mesma regra da tela: só o hash é gravado, `senha_trocada_em` volta a NULL
    para o app exigir a troca, o bloqueio é zerado e as sessões vivas caem.
    """
    u = cx.execute("SELECT id,email,papel,ativo FROM usuarios WHERE email=?",
                   (email,)).fetchone()
    if not u:
        sys.exit(f"não existe conta com o e-mail {email!r}")
    nova = secrets.token_urlsafe(9)
    while seg.criticar_senha(nova, email):
        nova = secrets.token_urlsafe(9)
    h, sal = seg.hash_senha(nova)
    # `ativo` NÃO ENTRA AQUI. Reativar junto com a senha desfaz, em silêncio, um
    # desligamento deliberado — alguém que saiu do órgão, uma conta suspensa por
    # incidente. Quem quer reativar tem a tela de pessoas para isso, e o comando
    # diz o que fez.
    cx.execute("""UPDATE usuarios SET senha_hash=?, senha_sal=?, senha_trocada_em=NULL,
                  bloqueado_ate=NULL, falhas_seq=0 WHERE id=?""", (h, sal, u["id"]))
    # SESSOES, DESAFIOS E LINKS de uma vez — o mesmo lugar unico que o painel usa.
    # Um desafio pendente sobrevivente viraria sessao e cairia em /primeiro-acesso,
    # que nao pede a senha antiga: quem tinha o codigo em transito definiria a
    # propria senha e a provisoria impressa aqui morreria sem uso.
    import acesso as _ac
    _ac.derrubar_acesso(cx, u["id"], "senha provisoria de emergencia")
    cx.execute("DELETE FROM tentativas_login WHERE email=? AND sucesso=0", (email,))
    banco.registrar(cx, None, "emergencia_senha_provisoria", alvo=str(u["id"]))
    print(f"\n  {u['email']}  ({u['papel']})")
    print(f"  SENHA: {nova}")
    if not u["ativo"]:
        print("\n  ATENÇÃO: esta conta está DESATIVADA e continua desativada — a")
        print("  senha nova não a faz entrar. Reative pela tela de pessoas se for")
        print("  isso que você quer.")
    print("\n  Vale uma entrada; o sistema exige a troca antes de mostrar a carteira.")


COMANDOS = {"estado": estado, "desligar-fator2": desligar_fator2,
            "desligar-tudo": desligar_tudo}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in COMANDOS and args[0] != "senha":
        sys.exit(__doc__.strip().split("QUEM CONSEGUE")[0].strip())
    # MIGRA ANTES. Este script costuma ser a primeira coisa que roda depois de
    # um deploy que deu errado, e a tabela que ele lê pode não existir ainda —
    # `estado` responderia "no such table: config_acesso" justamente para quem
    # está tentando entender por que ninguém entra.
    banco.migrar()
    cx = banco.conectar()
    try:
        if args[0] == "senha":
            if len(args) < 2:
                sys.exit("uso: python emergencia.py senha <email>")
            senha(cx, args[1].strip().lower())
        else:
            COMANDOS[args[0]](cx)
        cx.commit()
    finally:
        cx.close()
