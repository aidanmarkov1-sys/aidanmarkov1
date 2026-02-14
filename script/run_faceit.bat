@echo off
echo ╔══════════════════════════════════════════════════════════════════════════════╗
echo ║                    FACEIT HUNTER - Quick Launch                              ║
echo ╚══════════════════════════════════════════════════════════════════════════════╝
echo.

REM Запускаем Firefox
cd script
start start_firefox.bat
cd ..

echo ✅ Firefox запускается...
echo.
echo ИНСТРУКЦИЯ:
echo 1. Дождитесь открытия Firefox
echo 2. Зайдите на Faceit.com и залогиньтесь
echo 3. Нажмите Enter чтобы запустить программу
echo.
pause

REM Запускаем программу
call run.bat
