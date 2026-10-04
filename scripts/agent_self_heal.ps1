param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [switch]$ForceRestart
)
$ErrorActionPreference = 'Stop'
$taskName = 'Crypto Paper Portal Agent'
$source = (Resolve-Path -LiteralPath $SourcePath).Path
function Enter-AgentRepairLock([string]$Root) {
    $directory = Join-Path $Root 'data'
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    try { return [System.IO.File]::Open((Join-Path $directory 'agent-repair.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch [System.IO.IOException] {
        if (($_.Exception.GetBaseException().HResult -band 0xffff) -in @(32, 33)) { return $null }
        throw
    }
}
function Test-AgentRepairHeartbeat($Status, [string]$TaskState, [double]$LastSeen) {
    return ($TaskState -eq 'Running' -and $Status.sync_ok -eq $true -and
        [double]$Status.last_success -gt $LastSeen -and
        [string]$Status.error_type -notlike 'SUPERVISOR_UNAVAILABLE:*')
}
$repairLock = Enter-AgentRepairLock $source
if ($null -eq $repairLock) {
    [PSCustomObject]@{ status='repair_in_progress' } | ConvertTo-Json -Compress
    exit 0
}
try {
$statusPath = Join-Path $source 'data\agent-self-heal.json'
function Write-HealState([string]$Phase, [string]$Detail = '') {
    $payload = [PSCustomObject]@{
        phase = $Phase
        detail = $Detail
        at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    } | ConvertTo-Json -Compress
    $tmp = $statusPath + '.tmp'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $statusPath) | Out-Null
    Set-Content -LiteralPath $tmp -Value $payload -Encoding utf8
    Move-Item -LiteralPath $tmp -Destination $statusPath -Force
}
trap {
    try { Write-HealState 'failed' $_.Exception.GetType().Name } catch { }
    exit 1
}
Write-HealState 'starting'
$taskName = 'Crypto Paper Portal Agent'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.State -eq 'Disabled') {
    [PSCustomObject]@{ status='skipped_disabled'; task=$taskName } | ConvertTo-Json -Compress
    exit 0
}
if ($task.Actions.Count -ne 1 -or -not $task.Actions[0].WorkingDirectory) {
    throw 'La tarea del agente no tiene una única carpeta de trabajo verificable.'
}
$agentRoot = (Resolve-Path -LiteralPath $task.Actions[0].WorkingDirectory).Path
if ($agentRoot -eq $source) { throw 'El agente remoto debe permanecer fuera de la instalación de trading.' }
$currentExecute = [Environment]::ExpandEnvironmentVariables([string]$task.Actions[0].Execute)
$currentArgs = [string]$task.Actions[0].Arguments
$agentScript = Join-Path $agentRoot 'scripts\windows_agent.py'
$runner = Join-Path $source 'scripts\refresh_independent_agent.py'
if (-not (Test-Path -LiteralPath $agentScript) -or -not (Test-Path -LiteralPath $runner)) {
    throw 'Faltan componentes firmados de recuperación del agente.'
}

# Accept both the legacy direct-python task and the temporary PowerShell watchdog
# task so existing installations can migrate safely to the final direct-python model.
$directAction = ($currentExecute -match '(?i)pythonw?\.exe$' -and
                 $currentArgs.Contains($agentScript) -and $currentArgs.Contains($source) -and
                 $currentArgs.Contains('--autostart'))
$legacyWatchdogAction = ($currentExecute -match '(?i)powershell\.exe$' -and
                         $currentArgs.Contains('agent_watchdog.ps1') -and
                         $currentArgs.Contains($source) -and $currentArgs.Contains($agentRoot))
if (-not $directAction -and -not $legacyWatchdogAction) {
    throw 'La tarea existente no coincide con un agente conocido; se requiere revisión local.'
}

$pythonw = ''
if ($directAction) {
    $pythonw = $currentExecute
} elseif ($currentArgs -match '(?i)-PythonPath\s+"([^"]+)"') {
    $pythonw = [Environment]::ExpandEnvironmentVariables($Matches[1])
}
if (-not $pythonw -or -not (Test-Path -LiteralPath $pythonw)) {
    throw 'No se encontró el runtime Python ya aprobado para el agente.'
}
$python = if ($pythonw -match '(?i)pythonw\.exe$') { Join-Path (Split-Path -Parent $pythonw) 'python.exe' } else { $pythonw }
if (-not (Test-Path -LiteralPath $python)) { throw 'No se encontró python.exe para verificar módulos firmados.' }

$previewRaw = & $python $runner --source $source --agent-root $agentRoot
if ($LASTEXITCODE -ne 0) { throw 'No se pudo validar la instalación firmada antes de refrescar el agente.' }
$preview = (($previewRaw | Out-String) | ConvertFrom-Json)
if ($preview.status -ne 'refresh_available') { throw 'El supervisor no encontró una instalación firmada comprometida.' }

$directArgs = '"' + $agentScript + '" --source "' + $source + '" --autostart'
$newTaskAction = New-ScheduledTaskAction -Execute $pythonw -Argument $directArgs -WorkingDirectory $agentRoot
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable

$state = Join-Path $agentRoot 'data'
New-Item -ItemType Directory -Force -Path $state | Out-Null
$stopMarker = Join-Path $state 'REMOTE_STOP'
$repairMarker = Join-Path $state 'AUTO_REFRESH_AGENT'
$statusFile = Join-Path $state 'remote-status.json'
$previousSuccess = 0
if (Test-Path -LiteralPath $statusFile) {
    try { $previousSuccess = [double]((Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json).last_success) } catch { }
}

Write-HealState 'stopping_agent'
Set-Content -LiteralPath $repairMarker -Value 'signed self-heal' -Encoding utf8
Set-Content -LiteralPath $stopMarker -Value 'refresh outbound agent only' -Encoding utf8
$result = $null
try {
    if ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running') {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
    }
    # A legacy watchdog may have left pythonw detached from Task Scheduler.
    # The cooperative stop marker lets that process exit without killing an
    # unrelated PID.
    Start-Sleep -Seconds 3

    Write-HealState 'refreshing_modules'
    if ($preview.changes.Count -gt 0) {
        $appliedRaw = & $python $runner --source $source --agent-root $agentRoot --apply
        if ($LASTEXITCODE -ne 0) { throw 'Falló la actualización verificada de módulos del agente.' }
        $result = (($appliedRaw | Out-String) | ConvertFrom-Json)
        if ($result.status -notin @('refreshed','already_current')) { throw 'El refresco del agente no fue confirmado.' }
    } else {
        $result = [PSCustomObject]@{ status='already_current'; backup=$null }
    }

    # Reconfigure while the task is stopped. Rewriting a running task can
    # terminate its PowerShell host and orphan the child agent.
    Write-HealState 'configuring_task'
    Set-ScheduledTask -TaskName $taskName -Action $newTaskAction -Trigger @($task.Triggers) -Settings $settings | Out-Null
} catch {
    Write-HealState 'failed' $_.Exception.GetType().Name
    throw
} finally {
    Remove-Item -LiteralPath $repairMarker -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stopMarker -ErrorAction SilentlyContinue
}

Write-HealState 'starting_agent'
Start-ScheduledTask -TaskName $taskName -ErrorAction Stop

# Require two distinct successful HTTPS heartbeats after the restart and keep
# the task itself Running. One successful sync is not enough to call this healthy.
$successes = 0
$lastSeenSuccess = $previousSuccess
$mode = $null
$lastError = 'NO_SUCCESSFUL_HEARTBEAT'
for ($attempt=0; $attempt -lt 120; $attempt++) {
    $taskState = (Get-ScheduledTask -TaskName $taskName).State
    if (Test-Path -LiteralPath $statusFile) {
        try {
            $status = Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json
            if ([string]$status.error_type -match '^([A-Za-z][A-Za-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*|:[0-9]{3})?)(?::|$)') {
                $lastError = $Matches[1]
            }
            $successAt = [double]$status.last_success
            if (Test-AgentRepairHeartbeat $status $taskState $lastSeenSuccess) {
                $successes++
                $lastSeenSuccess = $successAt
                $mode = $status.mode
                if ($successes -ge 2) { break }
            }
        } catch { }
    }
    Start-Sleep -Seconds 1
}
if ($successes -lt 2 -or (Get-ScheduledTask -TaskName $taskName).State -ne 'Running') {
    Write-HealState 'connection_pending' ('heartbeats=' + $successes)
    [PSCustomObject]@{ status='connection_pending'; version=$preview.version; restart_policy=999;
        heartbeats=$successes; agent_refresh=$result.status; error_type=$lastError } | ConvertTo-Json -Compress
    exit 0
}

Write-HealState 'healthy' 'direct_pythonw'
[PSCustomObject]@{ status='healthy'; version=$preview.version; mode=$mode;
    restart_policy=999; task_upgrade='direct_pythonw'; heartbeats=$successes;
    agent_refresh=$result.status } | ConvertTo-Json -Compress
exit 0
} finally { $repairLock.Dispose() }
