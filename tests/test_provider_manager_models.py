"""Выбор моделей: один клик отмечает одну модель, выбор не теряется.

Регрессия: в `SmartCheck._on_click` бит 0x0008 (на Windows это NumLock)
считался вторым Ctrl, поэтому при включённом NumLock обычный клик уходил в
`toggle_all()` и отмечал все модели. Плюс при повторном открытии профиля
диалог ставил галочки на все `known_models`, включая `disabled`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter")

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "opencode_provider_manager.py"
MODULE_NAME = "opencode_provider_manager"


@pytest.fixture(scope="module")
def manager():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(MODULE_NAME, None)
        raise
    return module


@pytest.fixture(scope="module")
def root(manager):
    try:
        win = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - нет дисплея/Tcl
        pytest.skip("Tk недоступен: %s" % exc)
    win.withdraw()
    try:
        yield win
    finally:
        try:
            win.destroy()
        except Exception:
            pass


class _Owner:
    def __init__(self):
        self.calls = []

    def toggle_all(self, flip=False, want=None):
        self.calls.append((flip, want))


def _event(state):
    return SimpleNamespace(state=state)


def _profile(manager, models=("m1",), known=("m1", "m2", "m3")):
    return {
        "id": "alpha",
        "display_name": "Alpha",
        "coefficient": "",
        "base_url": "https://alpha.example/v1",
        "package": "@ai-sdk/openai-compatible",
        "api_key": "key-alpha",
        "models": list(models),
        "known_models": list(known),
        "model_capabilities": {},
        "extra_settings": {},
        "_raw": {},
    }


class _FakeApp:
    def __init__(self, root):
        self.root = root
        self.profiles = []


def _dialog(manager, root, profile=None):
    app = _FakeApp(root)
    dialog = manager.ProfileDialog(app, profile)
    root.update()
    return dialog


# --- SmartCheck: модификаторы --------------------------------------------


def test_plain_click_with_numlock_bit_does_not_select_all(manager, root):
    owner = _Owner()
    var = tk.BooleanVar(master=root, value=False)
    cb = manager.SmartCheck(root, owner, var, "m1")
    try:
        assert cb._on_click(_event(0x0008)) is None
        assert owner.calls == []
        assert var.get() is False
    finally:
        cb.destroy()


def test_ctrl_click_toggles_all(manager, root):
    owner = _Owner()
    var = tk.BooleanVar(master=root, value=False)
    cb = manager.SmartCheck(root, owner, var, "m1")
    try:
        assert cb._on_click(_event(manager.SmartCheck.CTRL_STATE)) == "break"
        assert owner.calls == [(False, True)]
    finally:
        cb.destroy()


def test_shift_click_flips_visible(manager, root):
    owner = _Owner()
    var = tk.BooleanVar(master=root, value=False)
    cb = manager.SmartCheck(root, owner, var, "m1")
    try:
        assert cb._on_click(_event(manager.SmartCheck.SHIFT_STATE)) == "break"
        assert owner.calls == [(True, None)]
    finally:
        cb.destroy()


# --- диалог профиля -------------------------------------------------------


def test_dialog_checks_only_selected_models(manager, root):
    dialog = _dialog(manager, root, _profile(manager))
    try:
        checked = {mid: var.get() for mid, var in dialog.model_vars.items()}
        assert checked == {"m1": True, "m2": False, "m3": False}
        assert dialog.lbl_selected.cget("text") == "ОТМЕЧЕНО: 1 / 3"
    finally:
        dialog.destroy()


def test_dialog_save_does_not_reenable_disabled_models(manager, root):
    dialog = _dialog(manager, root, _profile(manager))
    try:
        dialog._save()
        assert dialog.result is not None
        assert dialog.result["models"] == ["m1"]
    finally:
        try:
            dialog.destroy()
        except Exception:
            pass


def test_recheck_does_not_reenable_all_after_user_unchecked_everything(manager, root):
    dialog = _dialog(manager, root, _profile(manager))
    try:
        for var in dialog.model_vars.values():
            var.set(False)
        dialog._on_checked([
            {"id": "m1", "display": "m1"},
            {"id": "m2", "display": "m2"},
            {"id": "new", "display": "new"},
        ], None)
        assert all(var.get() is False for var in dialog.model_vars.values())
    finally:
        dialog.destroy()


def test_first_discovery_checks_everything(manager, root):
    dialog = _dialog(manager, root, None)
    try:
        dialog._on_checked([
            {"id": "a", "display": "a"},
            {"id": "b", "display": "b"},
        ], None)
        assert all(var.get() is True for var in dialog.model_vars.values())
    finally:
        dialog.destroy()
