@echo off
rem ===========================================================================
rem  PC Agent - запуск графического интерфейса
rem  Если .venv нет - скрипт создаст его и поставит зависимости.
rem
rem  Обычный запуск идёт через pythonw.exe: окно терминала не появляется,
rem  вывод и ошибки пишутся в logs\gui.log.
rem  С аргументами (например run.bat --debug-console) консоль остаётся -
rem  это режим отладки.
rem ===========================================================================
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
rem pythonw.exe запускает приложение без чёрного окна консоли.
rem Если его нет (нестандартная сборка Python) - работаем через python.exe.
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%VENV_PYW%" set "VENV_PYW=%VENV_PY%"

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
    echo [setup] Устанавливаю зависимости из requirements.txt...
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ошибка] Не удалось установить зависимости. Проверьте интернет и права.
        pause
        exit /b 1
    )
    if not exist "%VENV_PYW%" set "VENV_PYW=%VENV_PY%"
)

if not exist "%~dp0.env" (
    echo [внимание] Файл .env не найден.
    echo            Скопируйте .env.example в .env и впишите ключ API любого
    echo            провайдера в переменную PCAGENT_API_KEY - провайдер определится сам.
    echo            Без ключа интерфейс запустится, но задачи выполняться не будут.
    echo.
)

rem Аргументы означают отладочный запуск: консоль остаётся, чтобы видеть вывод.
if not "%~1"=="" goto console_mode

echo [run] Запускаю GUI PC Agent без окна консоли...
echo        Вывод и ошибки: logs\gui.log
start "PC Agent" "%VENV_PYW%" -m pcagent gui
endlocal & exit /b 0

:console_mode
echo [run] Запускаю GUI PC Agent с выводом в консоль...
"%VENV_PY%" -m pcagent gui %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo [ошибка] Процесс завершился с кодом %EXITCODE%.
    pause
)
endlocal & exit /b %EXITCODE%
