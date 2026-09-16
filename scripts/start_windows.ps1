$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".env.local")) {
  Copy-Item ".env.example" ".env.local"
  Write-Host "Created .env.local. Add credentials there before enabling AI/Testnet."
}
$running = @(
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*-m trader *" -and $_.CommandLine.Contains((Join-Path (Get-Location) 'config.toml')) -and $_.CommandLine -match '\brun\s*$' }
)
if ($running.Count -gt 0) {
  Write-Host "Crypto AI Trader is already running."
  exit 0
}
py -3 -m trader --config (Join-Path (Get-Location) 'config.toml') run
