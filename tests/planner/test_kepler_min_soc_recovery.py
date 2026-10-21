"""min-soc-floor-tracking: Kepler below-minimum recovery window (min-soc-recovery spec)."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pulp
import pytest

from planner.solver.kepler import (
    MIN_SOC_RECOVERY_HOURS,
    KeplerSolver,
    min_soc_floor_kwh,
)
from planner.solver.types import (
    KeplerBenchmark,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
    KeplerResult,
)

CAPACITY = 19.2
MIN_SOC = 12.0
MIN_KWH = CAPACITY * MIN_SOC / 100.0  # 2.304
EPS = 1e-6
START = datetime(2026, 10, 21, 0, 0)
SLOTS_PER_HOUR = 4


def _pct(percent: float) -> float:
    return CAPACITY * percent / 100.0


def _slots(prices: list[float], load_kwh: float = 0.1) -> list[KeplerInputSlot]:
    return [
        KeplerInputSlot(
            start_time=START + timedelta(minutes=15 * i),
            end_time=START + timedelta(minutes=15 * (i + 1)),
            load_kwh=load_kwh,
            pv_kwh=0.0,
            import_price_sek_kwh=price,
            export_price_sek_kwh=0.0,
        )
        for i, price in enumerate(prices)
    ]


def _hourly_prices(per_hour: list[float]) -> list[float]:
    return [p for p in per_hour for _ in range(SLOTS_PER_HOUR)]


# Expensive for 3 h, cheap from hour 3 to hour 4, expensive again until hour 8.
DRIFT_PRICES = _hourly_prices([3.0, 3.0, 3.0, 0.5, 3.0, 3.0, 3.0, 3.0])


def _config(**kwargs: Any) -> KeplerConfig:
    defaults: dict[str, Any] = {
        "capacity_kwh": CAPACITY,
        "min_soc_percent": MIN_SOC,
        "max_soc_percent": 100.0,
        "max_charge_power_kw": 10.0,
        "max_discharge_power_kw": 10.0,
        "charge_efficiency": 0.95,
        "discharge_efficiency": 0.95,
        "wear_cost_sek_per_kwh": 0.1,
        "target_soc_kwh": None,
    }
    defaults.update(kwargs)
    return KeplerConfig(**defaults)


@pytest.fixture
def solved_problem(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """Capture the solved pulp problem so slack variables can be inspected."""
    captured: list[Any] = []
    original = pulp.LpProblem.solve

    def solve(self: Any, *args: Any, **kwargs: Any) -> Any:
        captured.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pulp.LpProblem, "solve", solve)
    yield captured


def _var(problem: Any, name: str) -> float:
    value = problem.variablesDict()[name].varValue
    return float(value or 0.0)


def _states(result: KeplerResult, initial_kwh: float) -> list[float]:
    """SoC states 0..T (slot t reports the state at its end, t + 1)."""
    return [initial_kwh] + [s.soc_kwh for s in result.slots]


def _window_end_state() -> int:
    return int(MIN_SOC_RECOVERY_HOURS * SLOTS_PER_HOUR)


class TestFloorHelper:
    def test_window_uses_initial_then_min(self):
        hours = [0.25] * 32
        floors = min_soc_floor_kwh(hours, _pct(11), MIN_KWH, CAPACITY, recovery_enabled=True)
        window_end = _window_end_state()
        assert floors[:window_end] == [_pct(11)] * window_end
        assert floors[window_end:] == [MIN_KWH] * (len(hours) + 1 - window_end)

    def test_at_or_above_min_is_unchanged(self):
        hours = [0.25] * 32
        for initial in (MIN_KWH, _pct(50)):
            floors = min_soc_floor_kwh(hours, initial, MIN_KWH, CAPACITY, recovery_enabled=True)
            assert floors == [MIN_KWH] * 33

    def test_exactly_five_points_below_uses_window(self):
        floors = min_soc_floor_kwh(
            [0.25] * 8, _pct(7), MIN_KWH, CAPACITY, recovery_enabled=True
        )
        assert floors[0] == _pct(7)
        assert floors[-1] == MIN_KWH

    def test_deep_deficit_has_no_window(self):
        floors = min_soc_floor_kwh(
            [0.25] * 8, _pct(6), MIN_KWH, CAPACITY, recovery_enabled=True
        )
        assert floors == [MIN_KWH] * 9

    def test_disabled_for_benchmark(self):
        floors = min_soc_floor_kwh(
            [0.25] * 8, _pct(11), MIN_KWH, CAPACITY, recovery_enabled=False
        )
        assert floors == [MIN_KWH] * 9

    def test_short_horizon_terminal_uses_min(self):
        floors = min_soc_floor_kwh(
            [0.25] * 16, _pct(11), MIN_KWH, CAPACITY, recovery_enabled=True
        )
        assert floors[:16] == [_pct(11)] * 16
        assert floors[16] == MIN_KWH


class TestRecoveryWindow:
    def test_drift_refilled_at_cheaper_slot(self, solved_problem):
        initial = _pct(11)
        result = KeplerSolver().solve(KeplerInput(_slots(DRIFT_PRICES), initial), _config())
        assert result.is_optimal

        # No grid charging in the first 3 hours.
        for slot in result.slots[: 3 * SLOTS_PER_HOUR]:
            assert slot.charge_kwh < EPS

        states = _states(result, initial)
        assert min(states) >= initial - EPS
        for state in states[_window_end_state() :]:
            assert state >= MIN_KWH - EPS

        problem = solved_problem[-1]
        for k in range(len(states)):
            assert _var(problem, f"soc_violation_kwh_{k}") == pytest.approx(0.0, abs=EPS)

    def test_deadline_enforced_at_flat_price(self, solved_problem):
        initial = _pct(11)
        prices = [1.0] * (8 * SLOTS_PER_HOUR)
        result = KeplerSolver().solve(KeplerInput(_slots(prices), initial), _config())
        assert result.is_optimal

        states = _states(result, initial)
        assert states[_window_end_state()] >= MIN_KWH - EPS
        problem = solved_problem[-1]
        for k in range(len(states)):
            assert _var(problem, f"soc_violation_kwh_{k}") == pytest.approx(0.0, abs=EPS)

    def test_exactly_five_points_below_waits_for_cheap_slot(self):
        initial = _pct(7)
        result = KeplerSolver().solve(KeplerInput(_slots(DRIFT_PRICES), initial), _config())
        assert result.is_optimal
        for slot in result.slots[: 3 * SLOTS_PER_HOUR]:
            assert slot.charge_kwh < EPS
        states = _states(result, initial)
        assert min(states) >= initial - EPS
        assert states[_window_end_state()] >= MIN_KWH - EPS

    def test_horizon_shorter_than_window_holds_terminal(self, solved_problem):
        initial = _pct(11)
        prices = [3.0] * (4 * SLOTS_PER_HOUR)
        result = KeplerSolver().solve(KeplerInput(_slots(prices), initial), _config())
        assert result.is_optimal
        states = _states(result, initial)
        assert states[-1] >= MIN_KWH - EPS
        assert _var(solved_problem[-1], f"soc_violation_kwh_{len(states) - 1}") == (
            pytest.approx(0.0, abs=EPS)
        )

    def test_at_minimum_keeps_min_bound(self):
        initial = MIN_KWH
        result = KeplerSolver().solve(KeplerInput(_slots(DRIFT_PRICES), initial), _config())
        assert result.is_optimal
        assert min(_states(result, initial)) >= MIN_KWH - EPS


class TestDeepDeficit:
    def test_six_points_below_charges_in_first_slot(self):
        initial = _pct(6)
        result = KeplerSolver().solve(KeplerInput(_slots(DRIFT_PRICES), initial), _config())
        assert result.is_optimal
        assert result.slots[0].charge_kwh > EPS
        assert result.slots[0].soc_kwh >= MIN_KWH - EPS


class TestExportFloorRecovery:
    def test_no_export_floor_violation_inside_window(self, solved_problem):
        initial = _pct(11)
        config = _config(
            enable_export=True,
            export_floor_soc_percent=20.0,
            max_export_power_kw=10.0,
        )
        result = KeplerSolver().solve(KeplerInput(_slots(DRIFT_PRICES), initial), config)
        assert result.is_optimal

        problem = solved_problem[-1]
        window_slots = _window_end_state() - 1  # slot t constrains state t + 1
        for t in range(window_slots):
            assert result.slots[t].grid_export_kwh < EPS
            assert _var(problem, f"export_floor_violation_kwh_{t}") == (
                pytest.approx(0.0, abs=EPS)
            )
        # Charging stays deferred to the cheap hour, not forced by the export floor.
        for slot in result.slots[: 3 * SLOTS_PER_HOUR]:
            assert slot.charge_kwh < EPS


class TestBenchmarkUnaffected:
    def test_benchmark_keeps_relaxed_bound_after_window(self):
        # Hourly slots over 8 h: hour 6 is expensive, hour 7 is cheap. The optimum
        # discharges in hour 6 down to the lower bound and refills in hour 7, so the
        # state after hour 6 (past the 6 h window) shows the bound in force.
        initial = _pct(10)
        slots = [
            KeplerInputSlot(
                start_time=START + timedelta(hours=h),
                end_time=START + timedelta(hours=h + 1),
                load_kwh=1.0,
                pv_kwh=0.0,
                import_price_sek_kwh=price,
                export_price_sek_kwh=0.0,
            )
            for h, price in enumerate([1.0] * 6 + [5.0, 0.1])
        ]
        bench = KeplerBenchmark(terminal_soc_kwh=MIN_KWH, no_discharge_slots=[False] * 8)
        result = KeplerSolver().solve(
            KeplerInput(slots, initial, benchmark=bench),
            _config(charge_efficiency=1.0, discharge_efficiency=1.0, wear_cost_sek_per_kwh=0.0),
        )
        assert result.is_optimal
        assert min(s.soc_kwh for s in result.slots) >= initial - EPS
        assert result.slots[6].soc_kwh == pytest.approx(initial, abs=1e-4)
        assert result.slots[-1].soc_kwh == pytest.approx(MIN_KWH, abs=1e-4)
