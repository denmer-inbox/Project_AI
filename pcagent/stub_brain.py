"""Скриптованный "мозг" без сети: используется тестами и режимом --stub.

Формат сценария:
    [
        {"thought": "Смотрю на экран",
         "calls": [{"name": "screenshot", "args": {}}]},
        ...
    ]
Каждый шаг - один ответ модели. Последний шаг сценария обычно вызывает
finish_task. Если сценарий закончился, а задача не завершена, StubBrain сам
возвращает finish_task, чтобы цикл не крутился до лимита шагов.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

@dataclass
class StubFunctionCall:
    """Вызов инструмента в ответе заглушки."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str | None = None

@dataclass
class StubPart:
    """Часть ответа заглушки: текст, мысль или вызов инструмента."""

    text: str | None = None
    function_call: StubFunctionCall | None = None
    thought: bool = False
    inline_data: Any = None

@dataclass
class StubContent:
    """Content заглушки (role + parts)."""

    role: str = "model"
    parts: list[StubPart] = field(default_factory=list)

@dataclass
class StubCandidate:
    """Кандидат ответа заглушки."""

    content: StubContent
    finish_reason: str = "STOP"

@dataclass
class StubResponse:
    """Ответ, структурно совпадающий с types.GenerateContentResponse."""

    candidates: list[StubCandidate]
    text: str = ""

# Сценарий по умолчанию: видно, что цикл работает без сети и ключа API.
DEFAULT_SCENARIO: list[dict[str, Any]] = [
    {
        "thought": "Сначала снимаю экран, чтобы понять, что происходит.",
        "calls": [{"name": "screenshot", "args": {}}],
    },
    {
        "thought": "Уточняю разрешение и активное окно для точных координат.",
        "calls": [{"name": "screen_info", "args": {}}],
    },
    {
        "thought": "Данных достаточно, задача выполнена в офлайн-режиме.",
        "calls": [
            {
                "name": "finish_task",
                "args": {
                    "summary": "Stub-режим: цикл отработал, экран прочитан.",
                    "success": True,
                },
            }
        ],
    },
]

class StubBrain:
    """Мозг, который отдаёт заранее записанные ответы."""

    def __init__(
        self,
        script: Sequence[Mapping[str, Any]] | None = None,
        *,
        name: str = "stub",
        logger: Any = None,
    ) -> None:
        self.script: list[dict[str, Any]] = [dict(step) for step in (script or DEFAULT_SCENARIO)]
        self.name = name
        self.logger = logger
        self.index = 0
        self.calls = 0
        self.seen_contents: list[list[Any]] = []
        self.seen_instructions: list[str | None] = []
        self.seen_declarations: list[list[dict[str, Any]]] = []

    # --- интерфейс мозга ---------------------------------------------
    def generate(
        self,
        contents: Sequence[Any],
        tools_declarations: Sequence[Mapping[str, Any]] | None = None,
        system_instruction: str | None = None,
    ) -> StubResponse:
        """Вернуть очередной шаг сценария."""
        self.calls += 1
        self.seen_contents.append(list(contents))
        self.seen_instructions.append(system_instruction)
        self.seen_declarations.append([dict(item) for item in (tools_declarations or [])])
        if self.index < len(self.script):
            step = self.script[self.index]
            self.index += 1
        else:
            step = {
                "thought": "Сценарий исчерпан, завершаю задачу.",
                "calls": [
                    {
                        "name": "finish_task",
                        "args": {"summary": "Сценарий stub исчерпан.", "success": True},
                    }
                ],
            }
        return self._build_response(step)

    def reset(self) -> None:
        """Начать сценарий сначала."""
        self.index = 0

    @property
    def finished(self) -> bool:
        return self.index >= len(self.script)

    # --- сборка ответа ------------------------------------------------
    def _build_response(self, step: Mapping[str, Any]) -> StubResponse:
        parts: list[StubPart] = []
        thought = str(step.get("thought") or "").strip()
        if thought:
            parts.append(StubPart(text=thought, thought=True))
        text = str(step.get("text") or "").strip()
        if text:
            parts.append(StubPart(text=text))
        for raw_call in step.get("calls") or []:
            name = str(raw_call.get("name") or "").strip()
            if not name:
                continue
            args = dict(raw_call.get("args") or {})
            call_id = raw_call.get("id")
            parts.append(
                StubPart(
                    function_call=StubFunctionCall(
                        name=name,
                        args=args,
                        id=str(call_id) if call_id else f"stub-{self.index}-{len(parts)}",
                    )
                )
            )
        if not parts:
            parts.append(StubPart(text="(пустой шаг сценария)"))
        content = StubContent(role="model", parts=parts)
        text_out = "\n".join(p.text or "" for p in parts if p.text and not p.thought)
        self._log("stub_step", {"index": self.index, "calls": [p.function_call.name for p in parts if p.function_call]})
        return StubResponse(candidates=[StubCandidate(content=content)], text=text_out)

    def _log(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        if self.logger is None:
            return
        try:
            self.logger.log(kind, payload)
        except Exception:  # noqa: BLE001
            pass

def make_script(steps: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Нормализовать внешний сценарий в список шагов."""
    return [dict(step) for step in steps or []]
