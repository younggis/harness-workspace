$ErrorActionPreference='Stop'
$base='http://portal.127.0.0.1.nip.io:8080'

function New-Session($login,$password){
  $s=$null
  $r=Invoke-WebRequest -UseBasicParsing "$base/api/auth/login" -Method Post `
    -Headers @{'Origin'=$base} -Body (@{login=$login;password=$password}|ConvertTo-Json -Compress) `
    -ContentType 'application/json' -SessionVariable s -TimeoutSec 15
  if($r.StatusCode -ne 200){ throw "login $login failed: $($r.StatusCode)" }
  $csrf=($r.Content|ConvertFrom-Json).csrf_token
  return @{ Session=$s; Csrf=$csrf; Body=($r.Content|ConvertFrom-Json) }
}
function Api($s,$csrf,$path,$method='GET',$body=$null,$extra=@{}){
  $h=@{'Origin'=$base;'X-CSRF-Token'=$csrf}
  foreach($k in $extra.Keys){$h[$k]=$extra[$k]}
  $p=@{}
  if($body){$p=@{Body=($body|ConvertTo-Json -Compress);ContentType='application/json'}}
  $r=Invoke-WebRequest -UseBasicParsing "$base$path" -Method $method -Headers $h -WebSession $s -TimeoutSec 15 @p
  $j=$null; try{$j=$r.Content|ConvertFrom-Json}catch{}
  return @{ Status=[int]$r.StatusCode; Body=$j; Raw=$r.Content }
}

Write-Output '--- 1) login as platform admin ---'
$a=New-Session 'admin' 'AdminStr0ng!2026#local'
Write-Output "admin login=$($a.Body.user.login_norm) tenants=$($a.Body.tenants.Count)"

Write-Output '--- 2) create test tenant ---'
$t=Api $a.Session $a.Csrf '/api/admin/tenants' 'POST' @{slug='test-tenant';name='Test Tenant';max_running=2;max_workspaces=5}
if($t.Status -eq 409){ Write-Output 'tenant already exists; reusing' }
elseif($t.Status -ne 201){ throw "create tenant failed: $($t.Status) $($t.Raw)" }
$tenants=(Api $a.Session $a.Csrf '/api/admin/tenants' 'GET').Body.items
$tid=($tenants|Where-Object{$_.slug -eq 'test-tenant'}).id
Write-Output "tenant id=$tid"

Write-Output '--- 3) create tenant admin + member ---'
$ta=Api $a.Session $a.Csrf '/api/admin/users' 'POST' @{login='testadmin';display_name='Test Admin';password='TestPassw0rd!2026'}
if($ta.Status -notin 201,409){ throw "create testadmin failed $($ta.Status) $($ta.Raw)" }
$tu=Api $a.Session $a.Csrf '/api/admin/users' 'POST' @{login='testuser';display_name='Test User';password='TestPassw0rd!2026'}
if($tu.Status -notin 201,409){ throw "create testuser failed $($tu.Status) $($tu.Raw)" }

Write-Output '--- 4) resolve user ids ---'
$env:PGPASSWORD='postgis'
$taid=(& 'C:\Program Files\QGIS 3.44.8\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgis -w -t -A -c "select id from harness.users where login_norm='testadmin';").Trim()
$tuid=(& 'C:\Program Files\QGIS 3.44.8\bin\psql.exe' -h 127.0.0.1 -U postgres -d postgis -w -t -A -c "select id from harness.users where login_norm='testuser';").Trim()
Remove-Item Env:PGPASSWORD
Write-Output "testadmin=$taid testuser=$tuid"

Write-Output '--- 5) memberships ---'
$m1=Api $a.Session $a.Csrf "/api/admin/tenants/$tid/members/$taid" 'PUT' @{role='tenant_admin';status='active'}
$m2=Api $a.Session $a.Csrf "/api/admin/tenants/$tid/members/$tuid" 'PUT' @{role='member';status='active'}
Write-Output "membership admin=$($m1.Status) member=$($m2.Status)"

Write-Output '--- 6) login as testadmin ---'
$b=New-Session 'testadmin' 'TestPassw0rd!2026'
Write-Output "testadmin login=$($b.Body.user.login_norm) tenants=$($b.Body.tenants.Count) active=$($b.Body.active_tenant_id)"
if($b.Body.active_tenant_id -ne $tid){ throw 'active tenant mismatch' }

Write-Output '--- 7) /api/me ---'
$me=Api $b.Session $b.Csrf '/api/me' 'GET'
Write-Output "me=$($me.Status) user=$($me.Body.user.login_norm) active=$($me.Body.active_tenant_id)"

Write-Output '--- 8) session persists across requests (cookie) ---'
$me2=Api $b.Session $b.Csrf '/api/me' 'GET'
Write-Output "me again=$($me2.Status) same-user=$($me2.Body.user.id -eq $me.Body.user.id)"

Write-Output '--- 9) logout revokes session ---'
$lo=Api $b.Session $b.Csrf '/api/auth/logout' 'POST'
Write-Output "logout=$($lo.Status)"
try {
  $after=Invoke-WebRequest -UseBasicParsing "$base/api/me" -Headers @{'Origin'=$base} -WebSession $b.Session -TimeoutSec 10
  Write-Output "after logout /me=$([int]$after.StatusCode) (UNEXPECTED)"
} catch {
  Write-Output "after logout /me=$([int]$_.Exception.Response.StatusCode) (expected 401)"
}

Write-Output '--- 10) testuser login ---'
$u=New-Session 'testuser' 'TestPassw0rd!2026'
Write-Output "testuser login=$($u.Body.user.login_norm) tenants=$($u.Body.tenants.Count) active=$($u.Body.active_tenant_id)"
Write-Output 'TENANT_TEST_DONE'
