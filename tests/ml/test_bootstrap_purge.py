"""Startup purge of the stale pv_error.lgb / load_error.lgb model files."""

import logging
from pathlib import Path

import pytest

import ml.bootstrap as bootstrap
from ml.bootstrap import STALE_MODEL_FILES, ensure_active_models, purge_stale_error_models

REAL = ("load_model.lgb", "load_model_p50.lgb", "pv_model_p10.lgb")


def _populate(runtime: Path) -> list[Path]:
    """Real models plus stale files in runtime, defaults/ and two backups."""
    folders = [
        runtime,
        runtime / "defaults",
        runtime / "backup" / "backup_20260101",
        runtime / "backup" / "backup_20260102",
    ]
    stale: list[Path] = []
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        for name in REAL:
            (folder / name).write_bytes(b"model")
        (folder / "load_model.features.json").write_text("{}")
    for folder in (runtime, runtime / "defaults", runtime / "backup" / "backup_20260101"):
        for name in STALE_MODEL_FILES:
            (folder / name).write_bytes(b"stale")
            stale.append(folder / name)
    # One backup holds only a single stale file
    (runtime / "backup" / "backup_20260102" / "load_error.lgb").write_bytes(b"stale")
    stale.append(runtime / "backup" / "backup_20260102" / "load_error.lgb")
    return stale


def test_purge_removes_only_the_two_stale_files_and_logs(tmp_path, caplog):
    runtime = tmp_path / "models"
    stale = _populate(runtime)
    before_real = sorted(p for p in runtime.rglob("*") if p.is_file() and p not in stale)

    with caplog.at_level(logging.INFO, logger="ml.bootstrap"):
        deleted = purge_stale_error_models(runtime)

    assert sorted(deleted) == sorted(stale)
    assert not any(p.exists() for p in stale)
    assert sorted(p for p in runtime.rglob("*") if p.is_file()) == before_real
    assert sum("Deleted stale model file" in r.message for r in caplog.records) == len(stale)


def test_second_run_is_a_silent_noop(tmp_path, caplog):
    runtime = tmp_path / "models"
    _populate(runtime)
    purge_stale_error_models(runtime)
    snapshot = sorted(runtime.rglob("*"))
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="ml.bootstrap"):
        assert purge_stale_error_models(runtime) == []

    assert sorted(runtime.rglob("*")) == snapshot
    assert [r for r in caplog.records if r.name == "ml.bootstrap"] == []


def test_missing_folders_do_not_fail(tmp_path):
    assert purge_stale_error_models(tmp_path / "does-not-exist") == []


def test_defaults_do_not_ship_stale_files():
    defaults = Path(bootstrap.__file__).parent / "models" / "defaults"
    assert not any((defaults / name).exists() for name in STALE_MODEL_FILES)


@pytest.mark.parametrize("with_defaults", [True, False])
def test_ensure_active_models_purges_even_without_defaults(tmp_path, monkeypatch, with_defaults):
    root = tmp_path / "root"
    (root / "ml").mkdir(parents=True)
    if with_defaults:
        (root / "ml" / "models" / "defaults").mkdir(parents=True)
        (root / "ml" / "models" / "defaults" / "load_model.lgb").write_bytes(b"m")
    runtime = root / "data" / "ml" / "models"
    stale = _populate(runtime)
    monkeypatch.setattr(bootstrap, "__file__", str(root / "ml" / "bootstrap.py"))

    ensure_active_models()

    assert not any(p.exists() for p in stale)
    assert (runtime / "load_model.lgb").exists()
    if with_defaults:
        # The refreshed defaults copy mirrors the shipped defaults only
        assert sorted(p.name for p in (runtime / "defaults").iterdir()) == ["load_model.lgb"]
