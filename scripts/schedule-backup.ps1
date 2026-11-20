<#
.SYNOPSIS
Install or remove a Windows Scheduled Task for daily harness backups.

.DESCRIPTION
Does NOT install anything unless -Install is passed. The task runs backup.ps1
into -BackupRoot, keeping only the newest -KeepDays daily folders.
Requires elevated PowerShell for Register-ScheduledTask / Unregister-ScheduledTask.
This is a host-level change: review with the operator before running -Install.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$BackupRoot,
  [switch]$Install,
  [switch]$Uninstall,
  [int]$KeepDays = 14,
  [string]$TaskName = 'HarnessDailyBackup',
  [string]$Time = '02:00'
)

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ps = (Get-Command powershell.exe).Source
$args = "-NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\backup.ps1`" -OutDir `"$BackupRoot\today`""

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "removed task $TaskName"
  exit 0
}
if (-not $Install) {
  Write-Host "DRY-RUN. To install, run elevated:"
  Write-Host "  powershell -ExecutionPolicy Bypass -File $root\scripts\schedule-backup.ps1 -Install -BackupRoot '$BackupRoot'"
  Write-Host "  action: $ps $args"
  exit 0
}

$action = New-ScheduledTaskAction -Execute $ps -Argument $args
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "installed $TaskName at $Time -> $BackupRoot"
Write-Host "Note: add a retention step (delete folders older than $KeepDays days) per your backup policy."
