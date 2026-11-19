$ErrorActionPreference='Stop'
$base='http://portal.127.0.0.1.nip.io:8080'
$s=$null
$r=Invoke-WebRequest -UseBasicParsing "$base/api/auth/login" -Method Post -Headers @{'Origin'=$base} -Body '{"login":"a1","password":"Str0ngPassw0rd!x"}' -ContentType 'application/json' -SessionVariable s -TimeoutSec 15
$csrf=($r.Content|ConvertFrom-Json).csrf_token
$wid='319fc425-cf45-4307-b4a9-b693fe67cad9'
$t=Invoke-WebRequest -UseBasicParsing "$base/api/workspaces/$wid/entry-tickets" -Method Post -Headers @{'Origin'=$base;'X-CSRF-Token'=$csrf} -Body '{"target":"agent"}' -ContentType 'application/json' -WebSession $s -TimeoutSec 15
$j=($t.Content|ConvertFrom-Json)
Write-Output "ticket=$([int]$t.StatusCode) host=$($j.workspace_host)"
$e=Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8080/_platform/enter" -Method Post -Headers @{'Host'=$j.workspace_host;'Origin'=$base} -Body @{ticket=$j.ticket} -WebSession $s -TimeoutSec 20 -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Output "enter=$([int]$e.StatusCode) loc=$($e.Headers['Location'])"
$p=Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8080/" -Headers @{'Host'=$j.workspace_host} -WebSession $s -TimeoutSec 25 -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Output "root=$([int]$p.StatusCode) len=$($p.Content.Length)"
Write-Output ($p.Content.Substring(0,[Math]::Min(260,$p.Content.Length)) -replace "`r?`n",' ')
