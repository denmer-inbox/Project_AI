"""Мозг на официальном SDK Google (google-genai): запросы, ответы, модели.

Модуль универсального клиента: он отвечает только за Google-провайдера,
остальные работают через pcagent/gui/providers.py (HTTP-совместимые API).

SDK google-genai импортируется лениво: команды doctor/models и stub-режим
не должны зависеть от сетевого клиента. Клиент создаётся только при первом
обращении к модели.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

try:  # pragma: no cover - зависит от окружения
    from google.genai import types
except Exception:  # noqa: BLE001 - без SDK работают stub-режим и часть CLI
    types = None  # type: ignore[assignment]

DEFAULT_IMAGE_MIME = "image/jpeg"
IMAGE_PLACEHOLDER = "[снимок экрана удалён из истории]"

# Признаки того, что проблема в самой модели, а не в сети: тогда имеет смысл
# пробовать fallback_models из конфигурации.
_MODEL_UNAVAILABLE_MARKERS = (
    "not found",
    "not_found",
    "404",
    "unsupported model",
    "is not supported",
    "does not support",
    "invalid model",
    "model not",
    "permission_denied",
    "permission denied",
)

class BrainError(RuntimeError):
    """Мозг не смог получить ответ модели."""

    def __init__(
        self,
        message: str,
        *,
        tried_models: Iterable[str] | None = None,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.tried_models = list(tried_models or [])
        self.original = original

# ---------------------------------------------------------------------------
# Сборка запросов
# ---------------------------------------------------------------------------

def _require_types():
    """Вернуть модуль types или понятную ошибку."""
    if types is None:
        raise BrainError("google-genai не установлен: pip install google-genai")
    return types

def build_tool_config(declarations: Sequence[Mapping[str, Any]] | None) -> Any:
    """Собрать types.Tool из списка деклараций реестра инструментов."""
    t = _require_types()
    function_declarations = []
    for item in declarations or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kwargs: dict[str, Any] = {
            "name": name,
            "description": str(item.get("description") or ""),
        }
        parameters = item.get("parameters") or item.get("parameters_json_schema") or {}
        if parameters:
            kwargs["parameters_json_schema"] = dict(parameters)
        function_declarations.append(t.FunctionDeclaration(**kwargs))
    return t.Tool(function_declarations=function_declarations)

def image_part(data: bytes, mime_type: str = DEFAULT_IMAGE_MIME) -> Any:
    """Часть Content с изображением."""
    t = _require_types()
    return t.Part.from_bytes(data=data, mime_type=mime_type or DEFAULT_IMAGE_MIME)

def screenshot_part(shot: Any) -> Any | None:
    """Часть Content из pcagent.interfaces.Screenshot."""
    data = getattr(shot, "image_bytes", None)
    if not data:
        return None
    mime = getattr(shot, "mime_type", None) or DEFAULT_IMAGE_MIME
    return image_part(data, mime)

def part_from_spec(spec: Mapping[str, Any]) -> Any | None:
    """Собрать types.Part из внутреннего описания части.

    Поддерживаются виды: text, image, function_call, function_response, raw.
    """
    t = _require_types()
    if not isinstance(spec, Mapping):
        return None
    kind = str(spec.get("type") or "text").lower()

    if kind == "raw":
        part = spec.get("part")
        return part if part is not None else None

    if kind == "text":
        text = spec.get("text")
        if text is None:
            text = spec.get("content") or ""
        text = str(text)
        return t.Part(text=text) if text else None

    if kind == "image":
        data = spec.get("data") or b""
        mime = str(spec.get("mime_type") or DEFAULT_IMAGE_MIME)
        return image_part(bytes(data), mime) if data else None

    if kind == "function_call":
        name = str(spec.get("name") or "")
        if not name:
            return None
        call = t.FunctionCall(name=name, args=dict(spec.get("args") or {}))
        call_id = spec.get("id")
        if call_id:
            call.id = str(call_id)
        return t.Part(function_call=call)

    if kind == "function_response":
        name = str(spec.get("name") or "")
        if not name:
            return None
        response = spec.get("response")
        if response is None:
            response = {"ok": bool(spec.get("ok", True)), "summary": str(spec.get("summary") or "")}
        fr = t.FunctionResponse(name=name, response=dict(response))
        call_id = spec.get("id")
        if call_id:
            fr.id = str(call_id)
        return t.Part(function_response=fr)

    return None

def message_to_content(message: Mapping[str, Any] | Any) -> Any:
    """Превратить описание сообщения во внутренний types.Content.

    message = {"role": "user" | "model", "parts": [описание, ...]}
    Готовый types.Content возвращается как есть.
    """
    t = _require_types()
    if isinstance(message, t.Content):
        return message
    if not isinstance(message, Mapping):
        raise TypeError("message_to_content ожидает dict или types.Content")

    role = str(message.get("role") or "user")
    parts = []
    for spec in message.get("parts") or []:
        part = part_from_spec(spec)
        if part is not None:
            parts.append(part)
    if not parts:
        # Пустой Content SDK не отправляет; даём безобидную заглушку.
        parts.append(t.Part(text=" "))
    return t.Content(role=role, parts=parts)

def history_to_contents(history: Sequence[Mapping[str, Any] | Any]) -> list[Any]:
    """Превратить историю сообщений в список types.Content."""
    return [message_to_content(item) for item in history or []]

# ---------------------------------------------------------------------------
# Разбор ответа
# ---------------------------------------------------------------------------

def response_content(response: Any) -> Any | None:
    """Content первого кандидата ответа (или None)."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    return getattr(candidates[0], "content", None)

def extract_parts(response: Any) -> list[dict[str, Any]]:
    """Нормализованные части ответа: text и function_call, без thought.

    parts у кандидата может быть None - это не ошибка, а пустой ответ.
    """
    content = response_content(response)
    raw_parts = getattr(content, "parts", None) or []
    result: list[dict[str, Any]] = []
    for part in raw_parts:
        if part is None:
            continue
        if getattr(part, "thought", False):
            continue
        call = getattr(part, "function_call", None)
        if call is not None:
            result.append(
                {
                    "type": "function_call",
                    "name": str(getattr(call, "name", "") or ""),
                    "args": dict(getattr(call, "args", None) or {}),
                    "id": getattr(call, "id", None),
                }
            )
            continue
        text = getattr(part, "text", None)
        if text:
            result.append({"type": "text", "text": str(text)})
    return result

def extract_text(parts: Sequence[Mapping[str, Any]]) -> str:
    """Склеить текстовые части ответа."""
    return "\n".join(str(p.get("text") or "") for p in parts or [] if p.get("type") == "text").strip()

def extract_calls(parts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Только вызовы инструментов, в порядке ответа модели."""
    return [dict(p) for p in parts or [] if p.get("type") == "function_call"]

def extract_thoughts(response: Any) -> str:
    """Текст рассуждений модели (части с thought=True) для журнала и UI."""
    content = response_content(response)
    raw_parts = getattr(content, "parts", None) or []
    lines: list[str] = []
    for part in raw_parts:
        if part is None or not getattr(part, "thought", False):
            continue
        text = getattr(part, "text", None)
        if text:
            lines.append(str(text).strip())
    return "\n".join(line for line in lines if line).strip()

def response_text(response: Any) -> str:
    """Текст ответа (для логов и финального сообщения)."""
    try:
        text = getattr(response, "text", None)
    except Exception:  # noqa: BLE001 - SDK может ругаться на пустые части
        text = None
    return str(text or "").strip()

# ---------------------------------------------------------------------------
# История и изображения
# ---------------------------------------------------------------------------

def is_image_part(part: Any) -> bool:
    """Похоже ли на часть с изображением."""
    return getattr(part, "inline_data", None) is not None

def prune_history_images(contents: Sequence[Any], keep: int = 3) -> int:
    """Заменить старые изображения текстовой заглушкой.

    Оставляем последние keep изображений, остальные заменяются на текст,
    чтобы запрос не разрастался. Возвращает число замен.
    """
    t = _require_types()
    try:
        limit = max(0, int(keep))
    except (TypeError, ValueError):
        limit = 0

    positions: list[tuple[int, int]] = []
    for ci, content in enumerate(contents or []):
        for pi, part in enumerate(getattr(content, "parts", None) or []):
            if is_image_part(part):
                positions.append((ci, pi))

    stale = positions[:-limit] if limit else positions
    replaced = 0
    for ci, pi in stale:
        parts = contents[ci].parts
        parts[pi] = t.Part(text=IMAGE_PLACEHOLDER)
        replaced += 1
    return replaced

#: Заглушка вместо старых результатов инструментов.
RESULT_PLACEHOLDER = "[результат инструмента сокращён: шаг уже неактуален]"

#: Предел на размер одного ответа инструмента, попадающего в историю.
#: Дерево UI Automation на большом окне даёт 8-12 КБ, а таких вызовов за
#: задачу бывает десяток: без ограничения контекст растёт и модель начинает
#: отвечать по 40-70 секунд вместо 2-3.
DEFAULT_MAX_RESULT_CHARS = 6000


def truncate_result(payload: dict[str, Any], limit: int = DEFAULT_MAX_RESULT_CHARS) -> dict[str, Any]:
    """Урезать слишком большой ответ инструмента, сохранив признаки.

    Обрезается только длинный текст внутри data, структура и ключевые поля
    (ok, summary, error) остаются нетронутыми.
    """
    import json

    try:
        limit = max(200, int(limit))
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_RESULT_CHARS

    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return payload

    result = dict(payload)
    data = result.get("data")
    if isinstance(data, dict):
        trimmed: dict[str, Any] = {}
        budget = limit
        # Сначала оставляем короткие поля: они несут смысл.
        for key, value in sorted(data.items(), key=lambda kv: len(str(kv[1]))):
            piece = json.dumps({key: value}, ensure_ascii=False, default=str)
            if len(piece) <= budget:
                trimmed[key] = value
                budget -= len(piece)
            else:
                if isinstance(value, str):
                    keep = max(0, budget - 80)
                    trimmed[key] = value[:keep] + (" ... [обрезано]" if keep else "[обрезано]")
                else:
                    trimmed[key] = "[обрезано]"
                budget = 0
        result["data"] = trimmed
        result["truncated"] = True
    return result


def prune_history_results(contents: Sequence[Any], keep: int = 6) -> int:
    """Заменить заглушкой результаты инструментов, кроме последних keep.

    Модель опирается на свежие результаты; давние вызовы (например, десятый
    по счёту обход UIA-дерева) только раздувают запрос.
    """
    t = _require_types()
    try:
        limit = max(0, int(keep))
    except (TypeError, ValueError):
        limit = 0

    positions: list[tuple[int, int]] = []
    for ci, content in enumerate(contents or []):
        for pi, part in enumerate(getattr(content, "parts", None) or []):
            if getattr(part, "function_response", None) is not None:
                positions.append((ci, pi))

    stale = positions[:-limit] if limit else positions
    replaced = 0
    for ci, pi in stale:
        part = contents[ci].parts[pi]
        response = getattr(part, "function_response", None)
        name = str(getattr(response, "name", "") or "")
        contents[ci].parts[pi] = t.Part(
            function_response=t.FunctionResponse(
                name=name or "tool",
                response={"ok": True, "summary": RESULT_PLACEHOLDER},
            )
        )
        replaced += 1
    return replaced


def count_images(contents: Sequence[Any]) -> int:
    """Сколько изображений сейчас в истории."""
    total = 0
    for content in contents or []:
        for part in getattr(content, "parts", None) or []:
            if is_image_part(part):
                total += 1
    return total

def strip_images(contents: Sequence[Any], placeholder: str = "[снимок убран из повторного запроса]") -> int:
    """Убрать все изображения (повтор запроса после сетевой ошибки)."""
    t = _require_types()
    replaced = 0
    for content in contents or []:
        parts = getattr(content, "parts", None) or []
        for index, part in enumerate(parts):
            if is_image_part(part):
                parts[index] = t.Part(text=placeholder)
                replaced += 1
    return replaced

# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------

def _is_model_unavailable(exc: BaseException) -> bool:
    """Ошибка похожа на 'такой модели нет / нет доступа'."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _MODEL_UNAVAILABLE_MARKERS)

def model_supports_generate(model: Any) -> bool:
    """Модель умеет generateContent (по данным SDK)."""
    actions = getattr(model, "supported_actions", None)
    if not actions:
        actions = getattr(model, "supported_generation_methods", None)
    if not actions:
        return True  # список методов не отдан - не отсеиваем
    return "generateContent" in {str(a) for a in actions}

def list_models(client: Any) -> list[dict[str, Any]]:
    """Список моделей аккаунта через SDK (для команды models)."""
    try:
        raw = client.models.list()
    except Exception as exc:  # noqa: BLE001 - ошибку показываем пользователю
        raise BrainError(f"Не удалось получить список моделей: {exc}") from exc

    items: list[dict[str, Any]] = []
    for model in raw or []:
        full_name = str(getattr(model, "name", "") or "")
        short = full_name[7:] if full_name.startswith("models/") else full_name
        items.append(
            {
                "name": short,
                "full_name": full_name,
                "display_name": getattr(model, "display_name", None),
                "description": getattr(model, "description", None),
                "supports_generate": model_supports_generate(model),
                "input_token_limit": getattr(model, "input_token_limit", None),
                "output_token_limit": getattr(model, "output_token_limit", None),
            }
        )
    items.sort(key=lambda item: item["name"])
    return items

# ---------------------------------------------------------------------------
# Мозг на официальном SDK Google
# ---------------------------------------------------------------------------

class GoogleBrain:
    """Мозг агента на официальном SDK Google (function calling)."""

    def __init__(self, config: Any, *, client: Any = None, logger: Any = None) -> None:
        self.config = config
        self.logger = logger
        self._client = client
        self.active_model = str(getattr(config, "model", "") or "").strip()
        self.last_model: str = self.active_model
        self.calls: int = 0

    # --- клиент -------------------------------------------------------
    @property
    def client(self) -> Any:
        if self._client is None:
            from google import genai

            api_key = self.config.resolve_api_key()
            if not api_key:
                raise BrainError(
                    "ключ API не задан: положите его в .env как PCAGENT_API_KEY или GEMINI_API_KEY, "
                "либо укажите api_key в config.yaml"
                )
            timeout_ms = max(1, int(getattr(self.config, "request_timeout_s", 120) or 120)) * 1000
            self._client = genai.Client(api_key=api_key, http_options={"timeout": timeout_ms})
        return self._client

    def close(self) -> None:
        """Закрыть клиент, если он был создан."""
        client = self._client
        self._client = None
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - закрытие не должно падать
                pass

    # --- модели -------------------------------------------------------
    def candidate_models(self) -> list[str]:
        """Основная модель и fallback_models без дублей."""
        names: list[str] = []
        for name in [getattr(self.config, "model", ""), *(getattr(self.config, "fallback_models", None) or [])]:
            name = str(name or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    # --- генерация ----------------------------------------------------
    def _build_config(self, tools_declarations: Sequence[Mapping[str, Any]] | None, system_instruction: str | None) -> Any:
        t = _require_types()
        cfg = t.GenerateContentConfig(
            system_instruction=str(system_instruction).strip() if system_instruction else None,
            temperature=float(getattr(self.config, "temperature", 0.2) or 0.0),
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )
        if tools_declarations:
            cfg.tools = [build_tool_config(tools_declarations)]
        return cfg

    def generate(
        self,
        contents: Sequence[Any],
        tools_declarations: Sequence[Mapping[str, Any]] | None = None,
        system_instruction: str | None = None,
    ) -> Any:
        """Запрос к модели: возвращает ответ SDK.

        Если модель недоступна - пробуем fallback_models по порядку.
        Сетевые ошибки не глотаем: цикл сам решит, повторять ли без снимков.
        """
        config_obj = self._build_config(tools_declarations, system_instruction)
        tried: list[str] = []
        last_exc: BaseException | None = None

        for model in self.candidate_models() or [""]:
            tried.append(model)
            try:
                response = self.client.models.generate_content(
                    model=model, contents=list(contents), config=config_obj
                )
            except Exception as exc:  # noqa: BLE001 - разбираем тип ошибки
                last_exc = exc
                self._log("llm_error", {"model": model, "error": str(exc)[:800]})
                if _is_model_unavailable(exc):
                    continue
                raise
            self.calls += 1
            self.last_model = model
            if model != self.active_model:
                self.active_model = model
                self._log("model_switched", {"model": model, "previous": tried[0]})
            return response

        raise BrainError(
            "не удалось получить ответ модели; испробованы: " + ", ".join(m for m in tried if m)
            + (f"; последняя ошибка: {last_exc}" if last_exc else ""),
            tried_models=tried,
            original=last_exc,
        )

    def _log(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        if self.logger is None:
            return
        try:
            self.logger.log(kind, payload)
        except Exception:  # noqa: BLE001 - логи не должны ломать агента
            pass

def json_dumps(data: Any, limit: int | None = None) -> str:
    """Компактный JSON для логов и подсказок."""
    text = json.dumps(data, ensure_ascii=False, default=str)
    if limit is not None and len(text) > limit:
        text = text[: max(0, limit - 1)] + "…"
    return text


#: Старое имя, оставлено для совместимости импортов.
GeminiBrain = GoogleBrain
