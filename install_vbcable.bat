@echo off
title VB-Audio Virtual Cable Setup
cls
echo ===============================================================
echo          VB-Audio Virtual Cable 虚拟声卡一键安装程序
echo ===============================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "SETUP_EXE=%SCRIPT_DIR%tools\vbcable\VBCABLE_Setup_x64.exe"
if not exist "%SETUP_EXE%" set "SETUP_EXE=%SCRIPT_DIR%wechatauto-replica\tools\vbcable\VBCABLE_Setup_x64.exe"

if not exist "%SETUP_EXE%" (
    echo [ERROR] Not found: %SETUP_EXE%
    pause
    exit /b 1
)

echo [*] 正在以管理员权限启动驱动安装程序...
echo [*] 请在弹出的 Windows UAC 窗口中点击【是】允许运行
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%SETUP_EXE%' -Verb RunAs"

echo.
echo ===============================================================
echo 安装说明:
echo 1. 请在弹出的安装窗口中点击【Install Driver】完成驱动安装
echo 2. 安装完成后系统声音设备中将新增:
echo    - 播放设备: CABLE Input (VB-Audio Virtual Cable)
echo    - 录音设备: CABLE Output (VB-Audio Virtual Cable)
echo ===============================================================
echo.
pause
