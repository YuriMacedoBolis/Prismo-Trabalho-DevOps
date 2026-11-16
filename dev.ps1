<#
.SYNOPSIS
    Prismo - atalhos de desenvolvimento para PowerShell.
    Equivalente ao Makefile, para quem nao tem `make` no Windows.

.EXAMPLE
    ./dev.ps1 setup
    ./dev.ps1 up
    ./dev.ps1 obs
    ./dev.ps1 logs gateway
    ./dev.ps1 down
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'setup', 'up', 'obs', 'down', 'build', 'logs', 'ps', 'restart', 'smoke', 'clean', 'nuke')]
    [string]$Alvo = 'help',

    [Parameter(Position = 1)]
    [string]$Servico = ''
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$compose = @('compose')
$composeObs = @('compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.obs.yml')

function Invoke-Compose {
    param([string[]]$Base, [string[]]$Args)
    & docker ($Base + $Args)
    if ($LASTEXITCODE -ne 0) { throw "docker compose falhou com codigo $LASTEXITCODE" }
}

switch ($Alvo) {
    'help' {
        Write-Host ""
        Write-Host "  Prismo - alvos disponiveis" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "    setup      Cria o .env a partir do modelo"
        Write-Host "    up         Sobe a aplicacao (redis + gateway + web)"
        Write-Host "    obs        Sobe tambem Prometheus e Grafana"
        Write-Host "    down       Para tudo, preservando os volumes"
        Write-Host "    build      Reconstroi as imagens sem cache"
        Write-Host "    logs [svc] Acompanha os logs"
        Write-Host "    ps         Estado dos containers"
        Write-Host "    restart svc  Reinicia um servico"
        Write-Host "    smoke      Verifica os endpoints essenciais"
        Write-Host "    clean      Remove containers e redes"
        Write-Host "    nuke       Remove tudo, inclusive os volumes"
        Write-Host ""
    }

    'setup' {
        if (Test-Path '.env') {
            Write-Host "  .env ja existe, mantido como esta." -ForegroundColor Yellow
        }
        else {
            Copy-Item '.env.example' '.env'
            Write-Host "  .env criado. Preencha DATABASE_URL e JWT_SECRET." -ForegroundColor Green
        }
    }

    'up' {
        Invoke-Compose $compose @('up', '--build', '-d')
        Write-Host ""
        Write-Host "  web ............ http://localhost:8000" -ForegroundColor Green
        Write-Host "  status ......... http://localhost:8000/status" -ForegroundColor Green
        Write-Host "  gateway (API) .. http://localhost:8001/docs" -ForegroundColor Green
    }

    'obs' {
        Invoke-Compose $composeObs @('up', '--build', '-d')
        Write-Host ""
        Write-Host "  web ............ http://localhost:8000" -ForegroundColor Green
        Write-Host "  grafana ........ http://localhost:3000  (admin / prismo)" -ForegroundColor Green
        Write-Host "  prometheus ..... http://localhost:9090" -ForegroundColor Green
    }

    'down'    { Invoke-Compose $composeObs @('down') }
    'build'   { Invoke-Compose $compose @('build', '--no-cache') }
    'ps'      { Invoke-Compose $composeObs @('ps') }
    'clean'   { Invoke-Compose $composeObs @('down', '--remove-orphans') }
    'nuke'    { Invoke-Compose $composeObs @('down', '-v', '--remove-orphans') }

    'logs' {
        $args = @('logs', '-f', '--tail=100')
        if ($Servico) { $args += $Servico }
        Invoke-Compose $composeObs $args
    }

    'restart' {
        if (-not $Servico) { throw "Informe o servico: ./dev.ps1 restart web" }
        Invoke-Compose $compose @('restart', $Servico)
    }

    'smoke' {
        & python 'scripts/smoke_test.py'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}
