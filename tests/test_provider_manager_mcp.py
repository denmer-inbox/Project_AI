"""MCP-серверы и скиллы в менеджере: запись в конфиг, безопасная распаковка."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "opencode_provider_manager.py"

#: Имя как у профилей: кэш модулей должен указывать на тот же файл, что
#: загружают Tk-тесты, иначе `isinstance` и подмена классов расходятся.
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


def _skill_md(name, description="описание"):
    return "---\nname: %s\ndescription: %s\n---\n\n# %s\n\nтекст\n" % (
        name, description, name)


# --- каталог MCP --------------------------------------------------------


def test_mcp_catalog_has_ids_and_entries(manager):
    assert "rea" in manager.MCP_SERVER_IDS
    rea = manager.mcp_catalog_entry("rea")
    assert rea["kind"] == "local"
    assert rea["command"][:3] == ["cmd.exe", "/d", "/c"]
    assert manager.mcp_catalog_entry("нет-такого") is None


def test_mcp_local_entry_keeps_only_filled_env(manager):
    entry = manager.mcp_server_entry(
        manager.mcp_catalog_entry("rea"),
        {"GHIDRA_INSTALL_DIR": "D:\\ghidra", "JAVA_HOME": "  "})
    assert entry["type"] == "local"
    assert entry["disabled"] is False
    assert "enabled" not in entry
    assert entry["environment"] == {"GHIDRA_INSTALL_DIR": "D:\\ghidra"}
    plain = manager.mcp_server_entry(manager.mcp_catalog_entry("rea"), {})
    assert "environment" not in plain


def test_mcp_remote_entry_stores_real_token(manager):
    entry = manager.mcp_server_entry(manager.mcp_catalog_entry("github"),
                                     {"GITHUB_PAT": "ghp_secret"})
    assert entry["type"] == "remote"
    assert entry["headers"]["Authorization"] == "Bearer ghp_secret"
    assert "ghp_secret" in json.dumps(entry)
    assert list(manager.mcp_entry_secrets(entry)) == []
    with pytest.raises(ValueError):
        manager.mcp_server_entry(manager.mcp_catalog_entry("github"), {})


def test_mcp_path_server_requires_folder(manager):
    with pytest.raises(ValueError):
        manager.mcp_server_entry(manager.mcp_catalog_entry("filesystem"), {})
    entry = manager.mcp_server_entry(manager.mcp_catalog_entry("filesystem"),
                                     {"path": "C:\\Projects"})
    assert entry["command"][-1] == "C:\\Projects"


# --- запись в конфиг ----------------------------------------------------


def test_apply_mcp_servers_keeps_everything_else(manager):
    config = {
        "providers": {"alpha": {"name": "A", "models": {}}},
        "skills": ["skills"],
        "agent": {"plan": {"description": "x"}},
    }
    entry = manager.mcp_server_entry(manager.mcp_catalog_entry("memory"), {})
    result = manager.apply_mcp_servers(config, {"memory": entry})
    new = result["config"]
    assert new["mcp"]["servers"]["memory"] == entry
    assert "memory" not in new["mcp"]
    assert new["providers"] == config["providers"]
    assert new["skills"] == ["skills"]
    assert new["agent"] == config["agent"]
    assert result["changes"]["memory"] == ["новый сервер"]


def test_apply_mcp_servers_reports_update(manager):
    old = {"mcp": {"rea": {"type": "local", "command": ["old"], "enabled": True}}}
    entry = manager.mcp_server_entry(manager.mcp_catalog_entry("rea"), {})
    result = manager.apply_mcp_servers(old, {"rea": entry})
    assert "обновлён «command»" in result["changes"]["rea"]
    assert result["config"]["mcp"]["servers"]["rea"]["disabled"] is False


def test_apply_mcp_servers_migrates_legacy_entries(manager):
    """Старая запись «прямо в mcp» переезжает в mcp.servers без ключа enabled."""
    old = {"mcp": {"rea": {"type": "local", "command": ["old"], "enabled": True}}}
    entry = manager.mcp_server_entry(manager.mcp_catalog_entry("memory"), {})
    result = manager.apply_mcp_servers(old, {"memory": entry})
    mcp = result["config"]["mcp"]
    assert list(mcp) == ["servers"]
    assert mcp["servers"]["rea"] == {"type": "local", "command": ["old"],
                                     "disabled": False}
    assert set(mcp["servers"]) == {"rea", "memory"}


def test_install_mcp_servers_writes_config_and_backup(tmp_path, manager):
    config_file = tmp_path / "opencode.json"
    config_file.write_text(json.dumps({"providers": {}, "mcp": {}}), encoding="utf-8")
    entry = manager.mcp_server_entry(manager.mcp_catalog_entry("rea"), {})
    results = manager.install_mcp_servers({"rea": entry}, config_path=config_file,
                                          home=tmp_path)
    assert results[0]["ok"] is True
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["mcp"]["servers"]["rea"]["command"][-1] == "mcp"
    assert "rea" not in saved["mcp"]
    assert Path(results[0]["backup"]).exists()


def test_install_mcp_servers_writes_agent_files(tmp_path, manager):
    config_file = tmp_path / "opencode.json"
    config_file.write_text("{}", encoding="utf-8")
    entry = manager.mcp_server_entry(manager.mcp_catalog_entry("memory"), {})
    results = manager.install_mcp_servers(
        {"memory": entry}, config_path=config_file, home=tmp_path,
        mcp_config_path=tmp_path / ".mcp.json",
        mcp_agent_ids=["claude", "codex"])
    assert all(r["ok"] for r in results)
    claude = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert claude["mcpServers"]["memory"]["command"] == "cmd.exe"
    assert "server-memory" in claude["mcpServers"]["memory"]["args"][-1]
    toml = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.memory]" in toml
    # повторная запись не дублирует блок
    manager.install_mcp_servers({"memory": entry}, config_path=config_file,
                                home=tmp_path, mcp_agent_ids=["codex"])
    toml2 = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert toml2.count("[mcp_servers.memory]") == 1


def test_mcp_servers_from_config_skips_disabled(manager):
    servers = manager.mcp_servers_from_config({"mcp": {
        "on": {"type": "local", "command": ["x"], "enabled": True},
        "off": {"type": "local", "command": ["y"], "enabled": False},
        "short": {"enabled": True},
    }})
    assert set(servers) == {"on"}
    assert servers["on"]["command"] == ["x"]


# --- скиллы -------------------------------------------------------------


def test_skill_manifest_reads_frontmatter(manager, tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(_skill_md("my-skill", "полезный навык"), encoding="utf-8")
    manifest = manager.skill_manifest(path)
    assert manifest == {"name": "my-skill", "description": "полезный навык"}


def test_install_skills_from_folder(manager, tmp_path):
    src = tmp_path / "src"
    (src / "one").mkdir(parents=True)
    (src / "one" / "SKILL.md").write_text(_skill_md("one"), encoding="utf-8")
    (src / "two" / "references").mkdir(parents=True)
    (src / "two" / "SKILL.md").write_text(_skill_md("two"), encoding="utf-8")
    (src / "two" / "references" / "doc.md").write_text("ref", encoding="utf-8")
    base = tmp_path / "skills"

    report = manager.install_skills(src, base=base)
    assert sorted(report["installed"]) == ["one", "two"]
    assert (base / "two" / "references" / "doc.md").read_text(encoding="utf-8") == "ref"
    assert [s["name"] for s in manager.list_installed_skills(base)] == ["one", "two"]

    report = manager.install_skills(src, base=base)
    assert sorted(report["skipped"]) == ["one", "two"]
    assert report["installed"] == []


def test_install_skills_from_zip(manager, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("pack-1.0/skills/zip-skill/SKILL.md", _skill_md("zip-skill"))
    archive_path = tmp_path / "skills.zip"
    archive_path.write_bytes(buf.getvalue())

    report = manager.install_skills(archive_path, base=tmp_path / "skills")
    assert report["installed"] == ["zip-skill"]


def test_install_skills_from_tar_gz(manager, tmp_path):
    payload = _skill_md("tar-skill").encode("utf-8")
    archive_path = tmp_path / "skills.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("pkg/tar-skill/SKILL.md")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    report = manager.install_skills(archive_path, base=tmp_path / "skills")
    assert report["installed"] == ["tar-skill"]


def test_install_skills_rejects_zip_slip(manager, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("../../evil/SKILL.md", _skill_md("evil"))
    archive_path = tmp_path / "evil.zip"
    archive_path.write_bytes(buf.getvalue())

    with pytest.raises(Exception):
        manager.install_skills(archive_path, base=tmp_path / "skills")
    assert not (tmp_path / "evil").exists()


def test_remove_skill_only_inside_base(manager, tmp_path):
    base = tmp_path / "skills"
    (base / "one").mkdir(parents=True)
    (base / "one" / "SKILL.md").write_text(_skill_md("one"), encoding="utf-8")
    assert manager.remove_skill("one", base=base) is True
    assert not (base / "one").exists()
    assert manager.remove_skill("../outside", base=base) is False
    assert manager.remove_skill("absent", base=base) is False


def test_skills_base_dir_from_config_and_default(manager, tmp_path):
    assert manager.skills_base_dir({"skills": ["my-skills"]},
                                   home=tmp_path) == (
        tmp_path / ".config" / "opencode" / "my-skills")
    assert manager.skills_base_dir({}, home=tmp_path) == (
        tmp_path / ".config" / "opencode" / "skills")


def test_find_skill_dirs_accepts_single_root(manager, tmp_path):
    (tmp_path / "SKILL.md").write_text(_skill_md("root-skill"), encoding="utf-8")
    found = manager.find_skill_dirs(tmp_path)
    assert found == [tmp_path]
