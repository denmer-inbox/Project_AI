"""Ускорение цикла: ожидание по факту, обрезка результатов, умолчания."""

from __future__ import annotations

import time

import pytest

from pcagent import vision
from pcagent.config import AppConfig
from pcagent.llm import DEFAULT_MAX_RESULT_CHARS, truncate_result


# ---------------------------------------------------------------- подписи кадра
def test_frame_difference_of_identical_frames_is_zero():
    signature = bytes(range(64))
    assert vision.frame_difference(signature, signature) == 0.0


def test_frame_difference_of_incomparable_frames_is_max():
    assert vision.frame_difference(b"abc", b"abcdef") == 255.0
    assert vision.frame_difference(None, b"abc") == 255.0


def test_block_metric_catches_local_change():
    """Локальное изменение видно, хотя средняя по кадру его размывает."""
    size = 16 * 16
    base = bytes([100] * size)
    changed = bytearray(base)
    # меняем один блок 8x8 целиком
    for index in range(0, 64):
        changed[index] = 200
    block = vision.frame_difference(base, bytes(changed))
    assert block > vision.DEFAULT_THRESHOLD, "локальное изменение должно ловиться"

    mean = sum(abs(a - b) for a, b in zip(base, changed)) / size
    assert mean < block, "поблочная метрика чувствительнее средней"


def test_jpeg_like_noise_is_below_threshold():
    """Небольшой равномерный шум не должен считаться изменением."""
    base = bytes([100] * 4096)
    noisy = bytes([101] * 4096)
    assert vision.frame_difference(base, noisy) < vision.DEFAULT_THRESHOLD


# ------------------------------------------------------------ детектор покоя
class _FakeScreen:
    """Сервис экрана: отдаёт заданную последовательность кадров."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0

    def capture_geometry(self):
        from pcagent.interfaces import Screenshot

        index = min(self.calls, len(self.frames) - 1)
        self.calls += 1
        return Screenshot(image_bytes=self.frames[index], width=10, height=10, scale=1.0)


def _jpeg(color: int, size: int = 40) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("L", (size, size), color).save(buffer, format="JPEG", quality=70)
    return buffer.getvalue()


def test_settle_returns_quickly_when_screen_is_static():
    screen = _FakeScreen([_jpeg(100)])
    detector = vision.SettleDetector(screen, poll_s=0.01, max_wait_s=0.5)
    started = time.monotonic()
    result = detector.wait()
    elapsed = time.monotonic() - started
    assert result.settled is True
    assert elapsed < 0.4, f"ждали {elapsed:.2f} c при статичном экране"
    assert result.frames >= 2


def test_settle_waits_while_screen_changes():
    frames = [_jpeg(10), _jpeg(200), _jpeg(20), _jpeg(200)]
    screen = _FakeScreen(frames)
    detector = vision.SettleDetector(screen, poll_s=0.01, max_wait_s=0.25)
    result = detector.wait()
    assert result.changed is True
    assert result.waited >= 0.05


def test_settle_without_screen_does_not_sleep():
    detector = vision.SettleDetector(None, poll_s=0.01, max_wait_s=5.0)
    started = time.monotonic()
    result = detector.wait()
    assert time.monotonic() - started < 0.1
    assert result.settled is False


def test_ui_action_tools_cover_input_and_windows():
    for name in ("click", "type_text", "hotkey", "focus_window", "close_window"):
        assert name in vision.UI_ACTION_TOOLS
    for name in ("run_script", "list_windows", "get_system_info"):
        assert name not in vision.UI_ACTION_TOOLS


# --------------------------------------------------------- обрезка результатов
def test_truncate_result_keeps_small_payload():
    payload = {"ok": True, "summary": "мало", "data": {"a": 1}}
    assert truncate_result(payload) == payload


def test_truncate_result_shortens_large_text():
    payload = {"ok": True, "summary": "много", "data": {"tree": "x" * 20000}}
    result = truncate_result(payload, limit=500)
    assert result["truncated"] is True
    assert len(result["data"]["tree"]) < 20000
    assert result["ok"] is True
    assert result["summary"] == "много"


def test_truncate_result_preserves_short_fields():
    payload = {
        "ok": True,
        "summary": "s",
        "data": {"nodes": 121, "tree": "y" * 50000},
    }
    result = truncate_result(payload, limit=800)
    assert result["data"]["nodes"] == 121


def test_default_result_limit_is_sane():
    assert 2000 <= DEFAULT_MAX_RESULT_CHARS <= 20000


# ------------------------------------------------------------------ умолчания
def test_new_speed_settings_have_safe_defaults():
    config = AppConfig()
    assert config.max_tool_result_chars == 6000
    assert config.keep_tool_results == 6
    assert config.action_delay <= 1.0


def test_env_file_can_be_disabled_for_tests(monkeypatch, tmp_path):
    from pcagent.config import load_env

    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("PCAGENT_NO_ENV", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    load_env(env_file)
    import os

    assert os.environ.get("GEMINI_API_KEY") is None
