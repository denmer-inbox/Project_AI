"""Дешёвые признаки кадра: подпись экрана и ожидание "успокоения".

Зачем это нужно. Раньше после каждого действия стояла фиксированная пауза
(action_delay, по умолчанию 0.7 с), чтобы интерфейс успел перерисоваться.
Проблема: пауза не знает, случилось ли что-то на экране. Если действие
мгновенное (клик по кнопке, нажатие клавиши), агент всё равно спит 0.7 с.

Здесь вместо сна по таймеру измеряется ФАКТ: кадр уменьшается до маленькой
серой подписи (160 px по ширине), и цикл ждёт, пока две подписи подряд не
совпадут. Обычно это 60-120 мс вместо 700, а при анимации ожидание честно
продолжается, но не дольше заданного предела.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

#: Ширина подписи в пикселях: 160x90 даёт ~14 КБ и считается за миллисекунды.
THUMB_WIDTH = 160

#: Порог поблочной разницы (0..255), ниже которого кадры считаются
#: одинаковыми. Замеры на реальном экране 2560x1440:
#:   шум сжатия JPEG (q90 vs q60) .... 1.4
#:   точка 4 px ...................... 16.4
#:   иконка 12 px .................... 62.1
#:   кнопка 60 px ................... 202.5
#: Порог 4.0 уверенно отсекает шум сжатия и ловит даже точечные изменения.
DEFAULT_THRESHOLD = 4.0

#: Размер блока для поблочной метрики. Средняя разница по всему кадру
#: размывает локальные изменения (кнопка 40 px давала 0.8 при шуме 0.2),
#: а максимум по блокам видит их сразу.
BLOCK_SIZE = 8

#: Как часто снимать кадр во время ожидания.
DEFAULT_POLL_S = 0.06


def frame_signature(image_bytes: bytes, width: int = THUMB_WIDTH) -> bytes | None:
    """Уменьшенная серая подпись кадра. None, если изображение не читается."""
    if not image_bytes:
        return None
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - без Pillow подпись недоступна
        return None
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        if image.width <= 0 or image.height <= 0:
            return None
        height = max(1, int(round(image.height * width / image.width)))
        small = image.convert("L").resize((width, height), Image.BILINEAR)
        return small.tobytes()
    except Exception:  # noqa: BLE001 - битый кадр не должен ломать цикл
        return None


def frame_difference(first: bytes | None, second: bytes | None, block: int = BLOCK_SIZE) -> float:
    """Побочная разница двух подписей (0..255): максимум средних по блокам.

    Средняя разница по всему кадру размывает локальные изменения: кнопка
    40 px на экране 2560x1440 даёт всего 0.8 при шуме сжатия 0.2, и порог
    становится неразличимым. Максимум по блокам 8x8 видит такую кнопку как
    201, а шум остаётся на уровне 1.4.

    Несопоставимые подписи дают максимум: лучше лишний раз подождать,
    чем принять разные кадры за одинаковые.
    """
    if not first or not second or len(first) != len(second):
        return 255.0
    if block < 1:
        block = BLOCK_SIZE
    worst = 0.0
    for start in range(0, len(first), block):
        left_block = first[start:start + block]
        right_block = second[start:start + block]
        if not left_block:
            break
        total = 0
        for left, right in zip(left_block, right_block):
            total += abs(left - right)
        average = total / len(left_block)
        if average > worst:
            worst = average
            if worst >= 255.0:
                break
    return worst


@dataclass
class SettleResult:
    """Итог ожидания: сколько ждали и дождались ли стабильности."""

    waited: float = 0.0
    settled: bool = False
    frames: int = 0
    changed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "waited": round(self.waited, 3),
            "settled": self.settled,
            "frames": self.frames,
            "changed": self.changed,
        }


class SettleDetector:
    """Ждёт, пока экран перестанет меняться, вместо фиксированного сна.

    Снимает кадры через переданный сервис экрана. Если сервис умеет отдавать
    снимок только для геометрии (capture_geometry), используется он: такой
    снимок не тратит бюджет снимков модели.
    """

    def __init__(
        self,
        screen: Any,
        *,
        poll_s: float = DEFAULT_POLL_S,
        max_wait_s: float = 0.7,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self.screen = screen
        self.poll_s = max(0.01, float(poll_s))
        self.max_wait_s = max(0.0, float(max_wait_s))
        self.threshold = float(threshold)

    # ------------------------------------------------------------------
    def _capture_signature(self) -> bytes | None:
        if self.screen is None:
            return None
        capture = getattr(self.screen, "capture_geometry", None) or getattr(
            self.screen, "capture", None
        )
        if capture is None:
            return None
        try:
            shot = capture()
        except Exception:  # noqa: BLE001 - ожидание не должно падать
            return None
        data = getattr(shot, "image_bytes", None)
        if not data:
            return None
        return frame_signature(data)

    # ------------------------------------------------------------------
    def wait(self) -> SettleResult:
        """Дождаться стабильного кадра. Возвращает фактически потраченное время."""
        started = time.monotonic()
        result = SettleResult()

        previous = self._capture_signature()
        if previous is None:
            # Нет доступа к экрану: не спим вовсе, вызывающий сам решит.
            return result
        result.frames = 1

        while True:
            elapsed = time.monotonic() - started
            remaining = self.max_wait_s - elapsed
            if remaining <= 0:
                result.waited = elapsed
                result.settled = False
                return result

            time.sleep(min(self.poll_s, remaining))
            current = self._capture_signature()
            result.frames += 1
            if current is None:
                continue

            difference = frame_difference(previous, current)
            if difference > self.threshold:
                result.changed = True
            else:
                # Кадр не изменился: экран успокоился.
                result.waited = time.monotonic() - started
                result.settled = True
                return result
            previous = current

    def __call__(self) -> SettleResult:
        return self.wait()


#: Инструменты, после которых экран действительно может перерисоваться.
#: Для остальных ждать нечего: run_script уже вернул управление по завершении.
UI_ACTION_TOOLS: frozenset[str] = frozenset(
    {
        "click",
        "move_mouse",
        "drag",
        "scroll",
        "hotkey",
        "type_text",
        "press_key",
        "focus_window",
        "minimize_window",
        "maximize_window",
        "restore_window",
        "move_window",
        "close_window",
    }
)
