@echo off
echo ╔══════════════════════════════════════════════════════════════════════════════╗
echo ║                     FACEIT HUNTER - Firefox Launcher                         ║
echo ╚══════════════════════════════════════════════════════════════════════════════╝
echo.
echo Запуск Firefox...
echo.

REM Ищем Firefox по стандартным путям
set FIREFOX_PATH=""

if exist "C:\Program Files\Mozilla Firefox\firefox.exe" (
    set FIREFOX_PATH="C:\Program Files\Mozilla Firefox\firefox.exe"
)

if exist "C:\Program Files (x86)\Mozilla Firefox\firefox.exe" (
    set FIREFOX_PATH="C:\Program Files (x86)\Mozilla Firefox\firefox.exe"
)

if %FIREFOX_PATH%=="" (
    echo ❌ Firefox не найден!
    echo.
    echo Установите Firefox или укажите путь вручную в файле start_firefox.bat
    echo.
    pause
    exit
)

echo ✅ Firefox найден: %FIREFOX_PATH%
echo.

REM Запускаем Firefox с вашим профилем
echo Запуск Firefox...
start "" %FIREFOX_PATH%

echo.
echo ✅ Firefox запущен!
echo.
echo ИНСТРУКЦИЯ:
echo 1. Зайдите на Faceit.com и залогиньтесь
echo 2. Запустите программу и выберите "Faceit Hunter"
echo.
echo Это окно можно закрыть
echo.
pause
