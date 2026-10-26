"""Настройка поведения модели в GUI: текст вместо картинок.

Модель склонна снимать экран на каждом шаге, хотя большинство задач на
Windows решается текстом. Модуль оборачивает мозг агента и дописывает к
системной инструкции правила "сначала консоль, снимок - в последнюю
очередь". Правка живёт в GUI и не меняет общий промпт агента.
"""

from __future__ import annotations

from typing import Any, Sequence

#: Правила, которые дописываются к системной инструкции.
CONSOLE_FIRST_APPENDIX = """
PREFER TEXT OVER PIXELS (this matters: screenshots are slow and expensive)
* Try a console or text approach BEFORE any screenshot. Most Windows tasks are solved
  with run_powershell, run_script, run_command, ui_tree, list_windows or screen_info.
* Do not take a screenshot just to find out what is on screen when a tool can tell you
  in text. Window titles, element trees, file lists and command output are cheaper and
  more exact than an image.
* Take a screenshot ONLY when the task truly needs visual information: the position of a
  control inside a custom-drawn window, the content of a canvas or picture, or a program
  that cannot be driven by command line, UI Automation or keyboard at all.
* Never take a second screenshot without performing an action in between. If a screenshot
  is refused because of the budget, switch to text tools instead of retrying.
* Prefer one script over many small clicks: a single run_script call that does the whole
  job is cheaper and more reliable than ten GUI actions.
"""


def _extra(config: Any) -> dict[str, Any]:
    return dict(getattr(config, "extra", None) or {})


def console_first_enabled(config: Any) -> bool:
    """Включено ли предпочтение текста.

    По умолчанию ВЫКЛЮЧЕНО: клиент создавался как агент, который читает экран,
    и подменять это правилом "сначала консоль" без просьбы пользователя нельзя.
    Включается ключом console_first: true в config.yaml.
    """
    value = _extra(config).get("console_first")
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "да")
    return bool(value)


class ConsoleFirstBrain:
    """Обёртка над мозгом: дополняет системную инструкцию правилами.

    Все остальные атрибуты и методы делегируются исходному мозгу, поэтому
    обёртка не мешает ни смене модели, ни статистике запросов.
    """

    def __init__(self, inner: Any, appendix: str = CONSOLE_FIRST_APPENDIX) -> None:
        self._inner = inner
        self._appendix = str(appendix or "")

    @property
    def inner(self) -> Any:
        return self._inner

    def _augment(self, instruction: Any) -> str:
        base = str(instruction or "")
        if not self._appendix:
            return base
        return (base + "\n" + self._appendix).strip() if base else self._appendix.strip()

    def generate(
        self,
        contents: Sequence[Any],
        tools_declarations: Sequence[Any] | None = None,
        system_instruction: str | None = None,
    ) -> Any:
        return self._inner.generate(
            contents,
            tools_declarations,
            system_instruction=self._augment(system_instruction),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def wrap_brain(brain: Any, config: Any = None) -> Any:
    """Обернуть мозг, если предпочтение текста включено."""
    if brain is None:
        return None
    if config is not None and not console_first_enabled(config):
        return brain
    if isinstance(brain, ConsoleFirstBrain):
        return brain
    return ConsoleFirstBrain(brain)
