"""Пакет инструментов агента.

Каждый модуль инструментов обязан экспортировать функцию
register(registry: ToolRegistry) -> None и реализовывать независимую
группу инструментов (категорию).
"""

from __future__ import annotations

import importlib
from types import ModuleType

TOOL_MODULES: tuple[str, ...] = (
    "pcagent.capture",          # категория capture  (исполнитель A)
    "pcagent.input_control",    # категория input    (исполнитель B)
    "pcagent.windows_apps",     # категория windows  (исполнитель B)
    "pcagent.system_ops",       # категория system   (исполнитель B)
    "pcagent.gui.console_tools",  # system: run_script / run_powershell (без tkinter)
)

__all__ = ["TOOL_MODULES", "import_tool_module", "build_default_registry"]


def import_tool_module(module_name: str) -> ModuleType | None:
    """Импортировать модуль инструментов, вернув None при отсутствии зависимостей."""
    try:
        return importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 - модуль может требовать необязательные пакеты
        return None


def build_default_registry(categories: list[str] | None = None):
    from pcagent.tools.base import build_default_registry as _build

    return _build(categories)
