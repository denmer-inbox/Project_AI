# ===========================================================================
#  PC Agent - запуск графического интерфейса (PowerShell)
#  Если .venv нет - скрипт создаст его и поставит зависимости.
#
#  Обычный запуск идёт через pythonw.exe: окно терминала не появляется,
#  вывод и ошибки пишутся в logs\gui.log.
#  С аргументами (например .\run.ps1 --debug-console) консоль остаётся.
#
#  Если PowerShell не разрешает запуск скриптов:
#      powershell -ExecutionPolicy Bypass -File .\run.ps1
# ===========================================================================
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
# Кодировка: без этого русский текст в консоли Windows превращается в кракозябры.
try { chcp 65001 | Out-Null } catch { }
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = "utf-8"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $root ".venv\Scripts\pythonw.exe"

function Install-Environment {
    Write-Host "[setup] Виртуальное окружение .venv не найдено - создаю..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.14 -m venv (Join-Path $root ".venv")
    } else {
        & python -m venv (Join-Path $root ".venv")
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw "Не удалось создать .venv. Нужен Python 3.14 в PATH."
    }
    Write-Host "[setup] Устанавливаю зависимости из requirements.txt..."
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $root "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось установить зависимости. Проверьте интернет и права."
    }
}

if (-not (Test-Path $venvPython)) {
    Install-Environment
}

if (-not (Test-Path (Join-Path $root ".env"))) {
    Write-Host "[внимание] Файл .env не найден. Скопируйте .env.example в .env и впишите ключ API любого провайдера (PCAGENT_API_KEY)." -ForegroundColor Yellow
}

# Без аргументов - обычный запуск без окна консоли.
if (-not $Rest -or $Rest.Count -eq 0) {
    $launcher = $venvPythonw
    if (-not (Test-Path $launcher)) { $launcher = $venvPython }
    Write-Host "[run] Запускаю GUI PC Agent без окна консоли..."
    Write-Host "       Вывод и ошибки: logs\gui.log"
    Start-Process -FilePath $launcher -ArgumentList "-m", "pcagent", "gui" -WorkingDirectory $root | Out-Null
    exit 0
}

Write-Host "[run] Запускаю GUI PC Agent с выводом в консоль..."
& $venvPython -m pcagent gui @Rest
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host "[ошибка] Процесс завершился с кодом $code." -ForegroundColor Red
}
exit $code
