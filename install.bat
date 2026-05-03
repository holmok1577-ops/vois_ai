@echo off
chcp 65001 >nul
echo Установка зависимостей для голосового помощника...
echo.

cd /d "%~dp0"
pip install -r requirements.txt

echo.
echo Установка завершена!
echo Не забудьте создать файл .env и указать в нем YANDEX_CLOUD_API_KEY и YANDEX_CLOUD_FOLDER_ID
pause

