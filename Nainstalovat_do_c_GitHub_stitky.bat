@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "DEST=c:\GitHub\stitky"
set "REPO=https://github.com/Hajis75/stitky.git"

echo ========================================
echo  Instalace do %DEST%
echo ========================================
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo Chybi Git. Stahnete: https://git-scm.com/download/win
  pause
  exit /b 1
)

if not exist "c:\GitHub" mkdir "c:\GitHub"

if exist "%DEST%\.git" (
  echo Slozka uz existuje — aktualizuji...
  pushd "%DEST%"
  git pull
  popd
) else if exist "%DEST%" (
  echo Slozka %DEST% existuje, ale neni git repo.
  echo Prejmenuji ji a naklonuji znovu...
  move "%DEST%" "%DEST%.bak_%RANDOM%"
  git clone "%REPO%" "%DEST%"
) else (
  git clone "%REPO%" "%DEST%"
)

if errorlevel 1 (
  echo Klonovani selhalo.
  pause
  exit /b 1
)

echo.
echo Hotovo: %DEST%
explorer "%DEST%"

if exist "%DEST%\dist\StitkyTisk.exe" (
  start "" "%DEST%\dist\StitkyTisk.exe"
) else if exist "%DEST%\Spustit.bat" (
  start "" "%DEST%\Spustit.bat"
)

pause
