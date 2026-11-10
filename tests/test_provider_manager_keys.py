"""API-ключи: в файлы попадает только реальное значение, а не `{env:...}`.

Причина бага: менеджер писал в конфиг ссылку `{env:NAME}`, а значение держал
в `os.environ` своего процесса. OpenCode и другие агенты — отдельные процессы,
поэтому на другой машине (и после перезапуска) ключ оказывался пустым.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

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


def _profile(pid="alpha", key="key-alpha", package="@ai-sdk/openai-compatible"):
    return {
        "id": pid,
        "display_name": pid.title(),
        "coefficient": "",
        "base_url": "https://%s.example/v1" % pid,
        "package": package,
        "api_key": key,
        "models": ["m1"],
        "known_models": ["m1"],
        "model_capabilities": {},
        "extra_settings": {},
        "_raw": {"name": pid.title()},
    }


# --- чтение конфига -------------------------------------------------------


def test_profiles_from_config_resolves_placeholder_from_env(manager, monkeypatch):
    monkeypatch.setenv("TEST_KEY_ALPHA", "real-alpha")
    config = {"providers": {"alpha": {
        "package": "@ai-sdk/openai",
        "settings": {"apiKey": "{env:TEST_KEY_ALPHA}"},
        "models": {},
    }}}
    profile = manager.profiles_from_config(config)[0]
    assert profile["api_key"] == "real-alpha"
    assert profile["key_placeholder"] == "TEST_KEY_ALPHA"


def test_profiles_from_config_unresolved_placeholder_is_empty(manager, monkeypatch):
    monkeypatch.delenv("TEST_KEY_MISSING", raising=False)
    config = {"providers": {"alpha": {
        "package": "@ai-sdk/openai",
        "settings": {"apiKey": "{env:TEST_KEY_MISSING}"},
        "models": {},
    }}}
    profile = manager.profiles_from_config(config)[0]
    assert profile["api_key"] == ""
    assert profile["key_placeholder"] == "TEST_KEY_MISSING"


# --- запись opencode.json -------------------------------------------------


@pytest.mark.parametrize("package", [
    "@ai-sdk/openai", "@ai-sdk/anthropic", "@ai-sdk/google",
    "@ai-sdk/openai-compatible",
])
def test_build_provider_writes_real_key_for_every_package(manager, package):
    proxy = manager.build_provider(_profile(package=package))
    assert proxy["settings"]["apiKey"] == "key-alpha"
    assert "env" not in proxy


def test_build_provider_empty_key_writes_neither_key_nor_env(manager):
    proxy = manager.build_provider(_profile(key=""))
    assert "apiKey" not in (proxy.get("settings") or {})
    assert "env" not in proxy


def test_build_provider_without_api_key_field_does_not_crash(manager):
    profile = _profile()
    profile.pop("api_key")
    proxy = manager.build_provider(profile)
    assert "apiKey" not in (proxy.get("settings") or {})


def test_build_provider_drops_old_placeholder_and_env(manager):
    profile = _profile()
    profile["_raw"] = {
        "name": "Alpha",
        "package": "@ai-sdk/openai",
        "env": ["OPENCODE_ALPHA_API_KEY"],
        "settings": {"baseURL": "https://old.example/v1",
                     "apiKey": "{env:OPENCODE_ALPHA_API_KEY}"},
    }
    proxy = manager.build_provider(profile)
    assert proxy["settings"]["apiKey"] == "key-alpha"
    assert "env" not in proxy


def test_merge_replaces_placeholder_with_real_key(manager):
    config = {"providers": {"alpha": {
        "name": "Alpha",
        "package": "@ai-sdk/openai",
        "env": ["OPENCODE_ALPHA_API_KEY"],
        "settings": {"baseURL": "https://old.example/v1",
                     "apiKey": "{env:OPENCODE_ALPHA_API_KEY}"},
        "models": {"old": {}},
    }}}
    merged = manager.merge_profiles_into_config(config, [_profile()])
    proxy = merged["providers"]["alpha"]
    assert proxy["settings"]["apiKey"] == "key-alpha"
    assert "env" not in proxy
    assert "old" in proxy["models"]


def test_merge_keyless_profile_removes_stale_placeholder(manager):
    config = {"providers": {"alpha": {
        "package": "@ai-sdk/openai",
        "env": ["OPENCODE_ALPHA_API_KEY"],
        "settings": {"apiKey": "{env:OPENCODE_ALPHA_API_KEY}"},
        "models": {},
    }}}
    merged = manager.merge_profiles_into_config(config, [_profile(key="")])
    proxy = merged["providers"]["alpha"]
    assert "apiKey" not in (proxy.get("settings") or {})
    assert "env" not in proxy


# --- миграция старых конфигов --------------------------------------------


def test_migrate_resolves_placeholder_when_env_is_set(manager, monkeypatch):
    monkeypatch.setenv("TEST_KEY_MIGR", "real-migr")
    config = {"providers": {"alpha": {
        "package": "@ai-sdk/openai",
        "env": ["OPENCODE_ALPHA_API_KEY"],
        "settings": {"apiKey": "{env:TEST_KEY_MIGR}"},
        "models": {},
    }}}
    assert manager.migrate_provider_keys(config) == ["alpha"]
    proxy = config["providers"]["alpha"]
    assert proxy["settings"]["apiKey"] == "real-migr"
    assert "env" not in proxy


def test_migrate_drops_unresolved_placeholder(manager, monkeypatch):
    monkeypatch.delenv("TEST_KEY_GONE", raising=False)
    config = {"providers": {"alpha": {
        "package": "@ai-sdk/openai",
        "env": ["OPENCODE_ALPHA_API_KEY"],
        "settings": {"apiKey": "{env:TEST_KEY_GONE}"},
        "models": {},
    }}}
    assert manager.migrate_provider_keys(config) == ["alpha"]
    proxy = config["providers"]["alpha"]
    assert "apiKey" not in (proxy.get("settings") or {})
    assert "env" not in proxy


# --- экспорт/импорт -------------------------------------------------------


def test_export_never_contains_placeholder(manager, monkeypatch):
    monkeypatch.delenv("TEST_KEY_EXPORT", raising=False)
    config = {"providers": {"alpha": {
        "package": "@ai-sdk/openai",
        "env": ["OPENCODE_ALPHA_API_KEY"],
        "settings": {"apiKey": "{env:TEST_KEY_EXPORT}"},
        "models": {"m1": {}},
    }}}
    profiles = manager.profiles_from_config(config)
    payload = manager.build_export_payload(profiles)
    text = json.dumps(payload)
    assert "{env:" not in text
    assert payload["profiles"][0]["api_key"] == ""
    assert payload["profiles"][0]["key_placeholder"] == "TEST_KEY_EXPORT"


def test_export_resolved_key_and_import_round_trip(manager, monkeypatch):
    monkeypatch.setenv("TEST_KEY_RT", "real-rt")
    config = {"providers": {"alpha": {
        "package": "@ai-sdk/openai",
        "settings": {"apiKey": "{env:TEST_KEY_RT}"},
        "models": {"m1": {}},
    }}}
    payload = manager.build_export_payload(manager.profiles_from_config(config))
    assert payload["profiles"][0]["api_key"] == "real-rt"
    restored, _ = manager.profiles_from_export(json.loads(json.dumps(payload)))
    assert restored[0]["api_key"] == "real-rt"
    proxy = manager.apply_profiles({}, restored)["providers"]["alpha"]
    assert proxy["settings"]["apiKey"] == "real-rt"


def test_old_export_recovers_key_from_raw_settings(manager):
    payload = {"version": 2, "profiles": [{
        "id": "alpha", "base_url": "https://alpha.example/v1",
        "package": "@ai-sdk/openai", "models": ["m1"],
        "raw": {"settings": {"apiKey": "old-real-key"}},
    }]}
    restored, _ = manager.profiles_from_export(payload)
    assert restored[0]["api_key"] == "old-real-key"
    proxy = manager.build_provider(restored[0])
    assert proxy["settings"]["apiKey"] == "old-real-key"


# --- писатели конфигов агентов -------------------------------------------


def _transfer(manager, tmp_path, profile, agents):
    return manager.transfer_profiles([profile], "", agents, home=tmp_path)


def test_writers_never_write_placeholder(manager, tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_KEY_PLACEHOLDER", raising=False)
    profile = _profile(key="{env:TEST_KEY_PLACEHOLDER}")
    results = _transfer(
        manager, tmp_path, profile,
        ["cline", "continue", "codex", "claude", "aider", "dsh"])
    assert all(r["ok"] for r in results), results

    cline = json.loads((tmp_path / ".cline/data/settings/providers.json")
                       .read_text(encoding="utf-8"))
    assert "apiKey" not in cline["providers"]["ocm-alpha"]["settings"]

    continue_text = (tmp_path / ".continue/config.yaml").read_text(encoding="utf-8")
    assert "{env:" not in continue_text
    assert "apiKey" not in continue_text

    codex_text = (tmp_path / ".codex/config.toml").read_text(encoding="utf-8")
    assert "{env:" not in codex_text
    assert "experimental_bearer_token" not in codex_text

    claude = json.loads((tmp_path / ".claude/settings.json")
                        .read_text(encoding="utf-8"))
    assert "ANTHROPIC_AUTH_TOKEN" not in claude["env"]

    aider_text = (tmp_path / ".aider.conf.yml").read_text(encoding="utf-8")
    assert "{env:" not in aider_text
    assert "openai-api-key" not in aider_text

    cred = tmp_path / ".dsh/.credentials.yaml"
    assert not cred.exists() or "{env:" not in cred.read_text(encoding="utf-8")


def test_writers_write_real_key(manager, tmp_path):
    profile = _profile(key='abc"de\\fg')
    results = _transfer(
        manager, tmp_path, profile,
        ["cline", "continue", "codex", "claude", "aider", "dsh"])
    assert all(r["ok"] for r in results), results

    cline = json.loads((tmp_path / ".cline/data/settings/providers.json")
                       .read_text(encoding="utf-8"))
    assert cline["providers"]["ocm-alpha"]["settings"]["apiKey"] == 'abc"de\\fg'

    continue_text = (tmp_path / ".continue/config.yaml").read_text(encoding="utf-8")
    assert 'abc"de\\fg' in continue_text

    codex_text = (tmp_path / ".codex/config.toml").read_text(encoding="utf-8")
    assert 'abc\\"de\\\\fg' in codex_text

    claude = json.loads((tmp_path / ".claude/settings.json")
                        .read_text(encoding="utf-8"))
    assert claude["env"]["ANTHROPIC_AUTH_TOKEN"] == 'abc"de\\fg'

    aider_text = (tmp_path / ".aider.conf.yml").read_text(encoding="utf-8")
    assert 'abc"de\\fg' in aider_text

    cred_text = (tmp_path / ".dsh/.credentials.yaml").read_text(encoding="utf-8")
    assert 'abc"de\\fg' in cred_text


# --- MCP-секреты ----------------------------------------------------------


def test_mcp_secret_is_stored_as_real_value(manager):
    entry = manager.mcp_server_entry(
        manager.mcp_catalog_entry("github"), {"GITHUB_PAT": "ghp_real"})
    assert entry["headers"]["Authorization"] == "Bearer ghp_real"
    assert "{env:" not in json.dumps(entry)


def test_apply_mcp_does_not_create_empty_env(manager, monkeypatch):
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    entry = manager.mcp_server_entry(
        manager.mcp_catalog_entry("github"), {"GITHUB_PAT": "ghp_real"})
    manager.apply_mcp_servers({}, {"github": entry})
    import os
    assert "GITHUB_PAT" not in os.environ


# --- сохранение чужих провайдеров ----------------------------------------


def test_apply_profiles_keeps_ids_added_after_load(manager):
    config = {"providers": {
        "alpha": {"name": "Alpha", "models": {}},
        "foreign": {"name": "Foreign", "models": {}},
    }}
    applied = manager.apply_profiles(config, [_profile()], keep_ids={"foreign"})
    assert set(applied["providers"]) == {"alpha", "foreign"}


def test_apply_profiles_still_deletes_loaded_provider(manager):
    config = {"providers": {"alpha": {"name": "Alpha", "models": {}}}}
    assert manager.apply_profiles(config, [], keep_ids=set())["providers"] == {}
