[CmdletBinding()]
param(
  [switch] $Resume,
  [switch] $AcceptDockerTerms,
  [switch] $NoRestart,
  [string] $CredentialFile = '',
  [switch] $Gui,
  [string] $GuiPath = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = Join-Path $env:ProgramData 'AdmiraIA\SelfService'
$logs = Join-Path $root 'logs'
$installedScript = Join-Path $root '01-Preparar-PC-Admira-IA.ps1'
$installedInstallerScript = Join-Path $root '02-Instalar-Admira-IA.ps1'
$installResultPath = Join-Path $root 'install-result.json'
$credentialRoot = Join-Path $env:LOCALAPPDATA 'AdmiraIA\SelfService'
$defaultCredentialFile = Join-Path $credentialRoot 'license-input.xml'
$statePath = Join-Path $root 'prepare-state.json'
$taskName = 'AdmiraIA-ContinueSetup'
$dockerInstaller = Join-Path $root 'Docker Desktop Installer.exe'
$wslInstaller = Join-Path $root 'wsl-latest-x64.msi'
$dockerTermsUrl = 'https://www.docker.com/legal/docker-subscription-service-agreement/'
$dockerDownloadUrl = 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe'
$installerVersion = '1.0.7'

# Create a bootstrap record in the user's profile before requesting elevation.
# ProgramData may not be writable yet; this path is always available, so UAC
# failures cannot leave the GUI with an empty progress bar and no logs.
$bootstrapRoot = Join-Path $env:LOCALAPPDATA 'AdmiraIA\SelfService'
New-Item -ItemType Directory -Path $bootstrapRoot -Force | Out-Null
$bootstrapLog = Join-Path $bootstrapRoot 'bootstrap.log'
$bootstrapAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
try { Add-Content -LiteralPath $bootstrapLog -Value "[$([DateTime]::UtcNow.ToString('o'))] Preparador iniciado. Admin=$bootstrapAdmin" -Encoding UTF8 } catch { }

function Write-Step([string] $Text) {
  Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Stop-WithDiagnostic([string] $Code, [string] $Message, [int] $ExitCode = 20) {
  Write-Host "`n[$Code] $Message" -ForegroundColor Red
  if (Test-Path $root) {
    @{
      status = 'blocked'
      code = $Code
      message = $Message
      updated_at = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
  }
  if ($Resume -and [Environment]::UserInteractive) {
    [void](Read-Host 'La continuación se detuvo. Presiona ENTER para cerrar esta ventana')
  }
  exit $ExitCode
}

function Save-State([string] $Stage, [string] $Status = 'running') {
  @{
    status = $Status
    stage = $Stage
    computer = $env:COMPUTERNAME
    user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    updated_at = [DateTime]::UtcNow.ToString('o')
  } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
}

function Test-Administrator {
  return ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
  )
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
  } finally { $sha.Dispose() }
}

function Read-MaskedText([string] $Prompt) {
  Write-Host -NoNewline "${Prompt}: "
  $builder = New-Object Text.StringBuilder
  try {
    while ($true) {
      $key = [Console]::ReadKey($true)
      if ($key.Key -eq [ConsoleKey]::Enter) { break }
      if ($key.Key -eq [ConsoleKey]::Backspace) {
        if ($builder.Length -gt 0) { $builder.Length--; Write-Host -NoNewline "`b `b" }
        continue
      }
      if ($key.Key -eq [ConsoleKey]::C -and ($key.Modifiers -band [ConsoleModifiers]::Control)) {
        throw 'Entrada cancelada por el usuario.'
      }
      if (-not [char]::IsControl($key.KeyChar)) {
        [void]$builder.Append($key.KeyChar)
        Write-Host -NoNewline '*'
      }
    }
  } finally { Write-Host }
  return $builder.ToString()
}

function Request-LicenseBeforeChecks {
  if ($Resume) {
    if (-not $CredentialFile) { $CredentialFile = $defaultCredentialFile }
    if (-not (Test-Path -LiteralPath $CredentialFile)) {
      throw 'No se encontró el registro protegido de la licencia para reanudar esta instalación.'
    }
    return
  }
  if (-not $CredentialFile) { $CredentialFile = $defaultCredentialFile }
  New-Item -ItemType Directory -Path (Split-Path $CredentialFile -Parent) -Force | Out-Null
  Write-Host "`nAntes de preparar Windows, registra los datos de tu compra." -ForegroundColor Cyan
  do {
    $email = (Read-Host 'Correo usado para comprar Admira IA').Trim().ToLowerInvariant()
    if ($email -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
      Write-Host 'El correo no tiene un formato válido.' -ForegroundColor Yellow
    }
  } while ($email -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$')
  $license = ''
  foreach ($attempt in 1..3) {
    $candidate = Normalize-LicenseKey (Read-MaskedText 'Licencia de Admira IA (no se mostrará en pantalla)')
    if (Test-LicenseKeyFormat $candidate) { $license = $candidate; break }
    if ($attempt -lt 3) {
      Write-Host 'La clave no llegó completa o contiene caracteres incorrectos. Cópiala otra vez sin comillas.' -ForegroundColor Yellow
    }
  }
  if (-not $license) { throw 'No se recibió una licencia completa y válida después de tres intentos.' }
  $secureLicense = ConvertTo-SecureString $license -AsPlainText -Force
  $credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $email, $secureLicense
  $credential | Export-Clixml -LiteralPath $CredentialFile -Force
  Write-Host 'Datos guardados de forma protegida. Continuando con la comprobación del equipo...' -ForegroundColor Green
}

function Invoke-NativeCapture([string] $File, [string[]] $Arguments) {
  # Windows PowerShell 5 turns text written by native programs to stderr into
  # ErrorRecord objects. With ErrorActionPreference=Stop, harmless WSL status
  # messages such as "WSL is finishing an upgrade" otherwise abort the script.
  $previousPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $output = (& $File @Arguments 2>&1 | Out-String).Trim()
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousPreference
  }
  return [PSCustomObject]@{
    Output = $output
    ExitCode = $code
  }
}

function Invoke-Native([string] $File, [string[]] $Arguments, [int[]] $AllowedExitCodes = @(0)) {
  $result = Invoke-NativeCapture -File $File -Arguments $Arguments
  if ($AllowedExitCodes -notcontains $result.ExitCode) {
    throw "$File terminó con código $($result.ExitCode). $($result.Output)"
  }
  return $result.Output
}

function Download-VerifiedPublisher(
  [string] $Uri,
  [string] $Destination,
  [string] $PublisherPattern,
  [string] $ExpectedSha256 = ''
) {
  if (Test-Path $Destination) { Remove-Item -LiteralPath $Destination -Force }
  $fileName = [IO.Path]::GetFileName($Destination)
  Write-Host "Descargando $fileName. Puede tardar varios minutos; no cierres esta ventana..." -ForegroundColor Yellow
  $downloadDeadline = [DateTime]::UtcNow.AddMinutes(20)
  try {
    $bits = Start-BitsTransfer -Source $Uri -Destination $Destination -Priority Foreground -Asynchronous -ErrorAction Stop
    do {
      $bits = Get-BitsTransfer -Id $bits.Id -ErrorAction Stop
      if ($bits.JobState -eq 'Error') { throw "BITS no pudo descargar ${fileName}: $($bits.ErrorDescription)" }
      if ($bits.JobState -in @('Transferred', 'Acknowledged')) { Complete-BitsTransfer -BitsJob $bits -ErrorAction Stop; break }
      if ([DateTime]::UtcNow -gt $downloadDeadline) {
        Remove-BitsTransfer -BitsJob $bits -Confirm:$false -ErrorAction SilentlyContinue
        throw "La descarga de $fileName superó el límite de 20 minutos."
      }
      Start-Sleep -Seconds 1
    } while ($true)
  } catch {
    if ($_.Exception.Message -match 'superó el límite|no pudo descargar') { throw }
    Write-Host 'BITS no estuvo disponible; usando descarga HTTPS directa con límite de tiempo.' -ForegroundColor Yellow
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination -TimeoutSec 1200
  }
  if (-not (Test-Path $Destination)) { throw "No se descargó $Uri" }
  if ($ExpectedSha256) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) { throw 'La descarga no coincide con el SHA-256 publicado.' }
  }
  $signature = Get-AuthenticodeSignature -LiteralPath $Destination
  $subject = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { '' }
  if ($signature.Status -ne 'Valid' -or $subject -notmatch $PublisherPattern) {
    throw "Firma digital inválida o publicador inesperado: $subject"
  }
}

function Get-WslVersion {
  $upgradeStillFinishing = $false
  foreach ($attempt in 1..60) {
    $result = Invoke-NativeCapture -File 'wsl.exe' -Arguments @('--version')
    if ($result.Output -notmatch '(?i)finishing an upgrade|terminando (?:una )?actualizaci[oó]n') {
      $upgradeStillFinishing = $false
      if ($result.ExitCode -ne 0) { return $null }
      $normalized = $result.Output -replace ([string][char]0), ''
      $match = [regex]::Match(
        $normalized,
        '(?im)^\s*(?:WSL version|Versi[oó]n de WSL)\s*:\s*([0-9]+(?:\.[0-9]+){2,3})'
      )
      if ($match.Success) { return [version]$match.Groups[1].Value }
      break
    }
    $upgradeStillFinishing = $true
    if ($attempt -eq 1) {
      Write-Host 'WSL está terminando su actualización. Esperando automáticamente...' -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 5
  }
  if ($upgradeStillFinishing) {
    throw 'WSL no terminó su actualización después de 5 minutos.'
  }

  # Some Windows 10 builds localize or fail to expose `wsl --version` even
  # after the Store/MSI package is current. Use installed-package metadata as
  # a secondary source before deciding that an MSI is required.
  $versions = @()
  try {
    $versions += Get-AppxPackage -AllUsers -Name 'MicrosoftCorporationII.WindowsSubsystemForLinux' -ErrorAction SilentlyContinue |
      ForEach-Object { $_.Version.ToString() }
  } catch { }
  try {
    $versions += Get-ItemProperty `
      'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*', `
      'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' `
      -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -eq 'Windows Subsystem for Linux' } |
      ForEach-Object { [string]$_.DisplayVersion }
  } catch { }
  foreach ($candidate in ($versions | Where-Object { $_ } | Sort-Object -Descending)) {
    try { return [version]$candidate } catch { }
  }
  return $null
}

function Wait-MsiIdle([int] $TimeoutMinutes = 10) {
  $deadline = [DateTime]::UtcNow.AddMinutes($TimeoutMinutes)
  do {
    $active = @(Get-Process -Name msiexec -ErrorAction SilentlyContinue | Where-Object { -not $_.HasExited })
    if ($active.Count -eq 0) { return $true }
    Start-Sleep -Seconds 3
  } while ([DateTime]::UtcNow -lt $deadline)
  return $false
}

function Test-PendingRestart {
  return (
    (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or
    (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
    ((Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue) -ne $null)
  )
}

function Sync-InstalledScript {
  $source = [IO.Path]::GetFullPath($PSCommandPath)
  $destination = [IO.Path]::GetFullPath($installedScript)
  if (-not $source.Equals($destination, [StringComparison]::OrdinalIgnoreCase)) {
    Copy-Item -LiteralPath $source -Destination $destination -Force
  }
  $helperSource = Join-Path (Split-Path $source -Parent) '02-Instalar-Admira-IA.ps1'
  if (Test-Path -LiteralPath $helperSource) {
    Copy-Item -LiteralPath $helperSource -Destination $installedInstallerScript -Force
  }
}

function Find-DockerDesktopExecutable {
  return @(
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\Docker Desktop.exe'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Find-DockerCliExecutable {
  $candidate = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\resources\bin\docker.exe'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
  ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if ($candidate) { return $candidate }
  $command = Get-Command docker.exe -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  return $null
}

function Register-Continuation {
  Sync-InstalledScript
  if ($Gui -and $GuiPath -and (Test-Path -LiteralPath $GuiPath)) {
    $action = New-ScheduledTaskAction -Execute $GuiPath -Argument "-Resume -CredentialFile `"$CredentialFile`" -GuiPath `"$GuiPath`""
  } else {
    $powerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $action = New-ScheduledTaskAction -Execute $powerShell -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$installedScript`" -Resume -CredentialFile `"$CredentialFile`""
  }
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
  # Windows can start the logon task before component servicing finishes.
  # Starting the continuation a little later prevents it from reading an
  # already-rebooting feature as EnablePending and asking for another reboot.
  try { $trigger.Delay = 'PT90S' } catch { }
  $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::FromHours(2)) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $taskName -Description 'Continúa la preparación de WSL2 y Docker Desktop para Admira IA.' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
}

function Request-Restart {
  Save-State 'restart_required' 'waiting_for_restart'
  Register-Continuation
  Write-Host "`nWindows debe reiniciarse para terminar de habilitar WSL2." -ForegroundColor Yellow
  Write-Host 'La preparación continuará automáticamente cuando este mismo usuario vuelva a iniciar sesión.'
  if ($NoRestart -or $Gui) { exit 10 }
  $answer = Read-Host '¿Reiniciar Windows ahora? Escribe SI para confirmar'
  if ($answer -match '^(?i:si|sí|yes|y)$') {
    shutdown.exe /r /t 30 /c "Admira IA continuará la preparación después del reinicio."
    exit 10
  }
  exit 10
}

if (-not (Test-Administrator)) {
  if (-not $CredentialFile) { $CredentialFile = $defaultCredentialFile }
  try { Request-LicenseBeforeChecks } catch {
    Write-Host "`n[ADM-LICENSE-100] $($_.Exception.Message)" -ForegroundColor Red
    if ([Environment]::UserInteractive) { [void](Read-Host 'Presiona ENTER para cerrar') }
    exit 20
  }
  Write-Host 'Solicitando permisos de administrador...' -ForegroundColor Yellow
  # The GUI continuation must never open a console or wait for keyboard input.
  # WSL can print an interactive-looking hint when its feature was just enabled;
  # keep that child process hidden and non-interactive.
  $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`""
  if ($Resume) { $arguments += ' -Resume' }
  if ($AcceptDockerTerms) { $arguments += ' -AcceptDockerTerms' }
  if ($NoRestart) { $arguments += ' -NoRestart' }
  if ($CredentialFile) { $arguments += " -CredentialFile `"$CredentialFile`"" }
  if ($Gui) { $arguments += ' -Gui' }
  if ($GuiPath) { $arguments += " -GuiPath `"$GuiPath`"" }
  try {
    Add-Content -LiteralPath $bootstrapLog -Value "[$([DateTime]::UtcNow.ToString('o'))] Solicitando elevación UAC." -Encoding UTF8
    $elevated = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments -PassThru -ErrorAction Stop
    Add-Content -LiteralPath $bootstrapLog -Value "[$([DateTime]::UtcNow.ToString('o'))] Proceso elevado iniciado: $($elevated.Id)." -Encoding UTF8
    exit 0
  } catch {
    Add-Content -LiteralPath $bootstrapLog -Value "[$([DateTime]::UtcNow.ToString('o'))] UAC rechazado o no disponible: $($_.Exception.Message)" -Encoding UTF8
    Stop-WithDiagnostic 'ADM-UAC-001' 'Windows no permitió elevar el instalador. Acepta la ventana de Control de cuentas de usuario y vuelve a intentarlo.' 40
  }
}

if (-not $CredentialFile) { $CredentialFile = $defaultCredentialFile }
if (-not (Test-Path -LiteralPath $CredentialFile)) {
  try { Request-LicenseBeforeChecks } catch {
    Write-Host "`n[ADM-LICENSE-100] $($_.Exception.Message)" -ForegroundColor Red
    if ([Environment]::UserInteractive) { [void](Read-Host 'Presiona ENTER para cerrar') }
    exit 20
  }
}

New-Item -ItemType Directory -Path $logs -Force | Out-Null
$mutex = New-Object Threading.Mutex($false, 'Global\AdmiraIA-SelfService-Prepare')
$ownsMutex = $false
try { $ownsMutex = $mutex.WaitOne(0, $false) }
catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) {
  Write-Host 'El preparador de Admira IA ya está ejecutándose en otra ventana.' -ForegroundColor Yellow
  Write-Host 'Espera a que esa ejecución termine; no abras otra copia.'
  $mutex.Dispose()
  exit 11
}
Sync-InstalledScript
Start-Transcript -Path (Join-Path $logs 'prepare.log') -Append | Out-Null

try {
  Write-Host "Preparador de Admira IA v$installerVersion" -ForegroundColor Cyan
  if ($Resume) {
    Write-Host 'Reanudando la preparación después del reinicio...' -ForegroundColor Green
  }
  Write-Step 'Diagnóstico de compatibilidad'
  Save-State 'preflight'
  $os = Get-CimInstance Win32_OperatingSystem
  $computer = Get-CimInstance Win32_ComputerSystem
  $processor = Get-CimInstance Win32_Processor | Select-Object -First 1
  $build = [int]$os.BuildNumber

  if ([int]$os.ProductType -ne 1) {
    Stop-WithDiagnostic 'ADM-OS-001' 'Docker Desktop no está soportado oficialmente en Windows Server. Usa una VPS Windows 10/11 para probar este instalador.'
  }
  if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -notmatch 'AMD64') {
    Stop-WithDiagnostic 'ADM-OS-002' 'Esta primera versión requiere Windows x64.'
  }
  if (($build -lt 19045) -or ($build -ge 22000 -and $build -lt 22631)) {
    Stop-WithDiagnostic 'ADM-OS-003' "Windows está fuera de la versión soportada por Docker Desktop. Build detectado: $build."
  }
  $memoryGb = [math]::Round(([double]$computer.TotalPhysicalMemory / 1073741824), 1)
  if ($memoryGb -lt 8) {
    Stop-WithDiagnostic 'ADM-HW-001' 'Se requieren al menos 8 GB de memoria RAM.'
  }

  $hypervisorPresent = [bool]$computer.HypervisorPresent
  $firmwareVirtualization = [bool]$processor.VirtualizationFirmwareEnabled
  $slat = [bool]$processor.SecondLevelAddressTranslationExtensions
  if (-not $hypervisorPresent -and (-not $firmwareVirtualization -or -not $slat)) {
    $isVirtual = ([string]$computer.Model + ' ' + [string]$computer.Manufacturer) -match '(?i)virtual|vmware|kvm|qemu|xen|bochs|bxpc|parallels'
    if ($isVirtual) {
      Stop-WithDiagnostic 'ADM-VIRT-002' 'La VPS no expone virtualización anidada. Actívala en el proveedor antes de continuar.'
    }
    Stop-WithDiagnostic 'ADM-VIRT-001' 'La virtualización está deshabilitada en BIOS/UEFI. Activa Intel VT-x/AMD-V y vuelve a ejecutar el instalador.'
  }

  Write-Step 'Habilitando los componentes de WSL2'
  Save-State 'windows_features'
  $restartNeeded = $false
  # Docker with the WSL2 backend requires only these two features. Enabling the
  # full Hyper-V suite adds unrelated server components and can turn one reboot
  # into a sequence of reboots on fresh Enterprise images. /All enables only
  # the direct parents required by each WSL feature.
  $wslFeatures = @('VirtualMachinePlatform', 'Microsoft-Windows-Subsystem-Linux')
  if ($Resume) {
    # A logon task can run while Windows is still committing the restart. Give
    # it up to three minutes to settle instead of immediately enabling an
    # EnablePending feature again and creating a restart loop.
    $settleDeadline = [DateTime]::UtcNow.AddMinutes(3)
    do {
      $pending = @()
      foreach ($pendingFeature in $wslFeatures) {
        try {
          $pendingState = (Get-WindowsOptionalFeature -Online -FeatureName $pendingFeature -ErrorAction Stop).State
          if ($pendingState -eq 'EnablePending') { $pending += $pendingFeature }
        } catch { }
      }
      if ($pending.Count -eq 0) { break }
      Write-Host "Windows todavía está terminando de aplicar: $($pending -join ', '). Esperando..." -ForegroundColor Yellow
      Start-Sleep -Seconds 10
    } while ([DateTime]::UtcNow -lt $settleDeadline)
  }
  foreach ($feature in $wslFeatures) {
    try { $current = Get-WindowsOptionalFeature -Online -FeatureName $feature -ErrorAction Stop }
    catch {
      Stop-WithDiagnostic 'ADM-WSL-002' "Windows no expone la característica requerida $feature. La imagen de Windows no parece compatible con WSL2." 40
    }
    if ($current.State -eq 'Enabled') { continue }
    if ($current.State -eq 'EnablePending') {
      # This is a genuine pending restart only after the settling window above
      # has expired. Do not invoke Enable-WindowsOptionalFeature a second time.
      $restartNeeded = $true
      continue
    }
    try {
      $result = Enable-WindowsOptionalFeature -Online -FeatureName $feature -All -NoRestart -ErrorAction Stop
      if ($result.RestartNeeded) { $restartNeeded = $true }
    } catch {
      $dism = Invoke-NativeCapture -File 'dism.exe' -Arguments @('/Online', '/Enable-Feature', "/FeatureName:$feature", '/All', '/NoRestart')
      if ($dism.ExitCode -in @(0, 3010)) {
        $restartNeeded = $true
        continue
      }
      $detail = ($dism.Output -replace '\s+', ' ').Trim()
      Stop-WithDiagnostic 'ADM-WSL-002' "Windows no pudo habilitar $feature porque falta una característica padre. $detail" 40
    }
  }
  $boot = (& bcdedit.exe /enum '{current}' 2>&1 | Out-String)
  if ($boot -notmatch '(?im)hypervisorlaunchtype\s+Auto') {
    Invoke-Native bcdedit.exe @('/set', '{current}', 'hypervisorlaunchtype', 'Auto') | Out-Null
    $restartNeeded = $true
  }
  # Restart only when this run changed WSL/hypervisor features. Generic
  # Windows Update reboot flags can persist after a successful reboot and must
  # not trap the installer in an unrelated restart loop.
  if ($restartNeeded) { Request-Restart }

  Write-Step 'Instalando o actualizando WSL'
  Save-State 'wsl_update'
  $minimumWsl = [version]'2.1.5'
  $wslVersion = Get-WslVersion
  $wslUpdateSucceeded = $false
  if ($null -eq $wslVersion -or $wslVersion -lt $minimumWsl) {
    # Do not run `wsl --update` and the WSL MSI as competing installers. On a
    # fresh Windows image, `wsl --update` can install 2.x and still leave the
    # Windows Installer mutex busy, which makes the fallback return 1618.
    Write-Host 'WSL no está listo; usando únicamente el MSI oficial de Microsoft.' -ForegroundColor Yellow
    $release = Invoke-RestMethod -UseBasicParsing -Headers @{ 'User-Agent' = 'AdmiraIA-Installer' } -Uri 'https://api.github.com/repos/microsoft/WSL/releases/latest'
    $asset = @($release.assets | Where-Object { $_.name -match '(?i)^wsl\..*\.x64\.msi$' }) | Select-Object -First 1
    if (-not $asset) { throw 'No se encontró el MSI x64 estable de WSL.' }
    $expected = if ([string]$asset.digest -match '^sha256:(.+)$') { $Matches[1] } else { '' }
    Download-VerifiedPublisher -Uri ([string]$asset.browser_download_url) -Destination $wslInstaller -PublisherPattern 'Microsoft' -ExpectedSha256 $expected
    $msiLog = Join-Path $logs 'wsl-msi.log'
    $msiExit = $null
    foreach ($attempt in 1..3) {
      if (-not (Wait-MsiIdle -TimeoutMinutes 10)) {
        Stop-WithDiagnostic 'ADM-WSL-006' 'Windows Installer está ocupado con otra instalación durante más de 10 minutos. Cierra esa instalación y vuelve a intentarlo.' 40
      }
      $process = Start-Process msiexec.exe -WindowStyle Hidden -PassThru -ArgumentList '/i', "`"$wslInstaller`"", '/qn', '/norestart', '/L*v', "`"$msiLog`""
      $deadline = [DateTime]::UtcNow.AddMinutes(20)
      while (-not $process.HasExited -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Seconds 2; $process.Refresh() }
      if (-not $process.HasExited) { try { $process.Kill() } catch { }; throw 'El MSI de WSL no respondió durante 20 minutos.' }
      $msiExit = $process.ExitCode
      if ($msiExit -ne 1618) { break }
      Write-Host 'Windows Installer sigue ocupado (1618); esperando antes de reintentar...' -ForegroundColor Yellow
      Start-Sleep -Seconds 30
    }
    if ($msiExit -notin @(0, 3010, 1641)) { throw "El MSI de WSL terminó con código $msiExit." }
    $wslUpdateSucceeded = $true
    if ($msiExit -in @(3010, 1641)) { Request-Restart }
  }
  $wslVersion = Get-WslVersion
  if ($null -ne $wslVersion -and $wslVersion -lt $minimumWsl) {
    Stop-WithDiagnostic 'ADM-WSL-005' 'No fue posible instalar WSL 2.1.5 o superior. Envía el diagnóstico al Helper de Admira IA.'
  }
  if ($null -eq $wslVersion) {
    $status = Invoke-NativeCapture -File 'wsl.exe' -Arguments @('--status')
    if (
      -not $wslUpdateSucceeded -or
      $status.ExitCode -ne 0 -or
      $status.Output -match '(?im)^\s*(usage|uso):\s*wsl\.exe'
    ) {
      Stop-WithDiagnostic 'ADM-WSL-005' 'Windows no pudo confirmar que WSL está actualizado y operativo.'
    }
  }
  try {
    Invoke-Native wsl.exe @('--set-default-version', '2') | Out-Null
  } catch {
    $kernelMessage = $_.Exception.Message
    if ($kernelMessage -notmatch '(?i)kernel|núcleo|0x1bc|wsl2kernel') { throw }
    Write-Host 'El kernel de WSL2 está incompleto; aplicando el paquete oficial de Microsoft.' -ForegroundColor Yellow
    $legacyKernel = Join-Path $root 'wsl_update_x64.msi'
    Download-VerifiedPublisher `
      -Uri 'https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi' `
      -Destination $legacyKernel `
      -PublisherPattern 'Microsoft'
    $kernelProcess = Start-Process msiexec.exe -Wait -PassThru -ArgumentList '/i', "`"$legacyKernel`"", '/qn', '/norestart'
    if ($kernelProcess.ExitCode -notin @(0, 3010, 1641)) {
      throw "El actualizador del kernel WSL2 terminó con código $($kernelProcess.ExitCode)."
    }
    if ($kernelProcess.ExitCode -in @(3010, 1641)) { Request-Restart }
    Invoke-Native wsl.exe @('--set-default-version', '2') | Out-Null
  }
  $wslDisplay = if ($null -ne $wslVersion) {
    $wslVersion.ToString()
  } else {
    'actualizado y validado por Windows'
  }
  Write-Host "WSL $wslDisplay listo." -ForegroundColor Green

  Write-Step 'Instalando Docker Desktop'
  Save-State 'docker_desktop'
  $dockerDesktop = Find-DockerDesktopExecutable

  if (-not $dockerDesktop) {
    # The GUI never has a visible console in the elevated continuation. The
    # Docker installer is invoked with --accept-license below, so do not block
    # a hidden PowerShell process waiting for Read-Host('ACEPTO').
    if ($Gui) { $AcceptDockerTerms = $true }
    if (-not $AcceptDockerTerms) {
      Write-Host "Antes de instalar debes aceptar los términos de Docker:" -ForegroundColor Yellow
      Write-Host $dockerTermsUrl
      $answer = Read-Host 'Después de revisarlos, escribe ACEPTO para continuar'
      if ($answer -ne 'ACEPTO') {
        Stop-WithDiagnostic 'ADM-DOCKER-TERMS' 'Docker Desktop no se instalará hasta que el usuario acepte expresamente sus términos.' 30
      }
    }
    Download-VerifiedPublisher -Uri $dockerDownloadUrl -Destination $dockerInstaller -PublisherPattern 'Docker'
    $arguments = @(
      'install',
      '--user',
      '--quiet',
      '--accept-license',
      '--backend=wsl-2',
      '--no-windows-containers'
    )
    $process = Start-Process -FilePath $dockerInstaller -ArgumentList $arguments -PassThru
    $dockerDeadline = [DateTime]::UtcNow.AddMinutes(20)
    while (-not $process.HasExited) {
      if ([DateTime]::UtcNow -gt $dockerDeadline) {
        try { $process.Kill() } catch { }
        Stop-WithDiagnostic 'ADM-DOCKER-001' 'El instalador de Docker Desktop no respondió durante 20 minutos. Revisa la instalación de Docker y vuelve a intentarlo.' 40
      }
      Start-Sleep -Seconds 2
      $process.Refresh()
    }
    if ($process.ExitCode -ne 0) { throw "Docker Desktop terminó con código $($process.ExitCode)." }
    $dockerDesktop = Find-DockerDesktopExecutable
  }
  if (-not $dockerDesktop) { Stop-WithDiagnostic 'ADM-DOCKER-002' 'Docker Desktop se instaló, pero no se encontró su ejecutable.' }

  Start-Process -FilePath $dockerDesktop -ErrorAction SilentlyContinue
  $dockerCliPath = Find-DockerCliExecutable
  if (-not $dockerCliPath) { Stop-WithDiagnostic 'ADM-DOCKER-003' 'No se encontró Docker CLI después de instalar Docker Desktop.' }

  Write-Host 'Esperando que Docker Desktop termine de iniciar...'
  $deadline = [DateTime]::UtcNow.AddMinutes(15)
  $dockerReady = $false
  do {
    try {
      & $dockerCliPath info --format '{{.ServerVersion}}' *> $null
      if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
  } while ([DateTime]::UtcNow -lt $deadline)
  if (-not $dockerReady) {
    Stop-WithDiagnostic 'ADM-DOCKER-004' 'Docker Desktop está instalado pero el motor no inició. Abre Docker Desktop y envía este código al Helper.' 40
  }

  Save-State 'installing_admira'
  Write-Host "`nWSL2 y Docker están listos. Continuando automáticamente con Admira IA..." -ForegroundColor Green
  if (-not (Test-Path -LiteralPath $installedInstallerScript)) {
    throw 'No se encontró el componente interno de instalación de Admira IA.'
  }
  $installerArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$installedInstallerScript`" -CredentialFile `"$CredentialFile`""
  $installerProcess = Start-Process powershell.exe -Wait -PassThru -ArgumentList $installerArgs
  if ($installerProcess.ExitCode -ne 0) {
    $detail = ''
    if (Test-Path -LiteralPath $installResultPath) {
      try {
        $result = Get-Content -Raw -LiteralPath $installResultPath | ConvertFrom-Json
        $detail = ([string]$result.message).Trim()
      } catch { }
    }
    if ($detail) {
      throw "La instalación de Admira IA terminó con código $($installerProcess.ExitCode): $detail"
    }
    throw "La instalación de Admira IA terminó con código $($installerProcess.ExitCode)."
  }
  Save-State 'complete' 'complete'
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $CredentialFile -Force -ErrorAction SilentlyContinue
  Write-Host "`nADMIRA IA INSTALADA CORRECTAMENTE" -ForegroundColor Green
  Write-Host "WSL: $wslDisplay"
  Write-Host "Docker Server: $(& $dockerCliPath info --format '{{.ServerVersion}}')"
  Write-Host 'El dashboard y el arranque automático quedaron configurados.'
  exit 0
} catch {
  $message = $_.Exception.Message
  Write-Host "`n[ADM-SETUP-999] $message" -ForegroundColor Red
  @{
    status = 'error'
    code = 'ADM-SETUP-999'
    message = $message
    updated_at = [DateTime]::UtcNow.ToString('o')
  } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
  if ($Resume -and [Environment]::UserInteractive) {
    [void](Read-Host 'La continuación encontró un error. Presiona ENTER para cerrar esta ventana')
  }
  exit 99
} finally {
  try { Stop-Transcript | Out-Null } catch { }
  if ($ownsMutex) { try { $mutex.ReleaseMutex() } catch { } }
  try { $mutex.Dispose() } catch { }
}
