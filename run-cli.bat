@echo off
rem ===========================================================================
rem  PC Agent - запуск из командной строки (примеры)
rem  Без аргументов выполняет демонстрационную задачу.
rem  С аргументами передаёт их в python -m pcagent, например:
rem      run-cli.bat run "открой Блокнот и напиши Привет"
rem      run-cli.bat gui
rem      run-cli.bat run "задача" --dry-run --yes
rem ===========================================================================
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [setup] Виртуальное окружение .venv не найдено - создаю...
    where py >nul 2>nul
    if errorlevel 1 (
        python -m venv "%~dp0.venv"
    ) else (
        py -3.14 -m venv "%~dp0.venv"
    )
    if errorlevel 1 (
        echo [ошибка] Не удалось создать .venv. Нужен Python 3.14 в PATH.
        pause
        exit /b 1
    )
    "%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ошибка] Не удалось установить зависимости.
        pause
        exit /b 1
    )
)

if not exist "%~dp0.env" (
    echo [внимание] Файл .env не найден - ключ API не задан, нужна переменная PCAGENT_API_KEY.
    echo.
)

if "%~1"=="" (
    echo [run] Демонстрационная задача: открыть Блокнот и напечатать текст.
    "%VENV_PY%" -m pcagent run "Открой Блокнот и напиши в нём: Привет от PC Agent!"
) else (
    "%VENV_PY%" -m pcagent %*
)
set "EXITCODE=%ERRORLEVEL%"
endlocal & exit /b %EXITCODE%
