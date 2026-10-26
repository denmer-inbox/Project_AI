"""Экспорт профилей менеджера OpenCode: в файл должны попадать все профили."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "opencode_provider_manager.py"


@pytest.fixture(scope="module")
def manager():
    spec = importlib.util.spec_from_file_location("opencode_provider_manager", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile(manager, pid, models):
    return {
        "id": pid,
        "display_name": pid.title(),
        "coefficient": "",
        "base_url": "https://%s.example" % pid,
        "package": manager.PACKAGES[0],
        "api_key": "key-" + pid,
        "models": list(models),
        "known_models": list(models) + ["hidden-model"],
        "extra_settings": {},
        "_raw": {"name": pid.title()},
    }


def test_export_payload_contains_every_profile(manager):
    profiles = [
        _profile(manager, "alpha", ["a1", "a2"]),
        _profile(manager, "beta", ["b1"]),
        _profile(manager, "gamma", ["g1"]),
    ]
    payload = manager.build_export_payload(profiles, "alpha/a1")

    assert payload["type"] == "opencode-provider-profiles"
    assert payload["version"] == 2
    assert [p["id"] for p in payload["profiles"]] == ["alpha", "beta", "gamma"]
    assert payload["default_model"] == "alpha/a1"
    assert "raw" in payload["profiles"][0]
    assert "_raw" not in payload["profiles"][0]


def test_export_payload_without_default_model(manager):
    payload = manager.build_export_payload([_profile(manager, "alpha", ["a1"])], "(не задана)")
    assert "default_model" not in payload


def test_round_trip_all_profiles(manager):
    profiles = [
        _profile(manager, "alpha", ["a1"]),
        _profile(manager, "beta", ["b1", "b2"]),
    ]
    text = json.dumps(manager.build_export_payload(profiles, "beta/b1"), ensure_ascii=False)

    restored, default_model = manager.profiles_from_export(json.loads(text))

    assert [p["id"] for p in restored] == ["alpha", "beta"]
    assert default_model == "beta/b1"
    assert restored[1]["models"] == ["b1", "b2"]
    assert restored[1]["api_key"] == "key-beta"


def test_legacy_single_profile_file_still_imports(manager):
    legacy = {
        "version": 1,
        "type": "opencode-provider-profile",
        "id": "old",
        "display_name": "Old",
        "base_url": "https://old.example",
        "package": manager.PACKAGES[0],
        "api_key": "k",
        "models": ["m1"],
        "known_models": ["m1", "m2"],
        "extra_settings": {},
        "raw": {},
    }

    restored, default_model = manager.profiles_from_export(legacy)

    assert [p["id"] for p in restored] == ["old"]
    assert default_model == ""
    assert restored[0]["known_models"] == ["m1", "m2"]


def test_plain_list_of_profiles_imports(manager):
    restored, _ = manager.profiles_from_export([{"id": "solo", "models": ["m"]}])
    assert [p["id"] for p in restored] == ["solo"]
    assert restored[0]["known_models"] == ["m"]


@pytest.mark.parametrize("bad", [
    {"no_profiles": True},
    {"profiles": []},
    {"profiles": [{"id": "плохой id"}]},
    [],
])
def test_bad_export_files_raise(manager, bad):
    with pytest.raises(ValueError):
        manager.profiles_from_export(bad)


def test_all_profiles_land_in_config(manager):
    profiles = [
        _profile(manager, "alpha", ["a1"]),
        _profile(manager, "beta", ["b1"]),
    ]
    config = manager.apply_profiles({"model": "alpha/a1"}, profiles)

    assert sorted(config["providers"]) == ["alpha", "beta"]
    assert config["model"] == "alpha/a1"
