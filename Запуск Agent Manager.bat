@echo off
cd /d "%~dp0"

rem Однофайловая сборка: если есть exe, берём сразу проверенный файл.
if exist "%~dp0dist\AgentManager.exe" (
  start "" "%~dp0dist\AgentManager.exe"
  exit /b 0
)

rem Основная сборка в папку (работает даже там, где onefile не может
rem распаковаться в TEMP).
if exist "%~dp0dist\AgentManager\AgentManager.exe" (
  start "" "%~dp0dist\AgentManager\AgentManager.exe"
  exit /b 0
)

rem Последний вариант: исходник через pythonw из PATH.
start "" pythonw "%~dp0agent_manager.py"
