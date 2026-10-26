[CmdletBinding(DefaultParameterSetName = 'Scope')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Scope')]
    [ValidateSet('SPOT_LIVE', 'FUTURES_LIVE')]
    [string]$Scope,
    [Parameter(ParameterSetName = 'Scope')]
    [switch]$Replace,
    [Parameter(Mandatory = $true, ParameterSetName = 'Status')]
    [switch]$Status
)
$ErrorActionPreference = 'Stop'

function Get-LiveConnectionDependencies {
    # Only the installed entry point and its local import closure, plus the
    # version record. No vault, .env, financial data or provider call is read.
    return @('scripts/open_live_connection_windows.ps1', 'scripts/configure_live_connection.py',
        'trader/__init__.py', 'trader/live_credentials.py', 'trader/local_protection.py',
        'trader/live_transport.py', 'trader/account_inventory.py', 'trader/runtime.py', 'pyproject.toml')
}

function Get-LiveConnectionSafePath([string]$Path) {
    # cmd expands percent/bang and interprets metacharacters independently of
    # PowerShell. Accept spaces and Unicode, but never an expandable command.
    if (-not $Path -or $Path -match '[\x00-\x1f"%!^&|<>]' -or $Path -notmatch '^[A-Za-z]:[\\/]') {
        throw 'LOCAL_CONSOLE_PATH_BLOCKED'
    }
    return [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Assert-LiveConnectionRegularFile([string]$Path, [string]$Root = '') {
    $safe = Get-LiveConnectionSafePath $Path
    $item = Get-Item -LiteralPath $safe -Force -ErrorAction Stop
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'LOCAL_CONSOLE_FILE_BLOCKED'
    }
    if ($Root) {
        $rootPath = Get-LiveConnectionSafePath $Root
        if (-not $safe.StartsWith($rootPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'LOCAL_CONSOLE_FILE_BLOCKED'
        }
        $parent = $item.Directory
        while ($null -ne $parent) {
            if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'LOCAL_CONSOLE_FILE_BLOCKED' }
            if ($parent.FullName.TrimEnd('\') -ieq $rootPath) { break }
            $parent = $parent.Parent
        }
        if ($null -eq $parent) { throw 'LOCAL_CONSOLE_FILE_BLOCKED' }
    }
    return $safe
}

function Get-LiveConnectionPython($Task) {
    if (-not $Task.Actions -or -not $Task.Actions[0].WorkingDirectory) {
        throw 'INDEPENDENT_SUPERVISOR_REQUIRED'
    }
    $action = $Task.Actions[0]
    $executable = [Environment]::ExpandEnvironmentVariables([string]$action.Execute)
    $arguments = [Environment]::ExpandEnvironmentVariables([string]$action.Arguments)
    $python = ''
    if ($executable -match '(?i)pythonw\.exe$') {
        $python = Join-Path (Split-Path -Parent $executable) 'python.exe'
    } elseif ($executable -match '(?i)python\.exe$') {
        $python = $executable
    } elseif ($executable -match '(?i)powershell\.exe$' -and $arguments -match '(?i)-PythonPath\s+"([^"]+)"') {
        $candidate = $Matches[1]
        if ($candidate -match '(?i)pythonw\.exe$') {
            $python = Join-Path (Split-Path -Parent $candidate) 'python.exe'
        } elseif ($candidate -match '(?i)python\.exe$') {
            $python = $candidate
        }
    }
    if (-not $python) { throw 'SUPERVISOR_PYTHON_UNAVAILABLE' }
    return (Assert-LiveConnectionRegularFile $python)
}

function Assert-LiveConnectionSignedInstall([string]$ProjectRoot, [string]$AgentRoot) {
    $root = Get-LiveConnectionSafePath $ProjectRoot
    $agent = Get-LiveConnectionSafePath $AgentRoot
    if ($root -ieq $agent) { throw 'INDEPENDENT_SUPERVISOR_REQUIRED' }
    $journalPath = Assert-LiveConnectionRegularFile (Join-Path $agent 'data/remote-updates/journal.json') $agent
    $sequencePath = Assert-LiveConnectionRegularFile (Join-Path $agent 'data/remote-updates/sequence.json') $agent
    if ((Get-Item -LiteralPath $journalPath).Length -gt 1048576 -or
        (Get-Item -LiteralPath $sequencePath).Length -gt 4096) { throw 'COMMITTED_INSTALL_UNAVAILABLE' }
    $journal = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
    $sequence = Get-Content -LiteralPath $sequencePath -Raw | ConvertFrom-Json
    $project = Assert-LiveConnectionRegularFile (Join-Path $root 'pyproject.toml') $root
    if ((Get-Item -LiteralPath $project).Length -gt 1048576) { throw 'COMMITTED_INSTALL_UNAVAILABLE' }
    $versions = [regex]::Matches((Get-Content -LiteralPath $project -Raw), '(?m)^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$')
    if ($versions.Count -ne 1 -or $journal.phase -isnot [string] -or $journal.phase -cne 'committed' -or
        $journal.version -isnot [string] -or $journal.version -cne $versions[0].Groups[1].Value -or
        ($journal.sequence -isnot [int] -and $journal.sequence -isnot [long]) -or
        ($sequence.sequence -isnot [int] -and $sequence.sequence -isnot [long]) -or
        $journal.sequence -lt 1 -or $journal.sequence -ne $sequence.sequence -or
        $journal.release_id -isnot [string] -or $journal.release_id -cnotmatch '^[a-f0-9]{64}$' -or
        $null -eq $journal.files -or $journal.files -isnot [PSCustomObject]) {
        throw 'COMMITTED_INSTALL_UNAVAILABLE'
    }
    foreach ($relative in (Get-LiveConnectionDependencies)) {
        $expected = $journal.files.PSObject.Properties[$relative]
        if ($null -eq $expected -or $expected.Value -isnot [string] -or
            $expected.Value -cnotmatch '^[a-f0-9]{64}$') { throw 'SIGNED_ENTRY_INVENTORY_MISSING' }
        $path = Assert-LiveConnectionRegularFile (Join-Path $root $relative) $root
        if ((Get-Item -LiteralPath $path).Length -gt 1048576 -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected.Value) {
            throw 'SIGNED_ENTRY_INVENTORY_CHANGED'
        }
    }
}

function New-LiveConnectionLaunchPlan {
    param([string]$ProjectRoot, [string]$Scope = '', [switch]$Replace, [switch]$Status, $Task = $null)
    if (($Status -and ($Scope -or $Replace)) -or (-not $Status -and $Scope -cnotin @('SPOT_LIVE', 'FUTURES_LIVE'))) {
        throw 'EXPLICIT_LOCAL_CONNECTION_ACTION_REQUIRED'
    }
    $root = Get-LiveConnectionSafePath $ProjectRoot
    if ($null -eq $Task) { $Task = Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent' -ErrorAction Stop }
    $agent = Get-LiveConnectionSafePath ([Environment]::ExpandEnvironmentVariables([string]$Task.Actions[0].WorkingDirectory))
    Assert-LiveConnectionSignedInstall $root $agent
    $python = Get-LiveConnectionPython $Task
    $nativeShell = Assert-LiveConnectionRegularFile (Join-Path $env:SystemRoot 'System32/cmd.exe')
    $cli = Assert-LiveConnectionRegularFile (Join-Path $root 'scripts/configure_live_connection.py') $root
    $selection = if ($Status) { ' --status' } else { ' --scope ' + $Scope }
    if ($Replace) { $selection += ' --replace' }
    # /D disables AutoRun; /V:OFF disables delayed expansion. /S strips the outer
    # command quotes, preserving the individually quoted executable/script.
    $arguments = '/D /V:OFF /S /K ""' + $python + '" -I -B "' + $cli + '"' + $selection + '"'
    return [PSCustomObject]@{ FilePath=$nativeShell; Arguments=$arguments; WorkingDirectory=$root; WindowStyle='Normal' }
}

function Start-LiveConnectionConsole($Plan) {
    # A visible, independent native console is required for the owner's hidden
    # input. No stdin pipe, output capture, transcript or trading process.
    Start-Process -FilePath $Plan.FilePath -ArgumentList $Plan.Arguments -WorkingDirectory $Plan.WorkingDirectory -WindowStyle Normal | Out-Null
}

try {
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $plan = New-LiveConnectionLaunchPlan -ProjectRoot $projectRoot -Scope $Scope -Replace:$Replace -Status:$Status
    Start-LiveConnectionConsole $plan
} catch {
    throw 'LOCAL_PROTECTED_CONNECTION_CONSOLE_UNAVAILABLE'
}
