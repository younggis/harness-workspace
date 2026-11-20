<#
.SYNOPSIS
Generate replacement signing keys / tokens for a zero-downtime rotation.

.DESCRIPTION
Prints NEW values and the exact .env.local edits. It does NOT modify files.
Two-phase rollout:
  1) Set SESSION_SIGNING_KEY_PREVIOUS=<old>, SESSION_SIGNING_KEY=<new>,
     and/or replace SCIM_BEARER_TOKEN / RELAY_SIGNING_KEY / HARNESS_WORKSPACE_TOKEN_SEED.
     Restart control services. Old state cookies remain verifiable for one window.
  2) After all in-flight OIDC/MFA flows finish, remove *_PREVIOUS and restart again.
Rotating HARNESS_WORKSPACE_TOKEN_SEED forces runtime re-credentialing: rebuild
all spaces (the worker revokes old credentials on rebuild).
#>
[CmdletBinding()]
param()

function New-Secret([int]$Bytes = 32) {
  $buf = New-Object byte[] $Bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buf)
  [Convert]::ToHexString($buf).ToLowerInvariant()
}

Write-Host '=== NEW SECRET VALUES (store in .env.local / Docker secrets) ==='
Write-Host "SESSION_SIGNING_KEY=$((New-Secret 32))"
Write-Host "SESSION_SIGNING_KEY_PREVIOUS=<current value from .env.local, keep for one window>"
Write-Host "RELAY_SIGNING_KEY=$((New-Secret 32))"
Write-Host "HARNESS_WORKSPACE_TOKEN_SEED=$((New-Secret 32))"
Write-Host "SCIM_BEARER_TOKEN=$((New-Secret 24))"
Write-Host ''
Write-Host 'Production: regenerate secrets/*.txt via scripts/init-secrets.ps1 after editing .env.local.'
Write-Host 'Never commit .env.local or secrets/.'
