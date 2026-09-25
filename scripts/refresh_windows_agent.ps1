param([Parameter(Mandatory = $true)][string]$SourcePath, [switch]$Automatic)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$source = (Resolve-Path -LiteralPath $SourcePath).Path
$task = Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent' -ErrorAction Stop
if ($task.Actions.Count -ne 1 -or -not $task.Actions[0].WorkingDirectory) {
    throw 'La tarea del agente debe apuntar a un solo supervisor independiente.'
}
$agentRoot = (Resolve-Path -LiteralPath $task.Actions[0].WorkingDirectory).Path
$agentScript = Join-Path $agentRoot 'scripts\windows_agent.py'
if ($agentRoot -eq $source -or -not ($task.Actions[0].Arguments.Contains($agentScript)) -or
    -not ($task.Actions[0].Arguments.Contains($source)) -or
    -not ($task.Actions[0].Arguments.Contains('--autostart'))) {
    throw 'La tarea programada no apunta al bot y agente esperados.'
}
$runner = Join-Path $source 'scripts\refresh_independent_agent.py'
if (-not (Test-Path -LiteralPath $runner)) { throw 'Instala primero el bot firmado que incluye la reparación del agente.' }
$executable = [Environment]::ExpandEnvironmentVariables([string]$task.Actions[0].Execute)
if ($executable -notmatch '(?i)pythonw?\.exe$' -or -not (Test-Path -LiteralPath $executable)) {
    throw 'La tarea debe utilizar el Python existente y verificable del agente.'
}
$python = if ($executable -match '(?i)pythonw\.exe$') {
    Join-Path (Split-Path -Parent $executable) 'python.exe'
} else { $executable }
if (-not (Test-Path -LiteralPath $python)) { throw 'No se encontró python.exe junto al agente.' }

$args = @($runner, '--source', $source, '--agent-root', $agentRoot)
$preview = & $python @args
if ($LASTEXITCODE -ne 0) { throw 'No se pudo comprobar el registro de instalación firmada.' }
$offer = (($preview | Out-String) | ConvertFrom-Json)
if ($offer.status -ne 'refresh_available') { throw 'No se encontró una instalación PAPER firmada y confirmada.' }
if ($offer.changes.Count -eq 0) {
    Write-Output 'El supervisor ya tiene los módulos firmados de la instalación actual.'
    return
}
if (-not $Automatic) {
    $answer = [System.Windows.Forms.MessageBox]::Show(
        "Versión PAPER $($offer.version) verificada.`nSolo se actualizarán los módulos del agente independiente indicados en el paquete firmado. Se guardará una copia anterior y se reiniciará la tarea existente. El motor de trading y sus datos no se detienen.`n`n¿Continuar?",
        'Actualizar conexión del portal',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) { return }
}

# An automatic refresh is covered by the owner's approval of this exact signed
# release. Never wake a deliberately stopped independent agent.
if ((Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent').State -ne 'Running') {
    throw 'El agente está detenido; inicia su tarea antes de sincronizarlo.'
}

$state = Join-Path $agentRoot 'data'
$stopMarker = Join-Path $state 'REMOTE_STOP'
if (Test-Path -LiteralPath $stopMarker) { throw 'El agente ya tiene una orden de parada.' }
Set-Content -LiteralPath $stopMarker -Value 'Stop outbound agent only' -Encoding utf8
$statusFile = Join-Path $state 'remote-status.json'
$previousSuccess = 0
if (Test-Path -LiteralPath $statusFile) {
    try { $previousSuccess = [double]((Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json).last_success) }
    catch { $previousSuccess = 0 }
}
$result = $null
try {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $current = Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent'
        if ($current.State -ne 'Running') { break }
        Start-Sleep -Milliseconds 500
    }
    if ((Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent').State -eq 'Running') {
        throw 'El agente no se detuvo; no se copiaron archivos.'
    }
    $updated = & $python @args --apply
    if ($LASTEXITCODE -ne 0) { throw 'La copia verificada falló; revisa el respaldo del supervisor.' }
    $result = (($updated | Out-String) | ConvertFrom-Json)
    if ($result.status -ne 'refreshed' -and $result.status -ne 'already_current') {
        throw 'El supervisor no confirmó la actualización de los módulos.'
    }
} finally {
    # If the task timed out and is still running, cancel our stop marker instead.
    if ((Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent').State -eq 'Running') {
        Remove-Item -LiteralPath $stopMarker -ErrorAction SilentlyContinue
    } else {
        try { Start-ScheduledTask -TaskName 'Crypto Paper Portal Agent' }
        catch {
            Remove-Item -LiteralPath $stopMarker -ErrorAction SilentlyContinue
            throw
        }
    }
}
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if (Test-Path -LiteralPath $statusFile) {
        try {
            $status = Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json
            if ($status.sync_ok -eq $true -and [double]$status.last_success -gt $previousSuccess) {
                Write-Output "Agente conectado con versión PAPER $($offer.version). Respaldo: $($result.backup)"
                return
            }
        } catch { }
    }
    Start-Sleep -Milliseconds 500
}
Write-Output "Módulos firmados instalados; la conexión HTTPS sigue pendiente. Respaldo: $($result.backup)"
