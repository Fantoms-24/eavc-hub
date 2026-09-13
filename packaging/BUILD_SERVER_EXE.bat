@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM Скрипт лежит в packaging\ — работаем из корня проекта
cd /d "%~dp0.."

echo.
echo ═══════════════════════════════════════════════════════════════
echo 🔨 СБОРКА ЦЕНТРАЛЬНОГО СЕРВЕРА (EXE) - EAVC
echo ═══════════════════════════════════════════════════════════════
echo.

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден в PATH.
    echo 💡 Установите Python 3.10+ на машине сборки и повторите.
    exit /b 1
)

REM Создаём отдельное окружение для сборки (чтобы не ломать систему)
if not exist .venv-build (
    echo 📦 Создаю venv .venv-build ...
    python -m venv .venv-build
    if errorlevel 1 (
        echo ❌ Не удалось создать venv.
        exit /b 1
    )
)

call .venv-build\Scripts\activate.bat
if errorlevel 1 (
    echo ❌ Не удалось активировать venv.
    exit /b 1
)

echo.
echo ⬇️  Устанавливаю зависимости (требуется интернет ТОЛЬКО на машине сборки)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ Ошибка установки зависимостей.
    exit /b 1
)

python -m pip install pyinstaller
if errorlevel 1 (
    echo ❌ Ошибка установки PyInstaller.
    exit /b 1
)

echo.
echo 📥 Готовлю офлайн-стили (Bootstrap + Icons) в static\vendor\ ...
set "VENDOR_BOOTSTRAP=static\vendor\bootstrap"
set "VENDOR_BI=static\vendor\bootstrap-icons"
if not exist "%VENDOR_BOOTSTRAP%" mkdir "%VENDOR_BOOTSTRAP%" >nul 2>&1
if not exist "%VENDOR_BI%\fonts" mkdir "%VENDOR_BI%\fonts" >nul 2>&1

REM Bootstrap CSS/JS
if not exist "%VENDOR_BOOTSTRAP%\bootstrap.min.css" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' -OutFile '%VENDOR_BOOTSTRAP%\\bootstrap.min.css'"
  if errorlevel 1 ( echo ❌ Не удалось скачать bootstrap.min.css & exit /b 1 )
)
if not exist "%VENDOR_BOOTSTRAP%\bootstrap.bundle.min.js" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js' -OutFile '%VENDOR_BOOTSTRAP%\\bootstrap.bundle.min.js'"
  if errorlevel 1 ( echo ❌ Не удалось скачать bootstrap.bundle.min.js & exit /b 1 )
)

REM Bootstrap Icons (CSS + fonts)
if not exist "%VENDOR_BI%\bootstrap-icons.min.css" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css' -OutFile '%VENDOR_BI%\\bootstrap-icons.min.css'"
  if errorlevel 1 ( echo ❌ Не удалось скачать bootstrap-icons.min.css & exit /b 1 )
)
if not exist "%VENDOR_BI%\fonts\bootstrap-icons.woff2" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2' -OutFile '%VENDOR_BI%\\fonts\\bootstrap-icons.woff2'"
  if errorlevel 1 ( echo ❌ Не удалось скачать bootstrap-icons.woff2 & exit /b 1 )
)
if not exist "%VENDOR_BI%\fonts\bootstrap-icons.woff" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff' -OutFile '%VENDOR_BI%\\fonts\\bootstrap-icons.woff'"
  if errorlevel 1 ( echo ❌ Не удалось скачать bootstrap-icons.woff & exit /b 1 )
)

echo.
echo 🧹 Удаляю старые build/dist ...
if exist build\server rmdir /s /q build\server >nul 2>&1
if exist "dist\EAVC - SERVER" rmdir /s /q "dist\EAVC - SERVER" >nul 2>&1

echo.
echo 🚀 Собираю SERVER.exe ...
pyinstaller packaging\server.spec --noconfirm
if errorlevel 1 (
    echo ❌ Ошибка при сборке!
    exit /b 1
)

echo.
echo ═══════════════════════════════════════════════════════════════
echo ✅ ГОТОВО!
echo ═══════════════════════════════════════════════════════════════
echo 📂 Результат: dist\EAVC - SERVER\
echo    ▶ Запуск: dist\EAVC - SERVER\EAVC - SERVER.exe
echo.
echo 💡 На сервере скопируйте ЦЕЛИКОМ папку dist\EAVC - SERVER\ (вместе с _internal) и запускайте EAVC - SERVER.exe
echo.
exit /b 0
