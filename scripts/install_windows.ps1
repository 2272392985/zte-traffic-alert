$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$ConfigPath = Join-Path $ProjectDir "config.json"
$TaskName = "ZTE Traffic Alert"

if (-not (Test-Path $ConfigPath)) {
  throw "Missing config.json. Copy config.example.json to config.json first."
}

$Python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Python) {
  $Python = (Get-Command py -ErrorAction SilentlyContinue)
}
if (-not $Python) {
  throw "Python was not found in PATH."
}

$PythonExe = $Python.Source
$Argument = "-m zte_traffic_alert --config `"$ConfigPath`" run"
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $Argument -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Config: $ConfigPath"
Write-Host "Log: $(Join-Path $ProjectDir 'zte_traffic_alert.log')"

