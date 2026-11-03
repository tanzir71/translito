[CmdletBinding()]
param(
    [switch]$SkipDependencies,
    [string]$BuildRoot,
    [string]$OutputDirectory,
    [string]$FrozenSource
)

$ErrorActionPreference = "Stop"
$installerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $BuildRoot) { $BuildRoot = $installerDir }
$BuildRoot = [System.IO.Path]::GetFullPath($BuildRoot)
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
$venvDir = Join-Path $BuildRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$version = (Get-Content -LiteralPath (Join-Path $installerDir 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid installer/VERSION.' }
$buildId = [Guid]::NewGuid().ToString('N').Substring(0, 8)
$stageRoot = Join-Path $BuildRoot ".p\$buildId"
$releaseDistRoot = Join-Path $stageRoot 'd'
$pyinstallerWork = Join-Path $stageRoot 'w'
$releaseAppDir = Join-Path $releaseDistRoot "Translito"
if ($releaseAppDir.Length -gt 70) { throw 'BuildRoot is too long for Inno dependency paths. Use a short path such as D:\TranslitoBuild.' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $BuildRoot "output\$version" }
$outputDir = [IO.Path]::GetFullPath($OutputDirectory)
$portableOutput = Join-Path $outputDir "TranslitoPortable-$version.zip"
$installerOutput = Join-Path $outputDir "TranslitoSetup-$version.exe"
$windowsChecksums = Join-Path $outputDir 'SHA256SUMS-Windows.txt'
foreach ($artifact in @($portableOutput, $installerOutput, $windowsChecksums)) {
    if (Test-Path -LiteralPath $artifact) { throw "Existing release artifact preserved: $artifact. Choose a new OutputDirectory." }
}
$innoText = Get-Content -LiteralPath (Join-Path $installerDir 'Translito.iss') -Raw
$resourceText = Get-Content -LiteralPath (Join-Path $installerDir 'version_info.txt') -Raw
if (-not $innoText.Contains("#define MyAppVersion `"$version`"") -or -not $resourceText.Contains("u'ProductVersion', u'$version'")) {
    throw 'Installer and EXE version metadata must match VERSION.'
}

Push-Location $installerDir
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        python -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Unable to create the build environment." }
    }

    if (-not $SkipDependencies) {
        & $venvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Unable to update pip." }
        & $venvPython -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "Unable to install build dependencies." }
    }

    if ($FrozenSource) {
        $FrozenSource = (Resolve-Path -LiteralPath $FrozenSource).Path
        $frozenExe = Join-Path $FrozenSource 'Translito.exe'
        if (-not (Test-Path -LiteralPath $frozenExe) -or
            (Get-Item -LiteralPath $frozenExe).VersionInfo.ProductVersion -ne $version) {
            throw 'FrozenSource must contain an already-built Translito EXE with the matching version.'
        }
        New-Item -ItemType Directory -Path $releaseDistRoot -Force | Out-Null
        Copy-Item -LiteralPath $FrozenSource -Destination $releaseAppDir -Recurse
    }
    else {
        & $venvPython -m PyInstaller Translito.spec --noconfirm --clean --workpath $pyinstallerWork --distpath $releaseDistRoot
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
    }

    $engineData = Join-Path (Split-Path -Parent $installerDir) 'engines\data'
    foreach ($sourceData in Get-ChildItem -LiteralPath $engineData -File -Recurse) {
        $relativeData = $sourceData.FullName.Substring($engineData.TrimEnd('\').Length + 1)
        $frozenData = Join-Path $releaseAppDir "_internal\engines\data\$relativeData"
        if (-not (Test-Path -LiteralPath $frozenData) -or
            (Get-FileHash -LiteralPath $sourceData.FullName -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $frozenData -Algorithm SHA256).Hash) {
            throw "Frozen engine data is missing or changed: $relativeData"
        }
    }
    $tooLong = Get-ChildItem -LiteralPath $releaseAppDir -File -Recurse |
        Where-Object { $_.FullName.Length -gt 259 } | Select-Object -First 1
    if ($tooLong) { throw 'A packaged dependency path exceeds Inno limits. Use a shorter BuildRoot.' }

    # Probe the frozen EXE, not the build Python. Missing native dependencies
    # must fail before either downloadable artifact is produced.
    $runtimeReport = Join-Path $stageRoot 'runtime-check.json'
    $probe = Start-Process -FilePath (Join-Path $releaseAppDir 'Translito.exe') -ArgumentList @('--check-runtime', ('"' + $runtimeReport + '"')) -WindowStyle Hidden -PassThru
    if (-not $probe.WaitForExit(120000)) {
        Stop-Process -Id $probe.Id -ErrorAction SilentlyContinue
        throw 'Frozen runtime check timed out.'
    }
    $probe.Refresh()
    if ($probe.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $runtimeReport)) {
        throw "Frozen runtime check failed. Report: $runtimeReport"
    }
    $runtimeResult = Get-Content -LiteralPath $runtimeReport -Raw | ConvertFrom-Json
    if (-not $runtimeResult.ok -or -not $runtimeResult.frozen) {
        throw "Frozen runtime check did not pass: $runtimeReport"
    }

    $cablePackage = Join-Path $installerDir "redist\vbcable\VBCABLE_Driver_Pack45.zip"
    $cablePin = ((Get-Content -LiteralPath (Join-Path $installerDir "vbcable.sha256") -Raw).Trim() -split '\s+')[0]
    if ((Get-FileHash -LiteralPath $cablePackage -Algorithm SHA256).Hash.ToLowerInvariant() -ne $cablePin) {
        throw "Bundled VB-CABLE package checksum mismatch."
    }
    $cableDestination = Join-Path $releaseAppDir "redist\vbcable"
    New-Item -ItemType Directory -Path $cableDestination -Force | Out-Null
    Copy-Item -LiteralPath $cablePackage -Destination $cableDestination -Force
    Copy-Item -LiteralPath (Join-Path $installerDir "redist\vbcable\NOTICE.txt") -Destination $cableDestination -Force
    Copy-Item -LiteralPath (Join-Path $installerDir "vbcable.sha256") -Destination $cableDestination -Force

    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    Copy-Item -LiteralPath $runtimeReport -Destination (Join-Path $outputDir 'runtime-check.json')

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

    $runtimeBytes = [long](Get-ChildItem -LiteralPath $releaseAppDir -File -Recurse | Measure-Object -Property Length -Sum).Sum
    & $iscc "/DSourceDir=$releaseAppDir" "/DOutputDir=$outputDir" "/DRuntimeBytes=$runtimeBytes" Translito.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }

    @($installerOutput, $portableOutput) | ForEach-Object {
        $artifactHash = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()
        "$artifactHash  $([IO.Path]::GetFileName($_))"
    } | Set-Content -LiteralPath $windowsChecksums -Encoding ASCII

    Write-Host "Portable Windows app ready: $portableOutput"
    Write-Host "Windows installer ready: $installerOutput"
}
finally {
    Pop-Location
}
