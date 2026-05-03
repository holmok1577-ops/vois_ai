# Скрипт установки зависимостей для голосового помощника
Write-Host "Установка зависимостей для голосового помощника..." -ForegroundColor Green
Write-Host ""

# Переходим в директорию скрипта
Set-Location $PSScriptRoot

# Устанавливаем зависимости
pip install -r requirements.txt

Write-Host ""
Write-Host "Установка завершена!" -ForegroundColor Green
Write-Host "Не забудьте создать файл .env и указать в нем YANDEX_CLOUD_API_KEY и YANDEX_CLOUD_FOLDER_ID" -ForegroundColor Yellow

