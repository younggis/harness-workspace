<#
.SYNOPSIS
Gate for upgrading the pinned deepseek-harness version. Builds a candidate image,
runs the contract + offline suites, and records the result. Does NOT publish a
template; an operator must re-capture samples against a candidate workspace first.
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Version)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg=Import-LocalEnv
Assert-Installation $cfg
if($Version -notmatch '^\d+\.\d+\.\d+'){ throw "Version must look like 0.2.2-rc.4, got: $Version" }

Push-Location $Root
try {
  Write-Host "--- building candidate dsh $Version ---"
  & docker build --build-arg "DSH_VERSION=$Version" -t "harness-runtime-base:$Version" -f runtime/base/Dockerfile .
  if($LASTEXITCODE -ne 0){ throw 'candidate build failed' }
  $digest=& docker inspect --format '{{.Id}}' "harness-runtime-base:$Version"
  Write-Host "image=$digest"

  Write-Host '--- verifying locked dsh version in candidate ---'
  $actual=& docker run --rm --entrypoint sh "harness-runtime-base:$Version" -c 'dsh --version 2>/dev/null | head -1'
  Write-Host "dsh --version = $actual"
  if($actual -ne $Version){ throw "version mismatch: expected $Version, got $actual" }

  Write-Host '--- contract + offline gates ---'
  $env:PYTHONPATH="$Root;$Root\common"
  & "$Root\.venv\Scripts\python.exe" -m pytest "$Root\tests\test_upstream_contracts.py" "$Root\tests\test_security.py" "$Root\tests\test_control_plane.py" "$Root\tests\test_worker.py" "$Root\tests\test_connections.py" -q
  if($LASTEXITCODE -ne 0){ throw 'contract/offline gate failed; do NOT publish this template' }
} finally { Pop-Location }

$report=Join-Path $Root 'docs\upgrades.md'
$line="- $(Get-Date -Format o) candidate=$Version image=$digest dsh=$actual gate=PASS operator=$($cfg.INSTALLATION_ID)"
Add-Content -Path $report -Value $line -Encoding utf8
Write-Host 'UPGRADE_CHECK_PASS'
Write-Host 'Next: start a workspace from this image, run scripts/capture_contracts.py and capture_session_contract.py, review diffs, then register a new template via POST /api/admin/templates with dsh_version.'
