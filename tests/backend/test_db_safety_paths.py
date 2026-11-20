"""Database path resolution of backend.db_safety."""

from pathlib import Path

import pytest

from backend import db_safety


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DB_PATH", raising=False)


def _write_config(tmp_path: Path, body: str) -> None:
    (tmp_path / "config.yaml").write_text(body)


def test_default_path_is_relative_to_cwd(tmp_path: Path) -> None:
    assert db_safety.resolve_db_path() == tmp_path / "data" / "planner_learning.db"


def test_config_overrides_default(tmp_path: Path) -> None:
    _write_config(tmp_path, "learning:\n  sqlite_path: custom/learn.db\n")
    assert db_safety.resolve_db_path() == tmp_path / "custom" / "learn.db"


def test_env_overrides_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, "learning:\n  sqlite_path: custom/learn.db\n")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "share" / "x.db"))
    assert db_safety.resolve_db_path() == tmp_path / "share" / "x.db"


def test_config_without_learning_section_uses_default(tmp_path: Path) -> None:
    _write_config(tmp_path, "timezone: Europe/Stockholm\n")
    assert db_safety.resolve_db_path() == tmp_path / "data" / "planner_learning.db"


def test_backup_dir_is_next_to_database(tmp_path: Path) -> None:
    db = tmp_path / "share" / "planner_learning.db"
    assert db_safety.backup_dir(db) == tmp_path / "share" / "backups"
