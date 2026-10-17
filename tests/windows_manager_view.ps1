# AST-extracted UI helpers only: never launch the app, indicator, task or engine.
param([string]$RenderPath = '')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'scripts/manager_windows.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw ($errors -join '; ') }
foreach ($name in @('Get-ManagerValue','Format-ManagerNumber','Get-ManagerAge','Format-ManagerTime',
    'Get-ManagerArmedCount','Get-ManagerProtection','Get-ManagerEngineViews','Get-ManagerGuardianView','Get-ManagerRemoteView','New-EngineCard','Set-EngineCard')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if ($null -eq $definition) { throw "Missing view helper: $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Assert-View([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
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

if ($RenderPath) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $canvas = New-Object System.Windows.Forms.Panel
    $canvas.Size = New-Object System.Drawing.Size(716, 316)
    $canvas.BackColor = [Drawing.Color]::FromArgb(8,13,24)
    $drawn = @()
    foreach ($row in @(@('SPOT BOT',12,8,$views.Spot), @('FUTURES BOT',362,8,$views.Futures), @('AI MARKET PULSE',12,160,$views.Pulse), @('QUANT ARBITRAGE',362,160,$four.Quant))) {
        $card = New-EngineCard $row[0] $row[1] $row[2]
        Set-EngineCard $card $row[3]
        $canvas.Controls.Add($card.Panel); $drawn += $card
        Assert-View (($card.Panel.Right -le $canvas.Width) -and ($card.Panel.Bottom -le $canvas.Height)) 'Every compact card must fit the 2x2 render bounds'
    }
    $bitmap = New-Object Drawing.Bitmap(716,316)
    try {
        $canvas.CreateControl()
        $canvas.DrawToBitmap($bitmap, [Drawing.Rectangle]::new(0,0,716,316))
        $bitmap.Save([IO.Path]::GetFullPath($RenderPath), [Drawing.Imaging.ImageFormat]::Png)
    } finally { $bitmap.Dispose(); $canvas.Dispose() }
}
Write-Output 'Windows four-engine and Guardian Observer view checks passed: synthetic state, finances, protections, missing/stale data, isolated HTTPS and async read-only polling.'
