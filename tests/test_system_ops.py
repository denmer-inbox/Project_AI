"""Тесты системных инструментов: команды, сведения о ПК, буфер обмена, оболочка.

Реальные проверки ограничены безопасными операциями: echo, сведения о системе и
буфер обмена (с восстановлением исходного содержимого).
"""

from __future__ import annotations

import json
import os
import time

import pytest

from pcagent.config import AppConfig
from pcagent.events import EventBus
from pcagent.interfaces import MonitorInfo, Risk
from pcagent.safety import Policy
from pcagent.tools.base import ToolContext, ToolRegistry

import pcagent.system_ops as system_ops

EXPECTED_TOOLS = {"run_command", "get_system_info", "open_path", "start_uri", "clipboard_get", "clipboard_set"}


class FakeScreen:
    """Сервис экрана без реального захвата."""

    def monitors(self):
        return [MonitorInfo(0, 0, 0, 2560, 1440, True)]

    def capture(self, monitor=None, max_width=None, fmt=None, quality=None):
        raise AssertionError("system_ops не должен захватывать экран")

    def size(self, monitor=None):
        return (2560, 1440)

    def uia_tree(self, max_nodes=None):
        return ""

    def active_window(self):
        return None

    def close(self):
        pass


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    system_ops.register(reg)
    return reg


@pytest.fixture()
def ctx(config, bus, registry) -> ToolContext:
    return ToolContext(
        config=config,
        screen=FakeScreen(),
        policy=Policy("never", assume_yes=True),
        bus=bus,
        registry=registry,
    )


def _run(ctx, **args):
    return ctx.registry.execute(ctx, "run_command", args)


# --------------------------------------------------------------- регистрация
def test_system_tools_are_registered(registry):
    assert set(registry.names()) == EXPECTED_TOOLS
    assert registry.categories() == ["system"]


def test_system_declarations_and_risks(registry):
    risk_map = {
        "run_command": Risk.WRITE,
        "get_system_info": Risk.READ,
        "open_path": Risk.WRITE,
        "start_uri": Risk.WRITE,
        "clipboard_get": Risk.READ,
        "clipboard_set": Risk.WRITE,
    }
    for declaration in registry.declarations():
        assert declaration["name"] in EXPECTED_TOOLS
        assert len(declaration["description"]) > 20
        params = declaration["parameters"]
        assert params["type"] == "object"
        json.dumps(params)
        for required in params.get("required", []):
            assert required in params["properties"]
    for name, risk in risk_map.items():
        assert registry.get(name).risk is risk
        assert registry.get(name).category == "system"


# ------------------------------------------------------------ get_system_info
def test_get_system_info_has_expected_fields(ctx):
    result = ctx.registry.execute(ctx, "get_system_info", {})
    assert result.ok, result.error
    data = result.data
    assert data["os"]["system"]
    assert data["os"]["release"]
    assert data["computer_name"]
    assert data["user"]
    assert data["screen"]["width"] == 2560
    assert data["screen"]["height"] == 1440
    assert data["screen"]["monitors"][0]["width"] == 2560
    assert data["memory"] is None or data["memory"]["total_gb"] > 0
    assert data["disk"] is None or data["disk"]["total_gb"] > 0
    assert data["now"]
    assert "Windows" in result.summary


def test_get_system_info_without_screen_uses_win32(config, bus, registry):
    ctx = ToolContext(config=config, screen=None, policy=Policy("never", assume_yes=True), bus=bus, registry=registry)
    result = ctx.registry.execute(ctx, "get_system_info", {})
    assert result.ok, result.error
    assert result.data["screen"]["width"] > 0
    assert result.data["screen"]["height"] > 0


# --------------------------------------------------------------- run_command
def test_run_command_cmd_echo(ctx):
    result = _run(ctx, command="echo hello", shell="cmd")
    assert result.ok, result.error
    assert "hello" in result.data["stdout"]
    assert result.data["exit_code"] == 0
    assert result.data["timeout"] is False


def test_run_command_powershell_unicode(ctx):
    result = _run(ctx, command="Write-Output привет", shell="powershell")
    assert result.ok, result.error
    assert result.data["stdout"].strip() == "привет"


def test_run_command_nonzero_exit_reports_code(ctx):
    result = _run(ctx, command="exit 3", shell="cmd")
    assert not result.ok
    assert result.error == "exit_code_3"
    assert result.data["exit_code"] == 3


def test_run_command_timeout_is_reported(ctx):
    started = time.monotonic()
    result = _run(ctx, command="Start-Sleep -Seconds 10", shell="powershell", timeout=1)
    elapsed = time.monotonic() - started
    assert not result.ok and result.error == "timeout"
    assert result.data["timeout"] is True
    assert elapsed < 8


def test_run_command_truncates_long_output(ctx):
    command = 'for /L %i in (1,1,900) do @echo 0123456789'
    result = _run(ctx, command=command, shell="cmd")
    assert result.ok, result.error
    assert result.data["truncated"]["stdout"] is True
    assert len(result.data["stdout"]) <= system_ops.MAX_OUTPUT + 40


def test_run_command_argument_validation(ctx):
    assert _run(ctx, command="   ").error == "bad_arguments"
    assert _run(ctx, command="echo hi", shell="bash").error == "bad_shell"
    assert _run(ctx, command="echo hi", shell="cmd", cwd="C:\\zzz-no-such-dir").error == "bad_arguments"


def test_run_command_respects_allow_shell_false(config, bus, registry):
    strict = AppConfig(stub_mode=True, confirm_mode="never", allow_shell=False)
    ctx = ToolContext(config=strict, policy=Policy("never", assume_yes=True), bus=bus, registry=registry)
    result = _run(ctx, command="echo hello", shell="cmd")
    assert not result.ok and result.error == "shell_disabled"


def test_run_command_is_blocked_by_policy_for_shutdown(ctx):
    result = _run(ctx, command="shutdown /s /t 0", shell="cmd")
    assert not result.ok and result.error == "policy_denied"


def test_run_command_dry_run_skips_execution(ctx):
    ctx.dry_run = True
    result = _run(ctx, command="echo hello", shell="cmd")
    assert result.ok and result.data.get("dry_run") is True
    assert "stdout" not in result.data


# ---------------------------------------------------------- open_path / URI
def test_open_path_rejects_missing_path(ctx):
    result = ctx.registry.execute(ctx, "open_path", {"path": "C:\\zzz-no-such-file-zzz.txt"})
    assert not result.ok and result.error == "path_not_found"
    empty = ctx.registry.execute(ctx, "open_path", {"path": ""})
    assert not empty.ok and empty.error == "bad_arguments"


def test_start_uri_rejects_unsafe_scheme(ctx):
    result = ctx.registry.execute(ctx, "start_uri", {"uri": "file:///C:/Windows/System32/cmd.exe"})
    assert not result.ok and result.error == "bad_uri"
    empty = ctx.registry.execute(ctx, "start_uri", {"uri": ""})
    assert not empty.ok and empty.error == "bad_arguments"


# --------------------------------------------------------------- clipboard
def _clipboard_set_with_retry(ctx, text: str):
    last = None
    for _attempt in range(3):
        last = ctx.registry.execute(ctx, "clipboard_set", {"text": text})
        if last.ok:
            return last
        time.sleep(0.1)
    return last


def test_clipboard_roundtrip_restores_original(ctx):
    import pyperclip

    original = pyperclip.paste() or ""
    try:
        set_result = _clipboard_set_with_retry(ctx, "PCAGENT_CLIPBOARD_TEST_42")
        assert set_result.ok, set_result.error
        get_result = ctx.registry.execute(ctx, "clipboard_get", {})
        assert get_result.ok, get_result.error
        assert get_result.data["text"] == "PCAGENT_CLIPBOARD_TEST_42"
        assert get_result.data["length"] == len("PCAGENT_CLIPBOARD_TEST_42")
        assert get_result.data["truncated"] is False
    finally:
        pyperclip.copy(original)


def test_clipboard_get_truncates_long_text(ctx, monkeypatch):
    import pyperclip

    long_text = "x" * (system_ops.MAX_OUTPUT + 500)
    monkeypatch.setattr(pyperclip, "paste", lambda: long_text)
    result = ctx.registry.execute(ctx, "clipboard_get", {})
    assert result.ok, result.error
    assert result.data["truncated"] is True
    assert len(result.data["text"]) <= system_ops.MAX_OUTPUT + 40
    assert result.data["length"] == len(long_text)


def test_clipboard_get_reports_failure(ctx, monkeypatch):
    import pyperclip

    def boom():
        raise RuntimeError("буфер занят")

    monkeypatch.setattr(pyperclip, "paste", boom)
    result = ctx.registry.execute(ctx, "clipboard_get", {})
    assert not result.ok
    assert (result.error or "").startswith("clipboard_failed")


def test_clipboard_set_requires_text(ctx):
    result = ctx.registry.execute(ctx, "clipboard_set", {})
    assert not result.ok and result.error == "bad_arguments"
