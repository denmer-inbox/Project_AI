"""Перенос профилей менеджера OpenCode в конфиги ИИ-агентов."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "opencode_provider_manager.py"


@pytest.fixture(scope="module")
def manager():
    spec = importlib.util.spec_from_file_location("opencode_provider_manager", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile(pid, models, base_url=None, key=None, package=None):
    return {
        "id": pid,
        "display_name": pid.title(),
        "coefficient": "",
        "base_url": base_url or "https://%s.example/v1" % pid,
        "package": package or "@ai-sdk/openai-compatible",
        "api_key": key if key is not None else "key-" + pid,
        "models": list(models),
        "known_models": list(models),
        "extra_settings": {},
        "_raw": {"name": pid.title()},
    }


def test_catalog_lists_all_supported_agents(manager, tmp_path):
    catalog = manager.agent_catalog(home=tmp_path)
    ids = [item["id"] for item in catalog]

    assert ids == ["opencode", "vscode", "cline", "continue", "codex", "claude",
                   "aider", "dsh"]
    for item in catalog:
        assert item["path"]
        assert item["description"]
        assert item["exists"] is False
    assert catalog[0]["path"] == tmp_path / ".config" / "opencode" / "opencode.json"


def test_catalog_marks_existing_files(manager, tmp_path):
    target = tmp_path / ".continue" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("name: test\n", encoding="utf-8")

    catalog = {item["id"]: item for item in manager.agent_catalog(home=tmp_path)}

    assert catalog["continue"]["exists"] is True
    assert catalog["codex"]["exists"] is False


def test_transfer_to_cline_writes_provider_and_models(manager, tmp_path):
    providers = tmp_path / ".cline" / "data" / "settings" / "providers.json"
    providers.parent.mkdir(parents=True)
    providers.write_text(json.dumps({
        "version": 1,
        "lastUsedProvider": "cline",
        "modes": {},
        "providers": {
            "cline": {"settings": {"provider": "cline", "model": "x"}, "tokenSource": "migration"},
        },
    }), encoding="utf-8")

    results = manager.transfer_profiles(
        [_profile("alpha", ["a1", "a2"]), _profile("beta", ["b1"])], "beta/b1",
        ["cline"], home=tmp_path)

    assert [r["ok"] for r in results] == [True]
    doc = json.loads(providers.read_text(encoding="utf-8"))
    assert doc["lastUsedProvider"] == "ocm-beta"
    assert "cline" in doc["providers"]
    alpha = doc["providers"]["ocm-alpha"]["settings"]
    assert alpha["provider"] == "ocm-alpha"
    assert alpha["baseUrl"] == "https://alpha.example/v1"
    assert alpha["apiKey"] == "key-alpha"
    assert alpha["model"] == "a1"

    models = json.loads(
        (providers.parent / "models.json").read_text(encoding="utf-8"))
    assert set(models["providers"]["ocm-alpha"]["models"]) == {"a1", "a2"}
    assert models["providers"]["ocm-alpha"]["models"]["a1"]["supportsVision"] is False


def test_transfer_to_cline_keeps_other_providers(manager, tmp_path):
    providers = tmp_path / ".cline" / "data" / "settings" / "providers.json"
    providers.parent.mkdir(parents=True)
    providers.write_text(json.dumps({
        "version": 1,
        "providers": {"openrouter": {"settings": {"provider": "openrouter"}}},
    }), encoding="utf-8")

    manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["cline"], home=tmp_path)

    doc = json.loads(providers.read_text(encoding="utf-8"))
    assert doc["providers"]["openrouter"]["settings"]["provider"] == "openrouter"
    assert "ocm-alpha" in doc["providers"]


def test_catalog_points_cline_at_providers_json(manager, tmp_path):
    catalog = {item["id"]: item for item in manager.agent_catalog(home=tmp_path)}
    assert catalog["cline"]["path"] == (
        tmp_path / ".cline" / "data" / "settings" / "providers.json")


def test_transfer_to_continue_writes_models(manager, tmp_path):
    profiles = [_profile("alpha", ["a1", "a2"]), _profile("beta", ["b1"])]

    results = manager.transfer_profiles(profiles, "alpha/a1", ["continue"], home=tmp_path)

    assert [r["ok"] for r in results] == [True]
    path = tmp_path / ".continue" / "config.yaml"
    text = path.read_text(encoding="utf-8")
    assert "a1" in text and "b1" in text
    assert "https://alpha.example/v1" in text
    assert "name: Local Config" in text

    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(text)
    assert doc["schema"] == "v1"
    assert len(doc["models"]) == 3
    assert doc["models"][0]["apiBase"] == "https://alpha.example/v1"
    assert doc["models"][0]["roles"] == ["chat", "edit", "apply"]


def test_transfer_to_continue_replaces_its_own_entries(manager, tmp_path):
    path = tmp_path / ".continue" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "name: Local\nschema: v1\nmodels:\n"
        "  - name: Alpha old\n    provider: openai\n    model: a1\n"
        "    apiBase: https://alpha.example/v1\n    apiKey: sk-stale\n"
        "  - name: Manual\n    provider: openai\n    model: keep-me\n"
        "    apiBase: https://alpha.example/v1\n", encoding="utf-8")
    yaml = pytest.importorskip("yaml")

    manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["continue"], home=tmp_path)

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    names = [m["name"] for m in doc["models"]]
    # запись, которую писал менеджер (та же тройка провайдер/URL/модель),
    # обновляется, а пользовательская модель на том же URL остаётся
    assert "Manual" in names
    assert not any("Alpha old" == n for n in names)
    assert "Alpha · a1" in names
    assert [m["apiKey"] for m in doc["models"] if m.get("model") == "a1"] == ["key-alpha"]
    assert len([m for m in doc["models"] if m.get("model") == "a1"]) == 1


def test_transfer_to_codex_preserves_other_tables(manager, tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        'notify = ["cmd", "turn-ended"]\n\n'
        '[mcp_servers.node_repl]\ncommand = "node"\nargs = []\n\n'
        '[model_providers.alpha]\nname = "stale"\nbase_url = "https://old.example"\n',
        encoding="utf-8")

    results = manager.transfer_profiles(
        [_profile("alpha", ["a1"]), _profile("beta", ["b1"])], "beta/b1",
        ["codex"], home=tmp_path)

    assert [r["ok"] for r in results] == [True]
    text = path.read_text(encoding="utf-8")
    assert "[mcp_servers.node_repl]" in text
    assert 'notify = ["cmd", "turn-ended"]' in text
    assert 'model_provider = "beta"' in text
    assert 'model = "b1"' in text
    assert "https://old.example" not in text
    assert '[model_providers.alpha]' in text
    assert '[model_providers.beta]' in text
    assert text.count("[model_providers.alpha]") == 1
    assert 'wire_api = "chat"' in text
    # ключ передаётся bearer-токеном: env_key без переменной окружения
    # роняет Codex с EnvVarError
    assert 'experimental_bearer_token = "key-alpha"' in text
    assert "env_key" not in text


def test_transfer_to_claude_sets_env(manager, tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}), encoding="utf-8")

    manager.transfer_profiles([_profile("alpha", ["a1"])], "alpha/a1", ["claude"],
                              home=tmp_path)

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["permissions"] == {"allow": ["Bash"]}
    assert doc["env"]["ANTHROPIC_BASE_URL"] == "https://alpha.example/v1"
    assert doc["env"]["ANTHROPIC_AUTH_TOKEN"] == "key-alpha"
    assert doc["env"]["ANTHROPIC_MODEL"] == "a1"


def test_transfer_to_aider_sets_openai_keys(manager, tmp_path):
    path = tmp_path / ".aider.conf.yml"
    path.write_text("auto-commits: false\n", encoding="utf-8")
    yaml = pytest.importorskip("yaml")

    manager.transfer_profiles([_profile("alpha", ["a1"])], "alpha/a1", ["aider"],
                              home=tmp_path)

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["auto-commits"] is False
    assert doc["openai-api-base"] == "https://alpha.example/v1"
    assert doc["openai-api-key"] == "key-alpha"
    assert doc["model"] == "openai/a1"


def _fake_vsix(manager, home, version="1.0.0"):
    """Собирает минимальный .vsix рядом с «исходниками» расширения."""
    import zipfile
    src = home / "opencode-lm-vscode"
    src.mkdir(parents=True, exist_ok=True)
    vsix = src / ("opencode-lm-%s.vsix" % version)
    with zipfile.ZipFile(vsix, "w") as zf:
        zf.writestr("extension.vsixmanifest",
                    '<?xml version="1.0"?><PackageManifest/>')
        zf.writestr("extension/package.json", json.dumps({
            "name": "opencode-lm", "version": version, "main": "./extension.js",
        }))
        zf.writestr("extension/extension.js", "module.exports = {};\n")
        zf.writestr("extension/readme.md", "readme\n")
    return vsix


def test_transfer_to_vscode_installs_extension_and_points_config(manager, tmp_path):
    _fake_vsix(manager, tmp_path)
    settings = tmp_path / "AppData" / "Roaming" / "Code" / "User" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"editor.fontSize": 14}), encoding="utf-8")
    config = tmp_path / "opencode.json"
    config.write_text("{}", encoding="utf-8")

    results = manager.transfer_profiles([_profile("alpha", ["a1"])], "",
                                        ["vscode"], home=tmp_path,
                                        config_path=config)

    assert [r["ok"] for r in results] == [True]
    installed = tmp_path / ".vscode" / "extensions" / "local.opencode-lm-1.0.0"
    assert (installed / "package.json").is_file()
    assert (installed / "extension.js").is_file()
    # VS Code видит расширение только при скрытом .vsixmanifest
    assert (installed / ".vsixmanifest").is_file()
    entries = json.loads(
        (tmp_path / ".vscode" / "extensions" / "extensions.json").read_text(encoding="utf-8"))
    assert [e["identifier"]["id"] for e in entries] == ["local.opencode-lm"]
    assert entries[0]["relativeLocation"] == "local.opencode-lm-1.0.0"
    assert "\\" not in entries[0]["location"]["path"]

    doc = json.loads(settings.read_text(encoding="utf-8"))
    assert doc["editor.fontSize"] == 14
    assert doc["opencodeLM.configPath"] == str(config)


def test_transfer_to_vscode_is_idempotent(manager, tmp_path):
    _fake_vsix(manager, tmp_path)
    config = tmp_path / "opencode.json"
    config.write_text("{}", encoding="utf-8")

    first = manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["vscode"],
                                      home=tmp_path, config_path=config)
    second = manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["vscode"],
                                       home=tmp_path, config_path=config)

    assert [r["ok"] for r in (first + second)] == [True, True]
    assert "уже установлено" in second[0]["message"]
    entries = json.loads(
        (tmp_path / ".vscode" / "extensions" / "extensions.json").read_text(encoding="utf-8"))
    assert len(entries) == 1


def test_transfer_to_vscode_without_vsix_explains_where_to_put_it(manager, tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text("{}", encoding="utf-8")

    results = manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["vscode"],
                                        home=tmp_path, config_path=config)

    assert [r["ok"] for r in results] == [True]
    assert ".vsix" in results[0]["message"]
    assert str(tmp_path / "opencode-lm-vscode") in results[0]["message"]


def test_vscode_extension_install_uses_task_paths(manager, tmp_path):
    """Установка расширения не должна зависеть от TRANSFER_PROMPT.md."""
    _fake_vsix(manager, tmp_path)
    config = tmp_path / "opencode.json"
    config.write_text("{}", encoding="utf-8")

    results = manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["vscode"],
                                        home=tmp_path, config_path=config)

    assert [r["ok"] for r in results] == [True]
    assert "TRANSFER" not in results[0]["message"]


def test_transfer_to_vscode_keeps_settings_with_comments(manager, tmp_path):
    _fake_vsix(manager, tmp_path)
    settings = tmp_path / "AppData" / "Roaming" / "Code" / "User" / "settings.json"
    settings.parent.mkdir(parents=True)
    original = '{\n  // мой комментарий\n  "editor.fontSize": 14\n}\n'
    settings.write_text(original, encoding="utf-8")

    results = manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["vscode"],
                                        home=tmp_path)

    assert [r["ok"] for r in results] == [True]
    assert "комментарии сохранены" in results[0]["message"]
    text = settings.read_text(encoding="utf-8")
    assert "// мой комментарий" in text
    assert '"editor.fontSize": 14' in text
    patched = json.loads(manager.strip_jsonc(text))
    assert patched["editor.fontSize"] == 14
    assert patched["opencodeLM.configPath"].endswith("opencode.json")


def test_transfer_to_opencode_writes_providers(manager, tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({"$schema": "https://opencode.ai/config.json"}),
                      encoding="utf-8")

    results = manager.transfer_profiles(
        [_profile("alpha", ["a1"])], "alpha/a1", ["opencode"], config_path=config)

    assert [r["ok"] for r in results] == [True]
    doc = json.loads(config.read_text(encoding="utf-8"))
    assert doc["$schema"] == "https://opencode.ai/config.json"
    assert doc["providers"]["alpha"]["settings"]["apiKey"] == "key-alpha"
    assert doc["model"] == "alpha/a1"
    assert results[0]["path"] == config


def test_transfer_to_opencode_keeps_other_providers_and_models(manager, tmp_path):
    """Перенос поднабора профилей не должен трогать остальное.

    Регрессия: раньше apply_profiles заменял providers целиком, из-за чего
    из рабочего конфига пропадали провайдеры, а модели помечались disabled.
    """
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "model": "big/m1",
        "agent": {"plan": {"description": "Read-only planning agent."}},
        "skills": ["skills"],
        "mcp": {"rea": {"type": "local", "command": ["cmd"], "enabled": True}},
        "providers": {
            "big": {
                "name": "Big",
                "package": manager.PACKAGES[0],
                "settings": {"baseURL": "https://big.example/v1", "apiKey": "k1"},
                "models": {"m1": {"name": "m1"}, "m2": {"name": "m2"},
                           "m3": {"name": "m3"}},
            },
            "other": {
                "name": "Other",
                "package": manager.PACKAGES[0],
                "settings": {"baseURL": "https://other.example/v1", "apiKey": "k2"},
                "models": {"o1": {"name": "o1"}},
            },
        },
    }, indent=2), encoding="utf-8")

    manager.transfer_profiles(
        [_profile("big", ["m1"], base_url="https://big.example/v1",
                  key="k1")], "", ["opencode"], config_path=config)

    doc = json.loads(config.read_text(encoding="utf-8"))
    assert doc["$schema"] == "https://opencode.ai/config.json"
    assert doc["agent"] == {"plan": {"description": "Read-only planning agent."}}
    assert doc["skills"] == ["skills"]
    assert doc["mcp"]["rea"]["enabled"] is True
    assert doc["model"] == "big/m1"
    assert sorted(doc["providers"]) == ["big", "other"]
    assert sorted(doc["providers"]["big"]["models"]) == ["m1", "m2", "m3"]
    assert doc["providers"]["other"]["models"] == {"o1": {"name": "o1"}}
    hidden = [mid for mid, spec in doc["providers"]["big"]["models"].items()
              if isinstance(spec, dict) and spec.get("disabled")]
    assert hidden == []


def test_transfer_without_profiles_reports_error(manager, tmp_path):
    results = manager.transfer_profiles([], "", ["continue"], home=tmp_path)

    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "профил" in results[0]["message"]


def test_transfer_reports_writer_errors_without_raising(manager, tmp_path):
    broken = tmp_path / ".claude" / "settings.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{ это не json", encoding="utf-8")

    results = manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["claude"],
                                        home=tmp_path)

    assert [r["ok"] for r in results] == [False]
    assert "json" in results[0]["message"].lower()


def test_transfer_order_follows_agent_ids(manager, tmp_path):
    results = manager.transfer_profiles(
        [_profile("alpha", ["a1"])], "", ["aider", "continue", "codex"],
        home=tmp_path)

    assert [r["agent"] for r in results] == ["continue", "codex", "aider"]


def test_agents_settings_round_trip(manager, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    manager.save_agents_settings({
        "agents": ["vscode", "continue"],
        "profiles": ["alpha"],
    })

    restored = manager.load_agents_settings()

    assert restored["agents"] == ["vscode", "continue"]
    assert restored["profiles"] == ["alpha"]


def test_backup_created_before_overwriting(manager, tmp_path):
    path = tmp_path / ".aider.conf.yml"
    path.write_text("auto-commits: true\n", encoding="utf-8")

    manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["aider"], home=tmp_path)

    backups = list(tmp_path.glob(".aider.conf.yml.bak-*"))
    assert len(backups) == 1
    assert "auto-commits: true" in backups[0].read_text(encoding="utf-8")


# --- диалог переноса ------------------------------------------------------

@pytest.fixture()
def tk_root():
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - нет дисплея/Tcl
        pytest.skip("Tk недоступен: %s" % exc)
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass


class _FakeApp:
    def __init__(self, root, profiles, tmp_path):
        self.root = root
        self.profiles = profiles
        self.config_path = tmp_path / "opencode.json"
        self.var_default_model = tk.StringVar(master=root, value="alpha/a1")
        self.status = []
        self.clipboard = type("Clip", (), {"bind_tree": lambda *a, **k: None})()

    def _set_status(self, text):
        self.status.append(text)


def test_agents_dialog_lists_every_agent_with_checkbox(manager, tk_root, tmp_path,
                                                       monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = _FakeApp(tk_root, [_profile("alpha", ["a1"])], tmp_path)

    dlg = manager.AgentsDialog(app, home=tmp_path)
    tk_root.update()

    for agent in manager.AGENT_IDS:
        assert agent in dlg.agent_vars
        assert dlg.agent_vars[agent].get() is False
    assert dlg.profile_vars["alpha"].get() is True

    dlg._set_agents(True)
    assert all(v.get() for v in dlg.agent_vars.values())
    dlg.destroy()


def test_agents_dialog_selection_is_saved_and_reused(manager, tk_root, tmp_path,
                                                     monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = _FakeApp(tk_root, [_profile("alpha", ["a1"])], tmp_path)

    dlg = manager.AgentsDialog(app, home=tmp_path)
    tk_root.update()
    dlg.agent_vars["continue"].set(True)
    dlg.agent_vars["vscode"].set(True)
    dlg.profile_vars["alpha"].set(True)
    dlg._import(dry_run=True)

    saved = manager.load_agents_settings()
    assert saved["agents"] == ["vscode", "continue"]
    assert saved["profiles"] == ["alpha"]

    second = manager.AgentsDialog(app, home=tmp_path)
    tk_root.update()
    assert second.agent_vars["continue"].get() is True
    assert second.agent_vars["vscode"].get() is True
    assert second.agent_vars["codex"].get() is False
    second.destroy()
    dlg.destroy()


def test_agents_dialog_dry_run_writes_nothing(manager, tk_root, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = _FakeApp(tk_root, [_profile("alpha", ["a1"])], tmp_path)
    dlg = manager.AgentsDialog(app, home=tmp_path)
    tk_root.update()
    dlg._set_agents(True)

    dlg._import(dry_run=True)

    report = dlg.txt_report.get("1.0", "end")
    assert "файлы не изменяются" in report
    # у VS Code в пустом домашнем каталоге нет .vsix — отчёт обязан это показать
    assert "OK" in report
    assert "ВНИМАНИЕ" in report
    assert "Требуют внимания" in report
    assert not (tmp_path / ".continue" / "config.yaml").exists()
    assert not (tmp_path / ".aider.conf.yml").exists()
    dlg.destroy()


def test_agents_dialog_import_writes_files(manager, tk_root, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = _FakeApp(tk_root, [_profile("alpha", ["a1"])], tmp_path)
    dlg = manager.AgentsDialog(app, home=tmp_path)
    tk_root.update()
    dlg.agent_vars["aider"].set(True)
    dlg.profile_vars["alpha"].set(True)

    dlg._import()

    report = dlg.txt_report.get("1.0", "end")
    assert "OK Aider" in report
    assert app.status and "ПЕРЕНОС В АГЕНТОВ" in app.status[-1]
    assert (tmp_path / ".aider.conf.yml").is_file()
    dlg.destroy()


def test_agents_dialog_requires_selection(manager, tk_root, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = _FakeApp(tk_root, [_profile("alpha", ["a1"])], tmp_path)
    dlg = manager.AgentsDialog(app, home=tmp_path)
    tk_root.update()

    shown = []
    monkeypatch.setattr(manager.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a[1] if len(a) > 1 else ""))

    dlg._set_agents(False)
    dlg._import()

    assert shown and "агента" in shown[0]
    dlg.destroy()


# --- DeepSeek Harness -----------------------------------------------------

def test_transfer_to_dsh_writes_providers_and_keys(manager, tmp_path):
    results = manager.transfer_profiles(
        [_profile("alpha", ["a1", "a2"], key="sk-test-1")], "", ["dsh"],
        home=tmp_path)

    assert [r["ok"] for r in results] == [True]
    patch = tmp_path / ".dsh" / "profiles" / "desktop" / "cordis.patch.yml"
    assert patch.is_file()

    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(patch.read_text(encoding="utf-8"))
    assert isinstance(doc, list)
    block = next(e for e in doc if e.get("id") == "llm-pi-ai")
    providers = block["config"]["providers"]
    assert "alpha" in providers
    entry = providers["alpha"]
    assert entry["api"] == "openai-completions"
    assert entry["baseURL"] == "https://alpha.example/v1"
    assert entry["apiKeyEnv"] == "DEEPSEEK_ALPHA_API_KEY"
    assert [m["id"] for m in entry["models"]] == ["a1", "a2"]

    creds = yaml.safe_load(
        (tmp_path / ".dsh" / ".credentials.yaml").read_text(encoding="utf-8"))
    assert creds["refs"]["DEEPSEEK_ALPHA_API_KEY"] == "sk-test-1"


def test_transfer_to_dsh_keeps_existing_patches_and_providers(manager, tmp_path):
    patch = tmp_path / ".dsh" / "profiles" / "desktop" / "cordis.patch.yml"
    patch.parent.mkdir(parents=True)
    patch.write_text(
        "- id: ui-theme\n"
        "  name: \"@deepseek-ai/dsh-client-ui-theme\"\n"
        "  config:\n"
        "    preference: dark\n"
        "- id: llm-pi-ai\n"
        "  name: \"@deepseek-ai/dsh-llm-pi-ai\"\n"
        "  config:\n"
        "    providers:\n"
        "      keeper:\n"
        "        displayName: Keeper\n"
        "        apiKeyEnv: KEEPER_KEY\n"
        "        api: openai-completions\n"
        "        baseURL: https://keeper.example/v1\n"
        "        models:\n"
        "          - id: k1\n",
        encoding="utf-8")

    manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["dsh"],
                              home=tmp_path)

    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(patch.read_text(encoding="utf-8"))
    assert [e["id"] for e in doc] == ["ui-theme", "llm-pi-ai"]
    providers = doc[1]["config"]["providers"]
    assert sorted(providers) == ["alpha", "keeper"]
    assert providers["keeper"]["displayName"] == "Keeper"


def test_transfer_to_dsh_keeps_other_credentials(manager, tmp_path):
    cred = tmp_path / ".dsh" / ".credentials.yaml"
    cred.parent.mkdir(parents=True)
    cred.write_text(
        "version: 1\n"
        "refs:\n"
        "  EXISTING_KEY: keep-me\n",
        encoding="utf-8")

    manager.transfer_profiles([_profile("alpha", ["a1"], key="new-key")], "",
                              ["dsh"], home=tmp_path)

    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(cred.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    assert doc["refs"]["EXISTING_KEY"] == "keep-me"
    assert doc["refs"]["DEEPSEEK_ALPHA_API_KEY"] == "new-key"


def test_transfer_to_dsh_is_idempotent(manager, tmp_path):
    first = manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["dsh"],
                                      home=tmp_path)
    second = manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["dsh"],
                                       home=tmp_path)

    assert [r["ok"] for r in (first + second)] == [True, True]
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(
        (tmp_path / ".dsh" / "profiles" / "desktop" / "cordis.patch.yml")
        .read_text(encoding="utf-8"))
    blocks = [e for e in doc if e.get("id") == "llm-pi-ai"]
    assert len(blocks) == 1
    assert len(blocks[0]["config"]["providers"]) == 1


def test_transfer_to_dsh_backup_created(manager, tmp_path):
    patch = tmp_path / ".dsh" / "profiles" / "desktop" / "cordis.patch.yml"
    patch.parent.mkdir(parents=True)
    patch.write_text("- id: ui-theme\n  config:\n    preference: dark\n",
                     encoding="utf-8")

    manager.transfer_profiles([_profile("alpha", ["a1"])], "", ["dsh"],
                              home=tmp_path)

    backups = list(patch.parent.glob("cordis.patch.yml.bak-*"))
    assert len(backups) == 1


# --- предпросмотр (сухой прогон) ------------------------------------------

def test_transfer_plan_counts_models(manager, tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({
        "providers": {
            "big": {"name": "Big", "package": manager.PACKAGES[0],
                    "settings": {"baseURL": "https://big.example/v1"},
                    "models": {"m1": {"name": "m1"}, "m2": {"name": "m2"}}},
        }
    }), encoding="utf-8")

    plan = manager.transfer_plan(
        [_profile("alpha", ["a1", "a2"])], "", ["opencode"],
        home=tmp_path, config_path=str(config))

    assert len(plan) == 1
    assert plan[0]["ok"] is True
    message = plan[0]["message"]
    assert "провайдеров 1 → 2" in message
    assert "моделей 2 → 4" in message
    assert "новые: alpha" in message


def test_transfer_plan_writes_nothing(manager, tmp_path):
    config = tmp_path / "opencode.json"
    config.write_text(json.dumps({"providers": {}}), encoding="utf-8")
    before = config.read_text(encoding="utf-8")

    manager.transfer_plan([_profile("alpha", ["a1"])], "", list(manager.AGENT_IDS),
                          home=tmp_path, config_path=str(config))

    assert config.read_text(encoding="utf-8") == before
    assert not (tmp_path / ".continue" / "config.yaml").exists()
    assert not (tmp_path / ".aider.conf.yml").exists()
    assert not (tmp_path / ".dsh" / "profiles").exists()


def test_transfer_plan_reports_broken_target(manager, tmp_path):
    cline = tmp_path / ".cline" / "data" / "settings" / "providers.json"
    cline.parent.mkdir(parents=True)
    cline.write_text("{ это не json", encoding="utf-8")

    plan = manager.transfer_plan([_profile("alpha", ["a1"])], "", ["cline"],
                                 home=tmp_path)

    assert len(plan) == 1
    assert plan[0]["ok"] is False
    assert "не разбирается" in plan[0]["message"]


def test_transfer_plan_marks_missing_vsix(manager, tmp_path):
    plan = manager.transfer_plan([_profile("alpha", ["a1"])], "", ["vscode"],
                                 home=tmp_path)
    assert plan[0]["ok"] is False
    assert ".vsix" in plan[0]["message"]


def test_transfer_plan_reports_missing_profiles(manager, tmp_path):
    plan = manager.transfer_plan([], "", ["aider"], home=tmp_path)
    assert plan[0]["ok"] is False
    assert "профил" in plan[0]["message"]
