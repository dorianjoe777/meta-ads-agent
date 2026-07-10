const WINDOWS_INSTALLER = `param([switch]$RunKeeper)

function Invoke-AdmiraAccessKeeper {
  $ConfigPath = Join-Path $env:USERPROFILE ".meta-ads-agent\\\\cloud-access-keeper.json"
  if (!(Test-Path $ConfigPath)) { throw "Missing config: $ConfigPath" }
  $Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
  $LogDir = Join-Path $env:USERPROFILE ".meta-ads-agent\\\\logs"
  New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
  $LogFile = Join-Path $LogDir "cloud-access-keeper.log"
  function Write-KeeperLog($Message) {
    Add-Content -Path $LogFile -Value ("{0} {1}" -f (Get-Date).ToUniversalTime().ToString("s") + "Z", $Message)
  }
  try {
    $CurrentIp = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 10).Trim()
  } catch {
    $CurrentIp = (Invoke-RestMethod -Uri "https://checkip.amazonaws.com" -TimeoutSec 10).Trim()
  }
  if ($CurrentIp -notmatch '^([0-9]{1,3}\\.){3}[0-9]{1,3}$') {
    Write-KeeperLog "Could not detect public IPv4."
    exit 1
  }
  $StatePath = Join-Path $env:USERPROFILE ".meta-ads-agent\\\\cloud-access-keeper-state.json"
  $State = @{ last_success_ip = ""; last_success_epoch = 0 }
  if (Test-Path $StatePath) {
    try { $State = Get-Content $StatePath -Raw | ConvertFrom-Json } catch {}
  }
  $Now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $Age = $Now - [int64]($State.last_success_epoch)
  if ($CurrentIp -eq $State.last_success_ip -and $Age -lt 86400) {
    Write-KeeperLog "IP unchanged: $CurrentIp"
    return
  }
  if (!(Test-Path $Config.identity_path)) {
    Write-KeeperLog "SSH identity file missing: $($Config.identity_path)"
    exit 1
  }
  $RemoteRefresh = if ($Config.remote_refresh_command) { $Config.remote_refresh_command } else { "~/.local/bin/meta-ads-refresh-access" }
  $RemoteCommand = "$RemoteRefresh --ip $CurrentIp --quiet"
  & ssh -i $Config.identity_path -p $Config.ssh_port -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=10 -o StrictHostKeyChecking=accept-new "$($Config.ssh_user)@$($Config.droplet_host)" $RemoteCommand
  if ($LASTEXITCODE -ne 0) {
    Write-KeeperLog "SSH refresh failed for $CurrentIp"
    exit $LASTEXITCODE
  }
  @{ last_success_ip = $CurrentIp; last_success_epoch = $Now } | ConvertTo-Json | Set-Content -Path $StatePath -Encoding UTF8
  Write-KeeperLog "Dashboard access refreshed for $CurrentIp"
}

function Install-AdmiraAccessKeeper {
  param(
    [Parameter(Mandatory=$true)][string]$DropletHost,
    [string]$SshUser = "root",
    [int]$SshPort = 22,
    [string]$IdentityPath = "$env:USERPROFILE\\\\.ssh\\\\admira_ia",
    [int]$IntervalMinutes = 60,
    [switch]$RunNow
  )
  if ($DropletHost -notmatch '^[A-Za-z0-9.-]+$') { throw "Invalid Droplet host." }
  $LegacyIdentityPath = Join-Path (Join-Path $env:USERPROFILE ".ssh") ("admi" + "ro_ai")
  $DefaultIdentityPath = Join-Path (Join-Path $env:USERPROFILE ".ssh") "admira_ia"
  if ($IdentityPath -eq $DefaultIdentityPath -and !(Test-Path $IdentityPath) -and (Test-Path $LegacyIdentityPath)) {
    $IdentityPath = $LegacyIdentityPath
  }
  $BaseDir = Join-Path $env:USERPROFILE ".meta-ads-agent"
  $BinDir = Join-Path $BaseDir "bin"
  New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
  $ScriptPath = Join-Path $BinDir "AdmiraCloudAccessKeeper.ps1"
  $ConfigPath = Join-Path $BaseDir "cloud-access-keeper.json"
  Invoke-WebRequest -UseBasicParsing -Uri "https://admiraia.uboost.lat/api/portal/cloud/access-keeper-ps" -OutFile $ScriptPath
  @{
    droplet_host = $DropletHost
    ssh_user = $SshUser
    ssh_port = $SshPort
    identity_path = $IdentityPath
    remote_refresh_command = "~/.local/bin/meta-ads-refresh-access"
  } | ConvertTo-Json | Set-Content -Path $ConfigPath -Encoding UTF8
  $TaskName = "Admira IA Cloud Access Keeper"
  $TaskCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '" -RunKeeper'
  schtasks /Create /F /SC MINUTE /MO $IntervalMinutes /TN "$TaskName" /TR "$TaskCommand" | Out-Null
  if ($RunNow) { Invoke-AdmiraAccessKeeper }
  Write-Host "Admira IA access keeper installed. It checks this PC public IP every $IntervalMinutes minutes."
}

if ($RunKeeper) {
  Invoke-AdmiraAccessKeeper
}
`;

export default function handler(request, response) {
  response.setHeader("Content-Type", "text/plain; charset=utf-8");
  response.setHeader("Cache-Control", "public, max-age=300");
  return response.status(200).send(WINDOWS_INSTALLER);
}
