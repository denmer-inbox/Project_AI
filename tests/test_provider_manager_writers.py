"""Писатели конфигов агентов: формат, ключи, чистота и идемпотентность.

Здесь закреплены находки аудита: Cline игнорирует встроенные ID провайдеров
и требует UTC-время; Codex не умеет читать `env_key` без переменной
окружения; при переносе без ключа нельзя оставлять старые токены; повторная
синхронизация не должна переписывать файл.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("tkinter")
pytest.importorskip("yaml")

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


def _profile(pid="alpha", key="sk-alpha", base="https://api.alpha.example/v1",
             models=("m1",)):
    return {
        "id": pid,
        "display_name": pid.title(),
        "coefficient": "",
        "base_url": base,
        "package": "@ai-sdk/openai-compatible",
        "api_key": key,
        "models": list(models),
        "known_models": list(models),
        "model_capabilities": {},
        "extra_settings": {},
        "_raw": {"name": pid.title(), "models": {m: {} for m in models}},
    }


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- Cline ---------------------------------------------------------------

def test_cline_provider_id_is_not_builtin(manager):
    assert manager._cline_provider_id("deepseek") == "ocm-deepseek"
    assert manager._cline_provider_id("openai-compatible") == "ocm-openai-compatible"
    for raw in ("My Provider!", "alpha", "A_B.c", "  spaced  ", "провайдер"):
        pid = manager._cline_provider_id(raw)
        assert re.match(r"^[a-z0-9][a-z0-9-]*$", pid), pid
        assert pid.startswith("ocm-")
    # разные «грязные» имена не должны схлопываться в один ID
    assert manager._cline_provider_id("провайдер") != manager._cline_provider_id("провайдер2")
    assert manager._cline_provider_id("a b") == manager._cline_provider_id("a b")


def test_cline_writes_custom_provider_with_utc_time(manager, tmp_path):
    manager._transfer_cline([_profile(base="api.alpha.example/v1")],
                            "alpha/m1", home=tmp_path)
    path = tmp_path / ".cline" / "data" / "settings" / "providers.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    entry = doc["providers"]["ocm-alpha"]
    # settings.provider должен ссылаться на собственный ID, иначе Cline
    # молча игнорирует запись (встроенные ID отбрасываются)
    assert entry["settings"]["provider"] == "ocm-alpha"
    assert entry["settings"]["baseUrl"] == "https://api.alpha.example/v1"
    assert entry["updatedAt"].endswith("Z")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
                    entry["updatedAt"]), entry["updatedAt"]
    assert doc["lastUsedProvider"] == "ocm-alpha"


def test_cline_models_file_uses_same_id_and_metadata(manager, tmp_path):
    manager._transfer_cline([_profile(models=("m1", "m2"))], "alpha/m1",
                            home=tmp_path)
    path = tmp_path / ".cline" / "data" / "settings" / "models.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc["providers"]["ocm-alpha"]["models"]) == {"m1", "m2"}
    assert doc["providers"]["ocm-alpha"]["provider"] == {
        "name": "Alpha", "baseUrl": "https://api.alpha.example/v1"}


def test_cline_is_idempotent_and_keeps_updated_at(manager, tmp_path):
    manager._transfer_cline([_profile()], "alpha/m1", home=tmp_path)
    path = tmp_path / ".cline" / "data" / "settings" / "providers.json"
    first = path.read_text(encoding="utf-8")
    stamp = json.loads(first)["providers"]["ocm-alpha"]["updatedAt"]
    manager._transfer_cline([_profile()], "alpha/m1", home=tmp_path)
    second = path.read_text(encoding="utf-8")
    assert first == second
    assert json.loads(second)["providers"]["ocm-alpha"]["updatedAt"] == stamp


def test_cline_replaces_legacy_raw_id_entry(manager, tmp_path):
    path = tmp_path / ".cline" / "data" / "settings" / "providers.json"
    _write(path, json.dumps({
        "version": 1,
        "providers": {
            "alpha": {
                "settings": {"provider": "openai-compatible",
                             "model": "m1",
                             "baseUrl": "https://api.alpha.example/v1"},
                "updatedAt": "2026-01-01T00:00:00.000Z",
                "tokenSource": "manual",
            }
        },
        "modes": {},
    }))
    manager._transfer_cline([_profile()], "alpha/m1", home=tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert "alpha" not in doc["providers"]
    assert "ocm-alpha" in doc["providers"]


def test_cline_keeps_foreign_builtin_entry(manager, tmp_path):
    path = tmp_path / ".cline" / "data" / "settings" / "providers.json"
    _write(path, json.dumps({
        "version": 1,
        "providers": {"openrouter": {"settings": {"provider": "openrouter",
                                                  "apiKey": "sk-or-keep"}}},
        "modes": {},
    }))
    manager._transfer_cline([_profile()], "alpha/m1", home=tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["providers"]["openrouter"]["settings"]["apiKey"] == "sk-or-keep"


# --- Codex ---------------------------------------------------------------

def test_codex_writes_bearer_token_only(manager, tmp_path):
    manager._transfer_codex([_profile(base="api.alpha.example/v1")], "",
                            home=tmp_path)
    path = tmp_path / ".codex" / "config.toml"
    text = path.read_text(encoding="utf-8")
    parsed = tomllib.loads(text)
    provider = parsed["model_providers"]["alpha"]
    # env_key без переменной окружения даёт EnvVarError в отдельном процессе
    assert "env_key" not in provider
    assert provider["experimental_bearer_token"] == "sk-alpha"
    assert provider["base_url"] == "https://api.alpha.example/v1"
    assert parsed["model_provider"] == "alpha"


def test_codex_is_idempotent(manager, tmp_path):
    manager._transfer_codex([_profile()], "", home=tmp_path)
    path = tmp_path / ".codex" / "config.toml"
    first = path.read_text(encoding="utf-8")
    manager._transfer_codex([_profile()], "", home=tmp_path)
    assert path.read_text(encoding="utf-8") == first
    tomllib.loads(first)


def test_codex_replaces_existing_section_without_duplicates(manager, tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    _write(path, 'approval_policy = "on-request"\n\n'
                '[model_providers.alpha]\nname = "Old"\n'
                'env_key = "ALPHA_KEY"\nbase_url = "http://old"\n\n'
                '[mcp_servers.keepme]\ncommand = "echo"\n')
    manager._transfer_codex([_profile()], "", home=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.count("[model_providers.alpha]") == 1
    assert "ALPHA_KEY" not in text
    assert 'command = "echo"' in text
    parsed = tomllib.loads(text)
    assert parsed["approval_policy"] == "on-request"


def test_codex_keyless_has_no_auth_fields(manager, tmp_path):
    manager._transfer_codex([_profile(key="")], "", home=tmp_path)
    provider = tomllib.loads(
        (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    )["model_providers"]["alpha"]
    assert "env_key" not in provider
    assert "experimental_bearer_token" not in provider


# --- Claude --------------------------------------------------------------

def test_claude_keyless_removes_stale_tokens(manager, tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    _write(path, json.dumps({
        "env": {"ANTHROPIC_AUTH_TOKEN": "sk-old",
                "ANTHROPIC_API_KEY": "sk-old",
                "FOO": "bar"},
    }))
    manager._transfer_claude([_profile(key="")], "", home=tmp_path)
    env = json.loads(path.read_text(encoding="utf-8"))["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["FOO"] == "bar"
    assert env["ANTHROPIC_BASE_URL"] == "https://api.alpha.example/v1"


def test_claude_writes_real_key(manager, tmp_path):
    manager._transfer_claude([_profile()], "", home=tmp_path)
    env = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))["env"]
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-alpha"
    assert env["ANTHROPIC_API_KEY"] == "sk-alpha"


# --- Aider ---------------------------------------------------------------

def test_aider_keyless_removes_stale_key(manager, tmp_path):
    path = tmp_path / ".aider.conf.yml"
    _write(path, "openai-api-key: sk-old\nweak-model: openai/old\n")
    manager._transfer_aider([_profile(key="")], "", home=tmp_path)
    doc = manager._require_yaml(path.read_text(encoding="utf-8"), path)
    assert "openai-api-key" not in doc
    assert doc["weak-model"] == "openai/old"
    assert doc["openai-api-base"] == "https://api.alpha.example/v1"


# --- DeepSeek Harness ----------------------------------------------------

def test_dsh_writes_key_and_normalizes_url(manager, tmp_path):
    manager._transfer_dsh([_profile(base="api.alpha.example/v1")], "",
                          home=tmp_path)
    patch = tmp_path / ".dsh" / "profiles" / "desktop" / "cordis.patch.yml"
    creds = tmp_path / ".dsh" / ".credentials.yaml"
    doc = manager._require_yaml_any(patch.read_text(encoding="utf-8"), patch, [])
    block = next(e for e in doc if e.get("id") == "llm-pi-ai")
    entry = block["config"]["providers"]["alpha"]
    assert entry["baseURL"] == "https://api.alpha.example/v1"
    assert entry["apiKeyEnv"] == "DEEPSEEK_ALPHA_API_KEY"
    refs = manager._require_yaml_any(creds.read_text(encoding="utf-8"), creds, {})
    assert refs["refs"]["DEEPSEEK_ALPHA_API_KEY"] == "sk-alpha"


def test_dsh_keyless_drops_env_and_stale_ref(manager, tmp_path):
    patch = tmp_path / ".dsh" / "profiles" / "desktop" / "cordis.patch.yml"
    creds = tmp_path / ".dsh" / ".credentials.yaml"
    _write(patch, "- id: llm-pi-ai\n  name: '@deepseek-ai/dsh-llm-pi-ai'\n"
                  "  config:\n    providers:\n      alpha:\n"
                  "        displayName: Alpha\n        apiKeyEnv: DEEPSEEK_ALPHA_API_KEY\n"
                  "        api: openai-completions\n"
                  "        baseURL: https://api.alpha.example/v1\n        models: []\n")
    _write(creds, "refs:\n  DEEPSEEK_ALPHA_API_KEY: sk-old\n  OTHER: keep\n")
    manager._transfer_dsh([_profile(key="")], "", home=tmp_path)
    doc = manager._require_yaml_any(patch.read_text(encoding="utf-8"), patch, [])
    entry = next(e for e in doc if e.get("id") == "llm-pi-ai")[
        "config"]["providers"]["alpha"]
    assert "apiKeyEnv" not in entry
    refs = manager._require_yaml_any(creds.read_text(encoding="utf-8"), creds, {})
    assert "DEEPSEEK_ALPHA_API_KEY" not in refs["refs"]
    assert refs["refs"]["OTHER"] == "keep"


# --- VS Code -------------------------------------------------------------

def test_vscode_replaces_duplicate_key_and_keeps_comments(manager, tmp_path):
    path = tmp_path / "settings.json"
    _write(path,
           '// user comment\n{\n'
           '    "editor.fontSize": 14,\n'
           '    "opencodeLM.configPath": "C:\\\\old\\\\one.json",\n'
           '    "opencodeLM.configPath": "C:\\\\old\\\\two.json",\n'
           '    "workbench.colorTheme": "dark"\n}\n')
    manager._patch_vscode_settings(path, tmp_path / "opencode.json")
    text = path.read_text(encoding="utf-8")
    assert text.count("opencodeLM.configPath") == 1
    assert "// user comment" in text
    parsed = json.loads(manager.strip_jsonc(text))
    assert parsed["opencodeLM.configPath"].endswith("opencode.json")
    assert parsed["editor.fontSize"] == 14
    assert parsed["workbench.colorTheme"] == "dark"


def test_vscode_is_idempotent(manager, tmp_path):
    path = tmp_path / "settings.json"
    _write(path, '{\n    "editor.fontSize": 14\n}\n')
    manager._patch_vscode_settings(path, tmp_path / "opencode.json")
    first = path.read_text(encoding="utf-8")
    manager._patch_vscode_settings(path, tmp_path / "opencode.json")
    assert path.read_text(encoding="utf-8") == first


def test_vscode_removes_key_when_path_empty(manager, tmp_path):
    path = tmp_path / "settings.json"
    _write(path, '{\n    "opencodeLM.configPath": "old",\n'
                '    "editor.fontSize": 14\n}\n')
    manager._patch_vscode_settings(path, None)
    parsed = json.loads(manager.strip_jsonc(path.read_text(encoding="utf-8")))
    assert "opencodeLM.configPath" not in parsed
    assert parsed["editor.fontSize"] == 14


# --- Continue ------------------------------------------------------------

def test_continue_keeps_user_model_on_same_base(manager, tmp_path):
    path = tmp_path / ".continue" / "config.yaml"
    _write(path,
           "name: Local Config\nversion: 1.0.0\nschema: v1\nmodels:\n"
           "  - name: My own\n    provider: openai\n    model: user-model\n"
           "    apiBase: https://api.alpha.example/v1\n    apiKey: sk-user\n"
           "    roles:\n      - chat\n")
    manager._transfer_continue([_profile(base="api.alpha.example/v1")], "",
                               home=tmp_path)
    doc = manager._require_yaml(path.read_text(encoding="utf-8"), path)
    names = [m["name"] for m in doc["models"]]
    assert "My own" in names
    ours = [m for m in doc["models"] if m.get("model") == "m1"]
    assert ours and ours[0]["apiBase"] == "https://api.alpha.example/v1"
    assert ours[0]["apiKey"] == "sk-alpha"


def test_continue_is_idempotent(manager, tmp_path):
    manager._transfer_continue([_profile()], "", home=tmp_path)
    path = tmp_path / ".continue" / "config.yaml"
    first = path.read_text(encoding="utf-8")
    manager._transfer_continue([_profile()], "", home=tmp_path)
    assert path.read_text(encoding="utf-8") == first
