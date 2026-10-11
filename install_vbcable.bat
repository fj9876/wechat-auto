@echo off
title VB-Audio Virtual Cable Setup
cls
echo ===============================================================
echo          VB-Audio Virtual Cable Setup
echo ===============================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "SETUP_EXE=%SCRIPT_DIR%tools\vbcable\VBCABLE_Setup_x64.exe"
if not exist "%SETUP_EXE%" set "SETUP_EXE=%SCRIPT_DIR%wechatauto-replica\tools\vbcable\VBCABLE_Setup_x64.exe"

if not exist "%SETUP_EXE%" (
    echo [ERROR] Installer not found: %SETUP_EXE%
    pause
    exit /b 1
)

echo [*] Requesting Administrator privileges...
echo [*] Please click 'Yes' in Windows UAC prompt.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%SETUP_EXE%' -Verb RunAs"

echo.
echo ===============================================================
echo Post-installation steps:
echo 1. In the installer window, click 'Install Driver'.
echo 2. Recommended Windows Audio settings:
echo    - Default Playback: CABLE Input (VB-Audio Virtual Cable)
echo    - Default Recording: CABLE Output (VB-Audio Virtual Cable)
echo ===============================================================
echo.
pause
