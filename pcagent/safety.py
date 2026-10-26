"""Политика безопасности: что можно, что требует подтверждения, что запрещено."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from pcagent.interfaces import Confirmer, Risk

DEFAULT_DENY_PATTERNS: tuple[str, ...] = (
    r"\bformat\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\bvssadmin\s+delete\b",
    r"\bwbadmin\s+delete\b",
    r"\bcipher\s+/w\b",
    r"\brm\s+-rf\s+/(\s|$)",
    r"\b(rd|rmdir)\s+/s\b",
    r"\bdel\s+/[fsq]\b[^\n]*\b[a-z]:\\",
    r"remove-item[^\n]*-(recurse|force)[^\n]*\b[a-z]:\\",
    r"\breg\s+delete\s+hklm",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bstop-computer\b",
    r"\bnet\s+user\b[^\n]*\/add",
    r"\btakeown\b",
    r"\bset-mppreference\b",
    r"\bwevtutil\s+cl\b",
    r"\bauditpol\b",
    r"\bwmic\s+shadowcopy\b",
    r"\\\\\.\\physicaldrive",
    r"\bicacls\b[^\n]*\/grant\s+everyone",
    r"\bnet\s+share\b[^\n]*\/delete",
    r"\bpowershell\b[^\n]*-encodedcommand\b",
)

BLOCKED_TOOL_NAMES: frozenset[str] = frozenset()

# Инструменты, которые выполняют команды ОС: выключаются флагом allow_shell=false.
# Список обязан включать ВСЕ способы запуска кода, иначе allow_shell=false
# становится фиктивным: например, run_script обходил бы запрет через временный файл.
SHELL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "run_command",
        "run_script",
        "run_powershell",
        "run_cmd",
        "shell",
        "execute",
    }
)


#: Признаки того, что модель пытается управлять мышью и клавиатурой ИЗ КОДА,
#: вместо инструментов click / type_text / press_key / hotkey.
#:
#: Зачем запрещать. На реальном прогоне клиент 21 раз вызывал run_script с
#: ctypes.SetCursorPos и mouse_event вместо штатного click. Это обходит и
#: политику безопасности (проверка идёт по имени инструмента, а не по телу
#: скрипта), и проверку координат, и учёт действий для снимков экрана.
INPUT_EMULATION_PATTERNS: tuple[str, ...] = (
    'mouse_event',
    'setcursorpos',
    'keybd_event',
    'sendinput',
    'sendkeys',
    'sendwait',
    'pyautogui',
    'pynput',
    'autohotkey',
    'xdotool',
    '[system.windows.forms.sendkeys]',
)


#: Готовая подсказка модели: чем заменить самодельное управление вводом.
INPUT_TOOL_HINT = (
    "Управляйте мышью и клавиатурой только инструментами агента: "
    "click (клик по координатам), type_text (ввод текста), press_key (одна клавиша), "
    "hotkey (сочетание клавиш), drag, scroll. "
    "Писать код с mouse_event / SetCursorPos / SendKeys / pyautogui нельзя: "
    "такой код обходит политику безопасности и проверку координат."
)


def detect_input_emulation(text: str) -> str | None:
    """Найти в тексте сценария прямой обход инструментов ввода.

    Возвращает совпавший фрагмент или None, если ничего подозрительного нет.
    Сравнение идёт подстрокой без учёта регистра: так не бывает осечек
    из-за экранирования в регулярных выражениях.
    """
    if not text:
        return None
    lowered = str(text).lower()
    for pattern in INPUT_EMULATION_PATTERNS:
        if pattern in lowered:
            return pattern
    return None


@dataclass
class Decision:
    allowed: bool
    needs_confirmation: bool
    reason: str = ""

    @property
    def denied(self) -> bool:
        return not self.allowed


class PolicyRefusal(Exception):
    """Действие запрещено политикой."""


class ConsoleConfirmer:
    """Подтверждение в терминале (используется CLI)."""

    def __init__(self, stream_printer: Callable[[str], None] = print, auto_answer: bool | None = None) -> None:
        self._print = stream_printer
        self.auto_answer = auto_answer

    def ask(self, question: str, details: str = "", timeout: float | None = None) -> bool:
        if self.auto_answer is not None:
            return bool(self.auto_answer)
        self._print("")
        self._print("=" * 68)
        self._print(f"ТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ: {question}")
        if details:
            self._print(f"Детали: {details}")
        self._print("=" * 68)
        try:
            answer = input("Выполнить? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes", "д", "да")


class AutoConfirmer:
    """Автоматический ответ (--yes или GUI-брокер)."""

    def __init__(self, approve: bool = True) -> None:
        self.approve = bool(approve)
        self.calls: list[tuple[str, str]] = []

    def ask(self, question: str, details: str = "", timeout: float | None = None) -> bool:
        self.calls.append((question, details))
        return self.approve


class DenyConfirmer:
    """Ничего не подтверждает: подтверждение невозможно без UI."""

    def ask(self, question: str, details: str = "", timeout: float | None = None) -> bool:
        return False


class Policy:
    """Решает, можно ли выполнить инструмент и нужно ли подтверждение."""

    def __init__(
        self,
        confirm_mode: str = "risky",
        *,
        allow_destructive: bool = True,
        dry_run: bool = False,
        assume_yes: bool = False,
        confirmer: Confirmer | None = None,
        allow_shell: bool = True,
        deny_patterns: tuple[str, ...] = DEFAULT_DENY_PATTERNS,
        blocked_tools: frozenset[str] = BLOCKED_TOOL_NAMES,
    ) -> None:
        self.confirm_mode = (confirm_mode or "risky").lower()
        self.allow_shell = bool(allow_shell)
        self.allow_destructive = bool(allow_destructive)
        self.dry_run = bool(dry_run)
        self.assume_yes = bool(assume_yes)
        self.confirmer = confirmer
        self.blocked_tools = blocked_tools
        self._deny = tuple(re.compile(p, re.IGNORECASE) for p in deny_patterns)

    # ------------------------------------------------------------------
    def evaluate(self, tool_name: str, risk: Risk, args: dict[str, Any] | None = None) -> Decision:
        if tool_name in self.blocked_tools:
            return Decision(False, False, f"инструмент {tool_name} заблокирован политикой")

        haystack = json.dumps(args or {}, ensure_ascii=False, default=str)
        for pattern in self._deny:
            if pattern.search(haystack):
                return Decision(False, False, f"аргументы содержат запрещённый шаблон: {pattern.pattern}")

        if risk is Risk.DESTRUCTIVE and not self.allow_destructive:
            return Decision(False, False, "деструктивные действия отключены (allow_destructive=false)")

        if not self.allow_shell and tool_name in SHELL_TOOL_NAMES:
            return Decision(False, False, "выполнение команд ОС отключено (allow_shell=false)")

        if self.dry_run:
            return Decision(True, False, "режим dry-run")

        if self.assume_yes:
            return Decision(True, False, "подтверждение отключено (--yes)")

        if self.confirm_mode == "never":
            return Decision(True, False, "confirm_mode=never")

        if self.confirm_mode == "always":
            return Decision(True, True, "confirm_mode=always")

        # risky (по умолчанию): подтверждаем запись и деструктивные операции
        needs = risk in (Risk.WRITE, Risk.DESTRUCTIVE)
        return Decision(True, needs, "confirm_mode=risky")

    def check(self, tool_name: str, risk: Risk, args: dict[str, Any] | None = None) -> Decision:
        """Полная проверка с запросом подтверждения у пользователя."""
        decision = self.evaluate(tool_name, risk, args)
        if decision.denied or not decision.needs_confirmation:
            return decision

        question = f"Инструмент {tool_name} изменяет систему. Разрешить?"
        details = json.dumps(args or {}, ensure_ascii=False, default=str)[:800]
        if self.confirmer is None:
            return Decision(False, False, f"{question} Подтверждение недоступно - отказ.")
        approved = bool(self.confirmer.ask(question, details))
        if not approved:
            return Decision(False, False, "пользователь отклонил действие")
        return Decision(True, False, "подтверждено пользователем")

    def describe(self) -> dict[str, Any]:
        return {
            "confirm_mode": self.confirm_mode,
            "allow_destructive": self.allow_destructive,
            "allow_shell": self.allow_shell,
            "dry_run": self.dry_run,
            "assume_yes": self.assume_yes,
            "deny_patterns": len(self._deny),
        }
