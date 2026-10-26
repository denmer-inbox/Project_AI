"""Тесты командной строки: разбор аргументов, doctor, config, stub-запуск."""

from __future__ import annotations

import pytest

from pcagent import cli
from pcagent.events import kill_switch
from pcagent.logging_utils import NullLogger

@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Без ключа API, без .env и с временным каталогом журналов."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY", "PCAGENT_MODEL", "PCAGENT_DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    kill_switch.reset()
    yield
    kill_switch.reset()

class FakeLogger:
    """Журнал в памяти: CLI проверяет только путь для отчёта."""

    def __init__(self, path: str = "logs/test.jsonl") -> None:
        self.path = path
        self.records: list[tuple[str, dict]] = []

    def log(self, kind: str, payload: dict | None = None, **extra) -> None:
        self.records.append((kind, payload or {}))

    def close(self) -> None:
        return None

@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Изолировать CLI от реального экрана, журналов и чужих модулей."""
    monkeypatch.setattr(cli, "_make_logger", lambda config: FakeLogger())
    monkeypatch.setattr(cli, "_make_screen", lambda config: None)
    return tmp_path

# ---------------------------------------------------------------------------
# Разбор аргументов
# ---------------------------------------------------------------------------

def test_parser_run_defaults():
    args = cli.parse_args(["run", "открой", "блокнот"])

    assert args.command == "run"
    assert args.task == "открой блокнот"
    assert args.max_steps is None
    assert args.model is None
    assert args.confirm is None
    assert args.yes is False
    assert args.dry_run is False
    assert args.stub is False
    assert args.verbose is False
    assert args.no_uia is False

def test_parser_run_all_flags():
    args = cli.parse_args(
        [
            "run",
            "сделай",
            "что-то",
            "--max-steps",
            "7",
            "--model",
            "gemini-2.5-flash",
            "--confirm",
            "always",
            "--yes",
            "--dry-run",
            "--stub",
            "--verbose",
            "--no-uia",
        ]
    )

    assert args.task == "сделай что-то"
    assert args.max_steps == 7
    assert args.model == "gemini-2.5-flash"
    assert args.confirm == "always"
    assert args.yes is True
    assert args.dry_run is True
    assert args.stub is True
    assert args.verbose is True
    assert args.no_uia is True

def test_parser_rejects_unknown_confirm_mode():
    with pytest.raises(SystemExit):
        cli.parse_args(["run", "задача", "--confirm", "maybe"])

def test_parser_subcommands_exist():
    assert cli.parse_args(["gui"]).command == "gui"
    assert cli.parse_args(["models"]).command == "models"
    assert cli.parse_args(["doctor"]).command == "doctor"
    config_args = cli.parse_args(["config", "--show"])
    assert config_args.command == "config"
    assert config_args.show is True

def test_main_without_command_prints_help_and_returns_2(capsys):
    assert cli.main([]) == 2
    out = capsys.readouterr().out
    assert "run" in out and "doctor" in out

def test_run_overrides_config_from_flags(isolated):
    args = cli.parse_args(["run", "задача", "--max-steps", "3", "--model", "custom-model", "--dry-run", "--stub"])
    config = cli._load_config(args)

    assert config.max_steps == 3
    assert config.model == "custom-model"
    assert config.dry_run is True
    assert config.stub_mode is True

def test_run_no_uia_flag_disables_tree(isolated):
    args = cli.parse_args(["run", "задача", "--no-uia", "--stub"])
    assert cli._load_config(args).include_uia_tree is False

# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def test_doctor_reports_missing_api_key(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_check_screen", lambda: (True, "1280x720"))
    monkeypatch.setattr(cli, "_check_dpi", lambda: (True, "per-monitor"))

    code = cli.main(["doctor"])
    out = capsys.readouterr().out

    assert code == 0
    assert "ключ API" in out
    assert "не найден" in out
    assert "Python" in out
    assert "доступ к экрану" in out
    assert "config.yaml" in out

def test_doctor_reports_failures(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_check_screen", lambda: (False, "нет доступа"))
    monkeypatch.setattr(cli, "_check_dpi", lambda: (False, "unaware"))
    monkeypatch.setattr(cli, "_check_package", lambda name: (False, name))

    code = cli.main(["doctor"])
    out = capsys.readouterr().out

    assert code == 1
    assert "FAIL" in out
    assert "нет доступа" in out
    assert "Проблем" in out

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_config_show_masks_api_key(monkeypatch, capsys, isolated):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key")
    code = cli.main(["config", "--show"])
    out = capsys.readouterr().out

    assert code == 0
    assert "model:" in out
    assert "super-secret-key" not in out

def test_config_json_output(capsys, isolated):
    code = cli.main(["config", "--json"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"confirm_mode"' in out
    assert '"max_steps"' in out

# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

def test_models_without_key_returns_2(capsys, isolated):
    assert cli.main(["models"]) == 2
    assert "ключ API" in capsys.readouterr().out

# ---------------------------------------------------------------------------
# run в stub-режиме (без сети и без реального экрана)
# ---------------------------------------------------------------------------

def test_stub_run_completes_offline(capsys, isolated):
    code = cli.main(["run", "проверь цикл", "--stub", "--yes", "--max-steps", "5"])
    out = capsys.readouterr().out

    assert code == 0
    assert "ГОТОВО" in out
    assert "--- шаг 1 ---" in out
    assert "Журнал:" in out

def test_stub_run_survives_missing_tools(capsys, isolated, monkeypatch):
    """Пустой реестр: агент получает ошибки инструментов, но не падает."""
    from pcagent.tools.base import ToolRegistry

    monkeypatch.setattr(cli, "build_default_registry", lambda categories=None: ToolRegistry())

    code = cli.main(["run", "проверь цикл", "--stub", "--yes", "--max-steps", "5"])
    out = capsys.readouterr().out

    assert code == 0
    assert "не найден" in out
    assert "ГОТОВО" in out

def test_run_without_key_and_without_stub_returns_2(capsys, isolated):
    code = cli.main(["run", "задача без ключа"])
    out = capsys.readouterr().out

    assert code == 2
    assert "ключ API" in out or "не задан ключ" in out

# ---------------------------------------------------------------------------
# обработчики событий и подтверждений
# ---------------------------------------------------------------------------

def test_console_printer_handles_main_event_kinds():
    from pcagent.events import (
        KIND_ACTION,
        KIND_DONE,
        KIND_ERROR,
        KIND_IMAGE,
        KIND_RESULT,
        KIND_STATUS,
        KIND_STEP,
        KIND_THOUGHT,
        Event,
    )

    lines: list[str] = []
    printer = cli.ConsolePrinter(verbose=True, printer=lines.append)

    printer(Event.step(2))
    printer(Event.status("работаю"))
    printer(Event.thought("думаю"))
    printer(Event.action("click", {"x": 1}))
    printer(Event.result("click", True, "клик выполнен"))
    printer(Event.image(None, b"xx", width=100, height=50))
    printer(Event.error("сломалось"))
    printer(Event.done({"success": True, "steps": 2, "transcript_path": "logs/a.jsonl"}))

    text = "\n".join(lines)
    assert "шаг 2" in text
    assert "работаю" in text
    assert "думаю" in text
    assert "click" in text
    assert "клик выполнен" in text
    assert "100x50" in text
    assert "сломалось" in text
    assert "success=True" in text

def test_ask_handler_answers_broker(monkeypatch):
    from pcagent.events import AskBroker, Event, EventBus

    bus = EventBus()
    broker = AskBroker(bus, default_timeout=1.0)
    answers: list[bool] = []
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    handler = cli.make_ask_handler(broker, printer=lambda text="": None)
    original_answer = broker.answer

    def spy(request_id: str, approved: bool) -> bool:
        answers.append(approved)
        return original_answer(request_id, approved)

    broker.answer = spy  # type: ignore[assignment]
    handler(Event.ask("Разрешить клик?", "req-1", "детали"))

    assert answers == [True]

def test_terminal_broker_confirmer_delegates():
    from pcagent.events import EventBus

    class FakeBroker:
        def __init__(self):
            self.calls: list[tuple] = []

        def ask(self, question, details="", timeout=None):
            self.calls.append((question, details, timeout))
            return True

    broker = FakeBroker()
    confirmer = cli.TerminalBrokerConfirmer(broker)
    assert confirmer.ask("Вопрос", "Детали") is True
    assert broker.calls == [("Вопрос", "Детали", None)]
