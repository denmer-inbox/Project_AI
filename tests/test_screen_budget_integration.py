# -*- coding: utf-8 -*-
"""Регресс-тест: инструменты мыши не тратят бюджет снимков модели."""
import sys
sys.path.insert(0, r"C:\Users\nickd\Downloads\Project_AI")
from pcagent.capture import Screen
from pcagent.config import AppConfig
from pcagent.events import EventBus
from pcagent.gui.screen_policy import SmartScreenGate
from pcagent.interfaces import Risk
from pcagent.safety import Policy
from pcagent.tools.base import ToolContext, build_default_registry
import pcagent.input_control as ic


class FakeInner:
    """Сервис экрана-заглушка с учётом реальных вызовов."""

    def __init__(self):
        self.calls = 0

    def capture(self, *args, **kwargs):
        self.calls += 1
        from pcagent.interfaces import Screenshot

        return Screenshot(image_bytes=b"x" * 10, width=100, height=50, scale=0.5,
                          origin_left=0, origin_top=0, real_width=200, real_height=100)

    def uia_tree(self, max_nodes=None):
        return ""


def test_tool_geometry_does_not_consume_budget():
    inner = FakeInner()
    gate = SmartScreenGate(inner, allow_initial=True, extra={})
    cfg = AppConfig(confirm_mode="never")
    ctx = ToolContext(config=cfg, screen=gate, policy=Policy("never", assume_yes=True),
                      bus=EventBus(), registry=build_default_registry())

    # инструмент запрашивает геометрию -> бюджет не тратится
    shot, err = ic._shot_or_fail(ctx)
    assert shot is not None, err.error if err else "нет снимка"
    assert gate.budget.used == 0, "геометрия не должна тратить бюджет модели"

    # снимок модели тратит бюджет
    model_shot = gate.capture(monitor=0, max_width=1024, fmt="jpeg", quality=60)
    assert model_shot is not None
    assert gate.budget.used == 1

    # клик теперь использует запомненный снимок, а не новый
    ctx.remember_screenshot(model_shot)
    before_calls = inner.calls
    shot2, err2 = ic._shot_or_fail(ctx)
    assert shot2 is not None
    assert inner.calls == before_calls, "клик не должен делать новый снимок"
    assert gate.budget.used == 1


def test_budget_exhaustion_does_not_break_clicks():
    inner = FakeInner()
    gate = SmartScreenGate(inner, allow_initial=True, extra={"screenshot_max_per_task": 1})
    cfg = AppConfig(confirm_mode="never")
    ctx = ToolContext(config=cfg, screen=gate, policy=Policy("never", assume_yes=True),
                      bus=EventBus(), registry=build_default_registry())
    gate.capture(monitor=0, max_width=1024)  # 1/1
    shot, err = ic._shot_or_fail(ctx)
    assert shot is not None, "клик обязан работать даже при исчерпанном бюджете"


def test_agent_integrates_with_context():
    """Не должно падать при отсутствии сервиса экрана."""
    ctx = ToolContext(config=AppConfig(), screen=None)
    shot, err = ic._shot_or_fail(ctx)
    assert shot is None and err is not None and err.error == "screen_unavailable"
