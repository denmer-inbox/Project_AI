"""Инструменты управления окнами и процессами (категория windows).

Перечисление и поиск окон идут через win32gui (заголовок, PID, прямоугольник,
состояние), активация - через SetForegroundWindow с обходом ограничения
переднего плана, процессы - через psutil. Координаты move_window задаются в
пикселях изображения последнего снимка и переводятся в абсолютные.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from typing import Any

from pcagent.interfaces import Risk, Screenshot
from pcagent.tools.base import (
    ToolContext,
    ToolRegistry,
    ToolResult,
    prop_boolean,
    prop_integer,
    prop_string,
    schema,
)

CATEGORY = "windows"
SHOT_CACHE_TTL = 2.0
MAX_WINDOWS = 200

# Процессы, которые нельзя завершать: падение любого из них ломает сессию Windows.
PROTECTED_PROCESS_NAMES: frozenset[str] = frozenset(
    {
        "system",
        "system idle process",
        "registry",
        "memory compression",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "winlogon.exe",
        "dwm.exe",
        "svchost.exe",
    }
)
PROTECTED_PIDS: frozenset[int] = frozenset({0, 4})

# Ключ кэша снимка живёт на контексте, чтобы не дёргать захват на каждый вызов.
_SHOT_ATTR = "_windows_apps_shot"


# --------------------------------------------------------------------------- #
# ленивые импорты и мелкие помощники
# --------------------------------------------------------------------------- #
def _win32():
    """Модули pywin32, нужные для работы с окнами."""
    import win32con
    import win32gui
    import win32process

    return win32gui, win32con, win32process


def _psutil():
    import psutil

    return psutil


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        result = int(value) if value is not None else default
    except (TypeError, ValueError):
        result = default
    return max(low, min(high, result))


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        result = float(value) if value is not None else default
    except (TypeError, ValueError):
        result = default
    return max(low, min(high, result))


def _screenshot(ctx: ToolContext) -> Screenshot | None:
    """Снимок для перевода координат: последний известный либо свежий (с кэшем)."""
    screen = getattr(ctx, "screen", None)
    if screen is None:
        return None
    for attr in ("last_screenshot", "last_shot"):
        shot = getattr(ctx, attr, None)
        if isinstance(shot, Screenshot) and shot.scale > 0:
            return shot
    cached = getattr(ctx, _SHOT_ATTR, None)
    if isinstance(cached, tuple) and len(cached) == 2:
        stamp, shot = cached
        if isinstance(shot, Screenshot) and time.monotonic() - float(stamp) < SHOT_CACHE_TTL:
            return shot
    config = ctx.config
    # Геометрия не должна тратить бюджет снимков модели.
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
        setattr(ctx, _SHOT_ATTR, (time.monotonic(), shot))
    except Exception:  # noqa: BLE001 - кэш необязателен
        pass
    return shot


def _shot_or_fail(ctx: ToolContext) -> tuple[Screenshot | None, ToolResult | None]:
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


# --------------------------------------------------------------------------- #
# окна
# --------------------------------------------------------------------------- #
def _process_name(pid: int) -> str | None:
    try:
        return _psutil().Process(pid).name()
    except Exception:  # noqa: BLE001 - процесс мог завершиться
        return None


def _window_state(hwnd: int) -> dict[str, bool]:
    win32gui, win32con, _ = _win32()
    minimized = bool(win32gui.IsIconic(hwnd))
    show_cmd = 0
    try:
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement and len(placement) > 1:
            show_cmd = int(placement[1])
    except Exception:  # noqa: BLE001
        show_cmd = 0
    return {"minimized": minimized, "maximized": show_cmd == win32con.SW_SHOWMAXIMIZED}


def _window_info(hwnd: int) -> dict[str, Any] | None:
    """Сведения об окне по hwnd или None, если окно не существует."""
    win32gui, win32con, win32process = _win32()
    hwnd = int(hwnd)
    if not win32gui.IsWindow(hwnd):
        return None
    title = win32gui.GetWindowText(hwnd).strip()
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    state = _window_state(hwnd)
    return {
        "hwnd": hwnd,
        "title": title,
        "pid": int(pid),
        "rect": {
            "left": int(left),
            "top": int(top),
            "width": int(right - left),
            "height": int(bottom - top),
        },
        "minimized": state["minimized"],
        "maximized": state["maximized"],
        "visible": bool(win32gui.IsWindowVisible(hwnd)),
        "process": _process_name(int(pid)),
        "foreground": win32gui.GetForegroundWindow() == hwnd,
    }


def _iter_windows() -> list[dict[str, Any]]:
    """Все видимые окна с непустым заголовком."""
    win32gui, _, win32process = _win32()
    windows: list[dict[str, Any]] = []
    foreground = int(win32gui.GetForegroundWindow())

    def _callback(hwnd: int, _param: Any) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return True
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width, height = int(right - left), int(bottom - top)
            if width <= 0 or height <= 0:
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            state = _window_state(hwnd)
            windows.append(
                {
                    "hwnd": int(hwnd),
                    "title": title,
                    "pid": int(pid),
                    "rect": {"left": int(left), "top": int(top), "width": width, "height": height},
                    "minimized": state["minimized"],
                    "maximized": state["maximized"],
                    "process": _process_name(int(pid)),
                    "foreground": int(hwnd) == foreground,
                }
            )
        except Exception:  # noqa: BLE001 - отдельное окно не должно ломать перечисление
            pass
        return True

    win32gui.EnumWindows(_callback, None)
    return windows


def _normalize_title(text: str) -> str:
    """Привести заголовок к сравнимому виду.

    Windows-программы пишут названия по-разному: "Micro/WIN", "Micro-WIN",
    "MicroWIN". Модель угадывает одну форму и ждёт окно, которого нет:
    на реальном прогоне два ожидания подряд съели 155 секунд. Поэтому
    сравниваем только буквы и цифры.
    """
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def _find_windows(title: str) -> list[dict[str, Any]]:
    """Окна, в заголовке которых есть подстрока (без учёта регистра).

    Сначала ищется точное совпадение подстроки, затем - совпадение без
    учёта разделителей ("MicroWIN" найдёт "STEP 7-Micro/WIN SMART").
    """
    needle = str(title or "").strip().lower()
    if not needle:
        return []
    windows = _iter_windows()
    exact = [window for window in windows if window["title"].lower() == needle]
    partial = [
        window
        for window in windows
        if needle in window["title"].lower() and window["title"].lower() != needle
    ]
    partial.sort(key=lambda window: (len(window["title"]), window["title"].lower()))

    if exact or partial:
        return exact + partial

    # Запасной проход: сравнение без разделителей.
    loose_needle = _normalize_title(title)
    if not loose_needle:
        return []
    loose = [
        window
        for window in windows
        if loose_needle in _normalize_title(window["title"])
    ]
    loose.sort(key=lambda window: (len(window["title"]), window["title"].lower()))
    return loose


def _is_own_window(hwnd: int) -> bool:
    """Принадлежит ли окно процессу самого клиента.

    Агент, свернувший или закрывший собственное окно, теряет экран и больше
    не видит ни цель, ни результат своих действий. На реальном прогоне
    клиент свернул себя на третьем шаге и потратил десять шагов на поиски
    окна STEP 7, которое просто было скрыто вместе с ним.
    """
    try:
        _win32gui, _win32con, win32process = _win32()
        _thread, pid = win32process.GetWindowThreadProcessId(int(hwnd))
        return int(pid) == int(os.getpid())
    except Exception:  # noqa: BLE001 - не смогли определить, не блокируем
        return False


OWN_WINDOW_HINT = (
    "Это окно самого клиента. Свернув или закрыв его, агент перестанет видеть экран. "
    "Управляйте целевой программой, а не окном клиента."
)


def _resolve_window(args: dict[str, Any]) -> tuple[int | None, dict[str, Any] | None, ToolResult | None]:
    """Найти окно по hwnd или по подстроке заголовка."""
    hwnd_arg = args.get("hwnd")
    if hwnd_arg is not None:
        try:
            hwnd = int(hwnd_arg)
        except (TypeError, ValueError):
            return None, None, ToolResult.fail("Параметр hwnd должен быть целым числом", error="bad_arguments")
        info = _window_info(hwnd)
        if info is None:
            return None, None, ToolResult.fail(f"Окно с hwnd={hwnd} не существует", error="window_not_found")
        return hwnd, info, None

    title = args.get("title")
    if title is None or not str(title).strip():
        return None, None, ToolResult.fail(
            "Укажите title (подстроку заголовка окна) или hwnd",
            error="bad_arguments",
        )
    matches = _find_windows(str(title))
    if not matches:
        return None, None, ToolResult.fail(
            f"Окно, в заголовке которого есть {str(title)!r}, не найдено",
            error="window_not_found",
        )
    best = matches[0]
    return int(best["hwnd"]), best, None


def _alt_tap() -> None:
    """Имитация нажатия Alt: снимает блокировку переднего плана Windows."""
    try:
        user32 = ctypes.windll.user32
        vk_menu = 0x12
        keyeventf_keyup = 0x0002
        user32.keybd_event(vk_menu, 0, 0, 0)
        user32.keybd_event(vk_menu, 0, keyeventf_keyup, 0)
    except Exception:  # noqa: BLE001 - не критично
        pass


def _force_foreground(hwnd: int) -> bool:
    """Вывести окно на передний план и проверить результат."""
    win32gui, _, win32process = _win32()
    try:
        import win32api
    except Exception:  # noqa: BLE001
        win32api = None

    if int(win32gui.GetForegroundWindow()) == int(hwnd):
        return True
    try:
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001 - штатное ограничение переднего плана
        pass
    if int(win32gui.GetForegroundWindow()) == int(hwnd):
        return True

    attached = False
    target_thread = 0
    try:
        target_thread = int(win32process.GetWindowThreadProcessId(hwnd)[0])
        if win32api is not None:
            current_thread = int(win32api.GetCurrentThreadId())
            if current_thread != target_thread:
                attached = bool(win32process.AttachThreadInput(target_thread, current_thread, True))
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        win32gui.SetFocus(hwnd)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if attached and win32api is not None:
            try:
                win32process.AttachThreadInput(target_thread, int(win32api.GetCurrentThreadId()), False)
            except Exception:  # noqa: BLE001
                pass

    if int(win32gui.GetForegroundWindow()) == int(hwnd):
        return True

    # Последняя попытка: Alt-тап + SetForegroundWindow.
    try:
        _alt_tap()
        time.sleep(0.05)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass
    return int(win32gui.GetForegroundWindow()) == int(hwnd)


def _tool_list_windows(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    limit = _clamp_int(args.get("limit"), 50, 1, MAX_WINDOWS)
    title_filter = str(args.get("title_filter") or "").strip().lower()
    try:
        windows = _iter_windows()
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Не удалось перечислить окна: {exc}",
            error=f"enum_windows_failed: {type(exc).__name__}: {exc}",
        )
    if title_filter:
        windows = [window for window in windows if title_filter in window["title"].lower()]
    total = len(windows)
    windows.sort(key=lambda window: (not window["foreground"], window["title"].lower()))
    shown = windows[:limit]
    return ToolResult(
        ok=True,
        summary=f"Найдено окон: {total}, показано {len(shown)}",
        data={"total": total, "limit": limit, "windows": shown},
    )


def _tool_focus_window(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    hwnd, info, fail = _resolve_window(args)
    if fail is not None:
        return fail
    assert hwnd is not None and info is not None
    win32gui, win32con, _ = _win32()
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.15)
        activated = False
        for _attempt in range(3):
            if _force_foreground(hwnd):
                activated = True
                break
            time.sleep(0.1)
        current = int(win32gui.GetForegroundWindow())
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Не удалось активировать окно {info['title']!r}: {exc}",
            error=f"focus_failed: {type(exc).__name__}: {exc}",
        )
    if not activated:
        return ToolResult.fail(
            f"Окно {info['title']!r} не стало активным (сейчас активно hwnd={current})",
            error="focus_failed",
            hwnd=hwnd,
            foreground_hwnd=current,
        )
    return ToolResult(
        ok=True,
        summary=f"Окно {info['title']!r} активировано",
        data={"hwnd": hwnd, "title": info["title"], "pid": info["pid"], "foreground": True},
    )


def _change_window_state(ctx: ToolContext, args: dict[str, Any], action: str) -> ToolResult:
    hwnd, info, fail = _resolve_window(args)
    if fail is not None:
        return fail
    assert hwnd is not None and info is not None
    if action == "minimize" and _is_own_window(hwnd):
        return ToolResult.fail(
            "Нельзя свернуть собственное окно клиента: " + OWN_WINDOW_HINT,
            error="own_window_blocked",
            hwnd=hwnd,
        )
    win32gui, win32con, _ = _win32()
    commands = {
        "minimize": win32con.SW_MINIMIZE,
        "maximize": win32con.SW_MAXIMIZE,
        "restore": win32con.SW_RESTORE,
    }
    labels = {"minimize": "свёрнуто", "maximize": "развёрнуто", "restore": "восстановлено"}
    try:
        win32gui.ShowWindow(hwnd, commands[action])
        time.sleep(0.2)
        state = _window_state(hwnd)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Не удалось изменить состояние окна {info['title']!r}: {exc}",
            error=f"window_state_failed: {type(exc).__name__}: {exc}",
        )
    expected = {"minimize": state["minimized"], "maximize": state["maximized"], "restore": not state["minimized"] and not state["maximized"]}
    if not expected[action]:
        return ToolResult.fail(
            f"Окно {info['title']!r} не удалось {labels[action]} (состояние: minimized={state['minimized']}, maximized={state['maximized']})",
            error="window_state_failed",
            hwnd=hwnd,
            state=state,
        )
    return ToolResult(
        ok=True,
        summary=f"Окно {info['title']!r} {labels[action]}",
        data={"hwnd": hwnd, "title": info["title"], "state": state},
    )


def _tool_minimize_window(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _change_window_state(ctx, args, "minimize")


def _tool_maximize_window(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _change_window_state(ctx, args, "maximize")


def _tool_restore_window(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _change_window_state(ctx, args, "restore")


def _tool_close_window(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    hwnd, info, fail = _resolve_window(args)
    if fail is not None:
        return fail
    assert hwnd is not None and info is not None
    if _is_own_window(hwnd):
        return ToolResult.fail(
            "Нельзя закрыть собственное окно клиента: " + OWN_WINDOW_HINT,
            error="own_window_blocked",
            hwnd=hwnd,
        )
    win32gui, win32con, _ = _win32()
    timeout = _clamp_float(args.get("timeout"), 2.0, 0.2, 30.0)
    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Не удалось отправить запрос на закрытие окна {info['title']!r}: {exc}",
            error=f"close_failed: {type(exc).__name__}: {exc}",
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not win32gui.IsWindow(hwnd):
            return ToolResult(
                ok=True,
                summary=f"Окно {info['title']!r} закрыто",
                data={"hwnd": hwnd, "title": info["title"], "closed": True},
            )
        time.sleep(0.1)
    still_open = bool(win32gui.IsWindow(hwnd))
    return ToolResult(
        ok=True,
        summary=(
            f"Окно {info['title']!r} получило запрос на закрытие, но ещё открыто "
            f"(возможно, приложение просит подтверждение)"
        ),
        data={"hwnd": hwnd, "title": info["title"], "closed": not still_open},
    )


def _tool_move_window(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    hwnd, info, fail = _resolve_window(args)
    if fail is not None:
        return fail
    assert hwnd is not None and info is not None
    wants_move = args.get("x") is not None or args.get("y") is not None
    wants_resize = args.get("width") is not None or args.get("height") is not None
    if not wants_move and not wants_resize:
        return ToolResult.fail(
            "Укажите x/y (позиция) и/или width/height (размер) в пикселях изображения",
            error="bad_arguments",
        )
    shot, fail = _shot_or_fail(ctx)
    if fail is not None:
        return fail
    assert shot is not None
    scale = shot.scale or 1.0

    win32gui, win32con, _ = _win32()
    try:
        if _window_state(hwnd)["maximized"]:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        target_x = int(left)
        target_y = int(top)
        target_w = int(right - left)
        target_h = int(bottom - top)
        if args.get("x") is not None:
            target_x = shot.to_absolute(float(args["x"]), 0.0, clamp=False)[0]
        if args.get("y") is not None:
            target_y = shot.to_absolute(0.0, float(args["y"]), clamp=False)[1]
        if args.get("width") is not None:
            target_w = max(50, int(round(float(args["width"]) / scale)))
        if args.get("height") is not None:
            target_h = max(50, int(round(float(args["height"]) / scale)))
        win32gui.SetWindowPos(
            hwnd,
            0,
            target_x,
            target_y,
            target_w,
            target_h,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        time.sleep(0.15)
        new_left, new_top, new_right, new_bottom = win32gui.GetWindowRect(hwnd)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Не удалось переместить окно {info['title']!r}: {exc}",
            error=f"move_failed: {type(exc).__name__}: {exc}",
        )
    actual = {
        "left": int(new_left),
        "top": int(new_top),
        "width": int(new_right - new_left),
        "height": int(new_bottom - new_top),
    }
    applied = (
        abs(actual["left"] - target_x) <= 8
        and abs(actual["top"] - target_y) <= 8
        and abs(actual["width"] - target_w) <= 8
        and abs(actual["height"] - target_h) <= 8
    )
    return ToolResult(
        ok=True,
        summary=(
            f"Окно {info['title']!r} перемещено в ({actual['left']}, {actual['top']}) "
            f"размером {actual['width']}x{actual['height']}"
        ),
        data={
            "hwnd": hwnd,
            "title": info["title"],
            "requested": {"left": target_x, "top": target_y, "width": target_w, "height": target_h},
            "actual": actual,
            "applied": applied,
        },
    )


def _tool_wait_for_window(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    title = str(args.get("title") or "").strip()
    if not title:
        return ToolResult.fail("Не хватает параметра title (подстрока заголовка)", error="bad_arguments")
    timeout = _clamp_float(args.get("timeout"), 10.0, 0.5, 120.0)
    started = time.monotonic()
    deadline = started + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            matches = _find_windows(title)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            matches = []
        if matches:
            window = matches[0]
            return ToolResult(
                ok=True,
                summary=f"Окно {window['title']!r} появилось (hwnd={window['hwnd']})",
                data={"window": window, "waited": round(time.monotonic() - started, 2)},
            )
        time.sleep(0.2)
    error = "window_timeout" if last_error is None else f"window_timeout: {last_error}"
    # Что реально открыто: иначе модель гадает следующий заголовок и снова
    # ждёт впустую. Одно такое ожидание стоило 60-90 секунд.
    try:
        visible = _iter_windows()
    except Exception:  # noqa: BLE001
        visible = []
    titles = [window["title"] for window in visible if window.get("title")][:15]
    hint = ""
    if titles:
        hint = " Сейчас открыты окна: " + "; ".join(repr(item) for item in titles) + "."
    return ToolResult.fail(
        f"Окно с заголовком, содержащим {title!r}, не появилось за {timeout:g} с."
        + hint
        + " Возьмите точное имя из списка или используйте hwnd.",
        error=error,
        title=title,
        timeout=timeout,
        visible_titles=titles,
    )


def _tool_launch_app(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    target = str(args.get("target") or "").strip()
    if not target:
        return ToolResult.fail("Не хватает параметра target (путь к программе или документу)", error="bad_arguments")
    raw_args = args.get("args") or []
    if isinstance(raw_args, str):
        raw_args = [raw_args]
    if not isinstance(raw_args, (list, tuple)):
        return ToolResult.fail("Параметр args должен быть списком строк", error="bad_arguments")
    command = [target, *[str(item) for item in raw_args]]
    cwd = args.get("cwd")
    cwd_str = str(cwd) if cwd else None
    if cwd_str is not None and not os.path.isdir(cwd_str):
        return ToolResult.fail(f"Рабочая папка не найдена: {cwd_str}", error="bad_arguments")

    popen_error: Exception | None = None
    try:
        proc = subprocess.Popen(command, cwd=cwd_str)
        return ToolResult(
            ok=True,
            summary=f"Запущен процесс {target!r} (pid={proc.pid})",
            data={"target": target, "args": command[1:], "pid": int(proc.pid), "method": "popen"},
        )
    except (OSError, ValueError) as exc:
        popen_error = exc

    # Запасной путь: оболочка Windows умеет открывать документы и URI.
    try:
        os.startfile(target)  # type: ignore[attr-defined]
        return ToolResult(
            ok=True,
            summary=f"Открыто через оболочку Windows: {target!r}",
            data={"target": target, "method": "startfile"},
        )
    except (OSError, AttributeError) as exc:
        return ToolResult.fail(
            f"Не удалось запустить {target!r}: {exc}",
            error=f"launch_failed: popen={popen_error}; startfile={type(exc).__name__}: {exc}",
        )


# --------------------------------------------------------------------------- #
# процессы
# --------------------------------------------------------------------------- #
def _is_protected(pid: int, name: str | None) -> str | None:
    """Причина, по которой процесс нельзя завершать, или None."""
    if pid in PROTECTED_PIDS:
        return f"pid={pid} - системный процесс"
    if pid == os.getpid():
        return "это процесс самого PC Agent"
    if name and name.strip().lower() in PROTECTED_PROCESS_NAMES:
        return f"{name} - критичный системный процесс"
    return None


def _terminate_process(proc: Any, force: bool, timeout: float) -> dict[str, Any]:
    """Завершить процесс: сначала terminate, при необходимости kill."""
    psutil = _psutil()
    pid = int(proc.pid)
    name: str | None = None
    try:
        name = proc.name()
    except Exception:  # noqa: BLE001
        name = None
    try:
        proc.terminate()
    except psutil.NoSuchProcess:
        return {"pid": pid, "name": name, "result": "already_gone"}
    except psutil.AccessDenied as exc:
        return {"pid": pid, "name": name, "result": "access_denied", "error": str(exc)}
    try:
        proc.wait(timeout=timeout)
        return {"pid": pid, "name": name, "result": "terminated"}
    except psutil.TimeoutExpired:
        if not force:
            return {"pid": pid, "name": name, "result": "still_running"}
    except psutil.NoSuchProcess:
        return {"pid": pid, "name": name, "result": "terminated"}
    try:
        proc.kill()
        proc.wait(timeout=3)
        return {"pid": pid, "name": name, "result": "killed"}
    except psutil.NoSuchProcess:
        return {"pid": pid, "name": name, "result": "terminated"}
    except psutil.AccessDenied as exc:
        return {"pid": pid, "name": name, "result": "access_denied", "error": str(exc)}


def _tool_kill_process(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    psutil = _psutil()
    pid_arg = args.get("pid")
    name_arg = args.get("name")
    force = bool(args.get("force", True))
    timeout = _clamp_float(args.get("timeout"), 3.0, 0.2, 30.0)

    if pid_arg is None and (name_arg is None or not str(name_arg).strip()):
        return ToolResult.fail("Укажите pid или name процесса", error="bad_arguments")

    if pid_arg is not None:
        try:
            pid = int(pid_arg)
        except (TypeError, ValueError):
            return ToolResult.fail("Параметр pid должен быть целым числом", error="bad_arguments")
        try:
            proc = psutil.Process(pid)
            name = proc.name()
        except psutil.NoSuchProcess:
            return ToolResult.fail(f"Процесс с pid={pid} не найден", error="process_not_found", pid=pid)
        except psutil.AccessDenied as exc:
            return ToolResult.fail(
                f"Нет доступа к процессу pid={pid}: {exc}",
                error="access_denied",
                pid=pid,
            )
        reason = _is_protected(pid, name)
        if reason:
            return ToolResult.fail(f"Завершение процесса pid={pid} запрещено: {reason}", error="protected_process", pid=pid)
        outcome = _terminate_process(proc, force, timeout)
        if outcome["result"] in ("terminated", "killed", "already_gone"):
            return ToolResult(
                ok=True,
                summary=f"Процесс {name or '?'} (pid={pid}) завершён ({outcome['result']})",
                data=outcome,
            )
        details = {key: value for key, value in outcome.items() if key != "error"}
        return ToolResult.fail(
            f"Не удалось завершить процесс pid={pid}: {outcome['result']}",
            error=outcome["result"],
            **details,
        )

    needle = str(name_arg).strip().lower()
    needle_stem = os.path.splitext(needle)[0]
    killed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            info = proc.info
            pid = int(info["pid"])
            name = str(info.get("name") or "")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if os.path.splitext(name.strip().lower())[0] != needle_stem:
            continue
        reason = _is_protected(pid, name)
        if reason:
            skipped.append({"pid": pid, "name": name, "reason": reason})
            continue
        killed.append(_terminate_process(proc, force, timeout))

    if not killed and not skipped:
        return ToolResult.fail(f"Процессы с именем {name_arg!r} не найдены", error="process_not_found")
    if not killed and skipped:
        return ToolResult.fail(
            f"Все найденные процессы с именем {name_arg!r} защищены: {skipped[0]['reason']}",
            error="protected_process",
            skipped=skipped,
        )
    done = [item for item in killed if item["result"] in ("terminated", "killed", "already_gone")]
    failed = [item for item in killed if item["result"] not in ("terminated", "killed", "already_gone")]
    summary = f"Завершено процессов {name_arg!r}: {len(done)}"
    if failed:
        summary += f", не удалось: {len(failed)}"
    if skipped:
        summary += f", пропущено защищённых: {len(skipped)}"
    return ToolResult(
        ok=bool(done),
        summary=summary,
        data={"killed": killed, "skipped": skipped, "failed": failed},
        error=None if done else "kill_failed",
    )


def _tool_list_processes(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    psutil = _psutil()
    limit = _clamp_int(args.get("limit"), 40, 1, 300)
    name_filter = str(args.get("name_filter") or "").strip().lower()
    items: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "memory_info", "cpu_percent"]):
        try:
            info = proc.info
            name = str(info.get("name") or "")
            if name_filter and name_filter not in name.lower():
                continue
            memory = info.get("memory_info")
            items.append(
                {
                    "pid": int(info["pid"]),
                    "name": name,
                    "memory_mb": round(float(memory.rss) / (1024 * 1024), 1) if memory else None,
                    "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 1),
                    "exe": info.get("exe"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    total = len(items)
    items.sort(key=lambda item: item["memory_mb"] or 0.0, reverse=True)
    shown = items[:limit]
    return ToolResult(
        ok=True,
        summary=f"Процессов: {total}, показано {len(shown)} (сортировка по памяти)",
        data={"total": total, "limit": limit, "processes": shown},
    )


# --------------------------------------------------------------------------- #
# регистрация
# --------------------------------------------------------------------------- #
_WINDOW_TARGET_PROPS: dict[str, Any] = {
    "title": prop_string("Substring of the window title (case-insensitive)"),
    "hwnd": prop_integer("Window handle (use instead of title when known)"),
}


def register(registry: ToolRegistry) -> None:
    """Зарегистрировать инструменты категории windows."""
    registry.add(
        name="list_windows",
        description=(
            "List visible top-level windows with their title, hwnd, process id, rectangle and state. "
            "The active window comes first. Optionally filter by a title substring."
        ),
        parameters=schema(
            {
                "title_filter": prop_string("Optional case-insensitive substring to filter titles"),
                "limit": prop_integer("Maximum number of windows to return", minimum=1, maximum=MAX_WINDOWS),
            }
        ),
        risk=Risk.READ,
        category=CATEGORY,
    )(_tool_list_windows)

    registry.add(
        name="focus_window",
        description=(
            "Bring a window to the foreground and make it active. Find the window by a title "
            "substring or by hwnd. A minimized window is restored first."
        ),
        parameters=schema(dict(_WINDOW_TARGET_PROPS)),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_focus_window)

    registry.add(
        name="minimize_window",
        description="Minimize a window found by title substring or hwnd.",
        parameters=schema(dict(_WINDOW_TARGET_PROPS)),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_minimize_window)

    registry.add(
        name="maximize_window",
        description="Maximize a window found by title substring or hwnd.",
        parameters=schema(dict(_WINDOW_TARGET_PROPS)),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_maximize_window)

    registry.add(
        name="restore_window",
        description="Restore a minimized or maximized window to its normal size.",
        parameters=schema(dict(_WINDOW_TARGET_PROPS)),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_restore_window)

    registry.add(
        name="close_window",
        description=(
            "Ask a window to close by sending WM_CLOSE. Use it only when the user really wants "
            "to close the application; unsaved data may be lost."
        ),
        parameters=schema(
            {
                **_WINDOW_TARGET_PROPS,
                "timeout": {"type": "number", "description": "Seconds to wait for the window to disappear", "minimum": 0.2, "maximum": 30},
            }
        ),
        risk=Risk.DESTRUCTIVE,
        category=CATEGORY,
    )(_tool_close_window)

    registry.add(
        name="move_window",
        description=(
            "Move and/or resize a window. x, y, width and height are given in screenshot image "
            "pixels and converted to real desktop pixels; omitted values keep the current geometry."
        ),
        parameters=schema(
            {
                **_WINDOW_TARGET_PROPS,
                "x": prop_integer("New window left edge in screenshot image pixels"),
                "y": prop_integer("New window top edge in screenshot image pixels"),
                "width": prop_integer("New window width in screenshot image pixels", minimum=50),
                "height": prop_integer("New window height in screenshot image pixels", minimum=50),
            }
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_move_window)

    registry.add(
        name="wait_for_window",
        description=(
            "Wait until a window whose title contains the given substring appears. Useful after "
            "launching an application."
        ),
        parameters=schema(
            {
                "title": prop_string("Substring of the expected window title (case-insensitive)"),
                "timeout": {"type": "number", "description": "Maximum wait in seconds", "minimum": 0.5, "maximum": 120},
            },
            required=["title"],
        ),
        risk=Risk.READ,
        category=CATEGORY,
    )(_tool_wait_for_window)

    registry.add(
        name="launch_app",
        description=(
            "Launch an application, document or executable. target is an executable name or path "
            "(for example 'notepad.exe' or 'C:/Windows/notepad.exe'); args is an optional list of "
            "command line arguments."
        ),
        parameters=schema(
            {
                "target": prop_string("Executable name or full path to launch"),
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional command line arguments",
                },
                "cwd": prop_string("Optional working directory"),
            },
            required=["target"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_launch_app)

    registry.add(
        name="kill_process",
        description=(
            "Terminate a process by pid or by exact process name. Critical Windows processes and "
            "the agent itself are protected and cannot be killed."
        ),
        parameters=schema(
            {
                "pid": prop_integer("Process id to terminate"),
                "name": prop_string("Process name to terminate, for example 'notepad.exe'"),
                "force": prop_boolean("Kill the process if it does not exit after terminate (default true)"),
                "timeout": {"type": "number", "description": "Seconds to wait for a graceful exit", "minimum": 0.2, "maximum": 30},
            }
        ),
        risk=Risk.DESTRUCTIVE,
        category=CATEGORY,
    )(_tool_kill_process)

    registry.add(
        name="list_processes",
        description=(
            "List running processes with pid, name, memory usage and executable path, sorted by "
            "memory usage. Optionally filter by a process name substring."
        ),
        parameters=schema(
            {
                "name_filter": prop_string("Optional case-insensitive substring of the process name"),
                "limit": prop_integer("Maximum number of processes to return", minimum=1, maximum=300),
            }
        ),
        risk=Risk.READ,
        category=CATEGORY,
    )(_tool_list_processes)
