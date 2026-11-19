<#
.SYNOPSIS
Restore a backup into an ISOLATED test target only. Never overwrites the dev install.
Targets: PG schema harness_test, volumes prefixed harness-test-restore-, separate project.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidateSet('test')][string]$Target,
  [Parameter(Mandatory=$true)][string]$Manifest
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg
if ($cfg.PG_TEST_SCHEMA -eq $cfg.PG_SCHEMA) { throw 'PG_TEST_SCHEMA must differ from PG_SCHEMA' }
if ($cfg.COMPOSE_PROJECT_NAME -like '*prod*') { throw 'Refuse restore in a production-named project' }
if (-not (Test-Path $Manifest)) { throw "Manifest not found: $Manifest" }
$m = Get-Content $Manifest -Raw | ConvertFrom-Json
$backupDir = Split-Path $Manifest -Parent
$dump = Join-Path $backupDir $m.pg_dump.file
if (-not (Test-Path $dump)) { throw "Dump missing: $dump" }
if ((Get-FileHash $dump -Algorithm SHA256).Hash -ne $m.pg_dump.sha256) { throw 'Dump checksum mismatch' }

$answer = Read-Host "This will REPLACE schema '$($cfg.PG_TEST_SCHEMA)' and test volumes. Type RESTORE to continue"
if ($answer -ne 'RESTORE') { Write-Host 'Aborted'; exit 1 }

# --- 1) Restore metadata into isolated schema --------------------------------
$regDb = 'harness_restore_test'
$bin = 'C:\Program Files\QGIS 3.44.8\bin'
$psql = Join-Path $bin 'psql.exe'
$pgrestore = Join-Path $bin 'pg_restore.exe'
if (-not (Test-Path $pgrestore)) { throw "pg_restore.exe not found at $pgrestore" }
if (-not $cfg.PG_ADMIN_PASSWORD) { throw 'PG_ADMIN_PASSWORD is required for an isolated restore drill' }
$env:PGPASSWORD = $cfg.PG_ADMIN_PASSWORD
try {
  & $psql -h 127.0.0.1 -p $cfg.PG_PORT -U $($cfg.PG_ADMIN_USER) -d postgres -w -c "DROP DATABASE IF EXISTS $regDb;"
  & $psql -h 127.0.0.1 -p $cfg.PG_PORT -U $($cfg.PG_ADMIN_USER) -d postgres -w -c "CREATE DATABASE $regDb OWNER $($cfg.PG_MIGRATION_USER);"
  # Render SQL then strip SET transaction_timeout (pg_restore 17 emits it; PG 12 rejects it).
  $sql = Join-Path $backupDir "restore-$regDb.sql"
  & $pgrestore --no-owner --no-privileges -f $sql $dump
  if ($LASTEXITCODE -ne 0) { throw 'pg_restore (render) failed' }
  $sqlLines = Get-Content $sql | Where-Object { $_ -notmatch 'transaction_timeout' }
  $sqlLines | Set-Content -Path $sql -Encoding utf8
  & $psql -h 127.0.0.1 -p $cfg.PG_PORT -U $cfg.PG_MIGRATION_USER -d $regDb -w -f $sql
  if ($LASTEXITCODE -ne 0) { throw 'restore SQL apply failed' }
} finally { Remove-Item Env:PGPASSWORD }

# --- 2) Sanitize restored sessions / leases, bump epoch ----------------------
$env:PGPASSWORD = $cfg.PG_MIGRATION_PASSWORD
try {
  & $psql -h 127.0.0.1 -p $cfg.PG_PORT -U $cfg.PG_MIGRATION_USER -d $regDb -w `
    -c "DELETE FROM harness.workspace_sessions; DELETE FROM harness.entry_tickets; DELETE FROM harness.auth_sessions;
        UPDATE harness.workspace_operations SET state='failed', finished_at=now(), error_code='RESTORE_RESET' WHERE state IN ('queued','running');
        UPDATE harness.workspaces SET auth_epoch = auth_epoch + 1, observed_state='stopped', desired_state='stopped';"
} finally { Remove-Item Env:PGPASSWORD }

# --- 3) Restore volumes into test-prefixed volumes ---------------------------
foreach ($a in $m.volumes) {
  $tar = Join-Path $backupDir $a.file
  if ((Get-FileHash $tar -Algorithm SHA256).Hash -ne $a.sha256) { throw "Volume checksum mismatch: $($a.volume)" }
  $testVol = $a.volume -replace '^harness-', 'harness-test-restore-'
  docker volume create --name $testVol 2>&1 | Out-Null
  # Mount the backup directory into the helper container; never stream bytes via PowerShell.
  docker run --rm -v "${backupDir}:/backup:ro" -v "${testVol}:/data" alpine `
    sh -c "tar -C /data -xf /backup/$(Split-Path $tar -Leaf)"
  if ($LASTEXITCODE -ne 0) { throw "volume restore failed: $($a.volume)" }
}

Write-Host "RESTORE_OK target=$Target database=$regDb volumes=$($m.volumes.Count)"
Write-Host 'NOTICE: sessions cleared, auth_epoch bumped, workspaces stopped. Run a separate Compose project against harness_test and reconcile from stopped before use.'
