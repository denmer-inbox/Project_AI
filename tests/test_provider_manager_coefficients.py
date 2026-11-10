"""Коэффициенты пакетов: отдельный файл, а не `providers.<id>._coefficient`.

Схема OpenCode запрещает лишние свойства внутри провайдера
(`additionalProperties: false`), поэтому `_coefficient` в конфиге давал
ошибки валидации. Теперь значение живёт в `provider_coefficients.json`
рядом с `opencode.json`, а старое поле при записи вычищается.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "opencode_provider_manager.py"
MODULE_NAME = "opencode_provider_manager"


@pytest.fixture(scope="module")
def manager():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(MODULE_NAME, None)
        raise
    return module


def _profile(pid="alpha", coefficient="1.25"):
    return {
        "id": pid,
        "display_name": pid.title(),
        "coefficient": coefficient,
        "base_url": "https://%s.example/v1" % pid,
        "package": "@ai-sdk/openai-compatible",
        "api_key": "key-" + pid,
        "models": ["m1"],
        "known_models": ["m1"],
        "model_capabilities": {},
        "extra_settings": {},
        "_raw": {},
    }


def _has_coefficient(obj):
    if isinstance(obj, dict):
        return any(key == "_coefficient" or _has_coefficient(value)
                   for key, value in obj.items())
    if isinstance(obj, list):
        return any(_has_coefficient(value) for value in obj)
    return False


# --- файл коэффициентов ---------------------------------------------------


def test_save_and_load_coefficients_round_trip(manager, tmp_path):
    config_path = tmp_path / "opencode.json"
    target = manager.save_coefficients(config_path, {"alpha": " 1.25 ", "beta": ""})
    assert target == tmp_path / "provider_coefficients.json"
    assert manager.load_coefficients(config_path) == {"alpha": "1.25"}


def test_save_empty_coefficients_removes_file(manager, tmp_path):
    config_path = tmp_path / "opencode.json"
    manager.save_coefficients(config_path, {"alpha": "2"})
    assert (tmp_path / "provider_coefficients.json").exists()
    manager.save_coefficients(config_path, {"alpha": ""})
    assert not (tmp_path / "provider_coefficients.json").exists()


def test_load_coefficients_ignores_broken_file(manager, tmp_path):
    config_path = tmp_path / "opencode.json"
    (tmp_path / "provider_coefficients.json").write_text("{не json", encoding="utf-8")
    assert manager.load_coefficients(config_path) == {}


# --- конфиг не содержит служебное поле -----------------------------------


def test_build_provider_does_not_write_coefficient(manager):
    proxy = manager.build_provider(_profile(coefficient="3.5"))
    assert "_coefficient" not in proxy


def test_build_provider_removes_stale_coefficient_from_raw(manager):
    profile = _profile()
    profile["_raw"] = {"name": "Alpha", "_coefficient": "9"}
    proxy = manager.build_provider(profile)
    assert "_coefficient" not in proxy


def test_apply_profiles_strips_coefficient_everywhere(manager):
    config = {
        "providers": {"foreign": {"name": "Foreign", "_coefficient": "2",
                                  "models": {}}},
        "mcp": {"servers": {}},
    }
    applied = manager.apply_profiles(config, [_profile(coefficient="4")],
                                     keep_ids={"foreign"})
    assert not _has_coefficient(applied)
    assert applied["providers"]["foreign"]["name"] == "Foreign"
    assert applied["mcp"] == {"servers": {}}


def test_merge_profiles_strips_stale_coefficient(manager):
    config = {"providers": {"alpha": {"name": "Alpha", "_coefficient": "9",
                                      "models": {}}}}
    merged = manager.merge_profiles_into_config(config, [_profile(coefficient="2")])
    assert not _has_coefficient(merged)


# --- чтение ---------------------------------------------------------------


def test_profiles_from_config_prefers_sidecar_value(manager):
    config = {"providers": {"alpha": {"name": "Alpha", "_coefficient": "9",
                                      "models": {}}}}
    profile = manager.profiles_from_config(config, {"alpha": "1.5"})[0]
    assert profile["coefficient"] == "1.5"


def test_profiles_from_config_falls_back_to_old_field(manager):
    config = {"providers": {"alpha": {"name": "Alpha", "_coefficient": "9",
                                      "models": {}}}}
    profile = manager.profiles_from_config(config)[0]
    assert profile["coefficient"] == "9"


# --- перенос в OpenCode ---------------------------------------------------


def test_transfer_opencode_saves_coefficients_sidecar(manager, tmp_path):
    config_path = tmp_path / "opencode.json"
    result = manager._transfer_opencode([_profile(coefficient="2.5")], "",
                                        config_path=config_path)
    assert result["ok"] is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert not _has_coefficient(saved)
    assert manager.load_coefficients(config_path) == {"alpha": "2.5"}
