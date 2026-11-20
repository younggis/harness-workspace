<#
.SYNOPSIS
Local CI gate: secret scan, backend tests, frontend tests/build, compose config.

.DESCRIPTION
Runs everything that does not need real DeepSeek credentials or a maintenance
window. Exit non-zero on the first failure. Use before push or on a runner.
#>
[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $root
try {
  Write-Host '== 1/5 secret scan =='
  & "$root\scripts\secret-scan.ps1"
  if ($LASTEXITCODE -ne 0) { throw 'secret scan failed' }

  Write-Host '== 2/5 backend tests =='
  & "$root\.venv\Scripts\python.exe" -m pytest tests/ -q
  if ($LASTEXITCODE -ne 0) { throw 'backend tests failed' }

  Write-Host '== 3/5 frontend tests =='
  Push-Location "$root\apps\portal"
  pnpm run test
  if ($LASTEXITCODE -ne 0) { throw 'frontend tests failed' }

  if (-not $SkipBuild) {
    Write-Host '== 4/5 frontend build =='
    pnpm run build
    if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
  }
  Pop-Location

  Write-Host '== 5/5 compose config =='
  $env:PG_APP_PASSWORD = 'ci'; $env:PG_MIGRATION_PASSWORD = 'ci'
  $env:SESSION_SIGNING_KEY = 'ci'; $env:RELAY_SIGNING_KEY = 'ci'
  $env:HARNESS_WORKSPACE_TOKEN_SEED = 'ci'
  docker compose --env-file .env.example -f compose.prod.yaml config --quiet
  if ($LASTEXITCODE -ne 0) { throw 'compose config failed' }

  Write-Host 'CI_PASS'
  exit 0
} finally {
  Pop-Location
}
