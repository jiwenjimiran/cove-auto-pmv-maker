param(
    [switch]$Docker,
    [switch]$Validate
)

$ErrorActionPreference = 'Stop'
$companionDir = $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = 'py'
    $pythonPrefix = @('-3')
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = 'python'
    $pythonPrefix = @()
}
else {
    throw 'Install Python 3.11 or newer, then run this launcher again.'
}

& $pythonCommand @pythonPrefix -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
foreach ($tool in @('ffmpeg', 'ffprobe')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is required in PATH. Install FFmpeg, then run this launcher again."
    }
}

Push-Location $companionDir
try {
    if ($Validate) {
        Write-Host 'Validating Resolve Studio with short fixture renders. Follow the prompts to finish validation.'
        & $pythonCommand @pythonPrefix (Join-Path $companionDir 'smoke.py')
        if ($LASTEXITCODE -ne 0) { throw 'Resolve validation failed. Review the error above.' }
        return
    }

    $tokenPath = Join-Path $companionDir '.companion-token'
    if (Test-Path -LiteralPath $tokenPath) {
        $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
    }
    else {
        $bytes = New-Object byte[] 32
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($bytes) }
        finally { $random.Dispose() }
        $token = [BitConverter]::ToString($bytes).Replace('-', '')
        Set-Content -LiteralPath $tokenPath -Value $token -Encoding Ascii -NoNewline
    }
    if ($token.Length -lt 24) { throw 'The saved companion token is too short. Remove .companion-token and run this launcher again.' }

    $env:COVE_PMV_TOKEN = $token
    $listenAddress = if ($Docker) { '0.0.0.0' } else { '127.0.0.1' }
    $coveUrl = if ($Docker) { 'http://host.docker.internal:8765' } else { 'http://127.0.0.1:8765' }
    Write-Host "Companion URL for Cove: $coveUrl"
    Write-Host "Companion token for Cove: $token"
    Write-Host 'The token is saved in .companion-token and reused next time.'
    if ($Docker) { Write-Host "Allow TCP 8765 only from Docker's network in Windows Firewall." }
    if (-not (Test-Path -LiteralPath (Join-Path $companionDir 'validated-version.json'))) {
        Write-Host 'Before rendering, run Validate Resolve.cmd once with Resolve Studio open.'
    }
    Write-Host 'Keep this window open while making PMVs. Press Ctrl+C to stop.'
    & $pythonCommand @pythonPrefix (Join-Path $companionDir 'server.py') --host $listenAddress
    if ($LASTEXITCODE -ne 0) { throw 'The companion stopped with an error. Review the output above.' }
}
finally {
    Pop-Location
}
