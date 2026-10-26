"""Базовые типы инструментов агента (замороженный контракт)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from pcagent.interfaces import Risk, Screenshot

if TYPE_CHECKING:  # pragma: no cover - только для типизации
    from pcagent.config import AppConfig
    from pcagent.events import EventBus
    from pcagent.safety import Policy


def schema(properties: dict[str, Any], required: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    """Собрать JSON Schema объекта для FunctionDeclaration."""
    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = list(required)
    result.update(extra)
    return result


def prop_string(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "string", "description": desc, **kw}


def prop_integer(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "integer", "description": desc, **kw}


def prop_number(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "number", "description": desc, **kw}


def prop_boolean(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "boolean", "description": desc, **kw}


@dataclass
class ToolResult:
    ok: bool = True
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    images: list[Screenshot] = field(default_factory=list)
    error: str | None = None

    def model_response(self) -> dict[str, Any]:
        """Компактный ответ, который уйдёт модели как functionResponse."""
        payload: dict[str, Any] = {"ok": self.ok, "summary": self.summary}
        if self.error:
            payload["error"] = self.error
        if self.data:
            payload["data"] = self.data
        if self.images:
            payload["screenshots"] = [img.as_dict() for img in self.images]
        return payload

    @classmethod
    def fail(cls, summary: str, error: str | None = None, **data: Any) -> "ToolResult":
        return cls(ok=False, summary=summary, error=error or summary, data=dict(data))


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    handler: Callable[["ToolContext", dict[str, Any]], ToolResult]
    category: str = "general"

    def declaration(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


@dataclass
class ToolContext:
    """Всё, что нужно инструменту во время выполнения."""

    config: "AppConfig"
    screen: Any = None          # ScreenService
    policy: Any = None          # Policy
    logger: Any = None          # JsonlLogger | NullLogger
    bus: Any = None             # EventBus
    dry_run: bool = False
    registry: Any = None        # ToolRegistry
    last_screenshot: Any = None # Screenshot, который последним видел агент

    def remember_screenshot(self, shot: Any) -> None:
        """Запомнить геометрию последнего снимка (клики переводятся по ней)."""
        self.last_screenshot = shot

    def emit(self, event: Any) -> None:
        if self.bus is not None:
            try:
                self.bus.publish(event)
            except Exception:  # noqa: BLE001
                pass

    def log(self, kind: str, payload: dict[str, Any] | None = None, **extra: Any) -> None:
        if self.logger is not None:
            try:
                self.logger.log(kind, payload, **extra)
            except Exception:  # noqa: BLE001
                pass


class ToolRegistry:
    """Реестр инструментов: единственная точка выполнения и проверки политики."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # --- регистрация ---
    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Инструмент {tool.name!r} уже зарегистрирован")
        self._tools[tool.name] = tool
        return tool

    def add(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        risk: Risk,
        category: str = "general",
    ) -> Callable[[Callable[[ToolContext, dict[str, Any]], ToolResult]], Callable[..., ToolResult]]:
        def decorator(fn: Callable[[ToolContext, dict[str, Any]], ToolResult]) -> Callable[..., ToolResult]:
            self.register(
                Tool(
                    name=name,
                    description=description,
                    parameters=parameters,
                    risk=risk,
                    handler=fn,
                    category=category,
                )
            )
            return fn

        return decorator

    # --- доступ ---
    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools)

    def categories(self) -> list[str]:
        return sorted({tool.category for tool in self._tools.values()})

    def declarations(self) -> list[dict[str, Any]]:
        return [tool.declaration() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    # --- выполнение ---
    def execute(self, ctx: ToolContext, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        args = dict(args or {})
        tool = self.get(name)
        if tool is None:
            result = ToolResult.fail(f"Инструмент {name!r} не найден", error="unknown_tool")
            ctx.log("tool_error", {"name": name, "error": result.error})
            return result

        if ctx.policy is not None:
            decision = ctx.policy.check(tool.name, tool.risk, args)
            if decision.denied:
                result = ToolResult.fail(f"Отказано политикой безопасности: {decision.reason}", error="policy_denied")
                ctx.log("policy_denied", {"name": name, "args": args, "reason": decision.reason})
                return result

        if (ctx.dry_run or (ctx.policy is not None and ctx.policy.dry_run)) and tool.risk is not Risk.READ:
            summary = f"[dry-run] действие {name} пропущено, аргументы: {args}"
            ctx.log("dry_run", {"name": name, "args": args})
            return ToolResult(ok=True, summary=summary, data={"dry_run": True, "args": args})

        ctx.log("tool_call", {"name": name, "args": args, "risk": tool.risk.value})
        try:
            result = tool.handler(ctx, args)
        except Exception as exc:  # noqa: BLE001 - инструмент не должен ронять агента
            result = ToolResult.fail(f"Ошибка инструмента {name}: {exc}", error=f"{type(exc).__name__}: {exc}")
            ctx.log("tool_exception", {"name": name, "args": args, "error": result.error})
            return result

        if not isinstance(result, ToolResult):
            result = ToolResult.fail(f"Инструмент {name} вернул не ToolResult", error="bad_return_type")
        ctx.log("tool_result", {"name": name, "ok": result.ok, "summary": result.summary})
        return result


def build_default_registry(categories: list[str] | None = None) -> ToolRegistry:
    """Собрать реестр из всех доступных модулей инструментов.

    Модули, чьи зависимости не установлены, молча пропускаются.
    """
    from pcagent import tools as tools_pkg

    registry = ToolRegistry()
    for module_name in tools_pkg.TOOL_MODULES:
        module = tools_pkg.import_tool_module(module_name)
        if module is None:
            continue
        register = getattr(module, "register", None)
        if register is None:
            continue
        register(registry)
    if categories:
        allowed = {c.strip() for c in categories if c.strip()}
        registry._tools = {n: t for n, t in registry._tools.items() if t.category in allowed}
    return registry
