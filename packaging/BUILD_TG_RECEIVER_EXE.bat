@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
REM Скрипт лежит в packaging\ — работаем из корня проекта
cd /d "%~dp0.."

echo.
echo ================================================================
echo BUILD TG RECEIVER + TG USER LOGIN (EXE)
echo ================================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    exit /b 1
)

if not exist .venv-build (
    echo [INFO] Creating venv .venv-build ...
    python -m venv .venv-build
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        exit /b 1
    )
)

call .venv-build\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate venv.
    exit /b 1
)

python -m pip install --upgrade pip >nul
python -m pip install -r requirements\tg-receiver.txt
if errorlevel 1 (
    echo [ERROR] Failed to install telethon/pyinstaller.
    exit /b 1
)

if exist build\TG_RECEIVER rmdir /s /q build\TG_RECEIVER >nul 2>&1
if exist build\TG_USER_LOGIN rmdir /s /q build\TG_USER_LOGIN >nul 2>&1
if exist dist\TG_RECEIVER.exe del /q dist\TG_RECEIVER.exe >nul 2>&1
if exist dist\TG_USER_LOGIN.exe del /q dist\TG_USER_LOGIN.exe >nul 2>&1

echo [INFO] Building TG_RECEIVER.exe ...
pyinstaller --noconfirm --clean --onefile --console --name TG_RECEIVER --hidden-import telethon --add-data "config\telegram_receiver_config.example.json;." telegram_receiver_main.py
if errorlevel 1 (
    echo [ERROR] TG_RECEIVER build failed.
    exit /b 1
)

echo [INFO] Building TG_USER_LOGIN.exe ...
pyinstaller --noconfirm --clean --onefile --console --name TG_USER_LOGIN --hidden-import telethon --add-data "config\telegram_receiver_config.example.json;." telegram_user_login.py
if errorlevel 1 (
    echo [ERROR] TG_USER_LOGIN build failed.
    exit /b 1
)

echo.
echo [OK] Done:
echo      dist\TG_RECEIVER.exe
echo      dist\TG_USER_LOGIN.exe
echo.
echo Next steps:
echo  1. Copy config\telegram_receiver_config.example.json to telegram_receiver_config.json
echo  2. Fill api_id, api_hash, target, secret_key
echo  3. Run TG_USER_LOGIN.exe once (phone + code)
echo  4. Run TG_RECEIVER.exe
echo  5. Set intercepts_forward_url on SERVER to http://IP:8787
echo.
exit /b 0
