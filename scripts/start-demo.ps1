param(
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $projectRoot "tmp"
$startupLog = Join-Path $logDirectory "startup-demo.log"
$uvicornOut = Join-Path $logDirectory "uvicorn.stdout.log"
$uvicornErr = Join-Path $logDirectory "uvicorn.stderr.log"
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$healthUrl = "http://127.0.0.1:8000/health"
$appUrl = "http://127.0.0.1:8000/"

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

function Write-StartupLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $startupLog -Value "[$timestamp] $Message"
}

function Test-DemoHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

try {
    Write-StartupLog "Iniciando servicios de Facturacion IA."

    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "No se encontro el entorno Python en $pythonExe"
    }

    if (-not (Test-DemoHealth)) {
        if (-not (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue)) {
            if (-not (Test-Path -LiteralPath $dockerDesktop)) {
                throw "No se encontro Docker Desktop."
            }
            Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
            Write-StartupLog "Docker Desktop iniciado."
        }

        $dockerReady = $false
        for ($attempt = 1; $attempt -le 40; $attempt++) {
            & cmd.exe /d /c "docker info >nul 2>&1"
            if ($LASTEXITCODE -eq 0) {
                $dockerReady = $true
                break
            }
            Start-Sleep -Seconds 3
        }
        if (-not $dockerReady) {
            throw "Docker no estuvo disponible despues de 120 segundos."
        }

        Push-Location $projectRoot
        try {
            & cmd.exe /d /c "docker compose up -d >> tmp\startup-docker.log 2>&1"
            if ($LASTEXITCODE -ne 0) {
                throw "No fue posible iniciar PostgreSQL con Docker Compose."
            }
        }
        finally {
            Pop-Location
        }
        Write-StartupLog "PostgreSQL disponible."

        $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
        if (-not $listener) {
            Start-Process `
                -FilePath $pythonExe `
                -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
                -WorkingDirectory $projectRoot `
                -WindowStyle Hidden `
                -RedirectStandardOutput $uvicornOut `
                -RedirectStandardError $uvicornErr
            Write-StartupLog "FastAPI iniciado."
        }

        $healthy = $false
        for ($attempt = 1; $attempt -le 30; $attempt++) {
            if (Test-DemoHealth) {
                $healthy = $true
                break
            }
            Start-Sleep -Seconds 2
        }
        if (-not $healthy) {
            throw "FastAPI no respondio correctamente despues de 60 segundos."
        }
    }

    Write-StartupLog "Demo disponible en $appUrl"
    if ($OpenBrowser) {
        Start-Process $appUrl
    }
}
catch {
    Write-StartupLog "ERROR: $($_.Exception.Message)"
    exit 1
}
