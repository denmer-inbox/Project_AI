"""Тесты окон и процессов.

Реальные окна создаются отдельным процессом Tk: его можно активировать,
перемещать, сворачивать и закрывать, не мешая рабочему столу пользователя.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from pcagent.config import AppConfig
from pcagent.events import EventBus
from pcagent.interfaces import MonitorInfo, Risk, Screenshot
from pcagent.safety import Policy
from pcagent.tools.base import ToolContext, ToolRegistry

import pcagent.windows_apps as windows_apps

CHILD_SCRIPT = (
    "import sys\n"
    "import tkinter as tk\n"
    "root = tk.Tk()\n"
    "root.title(sys.argv[1])\n"
    "root.geometry('320x220+140+140')\n"
    "root.mainloop()\n"
)

EXPECTED_TOOLS = {
    "list_windows",
    "focus_window",
    "minimize_window",
    "maximize_window",
    "restore_window",
    "close_window",
    "move_window",
    "wait_for_window",
    "launch_app",
    "kill_process",
    "list_processes",
}


class FakeScreen:
    """Сервис экрана без реального захвата (scale 0.5, смещение 100/50)."""

    def __init__(self) -> None:
        self.shot = Screenshot(
            image_bytes=b"",
            width=1280,
            height=720,
            scale=0.5,
            origin_left=100,
            origin_top=50,
            real_width=2560,
            real_height=1440,
        )

    def monitors(self):
        return [MonitorInfo(0, 0, 0, 2560, 1440, True)]

    def capture(self, monitor=None, max_width=None, fmt=None, quality=None):
        return self.shot

    def size(self, monitor=None):
        return (2560, 1440)

    def uia_tree(self, max_nodes=None):
        return ""

    def active_window(self):
        return None

    def close(self):
        pass


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    windows_apps.register(reg)
    return reg


@pytest.fixture()
def ctx(config, bus, registry) -> ToolContext:
    return ToolContext(
        config=config,
        screen=FakeScreen(),
        policy=Policy("never", assume_yes=True),
        bus=bus,
        registry=registry,
    )


@pytest.fixture()
def child_window():
    """Отдельный процесс с окном Tk; гарантированно закрывается после теста."""
    title = f"PCAGENT_TEST_WINDOW_{os.getpid()}_{int(time.time() * 1000) % 100000}"
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD_SCRIPT, title],
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    try:
        yield title, child
    finally:
        if child.poll() is None:
            child.kill()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


# --------------------------------------------------------------- регистрация
def test_windows_tools_are_registered(registry):
    assert set(registry.names()) == EXPECTED_TOOLS
    assert registry.categories() == ["windows"]


def test_windows_declarations_and_risks(registry):
    risk_map = {
        "list_windows": Risk.READ,
        "list_processes": Risk.READ,
        "wait_for_window": Risk.READ,
        "focus_window": Risk.WRITE,
        "minimize_window": Risk.WRITE,
        "maximize_window": Risk.WRITE,
        "restore_window": Risk.WRITE,
        "move_window": Risk.WRITE,
        "launch_app": Risk.WRITE,
        "close_window": Risk.DESTRUCTIVE,
        "kill_process": Risk.DESTRUCTIVE,
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
        assert registry.get(name).category == "windows"


# --------------------------------------------------------------- list_windows
def test_list_windows_returns_valid_items(ctx):
    result = ctx.registry.execute(ctx, "list_windows", {"limit": 5})
    assert result.ok, result.error
    assert result.data["total"] >= 0
    assert len(result.data["windows"]) <= 5
    for window in result.data["windows"]:
        assert isinstance(window["hwnd"], int) and window["hwnd"] > 0
        assert window["title"]
        assert isinstance(window["pid"], int)
        assert set(window["rect"]) == {"left", "top", "width", "height"}
        assert window["rect"]["width"] > 0 and window["rect"]["height"] > 0
        assert "minimized" in window and "maximized" in window


def test_list_windows_title_filter_returns_empty_for_unknown(ctx):
    result = ctx.registry.execute(ctx, "list_windows", {"title_filter": "zzz-no-such-window-zzz"})
    assert result.ok, result.error
    assert result.data["total"] == 0
    assert result.data["windows"] == []


def test_find_windows_prefers_exact_title(monkeypatch):
    fake = [
        {"hwnd": 2, "title": "Notepad++ - file.txt", "pid": 20},
        {"hwnd": 1, "title": "Notepad", "pid": 10},
        {"hwnd": 3, "title": "Something else", "pid": 30},
    ]
    monkeypatch.setattr(windows_apps, "_iter_windows", lambda: fake)
    matches = windows_apps._find_windows("notepad")
    assert [item["hwnd"] for item in matches] == [1, 2]
    assert windows_apps._find_windows("missing") == []


# --------------------------------------------------------- окно отдельного Tk
def test_window_lifecycle_in_child_process(ctx, child_window):
    title, child = child_window
    waited = ctx.registry.execute(ctx, "wait_for_window", {"title": title, "timeout": 20})
    assert waited.ok, waited.error
    window_pid = waited.data["window"]["pid"]
    assert window_pid > 0
    assert window_pid != os.getpid()

    listed = ctx.registry.execute(ctx, "list_windows", {"title_filter": title})
    assert listed.ok, listed.error
    assert listed.data["total"] == 1
    assert listed.data["windows"][0]["pid"] == window_pid

    focused = ctx.registry.execute(ctx, "focus_window", {"title": title})
    assert focused.ok, focused.error

    # x/y/width/height заданы в пикселях снимка: scale 0.5, смещение 100/50.
    moved = ctx.registry.execute(
        ctx,
        "move_window",
        {"title": title, "x": 40, "y": 40, "width": 300, "height": 200},
    )
    assert moved.ok, moved.error
    assert moved.data["applied"], moved.data
    assert moved.data["actual"]["left"] == pytest.approx(180, abs=8)
    assert moved.data["actual"]["top"] == pytest.approx(130, abs=8)
    assert moved.data["actual"]["width"] == pytest.approx(600, abs=8)
    assert moved.data["actual"]["height"] == pytest.approx(400, abs=8)

    minimized = ctx.registry.execute(ctx, "minimize_window", {"title": title})
    assert minimized.ok, minimized.error
    assert minimized.data["state"]["minimized"] is True

    restored = ctx.registry.execute(ctx, "restore_window", {"title": title})
    assert restored.ok, restored.error
    assert restored.data["state"]["minimized"] is False

    maximized = ctx.registry.execute(ctx, "maximize_window", {"title": title})
    assert maximized.ok, maximized.error
    assert maximized.data["state"]["maximized"] is True

    assert ctx.registry.execute(ctx, "restore_window", {"title": title}).ok

    closed = ctx.registry.execute(ctx, "close_window", {"title": title, "timeout": 10})
    assert closed.ok, closed.error
    assert closed.data["closed"] is True
    assert child.wait(timeout=10) is not None


def test_move_window_requires_geometry(ctx, child_window):
    title, _child = child_window
    waited = ctx.registry.execute(ctx, "wait_for_window", {"title": title, "timeout": 20})
    assert waited.ok, waited.error
    result = ctx.registry.execute(ctx, "move_window", {"title": title})
    assert not result.ok and result.error == "bad_arguments"


def test_move_window_without_screen_fails(config, bus, registry, child_window):
    title, _child = child_window
    ctx = ToolContext(config=config, screen=None, policy=Policy("never", assume_yes=True), bus=bus, registry=registry)
    assert ctx.registry.execute(ctx, "wait_for_window", {"title": title, "timeout": 20}).ok
    result = ctx.registry.execute(ctx, "move_window", {"title": title, "x": 1, "y": 1})
    assert not result.ok and result.error == "screen_unavailable"


# ------------------------------------------------------------- ошибки поиска
def test_unknown_window_operations_fail(ctx):
    for tool, args in (
        ("focus_window", {"title": "zzz-no-such-window-zzz"}),
        ("minimize_window", {"title": "zzz-no-such-window-zzz"}),
        ("maximize_window", {"title": "zzz-no-such-window-zzz"}),
        ("restore_window", {"title": "zzz-no-such-window-zzz"}),
        ("close_window", {"title": "zzz-no-such-window-zzz"}),
        ("move_window", {"title": "zzz-no-such-window-zzz", "x": 1, "y": 1}),
        ("focus_window", {"hwnd": 987654321}),
    ):
        result = ctx.registry.execute(ctx, tool, args)
        assert not result.ok, tool
        assert result.error == "window_not_found", (tool, result.error)


def test_focus_window_requires_title_or_hwnd(ctx):
    result = ctx.registry.execute(ctx, "focus_window", {})
    assert not result.ok and result.error == "bad_arguments"


def test_wait_for_window_times_out(ctx):
    started = time.monotonic()
    result = ctx.registry.execute(
        ctx,
        "wait_for_window",
        {"title": "zzz-no-such-window-zzz", "timeout": 0.5},
    )
    elapsed = time.monotonic() - started
    assert not result.ok and result.error == "window_timeout"
    assert elapsed >= 0.45


# --------------------------------------------------------------- launch_app
def test_launch_app_rejects_missing_target(ctx):
    result = ctx.registry.execute(ctx, "launch_app", {"target": ""})
    assert not result.ok and result.error == "bad_arguments"


def test_launch_app_rejects_bad_path(ctx):
    result = ctx.registry.execute(ctx, "launch_app", {"target": "C:\\zzz-no-such-dir\\zzz.exe"})
    assert not result.ok
    assert (result.error or "").startswith("launch_failed")


# --------------------------------------------------------------- kill_process
def test_kill_process_protects_critical_processes(ctx):
    for args in ({"name": "csrss.exe"}, {"name": "lsass.exe"}, {"pid": 4}, {"pid": os.getpid()}):
        result = ctx.registry.execute(ctx, "kill_process", args)
        assert not result.ok, args
        assert result.error == "protected_process", (args, result.error)


def test_kill_process_unknown_target(ctx):
    missing_pid = ctx.registry.execute(ctx, "kill_process", {"pid": 999999})
    assert not missing_pid.ok and missing_pid.error == "process_not_found"
    missing_name = ctx.registry.execute(ctx, "kill_process", {"name": "zzz-no-such-process.exe"})
    assert not missing_name.ok and missing_name.error == "process_not_found"
    no_target = ctx.registry.execute(ctx, "kill_process", {})
    assert not no_target.ok and no_target.error == "bad_arguments"


def test_kill_process_access_denied_is_reported(ctx, monkeypatch):
    import psutil

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    try:
        proc = psutil.Process(child.pid)

        def deny() -> None:
            raise psutil.AccessDenied(pid=child.pid)

        monkeypatch.setattr(proc, "terminate", deny)

        class PsutilShim:
            NoSuchProcess = psutil.NoSuchProcess
            AccessDenied = psutil.AccessDenied
            TimeoutExpired = psutil.TimeoutExpired

            @staticmethod
            def Process(pid: int):
                return proc

        monkeypatch.setattr(windows_apps, "_psutil", lambda: PsutilShim)
        result = ctx.registry.execute(ctx, "kill_process", {"pid": child.pid})
        assert not result.ok and result.error == "access_denied"
        assert child.poll() is None
    finally:
        child.kill()
        child.wait(timeout=10)


def test_launch_and_kill_own_child_process(ctx):
    import psutil

    launched = ctx.registry.execute(
        ctx,
        "launch_app",
        {"target": sys.executable, "args": ["-c", "import time; time.sleep(30)"]},
    )
    assert launched.ok, launched.error
    pid = launched.data["pid"]
    try:
        assert psutil.pid_exists(pid)
        killed = ctx.registry.execute(ctx, "kill_process", {"pid": pid, "timeout": 5})
        assert killed.ok, killed.error
        deadline = time.time() + 5
        while time.time() < deadline and psutil.pid_exists(pid):
            time.sleep(0.1)
        assert not psutil.pid_exists(pid)
    finally:
        try:
            if psutil.pid_exists(pid):
                psutil.Process(pid).kill()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------- list_processes
def test_list_processes_returns_sorted_items(ctx):
    result = ctx.registry.execute(ctx, "list_processes", {"limit": 10})
    assert result.ok, result.error
    assert result.data["total"] > 0
    items = result.data["processes"]
    assert 1 <= len(items) <= 10
    for item in items:
        assert isinstance(item["pid"], int)
        assert item["name"]
        assert item["memory_mb"] is None or item["memory_mb"] >= 0
    memory = [item["memory_mb"] or 0.0 for item in items]
    assert memory == sorted(memory, reverse=True)


def test_list_processes_name_filter(ctx):
    result = ctx.registry.execute(ctx, "list_processes", {"name_filter": "python", "limit": 50})
    assert result.ok, result.error
    assert result.data["total"] >= 1
    for item in result.data["processes"]:
        assert "python" in item["name"].lower()
