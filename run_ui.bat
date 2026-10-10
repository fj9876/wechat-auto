@echo off
chcp 65001 >nul
title WeChat-AIAgent 微信AI自动回复控制台

cd /d "%~dp0"
if exist "wechatauto-replica\gui_app.py" cd /d "%~dp0wechatauto-replica"

REM Environment isolation
REM set "PYTHONNOUSERSITE=1"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

REM 彻底将所有 AI 模型与缓存路径重定向至本项目 models 目录 (坚决不占用 C 盘空间)
set "PROJECT_MODELS=%CD%\models"
if not exist "%PROJECT_MODELS%" (
    if exist "%~dp0wechatauto-replica\models" set "PROJECT_MODELS=%~dp0wechatauto-replica\models"
    if exist "%~dp0models" set "PROJECT_MODELS=%~dp0models"
)
set "MODELSCOPE_CACHE=%PROJECT_MODELS%\modelscope"
set "HF_HOME=%PROJECT_MODELS%\huggingface"
set "HUGGINGFACE_HUB_CACHE=%PROJECT_MODELS%\huggingface\hub"
set "TORCH_HOME=%PROJECT_MODELS%\torch"

set "PYTHON_EXE="

REM 1. Check portable runtime
if exist "runtime\python.exe" (
    set "PYTHON_EXE=runtime\python.exe"
    goto :FOUND_PYTHON
)

if exist "wechatauto-replica\runtime\python.exe" (
    set "PYTHON_EXE=wechatauto-replica\runtime\python.exe"
    goto :FOUND_PYTHON
)

if exist "..\runtime\python.exe" (
    set "PYTHON_EXE=..\runtime\python.exe"
    goto :FOUND_PYTHON
)

REM 2. Check virtualenv
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=venv\Scripts\python.exe"
        goto :FOUND_PYTHON
    )
)

if exist "wechatauto-replica\venv\Scripts\python.exe" (
    "wechatauto-replica\venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=wechatauto-replica\venv\Scripts\python.exe"
        goto :FOUND_PYTHON
    )
)

REM 3. Check system Python
py -3.12 -c "import sys" >nul 2>&1 && set "PYTHON_EXE=py -3.12" && goto :FOUND_PYTHON
python -c "import sys" >nul 2>&1 && set "PYTHON_EXE=python" && goto :FOUND_PYTHON

:NOT_FOUND
echo ===============================================================
echo [ERROR] No Python runtime found!
echo Please ensure the runtime folder exists.
echo ===============================================================
echo.
pause
exit /b 1

:FOUND_PYTHON
echo ===============================================================
echo      WeChat-AIAgent 启动中...
echo ===============================================================
echo.
echo [环境] Python解释器: %PYTHON_EXE%
echo [环境] 运行目录: %CD%
echo [启动] 正在启动客户端图形界面 (Tkinter GUI)...
echo.
echo 提示：如需退出程序，请直接关闭窗口或在此控制台按 Ctrl+C。
echo ===============================================================
echo.

%PYTHON_EXE% gui_app.py

if errorlevel 1 (
    echo.
    echo ===============================================================
    echo [提示] 程序已退出 (退出码: %errorlevel%)
    echo 如遇问题，请查看 logs 目录下的日志文件。
    echo ===============================================================
    pause
)
