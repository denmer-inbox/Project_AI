"""Глобальная горячая клавиша стоп-крана (Windows, RegisterHotKey).

Клавиша работает даже когда окно PC Agent не в фокусе: например, если агент
увёл мышь и клавиатуру в другое приложение, пользователь всё равно может
остановить его сочетанием из config.yaml (по умолчанию Ctrl+Alt+Q).

Реализация на ctypes + отдельный поток с циклом сообщений Windows:
никаких сторонних библиотек и хуков клавиатуры не требуется.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Any, Callable

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
}

_NAMED_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "pause": 0x13,
    "printscreen": 0x2C,
}


def parse_hotkey(combination: str) -> tuple[int, int]:
    """Разобрать 'ctrl+alt+q' в (модификаторы, виртуальный код клавиши).

    Бросает ValueError на пустое/неизвестное сочетание.
    """
    text = (combination or "").strip().lower().replace(" ", "")
    if not text:
        raise ValueError("пустое сочетание клавиш")
    parts = [p for p in text.split("+") if p]
    if not parts:
        raise ValueError(f"не удалось разобрать сочетание {combination!r}")

    modifiers = 0
    key_part = ""
    for part in parts:
        if part in MODIFIERS:
            modifiers |= MODIFIERS[part]
        else:
            if key_part:
                raise ValueError(f"в сочетании {combination!r} больше одной клавиши")
            key_part = part

    if not key_part:
        raise ValueError(f"в сочетании {combination!r} нет клавиши")

    if key_part in _NAMED_KEYS:
        vk = _NAMED_KEYS[key_part]
    elif len(key_part) == 1 and key_part.isalnum():
        vk = ord(key_part.upper())
    elif key_part.startswith("f") and key_part[1:].isdigit() and 1 <= int(key_part[1:]) <= 24:
        vk = 0x70 + int(key_part[1:]) - 1
    else:
        raise ValueError(f"неизвестная клавиша {key_part!r} в сочетании {combination!r}")

    if not modifiers:
        raise ValueError(f"сочетание {combination!r} должно содержать модификатор (ctrl/alt/shift/win)")
    return modifiers | MOD_NOREPEAT, vk


class HotkeyListener:
    """Слушатель глобальной горячей клавиши.

    start() не бросает исключений: если Windows не дала зарегистрировать
    клавишу (занята другим приложением) или мы не на Windows, вернётся False,
    а приложение продолжит работать без горячей клавиши.
    """

    def __init__(
        self,
        combination: str = "ctrl+alt+q",
        callback: Callable[[], Any] | None = None,
        logger: Any = None,
    ) -> None:
        self.combination = combination
        self.callback = callback or (lambda: None)
        self.logger = logger
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._registered = False
        self._hotkey_id = 0xB0B0

    # ------------------------------------------------------------------
    def _log(self, text: str) -> None:
        if self.logger is not None:
            try:
                self.logger.log("hotkey", {"text": text, "combination": self.combination})
            except Exception:  # noqa: BLE001
                pass

    @property
    def registered(self) -> bool:
        return self._registered

    def start(self, wait: float = 1.5) -> bool:
        """Запустить поток-слушатель. Возвращает True, если клавиша зарегистрирована."""
        if self._thread is not None and self._thread.is_alive():
            return self._registered
        if sys.platform != "win32":
            self.error = "глобальная горячая клавиша поддерживается только в Windows"
            return False
        try:
            modifiers, vk = parse_hotkey(self.combination)
        except ValueError as exc:
            self.error = str(exc)
            self._log(f"не удалось разобрать сочетание: {exc}")
            return False

        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, args=(modifiers, vk), name="pcagent-hotkey", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=wait)
        if not self._registered:
            self._log(f"горячая клавиша {self.combination} не зарегистрирована: {self.error}")
        return self._registered

    # ------------------------------------------------------------------
    def _run(self, modifiers: int, vk: int) -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
        except Exception as exc:  # noqa: BLE001
            self.error = f"user32 недоступен: {exc}"
            self._ready.set()
            return

        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

        if not user32.RegisterHotKey(None, self._hotkey_id, modifiers, vk):
            self.error = f"RegisterHotKey: код {ctypes.get_last_error()} (клавиша занята?)"
            self._ready.set()
            return

        self._registered = True
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                if msg.message == WM_HOTKEY and int(msg.wParam) == self._hotkey_id:
                    try:
                        self.callback()
                    except Exception:  # noqa: BLE001 - колбэк не должен убивать слушатель
                        pass
        finally:
            try:
                user32.UnregisterHotKey(None, self._hotkey_id)
            except Exception:  # noqa: BLE001
                pass
            self._registered = False

    def stop(self, wait: float = 1.0) -> None:
        """Снять регистрацию и остановить поток."""
        thread_id = self._thread_id
        if thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:  # noqa: BLE001
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=wait)
        self._thread = None
        self._thread_id = None
        self._registered = False

    def __enter__(self) -> "HotkeyListener":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
