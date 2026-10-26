"""Тесты сборки запросов и разбора ответов Gemini (без сети)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pcagent import llm
from pcagent.config import AppConfig
from pcagent.interfaces import Risk
from pcagent.tools.base import ToolRegistry, ToolResult, prop_integer, schema

types = pytest.importorskip("google.genai.types")

# ---------------------------------------------------------------------------
# Декларации инструментов
# ---------------------------------------------------------------------------

def sample_registry() -> ToolRegistry:
    registry = ToolRegistry()

    @registry.add(
        name="click",
        description="Click at image coordinates.",
        parameters=schema(
            {"x": prop_integer("X pixel"), "y": prop_integer("Y pixel")}, required=["x", "y"]
        ),
        risk=Risk.WRITE,
        category="input",
    )
    def _click(ctx, args):
        return ToolResult(ok=True, summary="ok")

    @registry.add(
        name="screenshot",
        description="Take a screenshot.",
        parameters=schema({}),
        risk=Risk.READ,
        category="capture",
    )
    def _screenshot(ctx, args):
        return ToolResult(ok=True, summary="ok")

    return registry

def test_build_tool_config_from_declarations():
    declarations = sample_registry().declarations()
    tool = llm.build_tool_config(declarations)

    assert isinstance(tool, types.Tool)
    names = [item.name for item in tool.function_declarations]
    assert names == ["click", "screenshot"]

    click = tool.function_declarations[0]
    assert click.description == "Click at image coordinates."
    assert click.parameters_json_schema["type"] == "object"
    assert set(click.parameters_json_schema["properties"]) == {"x", "y"}
    assert click.parameters_json_schema["required"] == ["x", "y"]

def test_build_tool_config_skips_invalid_and_empty():
    tool = llm.build_tool_config(
        [
            {"name": "", "description": "пустое имя"},
            {"name": "screen_info", "description": "info", "parameters": schema({})},
        ]
    )
    assert [item.name for item in tool.function_declarations] == ["screen_info"]

# ---------------------------------------------------------------------------
# Конвертация сообщений
# ---------------------------------------------------------------------------

def test_message_to_content_text_and_image():
    content = llm.message_to_content(
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "Смотри сюда"},
                {"type": "image", "data": b"\x89PNG...", "mime_type": "image/png"},
            ],
        }
    )

    assert isinstance(content, types.Content)
    assert content.role == "user"
    assert len(content.parts) == 2
    assert content.parts[0].text == "Смотри сюда"
    assert content.parts[1].inline_data.mime_type == "image/png"
    assert content.parts[1].inline_data.data == b"\x89PNG..."

def test_message_to_content_function_response():
    content = llm.message_to_content(
        {
            "role": "user",
            "parts": [
                {
                    "type": "function_response",
                    "name": "click",
                    "response": {"ok": True, "summary": "клик выполнен"},
                    "id": "call-1",
                }
            ],
        }
    )

    part = content.parts[0]
    assert part.function_response.name == "click"
    assert part.function_response.response == {"ok": True, "summary": "клик выполнен"}
    assert part.function_response.id == "call-1"

def test_message_to_content_function_call():
    content = llm.message_to_content(
        {
            "role": "model",
            "parts": [
                {"type": "function_call", "name": "click", "args": {"x": 1, "y": 2}, "id": "abc"}
            ],
        }
    )

    call = content.parts[0].function_call
    assert call.name == "click"
    assert call.args == {"x": 1, "y": 2}
    assert call.id == "abc"

def test_message_to_content_passes_through_content():
    original = types.Content(role="user", parts=[types.Part(text="привет")])
    assert llm.message_to_content(original) is original

def test_history_to_contents_keeps_roles():
    history = [
        {"role": "user", "parts": [{"type": "text", "text": "задача"}]},
        {"role": "model", "parts": [{"type": "text", "text": "делаю"}]},
    ]
    contents = llm.history_to_contents(history)

    assert [item.role for item in contents] == ["user", "model"]
    assert contents[0].parts[0].text == "задача"
    assert contents[1].parts[0].text == "делаю"

def test_screenshot_part_from_interface_object():
    shot = SimpleNamespace(image_bytes=b"jpeg-bytes", mime_type="image/jpeg")
    part = llm.screenshot_part(shot)

    assert part.inline_data.mime_type == "image/jpeg"
    assert part.inline_data.data == b"jpeg-bytes"
    assert llm.screenshot_part(SimpleNamespace(image_bytes=b"", mime_type="image/jpeg")) is None

# ---------------------------------------------------------------------------
# Разбор ответа
# ---------------------------------------------------------------------------

def make_response(parts):
    content = types.Content(role="model", parts=parts)
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])

def test_extract_parts_text_call_and_thought():
    response = make_response(
        [
            types.Part(text="думаю про себя", thought=True),
            types.Part(text="нажимаю кнопку"),
            types.Part(function_call=types.FunctionCall(name="click", args={"x": 3, "y": 4}, id="c1")),
        ]
    )
    parts = llm.extract_parts(response)

    assert [part["type"] for part in parts] == ["text", "function_call"]
    assert parts[0]["text"] == "нажимаю кнопку"
    assert parts[1]["name"] == "click"
    assert parts[1]["args"] == {"x": 3, "y": 4}
    assert parts[1]["id"] == "c1"
    assert llm.extract_text(parts) == "нажимаю кнопку"
    assert len(llm.extract_calls(parts)) == 1

def test_extract_parts_handles_missing_candidates_and_none_parts():
    assert llm.extract_parts(SimpleNamespace(candidates=[])) == []
    assert llm.extract_parts(SimpleNamespace(candidates=None)) == []
    assert llm.extract_parts(make_response(None)) == []
    # В parts может оказаться None: разбор не должен падать.
    raw = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[None, types.Part(text="ок")]))]
    )
    assert llm.extract_parts(raw) == [{"type": "text", "text": "ок"}]

def test_extract_calls_keeps_order():
    response = make_response(
        [
            types.Part(function_call=types.FunctionCall(name="screenshot", args={})),
            types.Part(function_call=types.FunctionCall(name="screen_info", args={})),
        ]
    )
    calls = llm.extract_calls(llm.extract_parts(response))
    assert [call["name"] for call in calls] == ["screenshot", "screen_info"]

# ---------------------------------------------------------------------------
# История и изображения
# ---------------------------------------------------------------------------

def image_content() -> types.Content:
    return types.Content(
        role="user", parts=[types.Part.from_bytes(data=b"img", mime_type="image/jpeg")]
    )

def test_prune_history_images_keeps_last_n():
    history = [image_content() for _ in range(4)]
    replaced = llm.prune_history_images(history, keep=2)

    assert replaced == 2
    assert llm.count_images(history) == 2
    assert history[0].parts[0].text == llm.IMAGE_PLACEHOLDER
    assert history[1].parts[0].text == llm.IMAGE_PLACEHOLDER
    assert llm.is_image_part(history[2].parts[0])
    assert llm.is_image_part(history[3].parts[0])

def test_strip_images_removes_all():
    history = [image_content(), image_content()]
    assert llm.count_images(history) == 2
    assert llm.strip_images(history) == 2
    assert llm.count_images(history) == 0

# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------

class FakeModelsApi:
    def __init__(self, models=None, error: Exception | None = None) -> None:
        self._models = models or []
        self._error = error
        self.requested: list[str] = []

    def list(self):
        if self._error is not None:
            raise self._error
        return self._models

    def generate_content(self, model, contents, config):
        self.requested.append(model)
        raise AssertionError("этот метод переопределяют в тестах")

def test_list_models_filters_and_sorts():
    client = SimpleNamespace(
        models=FakeModelsApi(
            models=[
                types.Model(name="models/gemini-2.5-flash", display_name="Flash", supported_actions=["generateContent"]),
                types.Model(name="models/text-embedding-004", supported_actions=["embedContent"]),
            ]
        )
    )
    items = llm.list_models(client)

    assert [item["name"] for item in items] == ["gemini-2.5-flash", "text-embedding-004"]
    assert items[0]["full_name"] == "models/gemini-2.5-flash"
    assert items[0]["supports_generate"] is True
    assert items[1]["supports_generate"] is False

def test_list_models_wraps_errors():
    client = SimpleNamespace(models=FakeModelsApi(error=RuntimeError("нет сети")))
    with pytest.raises(llm.BrainError) as excinfo:
        llm.list_models(client)
    assert "нет сети" in str(excinfo.value)

# ---------------------------------------------------------------------------
# GoogleBrain: выбор модели
# ---------------------------------------------------------------------------

def make_config(**overrides) -> AppConfig:
    data = {
        "model": "missing-model",
        "fallback_models": ["working-model"],
        "temperature": 0.2,
        "request_timeout_s": 5,
        "stub_mode": True,
    }
    data.update(overrides)
    return AppConfig(**data)

def user_contents():
    return [
        llm.message_to_content({"role": "user", "parts": [{"type": "text", "text": "привет"}]})
    ]

def test_generate_falls_back_to_next_model():
    sentinel = object()
    calls: list[str] = []

    class Models:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "missing-model":
                raise RuntimeError("404 NOT_FOUND: model missing-model not found")
            return sentinel

    brain = llm.GoogleBrain(make_config(), client=SimpleNamespace(models=Models()))
    response = brain.generate(user_contents(), [{"name": "click", "description": "d"}], "system")

    assert response is sentinel
    assert calls == ["missing-model", "working-model"]
    assert brain.active_model == "working-model"
    assert brain.calls == 1

def test_generate_raises_brain_error_when_all_models_fail():
    class Models:
        def generate_content(self, model, contents, config):
            raise RuntimeError(f"404 NOT_FOUND: model {model} not found")

    brain = llm.GoogleBrain(make_config(), client=SimpleNamespace(models=Models()))
    with pytest.raises(llm.BrainError) as excinfo:
        brain.generate(user_contents())

    assert excinfo.value.tried_models == ["missing-model", "working-model"]
    assert "missing-model" in str(excinfo.value)
    assert "working-model" in str(excinfo.value)

def test_generate_does_not_hide_network_errors():
    class Models:
        def generate_content(self, model, contents, config):
            raise RuntimeError("connection reset by peer")

    brain = llm.GoogleBrain(make_config(), client=SimpleNamespace(models=Models()))
    with pytest.raises(RuntimeError) as excinfo:
        brain.generate(user_contents())
    assert "connection reset" in str(excinfo.value)

def test_generate_without_api_key_reports_clearly(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    brain = llm.GoogleBrain(make_config(model="m", fallback_models=[]))
    brain.config.api_key = ""
    with pytest.raises(llm.BrainError) as excinfo:
        brain.generate(user_contents())
    assert "ключ" in str(excinfo.value).lower()
