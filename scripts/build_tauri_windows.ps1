$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")

if ([System.Environment]::OSVersion.Platform -ne "Win32NT") {
  throw "This script must be run on Windows to build the Tauri .exe/.msi targets."
}

Push-Location $ProjectDir
try {
  if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust/Cargo was not found. Install Rust first: https://www.rust-lang.org/tools/install"
  }
  npm install
  npm run tauri:build
} finally {
  Pop-Location
}

Write-Host "Tauri Windows artifacts are under: $(Join-Path $ProjectDir 'src-tauri\target\release\bundle')"
