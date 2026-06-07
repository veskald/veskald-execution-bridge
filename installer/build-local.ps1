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
        $Version = (git describe --tags --always --dirty 2>$null).Trim()
    } catch {}
    if (-not $Version) { $Version = "dev" }
}

$target = "windows-x86_64"
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
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
        Write-Error "ERROR: -Deploy requires the aws CLI. Install from https://aws.amazon.com/cli/"
        exit 1
    }
    $bucket = $env:S3_BUCKET
    if (-not $bucket) {
        Write-Error "ERROR: S3_BUCKET env var is required for -Deploy"
        exit 1
    }
    $prefix = if ($env:S3_PREFIX) { $env:S3_PREFIX } else { "execution-bridge/releases" }
    $region = if ($env:S3_REGION) { $env:S3_REGION } else { "us-east-1" }

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
