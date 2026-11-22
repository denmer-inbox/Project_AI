# BOOTSTRAP обмена на второй машине. Запускать из папки AI_EXCHANGE (локальной или сетевой).
# PowerShell 5.1 compatible. Ничего не удаляет и не перезаписывает чужое.
[CmdletBinding()]
param(
  [string]$Mirror = '',
  [switch]$NoTask,
  [switch]$NoMail,
  [switch]$DryRun,
  [switch]$Quiet
)
$ErrorActionPreference = 'Continue'
function Say([string]$m) { if (-not $Quiet) { Write-Host $m } }

$src = $PSScriptRoot
if (-not $src) { $src = (Get-Location).Path }
Say "источник: $src"

# ---------- 1. выбрать локальный корень ----------
if ($src.StartsWith('\\')) {
  $local = Join-Path $env:PUBLIC 'Documents\AI_EXCHANGE'
  if ($DryRun) { Say "[dry] скопировал бы $src -> $local" }
  else {
    New-Item -ItemType Directory -Force -Path $local | Out-Null
    & robocopy $src $local /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
  }
  $root = $local
  if (-not $Mirror) { $Mirror = $src }
} else {
  $root = $src
  if (-not $Mirror) {
    if ($env:COMPUTERNAME -match 'SECOND') { $Mirror = '\\NICK\Users\Public\Documents\AI_EXCHANGE' }
    else { $Mirror = '\\NICK-SECOND\Users\Public\Documents\AI_EXCHANGE' }
  }
}
Say "корень:  $root"
Say "зеркало: $Mirror"
$wake = if ($env:COMPUTERNAME -match 'SECOND') { 'dsh' } else { 'ocm' }

# ---------- 2. структура ----------
$dirs = 'inbox\ocm','inbox\dsh','archive','shared','shared\incoming','shared\outgoing','tasks','locks','state','logs'
foreach ($d in $dirs) {
  $p = Join-Path $root $d
  if (-not (Test-Path -LiteralPath $p)) {
    if ($DryRun) { Say "[dry] mkdir $p" } else { New-Item -ItemType Directory -Force -Path $p | Out-Null }
  }
}

# ---------- 3. задача планировщика ----------
$taskName = 'AI_EXCHANGE_DISPATCHER'
$taskResult = 'пропущено (-NoTask)'
if (-not $NoTask -and -not $DryRun) {
  $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  # на этой машине живёт только один агент: свой и будим, чужого не поднимаем
  Say "будим:   $wake (остальных будит их собственный диспетчер)"
  $arg = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\dispatcher.ps1`" -Once -Mirror `"$Mirror`" -WakeOnly $wake"
  try {
    $action = New-ScheduledTaskAction -Execute $ps -Argument $arg -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
      -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
      -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
      -Principal $principal -Description 'AI_EXCHANGE: обмен сообщениями между агентами' | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 4
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    $taskResult = "код $($info.LastTaskResult), следующий запуск $($info.NextRunTime)"
  } catch {
    $startup = [Environment]::GetFolderPath('Startup')
    $lnk = Join-Path $startup 'AI_EXCHANGE_dispatcher.lnk'
    try {
      $ws = New-Object -ComObject WScript.Shell
      $s = $ws.CreateShortcut($lnk)
      $s.TargetPath = $ps; $s.Arguments = $arg; $s.WorkingDirectory = $root
      $s.WindowStyle = 7; $s.Description = 'AI_EXCHANGE dispatcher'; $s.Save()
      $taskResult = "планировщик недоступен, поставлен автозапуск: $lnk"
    } catch {
      $taskResult = "ОШИБКА: ни задача, ни автозапуск не созданы ($($_.Exception.Message))"
    }
  }
}
Say "задача:  $taskResult"

# ---------- 4. правило в инструкции агента ----------
$rule = @'

---

# AI_EXCHANGE — почта между агентами (обязательно)

Общая папка: `C:\Users\Public\Documents\AI_EXCHANGE`. Протокол — `PROTOCOL.md` там же.

В начале каждого хода:

    cd C:\Users\Public\Documents\AI_EXCHANGE
    .\ai.ps1 list -For <мой id>

Есть непрочитанные -> `.\ai.ps1 read -From <id> -Id <msgid>`, выполнить просьбу,
затем `.\ai.ps1 ack -From <id> -Id <msgid>`. Ответ:

    .\ai.ps1 send -From <id> -To <другой id> -Subject "..." -Body "..." -Thread <ветка> -ReplyTo <msgid>

Идентификаторы: `ocm` = OpenCode, `dsh` = DeepSeek Harness.
Лимиты: не более 5 сообщений за ход, один ответ на письмо, нет нового знания — только ack.
Файл `state\WAKE_<id>.txt` означает «проверь почту»; после обработки удалить.
Артефакты — в `shared\`, задачи — в `tasks\`, чужие файлы не удалять.
'@

$targets = @("$env:USERPROFILE\.dsh\AGENTS.md", "$env:USERPROFILE\.config\opencode\AGENTS.md")
$patched = @()
foreach ($t in $targets) {
  $dir = Split-Path $t -Parent
  if (-not (Test-Path -LiteralPath $dir)) { continue }
  if (Test-Path -LiteralPath $t) {
    $c = Get-Content -LiteralPath $t -Raw -Encoding UTF8
    if ($c -match 'AI_EXCHANGE') { $patched += "$t (уже было)"; continue }
    if ($DryRun) { $patched += "[dry] $t" } else {
      Add-Content -LiteralPath $t -Value $rule -Encoding UTF8
      $patched += "$t (дописано)"
    }
  } else {
    if ($DryRun) { $patched += "[dry] $t (создать)" } else {
      Set-Content -LiteralPath $t -Value $rule -Encoding UTF8
      $patched += "$t (создан)"
    }
  }
}
if ($patched.Count -eq 0) { Say 'инструкции: подходящих файлов не найдено — добавь правило вручную (текст в AGENT_RULES.md)' }
else { Say ('инструкции: ' + ($patched -join '; ')) }

# ---------- 5. heartbeat и приветствие ----------
$me = if ($env:COMPUTERNAME -match 'SECOND') { 'dsh' } else { 'ocm' }
$peer = if ($me -eq 'dsh') { 'ocm' } else { 'dsh' }
$appName = if ($me -eq 'dsh') { 'DeepSeek Harness' } else { 'OpenCode Desktop' }
if (-not $DryRun) {
  Set-Content -LiteralPath (Join-Path $root "state\$me.hb") -Value ((Get-Date).ToString('o')) -Encoding UTF8
  $unread = 0
  $inbox = Join-Path $root "inbox\$me"
  if (Test-Path -LiteralPath $inbox) {
    foreach ($f in Get-ChildItem -LiteralPath $inbox -Filter '*.md' -File -ErrorAction SilentlyContinue) {
      if (-not (Test-Path -LiteralPath (Join-Path $root "archive\$($f.BaseName).ack"))) { $unread++ }
    }
  }
  if ($NoMail) {
    Say "приветствие не отправлено (-NoMail), непрочитанных у ${me}: $unread"
  } else {
    $body = @(
      "BOOTSTRAP OK"
      "Агент: $me ($appName)"
      "ПК: $env:COMPUTERNAME, пользователь $env:USERNAME"
      "Корень обмена: $root"
      "Зеркало: $Mirror"
      "Задача планировщика: $taskResult"
      "Будим только своего агента: $wake"
      "Инструкции: " + ($patched -join '; ')
      "Непрочитанных писем у ${me}: $unread"
      ""
      "Дальше проверяю почту сам в начале каждого хода."
    ) -join "`r`n"
    $tmp = Join-Path $env:TEMP "${me}_bootstrap_msg.txt"
    Set-Content -LiteralPath $tmp -Value $body -Encoding UTF8
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'ai.ps1') send `
        -From $me -To $peer -Subject "BOOTSTRAP OK: копия обмена запущена ($appName)" -BodyFile $tmp -Thread boot -Force | Out-Null
    Say "приветствие $peer отправлено"
  }
}

Say 'ГОТОВО'
