@echo off
cd /d "%~dp0"

rem Однофайловая сборка: всё внутри exe, можно просто копировать файл.
if exist "%~dp0dist\OpenCodeProviderManager.exe" (
  start "" "%~dp0dist\OpenCodeProviderManager.exe"
  exit /b 0
)

rem Запасной вариант: папочная сборка (быстрее стартует, но это папка, не файл).
if exist "%~dp0dist\OpenCodeProviderManager\OpenCodeProviderManager.exe" (
  start "" "%~dp0dist\OpenCodeProviderManager\OpenCodeProviderManager.exe"
  exit /b 0
)

rem Последний вариант: запуск исходника через pythonw из PATH.
start "" pythonw "%~dp0opencode_provider_manager.py"
