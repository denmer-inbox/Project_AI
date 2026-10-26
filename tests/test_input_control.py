"""Тесты инструментов ввода: перевод координат, валидация и моки pyautogui.

Реальная мышь и клавиатура не трогаются: все функции pyautogui подменяются,
кроме случаев dry-run, где обработчик вообще не вызывается.
"""

from __future__ import annotations

import json

import pytest

from pcagent.config import AppConfig
from pcagent.events import EventBus
from pcagent.interfaces import MonitorInfo, Risk, Screenshot
from pcagent.safety import Policy
from pcagent.tools.base import ToolContext, ToolRegistry

import pcagent.input_control as input_control

EXPECTED_TOOLS = {"click", "move_mouse", "drag", "scroll", "hotkey", "type_text", "press_key"}


class FakeScreen:
    """Сервис экрана без реального захвата."""

    def __init__(self, shot: Screenshot) -> None:
        self.shot = shot
        self.captures = 0

    def monitors(self) -> list[MonitorInfo]:
        return [MonitorInfo(0, 0, 0, 2560, 1440, True)]

    def capture(self, monitor=None, max_width=None, fmt=None, quality=None) -> Screenshot:
        self.captures += 1
        return self.shot

    def size(self, monitor=None) -> tuple[int, int]:
        return (2560, 1440)

    def uia_tree(self, max_nodes=None) -> str:
        return ""

    def active_window(self):
        return None

    def close(self) -> None:
        pass


def make_shot() -> Screenshot:
    return Screenshot(
        image_bytes=b"",
        width=1280,
        height=720,
        scale=0.5,
        origin_left=100,
        origin_top=50,
        real_width=2560,
        real_height=1440,
    )


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    input_control.register(reg)
    return reg


@pytest.fixture()
def screen() -> FakeScreen:
    return FakeScreen(make_shot())


@pytest.fixture()
def ctx(config, bus, registry, screen) -> ToolContext:
    return ToolContext(
        config=config,
        screen=screen,
        policy=Policy("never", assume_yes=True),
        bus=bus,
        registry=registry,
    )


@pytest.fixture()
def mouse(monkeypatch):
    """Записать вызовы pyautogui вместо реального управления мышью."""
    import pyautogui

    calls: dict[str, list] = {
        "click": [],
        "moveTo": [],
        "dragTo": [],
        "scroll": [],
        "hotkey": [],
        "write": [],
        "press": [],
    }
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: calls["click"].append((a, k)))
    monkeypatch.setattr(pyautogui, "moveTo", lambda *a, **k: calls["moveTo"].append((a, k)))
    monkeypatch.setattr(pyautogui, "dragTo", lambda *a, **k: calls["dragTo"].append((a, k)))
    monkeypatch.setattr(pyautogui, "scroll", lambda *a, **k: calls["scroll"].append((a, k)))
    monkeypatch.setattr(pyautogui, "hotkey", lambda *a, **k: calls["hotkey"].append((a, k)))
    monkeypatch.setattr(pyautogui, "write", lambda *a, **k: calls["write"].append((a, k)))
    monkeypatch.setattr(pyautogui, "press", lambda *a, **k: calls["press"].append((a, k)))
    return calls


# --------------------------------------------------------------- регистрация
def test_input_tools_are_registered(registry):
    assert set(registry.names()) == EXPECTED_TOOLS
    assert registry.categories() == ["input"]


def test_input_declarations_are_valid(registry):
    risk_map = {
        "click": Risk.WRITE,
        "move_mouse": Risk.WRITE,
        "drag": Risk.WRITE,
        "scroll": Risk.WRITE,
        "hotkey": Risk.WRITE,
        "type_text": Risk.WRITE,
        "press_key": Risk.WRITE,
    }
    for declaration in registry.declarations():
        assert declaration["name"] in EXPECTED_TOOLS
        assert len(declaration["description"]) > 20
        params = declaration["parameters"]
        assert params["type"] == "object"
        json.dumps(params)
        for required in params.get("required", []):
            assert required in params["properties"]
    for name, risk in risk_map.items():
        assert registry.get(name).risk is risk
        assert registry.get(name).category == "input"


# --------------------------------------------------------------------- click
def test_click_converts_image_coordinates(ctx, mouse):
    result = ctx.registry.execute(ctx, "click", {"x": 10, "y": 10})
    assert result.ok, result.error
    assert len(mouse["click"]) == 1
    args, kwargs = mouse["click"][0]
    assert args == (120, 70)
    assert kwargs["button"] == "left"
    assert kwargs["clicks"] == 1
    assert result.data["x"] == 120 and result.data["y"] == 70
    assert result.data["image_x"] == 10 and result.data["image_y"] == 10


def test_click_double_flag_and_button(ctx, mouse):
    result = ctx.registry.execute(ctx, "click", {"x": 10, "y": 20, "double": True, "button": "right"})
    assert result.ok, result.error
    _, kwargs = mouse["click"][0]
    assert kwargs["clicks"] == 2
    assert kwargs["button"] == "right"


def test_click_clamps_coordinates_to_real_area(ctx, mouse):
    result = ctx.registry.execute(ctx, "click", {"x": 100000, "y": 100000})
    assert result.ok, result.error
    args, _ = mouse["click"][0]
    assert args == (100 + 2559, 50 + 1439)


def test_click_rejects_missing_coordinates(ctx, mouse):
    result = ctx.registry.execute(ctx, "click", {"x": 5})
    assert not result.ok and result.error == "bad_arguments"
    assert not mouse["click"]


def test_click_rejects_unknown_button(ctx, mouse):
    result = ctx.registry.execute(ctx, "click", {"x": 5, "y": 5, "button": "side"})
    assert not result.ok and result.error == "bad_button"
    assert not mouse["click"]


def test_click_without_screen_fails_clearly(config, bus, registry, mouse):
    ctx = ToolContext(config=config, screen=None, policy=Policy("never", assume_yes=True), bus=bus, registry=registry)
    result = ctx.registry.execute(ctx, "click", {"x": 5, "y": 5})
    assert not result.ok and result.error == "screen_unavailable"
    assert "экран" in result.summary.lower()
    assert not mouse["click"]


# ---------------------------------------------------------------- move_mouse
def test_move_mouse_uses_absolute_point(ctx, mouse):
    result = ctx.registry.execute(ctx, "move_mouse", {"x": 20, "y": 30, "duration": 0.4})
    assert result.ok, result.error
    args, kwargs = mouse["moveTo"][0]
    assert args == (140, 110)
    assert kwargs["duration"] == pytest.approx(0.4)


# ---------------------------------------------------------------------- drag
def test_drag_requires_four_coordinates(ctx, mouse):
    result = ctx.registry.execute(ctx, "drag", {"from_x": 1, "from_y": 2, "to_x": 3})
    assert not result.ok and result.error == "bad_arguments"
    assert not mouse["dragTo"]


def test_drag_converts_both_points(ctx, mouse):
    result = ctx.registry.execute(ctx, "drag", {"from_x": 10, "from_y": 10, "to_x": 60, "to_y": 60})
    assert result.ok, result.error
    assert mouse["moveTo"][0][0] == (120, 70)
    args, kwargs = mouse["dragTo"][0]
    assert args == (220, 170)
    assert kwargs["button"] == "left"


# -------------------------------------------------------------------- scroll
def test_scroll_without_point(ctx, mouse):
    result = ctx.registry.execute(ctx, "scroll", {"amount": -3})
    assert result.ok, result.error
    args, kwargs = mouse["scroll"][0]
    assert args == (-3,)
    assert kwargs["x"] is None and kwargs["y"] is None


def test_scroll_at_point(ctx, mouse):
    result = ctx.registry.execute(ctx, "scroll", {"amount": 2, "x": 10, "y": 10})
    assert result.ok, result.error
    args, kwargs = mouse["scroll"][0]
    assert args == (2,)
    assert (kwargs["x"], kwargs["y"]) == (120, 70)


def test_scroll_rejects_zero_and_partial_point(ctx, mouse):
    zero = ctx.registry.execute(ctx, "scroll", {"amount": 0})
    assert not zero.ok
    partial = ctx.registry.execute(ctx, "scroll", {"amount": 1, "x": 10})
    assert not partial.ok and partial.error == "bad_arguments"


# -------------------------------------------------------------------- hotkey
def test_hotkey_normalizes_aliases(ctx, mouse):
    result = ctx.registry.execute(ctx, "hotkey", {"keys": ["ctrl", "c"]})
    assert result.ok, result.error
    assert mouse["hotkey"][0][0] == ("ctrl", "c")

    alias = ctx.registry.execute(ctx, "hotkey", {"keys": ["esc"]})
    assert alias.ok, alias.error
    assert mouse["hotkey"][1][0] == ("escape",)
    assert alias.data["keys"] == ["escape"]


def test_hotkey_accepts_plus_separated_string(ctx, mouse):
    result = ctx.registry.execute(ctx, "hotkey", {"keys": "alt+f4"})
    assert result.ok, result.error
    assert mouse["hotkey"][0][0] == ("alt", "f4")


def test_hotkey_unknown_key_reports_allowed_list(ctx, mouse):
    result = ctx.registry.execute(ctx, "hotkey", {"keys": ["ctrl", "nope"]})
    assert not result.ok and result.error == "unknown_key"
    assert "nope" in result.summary
    assert result.data["allowed_keys"]
    assert "ctrl" in result.data["allowed_keys"]
    assert not mouse["hotkey"]


def test_hotkey_requires_non_empty_list(ctx, mouse):
    result = ctx.registry.execute(ctx, "hotkey", {"keys": []})
    assert not result.ok and result.error == "bad_arguments"


# ----------------------------------------------------------------- press_key
def test_press_key_alias_and_repeats(ctx, mouse):
    result = ctx.registry.execute(ctx, "press_key", {"key": "pgup", "presses": 2})
    assert result.ok, result.error
    args, kwargs = mouse["press"][0]
    assert args == ("pageup",)
    assert kwargs["presses"] == 2


def test_press_key_unknown_key_fails(ctx, mouse):
    result = ctx.registry.execute(ctx, "press_key", {"key": "hyper"})
    assert not result.ok and result.error == "unknown_key"
    assert not mouse["press"]


# ----------------------------------------------------------------- type_text
def test_type_text_ascii_uses_write(ctx, mouse):
    result = ctx.registry.execute(ctx, "type_text", {"text": "hello", "interval": 0.0})
    assert result.ok, result.error
    args, kwargs = mouse["write"][0]
    assert args == ("hello",)
    assert kwargs["interval"] == pytest.approx(0.0)
    assert result.data["method"] == "write"


def test_type_text_non_ascii_uses_clipboard(ctx, mouse, monkeypatch):
    import pyperclip

    copied: list[str] = []
    monkeypatch.setattr(pyperclip, "paste", lambda: "старый буфер")
    monkeypatch.setattr(pyperclip, "copy", lambda text: copied.append(text))

    result = ctx.registry.execute(ctx, "type_text", {"text": "привет мир"})
    assert result.ok, result.error
    assert result.data["method"] == "clipboard"
    assert copied[0] == "привет мир"
    assert copied[-1] == "старый буфер"  # буфер восстановлен
    assert mouse["hotkey"][0][0] == ("ctrl", "v")
    assert not mouse["write"]


def test_type_text_rejects_empty(ctx, mouse):
    result = ctx.registry.execute(ctx, "type_text", {"text": ""})
    assert not result.ok and result.error == "bad_arguments"
    assert not mouse["write"]


# ------------------------------------------------------------------- dry-run
def test_dry_run_click_does_not_touch_mouse(ctx, mouse):
    ctx.dry_run = True
    result = ctx.registry.execute(ctx, "click", {"x": 5, "y": 5})
    assert result.ok and result.data.get("dry_run") is True
    assert not mouse["click"]


def test_screenshot_cache_reuses_last_capture(ctx, mouse, screen):
    ctx.registry.execute(ctx, "click", {"x": 1, "y": 1})
    ctx.registry.execute(ctx, "click", {"x": 2, "y": 2})
    ctx.registry.execute(ctx, "move_mouse", {"x": 3, "y": 3})
    assert screen.captures == 1
