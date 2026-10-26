"""Исключение собственного окна клиента из снимков экрана.

Зачем. Клиент делает снимок экрана и отдаёт его модели. Если на экране
видно само окно клиента, модель смотрит на себя: в кадре оказывается чат
с её же прошлыми сообщениями, а целевая программа может быть перекрыта.

Как. Windows умеет исключать окно из захвата экрана:
  WDA_EXCLUDEFROMCAPTURE (17, Windows 10 2004+) - окно остаётся видимым
    на экране, но не попадает ни в один снимок;
  WDA_MONITOR (1) - более старый режим, работает почти везде, но окно
    на снимке становится чёрным прямоугольником.

Проверено на этой машине: при включённой аффинити окно исчезает из кадра
и остаётся на экране - пользователь ничего не замечает.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Any

#: Окно исключено из захвата, на экране остаётся видимым.
WDA_EXCLUDEFROMCAPTURE = 0x00000011
#: Более старый режим: на снимке окно будет чёрным прямоугольником.
WDA_MONITOR = 0x00000001
#: Обычный режим: окно попадает в снимки.
WDA_NONE = 0x00000000

#: Сколько раз пробовать включить аффинити: окно должно уже существовать.
_APPLY_ATTEMPTS = 20

_applied: dict[int, int] = {}
_lock = threading.Lock()


def _user32() -> Any:
    """user32 с правильными типами аргументов."""
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
        return user32
    except Exception:  # noqa: BLE001 - не Windows или нет API
        return None


def apply(hwnd: int, mode: int = WDA_EXCLUDEFROMCAPTURE) -> bool:
    """Исключить окно hwnd из снимков экрана.

    Возвращает True, если Windows приняла режим. Без Windows и без прав
    вернёт False - тогда снимок останется как есть, хуже не станет.
    """
    user32 = _user32()
    if user32 is None or not hwnd:
        return False
    try:
        if not user32.SetWindowDisplayAffinity(wintypes.HWND(int(hwnd)), mode):
            return False
        with _lock:
            _applied[int(hwnd)] = int(mode)
        return True
    except Exception:  # noqa: BLE001
        return False


def current(hwnd: int) -> int | None:
    """Какой режим сейчас действует для окна (None - не удалось узнать)."""
    user32 = _user32()
    if user32 is None or not hwnd:
        return None
    try:
        value = wintypes.DWORD()
        if not user32.GetWindowDisplayAffinity(wintypes.HWND(int(hwnd)), ctypes.byref(value)):
            return None
        return int(value.value)
    except Exception:  # noqa: BLE001
        return None


def is_excluded(hwnd: int) -> bool:
    """Исключено ли окно из снимков."""
    return current(hwnd) in (WDA_EXCLUDEFROMCAPTURE, WDA_MONITOR)


def restore(hwnd: int) -> bool:
    """Вернуть окно в снимки (нужно при закрытии)."""
    return apply(hwnd, WDA_NONE)


def apply_with_retry(hwnd: int, attempts: int = _APPLY_ATTEMPTS) -> bool:
    """Попробовать включить исключение несколько раз.

    Сразу после создания окна Windows иногда ещё не готова принять
    аффинити, поэтому делаем несколько попыток с короткой паузой.
    """
    import time

    for _ in range(max(1, attempts)):
        if apply(hwnd):
            return True
        time.sleep(0.05)
    return False


__all__ = [
    "WDA_EXCLUDEFROMCAPTURE",
    "WDA_MONITOR",
    "WDA_NONE",
    "apply",
    "apply_with_retry",
    "current",
    "is_excluded",
    "restore",
]