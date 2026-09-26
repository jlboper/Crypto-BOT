param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$AgentRoot,
    [Parameter(Mandatory = $true)][string]$PythonPath
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $SourcePath).Path
$agent = (Resolve-Path -LiteralPath $AgentRoot).Path
$python = (Resolve-Path -LiteralPath $PythonPath).Path
if ($source -eq $agent) { throw 'El watchdog requiere un agente independiente.' }
$agentScript = Join-Path $agent 'scripts\windows_agent.py'
if (-not (Test-Path -LiteralPath $agentScript)) { throw 'Falta windows_agent.py en el supervisor independiente.' }
if ($python -notmatch '(?i)pythonw?\.exe$') { throw 'Runtime Python no válido para el agente.' }
$state = Join-Path $agent 'data'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$stopMarker = Join-Path $state 'REMOTE_STOP'
$repairMarker = Join-Path $state 'AUTO_REFRESH_AGENT'
$delays = @(10, 30, 60, 120, 300)
$failures = 0
while ($true) {
    if (Test-Path -LiteralPath $repairMarker) { exit 0 }
    if (Test-Path -LiteralPath $stopMarker) { exit 0 }
    $arguments = '"' + $agentScript + '" --source "' + $source + '" --autostart'
    try {
        $child = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $agent -WindowStyle Hidden -PassThru
        Wait-Process -Id $child.Id
    } catch { }
    if (Test-Path -LiteralPath $repairMarker) { exit 0 }
    if (Test-Path -LiteralPath $stopMarker) { exit 0 }
    $delay = $delays[[Math]::Min($failures, $delays.Count - 1)]
    $failures = [Math]::Min($failures + 1, $delays.Count - 1)
    Start-Sleep -Seconds $delay
}
