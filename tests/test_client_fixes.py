"""Исправления по итогам реального прогона клиента на STEP 7.

Прогон показал три дефекта, каждый закрыт отдельным тестом:
  * модель обходила инструменты ввода через run_script с mouse_event;
  * агент свернул собственное окно и ослеп;
  * бюджет снимков не масштабировался под длину задачи.
"""

from __future__ import annotations

import pytest

from pcagent import safety
from pcagent.gui import screen_policy


# ------------------------------------------- обход инструментов ввода
@pytest.mark.parametrize(
    "script",
    [
        "import ctypes; ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)",
        "u.SetCursorPos(898, 525)",
        "user32.keybd_event(0x12, 0, 0, 0)",
        "[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')",
        "import pyautogui; pyautogui.click(10, 10)",
        "from pynput.mouse import Controller",
        "SendInput(1, ...)",
    ],
)
def test_detects_input_emulation(script):
    assert safety.detect_input_emulation(script), f"не поймал: {script}"


@pytest.mark.parametrize(
    "script",
    [
        "Get-Process | Select-Object Name",
        "Get-ChildItem C:\\Windows | Measure-Object",
        "import os; print(os.getcwd())",
        "Start-Process notepad.exe",
        "",
    ],
)
def test_allows_normal_scripts(script):
    assert safety.detect_input_emulation(script) is None


def test_run_script_refuses_input_emulation():
    from pcagent.config import AppConfig
    from pcagent.events import EventBus
    from pcagent.gui.console_tools import _tool_run_script
    from pcagent.safety import Policy
    from pcagent.tools.base import ToolContext, build_default_registry

    config = AppConfig(confirm_mode="never", allow_shell=True)
    registry = build_default_registry()
    context = ToolContext(
        config=config,
        screen=None,
        policy=Policy("never", assume_yes=True),
        bus=EventBus(),
        registry=registry,
    )
    result = _tool_run_script(
        context,
        {"script": "import ctypes; ctypes.windll.user32.SetCursorPos(10, 10)", "language": "python"},
    )
    assert result.ok is False
    assert result.error == "input_emulation_blocked"
    # Подсказка должна называть штатные инструменты.
    assert "click" in result.summary


def test_run_command_refuses_input_emulation():
    from pcagent.config import AppConfig
    from pcagent.events import EventBus
    from pcagent.safety import Policy
    from pcagent.system_ops import _tool_run_command
    from pcagent.tools.base import ToolContext, build_default_registry

    config = AppConfig(confirm_mode="never", allow_shell=True)
    registry = build_default_registry()
    context = ToolContext(
        config=config,
        screen=None,
        policy=Policy("never", assume_yes=True),
        bus=EventBus(),
        registry=registry,
    )
    result = _tool_run_command(
        context, {"command": "[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')"}
    )
    assert result.ok is False
    assert result.error == "input_emulation_blocked"


# ------------------------------------------------- своё окно клиента
def test_is_own_window_compares_pid(monkeypatch):
    """Окно считается своим, когда его PID совпадает с нашим."""
    import os

    from pcagent import windows_apps

    class _Process:
        def __init__(self, pid):
            self.pid = pid

        def GetWindowThreadProcessId(self, _hwnd):
            return (1, self.pid)

    def fake_win32(pid):
        return (object(), object(), _Process(pid))

    monkeypatch.setattr(windows_apps, "_win32", lambda: fake_win32(os.getpid()))
    assert windows_apps._is_own_window(123) is True

    monkeypatch.setattr(windows_apps, "_win32", lambda: fake_win32(os.getpid() + 1))
    assert windows_apps._is_own_window(123) is False


def test_is_own_window_survives_failures(monkeypatch):
    """Если PID определить нельзя, окно не блокируется."""
    from pcagent import windows_apps

    def boom():
        raise RuntimeError("win32 недоступен")

    monkeypatch.setattr(windows_apps, "_win32", boom)
    assert windows_apps._is_own_window(0) is False


def _context():
    from pcagent.config import AppConfig
    from pcagent.events import EventBus
    from pcagent.safety import Policy
    from pcagent.tools.base import ToolContext, build_default_registry

    return ToolContext(
        config=AppConfig(confirm_mode="never"),
        screen=None,
        policy=Policy("never", assume_yes=True),
        bus=EventBus(),
        registry=build_default_registry(),
    )


def test_minimize_own_window_is_blocked(monkeypatch):
    """Свернуть окно собственного процесса агент не должен."""
    from pcagent import windows_apps

    monkeypatch.setattr(
        windows_apps, "_resolve_window", lambda args: (999, {"title": "PC Agent", "pid": 1}, None)
    )
    monkeypatch.setattr(windows_apps, "_is_own_window", lambda hwnd: True)

    result = windows_apps._tool_minimize_window(_context(), {"title": "PC Agent"})
    assert result.ok is False
    assert result.error == "own_window_blocked"
    assert "ослепнет" in result.summary or "перестанет видеть" in result.summary


def test_close_own_window_is_blocked(monkeypatch):
    from pcagent import windows_apps

    monkeypatch.setattr(
        windows_apps, "_resolve_window", lambda args: (999, {"title": "PC Agent", "pid": 1}, None)
    )
    monkeypatch.setattr(windows_apps, "_is_own_window", lambda hwnd: True)

    result = windows_apps._tool_close_window(_context(), {"title": "PC Agent"})
    assert result.ok is False
    assert result.error == "own_window_blocked"


def test_restore_own_window_is_allowed(monkeypatch):
    """Восстановить своё окно можно: это возвращает агенту экран."""
    from pcagent import windows_apps

    monkeypatch.setattr(
        windows_apps, "_resolve_window", lambda args: (999, {"title": "PC Agent", "pid": 1}, None)
    )
    monkeypatch.setattr(windows_apps, "_is_own_window", lambda hwnd: True)
    # Дальше пойдёт обращение к win32: подменяем, чтобы не трогать реальное окно.
    monkeypatch.setattr(
        windows_apps,
        "_win32",
        lambda: (
            type("G", (), {"ShowWindow": staticmethod(lambda h, c: None)}),
            type("C", (), {"SW_RESTORE": 9, "SW_MINIMIZE": 6, "SW_MAXIMIZE": 3}),
            object(),
        ),
    )
    monkeypatch.setattr(
        windows_apps,
        "_window_state",
        lambda hwnd: {"minimized": False, "maximized": False, "visible": True},
    )
    result = windows_apps._tool_restore_window(_context(), {"title": "PC Agent"})
    assert result.ok is True


# ------------------------------------------------- бюджет снимков
@pytest.mark.parametrize(
    "steps,expected",
    [
        (4, 6),      # короткая задача: минимум
        (24, 6),
        (60, 15),    # реальный прогон: было 4, стало 15
        (120, 30),
        (400, 40),   # верхняя граница
    ],
)
def test_budget_scales_with_task_length(steps, expected):
    assert screen_policy.budget_for_steps(steps) == expected


def test_budget_handles_garbage():
    assert screen_policy.budget_for_steps("много") == 7
    assert screen_policy.budget_for_steps(None) == 7


def test_budget_gate_uses_scaled_value():
    from pcagent.gui.screen_policy import SmartScreenGate

    class _Inner:
        def capture(self, **kwargs):
            raise RuntimeError("не вызывается")

    gate = SmartScreenGate(_Inner(), extra={"screenshot_max_per_task": screen_policy.budget_for_steps(60)})
    assert gate.budget.max_per_task == 15
