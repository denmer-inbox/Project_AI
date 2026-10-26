# -*- coding: utf-8 -*-
"""Регресс-тесты: allow_shell закрывает ВСЕ пути запуска кода."""
from __future__ import annotations

import pytest

from pcagent.interfaces import Risk
from pcagent.safety import Policy


@pytest.mark.parametrize("tool", ["run_command", "run_script", "run_powershell", "run_cmd"])
def test_allow_shell_false_blocks_every_execution_path(tool):
    """Флаг allow_shell=false не должен оставлять обходных путей."""
    policy = Policy("risky", assume_yes=True, allow_shell=False)
    decision = policy.evaluate(tool, Risk.WRITE, {"script": "Get-Date", "command": "echo hi"})
    assert decision.denied, f"{tool} обходит allow_shell=false"


@pytest.mark.parametrize("tool", ["run_command", "run_script", "run_powershell"])
def test_allow_shell_true_keeps_tools_available(tool):
    policy = Policy("risky", assume_yes=True, allow_shell=True)
    decision = policy.evaluate(tool, Risk.WRITE, {"script": "Get-Date", "command": "echo hi"})
    assert decision.allowed


@pytest.mark.parametrize(
    "payload",
    ["shutdown /s /t 0", "format c: /q", "diskpart", "vssadmin delete shadows", "bcdedit /set"],
)
def test_deny_list_applies_to_run_script_payload(payload):
    """Опасные команды внутри скрипта ловятся так же, как в run_command."""
    policy = Policy("risky", assume_yes=True)
    decision = policy.evaluate("run_script", Risk.WRITE, {"script": payload})
    assert decision.denied


def test_console_tools_are_registered_for_cli_too():
    """CLI и GUI должны видеть одинаковый набор инструментов."""
    from pcagent.tools.base import build_default_registry

    registry = build_default_registry()
    assert "run_script" in registry
    assert "run_powershell" in registry
    assert registry.get("run_script").risk is Risk.WRITE
