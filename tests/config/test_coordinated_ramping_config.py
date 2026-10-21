"""load-balancer-coordinated-ramping: new load_balancing keys, custom load power
fields, validation errors and the migration that drops replan_after_throttled_s."""

from pathlib import Path

import pytest
import yaml

from backend.api.routers.config import (
    _validate_balanced_load_fields,
    _validate_graceful_degradation_ranges,
)
from backend.config_migration import _migrate_config, remove_deprecated_keys
from executor.config import (
    BalancedLoadType,
    LoadBalancingConfig,
    load_executor_config,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = str(REPO_ROOT / "config.default.yaml")


def _load(tmp_path: Path, load_balancing: dict, **extra) -> "LoadBalancingConfig":
    data = {
        "system": {"grid": {"main_fuse_a": 20}},
        "load_balancing": {"enabled": True, **load_balancing},
        **extra,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_executor_config(str(path)).load_balancing


class TestNewKeys:
    def test_defaults(self, tmp_path):
        lb = _load(tmp_path, {})
        assert lb.max_step_interval_s == 30
        assert lb.write_deadband_percent == 2.0
        assert lb.pending_timeout_s == 60
        assert lb.phase_sign == "import_positive"

    def test_values_are_read(self, tmp_path):
        lb = _load(
            tmp_path,
            {
                "max_step_interval_s": 20,
                "write_deadband_percent": 5,
                "pending_timeout_s": 90,
                "phase_sign": "import_negative",
            },
        )
        assert (lb.max_step_interval_s, lb.write_deadband_percent, lb.pending_timeout_s) == (
            20,
            5.0,
            90,
        )
        assert lb.phase_sign == "import_negative"

    def test_out_of_range_values_fall_back_to_defaults(self, tmp_path):
        lb = _load(
            tmp_path,
            {"max_step_interval_s": 1, "write_deadband_percent": 80, "pending_timeout_s": 5000},
        )
        assert lb.max_step_interval_s == 30
        assert lb.write_deadband_percent == 2.0
        assert lb.pending_timeout_s == 60

    def test_invalid_phase_sign_falls_back(self, tmp_path):
        assert _load(tmp_path, {"phase_sign": "sideways"}).phase_sign == "import_positive"


class TestLoadFields:
    def test_existing_custom_load_loads_without_new_fields(self, tmp_path):
        lb = _load(
            tmp_path,
            {
                "loads": [
                    {
                        "device_type": "custom_entity",
                        "device_id": "pump",
                        "phases": [1],
                        "entity": "switch.pump",
                    }
                ]
            },
        )
        load = lb.loads[0]
        assert load.device_type == BalancedLoadType.CUSTOM_ENTITY
        assert load.power_kw is None
        assert load.power_sensor is None
        assert (load.min_on_s, load.min_off_s) == (300, 300)

    def test_power_and_min_times_are_read(self, tmp_path):
        lb = _load(
            tmp_path,
            {
                "loads": [
                    {
                        "device_type": "custom_entity",
                        "device_id": "pump",
                        "phases": [1],
                        "power_kw": 2.2,
                        "power_sensor": "sensor.pump_w",
                        "min_on_s": 120,
                        "min_off_s": 600,
                    }
                ]
            },
        )
        load = lb.loads[0]
        assert load.power_kw == 2.2
        assert load.power_sensor == "sensor.pump_w"
        assert (load.min_on_s, load.min_off_s) == (120, 600)

    @pytest.mark.parametrize("bad", [0, -1.5, "abc"])
    def test_non_positive_power_is_ignored(self, tmp_path, bad):
        lb = _load(
            tmp_path,
            {
                "loads": [
                    {
                        "device_type": "custom_entity",
                        "device_id": "p",
                        "phases": [1],
                        "power_kw": bad,
                    }
                ]
            },
        )
        assert lb.loads[0].power_kw is None


class TestValidation:
    @pytest.mark.parametrize("bad", [0, -2, "x"])
    def test_non_positive_power_kw_is_an_error(self, bad):
        issues = _validate_balanced_load_fields({"power_kw": bad}, 0, "pump")
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"
        assert "power_kw" in issues[0]["message"]
        assert issues[0]["guidance"]

    def test_valid_load_fields_pass(self):
        assert (
            _validate_balanced_load_fields(
                {"power_kw": 1.5, "min_on_s": 0, "min_off_s": 300}, 0, "p"
            )
            == []
        )
        assert _validate_balanced_load_fields({}, 0, "p") == []

    def test_min_times_out_of_range(self):
        issues = _validate_balanced_load_fields({"min_on_s": 99999}, 1, "p")
        assert len(issues) == 1 and "min_on_s" in issues[0]["message"]

    def test_global_ranges_and_phase_sign(self):
        issues = _validate_graceful_degradation_ranges(
            {"max_step_interval_s": 1, "write_deadband_percent": 50, "phase_sign": "no"}
        )
        messages = " ".join(i["message"] for i in issues)
        assert "max_step_interval_s" in messages
        assert "write_deadband_percent" in messages
        assert "phase_sign" in messages
        assert _validate_graceful_degradation_ranges({"phase_sign": "import_negative"}) == []


class TestReplanKeyMigration:
    def test_old_config_drops_only_the_key(self):
        cfg = {
            "load_balancing": {
                "enabled": True,
                "replan_after_throttled_s": 600,
                "pause_debounce_s": 5,
            }
        }
        out, changed = remove_deprecated_keys(cfg)
        assert changed is True
        assert out["load_balancing"] == {"enabled": True, "pause_debounce_s": 5}

    def test_migrated_config_is_untouched(self):
        cfg = {"load_balancing": {"enabled": True}}
        _, changed = remove_deprecated_keys(cfg)
        assert changed is False

    def test_full_migration_is_idempotent_and_template_does_not_readd_it(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(
            yaml.safe_dump({"load_balancing": {"enabled": False, "replan_after_throttled_s": 600}}),
            encoding="utf-8",
        )
        _migrate_config(str(path), DEFAULT_PATH, False)
        migrated = yaml.safe_load(path.read_text())
        assert "replan_after_throttled_s" not in migrated["load_balancing"]
        # The shipped template documents the new keys, not the removed one.
        template = yaml.safe_load(Path(DEFAULT_PATH).read_text())["load_balancing"]
        assert "replan_after_throttled_s" not in template
        for key in (
            "max_step_interval_s",
            "write_deadband_percent",
            "pending_timeout_s",
            "phase_sign",
        ):
            assert key in template

        _migrate_config(str(path), DEFAULT_PATH, False)
        first = path.read_text()
        mtime = path.stat().st_mtime_ns
        _migrate_config(str(path), DEFAULT_PATH, False)
        assert path.read_text() == first
        assert path.stat().st_mtime_ns == mtime


@pytest.mark.parametrize(
    "key,default",
    [
        ("max_step_interval_s", 30),
        ("write_deadband_percent", 2),
        ("pending_timeout_s", 60),
        ("phase_sign", "import_positive"),
    ],
)
def test_shipped_coordination_defaults_are_documented(key, default):
    template = Path(DEFAULT_PATH).read_text()
    config = yaml.safe_load(template)
    assert config["load_balancing"][key] == default
    line = next(line for line in template.splitlines() if line.strip().startswith(key + ":"))
    assert "#" in line and len(line.split("#", 1)[1].strip()) > 20


def test_fuse_rating_does_not_change_planner_import_budget(tmp_path):
    from planner.solver.adapter import config_to_kepler_config

    config = {
        "config_version": 2,
        "system": {"grid": {"main_fuse_a": 20, "max_power_kw": 8}},
        "load_balancing": {"enabled": True},
        "battery": {"capacity_kwh": 0},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    assert load_executor_config(str(path)).load_balancing.main_fuse_a == 20
    assert config_to_kepler_config(config).max_import_power_kw == 8
