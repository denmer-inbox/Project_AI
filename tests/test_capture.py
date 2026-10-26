"""Тесты модуля pcagent.capture: только чтение, реальный экран этой машины."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

from pcagent.capture import Screen, fit_size, register
from pcagent.config import AppConfig
from pcagent.events import EventBus
from pcagent.interfaces import Risk, ScreenService
from pcagent.safety import Policy
from pcagent.tools.base import ToolContext, ToolRegistry


def _decode(image_bytes: bytes):
    from PIL import Image

    return Image.open(BytesIO(image_bytes))


@pytest.fixture(scope="module")
def screen():
    instance = Screen(
        AppConfig(
            confirm_mode="never",
            save_screenshots=False,
            screenshot_max_width=800,
            screenshot_quality=70,
            uia_max_nodes=40,
        )
    )
    yield instance
    instance.close()


# --------------------------------------------------------------- масштаб
def test_fit_size_scales_without_upscaling():
    assert fit_size(2560, 1440, 1280) == (1280, 720)
    assert fit_size(1920, 1080, 800) == (800, 450)
    assert fit_size(800, 600, 1280) == (800, 600)          # без апскейла
    assert fit_size(1000, 1000, 333) == (333, 333)
    assert fit_size(1000, 1, 500) == (500, 1)              # высота не уходит в ноль
    assert fit_size(0, 0, 100) == (1, 1)
    assert fit_size(640, 480, None) == (640, 480)
    width, height = fit_size(2560, 1440, 640)
    assert width == 640 and height == 360


# --------------------------------------------------------------- мониторы
def test_monitors_and_size_are_consistent(screen):
    monitors = screen.monitors()
    assert monitors, "должен найтись хотя бы один монитор"
    for monitor in monitors:
        assert monitor.width > 0 and monitor.height > 0
        assert monitor.right == monitor.left + monitor.width
        assert monitor.bottom == monitor.top + monitor.height

    first = monitors[0]
    assert screen.size(0) == (first.width, first.height)

    desktop = screen.desktop()
    assert desktop["width"] >= first.width
    assert desktop["height"] >= first.height
    assert screen.size(-1) == (desktop["width"], desktop["height"])
    assert isinstance(screen, ScreenService)


# ------------------------------------------------- снимок и координаты
def test_capture_real_screen_and_coordinate_mapping(screen):
    shot = screen.capture(max_width=640)
    assert shot.image_bytes
    image = _decode(shot.image_bytes)
    assert (image.width, image.height) == (shot.width, shot.height)
    assert shot.width <= 640
    assert shot.real_width >= shot.width and shot.real_height > 0
    assert shot.scale == pytest.approx(shot.width / shot.real_width, rel=1e-9)
    assert shot.monitor == 0
    assert shot.origin_left == screen.monitors()[0].left
    assert shot.origin_top == screen.monitors()[0].top

    # пиксель снимка -> координата рабочего стола и обратно
    assert shot.to_absolute(0, 0) == (shot.origin_left, shot.origin_top)
    abs_x, abs_y = shot.to_absolute(shot.width - 1, shot.height - 1)
    assert shot.origin_left <= abs_x <= shot.origin_left + shot.real_width - 1
    assert shot.origin_top <= abs_y <= shot.origin_top + shot.real_height - 1
    assert shot.to_image(shot.origin_left, shot.origin_top) == (0, 0)
    assert shot.to_absolute(10_000, 10_000) == (
        shot.origin_left + shot.real_width - 1,
        shot.origin_top + shot.real_height - 1,
    )


def test_capture_encodes_jpeg_and_png_and_saves_file(tmp_path):
    config = AppConfig(
        screenshot_max_width=320,
        screenshot_format="jpeg",
        screenshot_quality=60,
        save_screenshots=True,
        screenshot_dir=str(tmp_path),
    )
    instance = Screen(config)
    try:
        jpeg = instance.capture()
        assert jpeg.mime_type == "image/jpeg"
        assert _decode(jpeg.image_bytes).format == "JPEG"
        assert jpeg.width <= 320
        assert jpeg.path and Path(jpeg.path).exists()
        assert Path(jpeg.path).read_bytes() == jpeg.image_bytes

        png = instance.capture(fmt="png")
        assert png.mime_type == "image/png"
        assert _decode(png.image_bytes).format == "PNG"
        assert png.path and png.path.endswith(".png")

        full = instance.capture(max_width=100000)
        assert full.width == full.real_width
        assert full.scale == pytest.approx(1.0)
        assert full.height == full.real_height
    finally:
        instance.close()


# ------------------------------------------------------------ UIA-дерево
def test_uia_tree_returns_text_without_crashing(screen):
    tree = screen.uia_tree(max_nodes=15)
    assert isinstance(tree, str)
    if tree.startswith("UIA недоступен"):
        pytest.skip("uiautomation недоступен на этой машине")
    if tree == "":
        pytest.skip("UIA вернул пустое дерево (рабочий стол недоступен)")
    lines = [line for line in tree.splitlines() if line.strip()]
    assert lines
    assert len(lines) <= 16, "должен соблюдаться лимит узлов плюс маркер обрезки"
    assert "[" in tree and "]" in tree
    assert screen.uia_tree(max_nodes=1)  # повторный вызов не падает


# ------------------------------------------------------ инструменты capture
def test_capture_tools_registered_with_read_risk_and_valid_schema(tmp_path):
    registry = ToolRegistry()
    register(registry)
    assert set(registry.names()) == {"screenshot", "screen_info", "ui_tree"}
    assert registry.categories() == ["capture"]

    for tool in registry.all():
        assert tool.risk is Risk.READ, "все инструменты capture только читают"
        assert isinstance(tool.description, str) and len(tool.description) > 10
        parameters = tool.parameters
        assert parameters.get("type") == "object"
        assert isinstance(parameters.get("properties"), dict)
        json.dumps(parameters)
        for required in parameters.get("required", []):
            assert required in parameters["properties"]

    config = AppConfig(
        screenshot_max_width=400,
        uia_max_nodes=20,
        save_screenshots=False,
        confirm_mode="never",
    )
    instance = Screen(config)
    ctx = ToolContext(
        config=config,
        screen=instance,
        policy=Policy("never", assume_yes=True),
        logger=None,
        bus=EventBus(),
        registry=registry,
    )
    try:
        shot = registry.execute(ctx, "screenshot", {})
        assert shot.ok, shot.error
        assert shot.summary and shot.images
        assert shot.images[0].width <= 400

        info = registry.execute(ctx, "screen_info", {})
        assert info.ok, info.error
        assert info.data["monitors"]
        active = info.data["active_window"]
        assert active is None or {"title", "pid", "left", "top", "width", "height"} <= set(active)
        assert info.summary

        tree = registry.execute(ctx, "ui_tree", {"max_nodes": 10})
        assert tree.ok, tree.error
        assert tree.summary

        bad = registry.execute(ctx, "ui_tree", {"max_nodes": "много"})
        assert not bad.ok and bad.error == "bad_argument"
    finally:
        instance.close()
