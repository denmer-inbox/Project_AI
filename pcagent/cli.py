"""Командная строка PC Agent: run / gui / models / doctor / config."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from typing import Any, Sequence

from pcagent import llm
from pcagent.agent import AgentSession
from pcagent.config import CONFIRM_MODES, AppConfig, load_config, load_env
from pcagent.events import (
    KIND_ACTION,
    KIND_ASK,
    KIND_DONE,
    KIND_ERROR,
    KIND_IMAGE,
    KIND_LOG,
    KIND_RESULT,
    KIND_STATUS,
    KIND_STEP,
    KIND_THOUGHT,
    AskBroker,
    EventBus,
    kill_switch,
)
from pcagent.logging_utils import JsonlLogger, NullLogger, setup_console_logging
from pcagent.safety import Policy
from pcagent.tools.base import build_default_registry

PROG = "pcagent"

# ---------------------------------------------------------------------------
# Вывод событий в терминал
# ---------------------------------------------------------------------------

def _safe_print(text: str = "") -> None:
    """Печать без падений на кодировке консоли."""
    try:
        print(text)
    except Exception:  # noqa: BLE001
        try:
            sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")
        except Exception:  # noqa: BLE001
            pass

class ConsolePrinter:
    """Печатает события шины в консоль."""

    def __init__(self, verbose: bool = False, printer: Any = None) -> None:
        self.verbose = verbose
        self._print = printer or _safe_print

    def __call__(self, event: Any) -> None:
        kind = getattr(event, "kind", "")
        text = getattr(event, "text", "") or ""
        data = getattr(event, "data", None) or {}
        try:
            if kind == KIND_STEP:
                self._print("")
                self._print(f"--- шаг {data.get('number', '?')} ---")
            elif kind == KIND_STATUS:
                self._print(f"[статус] {text}")
            elif kind == KIND_THOUGHT:
                self._print(f"[мысль] {text}")
            elif kind == KIND_ACTION:
                self._print(f"[действие] {text} {json.dumps(data.get('args') or {}, ensure_ascii=False)}")
            elif kind == KIND_RESULT:
                mark = "ok" if data.get("ok", True) else "ошибка"
                self._print(f"[результат] {data.get('name', '')} ({mark}): {text}")
            elif kind == KIND_IMAGE:
                size = f"{data.get('width')}x{data.get('height')}" if data.get("width") else "?"
                self._print(f"[снимок] {size} {data.get('path') or ''}".rstrip())
            elif kind == KIND_ERROR:
                self._print(f"[ОШИБКА] {text}")
            elif kind == KIND_DONE:
                result = data or {}
                self._print("")
                self._print(
                    f"[итог] success={result.get('success')} шагов={result.get('steps')} "
                    f"ошибка={result.get('error')}"
                )
                if result.get("transcript_path"):
                    self._print(f"[журнал] {result['transcript_path']}")
            elif kind == KIND_LOG:
                if self.verbose:
                    self._print(f"[лог] {text}")
            elif self.verbose:
                self._print(f"[{kind}] {text}")
        except Exception:  # noqa: BLE001 - печать не должна ломать агента
            pass

class TerminalBrokerConfirmer:
    """Подтверждение через AskBroker: вопрос задаёт главный поток CLI."""

    def __init__(self, broker: AskBroker) -> None:
        self.broker = broker

    def ask(self, question: str, details: str = "", timeout: float | None = None) -> bool:
        return self.broker.ask(question, details, timeout)

def make_ask_handler(broker: AskBroker, printer: Any = None) -> Any:
    """Обработчик KIND_ASK: спрашивает в терминале и отвечает брокеру."""
    out = printer or _safe_print

    def handler(event: Any) -> None:
        if getattr(event, "kind", None) != KIND_ASK:
            return
        data = getattr(event, "data", None) or {}
        request_id = data.get("request_id")
        out("")
        out("=" * 66)
        out(f"ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ: {getattr(event, 'text', '')}")
        details = data.get("details") or ""
        if details:
            out(f"Детали: {details}")
        out("=" * 66)
        try:
            answer = input("Выполнить? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        approved = answer in ("y", "yes", "д", "да")
        if request_id:
            broker.answer(str(request_id), approved)

    return handler

# ---------------------------------------------------------------------------
# Аргументы командной строки
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "PC Agent - ИИ-агент для управления компьютером. "
            "Работает с любой моделью: Google, OpenAI, Anthropic, DeepSeek, "
            "OpenRouter и другими - провайдер определяется по ключу."
        ),
    )
    parser.add_argument("--config", metavar="PATH", default=None, help="путь к config.yaml")
    sub = parser.add_subparsers(dest="command", metavar="КОМАНДА")

    run = sub.add_parser("run", help="выполнить задачу агента")
    run.add_argument("task", nargs="+", help="текст задачи для агента")
    run.add_argument("--max-steps", type=int, default=None, help="лимит шагов агента")
    run.add_argument("--model", default=None, help="модель (по умолчанию - подбор под провайдера)")
    run.add_argument(
        "--confirm",
        choices=list(CONFIRM_MODES),
        default=None,
        help="когда спрашивать подтверждение опасных действий",
    )
    run.add_argument("--yes", action="store_true", help="не спрашивать подтверждений")
    run.add_argument("--dry-run", action="store_true", help="только показать действия, не выполнять")
    run.add_argument("--stub", action="store_true", help="оффлайн-сценарий без сети и ключа API")
    run.add_argument("--verbose", action="store_true", help="подробный вывод")
    run.add_argument("--no-uia", action="store_true", help="не читать дерево UI Automation")

    gui = sub.add_parser("gui", help="запустить графический интерфейс")
    gui.add_argument("--verbose", action="store_true", help="подробный вывод")
    gui.add_argument(
        "--debug-console",
        action="store_true",
        help="не уводить вывод в файл журнала (для отладки)",
    )

    models = sub.add_parser("models", help="показать модели, доступные ключу (любой провайдер)")
    models.add_argument("--json", action="store_true", help="вывести JSON")

    doctor = sub.add_parser("doctor", help="проверить окружение и доступы")
    doctor.add_argument("--verbose", action="store_true", help="подробный вывод")

    balance = sub.add_parser("balance", help="показать остаток токенов по ключу API")
    balance.add_argument("--json", action="store_true", help="вывести JSON")
    balance.add_argument(
        "--models",
        action="store_true",
        help="показать, на сколько хватит остатка по каждой модели",
    )

    config = sub.add_parser("config", help="показать текущую конфигурацию")
    config.add_argument("--show", action="store_true", help="показать конфигурацию (действие по умолчанию)")
    config.add_argument("--json", action="store_true", help="вывести JSON вместо YAML")

    return parser

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы и нормализовать задачу в строку."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if getattr(args, "task", None):
        args.task = " ".join(str(part) for part in args.task).strip()
    return args

# ---------------------------------------------------------------------------
# Конфигурация и сборка компонентов
# ---------------------------------------------------------------------------

def _load_config(args: argparse.Namespace) -> AppConfig:
    """Загрузить конфигурацию с учётом флагов командной строки."""
    load_env()
    config = load_config(getattr(args, "config", None), use_env=False)
    if getattr(args, "model", None):
        config.model = str(args.model).strip()
    if getattr(args, "max_steps", None):
        config.max_steps = max(1, int(args.max_steps))
    if getattr(args, "confirm", None):
        config.confirm_mode = str(args.confirm)
    if getattr(args, "dry_run", False):
        config.dry_run = True
    if getattr(args, "stub", False):
        config.stub_mode = True
    if getattr(args, "no_uia", False):
        config.include_uia_tree = False
    return config

def _make_logger(config: AppConfig) -> Any:
    """JSONL-журнал; при проблемах с диском - пустой журнал."""
    try:
        return JsonlLogger(config.log_path, "agent")
    except Exception as exc:  # noqa: BLE001
        _safe_print(f"[предупреждение] журнал недоступен: {exc}")
        return NullLogger()

def _make_screen(config: AppConfig) -> Any:
    """Сервис экрана, если модуль pcagent.capture уже готов."""
    try:
        from pcagent.capture import Screen

        return Screen(config)
    except Exception as exc:  # noqa: BLE001 - модуль может быть ещё не готов
        _safe_print(f"[предупреждение] сервис экрана недоступен: {exc}")
        return None

# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------

def _start_hotkey(config: AppConfig, callback: Any, logger: Any = None) -> Any:
    """Включить глобальный стоп-кран (Ctrl+Alt+Q по умолчанию).

    Если Windows не дала зарегистрировать сочетание, работа продолжается
    без него: Ctrl+C в консоли всегда доступен.
    """
    combination = str(getattr(config, "stop_hotkey", "") or "").strip()
    if not combination:
        return None
    try:
        from pcagent.hotkey import HotkeyListener

        listener = HotkeyListener(combination, callback=callback, logger=logger)
    except Exception as exc:  # noqa: BLE001
        _safe_print(f"[предупреждение] стоп-кран недоступен: {exc}")
        return None
    if listener.start():
        _safe_print(f"[стоп-кран] {combination} - аварийная остановка агента")
        return listener
    _safe_print(f"[предупреждение] не удалось занять {combination}: {listener.error}")
    return None


def cmd_run(args: argparse.Namespace) -> int:
    """Выполнить задачу агента."""
    config = _load_config(args)
    setup_console_logging(bool(getattr(args, "verbose", False)))

    if not config.stub_mode:
        issues = config.validate()
        if issues:
            for issue in issues:
                _safe_print(f"[ошибка] {issue}")
            _safe_print("Подсказка: ключ задаётся в .env (PCAGENT_API_KEY или имя провайдера) "
                    "либо через --stub для офлайн-проверки.")
            return 2

    kill_switch.reset()
    # Посредник видит задачи, снимки экрана и ключ: сказать об этом до старта.
    try:
        from pcagent.gui import providers as _providers

        _pr = _providers.detect_provider(str(config.resolve_api_key() or ""))
        _notice = _providers.privacy_notice(_pr, str(config.model or ""))
        if _notice:
            _safe_print("[внимание] " + _notice)
    except Exception:  # noqa: BLE001 - предупреждение не должно мешать запуску
        pass

    bus = EventBus()
    printer = ConsolePrinter(verbose=bool(getattr(args, "verbose", False)))
    bus.subscribe(printer)

    broker = AskBroker(bus)
    bus.subscribe(make_ask_handler(broker))
    confirmer = TerminalBrokerConfirmer(broker)

    policy = Policy(
        confirm_mode=config.confirm_mode,
        allow_destructive=config.allow_destructive,
        allow_shell=config.allow_shell,
        dry_run=config.dry_run,
        assume_yes=bool(getattr(args, "yes", False)),
        confirmer=confirmer,
    )
    registry = build_default_registry(config.enabled_categories)
    if len(registry) == 0:
        _safe_print("[предупреждение] не найдено ни одного инструмента: модули pcagent.capture / input_control / ...")
    logger = _make_logger(config)
    screen = _make_screen(config)

    brain = None
    if config.stub_mode:
        from pcagent.stub_brain import StubBrain

        brain = StubBrain(logger=logger)
    else:
        # Мозг строится по ключу: официальный SDK Google или HTTP
        # (OpenAI-совместимые API остальных провайдеров). Раньше CLI умел
        # работать только с Google, хотя GUI поддерживал всех.
        api_key = config.resolve_api_key()
        if api_key:
            try:
                from pcagent.gui import providers

                extra = dict(getattr(config, "extra", None) or {})
                brain = providers.make_brain(
                    config,
                    api_key,
                    logger=logger,
                    provider_id=extra.get("provider") or None,
                    base_url=extra.get("base_url") or None,
                    model=str(config.model or "") or None,
                )
                _safe_print(
                    f"[мозг] провайдер: {extra.get('provider') or 'auto'}, модель: {config.model}"
                )
            except Exception as exc:  # noqa: BLE001 - AgentSession попробует сам
                _safe_print(f"[предупреждение] не удалось собрать мозг провайдера: {exc}")

    session = AgentSession(
        config=config,
        registry=registry,
        policy=policy,
        bus=bus,
        logger=logger,
        brain=brain,
        screen=screen,
    )

    hotkey = _start_hotkey(config, kill_switch.trigger, logger)
    try:
        result = session.run_task(args.task)
    except KeyboardInterrupt:
        kill_switch.trigger()
        _safe_print("\n[прервано] задача остановлена пользователем")
        return 130
    finally:
        if hotkey is not None:
            hotkey.stop()

    _safe_print("")
    if result.success:
        _safe_print(f"ГОТОВО за {result.steps} шаг(ов): {result.final_text}")
    else:
        _safe_print(f"НЕ ВЫПОЛНЕНО за {result.steps} шаг(ов): {result.error}")
    if result.transcript_path:
        _safe_print(f"Журнал: {result.transcript_path}")
    return 0 if result.success else 1

def cmd_gui(args: argparse.Namespace) -> int:
    """Запустить графический интерфейс (ленивый импорт).

    В безконсольном режиме (pythonw) stdout и stderr отсутствуют, поэтому
    весь вывод уводится в файл logs/gui.log: иначе первый же print()
    уронил бы запуск, а ошибка исчезла бы бесследно.
    """
    config = _load_config(args)
    debug_console = bool(getattr(args, "debug_console", False))
    logger_mod = None
    # Журнал ведём всегда: при запуске через pythonw у процесса нет консоли,
    # и без файла ошибки исчезают бесследно. Потоки вывода подменяются только
    # когда их нет, поэтому консольный запуск печатает как обычно.
    try:
        from pcagent.gui import logfile as logger_mod

        logger_mod.setup(getattr(config, "log_dir", "logs"), console=debug_console)
    except Exception:  # noqa: BLE001 - журнал не должен мешать запуску
        logger_mod = None
    try:
        from pcagent import gui
    except Exception as exc:  # noqa: BLE001 - GUI пишет другой исполнитель
        message = f"GUI недоступен: {type(exc).__name__}: {exc}"
        _safe_print(f"[ошибка] {message}")
        _safe_print("GUI ещё не готов или не установлен tkinter. Используйте команду run.")
        if logger_mod is not None:
            logger_mod.show_error("PC Agent: GUI недоступен", message)
        return 2

    launch = getattr(gui, "launch", None)
    if launch is None:
        _safe_print("[ошибка] в pcagent.gui нет функции launch()")
        return 2
    try:
        try:
            return int(launch(config) or 0)
        except TypeError:
            return int(launch() or 0)
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        _safe_print(f"[ошибка] не удалось запустить GUI: {message}")
        if logger_mod is not None:
            logger_mod.show_error("PC Agent: ошибка запуска", message)
        return 2

def config_error_hint() -> str:
    """Единая подсказка про ключ: клиент универсальный, провайдер любой."""
    try:
        from pcagent.config import API_KEY_HINT

        return API_KEY_HINT
    except Exception:  # noqa: BLE001
        return "ключ API не задан: положите его в .env как PCAGENT_API_KEY"


def cmd_models(args: argparse.Namespace) -> int:
    """Показать модели, доступные ключу API (любой провайдер)."""
    config = _load_config(args)
    api_key = config.resolve_api_key()
    if not api_key:
        _safe_print("[ошибка] " + config_error_hint())
        return 2

    try:
        from pcagent.gui import providers
    except Exception as exc:  # noqa: BLE001
        _safe_print(f"[ошибка] модуль провайдеров недоступен: {exc}")
        return 1

    provider = providers.detect_provider(str(api_key))
    if provider is None:
        _safe_print("[ошибка] не удалось определить провайдера по ключу")
        return 2

    extra = dict(getattr(config, "extra", None) or {})
    base_url = extra.get("base_url") or None
    _safe_print(f"Провайдер: {provider.title} ({provider.id})")

    if provider.google_sdk:
        # У Google свой SDK: он отдаёт больше сведений о модели.
        try:
            from google import genai

            timeout_ms = max(1, int(config.request_timeout_s)) * 1000
            client = genai.Client(api_key=api_key, http_options={"timeout": timeout_ms})
            items = llm.list_models(client)
        except Exception as exc:  # noqa: BLE001 - сеть, ключ, SDK
            _safe_print(f"[ошибка] {exc}")
            return 1
        if getattr(args, "json", False):
            _safe_print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
        if not items:
            _safe_print("Модели не найдены.")
            return 0
        _safe_print(f"Модель по умолчанию: {config.model}")
        _safe_print("")
        _safe_print(f"{'модель':<42} {'generateContent':<16} контекст")
        for item in items:
            supports = "да" if item.get("supports_generate") else "нет"
            limit = item.get("input_token_limit") or "-"
            _safe_print(f"{item['name']:<42} {supports:<16} {limit}")
        return 0

    names, error = providers.fetch_models(provider, str(api_key), base_url=base_url)
    if error and not names:
        _safe_print(f"[ошибка] {error}")
        return 1

    multipliers = providers.fetch_multipliers(provider, str(api_key), base_url=base_url)
    if getattr(args, "json", False):
        _safe_print(
            json.dumps(
                {
                    "provider": provider.id,
                    "provider_title": provider.title,
                    "models": names,
                    "multipliers": multipliers,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    if not names:
        _safe_print("Модели не найдены.")
        return 0

    current = str(config.model or "")
    _safe_print(f"Модель по умолчанию: {current or 'подбирается под провайдера'}")
    _safe_print(f"Всего моделей: {len(names)}")
    if multipliers:
        _safe_print("")
        _safe_print(f"{'модель':<40} {'множитель':>10}")
        for name in names:
            mark = " *" if name == current else ""
            _safe_print(f"{name:<40} {multipliers.get(name, '-'):>10}{mark}")
        _safe_print("")
        _safe_print("* - текущая модель")
    else:
        _safe_print("")
        for name in names:
            _safe_print(f"  {name}{' *' if name == current else ''}")
    return 0


def _check_package(module_name: str) -> tuple[bool, str]:
    """Установлен ли модуль (без импорта)."""
    try:
        return importlib.util.find_spec(module_name) is not None, module_name
    except Exception:  # noqa: BLE001
        return False, module_name

def _check_screen() -> tuple[bool, str]:
    """Доступ к экрану через mss."""
    try:
        import mss

        factory = getattr(mss, "MSS", None) or mss.mss
        with factory() as sct:
            monitor = sct.monitors[0]
            width, height = int(monitor.get("width", 0)), int(monitor.get("height", 0))
        if width <= 0 or height <= 0:
            return False, "нулевой размер экрана"
        return True, f"{width}x{height}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"

def _check_dpi() -> tuple[bool, str]:
    """DPI-awareness текущего процесса."""
    try:
        import ctypes

        try:
            awareness = ctypes.c_int()
            hr = ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness))
            if hr == 0:
                names = {0: "unaware", 1: "system", 2: "per-monitor"}
                return awareness.value > 0, names.get(awareness.value, str(awareness.value))
        except Exception:  # noqa: BLE001 - старые Windows
            pass
        aware = bool(ctypes.windll.user32.GetProcessDPIAware())
        return aware, "system (legacy)"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"

def cmd_doctor(args: argparse.Namespace) -> int:
    """Отчёт о готовности окружения.

    Сеть не используется, кроме проверки сертификата провайдера, и только
    если ключ API найден.
    """
    config = _load_config(args)
    verbose = bool(getattr(args, "verbose", False))
    # (имя, успех, подробности, критично ли для запуска)
    checks: list[tuple[str, bool, str, bool]] = []

    version = sys.version_info
    checks.append(
        (
            "Python",
            version >= (3, 10),
            f"{version.major}.{version.minor}.{version.micro}",
            True,
        )
    )

    packages = [
        ("google.genai", True),
        ("mss", True),
        ("PIL", True),
        ("pyautogui", True),
        ("pygetwindow", True),
        ("psutil", True),
        ("uiautomation", True),
        ("dotenv", False),
        ("yaml", False),
        ("pyperclip", False),
        ("pytest", False),
    ]
    for module_name, critical in packages:
        present, _ = _check_package(module_name)
        checks.append(
            (
                f"пакет {module_name}",
                present,
                "установлен" if present else "не найден",
                critical,
            )
        )

    # Без ключа работает stub-режим, поэтому это предупреждение, а не отказ.
    api_key = config.resolve_api_key()
    checks.append(
        (
            "ключ API",
            bool(api_key),
            "найден" if api_key else "не найден (PCAGENT_API_KEY или имя провайдера) - доступен только режим --stub",
            False,
        )
    )

    # Провайдер и его TLS: посредник видит данные, а просроченный сертификат
    # означает, что клиент не может убедиться, что говорит с нужным сервером.
    if api_key:
        try:
            from pcagent.gui import providers

            provider = providers.detect_provider(str(api_key))
            if provider is not None:
                if providers.is_official(provider):
                    checks.append(("провайдер", True, f"{provider.title} (официальный API)", False))
                else:
                    checks.append(
                        (
                            "провайдер",
                            True,
                            f"{provider.title} - ПОСРЕДНИК: видит задачи, снимки экрана и ключ",
                            False,
                        )
                    )
                tls_ok, tls_detail = providers.check_tls(provider)
                if tls_ok is False:
                    checks.append(("TLS провайдера", False, tls_detail, False))
                elif tls_ok is True:
                    checks.append(("TLS провайдера", True, tls_detail, False))
                elif verbose:
                    checks.append(("TLS провайдера", True, tls_detail, False))
        except Exception as exc:  # noqa: BLE001 - проверка не критична
            checks.append(("провайдер", True, f"не проверен: {exc}", False))

    screen_ok, screen_detail = _check_screen()
    checks.append(("доступ к экрану", screen_ok, screen_detail, True))

    dpi_ok, dpi_detail = _check_dpi()
    checks.append(("DPI-awareness процесса", dpi_ok, dpi_detail, False))

    try:
        from pcagent.config import DEFAULT_CONFIG_PATH

        exists = DEFAULT_CONFIG_PATH.exists()
        checks.append(
            (
                "config.yaml",
                True,
                "найден" if exists else "нет (будут значения по умолчанию)",
                False,
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("config.yaml", False, str(exc), False))

    try:
        config.log_path.mkdir(parents=True, exist_ok=True)
        checks.append(("каталог журналов", True, str(config.log_path), True))
    except Exception as exc:  # noqa: BLE001
        checks.append(("каталог журналов", False, str(exc), True))

    if verbose:
        checks.append(("модель", True, str(config.model), False))
        checks.append(("режим подтверждений", True, str(config.confirm_mode), False))

    _safe_print("Проверка окружения PC Agent")
    _safe_print("=" * 66)
    failed = 0
    warnings = 0
    for name, ok, detail, critical in checks:
        if ok:
            mark = "OK  "
        elif critical:
            mark = "FAIL"
            failed += 1
        else:
            mark = "WARN"
            warnings += 1
        _safe_print(f"[{mark}] {name}: {detail}")
    _safe_print("=" * 66)
    if failed:
        _safe_print(f"Проблем: {failed}. Исправьте их перед реальным запуском агента.")
        return 1
    if warnings:
        _safe_print(f"Предупреждений: {warnings}. Агент запустится, но возможности ограничены.")
    _safe_print("Всё готово: можно запускать 'pcagent run \"задача\"'.")
    return 0

def cmd_config(args: argparse.Namespace) -> int:
    """Показать текущую конфигурацию без секретов."""
    config = _load_config(args)
    data = config.to_dict()
    if data.get("api_key"):
        data["api_key"] = "***"
    if getattr(args, "json", False):
        _safe_print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return 0
    try:
        import yaml

        _safe_print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    except Exception:  # noqa: BLE001
        _safe_print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return 0

# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def cmd_balance(args: argparse.Namespace) -> int:
    """Показать остаток токенов по ключу API."""
    config = _load_config(args)
    if bool(getattr(config, "stub_mode", False)):
        _safe_print("[ошибка] stub-режим: остаток смотреть не у чего")
        return 2

    key = ""
    try:
        key = str(config.resolve_api_key() or "").strip()
    except Exception:  # noqa: BLE001
        key = str(getattr(config, "api_key", "") or "").strip()
    if not key:
        _safe_print("[ошибка] ключ API не найден (проверьте .env или Файл - Ключ API...)")
        return 2

    try:
        from pcagent.gui import providers
    except Exception as exc:  # noqa: BLE001
        _safe_print(f"[ошибка] модуль провайдеров недоступен: {exc}")
        return 1

    provider = providers.detect_provider(key)
    if provider is None:
        _safe_print("[ошибка] не удалось определить провайдера по ключу")
        return 2

    extra = dict(getattr(config, "extra", None) or {})
    base_url = extra.get("base_url") or None

    balance, error = providers.fetch_balance(provider, key, base_url=base_url)
    multipliers = providers.fetch_multipliers(provider, key, base_url=base_url)

    if getattr(args, "json", False):
        payload = {
            "provider": provider.id,
            "provider_title": provider.title,
            "model": config.model,
            "tokens": balance.tokens if balance else None,
            "note": (balance.note if balance else "") or (error or ""),
            "multipliers": multipliers,
            "models": {},
        }
        if balance and balance.tokens is not None and multipliers:
            payload["models"] = {
                name: int(balance.tokens / value)
                for name, value in sorted(multipliers.items(), key=lambda kv: kv[1])
            }
        _safe_print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0

    _safe_print(f"Провайдер: {provider.title}")
    _safe_print(f"Ключ:      {key[:8]}...{key[-4:]}")
    if balance is None:
        _safe_print(f"Остаток:   неизвестен - {error}")
        return 0

    _safe_print(f"Остаток:   {balance.describe()}")
    if balance.tokens is not None and multipliers:
        current = str(config.model or "")
        if current in multipliers:
            share = int(balance.tokens / multipliers[current])
            _safe_print(
                f"           в токенах модели {current} (множитель {multipliers[current]:g}): "
                f"~{share:,}".replace(",", " ")
            )
        if getattr(args, "models", False):
            _safe_print("")
            _safe_print(f"{'модель':<24} {'множ.':>6}  хватит токенов")
            for name, value in sorted(multipliers.items(), key=lambda kv: kv[1]):
                share = int(balance.tokens / value)
                _safe_print(f"{name:<24} {value:>6g}  ~{share:,}".replace(",", " "))
    return 0

COMMANDS = {
    "run": cmd_run,
    "gui": cmd_gui,
    "models": cmd_models,
    "balance": cmd_balance,
    "doctor": cmd_doctor,
    "config": cmd_config,
}

def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI: возвращает код возврата."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if getattr(args, "task", None):
        args.task = " ".join(str(part) for part in args.task).strip()

    command = getattr(args, "command", None)
    if not command:
        parser.print_help()
        return 2

    handler = COMMANDS.get(str(command))
    if handler is None:  # pragma: no cover - защита от опечатки
        parser.print_help()
        return 2

    try:
        return int(handler(args))
    except KeyboardInterrupt:
        _safe_print("\n[прервано]")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI не должен показывать трейс
        _safe_print(f"[ошибка] {type(exc).__name__}: {exc}")
        return 1

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
