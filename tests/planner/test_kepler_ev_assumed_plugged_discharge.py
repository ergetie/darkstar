"""Assumed-plugged (away) chargers must not block battery discharge (ev-car-away)."""

from __future__ import annotations

from datetime import datetime, timedelta

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
    KeplerResult,
)

START = datetime(2026, 9, 25, 22, 0)
N_SLOTS = 8
# The EV has to charge inside the expensive window (deadline at slot 4).
DEADLINE = START + timedelta(minutes=15 * 4)


def _slots() -> list[KeplerInputSlot]:
    return [
        KeplerInputSlot(
            start_time=START + timedelta(minutes=15 * i),
            end_time=START + timedelta(minutes=15 * (i + 1)),
            load_kwh=1.0,
            pv_kwh=0.0,
            import_price_sek_kwh=5.0 if i < 4 else 1.0,
            export_price_sek_kwh=0.0,
        )
        for i in range(N_SLOTS)
    ]


def _config(chargers: list[EVChargerInput]) -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        wear_cost_sek_per_kwh=0.1,
        max_import_power_kw=25.0,
        ev_chargers=chargers,
    )


def _charger(
    cid: str, *, plugged: bool, assumed: bool, deadline: datetime = DEADLINE
) -> EVChargerInput:
    return EVChargerInput(
        id=cid,
        max_power_kw=11.0,
        battery_capacity_kwh=60.0,
        current_soc_percent=50.0,
        plugged_in=plugged,
        assumed_plugged=assumed,
        deadline=deadline,
        required_kwh=5.0,
        control_type="current",
        min_power_kw=4.2,
    )


def _solve(chargers: list[EVChargerInput]) -> KeplerResult:
    return KeplerSolver().solve(
        KeplerInput(slots=_slots(), initial_soc_kwh=10.0), _config(chargers)
    )


def _ev_slots(result: KeplerResult, cid: str) -> list[int]:
    return [
        i for i, s in enumerate(result.slots) if s.ev_charger_results.get(cid, 0.0) > 0.1
    ]


def test_assumed_plugged_does_not_block_discharge():
    baseline = _solve([])
    result = _solve([_charger("ev1", plugged=False, assumed=True)])
    ev_slots = _ev_slots(result, "ev1")
    assert ev_slots
    assert all(result.slots[i].discharge_kwh > 0.1 for i in ev_slots)
    for base, got in zip(baseline.slots, result.slots, strict=True):
        assert abs(base.discharge_kwh - got.discharge_kwh) < 1e-4
        assert abs(base.charge_kwh - got.charge_kwh) < 1e-4


def test_plugged_charger_still_blocks_discharge():
    result = _solve([_charger("ev1", plugged=True, assumed=False)])
    ev_slots = _ev_slots(result, "ev1")
    assert ev_slots
    assert all(result.slots[i].discharge_kwh < 1e-6 for i in ev_slots)


def test_mixed_blocks_only_in_plugged_charger_slots():
    result = _solve(
        [
            _charger("ev1", plugged=True, assumed=False, deadline=START + timedelta(minutes=30)),
            _charger("ev2", plugged=False, assumed=True),
        ]
    )
    plugged_slots = set(_ev_slots(result, "ev1"))
    assumed_only = set(_ev_slots(result, "ev2")) - plugged_slots
    assert plugged_slots
    assert all(result.slots[i].discharge_kwh < 1e-6 for i in plugged_slots)
    assert assumed_only
    assert any(result.slots[i].discharge_kwh > 0.1 for i in assumed_only)


def test_charger_without_plug_sensor_still_blocks():
    # No plug sensor is reported as plugged_in=True (ev-live-state), never assumed.
    result = _solve([_charger("ev1", plugged=True, assumed=False)])
    assert _ev_slots(result, "ev1")
    assert all(
        result.slots[i].discharge_kwh < 1e-6 for i in _ev_slots(result, "ev1")
    )


def test_only_assumed_adds_no_discharge_constraint():
    import pulp

    seen: list[str] = []
    orig = pulp.LpProblem.solve

    def spy(self, *a, **k):  # type: ignore[no-untyped-def]
        seen.extend(v.name for v in self.variables())
        return orig(self, *a, **k)

    pulp.LpProblem.solve = spy  # type: ignore[method-assign]
    try:
        _solve([_charger("ev1", plugged=False, assumed=True)])
    finally:
        pulp.LpProblem.solve = orig  # type: ignore[method-assign]
    assert seen
    assert not any(n.startswith("any_ev_charging") for n in seen)
