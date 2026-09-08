# SEI360 — Levantamento e plano de execução

**Data:** 07/09/2026. **Base:** código em `C:\Claude\sei_sistema\sei360`, banco de trabalho
`servidor/_dados/sei360.db` (só leitura), logs da estação (`painel_sesab/_logs`), agendador do
Windows, extrator irmão (`sei_sistema/sei_extractor.py`), e quatro varreduras independentes
(documentação, caminho FESF, caminho SESAB, saúde do código) conferidas por amostragem.
**Nenhuma linha de código foi alterada neste levantamento. Este documento planeja; não executa.**

Linha citada como `arquivo:linha` vale para o instante da leitura (07/09, tarde).

---

## 0. Resumo executivo

1. **A coleta SESAB está parada há 11 dias — e não existe credencial em lugar nenhum.** A tarefa
   `SEI_SESAB_Coleta` está **desabilitada** (última execução 27/08 07:30). O bloco CONFIG do
   `painel_sesab/automacao_sei.js` foi esvaziado em 01/09 09:54 (passo 3 da Fase 00) **sem** a
   semeadura no perfil (passo 2): `__SEI_CRED` não existe em `_perfil_sei`, o cofre (`credencial`)
   tem 0 linhas. Só o cookie de sessão de 01/09 11:11 sustentaria um login. O painel mostra 27/08
   porque `ingestao.py` foi rodado à mão em 01/09; **11 das 14 coletas em disco nunca entraram no
   banco** (12, 13, 15, 16, 17, 19, 20, 22, 23, 24 e 25/08).
2. **A FESF nunca coletou uma linha — por desenho e por um laço fechado.** O modelo de dados e o
   encanamento da busca estão prontos para duas instalações (instância na chave, trava por
   `(instancia, conta)`, perfil, envelope). Mas a tela de configuração recusa a FESF
   (`servidor/app.py:1058-1059`), a validação exige `@` no login (`app.py:1070-1071`) enquanto o
   login FESF é `nome.sobrenome` (`servidor/perfil_sei.py:128`), o vínculo de unidade exige snapshot
   prévio (`app.py:1809-1811`) e **não existe parser da listagem do SEI 4.0**
   (`perfil_sei.py:134-138`). **Porém:** o extrator irmão (`sei_sistema/sei_extractor.py`) já lê o
   Controle de Processos da FESF em **33 mesas, todo dia** (03/09: 1.270 processos em 28 min, 0
   mesas com erro) — é o oráculo de contagem e o mapa de seletores para o parser 4.0.
3. **A imagem Docker nunca foi construída** (sem Docker na estação; `teste_container.py` nunca
   rodou). O portão de build **fecha limpo hoje** (`conferir_contexto.py` sai 0 porque o CONFIG está
   vazio): `--empacotar` já gera o ZIP para o EasyPanel.
4. **O caminho crítico é decisão e operação, não código.** A0–A6 sem assinatura, dono ou prazo;
   P1–P10 abertas (P1 foi respondida de fato pela escolha da HostGator em 21/08, sem registro); o
   agente de coleta não tem dono e por isso o servidor recusa tarefa para sempre
   (`app.py:2681-2686`); `SEI360_CHAVE_MESTRA` não está no ambiente do processo (cofre desligado,
   busca parada — `servidor/_dados/_servidor.log:4`).
5. **Documentação:** o objetivo existe (`SPECS.md:11-17`) mas não cobre busca, poço, 2FA nem FESF;
   **não há critério de sucesso de produto** (só "pronto" técnico por fatia); a FESF não tem escopo
   institucional em documento nenhum; há **12 contradições** entre documentos, quatro delas no
   `ARQUITETURA_ACESSO.md` contra a própria revogação de 21/08.

**Caminho recomendado** (detalhe no §5): (a) recolocar a SESAB em pé hoje, pela estação, na ordem
certa; (b) provar a imagem e subir no EasyPanel; (c) trocar a ingestão manual pelo agente pull com
dono; (d) destravar a FESF no produto e escrever o parser 4.0 **no mesmo coletor**, validado contra o
irmão; (e) só então busca, 2FA e IA.

---

## 1. Onde o sistema está hoje (medido em 07/09)

| Componente | Estado | Prova |
|---|---|---|
| Coletor SESAB (estação) | funciona: 12 mesas, 1.182 processos, 15m07s | `painel_sesab/_logs/coleta_20260827.log` |
| Tarefa agendada | **desabilitada** desde 27/08; logon interativo; a máquina esteve ligada (eventos 31/08) | `Get-ScheduledTask SEI_SESAB_Coleta` |
| Credencial SESAB | **nenhuma**: CONFIG vazio (mtime 01/09 09:54), `__SEI_CRED` em 0 arquivos do leveldb, `credencial` 0 linhas; cookie de 01/09 11:11 | `conferir_contexto.config_preenchido`, `_perfil_sei`, banco |
| Rotação da senha (A0) | **desconhecida** — nenhum registro em documento ou banco (`credencial_rotacionada_em` NULL) | `ARQUITETURA_ACESSO.md:38-46` |
| Ingestão no SEI360 | manual (`python ingestao.py`); último dado 27/08, ingerido 01/09; nenhum watcher/agendamento — por desenho (`ARQUITETURA_ACESSO.md:886`) | `snapshot.arquivo`, `execucao.gatilho='importacao_manual'` |
| Agente pull | código completo dos dois lados; agente 1 (`ESTACAO-COLETA`) **sem dono**, aponta `127.0.0.1:8360`, tarefa `SEI360_Agente` nunca criada, sem contato desde 19/08 | `agente/agente.json`, `app.py:2681-2686`, `agente/sei360_agente.py:407-411` |
| Busca no container | pronta; **parada**: sem `SEI360_CHAVE_MESTRA` no processo, 0 credenciais; única busca (id 1, 21/08) `falhou` | `_dados/_servidor.log:4`, `SPECS.md:1145-1160` |
| Servidor | Flask de desenvolvimento em `127.0.0.1:8360`; imagem nunca construída | `LEIAME_EASYPANEL.md:172-177` |
| Portão de build | **exit 0 hoje**; `.dockerignore` da raiz sem padrões inertes; `.env.local` barrado | `conferir_contexto.py` |
| FESF | 0 snapshots (48/48 são `SEI-SESAB`); perfil pronto; laço fechado; sem parser 4.0; sem tratamento de DNS no container | §4 |
| Extrator irmão (FESF) | 33 mesas, 1.270 processos, 958 abertos em mais de uma mesa, 28 min, 0 erros (03/09 06:00–06:29); campos preenchidos: número e tipo (atribuição/marcador vazios nessa rodada) | `sei_sistema/sei_extraidos/_multi_mesa_results.json` |
| Contas | 64 (1 admin, 1 gestor, 62 servidor); 3 ativas; 61 sem senha; 3 em `@sei360.local` | banco |
| 2FA / recuperação | prontos, **desligados**; `config_email` e `config_acesso` vazias | banco |
| IA | desligada: sem chave, `aceite_ia` vazia; 1.054 resumos legados 100% sem procedência, expurgo em 60 d | banco; `expurgo.py:50-56` |
| Suíte | 1.118 verificações, 1 falha — `teste_poco.py:359-360`, reprova ~9 dias por ano por calendário: **defeito do teste** | última rodada; `poco.py:117-122` |
| Segredos em disco | `servidor/.env.local` (chave mestra e segredo do app — fora do build); `agente/agente.json:3` (token do agente); `sei_sistema/.claude/sei-credenciais.local.json` (credenciais do irmão, inclusive FESF) | — |

---

## 2. Documentação: o que está escrito e o que não está

### 2.1 Objetivos — existem, e estão desatualizados
- Declaração única: `SPECS.md:11-17` — três perguntas (o que está parado e há quanto tempo; o que
  é ação minha e o que é espera de terceiro; onde o processo está e o que foi combinado). Repetida em
  `PLANO_PRODUTO.md:11` (a terceira pergunta sai truncada). A finalidade juridicamente vinculante
  ("triagem da carteira; proibido reuso para desempenho de servidor") mora em
  `ARQUITETURA_ACESSO.md:786`, fora do documento de produto — e o PLANO §2.5 descreve um ranking
  nominal de 57 pessoas sem citar essa proibição.
- **Não cobre** o que foi construído depois: busca avançada (§5-ter), poço (§5-bis), IA (PLANO §4),
  2FA/recuperação (§5-duodecies), multi-instância FESF (§5-quater).
- `SPECS.md:4-5` ainda diz "Instância de referência: SESAB" e "Última atualização: 12/08" — o
  arquivo tem seções de 21, 25, 26 e 27/08.

### 2.2 Critérios — só técnicos, por fatia
- **Existem** critérios mensuráveis de pronto: `ARQUITETURA_ACESSO.md` §10 ("Pronto quando") e
  `PLANO_PRODUTO.md` §7 ("PRONTO"), mais números operacionais (janela 07:30 + 90 min; gate 90% por
  unidade; 5 falhas/15 min; sessão 12 h; retenções; teto de e-mail 60/20; container 2 GB).
- **Não existe**: meta de resultado (526 parados +90 d, sem alvo); taxa aceitável de coleta (a
  medida é "1 janela perdida em 6" — hoje são 11 dias perdidos); SLO; meta de adoção (P8);
  definição de "pronto do produto"; **nenhum critério menciona a FESF**.

### 2.3 Funcionalidades — status que o próprio documento afirma
- **Prontas:** fronteira por unidade (leitura e escrita), login/lockout/CSRF, cofre, 14 relatórios,
  N1/N2, régua da coleta, ordem das coletas, papéis, portas, limpeza do banco, alertas agrupados,
  semeadura de vínculo + ativação em lote, 2FA/recuperação (desligados), `emergencia.py`, migração
  de instância, poço (52% de leitura evitada).
- **Parciais:** IA (só as travas), busca (4 bloqueios + 18 achados), poço sem dado (ingestão
  pendente), N3 "Saúde do dado" sem status declarado.
- **Não construídas:** motor de 11 regras (`SPECS.md:108-126`, nunca reaparece), API paginada,
  espelho de auditoria, códigos de recuperação, e-mail assíncrono, CI/deploy por digest, coleta no
  container (por decisão), Fatia 9 (conta de serviço), **imagem Docker**, **coleta FESF / parser
  4.0**.

### 2.4 Decisões datadas — registradas e não registradas
Registradas: 18/08 Fase 3, host fora do BR descartado, base legal art. 11 II "b", isolamento A/B,
18 itens YAGNI; 19/08 auditoria ("não dá para subir"), 9 fatias executadas, 12 "não fazer", revisão
de 8 lentes; **21/08** revogação §6.1/§3.7 (busca no container; VPS/EasyPanel HostGator); 25/08
correção do §3.5; **26/08** "modo estação sai do caminho do leigo"; 27/08 medições do Resend.

**Não registradas:** P1 respondida de fato (HostGator = via "(a) VPS BR" — confirmar região);
CONFIG esvaziado e tarefa desabilitada (01/09); a auditoria de 19/08 está fechada — conferido no
código (`destino_interno` em `app.py:195/419`, vínculos como conjunto `app.py:1842-1844`,
ProxyFix `app.py:23/99`), mas nenhum documento diz isso.

### 2.5 Contradições a corrigir (12 + 1)
| # | Onde | O quê |
|---|---|---|
| C1 | `ARQUITETURA_ACESSO.md` §1 (`:12`), §3.1 (`:70-75`), §3.4 (`:107`), §11 (`:881`) vs §6.0 (`:529`), §3.5 (`:136`), §3.6 (`:270`) | "nenhum navegador no container" vs Chromium + Playwright na imagem |
| C2 | `:88` vs `:288` e `LEIAME:24` | 256 MB vs mínimo 2 GB |
| C3 | `LEIAME_EASYPANEL.md:96-100` vs `ARQUITETURA_ACESSO.md:551` | senha "no Credential Manager da estação" vs "cifrada no cofre do servidor" (modo padrão desde 26/08) |
| C4 | **termo A2, item 5** (`ARQUITETURA_ACESSO.md:592`) | afirma que o painel hospedado não possui a senha — falso desde 21/08 — num termo a ser assinado por pessoa física |
| C5 | `:519`, `:97` vs `:163-214` | "sem segundo fator na v1" vs 2FA desenhado e implementado |
| C6 | `SPECS.md:292-300` vs `:619`, `:1085-1143` | "decisão pendente" sobre busca no container vs seções que descrevem a busca já no container |
| C7 | `SPECS.md:23-34` vs `ARQUITETURA_ACESSO.md:551` | "servidor guardando senha do SEI: descartado" vs cofre; reescrita prometida em `ARQ:5` e `:868` nunca feita |
| C8 | `SPECS.md:5` | "12/08" com seções de 21–27/08 |
| C9 | `ARQUITETURA_ACESSO.md:639`, `:433` vs `LEIAME:103-105`, `SPECS.md:724-731` | "uma unidade pertence a um agente" vs coleta compartilhada (`dono_usuario_id=NULL`) |
| C10 | `LEIAME:47-49` vs `ARQ:130` | `SEI360_SECRET_KEY` "nunca lida" vs "também aceita" |
| C11 | termo A1 (e), `ARQ:762` | "não existirá busca por texto livre no painel" sem a distinção SEI × base local (`SPECS.md:137-148`) |
| C12 | `ARQ:697-706` | `DIAS['resumo']=60` (`PLANO:417`) fora da tabela de retenção que sustenta o art. 37 |
| +1 | `LEIAME_EASYPANEL.md:166-171` | diz que o expurgo não roda sozinho; roda, oportunista a cada 20 h, em `app.py:2543-2582` |

### 2.6 Lacunas — o que um gestor precisa e não está escrito
Ninguém tem nome (dono do produto, titular da credencial, encarregado, quem assina A0–A6, quem
recebe alerta); nenhum prazo (`ARQ:873`: "autorizado para produção: indeterminado"); nenhuma
definição de "pronto"; nenhuma medida de sucesso; **escopo institucional da FESF inexistente**
(FESF-SUS é outra pessoa jurídica; A3 designa a SESAB controladora; não há quem autoriza, base legal,
usuários, mesas); operação (quem opera o VPS, backup/restauração nunca testados, RPO/RTO, custo do
VPS/domínio/Resend); instalação de produção (não existe); saída do projeto (P4 nunca pedido).

---

## 3. O que falta para a SESAB

| # | Item | Onde | Dono |
|---|---|---|---|
| S1 | **A0 — rotação da senha da titular** (login mascarado `z****@saude.ba.gov.br`). Status desconhecido. A credencial é de **terceira pessoa**: toda coleta é ato nominal dela; A2 é dela | `ARQ:38`, `:50-56`, `SPECS.md:987-990` | titular |
| S2 | **Semeadura no perfil** — `SEIAuto.credencial(login, senha)` no console do Chromium de `_perfil_sei`, digitado pela titular. A tarefa agendada roda sem stdin: o localStorage é a única fonte (`coletor_sesab.py:246-251`) | `conferir_contexto.py:202-210` | titular |
| S3 | Reabilitar `SEI_SESAB_Coleta` — ou substituí-la pela tarefa do agente (S6). Reabilitar antes de S2 = `exit 3` calado | `ARQ:609` | dono |
| S4 | Ingerir o acervo em ordem (11 arquivos). É o que o poço espera desde 27/08 | `SPECS.md:756-758` | engenharia |
| S5 | Ingestão sem mão: por desenho é o agente (`POST /api/agente/resultado` → `ingerir()`), não um watcher. Enquanto o VPS não existir: um passo de ingestão no `_run_coleta.cmd` após `EXIT≤1`, contra o servidor local | `ARQ:886` | engenharia |
| S6 | Dono no agente 1 (`dono_usuario_id`); `agente.json` apontando para o VPS; `instalar-tarefa` executado; rotina de aposentar o snapshot legado `dono=NULL` quando o nominal chegar (não existe — os dois disputariam "corrente", `ingestao.py:414-429`) | `app.py:2681-2686` | engenharia + dono |
| S7 | Alerta de janela perdida que não dependa de um agente perguntar (`janela_perdida` só dispara em `/api/agente/tarefa`); Fatia 5 não feita; sem e-mail, sem ninguém sabendo — a falha de 01/09 está no log há 6 dias | `app.py:2538`, `ARQ:854-856` | engenharia |
| S8 | P7 — estação pessoal × máquina dedicada. A parada de 11 dias é o argumento; a tarefa exige logon interativo | `ARQ:921-922` | dono |
| S9 | `SEI360_CHAVE_MESTRA` no ambiente do processo (hoje só em `.env.local`) e **decisão de onde mora** antes da primeira credencial — trocá-la depois torna tudo indecifrável | `cofre.py:160-167`, `ARQ §3.5` | dono |
| S10 | Recorte por `instancia` nas cláusulas de "corrente" e de queda da ingestão (hoje a chave efetiva é `(unidade, dono)`) — inofensivo só enquanto há uma instância | `ingestao.py:330-333`, `:414-429` vs `banco.py:279-283` | engenharia |

---

## 4. O que falta para a FESF

| # | Item | Onde |
|---|---|---|
| F1 | Passo 1 da configuração aceitar instância com **busca** (não só com coleta) | `configuracao.py:51`, `templates/configuracao.html:113-118`, `app.py:1058-1059` |
| F2 | Validação de login conforme o perfil (`nome.sobrenome`, sem `@`) | `app.py:1070-1071` vs `perfil_sei.py:128` |
| F3 | Vínculo de unidade **sem snapshot prévio**: texto livre do admin (já existe para agentes) ou "Testar acesso" descobrindo mesas no 4.0 (`descobrirMesas` — a validar) | `app.py:1809-1811`, `semear.py:107`, `coleta.py:180-184` |
| F4 | `instancia` na ingestão da coleta: `automacao_sei.js` emitir `instancia` do envelope (hoje zero ocorrências); `app.py:3104` passar `instancia=`; `ingestao.py:233-235` deixar de cair em `SEI-SESAB` | — |
| F5 | Painel: `unidades_do` (`app.py:210-216`) e `snapshots_de` (`app.py:786-789`, dicionário chaveado só pelo nome — colide entre instâncias) por `(instancia, unidade)`; rótulo/filtro de instância em `painel.html` (zero ocorrências); `medidos` renderizado em `busca.html` | — |
| F6 | **Parser 4.0** no `automacao_sei.js`, dirigido por `perfil`: listagem (resumida/detalhada), histórico, `descobrirMesas`, login sem `#selOrgao` (já tratado em `coletor_sesab.py:305-317`). Superfície hoje: `hdnTipoVisualizacao` ×2, `procedimento_consultar_historico` ×1, `infra_trocar_unidade` ×1, `lnkInfraUnidade` ×4. Mapa medido pelo irmão no 4.0: `tr[id^="P"]`, `a.processoVisualizado / .processoNaoVisualizado`, célula de atribuição, `img[src*="marcador"]`, `trD*` (linha de detalhe), `infra_trocar_unidade` + `selecionarUnidade(id)`, ativação da visão detalhada por ícone/texto (`trocarVisualizacao` não é global no 4.0) | `sei_sistema/sei_extractor.py:635-704`, `:2765-2870`, `:3500-3560` |
| F7 | **Validação em campo**, somente leitura, com a credencial do próprio dono da FESF. Oráculo: `_multi_mesa_results.json` — 33 mesas; HECC 850, GC 794, GAF 407, GAF/CAF 231, GAF/ALMOX 201, DG 185, DM 183, GAF/RH 145, ASTEC 66, GO/HIG 32, GO 29, GAF/ADM 20; 958 compartilhados. Contagem por mesa tem de bater | — |
| F8 | `perfil_sei.py:134` → `disponivel_coleta: True` para a FESF **só depois** de F6 + F7 | — |
| F9 | DNS: a estação já tem pin em `hosts` (`200.187.36.63`); o container não tem nada — `--add-host` no EasyPanel ou `--host-resolver-rules` por instância em `ARGS_NAVEGADOR` (`coletor_sesab.py:144-147`) | — |
| F10 | Escopo institucional: titular FESF (o próprio dono — HECC), mesas (33 sob `FESF/DIGAS/HECC`), controladora/base legal para dados FESF (A3-bis), A1/A2 para a FESF, 2FA "possível" na FESF — medir | `SPECS.md:302-305` |
| F11 | Testes: fixture 4.0 **real** (hoje derivado do 5.0.4 por `String.replace`, `painel_sesab/_teste_pesquisa.js:124-128`); caso de vínculo nas **duas** instâncias em `teste_multiusuario.py` | — |
| F12 | Só confirmável contra o SEI real: `sip.fesfsus` alcançável de dentro do container; login sem `selOrgao`; ids da Pesquisa (`busca_ids_medidos: True` apoia-se no irmão); `#lnkInfraUnidade` / `#lnkUsuarioSistema` no 4.0; colisão real de `id_sei` (nunca observada) | — |

---

## 5. O melhor caminho — decisões de engenharia

### 5.1 FESF: parser 4.0 **no mesmo coletor**, com o irmão como oráculo — não um segundo coletor
Alternativas avaliadas:
- **(A) portar `automacao_sei.js` ao 4.0, dirigido por `perfil`** — **escolhida**.
- (B) adaptador sobre `sei_extractor.py` emitindo o envelope que `ingestao.py` lê.
- (C) usar a busca (tela Pesquisa) como coleta.

Por que (A): um pipeline só (coleta → JSON → ingestão → poço → painel) com o rigor que já existe
(checkpoint, conserto de histórico truncado, gate por unidade, canário, `medido_em`). O irmão dorme
3 s por página (28 min só na listagem — `SPECS.md:280-284`) e lê processo a processo (horas para
1.270); usá-lo como motor acoplaria dois projetos e manteria duas credenciais em texto puro
(`.claude/sei-credenciais.local.json`). (C) não vira snapshot por decisão (`busca.py:11-19`). O irmão
entra como **mapa de seletores e oráculo de contagem**, e a rodada de campo é em modo leitura.

Onde roda: na estação do titular FESF (o dono), pelo agente — a coleta continua fora do container
por desenho (a revogação de 21/08 alcança só a busca, `ARQ:538-543`).

### 5.2 SESAB: estação de volta hoje → agente pull com dono → VPS
Não há caminho novo a construir. Os quatro elos que faltam são operação: credencial existente
(S1/S2), agendador disparando (S3/S6), dono no agente (S6), servidor num endereço alcançável (F1 do
§6). Tudo o mais está escrito e testado onde dava para testar.

### 5.3 Ingestão automática = agente, não watcher
Coerente com `ARQ §7.1` ("o agente sempre puxa"). Enquanto o VPS não existir, um passo de ingestão
no `_run_coleta.cmd` cobre o intervalo sem inventar componente.

### 5.4 Busca no container: ligar só com credenciais e três correções
Troca de mesa (`pesquisa_sei.js:268` só lê), `usuario_confirmado` (zero ocorrências), relógio da
fila (`busca.varrer` só roda em três rotas HTTP; a busca id 1 viveu 926 s sob teto de 90 s).

### 5.5 Deploy: provar a imagem antes de qualquer promessa
Docker via WSL na estação (`sei360/instalar_docker_wsl.ps1` existe, nunca executado) ou build no
próprio EasyPanel olhando o log; `teste_container.py` (30+ verificações) é a prova.

---

## 6. Fases — ordem, critério de pronto, esforço, dono

### F0 — SESAB de pé hoje · 0,5 dia · titular + engenharia
1. Confirmar A0 (S1). 2. Semear no perfil (S2). 3. Reabilitar a tarefa (S3). 4. Uma coleta manual com o
SEI no ar (01/09 foi timeout do SEI, `exit 4`, duas vezes). 5. Ingerir o acervo (S4). 6. Ingestão no
wrapper (S5).
**PRONTO:** log com `EXIT=0` e 12/12 mesas; 12 snapshots correntes com data de hoje; poço com blocos
servidos > 0 na coleta seguinte; painel verde; `conferir_contexto.py` continua saindo 0.

### F1 — Imagem provada e no ar · 1–2 dias + provisionamento do VPS pelo dono
Docker (WSL) ou build no EasyPanel; `teste_container.py` verde; `--empacotar`; subir conforme o guia
publicado ("SEI360 no EasyPanel"); volume nomeado `/dados`; `TZ`, `SEI360_CHAVE_MESTRA` (S9),
`SEI360_FORCAR_HTTPS=1`, `SEI360_SEGREDO`; `semear.py --so-contas`; restrição de origem (P9)
enquanto o 2FA estiver desligado.
**Requer:** A6/P1 confirmada (região BR da HostGator), A5 (lista nominal + MFA). A3/A4 antes de expor.
**PRONTO:** `/saude` 200 com volume vazio; login real pelo gunicorn; dado sobrevive a recriar o
container; `HEALTHCHECK` chega a `healthy`.

### F2 — SESAB automática no VPS · 1–2 dias
Dono no agente 1; `agente.json` → VPS; `instalar-tarefa` executado; **A2 assinado e registrado**
(`credencial_aceite_em`); rotina de aposentar snapshot `dono=NULL`; alerta de janela perdida por
e-mail (S7, depende do Resend de F6 — ou log + `/saude` até lá); P2 (19:00) e P7 decididos.
**PRONTO:** 3 dias úteis seguidos com snapshots `gatilho='agente'` e zero passo manual; janela
perdida vira alerta em ≤ 90 min.

### F3 — FESF destravada no produto · 2–3 dias
F1–F5 do §4, S10, F9, F11 (parte de produto).
**PRONTO:** pessoa com vínculo só na FESF configura sistema + login + mesas sem snapshot prévio;
ingestão sintética `instancia='SEI-FESF'` não expira snapshot SESAB de mesma sigla; painel rotula a
instância; teste de vínculo duplo passa.

### F4 — FESF coletando · 3–5 dias · exige sessão de campo com a credencial do dono
F6 → F7 → F8. Ordem interna: `descobrirMesas` 4.0 → listagem → histórico → multi-mesa → gate por
unidade. Comparar com o oráculo mesa a mesa; só então `disponivel_coleta: True`.
**PRONTO:** coleta FESF completa (33 mesas, contagens batendo com o irmão ±2%); snapshots correntes
`SEI-FESF`; painel com as duas carteiras para o dono, separadas; suíte com fixture real do 4.0;
dedup por `(id_sei, instancia)` provada com colisão sintética.

### F5 — Busca operacional nas duas instâncias · 3–4 dias
Chave mestra no processo (S9); credenciais cadastradas em `/configuracao`; troca de mesa;
`usuario_confirmado`; relógio da fila; `/api/agente/busca` pela instância da **busca** (não da
config); validação em campo (ids da SESAB estão `busca_ids_medidos: False`, `perfil_sei.py:111`);
`--add-host` FESF no container (F9).
**PRONTO:** busca em mesa diferente da ativa termina `completa`; identidade divergente é detectada e
registrada; busca abandonada morre em ≤ 90 s sem ninguém abrir a tela.

### F6 — Acesso e exposição · 1–2 dias + propagação DNS (até 72 h)
Domínio próprio verificado no Resend; e-mails reais nas 3 contas `@sei360.local` (decisão já tomada,
faltam os endereços); `SEI360_BASE_URL`; teste que **chegou**; armar 2FA para admin + gestor;
corrigir: coluna lateral some abaixo de 900 px (`estatico/sei360.css:91` — esconde o aviso "alguém
digitou a sua senha corretamente" justamente no celular), `autocomplete="username"` em
`recuperar.html:39-53`, revalidar `entregavel` ao criar/ativar/promover conta com 2FA armado
(`acesso.py:114-130` só vale ao armar). Só então abrir além da VPN/IP.
**PRONTO:** código chega no celular com o aviso visível; conta nova com e-mail inentregável é recusada
com o 2FA armado; `emergencia.py estado` sai limpo.

### F7 — Documentação · 1–2 dias · em paralelo desde F0
Objetivo reescrito (busca, poço, 2FA, FESF); **critérios de sucesso do produto** (proposta: ≥ 95%
das janelas úteis cumpridas por instância; dado ≤ 1 dia útil no painel; usuários ativos/semana;
redução dos parados +90 d com baseline 526 e alvo do dono); seção "Escopo FESF"; corrigir C1–C12 e o
LEIAME do expurgo; registrar 01/09 (CONFIG/tarefa), P1 respondida, auditoria de 19/08 fechada;
nomear donos e prazos de A0–A6; procedimento de backup/restauração **testado**; custo.

### F8 — Dívidas · 2–3 dias · quando couber
`teste_poco` com `agora_dt` fixo (`poco.py:322-323` já aceita); HMAC do agente com chave própria
(`seguranca.py:120-126`); expiração da senha provisória; agente respeitando escopo (roda `--mesas`
sempre); "COLETA INCOMPLETA" por execução; menu único (`_nav.html` × `montar_painel._lateral()`);
e-mail assíncrono; códigos de recuperação (decisão); API paginada (quando alguma unidade passar de
~3.000).

### F9 — IA · bloqueada pela DECISÃO 9.1 / P6 · 1–2 dias se "sim"
Chave no cofre, aceite por unidade, rodada pós-ingestão com teto — ou apagar os 1.054 legados (o
expurgo já os apaga em 60 dias, sem nada nascer no lugar).

**Esforço total de engenharia:** 15–24 dias úteis. **Caminho crítico:** A0 → F0 → F1 → F2. FESF
(F3 → F4) corre em paralelo a partir de F0. F7 desde o primeiro dia.

---

## 7. Decisões que só o dono responde (com recomendação)

| # | Decisão | Recomendação |
|---|---|---|
| D1 | **A0 foi feita?** Se não, fazer antes de F0 | rotacionar hoje |
| D2 | Quem semeia a credencial SESAB no perfil | a titular, na estação dela, no console — nunca por chat, arquivo ou terceiro |
| D3 | P7 — estação pessoal × máquina dedicada | dedicada; 11 dias parados |
| D4 | A6/P1 — região do VPS HostGator; registrar 21/08 como resposta à P1 | confirmar BR; registrar |
| D5 | A1–A5 — nomes, datas; A2 pela titular SESAB, A2-bis pelo dono para a FESF | fechar A1/A2 primeiro |
| D6 | FESF — mesas no escopo, controladora/base legal (FESF-SUS), quem mais acessa | começar pelo dono, 33 mesas do HECC |
| D7 | Onde mora `SEI360_CHAVE_MESTRA` | env do serviço, cópia fora do host; nunca no painel do EasyPanel |
| D8 | P2 — segunda janela | 19:00, dias úteis |
| D9 | P8 — contas | abrir aos 62 com ativação pelo admin |
| D10 | P9 — exposição | VPN/IP até o 2FA armado |
| D11 | 9.1 / P6 — IA | ligar "estruturado" com aceite por unidade, ou apagar os legados |
| D12 | 9.3 convite × semeadura; 9.5 retenção; P10 | convite; 30 d texto, agregado mais longo |
| D13 | P4 — pedir conta de serviço à PRODEB/TIC | pedir; é a única saída da imputação nominal |
| D14 | E-mails reais para `admin/gestor/servidor@sei360.local` | fornecer os três endereços |

---

## 8. Riscos e "não fazer"

- **Não** reabilitar a tarefa antes de semear: `exit 3` calado, todo dia.
- **Não** ligar a FESF na tela antes do parser: carteira vazia com cara de vazia de verdade.
- **Não** zipar pelo Explorer: só `conferir_contexto.py --empacotar`.
- **Não** ligar a IA antes de 9.1 e das travas por unidade.
- **Não** pôr a chave mestra no painel do EasyPanel; **não** trocá-la depois de guardar credenciais.
- **Não** usar o extrator irmão como motor de coleta do SEI360.
- **Não** automatizar 2FA ou captcha; **não** repetir senha em argv/ambiente — stdin só.
- **Não** reproduzir a senha antiga em lugar nenhum; considerá-la vazada.
- Risco: SEI fora do ar (01/09: `Page.goto` 60 s ×2) — o semáforo já mostra; o alerta (S7) é o que falta.
- Risco: a credencial SESAB é de terceira pessoa — cada coleta é ato nominal dela (A2).
- Risco: `id_sei` pode colidir entre instalações — a chave protege; a leitura precisa do recorte (S10).

---

## 9. Ordem de execução (checklist)

1. D1, D2, D7 respondidas → **F0** (hoje).
2. **F7** começa em paralelo (objetivo, critérios, escopo FESF, contradições).
3. D4, D5 → **F1** → **F2**.
4. **F3** → D6 → **F4** (campo).
5. **F5** → D14 → **F6**.
6. **F8**; **F9** quando D11.

---

## 10. Execução — 07/09/2026 (noite)

Três agentes em paralelo (servidor multi-instância, parser SEI 4.0, documentação) e integração.
**Suíte: 1.176 verificações, 0 falha** (era 1.118 com 1 falha). Banco de trabalho intacto (lacre SHA-256).

Acréscimos da integração final (noite):
- **`coleta.py coletar <usuario_id> <instancia> [--somente A,B] [--amostra SIGLA]`** — a coleta pela
  estação que também é o servidor: a credencial sai do **cofre** por stdin (não mais do localStorage
  do perfil nem do CONFIG), com o perfil da instalação; recusa instalação com `disponivel_coleta:
  False` citando o motivo do perfil (a `--amostra` passa, porque é a prova); registra em
  `log_acesso` (`coleta_estacao`). 11 verificações de guarda-corpo em `teste_configuracao.py`
  (duble de `_rodar`; a senha nunca vai em argv). No VPS este comando não roda — lá o executor
  continua sendo o agente.
- **`_run_coleta.cmd`** chama `coleta.py coletar 2 SEI-SESAB` e `coleta.py coletar 2 SEI-FESF`
  (a FESF recusada com motivo até virar o perfil), regenera o painel estático da SESAB e ingere
  `sei_sesab_<dia>.json` / `sei_fesf_<dia>.json`. Consequência: a semeadura no perfil do navegador
  (`SEIAuto.credencial`) deixa de ser necessária — a pessoa digita a senha uma vez, no passo
  "acesso" de `/configuracao`.
- `--somente A,B` no coletor e `opts.somente` no `.js` (sigla que a conta não tem é erro nomeado).
- Fumaça na FESF pelo perfil (sem credencial): abriu `sip.fesfsus` (DNS ok na estação), aplicou o
  perfil 4.0, parou antes de logar (`exit 3`). A tela de login da FESF tem `#selOrgao` oculto com o
  órgão único — o perfil `campo_orgao: None` continua certo; o aviso do coletor é ruído. O link
  "Autenticação em dois fatores" existe e é opcional.

| Feito | Onde |
|---|---|
| F3 inteira: passo 1 aceita instância com busca; login pelo perfil (`login_valido`); vínculo sem snapshot (`unidade_livre`, log `vincular_sem_snapshot`); `instancia` na ingestão com alerta quando cai no padrão; recorte por instância nas cláusulas de corrente/queda; painel e busca por `(instancia, unidade)` com rótulo; tarefa de coleta leva `instancia`+`perfil`; ingestão idempotente por `sha256`; padrões `"SEI-SESAB"` derivados | `perfil_sei.py`, `configuracao.py`, `app.py`, `ingestao.py`, `coleta.py`, `montar_painel.py`, `agente/sei360_agente.py` |
| Guarda-corpo novo: `/api/agente/tarefa` recusa coleta em instalação com `disponivel_coleta: False`, citando o motivo do perfil | `app.py:2691-2712` |
| Achado corrigido: `config_usuario.ler()` desempatava no mesmo segundo por ordem alfabética — a pessoa "trocava" para a SESAB e o passo 2 validava contra a FESF | `configuracao.py:31-49` |
| F6: parser 4.0 no `automacao_sei.js` (uma tabela de seletores por família, `linha4()`/`linha5()`, visão detalhada por ícone com log da visão lida, `descobrirMesas` com paginação, `instancia` em cada linha exportada); `coletor_sesab.py` com perfil por `window.__SEI_PERFIL`, login sem órgão, `--testar`, `--instancia SEI-XXXX` (envelope do servidor local), `--amostra SIGLA` (listagem de uma mesa, sem gravar), export `sei_<instalação>_<dia>.json` | `painel_sesab/automacao_sei.js`, `painel_sesab/coletor_sesab.py`, `_teste_parser40.js` (40 verificações, fixture **sintética** — não há captura real do 4.0 em disco) |
| "Testar acesso" passa o perfil da instalação ao coletor (antes batia na URL da SESAB com credencial FESF) | `coleta.py:199-216` |
| Wrapper da estação ingere `sei_*_<dia>.json` no SEI360 após coleta boa (`_gravar_cmd.py` → `_run_coleta.cmd`) | `painel_sesab/_run_coleta.cmd:27-42` |
| Agente 1 ganhou dono (usuário 2) — backup `sei360.db.antes-dono-agente-2026-09-07` | banco |
| Servidor local reiniciado com `SEI360_CHAVE_MESTRA` no ambiente: cofre ligado, atendente ligado (2 vagas) | `_dados/_servidor.log` |
| F7: 12 contradições corrigidas, escopo FESF (§5-quinquies-bis), incidente de 01/09 (§5-quaterdecies), critérios de sucesso propostos, P1 respondida, donos/prazos `[a nomear]` | `SPECS.md`, `ARQUITETURA_ACESSO.md`, `PLANO_PRODUTO.md`, `LEIAME_EASYPANEL.md` |
| `teste_relatorios.py` deixou de depender de a base ter "linha sem detalhe": cria o caso na cópia isolada | `teste_relatorios.py:1508-1525` |

**Decisões tomadas na integração (a confirmar pelo dono):** (1) na ingestão, se coletor e configuração discordarem da instalação, vence a **declaração do coletor** e fica alerta; (2) `--forcar` também fura a trava de `sha256`; (3) a coleta FESF pelo agente fica **recusada com motivo** até `disponivel_coleta: True`; (4) agente 1 → dono = usuário 2 (`gestor`), a conta em que a configuração SESAB da titular está gravada; (5) o caminho diário da SESAB continua o wrapper `SEI_SESAB_Coleta` (agora com ingestão automática) — o agente pull fica para quando o servidor for remoto.

**Não feito, porque só o dono pode:** rotação da senha SESAB (A0) e semeadura no perfil; credencial FESF no cofre (`/configuracao`); validação em campo do parser 4.0 (F7) e a virada de `disponivel_coleta`; reabilitar a tarefa; VPS/EasyPanel (sem Docker na estação; sem VPS provisionado).

**Próximo passo, na ordem:** (a) dono guarda a credencial FESF em `/configuracao` (sistema FESF → acesso → **Testar acesso**: prova login sem órgão e conta as mesas — esperado 33); (b) `python amostra_fesf.py 2 FESF/DIGAS/HECC/GAF/ADM` (mesa de 20 processos, ~1 min) e comparação com o oráculo; (c) `perfil_sei.py:134` → `True`; (d) coleta FESF pequena (2 mesas) e painel; (e) titular semeia a credencial SESAB no perfil → `coletor_sesab.py --testar` → reabilitar `SEI_SESAB_Coleta`.
