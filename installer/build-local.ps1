# Build the Veskald Execution Bridge desktop app on Windows.
# Output: dist\Veskald-Execution-Bridge-<version>-windows-x86_64.zip
#
# Usage (from PowerShell, inside the project root):
#   .\installer\build-local.ps1                  # version from git
#   .\installer\build-local.ps1 -Version v1.2.3  # pin version
#   .\installer\build-local.ps1 -Deploy          # also push to S3 after build
#
# Requirements:
#   - Python 3.11 on PATH  (python --version)
#   - Git on PATH for auto-version (optional)
#   - AWS CLI on PATH for -Deploy  (aws --version)
#
# Env vars used with -Deploy:
#   S3_BUCKET              required — destination bucket
#   S3_PREFIX              optional — default: execution-bridge/releases
#   S3_REGION              optional — default: us-east-1
#   AWS_PROFILE / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY — standard AWS auth
#   AWS_DOWNLOADS_BASE_URL optional — used for the "public URLs" printout

[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$Deploy
)

$ErrorActionPreference = "Stop"

# Move to project root (parent of installer/)
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

if (-not $Version) {
    try {
        $Version = (git describe --tags --always 2>$null).Trim()
    } catch {}
    if (-not $Version) { $Version = "dev" }
}

$target = "windows-x86_64"

function Ensure-AwsCli {
    if (Get-Command aws -ErrorAction SilentlyContinue) { return }
    Write-Host ">>> aws CLI not found — installing." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Amazon.AWSCLI --silent --accept-source-agreements --accept-package-agreements
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install awscli -y
    } else {
        $msi = Join-Path $env:TEMP "AWSCLIV2.msi"
        Invoke-WebRequest -Uri "https://awscli.amazonaws.com/AWSCLIV2.msi" -OutFile $msi
        Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn" -Wait
        Remove-Item $msi -ErrorAction SilentlyContinue
    }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
        Write-Error "aws CLI install reported success but 'aws' is still not on PATH. Close this window, open a new PowerShell, and re-run."
        exit 1
    }
    Write-Host ">>> aws CLI installed: $((aws --version) 2>&1 | Select-Object -First 1)" -ForegroundColor Green
}

function Ensure-DeployEnv {
    Write-Host ">>> AWS / S3 credentials for this run (Enter to keep the [default]):" -ForegroundColor Cyan
    Write-Host "    (values are set for this PowerShell only — nothing is persisted)" -ForegroundColor Cyan
    Write-Host ""

    function _Read($label, $default = "") {
        if ($default) {
            $v = Read-Host "  $label [$default]"
            if (-not $v) { return $default } else { return $v }
        } else {
            return Read-Host "  $label"
        }
    }
    function _ReadSecret($label, $default = "") {
        $hint = if ($default) { " [keep existing — press Enter]" } else { "" }
        $secure = Read-Host "  $label$hint" -AsSecureString
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
        finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if (-not $plain) { return $default } else { return $plain }
    }

    $defReg  = if ($env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION } else { "us-east-1" }
    $defBuck = if ($env:S3_BUCKET)          { $env:S3_BUCKET }          else { "veskald" }

    $key    = _Read       "AWS_ACCESS_KEY_ID"     $env:AWS_ACCESS_KEY_ID
    $secret = _ReadSecret "AWS_SECRET_ACCESS_KEY" $env:AWS_SECRET_ACCESS_KEY
    $reg    = _Read       "AWS_DEFAULT_REGION"    $defReg
    $buck   = _Read       "S3_BUCKET"             $defBuck
    $defBase = if ($env:AWS_DOWNLOADS_BASE_URL) { $env:AWS_DOWNLOADS_BASE_URL } else { "https://$buck.s3.$reg.amazonaws.com" }
    $base   = _Read       "AWS_DOWNLOADS_BASE_URL" $defBase

    if (-not $key -or -not $secret -or -not $buck) {
        Write-Error "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and S3_BUCKET are required."
        exit 1
    }

    $env:AWS_ACCESS_KEY_ID      = $key
    $env:AWS_SECRET_ACCESS_KEY  = $secret
    $env:AWS_DEFAULT_REGION     = $reg
    $env:S3_BUCKET              = $buck
    $env:AWS_DOWNLOADS_BASE_URL = $base
    Write-Host ""
}

if ($Deploy) {
    Ensure-AwsCli
    Ensure-DeployEnv
}

Write-Host ">>> Building Veskald Execution Bridge $Version for $target" -ForegroundColor Cyan

# ---- Venv ------------------------------------------------------------------
$venv = Join-Path $root ".build-venv"
if (-not (Test-Path $venv)) {
    Write-Host ">>> Creating .build-venv" -ForegroundColor Cyan
    python -m venv $venv
}
$venvPython = Join-Path $venv "Scripts\python.exe"
$venvPip    = Join-Path $venv "Scripts\pip.exe"

& $venvPython -m pip install --upgrade pip wheel | Out-Null
& $venvPip install -r requirements.txt
& $venvPip install -r requirements-gui.txt
& $venvPip install --no-deps "coinbase-advanced-py>=1.8.2"
& $venvPip install "pyinstaller==6.11.1"
# Pillow → PyInstaller auto-converts logo.png to .ico for Windows.
& $venvPip install "Pillow>=10.0.0"

# ---- Icon ------------------------------------------------------------------
# Build looks for installer\assets\logo.png. Drop your icon there.
if (-not (Test-Path "installer\assets\logo.png")) {
    Write-Host "    (warning: installer\assets\logo.png missing — icon will be empty)" -ForegroundColor Yellow
}

# ---- PyInstaller -----------------------------------------------------------
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist")  { Remove-Item -Recurse -Force "dist" }

$pyinstaller = Join-Path $venv "Scripts\pyinstaller.exe"
& $pyinstaller --clean --noconfirm "installer\veskald-execution-bridge.spec"

if (-not (Test-Path "dist\veskald-execution-bridge.exe")) {
    Write-Error "PyInstaller did not produce dist\veskald-execution-bridge.exe"
    exit 1
}

# ---- Package ---------------------------------------------------------------
$stage = "dist\stage"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

Copy-Item "dist\veskald-execution-bridge.exe" -Destination $stage
Copy-Item ".env.example"                 -Destination $stage
Copy-Item "README.md"                    -Destination $stage
Copy-Item "installer\INSTALL.md"         -Destination $stage

$archive = "dist\Veskald-Execution-Bridge-$Version-$target.zip"
if (Test-Path $archive) { Remove-Item $archive }
Compress-Archive -Path "$stage\*" -DestinationPath $archive

# ---- SHA-256 ---------------------------------------------------------------
$hash = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $archive -Leaf)" | Out-File -Encoding ASCII "$archive.sha256"

Write-Host ""
Write-Host ">>> Done." -ForegroundColor Green
Write-Host "    Archive: $archive"
Write-Host "    SHA-256: $hash"
Write-Host ""
Write-Host "Run it:  .\dist\veskald-execution-bridge.exe" -ForegroundColor Cyan

# ---- Deploy to S3 ----------------------------------------------------------
if ($Deploy) {
    $bucket = $env:S3_BUCKET
    $prefix = if ($env:S3_PREFIX) { $env:S3_PREFIX } else { "execution-bridge/releases" }
    $region = if ($env:S3_REGION) { $env:S3_REGION } elseif ($env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION } else { "us-east-1" }

    Write-Host ""
    Write-Host ">>> Deploying to s3://$bucket/$prefix/" -ForegroundColor Cyan

    function Upload-One($file) {
        if (-not (Test-Path $file)) { return }
        $name = Split-Path $file -Leaf
        $stable = $name -replace [regex]::Escape("$Version-"), ""

        $verUrl = "s3://$bucket/$prefix/$Version/$name"
        Write-Host "    upload  $verUrl"
        aws s3 cp $file $verUrl --region $region --no-progress `
            --cache-control "public, max-age=31536000, immutable"

        if ($name -ne $stable) {
            $latestUrl = "s3://$bucket/$prefix/latest/$stable"
            Write-Host "    mirror  $latestUrl"
            aws s3 cp $file $latestUrl --region $region --no-progress `
                --cache-control "public, max-age=300"
        }
    }

    Upload-One $archive
    Upload-One "$archive.sha256"

    Write-Host ""
    $base = if ($env:AWS_DOWNLOADS_BASE_URL) {
        $env:AWS_DOWNLOADS_BASE_URL
    } else {
        "https://$bucket.s3.$region.amazonaws.com"
    }
    Write-Host "    Done. Public URLs:" -ForegroundColor Green
    Write-Host "      $base/$prefix/$Version/"
    Write-Host "      $base/$prefix/latest/   (rolling)"
}
