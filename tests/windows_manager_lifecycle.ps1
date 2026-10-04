# Execute actual lifecycle functions in isolated child processes. No UI,
# scheduled tasks, operating installation, credentials, or engine is started.
param([switch]$Worker, [string]$Root, [string]$ResultPath, [string]$Action, [string]$Activate = 'true')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
foreach ($file in @('scripts/manager_windows.ps1', 'scripts/agent_self_heal.ps1')) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $repo $file), [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw "$file : $($errors -join '; ')" }
    foreach ($name in @('Enter-ManagerInstance', 'Exit-ManagerInstance', 'Enter-AgentRepairLock', 'Get-AgentRepairNotice', 'Test-AgentRepairHeartbeat')) {
        $definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
        if ($null -ne $definition) { . ([scriptblock]::Create($definition.Extent.Text)) }
    }
}
if ($Worker) {
    if ($Action -eq 'manager') {
        $instance = Enter-ManagerInstance $Root ($Activate -eq 'true')
        @{ owned=($null -ne $instance) } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath
        if ($null -ne $instance) { Exit-ManagerInstance $instance }
    } elseif ($Action -eq 'repair') {
        $handle = Enter-AgentRepairLock $Root
        @{ owned=($null -ne $handle) } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath
        if ($null -ne $handle) { $handle.Dispose() }
    } elseif ($Action -eq 'abandon') {
        $instance = Enter-ManagerInstance $Root $false
        if ($null -eq $instance) { throw 'Test owner could not claim mutex' }
        @{ ready=$true } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath
        Start-Sleep -Seconds 30
        Exit-ManagerInstance $instance
    } else { throw 'Invalid test action' }
    exit 0
}
function Assert-True([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('crypto-manager-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture | Out-Null
$instance = $null
$handle = $null
$child = $null
try {
    function Invoke-Worker([string]$Kind, [string]$Signal = 'true') {
        $result = Join-Path $fixture ([Guid]::NewGuid().ToString('N') + '.json')
        # Use Windows PowerShell 5.1, the same host as the real VBS launcher.
        $args = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $PSCommandPath +
            '" -Worker -Root "' + $fixture + '" -ResultPath "' + $result + '" -Action ' + $Kind + ' -Activate ' + $Signal
        $process = Start-Process powershell.exe -ArgumentList $args -PassThru -WindowStyle Hidden
        try {
            if (-not $process.WaitForExit(15000)) { throw 'Test worker timed out' }
            if ($process.ExitCode -ne 0) { throw 'Test worker failed' }
            return (Get-Content -LiteralPath $result -Raw | ConvertFrom-Json)
        } finally {
            if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
            $process.Dispose()
        }
    }
    $instance = Enter-ManagerInstance $fixture
    Assert-True ($null -ne $instance) 'First manager must own the mutex'
    Assert-True (-not (Invoke-Worker 'manager').owned) 'A second process must not own the same manager'
    Assert-True ($instance.Show.WaitOne(0)) 'Manual duplicate must activate the existing manager'
    Assert-True (-not (Invoke-Worker 'manager' 'false').owned) 'Autostart duplicate must also exit'
    Assert-True (-not $instance.Show.WaitOne(0)) 'Minimized autostart must not show the existing manager'
    Exit-ManagerInstance $instance
    $instance = $null
    Assert-True ((Invoke-Worker 'manager').owned) 'Clean exit must permit the next manager'

    $readyPath = Join-Path $fixture 'abandoned.json'
    $args = '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $PSCommandPath +
        '" -Worker -Root "' + $fixture + '" -ResultPath "' + $readyPath + '" -Action abandon'
    $child = Start-Process powershell.exe -ArgumentList $args -PassThru -WindowStyle Hidden
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while (-not (Test-Path $readyPath) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 50 }
    Assert-True (Test-Path $readyPath) 'Abandoned owner fixture did not start'
    # Retain a handle so the mutex survives the owning child process crash.
    $canonical = [IO.Path]::GetFullPath($fixture).TrimEnd('\', '/').ToUpperInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical))).Replace('-', '') }
    finally { $sha.Dispose() }
    $retained = [Threading.Mutex]::OpenExisting('Local\CryptoAITrader.Manager.' + $digest)
    try {
        $child.Kill()
        $child.WaitForExit()
        $instance = Enter-ManagerInstance $fixture $false
        Assert-True ($null -ne $instance) 'Crashed owner must permit recovery'
        Exit-ManagerInstance $instance
        $instance = $null
    } finally { $retained.Dispose() }

    $handle = Enter-AgentRepairLock $fixture
    Assert-True ($null -ne $handle) 'First repair must acquire the file lock'
    Assert-True (-not (Invoke-Worker 'repair').owned) 'Concurrent repairs must not overlap'
    $handle.Dispose()
    $handle = $null
    Assert-True ((Invoke-Worker 'repair').owned) 'Repair lock must release after exit'

    foreach ($status in @('connection_pending', 'skipped_disabled', 'repair_in_progress')) {
        $notice = Get-AgentRepairNotice ([PSCustomObject]@{ status=$status; error_type='ModuleNotFoundError' })
        Assert-True (-not $notice.Healthy) "$status must never be presented as healthy"
    }
    Assert-True (Get-AgentRepairNotice ([PSCustomObject]@{ status='healthy' })).Healthy 'Confirmed repair must be healthy'
    $heartbeat = [PSCustomObject]@{ sync_ok=$true; last_success=200; error_type=$null }
    Assert-True (Test-AgentRepairHeartbeat $heartbeat 'Running' 100) 'New successful heartbeat must count'
    Assert-True (-not (Test-AgentRepairHeartbeat $heartbeat 'Running' 200)) 'Same heartbeat must not count twice'
    Assert-True (-not (Test-AgentRepairHeartbeat $heartbeat 'Ready' 100)) 'Stopped task must not count'
    $heartbeat.error_type = 'SUPERVISOR_UNAVAILABLE:ModuleNotFoundError'
    Assert-True (-not (Test-AgentRepairHeartbeat $heartbeat 'Running' 100)) 'Partial supervisor failure must not claim successful repair'
    Write-Output 'Windows lifecycle checks passed: duplicate/quiet/clean/crash manager, repair exclusion, truthful notices.'
} finally {
    if ($null -ne $instance) { Exit-ManagerInstance $instance }
    if ($null -ne $handle) { $handle.Dispose() }
    if ($null -ne $child) {
        if (-not $child.HasExited) { $child.Kill(); $child.WaitForExit() }
        $child.Dispose()
    }
    Remove-Item -LiteralPath $fixture -Recurse -Force
}
