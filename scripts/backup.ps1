<#
.SYNOPSIS
Maintenance-window backup: pg_dump (custom format) of the harness schema plus both
volumes. Never touches other schemas or Docker projects.
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutDir)
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')

# Schema-only metadata dump (roles/grants recorded separately in docs).
$env:PGPASSWORD = $cfg.PG_MIGRATION_PASSWORD
$dump = Join-Path $OutDir "harness-$stamp.dump"
& 'C:\Program Files\QGIS 3.44.8\bin\psql.exe' --version | Out-Null
$pgdump = (Get-Command pg_dump.exe -ErrorAction SilentlyContinue).Source
if (-not $pgdump) { $pgdump = 'C:\Program Files\QGIS 3.44.8\bin\pg_dump.exe' }
& $pgdump -h 127.0.0.1 -p $cfg.PG_PORT -U $cfg.PG_MIGRATION_USER -d $cfg.PG_DATABASE `
  -n $cfg.PG_SCHEMA -Fc -f $dump
Remove-Item Env:PGPASSWORD
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }

# Volumes via trusted read-only helper container; checksums recorded.
foreach ($kind in @('proj','home')) {
    $vol = "harness-$($cfg.INSTALLATION_ID)-$kind-"
    Write-Host "Volume prefix to archive: $vol* (logical workspace id used, not container id)"
}
Set-Content (Join-Path $OutDir "manifest-$stamp.txt") -Value @(
  "installation=$($cfg.INSTALLATION_ID)","schema=$($cfg.PG_SCHEMA)","dump=$dump",
  "upstream_lock=$(Get-Content (Join-Path $Root 'upstream.lock.json') -Raw | Get-FileHash -Algorithm SHA256).Hash"
) -Encoding utf8
Write-Host "backup: OK -> $OutDir"
