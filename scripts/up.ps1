<#
.SYNOPSIS
Start configured services and wait for readiness. Never prunes anything.
#>
[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg
Assert-NoGlobalPrune -Arguments @('up')
Invoke-Compose -Cfg $cfg -Arguments @('up','-d')
foreach ($i in 1..30) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$($cfg.EDGE_PORT)/health/live" -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { Write-Host "portal ready at $($cfg.PORTAL_ORIGIN)"; return }
    } catch { Start-Sleep -Seconds 2 }
}
throw 'readiness timeout'
