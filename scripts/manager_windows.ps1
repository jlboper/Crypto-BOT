param([switch]$Minimized)

$ErrorActionPreference = "Stop"

function Enter-ManagerInstance([string]$Root, [bool]$ActivateExisting = $true) {
    $canonical = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/').ToUpperInvariant()
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical))).Replace('-', '') }
    finally { $sha.Dispose() }
    $name = 'Local\CryptoAITrader.Manager.' + $digest
    $mutex = [System.Threading.Mutex]::new($false, $name)
    $show = [System.Threading.EventWaitHandle]::new($false, [System.Threading.EventResetMode]::AutoReset, $name + '.Show')
    $owned = $false
    try {
        try { $owned = $mutex.WaitOne(0) }
        catch [System.Threading.AbandonedMutexException] { $owned = $true }
        if (-not $owned) {
            if ($ActivateExisting) { [void]$show.Set() }
            $show.Dispose()
            $mutex.Dispose()
            return $null
        }
        return [PSCustomObject]@{ Mutex=$mutex; Show=$show }
    } catch {
        if ($owned) { $mutex.ReleaseMutex() }
        $show.Dispose()
        $mutex.Dispose()
        throw
    }
}

function Exit-ManagerInstance($Instance) {
    if ($null -ne $Instance) {
        $Instance.Show.Dispose()
        $Instance.Mutex.ReleaseMutex()
        $Instance.Mutex.Dispose()
    }
}

# Claim the indicator before creating any UI, timer, or engine-start callback.
$managerRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$managerInstance = Enter-ManagerInstance -Root $managerRoot -ActivateExisting (-not $Minimized)
if ($null -eq $managerInstance) { exit 0 }
try {
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

Add-Type @"
using System.Runtime.InteropServices;
public static class CryptoAITraderWindowsIdentity {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
}
"@
[CryptoAITraderWindowsIdentity]::SetCurrentProcessExplicitAppUserModelID("JLBoper.CryptoAITrader.ControlCenter") | Out-Null

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DashboardUrl = "http://127.0.0.1:8765"
$RemotePortalUrl = "https://crypto-paper-private-portal.jlboper.workers.dev/"
$KillSwitchPath = Join-Path $ProjectRoot "data\KILL_SWITCH"
$StartupFolder = [Environment]::GetFolderPath("Startup")
$StartupShortcut = Join-Path $StartupFolder "Crypto AI Trader.lnk"
$StartupOptOutPath = Join-Path $ProjectRoot "data\DISABLE_AUTO_START"
$ManagerLauncher = Join-Path $ProjectRoot "Crypto AI Trader.vbs"
$OperationalIconPath = Join-Path $ProjectRoot "web\crypto-ai-trader.ico"
$WarningIconPath = Join-Path $ProjectRoot "web\crypto-ai-trader-warning.ico"
$OfflineIconPath = Join-Path $ProjectRoot "web\crypto-ai-trader-offline.ico"
$HeaderLogoPath = Join-Path $ProjectRoot "web\crypto-ai-trader-icon.png"
$script:RestartManager = $false
$script:AgentRefreshCheckedVersion = ''
$script:AgentRefreshNextAttempt = [DateTime]::MinValue
$script:AgentHealthFailures = 0
$script:AgentRestartNextAttempt = [DateTime]::MinValue
$script:EngineRestartNextAttempt = [DateTime]::MinValue

function Get-InstalledVersion {
    $projectFile = Join-Path $ProjectRoot "pyproject.toml"
    if (-not (Test-Path $projectFile)) { return "desconocida" }
    $match = Select-String -Path $projectFile -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($match) { return $match.Matches[0].Groups[1].Value }
    return "desconocida"
}

function Invoke-LocalSignedUpdate {
    param([string]$Action, [string]$ApprovedRelease = '')
    $task = Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent' -ErrorAction Stop
    if (-not $task.Actions -or -not $task.Actions[0].WorkingDirectory) {
        throw 'Falta la carpeta del supervisor independiente de Windows.'
    }
    $agentRoot = (Resolve-Path -LiteralPath $task.Actions[0].WorkingDirectory).Path
    if ($agentRoot -eq $ProjectRoot) { throw 'La instalación local requiere el supervisor independiente.' }
    $scriptPath = Join-Path $ProjectRoot 'scripts\local_update.py'
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw 'El bot instalado necesita el centro local de actualizaciones actualizado.'
    }
    $taskExecutable = [Environment]::ExpandEnvironmentVariables([string]$task.Actions[0].Execute)
    $taskArguments = [Environment]::ExpandEnvironmentVariables([string]$task.Actions[0].Arguments)
    $python = ''
    if ($taskExecutable -match '(?i)pythonw\.exe$') {
        $python = Join-Path (Split-Path -Parent $taskExecutable) 'python.exe'
    } elseif ($taskExecutable -match '(?i)python\.exe$') {
        $python = $taskExecutable
    } elseif ($taskExecutable -match '(?i)powershell\.exe$') {
        $pythonPathPattern = '(?i)-PythonPath\s+"([^"]+)"'
        if ($taskArguments -match $pythonPathPattern) {
            $pythonw = [Environment]::ExpandEnvironmentVariables($Matches[1])
            if ($pythonw -match '(?i)pythonw\.exe$') {
                $python = Join-Path (Split-Path -Parent $pythonw) 'python.exe'
            } elseif ($pythonw -match '(?i)python\.exe$') {
                $python = $pythonw
            }
        }
    }
    if ($python -and -not (Test-Path -LiteralPath $python)) { $python = '' }
    if (-not $python) {
        throw 'No se encontró el mismo runtime Python verificado que usa el supervisor independiente.'
    }
    $pythonFlags = @()
    $arguments = @($pythonFlags) + @($scriptPath, '--source', $ProjectRoot, '--agent-root', $agentRoot, $Action)
    if ($Action -eq '--install') { $arguments += $ApprovedRelease }
    $result = & $python @arguments 2>&1
    $decoded = $null
    try { $decoded = (($result | Out-String) | ConvertFrom-Json) } catch { }
    if ($LASTEXITCODE -ne 0) {
        $messages = @{
            'SUPERVISOR_DISABLED' = 'El supervisor local no permite instalaciones.'
            'MAINTENANCE_PENDING' = 'Existe una operación de mantenimiento pendiente; el supervisor debe recuperarla antes de instalar.'
            'ENGINE_RUNTIME_STALE' = 'El estado cooperativo del motor no coincide con la instalación actual.'
            'ENGINE_STOPPED' = 'El motor está detenido; debe estar operativo antes de actualizar.'
            'CANDIDATE_EXITED' = 'La versión candidata no logró arrancar; se conservó o restauró la versión anterior.'
            'CANDIDATE_HEALTH_FAILED' = 'La versión candidata no superó la comprobación de salud.'
            'SUPERVISOR_TIMEOUT' = 'El supervisor agotó el tiempo de espera al detener o arrancar el motor.'
            'LOCAL_CHANNEL_MISSING' = 'Falta parte del canal local firmado de actualizaciones.'
            'LOCAL_VALIDATION_FAILED' = 'La validación local del paquete o del estado no fue válida.'
        }
        $code = if ($decoded -and $decoded.code) { [string]$decoded.code } else { 'UNKNOWN_UPDATE_FAILURE' }
        $detail = if ($messages.ContainsKey($code)) { $messages[$code] } else { 'La actualización fue rechazada por el supervisor local.' }
        throw "$code · $detail"
    }
    return $decoded
}

function Show-LocalUpdateCenter {
    $choice = [System.Windows.Forms.MessageBox]::Show(
        "Sí: buscar y verificar una versión firmada por Internet.`nNo: usar un paquete firmado ya descargado, sin conexión.`nCancelar: volver a la app.",
        'Centro de actualizaciones local',
        [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) { return }
    $action = if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) { '--check-online' } else { '--check-offline' }
    $updateButton.Enabled = $false
    try {
        $verified = Invoke-LocalSignedUpdate -Action $action
        if ($verified.status -eq 'up_to_date') {
            [System.Windows.Forms.MessageBox]::Show(
                "Ya estás actualizado. Versión instalada y firma verificada: $($verified.version).",
                'Centro de actualizaciones local',
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
            return
        }
        $confirmation = [System.Windows.Forms.MessageBox]::Show(
            "Paquete firmado verificado: versión $($verified.version).`nIdentificación: $($verified.release_id)`nRevisión: $($verified.commit)`n`n¿Instalar esta versión exacta? El supervisor comprobará el arranque del motor activo y conservará la recuperación automática.",
            'Aprobar versión local exacta',
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($confirmation -ne [System.Windows.Forms.DialogResult]::Yes) { return }
        $result = Invoke-LocalSignedUpdate -Action '--install' -ApprovedRelease $verified.release_id
        if ($result.status -ne 'installed_healthy' -or $result.release_id -ne $verified.release_id) {
            throw 'El supervisor no confirmó la instalación exacta y saludable.'
        }
        $script:AgentRefreshNextAttempt = [DateTime]::MinValue
        Invoke-AutomaticAgentRefresh
        Update-ManagerStatus
        [System.Windows.Forms.MessageBox]::Show(
            "Bot $($result.version) instalado y comprobado. La conexión del portal se sincroniza automáticamente; si su revisión queda pendiente, utiliza Reparar conexión del portal.",
            'Actualización local completada',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show(
            "No se completó la actualización local. $($_.Exception.Message)",
            'Revisar actualización',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
    }
    finally { $updateButton.Enabled = $true }
}

function Get-AgentRepairNotice($Result) {
    switch ($Result.status) {
        'healthy' { return [PSCustomObject]@{ Healthy=$true; Message='Conexión del portal recuperada: dos sincronizaciones HTTPS nuevas confirmadas.' } }
        'repair_in_progress' { return [PSCustomObject]@{ Healthy=$false; Message='Ya hay una reparación en curso. Espera a que termine; no hace falta repetirla.' } }
        'skipped_disabled' { return [PSCustomObject]@{ Healthy=$false; Message='El agente está deshabilitado. La reparación respetó ese estado y no recuperó la conexión.' } }
        'connection_pending' { return [PSCustomObject]@{ Healthy=$false; Message=('El agente fue revisado, pero la conexión sigue pendiente. Diagnóstico: ' + $Result.error_type + '. No se confirmó la sincronización con el portal.') } }
        default { throw 'La reparación no devolvió un resultado reconocido.' }
    }
}

function Show-AgentRefresh {
    $scriptPath = Join-Path $ProjectRoot 'scripts\refresh_windows_agent.ps1'
    try {
        if (-not (Test-Path -LiteralPath $scriptPath)) { throw 'Actualiza el bot antes de reparar la conexión.' }
        $result = & $scriptPath -SourcePath $ProjectRoot -ForceRestart
        $notice = Get-AgentRepairNotice (($result | Out-String) | ConvertFrom-Json)
        $icon = if ($notice.Healthy) { [System.Windows.Forms.MessageBoxIcon]::Information } else { [System.Windows.Forms.MessageBoxIcon]::Warning }
        [System.Windows.Forms.MessageBox]::Show(
            $notice.Message, 'Conexión del portal',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            $icon) | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show(
            "No se completó la revisión del agente. $($_.Exception.Message)", 'Revisar conexión del portal',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
}

function Invoke-AutomaticAgentRefresh {
    $version = Get-InstalledVersion
    if ($version -eq 'desconocida' -or $version -eq $script:AgentRefreshCheckedVersion -or
        [DateTime]::UtcNow -lt $script:AgentRefreshNextAttempt) { return }
    $script:AgentRefreshNextAttempt = [DateTime]::UtcNow.AddMinutes(5)
    try {
        $scriptPath = Join-Path $ProjectRoot 'scripts\refresh_windows_agent.ps1'
        if (-not (Test-Path -LiteralPath $scriptPath)) { throw 'No se encontró la reparación firmada.' }
        # The helper verifies the committed signed inventory, backs up only
        # changed agent modules and restarts only the outbound agent task.
        $result = & $scriptPath -SourcePath $ProjectRoot -Automatic
        $decoded = (($result | Out-String) | ConvertFrom-Json)
        if ($decoded.status -eq 'repair_in_progress') { return }
        $script:AgentRefreshCheckedVersion = $version
        if ($decoded.status -ne 'healthy') {
            $repairAgentItem.Text = 'Revisar conexión del portal'
            return
        }
        $repairAgentItem.Text = 'Reparar conexión del portal'
    } catch {
        # Keep the menu recovery action and retry later. A refresh failure
        # never reverses a healthy bot installation or stops the trading motor.
        $repairAgentItem.Text = 'Revisar conexión del portal'
    }
}

function Invoke-PortalAgentWatchdog {
    # The outbound agent is disposable. Repairing it must never stop or restart
    # the trading engine, alter a ledger, or change credentials.
    try {
        # Never interrupt a signed repair that is replacing modules or waiting
        # for its two successful heartbeats. The OS releases this lock on exit.
        $repairLockPath = Join-Path $ProjectRoot 'data\agent-repair.lock'
        $repairLock = $null
        if (-not (Test-Path -LiteralPath (Split-Path -Parent $repairLockPath))) { return }
        try { $repairLock = [System.IO.File]::Open($repairLockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
        catch [System.IO.IOException] { return }
        try {
        $runtimePath = Join-Path $ProjectRoot 'data\engine-runtime.json'
        if (-not (Test-Path -LiteralPath $runtimePath)) { return }
        $runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
        $engineMode = ([string]$runtime.mode).ToUpperInvariant()
        if ($runtime.phase -ne 'running' -or $engineMode -notin @('PAPER','TESTNET')) { return }

        $task = Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent' -ErrorAction Stop
        if (-not $task.Actions -or -not $task.Actions[0].WorkingDirectory) { return }
        $agentRoot = (Resolve-Path -LiteralPath $task.Actions[0].WorkingDirectory).Path
        if ($agentRoot -eq $ProjectRoot) { return }
        $statusPath = Join-Path $agentRoot 'data\remote-status.json'
        $needsRepair = $false
        if (Test-Path -LiteralPath $statusPath) {
            try {
                $remote = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
                $fresh = ([double]$remote.at) -gt ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 90)
                $reportedMode = ([string]$remote.mode).ToUpperInvariant()
                # A fresh HTTPS/auth failure is connectivity, not stale process state.
                # Repair only when the agent reports the wrong motor mode or stops
                # updating its heartbeat altogether.
                $needsRepair = ($reportedMode -ne $engineMode -or -not $fresh)
                if (-not $needsRepair) {
                    $script:AgentHealthFailures = 0
                    return
                }
            } catch { $needsRepair = $true }
        }
        else { $needsRepair = $true }
        if (-not $needsRepair) { return }
        $script:AgentHealthFailures++
        if ($script:AgentHealthFailures -lt 2 -or [DateTime]::UtcNow -lt $script:AgentRestartNextAttempt) { return }
        $script:AgentRestartNextAttempt = [DateTime]::UtcNow.AddMinutes(2)
        $script:AgentHealthFailures = 0

        if ($task.State -eq 'Running') {
            Stop-ScheduledTask -TaskName 'Crypto Paper Portal Agent' -ErrorAction Stop
            Start-Sleep -Seconds 2
        }
        Start-ScheduledTask -TaskName 'Crypto Paper Portal Agent' -ErrorAction Stop
        $repairAgentItem.Text = 'Reparar conexión del portal'
        } finally { if ($null -ne $repairLock) { $repairLock.Dispose() } }
    } catch {
        # A watchdog failure degrades only remote visibility. Never touch motor state.
        $repairAgentItem.Text = 'Revisar conexión del portal'
    }
}

function Get-TradingProcesses {
    return @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -like "*-m trader *" -and $_.CommandLine.Contains((Join-Path $ProjectRoot 'config.toml')) -and $_.CommandLine -match '\brun\s*$' }
    )
}

function Invoke-TradingEngineWatchdog {
    if (Test-Path (Join-Path $ProjectRoot 'data\UPDATE_MAINTENANCE.json')) { return }
    if (Test-Path $StartupOptOutPath) { return }
    if ((Get-TradingProcesses).Count -gt 0) { return }
    if ([DateTime]::UtcNow -lt $script:EngineRestartNextAttempt) { return }
    $script:EngineRestartNextAttempt = [DateTime]::UtcNow.AddMinutes(1)
    try { Start-TradingBot } catch { }
}

function Start-TradingBot {
    if ((Get-TradingProcesses).Count -gt 0) { return }
    $launcher = (Get-Command py -ErrorAction Stop).Source
    Start-Process `
        -FilePath $launcher `
        -ArgumentList @("-3", "-m", "trader", "--config", ('"' + (Join-Path $ProjectRoot 'config.toml') + '"'), "run") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden
}

function Stop-TradingBot {
    foreach ($process in (Get-TradingProcesses)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-ProjectStartupShortcuts {
    $shell = New-Object -ComObject WScript.Shell
    return @(
        Get-ChildItem -LiteralPath $StartupFolder -Filter "*.lnk" -ErrorAction SilentlyContinue |
            Where-Object {
                try {
                    $shortcut = $shell.CreateShortcut($_.FullName)
                    ($shortcut.TargetPath + " " + $shortcut.Arguments) -like ("*" + $ProjectRoot + "*")
                }
                catch { $false }
            }
    )
}

function Test-CanonicalStartup {
    if (-not (Test-Path $StartupShortcut)) { return $false }
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($StartupShortcut)
        $expectedTarget = Join-Path $env:WINDIR "System32\wscript.exe"
        return (
            $shortcut.TargetPath -eq $expectedTarget -and
            $shortcut.Arguments -like ("*" + $ManagerLauncher + "*") -and
            $shortcut.Arguments -like "*/minimized*"
        )
    }
    catch { return $false }
}

function Enable-AutomaticStartup {
    foreach ($oldShortcut in (Get-ProjectStartupShortcuts)) {
        Remove-Item -LiteralPath $oldShortcut.FullName -Force -ErrorAction SilentlyContinue
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($StartupShortcut)
    $shortcut.TargetPath = Join-Path $env:WINDIR "System32\wscript.exe"
    $shortcut.Arguments = '"' + $ManagerLauncher + '" /minimized'
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.Description = "Inicia Crypto AI Trader y su indicador en segundo plano"
    $shortcut.IconLocation = $OperationalIconPath + ",0"
    $shortcut.Save()
    Remove-Item -LiteralPath $StartupOptOutPath -Force -ErrorAction SilentlyContinue
}

function Disable-AutomaticStartup {
    foreach ($shortcut in (Get-ProjectStartupShortcuts)) {
        Remove-Item -LiteralPath $shortcut.FullName -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path (Split-Path $StartupOptOutPath) -Force | Out-Null
    Set-Content -LiteralPath $StartupOptOutPath -Value "disabled by user"
}

function Show-ManagerWindow {
    $form.ShowInTaskbar = $true
    $form.Show()
    $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
    $form.Activate()
    $form.BringToFront()
}

function Hide-ManagerWindow {
    $form.Hide()
    $form.ShowInTaskbar = $false
}

function New-AppButton {
    param(
        [string]$Text,
        [int]$X,
        [int]$Y,
        [int]$Width = 330,
        [string]$Tone = "Default"
    )
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text
    $button.Location = New-Object System.Drawing.Point($X, $Y)
    $button.Size = New-Object System.Drawing.Size($Width, 46)
    $button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(47, 67, 94)
    $button.FlatAppearance.MouseOverBackColor = [System.Drawing.Color]::FromArgb(29, 46, 72)
    $button.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(12, 24, 42)
    $button.BackColor = [System.Drawing.Color]::FromArgb(20, 33, 54)
    $button.ForeColor = [System.Drawing.Color]::FromArgb(236, 242, 255)
    if ($Tone -eq "Accent") {
        $button.BackColor = [System.Drawing.Color]::FromArgb(14, 52, 48)
        $button.ForeColor = [System.Drawing.Color]::FromArgb(77, 239, 187)
        $button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(37, 112, 94)
    }
    elseif ($Tone -eq "Danger") {
        $button.BackColor = [System.Drawing.Color]::FromArgb(55, 24, 35)
        $button.ForeColor = [System.Drawing.Color]::FromArgb(255, 147, 164)
        $button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(120, 48, 66)
    }
    $button.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $button.Cursor = [System.Windows.Forms.Cursors]::Hand
    return $button
}

function Get-ManagerValue($Value, [string]$Path) {
    foreach ($part in $Path.Split('.')) {
        if ($null -eq $Value) { return $null }
        if ($Value -is [System.Collections.IDictionary]) { $Value = $Value[$part] }
        else {
            $property = $Value.PSObject.Properties[$part]
            if ($null -eq $property) { return $null }
            $Value = $property.Value
        }
    }
    return $Value
}

function Format-ManagerNumber($Value, [string]$Suffix = '') {
    if ($null -eq $Value -or $Value -is [bool]) { return '—' }
    $number = 0.0
    if (-not [double]::TryParse([string]$Value, [Globalization.NumberStyles]::Float,
        [Globalization.CultureInfo]::InvariantCulture, [ref]$number) -or
        [double]::IsNaN($number) -or [double]::IsInfinity($number)) { return '—' }
    return $number.ToString('N2', [Globalization.CultureInfo]::GetCultureInfo('es-MX')) + $Suffix
}

function Get-ManagerAge($Value, [DateTimeOffset]$Now) {
    if ($null -eq $Value) { return $null }
    $stamp = [DateTimeOffset]::MinValue
    if ($Value -is [DateTimeOffset] -or $Value -is [DateTime]) { $stamp = [DateTimeOffset]$Value }
    elseif (-not [DateTimeOffset]::TryParse([string]$Value, [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal, [ref]$stamp)) { return $null }
    $age = ($Now - $stamp).TotalSeconds
    if ($age -lt -5) { return $null }
    return [math]::Max(0, $age)
}

function Format-ManagerTime($Value) {
    $stamp = [DateTimeOffset]::MinValue
    if ($null -eq $Value) { return 'Sin evaluación registrada' }
    if ($Value -is [DateTimeOffset] -or $Value -is [DateTime]) { $stamp = [DateTimeOffset]$Value }
    elseif (-not [DateTimeOffset]::TryParse([string]$Value, [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal, [ref]$stamp)) { return 'Sin evaluación registrada' }
    return $stamp.ToLocalTime().ToString('dd/MM HH:mm:ss')
}

function Get-ManagerArmedCount($Native) {
    $armed = 0
    if ($null -ne $Native) {
        foreach ($item in $Native.PSObject.Properties) { if ($item.Value.status -eq 'ARMED') { $armed++ } }
    }
    return $armed
}

function Get-ManagerProtection($Native, $Positions, [string]$Name) {
    if ($null -eq $Native -or $null -eq $Positions) { return 'Confirmación nativa pendiente' }
    if ($Positions -eq 0) { return 'Sin exposición · verificar al abrir' }
    $armed = Get-ManagerArmedCount $Native
    return "$armed/$Positions $Name confirmados"
}

function Get-ManagerEngineViews($Spot, $Futures, $Pulse, [DateTimeOffset]$Now = [DateTimeOffset]::UtcNow, $Quant = $null) {
    $spotCount = Get-ManagerValue $Spot 'positions'
    $spotState = switch ([string](Get-ManagerValue $Spot 'activity.state')) {
        'operational' { 'OPERATIVO' } 'delayed' { 'RETRASADO' } 'offline' { 'SIN CICLO RECIENTE' } default { 'SIN DATOS' }
    }
    if ((Get-ManagerValue $Spot 'killed') -eq $true) { $spotState = 'ENTRADAS PAUSADAS' }
    $spotNative = Get-ManagerValue $Spot 'native_protection.positions'
    $spotMode = [string](Get-ManagerValue $Spot 'mode')
    $spotPaper = $spotMode.ToUpperInvariant() -eq 'PAPER'
    if (-not $spotPaper -and $spotState -eq 'OPERATIVO' -and $null -ne $spotCount -and [int]$spotCount -gt 0 -and (Get-ManagerArmedCount $spotNative) -lt [int]$spotCount) {
        $spotState = 'PROTECCIÓN PENDIENTE'
    }
    $spotPositions = if ($null -eq $spotCount) { 'Posiciones: —' } else { "Posiciones: $spotCount" }
    $spotView = [PSCustomObject]@{
        State=$spotState; Environment= $(if ($spotMode) { 'Spot ' + $spotMode.ToUpperInvariant() } else { 'Entorno sin confirmar' })
        Capital=('Equity: ' + (Format-ManagerNumber (Get-ManagerValue $Spot 'equity') ' USDT'))
        Return=('Retorno: ' + (Format-ManagerNumber (Get-ManagerValue $Spot 'return_pct') '%'))
        Positions=($spotPositions + "`r`nExposición: " + (Format-ManagerNumber (Get-ManagerValue $Spot 'exposure') ' USDT'))
        Protection=$(if ($spotPaper) { if ($null -ne $spotCount -and [int]$spotCount -eq 0) { 'Sin exposición · stops simulados' } else { 'Stops simulados · PAPER' } } else { Get-ManagerProtection $spotNative $spotCount 'OCO' })
        Latest=(Format-ManagerTime (Get-ManagerValue $Spot 'activity.last_cycle_at'))
        Tone=$(if ($spotState -eq 'OPERATIVO') { 'Green' } elseif ($null -eq $Spot) { 'Muted' } else { 'Amber' })
    }
    $fPositions = @(Get-ManagerValue $Futures 'positions' | Where-Object { $null -ne $_ })
    $fState = 'SIN DATOS'; $fTone = 'Muted'
    if ((Get-ManagerValue $Futures 'enabled') -eq $false) { $fState = 'NO HABILITADO' }
    elseif ((Get-ManagerValue $Futures 'enabled') -eq $true) {
        $fState = 'ESPERANDO SEÑAL'; $fTone = 'Green'
        $fAge = Get-ManagerAge (Get-ManagerValue $Futures 'cycle_diagnostic.at') $Now
        $cycle = Get-ManagerValue $Spot 'cycle_seconds'
        $maxAge = if ($null -ne $cycle -and [double]$cycle -gt 0) { [math]::Max([double]$cycle * 1.5, [double]$cycle + 120) } else { 1350 }
        if ($fPositions.Count -gt 0) { $fState = 'CON POSICIONES' }
        if ($null -eq $fAge -or $fAge -gt $maxAge) { $fState = 'SIN ANÁLISIS RECIENTE'; $fTone = 'Amber' }
        elseif ((Get-ManagerValue $Futures 'cycle_diagnostic.state') -eq 'ATTENTION') { $fState = 'DATOS PARCIALES'; $fTone = 'Amber' }
        if ((Get-ManagerValue $Futures 'killed') -eq $true) { $fState = 'ENTRADAS PAUSADAS'; $fTone = 'Amber' }
    }
    $fEquity = @(Get-ManagerValue $Futures 'equity' | Where-Object { $null -ne $_ })
    $wallet = $null
    if ($fEquity.Count -gt 0) {
        $wallet = Get-ManagerValue $fEquity[-1] 'wallet_balance'
        $unrealized = Get-ManagerValue $fEquity[-1] 'unrealized_pnl'
        if ($null -ne $wallet -and $null -ne $unrealized) { $wallet = [double]$wallet + [double]$unrealized } else { $wallet = $null }
    }
    $longs = @($fPositions | Where-Object { $_.direction -eq 'LONG' }).Count
    $shorts = @($fPositions | Where-Object { $_.direction -eq 'SHORT' }).Count
    $fNative = Get-ManagerValue $Futures 'native_protection.positions'
    if ($fState -in @('CON POSICIONES','ESPERANDO SEÑAL') -and $fPositions.Count -gt 0 -and (Get-ManagerArmedCount $fNative) -lt $fPositions.Count) {
        $fState = 'PROTECCIÓN PENDIENTE'; $fTone = 'Amber'
    }
    $fView = [PSCustomObject]@{
        State=$fState; Environment='Futures DEMO · cuenta separada'; Capital=('Equity: ' + (Format-ManagerNumber $wallet ' USDT'))
        Return=('Retorno: ' + (Format-ManagerNumber (Get-ManagerValue $Futures 'scorecard.account_return_pct') '%'))
        Positions=$(if ($null -eq $Futures -or $null -eq $Futures.PSObject.Properties['positions']) { 'LONG / SHORT: —' } else { "LONG $longs · SHORT $shorts" })
        Protection=(Get-ManagerProtection $fNative $fPositions.Count 'stops')
        Latest=(Format-ManagerTime (Get-ManagerValue $Futures 'cycle_diagnostic.at')); Tone=$fTone
    }
    $pulseState = switch ([string](Get-ManagerValue $Pulse 'state')) {
        'SHADOW' { 'SHADOW ACTIVO' } 'PAUSED' { 'ENTRADAS PAUSADAS' } 'WARMING_UP' { 'ACUMULANDO MUESTRAS' }
        'DEGRADED' { 'DATOS PARCIALES' } 'NOT_STARTED' { 'SIN INICIAR' } default { 'SIN DATOS' }
    }
    $pulseAge = Get-ManagerAge (Get-ManagerValue $Pulse 'updated_at') $Now
    $pulseOld = $null -ne $Pulse -and ($null -eq $pulseAge -or $pulseAge -gt 30 -or (Get-ManagerValue $Pulse 'freshness.state') -eq 'STALE')
    if ($pulseOld -and $pulseState -ne 'SIN INICIAR') { $pulseState += ' · ANTIGUO' }
    $pulsePositions = @(Get-ManagerValue $Pulse 'positions' | Where-Object { $null -ne $_ })
    $pCount = if ($null -eq $Pulse -or $null -eq $Pulse.PSObject.Properties['positions']) { '—' } else { [string]$pulsePositions.Count }
    $pEvents = Get-ManagerValue $Pulse 'stats.events_analyzed'
    $pOpp = Get-ManagerValue $Pulse 'stats.opportunities'
    $pView = [PSCustomObject]@{
        State=$pulseState; Environment='SHADOW · capital hipotético'
        Capital=$(if ($pulseOld) { 'Equity: —' } else { 'Equity: ' + (Format-ManagerNumber (Get-ManagerValue $Pulse 'performance.equity') ' USDT') })
        Return=$(if ($pulseOld) { 'Neto simulado: — · antiguo' } else { 'Neto simulado: ' + (Format-ManagerNumber (Get-ManagerValue $Pulse 'performance.net_pnl') ' USDT') })
        Positions=("Posiciones hipotéticas: $pCount`r`nEventos: $(if ($null -eq $pEvents) {'—'} else {$pEvents}) · oportunidades: $(if ($null -eq $pOpp) {'—'} else {$pOpp})")
        Protection=('Sin órdenes al exchange' + "`r`nWS: " + $(if ($null -eq (Get-ManagerValue $Pulse 'sources.binance_ws.state')) {'sin datos'} else {[string](Get-ManagerValue $Pulse 'sources.binance_ws.state')}))
        Latest=(Format-ManagerTime (Get-ManagerValue $Pulse 'updated_at'))
        Tone=$(if ($pulseState -eq 'SHADOW ACTIVO' -and -not $pulseOld) {'Green'} elseif ($null -eq $Pulse -or $pulseState -eq 'SIN INICIAR') {'Muted'} else {'Amber'})
    }
    # Quant is a contract scaffold in this phase, never an initialized virtual wallet.
    $quantValid = (Get-ManagerValue $Quant 'schema') -eq 1 -and (Get-ManagerValue $Quant 'engine') -eq 'QUANT_ARBITRAGE' -and
        (Get-ManagerValue $Quant 'mode') -eq 'SHADOW' -and (Get-ManagerValue $Quant 'state') -eq 'NOT_STARTED' -and
        (Get-ManagerValue $Quant 'initialized') -eq $false -and (Get-ManagerValue $Quant 'enabled') -eq $false -and
        (Get-ManagerValue $Quant 'execution_enabled') -eq $false -and (Get-ManagerValue $Quant 'controls_available') -eq $false -and
        (Get-ManagerValue $Quant 'promotion_allowed') -eq $false
    $qView = [PSCustomObject]@{
        State=$(if ($quantValid) { 'SIN INICIAR' } else { 'SIN DATOS' }); Environment='SHADOW · investigación pendiente'
        Capital='Capital: —'; Return='Neto simulado: —'; Positions="Funding Carry / StatArb`r`nSin ledger inicializado"
        Protection="Ejecución bloqueada`r`nPromoción bloqueada"; Latest='Sin evaluación registrada'; Tone='Muted'
    }
    return [PSCustomObject]@{ Spot=$spotView; Futures=$fView; Pulse=$pView; Quant=$qView }
}

function Get-ManagerGuardianView($Platform, [DateTimeOffset]$Now = [DateTimeOffset]::UtcNow) {
    $guardian = Get-ManagerValue $Platform 'portfolio_guardian'
    $compatible = (Get-ManagerValue $guardian 'schema') -eq 1 -and (Get-ManagerValue $guardian 'engine') -eq 'PORTFOLIO_GUARDIAN' -and
        (Get-ManagerValue $guardian 'mode') -eq 'OBSERVER' -and (Get-ManagerValue $guardian 'controls_enabled') -eq $false -and
        (Get-ManagerValue $guardian 'can_veto') -eq $false -and (Get-ManagerValue $guardian 'execution_enabled') -eq $false -and
        (Get-ManagerValue $guardian 'state') -in @('OBSERVING','PARTIAL','DEGRADED')
    if (-not $compatible) { return 'Guardian: sin lectura · sin veto' }
    $age = Get-ManagerAge (Get-ManagerValue $guardian 'at') $Now
    if ((Get-ManagerValue $Platform 'remote_sync_stale') -eq $true -or $null -eq $age -or $age -gt 120) {
        return 'Guardian: lectura antigua · sin veto'
    }
    $alerts = @(Get-ManagerValue $guardian 'alerts' | Where-Object { $null -ne $_ }).Count
    $state = switch ([string](Get-ManagerValue $guardian 'state')) {
        'OBSERVING' { 'Observer' } 'PARTIAL' { 'datos parciales' } default { 'sin evidencia actual' }
    }
    return "Guardian: $state · $([math]::Min($alerts,20)) alertas · sin veto"
}

function New-EngineCard {
    param([string]$Title, [int]$X, [int]$Y)
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Location = New-Object System.Drawing.Point($X, $Y)
    $panel.Size = New-Object System.Drawing.Size(338, 144)
    $panel.BackColor = [System.Drawing.Color]::FromArgb(16, 27, 45)
    $card = @{ Panel=$panel }
    foreach ($field in @(@('Title',12,9,155,21,9,'Bold'), @('State',172,12,154,18,7,'Bold'),
        @('Environment',12,34,314,18,8,'Regular'), @('Capital',12,58,156,22,10,'Bold'),
        @('Return',172,60,154,20,8,'Regular'), @('Positions',12,86,156,31,8,'Regular'),
        @('Protection',172,86,154,31,8,'Regular'), @('Latest',12,122,314,17,7,'Regular'))) {
        $label = New-Object System.Windows.Forms.Label
        $label.Text = if ($field[0] -eq 'Title') { $Title } else { '—' }
        $label.Location = New-Object System.Drawing.Point(([int]$field[1]), ([int]$field[2]))
        $label.Size = New-Object System.Drawing.Size(([int]$field[3]), ([int]$field[4]))
        $label.Font = New-Object System.Drawing.Font('Segoe UI', ([single]$field[5]), ([System.Drawing.FontStyle]$field[6]))
        $label.ForeColor = [System.Drawing.Color]::FromArgb(157, 181, 202)
        if ($field[0] -in @('Title','Capital')) { $label.ForeColor = [System.Drawing.Color]::FromArgb(236,242,255) }
        $panel.Controls.Add($label); $card[$field[0]]=$label
    }
    return [PSCustomObject]$card
}

function Set-EngineCard($Card, $View) {
    foreach ($field in @('State','Environment','Capital','Return','Positions','Protection','Latest')) { $Card.$field.Text = [string]$View.$field }
    $Card.State.ForeColor = switch ($View.Tone) {
        'Green' { [System.Drawing.Color]::FromArgb(45,226,166) }
        'Amber' { [System.Drawing.Color]::FromArgb(255,204,102) }
        default { [System.Drawing.Color]::FromArgb(143,160,186) }
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "Crypto AI Trader"
$form.Size = New-Object System.Drawing.Size(760, 770)
$form.MinimumSize = New-Object System.Drawing.Size(760, 770)
$form.MaximumSize = New-Object System.Drawing.Size(760, 770)
$form.AutoScroll = $true
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.BackColor = [System.Drawing.Color]::FromArgb(8, 13, 24)
$form.ForeColor = [System.Drawing.Color]::FromArgb(236, 242, 255)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)
$form.MaximizeBox = $false
$form.ShowIcon = $true

$script:OperationalIcon = if (Test-Path $OperationalIconPath) { New-Object System.Drawing.Icon($OperationalIconPath, 16, 16) } else { [System.Drawing.SystemIcons]::Information }
$script:WarningIcon = if (Test-Path $WarningIconPath) { New-Object System.Drawing.Icon($WarningIconPath, 16, 16) } else { [System.Drawing.SystemIcons]::Warning }
$script:OfflineIcon = if (Test-Path $OfflineIconPath) { New-Object System.Drawing.Icon($OfflineIconPath, 16, 16) } else { [System.Drawing.SystemIcons]::Error }
$script:FormIcon = if (Test-Path $OperationalIconPath) { New-Object System.Drawing.Icon($OperationalIconPath, 32, 32) } else { [System.Drawing.SystemIcons]::Information }
$form.Icon = $script:FormIcon

$logo = New-Object System.Windows.Forms.PictureBox
$logo.Location = New-Object System.Drawing.Point(28, 22)
$logo.Size = New-Object System.Drawing.Size(58, 58)
$logo.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
if (Test-Path $HeaderLogoPath) {
    $temporaryLogo = [System.Drawing.Image]::FromFile($HeaderLogoPath)
    $script:LogoBitmap = New-Object System.Drawing.Bitmap($temporaryLogo)
    $temporaryLogo.Dispose()
}
else {
    $script:LogoBitmap = $script:FormIcon.ToBitmap()
}
$logo.Image = $script:LogoBitmap
$form.Controls.Add($logo)

$title = New-Object System.Windows.Forms.Label
$title.Text = "Crypto AI Trader"
$title.Location = New-Object System.Drawing.Point(100, 20)
$title.Size = New-Object System.Drawing.Size(470, 40)
$title.Font = New-Object System.Drawing.Font("Segoe UI", 22, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(236, 242, 255)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Spot · Futures · Pulse · Quant | Guardian Observer"
$subtitle.Location = New-Object System.Drawing.Point(103, 59)
$subtitle.Size = New-Object System.Drawing.Size(460, 22)
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(132, 153, 184)
$form.Controls.Add($subtitle)

$pulseOpenLink = New-Object System.Windows.Forms.LinkLabel
$pulseOpenLink.Text = 'Inteligencia, Quant y Guardian →'
$pulseOpenLink.Location = New-Object System.Drawing.Point(103, 83)
$pulseOpenLink.Size = New-Object System.Drawing.Size(370, 17)
$pulseOpenLink.Font = New-Object System.Drawing.Font('Segoe UI', 8)
$pulseOpenLink.LinkColor = [System.Drawing.Color]::FromArgb(77,239,187)
$pulseOpenLink.ActiveLinkColor = [System.Drawing.Color]::FromArgb(157,250,220)
$pulseOpenLink.Add_LinkClicked({ Start-Process ($DashboardUrl + '/#portfolio-guardian') })
$form.Controls.Add($pulseOpenLink)

$modeBadge = New-Object System.Windows.Forms.Label
$modeBadge.Text = "3 BOTS"
$modeBadge.Location = New-Object System.Drawing.Point(625, 30)
$modeBadge.Size = New-Object System.Drawing.Size(91, 32)
$modeBadge.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
$modeBadge.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$modeBadge.BackColor = [System.Drawing.Color]::FromArgb(14, 52, 48)
$modeBadge.ForeColor = [System.Drawing.Color]::FromArgb(60, 232, 175)
$form.Controls.Add($modeBadge)

$statusPanel = New-Object System.Windows.Forms.Panel
$statusPanel.Location = New-Object System.Drawing.Point(28, 102)
$statusPanel.Size = New-Object System.Drawing.Size(688, 92)
$statusPanel.BackColor = [System.Drawing.Color]::FromArgb(14, 38, 42)
$form.Controls.Add($statusPanel)

$statusDot = New-Object System.Windows.Forms.Label
$statusDot.Text = "●"
$statusDot.Location = New-Object System.Drawing.Point(20, 17)
$statusDot.Size = New-Object System.Drawing.Size(24, 27)
$statusDot.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$statusDot.ForeColor = [System.Drawing.Color]::FromArgb(45, 226, 166)
$statusPanel.Controls.Add($statusDot)

$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = "Comprobando..."
$statusLabel.Location = New-Object System.Drawing.Point(51, 15)
$statusLabel.Size = New-Object System.Drawing.Size(390, 29)
$statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$statusPanel.Controls.Add($statusLabel)

$statusDescription = New-Object System.Windows.Forms.Label
$statusDescription.Text = "Validando el motor y el portal..."
$statusDescription.Location = New-Object System.Drawing.Point(53, 50)
$statusDescription.Size = New-Object System.Drawing.Size(390, 34)
$statusDescription.ForeColor = [System.Drawing.Color]::FromArgb(157, 181, 202)
$statusPanel.Controls.Add($statusDescription)

$lastCycleLabel = New-Object System.Windows.Forms.Label
$lastCycleLabel.Text = "ÚLTIMO CICLO`r`nComprobando..."
$lastCycleLabel.Location = New-Object System.Drawing.Point(469, 19)
$lastCycleLabel.Size = New-Object System.Drawing.Size(197, 52)
$lastCycleLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$lastCycleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$lastCycleLabel.ForeColor = [System.Drawing.Color]::FromArgb(139, 169, 190)
$statusPanel.Controls.Add($lastCycleLabel)

$spotCard = New-EngineCard "SPOT BOT" 28 202
$futuresCard = New-EngineCard "FUTURES BOT" 378 202
$pulseCard = New-EngineCard "AI MARKET PULSE" 28 354
$quantCard = New-EngineCard "QUANT ARBITRAGE" 378 354
foreach ($card in @($spotCard, $futuresCard, $pulseCard, $quantCard)) {
    $form.Controls.Add($card.Panel)
}

$actionsLabel = New-Object System.Windows.Forms.Label
$actionsLabel.Text = "ACCIONES RÁPIDAS"
$actionsLabel.Location = New-Object System.Drawing.Point(29, 506)
$actionsLabel.Size = New-Object System.Drawing.Size(250, 22)
$actionsLabel.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 9)
$actionsLabel.ForeColor = [System.Drawing.Color]::FromArgb(113, 139, 176)
$form.Controls.Add($actionsLabel)

$openLocalButton = New-AppButton "⌂   Portal local · cuatro bots" 28 530
$openLocalButton.Add_Click({ Start-Process $DashboardUrl })
$form.Controls.Add($openLocalButton)

$openRemoteButton = New-AppButton "↗   Portal remoto / móvil" 386 530
$openRemoteButton.Add_Click({ Start-Process -FilePath $RemotePortalUrl })
$form.Controls.Add($openRemoteButton)

$restartButton = New-AppButton "↻   Reiniciar motor supervisado" 28 580
$restartButton.Add_Click({
    $answer = [System.Windows.Forms.MessageBox]::Show(
        "¿Quieres reiniciar el motor ahora? El portal dejará de responder durante unos segundos.",
        "Confirmar reinicio",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
        Stop-TradingBot
        Start-Sleep -Seconds 2
        Start-TradingBot
        Start-Sleep -Seconds 3
        Update-ManagerStatus
    }
})
$form.Controls.Add($restartButton)

$killButton = New-AppButton "⚠   Pausar entradas Spot" 386 580 330 "Danger"
$killButton.Add_Click({
    if (Test-Path $KillSwitchPath) {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            "¿Reanudar la evaluación de nuevas operaciones?",
            "Confirmar reanudación",
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )
        if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
            Remove-Item -LiteralPath $KillSwitchPath -Force
        }
    }
    else {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            "Esto bloqueará nuevas entradas. Las posiciones existentes seguirán protegidas. ¿Continuar?",
            "Activar kill switch",
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
            New-Item -ItemType Directory -Path (Split-Path $KillSwitchPath) -Force | Out-Null
            Set-Content -LiteralPath $KillSwitchPath -Value "manual kill switch from manager"
        }
    }
    Update-ManagerStatus
})
$form.Controls.Add($killButton)

$updateButton = New-AppButton "↻   Actualización firmada local" 28 630 330 "Accent"
$updateButton.Add_Click({ Show-LocalUpdateCenter })
$form.Controls.Add($updateButton)

$startupButton = New-AppButton "⚙   Activar inicio automático" 386 630
$startupButton.Add_Click({
    if (Test-CanonicalStartup) {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            "¿Desactivar el inicio automático del bot y su indicador?",
            "Inicio automático",
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Question
        )
        if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
            Disable-AutomaticStartup
        }
    }
    else {
        Enable-AutomaticStartup
        [System.Windows.Forms.MessageBox]::Show(
            "El bot arrancará oculto después de iniciar sesión en Windows. El indicador quedará en el área de notificaciones.",
            "Inicio automático activado",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
    Update-ManagerStatus
})
$form.Controls.Add($startupButton)

$footerPanel = New-Object System.Windows.Forms.Panel
$footerPanel.Location = New-Object System.Drawing.Point(28, 686)
$footerPanel.Size = New-Object System.Drawing.Size(688, 42)
$footerPanel.BackColor = [System.Drawing.Color]::FromArgb(11, 20, 34)
$form.Controls.Add($footerPanel)

$protectionLabel = New-Object System.Windows.Forms.Label
$protectionLabel.Text = "Entornos separados · Pulse Shadow · Quant sin iniciar"
$protectionLabel.Location = New-Object System.Drawing.Point(16, 5)
$protectionLabel.Size = New-Object System.Drawing.Size(490, 17)
$protectionLabel.Font = New-Object System.Drawing.Font('Segoe UI', 8)
$protectionLabel.ForeColor = [System.Drawing.Color]::FromArgb(92, 215, 171)
$footerPanel.Controls.Add($protectionLabel)

$footerHint = New-Object System.Windows.Forms.Label
$footerHint.Text = "Guardian: esperando lectura · sin veto"
$footerHint.Location = New-Object System.Drawing.Point(17, 23)
$footerHint.Size = New-Object System.Drawing.Size(490, 16)
$footerHint.Font = New-Object System.Drawing.Font("Segoe UI", 8)
$footerHint.ForeColor = [System.Drawing.Color]::FromArgb(104, 128, 158)
$footerPanel.Controls.Add($footerHint)

$versionLabel = New-Object System.Windows.Forms.Label
$versionLabel.Text = "VERSIÓN " + (Get-InstalledVersion)
$versionLabel.Location = New-Object System.Drawing.Point(520, 8)
$versionLabel.Size = New-Object System.Drawing.Size(148, 24)
$versionLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$versionLabel.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 8)
$versionLabel.ForeColor = [System.Drawing.Color]::FromArgb(113, 139, 176)
$footerPanel.Controls.Add($versionLabel)

# Read-only HTTP polling uses .NET tasks, not a second PowerShell or trading process.
Add-Type -AssemblyName System.Net.Http
$script:ManagerHttp = New-Object System.Net.Http.HttpClient
$script:ManagerHttp.Timeout = [TimeSpan]::FromSeconds(3)
$script:ManagerHttp.MaxResponseContentBufferSize = 262144
$script:ManagerRequests = $null

function Get-ManagerRemoteView($Remote, [DateTimeOffset]$Now = [DateTimeOffset]::UtcNow) {
    $last = Get-ManagerValue $Remote 'last_success'
    $fresh = $null -ne $last -and [double]$last -ge ($Now.ToUnixTimeSeconds() - 90) -and [double]$last -le ($Now.ToUnixTimeSeconds() + 5)
    if ($fresh -and (Get-ManagerValue $Remote 'sync_ok') -eq $true -and -not (Get-ManagerValue $Remote 'error_type')) { return 'HTTPS remoto reciente' }
    if ($null -eq $Remote) { return 'HTTPS remoto sin evidencia disponible' }
    return 'HTTPS remoto pendiente / antiguo; motores independientes'
}

function Read-ManagerRemoteConnection {
    try {
        $task = Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent' -ErrorAction Stop
        $agentRoot = [string]$task.Actions[0].WorkingDirectory
        if (-not $agentRoot) { return (Get-ManagerRemoteView $null) }
        $remotePath = Join-Path $agentRoot 'data\remote-status.json'
        if (-not (Test-Path -LiteralPath $remotePath)) { return (Get-ManagerRemoteView $null) }
        $remote = Get-Content -LiteralPath $remotePath -Raw | ConvertFrom-Json
        return (Get-ManagerRemoteView $remote)
    } catch { return (Get-ManagerRemoteView $null) }
}

function Update-ManagerStatus {
    if ($null -ne $script:ManagerRequests) { return }
    $script:ManagerRequests = @{}
    foreach ($route in @(@('Spot','/api/status'), @('Futures','/api/futures-forward'), @('Pulse','/api/market-pulse'), @('Platform','/api/platform'))) {
        $script:ManagerRequests[$route[0]] = $script:ManagerHttp.GetAsync($DashboardUrl + $route[1])
    }
}

function Receive-ManagerStatus {
    if ($null -eq $script:ManagerRequests) { return }
    foreach ($request in $script:ManagerRequests.Values) { if (-not $request.IsCompleted) { return } }
    $snapshots = @{ Spot=$null; Futures=$null; Pulse=$null; Platform=$null }
    foreach ($name in @('Spot','Futures','Pulse','Platform')) {
        $response = $null
        try {
            $response = $script:ManagerRequests[$name].GetAwaiter().GetResult()
            if ($response.IsSuccessStatusCode) {
                $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                if ($payload.Length -le 262144) { $snapshots[$name] = $payload | ConvertFrom-Json }
            }
        } catch { } finally { if ($null -ne $response) { $response.Dispose() } }
    }
    $script:ManagerRequests = $null
    $views = Get-ManagerEngineViews $snapshots.Spot $snapshots.Futures $snapshots.Pulse -Quant (Get-ManagerValue $snapshots.Platform 'quant')
    Set-EngineCard $spotCard $views.Spot
    Set-EngineCard $futuresCard $views.Futures
    Set-EngineCard $pulseCard $views.Pulse
    Set-EngineCard $quantCard $views.Quant
    $footerHint.Text = Get-ManagerGuardianView $snapshots.Platform
    $remoteText = Read-ManagerRemoteConnection
    $connected = $null -ne $snapshots.Spot
    $statusLabel.Text = if ($connected) { 'Lectura local disponible' } else { 'Lectura local no disponible' }
    $statusDescription.Text = if ($connected) { "$remoteText. Entornos separados." } else { 'Sin respuesta local; esto no confirma que el motor esté detenido.' }
    $color = if ($connected -and $views.Spot.Tone -eq 'Green' -and $views.Futures.Tone -ne 'Amber' -and $views.Pulse.Tone -ne 'Amber') {
        [System.Drawing.Color]::FromArgb(45,226,166)
    } else { [System.Drawing.Color]::FromArgb(255,204,102) }
    $statusLabel.ForeColor = $color; $statusDot.ForeColor = $color
    $statusPanel.BackColor = if ($connected) { [System.Drawing.Color]::FromArgb(14,38,42) } else { [System.Drawing.Color]::FromArgb(44,37,24) }
    $lastCycleLabel.Text = "LECTURA DEL PANEL`r`n$([DateTime]::Now.ToString('dd/MM HH:mm:ss'))"
    if ($connected -and $views.Spot.Tone -eq 'Green') { $notifyIcon.Icon = $script:OperationalIcon }
    else { $notifyIcon.Icon = $script:WarningIcon }
    $trayStatusItem.Text = "Spot: $($views.Spot.State) | Futures: $($views.Futures.State)"
    $trayPulseStatusItem.Text = "Pulse: $($views.Pulse.State) | Quant: $($views.Quant.State)"
    $trayGuardianStatusItem.Text = Get-ManagerGuardianView $snapshots.Platform
    $trayStatusItem.ForeColor = $color
    $tip = "Crypto AI Trader | 4 bots | Pulse $($views.Pulse.State)"
    $notifyIcon.Text = $tip.Substring(0, [math]::Min(63, $tip.Length))
    if (Test-Path $KillSwitchPath) {
        $killButton.Text = '▶   Reanudar entradas Spot'
        $killButton.BackColor = [System.Drawing.Color]::FromArgb(14,52,48)
        $killButton.ForeColor = [System.Drawing.Color]::FromArgb(77,239,187)
        $protectionLabel.Text = 'Spot: entradas pausadas · protecciones independientes'
        $protectionLabel.ForeColor = [System.Drawing.Color]::FromArgb(255,204,102)
    } else {
        $killButton.Text = '⚠   Pausar entradas Spot'
        $killButton.BackColor = [System.Drawing.Color]::FromArgb(55,24,35)
        $killButton.ForeColor = [System.Drawing.Color]::FromArgb(255,147,164)
        $protectionLabel.Text = 'Ledgers separados · Pulse Shadow · Quant sin iniciar'
        $protectionLabel.ForeColor = [System.Drawing.Color]::FromArgb(92,215,171)
    }
    if (Test-CanonicalStartup) { $startupButton.Text = '✓   Inicio automático activado' }
    elseif ((Get-ProjectStartupShortcuts).Count -gt 0) { $startupButton.Text = '⚙   Actualizar inicio automático' }
    else { $startupButton.Text = '⚙   Activar inicio automático' }
    $versionLabel.Text = 'VERSIÓN ' + (Get-InstalledVersion)
}

$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Icon = $script:WarningIcon
$notifyIcon.Text = "Crypto AI Trader - comprobando"
$notifyIcon.Visible = $true

$notifyMenu = New-Object System.Windows.Forms.ContextMenuStrip
$notifyMenu.BackColor = [System.Drawing.Color]::FromArgb(16, 27, 45)
$notifyMenu.ForeColor = [System.Drawing.Color]::FromArgb(236, 242, 255)
$notifyMenu.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$notifyMenu.ShowImageMargin = $true
$trayStatusItem = $notifyMenu.Items.Add("● Comprobando estado")
$trayStatusItem.Enabled = $false
$trayStatusItem.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
$trayPulseStatusItem = $notifyMenu.Items.Add('Market Pulse: comprobando Shadow')
$trayPulseStatusItem.Enabled = $false
$trayGuardianStatusItem = $notifyMenu.Items.Add('Guardian: comprobando Observer')
$trayGuardianStatusItem.Enabled = $false
$notifyMenu.Items.Add("-") | Out-Null
$showManagerItem = $notifyMenu.Items.Add("Abrir centro de control")
$script:MenuBitmap = $script:OperationalIcon.ToBitmap()
$showManagerItem.Image = $script:MenuBitmap
$showManagerItem.Add_Click({
    Show-ManagerWindow
})
$openPortalItem = $notifyMenu.Items.Add("Abrir portal remoto")
$openPortalItem.Add_Click({ Start-Process -FilePath $RemotePortalUrl })
$openPulseItem = $notifyMenu.Items.Add('AI Market Pulse · Shadow')
$openPulseItem.Add_Click({ Start-Process ($RemotePortalUrl + '#market-pulse') })
$openQuantItem = $notifyMenu.Items.Add('Quant Arbitrage · sin iniciar')
$openQuantItem.Add_Click({ Start-Process ($RemotePortalUrl + '#quant-arbitrage') })
$openGuardianItem = $notifyMenu.Items.Add('Portfolio Guardian · Observer')
$openGuardianItem.Add_Click({ Start-Process ($RemotePortalUrl + '#portfolio-guardian') })
$checkUpdatesItem = $notifyMenu.Items.Add("Centro de actualizaciones")
$checkUpdatesItem.Add_Click({ Show-LocalUpdateCenter })
$repairAgentItem = $notifyMenu.Items.Add("Reparar conexión del portal")
$repairAgentItem.Add_Click({ Show-AgentRefresh })
$notifyMenu.Items.Add("-") | Out-Null
$exitItem = $notifyMenu.Items.Add("Salir del indicador")
$script:AllowExit = $false
$exitItem.Add_Click({
    $script:AllowExit = $true
    $form.Close()
})
$notifyIcon.ContextMenuStrip = $notifyMenu
$notifyIcon.Add_DoubleClick({
    Show-ManagerWindow
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 15000
$timer.Add_Tick({
    Update-ManagerStatus
    Invoke-AutomaticAgentRefresh
    Invoke-PortalAgentWatchdog
    Invoke-TradingEngineWatchdog
})
$activationTimer = New-Object System.Windows.Forms.Timer
$activationTimer.Interval = 300
$activationTimer.Add_Tick({ if ($managerInstance.Show.WaitOne(0)) { Show-ManagerWindow } })
$statusPollTimer = New-Object System.Windows.Forms.Timer
$statusPollTimer.Interval = 250
$statusPollTimer.Add_Tick({ Receive-ManagerStatus })
$form.Add_Shown({
    if (-not (Test-Path $StartupOptOutPath) -and -not (Test-CanonicalStartup)) {
        Enable-AutomaticStartup
    }
    if ($Minimized) {
        Start-TradingBot
    }
    Update-ManagerStatus
    $timer.Start()
    $activationTimer.Start()
    $statusPollTimer.Start()
    Invoke-AutomaticAgentRefresh
    Invoke-PortalAgentWatchdog
    if ($Minimized) { Hide-ManagerWindow }
})
$form.Add_Resize({
    if ($form.WindowState -eq [System.Windows.Forms.FormWindowState]::Minimized) {
        Hide-ManagerWindow
    }
})
$form.Add_FormClosing({
    param($sender, $eventArgs)
    if (
        -not $script:AllowExit -and
        $eventArgs.CloseReason -eq [System.Windows.Forms.CloseReason]::UserClosing
    ) {
        $eventArgs.Cancel = $true
        Hide-ManagerWindow
        $notifyIcon.ShowBalloonTip(
            2500,
            "Crypto AI Trader",
            "El indicador continuará funcionando en segundo plano.",
            [System.Windows.Forms.ToolTipIcon]::Info
        )
    }
})
$form.Add_FormClosed({
    $timer.Stop()
    $activationTimer.Stop()
    $activationTimer.Dispose()
    $statusPollTimer.Stop()
    $statusPollTimer.Dispose()
    $script:ManagerHttp.Dispose()
    $notifyIcon.Visible = $false
    $notifyIcon.Dispose()
    $script:LogoBitmap.Dispose()
    $script:MenuBitmap.Dispose()
    if ($script:RestartManager) {
        Start-Process -FilePath "wscript.exe" -ArgumentList ('"' + $ManagerLauncher + '"')
    }
})

[System.Windows.Forms.Application]::Run($form)
} finally { Exit-ManagerInstance $managerInstance }
