"""load-balancer-graceful-degradation 1.5: defaults, migration, range
validation and phase_1_line validation; plus the goal-at-risk helper (5.1)."""

from datetime import UTC, datetime, timedelta

import pytest
import yaml

from backend.api.routers.config import (
    _validate_graceful_degradation_ranges,
    _validate_phase_1_line,
)
from backend.config_migration import _migrate_target_margin
from executor.config import load_executor_config
from executor.goal_risk import pause_puts_goal_at_risk


_CHARGER = {
    "type": "current",
    "current_entity": "number.goe_current",
    "switch_entity": "switch.goe",
    "min_current_a": 6,
    "max_current_a": 16,
}


def _load(tmp_path, lb: dict, chargers: list | None = None):
    path = tmp_path / "config.yaml"
    data = {
        "system": {"grid": {"main_fuse_a": 16}},
        "executor": {"enabled": True},
        "load_balancing": lb,
    }
    if chargers is not None:
        data["ev_chargers"] = chargers
    path.write_text(yaml.dump(data))
    return load_executor_config(str(path))


class TestExecutorConfigParsing:
    def test_upgrade_picks_safe_defaults(self, tmp_path):
        lb = _load(tmp_path, {"enabled": True}).load_balancing
        assert lb.target_margin_percent == 85.0
        assert lb.pause_debounce_s == 5
        assert lb.resume_confirm_s == 10
        assert lb.resume_delay_s == 120
        assert lb.severe_overload_percent == 125.0
        assert lb.ramp_up_window_s == 60

    def test_tuned_legacy_resume_margin_is_used(self, tmp_path):
        lb = _load(tmp_path, {"resume_margin_percent": 80}).load_balancing
        assert lb.target_margin_percent == 80.0

    def test_untouched_legacy_default_uses_new_default(self, tmp_path):
        lb = _load(tmp_path, {"resume_margin_percent": 90}).load_balancing
        assert lb.target_margin_percent == 85.0

    def test_new_key_wins_over_legacy(self, tmp_path):
        lb = _load(
            tmp_path, {"resume_margin_percent": 80, "target_margin_percent": 70}
        ).load_balancing
        assert lb.target_margin_percent == 70.0

    @pytest.mark.parametrize(
        ("key", "bad", "default"),
        [
            ("target_margin_percent", 120, 85.0),
            ("pause_debounce_s", 120, 5),
            ("severe_overload_percent", 100, 125.0),
            ("ramp_up_window_s", 5, 60),
            ("pause_debounce_s", "soon", 5),
            ("resume_confirm_s", 2, 10),
            ("resume_confirm_s", 301, 10),
        ],
    )
    def test_out_of_range_falls_back_to_default(self, tmp_path, key, bad, default):
        lb = _load(tmp_path, {key: bad}).load_balancing
        assert getattr(lb, key) == default

    def test_phase_1_line_default_and_value(self, tmp_path):
        cfg = _load(
            tmp_path,
            {},
            [
                {**_CHARGER, "id": "a", "phases": [1, 2, 3]},
                {**_CHARGER, "id": "b", "phases": [1, 2, 3], "phase_1_line": 3},
            ],
        )
        lines = {c.id: c.phase_1_line for c in cfg.ev_chargers}
        assert lines == {"a": 1, "b": 3}

    def test_invalid_phase_1_line_falls_back(self, tmp_path):
        cfg = _load(tmp_path, {}, [{**_CHARGER, "id": "a", "phases": [1, 2], "phase_1_line": 3}])
        assert cfg.ev_chargers[0].phase_1_line == 1


class TestTargetMarginMigration:
    def test_tuned_value_is_moved(self):
        config = {"load_balancing": {"resume_delay_s": 120, "resume_margin_percent": 80}}
        config, changed = _migrate_target_margin(config)
        assert changed
        assert config["load_balancing"] == {"resume_delay_s": 120, "target_margin_percent": 80}

    def test_old_default_is_dropped_for_new_default(self):
        config = {"load_balancing": {"resume_margin_percent": 90}}
        config, changed = _migrate_target_margin(config)
        assert changed
        assert config["load_balancing"] == {}

    def test_both_present_new_key_wins(self):
        config = {"load_balancing": {"resume_margin_percent": 80, "target_margin_percent": 75}}
        config, changed = _migrate_target_margin(config)
        assert changed
        assert config["load_balancing"] == {"target_margin_percent": 75}

    def test_idempotent(self):
        config = {"load_balancing": {"resume_margin_percent": 80}}
        config, _ = _migrate_target_margin(config)
        config, changed = _migrate_target_margin(config)
        assert not changed
        assert config["load_balancing"] == {"target_margin_percent": 80}


class TestSaveValidation:
    def test_invalid_debounce_names_key_and_range(self):
        issues = _validate_graceful_degradation_ranges({"pause_debounce_s": 120})
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"
        assert "load_balancing.pause_debounce_s" in issues[0]["message"]
        assert "0-60" in issues[0]["message"]

    def test_invalid_resume_confirm_names_key_and_range(self):
        issues = _validate_graceful_degradation_ranges({"resume_confirm_s": 2})
        assert len(issues) == 1
        assert "load_balancing.resume_confirm_s" in issues[0]["message"]
        assert "5-300" in issues[0]["message"]

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("target_margin_percent", 49),
            ("severe_overload_percent", 201),
            ("ramp_up_window_s", 601),
            ("ramp_up_window_s", 30.5),
            ("pause_debounce_s", True),
            ("resume_confirm_s", 4),
            ("resume_confirm_s", 301),
            ("resume_confirm_s", 7.5),
        ],
    )
    def test_out_of_range_rejected(self, key, value):
        issues = _validate_graceful_degradation_ranges({key: value})
        assert [i["severity"] for i in issues] == ["error"]
        assert f"load_balancing.{key}" in issues[0]["message"]

    def test_valid_values_pass(self):
        assert (
            _validate_graceful_degradation_ranges(
                {
                    "target_margin_percent": 85,
                    "pause_debounce_s": 0,
                    "resume_confirm_s": 10,
                    "severe_overload_percent": 125,
                    "ramp_up_window_s": 60,
                }
            )
            == []
        )

    def test_phase_1_line_must_be_among_phases(self):
        issues = _validate_phase_1_line({"phases": [1, 2], "phase_1_line": 3}, "goe")
        assert len(issues) == 1 and "phase_1_line" in issues[0]["message"]
        assert _validate_phase_1_line({"phases": [1, 2, 3], "phase_1_line": 3}, "goe") == []
        assert _validate_phase_1_line({"phases": [1, 2, 3]}, "goe") == []
        assert _validate_phase_1_line({"phases": [1, 2, 3], "phase_1_line": 4}, "goe")


NOW = datetime(2026, 9, 25, 19, 30, tzinfo=UTC)


def _goal(deadline, edited=NOW - timedelta(hours=3), planned=NOW - timedelta(hours=1)):
    return {
        "deadline": deadline.isoformat(),
        "required_kwh": 8.0,
        "last_updated": edited.isoformat(),
        "last_planned_at": planned.isoformat(),
    }


def _diag(deadline, shortfall=0.0, reason=None):
    return {"deadline": deadline.isoformat(), "shortfall_kwh": shortfall, "reason": reason}


class TestGoalRisk:
    def test_far_goal_on_track_is_not_at_risk(self):
        deadline = NOW + timedelta(hours=30)
        assert not pause_puts_goal_at_risk(_goal(deadline), _diag(deadline), 7.0, NOW)[0]

    def test_shortfall_is_at_risk(self):
        deadline = NOW + timedelta(hours=30)
        at_risk, _ = pause_puts_goal_at_risk(
            _goal(deadline), _diag(deadline, 2.0, "grid_limit"), 0.0, NOW
        )
        assert at_risk

    def test_goal_slot_near_deadline_is_at_risk(self):
        deadline = NOW + timedelta(minutes=90)
        at_risk, why = pause_puts_goal_at_risk(_goal(deadline), _diag(deadline), 7.0, NOW)
        assert at_risk and "90 min" in why

    def test_near_deadline_outside_goal_slot_is_not_at_risk(self):
        deadline = NOW + timedelta(minutes=90)
        assert not pause_puts_goal_at_risk(_goal(deadline), _diag(deadline), 0.0, NOW)[0]

    def test_stale_diagnostics_fail_open(self):
        deadline = NOW + timedelta(hours=30)
        edited_after_plan = _goal(deadline, edited=NOW - timedelta(minutes=5))
        assert pause_puts_goal_at_risk(edited_after_plan, _diag(deadline), 0.0, NOW)[0]
        other_deadline = _diag(deadline + timedelta(days=1))
        assert pause_puts_goal_at_risk(_goal(deadline), other_deadline, 0.0, NOW)[0]

    def test_no_active_goal_is_not_at_risk(self):
        assert not pause_puts_goal_at_risk(None, None, 7.0, NOW)[0]
        past = _goal(NOW - timedelta(hours=1))
        assert not pause_puts_goal_at_risk(past, None, 7.0, NOW)[0]
        done = {**_goal(NOW + timedelta(hours=1)), "required_kwh": 0}
        assert not pause_puts_goal_at_risk(done, None, 7.0, NOW)[0]

    def test_charger_skipped_by_planner_is_not_at_risk(self):
        deadline = NOW + timedelta(hours=30)
        assert not pause_puts_goal_at_risk(_goal(deadline), None, 0.0, NOW)[0]


class TestPlugInReminderMigration:
    """Per-charger plug_in_reminder_minutes -> global notification setting."""

    def test_positive_values_enable_global_with_max(self):
        from backend.config_migration import _migrate_plug_in_reminder_to_global

        cfg = {
            "executor": {"notifications": {"on_error": True}},
            "ev_chargers": [
                {"id": "a", "plug_in_reminder_minutes": 15},
                {"id": "b", "plug_in_reminder_minutes": 45},
                {"id": "c", "plug_in_reminder_minutes": 0},
            ],
        }
        cfg, changed = _migrate_plug_in_reminder_to_global(cfg)
        assert changed
        notif = cfg["executor"]["notifications"]
        assert notif["on_ev_plug_in_reminder"] is True
        assert notif["ev_plug_in_reminder_minutes"] == 45
        assert notif["on_error"] is True
        assert all("plug_in_reminder_minutes" not in c for c in cfg["ev_chargers"])

        # Idempotent: a second run changes nothing.
        cfg, changed = _migrate_plug_in_reminder_to_global(cfg)
        assert not changed
        assert cfg["executor"]["notifications"]["ev_plug_in_reminder_minutes"] == 45

    def test_disabled_values_are_dropped_without_enabling(self):
        from backend.config_migration import _migrate_plug_in_reminder_to_global

        cfg = {"ev_chargers": [{"id": "a", "plug_in_reminder_minutes": 0}, {"id": "b"}]}
        cfg, changed = _migrate_plug_in_reminder_to_global(cfg)
        assert changed
        assert "executor" not in cfg
        assert "plug_in_reminder_minutes" not in cfg["ev_chargers"][0]

    def test_creates_notifications_block_and_ignores_invalid(self):
        from backend.config_migration import _migrate_plug_in_reminder_to_global

        cfg = {
            "ev_chargers": [
                {"id": "a", "plug_in_reminder_minutes": "soon"},
                {"id": "b", "plug_in_reminder_minutes": 30},
            ]
        }
        cfg, changed = _migrate_plug_in_reminder_to_global(cfg)
        assert changed
        assert cfg["executor"]["notifications"] == {
            "on_ev_plug_in_reminder": True,
            "ev_plug_in_reminder_minutes": 30,
        }

    def test_no_chargers_unchanged(self):
        from backend.config_migration import _migrate_plug_in_reminder_to_global

        assert _migrate_plug_in_reminder_to_global({"system": {}}) == ({"system": {}}, False)

    @pytest.mark.asyncio
    async def test_startup_migration_backs_up_and_survives_template_merge(
        self, tmp_path, monkeypatch
    ):
        from pathlib import Path

        import backend.config_migration as cm

        backup_dir = tmp_path / "backups"
        monkeypatch.setenv(cm.BACKUP_DIR_ENV, str(backup_dir))
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(
                {
                    "system": {"system_id": "t", "inverter_profile": "generic"},
                    "battery": {},
                    "executor": {"notifications": {"service": ""}},
                    "input_sensors": {},
                    "ev_chargers": [{"id": "ev1", "plug_in_reminder_minutes": 20}],
                }
            )
        )
        default_path = Path(__file__).resolve().parents[2] / "config.default.yaml"

        await cm.migrate_config(
            str(config_file), str(default_path), strict_validation=False
        )

        migrated = yaml.safe_load(config_file.read_text())
        notif = migrated["executor"]["notifications"]
        assert notif["on_ev_plug_in_reminder"] is True
        assert notif["ev_plug_in_reminder_minutes"] == 20
        assert "plug_in_reminder_minutes" not in migrated["ev_chargers"][0]
        assert list(backup_dir.glob("config.yaml_*.bak"))


class TestPlugInReminderValidation:
    @pytest.mark.parametrize("raw", [0, 1441, 12.5, "30", True])
    def test_invalid_lead_time_rejected(self, raw):
        from backend.api.routers.config import _validate_plug_in_reminder

        issues = _validate_plug_in_reminder(
            {"executor": {"notifications": {"ev_plug_in_reminder_minutes": raw}}}
        )
        assert issues and issues[0]["severity"] == "error"
        assert "ev_plug_in_reminder_minutes" in issues[0]["message"]

    @pytest.mark.parametrize("raw", [1, 15, 30, 1440, None])
    def test_valid_lead_time_accepted(self, raw):
        from backend.api.routers.config import _validate_plug_in_reminder

        assert (
            _validate_plug_in_reminder(
                {"executor": {"notifications": {"ev_plug_in_reminder_minutes": raw}}}
            )
            == []
        )
