# -*- coding: utf-8 -*-
"""
Esquema e conexao do SEI360.

POR QUE SQLITE E NAO POSTGRES
-----------------------------
Sao 1.165 linhas por coleta e UM processo escritor (a ingestao). Postgres entra
quando o web precisar de mais de uma replica — nao antes. Ver ARQUITETURA_ACESSO.md 3.2.

O QUE NAO EXISTE AQUI, DE PROPOSITO
-----------------------------------
Nao ha tabela de credencial do SEI. A ausencia e decisao de arquitetura, nao
lacuna: a senha do SEI nunca entra no servidor. Quem tomar este banco leva a base
coletada — grave — mas nao leva a capacidade de agir no SEI em nome de ninguem.
Nao "completar o que faltou".

Tambem nao existe coluna dias_na_unidade: numero de tempo gravado congela e o
painel passa a mentir conforme o snapshot envelhece. Grava-se marco_unidade e
calcula-se na exibicao (regra dura 3.2 #6 do SPECS).
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DADOS_DIR = Path(__import__("os").environ.get("SEI360_DADOS", BASE / "_dados"))
BANCO = DADOS_DIR / "sei360.db"

# A Bahia nao tem horario de verao desde 2019, entao o offset e fixo. zoneinfo
# exigiria o pacote tzdata no Windows (nao vem com o Python) e falharia no
# primeiro deploy da estacao — offset fixo nao tem esse modo de falha.
TZ = timezone(timedelta(hours=-3), "America/Bahia")


def agora():
    """ISO COM offset. Sem offset, um horario gravado no container (UTC) e lido
    como local pela tela — 3 horas de diferenca silenciosa em toda data."""
    return datetime.now(TZ).isoformat(timespec="seconds")


def conferir_escrita():
    """Falha ALTO e cedo se o volume nao for gravavel.

    No container a aplicacao roda como uid 10001. Volume nomeado herda o dono do
    diretorio da imagem e funciona; bind mount de diretorio do host chega como
    root:root e NAO. Sem esta conferencia, o sintoma seria "attempt to write a
    readonly database" no meio de um login, horas depois do deploy, em vez de
    uma mensagem na primeira linha do log.
    """
    DADOS_DIR.mkdir(parents=True, exist_ok=True)
    # NOME POR PROCESSO. Com nome fixo, dois processos subindo ao mesmo tempo —
    # que é o que `gunicorn --workers N` faz — se atropelam: A escreve, B
    # escreve, A apaga, B leva `FileNotFoundError` no unlink e o `except OSError`
    # transforma isso em SystemExit. O worker morre no boot com uma mensagem
    # sobre permissão de volume, que não é o problema. Medido: dois de quatro
    # processos morreram assim.
    teste = DADOS_DIR / f".escrita.{os.getpid()}"
    try:
        teste.write_text("ok", encoding="utf-8")
    except OSError as e:
        raise SystemExit(
            f"ERRO: nao consigo escrever em {DADOS_DIR} ({e}).\n"
            f"       No EasyPanel, use VOLUME (herda o dono da imagem), nao bind mount.\n"
            f"       Com bind mount: chown -R 10001:10001 <caminho no host>.")
    # A LIMPEZA NÃO DECIDE NADA. A pergunta era "dá para escrever aqui?", e ela
    # já foi respondida. Falhar em apagar o próprio arquivo temporário não é
    # motivo para não subir.
    try:
        teste.unlink()
    except OSError:
        pass


# `journal_mode` É PERSISTENTE: fica gravado no cabeçalho do arquivo e vale para
# toda conexão que o abrir depois, de qualquer processo. Reaplicá-lo a cada
# `conectar()` não muda nada e custa caro — medido: 1,94 ms por conexão, dos
# quais 1,48 ms são só esse PRAGMA (o `connect()` sozinho leva 0,16 ms). Ele
# precisa tomar lock no arquivo para trocar o modo, mesmo quando o modo já é o
# pedido.
#
# O painel abre 6 conexões e a tela de relatórios 5; eram ~9 ms e ~7,5 ms do
# tempo delas gastos reconfirmando algo já gravado. Agora ele roda UMA vez por
# processo e por caminho de banco — o que também cobre o arquivo recém-criado,
# que é o único caso em que o modo realmente muda.
_wal_feito = set()


def conectar():
    novo = str(BANCO) not in _wal_feito
    if novo:
        DADOS_DIR.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(BANCO, timeout=10)
    cx.row_factory = sqlite3.Row
    if novo:
        cx.execute("PRAGMA journal_mode=WAL")  # leitura durante a ingestao
        _wal_feito.add(str(BANCO))
    cx.execute("PRAGMA busy_timeout=5000")
    cx.execute("PRAGMA foreign_keys=ON")
    return cx


DDL = """
CREATE TABLE IF NOT EXISTS usuarios(
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  nome TEXT,
  senha_hash BLOB, senha_sal BLOB,
  senha_algo TEXT DEFAULT 'scrypt-n15-r8-p1',
  senha_trocada_em TEXT,                       -- NULL = primeiro acesso pendente
  papel TEXT NOT NULL CHECK(papel IN ('admin','gestor','servidor')),
  ativo INTEGER DEFAULT 1,
  origem TEXT,                                 -- 'admin' | 'auto_snapshot'
  criado_em TEXT, ultimo_login_em TEXT,
  falhas_seq INTEGER DEFAULT 0, bloqueado_ate TEXT);

CREATE TABLE IF NOT EXISTS usuario_unidade(
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  -- A sigla da mesa é texto do órgão, não identificador global. Hoje as da FESF
  -- começam com 'FESF/' e as da SESAB com 'SESAB/', mas isso é convenção de quem
  -- nomeia as unidades — não é regra do SEI, e não é onde uma fronteira de
  -- acesso deve se apoiar.
  instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  unidade TEXT NOT NULL,
  principal INTEGER DEFAULT 0,
  concedida_por INTEGER, concedida_em TEXT,
  -- De ONDE veio este vínculo. 'sei' = descoberto entrando no SEI com a
  -- credencial da própria pessoa; 'admin' = concedido à mão.
  --
  -- Existe porque a descoberta reconcilia só o que ELA mesma criou: um admin que
  -- concedeu acesso excepcional não pode ver a decisão dele desfeita por alguém
  -- clicar em "Testar acesso". Vínculo antigo não tem origem, e o DEFAULT o trata
  -- como 'admin' — que é a leitura segura: não mexer no que já estava lá.
  origem TEXT NOT NULL DEFAULT 'admin',
  PRIMARY KEY(usuario_id, instancia, unidade));

CREATE TABLE IF NOT EXISTS sessoes(
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  token_sha256 BLOB UNIQUE NOT NULL,           -- guarda o HASH, nunca o token
  criado_em TEXT, expira_em TEXT, ultimo_uso_em TEXT,
  ip TEXT, user_agent TEXT, lembrar INTEGER DEFAULT 0, revogada_em TEXT);

CREATE TABLE IF NOT EXISTS tentativas_login(
  id INTEGER PRIMARY KEY, email TEXT, ip TEXT, ts TEXT, sucesso INTEGER);
CREATE INDEX IF NOT EXISTS ix_tent_ip ON tentativas_login(ip, ts);
CREATE INDEX IF NOT EXISTS ix_tent_email ON tentativas_login(email, ts);

-- alvo guarda IDENTIFICADOR (protocolo, id do SEI, id de usuario). Nunca conteudo:
-- um log que copia a anotacao vira uma segunda base de dado pessoal sem controle.
CREATE TABLE IF NOT EXISTS log_acesso(
  id INTEGER PRIMARY KEY, ts TEXT, usuario_id INTEGER, acao TEXT,
  alvo TEXT, unidade TEXT, ip TEXT, espelhado INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_log_ts ON log_acesso(ts);

-- credencial_* aqui e METADADO para a tela dizer de quem e a credencial que roda.
-- Nenhuma coluna guarda senha, hash de senha do SEI, cookie ou material de sessao.
CREATE TABLE IF NOT EXISTS agentes(
  id INTEGER PRIMARY KEY,
  nome_estacao TEXT NOT NULL,
  -- dono: o agente roda NA ESTAÇÃO de alguém, com a credencial DE alguém. Sem
  -- dono, a trilha do SEI carimba um nome que o painel não sabe de quem é.
  dono_usuario_id INTEGER REFERENCES usuarios(id),
  token_sha256 BLOB,
  unidades_esperadas TEXT,                     -- JSON
  versao_agente TEXT, ultimo_contato_em TEXT,
  ativo INTEGER DEFAULT 1, pausado_motivo TEXT,
  higiene_config_vazio INTEGER, higiene_verificada_em TEXT,
  credencial_titular TEXT, credencial_login_mascarado TEXT,
  credencial_aceite_ref TEXT, credencial_aceite_em TEXT,
  credencial_rotacionada_em TEXT, credencial_validade_ate TEXT,
  criado_em TEXT);

-- Configuração de coleta POR USUÁRIO. É o que o assistente preenche.
--
-- Repare no que NÃO tem coluna: senha do SEI. O que se guarda aqui é o LOGIN
-- (identificador, não segredo), o sistema, as mesas e os horários. A senha é
-- digitada na estação, dentro do agente, e nunca trafega até aqui — se um dia
-- aparecer uma coluna de senha nesta tabela, a arquitetura mudou e o documento
-- a mudar primeiro é o ARQUITETURA_ACESSO.md §6.
-- PK (usuario_id, sistema) pelo mesmo motivo da credencial: as mesas, os
-- horários e o modo de coleta são de UMA instalação. Quem tem conta nas duas
-- configura as duas.
CREATE TABLE IF NOT EXISTS config_usuario(
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  sistema TEXT NOT NULL DEFAULT 'SEI-SESAB',
  sei_login TEXT,                              -- identificador, jamais a senha
  mesas_modo TEXT DEFAULT 'todas' CHECK(mesas_modo IN ('todas','selecionadas')),
  mesas TEXT DEFAULT '[]',                     -- JSON; vazio quando modo='todas'
  janelas TEXT DEFAULT '["07:30"]',            -- JSON, hora local
  dias TEXT DEFAULT 'uteis' CHECK(dias IN ('uteis','todos')),
  -- ONDE a coleta roda, e portanto onde a senha do SEI fica:
  --   'estacao' = na máquina da pessoa; a senha nunca chega ao servidor
  --   'servidor' = aqui; a senha fica cifrada em `credencial` e o servidor a
  --                decifra a cada janela para entregar ao Playwright
  modo_coleta TEXT DEFAULT 'servidor' CHECK(modo_coleta IN ('estacao','servidor')),
  passo INTEGER DEFAULT 0,                     -- até onde o assistente chegou
  -- Passos que a PESSOA decidiu, não os que têm valor padrão. Sem isto o
  -- assistente dava por concluído o que ninguém escolheu: mesas e horários
  -- nascem com padrão válido, então a trilha ficava verde sozinha e a pessoa
  -- nunca via a pergunta.
  decididos TEXT DEFAULT '[]',
  concluida_em TEXT, atualizado_em TEXT,
  PRIMARY KEY(usuario_id, sistema));

-- Credencial do SEI cifrada. A chave mestra NÃO está aqui: vem da variável de
-- ambiente SEI360_CHAVE_MESTRA. Cópia deste arquivo, backup do volume ou disco
-- descartado não carregam nada utilizável — é essa a única coisa que a cifra
-- garante, e é por isso que a chave nunca pode acabar dentro do volume.
--
-- Existe porque o Playwright preenche o formulário de login do SEI: a senha
-- precisa estar em claro no instante da coleta. A tabela guarda o mínimo para
-- isso e registra cada abertura em log_acesso.
-- PK (usuario_id, sistema): uma pessoa pode ter conta nas DUAS instalações do
-- SEI, com logins diferentes. Com `usuario_id` sozinho na chave, cadastrar a
-- segunda apagava a primeira em silêncio (ON CONFLICT DO UPDATE).
-- O AAD do AES-GCM já incluía `sistema` (ver cofre.py), então um blob trocado
-- entre instâncias falha em vez de decifrar errado — a chave só faz o banco
-- concordar com o que a cifra já dizia.
CREATE TABLE IF NOT EXISTS credencial(
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  sistema TEXT NOT NULL, login TEXT NOT NULL,
  segredo BLOB NOT NULL, nonce BLOB NOT NULL, algo TEXT NOT NULL,
  criado_em TEXT, ultimo_uso_em TEXT, usos INTEGER DEFAULT 0,
  PRIMARY KEY(usuario_id, sistema));

CREATE TABLE IF NOT EXISTS enrolamentos(
  codigo_sha256 BLOB PRIMARY KEY,
  agente_id INTEGER REFERENCES agentes(id) ON DELETE CASCADE,
  criado_por INTEGER, criado_em TEXT, expira_em TEXT, usado_em TEXT);

CREATE TABLE IF NOT EXISTS agendamento(
  agente_id INTEGER PRIMARY KEY REFERENCES agentes(id) ON DELETE CASCADE,
  janelas TEXT DEFAULT '["07:30"]',            -- JSON, hora local
  tz TEXT DEFAULT 'America/Bahia',
  tolerancia_min INTEGER DEFAULT 90,
  max_entregas_janela INTEGER DEFAULT 2,
  dias TEXT DEFAULT 'uteis' CHECK(dias IN ('uteis','todos')),
  ativo INTEGER DEFAULT 1, motivo_inativo TEXT, desarmado_em TEXT);

-- 'travada' e o sexto estado: page.evaluate NAO obedece set_default_timeout
-- (medido: 887s sob teto de 600s). Sem este estado, uma coleta pendurada nao
-- produz exit code nenhum e o painel mostra "em curso" para sempre.
CREATE TABLE IF NOT EXISTS execucao(
  id INTEGER PRIMARY KEY,
  agente_id INTEGER REFERENCES agentes(id) ON DELETE CASCADE,
  janela TEXT,                                 -- ISO da janela devida
  estado TEXT CHECK(estado IN ('entregue','em_curso','concluida','sem_dados',
                               'bloqueada','infra','travada','perdida','nao_executada')),
  gatilho TEXT, gatilho_por INTEGER,
  entregue_em TEXT, iniciado_em TEXT, heartbeat_em TEXT, terminado_em TEXT,
  duracao_s INTEGER, exit_code INTEGER, alertas TEXT, log_resumo TEXT,
  png_falha TEXT);                             -- nome do arquivo NA ESTACAO
CREATE INDEX IF NOT EXISTS ix_exec_agente ON execucao(agente_id, janela);

-- snapshot e POR UNIDADE: uma coleta que cobre 6 mesas e 6 snapshots. Se fosse
-- por execucao, uma mesa que falhou sumiria dentro de um numero agregado e a
-- coleta parcial seria publicada com cara de completa.
CREATE TABLE IF NOT EXISTS snapshot(
  id INTEGER PRIMARY KEY,
  execucao_id INTEGER REFERENCES execucao(id) ON DELETE CASCADE,
  unidade TEXT NOT NULL,
  coletado_em TEXT NOT NULL,                   -- ISO COM offset, carimbado na estacao
  coletados INTEGER, unicos INTEGER,
  sem_historico INTEGER, truncado_restante INTEGER,
  estado TEXT CHECK(estado IN ('candidato','corrente','rejeitado','expirado')),
  suspeito INTEGER DEFAULT 0, motivo TEXT,
  arquivo TEXT, sha256 TEXT, bytes INTEGER,
  -- DE QUEM é esta coleta. Cada pessoa entra no SEI com o login dela e traz a
  -- carteira dela; o dado de uma não é o dado da outra. Sai do dono do agente
  -- que publicou.
  --
  -- NULL = coleta COMPARTILHADA, da estação de bootstrap. As primeiras coletas
  -- de uma instalação são assim por necessidade: ninguém configurou a própria
  -- ainda. Elas continuam valendo para quem tem vínculo na unidade, e a tela diz
  -- que são compartilhadas — apagá-las deixaria todo mundo com a tela vazia na
  -- manhã seguinte à mudança.
  dono_usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
  -- DE QUAL INSTALAÇÃO do SEI. `snapshot` e `processo` não colidem por acidente
  -- (carregam `snapshot_id`), mas o índice por mesa e qualquer relatório
  -- agregado passariam a misturar dois órgãos sem dizer. Segurança por acidente
  -- não é segurança: o recorte entra na consulta também onde a chave já protege.
  instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  -- O FUNIL DA CORRIDA. `devidos` e quantos processos precisavam de leitura;
  -- `lidos_de_fato`, quantos foram lidos. Sessao que cai no terceiro processo
  -- com poco quente produziria, sem estes numeros, um snapshot completo e sem
  -- alarme nenhum — 92,6% de reaproveitamento, indistinguivel do regime normal.
  devidos INTEGER, lidos_de_fato INTEGER, servidos_do_poco INTEGER,
  canario_divergencias INTEGER,
  UNIQUE(execucao_id, unidade));
CREATE INDEX IF NOT EXISTS ix_snap_unidade ON snapshot(unidade, estado);

CREATE TABLE IF NOT EXISTS processo(
  snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
  id_sei TEXT NOT NULL, protocolo TEXT, mesa_coleta TEXT,
  tipo_processo TEXT, atribuido_login TEXT, atribuido_nome TEXT,
  marco_unidade TEXT,                          -- data-marco; NUNCA dias_na_unidade
  autuacao TEXT, recebimento TEXT, recebimento_por TEXT, envio TEXT, unidade_envio TEXT,
  mesas_coleta TEXT, mesas_fonte TEXT,   -- mesas_coleta e JSON: um processo pode estar em varias mesas da conta
  gerador_unidade TEXT, gerador_usuario TEXT,
  nivel_acesso TEXT, hipotese_legal TEXT,
  visualizado INTEGER, retorno TEXT, doc_incluido INTEGER,
  marcador TEXT, marcador_cor TEXT, urgente INTEGER, sobrestado INTEGER,
  sem_historico INTEGER, truncado INTEGER, mesas_divergem INTEGER,
  origem TEXT, documentos INTEGER, movimentos INTEGER, emails_enviados INTEGER,
  assinatura_externa INTEGER,
  ultimo_movimento TEXT,                       -- JSON {dh,un,de}
  assuntos TEXT, anexados TEXT,                -- JSON
  -- A REGUA DESTA LINHA. Sem ela o painel mede uma data velha com o relogio de
  -- hoje: uma linha com detalhe de tres dias atras, sob cabecalho verde
  -- "coletado hoje", imprime "388 dias na unidade" para um processo que chegou
  -- ontem. `medido_em` e a hora da leitura que produziu ESTE detalhe.
  medido_em TEXT, morno_em TEXT,
  morno_dono INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
  servido_do_poco INTEGER DEFAULT 0,
  -- historico com buraco: os cinco campos por mesa nao podem ser recalculados
  mov_parcial INTEGER DEFAULT 0,
  -- a unidade desta linha nao aparece na custodia: os cinco campos sao NULOS, e
  -- isso significa "nao sei", nunca "sem divergencia"
  mesa_indeterminada INTEGER DEFAULT 0,
  movimentos_exato INTEGER,
  -- o rotulo do icone de exclamacao, que dira se "novo" e novo para a MESA ou
  -- para a PESSOA. Enquanto nao houver um dia de coleta, doc_incluido nao se
  -- reaproveita.
  doc_incluido_rotulo TEXT,
  -- acompanhamento e por dono: quando nao foi lido nesta coleta, a tela diz
  -- "nao lido", nunca mostra vazio como se fosse ausencia de acompanhamento
  acomp_lido INTEGER DEFAULT 0,
  PRIMARY KEY(snapshot_id, id_sei));
CREATE INDEX IF NOT EXISTS ix_proc_mesa ON processo(mesa_coleta);

-- REFERENCES com ON DELETE CASCADE: sem isso, apagar um snapshot no expurgo
-- deixaria orfao exatamente o texto livre (o que pode citar paciente).
CREATE TABLE IF NOT EXISTS processo_mesa(
  snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
  id_sei TEXT NOT NULL, mesa TEXT, atribuido TEXT);
CREATE INDEX IF NOT EXISTS ix_pmesa ON processo_mesa(snapshot_id, id_sei);

-- Tabela separada de proposito: e onde estao os campos que podem citar paciente.
-- Separar permite decidir depois quem le o texto sem reescrever o modelo.
CREATE TABLE IF NOT EXISTS processo_texto(
  snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
  id_sei TEXT NOT NULL,
  especificacao TEXT, anotacao TEXT, anotacao_autor TEXT, anotacao_data TEXT,
  interessados TEXT, acompanhamento TEXT,      -- JSON
  PRIMARY KEY(snapshot_id, id_sei));

-- descrito_em e a data da COLETA que o resumo descreve, nao a da geracao: e o
-- unico jeito de a tela avisar que o resumo fala de um estado que ja mudou.
-- Aceite de envio à IA, POR UNIDADE. Não é burocracia: o texto que sai é o que
-- os servidores DAQUELA unidade escreveram, e quem responde por essa decisão é a
-- chefia dela — não um admin que ligou uma chave global. Sem esta tabela, um
-- clique numa tela mandava para fora o texto livre de seis unidades de uma vez.
CREATE TABLE IF NOT EXISTS aceite_ia(
  unidade      TEXT PRIMARY KEY,
  nivel        TEXT NOT NULL CHECK(nivel IN ('estruturado','completo')),
  aceito_por   INTEGER REFERENCES usuarios(id),
  aceito_em    TEXT NOT NULL,
  revogado_em  TEXT
);

CREATE TABLE IF NOT EXISTS resumo(
  id_sei TEXT NOT NULL, instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  curto TEXT, longo TEXT,
  descrito_em TEXT, gerado_em TEXT, gerado_por TEXT,
  PRIMARY KEY(id_sei, instancia));

-- `gerado_por` é OBRIGATÓRIO, e a regra é do banco — não de quem escreve o
-- INSERT. Sem ela, os 1.049 resumos existentes entraram com procedência NULA:
-- texto gerado por máquina, exibido numa tela de trabalho, sem dizer QUAL
-- máquina, com que nível de dado, em que versão. Um ano depois ninguém consegue
-- responder "de onde veio esta frase".
--
-- Gatilho em vez de NOT NULL de propósito: mudar a coluna exigiria recriar a
-- tabela num volume de produção, e a migração deste projeto compara colunas —
-- não cobre troca de esquema. O gatilho vale imediatamente e para todo mundo.
CREATE TRIGGER IF NOT EXISTS resumo_exige_procedencia
BEFORE INSERT ON resumo
WHEN NEW.gerado_por IS NULL OR TRIM(NEW.gerado_por) = ''
BEGIN
  SELECT RAISE(ABORT, 'resumo sem gerado_por: registre provedor/modelo/nivel');
END;


-- Integração de IA. Linha única (id=1) porque a chave é do ÓRGÃO, não de cada
-- pessoa: quem paga a API é o contrato, e o custo precisa de um lugar só para
-- ser visto. `nivel` decide o que sai daqui — 'estruturado' não manda texto
-- livre; 'completo' manda, e por isso exige aceite registrado.
CREATE TABLE IF NOT EXISTS config_ia(
  id INTEGER PRIMARY KEY CHECK(id=1),
  ativo INTEGER DEFAULT 0,
  provedor TEXT DEFAULT 'anthropic',
  modelo TEXT DEFAULT 'claude-haiku-4-5-20251001',
  nivel TEXT DEFAULT 'estruturado' CHECK(nivel IN ('estruturado','completo')),
  chave BLOB, nonce BLOB,                      -- cifrada; chave mestra fora do banco
  aceite_em TEXT, aceite_por INTEGER,          -- aceite do nível 'completo'
  gerados INTEGER DEFAULT 0, tokens INTEGER DEFAULT 0,
  ultimo_em TEXT, atualizado_em TEXT);

-- ================================================================== E-MAIL
-- O transporte de saída (Resend). Duas portas de entrada dependem dele —
-- recuperar senha e o código de segundo fator — e as duas ficam DESLIGADAS até
-- alguém provar que um e-mail chega: `teste_ok` é o que arma o resto.
--
-- `teste_ok` volta a zero sempre que a chave ou o remetente mudam. Uma chave
-- nova pode ser de outra conta, de outro plano ou simplesmente errada, e o
-- "teste ok" de ontem passaria a atestar uma chave que já não existe.
CREATE TABLE IF NOT EXISTS config_email(
  id INTEGER PRIMARY KEY CHECK(id=1),
  provedor TEXT DEFAULT 'resend',
  chave BLOB, nonce BLOB,                      -- cifrada; chave mestra fora do banco
  remetente TEXT,                              -- 'Nome <caixa@dominio>' verificado no provedor
  responder_para TEXT,
  testado_em TEXT, teste_ok INTEGER DEFAULT 0, teste_erro TEXT,
  -- SAÚDE DO ENVIO, separada do TESTE. Uma falha momentânea ao mandar um código
  -- carimbava `testado_em` (a coluna que a tela rotula "último teste") e deixava
  -- um erro vermelho ao lado da tag verde "pronto", para sempre, descrevendo um
  -- teste que nunca houve — e nenhum sucesso posterior limpava. São perguntas
  -- diferentes: "o último envio funcionou?" e "alguém já provou que funciona?".
  envio_em TEXT, envio_erro TEXT,
  atualizado_em TEXT);

-- A POLÍTICA DE ACESSO, separada do transporte. Ela existe em tabela e não em
-- constante porque quem liga e desliga o segundo fator é quem administra, e
-- porque desligá-lo é a saída de emergência quando o e-mail para de sair.
--
-- `fator2_papeis` é a lista de papéis que precisam do código. Vazia = ninguém.
-- O padrão nasce vazio DE PROPÓSITO: um segundo fator ligado antes de alguém
-- testar o envio tranca todo mundo do lado de fora ao mesmo tempo, e não há
-- tela por onde destrancar.
CREATE TABLE IF NOT EXISTS config_acesso(
  id INTEGER PRIMARY KEY CHECK(id=1),
  recuperacao_ativa INTEGER DEFAULT 0,
  fator2_papeis TEXT DEFAULT '[]',
  atualizado_em TEXT, atualizado_por INTEGER);

-- RECUPERAÇÃO DE SENHA. Guarda o SHA-256 do token, nunca o token: quem lê o
-- banco não consegue entrar na conta de ninguém com o que encontrou lá — é a
-- mesma regra da tabela `sessoes`.
--
-- A linha não é apagada no uso, é CARIMBADA. "Este token já foi usado, às
-- 14h02, deste IP" é uma resposta que a auditoria precisa dar; uma linha
-- ausente não distingue usado de nunca existiu.
CREATE TABLE IF NOT EXISTS recuperacao(
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  token_sha256 BLOB NOT NULL UNIQUE,
  criado_em TEXT NOT NULL, expira_em TEXT NOT NULL,
  usado_em TEXT, invalidado_em TEXT, motivo_invalidacao TEXT,
  ip_pedido TEXT, ip_uso TEXT);
CREATE INDEX IF NOT EXISTS ix_recuperacao_usuario ON recuperacao(usuario_id, criado_em);

-- O SEGUNDO FATOR. `desafio` É a sessão pendente: ela nasce quando a senha
-- confere e morre quando o código confere — e enquanto vive não serve para
-- nada além da tela do código. Não é uma linha em `sessoes` com uma marca de
-- "ainda não vale": uma marca é uma coluna que alguém esquece de conferir numa
-- consulta, e o custo desse esquecimento é acesso sem segundo fator.
--
-- O código também vai como SHA-256. Ele é curto (seis dígitos) e portanto
-- adivinhável por força bruta se alguém ler o banco — o que limita isso é
-- `tentativas` e a validade curta, não o hash; o hash existe para o código não
-- ficar em texto puro em backup nenhum.
CREATE TABLE IF NOT EXISTS desafio(
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  token_sha256 BLOB NOT NULL UNIQUE,           -- o que vai no cookie da sessão pendente
  codigo_sha256 BLOB NOT NULL,
  criado_em TEXT NOT NULL, expira_em TEXT NOT NULL,
  tentativas INTEGER DEFAULT 0,
  usado_em TEXT, cancelado_em TEXT,
  lembrar INTEGER DEFAULT 0,                   -- o 'continuar conectado' do login que o originou
  ip TEXT, user_agent TEXT);
CREATE INDEX IF NOT EXISTS ix_desafio_usuario ON desafio(usuario_id, criado_em);

-- ===================================================================== POCO
-- O que e do PROCESSO — igual para quem olhar — lido uma vez e reaproveitado.
-- O que e da VISAO de quem olha NAO entra aqui por nenhuma porta: a lista da
-- mesa (marcador, anotacao, atribuido, visualizado, retorno) e sempre relida
-- por pessoa, e custa ~12 requisicoes por mesa. Perigoso e caro sao conjuntos
-- quase disjuntos, e e isso que torna este cache defensavel.
--
-- `parser_versao` entra na chave porque um bloco so vale enquanto o significado
-- dos campos for o mesmo. Coletor que muda o que um campo quer dizer invalida o
-- poco inteiro sem apagar nada.
CREATE TABLE IF NOT EXISTS poco_processo(
  id_sei TEXT NOT NULL,
  -- `id_sei` é o id_procedimento do SEI: sequência autoincremento POR
  -- INSTALAÇÃO. Duas instalações colidem por construção. Sem a instância na
  -- chave, o poço devolveria a uma mesa da FESF o bloco de um processo da
  -- SESAB — e nenhuma trava olharia, porque para ela o id bate.
  instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  parser_versao TEXT NOT NULL,

  -- BLOCO "FRIO": muda muito pouco (medido: 5 mudancas em 5.545 pares de leitura),
  -- mas NAO tem prazo proprio no codigo. Ha um relogio so — `morno_em` —, e um
  -- bloco acima do teto e relido inteiro, autuacao junto. Isso e de proposito:
  -- reler a autuacao custa ZERO requisicao a mais, porque ela vem no mesmo
  -- historico que o resto. `frio_em`/`frio_dono` ficam como PROCEDENCIA (quem leu
  -- estes campos, e quando), nao como prazo.
  autuacao TEXT, gerador_unidade TEXT, gerador_usuario TEXT,
  nivel_acesso TEXT, hipotese_legal TEXT,
  protocolo TEXT, tipo_processo TEXT,
  assuntos TEXT, interessados TEXT,            -- JSON
  -- [] por processo sem assunto e [] por tela indisponivel sao coisas
  -- diferentes. Sem esta marca, servir um valor cheio mostraria a alguem o que
  -- o SEI lhe negaria.
  alterar_disponivel INTEGER,
  frio_em TEXT, frio_dono INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,

  -- BLOCO MORNO: 12 h para servir entre pessoas, teto absoluto de 72 h.
  -- Taxa medida de mudanca: ~9% por dia util.
  mov_custodia TEXT,                           -- JSON: so transicoes de custodia
  movimentos INTEGER, movimentos_exato INTEGER, movimentos_paginas INTEGER,
  documentos INTEGER, emails_enviados INTEGER, assinatura_externa INTEGER,
  anexados TEXT, sobrestado INTEGER, urgente INTEGER,
  mesas TEXT, mesas_fonte TEXT, ultimo_movimento TEXT,
  -- procedencia da LEITURA, nao propriedade do processo: nunca se herda o
  -- sem_historico=0 alheio como se fosse leitura minha.
  leitura_completa INTEGER, truncado_na_origem INTEGER, mov_parcial INTEGER,
  morno_em TEXT, morno_dono INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,

  -- O SEGUNDO RELOGIO, do servidor. A validade exige as duas datas dentro do
  -- prazo; assim relogio torto na estacao nao estica nem encurta o cache.
  recebido_em TEXT NOT NULL,
  PRIMARY KEY(id_sei, instancia, parser_versao));

-- A GUARDA. O que a lista da mesa mostrava quando o detalhe foi lido. Nunca e
-- servida a ninguem: so responde "mudou?". Ela ve o barulho (marcador novo,
-- anotacao, troca de atribuicao) e e CEGA ao silencio — por isso a faxina
-- prioriza justamente o que ela nao alcanca.
CREATE TABLE IF NOT EXISTS poco_conferencia(
  id_sei TEXT NOT NULL, instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  mesa TEXT NOT NULL,
  hash TEXT NOT NULL, em TEXT NOT NULL,
  PRIMARY KEY(id_sei, instancia, mesa));

-- ACOMPANHAMENTO NAO ATRAVESSA PESSOA. E o unico campo caro sem detector
-- gratuito, e nao esta provado que a tela do SEI nao recorta por usuario: na
-- CESS ha grupos com nome de pessoa alimentados so por ela. Fica por dono ate o
-- teste de duas contas na mesma mesa dizer o contrario. Custa ~19 s por pessoa
-- por dia — a apolice mais barata do desenho.
--
-- Nao confundir com a tabela `acompanhado` (mais abaixo, fora do poco): aquela
-- e a lista PESSOAL da pessoa, atravessando mesas; esta e cache da tela do SEI,
-- por mesa e por dono.
CREATE TABLE IF NOT EXISTS poco_acompanhamento(
  id_sei TEXT NOT NULL, instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  mesa TEXT NOT NULL,
  dono_usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  dados TEXT, grupos TEXT, em TEXT NOT NULL,
  PRIMARY KEY(id_sei, instancia, mesa, dono_usuario_id));

-- RESERVA. Todo mundo nasce agendado para 07:30. Sem reserva, as 31 pessoas da
-- CESS recebem o MESMO plano de 254 processos no mesmo minuto e a economia do
-- dia e zero — 39 mil requisicoes para produzir 254 blocos identicos. Reserva
-- vencida volta a fila sozinha: agente que morre no meio nao tranca nada.
CREATE TABLE IF NOT EXISTS poco_reserva(
  id_sei TEXT NOT NULL, instancia TEXT NOT NULL DEFAULT 'SEI-SESAB',
  execucao_id INTEGER REFERENCES execucao(id) ON DELETE CASCADE,
  reserva_ate TEXT NOT NULL,
  PRIMARY KEY(id_sei, instancia));
CREATE INDEX IF NOT EXISTS ix_reserva_ate ON poco_reserva(reserva_ate);

-- ===================================================================== BUSCA
-- Uma pesquisa que a PESSOA pediu ao SEI, com o login DELA, rodada pelo agente.
--
-- É TERMINAL, e isso é o desenho, não uma limitação: o resultado não vira
-- snapshot, não entra no poço, não cria linha em `processo` e não é servido a
-- mais ninguém. A tela de resultado do SEI não prova que aquele processo
-- pertence à mesa de quem buscou — ela responde à pergunta que foi feita. Deixar
-- isso alimentar a carteira seria transformar um filtro numa fonte de verdade.
--
-- É de UMA pessoa. Não há leitura por gestor nem por admin: quem não pediu não vê.
CREATE TABLE IF NOT EXISTS busca(
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  instancia TEXT NOT NULL,
  conta TEXT,                                  -- login do SEI usado, jamais a senha
  mesa TEXT,                                   -- a mesa PEDIDA
  mesa_confirmada TEXT,                        -- a que o SEI relatou ter ficado ativa
  filtros TEXT NOT NULL,                       -- JSON, da pessoa e com prazo
  filtros_sha TEXT,                            -- 6 hex: "foi a mesma busca?" sem o quê
  estado TEXT NOT NULL CHECK(estado IN
    ('pedida','entregue','em_curso','completa','parcial','vazia','falhou','cancelada')),
  motivo TEXT,
  -- O SEI DECLARA quantos registros achou. Guardar os dois números é o que
  -- separa "vieram 607 de 607" de "vieram 607 e ninguém conferiu" — o sistema
  -- irmão captura esse total e nunca o compara, e por isso uma paginação que
  -- falha no meio devolve metade com cara de tudo.
  total_declarado INTEGER, colhidos INTEGER,
  paginas_lidas INTEGER, paginas_teto INTEGER,
  execucao_id INTEGER REFERENCES execucao(id) ON DELETE SET NULL,
  pedida_em TEXT NOT NULL, entregue_em TEXT, terminada_em TEXT, duracao_s INTEGER);
CREATE INDEX IF NOT EXISTS ix_busca_dono ON busca(usuario_id, pedida_em);

-- As linhas do resultado. SÓ o que a tela de resultado do SEI mostra, e nada de
-- texto livre: `especificacao`, `anotacao` e `interessados` são os campos que
-- podem citar paciente — por isso vivem em `processo_texto`, separados, e o
-- consentimento para tratá-los é por unidade (`aceite_ia`). Guardá-los aqui
-- seria criar um segundo caminho para o mesmo dado, sem o mesmo cuidado.
CREATE TABLE IF NOT EXISTS busca_item(
  busca_id INTEGER NOT NULL REFERENCES busca(id) ON DELETE CASCADE,
  ordem INTEGER NOT NULL,
  id_sei TEXT, protocolo TEXT, tipo_processo TEXT,
  unidade_geradora TEXT, usuario_gerador TEXT, data_inclusao TEXT,
  PRIMARY KEY(busca_id, ordem));

-- Uma busca por conta do SEI, de cada vez.
--
-- O motivo é medido, não é prudência: a troca de mesa no SEI é por USUÁRIO, não
-- por sessão. Duas buscas simultâneas da mesma conta em mesas diferentes
-- devolvem a carteira errada SEM ERRO — o sistema irmão desta casa desabilitou o
-- paralelismo por isso, depois de ver todos os workers voltarem com 0 linhas.
--
-- A trava é por (instância, conta), não por pessoa: quem tem conta nas duas
-- instalações pode buscar nas duas ao mesmo tempo, porque são sessões de
-- servidores diferentes.
CREATE TABLE IF NOT EXISTS busca_trava(
  instancia TEXT NOT NULL, conta TEXT NOT NULL,
  busca_id INTEGER REFERENCES busca(id) ON DELETE CASCADE,
  ate TEXT NOT NULL,
  PRIMARY KEY(instancia, conta));

CREATE TABLE IF NOT EXISTS alerta(
  id INTEGER PRIMARY KEY, ts TEXT, tipo TEXT, severidade TEXT,
  execucao_id INTEGER, unidade TEXT, texto TEXT,
  reconhecido_por INTEGER, reconhecido_em TEXT);
CREATE INDEX IF NOT EXISTS ix_alerta_ts ON alerta(ts);

-- ============================================================ ACOMPANHAMENTO
-- A lista de processos que a pessoa segue mesmo FORA das mesas dela. Tabela
-- separada de `processo` de propósito: processo acompanhado não é carteira,
-- não vira snapshot e não entra em relatório nenhum. Se entrasse, todo número
-- do produto passaria a misturar "o que é meu" com "o que eu observo".
--
-- A chave é o PROTOCOLO, não o `id_sei`: o número é o que a pessoa tem na mão,
-- e o id interno do SEI só se conhece depois da primeira leitura.
--
-- Não confundir com `poco_acompanhamento` (linha ~542): aquele é cache da tela
-- "Acompanhamento Especial" do SEI, por mesa e por dono; esta é a lista
-- pessoal da pessoa, atravessando mesas — nome parecido, coisas diferentes.
CREATE TABLE IF NOT EXISTS acompanhado(
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  -- SEM default, ao contrário das tabelas antigas deste arquivo. `coleta.py`,
  -- `configuracao.py` e `ingestao.py` cada um documenta um defeito medido em que
  -- cair calado em 'SEI-SESAB' carimbou dado da FESF como SESAB. As tabelas que
  -- ainda têm o default o carregam como bagagem de linhas anteriores à FESF
  -- existir; esta nasce hoje, e quem grava resolve a instância explicitamente.
  instancia TEXT NOT NULL,
  protocolo TEXT NOT NULL,
  id_sei TEXT,
  origem TEXT NOT NULL,                   -- 'manual'|'painel'|'sei_acompanhamento'
  nota TEXT,
  adicionado_em TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'novo'
    CHECK(estado IN ('novo','lido','sem_acesso','nao_encontrado')),
  -- É a ÚLTIMA leitura, valor que se atualiza a cada leitura — como
  -- `ultimo_contato_em` — e não um carimbo de transição de estado.
  lido_em TEXT,
  -- QUANTAS VEZES ESTE ITEM FOI ENTREGUE À ESTAÇÃO HOJE SEM VOLTAR LEITURA.
  -- Zerado assim que uma leitura chega, de qualquer fonte.
  --
  -- Sem isto, falha TÉCNICA — que de propósito não carimba `lido_em`, para o
  -- item continuar pendente — reoferecia o mesmo processo a cada batida do
  -- agendador: 34 ciclos por dia x 100 itens x 5 requisições ≈ 17 mil
  -- requisições diárias contra o SEI do órgão, três vezes a coleta inteira, cada
  -- ciclo abrindo um Chromium, e nada no sistema percebendo. Queda de sessão já
  -- era barata (a estação para no primeiro `SESSAO`); o caro era a falha
  -- sistemática que NÃO é sessão — parse, DOMException, rede intermitente.
  --
  -- CONTA ENTREGA, NÃO FALHA RELATADA, e isso é deliberado: a estação que morre
  -- com o Chromium aberto depois de ler 100 processos não relata nada, e é
  -- justamente esse o caso que custa as 500 requisições. Contar o que o servidor
  -- ENTREGOU cobre os dois, e não depende de campo novo vindo de fora.
  tentativas INTEGER NOT NULL DEFAULT 0,
  -- QUANDO foi a última entrega. É o que faz `tentativas` significar "hoje": sem
  -- data, um item que falhou três vezes numa terça ficaria parado para sempre, e
  -- o recuo viraria desistência silenciosa.
  tentativa_em TEXT,
  PRIMARY KEY(usuario_id, instancia, protocolo));

-- O HISTÓRICO: uma linha por leitura. Existe para "o que mudou" ser DIFERENÇA
-- MEDIDA, e não texto escrito à mão em algum lugar. É também a primeira série
-- temporal do produto — todos os relatórios são retrato de um instante, e o
-- snapshot velho é expurgado em 30 dias.
--
-- `fonte` e `medido_em` não são enfeite: a leitura pode vir da carteira, que
-- pode ser de dias atrás (medido: nove dias úteis, em 10/09/2026). Carimbar isso
-- como "lido hoje" seria mentir.
CREATE TABLE IF NOT EXISTS acompanhado_leitura(
  id INTEGER PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  instancia TEXT NOT NULL,
  protocolo TEXT NOT NULL,
  lido_em TEXT NOT NULL,
  fonte TEXT NOT NULL,                    -- 'carteira' | 'sei'
  medido_em TEXT,
  aberto_em TEXT,                         -- JSON: lista de unidades
  -- 'arvore' aqui é a linha "Processo aberto nas unidades: ..." que o próprio SEI
  -- publica no topo da árvore (`Nos[0].html`), e NÃO a lista histórica de
  -- unidades dos metadados — que é a que o projeto irmão `sei_sistema` corrige
  -- computando do andamento. Medido em 10/09/2026 sobre 15 coletas do SEI360,
  -- com a própria lista da mesa como terceira fonte: em 1.278 discordâncias
  -- observáveis entre a linha da árvore e a máquina de estados do andamento, a
  -- árvore bateu com a mesa em 100% dos casos e o andamento em 0%.
  aberto_em_fonte TEXT,                   -- 'arvore' | 'andamento'
  ultimo_movimento TEXT,                  -- JSON {dh, un, de}
  documentos INTEGER,
  movimentos INTEGER,
  mudou TEXT,                             -- JSON do delta; NULL na 1a leitura
  -- POR QUE `mudou` está nulo — que são TRÊS coisas diferentes: 'primeira' (não
  -- havia leitura anterior), 'sem_avanco' (havia, mas esta medição não é mais
  -- nova que a dela, então não há observação nova a comparar) e 'comparada'
  -- (comparou, e o processo não mudou).
  --
  -- Sem esta coluna a tela afirmava a TERCEIRA para as três: imprimia "sem
  -- mudança" sobre item que nunca foi comparado. É o espelho exato da falsidade
  -- que `delta()` se recusa a cometer ao devolver None na primeira leitura — e
  -- quem lê a tela decide com base nisso.
  comparacao TEXT CHECK(comparacao IN ('primeira','sem_avanco','comparada')),
  -- A leitura morre com a lista. `remover()` já apaga as duas, mas a FK é o que
  -- garante isso quando o DELETE vier de outro lugar — do expurgo, de um
  -- ON DELETE CASCADE de `usuarios`, ou da mão de alguém no shell. É o mesmo
  -- par lista/detalhe de `busca`/`busca_item` e `snapshot`/`processo`.
  FOREIGN KEY(usuario_id, instancia, protocolo)
    REFERENCES acompanhado(usuario_id, instancia, protocolo) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS ix_acomp_leitura
  ON acompanhado_leitura(usuario_id, instancia, protocolo, id DESC);
"""


def _colunas_do_ddl(ddl):
    """Extrai {tabela: {coluna: definicao}} do próprio DDL.

    Derivar do DDL em vez de manter uma lista à parte: lista paralela envelhece
    no primeiro dia em que alguém acrescenta uma coluna e esquece de atualizá-la,
    e o sintoma seria a migração silenciosamente não migrar.
    """
    import re
    # COMENTÁRIO SAI ANTES DE ACHAR A TABELA, e não depois de recortá-la. A
    # expressão abaixo é não-gulosa e para no PRIMEIRO `);` — então um `);`
    # escrito dentro de um comentário do DDL truncava o corpo da tabela ali, e as
    # colunas depois dele simplesmente não existiam para a migração. Medido em
    # 11/09/2026: `acompanhado.tentativas` e `.tentativa_em` não eram criadas em
    # banco existente, e o sintoma seria "no such column: tentativas" no meio de
    # uma tela, em produção, meses depois de o DDL estar certo. Recortar primeiro
    # e limpar depois era o inverso da ordem necessária.
    ddl = re.sub(r"--[^\n]*", "", ddl)
    tabelas = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\);", ddl, re.S):
        nome, corpo = m.group(1), m.group(2)
        colunas, nivel, atual = {}, 0, ""
        for ch in corpo + ",":
            if ch == "(":
                nivel += 1
            elif ch == ")":
                nivel -= 1
            if ch == "," and nivel == 0:
                item = " ".join(atual.split())
                atual = ""
                if not item:
                    continue
                # A primeira PALAVRA, sem o que vier grudado. `UNIQUE(a, b)` tem
                # `UNIQUE(a,` como primeiro token — comparar o token inteiro
                # deixava a restrição passar por coluna e gerava
                # "ALTER TABLE ... ADD COLUMN UNIQUE(...)".
                primeira = re.match(r"[A-Za-z_]+", item)
                primeira = primeira.group(0).upper() if primeira else ""
                if primeira in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"):
                    continue
                nome_col, definicao = item.split()[0], " ".join(item.split()[1:])
                if not re.fullmatch(r"[A-Za-z_]\w*", nome_col):
                    continue
                colunas[nome_col] = definicao
            else:
                atual += ch
        tabelas[nome] = colunas
    return tabelas


def migrar():
    """Cria o que falta E acrescenta coluna nova em tabela que já existe.

    `CREATE TABLE IF NOT EXISTS` NÃO altera tabela existente: acrescentar uma
    coluna ao DDL não a cria em banco antigo, e o erro só aparece em produção,
    como "table X has no column named Y", no meio de uma tela. Aconteceu aqui
    com `config_usuario.modo_coleta`. Por isso a migração compara o DDL com o
    que o banco realmente tem, coluna por coluna.
    """
    conferir_escrita()
    cx = conectar()
    cx.executescript(DDL)
    # CHAVE, nao coluna. O SQLite nao tem ALTER TABLE que mude PRIMARY KEY, e
    # `CREATE TABLE IF NOT EXISTS` nao reescreve tabela existente: sem isto, um
    # banco ja criado ficaria com `credencial` chaveada so por `usuario_id` — e
    # cadastrar a segunda instancia apagaria a primeira em silencio.
    import migracao_instancia as _mig
    reconstruidas = _mig.migrar_instancia(cx, DDL, _colunas_do_ddl)
    if reconstruidas:
        # O DROP levou junto os indices e o GATILHO `resumo_exige_procedencia`.
        # Quem sabe recria-los e o DDL, e ele e todo IF NOT EXISTS.
        cx.executescript(DDL)
    acrescentadas = []
    for tabela, colunas in _colunas_do_ddl(DDL).items():
        existentes = {r["name"] for r in cx.execute(f"PRAGMA table_info({tabela})")}
        if not existentes:
            continue
        for col, definicao in colunas.items():
            if col in existentes:
                continue
            # ALTER TABLE ADD COLUMN do SQLite aceita MUITO pouco: nada de
            # UNIQUE, PRIMARY KEY, CHECK ou NOT NULL sem default. Em vez de
            # tentar limpar a definição por subtração — que já falhou com
            # "near UNIQUE: syntax error" —, montamos por adição: o tipo, e o
            # DEFAULT quando houver. É o que basta para a linha antiga continuar
            # legível; a restrição real vive no DDL, para bancos novos.
            import re as _re
            partes = definicao.split()
            tipo = partes[0] if partes and partes[0].upper() in (
                "TEXT", "INTEGER", "BLOB", "REAL", "NUMERIC") else "TEXT"
            m_def = _re.search(r"DEFAULT\s+('[^']*'|\S+)", definicao, _re.I)
            sufixo = f" DEFAULT {m_def.group(1)}" if m_def else ""
            cx.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} {tipo}{sufixo}")
            acrescentadas.append(f"{tabela}.{col}")
    cx.commit()
    cx.close()
    if reconstruidas:
        print("migração reconstruiu (instância na chave):", ", ".join(reconstruidas))
    if acrescentadas:
        print("migração acrescentou:", ", ".join(acrescentadas))
    return BANCO


def registrar(cx, usuario_id, acao, alvo=None, unidade=None, ip=None):
    """Log de acesso. Chamado em toda leitura de carteira e em toda mutacao —
    sem isso nao ha como responder 'quem viu o que' num incidente."""
    cx.execute("INSERT INTO log_acesso(ts,usuario_id,acao,alvo,unidade,ip) VALUES(?,?,?,?,?,?)",
               (agora(), usuario_id, acao, alvo, unidade, ip))


if __name__ == "__main__":
    print("banco criado em", migrar())
