"""Ctrl+V / Ctrl+C / Ctrl+X / Ctrl+A в менеджере провайдеров — при любой раскладке.

Причина бага: Tk на Windows сравнивает не код клавиши, а её символ (keysym).
При русской раскладке Ctrl+V приходит с keysym «м» (Cyrillic_em), поэтому
привязки вида <Control-v> и виртуальное событие <<Paste>> молчат — вставка
«молча» не работала. Менеджер теперь распознаёт сочетание по коду клавиши
(он не зависит от раскладки) и выполняет действие штатным виртуальным
событием Tk (<<Paste>>, <<Copy>>, <<Cut>>, <<SelectAll>>).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "opencode_provider_manager.py"


@pytest.fixture(scope="module")
def manager():
    spec = importlib.util.spec_from_file_location(
        "opencode_provider_manager_paste", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def clipboard(manager):
    """Один Tk-интерпретатор на модуль: повторный Tk() нестабилен."""
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - нет дисплея/Tcl
        pytest.skip(f"Tk недоступен: {exc}")
    root.withdraw()
    menu = manager.install_clipboard(root)
    try:
        yield root, menu
    finally:
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture()
def fields(clipboard):
    """Свежие поля ввода: ttk.Entry, tk.Entry и tk.Text."""
    root, menu = clipboard
    created = [ttk.Entry(root), tk.Entry(root), tk.Text(root, height=2)]
    try:
        yield menu, created
    finally:
        for widget in created:
            try:
                widget.destroy()
            except Exception:  # noqa: BLE001
                pass


def _event(**kwargs):
    base = {"state": 0, "keycode": 0, "keysym": "", "widget": None}
    base.update(kwargs)
    return SimpleNamespace(**base)


def _set_clipboard(root, text):
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


def _value(widget):
    if widget.winfo_class() == "Text":
        return widget.get("1.0", "end-1c")
    return widget.get()


# --------------------------------------------------------------- распознавание

def test_shortcut_is_detected_by_keycode(manager):
    """Сочетание узнаётся по коду клавиши: он одинаков при любой раскладке."""
    ctrl = manager.CONTROL_STATE
    assert manager.shortcut_action(_event(state=ctrl, keycode=manager.VK_V)) == "paste"
    assert manager.shortcut_action(_event(state=ctrl, keycode=manager.VK_C)) == "copy"
    assert manager.shortcut_action(_event(state=ctrl, keycode=manager.VK_X)) == "cut"
    assert manager.shortcut_action(_event(state=ctrl, keycode=manager.VK_A)) == "select_all"
    # Ctrl+Insert — второе имя копирования (Shift+Insert Tk обрабатывает сам).
    assert manager.shortcut_action(_event(state=ctrl, keycode=manager.VK_INSERT)) == "copy"


def test_shortcut_is_rejected_without_ctrl(manager):
    assert manager.shortcut_action(_event(state=0, keycode=manager.VK_V)) is None
    assert manager.shortcut_action(_event(state=0, keycode=manager.VK_A)) is None
    assert manager.shortcut_action(_event(state=manager.CONTROL_STATE, keycode=0x31)) is None
    assert manager.shortcut_action(None) is None


def test_event_helpers_tolerate_broken_events(manager):
    """У событий Tk поля всегда есть, но обработчики не должны падать."""
    broken = SimpleNamespace(state=None, keycode="?", keysym=None)
    assert manager.event_state(broken) == 0
    assert manager.event_keycode(broken) == 0
    assert manager.event_keysym(broken) == ""


# ------------------------------------------------------------- установка привязок

def test_control_keys_are_bound_for_every_input_class(clipboard):
    root, _menu = clipboard
    for klass in ("TEntry", "TCombobox", "TSpinbox", "Entry", "Spinbox", "Text"):
        assert root.bind_class(klass, "<Control-KeyPress>"), klass


def test_tk_native_paste_mapping_is_kept(clipboard):
    """Латинскую раскладку по-прежнему обрабатывает сам Tk — без дублей."""
    root, _menu = clipboard
    assert "<Control-Key-v>" in root.tk.call("event", "info", "<<Paste>>")


def test_bind_tree_binds_fields_created_later(manager, clipboard):
    """Поля, появившиеся после установки (диалог профиля), тоже получают привязку."""
    root, menu = clipboard
    frame = tk.Frame(root)
    entry = ttk.Entry(frame)
    entry.pack()
    try:
        menu.bind_tree(frame)
        assert entry.bind("<Control-KeyPress>")
    finally:
        frame.destroy()


# ------------------------------------------------------------------- вставка

def test_ctrl_v_works_with_russian_keysym(manager, clipboard, fields):
    """Русская раскладка: Ctrl+V приходит с keysym «м», вставка должна работать."""
    root, _menu = clipboard
    menu, widgets = fields
    entry = widgets[0]  # ttk.Entry — у него штатная вставка не требует окна на экране
    _set_clipboard(root, "КЛЮЧ-ПРОВАЙДЕРА-42")

    event = _event(state=manager.CONTROL_STATE, keycode=manager.VK_V,
                   keysym="м", widget=entry)
    assert menu.on_control_key(event) == "break"
    root.update()
    assert _value(entry) == "КЛЮЧ-ПРОВАЙДЕРА-42"


@pytest.mark.parametrize("kind", [1, 2])
def test_russian_keysym_uses_native_virtual_event(manager, clipboard, fields, kind, monkeypatch):
    """tk.Entry и tk.Text получают штатное виртуальное событие <<Paste>>."""
    _root, menu = clipboard
    widgets = fields[1]
    widget = widgets[kind]
    generated = []
    monkeypatch.setattr(widget, "event_generate", lambda seq: generated.append(seq))

    event = _event(state=manager.CONTROL_STATE, keycode=manager.VK_V,
                   keysym="м", widget=widget)
    assert menu.on_control_key(event) == "break"
    assert generated == ["<<Paste>>"]


def test_latin_keysym_is_left_to_tk(manager, clipboard, fields):
    """При латинской раскладке свой обработчик не вмешивается (Tk вставит сам)."""
    _root, menu = clipboard
    widgets = fields[1]
    event = _event(state=manager.CONTROL_STATE, keycode=manager.VK_V,
                   keysym="v", widget=widgets[1])
    assert menu.on_control_key(event) is None
    assert _value(widgets[1]) == ""


def test_unknown_keysym_does_not_break_typing(manager, clipboard, fields):
    _root, menu = clipboard
    widgets = fields[1]
    event = _event(state=0, keycode=manager.VK_V, keysym="м", widget=widgets[1])
    assert menu.on_control_key(event) is None


# ------------------------------------------------- копирование / вырезание / всё

def test_ctrl_a_and_ctrl_c_with_russian_keysym(manager, clipboard, fields):
    root, _menu = clipboard
    menu, widgets = fields
    entry = widgets[0]  # ttk.Entry
    entry.insert(0, "ВЫДЕЛИ-МЕНЯ")
    _set_clipboard(root, "")

    menu.on_control_key(_event(state=manager.CONTROL_STATE, keycode=manager.VK_A,
                               keysym="ф", widget=entry))
    root.update()
    menu.on_control_key(_event(state=manager.CONTROL_STATE, keycode=manager.VK_C,
                               keysym="с", widget=entry))
    root.update()
    assert root.clipboard_get() == "ВЫДЕЛИ-МЕНЯ"


def test_ctrl_x_with_russian_keysym(manager, clipboard, fields):
    root, _menu = clipboard
    menu, widgets = fields
    entry = widgets[0]  # ttk.Entry
    entry.insert(0, "ВЫРЕЖЬ-МЕНЯ")
    _set_clipboard(root, "")

    menu.on_control_key(_event(state=manager.CONTROL_STATE, keycode=manager.VK_A,
                               keysym="ф", widget=entry))
    root.update()
    menu.on_control_key(_event(state=manager.CONTROL_STATE, keycode=manager.VK_X,
                               keysym="ч", widget=entry))
    root.update()
    assert entry.get() == ""
    assert root.clipboard_get() == "ВЫРЕЖЬ-МЕНЯ"


# ------------------------------------------------------- диалог профиля целиком

def test_profile_dialog_fields_paste_with_russian_keysym(manager, clipboard):
    """Тот самый сценарий из отчёта: вставка в поля «ПРОФИЛЬ ПРОВАЙДЕРА»."""
    root, menu = clipboard

    class FakeApp:
        pass

    app = FakeApp()
    app.root = root
    app.clipboard = menu
    dialog = manager.ProfileDialog(app, None)
    try:
        root.update()
        _set_clipboard(root, "sk-live-key-777")
        event = _event(state=manager.CONTROL_STATE, keycode=manager.VK_V,
                       keysym="м", widget=dialog.e_key)
        assert menu.on_control_key(event) == "break"
        root.update()
        assert dialog.e_key.get() == "sk-live-key-777"
        assert dialog.var_key.get() == "sk-live-key-777"
    finally:
        try:
            dialog.destroy()
        except Exception:  # noqa: BLE001
            pass
