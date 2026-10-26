"""Окно клиента не попадает в собственные снимки экрана.

Раньше снимок захватывал и окно клиента: модель видела на кадре свой же
чат с прошлыми сообщениями вместо целевой программы. Windows умеет
исключать окно из захвата (WDA_EXCLUDEFROMCAPTURE), при этом на экране
окно остаётся видимым - пользователь ничего не замечает.
"""

from __future__ import annotations

import pytest

from pcagent.gui import window_exclusion as we


def test_mode_constants():
    """Режимы исключения должны совпадать с документацией Windows."""
    assert we.WDA_NONE == 0
    assert we.WDA_MONITOR == 1
    assert we.WDA_EXCLUDEFROMCAPTURE == 17


def test_apply_returns_bool_without_crash():
    """Вызов на несуществующем окне не должен бросать исключение."""
    assert we.apply(0) is False
    assert we.apply(-1) is False


def test_current_is_none_for_bad_hwnd():
    assert we.current(0) is None


def test_is_excluded_for_bad_hwnd():
    assert we.is_excluded(0) is False


def test_restore_on_bad_hwnd():
    assert we.restore(0) is False


def test_apply_with_retry_gives_up_quickly():
    """Без окна повторные попытки не должны занимать много времени."""
    import time

    started = time.monotonic()
    assert we.apply_with_retry(0, attempts=3) is False
    assert time.monotonic() - started < 2.0


class _FakeUser32:
    """Подмена user32 для проверки логики без реального окна."""

    def __init__(self, succeed: bool = True, mode: int = 17) -> None:
        self.succeed = succeed
        self.mode = mode
        self.calls: list[tuple[int, int]] = []

    def SetWindowDisplayAffinity(self, hwnd, mode):  # noqa: N802 - имя WinAPI
        self.calls.append((int(hwnd.value if hasattr(hwnd, "value") else hwnd), int(mode)))
        return 1 if self.succeed else 0

    def GetWindowDisplayAffinity(self, hwnd, out):  # noqa: N802 - имя WinAPI
        out._obj.value = self.mode
        return 1


def test_apply_sends_expected_mode(monkeypatch):
    fake = _FakeUser32()
    monkeypatch.setattr(we, "_user32", lambda: fake)

    assert we.apply(1234) is True
    assert fake.calls == [(1234, we.WDA_EXCLUDEFROMCAPTURE)]


def test_apply_returns_false_when_system_refuses(monkeypatch):
    fake = _FakeUser32(succeed=False)
    monkeypatch.setattr(we, "_user32", lambda: fake)
    assert we.apply(1234) is False


def test_apply_without_windows_api(monkeypatch):
    """Не Windows: функция молча возвращает False, снимки работают как раньше."""
    monkeypatch.setattr(we, "_user32", lambda: None)
    assert we.apply(1234) is False
    assert we.current(1234) is None


def test_config_has_hide_option():
    from pcagent.config import AppConfig

    assert AppConfig().hide_from_screenshots is True


def test_exclusion_can_be_disabled():
    from pcagent.config import AppConfig

    config = AppConfig(hide_from_screenshots=False)
    assert config.hide_from_screenshots is False