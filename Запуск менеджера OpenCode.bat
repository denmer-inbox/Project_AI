@echo off
cd /d "%~dp0"

rem The folder build is preferred: PyInstaller onefile has to unpack itself into
rem TEMP, and on some machines that fails with "Could not create temporary
rem directory!". The onedir build loads straight from its own folder.
if exist "%~dp0dist\OpenCodeProviderManager\OpenCodeProviderManager.exe" (
  start "" "%~dp0dist\OpenCodeProviderManager\OpenCodeProviderManager.exe"
  exit /b 0
)

rem Fallback for an older single-file build, if one is present.
if exist "%~dp0dist\OpenCodeProviderManager.exe" (
  start "" "%~dp0dist\OpenCodeProviderManager.exe"
  exit /b 0
)

rem Last resort: run the source with pythonw from PATH.
start "" pythonw "%~dp0opencode_provider_manager.py"
