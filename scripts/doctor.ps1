<#
.SYNOPSIS
Read-only preflight: Docker mode, port availability, PG login from a diagnostic
container, and (optionally) built-image probes. Secrets are masked.
#>
[CmdletBinding()]
param([switch]$PostBuild)
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg = Import-LocalEnv
Assert-Installation $cfg

Write-Host '--- Docker ---'
docker version --format '{{.Server.Version}}' 2>$null
$os = docker info --format '{{.OSType}} {{.Architecture}}'
Write-Host "OSType=$os"
if ($os -notlike 'linux*') { throw 'Docker must be in Linux container mode' }

Write-Host '--- ports ---'
$pip = Test-NetConnection 127.0.0.1 -Port 5432 -WarningAction SilentlyContinue
Write-Host "PG 5432 reachable: $($pip.TcpTestSucceeded)"
$edge = (Get-NetTCPConnection -LocalPort $cfg.EDGE_PORT -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "Edge $($cfg.EDGE_PORT) in use: $($edge -gt 0)"

Write-Host '--- PG login from container (harness_app) ---'
docker run --rm --add-host=host.docker.internal:host-gateway `
  -e PGPASSWORD=$($cfg.PG_APP_PASSWORD) postgres:12-alpine `
  psql -h host.docker.internal -p $($cfg.PG_PORT) -U $($cfg.PG_APP_USER) -d $($cfg.PG_DATABASE) -w `
  -c 'select current_database(),current_user,inet_client_addr();'
if ($LASTEXITCODE -ne 0) { throw 'Container-to-host PG login failed; check HBA, listen_addresses, firewall' }

if ($PostBuild) {
    Write-Host '--- post-build service probes ---'
    Invoke-Compose -Cfg $cfg -Arguments @('ps')
    foreach ($p in @('api/health/live','api/health/ready','relay/health/live','llm/health/live')) {
        $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$($cfg.EDGE_PORT)/$p" -ErrorAction SilentlyContinue
        Write-Host "$p => $($r.StatusCode)"
    }
}
Write-Host 'doctor: OK (secrets masked)'
