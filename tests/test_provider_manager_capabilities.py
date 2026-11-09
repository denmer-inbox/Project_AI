"""Возможности моделей (vision/web/…), галочки и ключи в opencode.json."""

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


def _profile(pid="alpha", models=("m1",), caps=None, package=None, key="key-alpha"):
    return {
        "id": pid,
        "display_name": pid.title(),
        "coefficient": "",
        "base_url": "https://%s.example/v1" % pid,
        "package": package or "@ai-sdk/openai-compatible",
        "api_key": key,
        "models": list(models),
        "known_models": list(models),
        "model_capabilities": caps if caps is not None else {},
        "extra_settings": {},
        "_raw": {"name": pid.title()},
    }


# --- запись галочек в конфиг ----------------------------------------------


def test_capabilities_flags_are_written_to_config(manager):
    flags = {
        "tools": True,
        "vision": True,
        "audio": True,
        "video": False,
        "web": True,
        "reasoning": True,
        "temperature": True,
        "attachment": False,
    }
    config = manager.apply_profiles({}, [_profile(caps={"m1": flags})])
    spec = config["providers"]["alpha"]["models"]["m1"]

    assert spec["capabilities"]["tools"] is True
    assert spec["capabilities"]["input"] == ["text", "image", "audio"]
    assert "video" not in spec["capabilities"]["input"]
    assert spec["capabilities"]["output"] == ["text", "web"]
    assert spec["capabilities"]["reasoning"] == {"supported": True}
    assert spec["capabilities"]["temperature"] is True
    # ключа attachment у модели нет: схема OpenCode его запрещает,
    # вложения выражаются типами входа image/audio/video
    assert "attachment" not in spec


def test_attachment_does_not_add_unknown_model_key(manager):
    """ВЛОЖЕНИЯ не пишут несуществующий ключ и добавляют типы входа."""
    flags = {"vision": False, "audio": False, "video": False, "attachment": True}
    config = manager.apply_profiles({}, [_profile(caps={"m1": flags})])
    spec = config["providers"]["alpha"]["models"]["m1"]

    assert "attachment" not in spec
    assert spec["capabilities"]["input"] == ["text", "image", "audio", "video"]


def test_attachment_off_removes_legacy_key(manager):
    """Мусорный attachment:true из старой версии вычищается при применении."""
    raw = {"name": "Alpha", "models": {"m1": {
        "name": "m1", "attachment": True,
        "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
    }}}
    profile = _profile(caps={"m1": {"vision": False}})
    profile["_raw"] = raw
    config = manager.apply_profiles({}, [profile])

    assert "attachment" not in config["providers"]["alpha"]["models"]["m1"]


def test_attachment_flag_follows_input_types(manager):
    spec = {"capabilities": {"input": ["text", "image"], "output": ["text"]}}
    assert manager._capability_flags_from_spec(spec)["attachment"] is True
    plain = {"capabilities": {"input": ["text"], "output": ["text"]}}
    assert manager._capability_flags_from_spec(plain)["attachment"] is False


def test_capabilities_off_removes_previous_vision(manager):
    raw = {
        "name": "Alpha",
        "models": {
            "m1": {
                "name": "m1",
                "capabilities": {"tools": True, "input": ["text", "image"],
                                 "output": ["text"]},
            },
        },
    }
    profile = _profile(caps={"m1": {"vision": False, "tools": True, "web": False}})
    profile["_raw"] = raw
    config = manager.apply_profiles({}, [profile])
    caps = config["providers"]["alpha"]["models"]["m1"]["capabilities"]

    assert caps["input"] == ["text"]
    assert caps["output"] == ["text"]
    assert caps["tools"] is True


def test_reasoning_off_removes_key_even_with_extra_fields(manager):
    """Снятая галочка reasoning не оставляет supported:false с effort."""
    raw = {"name": "Alpha", "models": {"m1": {
        "name": "m1",
        "capabilities": {"input": ["text"], "output": ["text"],
                         "reasoning": {"supported": True, "effort": ["low", "high"]}},
    }}}
    profile = _profile(caps={"m1": {"reasoning": False}})
    profile["_raw"] = raw
    config = manager.apply_profiles({}, [profile])
    caps = config["providers"]["alpha"]["models"]["m1"]["capabilities"]

    assert "reasoning" not in caps
    # при чтении галочка будет «выключено» (её просто нет в конфиге)
    loaded = manager.profiles_from_config(config)[0]["model_capabilities"]["m1"]
    assert not loaded.get("reasoning")


def test_reasoning_dict_without_supported_reads_as_enabled(manager):
    assert manager._capability_flags_from_spec(
        {"capabilities": {"reasoning": {"effort": ["low"]}}})["reasoning"] is True


def test_missing_flags_keep_existing_capabilities(manager):
    """Профиль без галочек (старый экспорт) не портит capabilities."""
    raw = {
        "name": "Alpha",
        "models": {
            "m1": {
                "name": "m1",
                "capabilities": {"tools": True, "input": ["text", "image"],
                                 "output": ["text", "web"],
                                 "reasoning": {"supported": True, "effort": ["low"]}},
            },
        },
    }
    profile = _profile(caps={})
    profile["_raw"] = raw
    config = manager.apply_profiles({}, [profile])
    caps = config["providers"]["alpha"]["models"]["m1"]["capabilities"]

    assert caps["input"] == ["text", "image"]
    assert "web" in caps["output"]
    assert caps["reasoning"]["effort"] == ["low"]


# --- чтение галочек из конфига --------------------------------------------


def test_capabilities_round_trip_through_config(manager):
    flags = {"tools": True, "vision": True, "web": True, "reasoning": True}
    config = manager.apply_profiles({}, [_profile(caps={"m1": flags})])
    loaded = manager.profiles_from_config(config)[0]

    assert loaded["model_capabilities"]["m1"]["vision"] is True
    assert loaded["model_capabilities"]["m1"]["web"] is True
    assert loaded["model_capabilities"]["m1"]["reasoning"] is True
    assert loaded["model_capabilities"]["m1"]["audio"] is False


def test_capabilities_survive_export_import(manager):
    flags = {"tools": True, "vision": True, "audio": True}
    profiles = [_profile(caps={"m1": flags})]
    payload = manager.build_export_payload(profiles)
    assert payload["profiles"][0]["model_capabilities"]["m1"]["vision"] is True

    restored, _ = manager.profiles_from_export(json.loads(json.dumps(payload)))
    assert restored[0]["model_capabilities"]["m1"]["vision"] is True

    config = manager.apply_profiles({}, restored)
    caps = config["providers"]["alpha"]["models"]["m1"]["capabilities"]
    assert caps["input"] == ["text", "image", "audio"]


def test_old_export_without_capabilities_still_imports(manager):
    payload = {"version": 2, "profiles": [{
        "id": "alpha", "base_url": "https://alpha.example/v1", "api_key": "k",
        "package": "@ai-sdk/openai-compatible", "models": ["a1"],
    }]}
    restored, _ = manager.profiles_from_export(payload)
    assert restored[0]["model_capabilities"] == {}
    config = manager.apply_profiles({}, restored)
    assert config["providers"]["alpha"]["models"]["a1"]["capabilities"]["output"] == ["text"]


# --- ключи: «API key is required» ------------------------------------------


def test_openai_compatible_keeps_key_in_settings(manager):
    config = manager.apply_profiles({}, [_profile()])
    proxy = config["providers"]["alpha"]
    assert proxy["settings"]["apiKey"] == "key-alpha"
    assert "env" not in proxy


def test_non_compatible_package_gets_env_key(manager):
    config = manager.apply_profiles({}, [_profile(package="@ai-sdk/openai")])
    proxy = config["providers"]["alpha"]
    assert proxy["env"] == ["OPENCODE_ALPHA_API_KEY"]
    assert proxy["settings"]["apiKey"] == "{env:OPENCODE_ALPHA_API_KEY}"


def test_migrate_provider_keys_fixes_openai_package(manager):
    config = {"providers": {"alpha": {
        "name": "Alpha",
        "package": "@ai-sdk/openai",
        "settings": {"baseURL": "https://api.aikeysforyou.com/v1",
                     "apiKey": "sk-cvc-abc"},
        "models": {"m1": {}},
    }}}
    fixed = manager.migrate_provider_keys(config)
    proxy = config["providers"]["alpha"]

    assert fixed == ["alpha"]
    assert proxy["package"] == "@opencode/ai/providers/openai-compatible"
    assert proxy["env"] == ["OPENCODE_ALPHA_API_KEY"]
    assert proxy["settings"]["apiKey"] == "{env:OPENCODE_ALPHA_API_KEY}"


def test_migrate_provider_keys_leaves_other_keys_alone(manager):
    config = {"providers": {
        "alpha": {"package": "@ai-sdk/openai",
                  "settings": {"apiKey": "sk-proj-xyz"}, "models": {}},
        "beta": {"package": "@ai-sdk/openai-compatible",
                 "settings": {"apiKey": "sk-cvc-1"}, "models": {}},
    }}
    assert manager.migrate_provider_keys(config) == []
    assert config["providers"]["alpha"]["package"] == "@ai-sdk/openai"
    assert config["providers"]["beta"]["settings"]["apiKey"] == "sk-cvc-1"


def test_default_package_is_current_opencode_runtime(manager):
    config = manager.apply_profiles({}, [{
        "id": "alpha", "display_name": "Alpha", "coefficient": "",
        "base_url": "https://alpha.example/v1", "api_key": "k",
        "package": "", "models": ["m1"], "known_models": ["m1"],
        "model_capabilities": {}, "extra_settings": {}, "_raw": {},
    }])
    proxy = config["providers"]["alpha"]
    assert proxy["package"] == "@opencode/ai/providers/openai-compatible"
    assert proxy["settings"]["apiKey"] == "k"
    assert "env" not in proxy


# --- перенос в агентов -----------------------------------------------------


def test_merge_into_agents_uses_capabilities(manager, tmp_path):
    profiles = [_profile(caps={"m1": {"tools": True, "vision": True}})]
    results = manager.transfer_profiles(profiles, "", ["cline", "continue"],
                                        home=tmp_path)
    assert [r["ok"] for r in results] == [True, True]

    models_path = tmp_path / ".cline" / "data" / "settings" / "models.json"
    doc = json.loads(models_path.read_text(encoding="utf-8"))
    assert doc["providers"]["alpha"]["models"]["m1"]["supportsVision"] is True

    yaml = pytest.importorskip("yaml")
    text = (tmp_path / ".continue" / "config.yaml").read_text(encoding="utf-8")
    entry = yaml.safe_load(text)["models"][0]
    assert "image_input" in entry["capabilities"]
