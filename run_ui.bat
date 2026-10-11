@echo off
setlocal
title WeChat-AIAgent Launcher

cd /d "%~dp0"
if exist "wechatauto-replica\gui_app.py" cd /d "%~dp0wechatauto-replica"

set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

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

rem ===============================================================
rem 1. Check local virtualenv (venv / .venv)
rem ===============================================================

if not exist "venv\Scripts\python.exe" goto :CHECK_DOT_VENV
"venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :CHECK_DOT_VENV
set "PYTHON_EXE=%CD%\venv\Scripts\python.exe"
set "VENV_ACTIVATE=%CD%\venv\Scripts\activate.bat"
set "ENV_DESC=Project Virtualenv [venv]"
goto :FOUND_PYTHON

:CHECK_DOT_VENV
if not exist ".venv\Scripts\python.exe" goto :CHECK_PARENT_VENV
".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :CHECK_PARENT_VENV
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
set "VENV_ACTIVATE=%CD%\.venv\Scripts\activate.bat"
set "ENV_DESC=Project Virtualenv [.venv]"
goto :FOUND_PYTHON

:CHECK_PARENT_VENV
if not exist "..\venv\Scripts\python.exe" goto :CHECK_PARENT_DOT_VENV
"..\venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :CHECK_PARENT_DOT_VENV
set "PYTHON_EXE=%CD%\..\venv\Scripts\python.exe"
set "VENV_ACTIVATE=%CD%\..\venv\Scripts\activate.bat"
set "ENV_DESC=Root Virtualenv [..\venv]"
goto :FOUND_PYTHON

:CHECK_PARENT_DOT_VENV
if not exist "..\.venv\Scripts\python.exe" goto :CHECK_RUNTIME
"..\.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :CHECK_RUNTIME
set "PYTHON_EXE=%CD%\..\.venv\Scripts\python.exe"
set "VENV_ACTIVATE=%CD%\..\.venv\Scripts\activate.bat"
set "ENV_DESC=Root Virtualenv [..\.venv]"
goto :FOUND_PYTHON

rem ===============================================================
rem 2. Check portable runtime (runtime)
rem ===============================================================

:CHECK_RUNTIME
if not exist "runtime\python.exe" goto :CHECK_PARENT_RUNTIME
"runtime\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :CHECK_PARENT_RUNTIME
set "PYTHON_EXE=%CD%\runtime\python.exe"
set "PATH=%CD%\runtime;%CD%\runtime\Scripts;%PATH%"
set "ENV_DESC=Portable Runtime [runtime]"
goto :FOUND_PYTHON

:CHECK_PARENT_RUNTIME
if not exist "..\runtime\python.exe" goto :CHECK_REPLICA_RUNTIME
"..\runtime\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :CHECK_REPLICA_RUNTIME
set "PYTHON_EXE=%CD%\..\runtime\python.exe"
set "PATH=%CD%\..\runtime;%CD%\..\runtime\Scripts;%PATH%"
set "ENV_DESC=Root Portable Runtime [..\runtime]"
goto :FOUND_PYTHON

:CHECK_REPLICA_RUNTIME
if not exist "wechatauto-replica\runtime\python.exe" goto :NOT_FOUND
"wechatauto-replica\runtime\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 goto :NOT_FOUND
set "PYTHON_EXE=%CD%\wechatauto-replica\runtime\python.exe"
set "PATH=%CD%\wechatauto-replica\runtime;%CD%\wechatauto-replica\runtime\Scripts;%PATH%"
set "ENV_DESC=Replica Portable Runtime [wechatauto-replica\runtime]"
goto :FOUND_PYTHON

rem ===============================================================
rem 3. Environment not found
rem ===============================================================

:NOT_FOUND
echo ===============================================================
echo [ERROR] No Python virtual environment or runtime found!
echo ===============================================================
echo.
echo Please run setup_env.bat first to configure environment:
echo   setup_env.bat
echo.
echo Or create virtualenv manually:
echo   python -m venv venv
echo   venv\Scripts\pip install -r requirements.txt
echo.
echo ===============================================================
pause
exit /b 1

rem ===============================================================
rem 4. Launch Application
rem ===============================================================

:FOUND_PYTHON
if not "%VENV_ACTIVATE%"=="" if exist "%VENV_ACTIVATE%" call "%VENV_ACTIVATE%"

echo ===============================================================
echo      WeChat-AIAgent Launcher
echo ===============================================================
echo [Environment] %ENV_DESC%
echo [Python Path] %PYTHON_EXE%
echo [Working Dir] %CD%
echo ===============================================================
echo.

"%PYTHON_EXE%" gui_app.py

if errorlevel 1 (
    echo.
    echo ===============================================================
    echo [ERROR] Application exited with code: %errorlevel%
    echo Please check console logs or logs directory for details.
    echo ===============================================================
    pause
)
