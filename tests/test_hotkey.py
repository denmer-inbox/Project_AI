"""Тесты разбора и запуска глобальной горячей клавиши."""

from __future__ import annotations

import pytest

from pcagent.hotkey import HotkeyListener, parse_hotkey


@pytest.mark.parametrize(
    "combination, expected_vk",
    [
        ("ctrl+alt+q", ord("Q")),
        ("CTRL+SHIFT+F9", 0x78),
        ("win+space", 0x20),
        ("alt+1", ord("1")),
    ],
)
def test_parse_hotkey_accepts_valid_combinations(combination, expected_vk):
    modifiers, vk = parse_hotkey(combination)
    assert modifiers & 0x4000  # MOD_NOREPEAT выставлен
    assert vk == expected_vk


@pytest.mark.parametrize("bad", ["", "q", "ctrl+", "ctrl+alt", "ctrl+alt+unknownkey"])
def test_parse_hotkey_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_hotkey(bad)


def test_listener_reports_error_without_raising():
    listener = HotkeyListener("ctrl+alt+q", callback=lambda: None)
    assert listener.registered is False
    listener.stop()  # остановка до запуска безопасна


def test_listener_start_and_stop_cycle():
    calls: list[int] = []
    listener = HotkeyListener("ctrl+alt+f12", callback=lambda: calls.append(1))
    started = listener.start()
    # В среде без интерактивного рабочего стола регистрация может не удаться:
    # главное - отсутствие исключений и корректная остановка.
    assert isinstance(started, bool)
    if started:
        assert listener.registered
    listener.stop()
    assert listener.registered is False
