# AI_EXCHANGE dispatcher. PowerShell 5.1 compatible.
# Один цикл: синхронизация зеркала + подъём "спящего" адресата при новом письме.
[CmdletBinding()]
param(
  [string]$Root = '',
  [string]$Mirror = '\\NICK-SECOND\Users\Public\Documents\AI_EXCHANGE',
  [int]$SleepSeconds = 60,
  [int]$WakeCooldownMinutes = 10,
  [int]$StaleMinutes = 5,
  [string[]]$WakeOnly = @('ocm'),
  [switch]$Once,
  [switch]$NoWake
)
$ErrorActionPreference = 'Continue'
if (-not $Root) { $Root = $PSScriptRoot }
$Root = (Resolve-Path -LiteralPath $Root).Path
$log = Join-Path $Root 'logs\dispatcher.log'
$logDir = Split-Path $log -Parent
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

function Log([string]$msg) {
  $line = "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) $msg"
  Add-Content -LiteralPath $log -Value $line -Encoding UTF8
  if ($Once) { Write-Host $line }
  $fi = Get-Item -LiteralPath $log -ErrorAction SilentlyContinue
  if ($fi -and $fi.Length -gt 2MB) { Move-Item -LiteralPath $log -Destination ($log + '.1') -Force }
}

function Sync-Mirror {
  if (-not (Test-Path -LiteralPath $Mirror)) { return }
  foreach ($pair in @(@($Root, $Mirror), @($Mirror, $Root))) {
    $src = $pair[0]; $dst = $pair[1]
    & robocopy $src $dst /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
  }
  Log "sync ok <- $Mirror"
}

function Count-Unread([string]$who) {
  $dir = Join-Path $Root "inbox\$who"
  if (-not (Test-Path -LiteralPath $dir)) { return 0 }
  $n = 0
  foreach ($f in Get-ChildItem -LiteralPath $dir -Filter '*.md' -File -ErrorAction SilentlyContinue) {
    if (-not (Test-Path -LiteralPath (Join-Path $Root "archive\$($f.BaseName).ack"))) { $n++ }
  }
  return $n
}

function Heartbeat-Age([string]$who) {
  $hb = Join-Path $Root "state\$who.hb"
  if (-not (Test-Path -LiteralPath $hb)) { return 9999 }
  try { return [int]((Get-Date) - [datetime]::Parse((Get-Content -LiteralPath $hb -Raw).Trim())).TotalMinutes } catch { return 9999 }
}

function Wake([string]$who, [int]$unread) {
  if ($NoWake) { return }
  if ($WakeOnly -notcontains $who) { return }
  $lastFile = Join-Path $Root "state\wake_$who.last"
  if (Test-Path -LiteralPath $lastFile) {
    $age = 9999
    try { $age = [int]((Get-Date) - [datetime]::Parse((Get-Content -LiteralPath $lastFile -Raw).Trim())).TotalMinutes } catch {}
    if ($age -lt $WakeCooldownMinutes) { return }
  }
  $reason = "$(Get-Date -Format s): для $who $unread непрочитанных, heartbeat отсутствует/старый"
  Set-Content -LiteralPath (Join-Path $Root "state\WAKE_$who.txt") -Value $reason -Encoding UTF8
  Set-Content -LiteralPath $lastFile -Value ((Get-Date).ToString('o')) -Encoding UTF8
  # ocm = OpenCode Desktop (opencode:), dsh = DeepSeek Harness (dsh:)
  $proto = if ($who -eq 'ocm') { 'opencode:' } else { 'dsh:' }
  try {
    Start-Process -FilePath $proto -ErrorAction Stop
    Log "wake $who via $proto ($unread unread)"
  } catch {
    Log "wake $who FAILED ($($_.Exception.Message)) — нужен ручной запуск приложения"
  }
}

function Cycle {
  Sync-Mirror
  foreach ($who in 'ocm','dsh') {
    $unread = Count-Unread $who
    if ($unread -le 0) { continue }
    $age = Heartbeat-Age $who
    Log "inbox ${who}: $unread unread, heartbeat ${age}m"
    if ($age -ge $StaleMinutes) { Wake $who $unread }
  }
}

if ($Once) { Cycle; return }
Log 'dispatcher start'
while ($true) {
  try { Cycle } catch { Log "cycle error: $($_.Exception.Message)" }
  Start-Sleep -Seconds $SleepSeconds
}
