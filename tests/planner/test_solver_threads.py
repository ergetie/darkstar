"""kepler-multithread-solver: CBC thread resolution, passing and validation."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pulp
import pytest
import yaml

from backend.api.routers.config import _validate_config_for_save
from planner.solver import adapter
from planner.solver.adapter import (
    available_cpu_count,
    config_to_kepler_config,
    resolve_solver_threads,
)
from planner.solver.kepler import KeplerSolver
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


@pytest.fixture
def cgroup_files(tmp_path, monkeypatch):
    v2 = tmp_path / "cpu.max"
    q1 = tmp_path / "quota"
    p1 = tmp_path / "period"
    monkeypatch.setattr(adapter, "_CGROUP_V2_CPU_MAX", v2)
    monkeypatch.setattr(adapter, "_CGROUP_V1_QUOTA", q1)
    monkeypatch.setattr(adapter, "_CGROUP_V1_PERIOD", p1)
    return v2, q1, p1


class TestCpuDetection:
    def test_affinity_used(self, cgroup_files):
        with patch("os.sched_getaffinity", return_value={0, 1, 2, 3}):
            assert available_cpu_count() == 4

    def test_cpu_count_fallback(self, cgroup_files):
        with (
            patch("os.sched_getaffinity", side_effect=AttributeError),
            patch("os.cpu_count", return_value=3),
        ):
            assert available_cpu_count() == 3

    def test_unknown_cpu_count_is_one(self, cgroup_files):
        with (
            patch("os.sched_getaffinity", side_effect=OSError),
            patch("os.cpu_count", return_value=None),
        ):
            assert available_cpu_count() == 1

    def test_cgroup_v2_quota_caps_rounded_up(self, cgroup_files):
        cgroup_files[0].write_text("250000 100000\n")
        with patch("os.sched_getaffinity", return_value=set(range(8))):
            assert available_cpu_count() == 3

    def test_cgroup_v2_fractional_quota_min_one(self, cgroup_files):
        cgroup_files[0].write_text("50000 100000\n")
        with patch("os.sched_getaffinity", return_value=set(range(8))):
            assert available_cpu_count() == 1

    def test_cgroup_v2_max_is_no_cap(self, cgroup_files):
        cgroup_files[0].write_text("max 100000\n")
        with patch("os.sched_getaffinity", return_value=set(range(6))):
            assert available_cpu_count() == 6

    def test_quota_above_affinity_does_not_raise_count(self, cgroup_files):
        cgroup_files[0].write_text("800000 100000\n")
        with patch("os.sched_getaffinity", return_value={0, 1}):
            assert available_cpu_count() == 2

    def test_cgroup_v1_fallback(self, cgroup_files):
        cgroup_files[1].write_text("200000\n")
        cgroup_files[2].write_text("100000\n")
        with patch("os.sched_getaffinity", return_value=set(range(8))):
            assert available_cpu_count() == 2

    def test_cgroup_v1_unlimited(self, cgroup_files):
        cgroup_files[1].write_text("-1\n")
        cgroup_files[2].write_text("100000\n")
        with patch("os.sched_getaffinity", return_value=set(range(4))):
            assert available_cpu_count() == 4

    def test_unreadable_or_garbage_files_ignored(self, cgroup_files):
        cgroup_files[0].write_text("garbage\n")
        with patch("os.sched_getaffinity", return_value={0, 1, 2}):
            assert available_cpu_count() == 3
        # missing files (none created) are also fine
        cgroup_files[0].unlink()
        with patch("os.sched_getaffinity", return_value={0, 1, 2}):
            assert available_cpu_count() == 3


class TestResolveThreads:
    @pytest.fixture(autouse=True)
    def _four_cpus(self):
        with patch.object(adapter, "available_cpu_count", return_value=4):
            yield

    @pytest.mark.parametrize("raw", [None, 0, "0", 0.0])
    def test_auto(self, raw):
        section = {} if raw is None else {"solver_threads": raw}
        assert resolve_solver_threads(section) == 4

    @pytest.mark.parametrize(("raw", "expected"), [(1, 1), (2, 2), ("3", 3), (64, 64), (8.0, 8)])
    def test_explicit(self, raw, expected):
        assert resolve_solver_threads({"solver_threads": raw}) == expected

    @pytest.mark.parametrize("raw", [-1, 65, "abc", 2.5, True, []])
    def test_invalid_warns_and_uses_auto(self, raw, caplog):
        assert resolve_solver_threads({"solver_threads": raw}) == 4
        assert any("solver_threads" in m for m in caplog.messages)

    def test_reaches_kepler_config(self):
        planner_cfg = {
            "system": {"has_battery": False},
            "battery": {"capacity_kwh": 0},
            "kepler": {"solver_threads": 2},
        }
        assert config_to_kepler_config(planner_cfg).solver_threads == 2
        planner_cfg["kepler"] = {}
        assert config_to_kepler_config(planner_cfg).solver_threads == 4

    def test_dataclass_default_is_one(self):
        assert KeplerConfig.solver_threads == 1


class TestCbcInvocation:
    def test_threads_passed_to_cbc_and_glpk_unchanged(self):
        real_cbc = pulp.PULP_CBC_CMD
        seen: dict = {}
        glpk_kwargs: dict = {}

        def recording_cbc(**kwargs):
            seen.update(kwargs)
            return real_cbc(**kwargs)

        def failing_glpk(**kwargs):
            glpk_kwargs.update(kwargs)
            raise RuntimeError("no glpk")

        with (
            patch("planner.solver.kepler.pulp.GLPK_CMD", side_effect=failing_glpk),
            patch("planner.solver.kepler.pulp.PULP_CBC_CMD", side_effect=recording_cbc),
        ):
            result = KeplerSolver().solve(_input(), _config(solver_threads=3))

        assert seen["threads"] == 3
        assert seen["timeLimit"] == 90
        assert glpk_kwargs == {"msg": False, "timeLimit": 90}
        assert result.is_optimal

    def test_thread_count_logged(self, caplog):
        with (
            caplog.at_level("INFO", logger="darkstar.kepler"),
            patch("planner.solver.kepler.pulp.GLPK_CMD", side_effect=RuntimeError("no glpk")),
        ):
            KeplerSolver().solve(_input(), _config(solver_threads=2))
        assert any("2 thread" in m for m in caplog.messages)


class TestDefaultsAndValidation:
    def test_default_yaml(self):
        path = Path(__file__).parent.parent.parent / "config.default.yaml"
        with path.open() as f:
            cfg = yaml.safe_load(f)
        assert cfg["kepler"]["solver_threads"] == 0
        assert cfg["kepler"]["solver_time_limit_s"] == 90

    @pytest.mark.parametrize("value", [-1, 65, "abc", 2.5, True])
    def test_invalid_rejected(self, value):
        issues = _validate_config_for_save({"kepler": {"solver_threads": value}})
        errors = [i for i in issues if i["severity"] == "error"]
        assert any("kepler.solver_threads" in e["message"] for e in errors)

    @pytest.mark.parametrize("value", [0, 1, 6, 64])
    def test_valid_accepted(self, value):
        issues = _validate_config_for_save({"kepler": {"solver_threads": value}})
        assert not any("solver_threads" in i["message"] for i in issues)
