<#
.SYNOPSIS
Prune old audit_events / model_requests rows in bounded batches.

.DESCRIPTION
Reads retention days from .env.local (AUDIT_RETENTION_DAYS=90,
MODEL_REQUEST_RETENTION_DAYS=90 by default). Dry-run by default; use -Apply to
actually delete. Deletes at most -BatchSize rows per table per invocation to
avoid long locks and WAL spikes. Run on a schedule with -Apply.
#>
[CmdletBinding()]
param(
  [switch]$Apply,
  [int]$BatchSize = 10000,
  [string]$PgExe = 'C:\Program Files\QGIS 3.44.8\bin\psql.exe'
)

. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
$auditDays = if ($cfg.AUDIT_RETENTION_DAYS) { [int]$cfg.AUDIT_RETENTION_DAYS } else { 90 }
$modelDays = if ($cfg.MODEL_REQUEST_RETENTION_DAYS) { [int]$cfg.MODEL_REQUEST_RETENTION_DAYS } else { 90 }
$schema = $cfg.PG_SCHEMA

$env:PGPASSWORD = $cfg.PG_ADMIN_PASSWORD
$admin = $cfg.PG_ADMIN_USER
if (-not $admin) { $admin = 'postgres' }

function Invoke-Sql([string]$sql) {
  & $PgExe -h 127.0.0.1 -U $admin -d postgis -w -t -A -c $sql 2>&1
}

$auditCuts = "now() - interval '$auditDays days'"
$modelCuts = "now() - interval '$modelDays days'"

$auditCount = (Invoke-Sql "select count(*) from $schema.audit_events where occurred_at < $auditCuts;").Trim()
$modelCount = (Invoke-Sql "select count(*) from $schema.model_requests where created_at < $modelCuts;").Trim()
Write-Host "audit_events older than ${auditDays}d: $auditCount"
Write-Host "model_requests older than ${modelDays}d: $modelCount"

if (-not $Apply) { Write-Host 'DRY-RUN (use -Apply to delete)'; exit 0 }

$a = (Invoke-Sql "with d as (select ctid from $schema.audit_events where occurred_at < $auditCuts limit $BatchSize for update skip locked) delete from $schema.audit_events where ctid in (select ctid from d) returning 1;" | Measure-Object -Line).Lines
$m = (Invoke-Sql "with d as (select ctid from $schema.model_requests where created_at < $modelCuts limit $BatchSize for update skip locked) delete from $schema.model_requests where ctid in (select ctid from d) returning 1;" | Measure-Object -Line).Lines
Write-Host "deleted audit_events=$a model_requests=$m"

Remove-Item Env:PGPASSWORD
