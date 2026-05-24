# Registers a Windows Task Scheduler task "worldcap-daily" that fires
# refresh.ps1 every day at 09:00 UTC.
#
# Usage (from PowerShell as your user, not Admin):
#   .\Register-Task.ps1
#
# To remove later:
#   Unregister-ScheduledTask -TaskName 'worldcap-daily' -Confirm:$false

param(
    [string]$WorldcapDir = (Join-Path $env:USERPROFILE 'repos\worldcap'),
    [string]$StaticRepo  = '',
    [string]$BaseUrl     = 'https://worldcup.zivalx.com',
    [string]$DailyTimeUtc = '09:00'  # 24h format
)

$ErrorActionPreference = 'Stop'

$refreshScript = Join-Path $WorldcapDir 'deploy\windows\refresh.ps1'
if (-not (Test-Path $refreshScript)) {
    throw "refresh.ps1 not found at $refreshScript — did you clone worldcap?"
}

# Convert UTC time to local (Task Scheduler runs in local time by default;
# the script trigger expects a local-time DateTime).
$parts = $DailyTimeUtc.Split(':')
$utcToday = (Get-Date).ToUniversalTime().Date.AddHours([int]$parts[0]).AddMinutes([int]$parts[1])
$localTime = $utcToday.ToLocalTime()

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$refreshScript`"" `
    -WorkingDirectory $WorldcapDir

$trigger = New-ScheduledTaskTrigger -Daily -At $localTime

# StartWhenAvailable=true → if the PC was off/asleep at scheduled time,
# run as soon as it boots.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

# Run as the current user, only when logged in.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'worldcap — daily World Cup forecast refresh + push to Cloudflare Pages'

# Environment variables for the task to consume
# Task Scheduler doesn't expose direct env-var injection at task level;
# instead, the user should either:
#   a) set them as user env vars permanently (System Properties → Environment Variables), OR
#   b) set them in refresh.ps1's defaults at the top of that file.
# If StaticRepo or BaseUrl were passed here, remind the user to configure them.

Register-ScheduledTask -TaskName 'worldcap-daily' -InputObject $task -Force | Out-Null

Write-Host "Registered task 'worldcap-daily'."
Write-Host "  Local trigger time: $localTime ($DailyTimeUtc UTC)"
Write-Host "  Script: $refreshScript"
Write-Host ""

if ($StaticRepo) {
    Write-Host "NOTE: -StaticRepo was provided but Task Scheduler has no built-in env injection."
    Write-Host "Set STATIC_REPO as a user environment variable (System Properties → Environment Variables)"
    Write-Host "  or edit the defaults at the top of refresh.ps1."
    Write-Host ""
}

Write-Host "Run it once now to verify:"
Write-Host "  Start-ScheduledTask -TaskName 'worldcap-daily'"
Write-Host "Check status:"
Write-Host "  Get-ScheduledTaskInfo -TaskName 'worldcap-daily'"
Write-Host "View logs:"
Write-Host "  Get-Content -Tail 100 -Wait `"$($env:USERPROFILE)\worldcap-refresh.log`""
