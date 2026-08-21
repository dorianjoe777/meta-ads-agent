$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$archive = Read-Host "Ruta del respaldo .zip"

if (!(Test-Path $archive)) {
    Write-Host "No encontre el respaldo: $archive"
    exit 1
}

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("meta-ads-migration-" + [Guid]::NewGuid().ToString("N"))
$backupDir = Join-Path $RootDir ("dashboard\data\import-backups\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $tmpDir, $backupDir | Out-Null

function Copy-CurrentIfExists {
    param([string]$Source, [string]$Target)
    if (Test-Path $Source) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
        Copy-Item -Path $Source -Destination $Target -Recurse -Force
    }
}

function Restore-IfExists {
    param([string]$Source, [string]$Target)
    if (Test-Path $Source) {
        if (Test-Path $Target) {
            Remove-Item -Path $Target -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
        Copy-Item -Path $Source -Destination $Target -Recurse -Force
    }
}

try {
    Expand-Archive -Path $archive -DestinationPath $tmpDir -Force
    $sourceDir = Join-Path $tmpDir "MetaAdsAgent-migracion"
    if (!(Test-Path $sourceDir)) {
        Write-Host "El archivo no parece ser un respaldo de Meta Ads Agent."
        exit 1
    }

    Copy-CurrentIfExists (Join-Path $RootDir ".env") (Join-Path $backupDir ".env")
    Copy-CurrentIfExists (Join-Path $RootDir "ad-config.json") (Join-Path $backupDir "ad-config.json")
    Copy-CurrentIfExists (Join-Path $RootDir "dashboard\data") (Join-Path $backupDir "dashboard-data")
    Copy-CurrentIfExists (Join-Path $RootDir "brand_guides") (Join-Path $backupDir "brand_guides")
    Copy-CurrentIfExists (Join-Path $RootDir "output") (Join-Path $backupDir "output")

    Restore-IfExists (Join-Path $sourceDir ".env") (Join-Path $RootDir ".env")
    Restore-IfExists (Join-Path $sourceDir "ad-config.json") (Join-Path $RootDir "ad-config.json")
    Restore-IfExists (Join-Path $sourceDir "dashboard\data") (Join-Path $RootDir "dashboard\data")
    Restore-IfExists (Join-Path $sourceDir "brand_guides") (Join-Path $RootDir "brand_guides")
    Restore-IfExists (Join-Path $sourceDir "output") (Join-Path $RootDir "output")

    Remove-Item -Path (Join-Path $RootDir "dashboard\data\license_unlock.json") -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $RootDir "dashboard\data\dashboard.html") -Force -ErrorAction SilentlyContinue

    $envPath = Join-Path $RootDir ".env"
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

    Write-Host "Datos restaurados."
    Write-Host "Respaldo del estado anterior:"
    Write-Host $backupDir
    Write-Host ""
    Write-Host "Ahora abre el dashboard y valida la licencia. Si era una licencia Individual en otro equipo, confirma la transferencia."
} finally {
    if (Test-Path $tmpDir) {
        Remove-Item -Path $tmpDir -Recurse -Force
    }
}
