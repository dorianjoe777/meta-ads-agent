param(
    [string]$InstallDir = "",
    [ValidateSet("auto", "existing", "new")]
    [string]$InstanceMode = "auto"
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
    param([string]$InstanceSlug = "default")
    $machine = "{0}:{1}:{2}" -f $env:COMPUTERNAME, [System.Environment]::MachineName, $InstanceSlug
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($machine)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant().Substring(0, 24)
}

function Get-HostLanIp {
    try {
        $socket = New-Object System.Net.Sockets.Socket([System.Net.Sockets.AddressFamily]::InterNetwork, [System.Net.Sockets.SocketType]::Dgram, [System.Net.Sockets.ProtocolType]::Udp)
        $socket.Connect("8.8.8.8", 80)
        $ip = $socket.LocalEndPoint.Address.ToString()
        $socket.Close()
        return $ip
    } catch {
        return ""
    }
}

function Get-SafeInstanceSlug {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { $Value = "default" }
    $slug = ([regex]::Replace($Value.ToLowerInvariant(), "[^a-z0-9]+", "-")).Trim("-")
    if ([string]::IsNullOrWhiteSpace($slug)) { return "default" }
    return $slug.Substring(0, [Math]::Min(32, $slug.Length))
}

function Get-FreeDashboardPort {
    param([int]$StartPort = 7871)
    for ($port = $StartPort; $port -lt ($StartPort + 100); $port++) {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        try {
            $listener.Start()
            return $port
        } catch {
        } finally {
            $listener.Stop()
        }
    }
    throw "No encontré un puerto libre para la nueva instancia."
}

function Select-InstanceProfile {
    param(
        [string]$BaseDir,
        [string]$RequestedMode
    )
    $existing = (Test-Path (Join-Path $BaseDir ".env")) -or (Test-Path (Join-Path $BaseDir "docker-compose.yml"))
    $mode = if ($env:META_ADS_INSTANCE_MODE) { $env:META_ADS_INSTANCE_MODE } else { $RequestedMode }
    $mode = $mode.ToLowerInvariant()
    $script:InstanceIsNew = $false
    $script:InstanceExists = $existing
    $script:InstanceDir = $BaseDir

    if ($existing -and $mode -eq "auto") {
        Write-Host ""
        Write-Host "Ya existe una instancia de Admira IA en: $BaseDir"
        Write-Host "1) Actualizar esa instancia (conserva sus datos y licencia)"
        Write-Host "2) Crear otra instancia aislada (nueva licencia, bot y datos)"
        $choice = Read-Host "Elige [1/2] (1)"
        $mode = if ([string]::IsNullOrWhiteSpace($choice)) { "existing" } elseif ($choice -eq "2") { "new" } else { "existing" }
    }

    $newRequested = $mode -eq "new" -or $env:META_ADS_NEW_INSTANCE -eq "true"
    if ($existing -and $newRequested) {
        $parent = Split-Path -Parent $BaseDir
        $name = Split-Path -Leaf $BaseDir
        $candidate = if ($env:META_ADS_NEW_INSTANCE_DIR) { $env:META_ADS_NEW_INSTANCE_DIR } else { Join-Path $parent "$name-2" }
        $suffix = 2
        while (Test-Path $candidate) {
            $suffix++
            $candidate = Join-Path $parent "$name-$suffix"
        }
        $script:InstanceDir = $candidate
        $script:InstanceIsNew = $true
        $script:InstanceExists = $false
    }

    $existingSlug = if (-not $script:InstanceIsNew) { Get-EnvFileValue (Join-Path $script:InstanceDir ".env") "ADMIRA_INSTANCE_SLUG" } else { "" }
    $existingPort = if (-not $script:InstanceIsNew) { Get-EnvFileValue (Join-Path $script:InstanceDir ".env") "DASHBOARD_PORT" } else { "" }
    $slugSource = if ($existingSlug) { $existingSlug } else { Split-Path -Leaf $script:InstanceDir }
    $script:InstanceSlug = Get-SafeInstanceSlug $slugSource
    if ($script:InstanceIsNew) {
        $portStart = if ($env:META_ADS_NEW_INSTANCE_PORT_START) { [int]$env:META_ADS_NEW_INSTANCE_PORT_START } else { 7871 }
        $script:InstancePort = Get-FreeDashboardPort $portStart
        $script:InstanceProject = "admira-ia-$($script:InstanceSlug)"
        $script:InstanceContainer = "admira-ia-$($script:InstanceSlug)"
        $script:InstanceVolumePrefix = "meta_ads_$($script:InstanceSlug.Replace('-', '_'))"
    } else {
        $script:InstancePort = if ($existingPort) { $existingPort } else { "7871" }
        $configuredProject = Get-EnvFileValue (Join-Path $script:InstanceDir ".env") "ADMIRA_COMPOSE_PROJECT_NAME"
        $configuredContainer = Get-EnvFileValue (Join-Path $script:InstanceDir ".env") "ADMIRA_CONTAINER_NAME"
        $configuredVolumePrefix = Get-EnvFileValue (Join-Path $script:InstanceDir ".env") "ADMIRA_VOLUME_PREFIX"
        $containerProbe = if ([string]::IsNullOrWhiteSpace($configuredContainer)) { "admira-ia" } else { $configuredContainer }
        $detectedProject = ""
        $detectedVolumePrefix = ""

        # Legacy releases used Docker Compose's implicit
        # <project>_meta_ads_* volume names. Detect them from the running
        # container before applying modern defaults, otherwise an update can
        # appear to lose every buyer setting by mounting fresh empty volumes.
        if (Get-Command docker -ErrorAction SilentlyContinue) {
            & docker inspect $containerProbe *> $null
            if ($LASTEXITCODE -eq 0) {
                $detectedProject = [string](& docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' $containerProbe 2>$null | Select-Object -First 1)
                $runtimeVolume = [string](& docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/runtime"}}{{.Name}}{{end}}{{end}}' $containerProbe 2>$null | Select-Object -First 1)
                if (-not [string]::IsNullOrWhiteSpace($runtimeVolume)) {
                    $detectedVolumePrefix = $runtimeVolume -replace '_config$', ''
                }
            }
        }

        $script:InstanceProject = if (-not [string]::IsNullOrWhiteSpace($configuredProject)) { $configuredProject } elseif (-not [string]::IsNullOrWhiteSpace($detectedProject)) { $detectedProject.Trim() } else { "admira-ia" }
        $script:InstanceContainer = $containerProbe
        $script:InstanceVolumePrefix = if (-not [string]::IsNullOrWhiteSpace($configuredVolumePrefix)) { $configuredVolumePrefix } elseif (-not [string]::IsNullOrWhiteSpace($detectedVolumePrefix)) { $detectedVolumePrefix.Trim() } else { "meta_ads" }
    }
}

function Wait-ForDashboard {
    param(
        [string]$Url = "http://127.0.0.1:7871/",
        [int]$TimeoutSeconds = 120
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }
    return $false
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

function Save-InstanceEnvValues {
    param([string]$EnvFile)
    if (!(Test-Path $EnvFile)) { return }
    $content = @(Get-Content $EnvFile)
    $updates = @{
        "ADMIRA_INSTANCE_SLUG" = $script:InstanceSlug
        "ADMIRA_COMPOSE_PROJECT_NAME" = $script:InstanceProject
        "ADMIRA_CONTAINER_NAME" = $script:InstanceContainer
        "ADMIRA_VOLUME_PREFIX" = $script:InstanceVolumePrefix
        "DASHBOARD_PORT" = $script:InstancePort
    }
    foreach ($key in $updates.Keys) {
        $value = [string]$updates[$key]
        $found = $false
        for ($index = 0; $index -lt $content.Count; $index++) {
            if ($content[$index] -match "^$([regex]::Escape($key))=") {
                $content[$index] = "$key=$value"
                $found = $true
                break
            }
        }
        if (-not $found) { $content += "$key=$value" }
    }
    Set-Content -Path $EnvFile -Value $content
}

function Get-SignedReleaseUrl {
    param(
        [string]$ResolvedInstallDir,
        [string]$TempDir,
        [bool]$ReuseExistingCredentials = $true
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

    $licenseKey = if ($env:META_ADS_LICENSE_KEY) { $env:META_ADS_LICENSE_KEY } else { "" }
    $buyerEmail = if ($env:META_ADS_LICENSE_BUYER_EMAIL) { $env:META_ADS_LICENSE_BUYER_EMAIL } else { "" }
    $deviceId = if ($env:META_ADS_LICENSE_DEVICE_ID) { $env:META_ADS_LICENSE_DEVICE_ID } else { "" }
    if ($ReuseExistingCredentials) {
        if ([string]::IsNullOrWhiteSpace($licenseKey)) { $licenseKey = Get-EnvFileValue $installEnv "LICENSE_KEY" }
        if ([string]::IsNullOrWhiteSpace($licenseKey)) { $licenseKey = Get-EnvFileValue $currentEnv "LICENSE_KEY" }
        if ([string]::IsNullOrWhiteSpace($buyerEmail)) { $buyerEmail = Get-EnvFileValue $installEnv "LICENSE_BUYER_EMAIL" }
        if ([string]::IsNullOrWhiteSpace($buyerEmail)) { $buyerEmail = Get-EnvFileValue $currentEnv "LICENSE_BUYER_EMAIL" }
        if ([string]::IsNullOrWhiteSpace($deviceId)) { $deviceId = Get-EnvFileValue $installEnv "LICENSE_DEVICE_ID" }
        if ([string]::IsNullOrWhiteSpace($deviceId)) { $deviceId = Get-EnvFileValue $currentEnv "LICENSE_DEVICE_ID" }
    }

    $licenseKey = Prompt-IfMissing "Ingresa tu licencia" $licenseKey
    $buyerEmail = Prompt-IfMissing "Ingresa el email de compra" $buyerEmail
    if ([string]::IsNullOrWhiteSpace($deviceId)) {
        $deviceId = Get-DefaultDeviceId $script:InstanceSlug
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

Select-InstanceProfile -BaseDir $InstallDir -RequestedMode $InstanceMode
$InstallDir = $script:InstanceDir

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("meta-ads-agent-" + [System.Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpDir "source.zip"
$unpackDir = Join-Path $tmpDir "unpack"
$keepDir = Join-Path $tmpDir "keep"

New-Item -ItemType Directory -Force -Path $tmpDir, $unpackDir, $keepDir | Out-Null

try {
    $reuseExistingCredentials = [bool]$script:InstanceExists
    $releaseUrl = Get-SignedReleaseUrl -ResolvedInstallDir $InstallDir -TempDir $tmpDir -ReuseExistingCredentials $reuseExistingCredentials
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

    Save-InstanceEnvValues -EnvFile (Join-Path $InstallDir ".env")

    Write-Host ""
    Write-Host "Version publicada lista en:"
    Write-Host $InstallDir
    Write-Host ""
    Write-Host "Construyendo y abriendo el dashboard..."
    if ([string]::IsNullOrWhiteSpace($env:ADMIRA_HOST_LAN_IP)) {
        $env:ADMIRA_HOST_LAN_IP = Get-HostLanIp
    }
    Push-Location $InstallDir
    try {
        # Run Docker in the background. The old foreground command kept this
        # installer PowerShell open for the entire lifetime of Admira IA.
        docker compose -p $script:InstanceProject up -d --build
        if ($LASTEXITCODE -ne 0) {
            throw "Docker no pudo iniciar Admira IA."
        }
    } finally {
        Pop-Location
    }
    $dashboardUrl = "http://127.0.0.1:$($script:InstancePort)/"
    if (Wait-ForDashboard -Url $dashboardUrl) {
        Start-Process $dashboardUrl
        Write-Host "Admira IA quedo lista. Puedes cerrar esta ventana."
    } else {
        Write-Host "Admira IA sigue iniciando en segundo plano. Abre $dashboardUrl en uno o dos minutos."
    }
} finally {
    if (Test-Path $tmpDir) {
        Remove-Item -Path $tmpDir -Recurse -Force
    }
}
