[CmdletBinding()]
param(
  [string]$Configuration = 'Release'
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $here
$payloadRoot = Join-Path $packageRoot 'payload'
$publish = Join-Path $here "bin\$Configuration\net8.0-windows\win-x64\publish"

dotnet publish (Join-Path $here 'AdmiraIA.Installer.Gui.csproj') `
  -c $Configuration -r win-x64 --self-contained true `
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true

New-Item -ItemType Directory -Path (Join-Path $publish 'payload') -Force | Out-Null
Copy-Item (Join-Path $payloadRoot '01-Preparar-PC-Admira-IA.ps1') (Join-Path $publish 'payload') -Force
Copy-Item (Join-Path $payloadRoot '02-Instalar-Admira-IA.ps1') (Join-Path $publish 'payload') -Force

# Stage the GUI and its private payload. Customer packages expose only the EXE
# plus this payload folder; they deliberately do not include a CMD/PS1 launcher.
Copy-Item (Join-Path $publish 'AdmiraIA-Installer.exe') (Join-Path $packageRoot 'AdmiraIA-Installer.exe') -Force
New-Item -ItemType Directory -Path (Join-Path $packageRoot 'payload') -Force | Out-Null
Copy-Item (Join-Path $payloadRoot '01-Preparar-PC-Admira-IA.ps1') (Join-Path $packageRoot 'payload') -Force
Copy-Item (Join-Path $payloadRoot '02-Instalar-Admira-IA.ps1') (Join-Path $packageRoot 'payload') -Force

Write-Host "GUI publicada en: $publish" -ForegroundColor Green
Write-Host 'Para un instalador distribuible, firma el EXE con un certificado Authenticode.' -ForegroundColor Yellow
