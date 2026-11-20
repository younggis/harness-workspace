<#
.SYNOPSIS
Remove orphan per-space Docker networks (kept relay/llm attachments only).

.DESCRIPTION
Over many generations/rebuilds, stale internal space networks can accumulate and
exhaust Docker Desktop's predefined address pools ("all predefined address pools
have been fully subnetted"). This script keeps the current generation network for
every enabled workspace and removes every other harness space network that has NO
runtime container attached (it disconnects relay/llm first).

Read-only check: run without -Apply to print what would be removed.
#>
[CmdletBinding()]
param([switch]$Apply)

. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv

$env:PGPASSWORD = $cfg.PG_MIGRATION_PASSWORD
$rows = & 'C:\Program Files\QGIS 3.44.8\bin\psql.exe' -h 127.0.0.1 -U $cfg.PG_MIGRATION_USER -d postgis -w -t -A `
  -c "select id||':'||generation from $($cfg.PG_SCHEMA).workspaces where enabled;"
Remove-Item Env:PGPASSWORD

$prefix = "harness-$($cfg.INSTALLATION_ID)-net-"
$keep = @()
foreach ($r in $rows) {
  $p = $r -split ':'
  $keep += "$prefix$($p[0])-g$($p[1])"
}

$removed = 0
foreach ($net in (docker network ls --filter "name=$prefix" --format '{{.Name}}')) {
  if ($keep -contains $net) { continue }
  $attached = docker network inspect --format '{{range $k,$v := .Containers}}{{$v.Name}} {{end}}' $net 2>$null
  $runtimes = ($attached -split '\s+') | Where-Object { $_ -match '-rt-' }
  if ($runtimes) { Write-Host "SKIP $net (runtime attached)"; continue }

  Write-Host "ORPHAN $net  attached=[$attached]"
  if ($Apply) {
    foreach ($svc in (($attached -split '\s+') | Where-Object { $_ })) {
      docker network disconnect -f $net $svc 2>&1 | Out-Null
    }
    docker network rm $net 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $removed++ }
  }
}
Write-Host "mode=$(if($Apply){'APPLY'}else{'DRY-RUN'}) removed=$removed"
