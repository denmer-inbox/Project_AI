"""Инструменты управления мышью и клавиатурой (категория input).

Координаты во всех инструментах задаются в пикселях ИЗОБРАЖЕНИЯ (того снимка,
который видит модель) и первым делом переводятся в абсолютные координаты
рабочего стола через Screenshot.to_absolute(). Если сервис экрана недоступен,
инструмент честно падает: без снимка перевод координат невозможен.
"""

from __future__ import annotations

import time
from typing import Any

from pcagent.interfaces import Risk, Screenshot
from pcagent.tools.base import (
    ToolContext,
    ToolRegistry,
    ToolResult,
    prop_boolean,
    prop_integer,
    prop_number,
    prop_string,
    schema,
)

CATEGORY = "input"
MOUSE_BUTTONS: tuple[str, ...] = ("left", "right", "middle")
SHOT_CACHE_TTL = 2.0

# Синонимы имён клавиш pyautogui: модель часто пишет короткие варианты.
KEY_ALIASES: dict[str, str] = {
    "esc": "escape",
    "return": "enter",
    "del": "delete",
    "ins": "insert",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "pgdown": "pagedown",
    "win": "winleft",
    "windows": "winleft",
    "meta": "winleft",
    "cmd": "winleft",
    "control": "ctrl",
    "option": "alt",
    "caps": "capslock",
    "prtsc": "printscreen",
    "print": "printscreen",
    "volup": "volumeup",
    "voldown": "volumedown",
}

FALLBACK_KEYS: tuple[str, ...] = (
    "alt", "backspace", "capslock", "ctrl", "delete", "down", "end", "enter",
    "escape", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
    "f11", "f12", "home", "insert", "left", "pagedown", "pageup", "printscreen",
    "right", "shift", "space", "tab", "up", "winleft",
)


# --------------------------------------------------------------------------- #
# вспомогательные функции
# --------------------------------------------------------------------------- #
def _pyautogui():
    """Ленивый импорт pyautogui с безопасными настройками."""
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    return pyautogui


def _configure_pyautogui() -> None:
    """Настройки по умолчанию при регистрации инструментов."""
    try:
        _pyautogui()
    except Exception:  # noqa: BLE001 - модуль не должен падать при импорте
        pass


def _screenshot(ctx: ToolContext) -> Screenshot | None:
    """Снимок для перевода координат: последний известный либо свежий (с кэшем)."""
    screen = getattr(ctx, "screen", None)
    if screen is None:
        return None
    for attr in ("last_screenshot", "last_shot"):
        shot = getattr(ctx, attr, None)
        if isinstance(shot, Screenshot) and shot.scale > 0:
            return shot
    cached = getattr(ctx, "_input_control_shot", None)
    if isinstance(cached, tuple) and len(cached) == 2:
        stamp, shot = cached
        if isinstance(shot, Screenshot) and time.monotonic() - float(stamp) < SHOT_CACHE_TTL:
            return shot
    config = ctx.config
    # Геометрия не должна тратить бюджет снимков модели: если сервис умеет
    # отдавать снимок "только для координат", используем его.
    capture = getattr(screen, "capture_geometry", None) or screen.capture
    try:
        shot = capture(
            monitor=getattr(config, "monitor", 0),
            max_width=getattr(config, "screenshot_max_width", None),
            fmt=getattr(config, "screenshot_format", None),
            quality=getattr(config, "screenshot_quality", None),
        )
    except TypeError:
        # Упрощённая реализация сервиса экрана без параметров.
        shot = capture()
    try:
        setattr(ctx, "_input_control_shot", (time.monotonic(), shot))
    except Exception:  # noqa: BLE001 - кэш необязателен
        pass
    return shot


def _shot_or_fail(ctx: ToolContext) -> tuple[Screenshot | None, ToolResult | None]:
    """Получить снимок или готовый ToolResult с понятной ошибкой."""
    try:
        shot = _screenshot(ctx)
    except Exception as exc:  # noqa: BLE001
        return None, ToolResult.fail(
            "Не удалось получить снимок экрана для перевода координат",
            error=f"screen_error: {type(exc).__name__}: {exc}",
        )
    if shot is None:
        return None, ToolResult.fail(
            "Нет доступа к экрану: ctx.screen не подключён, координаты снимка перевести нельзя",
            error="screen_unavailable",
        )
    return shot, None


def _coords(args: dict[str, Any], keys: tuple[str, ...]) -> tuple[list[float] | None, str | None]:
    """Прочитать числовые координаты по списку имён параметров."""
    values: list[float] = []
    for key in keys:
        raw = args.get(key)
        if raw is None:
            return None, f"не хватает параметра {key}"
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            return None, f"параметр {key} должен быть числом"
    return values, None


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        result = float(value) if value is not None else default
    except (TypeError, ValueError):
        result = default
    return max(low, min(high, result))


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        result = int(value) if value is not None else default
    except (TypeError, ValueError):
        result = default
    return max(low, min(high, result))


def _keyboard_keys() -> set[str]:
    """Допустимые имена клавиш pyautogui (или резервный список)."""
    try:
        import pyautogui

        return {str(key).lower() for key in pyautogui.KEYBOARD_KEYS}
    except Exception:  # noqa: BLE001
        return set(FALLBACK_KEYS)


def _normalize_key(key: Any) -> tuple[str | None, str | None]:
    """Привести имя клавиши к нотации pyautogui."""
    raw = str(key or "").strip().lower()
    if not raw:
        return None, "пустое имя клавиши"
    valid = _keyboard_keys()
    candidate = KEY_ALIASES.get(raw, raw)
    if candidate in valid:
        return candidate, None
    if raw in valid:
        return raw, None
    return None, f"неизвестная клавиша {raw!r}"


def _unknown_key_fail(raw: Any, reason: str) -> ToolResult:
    allowed = sorted(_keyboard_keys() or FALLBACK_KEYS)
    preview = ", ".join(allowed[:40])
    return ToolResult.fail(
        f"Клавиша {raw!r} не поддерживается ({reason}). Допустимые клавиши: {preview}, ... (всего {len(allowed)})",
        error="unknown_key",
        allowed_keys=allowed,
    )


#: Системы координат, которые принимают инструменты мыши.
COORD_SPACES: tuple[str, ...] = ("image", "screen")


def _coords_space(args: dict[str, Any]) -> str:
    """В какой системе заданы координаты: снимка или рабочего стола.

    По умолчанию - пиксели снимка (так модель видит картинку). Но ui_tree
    отдаёт координаты рабочего стола, и модели приходится пересчитывать их
    вручную: на реальном прогоне она путалась в этом десятки шагов и кликала
    мимо. Явный space="screen" позволяет кликнуть координаты из ui_tree как есть.
    """
    value = str(args.get("space") or "image").strip().lower()
    return "screen" if value in ("screen", "desktop", "absolute", "экран") else "image"


def _to_screen(shot: Any, x: float, y: float, args: dict[str, Any]) -> tuple[int, int]:
    """Перевести координаты в абсолютные координаты рабочего стола."""
    if _coords_space(args) == "screen":
        return int(round(x)), int(round(y))
    return shot.to_absolute(x, y)


def _pyautogui_fail(exc: Exception) -> ToolResult:
    return ToolResult.fail(
        "pyautogui недоступен: управление мышью и клавиатурой невозможно",
        error=f"pyautogui_unavailable: {type(exc).__name__}: {exc}",
    )


# --------------------------------------------------------------------------- #
# обработчики инструментов
# --------------------------------------------------------------------------- #
def _tool_click(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    shot, fail = _shot_or_fail(ctx)
    if fail is not None:
        return fail
    assert shot is not None
    coords, err = _coords(args, ("x", "y"))
    if err:
        return ToolResult.fail(f"Неверные координаты клика: {err}", error="bad_arguments")
    button = str(args.get("button") or "left").strip().lower()
    if button not in MOUSE_BUTTONS:
        return ToolResult.fail(
            f"Кнопка {button!r} не поддерживается, допустимо: {', '.join(MOUSE_BUTTONS)}",
            error="bad_button",
        )
    double = bool(args.get("double"))
    clicks = _clamp_int(args.get("clicks"), 2 if double else 1, 1, 3)
    interval = _clamp_float(args.get("interval"), 0.0, 0.0, 2.0)
    image_x, image_y = float(coords[0]), float(coords[1])
    abs_x, abs_y = _to_screen(shot, image_x, image_y, args)
    try:
        pyautogui = _pyautogui()
        pyautogui.click(abs_x, abs_y, clicks=clicks, interval=interval, button=button)
    except Exception as exc:  # noqa: BLE001 - FailSafeException и прочее
        return _pyautogui_fail(exc)
    return ToolResult(
        ok=True,
        summary=f"Клик {button} x{clicks} в точке ({abs_x}, {abs_y}) (координаты снимка: {image_x:g}, {image_y:g})",
        data={
            "x": abs_x,
            "y": abs_y,
            "image_x": round(image_x, 2),
            "image_y": round(image_y, 2),
            "button": button,
            "clicks": clicks,
        },
    )


def _tool_move_mouse(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    shot, fail = _shot_or_fail(ctx)
    if fail is not None:
        return fail
    assert shot is not None
    coords, err = _coords(args, ("x", "y"))
    if err:
        return ToolResult.fail(f"Неверные координаты: {err}", error="bad_arguments")
    duration = _clamp_float(args.get("duration"), 0.2, 0.0, 5.0)
    image_x, image_y = float(coords[0]), float(coords[1])
    abs_x, abs_y = _to_screen(shot, image_x, image_y, args)
    try:
        pyautogui = _pyautogui()
        pyautogui.moveTo(abs_x, abs_y, duration=duration)
    except Exception as exc:  # noqa: BLE001
        return _pyautogui_fail(exc)
    return ToolResult(
        ok=True,
        summary=f"Курсор перемещён в ({abs_x}, {abs_y})",
        data={"x": abs_x, "y": abs_y, "duration": duration},
    )


def _tool_drag(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    shot, fail = _shot_or_fail(ctx)
    if fail is not None:
        return fail
    assert shot is not None
    coords, err = _coords(args, ("from_x", "from_y", "to_x", "to_y"))
    if err:
        return ToolResult.fail(f"Неверные координаты перетаскивания: {err}", error="bad_arguments")
    button = str(args.get("button") or "left").strip().lower()
    if button not in MOUSE_BUTTONS:
        return ToolResult.fail(
            f"Кнопка {button!r} не поддерживается, допустимо: {', '.join(MOUSE_BUTTONS)}",
            error="bad_button",
        )
    duration = _clamp_float(args.get("duration"), 0.5, 0.05, 10.0)
    from_x, from_y = _to_screen(shot, float(coords[0]), float(coords[1]), args)
    to_x, to_y = _to_screen(shot, float(coords[2]), float(coords[3]), args)
    try:
        pyautogui = _pyautogui()
        pyautogui.moveTo(from_x, from_y, duration=0.1)
        pyautogui.dragTo(to_x, to_y, duration=duration, button=button)
    except Exception as exc:  # noqa: BLE001
        return _pyautogui_fail(exc)
    return ToolResult(
        ok=True,
        summary=f"Перетаскивание из ({from_x}, {from_y}) в ({to_x}, {to_y})",
        data={
            "from_x": from_x,
            "from_y": from_y,
            "to_x": to_x,
            "to_y": to_y,
            "button": button,
            "duration": duration,
        },
    )


def _tool_scroll(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    amount_raw = args.get("amount")
    if amount_raw is None:
        return ToolResult.fail("Не хватает параметра amount (отрицательное значение - вниз)", error="bad_arguments")
    try:
        amount = int(amount_raw)
    except (TypeError, ValueError):
        return ToolResult.fail("Параметр amount должен быть целым числом", error="bad_arguments")
    amount = max(-50, min(50, amount))
    if amount == 0:
        return ToolResult.fail("amount не может быть 0", error="bad_arguments")

    abs_x: int | None = None
    abs_y: int | None = None
    if args.get("x") is not None or args.get("y") is not None:
        shot, fail = _shot_or_fail(ctx)
        if fail is not None:
            return fail
        assert shot is not None
        coords, err = _coords(args, ("x", "y"))
        if err:
            return ToolResult.fail(f"Неверные координаты прокрутки: {err}", error="bad_arguments")
        abs_x, abs_y = shot.to_absolute(float(coords[0]), float(coords[1]))
    try:
        pyautogui = _pyautogui()
        pyautogui.scroll(amount, x=abs_x, y=abs_y)
    except Exception as exc:  # noqa: BLE001
        return _pyautogui_fail(exc)
    place = f" в точке ({abs_x}, {abs_y})" if abs_x is not None and abs_y is not None else ""
    return ToolResult(
        ok=True,
        summary=f"Прокрутка на {amount}{place}",
        data={"amount": amount, "x": abs_x, "y": abs_y},
    )


def _tool_hotkey(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    raw_keys = args.get("keys")
    if isinstance(raw_keys, str):
        raw_keys = [part for part in raw_keys.replace("+", " ").split() if part]
    if not isinstance(raw_keys, (list, tuple)) or not raw_keys:
        return ToolResult.fail("Не хватает параметра keys: список клавиш, например ['ctrl', 'c']", error="bad_arguments")
    if len(raw_keys) > 6:
        return ToolResult.fail("Слишком много клавиш в комбинации (максимум 6)", error="bad_arguments")
    normalized: list[str] = []
    for raw_key in raw_keys:
        key, err = _normalize_key(raw_key)
        if err or key is None:
            return _unknown_key_fail(raw_key, err or "не распознана")
        normalized.append(key)
    try:
        pyautogui = _pyautogui()
        pyautogui.hotkey(*normalized)
    except Exception as exc:  # noqa: BLE001
        return _pyautogui_fail(exc)
    return ToolResult(
        ok=True,
        summary=f"Нажата комбинация {'+'.join(normalized)}",
        data={"keys": normalized},
    )


def _tool_press_key(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    raw_key = args.get("key")
    if raw_key is None or str(raw_key).strip() == "":
        return ToolResult.fail("Не хватает параметра key (например 'enter')", error="bad_arguments")
    key, err = _normalize_key(raw_key)
    if err or key is None:
        return _unknown_key_fail(raw_key, err or "не распознана")
    presses = _clamp_int(args.get("presses"), 1, 1, 50)
    interval = _clamp_float(args.get("interval"), 0.05, 0.0, 1.0)
    try:
        pyautogui = _pyautogui()
        pyautogui.press(key, presses=presses, interval=interval)
    except Exception as exc:  # noqa: BLE001
        return _pyautogui_fail(exc)
    return ToolResult(
        ok=True,
        summary=f"Нажата клавиша {key} (повторов: {presses})",
        data={"key": key, "presses": presses},
    )


def _paste_via_clipboard(text: str) -> tuple[bool, str]:
    """Вставить текст через буфер обмена, восстановив прежнее содержимое."""
    try:
        import pyperclip
    except Exception as exc:  # noqa: BLE001
        return False, f"pyperclip недоступен: {exc}"
    try:
        pyautogui = _pyautogui()
    except Exception as exc:  # noqa: BLE001
        return False, f"pyautogui недоступен: {exc}"

    backup: str | None = None
    try:
        backup = pyperclip.paste()
    except Exception:  # noqa: BLE001 - буфер может быть занят
        backup = None
    try:
        pyperclip.copy(text)
    except Exception as exc:  # noqa: BLE001
        return False, f"не удалось записать текст в буфер обмена: {exc}"
    try:
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)
    except Exception as exc:  # noqa: BLE001
        return False, f"не удалось вставить текст: {exc}"
    finally:
        if backup is not None:
            try:
                pyperclip.copy(backup)
            except Exception:  # noqa: BLE001
                pass
    return True, ""


def _tool_type_text(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    text = args.get("text")
    if text is None or str(text) == "":
        return ToolResult.fail("Не хватает параметра text (непустая строка)", error="bad_arguments")
    text = str(text)
    interval = _clamp_float(args.get("interval"), 0.01, 0.0, 1.0)
    try:
        pyautogui = _pyautogui()
    except Exception as exc:  # noqa: BLE001
        return _pyautogui_fail(exc)

    if text.isascii():
        try:
            pyautogui.write(text, interval=interval)
        except Exception as exc:  # noqa: BLE001
            return _pyautogui_fail(exc)
        return ToolResult(
            ok=True,
            summary=f"Введён текст длиной {len(text)} символов",
            data={"length": len(text), "method": "write"},
        )

    # Не-ASCII: pyautogui.typewrite не умеет юникод, вставляем через буфер обмена.
    ok, reason = _paste_via_clipboard(text)
    if not ok:
        return ToolResult.fail(f"Не удалось ввести не-ASCII текст: {reason}", error="type_failed")
    return ToolResult(
        ok=True,
        summary=f"Введён не-ASCII текст длиной {len(text)} символов через буфер обмена",
        data={"length": len(text), "method": "clipboard"},
    )


# --------------------------------------------------------------------------- #
# регистрация
# --------------------------------------------------------------------------- #
def register(registry: ToolRegistry) -> None:
    """Зарегистрировать инструменты категории input."""
    _configure_pyautogui()

    registry.add(
        name="click",
        description=(
            "Click a mouse button at a point. By default the point is in screenshot image "
            "pixels and is converted to absolute desktop coordinates automatically; "
            "pass space='screen' to click coordinates taken from ui_tree as-is. "
            "Use double=true or clicks=2 for a double click."
        ),
        parameters=schema(
            {
                "x": prop_integer("X coordinate in screenshot image pixels"),
                "y": prop_integer("Y coordinate in screenshot image pixels"),
                "button": prop_string("Mouse button to click", enum=list(MOUSE_BUTTONS)),
                "clicks": prop_integer("Number of clicks: 1 (single) or 2 (double)", minimum=1, maximum=3),
                "double": prop_boolean("Shortcut for a double click (same as clicks=2)"),
                "interval": prop_number("Delay between clicks in seconds", minimum=0, maximum=2),
                "space": prop_string(
                    "Coordinate system: 'image' - pixels of the screenshot the model saw "
                    "(default); 'screen' - absolute desktop pixels, e.g. coordinates "
                    "copied from ui_tree.",
                    enum=list(COORD_SPACES),
                ),
            },
            required=["x", "y"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_click)

    registry.add(
        name="move_mouse",
        description="Move the mouse cursor to a point given in screenshot image pixels.",
        parameters=schema(
            {
                "x": prop_integer("X coordinate in screenshot image pixels"),
                "y": prop_integer("Y coordinate in screenshot image pixels"),
                "duration": prop_number("Movement duration in seconds", minimum=0, maximum=5),
                "space": prop_string(
                    "Coordinate system: 'image' - pixels of the screenshot the model saw "
                    "(default); 'screen' - absolute desktop pixels, e.g. coordinates "
                    "copied from ui_tree.",
                    enum=list(COORD_SPACES),
                ),
            },
            required=["x", "y"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_move_mouse)

    registry.add(
        name="drag",
        description=(
            "Drag with the mouse from one point to another. Both points are given in "
            "screenshot image pixels and converted to absolute coordinates."
        ),
        parameters=schema(
            {
                "from_x": prop_integer("Start X in screenshot image pixels"),
                "from_y": prop_integer("Start Y in screenshot image pixels"),
                "to_x": prop_integer("End X in screenshot image pixels"),
                "to_y": prop_integer("End Y in screenshot image pixels"),
                "button": prop_string("Mouse button to hold while dragging", enum=list(MOUSE_BUTTONS)),
                "duration": prop_number("Drag duration in seconds", minimum=0.05, maximum=10),
                "space": prop_string(
                    "Coordinate system: 'image' - pixels of the screenshot the model saw "
                    "(default); 'screen' - absolute desktop pixels, e.g. coordinates "
                    "copied from ui_tree.",
                    enum=list(COORD_SPACES),
                ),
            },
            required=["from_x", "from_y", "to_x", "to_y"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_drag)

    registry.add(
        name="scroll",
        description=(
            "Scroll the mouse wheel. Negative amount scrolls down, positive scrolls up. "
            "Optionally move the pointer to a screenshot pixel position first."
        ),
        parameters=schema(
            {
                "amount": prop_integer("Wheel clicks; negative scrolls down, positive scrolls up"),
                "x": prop_integer("Optional X in screenshot image pixels to scroll at"),
                "y": prop_integer("Optional Y in screenshot image pixels to scroll at"),
            },
            required=["amount"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_scroll)

    registry.add(
        name="hotkey",
        description=(
            "Press a keyboard shortcut, for example ['ctrl', 'c'] or ['alt', 'f4']. "
            "Keys use pyautogui names: ctrl, alt, shift, win, enter, esc, tab, f1..f12, letters."
        ),
        parameters=schema(
            {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keys to press together, in order, for example ['ctrl', 'shift', 's']",
                },
            },
            required=["keys"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_hotkey)

    registry.add(
        name="type_text",
        description=(
            "Type text into the focused window. ASCII text is typed character by character; "
            "non-ASCII (for example Cyrillic) text is pasted via the clipboard and the previous "
            "clipboard content is restored afterwards."
        ),
        parameters=schema(
            {
                "text": prop_string("Text to type"),
                "interval": prop_number("Delay between characters in seconds", minimum=0, maximum=1),
            },
            required=["text"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_type_text)

    registry.add(
        name="press_key",
        description=(
            "Press a single keyboard key, optionally several times. Examples: enter, esc, tab, "
            "backspace, delete, down, f5, win."
        ),
        parameters=schema(
            {
                "key": prop_string("Key name in pyautogui notation, for example 'enter'"),
                "presses": prop_integer("How many times to press the key", minimum=1, maximum=50),
                "interval": prop_number("Delay between presses in seconds", minimum=0, maximum=1),
            },
            required=["key"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_press_key)
