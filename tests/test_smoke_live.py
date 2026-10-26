"""Живые smoke-проверки на этой машине (только READ-операции).

Пропускаются, если соответствующий модуль ещё не реализован.
"""

from __future__ import annotations

import pytest

from pcagent.config import AppConfig
from pcagent.events import EventBus
from pcagent.safety import Policy
from pcagent.tools.base import ToolContext, build_default_registry


@pytest.fixture(scope="module")
def live():
    pytest.importorskip("pcagent.capture", reason="модуль capture ещё не реализован")
    from pcagent.capture import Screen

    screen = Screen()
    config = AppConfig(confirm_mode="never", save_screenshots=False, screenshot_max_width=800, uia_max_nodes=60)
    registry = build_default_registry()
    ctx = ToolContext(
        config=config,
        screen=screen,
        policy=Policy("never", assume_yes=True),
        logger=None,
        bus=EventBus(),
        registry=registry,
    )
    yield config, registry, ctx, screen
    try:
        screen.close()
    except Exception:  # noqa: BLE001
        pass


def test_screen_capture_produces_decodable_image(live):
    _, _, _, screen = live
    shot = screen.capture(max_width=800)
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(shot.image_bytes))
    assert image.width <= 800
    assert shot.scale == pytest.approx(shot.width / shot.real_width, rel=1e-3)
    assert shot.real_width > 0 and shot.real_height > 0


def test_read_only_tools_work_end_to_end(live):
    _, registry, ctx, _ = live
    for name, args in (
        ("screenshot", {}),
        ("screen_info", {}),
        ("ui_tree", {"max_nodes": 30}),
        ("list_windows", {}),
        ("get_system_info", {}),
    ):
        if name not in registry:
            pytest.skip(f"инструмент {name} ещё не зарегистрирован")
        result = registry.execute(ctx, name, args)
        assert result.ok, f"{name}: {result.error}"
        assert result.summary


def test_finish_and_dry_run_click_do_not_touch_desktop(live):
    _, registry, ctx, screen = live
    if "click" not in registry:
        pytest.skip("модуль input_control ещё не готов")
    ctx.dry_run = True
    result = registry.execute(ctx, "click", {"x": 5, "y": 5})
    assert result.ok and result.data.get("dry_run") is True
