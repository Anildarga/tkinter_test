param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseVersion
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$source = Get-Content -Raw (Join-Path $root "main.py")
if ($source -notmatch ('APP_VERSION\s*=\s*"' + [regex]::Escape($ReleaseVersion) + '"')) {
    throw "Set APP_VERSION in main.py to $ReleaseVersion before building."
}

$work = Join-Path $root "build-modern"
$dist = Join-Path $root "dist-modern"
$spec = Join-Path $work "spec"
New-Item -ItemType Directory -Path $spec -Force | Out-Null
pyinstaller --noconfirm --clean --onedir --windowed --name SampleApp `
    --workpath $work --distpath $dist --specpath $spec main.py
if ($LASTEXITCODE -ne 0) {
    throw "SampleApp build failed with exit code $LASTEXITCODE."
}

pyinstaller --noconfirm --clean --onefile --windowed --name Updater `
    --workpath $work --distpath $dist --specpath $spec updater.py
if ($LASTEXITCODE -ne 0) {
    throw "Updater build failed with exit code $LASTEXITCODE."
}

Copy-Item -LiteralPath (Join-Path $dist "Updater.exe") `
    -Destination (Join-Path $dist "SampleApp\Updater.exe") -Force

$appDir = Join-Path $dist "SampleApp"
if (-not (Test-Path (Join-Path $appDir "SampleApp.exe"))) {
    throw "Built application executable is missing."
}
Write-Output "Built app bundle: $appDir"
Write-Output "Version: $ReleaseVersion"
