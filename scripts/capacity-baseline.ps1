<#
.SYNOPSIS
Collect a machine-readable capacity baseline: host resources, container usage,
model request latency from harness.model_requests. Does not mutate the stack.
#>
[CmdletBinding()]
param([string]$Out = 'docs/capacity.md')
$ErrorActionPreference='Continue'
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg=Import-LocalEnv
$report=Join-Path $Root $Out

$cpu=(Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
$mem=[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,2)
$df=Get-PSDrive C
$lines=@(
  '# Capacity baseline (observation only)',
  '',
  "Collected: $(Get-Date -Format o)",
  "Config: $($cfg.PORTAL_ORIGIN) / project $($cfg.COMPOSE_PROJECT_NAME)",
  '',
  '## Host',
  "- Windows, logical CPUs: $cpu, RAM: $mem GB, C: free: $([math]::Round($df.Free/1GB,2)) GB",
  '- Docker: ' + (docker version --format '{{.Server.Version}}' 2>$null),
  '- Docker disk usage:',
  '```'
)
$lines += (docker system df 2>&1 | Out-String).Trim()
$lines += @('```','','## Container snapshot','','| Container | CPU% | Memory |','|---|---|---|')

$stats=docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}' 2>&1
foreach($s in $stats){
  if($s -match 'harness|rt-'){
    $p=$s -split '\|'
    $lines += "| $($p[0]) | $($p[1]) | $($p[2]) |"
  }
}

$lines += @('','## Model request latency (harness.model_requests)','')
$env:PGPASSWORD=$cfg.PG_APP_PASSWORD
$psql='C:\Program Files\QGIS 3.44.8\bin\psql.exe'
$rows=& $psql -h 127.0.0.1 -p $cfg.PG_PORT -U $cfg.PG_APP_USER -d $cfg.PG_DATABASE -w -c "select model,count(*) as n,round(avg(latency_ms)) as avg_ms,max(latency_ms) as max_ms,sum(input_tokens+output_tokens) as tokens from harness.model_requests group by model order by model;" 2>&1
Remove-Item Env:PGPASSWORD
$lines += '```'
$lines += ($rows | Out-String).Trim()
$lines += '```'
$lines += @('','## Notes','- Dev-machine snapshot, not a production capacity guarantee.',
  '- T17 cold/hot start x5 and 1/2/4-space load tests still require a dedicated test environment.')

$lines -join "`n" | Set-Content -Path $report -Encoding utf8
Write-Output "CAPACITY_REPORT=$report"
