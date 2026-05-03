@echo off
chcp 65001 >nul
echo ========================================
echo Создание файла .env
echo ========================================
echo.

cd /d "%~dp0"

python create_env.py

pause

