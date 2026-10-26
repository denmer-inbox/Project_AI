"""Команды редактирования при русской раскладке клавиатуры.

Tk сравнивает нажатия по символу клавиши (keysym), а при русской раскладке
Ctrl+C и Ctrl+V приходят с keysym "??". Поэтому привязки вида <Control-c>
не срабатывают, и вставка/копирование молча не работают. Клиент ловит
события по коду клавиши (keycode), который от раскладки не зависит.
"""

from __future__ import annotations

import pytest

from pcagent.gui import paste


class _Event:
    """Минимальная замена событию Tk: код, символ и модификаторы."""

    def __init__(self, keycode: int, keysym: str, state: int = 0) -> None:
        self.keycode = keycode
        self.keysym = keysym
        self.state = state


CTRL = paste.CONTROL_MASK
SHIFT = paste.SHIFT_MASK


# ----------------------------------------------------------- вставка
@pytest.mark.parametrize("keysym", ["v", "??", "м", "М"])
def test_ctrl_v_is_paste_in_any_layout(keysym):
    """Ctrl+V распознаётся и при латинской, и при русской раскладке."""
    assert paste.is_paste_event(_Event(paste.VK_V, keysym, CTRL)) is True


def test_shift_insert_is_paste():
    assert paste.is_paste_event(_Event(paste.VK_INSERT, "Insert", SHIFT)) is True


def test_plain_v_without_ctrl_is_not_paste():
    assert paste.is_paste_event(_Event(paste.VK_V, "v", 0)) is False


def test_ctrl_c_is_not_paste():
    assert paste.is_paste_event(_Event(paste.VK_C, "c", CTRL)) is False


def test_none_event_is_not_paste():
    assert paste.is_paste_event(None) is False


# -------------------------------------------------- команды редактирования
@pytest.mark.parametrize(
    "keycode,expected",
    [
        (paste.VK_C, "copy"),
        (paste.VK_X, "cut"),
        (paste.VK_A, "select_all"),
        (paste.VK_Z, "undo"),
        (paste.VK_Y, "redo"),
    ],
)
def test_shortcut_action_by_keycode(keycode, expected):
    """Действие определяется по коду, поэтому раскладка не важна."""
    assert paste.shortcut_action(_Event(keycode, "??", CTRL)) == expected


@pytest.mark.parametrize("keycode", [paste.VK_C, paste.VK_A, paste.VK_X])
def test_shortcut_requires_ctrl(keycode):
    """Без Ctrl те же клавиши ничего не означают."""
    assert paste.shortcut_action(_Event(keycode, "c", 0)) is None


def test_unknown_key_has_no_action():
    assert paste.shortcut_action(_Event(0x31, "1", CTRL)) is None


def test_none_event_has_no_action():
    assert paste.shortcut_action(None) is None


# ------------------------------------------------------------ привязки
class _FakeWidget:
    def __init__(self) -> None:
        self.bindings: dict[str, object] = {}
        self.generated: list[str] = []

    def bind(self, sequence, handler=None, add=None):
        self.bindings[sequence] = handler
        return handler

    def event_generate(self, virtual: str) -> None:
        self.generated.append(virtual)


def test_bind_paste_uses_keycode_binding():
    widget = _FakeWidget()
    paste.bind_paste(widget, lambda event: "break")
    assert "<Control-KeyPress>" in widget.bindings
    assert "<Shift-Insert>" in widget.bindings
    assert "<<Paste>>" in widget.bindings


def test_bind_edit_shortcuts_generates_virtual_event():
    """Ctrl+A должен вызвать штатное <<SelectAll>>, а не копировать логику."""
    widget = _FakeWidget()
    paste.bind_edit_shortcuts(widget)
    handler = widget.bindings["<Control-KeyPress>"]

    assert handler(_Event(paste.VK_A, "??", CTRL)) == "break"
    assert widget.generated == ["<<SelectAll>>"]


def test_bind_edit_shortcuts_ignores_other_keys():
    widget = _FakeWidget()
    paste.bind_edit_shortcuts(widget)
    handler = widget.bindings["<Control-KeyPress>"]

    assert handler(_Event(0x31, "1", CTRL)) is None
    assert widget.generated == []


def test_copy_generates_copy_event():
    widget = _FakeWidget()
    paste.bind_edit_shortcuts(widget)
    handler = widget.bindings["<Control-KeyPress>"]
    handler(_Event(paste.VK_C, "??", CTRL))
    assert widget.generated == ["<<Copy>>"]


def test_every_shortcut_maps_to_virtual_event():
    for action, (codes, virtual) in paste.EDIT_SHORTCUTS.items():
        assert codes, f"у {action} нет кодов клавиш"
        assert virtual.startswith("<<") and virtual.endswith(">>")