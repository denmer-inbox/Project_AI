# Передача контекста: OpenCode Provider Manager

Дата: 06.11.2026. Репозиторий: `C:\Users\nickd\Downloads\Project_AI`
Ветка: `master`. База — коммит `9c32255`; поверх него не закоммичены
доработки из раздела 3.4 (DeepSeek Harness + предпросмотр отчёта).

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
| DeepSeek Harness | `~/.dsh/profiles/desktop/cordis.patch.yml` + `~/.dsh/.credentials.yaml` |

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

### 3.4 Добавлено в этом сеансе

**DeepSeek Harness (`~/.dsh`) как восьмой агент.**

- `dsh_profile_dir()`, `dsh_patch_path()`, `dsh_credentials_path()`.
- `_transfer_dsh()`: в `cordis.patch.yml` точечно заменяется/добавляется
  элемент списка с `id: llm-pi-ai` (имя `@deepseek-ai/dsh-llm-pi-ai`), внутри —
  `config.providers.<id>`. Остальные патч-записи и существующие провайдеры
  сохраняются. Ключи дописываются в `.credentials.yaml` →
  `refs.DEEPSEEK_<ID>_API_KEY`, прочие refs не трогаются.
- `_require_yaml_any()` / `_dump_yaml_any()` — корень `cordis.patch.yml` это
  YAML-**список**, старый `_require_yaml` умел только словари.
- `AGENT_IDS` и `agent_catalog()` дополнены `dsh`.

**Предпросмотр отчёта — `transfer_plan()`.**

Сухой прогон, ноль записей. Для каждого агента проверяет то, что реально может
сломаться: дельта моделей OpenCode (`провайдеров N → M`, `моделей X → Y`,
предупреждение если моделей станет меньше), разбираемость `settings.json` /
`providers.json`, установлено ли расширение VS Code и есть ли `.vsix`,
корректность YAML Continue/Aider, состояние `cordis.patch.yml`. Кнопка
«ТОЛЬКО ОТЧЁТ (ПРОВЕРКА)» печатает метки `OK` / `ВНИМАНИЕ` и итог
«требуют внимания: N из 8».

**Проверки этого сеанса:**

- 61 тест проходит (36 в `_agents.py`, включая 10 новых на dsh и предпросмотр).
- Перенос в dsh на **копии** реального `cordis.patch.yml`: 15 блоков → 15,
  провайдеры `deepseek-4-flash` / `-funpay-csharponame` / `-v4-flash` целы,
  ключей 4 → 5, оригинал не изменён.
- Предпросмотр на реальном `opencode.json`: 4 профиля, 50 моделей,
  0 из 8 требуют внимания; файл после прогона байт-в-байт тот же.
- Пересобраны оба exe, onefile запущен — окно «OpenCode — менеджер
  провайдеров» и трей на месте; хеши `opencode.json`, `cordis.patch.yml`,
  `.credentials.yaml` до/после совпали.

---

## 4. Проверено и работает

- 61 тест проходит (`tests/test_provider_manager_agents.py`,
  `_export.py`, `_paste.py`).
- Кнопка «ОБНОВИТЬ» — 1 запрос на нажатие (как в исходной версии).
- Реальный перенос во все 8 агентов в изолированном каталоге: все OK,
  конфиг цел, повторный прогон ничего не ломает.
- В запущенном exe: кнопка есть, окно открывается, «ТОЛЬКО ОТЧЁТ» выдаёт
  отчёт (8 агентов, 4 профиля).
- Отчёт живого предпросмотра на реальном конфиге:

```
OK  OpenCode (этот конфиг)          провайдеров 4 → 4; моделей 50 → 50
OK  VS Code (чат-модели)            расширение уже установлено; пропишет путь к конфигу OpenCode
OK  Cline (VS Code, ~/.cline)       провайдеров сейчас: 6
OK  Continue (.continue/config.yaml) YAML разбирается
OK  Codex CLI (~/.codex/config.toml) блоки [model_providers.*] будут дописаны
OK  Claude Code (~/.claude/settings.json) settings.json будет создан
OK  Aider (~/.aider.conf.yml)        YAML разбирается
OK  DeepSeek Harness (~/.dsh)        патч-записей: 15

профилей: 4, моделей: 50
Требуют внимания: 0 из 8
```

Единственный отсутствующий файл — `~/.claude/settings.json`
(создастся при переносе в Claude Code).

**Чтение при загрузке:** `profiles_from_config` кладёт в `model_capabilities` то,
что реально записано (`capabilities.input` → vision/audio/video, `output` → web,
`tools`, `reasoning.supported`, `temperature`). Если галочки в конфиге не было —
она показывается как выключена. Галочка ВЛОЖЕНИЯ не хранится отдельно: она
включена, когда у модели во входе есть `image`/`audio`/`video`.

**Галочка ВЛОЖЕНИЯ и схема OpenCode (исправлено 09.11).** Ключа `attachment`
у модели в официальной схеме `https://opencode.ai/config.json` нет
(`Config.ModelEncoded` → `additionalProperties: false`), поэтому запись
`"attachment": true` делала конфиг невалидным. Теперь менеджер этот ключ
не пишет (а старый вычищает при применении), а галочка ВЛОЖЕНИЯ дописывает
типы входа `image`/`audio`/`video` к уже выбранным — иначе файл модели
отдать нельзя. Снятие галочки типы входа не трогает.

**Сброс ссылок на модели.** Раньше `apply_profiles` и
`merge_profiles_into_config` пересобирали все модели выбранных провайдеров из
`models: [id]`, и у моделей, которых не было в списке «доступные», пропадали
`name`, `limit`, `cost`, `capabilities` (у пользователя от этого терялись
50 моделей). Теперь список моделей профиля — это **все известные** модели,
скрытые помечаются `disabled: true`, а описание модели сохраняется.

**Ключи в opencode.json.** `settings.apiKey` читают только openai-совместимые
пакеты. Для остальных менеджер пишет `providers.<id>.env: ["OPENCODE_<ID>_API_KEY"]`
и `settings.apiKey: "{env:OPENCODE_<ID>_API_KEY}"` — иначе OpenCode отвечает
«API key is required». Значение кладётся в окружение процесса менеджера.

**Миграция старых конфигов.** Версия, которая выбирала пакет
`@ai-sdk/openai` (ключ из `settings.apiKey` не читается), оставила в конфигах
провайдеров с ключом `sk-cvc-*`. Кнопка «ПРИМЕНИТЬ К КОНФИГУ» теперь сама
переводит такой провайдер на `@opencode/ai/providers/openai-compatible`,
переводит ключ в `{env:…}` и сообщает об этом. `PACKAGES[0]` — актуальный
пакет `@opencode/ai/providers/openai-compatible`.

**Проверка:** 78 тестов менеджера проходят (в т.ч. 17 в
`tests/test_provider_manager_capabilities.py`); изолированный прогон
«галочка → JSON» (`check_capabilities.py` во временном каталоге) — 72 проверки,
0 провалов, все 13 собранных конфигов валидны по официальной схеме OpenCode;
диалог профиля проверен живым Tk-прогоном (снятие vision, включение
audio/reasoning, перечитывание); живой `opencode.json` не менялся
(`E473D1F95E032EE0`).

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

**Резервная копия для репозитория:** `dist/opencode-config-20261109.zip` —
этот же `opencode.json` (4 провайдера, 50 моделей), ZIP с шифрованием AES-256,
пароль `12321` (он же в названии коммита). Проверено: архив открывается только
с паролем, после распаковки SHA-256 совпадает (`E473D1F95E032EE0`).
В архиве лежат токены доступа OpenAI-совместимых провайдеров — файл в
публичном репозитории доступен всем, кто знает пароль; при утечке токены
нужно перевыпустить.

**Правило сборки (с 09.11.2026):** готовые exe всегда коммитятся и пушятся —
`dist/OpenCodeProviderManager.exe` (onefile) и
`dist/OpenCodeProviderManager/OpenCodeProviderManager.exe` (onedir), плюс
`dist/OpenCodeProviderManager/_internal/base_library.zip` (он меняется при
каждой пересборке). В `.gitignore` для этого уже есть `!dist/…` исключения,
но `dist/*` остаётся игнорируемым, поэтому добавлять нужно явно:
`git add -f dist/OpenCodeProviderManager.exe dist/OpenCodeProviderManager/OpenCodeProviderManager.exe`.
Порядок: правки → тесты → `PyInstaller OCM-onefile.spec` →
`PyInstaller OpenCodeProviderManager.spec` → коммит кода + exe → `git push`.

---

## 6. Что осталось / обратить внимание

1. **Реальный перенос пользователем ещё не выполнялся** — только сухой прогон.
   Следующий шаг: отметить агентов и профили → «ИМПОРТ В АГЕНТОВ» → проверить,
   что цифры/файлы появились. Для dsh это запишет в живой `~/.dsh`; бэкапы
   `<файл>.bak-<дата>` создаются автоматически, откат — копированием обратно.
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
6. **Python на машине три, и `python` из PATH — не тот**: `python` →
   3.15 без PyYAML (сборка конфигов падает), рабочий — 
   `C:\Users\nickd\AppData\Local\Python\pythoncore-3.14-64\python.exe`
   (3.14.5 + PyYAML 6.0.3 + tkinter). Тесты и PyInstaller запускать им.
7. **Подмена `APPDATA` ломает PyYAML** (пропадает user-site) — тесты на
   бэкапы начинают падать с «нужен PyYAML». Это корректная защита от затирания,
   не баг: подменяйте только `LOCALAPPDATA`, а `APPDATA` не трогайте.

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
- После правок: пересобрать обе сборки, запустить exe, сверить хеши
  `~/.config/opencode/opencode.json`, `~/.dsh/profiles/desktop/cordis.patch.yml`
  и `~/.dsh/.credentials.yaml` до/после — должны совпасть.

## 8. Обфускация — ОТМЕНЕНА

Собираем из `opencode_provider_manager.py` напрямую, обфускатор не используется.
Оба спека (`OpenCodeProviderManager.spec`, `OCM-onefile.spec`) указывают на
исходник:

```
a = Analysis(['opencode_provider_manager.py'], ...)
```

Файл `opencode_provider_manager.obfuscated.py` остаётся в репозитории как
исторический артефакт, но в сборке не участвует — не редактировать его и не
пересобирать.

Почему отказались: старый обфускатор переименовывал методы классов, из-за чего
ломались вызовы вида `app.run()` (`'_6t' object has no attribute 'run'`).
Чтобы не повторять, обфускация убрана из процесса сборки полностью.

Команды сборки:

```
C:\Users\nickd\AppData\Local\Python\pythoncore-3.14-64\python.exe -m PyInstaller OCM-onefile.spec --noconfirm --distpath dist --workpath build\onefile
C:\Users\nickd\AppData\Local\Python\pythoncore-3.14-64\python.exe -m PyInstaller OpenCodeProviderManager.spec --noconfirm --distpath dist --workpath build\onedir
```

Сначала onefile (его запускает ярлык), потом onedir.
