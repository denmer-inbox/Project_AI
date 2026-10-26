"""Вывод GUI без консоли: сообщения и ошибки уходят в файл.

Зачем. GUI запускается через pythonw.exe, чтобы не держать чёрное окно
терминала на экране. У pythonw нет stdout и stderr: sys.stdout is None.
Любой print() в этом режиме падает с AttributeError, а необработанное
исключение исчезает бесследно - окно просто не появляется.

Модуль подменяет потоки вывода файлом, ставит обработчики необработанных
исключений и, если запуск не удался, показывает ошибку в окне сообщения.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

#: Размер файла журнала, после которого он переименовывается в .old.
MAX_LOG_BYTES = 2 * 1024 * 1024

#: Имя файла журнала внутри каталога logs.
LOG_NAME = "gui.log"


class _FileStream:
    """Минимальная замена sys.stdout/sys.stderr с записью в файл.

    Реализует только то, что реально вызывают print() и traceback:
    write, flush, isatty, fileno (последний намеренно бросает исключение,
    чтобы код, проверяющий терминал, не решил, что перед ним консоль).
    """

    def __init__(self, path: Path, prefix: str = "") -> None:
        self._path = path
        self._prefix = prefix
        self._lock = threading.Lock()
        self.encoding = "utf-8"

    def write(self, text: Any) -> int:
        data = str(text)
        if not data:
            return 0
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8", errors="replace") as handle:
                    for line in data.splitlines() or [""]:
                        handle.write(f"{self._prefix}{line}\n")
            except Exception:  # noqa: BLE001 - журнал не должен ломать приложение
                pass
        return len(data)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        raise OSError("у потока нет файлового дескриптора")


def _rotate(path: Path) -> None:
    """Переименовать переросший журнал, чтобы он не рос бесконечно."""
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            old = path.with_suffix(path.suffix + ".old")
            if old.exists():
                old.unlink()
            path.rename(old)
    except Exception:  # noqa: BLE001
        pass


def log_path(log_dir: str | Path = "logs") -> Path:
    """Путь к файлу журнала GUI."""
    directory = Path(log_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        directory = Path.cwd()
    return directory / LOG_NAME


def setup(log_dir: str | Path = "logs", *, console: bool = False) -> Path:
    """Направить вывод в файл и перехватить необработанные исключения.

    console=True оставляет вывод в терминале (режим отладки): файл всё
    равно ведётся, но потоки не подменяются.
    """
    target = log_path(log_dir)
    _rotate(target)

    # Потоки подменяем ТОЛЬКО если их нет (pythonw) и только когда консоль
    # не нужна. Если поток есть и это не pythonw, не трогаем его: иначе
    # глобальный sys.stdout остаётся изменённым для всего процесса.
    if not console:
        if sys.stdout is None:
            sys.stdout = _FileStream(target)  # type: ignore[assignment]
        if sys.stderr is None:
            sys.stderr = _FileStream(target)  # type: ignore[assignment]

    def _write_header() -> None:
        try:
            with open(target, "a", encoding="utf-8") as handle:
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                handle.write(f"\n===== запуск GUI {stamp} =====\n")
                handle.write(f"python: {sys.executable}\n")
                handle.write(f"режим: {'консоль' if console else 'без консоли'}\n")
        except Exception:  # noqa: BLE001
            pass

    _write_header()

    def _hook(exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write("\n--- необработанная ошибка ---\n")
                handle.write(text)
        except Exception:  # noqa: BLE001
            pass
        show_error("Неожиданная ошибка", text)

    sys.excepthook = _hook

    def _thread_hook(args: Any) -> None:
        text = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        try:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(f"\n--- ошибка в потоке {args.thread.name if args.thread else '?'} ---\n")
                handle.write(text)
        except Exception:  # noqa: BLE001
            pass

    threading.excepthook = _thread_hook  # type: ignore[assignment]
    return target


def show_error(title: str, text: str) -> None:
    """Показать ошибку в окне сообщения, если это возможно.

    В безконсольном режиме это единственный способ сообщить пользователю,
    что запуск не удался. Если tkinter недоступен, остаётся только журнал.
    """
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, text[:2000])
        root.destroy()
    except Exception:  # noqa: BLE001 - показать не удалось, уже записано в журнал
        pass


def tail(log_dir: str | Path = "logs", lines: int = 40) -> str:
    """Последние строки журнала: для сообщения об ошибке запуска."""
    target = log_path(log_dir)
    try:
        content = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return ""
    return "\n".join(content[-lines:])


__all__ = ["LOG_NAME", "MAX_LOG_BYTES", "log_path", "setup", "show_error", "tail"]
