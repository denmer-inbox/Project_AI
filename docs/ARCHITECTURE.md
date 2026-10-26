# Архитектура PC Agent

Документ описывает устройство проекта: модули, поток данных, контракты и точки
расширения. Все пути указаны относительно корня репозитория `Project_AI`.

---

## 1. Общая идея

PC Agent - это **цикл "наблюдение -> решение -> действие"** поверх function
calling любой поддерживаемой модели. Клиент не привязан к вендору: девять
провайдеров, провайдер определяется по префиксу ключа. Ключевые принципы:

1. **Модель не трогает систему напрямую.** Она только возвращает имя инструмента
   и аргументы; всё исполнение идёт через `ToolRegistry` и `Policy`.
2. **Модель работает в пикселях снимка**, а не в координатах рабочего стола.
   Пересчёт делает `Screenshot.to_absolute()`.
3. **Контракты заморожены.** `pcagent/interfaces.py` и `pcagent/tools/base.py`
   общие для всех модулей, поэтому их меняет только владелец контракта (Lead).
4. **Наблюдаемость.** Любое действие публикуется в `EventBus` (GUI/CLI) и
   пишется в JSONL-журнал.
5. **Безопасность по умолчанию.** Режим `confirm_mode: risky` подтверждает
   любые изменяющие действия.
6. **Провайдер - это деталь конфигурации.** Агентный цикл разбирает ответ любой
   модели одинаково; замена провайдера не меняет ни одного модуля, кроме ключа
   в `.env`.

---

## 2. Граф модулей

```text
                          +------------------------------+
                          | config.yaml  +  .env         |
                          +--------------+---------------+
                                         |
                            pcagent/config.py (AppConfig,
                            load_config, load_env, validate)
                                         |
        +-----------------+    +---------+----------+    +---------------------+
        | pcagent/cli.py  |    | pcagent/agent/     |    | pcagent/gui/        |
        | run/gui/models  |--->| loop.py            |<---| app.py (tkinter)    |
        | balance/doctor  |    | AgentSession       |    | providers.py        |
        | config          |    |                    |    | credentials.py      |
        +-----------------+    +----+----------+----+    +---------------------+
                                    |          |
                     +--------------+          +------------------+
                     |                                            |
          pcagent/gui/providers.py                     pcagent/tools/base.py
          detect_provider, resolve_model,             ToolRegistry, ToolContext,
          fetch_models, fetch_balance,                ToolResult, Tool, schema()
          check_tls, make_brain
                     |
        +------------+-------------------------+
        |                                      |
  pcagent/llm.py                     providers.HttpBrain
  GoogleBrain (SDK google-genai)     OpenAI-совместимый HTTP
        |                                      |
  Google Gemini API             Anthropic, OpenAI, DeepSeek, Groq,
                                Mistral, Together AI, OpenRouter,
                                AI Keys For You
                                               |
                                +--------------+--------------+
                                |              |              |
                       pcagent/capture.py  input_control.py  windows_apps.py
                       Screen, снимки,     мышь, клавиши,    окна, процессы
                       UI Automation       буфер (кириллица)
                                               |
                                      pcagent/system_ops.py
                                      run_command, run_powershell, run_script,
                                      open_path, start_uri, clipboard_*,
                                      get_system_info

        Сквозные сервисы:
          pcagent/safety.py         Policy, Decision, deny-list, Confirmer-ы
          pcagent/events.py         EventBus, Event, KillSwitch, AskBroker
          pcagent/logging_utils.py  JsonlLogger, NullLogger
          pcagent/stub_brain.py     StubBrain - оффлайн-мозг для тестов и демо
```

### 2.1 Слой провайдеров

`pcagent/gui/providers.py` - единственное место, которое знает про вендоров.
Остальной код работает с абстракцией "мозг": объект, у которого есть
`generate(contents, tools_declarations, system_instruction)`.

| Что делает модуль | Функции |
| --- | --- |
| Определить провайдера по префиксу ключа | `detect_provider()`, `candidate_providers()` |
| Описать провайдера | dataclass `Provider`: `id`, `title`, `base_url`, `default_model`, `key_prefixes`, `official`, `google_sdk`, `vision` |
| Список моделей | `fetch_models()` (SDK для Google, `/models` для остальных) |
| Подобрать рабочую модель | `resolve_model()`, `model_fits_provider()`, `probe_chat()`, `find_working_model()`, `pick_default_model()` |
| Остаток и множители | `fetch_balance()`, `fetch_multipliers()`, `Balance` |
| Проверить TLS | `check_tls()` |
| Собрать "мозг" под ключ | `make_brain()` -> `GoogleBrain` или `HttpBrain` |
| Предупредить о посреднике | `is_official()`, `privacy_notice()`, `PRIVACY_NOTICE` |
| Перевести ошибку провайдера | `friendly_error()` |

Девять провайдеров описаны кортежем `PROVIDERS`; порядок важен, потому что
префиксы проверяются по очереди (специфичные `sk-ant-`, `sk-cvc-`, `sk-or-v1-`
раньше общего `sk-`). Поле `official` отделяет официальные API от посредников:
посреднику клиент показывает предупреждение о передаче данных.

`HttpBrain` реализует тот же контракт, что `GoogleBrain`: он переводит историю
`types.Content` в сообщения `chat/completions`, отправляет объявления инструментов
в формате `tools` и собирает ответ в структуру, которую разбирают
`llm.extract_text()` / `llm.extract_calls()`. Поэтому агентный цикл не знает,
с каким провайдером он говорит.

### Ответственность модулей

| Модуль | Ответственность |
| --- | --- |
| `pcagent/interfaces.py` | замороженные типы-контракты: `Risk`, `MonitorInfo`, `Screenshot`, `ScreenService`, `Confirmer`, `RunResult`, `AgentControl` |
| `pcagent/config.py` | `AppConfig` (dataclass), загрузка YAML + `.env` + переменные окружения, валидация |
| `pcagent/events.py` | шина событий, стоп-кран, брокер подтверждений |
| `pcagent/safety.py` | `Policy`: решение "можно / нужно подтверждение / запрещено", deny-list |
| `pcagent/logging_utils.py` | JSONL-аудит и консольное логирование |
| `pcagent/llm.py` | `GoogleBrain`: обёртка над официальным SDK `google-genai` - клиент, конфигурация с инструментами, разбор ответа, работа с изображениями, fallback-модели |
| `pcagent/gui/providers.py` | слой провайдеров: определение по ключу, каталог моделей, подбор модели, баланс, TLS, `HttpBrain` для OpenAI-совместимых API, `make_brain()` |
| `pcagent/gui/credentials.py` | поиск ключа по всем источникам (окружение, `.env`, `%APPDATA%\PCAgent\.env`, реестр, config.yaml), его проверка и сохранение; без tkinter |
| `pcagent/agent/loop.py` | `AgentSession` - сам агентный цикл, история, шаги, лимиты |
| `pcagent/agent/prompts.py` | системный промпт, первое сообщение, декларация `finish_task` |
| `pcagent/capture.py` | `Screen`: мониторы, снимки, DPI, UI Automation; инструменты категории `capture` |
| `pcagent/input_control.py` | мышь и клавиатура (pyautogui), инструменты категории `input` |
| `pcagent/windows_apps.py` | окна (win32) и процессы (psutil), инструменты категории `windows` |
| `pcagent/system_ops.py` | команды ОС, буфер обмена, открытие путей и ссылок, системная информация |
| `pcagent/tools/base.py` | `Tool`, `ToolResult`, `ToolContext`, `ToolRegistry`, хелперы JSON Schema |
| `pcagent/cli.py` | подкоманды `run`, `gui`, `models`, `balance`, `doctor`, `config` |
| `pcagent/gui/` | окно tkinter: чат, таблица действий, превью, подтверждения, настройки, диалог ключа API и остатка токенов |
| `pcagent/stub_brain.py` | скриптованный "мозг" для оффлайн-тестов (`--stub`) |

---

## 3. Поток данных

### 3.1 Запуск задачи

```text
CLI/GUI
  -> load_config()            config.yaml + .env + флаги
  -> resolve_api_key()        PCAGENT_API_KEY -> GEMINI_API_KEY -> ... -> config.yaml
  -> detect_provider(key)     префикс ключа: AIza -> Google, sk-ant- -> Anthropic, ...
  -> resolve_model(...)       auto -> модель провайдера -> проверка ключом
  -> build_default_registry() импорт модулей инструментов, регистрация Tool
  -> Screen(config)           DPI-awareness + бэкенд mss
  -> make_brain(...)          GoogleBrain (SDK) или HttpBrain (HTTP)
  -> AgentSession(...)        политика, шина, журнал
  -> session.run_task(task)
```

Перед стартом, если провайдер оказался посредником, клиент печатает
предупреждение `privacy_notice()`: через посредника проходят задачи, снимки
экрана и ключ.

### 3.2 Один шаг агентного цикла

```text
1. Проверка стоп-крана (kill_switch / session.stop())
2. Event.step(n)
3. brain.generate(history, declarations, system_instruction)
       -> ответ модели: части текста + части functionCall
          (GoogleBrain - нативный ответ SDK, HttpBrain - переведённый
           из chat/completions; структура для цикла одна и та же)
4. extract_text(parts)   -> Event.thought(...)
5. extract_calls(parts)  -> список {name, args, id}
6. Для каждого вызова:
       finish_task?  -> RunResult(success, summary) и выход из цикла
       иначе:
         Event.action(name, args)
         ToolRegistry.execute(ctx, name, args)
             -> Policy.check(name, risk, args)
                   denied      -> ToolResult.fail("Отказано политикой", "policy_denied")
                   dry-run     -> ToolResult(ok, "[dry-run] ...")
                   подтверждено -> handler(ctx, args)
             -> ToolResult(ok, summary, data, images)
         Event.result(name, ok, summary, data)
         результат + изображения -> functionResponse в историю
7. prune_history_images(history, max_history_images)
8. Пауза action_delay, следующий шаг
```

### 3.3 Система координат

Модель всегда получает снимок и возвращает координаты **в пикселях изображения**.
Перевод выполняется по формуле:

```text
scale        = ширина_изображения / ширина_реальной_области
absolute_x   = origin_left + image_x / scale
absolute_y   = origin_top  + image_y / scale
```

Обратное преобразование - `Screenshot.to_image(abs_x, abs_y)`. Значения
по умолчанию ограничиваются границами области (`clamp=True`), чтобы клик не
улетел на другой монитор.

### 3.4 События

| Константа | Смысл | Кто публикует |
| --- | --- | --- |
| `KIND_STATUS` | текстовый статус | цикл, CLI |
| `KIND_STEP` | номер шага | `AgentSession` |
| `KIND_THOUGHT` | рассуждение модели | `AgentSession` |
| `KIND_ACTION` | вызов инструмента | `AgentSession` |
| `KIND_RESULT` | результат инструмента | `AgentSession` |
| `KIND_IMAGE` | снимок экрана | `AgentSession`, GUI |
| `KIND_ERROR` | ошибка | цикл |
| `KIND_DONE` | задача завершена (`RunResult.as_dict()`) | `AgentSession` |
| `KIND_ASK` | запрос подтверждения (`request_id`) | `AskBroker` |
| `KIND_ANSWER` | ответ на подтверждение | GUI/CLI |
| `KIND_LOG` | отладочное сообщение | любой модуль |

GUI забирает события из очереди через `EventBus.drain()` по таймеру tkinter,
CLI подписывается на шину и печатает сразу.

---

## 4. Контракты

### 4.1 pcagent/interfaces.py

| Тип | Поля / методы | Замечания |
| --- | --- | --- |
| `Risk` | `READ`, `WRITE`, `DESTRUCTIVE`; `order` | порядок сравнения рисков |
| `MonitorInfo` | `index`, `left`, `top`, `width`, `height`, `is_primary` | `right` / `bottom` - свойства |
| `Screenshot` | `image_bytes`, `mime_type`, `width`, `height`, `scale`, `monitor`, `origin_left/top`, `real_width/height`, `path`, `captured_at` | `to_absolute()`, `to_image()`, `as_dict()` |
| `image_to_absolute()` | `(x, y, shot, clamp)` | свободная функция-обёртка |
| `ScreenService` | `monitors()`, `capture()`, `size()`, `uia_tree()`, `active_window()`, `close()` | `Protocol`, проверяется `isinstance` |
| `Confirmer` | `ask(question, details, timeout) -> bool` | реализации: `ConsoleConfirmer`, `AutoConfirmer`, `DenyConfirmer`, `AskBroker`-обёртки |
| `RunResult` | `success`, `steps`, `final_text`, `error`, `transcript_path`, `actions` | `as_dict()` для события `KIND_DONE` |
| `AgentControl` | `is_running`, `run_task(task)`, `stop()` | публичный интерфейс сессии |

### 4.2 pcagent/tools/base.py

| Тип | Назначение |
| --- | --- |
| `schema()`, `prop_string/integer/number/boolean()` | сборка JSON Schema для FunctionDeclaration |
| `ToolResult` | `ok`, `summary`, `data`, `images`, `error`; `model_response()` отдаёт компактный ответ модели |
| `Tool` | `name`, `description`, `parameters`, `risk`, `handler`, `category`; `declaration()` |
| `ToolContext` | `config`, `screen`, `policy`, `logger`, `bus`, `dry_run`, `registry`; `emit()`, `log()` |
| `ToolRegistry` | `register`, `add` (декоратор), `get`, `all`, `names`, `categories`, `declarations`, `execute()` |
| `build_default_registry()` | собрать реестр из `TOOL_MODULES`, пропуская модули без зависимостей |

Порядок проверок в `ToolRegistry.execute()`:

1. инструмент существует (иначе `unknown_tool`);
2. `Policy.check()` (иначе `policy_denied`);
3. dry-run для не-`read` действий (действие не выполняется, но шаг считается успешным);
4. вызов `handler` в `try/except` - любое исключение превращается в `ToolResult.fail()`;
5. проверка типа результата и запись в журнал.

---

## 5. Как добавить инструмент

1. Создать (или взять существующий) модуль в `pcagent/` с функцией
   `register(registry: ToolRegistry) -> None`.
2. Внутри зарегистрировать инструмент:

```python
from pcagent.interfaces import Risk
from pcagent.tools.base import ToolContext, ToolRegistry, ToolResult, prop_integer, schema

def _tool_example(ctx: ToolContext, args: dict) -> ToolResult:
    """Пример инструмента."""
    value = int(args.get("value", 0))
    if value < 0:
        return ToolResult.fail("value должно быть >= 0", error="bad_argument")
    return ToolResult(ok=True, summary=f"получено {value}", data={"value": value})

def register(registry: ToolRegistry) -> None:
    """Зарегистрировать инструменты модуля."""
    registry.register(
        Tool(
            name="example",
            description="Короткое описание для модели: что делает и когда применять.",
            parameters=schema({"value": prop_integer("целое число")}, required=["value"]),
            risk=Risk.READ,
            handler=_tool_example,
            category="system",
        )
    )
```

3. Если модуль новый - добавить его имя в `TOOL_MODULES` в `pcagent/tools/__init__.py`
   (это файл контрактов, менять согласованно).
4. Правила: описание длиннее 10 символов, аргументы описаны, риск выставлен
   честно, никакой сети, исключения не пробрасывать наружу.

---

## 6. Точки расширения

| Что | Где | Как |
| --- | --- | --- |
| Новый провайдер | `pcagent/gui/providers.py` | добавить `Provider(...)` в `PROVIDERS` (префиксы ключа, `base_url`, модель по умолчанию); OpenAI-совместимым API больше ничего не нужно |
| Свой шлюз или прокси | `config.yaml` -> `extra` | `provider: openai` + `base_url: https://...`; ключ - в `.env` |
| Своя модель/бэкенд | `pcagent/llm.py` | реализовать объект с `generate(contents, tools_declarations, system_instruction)` и передать в `AgentSession(brain=...)` |
| Оффлайн-мозг | `pcagent/stub_brain.py` | сценарий из шагов, используется флагом `--stub` |
| Свой подтверждатель | `pcagent/safety.py` | объект с `ask()`; GUI использует `AskBroker` |
| Своя политика | `pcagent/safety.py` | расширить deny-patterns или заменить `Policy` |
| Другой источник экрана | `pcagent/interfaces.py` | реализовать `ScreenService` и передать в `ToolContext(screen=...)` |
| Другой GUI | `pcagent/events.py` | подписаться на `EventBus` и отвечать через `AskBroker.answer()` |

---

## 7. Потоки выполнения и потоки ОС

* Агентный цикл выполняется в **рабочем потоке** (GUI) или в главном потоке (CLI).
* GUI обновляет виджеты только в главном потоке: события забираются через
  `after()` и `EventBus.drain()`.
* Подтверждение блокирует рабочий поток до ответа пользователя
  (`AskBroker.ask()` ждёт `threading.Event`); по таймауту считается отказом.
* Стоп-кран - `threading.Event`, проверяется перед каждым шагом; активный
  инструмент не прерывается.

---

## 8. Тесты

| Файл | Что проверяет |
| --- | --- |
| `tests/conftest.py` | пути, отсутствие ключа API в окружении, базовые фикстуры |
| `tests/test_integration.py` | контракты, конфигурация, координаты, политика, реестр, события, валидность деклараций |
| `tests/test_universal_provider.py` | определение провайдера по префиксу, подбор модели, `HttpBrain`, формат запросов |
| `tests/test_privacy_notice.py` | предупреждение о посреднике: есть для шлюзов, нет для официальных API |
| `tests/test_balance.py` | остаток токенов, множители моделей, подсказка для Gemini |
| `tests/test_key_dialog.py` | поиск, проверка и сохранение ключа API |
| `tests/test_llm.py` | `GoogleBrain`, разбор ответов, обрезка истории изображений |
| `tests/test_cli.py` | подкоманды CLI, флаги, коды возврата |
| `tests/test_loop.py` | агентный цикл со `StubBrain`, лимиты шагов, стоп-кран |
| `tests/test_tool_routing.py` | отбор инструментов под задачу и сжатие описаний |
| `tests/test_shell_policy.py` | `allow_shell`, deny-list, проверка тела скриптов |
| `tests/test_capture.py`, `test_window_and_coords.py` | снимки, масштабирование, UIA-дерево, координаты окон |
| `tests/test_input_control.py`, `test_windows_apps.py`, `test_system_ops.py` | инструменты категорий input, windows, system |
| `tests/test_hotkey.py` | глобальный стоп-кран |
| `tests/test_speed.py`, `test_screen_budget_integration.py` | ожидание по факту, бюджет снимков |
| `tests/test_gui.py` | окно GUI без реального показа |
| `tests/test_smoke_live.py` | живые READ-проверки на этой машине |

Запуск: `.venv\Scripts\python.exe -m pytest -q`. Тесты не выполняют реальных
опасных действий: изменяющие инструменты проверяются в dry-run.