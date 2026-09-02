# -*- coding: utf-8 -*-
"""Grava _run_coleta.cmd com CRLF e ASCII puro.

O cmd.exe engasga com arquivo terminado em LF (ja aconteceu aqui: as linhas REM
viraram erro). Editor de texto generico nao garante isso — este script garante.
"""
from pathlib import Path

LINHAS = [
    "@echo off",
    "REM ============================================================================",
    "REM Coleta agendada do SEI (SESAB), TODAS as mesas da conta, e regeracao do painel.",
    "REM PYTHONUNBUFFERED nao e enfeite: sem ele o log sai vazio quando o Task",
    "REM Scheduler encerra o processo - tropeco ja registrado nas automacoes AGHUse.",
    "REM Este arquivo e gerado por _gravar_cmd.py (CRLF obrigatorio para o cmd.exe).",
    "REM ============================================================================",
    "set PYTHONUNBUFFERED=1",
    "set PYTHONIOENCODING=utf-8",
    "set DIR=C:\\Claude\\sei_sistema\\painel_sesab",
    "set PY=C:\\Users\\Lucaskaram\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
    "",
    "if not exist \"%DIR%\\_logs\" mkdir \"%DIR%\\_logs\"",
    "set LOG=%DIR%\\_logs\\coleta_%date:~6,4%%date:~3,2%%date:~0,2%.log",
    "",
    "echo ============================================ >> \"%LOG%\"",
    "echo INICIO %date% %time% >> \"%LOG%\"",
    "\"%PY%\" \"%DIR%\\coletor_sesab.py\" --mesas %* >> \"%LOG%\" 2>&1",
    "set CODIGO=%ERRORLEVEL%",
    "",
    "REM 0=ok  1=coletou com alerta  2=sem dados  3=login falhou  4=infraestrutura",
    "REM O painel so e regerado se a coleta gravou dados. Regerar apos falha",
    "REM reimprimiria a coleta ANTERIOR com data de hoje - painel velho com cara de novo.",
    "REM O gerador AVISA no log quantos processos ficaram sem resumo de IA. Ele nao",
    "REM gera resumo sozinho: isso exige uma rodada de agentes, fora do alcance do",
    "REM agendador. Sem o aviso, processo novo ficaria sem resumo indefinidamente.",
    "if %CODIGO% LEQ 1 (",
    "  \"%PY%\" \"%DIR%\\gerar_painel.py\" >> \"%LOG%\" 2>&1",
    ") else (",
    "  echo ATENCAO: coleta NAO gravou dados; painel mantido como estava. >> \"%LOG%\"",
    "  echo Ver \"%LOG%\" e _coletas\\falha_*.png >> \"%LOG%\"",
    ")",
    "",
    "echo FIM %date% %time%  EXIT=%CODIGO% >> \"%LOG%\"",
    "exit /b %CODIGO%",
]

alvo = Path(__file__).resolve().parent / "_run_coleta.cmd"
texto = "\r\n".join(LINHAS) + "\r\n"
alvo.write_bytes(texto.encode("ascii"))
print(f"{alvo.name}: {len(LINHAS)} linhas, CRLF, ASCII — ok")
