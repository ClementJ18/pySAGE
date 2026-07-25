@echo off
REM Headless Ghidra runner for the CommandSet RE scripts.
REM Ghidra 12.x needs JDK 21. Edit the two paths below for your machine, then:
REM   run_ghidra.bat CommandSetAnalysis      (or CommandSetCallers / CommandSetMVP / CommandSetCrash)
REM
REM analyzeHeadless.bat chokes on parentheses in paths, so import a copy of
REM game.dat placed at a paren-free location (e.g. this folder), not the one
REM under "C:\Program Files (x86)\...".

setlocal
set "JAVA_HOME=C:\path\to\jdk-21"
set "GHIDRA=C:\path\to\ghidra_12.1.2_PUBLIC"

set "HERE=%~dp0"
set "SCRIPT=%~1"
if "%SCRIPT%"=="" set "SCRIPT=CommandSetAnalysis"
set "TARGET=%HERE%..\engine\game.dat.backup"

call "%GHIDRA%\support\analyzeHeadless.bat" "%HERE%ghidra_proj" cmdset ^
  -import "%TARGET%" ^
  -scriptPath "%HERE%" ^
  -postScript "%SCRIPT%.java" ^
  -deleteProject -analysisTimeoutPerFile 1200
endlocal
