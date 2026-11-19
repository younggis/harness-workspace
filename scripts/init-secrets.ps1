<#
.SYNOPSIS
Materialize local .env.local secrets into ./secrets/*.txt for Docker secrets.
The secrets directory is gitignored. Never commit these files.
#>
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
$cfg=Import-LocalEnv
Assert-Installation $cfg
$dir=Join-Path $Root 'secrets'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$map=[ordered]@{
  'pg_app_password'        = $cfg.PG_APP_PASSWORD
  'pg_migration_password'  = $cfg.PG_MIGRATION_PASSWORD
  'pg_llm_password'        = $cfg.PG_LLM_PASSWORD
  'deepseek_api_key'       = $cfg.DEEPSEEK_API_KEY
  'relay_signing_key'      = $cfg.RELAY_SIGNING_KEY
  'session_signing_key'    = $cfg.SESSION_SIGNING_KEY
  'workspace_token_seed'   = $cfg.HARNESS_WORKSPACE_TOKEN_SEED
  'oidc_client_secret'     = $cfg.OIDC_CLIENT_SECRET
  'scim_bearer_token'      = $cfg.SCIM_BEARER_TOKEN
}
foreach($k in $map.Keys){
  # Always materialize the file (empty allowed) so Compose secret mounts never break.
  $p=Join-Path $dir "$k.txt"
  [IO.File]::WriteAllText($p,[string]$map[$k],[Text.UTF8Encoding]::new($false))
  if([string]::IsNullOrWhiteSpace([string]$map[$k])){ Write-Host "WARN empty secret: $k" } else { Write-Host "wrote $k.txt" }
}
Write-Host 'SECRETS_OK (gitignored). Use compose.prod.yaml; do not commit ./secrets.'
