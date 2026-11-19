<#
.SYNOPSIS
Maintenance-window backup of the harness platform: PostgreSQL custom-format dump
of the dedicated schema + one tar archive per workspace volume, with checksums.
Never touches other schemas, other Compose projects or user containers.
#>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutDir)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$dump = Join-Path $OutDir "harness-$stamp.dump"
$manifest = Join-Path $OutDir "manifest-$stamp.json"

# --- 1) PostgreSQL custom-format dump of ONLY the harness schema -------------
$pgdump = (Get-Command pg_dump.exe -ErrorAction SilentlyContinue).Source
if (-not $pgdump) { $pgdump = 'C:\Program Files\QGIS 3.44.8\bin\pg_dump.exe' }
if (-not (Test-Path $pgdump)) { throw "pg_dump.exe not found at $pgdump" }
$env:PGPASSWORD = $cfg.PG_MIGRATION_PASSWORD
try {
  & $pgdump -h 127.0.0.1 -p $cfg.PG_PORT -U $cfg.PG_MIGRATION_USER -d $cfg.PG_DATABASE `
    -n $cfg.PG_SCHEMA -Fc -f $dump
  if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
} finally { Remove-Item Env:PGPASSWORD }

# --- 2) Archive the two named volumes of every harness workspace -------------
$archives = @()
$vols = docker volume ls --format '{{.Name}}' | Where-Object {
  $_ -like "harness-$($cfg.INSTALLATION_ID)-proj-*" -or $_ -like "harness-$($cfg.INSTALLATION_ID)-home-*"
}
foreach ($v in $vols) {
  $tar = Join-Path $OutDir "$v-$stamp.tar"
  # cmd.exe redirection writes raw bytes; PowerShell `>` corrupts binary streams.
  & cmd /c "docker run --rm -v `"${v}:/data:ro`" alpine tar -C /data -cf /dev/stdout . > `"$tar`""
  if ($LASTEXITCODE -ne 0) { throw "archive-to-file failed for $v" }
  $sum = (Get-FileHash $tar -Algorithm SHA256).Hash
  $archives += [ordered]@{ volume = $v; file = (Split-Path $tar -Leaf); sha256 = $sum }
}

# --- 3) Manifest with versions and checksums ---------------------------------
$dumpSum = (Get-FileHash $dump -Algorithm SHA256).Hash
$lock = Get-Content (Join-Path $Root 'upstream.lock.json') -Raw | Get-FileHash -Algorithm SHA256
$obj = [ordered]@{
  created_utc = $stamp
  installation = $cfg.INSTALLATION_ID
  database = $cfg.PG_DATABASE
  schema = $cfg.PG_SCHEMA
  pg_dump = [ordered]@{ file = (Split-Path $dump -Leaf); sha256 = $dumpSum }
  upstream_lock_sha256 = $lock.Hash
  volumes = $archives
  note = 'Secrets and sessions are included in the dump; restore into isolated test target only.'
}
$obj | ConvertTo-Json -Depth 6 | Set-Content -Path $manifest -Encoding utf8
Write-Host "BACKUP_OK dump=$(Split-Path $dump -Leaf) volumes=$($archives.Count) manifest=$(Split-Path $manifest -Leaf)"
