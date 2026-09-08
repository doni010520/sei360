# SEI360 no EasyPanel

> **A RECEITA DE DEPLOY NÃO MORA MAIS AQUI.** Ela está em
> [`../ARQUITETURA_ACESSO.md`](../ARQUITETURA_ACESSO.md), **§3.6-bis** — build
> context, Dockerfile, porta, volume, memória e a lista de variáveis que o código
> de fato lê. Este arquivo guarda o que aquela seção não cobre: o primeiro
> acesso, o volume, os pré-requisitos e a conferência depois de subir.
>
> Duas receitas divergindo foi o defeito que este aviso existe para não repetir.
> Até 26/08/2026 este documento ainda dizia "não há Chromium, não há Playwright",
> "256 MB de RAM bastam (sem navegador)" e "o container não precisa alcançar o
> SEI" — três afirmações que a decisão de 21/08 (§6.0) revogou, e que continuavam
> aqui porque quem mudou a arquitetura mudou o outro arquivo.

## 1. O que mudou, e por que este aviso existe

Em 21/08/2026 o dono do sistema decidiu hospedar em VPS próprio e **executar a
busca avançada dentro do container**. A consequência atravessa tudo o que este
documento dizia:

| O que o LEIAME dizia | O que vale hoje |
|---|---|
| "Não há Chromium, não há Playwright" | A imagem instala **Chromium**; a busca roda aqui |
| "256 MB de RAM e 0,5 vCPU bastam" | **Mínimo 2 GB** — ~0,45 GB por busca simultânea |
| "O container não precisa alcançar o SEI" | Ele **precisa**: teste `sip.seibahia.ba.gov.br` de dentro do VPS antes de tudo |
| "Build: Dockerfile na raiz deste diretório" | Contexto é a **raiz do repositório**; `-f sei360/servidor/Dockerfile` |
| Sem serviço extra | Continua um serviço só — o executor de busca é uma thread, e **um por container** |

**Antes do primeiro build**, a ordem que o `conferir_contexto.py` imprime — e ela
é obrigatória, porque o passo 3 sem o passo 2 quebra a coleta agendada da estação
em silêncio:

```bash
python sei360/servidor/conferir_contexto.py
```

Ele sai **0** quando a imagem pode ser construída, e enquanto sair 1 diz
exatamente o que falta.

**Desde 04/09/2026 o Source é GitHub** (`doni010520/sei360`, branch `main`, Auto
Deploy ligado) — o EasyPanel clona e builda sozinho a cada `git push`; o portão
acima continua obrigatório antes de cada push, só que local, sem confirmação do
lado do EasyPanel.

**Subindo por Upload (sem Git)?** `python sei360/servidor/conferir_contexto.py --empacotar`
gera o ZIP certo — só depois de o portão acima sair 0. Não zipe a pasta pelo
Explorer: ela carrega o banco de produção e a sessão do SEI, e um upload não tem
"desfazer".

> **Nota de 07/09/2026.** O portão acima fecha limpo — sai 0 — desde
> 01/09/2026, porque o bloco CONFIG do `automacao_sei.js` foi esvaziado nesse
> dia. **Isso não quer dizer que a Fatia 0 terminou**: o CONFIG foi esvaziado
> **sem** semear antes a nova senha no perfil da estação (a ordem exigida é
> rotacionar → semear → esvaziar; ver `ARQUITETURA_ACESSO.md` §3.6-bis), e a
> tarefa `SEI_SESAB_Coleta` está desabilitada desde 27/08/2026. **A rotação da
> senha (A0) continua sem registro em documento ou banco nenhum**
> (`credencial_rotacionada_em` permanece NULL). Ver
> `PLANO_EXECUCAO_2026-09-07.md` §0 e §3 (S1–S3).

## 2. Variáveis de ambiente

A lista completa está em `../ARQUITETURA_ACESSO.md` §3.5 — inclusive as que o
documento pediu por meses e **o código nunca leu** (`SEI360_DB`,
`SEI360_SNAPSHOTS`, `FERIADOS_BA`, `SMTP_*`, `AUDIT_SINK_*`). *(Corrigido em
07/09/2026: esta lista incluía `SEI360_SECRET_KEY` — errado, ver
`ARQUITETURA_ACESSO.md:130`: ela é **também aceita**, como alias de
`SEI360_SEGREDO`.)*

O mínimo para o serviço não subir pela metade:

| Variável | Por quê |
|---|---|
| `SEI360_CHAVE_MESTRA` | AES-256-GCM do cofre. **Sem ela não há busca nenhuma**, e nada na tela de saúde acusa |
| `TZ=America/Bahia` | as janelas de coleta e os prazos |
| `SEI360_FORCAR_HTTPS=1` | se o proxy não mandar `X-Forwarded-Proto`, o cookie sai sem `Secure` |
| `SEI360_SEGREDO` | recomendada; veja no §3.5 o que ela protege — e o que não |
| `SEI360_BUSCAS_SIMULTANEAS` | padrão 2; é o teto de MEMÓRIA, não de fila |
| `SEI360_BASE_URL` | opcional — só se for ligar a recuperação de senha por e-mail; ver §3.5-bis |

**A chave mestra não pode morar no painel do EasyPanel.** É ela que abre a senha
do SEI de todo mundo, e guardá-la na mesma tela em que se lê o log e se abre o
Terminal do container anula o cofre.

## 3. Primeiro acesso, numa instalação vazia

O esquema é criado **no import** do `app.py` (o `CMD` é `gunicorn app:app`, que
importa o módulo e nunca executa o bloco `__main__` — este foi um defeito real,
achado em auditoria: o container subia "verde" e respondia 500 em todas as rotas).

Falta criar a conta de administração. No terminal do container:

```bash
python semear.py --so-contas
```

Isso imprime **uma vez** a senha provisória de `admin@sei360.local` e um código
de vínculo de agente. A senha não vai por e-mail, não fica legível no banco e
exige troca antes de qualquer tela. Acrescente `--demo` **apenas** em ambiente de
teste: ele cria contas de exemplo com e-mail previsível.

**`admin@sei360.local` é um endereço que não existe** (domínio reservado, RFC
6762) — de propósito, para o bootstrap não depender de e-mail nenhum. Se for
usar recuperação de senha ou segundo fator para o próprio admin mais tarde,
troque esse e-mail primeiro (`/admin/usuarios`, editar) para um endereço real;
enquanto ele continuar em `.local`, o sistema recusa ligar o segundo fator para
o papel `admin` (ver §3.5-bis) e a recuperação nunca alcança essa conta.

### Cada pessoa configura a própria coleta

Depois de entrar, cada usuário vai em **Configuração da coleta** (menu de conta, no
canto superior direito do painel) e percorre cinco passos: sistema, o login com que
ela entra no SEI, quais mesas, em que horários e qual estação executa.

**Nota de 07/09/2026 — corrigido.** Os dois parágrafos abaixo descreviam só o
modo `estação`, como se fosse o único. Desde 26/08/2026 o **modo padrão é
`servidor` (cofre)**: a pessoa digita a senha do SEI no painel, e ela fica
**cifrada no cofre do servidor** (AES-256-GCM, chave em `SEI360_CHAVE_MESTRA`),
decifrada **em memória, só no instante em que uma busca é executada**
(`ARQUITETURA_ACESSO.md` §6.0, §6.1) — é o que permite a busca avançada rodar
sem depender de estação nenhuma ligada.

O modo **estação** continua existindo, como alternativa: quem prefere não
guardar a senha no servidor a digita no agente, na estação da própria pessoa, e
ela vai para o Gerenciador de Credenciais do Windows — nesse modo, e só nesse, o
servidor nunca a vê. A pessoa escolhe entre os dois em `/configuracao`, e a tela
diz com todas as letras qual está em vigor: o SEI carimba o nome da pessoa em
cada movimento, e a diferença entre os dois modos é **quem mais, além dela,
passa a ser capaz de agir com a credencial** — ver `ARQUITETURA_ACESSO.md` §6.0
e §6.3 para o conjunto de quem consegue ler a senha no modo servidor.

Quem só vai **ler** a carteira não precisa de nada disso: entra e lê o que a coleta
de outra pessoa já trouxe para as unidades a que ela tem vínculo. A coleta é
compartilhada por unidade (duas pessoas da mesma mesa não coletam duas vezes); quem
decide o que cada um enxerga é o vínculo de unidade dado pelo admin, não a
configuração de coleta.

Ainda em `/admin`:

1. **Agentes → Unidades que este agente pode publicar.** Numa instalação nova não
   há snapshot nenhum, logo não há lista de unidades para escolher — por isso o
   campo é texto livre, uma sigla por linha (`SESAB/SAIS/DGGUP/DGESS/CESS`, …).
   Sem escopo, toda publicação é recusada com 409, e é assim mesmo: escopo vazio
   não pode significar "pode tudo".
2. **Agentes → Novo código de vínculo** e, na estação:
   ```bash
   python sei360_agente.py vincular --codigo <código> --servidor https://seu.dominio
   python sei360_agente.py instalar-tarefa
   ```
3. **Usuários → Nova conta**, com o vínculo de unidade de cada pessoa.

## 4. Volume: use volume nomeado, não bind mount

A aplicação roda como uid **10001**, sem privilégio. Volume nomeado do EasyPanel
herda o dono do `/dados` da imagem e nasce gravável. **Bind mount** de diretório
do host chega como `root:root` e o processo não escreve — o sintoma seria
"attempt to write a readonly database" no meio de um login. O `banco.py` confere
isso no start e para com mensagem explícita em vez de falhar horas depois.

Se precisar mesmo de bind mount: `chown -R 10001:10001 <caminho no host>`.

**Backup é o volume inteiro.** Ele contém dado pessoal de saúde: nome, e-mail
institucional e especificação de processo que pode citar paciente. Backup cifrado,
com chave fora do mesmo host.

## 5. Antes de expor o domínio

Nada disto é técnico, e tudo isto está no `../ARQUITETURA_ACESSO.md` §2.2:

- **A0** — rotacionar a senha do SEI que esteve em texto puro no `automacao_sei.js`
- **A1** — termo de isolamento por unidade
- **A2** — termo de imputação nominal (a trilha do SEI registrará atos de máquina
  em nome da titular da credencial)
- **A3/A4** — ato designando a controladora, base legal e registro de tratamento
- **A5** — lista nominal de quem tem acesso ao painel do EasyPanel, com MFA
- **A6** — decisão datada sobre o local do host. **Fora do Brasil está descartado**:
  é transferência internacional de dado de saúde

**O sistema já sabe pedir código por e-mail (segundo fator), mas ele nasce
DESLIGADO** — armar exige configurar o Resend em `/admin`, mandar um teste que
chegue, e nenhuma conta ativa do papel escolhido pode estar num domínio que não
recebe e-mail (as contas de demonstração `@sei360.local` estão nessa situação:
troque o e-mail delas, ou deixe o segundo fator só para os papéis com e-mail
real). Enquanto ele não estiver ligado, restrinja a origem (VPN ou faixa de IP
do órgão) no Traefik. Uma tela de login sem MFA protegendo dado sensível, achável
por varredura de certificado, é uma aposta.

## 6. O que ainda não existe

> Revisto em 26/08/2026. Antes desta data esta seção descrevia um sistema
> sem navegador no container.


Honestidade sobre o estado, para ninguém descobrir em produção:

- **O expurgo roda sozinho, de forma oportunista — não por agendador dedicado.**
  *(Corrigido em 07/09/2026: esta linha dizia que ninguém o disparava e que
  faltava agendá-lo; não é mais verdade.)* `_faxina_se_devida` (`app.py:2543-2582`)
  chama `expurgo.py` a cada 20 h, verificado dentro do ciclo normal de
  requisições do servidor — não é um cron nem uma thread própria: só dispara se
  alguém bater numa rota nesse intervalo. `expurgo.py` apaga snapshot histórico
  com mais de 30 dias, log de acesso com mais de 180 e sessão morta — e nunca
  toca no snapshot **corrente** de uma unidade, por mais velho que seja (apagar
  deixaria a unidade em branco, e branco lê-se como "nada parado"). Continua
  existindo o botão manual em `/admin` e `python expurgo.py`. **Risco que
  fica:** por ser oportunista, depende de tráfego; um fim de semana sem ninguém
  abrir o painel é um fim de semana sem faxina, e nada avisa disso.
- **A imagem nunca foi construída.** Não havia Docker na estação de
  desenvolvimento. O código foi exercitado sob as condições do container
  (volume vazio, módulo importado sem `__main__`, `X-Forwarded-Proto`), e as duas
  suítes locais somam 95 verificações — mas `docker build` e `docker run`
  continuam sem prova. `teste_container.py` está escrito e espera o Docker.
  **Faça o primeiro deploy olhando o log.**

- **Um admin redefine a senha de outro admin** e vê a provisória na tela. Fica no
  `log_acesso`, mas não há segundo par de olhos nem aviso ao dono da conta. Com
  poucos administradores nomeados (A5) é aceitável; com muitos, não é.
- **Chave de assinatura do agente é o próprio token**, que viaja no mesmo request:
  a assinatura garante integridade, não sigilo.
- **API paginada** (Fatia 6): hoje o painel recebe a carteira inteira da unidade
  numa página só.

## 7. Conferência rápida depois do deploy

```bash
curl -s https://seu.dominio/saude
```

Deve responder `{"ok": true, "unidades_correntes": N, "versao": "..."}`. Se vier
500, veja o log: quase sempre é o volume não gravável (§4).

O `/saude` não devolve o detalhe por unidade de propósito — sigla com contagem e
data de coleta é inventário da carteira, e o endpoint fica exposto sem sessão.
