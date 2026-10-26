"""Экономия трафика и интеллектуальные снимки экрана.

Модель склонна «смотреть» на экран вместо того, чтобы действовать, а
каждый снимок это мегабайты трафика и потерянные шаги. Модуль решает три
задачи:

  * бюджет снимков - не больше N за задачу, не чаще интервала и никогда
    два снимка подряд без действия между ними;
  * умный кадр - снимок обрезается по активному окну и сжимается;
  * компактный текст - дерево UI Automation прореживается до сути, чтобы
    модель могла работать текстом вместо картинок.

Координаты остаются корректными: при обрезке пересчитываются origin_left,
origin_top, real_width, real_height и scale, поэтому инструменты ввода
получают правильные абсолютные координаты.
"""

from __future__ import annotations

import io
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pcagent.interfaces import Screenshot

#: Значения по умолчанию, если в config.extra ничего не задано.
DEFAULT_MAX_PER_TASK = 4
DEFAULT_MIN_INTERVAL_S = 3.0
DEFAULT_AGENT_MAX_WIDTH = 1024
DEFAULT_AGENT_QUALITY = 60
DEFAULT_CROP_TO_WINDOW = True
DEFAULT_UIA_MAX_LINES = 120
DEFAULT_UIA_MAX_LINE_LEN = 120

#: Сообщение, которое увидит модель при исчерпании бюджета.
BUDGET_HINT = (
    "Снимок экрана недоступен: {reason}. "
    "Действуйте без картинки: ui_tree (текст элементов), screen_info (геометрия "
    "и активное окно), list_windows (список окон), clipboard_get. "
    "Опирайтесь на результаты предыдущих шагов, а не на новый снимок."
)


#: Границы бюджета снимков при автоматическом подборе под длину задачи.
MIN_PER_TASK_BY_STEPS = 6
MAX_PER_TASK_BY_STEPS = 40


def budget_for_steps(max_steps: int) -> int:
    """Сколько снимков разрешить на задачу такой длины.

    Фиксированные 4 снимка душили длинные задачи: на 60 шагов агенту нужно
    видеть экран десятки раз, а отказ в снимке уводил модель в текстовые
    обходы и самодельное управление мышью. Один снимок примерно на четыре
    шага, но не меньше 6 и не больше 40.
    """
    try:
        steps = int(max_steps)
    except (TypeError, ValueError):
        steps = 30
    return max(MIN_PER_TASK_BY_STEPS, min(MAX_PER_TASK_BY_STEPS, steps // 4))


class ScreenshotBudgetExceeded(RuntimeError):
    """Снимок отклонён политикой экономии трафика."""


def _int_option(extra: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(extra.get(key, default))
    except (TypeError, ValueError):
        return default


def _float_option(extra: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(extra.get(key, default))
    except (TypeError, ValueError):
        return default


def _bool_option(extra: dict[str, Any], key: str, default: bool) -> bool:
    value = extra.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "да")
    return bool(value)


@dataclass
class ScreenshotBudget:
    """Потокобезопасный счётчик снимков на одну задачу.

    Правила:
      * не больше max_per_task снимков;
      * не чаще min_interval_s секунд;
      * между двумя снимками должно быть хотя бы одно действие.
    """

    max_per_task: int = DEFAULT_MAX_PER_TASK
    min_interval_s: float = DEFAULT_MIN_INTERVAL_S
    used: int = 0
    actions_since_capture: int = 0
    last_capture_ts: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reset(self) -> None:
        """Начать новую задачу."""
        with self._lock:
            self.used = 0
            self.actions_since_capture = 0
            self.last_capture_ts = 0.0

    def note_action(self) -> None:
        """Модель что-то сделала: снимок снова осмыслен."""
        with self._lock:
            self.actions_since_capture += 1

    def note_capture(self) -> None:
        """Снимок выдан."""
        with self._lock:
            self.used += 1
            self.actions_since_capture = 0
            self.last_capture_ts = time.time()

    def check(self) -> tuple[bool, str]:
        """Можно ли выдать снимок. Возвращает (разрешено, причина отказа)."""
        with self._lock:
            if self.max_per_task > 0 and self.used >= self.max_per_task:
                return False, (
                    f"лимит снимков на задачу исчерпан ({self.used} из {self.max_per_task})"
                )
            if self.last_capture_ts and self.min_interval_s > 0:
                elapsed = time.time() - self.last_capture_ts
                if elapsed < self.min_interval_s:
                    return False, (
                        f"слишком частые снимки: прошло {elapsed:.1f} с "
                        f"из {self.min_interval_s:.0f} с"
                    )
            if self.used > 0 and self.actions_since_capture == 0:
                return False, (
                    "с прошлого снимка не было ни одного действия - сначала сделайте шаг"
                )
            return True, ""

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "used": self.used,
                "max_per_task": self.max_per_task,
                "actions_since_capture": self.actions_since_capture,
                "min_interval_s": self.min_interval_s,
            }


def compact_uia_tree(
    text: str,
    max_lines: int = DEFAULT_UIA_MAX_LINES,
    max_line_len: int = DEFAULT_UIA_MAX_LINE_LEN,
) -> str:
    """Проредить дерево UI Automation до полезного минимума.

    Убирает пустые строки, дубликаты и обрезает длинные имена: цель -
    сохранить структуру и подписи элементов, выкинув шум.
    """
    if not text:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for raw in str(text).splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if len(line) > max_line_len:
            line = line[: max_line_len - 3] + "..."
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if max_lines > 0 and len(lines) >= max_lines:
            lines.append(f"... (дерево сокращено, показано {max_lines} строк)")
            break
    return "\n".join(lines)


def _load_image(data: bytes) -> Any:
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def _encode_jpeg(image: Any, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=max(1, min(100, quality)))
    return buffer.getvalue()


class SmartScreenGate:
    """Обёртка над сервисом экрана: бюджет, обрезка и сжатие снимков.

    Заменяет прямой доступ агента к Screen. Все методы, кроме capture и
    uia_tree, делегируются исходному сервису без изменений.
    """

    def __init__(
        self,
        inner: Any,
        allow_initial: bool = False,
        budget: ScreenshotBudget | None = None,
        extra: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> None:
        self._inner = inner
        self._allow_initial = bool(allow_initial)
        self._initial_consumed = False
        options = dict(extra or {})
        self._max_width = _int_option(options, "agent_screenshot_max_width", DEFAULT_AGENT_MAX_WIDTH)
        self._quality = _int_option(options, "agent_screenshot_quality", DEFAULT_AGENT_QUALITY)
        self._crop = _bool_option(options, "crop_to_active_window", DEFAULT_CROP_TO_WINDOW)
        self._uia_lines = _int_option(options, "uia_max_lines", DEFAULT_UIA_MAX_LINES)
        self.budget = budget or ScreenshotBudget(
            max_per_task=_int_option(options, "screenshot_max_per_task", DEFAULT_MAX_PER_TASK),
            min_interval_s=_float_option(options, "screenshot_min_interval_s", DEFAULT_MIN_INTERVAL_S),
        )
        self._on_event = on_event
        self.stats: dict[str, Any] = {
            "captures": 0,
            "denied": 0,
            "cropped": 0,
            "bytes_saved": 0,
        }

    # --- служебное ----------------------------------------------------
    def _emit(self, text: str) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(text)
        except Exception:  # noqa: BLE001 - телеметрия не должна ломать захват
            pass

    def note_action(self) -> None:
        """Сообщить, что модель выполнила действие."""
        self.budget.note_action()

    def capture_geometry(self, *args: Any, **kwargs: Any) -> Any:
        """Снимок ТОЛЬКО для перевода координат, без бюджета и обрезки.

        Инструменты мыши/окон иногда нужна геометрия, когда модель ещё не
        видела экран. Такой снимок не уходит модели, поэтому он не должен
        тратить бюджет и не должен запускать интервал между снимками.
        """
        return self._inner.capture(*args, **kwargs)

    def reset(self) -> None:
        """Новая задача: счётчики и стартовый снимок сбрасываются."""
        self._initial_consumed = False
        self.budget.reset()

    # --- захват -------------------------------------------------------
    def capture(self, *args: Any, **kwargs: Any) -> Any:
        """Снимок с учётом бюджета, обрезки и сжатия."""
        if not self._initial_consumed:
            self._initial_consumed = True
            if not self._allow_initial:
                return None

        allowed, reason = self.budget.check()
        if not allowed:
            self.stats["denied"] += 1
            self._emit(f"Снимок отклонён: {reason}")
            raise ScreenshotBudgetExceeded(BUDGET_HINT.format(reason=reason))

        shot = self._inner.capture(*args, **kwargs)
        self.budget.note_capture()
        processed = self._process(shot)
        self.stats["captures"] += 1
        return processed

    def _process(self, shot: Any) -> Any:
        """Обрезать по активному окну и сжать изображение."""
        data = getattr(shot, "image_bytes", b"") or b""
        if not data:
            return shot
        original_size = len(data)
        try:
            image = _load_image(data)
        except Exception:  # noqa: BLE001 - без PIL отдаём как есть
            return shot

        origin_left = int(getattr(shot, "origin_left", 0) or 0)
        origin_top = int(getattr(shot, "origin_top", 0) or 0)
        real_width = int(getattr(shot, "real_width", 0) or image.width)
        real_height = int(getattr(shot, "real_height", 0) or image.height)
        scale = float(getattr(shot, "scale", 1.0) or 1.0)

        cropped = False
        if self._crop:
            window = self._safe_active_window()
            if window is not None:
                crop = self._crop_box(
                    window, origin_left, origin_top, real_width, real_height, scale
                )
                if crop is not None:
                    box, real_rect = crop
                    try:
                        image = image.crop(box)
                        # Геометрию берём из самого окна, а не обратным
                        # пересчётом: иначе округление даёт сдвиг на пиксель
                        # и клики уезжают.
                        origin_left, origin_top, real_width, real_height = real_rect
                        scale = image.width / real_width if real_width else scale
                        cropped = True
                        self.stats["cropped"] += 1
                    except Exception:  # noqa: BLE001 - обрезка необязательна
                        pass

        if self._max_width > 0 and image.width > self._max_width:
            ratio = self._max_width / image.width
            new_size = (self._max_width, max(1, int(round(image.height * ratio))))
            try:
                from PIL import Image as _Image

                image = image.resize(new_size, _Image.LANCZOS)
            except Exception:  # noqa: BLE001
                image = image.resize(new_size)

        try:
            encoded = _encode_jpeg(image, self._quality)
        except Exception:  # noqa: BLE001
            return shot

        self.stats["bytes_saved"] += max(0, original_size - len(encoded))
        return Screenshot(
            image_bytes=encoded,
            mime_type="image/jpeg",
            width=image.width,
            height=image.height,
            scale=(image.width / real_width) if real_width else scale,
            monitor=int(getattr(shot, "monitor", 0) or 0),
            origin_left=origin_left,
            origin_top=origin_top,
            real_width=real_width,
            real_height=real_height,
            path=None,
            captured_at=float(getattr(shot, "captured_at", time.time()) or time.time()),
        )

    def _safe_active_window(self) -> dict[str, Any] | None:
        try:
            window = self._inner.active_window()
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(window, dict):
            return None
        try:
            width = int(window.get("width") or 0)
            height = int(window.get("height") or 0)
        except (TypeError, ValueError):
            return None
        if width < 200 or height < 150:
            return None
        return window

    @staticmethod
    def _crop_box(
        window: dict[str, Any],
        origin_left: int,
        origin_top: int,
        real_width: int,
        real_height: int,
        scale: float,
    ) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
        """Прямоугольник обрезки в пикселях изображения и реальный прямоугольник.

        Окно задано в координатах рабочего стола, снимок - в пикселях
        изображения, поэтому смещение делится на масштаб.
        """
        try:
            left = int(window.get("left") or 0)
            top = int(window.get("top") or 0)
            width = int(window.get("width") or 0)
            height = int(window.get("height") or 0)
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None

        # окно целиком вне снимка - обрезать нечего
        if left + width <= origin_left or top + height <= origin_top:
            return None
        if left >= origin_left + real_width or top >= origin_top + real_height:
            return None

        # если окно занимает почти весь кадр, обрезка не экономит трафик
        area_ratio = (width * height) / max(1, real_width * real_height)
        if area_ratio > 0.92:
            return None

        # обрезаем окно границами снимка, чтобы координаты остались верными
        clip_left = max(left, origin_left)
        clip_top = max(top, origin_top)
        clip_right = min(left + width, origin_left + real_width)
        clip_bottom = min(top + height, origin_top + real_height)
        clip_width = clip_right - clip_left
        clip_height = clip_bottom - clip_top
        if clip_width < 50 or clip_height < 50:
            return None

        safe_scale = scale if scale > 0 else 1.0
        box = (
            max(0, int(round((clip_left - origin_left) * safe_scale))),
            max(0, int(round((clip_top - origin_top) * safe_scale))),
            int(round((clip_right - origin_left) * safe_scale)),
            int(round((clip_bottom - origin_top) * safe_scale)),
        )
        if box[2] - box[0] < 50 or box[3] - box[1] < 50:
            return None
        return box, (clip_left, clip_top, clip_width, clip_height)

    # --- текст вместо картинки ---------------------------------------
    def uia_tree(self, max_nodes: int | None = None) -> str:
        """Дерево UI Automation в компактном виде."""
        try:
            tree = self._inner.uia_tree(max_nodes=max_nodes)
        except Exception:  # noqa: BLE001
            return ""
        return compact_uia_tree(str(tree or ""), max_lines=self._uia_lines)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
