# =============================================================================
# Docker nesta estação, para construir e testar a imagem do SEI360.
#
# POR QUE WSL + DOCKER ENGINE, E NÃO DOCKER DESKTOP
# -------------------------------------------------
# Docker Desktop exige assinatura paga para órgão público e empresa grande; o
# Docker Engine (Apache-2.0) não exige nada. E Engine dentro do WSL se dirige
# inteiro por linha de comando — não depende de abrir uma janela e aceitar termo.
#
# ETAPA 1 (já feita, exigiu elevação e REINÍCIO):
#   dism /online /enable-feature Microsoft-Windows-Subsystem-Linux
#   dism /online /enable-feature VirtualMachinePlatform
#
# ETAPA 2 é este arquivo. Rode DEPOIS de reiniciar:
#   powershell -ExecutionPolicy Bypass -File C:\Claude\sei_sistema\sei360\instalar_docker_wsl.ps1
#
# É idempotente: rodar de novo não estraga nada.
# =============================================================================
$ErrorActionPreference = "Continue"
$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
$DISTRO = "Ubuntu-24.04"

function Passo($n, $t) { Write-Host "`n[$n] $t" -ForegroundColor Cyan }

Passo 1 "conferindo se o WSL está ativo"
$null = & wsl.exe --status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WSL ainda não responde. A máquina foi reiniciada depois de habilitar os recursos?" -ForegroundColor Yellow
    Write-Host "  Se não: reinicie e rode este arquivo de novo." -ForegroundColor Yellow
    exit 1
}
Write-Host "  ok"

Passo 2 "atualizando o núcleo do WSL"
& wsl.exe --update 2>&1 | ForEach-Object { "  $_" }

Passo 3 "instalando a distribuição $DISTRO (sem abrir janela)"
$existe = (& wsl.exe --list --quiet 2>&1) -replace "`0","" | Where-Object { $_ -match [regex]::Escape($DISTRO) }
if ($existe) {
    Write-Host "  $DISTRO já existe"
} else {
    & wsl.exe --install -d $DISTRO --no-launch 2>&1 | ForEach-Object { "  $_" }
    # `--root` evita a criação interativa de usuário, que travaria um script.
    $lanc = Get-Command "ubuntu2404.exe" -ErrorAction SilentlyContinue
    if ($lanc) { & $lanc.Source install --root 2>&1 | ForEach-Object { "  $_" } }
}

Passo 4 "instalando o Docker Engine dentro do $DISTRO"
$roteiro = @'
set -e
export DEBIAN_FRONTEND=noninteractive
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq docker.io >/dev/null
fi
# systemd no WSL: sem ele o serviço do docker não sobe sozinho a cada abertura.
if ! grep -q "systemd=true" /etc/wsl.conf 2>/dev/null; then
  printf "[boot]\nsystemd=true\n" >> /etc/wsl.conf
  echo "SYSTEMD_LIGADO"
fi
docker --version
'@
$roteiro = $roteiro -replace "`r`n", "`n"
$tmp = "$env:TEMP\sei360_docker_setup.sh"
[IO.File]::WriteAllText($tmp, $roteiro, (New-Object Text.UTF8Encoding $false))
# `wslpath` faz a conversão de caminho. Montar "/mnt/c/..." na mão com regex já
# é fonte de bug conhecida: barra invertida, letra maiúscula do drive e espaço no
# caminho quebram cada um de um jeito.
$tmpWsl = (& wsl.exe -d $DISTRO -u root -- wslpath -u "$tmp") -replace "`0","" | Select-Object -First 1
& wsl.exe -d $DISTRO -u root -- bash -c "bash '$tmpWsl'" 2>&1 | ForEach-Object { "  $_" }

Passo 5 "reiniciando a distribuição para o systemd valer"
& wsl.exe --terminate $DISTRO 2>&1 | Out-Null
Start-Sleep -Seconds 3
& wsl.exe -d $DISTRO -u root -- bash -lc "systemctl enable --now docker 2>/dev/null || (dockerd > /var/log/dockerd.log 2>&1 &); sleep 4; docker version --format '{{.Server.Version}}'" 2>&1 |
    ForEach-Object { "  $_" }

Passo 6 "atalho docker.cmd no PATH do Windows"
$bin = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
$atalho = Join-Path $bin "docker.cmd"
# Repassa qualquer comando docker para dentro do WSL. Assim os scripts de teste
# rodam do Windows sem saber que o daemon mora do outro lado.
$conteudo = "@echo off`r`nwsl.exe -d $DISTRO -u root -- docker %*`r`n"
[IO.File]::WriteAllText($atalho, $conteudo)
Write-Host "  criado: $atalho"

Passo 7 "conferindo"
& docker version --format "{{.Server.Version}}" 2>&1 | ForEach-Object { "  engine: $_" }

Write-Host "`nPronto. Agora:" -ForegroundColor Green
Write-Host "  cd C:\Claude\sei_sistema\sei360\servidor"
Write-Host "  python teste_container.py"
