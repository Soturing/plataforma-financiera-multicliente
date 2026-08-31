param(
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "start-demo.ps1"
$taskName = "Facturacion IA"

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "No se encontro el lanzador en $launcher"
}

$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT30S"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Inicia Docker, PostgreSQL y la aplicacion Facturacion IA al entrar a Windows." `
    -Force | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName $taskName
}

Write-Output "Tarea '$taskName' instalada correctamente."
