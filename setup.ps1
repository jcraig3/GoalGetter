# GoalGetter first-time setup (Windows).
#
# Creates .env from .env.example with fresh random secrets, and optionally
# switches HTTPS on for a name:
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Https goals.internal
#
# Then:  docker compose up -d
#
# Never touches an existing .env: a new database password would lock you out
# of the database it already made, and a new encryption key would make every
# stored credential unreadable. Edit .env by hand instead.
param([string]$Https = '')

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

# A bare name or address: "https://goals.internal" or a space would be written
# into HTTPS_HOST as it is, and nothing would work (P5-4).
if ($PSBoundParameters.ContainsKey('Https')) {
    if (-not $Https) {
        Write-Host '-Https needs a name after it, e.g.  setup.ps1 -Https goals.internal'
        exit 2
    }
    if ($Https -match '://') {
        Write-Host 'Give just the name, without https:// - e.g. goals.internal'
        exit 2
    }
    # P6-4: the port has its own setting.
    if ($Https -match ':') {
        Write-Host 'Leave the port out: give just the name, then set HTTPS_PORT in .env (e.g. HTTPS_PORT=8443)'
        exit 2
    }
    if ($Https -notmatch '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$') {
        Write-Host "`"$Https`" is not a name or address. Use letters, digits, dots and dashes, e.g. goals.internal"
        exit 2
    }
}
$target = Join-Path $here '.env'

if (Test-Path $target) {
    Write-Host '.env already exists, so nothing was changed. Edit it by hand -'
    Write-Host 'see documentation\20-hosting.md.'
    exit 1
}

function New-Secret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

# [^\r\n]* rather than .* so a file with Windows line endings keeps them.
$text = [IO.File]::ReadAllText((Join-Path $here '.env.example'))
$text = $text -replace '(?m)^POSTGRES_PASSWORD=[^\r\n]*', "POSTGRES_PASSWORD=$(New-Secret)"
$text = $text -replace '(?m)^ENCRYPTION_KEY=[^\r\n]*', "ENCRYPTION_KEY=$(New-Secret)"
if ($Https) {
    $text = $text -replace '(?m)^HTTPS_HOST=[^\r\n]*', "HTTPS_HOST=$Https"
}
# No byte-order mark: Compose would read it as part of the first line.
[IO.File]::WriteAllText($target, $text, (New-Object Text.UTF8Encoding $false))

if (Test-Path (Join-Path $here 'volumes\postgres\18')) {
    Write-Host 'Warning: volumes\postgres already holds a database, made with an older'
    Write-Host 'password. Put that password in .env as POSTGRES_PASSWORD, or the app'
    Write-Host 'cannot connect to it.'
}

Write-Host 'Created .env with new secrets.'
Write-Host ''
Write-Host 'Next:'
Write-Host '  docker compose up -d'
if ($Https) {
    Write-Host "  then open https://$Https  (and see documentation\20-hosting.md to trust it)"
} else {
    Write-Host '  then open http://localhost:8080'
}
