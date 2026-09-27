param([string]$PythonPath = '', [string]$SourcePath = '')
$ErrorActionPreference = 'Stop'
$portalRoot = Split-Path $PSScriptRoot -Parent
$portalSource = if ($SourcePath) { (Resolve-Path -LiteralPath $SourcePath).Path } else { $portalRoot }
$portalPython = $PythonPath
if (-not $portalPython) {
    $portalCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($portalCommand) { $portalPython = $portalCommand.Source }
}
$portalTaskName = 'Crypto Paper Portal Agent'
$portalUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if (-not $portalPython -or -not (Test-Path -LiteralPath $portalPython)) { throw 'Pass -PythonPath with the reviewed pythonw.exe runtime' }
$portalExisting = Get-ScheduledTask -TaskName $portalTaskName -ErrorAction SilentlyContinue
if ($portalExisting) { throw 'Task already exists; inspect it before changing it' }
$agentScript = Join-Path $portalRoot 'scripts\windows_agent.py'
if (-not (Test-Path -LiteralPath $agentScript)) { throw 'Falta windows_agent.py en el supervisor independiente.' }
$portalArguments = '"' + $agentScript + '" --source "' + $portalSource + '" --autostart'
$portalAction = New-ScheduledTaskAction -Execute $portalPython -Argument $portalArguments -WorkingDirectory $portalRoot
$portalTrigger = New-ScheduledTaskTrigger -AtLogOn -User $portalUser
$portalTrigger.Delay = 'PT30S'
$portalPrincipal = New-ScheduledTaskPrincipal -UserId $portalUser -LogonType Interactive -RunLevel Limited
$portalSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$portalTask = New-ScheduledTask -Action $portalAction -Trigger $portalTrigger -Principal $portalPrincipal -Settings $portalSettings -Description 'Outbound HTTPS telemetry watchdog. Restarts only the independent portal agent; never starts the trading engine. User logon, no stored password.'
Register-ScheduledTask -TaskName $portalTaskName -InputObject $portalTask | Select-Object TaskName,State
Export-ScheduledTask -TaskName $portalTaskName | Set-Content -LiteralPath (Join-Path $portalRoot 'data/remote-autostart-task.xml') -Encoding utf8
