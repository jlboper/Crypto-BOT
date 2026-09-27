param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [switch]$ForceRestart
)
$ErrorActionPreference = 'Stop'
$taskName = 'Crypto Paper Portal Agent'
$source = (Resolve-Path -LiteralPath $SourcePath).Path
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
$watchdog = Join-Path $source 'scripts\agent_watchdog.ps1'
$runner = Join-Path $source 'scripts\refresh_independent_agent.py'
if (-not (Test-Path -LiteralPath $agentScript) -or -not (Test-Path -LiteralPath $watchdog) -or -not (Test-Path -LiteralPath $runner)) {
    throw 'Faltan componentes firmados de recuperación del agente.'
}
$oldAction = ($currentExecute -match '(?i)pythonw?\.exe$' -and
              $currentArgs.Contains($agentScript) -and $currentArgs.Contains($source) -and
              $currentArgs.Contains('--autostart'))
$newAction = ($currentExecute -match '(?i)powershell\.exe$' -and
              $currentArgs.Contains($watchdog) -and $currentArgs.Contains($source) -and
              $currentArgs.Contains($agentRoot))
if (-not $oldAction -and -not $newAction) {
    throw 'La tarea existente no coincide con un agente conocido; se requiere revisión local.'
}
$pythonw = ''
if ($oldAction) {
    $pythonw = $currentExecute
} elseif ($currentArgs -match '(?i)-PythonPath\s+"([^"]+)"') {
    $pythonw = [Environment]::ExpandEnvironmentVariables($Matches[1])
}
if (-not $pythonw -or -not (Test-Path -LiteralPath $pythonw)) {
    $candidate = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($candidate) { $pythonw = $candidate.Source }
}
if (-not $pythonw -or -not (Test-Path -LiteralPath $pythonw)) { throw 'No se encontró pythonw.exe para el agente.' }
$python = if ($pythonw -match '(?i)pythonw\.exe$') { Join-Path (Split-Path -Parent $pythonw) 'python.exe' } else { $pythonw }
if (-not (Test-Path -LiteralPath $python)) { throw 'No se encontró python.exe para verificar módulos firmados.' }

$previewRaw = & $python $runner --source $source --agent-root $agentRoot
if ($LASTEXITCODE -ne 0) { throw 'No se pudo validar la instalación firmada antes de refrescar el agente.' }
$preview = (($previewRaw | Out-String) | ConvertFrom-Json)
if ($preview.status -ne 'refresh_available') { throw 'El supervisor no encontró una instalación firmada comprometida.' }

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$watchdogArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $watchdog +
                '" -SourcePath "' + $source + '" -AgentRoot "' + $agentRoot +
                '" -PythonPath "' + $pythonw + '"'
$newTaskAction = New-ScheduledTaskAction -Execute $powershell -Argument $watchdogArgs -WorkingDirectory $agentRoot
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable
$taskNeedsUpgrade = -not $newAction

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
    for ($attempt=0; $attempt -lt 240; $attempt++) {
        if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') { break }
        Start-Sleep -Milliseconds 500
    }
    if ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running') {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
        Start-Sleep -Seconds 1
    }
    Write-HealState 'refreshing_modules'
    if ($preview.changes.Count -gt 0) {
        $appliedRaw = & $python $runner --source $source --agent-root $agentRoot --apply
        if ($LASTEXITCODE -ne 0) { throw 'Falló la actualización verificada de módulos del agente.' }
        $result = (($appliedRaw | Out-String) | ConvertFrom-Json)
        if ($result.status -notin @('refreshed','already_current')) { throw 'El refresco del agente no fue confirmado.' }
    } else {
        $result = [PSCustomObject]@{ status='restarted'; backup=$null }
    }
} catch {
    Write-HealState 'failed' $_.Exception.GetType().Name
    throw
} finally {
    Remove-Item -LiteralPath $repairMarker -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stopMarker -ErrorAction SilentlyContinue
}

# Recover connectivity with the already-known task definition first. Task hardening
# must never be allowed to block the outbound channel.
Write-HealState 'starting_agent'
if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') {
    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
}
$connected = $false
$mode = $null
for ($attempt=0; $attempt -lt 120; $attempt++) {
    if (Test-Path -LiteralPath $statusFile) {
        try {
            $status = Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json
            if ($status.sync_ok -eq $true -and [double]$status.last_success -gt $previousSuccess) {
                $connected = $true
                $mode = $status.mode
                break
            }
        } catch { }
    }
    Start-Sleep -Seconds 1
}
if (-not $connected) {
    Write-HealState 'connection_pending'
    [PSCustomObject]@{ status='connection_pending'; version=$preview.version; restart_policy='unchanged';
        agent_refresh=$result.status } | ConvertTo-Json -Compress
    exit 0
}

# Only after the channel is healthy do we harden the next invocation. Failure here
# is non-fatal: the connected refreshed agent remains alive and visible.
$taskUpgrade = 'already_hardened'
try {
    if ($taskNeedsUpgrade) {
        Set-ScheduledTask -TaskName $taskName -Action $newTaskAction -Trigger @($task.Triggers) -Settings $settings | Out-Null
        $taskUpgrade = 'upgraded'
    } else {
        Set-ScheduledTask -TaskName $taskName -Settings $settings | Out-Null
        $taskUpgrade = 'settings_refreshed'
    }
} catch {
    $taskUpgrade = 'pending'
}
Write-HealState 'healthy' $taskUpgrade
[PSCustomObject]@{ status='healthy'; version=$preview.version; mode=$mode;
    restart_policy=if($taskUpgrade -eq 'pending'){'current'}else{999};
    task_upgrade=$taskUpgrade; agent_refresh=$result.status } | ConvertTo-Json -Compress
exit 0
