param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('check-online','check-offline','install','restore-offer','restore')]
    [string]$Action,
    [string]$ReleaseId = '',
    [string]$StatusPath = ''
)

$ErrorActionPreference = 'Stop'
$Source = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Write-Status {
    param([hashtable]$Payload)
    if (-not $StatusPath) { return }
    $folder = Split-Path -Parent $StatusPath
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    $temp = $StatusPath + '.tmp'
    ($Payload | ConvertTo-Json -Compress -Depth 8) | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $StatusPath -Force
}

try {
    $task = Get-ScheduledTask -TaskName 'Crypto Paper Portal Agent' -ErrorAction Stop
    if (-not $task.Actions -or -not $task.Actions[0].WorkingDirectory) {
        throw 'Independent supervisor working directory unavailable'
    }
    $AgentRoot = (Resolve-Path -LiteralPath $task.Actions[0].WorkingDirectory).Path
    if ($AgentRoot -eq $Source -or -not (Test-Path -LiteralPath (Join-Path $AgentRoot 'scripts\windows_agent.py'))) {
        throw 'Independent supervisor unavailable'
    }

    $taskExecutable = [Environment]::ExpandEnvironmentVariables([string]$task.Actions[0].Execute)
    if ($taskExecutable -match '(?i)pythonw\.exe$') {
        $Python = Join-Path (Split-Path -Parent $taskExecutable) 'python.exe'
        $PythonFlags = @()
    }
    elseif ($taskExecutable -match '(?i)python\.exe$') {
        $Python = $taskExecutable
        $PythonFlags = @()
    }
    else {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) { $Python = $launcher.Source; $PythonFlags = @('-3') }
        else { $Python = (Get-Command python.exe -ErrorAction Stop).Source; $PythonFlags = @() }
    }
    if (-not (Test-Path -LiteralPath $Python) -and $Python -notmatch '(?i)py\.exe$') {
        throw 'Python runtime unavailable'
    }

    $LocalUpdater = Join-Path $Source 'scripts\local_update.py'
    if (-not (Test-Path -LiteralPath $LocalUpdater)) { throw 'Local updater unavailable' }

    $args = @($PythonFlags) + @($LocalUpdater, '--source', $Source, '--agent-root', $AgentRoot)
    switch ($Action) {
        'check-online' { $args += '--check-online' }
        'check-offline' { $args += '--check-offline' }
        'restore-offer' { $args += '--restore-offer' }
        'install' {
            if (-not $ReleaseId) { throw 'Exact release approval required' }
            $args += @('--install', $ReleaseId)
        }
        'restore' {
            if (-not $ReleaseId) { throw 'Exact restore approval required' }
            $args += @('--restore', $ReleaseId)
        }
    }

    Write-Status @{ status='running'; action=$Action; at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
    $raw = & $Python @args 2>&1
    $exit = $LASTEXITCODE
    $joined = ($raw | Out-String).Trim()
    $decoded = $null
    try { $decoded = $joined | ConvertFrom-Json } catch { }
    if ($exit -ne 0 -or -not $decoded) {
        $code = if ($decoded -and $decoded.code) { [string]$decoded.code } else { 'LOCAL_UPDATE_FAILED' }
        Write-Status @{ status='failed'; action=$Action; code=$code; at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
        if ($StatusPath) { exit 1 }
        @{status='failed';code=$code} | ConvertTo-Json -Compress
        exit 1
    }
    $payload = @{}
    foreach ($property in $decoded.PSObject.Properties) { $payload[$property.Name] = $property.Value }
    $payload['action'] = $Action
    $payload['at'] = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if (-not $payload.ContainsKey('status')) { $payload['status'] = 'completed' }
    Write-Status $payload
    if (-not $StatusPath) { $payload | ConvertTo-Json -Compress -Depth 8 }
}
catch {
    Write-Status @{ status='failed'; action=$Action; code='LOCAL_UPDATE_BRIDGE_FAILED'; at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
    if (-not $StatusPath) { @{status='failed';code='LOCAL_UPDATE_BRIDGE_FAILED'} | ConvertTo-Json -Compress }
    exit 1
}
