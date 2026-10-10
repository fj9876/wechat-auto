@echo off
chcp 65001 >nul
title WeChat-AIAgent Virtual Camera Setup
setlocal
cd /d "%~dp0"
set "PY=..\..\runtime\python.exe"
if not exist "%PY%" set "PY=..\..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" setup_vcam.py
