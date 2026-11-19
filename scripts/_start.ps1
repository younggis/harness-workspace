$ErrorActionPreference='Stop'
$base='http://portal.127.0.0.1.nip.io:8080'
$s=$null
$r=Invoke-WebRequest -UseBasicParsing "$base/api/auth/login" -Method Post -Headers @{'Origin'=$base} -Body '{"login":"a1","password":"Str0ngPassw0rd!x"}' -ContentType 'application/json' -SessionVariable s -TimeoutSec 15
$csrf=($r.Content|ConvertFrom-Json).csrf_token
$wid='319fc425-cf45-4307-b4a9-b693fe67cad9'
$st=Invoke-WebRequest -UseBasicParsing "$base/api/workspaces/$wid/actions/start" -Method Post -Headers @{'Origin'=$base;'X-CSRF-Token'=$csrf;'Idempotency-Key'='start-dsh1'} -WebSession $s -TimeoutSec 15
$op=($st.Content|ConvertFrom-Json).operation_id
for($i=0;$i -lt 20;$i++){
  Start-Sleep -Seconds 1
  $o=Invoke-WebRequest -UseBasicParsing "$base/api/operations/$op" -Headers @{'Origin'=$base} -WebSession $s -TimeoutSec 10
  $state=($o.Content|ConvertFrom-Json).state
  if($state -in 'succeeded','failed'){break}
}
$ws=Invoke-WebRequest -UseBasicParsing "$base/api/workspaces/$wid" -Headers @{'Origin'=$base} -WebSession $s -TimeoutSec 10
Write-Output "state=$state observed=$(($ws.Content|ConvertFrom-Json).observed_state) error=$(($ws.Content|ConvertFrom-Json).error_code)"
