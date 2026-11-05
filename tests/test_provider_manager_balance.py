"""Баланс профиля: один последовательный поток запросов, сумма не пропадает.

Причины исходного бага:
* `_balance_targets()` отдавал только профили из AOS, поэтому профиль,
  выбранный в главном окне, не запрашивался;
* каждый клик по списку запускал свой поток, шлюз отвечал 429, и баланс
  «то показывался, то нет»;
* при любой ошибке удачный баланс стирался (`_balance = None`).
"""

from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "agent_manager.py"


@pytest.fixture(scope="module")
def manager():
    spec = importlib.util.spec_from_file_location(
        "agent_manager_balance", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile(manager, pid):
    return {
        "id": pid,
        "display_name": pid,
        "base_url": "https://%s.example/v1" % pid,
        "api_key": "key-" + pid,
        "package": manager.PACKAGES[0],
        "models": ["m1"],
        "known_models": ["m1"],
        "extra_settings": {},
        "_raw": {},
    }


class _Label:
    def __init__(self):
        self.text = None
        self.fg = None

    def configure(self, **kw):
        if "text" in kw:
            self.text = kw["text"]
        if "fg" in kw:
            self.fg = kw["fg"]


class _Root:
    """Минимальный Tk-стаб: after() вызывает колбэк сразу, без mainloop."""

    def __init__(self):
        self.pending = []

    def after(self, delay, callback=None):
        self.pending.append(callback)
        return len(self.pending)

    def drain(self, limit=200):
        for _ in range(limit):
            if not self.pending:
                return
            callback = self.pending.pop(0)
            if callback:
                callback()


def _app(manager, profiles, selected):
    app = object.__new__(manager.App)
    app.root = _Root()
    app.selected = selected
    app.profiles = profiles

    class FakeAOS:
        def _visible_profiles(self):
            return [p for p in profiles if p["id"] == "alpha"]

    app.aos = FakeAOS()
    app.lbl_balance_main = _Label()
    app.lbl_balance_when = _Label()
    app.lbl_balance_est_main = _Label()
    app.btn_balance_main = _Label()
    app._refresh_dirty_marker = lambda: None
    app._log_balance_error = lambda text: None
    app._balance_results = None
    return app


def test_selected_profile_is_included_even_if_not_in_aos(manager):
    app = _app(manager, [_profile(manager, "alpha"), _profile(manager, "beta")],
               "beta")
    ids = [p["id"] for p in app._balance_targets()]
    assert "beta" in ids
    assert "alpha" in ids


def test_balance_targets_are_unique(manager):
    app = _app(manager, [_profile(manager, "alpha"), _profile(manager, "beta")],
               "alpha")
    ids = [p["id"] for p in app._balance_targets()]
    assert ids.count("alpha") == 1


def test_only_uses_given_profiles(manager):
    profiles = [_profile(manager, "alpha"), _profile(manager, "beta")]
    app = _app(manager, profiles, "alpha")
    assert app._balance_targets([profiles[1]]) == [profiles[1]]


def test_many_requests_go_one_at_a_time(manager, monkeypatch):
    """Десять кликов подряд не должны порождать параллельные запросы."""
    state = {"inflight": 0, "peak": 0, "calls": 0}
    lock = threading.Lock()

    def fake_fetch(base_url, api_key, *a, **k):
        with lock:
            state["inflight"] += 1
            state["calls"] += 1
            state["peak"] = max(state["peak"], state["inflight"])
        time.sleep(0.02)
        with lock:
            state["inflight"] -= 1
        return {"text": "1000", "tokens": 1000, "url": base_url}

    monkeypatch.setattr(manager, "fetch_balance", fake_fetch)
    profiles = [_profile(manager, "alpha"), _profile(manager, "beta")]
    app = _app(manager, profiles, "beta")

    for _ in range(10):
        app.request_balance(silent=True)

    deadline = time.time() + 10
    while time.time() < deadline:
        app.root.drain()
        if not getattr(app, "_balance_busy", False):
            break
        time.sleep(0.02)

    assert state["peak"] == 1
    assert state["calls"] == 2      # по одному на профиль, без дублей
    assert profiles[0]["_balance"]["text"] == "1000"
    assert profiles[1]["_balance"]["text"] == "1000"


def test_failed_refresh_keeps_last_balance_and_turns_red(manager, monkeypatch):
    monkeypatch.setattr(manager, "fetch_balance",
                        lambda *a, **k: {"text": "500 токенов", "tokens": 500,
                                         "url": "u"})
    profiles = [_profile(manager, "alpha"), _profile(manager, "beta")]
    app = _app(manager, profiles, "beta")

    app.request_balance(silent=True, only=[profiles[1]])
    app.root.drain()
    deadline = time.time() + 10
    while time.time() < deadline and getattr(app, "_balance_busy", False):
        time.sleep(0.01)
        app.root.drain()

    assert app.lbl_balance_main.text == "500 токенов"
    assert app.lbl_balance_main.fg == manager.T.green

    def boom(*a, **k):
        raise RuntimeError("Рейт-лимит 429")

    monkeypatch.setattr(manager, "fetch_balance", boom)
    app.request_balance(silent=True, force=True, only=[profiles[1]])
    deadline = time.time() + 10
    while time.time() < deadline and getattr(app, "_balance_busy", False):
        time.sleep(0.01)
        app.root.drain()

    # сумма осталась, но строка красная
    assert app.lbl_balance_main.text == "500 токенов"
    assert app.lbl_balance_main.fg == manager.T.red
    assert "429" in (profiles[1].get("_balance_error") or "")


def test_success_after_error_turns_green_again(manager, monkeypatch):
    profiles = [_profile(manager, "alpha"), _profile(manager, "beta")]
    app = _app(manager, profiles, "beta")
    profiles[1]["_balance"] = {"text": "777", "tokens": 777, "url": "u"}
    profiles[1]["_balance_error"] = "Рейт-лимит 429"
    app._show_balance(profiles[1])
    assert app.lbl_balance_main.fg == manager.T.red

    monkeypatch.setattr(manager, "fetch_balance",
                        lambda *a, **k: {"text": "888", "tokens": 888, "url": "u"})
    app.request_balance(silent=True, force=True, only=[profiles[1]])
    deadline = time.time() + 10
    while time.time() < deadline and getattr(app, "_balance_busy", False):
        time.sleep(0.01)
        app.root.drain()

    assert app.lbl_balance_main.text == "888"
    assert app.lbl_balance_main.fg == manager.T.green
    assert profiles[1].get("_balance_error") is None


def test_fresh_balance_is_not_requested_again(manager, monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "fetch_balance",
                        lambda *a, **k: calls.append(1) or {"text": "1",
                                                            "tokens": 1, "url": "u"})
    profiles = [_profile(manager, "alpha"), _profile(manager, "beta")]
    from datetime import datetime
    profiles[1]["_balance"] = {"text": "1", "tokens": 1, "url": "u"}
    profiles[1]["_balance_at"] = datetime.now()
    app = _app(manager, profiles, "beta")

    app.request_balance(silent=True, only=[profiles[1]])

    assert calls == []
