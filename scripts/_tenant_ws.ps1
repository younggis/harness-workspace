$ErrorActionPreference='Stop'
$base='http://portal.127.0.0.1.nip.io:8080'
$s=$null
$r=Invoke-WebRequest -UseBasicParsing "$base/api/auth/login" -Method Post `
  -Headers @{'Origin'=$base} -Body (@{login='testadmin';password='TestPassw0rd!2026'}|ConvertTo-Json -Compress) `
  -ContentType 'application/json' -SessionVariable s -TimeoutSec 15
$csrf=($r.Content|ConvertFrom-Json).csrf_token
Write-Output "login=$($r.StatusCode) user=$(($r.Content|ConvertFrom-Json).user.login_norm)"

function Api($path,$method='GET',$body=$null,$extra=@{}){
  $h=@{'Origin'=$base;'X-CSRF-Token'=$csrf}
  foreach($k in $extra.Keys){$h[$k]=$extra[$k]}
  $p=@{}
  if($body){$p=@{Body=($body|ConvertTo-Json -Compress);ContentType='application/json'}}
  $x=Invoke-WebRequest -UseBasicParsing "$base$path" -Method $method -Headers $h -WebSession $s -TimeoutSec 20 @p
  $j=$null; try{$j=$x.Content|ConvertFrom-Json}catch{}
  return @{Status=[int]$x.StatusCode;Body=$j;Raw=$x.Content}
}

$env:PGPASSWORD='postgis'
$tid=(& 'C:\Program Files\QGIS 3.44.8\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgis -w -t -A -c "select id from harness.tenants where slug='test-tenant';").Trim()
$uid=(& 'C:\Program Files\QGIS 3.44.8\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgis -w -t -A -c "select id from harness.users where login_norm='testadmin';").Trim()
Remove-Item Env:PGPASSWORD
Write-Output "tenant=$tid owner=$uid"

$list=Api '/api/workspaces' 'GET'
Write-Output "existing workspaces=$($list.Body.Count)"
if($list.Body.Count -eq 0){
  $a=Api "/api/admin/tenants/$tid/workspaces" 'POST' @{owner_id=$uid;template_version='base-v23'} @{'Idempotency-Key'='alloc-testadmin-1'}
  Write-Output "allocate=$($a.Status)"
  if($a.Status -ne 201){ throw "allocate failed: $($a.Raw)" }
}
$list=Api '/api/workspaces' 'GET'
$wid=$list.Body[0].id
Write-Output "workspace=$wid state=$($list.Body[0].observed_state)"

if($list.Body[0].observed_state -ne 'running'){
  $st=Api "/api/workspaces/$wid/actions/start" 'POST' $null @{'Idempotency-Key'='start-testadmin-1'}
  Write-Output "start=$($st.Status) op=$($st.Body.operation_id)"
  $op=$st.Body.operation_id
  for($i=0;$i -lt 30;$i++){
    Start-Sleep -Seconds 1
    $o=Api "/api/operations/$op" 'GET'
    if($o.Body.state -in 'succeeded','failed'){ Write-Output "op state=$($o.Body.state)"; break }
  }
}
$ws=Api "/api/workspaces/$wid" 'GET'
Write-Output "workspace state=$($ws.Body.observed_state) enabled=$($ws.Body.enabled) actions=$($ws.Body.actions -join ',')"

$t=Api "/api/workspaces/$wid/entry-tickets" 'POST' @{target='agent'} @{'Idempotency-Key'="ticket-$(Get-Random)"}
Write-Output "ticket=$($t.Status) host=$($t.Body.workspace_host)"
Write-Output "WORKSPACE_ID=$wid"
