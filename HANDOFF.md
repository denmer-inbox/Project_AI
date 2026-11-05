# Передача контекста: Agent Manager / OpenCode Provider Manager

Дата: 06.11.2026. Репозиторий: `C:\Users\nickd\Downloads\Project_AI`
Ветка: `master`, коммит `f5957ee`, синхронизирован с `origin/master`, дерево чистое.

---

## 1. Что это за проект

Графический менеджер профилей-провайдеров для OpenCode (`opencode_provider_manager.py`,
Tkinter, тёмная HUD-тема, трей, AOS-оверлей с балансом).
Сборки: `dist/OpenCodeProviderManager.exe` (однофайловая, её запускает ярлык)
и `dist/OpenCodeProviderManager/OpenCodeProviderManager.exe` (onedir).

Запуск: `Запуск менеджера OpenCode.bat`

---

## 2. Текущая история коммитов

```
f5957ee fix: кнопка «ИМПОРТ В АГЕНТОВ…» в нижней панели
97586d6 feat: перенос профилей в ИИ-агентов (без изменений в логике баланса)
ecd3ca3 fix(aos): прямоугольное окно без бордюра...   ← исходная рабочая версия
db28b62 feat: индикатор ● как глиф, автозагрузка в трее...
```

Отдельная ветка `feature/agents-balance` (локально и на GitHub) содержит
**отклонённые эксперименты**: переименование в Agent Manager и правки баланса,
которые ломали приложение. В master они НЕ влиты. Ветку можно удалить.

---

## 3. Что сделано в этом сеансе

### 3.1 Возвращён перенос профилей в ИИ-агентов

Кнопка **«ИМПОРТ В АГЕНТОВ…»** в нижней панели (рядом с «ИМПОРТ ПРОФИЛЕЙ…»).

Окно: два списка галочек — агенты и профили, кнопки
«☑ ВСЕ / ☐ НИЧЕГО», «ТОЛЬКО ОТЧЁТ (ПРОВЕРКА)», «ИМПОРТ В АГЕНТОВ».
Выбор запоминается в `%LOCALAPPDATA%\OpenCodeProviderManager\agents.json`.

Цели переноса:

| Агент | Файл |
|---|---|
| OpenCode | `~/.config/opencode/opencode.json` |
| VS Code | расширение `local.opencode-lm` + `%APPDATA%\Code\User\settings.json` |
| Cline | `~/.cline/data/settings/providers.json` + `models.json` |
| Continue | `~/.continue/config.yaml` |
| Codex CLI | `~/.codex/config.toml` |
| Claude Code | `~/.claude/settings.json` |
| Aider | `~/.aider.conf.yml` |

Ключевая функция — `merge_profiles_into_config()`: дописывает выбранные профили,
**не трогая** остальных провайдеров, их модели, `mcp`, `agent`, `skills`, `$schema`.
Перед записью любого файла создаётся копия `<файл>.bak-<дата-время>`.

### 3.2 ВАЖНО: логика баланса и AOS не менялась

Проверено программно (сравнение AST с `ecd3ca3`):
- в файле только **добавления: +1276 строк, 0 удалений**;
- `AOSOverlay` — идентичен прежнему;
- `request_balance`, `_balance_targets`, `apply_profiles`, `build_provider`,
  `fetch_balance`, `parse_balance` — не изменены;
- в классе `App` добавлен только метод `open_agents_dialog`.

### 3.3 Найденные причины прошлых поломок (не повторять!)

1. **TTL-кэш баланса блокировал кнопку «ОБНОВИТЬ»** — `request_balance` без
   `force=True` молча выходил, если баланс моложе 60 с. Кнопка «не работала».
2. **Последовательная очередь** — медленный провайдер тормозил остальных
   (выбранный профиль ждал 5+ секунд вместо 0.2 с).
3. **Замена `providers` при переносе** (`apply_profiles` в переносе) — у
   пользователя пропали 42 модели (появился `"disabled": true`).
   Исправлено на слияние.
4. **Переименование меняло мутекс** — старая и новая версии работали
   одновременно и обе писали конфиг.
5. **Кнопка не вставлялась** — проверка «уже есть» находила текст подсказки
   внутри диалога. Теперь проверка по `command=self.open_agents_dialog`.

---

## 4. Проверено и работает

- 50 тестов проходят (`tests/test_provider_manager_agents.py`,
  `_export.py`, `_paste.py`).
- Кнопка «ОБНОВИТЬ» — 1 запрос на нажатие (как в исходной версии).
- Реальный перенос во все 7 агентов в изолированном каталоге: все OK,
  конфиг цел, повторный прогон ничего не ломает.
- В запущенном exe: кнопка есть, окно открывается, «ТОЛЬКО ОТЧЁТ» выдаёт
  отчёт (7 агентов, 4 профиля).
- Отчёт пользователя (подтверждён вживую):

```
Проверка (файлы не изменяются):
  • opencode → C:\Users\nickd\.config\opencode\opencode.json
  • VS Code (чат-модели) → расширение local.opencode-lm + ...\Code\User\settings.json
  • cline → C:\Users\nickd\.cline\data\settings\providers.json
  • continue → C:\Users\nickd\.continue\config.yaml
  • codex → C:\Users\nickd\.codex\config.toml
  • claude → C:\Users\nickd\.claude\settings.json
  • aider → C:\Users\nickd\.aider.conf.yml
Профилей: 4
```

Все пути реальные. Единственный отсутствующий файл — `~/.claude/settings.json`
(создастся при переносе в Claude Code).

---

## 5. Состояние рабочего конфига OpenCode

`C:\Users\nickd\.config\opencode\opencode.json`
SHA-256 (первые 16): `E473D1F95E032EE0`, 16299 байт.

- провайдеры: `deepseek-4-flash`, `aikeysforyou.com`, `deepseek-v4-flash`, `DEEPSEEK_FLASH`
- моделей: 50, скрытых (`disabled`): **0**
- `model`: `DEEPSEEK_FLASH/deepseek-v4.1-flash-1017`
- `mcp.rea`, `agent.plan`, `skills` — на месте

Эталонные снимки: `~/.config/opencode/backups/opencode.json.20261106-001620-567.bak`
и `opencode.json.before-model-restore-20261106-003931`.

---

## 6. Что осталось / обратить внимание

1. **Реальный перенос пользователем ещё не выполнялся** — только сухой прогон.
   Следующий шаг: отметить агентов и профили → «ИМПОРТ В АГЕНТОВ» → проверить,
   что цифры/файлы появились.
2. **Claude Code**: файла `~/.claude/settings.json` пока нет — проверить, что
   создаётся корректно (env: `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`,
   `ANTHROPIC_MODEL`).
3. **VS Code**: расширение `local.opencode-lm` уже установлено; проверить, что
   `opencodeLM.configPath` в `settings.json` остаётся, а комментарии JSONC не
   теряются.
4. PowerShell на этой машине **не поддерживает `if` внутри `-f`/подстановок**
   и heredoc `<<'EOF'` — писать скрипты в `.py`-файлы, а не однострочниками.
5. `.gitignore` игнорирует `*.spec`, поэтому `OpenCodeProviderManager.spec` и
   `OCM-onefile.spec` в git НЕ лежат — при клоне их надо воссоздавать.

---

## 7. Правила, чтобы не сломать рабочую версию

- **Не менять** `request_balance`, `_balance_targets`, `AOSOverlay`,
  `apply_profiles` — это и есть «рабочая логика».
- Перенос профилей в OpenCode — только через `merge_profiles_into_config`.
- Тесты и проверки запускать в изолированном окружении:
  подменять `LOCALAPPDATA`, `APPDATA` и копировать конфиг во временный каталог.
  **Никогда** не писать в реальный `~/.config/opencode/opencode.json`.
- Не кликать мышью по живому окну во время проверок: один такой клик уже
  изменил `model` в рабочем конфиге (восстановлено).
- После правок: пересчитать обфускацию (`agent_manager`/`opencode_provider_manager.obfuscated.py`),
  пересобрать обе сборки, запустить exe, сверить хеш конфига до/после.
