<#
.SYNOPSIS
Run Alembic migrations against the dedicated schema using a one-shot owner context.
.PARAMETER Schema
Target schema (harness or harness_test). Never anything else.
#>
[CmdletBinding()]
param([ValidateSet('harness','harness_test')][string]$Schema = 'harness')
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg

Push-Location $Root
try {
    $env:PG_HOST = if ($Schema -eq 'harness') { '127.0.0.1' } else { '127.0.0.1' }
    $env:PG_MIGRATION_USER = if ($Schema -eq 'harness') { $cfg.PG_MIGRATION_USER } else { 'harness_test_owner' }
    $env:PG_MIGRATION_PASSWORD = if ($Schema -eq 'harness') { $cfg.PG_MIGRATION_PASSWORD } else { $cfg.PG_TEST_APP_PASSWORD }
    $env:HARNESS_MIGRATION_SCHEMA = $Schema
    $env:PYTHONPATH = "$Root;$Root\common"
    & "$Root\.venv\Scripts\python.exe" -m alembic -c "$Root\migrations\alembic.ini" upgrade head
    if ($LASTEXITCODE -ne 0) { throw "migration failed for schema $Schema" }
} finally { Pop-Location }
Write-Host "migrate: OK ($Schema)"
