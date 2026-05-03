# Скрипт для запуска всех вариантов голосового помощника
# Использование: .\start_all.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Запуск всех вариантов голосового помощника" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Переходим в директорию скрипта
Set-Location $PSScriptRoot

# Запускаем Python скрипт
python start_all.py

Write-Host ""
Write-Host "Нажмите любую клавишу для выхода..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

