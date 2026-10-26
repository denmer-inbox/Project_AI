"""Консольные инструменты GUI: скрипты PowerShell, cmd и Python.

Задача модуля - убрать лишние снимки экрана из работы агента. Большую
часть действий на Windows можно сделать текстом: запустить программу,
проверить состояние, найти файл, прочитать настройку. Экран нужен только
там, где программой нельзя управлять иначе, чем визуально.

Модуль дополняет уже существующий run_command (одна строка команды) и
добавляет run_script: многострочный сценарий записывается во временный
файл и выполняется нужным интерпретатором.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from pcagent import safety
from pcagent.interfaces import Risk
from pcagent.tools.base import (
    ToolContext,
    ToolResult,
    prop_boolean,
    prop_number,
    prop_string,
    schema,
)

#: Языки сценариев и их расширения.
LANGUAGES: dict[str, str] = {
    "powershell": ".ps1",
    "cmd": ".cmd",
    "python": ".py",
}

#: Категория инструментов: та же, что у системных операций.
CATEGORY = "system"

#: Сколько символов вывода отдавать модели.
MAX_OUTPUT_CHARS = 4000


def _decode(data: Any) -> str:
    """Декодировать вывод процесса с учётом кодировки Windows."""
    if not data:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """Обрезать вывод, сохранив начало и конец."""
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return text[:half] + "\n... (вывод сокращён) ...\n" + text[-half:], True


def _no_window_flag() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _build_argv(language: str, script_path: Path) -> list[str]:
    """Командная строка для запуска файла сценария."""
    if language == "powershell":
        return [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
    if language == "cmd":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(script_path)]
    return [sys.executable, str(script_path)]


def _script_dir(config: Any) -> Path:
    """Папка для временных сценариев."""
    extra = getattr(config, "extra", None) or {}
    custom = extra.get("script_dir")
    if custom:
        try:
            folder = Path(str(custom))
            folder.mkdir(parents=True, exist_ok=True)
            return folder
        except Exception:  # noqa: BLE001 - вернёмся к системной папке
            pass
    folder = Path(tempfile.gettempdir()) / "pcagent_scripts"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_script(folder: Path, language: str, text: str) -> Path:
    """Записать сценарий в файл с уникальным именем."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = LANGUAGES[language]
    target = folder / f"script-{stamp}-{os.getpid()}{suffix}"
    # PowerShell 5.1 читает .ps1 без BOM как ANSI и ломает кириллицу,
    # поэтому там BOM нужен. cmd же воспринимает BOM как часть первой
    # команды и печатает его в вывод - ему BOM только мешает.
    encoding = "utf-8-sig" if language == "powershell" else "utf-8"
    target.write_text(text, encoding=encoding, newline="\r\n" if language == "cmd" else None)
    return target


def _tool_run_script(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Записать многострочный сценарий и выполнить его."""
    text = str(args.get("script") or "")
    if not text.strip():
        return ToolResult.fail(
            "Не хватает параметра script (текст сценария)", error="bad_arguments"
        )
    if not bool(getattr(ctx.config, "allow_shell", True)):
        return ToolResult.fail(
            "Выполнение сценариев отключено в конфигурации (allow_shell=false)",
            error="shell_disabled",
        )

    # Сценарий не должен подменять инструменты ввода: иначе агент обходит
    # политику безопасности и проверку координат.
    emulation = safety.detect_input_emulation(text)
    if emulation:
        return ToolResult.fail(
            f"Сценарий содержит прямое управление вводом ({emulation}). "
            + safety.INPUT_TOOL_HINT,
            error="input_emulation_blocked",
        )

    language = str(args.get("language") or "powershell").strip().lower()
    if language not in LANGUAGES:
        return ToolResult.fail(
            f"Язык {language!r} не поддерживается, допустимо: {', '.join(LANGUAGES)}",
            error="bad_language",
        )

    try:
        timeout = float(args.get("timeout") or 120.0)
    except (TypeError, ValueError):
        timeout = 120.0
    timeout = max(1.0, min(600.0, timeout))

    cwd_arg = args.get("cwd")
    cwd = str(cwd_arg) if cwd_arg else None
    if cwd is not None and not os.path.isdir(cwd):
        return ToolResult.fail(f"Рабочая папка не найдена: {cwd}", error="bad_arguments")

    keep = bool(args.get("keep_file", False))
    folder = _script_dir(ctx.config)
    try:
        script_path = _write_script(folder, language, text)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(f"Не удалось записать сценарий: {exc}", error="write_failed")

    if bool(getattr(ctx, "dry_run", False)):
        return ToolResult(
            ok=True,
            summary=(
                f"Dry-run: сценарий {language} записан в {script_path}, "
                f"но не выполнен (строк: {len(text.splitlines())})"
            ),
            data={"path": str(script_path), "language": language, "dry_run": True},
        )

    argv = _build_argv(language, script_path)
    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
            creationflags=_no_window_flag(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout, cut_out = _truncate(_decode(exc.stdout))
        stderr, cut_err = _truncate(_decode(exc.stderr))
        return ToolResult.fail(
            f"Сценарий не завершился за {timeout:g} с и был прерван",
            error="timeout",
            path=str(script_path),
            language=language,
            stdout=stdout,
            stderr=stderr,
            truncated={"stdout": cut_out, "stderr": cut_err},
        )
    except FileNotFoundError as exc:
        return ToolResult.fail(
            f"Интерпретатор для {language!r} не найден: {exc}",
            error="interpreter_not_found",
        )
    except OSError as exc:
        return ToolResult.fail(
            f"Не удалось запустить сценарий: {exc}",
            error=f"run_failed: {type(exc).__name__}",
        )

    elapsed = round(time.time() - started, 2)
    stdout, cut_out = _truncate(_decode(proc.stdout))
    stderr, cut_err = _truncate(_decode(proc.stderr))
    code = int(proc.returncode)

    data: dict[str, Any] = {
        "path": str(script_path),
        "language": language,
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_s": elapsed,
        "truncated": {"stdout": cut_out, "stderr": cut_err},
    }
    if not keep:
        try:
            script_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 - файл мог остаться заблокированным
            data["kept"] = str(script_path)

    if code == 0:
        body = stdout.strip() or stderr.strip() or "(вывода нет)"
        return ToolResult(
            ok=True,
            summary=f"Сценарий {language} выполнен (код 0) за {elapsed} с. {body}",
            data=data,
        )
    body = (stderr.strip() or stdout.strip() or "(вывода нет)")
    return ToolResult(
        ok=False,
        summary=f"Сценарий {language} завершился с кодом {code}. {body}",
        data=data,
        error=f"exit_code_{code}",
    )


def _tool_run_powershell(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """Многострочный PowerShell без записи файла (через -Command)."""
    text = str(args.get("script") or args.get("command") or "")
    if not text.strip():
        return ToolResult.fail("Не хватает параметра script", error="bad_arguments")
    if not bool(getattr(ctx.config, "allow_shell", True)):
        return ToolResult.fail(
            "Выполнение команд отключено в конфигурации (allow_shell=false)",
            error="shell_disabled",
        )
    try:
        timeout = float(args.get("timeout") or 120.0)
    except (TypeError, ValueError):
        timeout = 120.0
    timeout = max(1.0, min(600.0, timeout))

    if bool(getattr(ctx, "dry_run", False)):
        return ToolResult(
            ok=True,
            summary=f"Dry-run: PowerShell не выполнен, строк: {len(text.splitlines())}",
            data={"dry_run": True, "script": text[:500]},
        )

    argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", text]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            creationflags=_no_window_flag(),
        )
    except subprocess.TimeoutExpired:
        return ToolResult.fail(
            f"PowerShell не завершился за {timeout:g} с", error="timeout"
        )
    except OSError as exc:
        return ToolResult.fail(f"Не удалось запустить PowerShell: {exc}", error="run_failed")

    stdout, _ = _truncate(_decode(proc.stdout))
    stderr, _ = _truncate(_decode(proc.stderr))
    code = int(proc.returncode)
    data = {"exit_code": code, "stdout": stdout, "stderr": stderr}
    if code == 0:
        return ToolResult(
            ok=True,
            summary="PowerShell выполнен (код 0). " + (stdout.strip() or "(вывода нет)"),
            data=data,
        )
    return ToolResult(
        ok=False,
        summary=f"PowerShell завершился с кодом {code}. " + (stderr.strip() or stdout.strip()),
        data=data,
        error=f"exit_code_{code}",
    )


def register_console_tools(registry: Any) -> int:
    """Добавить консольные инструменты в готовый реестр.

    Возвращает число добавленных инструментов. Уже существующие имена
    пропускаются, чтобы не спорить с инструментами других исполнителей.
    """
    existing = getattr(registry, "_tools", {}) or {}
    added = 0

    if "run_script" not in existing:
        registry.add(
            name="run_script",
            description=(
                "Write a multi-line script to a temporary file and run it. Use this for "
                "anything that takes more than one command: installing, configuring, "
                "checking state, batch file operations. Supported languages: powershell "
                "(.ps1), cmd (.cmd), python (.py). Returns exit code, stdout and stderr. "
                "Prefer this over taking screenshots: text output is cheaper and exact."
            ),
            parameters=schema(
                {
                    "script": prop_string("Full script text, may contain many lines"),
                    "language": prop_string(
                        "Script language", enum=list(LANGUAGES.keys())
                    ),
                    "timeout": prop_number(
                        "Maximum run time in seconds", minimum=1, maximum=600
                    ),
                    "cwd": prop_string("Optional working directory"),
                    "keep_file": prop_boolean(
                        "Keep the script file after the run for debugging", default=False
                    ),
                },
                required=["script"],
            ),
            risk=Risk.WRITE,
            category=CATEGORY,
        )(_tool_run_script)
        added += 1

    # Псевдоним для универсального протокола модулей инструментов
    # (pcagent.tools.TOOL_MODULES вызывает register(registry)).
    if "run_powershell" not in existing:
        registry.add(
            name="run_powershell",
            description=(
                "Run a PowerShell snippet without creating a file. Best for a few lines of "
                "Windows management: query services, registry, processes, files, network. "
                "Use it instead of looking at the screen when the answer is textual."
            ),
            parameters=schema(
                {
                    "script": prop_string("PowerShell code to execute"),
                    "timeout": prop_number(
                        "Maximum run time in seconds", minimum=1, maximum=600
                    ),
                },
                required=["script"],
            ),
            risk=Risk.WRITE,
            category=CATEGORY,
        )(_tool_run_powershell)
        added += 1

    return added


#: Универсальный протокол модулей инструментов (см. pcagent.tools.TOOL_MODULES):
#: модуль обязан предоставить register(registry).
register = register_console_tools
