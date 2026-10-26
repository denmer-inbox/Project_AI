"""Запуск GUI без окна терминала.

Обычный запуск идёт через pythonw.exe: чёрное окно консоли не появляется.
У pythonw нет stdout и stderr (они равны None), поэтому любой print()
уронил бы приложение, а ошибки исчезли бы бесследно. Вывод уводится в
logs/gui.log, а необработанные исключения перехватываются.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pcagent.gui import logfile


def test_logfile_path_created(tmp_path):
    path = logfile.log_path(tmp_path)
    assert path.name == logfile.LOG_NAME
    assert path.parent == tmp_path
    assert path.parent.exists()


def test_setup_writes_header(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    path = logfile.setup(tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "запуск GUI" in content
    assert "без консоли" in content


def test_setup_replaces_missing_streams(tmp_path, monkeypatch):
    """При pythonw sys.stdout is None: печать должна уходить в файл."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    path = logfile.setup(tmp_path)
    assert sys.stdout is not None
    assert sys.stderr is not None
    print("проверка записи")
    sys.stdout.flush()
    assert "проверка записи" in path.read_text(encoding="utf-8")


def test_console_mode_keeps_streams(tmp_path, monkeypatch):
    class _Fake:
        encoding = "utf-8"

        def __init__(self):
            self.buffer = []

        def write(self, text):
            self.buffer.append(str(text))
            return len(str(text))

        def flush(self):
            pass

        def isatty(self):
            return True

    fake_out = _Fake()
    fake_err = _Fake()
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)
    logfile.setup(tmp_path, console=True)
    assert sys.stdout is fake_out
    assert sys.stderr is fake_err


def test_rotation_renames_big_log(tmp_path):
    path = tmp_path / logfile.LOG_NAME
    path.write_bytes(b"x" * (logfile.MAX_LOG_BYTES + 10))
    logfile._rotate(path)
    assert not path.exists()
    assert (tmp_path / (logfile.LOG_NAME + ".old")).exists()


def test_tail_returns_last_lines(tmp_path):
    path = logfile.log_path(tmp_path)
    path.write_text("\n".join(f"строка {i}" for i in range(100)), encoding="utf-8")
    tail = logfile.tail(tmp_path, lines=5)
    assert "строка 99" in tail
    assert "строка 0" not in tail


def test_unhandled_exception_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    path = logfile.setup(tmp_path)
    monkeypatch.setattr(logfile, "show_error", lambda *a, **k: None)
    try:
        raise RuntimeError("тестовый сбой")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    content = path.read_text(encoding="utf-8")
    assert "необработанная ошибка" in content
    assert "тестовый сбой" in content


def test_file_stream_has_no_fileno(tmp_path):
    stream = logfile._FileStream(tmp_path / "x.log")
    with pytest.raises(OSError):
        stream.fileno()
    assert stream.isatty() is False


def test_cli_gui_has_debug_console_flag():
    from pcagent.cli import build_parser

    args = build_parser().parse_args(["gui", "--debug-console"])
    assert args.debug_console is True
    args = build_parser().parse_args(["gui"])
    assert args.debug_console is False


def test_run_bat_uses_pythonw():
    root = Path(__file__).resolve().parent.parent
    content = (root / "run.bat").read_text(encoding="utf-8", errors="replace")
    assert "pythonw.exe" in content
    assert "gui.log" in content


def test_run_ps1_uses_pythonw():
    root = Path(__file__).resolve().parent.parent
    content = (root / "run.ps1").read_text(encoding="utf-8-sig", errors="replace")
    assert "pythonw.exe" in content
    assert "gui.log" in content


def test_run_ps1_keeps_bom():
    """PowerShell 5.1 без BOM ломает кириллицу в самом скрипте."""
    root = Path(__file__).resolve().parent.parent
    raw = (root / "run.ps1").read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"