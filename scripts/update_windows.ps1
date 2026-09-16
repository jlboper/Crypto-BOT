[CmdletBinding()]
param([string]$PackagePath, [string]$TargetProjectRoot, [switch]$SkipConfirmation)
$ErrorActionPreference = 'Stop'
$ProjectRoot = if ($TargetProjectRoot) { (Resolve-Path -LiteralPath $TargetProjectRoot).Path } else { (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path }
if (-not $PackagePath) { throw 'Selecciona un paquete firmado usando el Update Manager; consulta DEPLOYMENT.md.' }
$PackagePath = (Resolve-Path -LiteralPath $PackagePath).Path
$ManifestPath = $PackagePath + '.manifest.json'
$PublicKeyPath = Join-Path $ProjectRoot 'data/trusted-update.pub'
if (-not (Test-Path -LiteralPath $ManifestPath) -or -not (Test-Path -LiteralPath $PublicKeyPath)) {
    throw 'Falta el manifiesto firmado o la clave pública confiable. Los ZIP sin firma están bloqueados.'
}
if (-not $SkipConfirmation) {
    if ((Read-Host 'Escribe SI para instalar con el motor y Research Lab detenidos') -ne 'SI') { throw 'Cancelado' }
}
Push-Location -LiteralPath $ProjectRoot
try {
    & py -3 -m trader.update_manager apply --root $ProjectRoot --public-key $PublicKeyPath --package $PackagePath --manifest $ManifestPath
    if ($LASTEXITCODE -ne 0) { throw 'La actualización firmada falló o hay un proceso activo. Consulta el registro de recuperación.' }
    Write-Host 'ACTUALIZACION COMPLETADA CORRECTAMENTE'
    Write-Host 'Código instalado sin iniciar procesos. La salud del motor aún requiere validación.'
} finally { Pop-Location }
