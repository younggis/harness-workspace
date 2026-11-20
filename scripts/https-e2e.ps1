<#
.SYNOPSIS
Local HTTPS end-to-end check using the production nginx config and dev certificate.

.DESCRIPTION
Starts a temporary nginx container with compose.prod's config (upstream pointed at
the running dev API), verifies HTTP->HTTPS redirect, HSTS/security headers and
TLS 1.2/1.3, then removes the container. Certificate is self-signed: this proves
the TLS/HSTS path, not public-CA trust.
#>
[CmdletBinding()]
param(
  [int]$HttpPort = 19080,
  [int]$HttpsPort = 19443,
  [string]$ApiHost = 'harness-local-dev-api-1'
)

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$cfg = Join-Path $env:TEMP 'harness-nginx-prod-test.conf'
(Get-Content "$root\infra\nginx\nginx-prod.conf" -Raw) -replace 'http://api:8000', "http://${ApiHost}:8000" | Set-Content -Path $cfg -Encoding ascii

docker rm -f harness-tls-test 2>$null | Out-Null
try {
  docker run -d --name harness-tls-test `
    -p ${HttpPort}:8080 -p ${HttpsPort}:8443 `
    -v "${cfg}:/etc/nginx/conf.d/default.conf:ro" `
    -v "$root\infra\nginx\certs:/etc/nginx/certs:ro" `
    -v "$root\apps\portal\dist:/usr/share/nginx/portal:ro" `
    --network harness-local-dev_backend nginx:1.27-alpine | Out-Null
  Start-Sleep -Seconds 3

  $redirect = curl.exe -s -i "http://127.0.0.1:${HttpPort}/health/live" | Select-Object -First 1
  $tls = curl.exe -s -k -i "https://127.0.0.1:${HttpsPort}/health/live"
  $hsts = $tls | Select-String 'Strict-Transport-Security'
  $t12 = curl.exe -s -k --tlsv1.2 -o NUL -w '%{http_code}' "https://127.0.0.1:${HttpsPort}/health/live"
  $t13 = curl.exe -s -k --tlsv1.3 -o NUL -w '%{http_code}' "https://127.0.0.1:${HttpsPort}/health/live"

  Write-Host "redirect=$redirect"
  Write-Host "hsts=$hsts"
  Write-Host "tls12=$t12 tls13=$t13"
  if ($redirect -match '301' -and $hsts -and $t12 -eq '200' -and $t13 -eq '200') {
    Write-Host 'HTTPS_E2E_PASS'
  } else {
    throw 'HTTPS E2E failed'
  }
} finally {
  docker rm -f harness-tls-test 2>$null | Out-Null
}
