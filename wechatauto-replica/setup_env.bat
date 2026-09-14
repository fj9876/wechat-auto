@echo off
title WeChat-AIAgent Environment Setup

cd /d "%~dp0"
if exist "%~dp0wechatauto-replica\runtime\python.exe" cd /d "%~dp0wechatauto-replica"

echo ===============================================================
echo        WeChat-AIAgent Environment Setup and Detection
echo ===============================================================
echo.

REM 1. Check portable runtime
if exist "runtime\python.exe" (
    echo [OK] Portable Python runtime found: runtime\python.exe
    runtime\python.exe --version
    echo [OK] Environment is ready. You can double click run_ui.bat directly!
    echo ===============================================================
    echo.
    goto :DONE
)

REM 2. Check system Python
set "PY_CMD="
py -3.12 --version >nul 2>&1 && set "PY_CMD=py -3.12"
if "%PY_CMD%"=="" (
    py -3.11 --version >nul 2>&1 && set "PY_CMD=py -3.11"
)
if "%PY_CMD%"=="" (
    py -3.10 --version >nul 2>&1 && set "PY_CMD=py -3.10"
)
if "%PY_CMD%"=="" (
    python --version >nul 2>&1 && set "PY_CMD=python"
)

if "%PY_CMD%"=="" (
    echo [ERROR] No Python found on this computer!
    echo Please install Python 3.10+ 64-bit and check "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo [OK] System Python detected: %PY_CMD%
%PY_CMD% --version

REM 3. Check or recreate venv
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Invalid or relocated venv detected, rebuilding...
        rmdir /s /q venv
    )
)

if not exist "venv\Scripts\python.exe" (
    echo [STEP 1/2] Creating virtual environment venv...
    %PY_CMD% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created successfully.
) else (
    echo [OK] Virtual environment is valid.
)

REM 4. Install dependencies
echo.
echo [STEP 2/2] Installing requirements...
venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

if errorlevel 1 (
    echo [WARN] Tsinghua mirror failed, trying default index...
    venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo.
echo ===============================================================
echo   [OK] Environment setup complete!
echo   Double click run_ui.bat to launch WeChat-AIAgent.
echo ===============================================================
echo.

:DONE
pause
