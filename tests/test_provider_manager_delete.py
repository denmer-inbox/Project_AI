"""Удаление профиля должно сразу попадать в opencode.json.

Раньше кнопка УДАЛИТЬ убирала профиль только из списка окна, и он
возвращался после перезапуска: запись происходила лишь по кнопке
«ПРИМЕНИТЬ КОНФИГУ», а выход через трей ничего не сохранял.
"""

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


def _bare_app(manager, profiles, config=None, loaded=None):
    """App без сборки окна: только то, что нужно проверяемым методам."""
    app = manager.App.__new__(manager.App)
    app.root = None
    app.profiles = list(profiles)
    app.selected = None
    app.config = config if config is not None else {}
    app._loaded_provider_ids = set(loaded if loaded is not None else [p["id"] for p in profiles])
    app._deleted_ids = set()
    app._render_list = lambda: None
    app._set_status = lambda *a, **k: None
    app._refresh_dirty_marker = lambda: None
    app._refresh_history = lambda: None
    return app


def _profile(pid, models=("m1",)):
    return {
        "id": pid,
        "display_name": pid.upper(),
        "coefficient": "",
        "base_url": "https://%s.example/v1" % pid,
        "package": "@ai-sdk/openai-compatible",
        "api_key": "key-" + pid,
        "models": list(models),
        "known_models": list(models),
        "model_capabilities": {},
        "extra_settings": {},
        "_raw": {"name": pid.upper()},
    }


def test_delete_profile_writes_config_immediately(manager, monkeypatch):
    app = _bare_app(manager, [_profile("a"), _profile("b")])
    app.selected = "a"
    calls = []
    app.write_config = lambda silent=False: calls.append(silent) or True
    monkeypatch.setattr(manager.messagebox, "askyesno", lambda *a, **k: True)

    app.delete_profile()

    assert calls == [True], "удаление обязано сразу писать конфиг"
    assert [p["id"] for p in app.profiles] == ["b"]
    assert "a" in app._deleted_ids


def test_delete_profile_rolls_back_when_write_fails(manager, monkeypatch):
    app = _bare_app(manager, [_profile("a"), _profile("b"), _profile("c")])
    app.selected = "b"
    app.write_config = lambda silent=False: False
    monkeypatch.setattr(manager.messagebox, "askyesno", lambda *a, **k: True)

    app.delete_profile()

    # профиль вернулся на прежнее место, экран не врёт
    assert [p["id"] for p in app.profiles] == ["a", "b", "c"]
    assert "b" not in app._deleted_ids


def test_delete_profile_cancelled_keeps_profile(manager, monkeypatch):
    app = _bare_app(manager, [_profile("a")])
    app.selected = "a"
    calls = []
    app.write_config = lambda silent=False: calls.append(silent) or True
    monkeypatch.setattr(manager.messagebox, "askyesno", lambda *a, **k: False)

    app.delete_profile()

    assert calls == []
    assert [p["id"] for p in app.profiles] == ["a"]


def test_write_plan_uses_fresh_file_not_stale_memory(manager, tmp_path):
    """Провайдер, добавленный в файл мимо менеджера, не должен теряться."""
    cfg_path = tmp_path / "opencode.json"
    disk = {
        "providers": {
            "alpha": {"name": "Alpha", "models": {"a1": {}}},
            "external": {"name": "External", "models": {"e1": {}}},
        }
    }
    cfg_path.write_text(json.dumps(disk), encoding="utf-8")

    app = _bare_app(manager, [_profile("alpha")],
                    config={"providers": {"alpha": disk["providers"]["alpha"]}},
                    loaded={"alpha"})
    app.config_path = cfg_path
    app.var_default_model = type("V", (), {"get": lambda self: ""})()

    new_config, _coefs, info = app._collect_write_plan()

    assert sorted(new_config["providers"]) == ["alpha", "external"]
    assert info["keep_ids"] == {"external"}
    assert info["removed"] == []


def test_write_plan_removes_deleted_profile_from_disk(manager, tmp_path):
    cfg_path = tmp_path / "opencode.json"
    disk = {"providers": {"alpha": {"name": "Alpha", "models": {"a1": {}}},
                          "beta": {"name": "Beta", "models": {"b1": {}}}}}
    cfg_path.write_text(json.dumps(disk), encoding="utf-8")

    app = _bare_app(manager, [_profile("alpha")],
                    config=disk, loaded={"alpha", "beta"})
    app.config_path = cfg_path
    app.var_default_model = type("V", (), {"get": lambda self: ""})()

    new_config, _coefs, info = app._collect_write_plan()

    assert sorted(new_config["providers"]) == ["alpha"]
    assert info["removed"] == ["beta"]


def test_write_plan_drops_dangling_default_model(manager, tmp_path):
    """Модель по умолчанию не должна ссылаться на удалённый профиль."""
    cfg_path = tmp_path / "opencode.json"
    disk = {"model": "beta/b1",
            "providers": {"alpha": {"name": "Alpha", "models": {"a1": {}}},
                          "beta": {"name": "Beta", "models": {"b1": {}}}}}
    cfg_path.write_text(json.dumps(disk), encoding="utf-8")

    app = _bare_app(manager, [_profile("alpha")],
                    config=disk, loaded={"alpha", "beta"})
    app.config_path = cfg_path
    app.var_default_model = type("V", (), {"get": lambda self: ""})()

    new_config, _coefs, info = app._collect_write_plan()

    assert "model" not in new_config
    assert info["cleared_default"] == "beta/b1"


def test_write_plan_handles_stale_config_path(manager, tmp_path):
    """Файла нет — план строится по памяти без падения."""
    app = _bare_app(manager, [_profile("alpha")],
                    config={"providers": {"alpha": {"name": "Alpha", "models": {"a1": {}}}}},
                    loaded={"alpha"})
    app.config_path = tmp_path / "missing.json"
    app.var_default_model = type("V", (), {"get": lambda self: "alpha/a1"})()

    new_config, _coefs, info = app._collect_write_plan()

    assert sorted(new_config["providers"]) == ["alpha"]
    assert info["base_ids"] == {"alpha"}
