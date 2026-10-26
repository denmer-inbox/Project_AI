"""Графический клиент PC Agent на tkinter.

Пакет содержит:
  * app.py - класс AgentApp (главное окно) и точку входа main();
  * launch() - собрать конфигурацию, шину и брокер, затем запустить GUI.

Импорт tkinter происходит только при реальном запуске окна, поэтому
остальные модули проекта (CLI, тесты) могут импортировать пакет без
графической подсистемы.
"""

from __future__ import annotations

from typing import Any

__all__ = ["launch", "main", "AgentApp", "APP_TITLE"]

APP_TITLE = "PC Agent"


def launch(
    config: Any = None,
    bus: Any = None,
    broker: Any = None,
    **app_kwargs: Any,
) -> int:
    """Запустить GUI и вернуть код выхода (0 - нормальное завершение).

    Параметры необязательны: если config/bus/broker не переданы, они
    создаются по умолчанию. Ошибки запуска печатаются в консоль и
    превращаются в код возврата 1, чтобы CLI не падал стектрейсом.
    """
    from pcagent.config import load_config
    from pcagent.events import AskBroker, EventBus

    try:
        cfg = config if config is not None else load_config()
        event_bus = bus if bus is not None else EventBus()
        ask_broker = broker if broker is not None else AskBroker(event_bus)
    except Exception as exc:  # noqa: BLE001 - запуск не должен падать стектрейсом
        print(f"Не удалось подготовить GUI: {exc}")
        return 1

    try:
        from pcagent.gui.app import AgentApp
    except Exception as exc:  # noqa: BLE001
        print(f"Не удалось загрузить GUI (нет tkinter?): {exc}")
        return 1

    try:
        app = AgentApp(cfg, event_bus, ask_broker, **app_kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"Не удалось открыть окно PC Agent: {exc}")
        return 1

    return app.run()


def main(argv: list[str] | None = None) -> int:
    """Точка входа для запуска GUI напрямую."""
    return launch()


def __getattr__(name: str) -> Any:
    """Ленивый доступ к AgentApp без импорта tkinter на уровне пакета."""
    if name in ("AgentApp", "APP_TITLE"):
        from pcagent.gui import app as app_module

        return getattr(app_module, name)
    raise AttributeError(f"module 'pcagent.gui' has no attribute {name!r}")
