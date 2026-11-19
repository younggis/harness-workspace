<#
.SYNOPSIS
Generate a SELF-SIGNED development certificate for compose.prod.yaml.
NOT for production: replace fullchain.pem/privkey.pem with a real CA/Let's Encrypt cert.
#>
[CmdletBinding()]
param([string]$CommonName = 'portal.localtest.me')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
$dir=Join-Path $Root 'infra\nginx\certs'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

docker run --rm -v "${dir}:/certs" alpine/openssl:3.3.2 `
  req -x509 -newkey rsa:2048 -nodes -days 365 `
  -keyout /certs/privkey.pem -out /certs/fullchain.pem `
  -subj "/CN=$CommonName" `
  -addext "subjectAltName=DNS:$CommonName,DNS:localhost,IP:127.0.0.1"
if($LASTEXITCODE -ne 0){ throw 'cert generation failed (docker/alpine/openssl unavailable)' }
Write-Output "DEVCERT_OK $dir (self-signed; replace with a trusted certificate for production)"
