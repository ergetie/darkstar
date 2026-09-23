"""fix-ev-current-charger-control 6.4: configurable solver time limit + limit-hit flag."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pulp
import pytest
import yaml

from backend.api.routers.config import _validate_config_for_save
from planner.solver.adapter import config_to_kepler_config, resolve_solver_time_limit_s
from planner.solver.kepler import KeplerSolver, is_time_limit_hit
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


def _input() -> KeplerInput:
    start = datetime(2026, 9, 23, 10, 0)
    return KeplerInput(
        slots=[
            KeplerInputSlot(
                start_time=start + timedelta(hours=i),
                end_time=start + timedelta(hours=i + 1),
                load_kwh=0.5,
                pv_kwh=0.0,
                import_price_sek_kwh=1.0,
                export_price_sek_kwh=0.5,
            )
            for i in range(3)
        ],
        initial_soc_kwh=5.0,
    )


def _config(**overrides) -> KeplerConfig:
    params = {
        "capacity_kwh": 10.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "charge_efficiency": 1.0,
        "discharge_efficiency": 1.0,
        "min_soc_percent": 10.0,
        "max_soc_percent": 90.0,
        "wear_cost_sek_per_kwh": 0.01,
    }
    params.update(overrides)
    return KeplerConfig(**params)


class TestConfigPlumbing:
    def test_default_is_60_when_absent(self):
        assert resolve_solver_time_limit_s({}) == 60.0
        assert KeplerConfig.solver_time_limit_s == 60.0

    def test_configured_value_reaches_kepler_config(self):
        planner_cfg = {
            "system": {"has_battery": False},
            "battery": {"capacity_kwh": 0},
            "kepler": {"solver_time_limit_s": 120},
        }
        cfg = config_to_kepler_config(planner_cfg)
        assert cfg.solver_time_limit_s == 120.0

    def test_default_yaml_ships_60(self):
        path = Path(__file__).parent.parent.parent / "config.default.yaml"
        with path.open() as f:
            default_cfg = yaml.safe_load(f)
        assert default_cfg["kepler"]["solver_time_limit_s"] == 60

    @pytest.mark.parametrize(("raw", "expected"), [(5, 10.0), (900, 600.0), ("abc", 60.0)])
    def test_out_of_range_or_invalid_is_clamped(self, raw, expected):
        assert resolve_solver_time_limit_s({"solver_time_limit_s": raw}) == expected


class TestSaveValidation:
    @pytest.mark.parametrize("value", [5, 601, "abc"])
    def test_out_of_range_rejected(self, value):
        issues = _validate_config_for_save({"kepler": {"solver_time_limit_s": value}})
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("between 10 and 600" in e["message"] for e in errors)

    @pytest.mark.parametrize("value", [10, 60, 600])
    def test_in_range_accepted(self, value):
        issues = _validate_config_for_save({"kepler": {"solver_time_limit_s": value}})
        assert not any("solver_time_limit_s" in i["message"] for i in issues)


class TestTimeLimitDetection:
    def test_incumbent_at_limit_counts_as_hit(self):
        assert is_time_limit_hit(60.1, 60.0) is True
        assert is_time_limit_hit(59.6, 60.0) is True
        assert is_time_limit_hit(30.1, 60.0) is False

    def test_configured_limit_passed_to_solver(self):
        real_cbc = pulp.PULP_CBC_CMD
        seen: dict = {}

        def recording_cbc(**kwargs):
            seen.update(kwargs)
            return real_cbc(**kwargs)

        with (
            patch("planner.solver.kepler.pulp.GLPK_CMD", side_effect=RuntimeError("no glpk")),
            patch("planner.solver.kepler.pulp.PULP_CBC_CMD", side_effect=recording_cbc),
        ):
            result = KeplerSolver().solve(_input(), _config(solver_time_limit_s=45))

        assert seen["timeLimit"] == 45
        assert result.is_optimal
        assert result.time_limit_hit is False

    def test_optimal_solve_at_limit_warns_and_flags(self, caplog):
        # CBC reports "Optimal" for its incumbent when it stops at the limit
        with (
            caplog.at_level(logging.WARNING, logger="darkstar.kepler"),
            patch("planner.solver.kepler.is_time_limit_hit", return_value=True),
        ):
            result = KeplerSolver().solve(_input(), _config(solver_time_limit_s=60))

        assert result.status_msg == "Optimal"
        assert result.time_limit_hit is True
        assert any("time limit" in m for m in caplog.messages)
