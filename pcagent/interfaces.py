"""Замороженные контракты проекта.

ВАЖНО: этот файл является общим для всех модулей. Менять его можно только
через Lead, иначе параллельная работа модулей разъедется.

Договорённости:
  * координаты на снимке экрана задаются в пикселях ИЗОБРАЖЕНИЯ (того, что
    видит модель). Перевод в абсолютные координаты рабочего стола делает
    image_to_absolute() / Screenshot.to_absolute().
  * Screenshot.scale = ширина_изображения / ширина_реальной_области.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class Risk(str, Enum):
    """Уровень риска операции."""

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"

    @property
    def order(self) -> int:
        return {Risk.READ: 0, Risk.WRITE: 1, Risk.DESTRUCTIVE: 2}[self]


@dataclass
class MonitorInfo:
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool = False

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "is_primary": self.is_primary,
        }


@dataclass
class Screenshot:
    """Снимок экрана, готовый к отправке модели."""

    image_bytes: bytes
    mime_type: str = "image/jpeg"
    width: int = 0            # ширина изображения (после масштабирования)
    height: int = 0           # высота изображения (после масштабирования)
    scale: float = 1.0        # ширина_изображения / ширина_реальной_области
    monitor: int = 0
    origin_left: int = 0      # смещение реальной области в рабочем столе
    origin_top: int = 0
    real_width: int = 0
    real_height: int = 0
    path: str | None = None
    captured_at: float = field(default_factory=time.time)

    def to_absolute(self, x: float, y: float, clamp: bool = True) -> tuple[int, int]:
        """Пиксели изображения -> абсолютные координаты рабочего стола."""
        scale = self.scale or 1.0
        abs_x = self.origin_left + int(round(float(x) / scale))
        abs_y = self.origin_top + int(round(float(y) / scale))
        if clamp:
            max_x = self.origin_left + max(int(self.real_width) - 1, 0)
            max_y = self.origin_top + max(int(self.real_height) - 1, 0)
            abs_x = min(max(abs_x, self.origin_left), max_x)
            abs_y = min(max(abs_y, self.origin_top), max_y)
        return abs_x, abs_y

    def to_image(self, abs_x: float, abs_y: float) -> tuple[int, int]:
        """Абсолютные координаты -> пиксели изображения (обратное преобразование)."""
        scale = self.scale or 1.0
        return (
            int(round((float(abs_x) - self.origin_left) * scale)),
            int(round((float(abs_y) - self.origin_top) * scale)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "scale": round(self.scale, 6),
            "monitor": self.monitor,
            "origin_left": self.origin_left,
            "origin_top": self.origin_top,
            "real_width": self.real_width,
            "real_height": self.real_height,
            "mime_type": self.mime_type,
            "bytes": len(self.image_bytes),
            "path": self.path,
        }


def image_to_absolute(x: float, y: float, shot: Screenshot, clamp: bool = True) -> tuple[int, int]:
    """Свободная функция-обёртка над Screenshot.to_absolute()."""
    return shot.to_absolute(x, y, clamp=clamp)


@runtime_checkable
class ScreenService(Protocol):
    """Сервис чтения экрана. Реализация - pcagent.capture (исполнитель A)."""

    def monitors(self) -> list[MonitorInfo]:
        ...

    def capture(
        self,
        monitor: int | None = None,
        max_width: int | None = None,
        fmt: str | None = None,
        quality: int | None = None,
    ) -> Screenshot:
        ...

    def size(self, monitor: int | None = None) -> tuple[int, int]:
        ...

    def uia_tree(self, max_nodes: int | None = None) -> str:
        ...

    def active_window(self) -> dict[str, Any] | None:
        ...

    def close(self) -> None:
        ...


@runtime_checkable
class Confirmer(Protocol):
    """Интерфейс подтверждения опасных действий."""

    def ask(self, question: str, details: str = "", timeout: float | None = None) -> bool:
        ...


@dataclass
class RunResult:
    """Результат выполнения задачи агентом."""

    success: bool
    steps: int = 0
    final_text: str = ""
    error: str | None = None
    transcript_path: str | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "steps": self.steps,
            "final_text": self.final_text,
            "error": self.error,
            "transcript_path": self.transcript_path,
            "actions": self.actions,
        }


@runtime_checkable
class AgentControl(Protocol):
    """Публичный интерфейс агентной сессии (реализация - pcagent.agent.loop)."""

    @property
    def is_running(self) -> bool:
        ...

    def run_task(self, task: str) -> RunResult:
        ...

    def stop(self) -> None:
        ...
