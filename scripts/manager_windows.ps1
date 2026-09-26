param([switch]$Minimized)

$ErrorActionPreference = "Stop"
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
    $python = if ($taskExecutable -match '(?i)pythonw\.exe$') {
        Join-Path (Split-Path -Parent $taskExecutable) 'python.exe'
    } elseif ($taskExecutable -match '(?i)python\.exe$') { $taskExecutable } else { '' }
    if ($python -and -not (Test-Path -LiteralPath $python)) { $python = '' }
    if (-not $python) {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) { $python = $launcher.Source; $pythonFlags = @('-3') }
        else { $python = (Get-Command python.exe -ErrorAction Stop).Source; $pythonFlags = @() }
    } else { $pythonFlags = @() }
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

function Show-AgentRefresh {
    $scriptPath = Join-Path $ProjectRoot 'scripts\refresh_windows_agent.ps1'
    try {
        if (-not (Test-Path -LiteralPath $scriptPath)) { throw 'Actualiza el bot antes de reparar la conexión.' }
        $result = & $scriptPath -SourcePath $ProjectRoot -ForceRestart
        [System.Windows.Forms.MessageBox]::Show(
            ($result | Out-String), 'Conexión del portal',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
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
        $script:AgentRefreshCheckedVersion = $version
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

function New-KpiCard {
    param([string]$Title, [int]$X, [int]$Y)
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Location = New-Object System.Drawing.Point($X, $Y)
    $panel.Size = New-Object System.Drawing.Size(166, 106)
    $panel.BackColor = [System.Drawing.Color]::FromArgb(16, 27, 45)

    $titleLabel = New-Object System.Windows.Forms.Label
    $titleLabel.Text = $Title.ToUpperInvariant()
    $titleLabel.Location = New-Object System.Drawing.Point(14, 12)
    $titleLabel.Size = New-Object System.Drawing.Size(138, 18)
    $titleLabel.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 8)
    $titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(124, 151, 188)
    $panel.Controls.Add($titleLabel)

    $valueLabel = New-Object System.Windows.Forms.Label
    $valueLabel.Text = "—"
    $valueLabel.Location = New-Object System.Drawing.Point(13, 36)
    $valueLabel.Size = New-Object System.Drawing.Size(143, 31)
    $valueLabel.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
    $valueLabel.ForeColor = [System.Drawing.Color]::FromArgb(240, 246, 255)
    $panel.Controls.Add($valueLabel)

    $noteLabel = New-Object System.Windows.Forms.Label
    $noteLabel.Text = "Comprobando"
    $noteLabel.Location = New-Object System.Drawing.Point(14, 76)
    $noteLabel.Size = New-Object System.Drawing.Size(138, 18)
    $noteLabel.Font = New-Object System.Drawing.Font("Segoe UI", 8)
    $noteLabel.ForeColor = [System.Drawing.Color]::FromArgb(116, 139, 171)
    $panel.Controls.Add($noteLabel)

    return [PSCustomObject]@{ Panel = $panel; Value = $valueLabel; Note = $noteLabel }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "Crypto AI Trader"
$form.Size = New-Object System.Drawing.Size(760, 680)
$form.MinimumSize = New-Object System.Drawing.Size(760, 680)
$form.MaximumSize = New-Object System.Drawing.Size(760, 680)
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
$subtitle.Text = "Centro de control local y monitor de inversión"
$subtitle.Location = New-Object System.Drawing.Point(103, 59)
$subtitle.Size = New-Object System.Drawing.Size(460, 22)
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(132, 153, 184)
$form.Controls.Add($subtitle)

$modeBadge = New-Object System.Windows.Forms.Label
$modeBadge.Text = "..."
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
$statusDescription.Size = New-Object System.Drawing.Size(390, 22)
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

$equityCard = New-KpiCard "Equity" 28 210
$returnCard = New-KpiCard "Rendimiento" 202 210
$cashCard = New-KpiCard "Efectivo" 376 210
$exposureCard = New-KpiCard "Exposición" 550 210
foreach ($card in @($equityCard, $returnCard, $cashCard, $exposureCard)) {
    $form.Controls.Add($card.Panel)
}

$actionsLabel = New-Object System.Windows.Forms.Label
$actionsLabel.Text = "ACCIONES RÁPIDAS"
$actionsLabel.Location = New-Object System.Drawing.Point(29, 335)
$actionsLabel.Size = New-Object System.Drawing.Size(250, 22)
$actionsLabel.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 9)
$actionsLabel.ForeColor = [System.Drawing.Color]::FromArgb(113, 139, 176)
$form.Controls.Add($actionsLabel)

$openLocalButton = New-AppButton "⌂   Abrir portal local" 28 365
$openLocalButton.Add_Click({ Start-Process $DashboardUrl })
$form.Controls.Add($openLocalButton)

$openRemoteButton = New-AppButton "↗   Abrir portal remoto" 386 365
$openRemoteButton.Add_Click({ Start-Process -FilePath $RemotePortalUrl })
$form.Controls.Add($openRemoteButton)

$restartButton = New-AppButton "↻   Reiniciar motor" 28 421
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

$killButton = New-AppButton "⚠   Activar kill switch" 386 421 330 "Danger"
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

$updateButton = New-AppButton "↻   Actualizar bot desde esta PC" 28 477 330 "Accent"
$updateButton.Add_Click({ Show-LocalUpdateCenter })
$form.Controls.Add($updateButton)

$startupButton = New-AppButton "⚙   Activar inicio automático" 386 477
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
$footerPanel.Location = New-Object System.Drawing.Point(28, 546)
$footerPanel.Size = New-Object System.Drawing.Size(688, 66)
$footerPanel.BackColor = [System.Drawing.Color]::FromArgb(11, 20, 34)
$form.Controls.Add($footerPanel)

$protectionLabel = New-Object System.Windows.Forms.Label
$protectionLabel.Text = "✓  Protecciones activas  ·  Simulación sin dinero real"
$protectionLabel.Location = New-Object System.Drawing.Point(16, 12)
$protectionLabel.Size = New-Object System.Drawing.Size(470, 22)
$protectionLabel.ForeColor = [System.Drawing.Color]::FromArgb(92, 215, 171)
$footerPanel.Controls.Add($protectionLabel)

$footerHint = New-Object System.Windows.Forms.Label
$footerHint.Text = "Al cerrar, el indicador continúa junto al reloj de Windows."
$footerHint.Location = New-Object System.Drawing.Point(17, 36)
$footerHint.Size = New-Object System.Drawing.Size(480, 20)
$footerHint.Font = New-Object System.Drawing.Font("Segoe UI", 8)
$footerHint.ForeColor = [System.Drawing.Color]::FromArgb(104, 128, 158)
$footerPanel.Controls.Add($footerHint)

$versionLabel = New-Object System.Windows.Forms.Label
$versionLabel.Text = "VERSIÓN " + (Get-InstalledVersion)
$versionLabel.Location = New-Object System.Drawing.Point(520, 20)
$versionLabel.Size = New-Object System.Drawing.Size(148, 24)
$versionLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$versionLabel.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 8)
$versionLabel.ForeColor = [System.Drawing.Color]::FromArgb(113, 139, 176)
$footerPanel.Controls.Add($versionLabel)

function Update-ManagerStatus {
    $processCount = (Get-TradingProcesses).Count
    try {
        $status = Invoke-RestMethod -Uri ($DashboardUrl + "/api/status") -TimeoutSec 3
        $activeMode = ([string]$status.mode).ToUpperInvariant()
        if ($activeMode -in @('PAPER','TESTNET')) {
            $modeBadge.Text = $activeMode
        }
        $state = [string]$status.activity.state
        if ($state -eq "operational") {
            $statusLabel.Text = "Motor operativo"
            $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(45, 226, 166)
            $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(45, 226, 166)
            $statusPanel.BackColor = [System.Drawing.Color]::FromArgb(14, 38, 42)
            $statusDescription.Text = "Todos los servicios responden correctamente."
            $notifyIcon.Icon = $script:OperationalIcon
            $trayStatusItem.Text = "● Motor operativo"
            $trayStatusItem.ForeColor = [System.Drawing.Color]::FromArgb(45, 226, 166)
        }
        elseif ($state -eq "delayed") {
            $statusLabel.Text = "Motor retrasado"
            $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
            $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
            $statusPanel.BackColor = [System.Drawing.Color]::FromArgb(44, 37, 24)
            $statusDescription.Text = "El último ciclo está tardando más de lo esperado."
            $notifyIcon.Icon = $script:WarningIcon
            $trayStatusItem.Text = "● Motor retrasado"
            $trayStatusItem.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
        }
        else {
            $statusLabel.Text = "Motor sin actividad"
            $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(255, 93, 115)
            $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(255, 93, 115)
            $statusPanel.BackColor = [System.Drawing.Color]::FromArgb(48, 25, 34)
            $statusDescription.Text = "No se registra un ciclo reciente. Revisa el motor."
            $notifyIcon.Icon = $script:OfflineIcon
            $trayStatusItem.Text = "● Motor sin actividad"
            $trayStatusItem.ForeColor = [System.Drawing.Color]::FromArgb(255, 93, 115)
        }
        $lastCycle = "sin ciclos"
        if ($status.activity.last_cycle_at) {
            $lastCycle = ([datetime]$status.activity.last_cycle_at).ToLocalTime().ToString("dd/MM/yyyy HH:mm:ss")
        }
        $equity = [math]::Round([double]$status.equity, 2)
        $returnPct = [math]::Round([double]$status.return_pct, 2)
        $cash = [math]::Round([double]$status.cash, 2)
        $exposure = [math]::Round([double]$status.exposure, 2)
        $equityCard.Value.Text = $equity.ToString("N2")
        $equityCard.Note.Text = "USDT de capital total"
        $returnPrefix = if ($returnPct -ge 0) { "+" } else { "" }
        $returnCard.Value.Text = $returnPrefix + $returnPct.ToString("N2") + "%"
        $returnCard.Value.ForeColor = if ($returnPct -ge 0) { [System.Drawing.Color]::FromArgb(45, 226, 166) } else { [System.Drawing.Color]::FromArgb(255, 120, 140) }
        $returnCard.Note.Text = "Desde el inicio"
        $cashCard.Value.Text = $cash.ToString("N2")
        $cashCard.Note.Text = "USDT disponibles"
        $exposureCard.Value.Text = $exposure.ToString("N2")
        $exposureCard.Note.Text = "$($status.positions) de $($status.max_positions) posiciones"
        if ([int]$status.positions -ge [int]$status.max_positions) {
            $exposureCard.Value.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
        }
        else {
            $exposureCard.Value.ForeColor = [System.Drawing.Color]::White
        }
        $lastCycleLabel.Text = "ÚLTIMO CICLO`r`n$lastCycle"
        $notifyIcon.Text = "Crypto AI Trader - $equity USDT"
    }
    catch {
        if ($processCount -gt 0) {
            $statusLabel.Text = "Motor iniciando"
            $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
            $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
            $statusPanel.BackColor = [System.Drawing.Color]::FromArgb(44, 37, 24)
            $statusDescription.Text = "El proceso está activo, pero el portal todavía no responde."
            $notifyIcon.Text = "Crypto AI Trader - iniciando"
            $notifyIcon.Icon = $script:WarningIcon
            $trayStatusItem.Text = "● Motor iniciando"
            $trayStatusItem.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
        }
        else {
            $statusLabel.Text = "Motor detenido"
            $statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(255, 93, 115)
            $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(255, 93, 115)
            $statusPanel.BackColor = [System.Drawing.Color]::FromArgb(48, 25, 34)
            $statusDescription.Text = "No se encontró el proceso automático. Usa Reiniciar motor."
            $notifyIcon.Text = "Crypto AI Trader - detenido"
            $notifyIcon.Icon = $script:OfflineIcon
            $trayStatusItem.Text = "● Motor detenido"
            $trayStatusItem.ForeColor = [System.Drawing.Color]::FromArgb(255, 93, 115)
        }
        $lastCycleLabel.Text = "ÚLTIMO CICLO`r`nSin conexión"
        foreach ($card in @($equityCard, $returnCard, $cashCard, $exposureCard)) {
            $card.Value.Text = "—"
            $card.Note.Text = "Datos no disponibles"
        }
    }
    if (Test-Path $KillSwitchPath) {
        $killButton.Text = "▶   Reanudar nuevas entradas"
        $killButton.BackColor = [System.Drawing.Color]::FromArgb(14, 52, 48)
        $killButton.ForeColor = [System.Drawing.Color]::FromArgb(77, 239, 187)
        $killButton.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(37, 112, 94)
        $protectionLabel.Text = "⚠  Kill switch activo  ·  No se abrirán nuevas posiciones"
        $protectionLabel.ForeColor = [System.Drawing.Color]::FromArgb(255, 204, 102)
    }
    else {
        $killButton.Text = "⚠   Activar kill switch"
        $killButton.BackColor = [System.Drawing.Color]::FromArgb(55, 24, 35)
        $killButton.ForeColor = [System.Drawing.Color]::FromArgb(255, 147, 164)
        $killButton.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(120, 48, 66)
        $shownMode = if ($modeBadge.Text -in @('PAPER','TESTNET')) { $modeBadge.Text } else { 'PRUEBA' }
        $protectionLabel.Text = if ($shownMode -eq 'TESTNET') {
            "✓  Binance Spot Testnet  ·  Fondos ficticios  ·  LIVE bloqueado"
        } else {
            "✓  PAPER  ·  Simulación interna  ·  LIVE bloqueado"
        }
        $protectionLabel.ForeColor = [System.Drawing.Color]::FromArgb(92, 215, 171)
    }
    if (Test-CanonicalStartup) {
        $startupButton.Text = "✓   Inicio automático activado"
    }
    elseif ((Get-ProjectStartupShortcuts).Count -gt 0) {
        $startupButton.Text = "⚙   Actualizar inicio automático"
    }
    else {
        $startupButton.Text = "⚙   Activar inicio automático"
    }
    $versionLabel.Text = "VERSIÓN " + (Get-InstalledVersion)
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
$notifyMenu.Items.Add("-") | Out-Null
$showManagerItem = $notifyMenu.Items.Add("Abrir centro de control")
$script:MenuBitmap = $script:OperationalIcon.ToBitmap()
$showManagerItem.Image = $script:MenuBitmap
$showManagerItem.Add_Click({
    Show-ManagerWindow
})
$openPortalItem = $notifyMenu.Items.Add("Abrir portal remoto")
$openPortalItem.Add_Click({ Start-Process -FilePath $RemotePortalUrl })
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
})
$form.Add_Shown({
    if (-not (Test-Path $StartupOptOutPath) -and -not (Test-CanonicalStartup)) {
        Enable-AutomaticStartup
    }
    if ($Minimized) {
        Start-TradingBot
    }
    Update-ManagerStatus
    $timer.Start()
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
    $notifyIcon.Visible = $false
    $notifyIcon.Dispose()
    $script:LogoBitmap.Dispose()
    $script:MenuBitmap.Dispose()
    if ($script:RestartManager) {
        Start-Process -FilePath "wscript.exe" -ArgumentList ('"' + $ManagerLauncher + '"')
    }
})

[System.Windows.Forms.Application]::Run($form)
