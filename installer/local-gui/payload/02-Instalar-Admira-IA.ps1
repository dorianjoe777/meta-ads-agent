[CmdletBinding()]
param(
  [string] $BuyerEmail = '',
  [switch] $TransferLicense,
  [string] $CredentialFile = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$licenseServer = 'https://admiraia.uboost.lat'
$stateRoot = Join-Path $env:ProgramData 'AdmiraIA\SelfService'
$logsRoot = Join-Path $stateRoot 'logs'
$defaultInstallRoot = Join-Path $env:LOCALAPPDATA 'AdmiraIA\app'
$instancesRoot = Join-Path $env:LOCALAPPDATA 'AdmiraIA\instances'
$installRoot = $defaultInstallRoot
$watchdogRoot = Join-Path $env:LOCALAPPDATA 'AdmiraIA'
$watchdogPath = Join-Path $watchdogRoot 'Start-AdmiraIA-DockerDesktop.ps1'
$watchdogLauncherPath = Join-Path $watchdogRoot 'Start-AdmiraIA-DockerDesktop.vbs'
$portStatePath = Join-Path $watchdogRoot 'dashboard-port.txt'
$devicePath = Join-Path $stateRoot 'device-id.txt'
$resultPath = Join-Path $stateRoot 'install-result.json'
$taskName = 'AdmiraIA-Autostart'
$composeProject = ''
$dashboardShortcutName = 'Admira IA Dashboard.html'
$installerVersion = '1.0.8'
$defaultCredentialFile = Join-Path $env:LOCALAPPDATA 'AdmiraIA\SelfService\license-input.xml'

function Write-Step([string] $Text) {
  Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Save-InstallStage([string] $Stage, [string] $Status = 'running') {
  @{ status = $Status; stage = $Stage; updated_at = [DateTime]::UtcNow.ToString('o') } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stateRoot 'prepare-state.json') -Encoding utf8
}

function Stop-WithDiagnostic([string] $Code, [string] $Message, [int] $ExitCode = 20) {
  Write-Host "`n[$Code] $Message" -ForegroundColor Red
  @{
    status = 'blocked'
    code = $Code
    message = $Message
    updated_at = [DateTime]::UtcNow.ToString('o')
  } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
  exit $ExitCode
}

function Test-Administrator {
  return ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
  )
}

function Invoke-NativeCapture([string] $File, [string[]] $Arguments) {
  # Windows PowerShell 5 promotes native stderr lines to ErrorRecord objects.
  # Docker uses stderr for ordinary BuildKit progress, so keep native progress
  # non-terminating and decide success only from the real process exit code.
  $previousPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $output = (& $File @Arguments 2>&1 | Out-String).Trim()
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousPreference
  }
  return [pscustomobject]@{ Output = $output; ExitCode = $code }
}

function Invoke-NativeToFile([string] $File, [string[]] $Arguments, [string] $OutputPath) {
  # Do not invoke Docker through PowerShell's native-command pipeline here.
  # Windows PowerShell 5 can turn a process' stderr into a terminating
  # NativeCommandError even when the output is redirected, preventing the
  # credential-helper recovery path from inspecting Docker's real exit code.
  $renderedArguments = foreach ($argument in $Arguments) {
    $value = [string]$argument
    if ($value -match '[\r\n"]') { throw 'El instalador recibió un argumento Docker no válido.' }
    if ($value -match '\s') { '"' + $value + '"' } else { $value }
  }
  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $File
  $startInfo.Arguments = ($renderedArguments -join ' ')
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  [void]$process.Start()
  $stdoutTask = $process.StandardOutput.ReadToEndAsync()
  $stderrTask = $process.StandardError.ReadToEndAsync()
  $process.WaitForExit()
  $stdout = $stdoutTask.Result
  $stderr = $stderrTask.Result
  $content = $stdout
  if ($stderr) {
    if ($content) { $content += [Environment]::NewLine }
    $content += $stderr
  }
  [IO.File]::WriteAllText($OutputPath, $content, (New-Object Text.UTF8Encoding($false)))
  return [int]$process.ExitCode
}

function Normalize-LicenseKey([string] $Value) {
  $normalized = ([string]$Value).Trim().ToUpperInvariant()
  $normalized = $normalized -replace '[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]', '-'
  return ($normalized -replace '[^A-Z0-9-]', '')
}

function Test-LicenseKeyFormat([string] $Key) {
  $parts = ([string]$Key).Trim().ToUpperInvariant().Split('-')
  if ($parts.Count -lt 4 -or $parts[0] -ne 'MAO') { return $false }
  $supplied = ($parts[$parts.Count - 1] -replace '[^A-Z0-9]', '')
  $body = (($parts[1..($parts.Count - 2)] -join '') -replace '[^A-Z0-9]', '')
  if ($supplied.Length -ne 6 -or $body.Length -lt 8) { return $false }
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.Encoding]::UTF8.GetBytes("meta-ads-operator-v1:$body")
    $hash = $sha.ComputeHash($bytes)
    $expected = ([BitConverter]::ToString($hash).Replace('-', '').Substring(0, 6)).ToUpperInvariant()
    return $supplied -eq $expected
  } finally {
    $sha.Dispose()
  }
}

function Read-MaskedText([string] $Prompt) {
  Write-Host -NoNewline "${Prompt}: "
  $builder = New-Object Text.StringBuilder
  try {
    while ($true) {
      $key = [Console]::ReadKey($true)
      if ($key.Key -eq [ConsoleKey]::Enter) { break }
      if ($key.Key -eq [ConsoleKey]::Backspace) {
        if ($builder.Length -gt 0) {
          $builder.Length--
          Write-Host -NoNewline "`b `b"
        }
        continue
      }
      if (
        $key.Key -eq [ConsoleKey]::C -and
        ($key.Modifiers -band [ConsoleModifiers]::Control)
      ) {
        throw 'Entrada cancelada por el usuario.'
      }
      if (-not [char]::IsControl($key.KeyChar)) {
        [void]$builder.Append($key.KeyChar)
        Write-Host -NoNewline '*'
      }
    }
  } finally {
    Write-Host
  }
  return $builder.ToString()
}

function Load-LicenseInput([string] $Path) {
  if (-not (Test-Path -LiteralPath $Path)) { throw 'No se encontró el registro protegido de la licencia.' }
  $record = Import-Clixml -LiteralPath $Path
  $email = if ($record.UserName) { [string]$record.UserName } else { [string]$record.BuyerEmail }
  $secure = if ($record.Password) { $record.Password } else { $record.License }
  if (-not $email -or -not $secure) { throw 'El registro protegido de la licencia está incompleto.' }
  $handle = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    $license = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($handle)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($handle)
  }
  return [pscustomobject]@{
    BuyerEmail = $email.Trim().ToLowerInvariant()
    License = Normalize-LicenseKey $license
  }
}

function Get-InstanceId([string] $Email, [string] $LicenseKey) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.Encoding]::UTF8.GetBytes("admira-instance-v1:$($Email.ToLowerInvariant()):$LicenseKey")
    return ([BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').Substring(0, 16)).ToLowerInvariant()
  } finally { $sha.Dispose() }
}

function Select-InstancePaths([string] $Email, [string] $LicenseKey, [string] $DockerCli) {
  $legacyEnvPath = Join-Path $defaultInstallRoot '.env'
  $legacyKey = ''
  if (Test-Path -LiteralPath $legacyEnvPath) {
    $legacyLine = @(Get-Content -LiteralPath $legacyEnvPath -ErrorAction SilentlyContinue |
      Where-Object { $_ -match '^LICENSE_KEY=' } | Select-Object -First 1)
    if ($legacyLine) { $legacyKey = Normalize-LicenseKey (($legacyLine -join '') -replace '^LICENSE_KEY=', '') }
  }
  $instanceId = Get-InstanceId -Email $Email -LicenseKey $LicenseKey
  $reuseLegacy = $legacyKey -and ($legacyKey -eq $LicenseKey)
  if ($reuseLegacy) {
    $script:installRoot = $defaultInstallRoot
    $script:watchdogRoot = Join-Path $env:LOCALAPPDATA 'AdmiraIA'
    $script:devicePath = Join-Path $stateRoot 'device-id.txt'
    $script:taskName = 'AdmiraIA-Autostart'
    $script:composeProject = ''
    $script:dashboardShortcutName = 'Admira IA Dashboard.html'
    $existing = @(& $DockerCli ps -aq --filter "label=com.docker.compose.project.working_dir=$defaultInstallRoot" 2>$null | Select-Object -First 1)
    if ($existing) {
      $project = (& $DockerCli inspect $existing --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>$null | Out-String).Trim()
      if ($project -and $project -notmatch '[^a-zA-Z0-9_.-]') { $script:composeProject = $project }
    }
  } else {
    $script:installRoot = Join-Path (Join-Path $instancesRoot $instanceId) 'app'
    $script:watchdogRoot = Join-Path $instancesRoot $instanceId
    $script:devicePath = Join-Path $script:watchdogRoot 'device-id.txt'
    $script:taskName = "AdmiraIA-Autostart-$instanceId"
    $script:composeProject = "admira-ia-$instanceId"
    $script:dashboardShortcutName = "Admira IA Dashboard $instanceId.html"
  }
  $script:watchdogPath = Join-Path $script:watchdogRoot 'Start-AdmiraIA-DockerDesktop.ps1'
  $script:watchdogLauncherPath = Join-Path $script:watchdogRoot 'Start-AdmiraIA-DockerDesktop.vbs'
  $script:portStatePath = Join-Path $script:watchdogRoot 'dashboard-port.txt'
}

function Get-DockerCli {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\resources\bin\docker.exe'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
  )
  $found = @($candidates | Where-Object { Test-Path $_ }) | Select-Object -First 1
  if ($found) { return $found }
  $command = Get-Command docker.exe -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  return $null
}

function Add-DockerCredentialHelperToPath([string] $DockerCli) {
  # Docker Desktop places docker.exe and docker-credential-desktop.exe in the
  # same resources\\bin directory. A process started before Docker finished
  # installing may have an older PATH, so Docker finds the CLI but not its
  # credential helper when BuildKit pulls a public base image.
  $dockerBin = Split-Path -Parent $DockerCli
  $helper = Join-Path $dockerBin 'docker-credential-desktop.exe'
  if (-not (Test-Path -LiteralPath $helper)) { return $false }
  $separator = [IO.Path]::PathSeparator
  $pathEntries = @($env:PATH -split [regex]::Escape([string]$separator))
  if ($pathEntries -notcontains $dockerBin) {
    $env:PATH = "$dockerBin$separator$env:PATH"
  }
  return $true
}

function Enable-AnonymousDockerConfig {
  # Do not edit the user's Docker configuration or credential store. This
  # isolated config is only used by this elevated installer process to pull
  # Admira's public base images when Docker Desktop's credential helper is not
  # yet available after a fresh install.
  $safeRoot = Join-Path $env:TEMP ('AdmiraIA-DockerCli-' + [Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $safeRoot -Force | Out-Null
  $safeConfig = @{ auths = @{} }
  $sourceRoot = if ($env:DOCKER_CONFIG) { $env:DOCKER_CONFIG } else { Join-Path $env:USERPROFILE '.docker' }
  $sourcePath = Join-Path $sourceRoot 'config.json'
  if (Test-Path -LiteralPath $sourcePath) {
    try {
      $source = Get-Content -Raw -LiteralPath $sourcePath | ConvertFrom-Json
      $context = [string]$source.currentContext
      if ($context -match '^[A-Za-z0-9._-]+$') { $safeConfig.currentContext = $context }
    } catch { }
  }
  $safeConfig | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $safeRoot 'config.json') -Encoding utf8
  $env:DOCKER_CONFIG = $safeRoot
}

function Get-DockerDesktop {
  return @(
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\Docker Desktop.exe'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

function Wait-Docker([string] $DockerCli, [int] $Minutes = 15) {
  $desktop = Get-DockerDesktop
  if ($desktop) { Start-Process -FilePath $desktop -ErrorAction SilentlyContinue }
  $deadline = [DateTime]::UtcNow.AddMinutes($Minutes)
  do {
    try {
      $result = Invoke-NativeCapture -File $DockerCli -Arguments @('info', '--format', '{{.ServerVersion}}')
      if ($result.ExitCode -eq 0) { return $true }
    } catch { }
    Start-Sleep -Seconds 5
  } while ([DateTime]::UtcNow -lt $deadline)
  return $false
}

function Test-DockerPortAllocated([int] $Port) {
  $docker = Get-DockerCli
  if (-not $docker) { return $false }
  $result = Invoke-NativeCapture -File $docker -Arguments @('ps', '--format', '{{.Ports}}')
  if ($result.ExitCode -ne 0) { return $false }
  return $result.Output -match "(?m)(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]|::):$Port->"
}

function Test-CurrentInstanceUsesPort([int] $Port) {
  $docker = Get-DockerCli
  if (-not $docker) { return $false }
  $arguments = @('ps')
  if ($composeProject) {
    $arguments += @('--filter', "label=com.docker.compose.project=$composeProject")
  } else {
    $arguments += @('--filter', "label=com.docker.compose.project.working_dir=$installRoot")
  }
  $arguments += @('--format', '{{.Ports}}')
  $result = Invoke-NativeCapture -File $docker -Arguments $arguments
  if ($result.ExitCode -ne 0) { return $false }
  return $result.Output -match "(?m)(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]|::):$Port->"
}

function Get-FreeDashboardPort {
  if (Test-Path $portStatePath) {
    $saved = (Get-Content -Raw -LiteralPath $portStatePath -ErrorAction SilentlyContinue).Trim()
    if ($saved -match '^[0-9]{4,5}$') {
      if (Test-DockerPortAllocated -Port ([int]$saved)) {
        if (Test-CurrentInstanceUsesPort -Port ([int]$saved)) { return [int]$saved }
      } else {
      try {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, [int]$saved)
        $listener.Start()
        $listener.Stop()
        return [int]$saved
      } catch {
          # A non-Docker process owns the saved port; choose another below.
        }
      }
    }
  }
  foreach ($port in 7871..7890) {
    if (Test-DockerPortAllocated -Port $port) { continue }
    $listener = $null
    try {
      $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
      $listener.Start()
      return $port
    } catch { }
    finally { if ($listener) { try { $listener.Stop() } catch { } } }
  }
  throw 'No hay un puerto disponible entre 7871 y 7890.'
}

function Set-EnvValues([string] $Path, [hashtable] $Updates) {
  $lines = if (Test-Path $Path) { @(Get-Content -LiteralPath $Path) } else { @() }
  foreach ($key in $Updates.Keys) {
    $rendered = "$key=$($Updates[$key])"
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
      if ($lines[$index] -match "^$([regex]::Escape($key))=") {
        $lines[$index] = $rendered
        $found = $true
        break
      }
    }
    if (-not $found) { $lines += $rendered }
  }
  $content = ($lines -join "`n").TrimEnd() + "`n"
  [IO.File]::WriteAllText($Path, $content, (New-Object Text.UTF8Encoding($false)))
}

function Get-LicenseRelease([string] $LicenseKey, [string] $Email, [string] $DeviceId, [bool] $Transfer) {
  $body = @{
    license_key = $LicenseKey
    buyer_email = $Email
    device_id = $DeviceId
    asset_name = 'MetaAdsAgent-source.zip'
    channel = 'stable'
    transfer_device = $Transfer
  } | ConvertTo-Json
  return Invoke-RestMethod -Method Post -Uri "$licenseServer/api/license/release" -ContentType 'application/json' -Body $body -TimeoutSec 90
}

function Write-DashboardHtml([int] $Port) {
  $desktop = [Environment]::GetFolderPath('Desktop')
  if (-not $desktop) { $desktop = Join-Path $env:PUBLIC 'Desktop' }
  New-Item -ItemType Directory -Path $desktop -Force | Out-Null
  $url = "http://localhost:$Port"
  $safe = [System.Net.WebUtility]::HtmlEncode($url)
  $html = '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=' + $safe + '"><title>Admira IA</title></head><body><p>Abriendo Admira IA… <a href="' + $safe + '">Continuar</a></p></body></html>'
  $path = Join-Path $desktop $dashboardShortcutName
  [IO.File]::WriteAllText($path, $html + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
  return $path
}

if (-not (Test-Administrator)) {
  Write-Host 'Solicitando permisos de administrador...' -ForegroundColor Yellow
  $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  if ($BuyerEmail) { $arguments += " -BuyerEmail `"$BuyerEmail`"" }
  if ($TransferLicense) { $arguments += ' -TransferLicense' }
  Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments
  exit 0
}

New-Item -ItemType Directory -Path $logsRoot -Force | Out-Null
Start-Transcript -Path (Join-Path $logsRoot 'install.log') -Append | Out-Null
$plainLicense = ''

try {
  Write-Host "Instalador de Admira IA v$installerVersion" -ForegroundColor Cyan
  if (-not $CredentialFile) { $CredentialFile = $defaultCredentialFile }
  $savedLicense = Load-LicenseInput -Path $CredentialFile
  $BuyerEmail = $savedLicense.BuyerEmail
  $plainLicense = $savedLicense.License
  Write-Step 'Verificando Docker Desktop'
  $docker = Get-DockerCli
  if (-not $docker) { Stop-WithDiagnostic 'ADM-DOCKER-101' 'Docker Desktop no está instalado. Vuelve a abrir AdmiraIA-Installer.exe para preparar el equipo.' }
  [void](Add-DockerCredentialHelperToPath -DockerCli $docker)
  if (-not (Wait-Docker -DockerCli $docker)) {
    Stop-WithDiagnostic 'ADM-DOCKER-102' 'Docker Desktop está instalado, pero el motor no respondió.'
  }
  Select-InstancePaths -Email $BuyerEmail -LicenseKey $plainLicense -DockerCli $docker
  New-Item -ItemType Directory -Path $installRoot,$watchdogRoot -Force | Out-Null

  Write-Step 'Activando la licencia'
  Save-InstallStage 'license_release'
  if (-not $BuyerEmail) { $BuyerEmail = (Read-Host 'Correo usado para comprar Admira IA').Trim().ToLowerInvariant() }
  if ($BuyerEmail -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
    Stop-WithDiagnostic 'ADM-LICENSE-101' 'El correo no tiene un formato válido.'
  }
  if (-not $plainLicense) {
    foreach ($licenseAttempt in 1..3) {
      $plainLicense = Normalize-LicenseKey (Read-MaskedText 'Licencia de Admira IA (no se mostrará en pantalla)')
      if (Test-LicenseKeyFormat $plainLicense) { break }
      $plainLicense = ''
      if ($licenseAttempt -lt 3) {
        Write-Host 'La clave no llegó completa o contiene caracteres incorrectos. Cópiala otra vez sin comillas.' -ForegroundColor Yellow
      }
    }
  }
  if ([string]::IsNullOrWhiteSpace($plainLicense)) {
    Stop-WithDiagnostic 'ADM-LICENSE-102' 'No se recibió una licencia completa y válida después de tres intentos.'
  }

  if (-not (Test-Path $devicePath)) {
    [Guid]::NewGuid().ToString('N') | Set-Content -LiteralPath $devicePath -Encoding ascii
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls.exe $devicePath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' "*${currentSid}:F" | Out-Null
  }
  $deviceId = (Get-Content -Raw -LiteralPath $devicePath).Trim()
  $release = $null
  try {
    $release = Get-LicenseRelease -LicenseKey $plainLicense -Email $BuyerEmail -DeviceId $deviceId -Transfer ([bool]$TransferLicense)
  } catch {
    Stop-WithDiagnostic 'ADM-LICENSE-104' 'No se pudo contactar el servidor de licencias de Admira IA.'
  }
  if (
    -not $release.valid -and
    $release.status -eq 'device_limit' -and
    $release.transfer_available -and
    -not $TransferLicense
  ) {
    Write-Host 'La licencia ya está registrada en otra instalación.' -ForegroundColor Yellow
    $answer = Read-Host '¿Transferirla a esta PC? Escribe TRANSFERIR para confirmar'
    if ($answer -eq 'TRANSFERIR') {
      $release = Get-LicenseRelease -LicenseKey $plainLicense -Email $BuyerEmail -DeviceId $deviceId -Transfer $true
    }
  }
  if (-not $release.valid -or -not $release.download_url -or -not $release.sha256) {
    $safeStatus = ([string]$release.status -replace '[^a-zA-Z0-9_-]', '').ToLowerInvariant()
    if (-not $safeStatus) { $safeStatus = 'unknown' }
    $safeDetail = ([string]$release.detail).Trim()
    if (-not $safeDetail -or $safeDetail.Length -gt 240) {
      $safeDetail = 'El servidor no autorizó una descarga estable de Admira IA.'
    }
    Stop-WithDiagnostic 'ADM-LICENSE-103' "$safeDetail Estado: $safeStatus."
  }

  Write-Step 'Descargando y verificando Admira IA'
  Save-InstallStage 'download_release'
  $temp = Join-Path $env:TEMP ("AdmiraIA-" + [Guid]::NewGuid().ToString('N'))
  $zipPath = Join-Path $temp 'AdmiraIA.zip'
  $unpack = Join-Path $temp 'unpack'
  New-Item -ItemType Directory -Path $unpack -Force | Out-Null
  Invoke-WebRequest -UseBasicParsing -Uri ([string]$release.download_url) -OutFile $zipPath -TimeoutSec 900
  $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
  if ($actualHash -ne ([string]$release.sha256).ToLowerInvariant()) {
    Stop-WithDiagnostic 'ADM-RELEASE-101' 'La descarga no coincide con el SHA-256 firmado.'
  }
  Expand-Archive -LiteralPath $zipPath -DestinationPath $unpack -Force
  $composeFiles = @(Get-ChildItem -Path $unpack -Filter 'docker-compose.yml' -File -Recurse)
  if ($composeFiles.Count -ne 1) { Stop-WithDiagnostic 'ADM-RELEASE-102' 'El paquete no contiene una estructura reconocible.' }
  $sourceRoot = $composeFiles[0].Directory.FullName
  if (-not (Test-Path (Join-Path $sourceRoot 'Dockerfile'))) {
    Stop-WithDiagnostic 'ADM-RELEASE-103' 'El paquete no contiene el Dockerfile esperado.'
  }

  Write-Step 'Preparando la configuración local'
  $preservedEnv = if (Test-Path (Join-Path $installRoot '.env')) {
    Get-Content -Raw -LiteralPath (Join-Path $installRoot '.env')
  } else {
    $null
  }
  Copy-Item -Path (Join-Path $sourceRoot '*') -Destination $installRoot -Recurse -Force
  $envPath = Join-Path $installRoot '.env'
  if ($null -ne $preservedEnv) {
    [IO.File]::WriteAllText($envPath, $preservedEnv, (New-Object Text.UTF8Encoding($false)))
  } elseif (-not (Test-Path $envPath)) {
    $example = Join-Path $installRoot '.env.example'
    if (Test-Path $example) { Copy-Item -LiteralPath $example -Destination $envPath }
    else { New-Item -ItemType File -Path $envPath | Out-Null }
  }
  $port = Get-FreeDashboardPort
  $envUpdates = @{
    LICENSE_KEY = $plainLicense
    LICENSE_BUYER_EMAIL = $BuyerEmail
    LICENSE_SERVER_URL = $licenseServer
    LICENSE_DEVICE_ID = $deviceId
    LICENSE_REQUIRED_FOR_LIVE = 'true'
    META_ADS_AGENT_VERSION = [string]$release.version
    DASHBOARD_HOST = '0.0.0.0'
    DASHBOARD_PORT = [string]$port
    ALLOW_PUBLIC_DASHBOARD = 'true'
    LAN_ACCESS_ENABLED = 'false'
    LIVE_ACTIONS_ENABLED = 'false'
    TELEGRAM_AGENT_ENABLED = 'false'
    TELEGRAM_AGENT_MODE = 'hermes_gateway'
  }
  if ($composeProject) { $envUpdates.COMPOSE_PROJECT_NAME = $composeProject }
  Set-EnvValues -Path $envPath -Updates $envUpdates
  $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  & icacls.exe $envPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' "*${currentSid}:F" | Out-Null

  $composePath = Join-Path $installRoot 'docker-compose.yml'
  $compose = Get-Content -Raw -LiteralPath $composePath
  $lower = $compose.ToLowerInvariant()
  foreach ($forbidden in @('/var/run/docker.sock', 'privileged: true', 'network_mode: host')) {
    if ($lower.Contains($forbidden)) { Stop-WithDiagnostic 'ADM-SECURITY-101' "El paquete contiene una opción no permitida: $forbidden" }
  }
  $portPatterns = @(
    '(?m)^(\s*-\s*)["'']?7871:7871["'']?\s*$',
    '(?m)^(\s*-\s*)["'']?0\.0\.0\.0:7871:7871["'']?\s*$',
    '(?m)^(\s*-\s*)["'']?\$\{DASHBOARD_PORT:-7871\}:7871["'']?\s*$',
    '(?m)^(\s*-\s*)["'']?127\.0\.0\.1:\$\{DASHBOARD_PORT:-7871\}:7871["'']?\s*$',
    '(?m)^(\s*-\s*)["'']?0\.0\.0\.0:\$\{DASHBOARD_PORT:-7871\}:7871["'']?\s*$'
  )
  $replaced = $false
  foreach ($pattern in $portPatterns) {
    if ([regex]::IsMatch($compose, $pattern)) {
      $compose = [regex]::Replace(
        $compose,
        $pattern,
        { param($match) $match.Groups[1].Value + '"127.0.0.1:${DASHBOARD_PORT:-7871}:7871"' },
        1
      )
      $replaced = $true
      break
    }
  }
  if (-not $replaced) { Stop-WithDiagnostic 'ADM-RELEASE-104' 'No se encontró el mapeo esperado del dashboard.' }
  if ($compose -notmatch 'no-new-privileges:true') {
    $compose = $compose -replace '    restart: unless-stopped', "    restart: unless-stopped`n    security_opt:`n      - no-new-privileges:true`n    cap_drop:`n      - ALL"
  }
  [IO.File]::WriteAllText($composePath, $compose, (New-Object Text.UTF8Encoding($false)))
  [string]$port | Set-Content -LiteralPath $portStatePath -Encoding ascii
  $composeArgs = @('compose', '--progress', 'plain')
  if ($composeProject) { $composeArgs += @('-p', $composeProject) }
  $env:BUILDKIT_PROGRESS = 'plain'

  Write-Step 'Construyendo e iniciando Admira IA'
  Save-InstallStage 'build_container'
  Push-Location $installRoot
  try {
    $rawComposePath = Join-Path $logsRoot 'compose-build.raw.log'
    if (Test-Path -LiteralPath $rawComposePath) { Remove-Item -LiteralPath $rawComposePath -Force -ErrorAction SilentlyContinue }
    $buildArguments = @($composeArgs + @('up', '-d', '--build'))
    $composeExitCode = Invoke-NativeToFile -File $docker -Arguments $buildArguments -OutputPath $rawComposePath
    $composeOutput = if (Test-Path -LiteralPath $rawComposePath) {
      (Get-Content -Raw -LiteralPath $rawComposePath -ErrorAction SilentlyContinue).Trim()
    } else { '' }
    if (
      $composeExitCode -ne 0 -and
      $composeOutput -match '(?is)docker-credential-[^\s"'']+.*executable file not found'
    ) {
      Write-Host 'Docker Desktop aún no expone su ayudante de credenciales. Reintentando la imagen pública con una configuración temporal...' -ForegroundColor Yellow
      Enable-AnonymousDockerConfig
      $composeExitCode = Invoke-NativeToFile -File $docker -Arguments $buildArguments -OutputPath $rawComposePath
      $composeOutput = if (Test-Path -LiteralPath $rawComposePath) {
        (Get-Content -Raw -LiteralPath $rawComposePath -ErrorAction SilentlyContinue).Trim()
      } else { '' }
    }
    Remove-Item -LiteralPath $rawComposePath -Force -ErrorAction SilentlyContinue
    $safeComposeOutput = $composeOutput -replace '(?i)(LICENSE_KEY|TELEGRAM_BOT_TOKEN|NVIDIA_API_KEY|META_ACCESS_TOKEN)=\S+', '$1=<redacted>'
    if ($safeComposeOutput) {
      [IO.File]::WriteAllText((Join-Path $logsRoot 'compose-build.log'), $safeComposeOutput + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    }
    if ($composeExitCode -ne 0) {
      $detail = $safeComposeOutput
      $composePsResult = Invoke-NativeCapture -File $docker -Arguments @($composeArgs + @('ps', '-a'))
      $composePs = $composePsResult.Output
      if ($composePs) { $detail += "`nCompose ps:`n$composePs" }
      if ($detail.Length -gt 2400) { $detail = $detail.Substring($detail.Length - 2400) }
      throw "docker compose terminó con código $composeExitCode. $detail"
    }
  } finally {
    Pop-Location
  }
  $dashboardUrl = "http://localhost:$port"
  Save-InstallStage 'health_check'
  $deadline = [DateTime]::UtcNow.AddMinutes(10)
  $healthy = $false
  do {
    try {
      Invoke-WebRequest -UseBasicParsing -Uri $dashboardUrl -TimeoutSec 5 | Out-Null
      $healthy = $true
      break
    } catch { Start-Sleep -Seconds 5 }
  } while ([DateTime]::UtcNow -lt $deadline)
  if (-not $healthy) {
    Push-Location $installRoot
    try { & $docker @composeArgs logs --tail 80 }
    finally { Pop-Location }
    Stop-WithDiagnostic 'ADM-RUNTIME-101' 'El contenedor inició, pero el dashboard no respondió.'
  }

  Write-Step 'Configurando el arranque automático'
  Save-InstallStage 'autostart'
  $watchdog = @'
$ErrorActionPreference = 'SilentlyContinue'
$installRoot = '__INSTALL_ROOT__'
$portState = '__PORT_STATE__'
$composeProject = '__COMPOSE_PROJECT__'
$shortcutName = '__DASHBOARD_SHORTCUT__'
$composeArgs = @('compose')
if ($composeProject) { $composeArgs += @('-p', $composeProject) }
function Write-DashboardHtml([int] $Port) {
  $desktopPath = [Environment]::GetFolderPath('Desktop')
  if (-not $desktopPath) { $desktopPath = Join-Path $env:PUBLIC 'Desktop' }
  if (-not (Test-Path $desktopPath)) { New-Item -ItemType Directory -Path $desktopPath -Force | Out-Null }
  $url = "http://localhost:$Port"
  $safe = [System.Net.WebUtility]::HtmlEncode($url)
  $html = '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=' + $safe + '"><title>Admira IA</title></head><body><p>Abriendo Admira IA… <a href="' + $safe + '">Continuar</a></p></body></html>'
  [IO.File]::WriteAllText((Join-Path $desktopPath $shortcutName), $html + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}
$dockerCandidates = @(
  (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
  (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\resources\bin\docker.exe'),
  (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
)
$docker = @($dockerCandidates | Where-Object { Test-Path $_ }) | Select-Object -First 1
$desktopCandidates = @(
  (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
  (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\Docker Desktop.exe'),
  (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
)
$desktop = @($desktopCandidates | Where-Object { Test-Path $_ }) | Select-Object -First 1
if ($desktop) { Start-Process -FilePath $desktop -ErrorAction SilentlyContinue }
if (-not $docker) { exit 1 }
$deadline = [DateTime]::UtcNow.AddMinutes(10)
do {
  & $docker info --format '{{.ServerVersion}}' *> $null
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Seconds 5
} while ([DateTime]::UtcNow -lt $deadline)
if ($LASTEXITCODE -ne 0) { exit 2 }
$port = (Get-Content -Raw -LiteralPath $portState -ErrorAction SilentlyContinue).Trim()
if ($port -notmatch '^[0-9]{4,5}$') { $port = '7871' }
Push-Location $installRoot
try {
  $composeOutput = (& $docker @composeArgs up -d 2>&1 | Out-String)
  $composeCode = $LASTEXITCODE
  if ($composeCode -ne 0 -and $composeOutput -match '(?i)port is already allocated|address already in use|bind.+failed') {
    $envPath = Join-Path $installRoot '.env'
    $originalEnv = Get-Content -Raw -LiteralPath $envPath
    foreach ($candidate in 7871..7890) {
      if ([string]$candidate -eq $port) { continue }
      $listener = $null
      try {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $candidate)
        $listener.Start()
      } catch {
        continue
      } finally {
        if ($listener) { try { $listener.Stop() } catch { } }
      }
      $candidateEnv = if ($originalEnv -match '(?m)^DASHBOARD_PORT=') {
        $originalEnv -replace '(?m)^DASHBOARD_PORT=.*$', "DASHBOARD_PORT=$candidate"
      } else {
        $originalEnv.TrimEnd() + "`nDASHBOARD_PORT=$candidate`n"
      }
      [IO.File]::WriteAllText($envPath, $candidateEnv, (New-Object Text.UTF8Encoding($false)))
      & $docker @composeArgs up -d --force-recreate *> $null
      if ($LASTEXITCODE -eq 0) {
        $port = [string]$candidate
        $port | Set-Content -LiteralPath $portState -Encoding ascii
        Write-DashboardHtml -Port $candidate
        $composeCode = 0
        break
      }
    }
  }
  if ($composeCode -ne 0) { exit 3 }
}
finally { Pop-Location }
$url = "http://localhost:$port"
Write-DashboardHtml -Port ([int]$port)
try { Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 10 | Out-Null }
catch {
  Push-Location $installRoot
  try { & $docker @composeArgs up -d --force-recreate *> $null }
  finally { Pop-Location }
}
'@
  $watchdog = $watchdog.Replace('__INSTALL_ROOT__', $installRoot.Replace("'", "''"))
  $watchdog = $watchdog.Replace('__PORT_STATE__', $portStatePath.Replace("'", "''"))
  $watchdog = $watchdog.Replace('__COMPOSE_PROJECT__', $composeProject.Replace("'", "''"))
  $watchdog = $watchdog.Replace('__DASHBOARD_SHORTCUT__', $dashboardShortcutName.Replace("'", "''"))
  $watchdog | Set-Content -LiteralPath $watchdogPath -Encoding utf8

  $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
  $powerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $watchdogCommand = "`"$powerShell`" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdogPath`""
  $watchdogLauncher = 'Set shell = CreateObject("WScript.Shell")' + "`r`n" +
    'shell.Run "' + $watchdogCommand.Replace('"', '""') + '", 0, False' + "`r`n"
  [IO.File]::WriteAllText($watchdogLauncherPath, $watchdogLauncher, (New-Object Text.UTF8Encoding($false)))
  $wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
  $action = New-ScheduledTaskAction -Execute $wscript -Argument "//B //Nologo `"$watchdogLauncherPath`""
  $logon = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
  $recovery = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval ([TimeSpan]::FromMinutes(5)) -RepetitionDuration ([TimeSpan]::FromDays(3650))
  $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 10 -RestartInterval ([TimeSpan]::FromMinutes(1)) -ExecutionTimeLimit ([TimeSpan]::FromMinutes(15)) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $taskName -Description 'Inicia Docker Desktop y Admira IA al entrar en Windows.' -Action $action -Trigger @($logon, $recovery) -Principal $principal -Settings $settings -Force | Out-Null

  $dashboardHtmlPath = Write-DashboardHtml -Port $port
  @{
    status = 'ok'
    release_version = [string]$release.version
    dashboard_url = $dashboardUrl
    docker_backend = 'desktop-wsl2'
    autostart = 'windows_logon'
    updated_at = [DateTime]::UtcNow.ToString('o')
  } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
  Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
  $plainLicense = ''

  Write-Host "`nADMIRA IA INSTALADA CORRECTAMENTE" -ForegroundColor Green
  Write-Host "Dashboard: $dashboardUrl"
  Start-Process $dashboardHtmlPath
  exit 0
} catch {
  $plainLicense = ''
  $message = $_.Exception.Message
  Write-Host "`n[ADM-INSTALL-999] $message" -ForegroundColor Red
  @{
    status = 'error'
    code = 'ADM-INSTALL-999'
    message = $message
    updated_at = [DateTime]::UtcNow.ToString('o')
  } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
  exit 99
} finally {
  $plainLicense = ''
  try { Stop-Transcript | Out-Null } catch { }
}
