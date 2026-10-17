"""Config migration of the old pv_residual_bound_fraction default (0.25 -> 1.0)."""

from pathlib import Path

import pytest
import yaml

from backend.config_migration import _migrate_config, _migrate_pv_residual_bound

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = str(REPO_ROOT / "config.default.yaml")


def _bound(cfg: dict) -> object:
    return cfg["forecasting"]["pv_residual_bound_fraction"]


def test_old_default_replaced() -> None:
    cfg, changed = _migrate_pv_residual_bound({"forecasting": {"pv_residual_bound_fraction": 0.25}})
    assert changed is True
    assert _bound(cfg) == 1.0


@pytest.mark.parametrize("value", [0.4, 0, 2.0, 1.0, True, "0.25", None])
def test_other_values_untouched(value: object) -> None:
    cfg, changed = _migrate_pv_residual_bound({"forecasting": {"pv_residual_bound_fraction": value}})
    assert changed is False
    assert _bound(cfg) == value or _bound(cfg) is value


def test_missing_key_or_section_untouched() -> None:
    assert _migrate_pv_residual_bound({"forecasting": {}})[1] is False
    assert _migrate_pv_residual_bound({})[1] is False
    assert _migrate_pv_residual_bound({"forecasting": None})[1] is False


def test_idempotent_function() -> None:
    cfg, _ = _migrate_pv_residual_bound({"forecasting": {"pv_residual_bound_fraction": 0.25}})
    _, changed = _migrate_pv_residual_bound(cfg)
    assert changed is False


def _write(tmp_path: Path, forecasting: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"forecasting": forecasting}), encoding="utf-8")
    return path


def test_full_migration_replaces_and_is_idempotent(tmp_path: Path) -> None:
    path = _write(tmp_path, {"pv_residual_bound_fraction": 0.25})
    _migrate_config(str(path), DEFAULT_PATH, False)
    assert yaml.safe_load(path.read_text())["forecasting"]["pv_residual_bound_fraction"] == 1.0

    # The first run also normalises formatting against the template; a further run
    # on the migrated file must be a no-op.
    _migrate_config(str(path), DEFAULT_PATH, False)
    first = path.read_text()
    mtime = path.stat().st_mtime_ns
    _migrate_config(str(path), DEFAULT_PATH, False)
    assert path.read_text() == first
    assert path.stat().st_mtime_ns == mtime


def test_full_migration_keeps_user_value(tmp_path: Path) -> None:
    for value in (0.4, 0, 2.0):
        path = _write(tmp_path, {"pv_residual_bound_fraction": value})
        _migrate_config(str(path), DEFAULT_PATH, False)
        assert yaml.safe_load(path.read_text())["forecasting"]["pv_residual_bound_fraction"] == value


def test_full_migration_missing_key_gets_template_default(tmp_path: Path) -> None:
    path = _write(tmp_path, {"pv_confidence_percent": 90})
    _migrate_config(str(path), DEFAULT_PATH, False)
    assert yaml.safe_load(path.read_text())["forecasting"]["pv_residual_bound_fraction"] == 1.0


def test_reflex_does_not_tune_pv_residual_bound() -> None:
    from backend.learning import reflex

    key = "forecasting.pv_residual_bound_fraction"
    assert key not in reflex.BOUNDS
    assert key not in reflex.MAX_DAILY_CHANGE
    source = Path(reflex.__file__).read_text(encoding="utf-8")
    assert "pv_residual_bound_fraction" not in source
