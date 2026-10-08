# GoalGetter — install the HTTPS front door on Windows (Phase 17).
#
# Why: Docker Desktop hides every device's address from anything inside
# Docker, so GoalGetter can limit wrong passwords per account but not per
# device. This puts Caddy on Windows itself, as a service, in front of Docker:
# it sees each device first and passes its address on. It also handles HTTPS
# for your name (goals.internal, goalgetter.company.com, a DuckDNS name).
#
# Run from the GoalGetter folder, in PowerShell **as administrator**:
#
#   powershell -ExecutionPolicy Bypass -File windows\install-front-door.ps1
#   powershell -ExecutionPolicy Bypass -File windows\install-front-door.ps1 -Remove
#
# Uses the HTTPS settings already in .env (HTTPS_HOST, HTTPS_CERTIFICATE, and
# DNS_* for Let's Encrypt) — documentation/20-hosting.md, "Seeing each device".
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$service = 'GoalGetterHTTPS'
$caddyDir = Join-Path $root 'windows\caddy'
$caddyExe = Join-Path $caddyDir 'caddy.exe'
$caddyfile = Join-Path $root 'windows\Caddyfile'
$data = Join-Path $root 'volumes\caddy-windows'
$overlay = 'docker-compose.frontdoor.yml'
$download = 'https://caddyserver.com/api/download?os=windows&arch=amd64&p=github.com%2Fcaddy-dns%2Fcloudflare&p=github.com%2Fcaddy-dns%2Fduckdns'

function Say([string]$text) { Write-Host "  $text" }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host 'Run this in PowerShell opened as administrator (right-click > Run as administrator).'
    exit 1
}
if (-not (Test-Path $envFile)) {
    Write-Host 'No .env yet. Run setup.ps1 first (see the README).'
    exit 1
}

# ── .env, read and edited in place (comments and order kept) ────────────────
$text = [IO.File]::ReadAllText($envFile)
function Get-Setting([string]$name) {
    $m = [regex]::Match($text, "(?m)^$name=([^\r\n]*)")
    if ($m.Success) { return $m.Groups[1].Value.Trim() } else { return '' }
}
function Set-Setting([string]$name, [string]$value) {
    if ([regex]::IsMatch($script:text, "(?m)^$name=")) {
        $script:text = [regex]::Replace($script:text, "(?m)^$name=[^\r\n]*", "$name=$value")
    } else {
        $script:text = $script:text.TrimEnd() + "`n$name=$value`n"
    }
}
function Save-Env { [IO.File]::WriteAllText($envFile, $script:text, (New-Object Text.UTF8Encoding $false)) }

$composeFile = Get-Setting 'COMPOSE_FILE'

if ($Remove) {
    Write-Host 'Removing the HTTPS front door...'
    if (Get-Service $service -ErrorAction SilentlyContinue) {
        Stop-Service $service -ErrorAction SilentlyContinue
        & sc.exe delete $service | Out-Null
        Say 'Service removed.'
    }
    Set-Setting 'HTTPS_FRONT_DOOR' ''
    Set-Setting 'COMPOSE_FILE' (($composeFile -split ':' | Where-Object { $_ -and $_ -ne $overlay }) -join ':')
    Save-Env
    Get-NetFirewallRule -DisplayName 'GoalGetter front door' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Push-Location $root; docker compose up -d; Pop-Location
    Say 'Docker publishes its own ports again. HTTPS is as set in Settings > Hosting.'
    exit 0
}

# ── Check the settings it needs ─────────────────────────────────────────────
$hostName = Get-Setting 'HTTPS_HOST'
if (-not $hostName) {
    Write-Host 'Set the name people will type first (e.g. goals.internal): Settings > Hosting, or HTTPS_HOST in .env.'
    exit 1
}
$https = Get-Setting 'HTTPS_PORT'; if (-not $https) { $https = '443' }
$http = Get-Setting 'HTTP_PORT'; if (-not $http) { $http = '80' }
$plain = Get-Setting 'APP_PORT'; if (-not $plain) { $plain = '8080' }

Write-Host "Installing the HTTPS front door for https://$hostName ..."

# ── 1. Caddy for Windows, with the DNS providers Let's Encrypt mode uses ────
New-Item -ItemType Directory -Force $caddyDir, $data | Out-Null
if (-not (Test-Path $caddyExe)) {
    Say 'Downloading Caddy...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $download -OutFile $caddyExe
}
& $caddyExe version | ForEach-Object { Say "Caddy $_" }

# **The front door is switched on in .env last** (P7-3). GoalGetter reads
# .env every 30 seconds, and HTTPS_FRONT_DOOR=windows tells it to send
# everybody to the front door — so it is written only once the front door is
# running and answering. Anything that fails first puts back what was changed.
$before = @{
    COMPOSE_FILE    = $composeFile
    FRONT_DOOR_DATA = Get-Setting 'FRONT_DOOR_DATA'
}
function Undo-Changes([string]$why) {
    Write-Host $why
    if (Get-Service $service -ErrorAction SilentlyContinue) {
        Stop-Service $service -ErrorAction SilentlyContinue
        & sc.exe delete $service | Out-Null
    }
    foreach ($name in $before.Keys) { Set-Setting $name $before[$name] }
    Save-Env
    Push-Location $root; docker compose up -d; Pop-Location
    Write-Host 'Everything is as it was. Fix the problem above and run this again.'
    exit 1
}

# ── 2. .env: where the front door keeps its data, Docker's ports on this computer only
Set-Setting 'FRONT_DOOR_DATA' ($data -replace '\\', '/')
if (($composeFile -split ':') -notcontains $overlay) {
    Set-Setting 'COMPOSE_FILE' "$composeFile`:$overlay"
}
Save-Env

# ── 3. Check the configuration before anything depends on it ────────────────
Push-Location (Join-Path $root 'windows')
& $caddyExe validate --config $caddyfile --adapter caddyfile --envfile $envFile
$valid = $LASTEXITCODE
Pop-Location
if ($valid -ne 0) {
    Undo-Changes 'Caddy did not accept the configuration (above).'
}

# ── 4. Docker moves to 127.0.0.1, so the front door can have the ports ──────
Push-Location $root; docker compose up -d; Pop-Location

# ── 5. The service: starts with Windows, restarts if it stops ───────────────
if (Get-Service $service -ErrorAction SilentlyContinue) {
    Stop-Service $service -ErrorAction SilentlyContinue
    & sc.exe delete $service | Out-Null
    Start-Sleep -Seconds 2
}
$bin = "`"$caddyExe`" run --config `"$caddyfile`" --adapter caddyfile --envfile `"$envFile`""
& sc.exe create $service binPath= $bin start= auto DisplayName= 'GoalGetter HTTPS front door' | Out-Null
& sc.exe failure $service reset= 86400 actions= restart/5000/restart/5000/restart/30000 | Out-Null
& sc.exe description $service 'HTTPS for GoalGetter, outside Docker so devices keep their addresses.' | Out-Null
try { Start-Service $service } catch { Undo-Changes "The service didn't start: $($_.Exception.Message)" }

# Answering on the HTTPS port before anybody is sent there.
$answering = $false
for ($i = 0; $i -lt 30 -and -not $answering; $i++) {
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1', [int]$https); $answering = $true } catch { Start-Sleep -Seconds 1 } finally { $client.Dispose() }
}
if (-not $answering) {
    Undo-Changes "The front door didn't answer on port $https within 30 seconds."
}
Say "Service '$service' started and answering on port $https."

# ── Now GoalGetter may send people to it ────────────────────────────────────
Set-Setting 'HTTPS_FRONT_DOOR' 'windows'
Save-Env
Say '.env updated (HTTPS_FRONT_DOOR, FRONT_DOOR_DATA, COMPOSE_FILE).'

# ── 6. Let the office in ─────────────────────────────────────────────────────
Get-NetFirewallRule -DisplayName 'GoalGetter front door' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'GoalGetter front door' -Direction Inbound -Protocol TCP `
    -LocalPort $https, $http, $plain -Action Allow -Profile Domain, Private | Out-Null
Say "Firewall open on $https, $http and $plain (domain and private networks)."

Write-Host ''
Write-Host "Done. Open https://$hostName and sign in, then check Settings > Hosting:"
Write-Host '"GoalGetter sees you as ..." should show your device''s own address.'
if ((Get-Setting 'HTTPS_CERTIFICATE') -in @('', 'internal')) {
    Write-Host "Other devices trust the certificate once: http://$hostName/goalgetter-root.crt"
}
