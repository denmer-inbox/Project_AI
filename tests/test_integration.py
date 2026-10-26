"""Интеграционные проверки: контракты, реестр, конфигурация, безопасность, CLI.

Эти тесты принадлежат Lead и не зависят от внутренностей отдельных модулей.
"""

from __future__ import annotations

import json

import pytest

from pcagent.config import AppConfig, load_config
from pcagent.events import KIND_ASK, Event, EventBus, AskBroker, KillSwitch
from pcagent.interfaces import Risk, Screenshot, image_to_absolute
from pcagent.safety import Policy
from pcagent.tools.base import Tool, ToolContext, ToolRegistry, ToolResult


# ---------------------------------------------------------------- конфигурация
def test_config_defaults_are_sane():
    cfg = AppConfig()
    assert cfg.max_steps >= 1
    assert cfg.confirm_mode in ("never", "risky", "always")
    assert cfg.screenshot_format in ("jpeg", "png")
    assert "capture" in cfg.enabled_categories


def test_config_roundtrip(tmp_path):
    cfg = AppConfig(model="gemini-test", max_steps=7, confirm_mode="always")
    path = cfg.save(tmp_path / "config.yaml")
    again = load_config(path, use_env=False)
    assert again.model == "gemini-test"
    assert again.max_steps == 7
    assert again.confirm_mode == "always"


def test_config_reads_yaml_and_ignores_unknown_keys(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("model: gemini-x\nunknown_option: 5\nmax_steps: 3\n", encoding="utf-8")
    cfg = load_config(path, use_env=False)
    assert cfg.model == "gemini-x"
    assert cfg.extra.get("unknown_option") == 5


def test_config_validate_flags_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    cfg = AppConfig()
    issues = cfg.validate()
    assert any("ключ" in item for item in issues)


# ------------------------------------------------------------------- координаты
def test_screenshot_coordinate_mapping_roundtrip():
    shot = Screenshot(image_bytes=b"", width=640, height=360, scale=0.5, origin_left=100, origin_top=50, real_width=1280, real_height=720)
    assert shot.to_absolute(10, 10) == (120, 70)
    assert shot.to_absolute(639, 359) == (100 + 1278, 50 + 718)
    assert shot.to_image(220, 170) == (60, 60)
    assert image_to_absolute(0, 0, shot) == (100, 50)


def test_screenshot_clamps_out_of_range():
    shot = Screenshot(image_bytes=b"", width=100, height=100, scale=1.0, real_width=100, real_height=100)
    assert shot.to_absolute(500, -50) == (99, 0)


# --------------------------------------------------------------------- политика
def test_policy_denies_dangerous_shell_commands():
    policy = Policy("never", assume_yes=True)
    decision = policy.evaluate("run_command", Risk.WRITE, {"command": "format c: /q"} )
    assert decision.denied


def test_policy_requires_confirmation_for_writes_in_risky_mode():
    policy = Policy("risky")
    decision = policy.evaluate("click", Risk.WRITE, {"x": 1, "y": 2})
    assert decision.allowed and decision.needs_confirmation
    read_decision = policy.evaluate("screenshot", Risk.READ, {})
    assert read_decision.allowed and not read_decision.needs_confirmation


def test_policy_check_asks_confirmer_and_honours_refusal():
    class No:
        def ask(self, question, details="", timeout=None):
            return False

    policy = Policy("risky", confirmer=No())
    decision = policy.check("type_text", Risk.WRITE, {"text": "hi"})
    assert decision.denied


def test_dry_run_marks_actions_without_confirmation():
    class Boom:
        def ask(self, question, details="", timeout=None):
            raise AssertionError("подтверждение не должно запрашиваться в dry-run")

    policy = Policy("risky", dry_run=True, confirmer=Boom())
    decision = policy.check("click", Risk.WRITE, {"x": 0, "y": 0})
    assert decision.allowed and not decision.needs_confirmation


# ------------------------------------------------------------------- реестр
def _ctx(config, registry, bus):
    return ToolContext(config=config, screen=None, policy=Policy("never", assume_yes=True), logger=None, bus=bus, registry=registry)


def test_registry_executes_tool_and_blocks_unknown(config, bus):
    registry = ToolRegistry()

    def handler(ctx, args):
        return ToolResult(ok=True, summary="ok", data={"echo": args.get("value")})

    registry.register(Tool(name="demo", description="demo", parameters={"type": "object", "properties": {}}, risk=Risk.READ, handler=handler))
    ctx = _ctx(config, registry, bus)
    res = registry.execute(ctx, "demo", {"value": 3})
    assert res.ok and res.data["echo"] == 3
    missing = registry.execute(ctx, "nope", {})
    assert not missing.ok and missing.error == "unknown_tool"


def test_registry_converts_handler_exception_into_result(config, bus):
    registry = ToolRegistry()

    def handler(ctx, args):
        raise RuntimeError("сломалось")

    registry.register(Tool(name="boom", description="b", parameters={}, risk=Risk.READ, handler=handler))
    res = registry.execute(_ctx(config, registry, bus), "boom", {})
    assert not res.ok and "сломалось" in (res.error or "")


def test_registry_denies_policy_rejected_tool(config, bus):
    called = []
    registry = ToolRegistry()

    def handler(ctx, args):
        called.append(True)
        return ToolResult()

    registry.register(Tool(name="danger", description="d", parameters={}, risk=Risk.DESTRUCTIVE, handler=handler))
    ctx = ToolContext(config=config, policy=Policy("never", allow_destructive=False), bus=bus)
    res = registry.execute(ctx, "danger", {})
    assert not res.ok and res.error == "policy_denied" and not called


# -------------------------------------------------------------------- события
def test_event_bus_queue_and_subscribers(bus):
    seen = []
    bus.subscribe(seen.append)
    bus.publish(Event.status("привет"))
    assert seen and seen[0].kind == "status"
    drained = bus.drain()
    assert any(e.text == "привет" for e in drained)


def test_ask_broker_releases_on_answer():
    import threading

    bus = EventBus()
    broker = AskBroker(bus, default_timeout=5)
    result: list[bool] = []

    def worker():
        result.append(broker.ask("Разрешить?", "details"))

    thread = threading.Thread(target=worker)
    thread.start()
    event = None
    for _ in range(50):
        event = bus.wait(timeout=1)
        if event is not None and event.kind == KIND_ASK:
            break
    assert event is not None and event.kind == KIND_ASK
    assert broker.answer(event.data["request_id"], True)
    thread.join(timeout=5)
    assert result == [True]


def test_kill_switch():
    sw = KillSwitch()
    assert not sw.triggered
    sw.trigger()
    assert sw.triggered
    sw.reset()
    assert not sw.triggered


# ------------------------------------------------------- целостность инструментов
@pytest.mark.skipif(False, reason="")
def test_all_registered_tool_declarations_are_valid():
    from pcagent.tools.base import build_default_registry

    registry = build_default_registry()
    if len(registry) == 0:
        pytest.skip("Модули инструментов ещё не реализованы")
    declarations = registry.declarations()
    names = [d["name"] for d in declarations]
    assert len(names) == len(set(names)), "имена инструментов должны быть уникальны"
    for declaration in declarations:
        assert isinstance(declaration["name"], str) and declaration["name"]
        assert isinstance(declaration["description"], str) and len(declaration["description"]) > 10
        params = declaration["parameters"]
        assert isinstance(params, dict)
        assert params.get("type") == "object"
        assert isinstance(params.get("properties"), dict)
        json.dumps(params)  # схема должна быть сериализуема
        for required in params.get("required", []):
            assert required in params["properties"]
    categories = set(registry.categories())
    assert {"capture", "input", "windows", "system"} <= categories


def test_tool_result_model_response_is_compact_and_nested():
    shot = Screenshot(image_bytes=b"x", width=10, height=10, scale=1.0)
    res = ToolResult(ok=True, summary="снимок", images=[shot], data={"a": 1})
    payload = res.model_response()
    assert payload["ok"] is True
    assert payload["screenshots"][0]["width"] == 10
    json.dumps(payload)
