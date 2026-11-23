"""The suite's protection of the real workspace (see the guard section of conftest.py)."""

import os
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def probe(real_workspace) -> Path:
    """A path inside the real data/ that must never come into existence."""
    return real_workspace.data_dir / ".guard_probe_never_created"


def test_tests_run_in_the_sandbox_not_the_repo(real_workspace):
    cwd = Path.cwd().resolve()
    assert cwd != real_workspace.repo_root.resolve()
    assert not (cwd / "data").resolve().is_relative_to(real_workspace.data_dir.resolve())
    assert (cwd / "config.default.yaml").exists()  # repo files stay reachable


def test_sandbox_has_no_real_state(real_workspace):
    assert Path("data").is_dir()
    assert Path("data").resolve() != real_workspace.data_dir.resolve()
    for name in ("config.yaml", "secrets.yaml"):
        real = real_workspace.repo_root / name
        if Path(name).exists() and real.exists():
            assert not os.path.samefile(name, real)


@pytest.mark.usefixtures("expect_real_workspace_violation")
def test_write_to_real_data_is_refused(probe):
    with pytest.raises(PermissionError), probe.open("w"):
        pass
    assert not probe.exists()


@pytest.mark.usefixtures("expect_real_workspace_violation")
def test_mkdir_and_rename_in_real_data_are_refused(real_workspace):
    data = real_workspace.data_dir
    with pytest.raises(PermissionError):
        (data / ".guard_probe_dir").mkdir()
    with pytest.raises(PermissionError):
        os.rename(data / ".guard_probe_a", data / ".guard_probe_b")


@pytest.mark.usefixtures("expect_real_workspace_violation")
def test_sqlite_connect_to_real_data_is_refused(probe):
    target = probe.with_suffix(".db")
    with pytest.raises(PermissionError):
        sqlite3.connect(str(target))
    assert not target.exists()


@pytest.mark.usefixtures("expect_real_workspace_violation")
def test_resolved_path_through_a_symlinked_checkout_is_refused(probe):
    # The repository may be reached through a symlink; the resolved location is protected too.
    with pytest.raises(PermissionError), Path(os.path.realpath(probe)).open("w"):
        pass


def test_reads_and_tmp_writes_are_allowed(tmp_path, real_workspace):
    (tmp_path / "x.txt").write_text("ok")
    assert (tmp_path / "x.txt").read_text() == "ok"
    sqlite3.connect(tmp_path / "x.db").close()
    for existing in real_workspace.data_dir.glob("*.json"):
        existing.read_bytes()  # reading is not blocked
        break


def test_snapshot_diff_reports_changes(real_workspace):
    before = {"a": (1, 1), "b": (2, 2), "d": (-1, 0)}
    after = {"a": (1, 1), "b": (3, 2), "c": (1, 1)}
    assert real_workspace.diff_snapshots(before, after) == [
        "added: c",
        "removed: d",
        "modified: b (size/mtime_ns (2, 2) -> (3, 2))",
    ]
