[CmdletBinding()]
param([string]$BuildRoot, [string]$VcVars)

$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
if (-not $BuildRoot) {
    $BuildRoot = Join-Path $env:TEMP ('Translito-native-' + [Guid]::NewGuid().ToString('N'))
}
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
if (-not $VcVars) {
    $taskVswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $taskVswhere)) { throw 'Visual Studio C++ build tools are required.' }
    $taskVsRoot = & $taskVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $taskVsRoot) { throw 'Visual Studio C++ build tools were not found.' }
    $VcVars = Join-Path $taskVsRoot 'VC\Auxiliary\Build\vcvars64.bat'
}
$VcVars = (Resolve-Path -LiteralPath $VcVars).Path
foreach ($taskPath in @($VcVars, $BuildRoot, $taskRepo)) {
    if ($taskPath -match '[%!"\r\n]' -or $taskPath -match '[^\x20-\x7e]') {
        throw 'Use plain ASCII build paths without percent signs, exclamation marks or quotes.'
    }
}
$taskSource = Join-Path $taskRepo 'native_windows\process_loopback.cpp'
$taskDll = Join-Path $BuildRoot 'TranslitoLoopback.dll'
$taskObj = Join-Path $BuildRoot 'process_loopback.obj'
$taskLib = Join-Path $BuildRoot 'TranslitoLoopback.lib'
$taskBatch = Join-Path $BuildRoot 'build-loopback.cmd'
@"
@echo off
call "$VcVars" >nul
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /W4 /O2 /MT /EHsc /LD /DUNICODE /D_UNICODE /D_WIN32_WINNT=0x0A00 /Fo"$taskObj" "$taskSource" /link /Brepro /OUT:"$taskDll" /IMPLIB:"$taskLib" ole32.lib mmdevapi.lib uuid.lib
exit /b %errorlevel%
"@ | Set-Content -LiteralPath $taskBatch -Encoding ASCII
& cmd.exe /d /c $taskBatch
if ($LASTEXITCODE -ne 0) { throw 'Process-loopback bridge build failed.' }
$taskDestination = Join-Path $taskRepo 'engines\data\windows'
New-Item -ItemType Directory -Path $taskDestination -Force | Out-Null
Copy-Item -LiteralPath $taskDll -Destination $taskDestination -Force
@{
    sha256 = (Get-FileHash -LiteralPath $taskDll -Algorithm SHA256).Hash.ToLowerInvariant()
    source_sha256 = (Get-FileHash -LiteralPath $taskSource -Algorithm SHA256).Hash.ToLowerInvariant()
    source = 'native_windows/process_loopback.cpp'
    abi = 1
    architecture = 'x64'
    format = '48000 Hz stereo PCM16'
    compiler = 'MSVC x64 /std:c++17 /O2 /MT; linker /Brepro'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskDestination 'process_loopback.json') -Encoding UTF8
Write-Host "Process-loopback DLL and source checksums updated in $taskDestination"
