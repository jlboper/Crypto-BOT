# AST-extracted UI helpers only: never launch the app, indicator, task or engine.
param([string]$RenderPath = '')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'scripts/manager_windows.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw ($errors -join '; ') }
foreach ($name in @('Get-ManagerValue','Format-ManagerNumber','Get-ManagerAge','Format-ManagerTime',
    'Get-ManagerArmedCount','Get-ManagerProtection','Get-ManagerEngineViews','Get-ManagerGuardianView','Get-ManagerRemoteView',
    'Get-ManagerPortalSections','Get-ManagerPortalUrl','New-ManagerPortalMenu','Get-InstalledVersion','New-AppButton','New-EngineCard','Set-EngineCard')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if ($null -eq $definition) { throw "Missing view helper: $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Assert-View([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
$DashboardUrl = 'http://127.0.0.1:8765'
$RemotePortalUrl = 'https://crypto-paper-private-portal.jlboper.workers.dev/'
$sections = @(Get-ManagerPortalSections)
$expectedSections = @('command-center','portfolio-capital','trading-engines','guardian-ai','operations-decisions','research-lab','system-settings')
Assert-View (($sections.Id -join ',') -ceq ($expectedSections -join ',')) 'Native navigation must share the seven command-center destinations'
foreach ($section in $sections) {
    $localUrl = [Uri](Get-ManagerPortalUrl $section.Id)
    $remoteUrl = [Uri](Get-ManagerPortalUrl $section.Id -Remote)
    Assert-View ($localUrl.Authority -eq '127.0.0.1:8765' -and $remoteUrl.Authority -eq 'crypto-paper-private-portal.jlboper.workers.dev') 'Navigation must retain the current local and authenticated remote portal origins'
    Assert-View ($localUrl.Fragment -ceq ('#' + $section.Id) -and $remoteUrl.Fragment -ceq ('#' + $section.Id)) 'Both portals must open the same section'
    Assert-View (-not $localUrl.Query -and -not $remoteUrl.Query -and -not $localUrl.UserInfo -and -not $remoteUrl.UserInfo) 'Section links must never carry credentials or approval parameters'
}
foreach ($unsafe in @('','LIVE','https://external.example','system-settings?token=private','command-center#other')) {
    $rejected = $false
    try { Get-ManagerPortalUrl $unsafe | Out-Null } catch { $rejected = $true }
    Assert-View $rejected 'A section link cannot become an arbitrary URL or execution control'
}
$now = [DateTimeOffset]::Parse('2026-10-16T12:00:00Z')
$spot = @'
{"mode":"TESTNET","equity":1002,"return_pct":0.2,"exposure":30,"positions":1,"cycle_seconds":300,"activity":{"state":"operational","last_cycle_at":"2026-10-16T12:00:00Z"},"native_protection":{"positions":{"BTCUSDT":{"status":"ARMED"}}}}
'@ | ConvertFrom-Json
$futures = @'
{"enabled":true,"killed":false,"positions":[{"symbol":"ETHUSDT","direction":"LONG"},{"symbol":"SOLUSDT","direction":"SHORT"}],"equity":[{"wallet_balance":2000,"unrealized_pnl":-5}],"cycle_diagnostic":{"state":"WAITING_CANDLE","at":"2026-10-16T12:00:00Z"},"scorecard":{"account_return_pct":0},"native_protection":{"positions":{"ETHUSDT":{"status":"ARMED"},"SOLUSDT":{"status":"PENDING"}}}}
'@ | ConvertFrom-Json
$pulse = @'
{"schema":1,"mode":"SHADOW","state":"SHADOW","updated_at":"2026-10-16T12:00:00Z","freshness":{"state":"FRESH"},"positions":[],"performance":{"equity":1000,"net_pnl":0},"stats":{"events_analyzed":0,"opportunities":0},"sources":{"binance_ws":{"state":"CONNECTED"}}}
'@ | ConvertFrom-Json
$views = Get-ManagerEngineViews $spot $futures $pulse $now
foreach ($stamp in @($now, $now.UtcDateTime, '2026-10-16T12:00:00Z')) {
    Assert-View ((Get-ManagerAge $stamp $now) -eq 0) 'ISO strings and auto-converted DateTime values must preserve the same UTC instant'
    Assert-View ((Format-ManagerTime $stamp) -ne 'Sin evaluación registrada') 'Valid converted timestamps must retain an evaluation label'
}
Assert-View ($views.Spot.State -eq 'OPERATIVO') 'Spot operational state must come from current API evidence'
Assert-View ($views.Spot.Protection -eq '1/1 OCO confirmados') 'Spot protection must count confirmed native journals'
Assert-View ($views.Futures.Capital -eq 'Equity: 1,995.00 USDT') 'Futures equity must include actual unrealized PnL'
Assert-View ($views.Futures.Positions -eq 'LONG 1 · SHORT 1') 'All Futures positions must count by actual direction'
Assert-View ($views.Futures.Protection -eq '1/2 stops confirmados') 'Pending protection must never look confirmed'
Assert-View ($views.Futures.Tone -eq 'Amber' -and $views.Futures.State -eq 'PROTECCIÓN PENDIENTE') 'Held Futures exposure without all native confirmations must show attention'
Assert-View ($views.Pulse.State -eq 'SHADOW ACTIVO') 'Pulse must be explicitly Shadow'
Assert-View ($views.Pulse.Positions -match 'hipotéticas: 0') 'Known empty positions must remain zero'
Assert-View ($views.Pulse.Return -eq 'Neto simulado: 0.00 USDT') 'Known zero financial result must not become missing'
Assert-View ($views.Pulse.Protection -match 'Sin órdenes al exchange') 'Pulse must never imply exchange execution'
$missing = Get-ManagerEngineViews $null $null $null $now
Assert-View ($missing.Spot.Capital -eq 'Equity: —') 'Missing capital must not be invented as zero'
Assert-View ($missing.Futures.State -eq 'SIN DATOS') 'Absent Futures projection is not an execution error'
Assert-View ($missing.Pulse.Positions -match 'hipotéticas: —') 'Absent Shadow positions must remain unavailable'
foreach ($bad in @($null, [double]::NaN, [double]::PositiveInfinity, $true, 'not a number')) {
    Assert-View ((Format-ManagerNumber $bad) -eq '—') 'Unknown or nonfinite amounts must remain unavailable'
}
$pulse.updated_at = '2026-10-16T11:59:10Z'
$stale = Get-ManagerEngineViews $spot $futures $pulse $now
Assert-View ($stale.Pulse.State -match 'ANTIGUO') 'Old snapshots must not be shown as current'
Assert-View ($stale.Pulse.Capital -eq 'Equity: —' -and $stale.Pulse.Return -eq 'Neto simulado: — · antiguo') 'Cached old Pulse finances must not appear current'
$pulse.updated_at = '2026-10-16T12:00:00Z'
$futures.native_protection.positions.SOLUSDT.status = 'ARMED'
$allArmed = Get-ManagerEngineViews $spot $futures $pulse $now
Assert-View ($allArmed.Futures.Tone -eq 'Green' -and $allArmed.Futures.State -eq 'CON POSICIONES') 'Fully confirmed fresh Futures exposure can show operational status'
$spot.native_protection.positions.BTCUSDT.status = 'PENDING'
$pending = Get-ManagerEngineViews $spot $futures $pulse $now
Assert-View ($pending.Spot.Tone -eq 'Amber' -and $pending.Spot.State -eq 'PROTECCIÓN PENDIENTE') 'Unconfirmed Spot exposure must show attention'
$spot | Add-Member -NotePropertyName killed -NotePropertyValue $true
$paused = Get-ManagerEngineViews $spot $futures $pulse $now
Assert-View ($paused.Spot.State -eq 'ENTRADAS PAUSADAS') 'An owner pause takes precedence over pending protection state'
$spot.killed = $false
$spot.positions = 0
$flat = Get-ManagerEngineViews $spot $futures $pulse $now
Assert-View ($flat.Spot.Tone -eq 'Green' -and $flat.Spot.Protection -match 'Sin exposición') 'No positions must not create a protection error'
$spot.positions = 1
$spot.native_protection.positions.BTCUSDT.status = 'ARMED'
$spot.mode = 'PAPER'
$spot.positions = 0
$paperFlat = Get-ManagerEngineViews $spot $futures $pulse $now
Assert-View ($paperFlat.Spot.Protection -eq 'Sin exposición · stops simulados') 'Flat PAPER must not imply missing native exchange protection'
$spot.positions = 1
$spot.native_protection.positions.BTCUSDT.status = 'PENDING'
$paperOpen = Get-ManagerEngineViews $spot $futures $pulse $now
Assert-View ($paperOpen.Spot.Protection -eq 'Stops simulados · PAPER' -and $paperOpen.Spot.Tone -eq 'Green') 'PAPER protections are simulated and do not require native ARMED status'
$spot.mode = 'TESTNET'
$spot.native_protection.positions.BTCUSDT.status = 'ARMED'
$remote = [PSCustomObject]@{sync_ok=$true;last_success=$now.ToUnixTimeSeconds();error_type=$null}
Assert-View ((Get-ManagerRemoteView $remote $now) -eq 'HTTPS remoto reciente') 'Remote health requires fresh HTTPS success'
$remote.sync_ok = $false
Assert-View ((Get-ManagerRemoteView $remote $now) -match 'motores independientes') 'Remote sync failure must not imply engine outage'
$request = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Update-ManagerStatus' }, $true)
Assert-View ($request.Extent.Text -match 'GetAsync' -and $request.Extent.Text -notmatch 'Invoke-RestMethod|Start-Process|Start-TradingBot') 'UI reads must stay asynchronous and must never launch an engine'

$platform = @'
{"quant":{"schema":1,"engine":"QUANT_ARBITRAGE","mode":"SHADOW","state":"NOT_STARTED","initialized":false,"enabled":false,"execution_enabled":false,"controls_available":false,"promotion_allowed":false,"performance":{"equity":9999,"net_pnl":8999}},"portfolio_guardian":{"schema":1,"engine":"PORTFOLIO_GUARDIAN","mode":"OBSERVER","state":"OBSERVING","at":"2026-10-16T12:00:00Z","controls_enabled":false,"can_veto":false,"execution_enabled":false,"alerts":[]}}
'@ | ConvertFrom-Json
$four = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $platform.quant
Assert-View ($four.Quant.State -eq 'SIN INICIAR' -and $four.Quant.Tone -eq 'Muted') 'Prepared Quant must not look operational'
Assert-View ($four.Quant.Capital -eq 'Capital: —' -and $four.Quant.Return -eq 'Neto simulado: —') 'Uninitialized Quant never has fabricated virtual capital or results'
Assert-View ($four.Quant.Protection -match 'Ejecución bloqueada' -and $four.Quant.Protection -match 'Promoción bloqueada') 'Quant execution and promotion remain blocked'
Assert-View ($missing.Quant.State -eq 'SIN DATOS') 'Missing optional Quant identity must remain unknown'
Assert-View ((Get-ManagerGuardianView $platform $now) -eq 'Guardian: Observer · 0 alertas · sin veto') 'Guardian only observes a compatible fresh read'
$platform.portfolio_guardian.at = '2026-10-16T12:00:10Z'
Assert-View ((Get-ManagerGuardianView $platform $now) -match 'lectura antigua') 'Future Guardian timestamps must not be treated as fresh'
$platform.portfolio_guardian.at = '2026-10-16T11:57:00Z'
Assert-View ((Get-ManagerGuardianView $platform $now) -match 'lectura antigua') 'Guardian must mark stale local evidence'
$platform.portfolio_guardian.at = '2026-10-16T12:00:00Z'
$platform | Add-Member -NotePropertyName remote_sync_stale -NotePropertyValue $true
Assert-View ((Get-ManagerGuardianView $platform $now) -match 'lectura antigua') 'Guardian must mark stale remote evidence'
$platform.remote_sync_stale = $false
$platform.portfolio_guardian.can_veto = $true
Assert-View ((Get-ManagerGuardianView $platform $now) -match 'sin lectura') 'A control-capable Guardian contract is incompatible with Observer UI'
$platform.quant.execution_enabled = $true
$incompatible = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $platform.quant
Assert-View ($incompatible.Quant.State -eq 'SIN DATOS') 'Unknown execution-capable Quant contracts must not be presented as running safely'
Assert-View ($ast.Extent.Text.Contains('$modeBadge.Text = "4 BOTS"')) 'Native badge must identify four bots'
Assert-View ($ast.Extent.Text.Contains('$title.Text = "CRYPTO-BOT 2.0"') -and $ast.Extent.Text.Contains('$levelBadge.Text = ''LEVEL 0''')) 'Foundation identity must preserve four engines and a read-only LEVEL 0 label'
$quantLive = @'
{"schema":1,"engine":"QUANT_ARBITRAGE","mode":"SHADOW","state":"SHADOW","initialized":true,"enabled":true,"execution_enabled":false,"controls_available":true,"promotion_allowed":false,"at":"2026-10-16T12:00:00Z","updated_at":"2026-10-16T12:00:00Z","last_evaluation":"2026-10-16T12:00:00Z","freshness":{"state":"FRESH","age_seconds":0},"positions":[{"legs":[{"symbol":"BTCUSDT","direction":"LONG"},{"symbol":"BTCUSDT","direction":"SHORT"}]}],"performance":{"equity":1001,"net_pnl":1,"closed_trades":0}}
'@ | ConvertFrom-Json
$shadow = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $quantLive
Assert-View ($shadow.Quant.State -eq 'SHADOW ACTIVO' -and $shadow.Quant.Tone -eq 'Green') 'Fresh initialized Quant is explicitly hypothetical Shadow'
Assert-View ($shadow.Quant.Capital -eq 'Equity: 1,001.00 USDT' -and $shadow.Quant.Return -eq 'Neto simulado: 1.00 USDT') 'Quant must render its own virtual equity and net result'
Assert-View ($shadow.Quant.Positions -match 'Pares: 1 · piernas: 2') 'Quant counts hypothetical pairs and legs without claiming actual exchange positions'
$flatQuant = $quantLive | ConvertTo-Json -Depth 10 | ConvertFrom-Json
$flatQuant.positions = @()
$flatQuantView = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $flatQuant
Assert-View ($flatQuantView.Quant.Positions -match 'Pares: 0 · piernas: 0' -and $flatQuantView.Quant.Positions -match 'Cierres: 0$') 'Known empty Quant positions and integer close counts must remain zero'
$flatQuant.PSObject.Properties.Remove('positions')
$unknownInventory = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $flatQuant
Assert-View ($unknownInventory.Quant.Positions -match 'Pares: — · piernas: —') 'Missing Quant inventory must not become a known empty pair ledger'
Assert-View ($shadow.Quant.Protection -match 'Sin órdenes al exchange' -and $shadow.Quant.Protection -match 'no atómicas') 'Quant must not imply an atomic real hedge'
$quantLive | Add-Member -NotePropertyName risk_halt -NotePropertyValue ([PSCustomObject]@{state='HALTED'})
$lossHalt = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $quantLive
Assert-View ($lossHalt.Quant.State -eq 'LÍMITE DE PÉRDIDA' -and $lossHalt.Quant.Tone -eq 'Amber') 'Quant loss halt is visible and does not imply removal of protective simulation'
$quantLive.risk_halt.state = 'UNKNOWN'
$unknownRisk = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $quantLive
Assert-View ($unknownRisk.Quant.State -eq 'VALORACIÓN PENDIENTE') 'Unknown Quant risk must remain visible'
$quantLive.risk_halt.state = 'READY'
$quantLive.updated_at = '2026-10-16T11:58:29Z'
$oldQuant = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $quantLive
Assert-View ($oldQuant.Quant.State -match 'ANTIGUO' -and $oldQuant.Quant.Capital -eq 'Equity: —') 'Quant marks older than ninety seconds must hide current valuations'
$quantLive.updated_at = '2026-10-16T12:00:10Z'
$futureQuant = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $quantLive
Assert-View ($futureQuant.Quant.State -match 'ANTIGUO') 'Quant future timestamps beyond clock tolerance are not fresh'
$quantLive.updated_at = '2026-10-16T12:00:00Z'
$quantLive.state = 'PAUSED'
$pausedQuant = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $quantLive
Assert-View ($pausedQuant.Quant.State -eq 'ENTRADAS PAUSADAS' -and $pausedQuant.Quant.Protection -match 'Sin órdenes') 'Quant pause is independent and remains hypothetical'
$quantLive.performance.equity = $null
$quantLive.performance.net_pnl = $null
$pendingFunding = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $quantLive
Assert-View ($pendingFunding.Quant.Capital -eq 'Equity: —' -and $pendingFunding.Quant.Return -eq 'Neto simulado: —') 'Pending authoritative funding must preserve unknown financial values'
$platform.quant.execution_enabled = $false
$platform.quant.state = 'DEGRADED'
$missingLedger = Get-ManagerEngineViews $spot $futures $pulse $now -Quant $platform.quant
Assert-View ($missingLedger.Quant.State -eq 'LEDGER NO DISPONIBLE' -and $missingLedger.Quant.Capital -eq 'Capital: —') 'A failed uninitialized ledger is not a fresh zero wallet or an unstarted healthy identity'

if ($RenderPath) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    # Construct only the form's layout statements. No manager instance, timers,
    # startup hooks or application loop is evaluated; no form is ever shown.
    $ProjectRoot = $repo
    $OperationalIconPath = Join-Path $repo 'web/crypto-ai-trader.ico'
    $WarningIconPath = Join-Path $repo 'web/crypto-ai-trader-warning.ico'
    $OfflineIconPath = Join-Path $repo 'web/crypto-ai-trader-offline.ico'
    $HeaderLogoPath = Join-Path $repo 'web/crypto-ai-trader-icon.png'
    $layoutStart = $ast.Extent.Text.IndexOf('$form = New-Object System.Windows.Forms.Form')
    $layoutEnd = $ast.Extent.Text.IndexOf('# Read-only HTTP polling')
    Assert-View ($layoutStart -ge 0 -and $layoutEnd -gt $layoutStart) 'The isolated render must stop before polling and startup ownership'
    . ([scriptblock]::Create($ast.Extent.Text.Substring($layoutStart,$layoutEnd-$layoutStart)))
    Set-EngineCard $spotCard $views.Spot
    Set-EngineCard $futuresCard $views.Futures
    Set-EngineCard $pulseCard $views.Pulse
    Set-EngineCard $quantCard $shadow.Quant
    $platform.portfolio_guardian.can_veto = $false
    $footerHint.Text = 'LEVEL 0 · ' + (Get-ManagerGuardianView $platform $now)
    $statusLabel.Text = 'VISTA SINTÉTICA · cuatro motores'
    $statusDescription.Text = 'Datos de prueba aislados. Capitales separados.'
    $lastCycleLabel.Text = "LECTURA DEL PANEL`r`n16/10 12:00:00"
    Assert-View ($ast.Extent.Text.Contains('$form.MaximumSize = New-Object System.Drawing.Size(760, 770)')) 'Foundation must keep the existing compact maximum dimensions'
    Assert-View ($form.Width -le 760 -and $form.Height -le 770) 'The native window must not grow beyond the compact layout when Windows constrains its working area'
    foreach ($card in @($spotCard,$futuresCard,$pulseCard,$quantCard)) {
        Assert-View ($card.Panel.Right -le $form.ClientSize.Width -and $card.Panel.Bottom -le $form.ClientSize.Height) 'All four cards must fit without horizontal scrolling'
    }
    Assert-View ($portalSectionsMenu.Items.Count -eq 7) 'One compact menu must expose every platform section'
    Assert-View ($levelBadge -is [System.Windows.Forms.Label]) 'LEVEL 0 must be a read-only label, never an authority toggle'
    # Render the actual child controls on an unattached canvas: Form.DrawToBitmap
    # omits children of an unshown form, while showing it would violate isolation.
    $canvas = New-Object System.Windows.Forms.Panel
    $canvas.Size = New-Object Drawing.Size(744,740)
    $canvas.BackColor = $form.BackColor
    $canvas.ForeColor = $form.ForeColor
    $canvas.Font = $form.Font
    $layoutControls = @($form.Controls | ForEach-Object { $_ })
    foreach ($control in $layoutControls) { $canvas.Controls.Add($control) }
    $bitmap = New-Object Drawing.Bitmap($canvas.Width,$canvas.Height)
    try {
        $canvas.CreateControl()
        $canvas.DrawToBitmap($bitmap, [Drawing.Rectangle]::new(0,0,$canvas.Width,$canvas.Height))
        $bitmap.Save([IO.Path]::GetFullPath($RenderPath), [Drawing.Imaging.ImageFormat]::Png)
    } finally { $bitmap.Dispose(); $canvas.Dispose(); $form.Dispose(); $portalSectionsMenu.Dispose(); $script:LogoBitmap.Dispose() }
}
Write-Output 'Windows command-center view checks passed: seven safe sections, read-only LEVEL 0, four engines, Guardian Observer, synthetic finances, protections, missing/stale data and isolated HTTPS.'
