param(
    [switch]$InstallAgentAutostart,
    [string]$PythonCommand = "py"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

Write-Host "Crypto-BOT portable bootstrap"
Write-Host "Root: $root"

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    if ($PythonCommand -eq "py") { & py -3 @Args } else { & $PythonCommand @Args }
    if ($LASTEXITCODE -ne 0) { throw "Python command failed" }
}

Invoke-Python -c "import sys; assert sys.version_info >= (3,11), sys.version"

if (-not (Test-Path ".venv")) {
    Invoke-Python -m venv ".venv"
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $root ".venv\Scripts\pythonw.exe"

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $venvPython -m pip install -e ".[portal,updates]"
if ($LASTEXITCODE -ne 0) { throw "project install failed" }

foreach ($dir in @("data", "logs", "backup")) {
    New-Item -ItemType Directory -Path (Join-Path $root $dir) -Force | Out-Null
}

if (-not (Test-Path ".env.local")) {
    Copy-Item ".env.example" ".env.local"
    Write-Warning ".env.local created from template. Add secrets locally before enabling AI/Testnet."
} else {
    Write-Host "Existing .env.local preserved."
}

& $venvPython (Join-Path $root "scripts\portability_check.py") --root $root
if ($LASTEXITCODE -ne 0) { throw "Portability preflight failed" }

if ($InstallAgentAutostart) {
    if (-not (Test-Path $venvPythonw)) { throw "pythonw.exe not found in .venv" }
    & (Join-Path $root "scripts\install_agent_autostart.ps1") -PythonPath $venvPythonw -SourcePath $root
}

Write-Host "Bootstrap complete. Review .env.local and restore only the intended persistent state before starting the engine."
