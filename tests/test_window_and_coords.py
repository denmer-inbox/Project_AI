"""Исправления по итогам прогонов на STEP 7: окна и координаты.

Прогон показал, что клиент тратит минуты на два недоразумения:
  * ждёт окно с заголовком "MicroWIN", а оно называется "Micro/WIN" -
    два ожидания подряд съели 155 секунд из 451;
  * ui_tree отдаёт координаты рабочего стола, а click ждёт пиксели снимка -
    модель пересчитывала их вручную и кликала мимо.
"""

from __future__ import annotations

import pytest

from pcagent import windows_apps


# ------------------------------------------------ сравнение заголовков
@pytest.mark.parametrize(
    "query,title",
    [
        ("MicroWIN", "Project1 - STEP 7-Micro/WIN SMART"),
        ("Micro/WIN", "Project1 - STEP 7-Micro/WIN SMART"),
        ("micro win", "Project1 - STEP 7-Micro/WIN SMART"),
        ("STEP7", "Project1 - STEP 7-Micro/WIN SMART"),
        ("S7-200", "Project1 - STEP 7-Micro/WIN SMART"),  # нет: проверим ниже
    ],
)
def test_normalize_title_ignores_separators(query, title):
    needle = windows_apps._normalize_title(query)
    haystack = windows_apps._normalize_title(title)
    if query == "S7-200":
        assert needle not in haystack
    else:
        assert needle in haystack, f"{query!r} должно находить {title!r}"


def test_find_windows_falls_back_to_loose_match(monkeypatch):
    """Если точной подстроки нет, ищем без учёта разделителей."""
    windows = [
        {"hwnd": 1, "title": "Project1 - STEP 7-Micro/WIN SMART", "pid": 10},
        {"hwnd": 2, "title": "Блокнот", "pid": 11},
    ]
    monkeypatch.setattr(windows_apps, "_iter_windows", lambda: windows)

    # Точное совпадение подстроки не сработает: в заголовке "Micro/WIN".
    found = windows_apps._find_windows("MicroWIN")
    assert [item["hwnd"] for item in found] == [1]


def test_find_windows_prefers_exact_substring(monkeypatch):
    windows = [
        {"hwnd": 1, "title": "Проект - Micro/WIN SMART", "pid": 10},
        {"hwnd": 2, "title": "Другое окно MicroWIN", "pid": 11},
    ]
    monkeypatch.setattr(windows_apps, "_iter_windows", lambda: windows)
    found = windows_apps._find_windows("MicroWIN")
    # Точная подстрока важнее "размытого" совпадения.
    assert found[0]["hwnd"] == 2


def test_wait_for_window_timeout_lists_visible_titles(monkeypatch):
    """На таймауте модель должна увидеть, что реально открыто."""
    windows = [
        {"hwnd": 1, "title": "Project1 - STEP 7-Micro/WIN SMART", "pid": 10},
        {"hwnd": 2, "title": "Блокнот", "pid": 11},
    ]
    monkeypatch.setattr(windows_apps, "_iter_windows", lambda: windows)
    monkeypatch.setattr(windows_apps, "_find_windows", lambda title: [])

    result = windows_apps._tool_wait_for_window(None, {"title": "НетТакого", "timeout": 0.3})
    assert result.ok is False
    assert result.error == "window_timeout"
    assert "Micro/WIN" in result.summary
    assert result.data["visible_titles"]


# ------------------------------------------------ система координат
def test_to_screen_uses_screenshot_by_default():
    from pcagent.input_control import _to_screen
    from pcagent.interfaces import Screenshot

    shot = Screenshot(
        image_bytes=b"",
        width=1000,
        height=500,
        scale=0.5,
        origin_left=100,
        origin_top=50,
        real_width=2000,
        real_height=1000,
    )
    x, y = _to_screen(shot, 100, 50, {})
    assert (x, y) == (300, 150)  # 100 + 100/0.5, 50 + 50/0.5


def test_to_screen_accepts_desktop_coordinates():
    from pcagent.input_control import _to_screen
    from pcagent.interfaces import Screenshot

    shot = Screenshot(image_bytes=b"", width=1000, height=500, scale=0.5)
    x, y = _to_screen(shot, 94, 239, {"space": "screen"})
    assert (x, y) == (94, 239)


@pytest.mark.parametrize("value", ["screen", "desktop", "absolute", "экран", "SCREEN"])
def test_coords_space_aliases(value):
    from pcagent.input_control import _coords_space

    assert _coords_space({"space": value}) == "screen"


@pytest.mark.parametrize("value", [None, "", "image", "пиксели"])
def test_coords_space_defaults_to_image(value):
    from pcagent.input_control import _coords_space

    assert _coords_space({"space": value} if value is not None else {}) == "image"


def test_click_schema_exposes_space():
    from pcagent.tools.base import build_default_registry

    registry = build_default_registry()
    tool = registry.tools["click"] if hasattr(registry, "tools") else None
    if tool is None:
        pytest.skip("реестр не отдаёт инструменты напрямую")
    properties = tool.parameters.get("properties") or {}
    assert "space" in properties
