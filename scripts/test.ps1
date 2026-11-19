<#
.SYNOPSIS
Test entry point. Offline always runs without secrets or Docker; integration/e2e/live
are opt-in and verified for isolation before touching resources.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('offline','integration','e2e','live')][string]$Suite
)
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
$Root2 = $Root
$env:PYTHONPATH = "$Root2;$Root2\common;$Root2\tests"
$py = "$Root2\.venv\Scripts\python.exe"

switch ($Suite) {
  'offline' {
    if (-not $cfg.PG_TEST_SCHEMA) { throw 'PG_TEST_SCHEMA must be set' }
    & $py -m pytest "$Root2\tests" -m 'not integration and not e2e and not live' -q
  }
  'integration' {
    Assert-Installation $cfg
    if ($cfg.PG_TEST_SCHEMA -eq $cfg.PG_SCHEMA) { throw 'Test schema must differ from dev schema' }
    if ($cfg.COMPOSE_PROJECT_NAME -like '*prod*') { throw 'Refusing integration in a production-named project' }
    & $py -m pytest "$Root2\tests\integration" -m integration -q
  }
  'e2e' {
    & $py -m pytest "$Root2\tests\e2e" -m e2e -q
  }
  'live' {
    if (-not $cfg.DEEPSEEK_API_KEY) { throw 'DEEPSEEK_API_KEY is required for live tests' }
    Write-Host 'WARNING: live suite calls the real DeepSeek API and incurs cost.'
    & $py "$Root2\scripts\deepseek_smoke.py"
    & $py -m pytest "$Root2\tests\live" -m live -q
  }
}
if ($LASTEXITCODE -ne 0) { throw "test suite $Suite failed" }
Write-Host "test $Suite: OK"
