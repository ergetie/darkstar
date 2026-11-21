"""Config migration dropping the dead error-correction and auto-tune keys."""

from pathlib import Path

import yaml

from backend.config_migration import _migrate_config, remove_deprecated_keys

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = str(REPO_ROOT / "config.default.yaml")


def _config() -> dict:
    return {
        "learning": {
            "enabled": True,
            "reflex_enabled": True,
            "error_correction_enabled": True,
            "auto_tune_enabled": True,
        },
        "automation": {
            "ml_training": {
                "enabled": True,
                "run_days": [1, 4],
                "error_correction_enabled": True,
            }
        },
    }


def test_three_keys_removed_siblings_kept() -> None:
    cfg, changed = remove_deprecated_keys(_config())
    assert changed is True
    assert cfg["learning"] == {"enabled": True, "reflex_enabled": True}
    assert cfg["automation"]["ml_training"] == {"enabled": True, "run_days": [1, 4]}


def test_idempotent_and_clean_config_unchanged() -> None:
    cfg, _ = remove_deprecated_keys(_config())
    _, changed_again = remove_deprecated_keys(cfg)
    assert changed_again is False
    assert remove_deprecated_keys({})[1] is False


def test_none_and_non_dict_sections_are_tolerated() -> None:
    for config in (
        {"learning": None, "automation": None},
        {"learning": [], "automation": {"ml_training": None}},
        {"learning": "x", "automation": {"ml_training": []}},
    ):
        assert remove_deprecated_keys(config)[1] is False


def test_template_does_not_define_keys() -> None:
    defaults = yaml.safe_load(Path(DEFAULT_PATH).read_text(encoding="utf-8"))
    assert "error_correction_enabled" not in defaults.get("learning", {})
    assert "auto_tune_enabled" not in defaults.get("learning", {})
    assert "error_correction_enabled" not in defaults.get("automation", {}).get("ml_training", {})


def test_full_migration_removes_and_merge_does_not_readd(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    _migrate_config(str(path), DEFAULT_PATH, False)
    migrated = yaml.safe_load(path.read_text())
    assert "error_correction_enabled" not in migrated["learning"]
    assert "auto_tune_enabled" not in migrated["learning"]
    assert "error_correction_enabled" not in migrated["automation"]["ml_training"]
    assert migrated["learning"]["reflex_enabled"] is True
    assert migrated["automation"]["ml_training"]["enabled"] is True
    assert migrated["automation"]["ml_training"]["run_days"] == [1, 4]
