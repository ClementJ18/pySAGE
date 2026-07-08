@echo off
REM Build a standalone, self-contained SageLint Sublime package: freeze the sage_lint CLI into
REM a binary, stage the plugin with that binary in bin\, and zip it to a .sublime-package.
REM The result needs no Python and no checkout on the target machine.
REM
REM Run by double-clicking, or from any directory:  sage_lint\plugins\sublime\build_package.bat
REM Output (under dist\, gitignored):
REM   dist\SageLint\                 - folder to drop into Sublime's Packages directory
REM   dist\SageLint.sublime-package  - zip to drop into the Installed Packages directory
REM PyInstaller binaries are not cross-platform: run this once on each OS you support.

setlocal

REM This script lives at <root>\sage_lint\plugins\sublime\ ; the repo root is three levels up.
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\..\.." || (echo [error] could not locate the repo root & exit /b 1)
set "ROOT=%CD%"

REM Prefer the project's virtualenv interpreter when present, else whatever python is on PATH.
set "PY=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"

echo === [1/4] Building the standalone sage_lint binary ===
"%PY%" -m PyInstaller sage_lint\sage-lint-cli.spec --noconfirm ^
    --distpath "%ROOT%\dist" --workpath "%ROOT%\build\sagelint-cli-build"
if errorlevel 1 (echo [error] PyInstaller build failed ^(is it installed? pip install -e .[lint-ui]^) & popd & exit /b 1)
if not exist "%ROOT%\dist\sage_lint.exe" (echo [error] binary missing after build & popd & exit /b 1)

echo === [2/4] Staging the plugin files ===
set "STAGE=%ROOT%\dist\SageLint"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
REM Copy the package runtime files, leaving out dev-only scripts and caches. robocopy exit
REM codes below 8 all mean success, so only >=8 is a real failure.
REM Keep .python-version: it selects Sublime's Python 3.8 plugin host, without which the
REM package loads under the legacy 3.3 host and f-strings raise SyntaxError on import.
REM Keep .no-sublime-package: it tells Package Control to install this as a loose folder
REM rather than a zip, so the bundled bin\ binary lands on disk where subprocess can exec it
REM (files inside a .sublime-package zip are never extracted and have no filesystem path).
robocopy "%SCRIPT_DIR%." "%STAGE%" /E ^
    /XD __pycache__ bin ^
    /XF build_package.bat install.sh install.bat generate_syntax.py >nul
if errorlevel 8 (echo [error] staging copy failed & popd & exit /b 1)

echo === [3/4] Bundling the binary into bin\ ===
mkdir "%STAGE%\bin" 2>nul
copy /y "%ROOT%\dist\sage_lint.exe" "%STAGE%\bin\sage_lint.exe" >nul
if errorlevel 1 (echo [error] could not copy the binary into the package & popd & exit /b 1)

echo === [4/4] Zipping the .sublime-package ===
set "PKG=%ROOT%\dist\SageLint.sublime-package"
if exist "%PKG%" del /q "%PKG%"
REM Compress-Archive appends .zip, so write SageLint.zip then rename to .sublime-package. The
REM zip's root holds the plugin files directly (what Installed Packages expects), via STAGE\*.
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%ROOT%\dist\SageLint.zip' -Force"
if errorlevel 1 (echo [error] zip step failed & popd & exit /b 1)
move /y "%ROOT%\dist\SageLint.zip" "%PKG%" >nul

echo.
echo Done. Standalone package built:
echo   Folder : %STAGE%
echo   Zip    : %PKG%
echo.
echo Install either way (no Python or checkout needed on the target machine):
echo   - copy the SageLint folder into Sublime's Packages directory
echo     ^(Preferences ^> Browse Packages...^), or
echo   - copy SageLint.sublime-package into the Installed Packages directory.

popd
endlocal
