$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$stagedFiles = @(& git -C $projectRoot diff --cached --name-only --diff-filter=ACMR)
if ($LASTEXITCODE -ne 0) {
    throw "No fue posible leer el índice de Git."
}

$forbiddenPaths = '^(output|outputs|deliverables|entregables|data|reports|exports|app/static/brands|config/tenants/private)/'
$officeFiles = '\.(pdf|docx|xlsx|xlsm|pptx|p12|pfx|pem|key)$'
$textExtensions = '\.(py|sql|md|html|css|js|mjs|ps1|sh|yaml|yml|toml|json|txt|example|cmd)$'
$secretPatterns = @(
    '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'github_pat_[A-Za-z0-9_]{20,}',
    'gh[pousr]_[A-Za-z0-9]{20,}',
    'AKIA[0-9A-Z]{16}'
)

$errors = New-Object System.Collections.Generic.List[string]
foreach ($path in $stagedFiles) {
    $normalized = $path.Replace('\', '/')
    if ($normalized -eq 'scripts/check_repo_safety.ps1') {
        continue
    }
    if ($normalized -match $forbiddenPaths) {
        $errors.Add("Ruta confidencial en el commit: $normalized")
        continue
    }
    if ($normalized -match $officeFiles -and $normalized -notmatch '^tests/fixtures/synthetic/') {
        $errors.Add("Binario no permitido fuera de fixtures sintéticos: $normalized")
        continue
    }
    if ($normalized -notmatch $textExtensions) {
        continue
    }

    $content = (& git -C $projectRoot show ":$normalized" 2>$null) -join "`n"
    foreach ($pattern in $secretPatterns) {
        if ($content -match $pattern) {
            $errors.Add("Posible secreto en $normalized (patrón: $pattern)")
        }
    }
}

if ($errors.Count -gt 0) {
    Write-Error ("Commit bloqueado por la política de seguridad:`n- " + ($errors -join "`n- "))
    exit 1
}

Write-Output "Control de repositorio: sin rutas confidenciales ni secretos evidentes."
