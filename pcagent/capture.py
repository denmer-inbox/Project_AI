"""Чтение экрана, UIA-дерево и инструменты категории capture.

Снимки делаются через mss, кодируются Pillow. Координаты в ответах
инструментов - пиксели рабочего стола. Снимок может быть уменьшен до
max_width, поэтому пиксели картинки переводятся в абсолютные координаты
через Screenshot.to_absolute() (scale = ширина_картинки / ширина_области).
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from pcagent.interfaces import MonitorInfo, Risk, Screenshot
from pcagent.tools.base import (
    ToolContext,
    ToolRegistry,
    ToolResult,
    prop_integer,
    prop_string,
    schema,
)

try:  # mss - обязательная зависимость, но модуль не должен падать при импорте
    import mss as _mss_module
except ImportError:  # pragma: no cover - защита от неполного окружения
    _mss_module = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]

try:
    import uiautomation as _uia
except ImportError:  # pragma: no cover - UIA необязателен
    _uia = None

try:
    import win32gui
    import win32process
except ImportError:  # pragma: no cover - только для Windows
    win32gui = None  # type: ignore[assignment]
    win32process = None  # type: ignore[assignment]

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"
FORMATS = ("jpeg", "png")
MAX_UIA_DEPTH = 25
#: Сколько секунд держать закэшированное дерево. Модель часто запрашивает
#: его дважды подряд; за это время интерфейс обычно не меняется.
UIA_CACHE_TTL = 0.5
MAX_NAME_LENGTH = 80

_DPI_STATE: dict[str, Any] = {"enabled": False, "mode": "none"}


# --------------------------------------------------------------- DPI awareness
def enable_dpi_awareness() -> bool:
    """Включить DPI awareness процесса. Идемпотентно, критично для координат."""
    if _DPI_STATE["enabled"]:
        return True
    if sys.platform != "win32":
        return False
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return False
    # 1) DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    try:
        if windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            _DPI_STATE.update(enabled=True, mode="per-monitor-v2")
            return True
    except Exception:  # noqa: BLE001 - на старых системах функции нет
        pass
    # 2) PROCESS_PER_MONITOR_DPI_AWARE = 2
    try:
        hresult = int(windll.shcore.SetProcessDpiAwareness(2))
        # S_OK, E_ACCESSDENIED (уже включено), 0x80070005 как unsigned
        if hresult in (0, -2147024891, 2147942405):
            _DPI_STATE.update(enabled=True, mode="per-monitor")
            return True
    except Exception:  # noqa: BLE001
        pass
    # 3) самый старый вариант
    try:
        if windll.user32.SetProcessDPIAware():
            _DPI_STATE.update(enabled=True, mode="system")
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def dpi_awareness_mode() -> str:
    """Текущий режим DPI awareness (для диагностики)."""
    return str(_DPI_STATE["mode"])


# -------------------------------------------------------------------- утилиты
def fit_size(width: int, height: int, max_width: int | None) -> tuple[int, int]:
    """Подогнать размер под max_width: пропорции сохраняются, апскейла нет."""
    try:
        real_w = max(1, int(width))
        real_h = max(1, int(height))
    except (TypeError, ValueError):
        return 1, 1
    if max_width is None:
        return real_w, real_h
    try:
        limit = int(max_width)
    except (TypeError, ValueError):
        return real_w, real_h
    if limit <= 0 or real_w <= limit:
        return real_w, real_h
    scaled_h = max(1, int(round(real_h * limit / real_w)))
    return limit, scaled_h


def _normalize_format(fmt: str | None) -> str:
    """Привести формат к jpeg или png (по умолчанию jpeg)."""
    name = str(fmt or "jpeg").strip().lower()
    if name in ("png", "image/png"):
        return "png"
    return "jpeg"


def _clamp_quality(quality: Any) -> int:
    """Ограничить качество JPEG диапазоном 1..100."""
    try:
        value = int(quality)
    except (TypeError, ValueError):
        value = 70
    return max(1, min(100, value))


def _new_mss() -> Any:
    """Создать сессию mss (новый MSS или устаревший mss.mss)."""
    if _mss_module is None:
        raise RuntimeError("модуль mss не установлен - снимок экрана невозможен")
    factory = getattr(_mss_module, "MSS", None) or getattr(_mss_module, "mss", None)
    if factory is None:  # pragma: no cover
        raise RuntimeError("в модуле mss нет фабрики MSS")
    return factory()


def _as_region(monitor: dict[str, Any]) -> dict[str, int]:
    """Привести описание монитора mss к словарю области снимка."""
    return {
        "left": int(monitor.get("left", 0)),
        "top": int(monitor.get("top", 0)),
        "width": max(1, int(monitor.get("width", 0))),
        "height": max(1, int(monitor.get("height", 0))),
    }


def _grab_to_image(grab: Any) -> Any:
    """Преобразовать снимок mss в PIL Image без лишних копий."""
    if Image is None:
        raise RuntimeError("Pillow не установлен - кодирование снимка невозможно")
    width = int(grab.width)
    height = int(grab.height)
    return Image.frombytes("RGB", (width, height), grab.bgra, "raw", "BGRX")


def _encode(image: Any, fmt: str, quality: int) -> tuple[bytes, str]:
    """Закодировать PIL Image в JPEG или PNG."""
    buffer = BytesIO()
    if fmt == "png":
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), PNG_MIME
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue(), JPEG_MIME


def _safe_attr(control: Any, name: str, default: Any = None) -> Any:
    """Прочитать свойство UIA-элемента, не падая на ошибках COM."""
    try:
        return getattr(control, name)
    except Exception:  # noqa: BLE001
        return default


def _clean_text(value: Any, limit: int = MAX_NAME_LENGTH) -> str:
    """Схлопнуть пробелы и обрезать длинный текст."""
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: max(0, limit - 1)] + "…"
    return text


def _control_type_name(control: Any) -> str:
    """Короткое имя типа элемента: ButtonControl -> Button."""
    raw = _clean_text(_safe_attr(control, "ControlTypeName", "?"), 40)
    if raw.endswith("Control") and len(raw) > len("Control"):
        raw = raw[: -len("Control")]
    return raw or "?"


def _control_rect(control: Any) -> tuple[int, int, int, int] | None:
    """Прямоугольник элемента в координатах рабочего стола."""
    rect = _safe_attr(control, "BoundingRectangle", None)
    if rect is None:
        return None
    try:
        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
    except Exception:  # noqa: BLE001
        return None
    return left, top, max(0, right - left), max(0, bottom - top)


def _format_node(control: Any, depth: int) -> str:
    """Одна строка компактного описания UIA-элемента."""
    parts = ["  " * depth + _control_type_name(control)]
    name = _clean_text(_safe_attr(control, "Name", ""))
    if name:
        parts.append('"' + name + '"')
    rect = _control_rect(control)
    if rect is not None:
        left, top, width, height = rect
        parts.append("[{0},{1} {2}x{3}]".format(left, top, width, height))
    if _safe_attr(control, "IsEnabled", True) is False:
        parts.append("(disabled)")
    if _safe_attr(control, "IsOffscreen", False) is True:
        parts.append("(offscreen)")
    return " ".join(parts)


def _children_of(control: Any) -> list[Any]:
    """Дети элемента одним COM-вызовом.

    GetChildren() отдаёт список за один round-trip. Перебор через
    GetFirstChildControl/GetNextSiblingControl делает вызов на каждого
    ребёнка, и на большом окне это превращается в секунды.
    """
    try:
        children = control.GetChildren()
    except Exception:  # noqa: BLE001 - узел мог исчезнуть
        return []
    return list(children or [])


def _render_tree(root: Any, limit: int, depth_limit: int = MAX_UIA_DEPTH) -> str:
    """Обойти дерево UIA в глубину и вернуть компактный текст."""
    lines: list[str] = []
    stack: list[tuple[Any, int]] = [(root, 0)]
    truncated = False
    while stack:
        if len(lines) >= limit:
            truncated = True
            break
        control, depth = stack.pop()
        try:
            lines.append(_format_node(control, depth))
        except Exception:  # noqa: BLE001 - узел может исчезнуть между вызовами
            lines.append("  " * depth + "?")
        if depth >= depth_limit:
            continue
        for child in reversed(_children_of(control)):
            stack.append((child, depth + 1))
    if truncated:
        lines.append("... (обрезано: лимит {0} узлов)".format(limit))
    return "\n".join(lines)


def _process_info(pid: int) -> tuple[str, str]:
    """Имя процесса и путь к исполняемому файлу по PID."""
    if psutil is None or not pid:
        return "", ""
    try:
        proc = psutil.Process(int(pid))
        name = str(proc.name() or "")
    except Exception:  # noqa: BLE001 - процесс мог завершиться
        return "", ""
    try:
        exe = str(proc.exe() or "")
    except Exception:  # noqa: BLE001
        exe = ""
    return name, exe


# --------------------------------------------------------------------- Screen
class Screen:
    """Сервис чтения экрана: снимки, мониторы, UIA-дерево, активное окно."""

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._sct: Any = None
        self._dpi_aware = enable_dpi_awareness()
        self._uia_cache: dict[tuple[str, int], tuple[float, str]] = {}

    # --- конфигурация -------------------------------------------------
    @property
    def config(self) -> Any:
        """Конфигурация приложения (по умолчанию - значения AppConfig)."""
        if self._config is None:
            from pcagent.config import AppConfig

            self._config = AppConfig()
        return self._config

    @property
    def dpi_aware(self) -> bool:
        return bool(self._dpi_aware)

    # --- backend mss --------------------------------------------------
    def _backend(self) -> Any:
        with self._lock:
            if self._sct is None:
                self._sct = _new_mss()
            return self._sct

    def _reset_backend(self) -> None:
        with self._lock:
            current = self._sct
            self._sct = None
        if current is not None:
            try:
                current.close()
            except Exception:  # noqa: BLE001
                pass

    def _raw_monitors(self) -> list[dict[str, Any]]:
        """Сырой список мониторов mss (нулевой элемент - весь рабочий стол)."""
        with self._lock:
            backend = self._backend()
            raw = list(getattr(backend, "monitors", None) or [])
        return [dict(item) for item in raw if isinstance(item, dict)]

    def _grab(self, region: dict[str, int]) -> Any:
        """Сделать снимок области, пересоздав сессию mss при сбое."""
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                with self._lock:
                    return self._backend().grab(dict(region))
            except Exception as exc:  # noqa: BLE001 - сессия mss могла умереть
                last_error = exc
                self._reset_backend()
                if attempt == 2:
                    break
        raise RuntimeError("не удалось получить снимок экрана: {0}".format(last_error))

    # --- геометрия ----------------------------------------------------
    def _region_for(self, monitor: int | None = None) -> tuple[int, dict[str, int]]:
        """Номер монитора и область снимка (индекс -1 означает весь рабочий стол)."""
        if monitor is None:
            try:
                index = int(getattr(self.config, "monitor", 0))
            except (TypeError, ValueError):
                index = 0
        else:
            try:
                index = int(monitor)
            except (TypeError, ValueError):
                index = 0
        raw = self._raw_monitors()
        if not raw:
            return 0, {"left": 0, "top": 0, "width": 1, "height": 1}
        if index < 0:
            return -1, _as_region(raw[0])
        physical = raw[1:] if len(raw) > 1 else raw
        if index >= len(physical):
            index = 0
        return index, _as_region(physical[index])

    def monitors(self) -> list[MonitorInfo]:
        """Список физических мониторов с координатами в рабочем столе."""
        raw = self._raw_monitors()
        physical = raw[1:] if len(raw) > 1 else raw
        result: list[MonitorInfo] = []
        for index, item in enumerate(physical):
            region = _as_region(item)
            result.append(
                MonitorInfo(
                    index=index,
                    left=region["left"],
                    top=region["top"],
                    width=region["width"],
                    height=region["height"],
                    is_primary=bool(item.get("is_primary", index == 0)),
                )
            )
        if not result:
            raise RuntimeError("не удалось определить ни одного монитора")
        return result

    def desktop(self) -> dict[str, int]:
        """Прямоугольник всего рабочего стола (объединение мониторов)."""
        _, region = self._region_for(-1)
        return {
            "left": region["left"],
            "top": region["top"],
            "width": region["width"],
            "height": region["height"],
            "right": region["left"] + region["width"],
            "bottom": region["top"] + region["height"],
        }

    def size(self, monitor: int | None = None) -> tuple[int, int]:
        """Размер области в реальных пикселях."""
        _, region = self._region_for(monitor)
        return region["width"], region["height"]

    # --- снимок -------------------------------------------------------
    def capture(
        self,
        monitor: int | None = None,
        max_width: int | None = None,
        fmt: str | None = None,
        quality: int | None = None,
    ) -> Screenshot:
        """Снимок области: PIL Image -> масштаб -> JPEG/PNG -> Screenshot."""
        if Image is None:
            raise RuntimeError("Pillow не установлен - снимок экрана невозможен")
        config = self.config
        format_name = _normalize_format(fmt if fmt is not None else getattr(config, "screenshot_format", "jpeg"))
        quality_value = _clamp_quality(quality if quality is not None else getattr(config, "screenshot_quality", 70))
        limit = max_width if max_width is not None else getattr(config, "screenshot_max_width", 1440)
        index, region = self._region_for(monitor)
        image = _grab_to_image(self._grab(region))
        real_width, real_height = image.size
        new_width, new_height = fit_size(real_width, real_height, limit)
        if (new_width, new_height) != (real_width, real_height):
            image = image.resize((new_width, new_height), Image.LANCZOS)
        image_bytes, mime_type = _encode(image, format_name, quality_value)
        path = self._store(image_bytes, format_name) if getattr(config, "save_screenshots", False) else None
        return Screenshot(
            image_bytes=image_bytes,
            mime_type=mime_type,
            width=new_width,
            height=new_height,
            scale=(new_width / float(real_width)) if real_width else 1.0,
            monitor=index,
            origin_left=region["left"],
            origin_top=region["top"],
            real_width=real_width,
            real_height=real_height,
            path=path,
        )

    def _store(self, image_bytes: bytes, fmt: str) -> str | None:
        """Сохранить снимок на диск, если это включено в конфигурации."""
        try:
            directory = Path(self.config.screenshots_path)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            extension = "png" if fmt == "png" else "jpg"
            target = directory / ("screen_{0}.{1}".format(stamp, extension))
            target.write_bytes(image_bytes)
            return str(target)
        except Exception:  # noqa: BLE001 - запись не должна ломать снимок
            return None

    # --- UIA ----------------------------------------------------------
    def uia_tree(self, max_nodes: int | None = None, scope: str = "active") -> str:
        """Компактное дерево UI Automation. При ошибках возвращает пустую строку.

        scope="active" (по умолчанию) обходит АКТИВНОЕ окно: это то, с чем
        работает агент, и обход занимает десятки миллисекунд. Обход всего
        рабочего стола (scope="desktop") на большом экране стоит секунды,
        потому что каждый узел - отдельный COM-вызов.

        Результат кэшируется на UIA_CACHE_TTL секунд: модель часто просит
        дерево дважды подряд, а между вызовами ничего не меняется.
        """
        limit = max_nodes if max_nodes is not None else getattr(self.config, "uia_max_nodes", 250)
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 250
        if _uia is None:
            return "UIA недоступен: модуль uiautomation не установлен"

        scope = (scope or "active").strip().lower()
        cache_key = (scope, limit)
        now = time.monotonic()
        with self._lock:
            cached = self._uia_cache.get(cache_key)
            if cached is not None and now - cached[0] < UIA_CACHE_TTL:
                return cached[1]

        try:
            # COM на потоке агента: инициализируем перед каждым обходом дерева
            _uia.InitializeUIAutomationInCurrentThread()
            if scope == "desktop":
                root = _uia.GetRootControl()
                depth_limit = MAX_UIA_DEPTH
            else:
                root = _uia.GetForegroundControl()
                if root is None:
                    root = _uia.GetRootControl()
                depth_limit = MAX_UIA_DEPTH
            if root is None:
                return ""
            text = _render_tree(root, limit, depth_limit=depth_limit)
            with self._lock:
                self._uia_cache[cache_key] = (time.monotonic(), text)
            return text
        except Exception:  # noqa: BLE001 - дерево не должно ронять агента
            return ""

    # --- активное окно ------------------------------------------------
    def active_window(self) -> dict[str, Any] | None:
        """Заголовок, PID, класс и прямоугольник активного окна."""
        if win32gui is None or win32process is None:
            return None
        try:
            hwnd = int(win32gui.GetForegroundWindow())
        except Exception:  # noqa: BLE001
            return None
        if not hwnd:
            return None
        try:
            title = str(win32gui.GetWindowText(hwnd) or "")
            class_name = str(win32gui.GetClassName(hwnd) or "")
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            pid = int(win32process.GetWindowThreadProcessId(hwnd)[1])
        except Exception:  # noqa: BLE001 - окно могло закрыться
            return None
        process_name, exe = _process_info(pid)
        return {
            "hwnd": hwnd,
            "title": title,
            "class_name": class_name,
            "pid": pid,
            "process": process_name,
            "exe": exe,
            "left": int(left),
            "top": int(top),
            "width": max(0, int(right) - int(left)),
            "height": max(0, int(bottom) - int(top)),
            "right": int(right),
            "bottom": int(bottom),
        }

    # --- жизненный цикл -----------------------------------------------
    def close(self) -> None:
        """Освободить сессию захвата экрана."""
        self._reset_backend()

    def __enter__(self) -> "Screen":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


# ------------------------------------------------------------- инструменты
def _screen_for(ctx: ToolContext) -> Any:
    """Взять ScreenService из контекста, создав его при необходимости."""
    screen = getattr(ctx, "screen", None)
    if screen is None:
        screen = Screen(getattr(ctx, "config", None))
        try:
            ctx.screen = screen
        except Exception:  # noqa: BLE001
            pass
    return screen


def _optional_int(value: Any, name: str) -> tuple[int | None, str | None]:
    """Разобрать необязательный целочисленный аргумент."""
    if value is None:
        return None, None
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, "Параметр {0} должен быть целым числом".format(name)


def _tool_screenshot(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Снимок экрана для модели."""
    monitor, error = _optional_int(args.get("monitor"), "monitor")
    if error:
        return ToolResult.fail(error, error="bad_argument")
    screen = _screen_for(ctx)
    try:
        shot = screen.capture(monitor=monitor)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail("Не удалось получить снимок экрана: {0}".format(exc), error="capture_failed")
    summary = "Снимок экрана {0}x{1} px (монитор {2}, область {3}x{4}, масштаб {5:.3f})".format(
        shot.width,
        shot.height,
        shot.monitor,
        shot.real_width,
        shot.real_height,
        shot.scale,
    )
    data = shot.as_dict()
    data["note"] = (
        "Координаты в пикселях снимка переводятся в рабочие как "
        "origin + пиксель / scale; инструменты ввода ждут координаты рабочего стола."
    )
    return ToolResult(ok=True, summary=summary, data=data, images=[shot])


def _tool_screen_info(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Мониторы, рабочий стол и активное окно - реальные координаты для клика."""
    screen = _screen_for(ctx)
    try:
        monitors = [monitor.as_dict() for monitor in screen.monitors()]
        desktop = screen.desktop()
        active = screen.active_window()
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail("Не удалось прочитать сведения об экране: {0}".format(exc), error="screen_info_failed")
    data: dict[str, Any] = {
        "monitors": monitors,
        "desktop": desktop,
        "active_window": active,
        "dpi_aware": bool(getattr(screen, "dpi_aware", False)),
        "note": "Координаты клика - пиксели рабочего стола: left/top монитора плюс смещение внутри него.",
    }
    parts = ["Мониторов: {0}".format(len(monitors)), "рабочий стол {0}x{1}".format(desktop["width"], desktop["height"])]
    if active:
        title = _clean_text(active.get("title", ""), 60) or "(без заголовка)"
        process = _clean_text(active.get("process", ""), 40) or "?"
        parts.append("активное окно: {0} ({1})".format(title, process))
        parts.append("окно {0},{1} {2}x{3}".format(active["left"], active["top"], active["width"], active["height"]))
    else:
        parts.append("активное окно не определено")
    return ToolResult(ok=True, summary="; ".join(parts), data=data)


def _tool_ui_tree(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Дерево UI Automation в компактном виде."""
    max_nodes, error = _optional_int(args.get("max_nodes"), "max_nodes")
    if error:
        return ToolResult.fail(error, error="bad_argument")
    if max_nodes is not None:
        max_nodes = max(1, min(600, max_nodes))
    scope = str(args.get("scope") or "active").strip().lower()
    if scope not in ("active", "desktop"):
        return ToolResult.fail(
            "scope должен быть 'active' (активное окно) или 'desktop' (весь рабочий стол)",
            error="bad_argument",
        )
    screen = _screen_for(ctx)
    try:
        try:
            tree = screen.uia_tree(max_nodes=max_nodes, scope=scope)
        except TypeError:
            # Упрощённая реализация сервиса экрана без параметра scope.
            tree = screen.uia_tree(max_nodes=max_nodes)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail("Не удалось прочитать UIA-дерево: {0}".format(exc), error="uia_failed")
    if not tree:
        return ToolResult(
            ok=True,
            summary="UIA-дерево пусто: элементы интерфейса недоступны (используйте снимок экрана)",
            data={"tree": "", "nodes": 0},
        )
    nodes = len([line for line in tree.splitlines() if line.strip()])
    return ToolResult(
        ok=True,
        summary="UIA-дерево: {0} строк (формат: Тип \"Имя\" [left,top WxH] enabled/disabled)".format(nodes),
        data={"tree": tree, "nodes": nodes},
    )


def register(registry: ToolRegistry) -> None:
    """Зарегистрировать инструменты категории capture."""
    registry.add(
        name="screenshot",
        description=(
            "Сделать снимок экрана и получить изображение. Возвращает картинку и метаданные: "
            "width/height (пиксели снимка), scale, origin_left/origin_top и real_width/real_height. "
            "Координата рабочего стола = origin + пиксель снимка / scale."
        ),
        parameters=schema(
            {
                "monitor": prop_integer(
                    "Номер монитора: 0 - первый (основной), -1 - все мониторы вместе. "
                    "По умолчанию берётся из конфигурации."
                )
            }
        ),
        risk=Risk.READ,
        category="capture",
    )(_tool_screenshot)

    registry.add(
        name="screen_info",
        description=(
            "Сведения об экране: список мониторов с координатами и размерами, полный рабочий стол "
            "и активное окно (заголовок, PID, класс, прямоугольник). Нужен, чтобы знать реальные "
            "координаты для кликов и границы областей."
        ),
        parameters=schema({}),
        risk=Risk.READ,
        category="capture",
    )(_tool_screen_info)

    registry.add(
        name="ui_tree",
        description=(
            "Дерево элементов интерфейса через UI Automation: тип, имя, прямоугольник в координатах "
            "рабочего стола и признак доступности. Дешевле снимка экрана и даёт точные координаты "
            "кнопок и полей. По умолчанию читает активное окно."
        ),
        parameters=schema(
            {
                "max_nodes": prop_integer(
                    "Сколько строк вернуть максимум (1..600). По умолчанию берётся из конфигурации.",
                    minimum=1,
                    maximum=600,
                ),
                "scope": prop_string(
                    "Область обхода: 'active' - активное окно (быстро, по умолчанию), "
                    "'desktop' - весь рабочий стол (медленнее).",
                    enum=["active", "desktop"],
                ),
            }
        ),
        risk=Risk.READ,
        category="capture",
    )(_tool_ui_tree)


__all__ = [
    "Screen",
    "enable_dpi_awareness",
    "dpi_awareness_mode",
    "fit_size",
    "register",
]
