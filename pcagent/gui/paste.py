"""Вставка и команды редактирования при нелатинской раскладке клавиатуры.

Проблема. В Tk привязки вида <Control-v> или <Control-c> сравнивают не
физическую клавишу, а её символ (keysym). При русской раскладке Ctrl+V
даёт keysym "??" вместо "v", и привязка не срабатывает: вставка молча не
работает. То же самое с Ctrl+C, Ctrl+A и Shift+Insert.

Решение. Ловим <Control-KeyPress> и смотрим на КОД клавиши (keycode),
который не зависит от раскладки: V=86, C=67, X=88, A=65, Insert=45.
Для команд редактирования генерируем штатное виртуальное событие Tk
(<<Copy>>, <<Cut>>, <<SelectAll>>), чтобы виджет вёл себя как обычно.
"""

from __future__ import annotations

from typing import Any, Callable

#: Виртуальные коды Windows: одинаковы при любой раскладке.
VK_INSERT = 45
VK_A = 65
VK_C = 67
VK_V = 86
VK_X = 88
VK_Y = 89
VK_Z = 90

#: Маска состояния Shift в событии Tk.
SHIFT_MASK = 0x0001
#: Маска состояния Ctrl в событии Tk.
CONTROL_MASK = 0x0004

#: Клавиши, которыми вставляют из буфера.
PASTE_KEYCODES = (VK_V, VK_INSERT)

#: Символы, которые тоже считаем вставкой (на случай других раскладок).
PASTE_KEYSYMS = ("v", "V", "м", "М", "insert", "Insert")

#: Команды редактирования: действие -> (коды клавиш, виртуальное событие Tk).
EDIT_SHORTCUTS: dict[str, tuple[tuple[int, ...], str]] = {
    "copy": ((VK_C,), "<<Copy>>"),
    "cut": ((VK_X,), "<<Cut>>"),
    "select_all": ((VK_A,), "<<SelectAll>>"),
    "undo": ((VK_Z,), "<<Undo>>"),
    "redo": ((VK_Y,), "<<Redo>>"),
}


def is_paste_event(event: Any) -> bool:
    """Похоже ли событие клавиатуры на команду "вставить из буфера".

    Сравнение идёт по коду клавиши, а не по символу: при русской раскладке
    Ctrl+V приходит с keysym "??", и проверка по символу не срабатывает.
    """
    if event is None:
        return False
    state = int(getattr(event, "state", 0) or 0)
    keycode = getattr(event, "keycode", None)
    keysym = str(getattr(event, "keysym", "") or "")

    # Shift+Insert: модификатор Shift, клавиша Insert.
    if keycode == VK_INSERT and state & SHIFT_MASK:
        return True
    # Ctrl+V: модификатор Ctrl, клавиша V.
    if keycode == VK_V and state & CONTROL_MASK:
        return True
    # Запасной путь: необычная раскладка с другим кодом, но знакомым символом.
    if keysym in PASTE_KEYSYMS and (state & CONTROL_MASK or state & SHIFT_MASK):
        if not isinstance(keycode, int) or keycode not in PASTE_KEYCODES:
            return True
    return False


def shortcut_action(event: Any) -> str | None:
    """Какую команду редактирования означает событие (или None).

    Возвращает "copy", "cut", "select_all", "undo", "redo" или None.
    Как и со вставкой, решение принимается по коду клавиши.
    """
    if event is None:
        return None
    state = int(getattr(event, "state", 0) or 0)
    if not state & CONTROL_MASK:
        return None
    keycode = getattr(event, "keycode", None)
    for action, (codes, _virtual) in EDIT_SHORTCUTS.items():
        if keycode in codes:
            return action
    return None


def bind_paste(widget: Any, handler: Callable[[Any], Any]) -> None:
    """Привязать вставку так, чтобы работала при любой раскладке.

    handler вызывается только для настоящей команды вставки и должен
    вернуть "break", чтобы Tk не вставил текст дважды.
    """

    def on_key(event: Any) -> Any:
        if is_paste_event(event):
            return handler(event)
        return None

    # Ctrl+V в любой раскладке: решение по коду клавиши.
    widget.bind("<Control-KeyPress>", on_key, add="+")
    # Shift+Insert: у него нет Control в состоянии, поэтому отдельная привязка.
    widget.bind("<Shift-Insert>", handler, add="+")
    widget.bind("<Shift-KP_Insert>", handler, add="+")
    # Виртуальное событие Tk: срабатывает, когда раскладка всё же латинская.
    widget.bind("<<Paste>>", handler, add="+")


def bind_edit_shortcuts(widget: Any) -> None:
    """Включить Ctrl+C, Ctrl+X, Ctrl+A, Ctrl+Z при любой раскладке.

    Стандартные привязки Tk сверяют символ клавиши, а при русской
    раскладке Ctrl+C даёт keysym "??". Здесь ловим код клавиши и
    генерируем штатное виртуальное событие, чтобы виджет повёл себя
    ровно так же, как при латинской раскладке.
    """

    def on_key(event: Any) -> Any:
        action = shortcut_action(event)
        if action is None:
            return None
        virtual = EDIT_SHORTCUTS[action][1]
        try:
            widget.event_generate(virtual)
        except Exception:  # noqa: BLE001 - виджет может не поддерживать команду
            return None
        return "break"

    widget.bind("<Control-KeyPress>", on_key, add="+")


__all__ = [
    "CONTROL_MASK",
    "EDIT_SHORTCUTS",
    "PASTE_KEYCODES",
    "PASTE_KEYSYMS",
    "SHIFT_MASK",
    "VK_A",
    "VK_C",
    "VK_INSERT",
    "VK_V",
    "VK_X",
    "VK_Y",
    "VK_Z",
    "bind_edit_shortcuts",
    "bind_paste",
    "is_paste_event",
    "shortcut_action",
]