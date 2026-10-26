# AST-extracted helpers and synthetic signed-journal fixtures only. No native
# console, provider, vault, engine, scheduled task or operating record is used.
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'scripts/open_live_connection_windows.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw 'Launcher parse failed' }
foreach ($name in @('Get-LiveConnectionDependencies', 'Get-LiveConnectionSafePath', 'Assert-LiveConnectionRegularFile',
    'Get-LiveConnectionPython', 'Assert-LiveConnectionSignedInstall', 'New-LiveConnectionLaunchPlan', 'Start-LiveConnectionConsole')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if ($null -eq $definition) { throw "Missing helper: $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Assert-Launcher([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
function Assert-Blocked([scriptblock]$Action, [string]$Message) {
    $blocked = $false
    try { & $Action | Out-Null } catch { $blocked = $true }
    Assert-Launcher $blocked $Message
}
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('crypto-local-connection-' + [Guid]::NewGuid().ToString('N'))
$source = Join-Path $fixture ('Instalaci' + [char]0xf3 + 'n Jos' + [char]0xe9 + ' con espacios')
$agent = Join-Path $fixture 'independent agent'
$runtime = Join-Path $fixture 'Python runtime'
New-Item -ItemType Directory -Path $source, $runtime, (Join-Path $agent 'data/remote-updates') -Force | Out-Null
$script:LauncherCalls = 0
$script:LaunchCapture = $null
$script:FixtureTask = $null
function Get-ScheduledTask {
    param([string]$TaskName, [string]$ErrorAction)
    Assert-Launcher ($TaskName -ceq 'Crypto Paper Portal Agent') 'Only the existing supervisor task may be read'
    return $script:FixtureTask
}
function Start-Process {
    param([string]$FilePath, [string]$ArgumentList, [string]$WorkingDirectory, [string]$WindowStyle)
    $script:LauncherCalls += 1
    $script:LaunchCapture = @{ FilePath=$FilePath; Arguments=$ArgumentList; WorkingDirectory=$WorkingDirectory; WindowStyle=$WindowStyle }
}
function New-FixtureTask([string]$Executable, [string]$Arguments = '') {
    return [PSCustomObject]@{ Actions=@([PSCustomObject]@{ Execute=$Executable; Arguments=$Arguments; WorkingDirectory=$agent }) }
}
function Write-FixtureJournal {
    $script:Journal | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $agent 'data/remote-updates/journal.json') -Encoding UTF8
}
try {
    $inventory = [ordered]@{}
    foreach ($relative in (Get-LiveConnectionDependencies)) {
        $path = Join-Path $source $relative
        New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
        $text = if ($relative -eq 'pyproject.toml') { "[project]`nversion = `"0.10.55`"`n" } else { '# synthetic fixture only' }
        [IO.File]::WriteAllText($path, $text)
        $inventory[$relative] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $script:Journal = [ordered]@{ phase='committed'; version='0.10.55'; sequence=55; release_id=('a' * 64); files=$inventory }
    Write-FixtureJournal
    '{"sequence":55}' | Set-Content -LiteralPath (Join-Path $agent 'data/remote-updates/sequence.json') -Encoding UTF8
    $python = Join-Path $runtime 'python.exe'
    [IO.File]::WriteAllText($python, 'not an executable; never launched')
    $script:FixtureTask = New-FixtureTask (Join-Path $runtime 'pythonw.exe')
    $plan = New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'SPOT_LIVE'
    Assert-Launcher ($script:LauncherCalls -eq 0) 'Building a launch plan must never start a process'
    Assert-Launcher ($plan.Arguments.Contains(('"' + $python + '" -I -B "'))) 'pythonw task must resolve its adjacent python console runtime'
    Assert-Launcher ($plan.Arguments.StartsWith('/D /V:OFF /S /K ""')) 'Disable AutoRun and expansion while retaining one quoted native command'
    Assert-Launcher ($plan.Arguments.EndsWith('--scope SPOT_LIVE"')) 'Only the selected scope may enter arguments'
    Assert-Launcher ($plan.WorkingDirectory -ceq $source) 'Spaces and Unicode must preserve the exact installed root'
    Assert-Launcher ($plan.Arguments -notmatch '(?i)--replace|-m\s+trader|--api-key|--api-secret|redirect|transcript') 'Default command must have no replace, engine, secret arguments or output handling'
    Start-LiveConnectionConsole $plan
    Assert-Launcher ($script:LauncherCalls -eq 1 -and $script:LaunchCapture.WindowStyle -ceq 'Normal') 'Only an intentional visible owner console may launch'
    Assert-Launcher ($script:LaunchCapture.FilePath -ieq (Join-Path $env:SystemRoot 'System32/cmd.exe')) 'Use the explicit native shell'

    $replacePlan = New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'FUTURES_LIVE' -Replace
    Assert-Launcher ($replacePlan.Arguments.EndsWith('--scope FUTURES_LIVE --replace"')) 'Replacement must require an explicit switch'
    $statusPlan = New-LiveConnectionLaunchPlan -ProjectRoot $source -Status
    Assert-Launcher ($statusPlan.Arguments.EndsWith('--status"') -and $statusPlan.Arguments -notmatch '--scope|--replace') 'Status is a separate action without input or replacement'
    foreach ($bad in @('', 'SPOT', 'spot_live', 'SPOT_LIVE & command', 'FUTURES_LIVE --replace')) {
        Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope $bad } 'Unlisted actions must be rejected before launch'
    }
    Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'SPOT_LIVE' -Status } 'Status cannot be mixed with configuration'
    Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Status -Replace } 'Status cannot replace credentials'
    foreach ($bad in @('C:\unsafe%NAME%\root', 'C:\unsafe!name\root', 'C:\unsafe&command\root', 'C:\unsafe^name\root', 'C:\unsafe|name\root', 'C:\unsafe<name\root', 'C:\unsafe>name\root', 'C:\unsafe"name\root', "C:\unsafe`nname\root", 'relative\root')) {
        Assert-Blocked { Get-LiveConnectionSafePath $bad } 'Expandable, quoted and nonabsolute paths must be blocked'
    }

    $wrapper = New-FixtureTask (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe') ('-NoProfile -File "watchdog.ps1" -PythonPath "' + (Join-Path $runtime 'pythonw.exe') + '"')
    Assert-Launcher ((Get-LiveConnectionPython $wrapper) -ceq $python) 'Watchdog PythonPath must resolve pythonw to adjacent python'
    $direct = New-FixtureTask $python
    Assert-Launcher ((Get-LiveConnectionPython $direct) -ceq $python) 'Direct python task must preserve its console runtime'
    Assert-Blocked { Get-LiveConnectionPython (New-FixtureTask (Join-Path $runtime 'missing/python.exe')) } 'Missing console runtime must fail closed'
    Assert-Blocked { Get-LiveConnectionPython (New-FixtureTask 'unrelated.exe') } 'No generic PATH Python fallback is allowed'

    $script:Journal.phase = 'pending_health'; Write-FixtureJournal
    Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'SPOT_LIVE' } 'Pending signed updates must not open input'
    $script:Journal.phase = 'committed'; $script:Journal.version = '0.10.54'; Write-FixtureJournal
    Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'SPOT_LIVE' } 'Journal version must match the installed version'
    $script:Journal.version = '0.10.55'; $script:Journal.sequence = '55'; Write-FixtureJournal
    Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'SPOT_LIVE' } 'A textual sequence must never stand in for the committed integer sequence'
    $script:Journal.sequence = 56; Write-FixtureJournal
    Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'SPOT_LIVE' } 'Journal and committed sequence must agree'
    $script:Journal.sequence = 55; Write-FixtureJournal
    $changed = Join-Path $source 'trader/live_transport.py'
    [IO.File]::WriteAllText($changed, '# changed fixture')
    Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'SPOT_LIVE' } 'Changed installed import dependency must block input'
    [IO.File]::WriteAllText($changed, '# synthetic fixture only')
    $saved = $script:Journal.files['scripts/configure_live_connection.py']
    $script:Journal.files.Remove('scripts/configure_live_connection.py'); Write-FixtureJournal
    Assert-Blocked { New-LiveConnectionLaunchPlan -ProjectRoot $source -Scope 'SPOT_LIVE' } 'Missing signed entry inventory must block input'
    $script:Journal.files['scripts/configure_live_connection.py'] = $saved; Write-FixtureJournal
    Assert-Launcher ($script:LauncherCalls -eq 1) 'All negative plans must leave the native launch count unchanged'
    Write-Output 'Windows local connection launcher passed: signed import inventory, task runtime, safe quoting, explicit scope/status/replace and visible owner console; zero real launches.'
} finally {
    $resolved = [IO.Path]::GetFullPath($fixture)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture deletion scope blocked' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
