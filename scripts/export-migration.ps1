$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$desktop = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($desktop)) {
    $desktop = Join-Path $RootDir "migration"
}
New-Item -ItemType Directory -Force -Path $desktop | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zipPath = Join-Path $desktop "MetaAdsAgent-migracion-$stamp.zip"
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("meta-ads-migration-" + [Guid]::NewGuid().ToString("N"))
$workDir = Join-Path $tmpDir "MetaAdsAgent-migracion"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

function Copy-IfExists {
    param([string]$Source, [string]$Target)
    if (Test-Path $Source) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
        Copy-Item -Path $Source -Destination $Target -Recurse -Force
    }
}

try {
    Copy-IfExists (Join-Path $RootDir ".env") (Join-Path $workDir ".env")
    Copy-IfExists (Join-Path $RootDir "ad-config.json") (Join-Path $workDir "ad-config.json")
    Copy-IfExists (Join-Path $RootDir "dashboard\data") (Join-Path $workDir "dashboard\data")
    Copy-IfExists (Join-Path $RootDir "brand_guides") (Join-Path $workDir "brand_guides")
    Copy-IfExists (Join-Path $RootDir "output") (Join-Path $workDir "output")

    Remove-Item -Path (Join-Path $workDir "dashboard\data\license_unlock.json") -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $workDir "dashboard\data\dashboard.html") -Force -ErrorAction SilentlyContinue

    $envPath = Join-Path $workDir ".env"
    if (Test-Path $envPath) {
        $lines = Get-Content $envPath
        $found = $false
        for ($i = 0; $i -lt $lines.Length; $i++) {
            if ($lines[$i].StartsWith("LICENSE_DEVICE_ID=")) {
                $lines[$i] = "LICENSE_DEVICE_ID="
                $found = $true
            }
        }
        if (-not $found) {
            $lines += "LICENSE_DEVICE_ID="
        }
        Set-Content -Path $envPath -Value $lines
    }

    @"
Este archivo mueve la memoria local de Meta Ads Agent a otro equipo.

Puede incluir tokens y claves privadas del comprador.
LICENSE_DEVICE_ID y el desbloqueo cloud no se copian; el nuevo equipo debe validar la licencia.
"@ | Set-Content -Path (Join-Path $workDir "LEEME-MIGRACION.txt")

    Compress-Archive -Path $workDir -DestinationPath $zipPath -Force
    Write-Host "Respaldo creado:"
    Write-Host $zipPath
    Write-Host ""
    Write-Host "Este archivo contiene datos privados del comprador. Guardalo con cuidado."
} finally {
    if (Test-Path $tmpDir) {
        Remove-Item -Path $tmpDir -Recurse -Force
    }
}
