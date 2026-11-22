
---

# AI_EXCHANGE — почта между агентами (обязательно)

Общая папка: `C:\Users\Public\Documents\AI_EXCHANGE` (сетевое зеркало:
`\\NICK-SECOND\Users\Public\Documents\AI_EXCHANGE`). Протокол — `PROTOCOL.md` там же.

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
