param(
    [string]$SourceDir = ""
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ProductName = "Admira IA"
$cleanSourceDir = ([string]$SourceDir).Trim().Trim('"')
$Root = if ($cleanSourceDir) { (Resolve-Path -LiteralPath $cleanSourceDir).Path } else { Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$StateDir = Join-Path $env:LOCALAPPDATA "Admira IA\cloud-installer"
$KeyPath = Join-Path $StateDir "id_ed25519"
$ArchivePath = Join-Path $StateDir "admira-source.zip"
$DashboardPort = 7871
$DoApi = "https://api.digitalocean.com/v2"

function Set-Status([string]$Message, [int]$Progress = -1) {
    if ($script:StatusLabel) { $script:StatusLabel.Text = $Message; $script:StatusLabel.Refresh() }
    if ($script:ProgressBar -and $Progress -ge 0) { $script:ProgressBar.Value = [Math]::Min(100, [Math]::Max(0, $Progress)); $script:ProgressBar.Refresh() }
    [System.Windows.Forms.Application]::DoEvents()
}

function Invoke-DoApi {
    param([string]$Token, [string]$Method, [string]$Path, [object]$Body = $null)
    $headers = @{ Authorization = "Bearer $Token"; "Content-Type" = "application/json" }
    $params = @{ Uri = "$DoApi$Path"; Method = $Method; Headers = $headers; UseBasicParsing = $true }
    if ($null -ne $Body) { $params.Body = ($Body | ConvertTo-Json -Depth 12 -Compress) }
    try { return Invoke-RestMethod @params }
    catch {
        $detail = $_.ErrorDetails.Message
        if (!$detail) { $detail = $_.Exception.Message }
        throw "DigitalOcean API error ($Method $Path): $detail"
    }
}

function Ensure-SshKey {
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    if (!(Test-Path $KeyPath) -or !(Test-Path "${KeyPath}.pub")) {
        if (!(Get-Command ssh-keygen -ErrorAction SilentlyContinue)) { throw "Windows OpenSSH (ssh-keygen) no está disponible." }
        & ssh-keygen -t ed25519 -N "" -C "admira-ia-cloud-$([Environment]::MachineName)" -f $KeyPath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "No se pudo generar la clave SSH." }
    }
    return (Get-Content "${KeyPath}.pub" -Raw).Trim()
}

function Wait-Droplet {
    param([string]$Token, [string]$Id)
    for ($i = 0; $i -lt 90; $i++) {
        $droplet = (Invoke-DoApi $Token GET "/droplets/$Id").droplet
        if ($droplet.status -eq "active" -and $droplet.networks.v4) {
            $public = @($droplet.networks.v4 | Where-Object { $_.type -eq "public" })[0]
            if ($public.ip_address) { return $public.ip_address }
        }
        Start-Sleep -Seconds 4
        Set-Status "Esperando que DigitalOcean prepare el servidor... ($($i + 1)/90)"
    }
    throw "DigitalOcean no terminó de preparar el servidor a tiempo."
}

function Wait-Ssh {
    param([string]$Ip)
    for ($i = 0; $i -lt 90; $i++) {
        try {
            & ssh -i $KeyPath -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ConnectTimeout=3 root@$Ip "echo ready" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return }
        } catch { }
        Start-Sleep -Seconds 4
        Set-Status "Esperando acceso SSH al servidor... ($($i + 1)/90)"
    }
    throw "No se pudo acceder por SSH al servidor recién creado."
}

function New-SourceArchive {
    if (Test-Path $ArchivePath) { Remove-Item -LiteralPath $ArchivePath -Force }
    $items = Get-ChildItem -LiteralPath $Root -Force | Where-Object { $_.Name -notin @(".env", "release", ".git", "dashboard\data", "logs", "output") }
    Compress-Archive -Path ($items.FullName) -DestinationPath $ArchivePath -CompressionLevel Optimal
}

function Get-LicenseSuffix([string]$LicenseKey) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($LicenseKey.Trim().ToUpperInvariant())
    $hash = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return (([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant().Substring(0, 10))
}

function Set-RemoteEnv([string]$Ip, [string]$LicenseKey, [string]$BuyerEmail, [string]$InstanceSuffix) {
    $cmd = @'
set -eu
mkdir -p /opt/meta-ads-agent
if [ ! -f /opt/meta-ads-agent/.env ] && [ -f /opt/meta-ads-agent/.env.example ]; then cp /opt/meta-ads-agent/.env.example /opt/meta-ads-agent/.env; fi
sed -i 's/^DASHBOARD_HOST=.*/DASHBOARD_HOST=0.0.0.0/' /opt/meta-ads-agent/.env || true
sed -i 's/^DASHBOARD_PORT=.*/DASHBOARD_PORT=7871/' /opt/meta-ads-agent/.env || true
sed -i 's/^ALLOW_PUBLIC_DASHBOARD=.*/ALLOW_PUBLIC_DASHBOARD=true/' /opt/meta-ads-agent/.env || true
sed -i 's/^LAN_ACCESS_ENABLED=.*/LAN_ACCESS_ENABLED=true/' /opt/meta-ads-agent/.env || true
grep -q '^DASHBOARD_HOST=' /opt/meta-ads-agent/.env || echo 'DASHBOARD_HOST=0.0.0.0' >> /opt/meta-ads-agent/.env
grep -q '^DASHBOARD_PORT=' /opt/meta-ads-agent/.env || echo 'DASHBOARD_PORT=7871' >> /opt/meta-ads-agent/.env
grep -q '^ALLOW_PUBLIC_DASHBOARD=' /opt/meta-ads-agent/.env || echo 'ALLOW_PUBLIC_DASHBOARD=true' >> /opt/meta-ads-agent/.env
grep -q '^LAN_ACCESS_ENABLED=' /opt/meta-ads-agent/.env || echo 'LAN_ACCESS_ENABLED=true' >> /opt/meta-ads-agent/.env
if ! swapon --show | grep -q /swapfile; then
  if [ ! -f /swapfile ]; then fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048; chmod 600 /swapfile; mkswap /swapfile; fi
  swapon /swapfile || true
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
cd /opt/meta-ads-agent
LICENSE_KEY_B64="__LICENSE_KEY_B64__"
BUYER_EMAIL_B64="__BUYER_EMAIL_B64__"
license_key=$(printf '%s' "$LICENSE_KEY_B64" | base64 -d)
buyer_email=$(printf '%s' "$BUYER_EMAIL_B64" | base64 -d)
for pair in "LICENSE_KEY=$license_key" "LICENSE_BUYER_EMAIL=$buyer_email"; do
  key=${pair%%=*}; value=${pair#*=}
  if grep -q "^$key=" .env; then sed -i "s#^$key=.*#$key=$value#" .env; else printf '\n%s=%s\n' "$key" "$value" >> .env; fi
done
instance_suffix="__INSTANCE_SUFFIX__"
for pair in "ADMIRA_INSTANCE_SLUG=client-$instance_suffix" "ADMIRA_COMPOSE_PROJECT_NAME=admira-ia-$instance_suffix" "ADMIRA_CONTAINER_NAME=admira-ia-$instance_suffix" "ADMIRA_VOLUME_PREFIX=meta_ads_$instance_suffix"; do
  key=${pair%%=*}; value=${pair#*=}
  if grep -q "^$key=" .env; then sed -i "s#^$key=.*#$key=$value#" .env; else printf '\n%s=%s\n' "$key" "$value" >> .env; fi
done
docker compose -p admira-ia build
docker compose -p "admira-ia-$instance_suffix" up -d
'@
    $keyB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($LicenseKey))
    $emailB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($BuyerEmail))
    $cmd = $cmd.Replace('__LICENSE_KEY_B64__', $keyB64).Replace('__BUYER_EMAIL_B64__', $emailB64).Replace('__INSTANCE_SUFFIX__', $InstanceSuffix)
    $tmp = Join-Path $StateDir "remote-setup.sh"
    Set-Content -LiteralPath $tmp -Value $cmd -Encoding ascii
    & scp -i $KeyPath -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL $tmp root@${Ip}:/tmp/admira-setup.sh | Out-Null
    & ssh -i $KeyPath -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL root@$Ip "bash /tmp/admira-setup.sh"
    if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de Admira IA en el servidor." }
}

function New-DesktopShortcut([string]$Ip) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcut = Join-Path $desktop "Admira IA - Cliente.url"
    @("[InternetShortcut]", "URL=http://$Ip`:$DashboardPort", "IconIndex=0") | Set-Content -LiteralPath $shortcut -Encoding ascii
    return $shortcut
}

function Start-Install {
    $token = $TokenBox.Text.Trim()
    if (!$token) { throw "Pega tu token de DigitalOcean." }
    $licenseKey = $LicenseBox.Text.Trim()
    $buyerEmail = $EmailBox.Text.Trim()
    if (!$licenseKey) { throw "Pega la licencia de Admira IA." }
    if ($buyerEmail -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') { throw "Escribe un correo de compra válido." }
    $licenseSuffix = Get-LicenseSuffix $licenseKey
    foreach ($command in @("ssh-keygen", "ssh", "scp")) {
        if (!(Get-Command $command -ErrorAction SilentlyContinue)) {
            throw "Windows OpenSSH Client no está completo: falta $command.exe. Actívalo en Características opcionales de Windows y vuelve a intentar."
        }
    }
    $size = [string]$SizeBox.SelectedValue
    $region = [string]$RegionBox.SelectedValue
    Set-Status "Validando token de DigitalOcean...", 5
    $null = Invoke-DoApi $token GET "/account"
    $publicKey = Ensure-SshKey
    Set-Status "Generando acceso SSH seguro...", 12
    $keyName = "admira-ia-$([Environment]::MachineName)-$((Get-Date).ToString('yyyyMMddHHmmss'))"
    $ssh = (Invoke-DoApi $token POST "/account/keys" @{ name = $keyName; public_key = $publicKey }).ssh_key
    Set-Status "Creando servidor en DigitalOcean...", 22
    $cloudInit = @"
#cloud-config
package_update: true
packages:
  - ca-certificates
  - curl
  - unzip
  - docker.io
  - docker-compose-v2
runcmd:
  - systemctl enable --now docker
"@
    $droplet = (Invoke-DoApi $token POST "/droplets" @{ name = "admira-ia-$licenseSuffix"; region = $region; size = $size; image = "ubuntu-24-04-x64"; ssh_keys = @($ssh.id); monitoring = $true; tags = @("admira-ia", "admira-$licenseSuffix"); user_data = $cloudInit }).droplet
    $ip = Wait-Droplet $token $droplet.id
    Set-Status "Configurando firewall...", 38
    $firewall = Invoke-DoApi $token POST "/firewalls" @{ name = "admira-ia-$($droplet.id)"; droplet_ids = @($droplet.id); inbound_rules = @(@{ protocol = "tcp"; ports = "22"; sources = @{ addresses = @("0.0.0.0/0", "::/0") } }, @{ protocol = "tcp"; ports = "7871"; sources = @{ addresses = @("0.0.0.0/0", "::/0") } }); outbound_rules = @(@{ protocol = "tcp"; ports = "1-65535"; destinations = @{ addresses = @("0.0.0.0/0", "::/0") } }, @{ protocol = "udp"; ports = "1-65535"; destinations = @{ addresses = @("0.0.0.0/0", "::/0") } }, @{ protocol = "icmp"; destinations = @{ addresses = @("0.0.0.0/0", "::/0") } }) }
    New-SourceArchive
    Wait-Ssh $ip
    Set-Status "Subiendo Admira IA al servidor...", 62
    & scp -i $KeyPath -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL $ArchivePath root@${ip}:/tmp/admira-source.zip | Out-Null
    & ssh -i $KeyPath -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL root@$ip "rm -rf /opt/meta-ads-agent; mkdir -p /opt/meta-ads-agent; unzip -q /tmp/admira-source.zip -d /opt/meta-ads-agent; if [ -d /opt/meta-ads-agent/product ]; then cp -a /opt/meta-ads-agent/product/. /opt/meta-ads-agent/; rm -rf /opt/meta-ads-agent/product; fi"
    Set-RemoteEnv $ip $licenseKey $buyerEmail $licenseSuffix
    $url = "http://$ip`:$DashboardPort"
    $shortcut = New-DesktopShortcut $ip $licenseSuffix
    @{ droplet_id = $droplet.id; ip = $ip; url = $url; instance_suffix = $licenseSuffix; ssh_key = $KeyPath; firewall_id = $firewall.firewall.id; created_at = (Get-Date).ToUniversalTime().ToString("o") } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $StateDir "installation-$licenseSuffix.json") -Encoding utf8
    Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
    Set-Status "Instalación terminada. Abriendo el onboarding...", 100
    Start-Process $url
    [System.Windows.Forms.MessageBox]::Show("Admira IA quedó instalada en $url`n`nSe creó el acceso directo: $shortcut`n`nTu clave SSH quedó guardada localmente en:`n$KeyPath", "Admira IA", "OK", "Information") | Out-Null
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "Instalar Admira IA en DigitalOcean"
$form.Size = New-Object System.Drawing.Size(620, 560)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(24, 20, 42)
$form.ForeColor = [System.Drawing.Color]::White
$font = New-Object System.Drawing.Font("Segoe UI", 10)

$title = New-Object System.Windows.Forms.Label; $title.Text = "Instala Admira IA en la nube"; $title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold); $title.Location = New-Object System.Drawing.Point(28, 22); $title.AutoSize = $true
$hint = New-Object System.Windows.Forms.Label; $hint.Text = "Pega tu token de DigitalOcean y elige el tamaño del servidor."; $hint.Location = New-Object System.Drawing.Point(30, 58); $hint.AutoSize = $true
$form.Controls.AddRange(@($title, $hint))

function Add-Field([string]$Label, [int]$Y, [string]$Value = "") {
    $l = New-Object System.Windows.Forms.Label; $l.Text = $Label; $l.Location = New-Object System.Drawing.Point(30, $Y); $l.AutoSize = $true
    $b = New-Object System.Windows.Forms.TextBox; $b.Location = New-Object System.Drawing.Point(30, ($Y + 22)); $b.Size = New-Object System.Drawing.Size(545, 27); $b.Text = $Value; $b.Font = $font
    $form.Controls.AddRange(@($l, $b)); return $b
}
$EmailBox = Add-Field "Correo usado para comprar la licencia" 92
$LicenseBox = Add-Field "Licencia de Admira IA" 160
$TokenBox = Add-Field "Token de DigitalOcean" 228
$TokenBox.UseSystemPasswordChar = $true
$sizeLabel = New-Object System.Windows.Forms.Label; $sizeLabel.Text = "Tamaño"; $sizeLabel.Location = New-Object System.Drawing.Point(30, 310); $sizeLabel.AutoSize = $true
$SizeBox = New-Object System.Windows.Forms.ComboBox; $SizeBox.Location = New-Object System.Drawing.Point(30, 333); $SizeBox.Size = New-Object System.Drawing.Size(260, 28); $SizeBox.DropDownStyle = "DropDownList"; $SizeBox.DisplayMember = "label"; $SizeBox.ValueMember = "slug"; $SizeBox.DataSource = @([pscustomobject]@{label="1 GB (con swap de 2 GB)";slug="s-1vcpu-1gb"}, [pscustomobject]@{label="2 GB";slug="s-1vcpu-2gb"}, [pscustomobject]@{label="4 GB";slug="s-2vcpu-4gb"})
$regionLabel = New-Object System.Windows.Forms.Label; $regionLabel.Text = "Región"; $regionLabel.Location = New-Object System.Drawing.Point(320, 310); $regionLabel.AutoSize = $true
$RegionBox = New-Object System.Windows.Forms.ComboBox; $RegionBox.Location = New-Object System.Drawing.Point(320, 333); $RegionBox.Size = New-Object System.Drawing.Size(255, 28); $RegionBox.DropDownStyle = "DropDownList"; $RegionBox.DisplayMember = "label"; $RegionBox.ValueMember = "slug"; $RegionBox.DataSource = @([pscustomobject]@{label="New York (NYC3)";slug="nyc3"}, [pscustomobject]@{label="San Francisco (SFO3)";slug="sfo3"}, [pscustomobject]@{label="Amsterdam (AMS3)";slug="ams3"})
$form.Controls.AddRange(@($sizeLabel, $SizeBox, $regionLabel, $RegionBox))
$script:StatusLabel = New-Object System.Windows.Forms.Label; $script:StatusLabel.Text = "Listo para comenzar"; $script:StatusLabel.Location = New-Object System.Drawing.Point(30, 378); $script:StatusLabel.Size = New-Object System.Drawing.Size(545, 28); $form.Controls.Add($script:StatusLabel)
$script:ProgressBar = New-Object System.Windows.Forms.ProgressBar; $script:ProgressBar.Location = New-Object System.Drawing.Point(30, 412); $script:ProgressBar.Size = New-Object System.Drawing.Size(545, 16); $script:ProgressBar.Minimum = 0; $script:ProgressBar.Maximum = 100; $script:ProgressBar.Style = "Continuous"; $form.Controls.Add($script:ProgressBar)
$button = New-Object System.Windows.Forms.Button; $button.Text = "Crear instalación"; $button.Location = New-Object System.Drawing.Point(30, 455); $button.Size = New-Object System.Drawing.Size(545, 42); $button.BackColor = [System.Drawing.Color]::FromArgb(186, 108, 255); $button.ForeColor = [System.Drawing.Color]::White; $button.FlatStyle = "Flat"; $button.Add_Click({ $button.Enabled = $false; try { Start-Install } catch { Set-Status $_.Exception.Message; [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "No se pudo instalar", "OK", "Error") | Out-Null } finally { $button.Enabled = $true } }); $form.Controls.Add($button)
$form.Add_Shown({ $TokenBox.Focus() })
[System.Windows.Forms.Application]::Run($form)
