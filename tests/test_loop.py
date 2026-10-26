"""Тесты агентного цикла на StubBrain и настоящем ToolRegistry."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pcagent.agent.loop import AgentSession
from pcagent.config import AppConfig
from pcagent.events import (
    KIND_ACTION,
    KIND_DONE,
    KIND_ERROR,
    KIND_IMAGE,
    KIND_RESULT,
    KIND_STEP,
    KIND_THOUGHT,
    EventBus,
    kill_switch,
)
from pcagent.interfaces import Risk, Screenshot
from pcagent.safety import Policy
from pcagent.stub_brain import StubBrain
from pcagent.tools.base import (
    ToolRegistry,
    ToolResult,
    prop_boolean,
    prop_integer,
    prop_string,
    schema,
)

@pytest.fixture(autouse=True)
def reset_kill_switch():
    """Стоп-кран - глобальный объект, сбрасываем его вокруг каждого теста."""
    kill_switch.reset()
    yield
    kill_switch.reset()

class Recorder:
    """Собирает вызовы инструментов и события шины."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.events: list = []
        self.ctx_shots: list = []       # ctx.last_screenshot на момент вызова инструмента

    def __call__(self, event) -> None:
        self.events.append(event)

    def kinds(self, kind: str) -> list:
        return [event for event in self.events if event.kind == kind]

    def tool_names(self) -> list[str]:
        return [name for name, _ in self.calls]

class FakeScreen:
    """Поддельный сервис экрана: без mss и без реального захвата."""

    def __init__(self) -> None:
        self.captures = 0
        self.uia_calls = 0

    def capture(self, monitor=None, max_width=None, fmt=None, quality=None) -> Screenshot:
        self.captures += 1
        return Screenshot(
            image_bytes=b"fake-jpeg-bytes",
            mime_type="image/jpeg",
            width=640,
            height=360,
            scale=0.5,
            monitor=0,
            real_width=1280,
            real_height=720,
        )

    def uia_tree(self, max_nodes=None) -> str:
        self.uia_calls += 1
        return "Window: Тестовое окно"

def make_registry(
    recorder: Recorder,
    *,
    with_finish: bool = True,
    failing: tuple[str, ...] = (),
    kill_after: str | None = None,
) -> ToolRegistry:
    """Реестр с инструментами-заглушками."""
    registry = ToolRegistry()

    @registry.add(
        name="screenshot",
        description="Take a screenshot of the screen.",
        parameters=schema({}),
        risk=Risk.READ,
        category="capture",
    )
    def _screenshot(ctx, args):
        recorder.calls.append(("screenshot", args))
        shot = Screenshot(
            image_bytes=b"shot-bytes",
            mime_type="image/jpeg",
            width=320,
            height=180,
            scale=0.25,
            real_width=1280,
            real_height=720,
        )
        return ToolResult(
            ok=True,
            summary="снимок 320x180",
            images=[shot],
            data={"width": 320, "height": 180},
        )

    @registry.add(
        name="screen_info",
        description="Describe monitors and the active window.",
        parameters=schema({}),
        risk=Risk.READ,
        category="capture",
    )
    def _screen_info(ctx, args):
        recorder.calls.append(("screen_info", args))
        return ToolResult(ok=True, summary="1280x720, активно: Тестовое окно")

    @registry.add(
        name="click",
        description="Click at image pixel coordinates.",
        parameters=schema(
            {
                "x": prop_integer("X pixel of the screenshot"),
                "y": prop_integer("Y pixel of the screenshot"),
            },
            required=["x", "y"],
        ),
        risk=Risk.WRITE,
        category="input",
    )
    def _click(ctx, args):
        recorder.calls.append(("click", args))
        recorder.ctx_shots.append(getattr(ctx, "last_screenshot", None))
        if kill_after == "click":
            kill_switch.trigger()
        if "click" in failing:
            raise RuntimeError("окно не найдено")
        return ToolResult(ok=True, summary=f"клик {args.get('x')},{args.get('y')}")

    if with_finish:

        @registry.add(
            name="finish_task",
            description="Finish the task.",
            parameters=schema(
                {"summary": prop_string("Final answer"), "success": prop_boolean("Task completed")},
                required=["summary", "success"],
            ),
            risk=Risk.READ,
            category="general",
        )
        def _finish(ctx, args):
            recorder.calls.append(("finish_task", args))
            return ToolResult(ok=True, summary=str(args.get("summary") or ""))

    return registry

def make_config(**overrides) -> AppConfig:
    """Конфигурация для тестов: без пауз и без UIA."""
    data = {
        "stub_mode": True,
        "max_steps": 6,
        "action_delay": 0.0,
        "include_uia_tree": False,
        "max_history_images": 3,
        "model": "test-model",
    }
    data.update(overrides)
    return AppConfig(**data)

def make_session(registry, script, *, recorder, bus=None, config=None, screen=None, brain=None):
    """Собрать сессию агента.

    recorder - тот же объект, что писали в make_registry: он собирает и вызовы
    инструментов, и события шины.
    """
    config = config or make_config()
    bus = bus or EventBus()
    bus.subscribe(recorder)
    brain = brain or StubBrain(script)
    if screen is None:
        screen = FakeScreen()   # никаких реальных захватов экрана в тестах
    session = AgentSession(
        config=config,
        registry=registry,
        policy=Policy(confirm_mode="never"),
        bus=bus,
        logger=None,
        brain=brain,
        screen=screen,
    )
    return session, bus, recorder, brain

def finish_step(summary: str = "Готово", success: bool = True) -> dict:
    """Шаг сценария, который завершает задачу."""
    return {
        "thought": "Задача выполнена.",
        "calls": [{"name": "finish_task", "args": {"summary": summary, "success": success}}],
    }

# ---------------------------------------------------------------------------

def test_full_cycle_with_tools_and_events():
    recorder = Recorder()
    registry = make_registry(recorder)
    script = [
        {"thought": "Сначала смотрю на экран.", "calls": [{"name": "screenshot", "args": {}}]},
        {"thought": "Кликаю по кнопке.", "calls": [{"name": "click", "args": {"x": 10, "y": 20}}]},
        finish_step("Кнопка нажата", True),
    ]
    screen = FakeScreen()
    session, _bus, events, _brain = make_session(
        registry, script, recorder=recorder, screen=screen
    )

    result = session.run_task("нажми кнопку")

    assert result.success is True
    assert result.steps == 3
    assert result.final_text == "Кнопка нажата"
    assert result.error is None
    assert events.tool_names() == ["screenshot", "click", "finish_task"]
    assert events.calls[1] == ("click", {"x": 10, "y": 20})

    assert len(events.kinds(KIND_STEP)) == 3
    assert len(events.kinds(KIND_ACTION)) == 3
    assert len(events.kinds(KIND_THOUGHT)) == 3
    assert len(events.kinds(KIND_IMAGE)) == 2          # стартовый снимок + снимок инструмента
    assert len(events.kinds(KIND_DONE)) == 1
    assert len(events.kinds(KIND_RESULT)) >= 2
    done = events.kinds(KIND_DONE)[0]
    assert done.data["success"] is True
    assert done.data["steps"] == 3
    assert session.is_running is False

def test_step_limit_returns_error():
    recorder = Recorder()
    registry = make_registry(recorder)
    script = [{"calls": [{"name": "click", "args": {"x": i, "y": i}}]} for i in range(5)]
    session, _bus, events, _brain = make_session(
        registry, script, recorder=recorder, config=make_config(max_steps=2)
    )

    result = session.run_task("кликай бесконечно")

    assert result.success is False
    assert result.steps == 2
    assert result.error == "превышен лимит шагов"
    assert len(events.kinds(KIND_STEP)) == 2
    assert len(events.kinds(KIND_ERROR)) >= 1

def test_kill_switch_stops_softly():
    recorder = Recorder()
    registry = make_registry(recorder, kill_after="click")
    script = [
        {"calls": [{"name": "click", "args": {"x": 1, "y": 2}}]},
        finish_step("не должно выполниться"),
    ]
    session, _bus, _events, _brain = make_session(registry, script, recorder=recorder)

    result = session.run_task("кликни и остановись")

    assert result.success is False
    assert "остановлено" in (result.error or "")
    assert result.steps == 1
    assert "finish_task" not in recorder.tool_names()

def test_kill_switch_before_start():
    recorder = Recorder()
    registry = make_registry(recorder)
    session, _bus, _events, _brain = make_session(
        registry, [finish_step()], recorder=recorder
    )
    kill_switch.trigger()

    result = session.run_task("что угодно")

    assert result.success is False
    assert result.steps == 0
    assert "остановлено" in (result.error or "")
    assert recorder.calls == []

def test_tool_error_does_not_crash_loop():
    recorder = Recorder()
    registry = make_registry(recorder, failing=("click",))
    script = [
        {"calls": [{"name": "click", "args": {"x": 5, "y": 6}}]},
        finish_step("Не удалось нажать", False),
    ]
    session, _bus, events, _brain = make_session(registry, script, recorder=recorder)

    result = session.run_task("нажми кнопку")

    assert result.success is False                     # finish_task пришёл с success=false
    assert result.steps == 2
    failed = [event for event in events.kinds(KIND_RESULT) if event.data.get("ok") is False]
    assert failed, "ошибка инструмента должна попасть в события"
    assert "окно не найдено" in failed[0].text

def test_last_screenshot_is_remembered_for_tools():
    """Цикл обязан отдавать инструментам геометрию последнего снимка."""
    recorder = Recorder()
    registry = make_registry(recorder)
    script = [
        {"calls": [{"name": "screenshot", "args": {}}]},
        {"calls": [{"name": "click", "args": {"x": 4, "y": 8}}]},
        finish_step("Готово"),
    ]
    session, _bus, _events, _brain = make_session(registry, script, recorder=recorder)

    result = session.run_task("нажми по кнопке")

    assert result.success is True
    assert len(recorder.ctx_shots) == 1
    shot = recorder.ctx_shots[0]
    assert shot is not None, "ctx.last_screenshot должен быть заполнен"
    assert shot.width == 320 and shot.real_width == 1280   # геометрия снимка из инструмента
    assert shot.to_absolute(4, 8) == (16, 32)              # scale = 0.25

def test_parallel_calls_are_batched_into_one_content():
    recorder = Recorder()
    registry = make_registry(recorder)
    script = [
        {
            "thought": "Снимаю экран и читаю информацию параллельно.",
            "calls": [
                {"name": "screenshot", "args": {}},
                {"name": "screen_info", "args": {}},
            ],
        },
        finish_step("Готово"),
    ]
    session, _bus, _events, brain = make_session(registry, script, recorder=recorder)

    result = session.run_task("посмотри на экран")

    assert result.success is True
    assert recorder.tool_names() == ["screenshot", "screen_info", "finish_task"]
    # На втором шаге мозг получил историю: ответы обоих инструментов лежат
    # в одном Content. Снимок идёт СЛЕДУЮЩИМ отдельным сообщением (без
    # текста провайдер его отбрасывает), поэтому ищем Content с ответами,
    # а не берём последний.
    history_at_second_step = brain.seen_contents[1]
    contents_with_responses = [
        content
        for content in history_at_second_step
        if any(getattr(part, "function_response", None) is not None for part in content.parts)
    ]
    assert contents_with_responses, "в истории нет ответов инструментов"
    last_content = contents_with_responses[-1]
    assert last_content.role == "user"
    responses = [
        part for part in last_content.parts if getattr(part, "function_response", None) is not None
    ]
    assert [part.function_response.name for part in responses] == ["screenshot", "screen_info"]

    # Ответы обоих инструментов остались в одном сообщении (батчинг).
    assert len(contents_with_responses) == 1

def test_finish_task_works_without_registered_tool():
    recorder = Recorder()
    registry = make_registry(recorder, with_finish=False)
    session, _bus, _events, brain = make_session(
        registry, [finish_step("Всё готово", True)], recorder=recorder
    )

    result = session.run_task("просто заверши")

    assert result.success is True
    assert result.final_text == "Всё готово"
    declared = [item["name"] for item in brain.seen_declarations[0]]
    assert "finish_task" in declared
    assert "click" in declared

def test_empty_model_answer_is_reported():
    class EmptyBrain:
        def generate(self, contents, tools_declarations=None, system_instruction=None):
            content = SimpleNamespace(role="model", parts=None)
            return SimpleNamespace(candidates=[SimpleNamespace(content=content)])

    recorder = Recorder()
    registry = make_registry(recorder)
    session, _bus, events, _brain = make_session(
        registry, [], recorder=recorder, brain=EmptyBrain()
    )

    result = session.run_task("тишина")

    assert result.success is False
    assert "не вернула" in (result.error or "")
    assert len(events.kinds(KIND_ERROR)) == 1

def test_network_error_retries_once_without_images():
    class FlakyBrain:
        def __init__(self):
            self.images_per_call: list[int] = []
            self._inner = StubBrain([finish_step("Повтор удался")])

        def generate(self, contents, tools_declarations=None, system_instruction=None):
            images = 0
            for content in contents:
                for part in getattr(content, "parts", None) or []:
                    if getattr(part, "inline_data", None) is not None:
                        images += 1
            self.images_per_call.append(images)
            if len(self.images_per_call) == 1:
                raise RuntimeError("500 internal server error")
            return self._inner.generate(contents, tools_declarations, system_instruction)

    recorder = Recorder()
    registry = make_registry(recorder)
    screen = FakeScreen()
    brain = FlakyBrain()
    session, _bus, events, _brain = make_session(
        registry, [], recorder=recorder, screen=screen, brain=brain
    )

    result = session.run_task("проверь повтор")

    assert result.success is True
    assert result.final_text == "Повтор удался"
    assert brain.images_per_call[0] == 1               # первый запрос был со снимком
    assert brain.images_per_call[1] == 0               # повтор пошёл без изображений
    assert screen.captures == 1
    assert len(events.kinds(KIND_IMAGE)) == 1
    assert len(events.kinds(KIND_ERROR)) >= 1

def test_initial_screenshot_and_uia_tree_in_history():
    recorder = Recorder()
    registry = make_registry(recorder)
    screen = FakeScreen()
    config = make_config(include_uia_tree=True)
    session, _bus, events, brain = make_session(
        registry, [finish_step()], recorder=recorder, screen=screen, config=config
    )

    result = session.run_task("осмотрись")

    assert result.success is True
    first_content = brain.seen_contents[0][0]
    assert first_content.role == "user"
    assert any(getattr(part, "inline_data", None) is not None for part in first_content.parts)
    text = "".join(getattr(part, "text", "") or "" for part in first_content.parts)
    assert "осмотрись" in text
    assert "UI AUTOMATION TREE" in text
    assert screen.uia_calls == 1
    assert len(events.kinds(KIND_IMAGE)) == 1
