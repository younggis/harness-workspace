<#
.SYNOPSIS
Build portal assets and all control/runtime images. Records pinned image IDs.
#>
[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg

Write-Host '--- portal build ---'
Push-Location (Join-Path $Root 'apps/portal')
try {
    if (-not (Test-Path node_modules)) { pnpm install --frozen-lockfile }
    pnpm run build
    if ($LASTEXITCODE -ne 0) { throw 'portal build failed' }
} finally { Pop-Location }

Write-Host '--- compose images ---'
Invoke-Compose -Cfg $cfg -Arguments @('build')

Write-Host '--- runtime image (pinned dsh version) ---'
Push-Location $Root
try {
    $ver = if ($cfg.DSH_VERSION) { $cfg.DSH_VERSION } else { '0.2.2-rc.4' }
    & docker build --build-arg "DSH_VERSION=$ver" `
        -t "harness-runtime-base:$ver" -f runtime/base/Dockerfile .
    if ($LASTEXITCODE -ne 0) { throw 'runtime build failed' }
} finally { Pop-Location }

$out = Join-Path $Root 'docs'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$lines = @('# Built image inventory', '', "Built at: $((Get-Date).ToUniversalTime().ToString('o'))", '')
foreach ($svc in @('api','worker','relay','llm')) {
    $id = Invoke-Compose -Cfg $cfg -Arguments @('images','-q',$svc)
    $lines += "- `$svc`: `$id"
}
$lines += "- runtime base: see runtime/base/Dockerfile (pinned dsh $($cfg.DSH_VERSION))"
Set-Content (Join-Path $out 'images.md') -Value $lines -Encoding utf8
Write-Host 'build: OK'
