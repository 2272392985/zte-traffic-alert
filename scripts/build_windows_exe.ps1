$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvDir = Join-Path $ProjectDir ".venv-build"
$AppName = "ZTE Traffic Alert"

if ([System.Environment]::OSVersion.Platform -ne "Win32NT") {
  throw "This script must be run on Windows to build a .exe file."
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
  $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
  throw "Python was not found in PATH."
}

if (-not (Test-Path $VenvDir)) {
  & $Python.Source -m venv $VenvDir
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$PyInstaller = Join-Path $VenvDir "Scripts\pyinstaller.exe"

& $VenvPython -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
  $ExtraArgs = @()
  if ($env:PIP_EXTRA_ARGS) {
    $ExtraArgs = $env:PIP_EXTRA_ARGS.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
  }
  & $VenvPython -m pip install @ExtraArgs --upgrade pip pyinstaller
}

Push-Location $ProjectDir
try {
  & $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name $AppName `
    --add-data "config.example.json;." `
    zte_traffic_alert_gui.py
} finally {
  Pop-Location
}

Write-Host "Built: $(Join-Path $ProjectDir "dist\$AppName.exe")"
