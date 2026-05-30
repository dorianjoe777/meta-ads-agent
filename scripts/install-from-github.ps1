param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$ConfigFile = Join-Path $RootDir "installer\release-bootstrap.env"

function Get-Lower {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }
    return $Value.ToLowerInvariant()
}

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

function Get-EnvFileValue {
    param(
        [string]$EnvFile,
        [string]$Key
    )
    if (!(Test-Path $EnvFile)) {
        return ""
    }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*#' -or $line -notmatch '=') {
            continue
        }
        $parts = $line.Split('=', 2)
        if ($parts[0].Trim() -eq $Key) {
            return $parts[1]
        }
    }
    return ""
}

function Prompt-IfMissing {
    param(
        [string]$Label,
        [string]$CurrentValue
    )
    if (![string]::IsNullOrWhiteSpace($CurrentValue)) {
        return $CurrentValue
    }
    return Read-Host $Label
}

function Get-DefaultDeviceId {
    $machine = "{0}:{1}" -f $env:COMPUTERNAME, [System.Environment]::MachineName
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($machine)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant().Substring(0, 24)
}

function Save-BootstrapEnvValues {
    param(
        [string]$EnvFile,
        [string]$LicenseKey,
        [string]$BuyerEmail,
        [string]$DeviceId,
        [string]$LicenseServerUrl
    )
    if (!(Test-Path $EnvFile)) {
        return
    }
    $content = Get-Content $EnvFile
    $entries = @{}
    for ($index = 0; $index -lt $content.Length; $index++) {
        $line = $content[$index]
        if ($line -match '^\s*#' -or $line -notmatch '=') {
            continue
        }
        $key = $line.Split('=', 2)[0]
        $entries[$key] = $index
    }
    $updates = @{
        "LICENSE_KEY" = $LicenseKey
        "LICENSE_BUYER_EMAIL" = $BuyerEmail
        "LICENSE_DEVICE_ID" = $DeviceId
        "LICENSE_SERVER_URL" = $LicenseServerUrl
    }
    foreach ($key in $updates.Keys) {
        $value = $updates[$key]
        if ([string]::IsNullOrWhiteSpace($value)) {
            continue
        }
        if ($entries.ContainsKey($key)) {
            $currentIndex = $entries[$key]
            if ($content[$currentIndex] -eq "$key=") {
                $content[$currentIndex] = "$key=$value"
            }
        } else {
            $content += "$key=$value"
        }
    }
    Set-Content -Path $EnvFile -Value $content
}

function Get-SignedReleaseUrl {
    param(
        [string]$ResolvedInstallDir,
        [string]$TempDir
    )
    $provider = if ($env:META_ADS_BOOTSTRAP_PROVIDER) { $env:META_ADS_BOOTSTRAP_PROVIDER } else { Get-ConfigValue "BOOTSTRAP_PROVIDER" }
    $licenseServerUrl = if ($env:META_ADS_LICENSE_SERVER_URL) { $env:META_ADS_LICENSE_SERVER_URL } else { Get-ConfigValue "LICENSE_SERVER_URL" }
    $releaseEndpoint = if ($env:META_ADS_LICENSE_RELEASE_ENDPOINT) { $env:META_ADS_LICENSE_RELEASE_ENDPOINT } else { Get-ConfigValue "LICENSE_RELEASE_ENDPOINT" }
    $releaseChannel = if ($env:META_ADS_RELEASE_CHANNEL) { $env:META_ADS_RELEASE_CHANNEL } else { Get-ConfigValue "RELEASE_CHANNEL" }
    $releaseAssetName = if ($env:META_ADS_RELEASE_ASSET_NAME) { $env:META_ADS_RELEASE_ASSET_NAME } else { Get-ConfigValue "RELEASE_ASSET_NAME" }

    if ((Get-Lower $provider) -ne "license_server") {
        return $null
    }
    if ([string]::IsNullOrWhiteSpace($licenseServerUrl)) {
        Write-Host "No hay servidor de licencias configurado para preparar tu descarga protegida."
        exit 42
    }

    if ([string]::IsNullOrWhiteSpace($releaseEndpoint)) {
        $releaseEndpoint = "/api/license/release"
    }
    if ([string]::IsNullOrWhiteSpace($releaseChannel)) {
        $releaseChannel = "stable"
    }
    if ([string]::IsNullOrWhiteSpace($releaseAssetName)) {
        $releaseAssetName = "MetaAdsAgent-source.zip"
    }

    $installEnv = Join-Path $ResolvedInstallDir ".env"
    $currentEnv = Join-Path $RootDir ".env"

    $licenseKey = if ($env:META_ADS_LICENSE_KEY) { $env:META_ADS_LICENSE_KEY } else { Get-EnvFileValue $installEnv "LICENSE_KEY" }
    if ([string]::IsNullOrWhiteSpace($licenseKey)) {
        $licenseKey = Get-EnvFileValue $currentEnv "LICENSE_KEY"
    }
    $buyerEmail = if ($env:META_ADS_LICENSE_BUYER_EMAIL) { $env:META_ADS_LICENSE_BUYER_EMAIL } else { Get-EnvFileValue $installEnv "LICENSE_BUYER_EMAIL" }
    if ([string]::IsNullOrWhiteSpace($buyerEmail)) {
        $buyerEmail = Get-EnvFileValue $currentEnv "LICENSE_BUYER_EMAIL"
    }
    $deviceId = if ($env:META_ADS_LICENSE_DEVICE_ID) { $env:META_ADS_LICENSE_DEVICE_ID } else { Get-EnvFileValue $installEnv "LICENSE_DEVICE_ID" }
    if ([string]::IsNullOrWhiteSpace($deviceId)) {
        $deviceId = Get-EnvFileValue $currentEnv "LICENSE_DEVICE_ID"
    }

    $licenseKey = Prompt-IfMissing "Ingresa tu licencia" $licenseKey
    $buyerEmail = Prompt-IfMissing "Ingresa el email de compra" $buyerEmail
    if ([string]::IsNullOrWhiteSpace($deviceId)) {
        $deviceId = Get-DefaultDeviceId
    }

    if ([string]::IsNullOrWhiteSpace($licenseKey) -or [string]::IsNullOrWhiteSpace($buyerEmail)) {
        Write-Host "Necesito licencia y email para preparar tu descarga protegida."
        exit 1
    }

    $transferDevice = if ($env:META_ADS_TRANSFER_DEVICE) { (Get-Lower $env:META_ADS_TRANSFER_DEVICE) -eq "true" } else { $false }
    $bodyObject = @{
        license_key = $licenseKey
        buyer_email = $buyerEmail
        device_id = $deviceId
        channel = $releaseChannel
        asset_name = $releaseAssetName
        transfer_device = $transferDevice
    }

    $targetUrl = $licenseServerUrl.TrimEnd("/") + $releaseEndpoint
    $responsePath = Join-Path $TempDir "license-release.json"

    try {
        $response = Invoke-RestMethod -Uri $targetUrl -Method Post -ContentType "application/json" -Body ($bodyObject | ConvertTo-Json)
        $response | ConvertTo-Json -Depth 8 | Set-Content -Path $responsePath
    } catch {
        $detail = "No se pudo contactar el servidor de licencias."
        if ($_.Exception.Response) {
            try {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $raw = $reader.ReadToEnd()
                if ($raw) {
                    $parsed = $raw | ConvertFrom-Json
                    if ($parsed.detail) {
                        $detail = $parsed.detail
                    }
                }
            } catch {
            }
        }
        Write-Host $detail
        exit 1
    }

    if (-not $response.valid -and $response.status -eq "device_limit" -and $response.transfer_available -and -not $transferDevice) {
        Write-Host "Esta licencia ya esta activa en otro equipo."
        $confirm = Read-Host "Escribe SI para transferir la licencia a este equipo"
        if ($confirm.ToUpperInvariant() -eq "SI") {
            $bodyObject.transfer_device = $true
            try {
                $response = Invoke-RestMethod -Uri $targetUrl -Method Post -ContentType "application/json" -Body ($bodyObject | ConvertTo-Json)
                $response | ConvertTo-Json -Depth 8 | Set-Content -Path $responsePath
            } catch {
                Write-Host "No se pudo transferir la licencia. Contacta soporte."
                exit 1
            }
        }
    }

    if (-not $response.valid -or [string]::IsNullOrWhiteSpace($response.download_url)) {
        $detail = if ($response.detail) { $response.detail } else { "No se pudo preparar tu descarga." }
        Write-Host $detail
        exit 1
    }

    $script:BootstrapLicenseKey = $licenseKey
    $script:BootstrapBuyerEmail = $buyerEmail
    $script:BootstrapDeviceId = $deviceId
    $script:BootstrapLicenseServerUrl = $licenseServerUrl
    return $response.download_url
}

function Get-GitHubReleaseUrl {
    $bootstrapEnabled = if ($env:META_ADS_BOOTSTRAP_FROM_GITHUB) { $env:META_ADS_BOOTSTRAP_FROM_GITHUB } else { Get-ConfigValue "BOOTSTRAP_FROM_GITHUB" }
    $repo = if ($env:META_ADS_GITHUB_REPO) { $env:META_ADS_GITHUB_REPO } else { Get-ConfigValue "GITHUB_RELEASE_REPO" }
    $asset = if ($env:META_ADS_GITHUB_SOURCE_ASSET) { $env:META_ADS_GITHUB_SOURCE_ASSET } else { Get-ConfigValue "GITHUB_SOURCE_ASSET" }
    $channel = if ($env:META_ADS_GITHUB_RELEASE_CHANNEL) { $env:META_ADS_GITHUB_RELEASE_CHANNEL } else { Get-ConfigValue "GITHUB_RELEASE_CHANNEL" }

    if ((Get-Lower $bootstrapEnabled) -ne "true") {
        return $null
    }
    if ([string]::IsNullOrWhiteSpace($repo) -or $repo -eq "REPLACE_WITH_GITHUB_REPO") {
        return $null
    }
    if ([string]::IsNullOrWhiteSpace($asset)) {
        $asset = "MetaAdsAgent-source.zip"
    }
    if ([string]::IsNullOrWhiteSpace($channel)) {
        $channel = "latest"
    }
    if ($channel -eq "latest") {
        return "https://github.com/$repo/releases/latest/download/$asset"
    }
    return "https://github.com/$repo/releases/download/$channel/$asset"
}

function Test-SafeReleaseArchive {
    param([string]$ZipPath)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $maxUnpacked = 300MB
    $total = 0
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace("\", "/")
            $parts = $name.Split("/")
            $total += $entry.Length
            if ($total -gt $maxUnpacked) {
                throw "El paquete publicado es demasiado grande."
            }
            if ([string]::IsNullOrWhiteSpace($name) -or $name.StartsWith("/") -or $name.StartsWith("~") -or ($parts -contains "..")) {
                throw "El paquete publicado contiene rutas no seguras."
            }
        }
    } finally {
        $archive.Dispose()
    }
}

$configuredInstallDir = if ($env:META_ADS_WINDOWS_INSTALL_DIR) { $env:META_ADS_WINDOWS_INSTALL_DIR } else { Get-ConfigValue "WINDOWS_INSTALL_DIR" }
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    if (![string]::IsNullOrWhiteSpace($configuredInstallDir)) {
        $InstallDir = $configuredInstallDir
    } else {
        $InstallDir = Join-Path $env:LOCALAPPDATA "Meta Ads Agent"
    }
}

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("meta-ads-agent-" + [System.Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpDir "source.zip"
$unpackDir = Join-Path $tmpDir "unpack"
$keepDir = Join-Path $tmpDir "keep"

New-Item -ItemType Directory -Force -Path $tmpDir, $unpackDir, $keepDir | Out-Null

try {
    $releaseUrl = Get-SignedReleaseUrl -ResolvedInstallDir $InstallDir -TempDir $tmpDir
    if ([string]::IsNullOrWhiteSpace($releaseUrl)) {
        $allowGitHubFallback = if ($env:META_ADS_ALLOW_GITHUB_FALLBACK) { $env:META_ADS_ALLOW_GITHUB_FALLBACK } else { Get-ConfigValue "ALLOW_GITHUB_FALLBACK" }
        if ((Get-Lower $allowGitHubFallback) -eq "true") {
            $releaseUrl = Get-GitHubReleaseUrl
        }
    }

    if ([string]::IsNullOrWhiteSpace($releaseUrl)) {
        Write-Host "Este instalador no encontro una fuente de descarga publicada. Revisa la configuracion del release."
        exit 42
    }

    Write-Host "Descargando la ultima version publicada..."
    Write-Host $releaseUrl
    Invoke-WebRequest -Uri $releaseUrl -OutFile $zipPath
    Test-SafeReleaseArchive -ZipPath $zipPath
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

    Save-BootstrapEnvValues `
        -EnvFile (Join-Path $InstallDir ".env") `
        -LicenseKey $script:BootstrapLicenseKey `
        -BuyerEmail $script:BootstrapBuyerEmail `
        -DeviceId $script:BootstrapDeviceId `
        -LicenseServerUrl $script:BootstrapLicenseServerUrl

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
