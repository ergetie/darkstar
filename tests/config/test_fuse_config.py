"""Fuse settings validation and startup compatibility."""

from pathlib import Path

import pytest
import yaml

from backend.api.routers.config import _validate_graceful_degradation_ranges
from backend.config_migration import remove_deprecated_keys, template_aware_merge
from executor.config import load_executor_config
from executor.fuse_model import FuseHeatModel


@pytest.mark.parametrize(
    "settings,key",
    [
        ({"fuse_preset": "unknown"}, "fuse_preset"),
        ({"fuse_safety_percent": 49}, "fuse_safety_percent"),
        ({"fuse_safety_percent": True}, "fuse_safety_percent"),
        ({"fuse_safety_percent": float("nan")}, "fuse_safety_percent"),
        ({"fuse_preset": "custom", "fuse_custom_points": []}, "fuse_custom_points"),
        (
            {
                "fuse_preset": "custom",
                "fuse_custom_points": [
                    {"overload_percent": 100, "time_s": 1},
                    {"overload_percent": 300, "time_s": 2},
                ],
            },
            "fuse_custom_points",
        ),
        (
            {
                "fuse_preset": "custom",
                "fuse_custom_points": [
                    {"overload_percent": 130, "time_s": 1},
                    {"overload_percent": 300, "time_s": 2},
                ],
            },
            "fuse_custom_points",
        ),
        (
            {
                "fuse_preset": "custom",
                "fuse_custom_points": [
                    {"overload_percent": 130, "time_s": 1},
                    {"overload_percent": 130, "time_s": 0.5},
                ],
            },
            "fuse_custom_points",
        ),
    ],
)
def test_invalid_settings_name_key(settings, key):
    issues = _validate_graceful_degradation_ranges(settings)
    assert any(f"load_balancing.{key}" in issue["message"] for issue in issues)


def test_custom_order_is_normalized_and_inactive_points_ignored(tmp_path):
    points = [{"overload_percent": 300, "time_s": 4}, {"overload_percent": 130, "time_s": 1200}]
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"load_balancing": {"fuse_preset": "custom", "fuse_custom_points": points}})
    )
    cfg = load_executor_config(str(path)).load_balancing
    assert cfg.fuse_custom_points[0].overload_percent == 130
    assert (
        _validate_graceful_degradation_ranges(
            {"fuse_preset": "typ_c", "fuse_custom_points": "ignored"}
        )
        == []
    )


@pytest.mark.parametrize("preset,safety", [("typ_c", 80), ("diazed_gg", 65), ("custom", 80)])
def test_loader_preserves_unset_safety(tmp_path, preset, safety):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"load_balancing": {"fuse_preset": preset}}))
    cfg = load_executor_config(str(path)).load_balancing
    assert cfg.fuse_safety_percent is None
    assert FuseHeatModel(cfg).safety_percent == safety


def test_old_keys_load_then_migrate_with_logging_and_no_readdition(tmp_path, caplog):
    old = {"pause_debounce_s": "obsolete", "severe_overload_percent": -1}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"load_balancing": {"enabled": True, **old}}))
    assert _validate_graceful_degradation_ranges(old) == []
    assert load_executor_config(str(path)).load_balancing.fuse_preset == "typ_c"
    assert not [
        record
        for record in caplog.records
        if record.levelno >= 30 and any(key in record.getMessage() for key in old)
    ]
    cfg = {"load_balancing": {"enabled": True, **old}}
    with caplog.at_level("INFO"):
        result, changed = remove_deprecated_keys(cfg)
    assert changed and result["load_balancing"] == {"enabled": True}
    assert all(key in caplog.text for key in old)
    _, changed = remove_deprecated_keys(result)
    assert not changed
    template_aware_merge(yaml.safe_load(Path("config.default.yaml").read_text()), result)
    assert not set(old).intersection(result["load_balancing"])
