<#
.SYNOPSIS
PostgreSQL PITR drill on an ISOLATED Docker instance (never touches the host PG).
Creates a base backup, writes new data, restores to a point in time, verifies.
#>
[CmdletBinding()]
param([string]$WorkDir = 'C:\Users\young\AppData\Local\Temp\opencode\pg-pitr')
# psql writes NOTICE/WARNING to stderr; do not treat those as terminating errors.
$ErrorActionPreference='Continue'
. (Join-Path $PSScriptRoot '_common.ps1')
$compose="$Root\compose.pg.yaml"
$proj='harness-pg-drill'
$work=Join-Path $WorkDir (Get-Date -Format 'yyyyMMddTHHmmss')
New-Item -ItemType Directory -Force -Path $work | Out-Null
$base=Join-Path $work 'base'
$restore=Join-Path $work 'restore'

function Pg($sql){ docker exec -i harness-pg-drill-pg-1 psql -U postgres -d harness_drill -v ON_ERROR_STOP=1 -c $sql 2>&1 }

Write-Host '--- 1) start isolated PG with WAL archiving ---'
docker compose -f $compose -p $proj up -d
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 1
  $s=docker inspect --format '{{.State.Health.Status}}' harness-pg-drill-pg-1 2>$null
  if($s -eq 'healthy'){ break }
}
if($s -ne 'healthy'){ throw "PG not healthy: $s" }
Write-Output "archive_mode=$(Pg "show archive_mode;")"

Write-Host '--- 2) create marker data and base backup ---'
Pg "DROP TABLE IF EXISTS pitr_marker; CREATE TABLE pitr_marker(id serial primary key, note text, at timestamptz default now()); INSERT INTO pitr_marker(note) VALUES ('before-backup');" | Out-Null
$target=(docker exec -i harness-pg-drill-pg-1 psql -U postgres -d harness_drill -t -A -c "select at::text from pitr_marker where note='before-backup';" 2>&1).Trim()
docker exec -i harness-pg-drill-pg-1 sh -c "rm -rf /tmp/base && pg_basebackup -U postgres -D /tmp/base -Fp -X stream -R" 2>&1 | Out-Null
if($LASTEXITCODE -ne 0){ throw 'pg_basebackup failed' }
docker cp 'harness-pg-drill-pg-1:/tmp/base' $base 2>&1 | Out-Null
Write-Output "target_time=$target base=$(Test-Path $base)"

Write-Host '--- 3) write data AFTER the backup ---'
Pg "INSERT INTO pitr_marker(note) VALUES ('after-backup');" | Out-Null
$countBefore=(docker exec -i harness-pg-drill-pg-1 psql -U postgres -d harness_drill -t -A -c 'select count(*) from pitr_marker;' 2>&1).Trim()
Write-Output "rows_before_restore=$countBefore"

Write-Host '--- 4) restore base backup to the point in time ---'
Copy-Item -Recurse $base $restore
$auto=Join-Path $restore 'postgresql.auto.conf'
Add-Content -Path $auto -Value "restore_command = 'cp /archive/%f %p'"
Add-Content -Path $auto -Value "recovery_target_time = '$target'"
Add-Content -Path $auto -Value "recovery_target_action = 'promote'"
New-Item -ItemType File -Force -Path (Join-Path $restore 'recovery.signal') | Out-Null

docker run -d --name harness-pg-drill-restore `
  -e POSTGRES_PASSWORD=postgres `
  -v "${restore}:/var/lib/postgresql/data" `
  -v 'harness-pg-drill_pg_archive:/archive:ro' `
  -p 127.0.0.1:15433:5432 `
  postgis/postgis:16-3.6 `
  sh -c "chmod -R 700 /var/lib/postgresql/data && exec docker-entrypoint.sh postgres -c wal_level=replica" 2>&1 | Out-Null
for($i=0;$i -lt 40;$i++){
  Start-Sleep -Seconds 1
  $ok=docker exec harness-pg-drill-restore pg_isready -U postgres -d harness_drill 2>$null
  if($LASTEXITCODE -eq 0){ break }
}
$rows=docker exec -i harness-pg-drill-restore psql -U postgres -d harness_drill -t -A -c 'select note from pitr_marker order by id;' 2>&1
Write-Output "restored_rows=$($rows -join ',')"

Write-Host '--- 5) cleanup ---'
docker rm -f harness-pg-drill-restore 2>&1 | Out-Null
if($rows -match 'before-backup' -and $rows -notmatch 'after-backup'){
  Write-Output 'PITR_DRILL_PASS'
}else{ throw "PITR result unexpected: $rows" }
