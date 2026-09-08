@echo off
REM ============================================================================
REM Coleta agendada do SEI (SESAB), TODAS as mesas da conta, e regeracao do painel.
REM PYTHONUNBUFFERED nao e enfeite: sem ele o log sai vazio quando o Task
REM Scheduler encerra o processo - tropeco ja registrado nas automacoes AGHUse.
REM Este arquivo e gerado por _gravar_cmd.py (CRLF obrigatorio para o cmd.exe).
REM ============================================================================
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set DIR=C:\Claude\sei_sistema\painel_sesab
set PY=C:\Users\Lucaskaram\AppData\Local\Programs\Python\Python312\python.exe

if not exist "%DIR%\_logs" mkdir "%DIR%\_logs"
set LOG=%DIR%\_logs\coleta_%date:~6,4%%date:~3,2%%date:~0,2%.log

echo ============================================ >> "%LOG%"
echo INICIO %date% %time% >> "%LOG%"
REM Desde 07/09/2026 a credencial sai do COFRE do SEI360 (AES-256-GCM, chave em
REM .env.local), por stdin, e nao mais do localStorage do perfil nem do CONFIG.
REM Uma chamada por instalacao; a FESF e recusada com motivo enquanto o perfil
REM disser disponivel_coleta=False. Usuario 2 = gestor (dono das duas config).
set SEI360=C:\Claude\sei_sistema\sei360\servidor
"%PY%" "%SEI360%\coleta.py" coletar 2 SEI-SESAB >> "%LOG%" 2>&1
set CODIGO=%ERRORLEVEL%
"%PY%" "%SEI360%\coleta.py" coletar 2 SEI-FESF >> "%LOG%" 2>&1
set CODIGO_FESF=%ERRORLEVEL%

REM 0=ok  1=coletou com alerta  2=sem dados  3=login falhou  4=infraestrutura
REM O painel so e regerado se a coleta gravou dados. Regerar apos falha
REM reimprimiria a coleta ANTERIOR com data de hoje - painel velho com cara de novo.
REM O gerador AVISA no log quantos processos ficaram sem resumo de IA. Ele nao
REM gera resumo sozinho: isso exige uma rodada de agentes, fora do alcance do
REM agendador. Sem o aviso, processo novo ficaria sem resumo indefinidamente.
REM A ingestao no SEI360 entra AQUI, e nao a mao: de 12/08 a 27/08, 11 das 14
REM coletas gravadas em _coletas nunca chegaram ao banco - ninguem lembrou de
REM rodar ingestao.py. A ingestao e idempotente por sha256 (arquivo ja
REM ingerido e recusado sem efeito), entao repetir e seguro. O arquivo e o de
REM HOJE, nomeado pelo coletor; se a coleta virou o dia, o proximo disparo pega.
set SEI360=C:\Claude\sei_sistema\sei360\servidor
set HOJE=%date:~6,4%-%date:~3,2%-%date:~0,2%
if %CODIGO% LEQ 1 (
  "%PY%" "%DIR%\gerar_painel.py" >> "%LOG%" 2>&1
  REM sei_<instalacao>_<dia>.json: sesab, fesf... - cada um e ingerido uma vez.
  REM (sem variavel de controle: dentro de parenteses o cmd expande %VAR% na
  REM  leitura do bloco, e a checagem sairia sempre falsa)
  for %%F in ("%DIR%\_coletas\sei_sesab_%HOJE%.json") do (
    "%PY%" "%SEI360%\ingestao.py" "%%F" >> "%LOG%" 2>&1
  )
  if not exist "%DIR%\_coletas\sei_sesab_%HOJE%.json" echo AVISO: nenhum sei_sesab_%HOJE%.json para ingerir no SEI360. >> "%LOG%"
) else (
  echo ATENCAO: coleta SESAB NAO gravou dados; painel mantido como estava. >> "%LOG%"
  echo Ver "%LOG%" e _coletas\falha_*.png >> "%LOG%"
)
REM A FESF nao tem painel estatico (gerar_painel.py e da SESAB): so ingestao.
if %CODIGO_FESF% LEQ 1 (
  for %%F in ("%DIR%\_coletas\sei_fesf_%HOJE%.json") do (
    "%PY%" "%SEI360%\ingestao.py" "%%F" >> "%LOG%" 2>&1
  )
) else (
  echo AVISO: coleta FESF nao gravou dados (exit %CODIGO_FESF%). >> "%LOG%"
)

echo FIM %date% %time%  EXIT=%CODIGO% >> "%LOG%"
exit /b %CODIGO%
