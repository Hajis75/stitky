@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python neni nainstalovany nebo neni v PATH.
  echo Stahnete z https://www.python.org/downloads/
  echo Pri instalaci zaskrtnete "Add python.exe to PATH".
  pause
  exit /b 1
)

python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Instalace zavislosti selhala.
  pause
  exit /b 1
)

python main.py
if errorlevel 1 pause
