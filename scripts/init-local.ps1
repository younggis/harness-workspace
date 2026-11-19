<#
.SYNOPSIS
Fill missing values in .env.local ONLY. Never overwrite existing values.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$example = Join-Path $root '.env.example'
$local = Join-Path $root '.env.local'

if (-not (Test-Path $local)) {
    Copy-Item $example $local
    Write-Host "Created $local from .env.example"
}

$lines = Get-Content $local
$keys = @{}
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*([A-Za-z0-9_]+)\s*=') { $keys[$matches[1]] = $i }
}
function Set-IfEmpty([string]$name, [string]$value) {
    if (-not $keys.ContainsKey($name)) { return }
    $i = $keys[$name]
    if ($lines[$i] -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$' -and $matches[2].Trim() -eq '') {
        $lines[$i] = "$name=$value"
        Write-Host "Generated $name"
    }
}
function New-Secret { [Convert]::ToBase64String([byte[]](1..48 | ForEach-Object { Get-Random -Max 256 })) }

Set-IfEmpty 'RELAY_SIGNING_KEY' (New-Secret)
Set-IfEmpty 'SESSION_SIGNING_KEY' (New-Secret)
Set-IfEmpty 'INSTALLATION_ID' 'harness-local-dev'

Set-Content -Path $local -Value $lines -Encoding utf8

$required = @('PG_APP_PASSWORD','PG_MIGRATION_PASSWORD','PG_LLM_PASSWORD','DEEPSEEK_API_KEY','PG_TEST_APP_PASSWORD')
$missing = @()
foreach ($line in (Get-Content $local)) {
    if ($line -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$' -and $matches[2].Trim() -eq '' -and $required -contains $matches[1]) {
        $missing += $matches[1]
    }
}
if ($missing.Count -gt 0) {
    Write-Host "Missing required configuration (set in .env.local): $($missing -join ', ')"
    exit 2
}
Write-Host 'init-local: configuration complete (secrets masked).'
