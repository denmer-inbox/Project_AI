"""Совместимость: ожидание "успокоения" экрана живёт в pcagent.vision."""

from __future__ import annotations

from pcagent.vision import (  # noqa: F401 - реэкспорт для старых импортов
    DEFAULT_POLL_S,
    DEFAULT_THRESHOLD,
    UI_ACTION_TOOLS,
    SettleDetector,
    SettleResult,
    frame_difference,
    frame_signature,
)

__all__ = [
    "DEFAULT_POLL_S",
    "DEFAULT_THRESHOLD",
    "UI_ACTION_TOOLS",
    "SettleDetector",
    "SettleResult",
    "frame_difference",
    "frame_signature",
]
