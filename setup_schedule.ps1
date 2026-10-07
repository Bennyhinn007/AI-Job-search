<#
.SYNOPSIS
  Registers (or updates) a daily Windows Task Scheduler job that runs
  AI Job Search once every morning and emails the digest.

.USAGE
  Right-click > Run with PowerShell, or from a terminal:
    powershell -ExecutionPolicy Bypass -File .\setup_schedule.ps1
  Optional: choose a time (24h HH:mm) and task name:
    powershell -ExecutionPolicy Bypass -File .\setup_schedule.ps1 -Time "08:30"

  To remove the schedule later:
    schtasks /Delete /TN "AI Job Search Daily" /F
#>

param(
    [string]$Time = "09:00",
    [string]$TaskName = "AI Job Search Daily"
)

$ErrorActionPreference = "Stop"

# Resolve the project directory (where this script lives) and the wrapper.
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Wrapper = Join-Path $ProjectDir "run_job_radar.bat"

if (-not (Test-Path $Wrapper)) {
    Write-Error "run_job_radar.bat not found in $ProjectDir"
    exit 1
}

Write-Host "Project directory : $ProjectDir"
Write-Host "Daily run time    : $Time"
Write-Host "Task name         : $TaskName"

# Build the scheduled task. /RL LIMITED runs as the current user (so it can
# reach your .env and send email). /F overwrites an existing task of the same name.
schtasks /Create `
    /TN "$TaskName" `
    /TR "`"$Wrapper`"" `
    /SC DAILY `
    /ST $Time `
    /RL LIMITED `
    /F

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Scheduled. The digest will be emailed every day at $Time." -ForegroundColor Green
    Write-Host "Test it now with:  schtasks /Run /TN `"$TaskName`""
    Write-Host "Check logs in:     $ProjectDir\logs\job_radar.log"
    Write-Host "Remove it with:    schtasks /Delete /TN `"$TaskName`" /F"
} else {
    Write-Error "Failed to create the scheduled task (exit $LASTEXITCODE)."
}
