param([switch]$Report, [string]$CrtPath)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$out = Join-Path $root ('build/pysage-accel-' + $(if ($Report) { 'report' } else { 'prod' }))
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
if (!(Test-Path -LiteralPath $vswhere)) { throw 'Install Visual Studio with the C++ desktop workload.' }
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$vs) { throw 'No Visual Studio x86 C++ toolchain found.' }
$vcvars = Join-Path $vs 'VC/Auxiliary/Build/vcvars32.bat'
New-Item -ItemType Directory -Force -Path $out | Out-Null
# The batch file only bootstraps MSVC. All output stays in the repository build directory.
$definitions = if ($Report) { '' } else { '/DAOTR_PROD' }
$batch = @"
@echo off
call "$vcvars" >nul
if errorlevel 1 exit /b 1
cl /nologo /O2 /MT /W3 /WX /I"$PSScriptRoot/vendor/rpmalloc" /c "$PSScriptRoot/vendor/rpmalloc/rpmalloc.c"
if errorlevel 1 exit /b 1
cl /nologo /O2 /MT /W3 /WX $definitions /LD /I"$PSScriptRoot/vendor/rpmalloc" /Fe:pysage_accel.dll "$PSScriptRoot/src/aotr_accel.cpp" rpmalloc.obj /link kernel32.lib user32.lib advapi32.lib /MAP /DEF:"$PSScriptRoot/src/pysage_accel.def"
if errorlevel 1 exit /b 1
cl /nologo /O2 /MT /W3 /WX /DAOTR_PROD /I"$PSScriptRoot/vendor/rpmalloc" /Fe:compat_test.exe "$PSScriptRoot/compat_test.cpp" rpmalloc.obj /link kernel32.lib user32.lib advapi32.lib
if errorlevel 1 exit /b 1
compat_test.exe
if errorlevel 1 exit /b 1
cl /nologo /O2 /MT /W3 /WX /Fe:crt_test.exe "$PSScriptRoot/crt_test.cpp" /link kernel32.lib
if errorlevel 1 exit /b 1
cl /nologo /O2 /MT /W3 /WX /Fe:rt_harness.exe "$PSScriptRoot/rt_harness.cpp" /link kernel32.lib user32.lib
exit /b %errorlevel%
"@
$script = Join-Path $out 'build.cmd'
Set-Content -LiteralPath $script -Value $batch -Encoding ascii
Push-Location $out
try {
    & $script
    if ($LASTEXITCODE -ne 0) { throw "Accelerator build/test failed with exit code $LASTEXITCODE" }
    if ($CrtPath) {
        & (Join-Path $out 'crt_test.exe') (Resolve-Path -LiteralPath $CrtPath).Path
        if ($LASTEXITCODE -ne 0) { throw "CRT comparison failed with exit code $LASTEXITCODE" }
    }
} finally { Pop-Location }
Write-Output "Built and tested: $(Join-Path $out 'pysage_accel.dll')"
