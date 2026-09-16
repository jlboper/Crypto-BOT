$ErrorActionPreference = 'Stop'
$portalState = Join-Path (Split-Path $PSScriptRoot -Parent) 'data'
New-Item -ItemType Directory -Path $portalState -Force | Out-Null
Set-Content -LiteralPath (Join-Path $portalState 'REMOTE_STOP') -Value 'Stop outbound agent only' -Encoding utf8
Write-Output 'Stop requested for the remote agent. The trading engine and its pause switch are unchanged.'
