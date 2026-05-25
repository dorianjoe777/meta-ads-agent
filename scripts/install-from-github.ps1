param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$ConfigFile = Join-Path $RootDir "installer\release-bootstrap.env"

function Get-ConfigValue {
    param([string]$Key)
    if (!(Test-Path $ConfigFile)) {
        return ""
    }
    foreach ($line in Get-Content $ConfigFile) {
        if ($line -match '^\s*#' -or $line -notmatch '=') {
            continue
        }
        $parts = $line.Split('=', 2)
        if ($parts[0].Trim() -eq $Key) {
            return $parts[1].Trim()
        }
    }
    return ""
}

$bootstrapEnabled = if ($env:META_ADS_BOOTSTRAP_FROM_GITHUB) { $env:META_ADS_BOOTSTRAP_FROM_GITHUB } else { Get-ConfigValue "BOOTSTRAP_FROM_GITHUB" }
$repo = if ($env:META_ADS_GITHUB_REPO) { $env:META_ADS_GITHUB_REPO } else { Get-ConfigValue "GITHUB_RELEASE_REPO" }
$asset = if ($env:META_ADS_GITHUB_SOURCE_ASSET) { $env:META_ADS_GITHUB_SOURCE_ASSET } else { Get-ConfigValue "GITHUB_SOURCE_ASSET" }
$channel = if ($env:META_ADS_GITHUB_RELEASE_CHANNEL) { $env:META_ADS_GITHUB_RELEASE_CHANNEL } else { Get-ConfigValue "GITHUB_RELEASE_CHANNEL" }
$configuredInstallDir = if ($env:META_ADS_WINDOWS_INSTALL_DIR) { $env:META_ADS_WINDOWS_INSTALL_DIR } else { Get-ConfigValue "WINDOWS_INSTALL_DIR" }

if ([string]::IsNullOrWhiteSpace($bootstrapEnabled)) {
    $bootstrapEnabled = "false"
}

if ($bootstrapEnabled.ToLowerInvariant() -ne "true") {
    exit 42
}

if ([string]::IsNullOrWhiteSpace($repo) -or $repo -eq "REPLACE_WITH_GITHUB_REPO") {
    Write-Host "Bootstrap de GitHub no esta configurado en este paquete. Usare la copia incluida."
    exit 42
}

if ([string]::IsNullOrWhiteSpace($asset)) {
    $asset = "MetaAdsAgent-source.zip"
}

if ([string]::IsNullOrWhiteSpace($channel)) {
    $channel = "latest"
}

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    if (![string]::IsNullOrWhiteSpace($configuredInstallDir)) {
        $InstallDir = $configuredInstallDir
    } else {
        $InstallDir = Join-Path $env:LOCALAPPDATA "Meta Ads Agent"
    }
}

if ($channel -eq "latest") {
    $releaseUrl = "https://github.com/$repo/releases/latest/download/$asset"
} else {
    $releaseUrl = "https://github.com/$repo/releases/download/$channel/$asset"
}

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("meta-ads-agent-" + [System.Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpDir "source.zip"
$unpackDir = Join-Path $tmpDir "unpack"
$keepDir = Join-Path $tmpDir "keep"

New-Item -ItemType Directory -Force -Path $tmpDir, $unpackDir, $keepDir | Out-Null

try {
    Write-Host "Descargando la ultima version publicada desde GitHub..."
    Write-Host $releaseUrl
    Invoke-WebRequest -Uri $releaseUrl -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $unpackDir -Force

    $preservePaths = @(
        ".env",
        "ad-config.json",
        "dashboard\data",
        "brand_guides",
        "logs",
        "output"
    )

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

    foreach ($relPath in $preservePaths) {
        $sourcePath = Join-Path $InstallDir $relPath
        $keepPath = Join-Path $keepDir $relPath
        if (Test-Path $sourcePath) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $keepPath) | Out-Null
            Move-Item -Path $sourcePath -Destination $keepPath -Force
        }
    }

    Copy-Item -Path (Join-Path $unpackDir "*") -Destination $InstallDir -Recurse -Force

    foreach ($relPath in $preservePaths) {
        $keepPath = Join-Path $keepDir $relPath
        $targetPath = Join-Path $InstallDir $relPath
        if (Test-Path $keepPath) {
            if (Test-Path $targetPath) {
                Remove-Item -Path $targetPath -Recurse -Force
            }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetPath) | Out-Null
            Move-Item -Path $keepPath -Destination $targetPath -Force
        }
    }

    if (!(Test-Path (Join-Path $InstallDir ".env")) -and (Test-Path (Join-Path $InstallDir ".env.example"))) {
        Copy-Item (Join-Path $InstallDir ".env.example") (Join-Path $InstallDir ".env")
    }
    if (!(Test-Path (Join-Path $InstallDir "ad-config.json")) -and (Test-Path (Join-Path $InstallDir "ad-config.example.json"))) {
        Copy-Item (Join-Path $InstallDir "ad-config.example.json") (Join-Path $InstallDir "ad-config.json")
    }

    Write-Host ""
    Write-Host "Version publicada lista en:"
    Write-Host $InstallDir
    Write-Host ""
    Write-Host "Construyendo y abriendo el dashboard..."
    Push-Location $InstallDir
    try {
        docker compose up --build
    } finally {
        Pop-Location
    }
} finally {
    if (Test-Path $tmpDir) {
        Remove-Item -Path $tmpDir -Recurse -Force
    }
}
