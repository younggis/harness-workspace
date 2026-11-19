$ErrorActionPreference='Stop'
$testPw=$env:HARNESS_TEST_PASSWORD
if(-not $testPw){ throw 'Set HARNESS_TEST_PASSWORD in the environment' }
$base='http://portal.127.0.0.1.nip.io:8080'
$s=$null
$r=Invoke-WebRequest -UseBasicParsing "$base/api/auth/login" -Method Post -Headers @{'Origin'=$base} -Body (@{login='testadmin';password=$testPw}|ConvertTo-Json -Compress) -ContentType 'application/json' -SessionVariable s -TimeoutSec 15
$csrf=($r.Content|ConvertFrom-Json).csrf_token
$wid='37c8fce0-5388-4d5d-bb69-62521ff5dee3'
$h=@{'Origin'=$base;'X-CSRF-Token'=$csrf;'Idempotency-Key'='rebuild-verify-'+(Get-Random)}
$op=Invoke-WebRequest -UseBasicParsing "$base/api/workspaces/$wid/actions/rebuild" -Method Post -Headers $h -WebSession $s -TimeoutSec 20
$oid=($op.Content|ConvertFrom-Json).operation_id
Write-Output "rebuild=$([int]$op.StatusCode) op=$oid"
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 1
  $x=Invoke-WebRequest -UseBasicParsing "$base/api/operations/$oid" -Headers @{'Origin'=$base} -WebSession $s -TimeoutSec 10
  $st=($x.Content|ConvertFrom-Json).state
  if($st -in 'succeeded','failed'){ Write-Output "state=$st"; break }
}
$ws=Invoke-WebRequest -UseBasicParsing "$base/api/workspaces/$wid" -Headers @{'Origin'=$base} -WebSession $s -TimeoutSec 10
Write-Output "observed=$(($ws.Content|ConvertFrom-Json).observed_state) generation=$(($ws.Content|ConvertFrom-Json).generation)"
