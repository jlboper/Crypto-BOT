param([Parameter(Mandatory = $true)][string]$SourcePath, [switch]$Automatic, [switch]$ForceRestart)

$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $SourcePath).Path
$helper = Join-Path $source 'scripts\agent_self_heal.ps1'
if (-not (Test-Path -LiteralPath $helper)) {
    throw 'El bot instalado no incluye todavía la autoreparación firmada del agente.'
}
$result = & $helper -SourcePath $source -ForceRestart:$ForceRestart
if ($LASTEXITCODE -ne 0) {
    throw 'No se pudo completar la autoreparación del agente remoto.'
}
Write-Output ($result | Out-String).Trim()
