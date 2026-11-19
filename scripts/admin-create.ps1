<#
.SYNOPSIS
Interactive creation of the first platform administrator (no default password).
If HARNESS_ADMIN_LOGIN / HARNESS_ADMIN_PASSWORD are set, runs non-interactively.
#>
[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg
$env:PG_HOST = '127.0.0.1'
$env:PYTHONPATH = "$Root\common"
Push-Location $Root
try {
    & "$Root\.venv\Scripts\python.exe" "$Root\services\api\cli.py" admin-create
    if ($LASTEXITCODE -ne 0) { throw 'admin-create failed' }
} finally { Pop-Location }
Write-Host 'admin-create: OK'
