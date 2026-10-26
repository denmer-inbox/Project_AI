@echo off
cd /d "%~dp0"
if exist "%~dp0dist\OpenCodeProviderManager.exe" (
  start "" "%~dp0dist\OpenCodeProviderManager.exe"
) else (
  start "" pythonw "%~dp0opencode_provider_manager.py"
)
