"""Автообновление баланса в AOS-оверлее.

Баг: таймер тикал, но запрос баланса фактически не уходил — интервал
обновления (60 с) совпадал с TTL свежести баланса (60 с), поэтому тик
считал данные «ещё свежими». Внешне это выглядело так: баланс в AOS
не обновляется сам, а только после ручного «ОБНОВИТЬ» в главном окне.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "agent_manager.py"


def _load():
    spec = importlib.util.spec_from_file_location("agent_manager_aos_timer",
                                                  MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _AfterRoot:
    """Стаб Tk: запоминает запланированные вызовы, time_scale управляет срабатыванием."""

    def __init__(self):
        self.callbacks = []
        self._delay = 0

    def after(self, delay, callback=None):
        self._delay = delay
        self.callbacks.append((delay, callback))
        return "after#%d" % len(self.callbacks)

    def after_cancel(self, _id):
        pass


class _Win:
    def winfo_exists(self):
        return True


class _App:
    def __init__(self):
        self.calls = []

    def request_balance(self, silent=False, force=False, only=None):
        self.calls.append({"silent": silent, "force": force, "only": only})


def _overlay(module, refresh_sec=60):
    overlay = object.__new__(module.AOSOverlay)
    overlay.app = _App()
    overlay.win = _Win()
    overlay._after_id = None
    overlay.settings = {"refresh_sec": refresh_sec, "profiles": ["alpha"]}
    return overlay


def test_timer_tick_forces_balance_request():
    """Тик автообновления обязан запрашивать баланс принудительно.

    Иначе TTL свежести (60 с) съедает запрос при интервале тоже 60 с.
    """
    module = _load()
    overlay = _overlay(module)

    overlay._tick()

    assert len(overlay.app.calls) == 1
    call = overlay.app.calls[0]
    assert call["force"] is True
    assert call["silent"] is True


def test_timer_uses_configured_interval():
    module = _load()
    overlay = _overlay(module, refresh_sec=300)
    root = _AfterRoot()
    overlay.win = type("W", (), {"winfo_exists": lambda self: True,
                                 "after": root.after,
                                 "after_cancel": root.after_cancel})()

    overlay._schedule_refresh(immediate=False)

    assert root.callbacks
    delay, callback = root.callbacks[-1]
    assert delay == 300 * 1000
    assert callback == overlay._tick


def test_interval_is_never_below_minute():
    module = _load()
    overlay = _overlay(module, refresh_sec=5)
    root = _AfterRoot()
    overlay.win = type("W", (), {"winfo_exists": lambda self: True,
                                 "after": root.after,
                                 "after_cancel": root.after_cancel})()

    overlay._schedule_refresh(immediate=False)

    assert root.callbacks[-1][0] == 60 * 1000


def test_restart_timer_requests_immediately():
    module = _load()
    overlay = _overlay(module)
    root = _AfterRoot()
    overlay.win = type("W", (), {"winfo_exists": lambda self: True,
                                 "after": root.after,
                                 "after_cancel": root.after_cancel})()

    overlay.restart_timer()

    assert overlay.app.calls and overlay.app.calls[0]["force"] is True
    assert root.callbacks


def test_schedule_without_immediate_does_not_request():
    module = _load()
    overlay = _overlay(module)
    root = _AfterRoot()
    overlay.win = type("W", (), {"winfo_exists": lambda self: True,
                                 "after": root.after,
                                 "after_cancel": root.after_cancel})()

    overlay._schedule_refresh(immediate=False)

    assert overlay.app.calls == []
