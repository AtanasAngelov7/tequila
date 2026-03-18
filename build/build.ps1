# build\build.ps1 — End-to-end Tequila Windows build script (Sprint 15 §29.1–§29.4)
#
# Usage (from repo root):
#   .\build\build.ps1
#   .\build\build.ps1 -SkipFrontend    # skip npm build (reuse existing dist/)
#   .\build\build.ps1 -SkipInstaller   # stop after PyInstaller
#
# Pre-requisites:
#   • Node.js 20+ and npm in PATH
#   • Python 3.12 .venv already created (.\venv\Scripts\python.exe)
#   • PyInstaller in .venv:  pip install pyinstaller
#   • Inno Setup 6 installed to default location (optional, for installer step)

param(
    [switch]$SkipFrontend,
    [switch]$SkipInstaller,
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$BuildDir  = Join-Path $RepoRoot "build"
$DistDir   = Join-Path $RepoRoot "dist"
$FrontendDir = Join-Path $RepoRoot "frontend"
$Python    = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$InnoCompiler = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
}

# ── 0. Clean up previous build ─────────────────────────────────────────────
if ($Clean) {
    Write-Step "Cleaning previous build artifacts"
    if (Test-Path $DistDir) { Remove-Item $DistDir -Recurse -Force }
    $buildOutputDir = Join-Path $BuildDir "output"
    if (Test-Path $buildOutputDir) { Remove-Item $buildOutputDir -Recurse -Force }
    Write-Host "Cleaned." -ForegroundColor Green
}

# ── 1. Frontend build ──────────────────────────────────────────────────────
if (-not $SkipFrontend) {
    Write-Step "Step 1/3: Building React frontend"
    Push-Location $FrontendDir
    try {
        Write-Host "Installing npm dependencies…"
        npm ci --prefer-offline 2>&1 | Write-Host
        Write-Host "Running npm build…"
        npm run build 2>&1 | Write-Host
        $distIndex = Join-Path $FrontendDir "dist\index.html"
        if (-not (Test-Path $distIndex)) {
            throw "Frontend build failed — dist\index.html not found."
        }
        Write-Host "Frontend build complete." -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    Write-Host "Skipping frontend build (-SkipFrontend)." -ForegroundColor Yellow
}

# ── 2. PyInstaller freeze ──────────────────────────────────────────────────
Write-Step "Step 2/3: Freezing with PyInstaller"

if (-not (Test-Path $Python)) {
    throw "Python venv not found at: $Python`nRun: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt pyinstaller"
}

# Ensure PyInstaller is available
& $Python -m PyInstaller --version 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller not found — installing…" -ForegroundColor Yellow
    & $Python -m pip install pyinstaller 2>&1 | Write-Host
}

$specFile = Join-Path $BuildDir "tequila.spec"
Push-Location $RepoRoot
try {
    & $Python -m PyInstaller $specFile `
        --distpath (Join-Path $DistDir "") `
        --workpath (Join-Path $BuildDir "work") `
        --noconfirm `
        --log-level WARN
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

$bundleExe = Join-Path $DistDir "tequila\tequila.exe"
if (-not (Test-Path $bundleExe)) {
    throw "PyInstaller succeeded but tequila.exe was not found at: $bundleExe"
}
Write-Host "PyInstaller bundle complete: $bundleExe" -ForegroundColor Green

# ── 3. Inno Setup installer ────────────────────────────────────────────────
if ($SkipInstaller) {
    Write-Host "Skipping Inno Setup (-SkipInstaller)." -ForegroundColor Yellow
} else {
    Write-Step "Step 3/3: Building Windows installer with Inno Setup"

    if (-not (Test-Path $InnoCompiler)) {
        Write-Host "Inno Setup compiler not found at: $InnoCompiler" -ForegroundColor Yellow
        Write-Host "Download from https://jrsoftware.org/isinfo.php and rerun." -ForegroundColor Yellow
    } else {
        $issFile = Join-Path $BuildDir "installer.iss"
        $outputDir = Join-Path $BuildDir "output"
        New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

        & $InnoCompiler $issFile 2>&1 | Write-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup failed with exit code $LASTEXITCODE"
        }

        $installerGlob = Get-ChildItem -Path $outputDir -Filter "TequilaSetup-*.exe" |
                         Sort-Object LastWriteTime -Descending |
                         Select-Object -First 1
        if ($installerGlob) {
            Write-Host "Installer ready: $($installerGlob.FullName)" -ForegroundColor Green
        } else {
            throw "Installer not found in $outputDir after build."
        }
    }
}

# ── Summary ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Build complete!" -ForegroundColor Green
Write-Host "  Bundle : $DistDir\tequila\"
if (-not $SkipInstaller -and (Test-Path $InnoCompiler)) {
    $installerPath = Join-Path $BuildDir "output"
    Write-Host "  Installer: $installerPath\TequilaSetup-*.exe"
}
Write-Host ""
Write-Host "To test the bundle without installing:"
Write-Host "  .\dist\tequila\tequila.exe"
