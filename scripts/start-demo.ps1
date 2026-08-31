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
$environmentFile = Join-Path $projectRoot ".env"
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

function New-LocalSecret {
    $bytes = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-ContainerEnvironmentValue {
    param(
        [string]$ContainerName,
        [string]$VariableName
    )

    $container = & docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}" 2>$null
    if ($LASTEXITCODE -ne 0 -or $container -ne $ContainerName) {
        return $null
    }

    $entries = @(& docker inspect --format "{{range .Config.Env}}{{println .}}{{end}}" $ContainerName 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    $prefix = "$VariableName="
    $entry = $entries | Where-Object { $_.StartsWith($prefix) } | Select-Object -First 1
    if (-not $entry) {
        return $null
    }
    return $entry.Substring($prefix.Length)
}

function Ensure-LocalEnvironment {
    $existingLines = @()
    if (Test-Path -LiteralPath $environmentFile) {
        $existingLines = @(Get-Content -LiteralPath $environmentFile)
    }

    $values = @{}
    foreach ($line in $existingLines) {
        if ($line -match '^\s*([^#=\s]+)\s*=(.*)$') {
            $values[$matches[1]] = $matches[2]
        }
    }

    $newLines = New-Object System.Collections.Generic.List[string]
    if (-not $values.ContainsKey('POSTGRES_PASSWORD') -or -not $values['POSTGRES_PASSWORD']) {
        $dataPassword = Get-ContainerEnvironmentValue `
            -ContainerName 'factaut-postgres-1' `
            -VariableName 'POSTGRES_PASSWORD'
        if (-not $dataPassword) {
            $dataPassword = New-LocalSecret
        }
        $values['POSTGRES_PASSWORD'] = $dataPassword
        $newLines.Add("POSTGRES_PASSWORD=$dataPassword")
    }

    if (-not $values.ContainsKey('FACTURAS_DATABASE_URL') -or -not $values['FACTURAS_DATABASE_URL']) {
        $encodedDataPassword = [Uri]::EscapeDataString($values['POSTGRES_PASSWORD'])
        $newLines.Add("FACTURAS_DATABASE_URL=postgresql://facturas_app:$encodedDataPassword@localhost:5432/facturas_demo")
    }

    if (-not $values.ContainsKey('CONTROL_POSTGRES_PASSWORD') -or -not $values['CONTROL_POSTGRES_PASSWORD']) {
        $controlPassword = New-LocalSecret
        $values['CONTROL_POSTGRES_PASSWORD'] = $controlPassword
        $newLines.Add("CONTROL_POSTGRES_PASSWORD=$controlPassword")
    }

    if (-not $values.ContainsKey('FACTURAS_CONTROL_DATABASE_URL') -or -not $values['FACTURAS_CONTROL_DATABASE_URL']) {
        $encodedControlPassword = [Uri]::EscapeDataString($values['CONTROL_POSTGRES_PASSWORD'])
        $newLines.Add("FACTURAS_CONTROL_DATABASE_URL=postgresql://control_owner:$encodedControlPassword@localhost:5433/facturas_control")
    }

    if ($newLines.Count -eq 0) {
        return
    }

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    if ($existingLines.Count -eq 0) {
        $contents = @(
            '# Configuracion local generada automaticamente. No versionar.',
            'POSTGRES_DB=facturas_demo',
            'POSTGRES_USER=facturas_app',
            'POSTGRES_PORT=5432',
            'CONTROL_POSTGRES_DB=facturas_control',
            'CONTROL_POSTGRES_USER=control_owner',
            'CONTROL_POSTGRES_PORT=5433'
        ) + $newLines
        [IO.File]::WriteAllLines($environmentFile, $contents, $utf8)
    }
    else {
        [IO.File]::AppendAllLines(
            $environmentFile,
            @('', '# Variables de seguridad agregadas por el iniciador local.') + $newLines,
            $utf8
        )
    }
    Write-StartupLog "Configuracion local segura creada o completada."
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

        Ensure-LocalEnvironment

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
