param([string]$PythonPath = '', [string]$SourcePath = '')
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) {
    $portalCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($portalCommand) { $PythonPath = $portalCommand.Source }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) { throw 'Pass -PythonPath with the reviewed Python runtime' }
$portalRoot = Split-Path $PSScriptRoot -Parent
$portalSource = if ($SourcePath) { (Resolve-Path -LiteralPath $SourcePath).Path } else { $portalRoot }
$portalState = Join-Path $portalRoot 'data'
$portalStatus = Join-Path $portalState 'remote-status.json'
if (Test-Path -LiteralPath $portalStatus) {
    $portalPrevious = Get-Content -LiteralPath $portalStatus -Raw | ConvertFrom-Json
    if (Get-Process -Id $portalPrevious.pid -ErrorAction SilentlyContinue) {
        throw 'A process with the recorded agent PID is still running. Check it before restarting.'
    }
}
& $PythonPath (Join-Path $PSScriptRoot 'windows_agent.py') --source $portalSource --check
if ($LASTEXITCODE -ne 0) { throw 'PAPER preflight failed' }
New-Item -ItemType Directory -Path $portalState -Force | Out-Null
$portalStop = Join-Path $portalState 'REMOTE_STOP'
if (Test-Path -LiteralPath $portalStop) { Remove-Item -LiteralPath $portalStop }
$portalArguments = '"' + (Join-Path $PSScriptRoot 'windows_agent.py') + '" --source "' + $portalSource + '"'
$portalProcess = Start-Process -FilePath $PythonPath -ArgumentList $portalArguments -WorkingDirectory $portalRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $portalState 'remote-agent.out.log') -RedirectStandardError (Join-Path $portalState 'remote-agent.err.log')
Write-Output ('Remote agent PID: ' + $portalProcess.Id + '. Trading engine was not started.')
