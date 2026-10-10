@echo off
chcp 65001 >nul
title WeChat-AIAgent 微信AI自动回复控制台

cd /d "%~dp0"
if exist "wechatauto-replica\gui_app.py" cd /d "%~dp0wechatauto-replica"

REM Environment isolation
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

REM 彻底将所有 AI 模型与缓存路径重定向至本项目 models 目录 (坚决不占用 C 盘空间)
set "PROJECT_MODELS=%CD%\models"
if not exist "%PROJECT_MODELS%" if exist "%~dp0wechatauto-replica\models" set "PROJECT_MODELS=%~dp0wechatauto-replica\models"
if not exist "%PROJECT_MODELS%" if exist "%~dp0models" set "PROJECT_MODELS=%~dp0models"

set "MODELSCOPE_CACHE=%PROJECT_MODELS%\modelscope"
set "HF_HOME=%PROJECT_MODELS%\huggingface"
set "HUGGINGFACE_HUB_CACHE=%PROJECT_MODELS%\huggingface\hub"
set "TORCH_HOME=%PROJECT_MODELS%\torch"

set "PYTHON_EXE="
set "VENV_ACTIVATE="
set "ENV_DESC="

REM ===============================================================
REM 1. 优先检查本项目虚拟环境 (venv / .venv)
REM ===============================================================

REM 1.1 当前目录下 venv
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%CD%\venv\Scripts\python.exe"
        set "VENV_ACTIVATE=%CD%\venv\Scripts\activate.bat"
        set "ENV_DESC=本项目虚拟环境 [venv]"
        goto :FOUND_PYTHON
    )
)

REM 1.2 当前目录下 .venv
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
        set "VENV_ACTIVATE=%CD%\.venv\Scripts\activate.bat"
        set "ENV_DESC=本项目虚拟环境 [.venv]"
        goto :FOUND_PYTHON
    )
)

REM 1.3 父目录下 venv
if exist "..\venv\Scripts\python.exe" (
    "..\venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%CD%\..\venv\Scripts\python.exe"
        set "VENV_ACTIVATE=%CD%\..\venv\Scripts\activate.bat"
        set "ENV_DESC=本项目根目录虚拟环境 [..\venv]"
        goto :FOUND_PYTHON
    )
)

REM 1.4 父目录下 .venv
if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%CD%\..\.venv\Scripts\python.exe"
        set "VENV_ACTIVATE=%CD%\..\.venv\Scripts\activate.bat"
        set "ENV_DESC=本项目根目录虚拟环境 [..\.venv]"
        goto :FOUND_PYTHON
    )
)

REM ===============================================================
REM 2. 检查本项目内置绿色便携运行环境 (runtime)
REM ===============================================================

if exist "runtime\python.exe" (
    "runtime\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%CD%\runtime\python.exe"
        set "PATH=%CD%\runtime;%CD%\runtime\Scripts;%PATH%"
        set "ENV_DESC=本项目内置便携运行时 [runtime]"
        goto :FOUND_PYTHON
    )
)

if exist "..\runtime\python.exe" (
    "..\runtime\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%CD%\..\runtime\python.exe"
        set "PATH=%CD%\..\runtime;%CD%\..\runtime\Scripts;%PATH%"
        set "ENV_DESC=本项目根目录便携运行时 [..\runtime]"
        goto :FOUND_PYTHON
    )
)

if exist "wechatauto-replica\runtime\python.exe" (
    "wechatauto-replica\runtime\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%CD%\wechatauto-replica\runtime\python.exe"
        set "PATH=%CD%\wechatauto-replica\runtime;%CD%\wechatauto-replica\runtime\Scripts;%PATH%"
        set "ENV_DESC=本项目便携运行时 [wechatauto-replica\runtime]"
        goto :FOUND_PYTHON
    )
)

REM ===============================================================
REM 3. 严格拦截：未找到本项目虚拟环境或内置运行时，严禁静默调用系统 Python
REM ===============================================================
echo ===============================================================
echo [错误] 未检测到本项目可用的专属虚拟环境 (venv/.venv) 或内置运行时！
echo ===============================================================
echo.
echo 本程序严格要求必须在【本项目专属的虚拟环境】下运行，
echo 严禁直接调用全局系统 Python，以避免缺少依赖或全局环境冲突导致崩溃。
echo.
echo 【解决方案】：
echo   1. 运行项目根目录下的 setup_env.bat 自动为本项目创建虚拟环境并安装依赖；
echo   2. 或者在终端手动为本项目创建虚拟环境并激活安装依赖：
echo      python -m venv venv
echo      venv\Scripts\pip install -r requirements.txt
echo.
echo ===============================================================
pause
exit /b 1

:FOUND_PYTHON
REM 若有虚拟环境激活脚本，执行激活
if not "%VENV_ACTIVATE%"=="" if exist "%VENV_ACTIVATE%" (
    call "%VENV_ACTIVATE%"
)

echo ===============================================================
echo      WeChat-AIAgent 启动中...
echo ===============================================================
echo.
echo [环境模式] %ENV_DESC%
echo [Python解释器] %PYTHON_EXE%
echo [工作目录] %CD%
echo [启动目标] gui_app.py (原生桌面 GUI)
echo.
echo 提示：如需退出程序，请直接关闭窗口或在此控制台按 Ctrl+C。
echo ===============================================================
echo.

"%PYTHON_EXE%" gui_app.py

if errorlevel 1 (
    echo.
    echo ===============================================================
    echo [提示] 程序已退出 (退出码: %errorlevel%)
    echo 如遇问题，请查看 logs 目录下的日志文件或控制台输出。
    echo ===============================================================
    pause
)
