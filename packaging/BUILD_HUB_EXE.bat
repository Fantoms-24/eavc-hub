@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM Скрипт лежит в packaging\ — работаем из корня проекта
cd /d "%~dp0.."

echo.
echo ================================================================
echo BUILD HUB (EXE) - OFFLINE READY
echo ================================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo [INFO] Install Python 3.10+ and try again.
    exit /b 1
)

REM Create build venv
if not exist ".venv-build" (
    echo [INFO] Creating venv .venv-build ...
    python -m venv ".venv-build"
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        exit /b 1
    )
)

REM Use Python from venv directly
set "VENV_PYTHON=.venv-build\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python not found in .venv-build\Scripts\
    exit /b 1
)

echo.
echo [INFO] Installing dependencies (internet required on build machine)...
"%VENV_PYTHON%" -m pip install --upgrade pip >nul 2>&1
if exist "requirements\hub.txt" (
    "%VENV_PYTHON%" -m pip install -r requirements\hub.txt
) else (
    "%VENV_PYTHON%" -m pip install flask flask-login openpyxl python-docx lxml reportlab pyinstaller
)
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    exit /b 1
)

echo.
echo [INFO] Preparing offline styles (Bootstrap + Icons) in static\vendor\ ...
set "VENDOR_BOOTSTRAP=static\vendor\bootstrap"
set "VENDOR_BI=static\vendor\bootstrap-icons"
if not exist "%VENDOR_BOOTSTRAP%" mkdir "%VENDOR_BOOTSTRAP%" >nul 2>&1
if not exist "%VENDOR_BI%\fonts" mkdir "%VENDOR_BI%\fonts" >nul 2>&1

REM Bootstrap CSS/JS
if not exist "%VENDOR_BOOTSTRAP%\bootstrap.min.css" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' -OutFile '%VENDOR_BOOTSTRAP%\bootstrap.min.css'"
  if errorlevel 1 ( echo [ERROR] Failed to download bootstrap.min.css & exit /b 1 )
)
if not exist "%VENDOR_BOOTSTRAP%\bootstrap.bundle.min.js" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js' -OutFile '%VENDOR_BOOTSTRAP%\bootstrap.bundle.min.js'"
  if errorlevel 1 ( echo [ERROR] Failed to download bootstrap.bundle.min.js & exit /b 1 )
)

REM Bootstrap Icons (CSS + fonts)
if not exist "%VENDOR_BI%\bootstrap-icons.min.css" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css' -OutFile '%VENDOR_BI%\bootstrap-icons.min.css'"
  if errorlevel 1 ( echo [ERROR] Failed to download bootstrap-icons.min.css & exit /b 1 )
)
if not exist "%VENDOR_BI%\fonts\bootstrap-icons.woff2" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2' -OutFile '%VENDOR_BI%\fonts\bootstrap-icons.woff2'"
  if errorlevel 1 ( echo [ERROR] Failed to download bootstrap-icons.woff2 & exit /b 1 )
)
if not exist "%VENDOR_BI%\fonts\bootstrap-icons.woff" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff' -OutFile '%VENDOR_BI%\fonts\bootstrap-icons.woff'"
  if errorlevel 1 ( echo [ERROR] Failed to download bootstrap-icons.woff & exit /b 1 )
)

echo.
echo [INFO] Cleaning old build/dist ...
if exist "build" rmdir /s /q "build" >nul 2>&1
if exist "dist" rmdir /s /q "dist" >nul 2>&1

echo.
echo [INFO] Building HUB.exe ...
"%VENV_PYTHON%" -m PyInstaller "packaging\hub.spec" --noconfirm
if errorlevel 1 (
    echo [ERROR] Build failed!
    exit /b 1
)

echo [INFO] Building independent updater ...
"%VENV_PYTHON%" -m PyInstaller "packaging\hub_updater.spec" --noconfirm
if errorlevel 1 (
    echo [ERROR] Updater build failed!
    exit /b 1
)
copy /y "dist\EAVC Updater.exe" "dist\EAVC - HUB\EAVC Updater.exe" >nul
if errorlevel 1 (
    echo [ERROR] Could not copy EAVC Updater.exe into HUB package.
    exit /b 1
)

echo.
echo ================================================================
echo [SUCCESS] DONE!
echo ================================================================
echo [INFO] Result: dist\EAVC - HUB\
echo [INFO] Run: dist\EAVC - HUB\EAVC - HUB.exe
echo.
echo [INFO] On offline PC, copy the entire dist\EAVC - HUB\ folder (with _internal) and run EAVC - HUB.exe
echo [INFO] To publish an update, zip the CONTENTS of dist\EAVC - HUB\ (EAVC - HUB.exe + _internal + EAVC Updater.exe).
echo.
exit /b 0
