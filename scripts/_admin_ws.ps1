$ErrorActionPreference='Stop'
$adminPw=$env:HARNESS_TEST_ADMIN_PASSWORD
if(-not $adminPw){ throw 'Set HARNESS_TEST_ADMIN_PASSWORD in the environment' }
$base='http://127.0.0.1:8080'
$s=$null
$r=Invoke-WebRequest -UseBasicParsing "$base/api/auth/login" -Method Post -Headers @{'Origin'=$base} -Body (@{login='admin';password=$adminPw}|ConvertTo-Json -Compress) -ContentType 'application/json' -SessionVariable s -TimeoutSec 15
$csrf=($r.Content|ConvertFrom-Json).csrf_token
$h=@{'Origin'=$base;'X-CSRF-Token'=$csrf}
$env:PGPASSWORD='postgis'
$tid=(& 'C:\Program Files\QGIS 3.44.8\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgis -w -t -A -c "select id from harness.tenants where slug='test-tenant';").Trim()
$aid=(& 'C:\Program Files\QGIS 3.44.8\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgis -w -t -A -c "select id from harness.users where login_norm='admin';").Trim()
Remove-Item Env:PGPASSWORD
$m=Invoke-WebRequest -UseBasicParsing "$base/api/admin/tenants/$tid/members/$aid" -Method Put -Headers $h -Body (@{role='tenant_admin';status='active'}|ConvertTo-Json -Compress) -ContentType 'application/json' -WebSession $s -TimeoutSec 15
Write-Output "member=$([int]$m.StatusCode)"
$a=Invoke-WebRequest -UseBasicParsing "$base/api/admin/tenants/$tid/workspaces" -Method Post -Headers ($h+@{'Idempotency-Key'='admin-own-ws'}) -Body (@{owner_id=$aid;template_version='base-v23'}|ConvertTo-Json -Compress) -ContentType 'application/json' -WebSession $s -TimeoutSec 15
Write-Output "allocate=$([int]$a.StatusCode) wid=$(($a.Content|ConvertFrom-Json).id)"
$wid=($a.Content|ConvertFrom-Json).id
$st=Invoke-WebRequest -UseBasicParsing "$base/api/workspaces/$wid/actions/start" -Method Post -Headers ($h+@{'Idempotency-Key'='admin-own-start'}) -WebSession $s -TimeoutSec 15
$oid=($st.Content|ConvertFrom-Json).operation_id
for($i=0;$i -lt 20;$i++){ Start-Sleep -Seconds 1; $o=Invoke-WebRequest -UseBasicParsing "$base/api/operations/$oid" -Headers $h -WebSession $s -TimeoutSec 10; $state=($o.Content|ConvertFrom-Json).state; if($state -in 'succeeded','failed'){break} }
Write-Output "start=$state wid=$wid"
