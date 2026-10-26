# -*- coding: utf-8 -*-
"""Регресс-тесты отбора: нужные инструменты не теряются на составных задачах."""
from __future__ import annotations

import pytest

from pcagent.gui import tool_router
from pcagent.tools.base import build_default_registry


@pytest.fixture(scope="module")
def registry():
    return build_default_registry()


@pytest.mark.parametrize(
    "task, needed",
    [
        ("открой калькулятор и посчитай 15*7", ["launch_app", "click", "type_text"]),
        ("запусти блокнот и напечатай текст", ["launch_app", "type_text"]),
        ("открой браузер и введи адрес", ["launch_app", "type_text", "press_key"]),
        ("что сейчас на экране?", ["screenshot", "screen_info", "ui_tree"]),
        ("заверши процесс notepad.exe", ["kill_process", "list_processes"]),
        ("удали файл report.txt из папки Загрузки", ["run_script", "open_path"]),
        ("open notepad and type hello", ["launch_app", "type_text"]),
    ],
)
def test_needed_tools_survive_routing(registry, task, needed):
    """Эвристика отбора не должна лишать модель нужного инструмента."""
    routed, _info = tool_router.filter_registry(registry, task, enabled=True)
    names = set(routed.names())
    missing = [name for name in needed if name not in names]
    assert not missing, f"для {task!r} потеряны: {missing}"


def test_opening_app_implies_basic_input_tools(registry):
    """Открытие приложения почти всегда требует ввода в него."""
    routed, info = tool_router.filter_registry(registry, "открой orcaslicer", enabled=True)
    names = set(routed.names())
    assert "window" in info["groups"]
    assert {"click", "type_text", "press_key", "hotkey"} <= names
    # но не вся группа input: drag/scroll для открытия приложения не нужны
    assert "drag" not in names
    assert "scroll" not in names


def test_capture_tools_are_never_filtered(registry):
    for task in ("удали файл", "заверши процесс", "посчитай сумму", "что на экране"):
        routed, _ = tool_router.filter_registry(registry, task, enabled=True)
        assert {"screenshot", "screen_info", "ui_tree"} <= set(routed.names())


def test_unrecognized_task_gets_everything(registry):
    routed, info = tool_router.filter_registry(registry, "сделай что-нибудь полезное", enabled=True)
    assert info["fallback"] is True
    assert len(routed) == len(registry)


def test_routing_can_be_disabled(registry):
    routed, info = tool_router.filter_registry(registry, "что на экране", enabled=False)
    assert routed is registry
    assert info["enabled"] is False


def test_routing_saves_meaningful_traffic(registry):
    full = tool_router.declaration_size(registry.declarations())
    routed, _ = tool_router.filter_registry(registry, "что сейчас на экране?", enabled=True)
    reduced = tool_router.declaration_size(routed.declarations())
    assert reduced < full * 0.35, f"экономия слишком мала: {reduced} из {full}"
