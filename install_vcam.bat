@echo off
chcp 65001 >nul
title WeChat-AIAgent Virtual Camera Setup
setlocal
cd /d "%~dp0"
if exist "wechatauto-replica\tools\vcam\install_vcam.bat" (
    call "wechatauto-replica\tools\vcam\install_vcam.bat"
) else if exist "tools\vcam\install_vcam.bat" (
    call "tools\vcam\install_vcam.bat"
) else (
    echo [ERROR] install_vcam.bat not found!
    pause
)
