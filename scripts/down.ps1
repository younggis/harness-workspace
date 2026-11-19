<#
.SYNOPSIS
Stop this installation's workspaces and control services. Preserve all volumes.
#>
[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg
Assert-NoGlobalPrune -Arguments @('down')
# Reconciler will stop labelled runtimes; we never delete volumes here.
Invoke-Compose -Cfg $cfg -Arguments @('stop')
Write-Host 'down: stopped (volumes preserved)'
