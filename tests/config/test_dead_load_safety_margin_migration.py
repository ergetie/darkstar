"""Config migration dropping the dead load_safety_margin_percent keys."""

from pathlib import Path

import yaml

from backend.config_migration import _migrate_config, _remove_dead_load_safety_margin

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = str(REPO_ROOT / "config.default.yaml")


def _config() -> dict:
    return {
        "forecasting": {"load_safety_margin_percent": 117.0, "pv_confidence_percent": 83.0},
        "learning": {
            "max_daily_param_change": {
                "load_safety_margin_percent": 1.0,
                "pv_confidence_percent": 1.0,
            }
        },
    }


def test_both_keys_removed_other_keys_kept() -> None:
    cfg, changed = _remove_dead_load_safety_margin(_config())
    assert changed is True
    assert cfg["forecasting"] == {"pv_confidence_percent": 83.0}
    assert cfg["learning"]["max_daily_param_change"] == {"pv_confidence_percent": 1.0}


def test_idempotent_and_clean_config_unchanged() -> None:
    cfg, _ = _remove_dead_load_safety_margin(_config())
    _, changed_again = _remove_dead_load_safety_margin(cfg)
    assert changed_again is False
    assert _remove_dead_load_safety_margin({})[1] is False
    assert _remove_dead_load_safety_margin({"forecasting": None, "learning": []})[1] is False


def test_template_does_not_define_keys() -> None:
    defaults = yaml.safe_load(Path(DEFAULT_PATH).read_text(encoding="utf-8"))
    assert "load_safety_margin_percent" not in defaults["forecasting"]
    assert "load_safety_margin_percent" not in defaults["learning"]["max_daily_param_change"]


def test_full_migration_removes_and_merge_does_not_readd(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    _migrate_config(str(path), DEFAULT_PATH, False)
    migrated = yaml.safe_load(path.read_text())
    assert "load_safety_margin_percent" not in migrated["forecasting"]
    assert "load_safety_margin_percent" not in migrated["learning"]["max_daily_param_change"]
    assert migrated["forecasting"]["pv_confidence_percent"] == 83.0
