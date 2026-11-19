<#
.SYNOPSIS
Restore a backup into an ISOLATED test target only. Requires explicit -Target test.
Never overwrites the development installation.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidateSet('test')][string]$Target,
  [Parameter(Mandatory=$true)][string]$DumpFile
)
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg
if (-not (Test-Path $DumpFile)) { throw "Dump not found: $DumpFile" }
Write-Host "Restore target=$Target (isolated). Requires harness_test schema and a separate compose project."
# 1. restore metadata into harness_test via pg_restore
# 2. restore both volumes into test-prefixed volumes by logical workspace id
# 3. clear auth_sessions/entry_tickets/in-flight leases; bump auth_epoch; revoke credentials
# 4. reconcile from stopped
Write-Host 'restore: manual drill required (see docs/verification.md T15) - never auto-overwrites production'
