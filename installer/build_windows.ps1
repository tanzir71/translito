[CmdletBinding()]
param(
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
$installerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $installerDir ".venv\Scripts\python.exe"
$releaseDistRoot = Join-Path $installerDir ".packaging\release-dist"
$releaseAppDir = Join-Path $releaseDistRoot "Translito"

Push-Location $installerDir
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Unable to create the build environment." }
    }

    if (-not $SkipDependencies) {
        & $venvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Unable to update pip." }
        & $venvPython -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "Unable to install build dependencies." }
    }

    & $venvPython -m PyInstaller Translito.spec --noconfirm --clean --distpath $releaseDistRoot
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $outputDir = Join-Path $installerDir "output"
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

    $portableOutput = Join-Path $outputDir "TranslitoPortable-1.0.0.zip"
    if (Test-Path -LiteralPath $portableOutput) {
        Remove-Item -LiteralPath $portableOutput -Force
    }
    & tar.exe -a -c -f $portableOutput -C $releaseDistRoot "Translito"
    if ($LASTEXITCODE -ne 0) { throw "Portable ZIP build failed." }

    $innoCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $iscc = $innoCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $iscc) {
        throw "Inno Setup 6 is required. Install it with: winget install JRSoftware.InnoSetup"
    }

    & $iscc "/DSourceDir=$releaseAppDir" Translito.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }

    $installerOutput = Join-Path $outputDir "TranslitoSetup-1.0.0.exe"
    Write-Host "Portable Windows app ready: $portableOutput"
    Write-Host "Windows installer ready: $installerOutput"
}
finally {
    Pop-Location
}
