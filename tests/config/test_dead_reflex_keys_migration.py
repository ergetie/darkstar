"""Config migration dropping the dead Reflex keys (Reflex was removed)."""

from pathlib import Path

import yaml

from backend.config_migration import _migrate_config, remove_deprecated_keys

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = str(REPO_ROOT / "config.default.yaml")
REFLEX_KEYS = (
    "reflex_enabled",
    "max_daily_param_change",
    "min_sample_threshold",
    "min_improvement_threshold",
)


def _config() -> dict:
    return {
        "learning": {
            "enable": True,
            "horizon_days": 3,
            "reflex_enabled": True,
            "max_daily_param_change": {"pv_confidence_percent": 1.0, "s_index_base_factor": 0.05},
            "min_sample_threshold": 2,
            "min_improvement_threshold": 0.015,
        },
        "forecasting": {"pv_confidence_percent": 95},
    }


def test_four_keys_removed_manual_values_kept() -> None:
    cfg, changed = remove_deprecated_keys(_config())
    assert changed is True
    assert cfg["learning"] == {"enable": True, "horizon_days": 3}
    assert cfg["forecasting"]["pv_confidence_percent"] == 95


def test_idempotent() -> None:
    cfg, _ = remove_deprecated_keys(_config())
    assert remove_deprecated_keys(cfg)[1] is False


def test_null_and_non_mapping_learning_are_tolerated() -> None:
    for learning in (None, [], "x", 3):
        assert remove_deprecated_keys({"learning": learning})[1] is False


def test_template_does_not_define_keys() -> None:
    defaults = yaml.safe_load(Path(DEFAULT_PATH).read_text(encoding="utf-8"))
    for key in REFLEX_KEYS:
        assert key not in defaults["learning"]


def test_full_migration_removes_and_merge_does_not_readd(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    _migrate_config(str(path), DEFAULT_PATH, False)
    migrated = yaml.safe_load(path.read_text())
    for key in REFLEX_KEYS:
        assert key not in migrated["learning"]
    assert migrated["forecasting"]["pv_confidence_percent"] == 95
    assert migrated["learning"]["enable"] is True
