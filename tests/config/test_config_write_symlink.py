"""Persistence regressions for shared config writes and every runtime caller."""

import errno
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from ruamel.yaml import YAML

from backend import config_migration as cm


@pytest.fixture
def linked_config(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.setattr(cm, "HOST_BACKUP_DIR", tmp_path / "no-host-backups")
    real_dir = tmp_path / "persistent"
    real_dir.mkdir()
    target = real_dir / "config.yaml"
    defaults = Path("config.default.yaml").read_text()
    target.write_text(defaults)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    link = app_dir / "config.yaml"
    link.symlink_to(target)
    (app_dir / "config.default.yaml").write_text(defaults)
    return link, target


def test_symlink_write_keeps_link_and_target_siblings(linked_config):
    link, target = linked_config
    yaml = YAML()
    data = yaml.load(target.read_text())
    data["system"]["inverter_profile"] = "deye"
    assert cm.write_config(link, data, yaml)
    assert link.is_symlink()
    assert yaml.load(target.read_text())["system"]["inverter_profile"] == "deye"
    assert target.with_suffix(".yaml.bak").exists()
    assert not target.with_suffix(".yaml.tmp").exists()
    assert sorted(p.name for p in link.parent.iterdir()) == ["config.default.yaml", "config.yaml"]


def test_backup_resolves_real_persistent_root(linked_config, monkeypatch):
    link, target = linked_config
    backup_root = target.parent / "share-backups"
    monkeypatch.setattr(cm, "PERSISTENT_CONFIG_ROOT", target.parent)
    monkeypatch.setattr(cm, "HA_BACKUP_DIR", backup_root)
    assert cm._get_persistent_backup_dir(link) == backup_root
    assert cm.update_config(link, lambda data: data["system"].update(inverter_profile="deye"))
    assert len(list(backup_root.glob("*.bak"))) == 1
    assert not (link.parent / "backups").exists()


def test_interrupted_temp_write_preserves_live_config(linked_config):
    link, target = linked_config
    before = target.read_bytes()

    class InterruptedYaml:
        def dump(self, data, handle):
            handle.write("system:\n  inverter_profile:")
            handle.flush()
            raise SystemExit("interrupted before replace")

    data = YAML().load(target.read_text())
    data["system"]["inverter_profile"] = "deye"
    with pytest.raises(SystemExit, match="interrupted before replace"):
        cm.write_config(link, data, InterruptedYaml())

    assert link.is_symlink()
    assert target.read_bytes() == before
    assert target.with_suffix(".yaml.bak").read_bytes() == before
    assert not target.with_suffix(".yaml.tmp").exists()


@pytest.mark.parametrize("error", [errno.EBUSY, errno.EXDEV, errno.ETXTBSY])
def test_bind_mount_fallback_single_replace_and_backup_first(linked_config, monkeypatch, error):
    link, target = linked_config
    calls = []
    real_copy = shutil.copyfile

    def replace(source, destination):
        calls.append((source, destination))
        raise OSError(error, "bind mount")

    def copy(source, destination, **kwargs):
        if str(source).endswith(".tmp"):
            assert target.with_suffix(".yaml.bak").exists()
            assert list((target.parent / "backups").glob("*.bak"))
        return real_copy(source, destination, **kwargs)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(shutil, "copyfile", copy)
    assert cm.update_config(link, lambda data: data["learning"].update(reflex_enabled=True))
    assert len(calls) == 1
    assert link.is_symlink()
    assert YAML().load(target.read_text())["learning"]["reflex_enabled"] is True


def test_addon_guard_refuses_ephemeral_target(linked_config, monkeypatch):
    link, target = linked_config
    before = target.read_bytes()
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    assert not cm.update_config(link, lambda data: data["learning"].update(reflex_enabled=True))
    assert target.read_bytes() == before
    assert link.is_symlink()
    assert not target.with_suffix(".yaml.bak").exists()


def test_concurrent_mutators_preserve_both_changes(linked_config):
    link, target = linked_config
    start = threading.Barrier(2)

    def update(key):
        start.wait(timeout=5)

        def mutate(data):
            time.sleep(0.02)
            data[key] = "persisted"

        return cm.update_config(link, mutate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(update, ["first", "second"]))
    data = YAML().load(target.read_text())
    assert data["first"] == data["second"] == "persisted"


def test_temp_fsync_precedes_replace_and_directory_fsync_follows(linked_config, monkeypatch):
    link, _ = linked_config
    operations = []
    fsync = os.fsync
    replace = Path.replace

    def spy_fsync(fd):
        operations.append("fsync")
        fsync(fd)

    def spy_replace(source, target):
        operations.append("replace")
        return replace(source, target)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(Path, "replace", spy_replace)
    assert cm.update_config(link, lambda data: data["learning"].update(reflex_enabled=True))
    assert operations == ["fsync", "replace", "fsync"]


@pytest.mark.asyncio
async def test_save_guard_returns_clear_error(linked_config, monkeypatch):
    from backend.api.routers import config

    link, target = linked_config
    monkeypatch.chdir(link.parent)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setattr(config, "_validate_config_for_save", lambda *_: [])
    before = target.read_bytes()
    with pytest.raises(HTTPException) as error:
        await config.save_config({"system": {"inverter_profile": "deye"}})
    assert error.value.status_code == 500
    assert "persistent storage" in error.value.detail["message"]
    assert target.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "writer",
    [
        "save",
        "empty_selection",
        "reset",
        "reflex",
        "executor",
        "entities",
        "notifications",
        "theme",
        "learning",
    ],
)
async def test_every_runtime_writer_preserves_symlink(linked_config, monkeypatch, writer):
    from backend.api.routers import config, executor, forecast, theme
    from backend.learning.reflex import AuroraReflex

    link, target = linked_config
    monkeypatch.chdir(link.parent)
    monkeypatch.setattr(executor, "get_executor_instance", lambda: None)
    monkeypatch.setattr(config, "get_executor_instance", lambda: None)
    monkeypatch.setattr(config, "_validate_config_for_save", lambda *_: [])
    monkeypatch.setattr(
        "backend.ha_socket.reload_ha_socket_client_async", AsyncMock(return_value=0)
    )
    expected_path, expected = None, None
    if writer == "save":
        await config.save_config({"system": {"inverter_profile": "deye"}})
        expected_path, expected = ("system", "inverter_profile"), "deye"
    elif writer == "empty_selection":
        await config.save_config(
            {"load_balancing": {"auto_include_devices": False, "give_way_order": []}}
        )
        expected_path, expected = ("load_balancing", "give_way_order"), []
        assert YAML().load(target.read_text())["load_balancing"]["auto_include_devices"] is False
    elif writer == "reset":
        await config.reset_config()
        assert YAML().load(target.read_text()) == YAML().load(
            (link.parent / "config.default.yaml").read_text()
        )
    elif writer == "reflex":
        await forecast.toggle_reflex(forecast.ToggleReflexRequest(enabled=True))
        expected_path, expected = ("learning", "reflex_enabled"), True
    elif writer == "executor":
        await executor.toggle_executor(executor.ToggleRequest(enabled=False))
        expected_path, expected = ("executor", "enabled"), False
    elif writer in ("entities", "notifications"):
        request = MagicMock()
        request.json = AsyncMock(
            return_value={"interval_seconds": 47} if writer == "entities" else {"on_error": True}
        )
        if writer == "entities":
            await executor.update_executor_config(request)
            expected_path, expected = ("executor", "interval_seconds"), 47
        else:
            await executor.update_notifications(request)
            expected_path, expected = ("executor", "notifications", "on_error"), True
    elif writer == "theme":
        name = next(iter(theme.load_themes()))
        await theme.select_theme(theme.ThemeSelectRequest(theme=name, accent_index=4))
        expected_path, expected = ("ui", "theme_accent_index"), 4
    elif writer == "learning":
        reflex = AuroraReflex.__new__(AuroraReflex)
        reflex.config_path = link
        reflex.yaml = YAML()
        reflex.store = MagicMock()
        reflex.store.update_reflex_state = AsyncMock()
        monkeypatch.setattr("backend.learning.reflex.append_strategy_event", MagicMock())
        await reflex.update_config({"battery.min_soc_percent": 24}, dry_run=False)
        expected_path, expected = ("battery", "min_soc_percent"), 24
    assert link.is_symlink()
    assert target.with_suffix(".yaml.bak").exists()
    assert list((target.parent / "backups").glob("*.bak"))
    if expected_path:
        value = YAML().load(target.read_text())
        for key in expected_path:
            value = value[key]
        assert value == expected


@pytest.mark.parametrize("bind_mount", [False, True])
def test_shared_config_does_not_require_metadata_permissions(
    linked_config, monkeypatch, bind_mount
):
    """A writable shared file need not permit chmod/utime by the app user."""
    link, target = linked_config
    before = target.read_bytes()
    legacy_backup = target.with_suffix(".yaml.bak")
    legacy_backup.write_text("previous backup")
    copystat = shutil.copystat

    def shared_metadata(source, destination, **kwargs):
        if Path(destination) in (target, legacy_backup):
            raise PermissionError(errno.EPERM, "shared file metadata owned by another user")
        return copystat(source, destination, **kwargs)

    monkeypatch.setattr(shutil, "copystat", shared_metadata)
    if bind_mount:

        def busy_replace(*_):
            raise OSError(errno.EBUSY, "bind mount")

        monkeypatch.setattr(Path, "replace", busy_replace)
    assert cm.update_config(link, lambda data: data["system"].update(inverter_profile="deye"))
    assert legacy_backup.read_bytes() == before
    assert YAML().load(target.read_text())["system"]["inverter_profile"] == "deye"


def test_legacy_backup_content_write_failure_aborts_save(linked_config, monkeypatch):
    link, target = linked_config
    before = target.read_bytes()
    copyfile = shutil.copyfile

    def denied_copy(source, destination, **kwargs):
        if Path(destination) == target.with_suffix(".yaml.bak"):
            raise PermissionError(errno.EACCES, "backup contents not writable")
        return copyfile(source, destination, **kwargs)

    monkeypatch.setattr(shutil, "copyfile", denied_copy)
    assert not cm.update_config(link, lambda data: data["system"].update(inverter_profile="deye"))
    assert target.read_bytes() == before
    assert not target.with_suffix(".yaml.tmp").exists()


def test_shared_config_rollback_restores_contents_without_metadata(linked_config, monkeypatch):
    link, target = linked_config
    before = target.read_bytes()
    target.with_suffix(".yaml.bak").write_text("previous backup")
    copystat = shutil.copystat

    def shared_metadata(source, destination, **kwargs):
        if Path(destination) in (target, target.with_suffix(".yaml.bak")):
            raise PermissionError(errno.EPERM, "shared metadata")
        return copystat(source, destination, **kwargs)

    monkeypatch.setattr(shutil, "copystat", shared_metadata)
    monkeypatch.setattr(cm, "_verify_written_config", lambda *_args, **_kwargs: False)
    assert not cm.update_config(link, lambda data: data["system"].update(inverter_profile="deye"))
    assert target.read_bytes() == before
    assert link.is_symlink()


def test_new_legacy_backup_preserves_restrictive_permissions(linked_config):
    link, target = linked_config
    target.chmod(0o600)
    assert cm.update_config(link, lambda data: data["system"].update(inverter_profile="deye"))
    assert target.with_suffix(".yaml.bak").stat().st_mode & 0o777 == 0o600
