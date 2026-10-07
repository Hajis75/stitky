@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python neni v PATH. Nainstalujte Python z python.org.
  pause
  exit /b 1
)

echo Instaluji PyInstaller a zavislosti...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo Instalace selhala.
  pause
  exit /b 1
)

echo Sestavuji StitkyTisk.exe ...
python -m PyInstaller --noconfirm --clean StitkyTisk.spec

if errorlevel 1 (
  echo Build selhal.
  pause
  exit /b 1
)

echo.
echo Hotovo: dist\StitkyTisk.exe
echo Soubor muzete zkopirovat kamkoli a spustit dvojklikem.
explorer dist
pause
