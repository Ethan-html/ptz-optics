@echo off
setlocal
cd /d "%~dp0"
title Build PTZ-Optics Controller installer

echo ============================================================
echo  PTZ-Optics Controller - build installer (.exe)
echo  Run this on the PC where you develop. Other PCs only need
echo  the finished installer from the "dist" folder.
echo ============================================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 ( echo [ERROR] Python 3 not found. Install from python.org and tick "Add to PATH". & goto :fail )
  set PY=python
) else (
  set PY=py
)

where npm >nul 2>nul
if errorlevel 1 ( echo [ERROR] Node.js not found. Install the LTS version from nodejs.org. & goto :fail )

echo [1/4] Installing Python packages...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

echo.
echo [2/4] Bundling the Python backend into ptz-backend.exe ...
if exist backend-dist rmdir /s /q backend-dist
if exist build rmdir /s /q build
%PY% -m PyInstaller --noconfirm --clean --onedir --name ptz-backend ^
  --distpath backend-dist --workpath build ^
  --icon icon.ico ^
  --add-data "index.html;." --add-data "icon.ico;." ^
  --hidden-import keyboard._winkeyboard ^
  app.py
if errorlevel 1 goto :fail

echo.
echo [3/4] Installing Node packages...
call npm install
if errorlevel 1 goto :fail

echo.
echo [4/4] Building the Windows installer...
call npm run dist
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  DONE. Copy one of these to the other computers:
echo    dist\PTZ-Optics-Controller-Setup-*.exe     (installer)
echo    dist\PTZ-Optics-Controller-Portable-*.exe  (no install, just run)
echo ============================================================
pause
exit /b 0

:fail
echo.
echo *** BUILD FAILED - scroll up to see the first error. ***
pause
exit /b 1
