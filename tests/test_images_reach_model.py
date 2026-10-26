"""Изображения должны реально доходить до модели.

Реальный прогон вскрыл дефект: агент делал снимки, но модель отвечала
"я не получаю изображение". Причина не в провайдере, а в форме сообщения:
провайдеры OpenAI-совместимого формата молча отбрасывают сообщение, которое
состоит только из image_url, без текстовой части.
"""

from __future__ import annotations

import pytest

from pcagent.gui import providers
from pcagent import llm


def _image_history_shape(contents):
    """Собрать сообщения и вернуть те, что содержат картинки."""
    messages = providers.contents_to_messages(contents)
    with_images = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "image_url" for part in content
        ):
            with_images.append(message)
    return messages, with_images


def _tiny_png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), (0, 128, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def _content(parts):
    return llm.message_to_content({"role": "user", "parts": parts})


def test_image_message_always_has_text():
    """Сообщение с картинкой обязано содержать текст, иначе оно теряется."""
    contents = [
        _content([{"type": "image", "data": _tiny_png(), "mime_type": "image/png"}]),
    ]
    _messages, with_images = _image_history_shape(contents)
    assert len(with_images) == 1
    parts = with_images[0]["content"]
    assert parts[0]["type"] == "text", "первой частью должен идти текст"
    assert parts[0]["text"].strip(), "текст не должен быть пустым"
    assert any(part["type"] == "image_url" for part in parts)


def test_tool_response_and_image_are_separate_messages():
    """Картинка идёт отдельным сообщением после ответа инструмента."""
    contents = [
        _content([{"type": "text", "text": "сделай снимок"}]),
        llm.message_to_content(
            {
                "role": "model",
                "parts": [{"type": "function_call", "name": "screenshot", "args": {}, "id": "c1"}],
            }
        ),
        _content(
            [
                {"type": "function_response", "name": "screenshot", "response": {"ok": True}, "id": "c1"},
                {"type": "image", "data": _tiny_png(), "mime_type": "image/png"},
            ]
        ),
    ]
    messages, with_images = _image_history_shape(contents)
    roles = [m["role"] for m in messages]
    assert "tool" in roles, "ответ инструмента должен идти отдельным tool-сообщением"
    assert len(with_images) == 1
    image_index = messages.index(with_images[0])
    tool_index = roles.index("tool")
    assert image_index > tool_index, "картинка должна идти после tool-сообщения"
    # Между tool и картинкой не должно быть пустых сообщений.
    for message in messages[tool_index + 1 : image_index]:
        assert message.get("content"), "пустое сообщение ломает порядок"


def test_image_data_uri_is_valid():
    uri = providers._image_data_uri(
        llm.part_from_spec({"type": "image", "data": _tiny_png(), "mime_type": "image/png"})
    )
    assert uri is not None
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 50


def test_plain_text_history_has_no_image_messages():
    contents = [_content([{"type": "text", "text": "привет"}])]
    messages = providers.contents_to_messages(contents)
    assert messages == [{"role": "user", "content": "привет"}]
