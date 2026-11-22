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
    assert payload["version"] == 3
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


def test_tolerant_report_keeps_valid_and_lists_broken(manager):
    good = _profile(manager, "alpha", ["a1"])
    bad = {"id": "плохой id", "base_url": "https://x.example", "models": ["m"]}
    payload = {
        "type": manager.EXPORT_TYPE,
        "version": manager.EXPORT_VERSION,
        "default_model": "alpha/a1",
        "profiles": [good, bad],
    }

    report = manager.profiles_from_export_report(payload)

    assert report["total"] == 2
    assert report["imported"] == 1
    assert report["skipped"] == 1
    assert [p["id"] for p in report["profiles"]] == ["alpha"]
    assert report["default_model"] == "alpha/a1"
    assert report["problems"][0]["index"] == 2
    assert report["problems"][0]["id"] == "плохой id"
    assert report["problems"][0]["error"]

    # строгий разбор на том же файле по-прежнему падает и ничего не отдаёт
    with pytest.raises(ValueError):
        manager.profiles_from_export(payload)


def test_tolerant_report_all_broken_returns_empty(manager):
    payload = {"profiles": [{"id": "плохой id"}, {"id": ""}]}

    report = manager.profiles_from_export_report(payload)

    assert report["imported"] == 0
    assert report["skipped"] == 2
    assert report["profiles"] == []
    with pytest.raises(ValueError):
        manager.profiles_from_export(payload)


def test_tolerant_report_structural_error_still_raises(manager):
    with pytest.raises(ValueError):
        manager.profiles_from_export_report({"nothing": 1})


# --- перенос не должен менять сам конфиг ----------------------------------


def test_export_import_keeps_model_input_types(manager):
    """Круг экспорт→импорт не расширяет типы входа модели.

    Галочка ВЛОЖЕНИЯ раньше дописывала image+audio+video, поэтому модель,
    которая видит только картинки, после импорта начинала «видеть» звук и
    видео — то есть экспорт переносил уже испорченный конфиг.
    """
    profile = _profile(manager, "alpha", ["a1"])
    profile["_raw"] = {
        "name": "Alpha",
        "models": {"a1": {"name": "a1", "capabilities": {
            "tools": True, "input": ["text", "image"], "output": ["text"]}}},
    }
    profile["model_capabilities"] = {
        "a1": manager._capability_flags_from_spec(profile["_raw"]["models"]["a1"]),
    }

    payload = manager.build_export_payload([profile], "alpha/a1")
    restored, _ = manager.profiles_from_export(json.loads(json.dumps(payload)))
    config = manager.apply_profiles({}, restored)

    caps = config["providers"]["alpha"]["models"]["a1"]["capabilities"]
    assert caps["input"] == ["text", "image"]


def test_hidden_models_survive_import_without_raw(manager):
    """Снятые галочки моделей остаются в конфиге выключенными, даже если
    в файле экспорта нет блока raw (старые версии)."""
    payload = {
        "type": manager.EXPORT_TYPE,
        "version": manager.EXPORT_VERSION,
        "profiles": [{
            "id": "alpha",
            "base_url": "https://alpha.example/v1",
            "api_key": "k",
            "package": manager.PACKAGES[0],
            "models": ["a1"],
            "known_models": ["a1", "a2"],
        }],
    }

    restored, _ = manager.profiles_from_export(payload)
    config = manager.apply_profiles({}, restored)
    models = config["providers"]["alpha"]["models"]

    assert "disabled" not in models["a1"]
    assert models["a2"]["disabled"] is True
