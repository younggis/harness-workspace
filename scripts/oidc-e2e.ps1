<#
.SYNOPSIS
Run the local OIDC end-to-end verification (mock IdP + isolated API).

.DESCRIPTION
Starts scripts/mock_idp.py (9100) and scripts/oidc_e2e_server.py (9101) as
background processes, runs scripts/oidc-e2e-check.py, then stops them.
No external IdP credentials needed; exercises real PKCE/JWKS/nonce/JIT code.
#>
[CmdletBinding()]
param()

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = "$root\.venv\Scripts\python.exe"
$jobs = @()
try {
  $jobs += Start-Process -FilePath $py -ArgumentList "$root\scripts\mock_idp.py" -WindowStyle Hidden -PassThru
  $jobs += Start-Process -FilePath $py -ArgumentList "$root\scripts\oidc_e2e_server.py" -WindowStyle Hidden -PassThru
  Start-Sleep -Seconds 4
  & $py "$root\scripts\oidc-e2e-check.py"
  if ($LASTEXITCODE -ne 0) { throw 'OIDC E2E failed' }
} finally {
  foreach ($j in $jobs) { Stop-Process -Id $j.Id -Force -ErrorAction SilentlyContinue }
}
