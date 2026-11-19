# Shared helpers for operational scripts. Do NOT print secret values.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env.local'

function Import-LocalEnv {
    if (-not (Test-Path $EnvFile)) { throw ".env.local missing. Copy .env.example and run init-local.ps1" }
    $vals = @{}
    foreach ($line in (Get-Content $EnvFile)) {
        if ($line -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$' -and -not $line.TrimStart().StartsWith('#')) {
            $vals[$matches[1]] = $matches[2].Trim()
        }
    }
    return $vals
}

function Assert-Installation {
    param([hashtable]$Cfg)
    if (-not $Cfg.INSTALLATION_ID -or $Cfg.INSTALLATION_ID -ne 'harness-local-dev') {
        throw "INSTALLATION_ID mismatch: refusing to operate on unknown installation"
    }
}

function Invoke-Compose {
    param([string[]]$Arguments, [hashtable]$Cfg)
    Push-Location $Root
    try {
        & docker compose --env-file $EnvFile -p $Cfg.COMPOSE_PROJECT_NAME @Arguments
        if ($LASTEXITCODE -ne 0) { throw "docker compose failed: $($Arguments -join ' ')" }
    } finally { Pop-Location }
}

function Assert-NoGlobalPrune {
    param([string[]]$Arguments)
    $joined = ($Arguments -join ' ').ToLower()
    if ($joined -match 'down\s+-v|system prune|volume prune|image prune') {
        throw 'Global prune / down -v is forbidden by the delivery spec.'
    }
}
