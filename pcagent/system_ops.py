"""Системные операции (категория system): команды, сведения о ПК, буфер обмена.

Все потенциально опасные действия помечены Risk.WRITE / Risk.DESTRUCTIVE -
подтверждение и запреты выполняет ToolRegistry через Policy.
"""

from __future__ import annotations

import ctypes
import datetime as dt
import locale
import os
import platform
import subprocess
import sys
import time
import webbrowser
from typing import Any

from pcagent import safety
from pcagent.interfaces import Risk
from pcagent.tools.base import (
    ToolContext,
    ToolRegistry,
    ToolResult,
    prop_number,
    prop_string,
    schema,
)

CATEGORY = "system"
MAX_OUTPUT = 4000
SHELLS: tuple[str, ...] = ("powershell", "cmd", "pwsh")
URI_SCHEMES: tuple[str, ...] = ("http", "https", "mailto")


# --------------------------------------------------------------------------- #
# вспомогательные функции
# --------------------------------------------------------------------------- #
def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        result = float(value) if value is not None else default
    except (TypeError, ValueError):
        result = default
    return max(low, min(high, result))


def _oem_codepage() -> str | None:
    """Кодовая страница консоли Windows (например cp866)."""
    try:
        code_page = int(ctypes.windll.kernel32.GetOEMCP())
    except Exception:  # noqa: BLE001 - не Windows или нет доступа
        return None
    return f"cp{code_page}" if code_page else None


def _decode_output(raw: bytes | None) -> str:
    """Декодировать вывод процесса: UTF-8, затем консольная кодовая страница."""
    if not raw:
        return ""
    candidates = ["utf-8"]
    oem = _oem_codepage()
    if oem:
        candidates.append(oem)
    candidates.append(locale.getpreferredencoding(False))
    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _truncate(text: str, limit: int = MAX_OUTPUT) -> tuple[str, bool]:
    """Обрезать длинный вывод, оставив пометку."""
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n...[вывод обрезан]", True


def _build_argv(shell: str, command: str) -> list[str]:
    if shell == "cmd":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command]
    if shell == "pwsh":
        return ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]


def _create_no_window_flag() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _pyperclip():
    import pyperclip

    return pyperclip


# --------------------------------------------------------------------------- #
# run_command
# --------------------------------------------------------------------------- #
def _tool_run_command(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    command = str(args.get("command") or "").strip()
    if not command:
        return ToolResult.fail("Не хватает параметра command (команда оболочки)", error="bad_arguments")
    if not bool(getattr(ctx.config, "allow_shell", True)):
        return ToolResult.fail(
            "Выполнение команд отключено в конфигурации (allow_shell=false)",
            error="shell_disabled",
        )
    emulation = safety.detect_input_emulation(command)
    if emulation:
        return ToolResult.fail(
            f"Команда содержит прямое управление вводом ({emulation}). "
            + safety.INPUT_TOOL_HINT,
            error="input_emulation_blocked",
        )
    shell = str(args.get("shell") or "powershell").strip().lower()
    if shell not in SHELLS:
        return ToolResult.fail(
            f"Оболочка {shell!r} не поддерживается, допустимо: {', '.join(SHELLS)}",
            error="bad_shell",
        )
    timeout = _clamp_float(args.get("timeout"), 60.0, 1.0, 600.0)
    cwd = args.get("cwd")
    cwd_str = str(cwd) if cwd else None
    if cwd_str is not None and not os.path.isdir(cwd_str):
        return ToolResult.fail(f"Рабочая папка не найдена: {cwd_str}", error="bad_arguments")

    argv = _build_argv(shell, command)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            cwd=cwd_str,
            creationflags=_create_no_window_flag(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_cut = _truncate(_decode_output(exc.stdout))
        stderr, stderr_cut = _truncate(_decode_output(exc.stderr))
        return ToolResult.fail(
            f"Команда не завершилась за {timeout:g} с и была прервана",
            error="timeout",
            command=command,
            shell=shell,
            timeout=True,
            stdout=stdout,
            stderr=stderr,
            truncated={"stdout": stdout_cut, "stderr": stderr_cut},
        )
    except FileNotFoundError as exc:
        return ToolResult.fail(
            f"Оболочка {shell!r} не найдена: {exc}",
            error="shell_not_found",
        )
    except OSError as exc:
        return ToolResult.fail(
            f"Не удалось запустить команду: {exc}",
            error=f"run_failed: {type(exc).__name__}: {exc}",
        )

    stdout, stdout_cut = _truncate(_decode_output(proc.stdout))
    stderr, stderr_cut = _truncate(_decode_output(proc.stderr))
    data = {
        "command": command,
        "shell": shell,
        "exit_code": int(proc.returncode),
        "stdout": stdout,
        "stderr": stderr,
        "truncated": {"stdout": stdout_cut, "stderr": stderr_cut},
        "timeout": False,
    }
    if proc.returncode != 0:
        return ToolResult.fail(
            f"Команда завершилась с кодом {proc.returncode}",
            error=f"exit_code_{proc.returncode}",
            **data,
        )
    return ToolResult(
        ok=True,
        summary=f"Команда {shell} выполнена (код 0), выведено символов: {len(stdout)}",
        data=data,
    )


# --------------------------------------------------------------------------- #
# сведения о системе
# --------------------------------------------------------------------------- #
def _primary_resolution(ctx: ToolContext) -> tuple[int | None, int | None, str | None]:
    screen = getattr(ctx, "screen", None)
    if screen is not None:
        try:
            width, height = screen.size(getattr(ctx.config, "monitor", 0))
            if width and height:
                return int(width), int(height), "screen_service"
        except Exception:  # noqa: BLE001 - переходим к Win32
            pass
    try:
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1)), "win32"
    except Exception:  # noqa: BLE001
        return None, None, None


def _monitors(ctx: ToolContext) -> list[dict[str, Any]]:
    screen = getattr(ctx, "screen", None)
    if screen is None:
        return []
    try:
        return [monitor.as_dict() for monitor in screen.monitors()]
    except Exception:  # noqa: BLE001
        return []


def _gb(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / (1024 ** 3), 2)


def _tool_get_system_info(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    psutil = None
    try:
        import psutil

        psutil = psutil
    except Exception:  # noqa: BLE001 - часть сведений будет недоступна
        psutil = None

    width, height, resolution_source = _primary_resolution(ctx)
    info: dict[str, Any] = {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "computer_name": os.environ.get("COMPUTERNAME") or platform.node(),
        "user": os.environ.get("USERNAME") or _safe_user(),
        "python": sys.version.split()[0],
        "now": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": time.strftime("%Z"),
        "screen": {
            "width": width,
            "height": height,
            "source": resolution_source,
            "monitors": _monitors(ctx),
        },
        "is_admin": _is_admin(),
    }

    if psutil is not None:
        try:
            memory = psutil.virtual_memory()
            info["memory"] = {
                "total_gb": _gb(memory.total),
                "available_gb": _gb(memory.available),
                "percent": float(memory.percent),
            }
        except Exception:  # noqa: BLE001
            info["memory"] = None
        try:
            root = (os.environ.get("SystemDrive") or "C:") + "\\"
            disk = psutil.disk_usage(root)
            info["disk"] = {
                "root": root,
                "total_gb": _gb(disk.total),
                "used_gb": _gb(disk.used),
                "free_gb": _gb(disk.free),
                "percent": float(disk.percent),
            }
        except Exception:  # noqa: BLE001
            info["disk"] = None
        try:
            battery = psutil.sensors_battery()
            info["battery"] = (
                None
                if battery is None
                else {
                    "percent": float(battery.percent),
                    "plugged": bool(battery.power_plugged),
                }
            )
        except Exception:  # noqa: BLE001
            info["battery"] = None
        try:
            info["uptime_hours"] = round((time.time() - float(psutil.boot_time())) / 3600.0, 2)
        except Exception:  # noqa: BLE001
            info["uptime_hours"] = None
        try:
            info["cpu"] = {
                "logical": int(psutil.cpu_count(logical=True) or 0),
                "physical": int(psutil.cpu_count(logical=False) or 0),
                "percent": float(psutil.cpu_percent(interval=0.1)),
            }
        except Exception:  # noqa: BLE001
            info["cpu"] = None
    else:
        info["memory"] = None
        info["disk"] = None
        info["battery"] = None
        info["uptime_hours"] = None
        info["cpu"] = None

    summary = (
        f"{info['os']['system']} {info['os']['release']}, ПК {info['computer_name']}, "
        f"пользователь {info['user']}, экран {width}x{height}"
    )
    return ToolResult(ok=True, summary=summary, data=info)


def _safe_user() -> str:
    try:
        import getpass

        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return ""


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# оболочка Windows: пути и URI
# --------------------------------------------------------------------------- #
def _tool_open_path(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    raw_path = args.get("path")
    if raw_path is None or not str(raw_path).strip():
        return ToolResult.fail("Не хватает параметра path (путь к файлу или папке)", error="bad_arguments")
    path = os.path.expandvars(os.path.expanduser(str(raw_path).strip().strip('"')))
    if not os.path.exists(path):
        return ToolResult.fail(f"Путь не найден: {path}", error="path_not_found", path=path)
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except (OSError, AttributeError) as exc:
        return ToolResult.fail(
            f"Не удалось открыть {path!r}: {exc}",
            error=f"open_failed: {type(exc).__name__}: {exc}",
        )
    return ToolResult(
        ok=True,
        summary=f"Открыто средством Windows: {path}",
        data={"path": path, "is_dir": os.path.isdir(path)},
    )


def _tool_start_uri(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    raw_uri = args.get("uri")
    if raw_uri is None or not str(raw_uri).strip():
        return ToolResult.fail("Не хватает параметра uri (например https://example.com)", error="bad_arguments")
    uri = str(raw_uri).strip()
    scheme = uri.split(":", 1)[0].strip().lower() if ":" in uri else ""
    if scheme not in URI_SCHEMES:
        return ToolResult.fail(
            f"Схема {scheme!r} не разрешена, допустимо: {', '.join(URI_SCHEMES)}",
            error="bad_uri",
        )
    try:
        opened = bool(webbrowser.open(uri))
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Не удалось открыть {uri!r}: {exc}",
            error=f"open_failed: {type(exc).__name__}: {exc}",
        )
    if not opened:
        return ToolResult.fail(
            f"Браузер по умолчанию не открыл {uri!r}",
            error="open_failed",
        )
    return ToolResult(ok=True, summary=f"Открыт адрес {uri}", data={"uri": uri})


# --------------------------------------------------------------------------- #
# буфер обмена
# --------------------------------------------------------------------------- #
def _tool_clipboard_get(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    try:
        text = _pyperclip().paste()
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Не удалось прочитать буфер обмена: {exc}",
            error=f"clipboard_failed: {type(exc).__name__}: {exc}",
        )
    text = "" if text is None else str(text)
    shown, truncated = _truncate(text)
    return ToolResult(
        ok=True,
        summary=f"Буфер обмена: {len(text)} символов",
        data={"text": shown, "length": len(text), "truncated": truncated},
    )


def _tool_clipboard_set(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if "text" not in args or args.get("text") is None:
        return ToolResult.fail("Не хватает параметра text", error="bad_arguments")
    text = str(args.get("text"))
    try:
        _pyperclip().copy(text)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Не удалось записать текст в буфер обмена: {exc}",
            error=f"clipboard_failed: {type(exc).__name__}: {exc}",
        )
    return ToolResult(
        ok=True,
        summary=f"В буфер обмена записано {len(text)} символов",
        data={"length": len(text)},
    )


# --------------------------------------------------------------------------- #
# регистрация
# --------------------------------------------------------------------------- #
def register(registry: ToolRegistry) -> None:
    """Зарегистрировать инструменты категории system."""
    registry.add(
        name="run_command",
        description=(
            "Run a shell command on this Windows PC and return its exit code, stdout and stderr. "
            "Output is truncated to 4000 characters. Dangerous system commands are blocked by "
            "the safety policy. Prefer cmd for simple commands and powershell for Windows "
            "management tasks."
        ),
        parameters=schema(
            {
                "command": prop_string("Command line to execute"),
                "shell": prop_string("Shell to use", enum=list(SHELLS)),
                "timeout": prop_number("Maximum execution time in seconds", minimum=1, maximum=600),
                "cwd": prop_string("Optional working directory"),
            },
            required=["command"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_run_command)

    registry.add(
        name="get_system_info",
        description=(
            "Get basic information about this computer: Windows version, computer name, user, "
            "screen resolution and monitors, CPU, memory, disk, battery and uptime."
        ),
        parameters=schema({}),
        risk=Risk.READ,
        category=CATEGORY,
    )(_tool_get_system_info)

    registry.add(
        name="open_path",
        description="Open a file or folder with the default Windows application.",
        parameters=schema(
            {"path": prop_string("Existing file or folder path")},
            required=["path"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_open_path)

    registry.add(
        name="start_uri",
        description=(
            "Open a web address or mail link in the default browser. Allowed schemes: http, "
            "https, mailto."
        ),
        parameters=schema(
            {"uri": prop_string("URI to open, for example https://example.com")},
            required=["uri"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_start_uri)

    registry.add(
        name="clipboard_get",
        description="Read the current clipboard text (truncated to 4000 characters).",
        parameters=schema({}),
        risk=Risk.READ,
        category=CATEGORY,
    )(_tool_clipboard_get)

    registry.add(
        name="clipboard_set",
        description="Replace the clipboard content with the given text.",
        parameters=schema(
            {"text": prop_string("Text to place into the clipboard")},
            required=["text"],
        ),
        risk=Risk.WRITE,
        category=CATEGORY,
    )(_tool_clipboard_set)
