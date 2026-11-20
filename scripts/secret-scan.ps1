<#
.SYNOPSIS
Fail if a real credential shape or a sensitive local file is tracked.

.DESCRIPTION
Scans git-tracked text files for: DeepSeek/OpenAI-style keys (sk-...), AWS
access key IDs, PEM private-key blocks. Also fails if .env.local or anything
under secrets/ is tracked. Variable names in code/docs/tests are NOT secrets.
Intended as a pre-commit / CI gate. Never prints the matched value.
#>
[CmdletBinding()]
param()

$patterns = @(
  'sk-[A-Za-z0-9]{20,}',
  'AKIA[0-9A-Z]{16}',
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
)
$exclude = '\.(png|jpg|jpeg|gif|pdf|zip|gz|dump|lock)$|(^|/)dist/|(^|/)node_modules/'

$files = git ls-files
$trackedSensitive = @($files | Where-Object { $_ -match '(^|/)\.env\.local$|^secrets/' })
$findings = @()
foreach ($f in $files) {
  if ($f -match $exclude) { continue }
  if (-not (Test-Path -LiteralPath $f)) { continue }
  $content = Get-Content -LiteralPath $f -Raw -ErrorAction SilentlyContinue
  if (-not $content) { continue }
  foreach ($p in $patterns) {
    if ($content -match $p) { $findings += "$f :: $p"; break }
  }
}
if ($trackedSensitive.Count -or $findings.Count) {
  Write-Host 'SECRET_SCAN_FAIL'
  $trackedSensitive | ForEach-Object { Write-Host "  tracked sensitive file: $_" }
  $findings | ForEach-Object { Write-Host "  $_" }
  exit 1
}
Write-Host 'SECRET_SCAN_CLEAN'
