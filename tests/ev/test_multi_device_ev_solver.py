"""
Task 3.10: Multi-device EV solver tests.

Covers:
- Single charger equivalence with old scalar approach
- Two chargers with different deadlines
- Two chargers exceeding grid limit get staggered
- Unplugged charger gets no variables / no charging
- No chargers equals no EV constraints
"""

from datetime import datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)


def _slots(n=4, import_price=1.0, export_price=0.5, load_kwh=0.0, pv_kwh=0.0, start_hour=0):
    tz = pytz_timezone("Europe/Stockholm")
    base = tz.localize(datetime(2026, 1, 15, start_hour, 0))
    result = []
    for i in range(n):
        s = base + timedelta(hours=i)
        result.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(hours=1),
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                import_price_sek_kwh=import_price,
                export_price_sek_kwh=export_price,
            )
        )
    return result


def _ev(
    ev_id="ev1",
    max_power_kw=7.4,
    battery_capacity_kwh=100.0,
    soc_percent=50.0,
    plugged_in=True,
    deadline=None,
    required_kwh=None,
) -> EVChargerInput:
    if required_kwh is None:
        # Default soft target: charge to 100% SoC by the deadline
        required_kwh = battery_capacity_kwh * (1.0 - soc_percent / 100.0)
    return EVChargerInput(
        id=ev_id,
        max_power_kw=max_power_kw,
        battery_capacity_kwh=battery_capacity_kwh,
        current_soc_percent=soc_percent,
        plugged_in=plugged_in,
        deadline=deadline,
        required_kwh=required_kwh,
    )


def _config(ev_chargers, import_limit=None):
    kwargs = {
        "capacity_kwh": 10.0,
        "min_soc_percent": 10.0,
        "max_soc_percent": 100.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "charge_efficiency": 1.0,
        "discharge_efficiency": 1.0,
        "wear_cost_sek_per_kwh": 0.0,
        "ev_chargers": ev_chargers,
    }
    if import_limit is not None:
        kwargs["grid_import_limit_kw"] = import_limit
    return KeplerConfig(**kwargs)


class TestSingleChargerEquivalence:
    """Single charger produces same result as before multi-device refactor."""

    def test_single_charger_charges_to_meet_target(self):
        """EV with a soft target charges to meet it when price is below shortfall penalty."""
        solver = KeplerSolver()
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        cfg = _config([_ev(max_power_kw=7.4, soc_percent=50.0)])

        result = solver.solve(inp, cfg)

        total_ev = sum(s.ev_charge_kw for s in result.slots)
        assert total_ev > 0, "EV should charge when incentive > price"

    def test_ev_with_no_target_does_not_charge(self):
        """EV without a required-kWh target does not charge even when grid is cheap."""
        solver = KeplerSolver()
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        cfg = _config([_ev(required_kwh=0.0)])

        result = solver.solve(inp, cfg)

        total_ev = sum(s.ev_charge_kw for s in result.slots)
        assert total_ev < 0.1, "EV should not charge when it has no energy target"

    def test_per_device_results_match_aggregate(self):
        """ev_charger_results['ev1'] should match ev_charge_kw for single charger."""
        solver = KeplerSolver()
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        cfg = _config([_ev(ev_id="ev1")])

        result = solver.solve(inp, cfg)

        for slot in result.slots:
            per_device = slot.ev_charger_results.get("ev1", 0.0)
            assert abs(per_device - slot.ev_charge_kw) < 0.01, (
                f"Per-device result ({per_device}) should match aggregate ({slot.ev_charge_kw})"
            )


class TestTwoChargersWithDifferentDeadlines:
    """Two EVs with non-overlapping deadlines charge in the right slots."""

    def test_each_charger_respects_its_own_deadline(self):
        """EV1 deadline at slot 2, EV2 deadline at slot 4 — EV1 only charges in slots 0-1."""
        tz = pytz_timezone("Europe/Stockholm")
        base = tz.localize(datetime(2026, 1, 15, 0, 0))
        deadline_ev1 = base + timedelta(hours=2)
        deadline_ev2 = base + timedelta(hours=4)

        solver = KeplerSolver()
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        cfg = _config(
            [
                _ev(ev_id="ev1", deadline=deadline_ev1, soc_percent=0.0),
                _ev(ev_id="ev2", deadline=deadline_ev2, soc_percent=0.0),
            ]
        )

        result = solver.solve(inp, cfg)

        # EV1 must not charge after its deadline (slot index >= 2)
        ev1_post = sum(result.slots[i].ev_charger_results.get("ev1", 0.0) for i in range(2, 4))
        assert ev1_post < 0.01, f"EV1 should not charge after deadline, got {ev1_post}"

        # EV1 should charge before its deadline
        ev1_pre = sum(result.slots[i].ev_charger_results.get("ev1", 0.0) for i in range(2))
        assert ev1_pre > 0, "EV1 should charge before deadline"

    def test_no_cross_contamination_of_deadlines(self):
        """EV2 without deadline charges freely even after EV1's deadline."""
        tz = pytz_timezone("Europe/Stockholm")
        base = tz.localize(datetime(2026, 1, 15, 0, 0))
        deadline_ev1 = base + timedelta(hours=1)

        solver = KeplerSolver()
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        cfg = _config(
            [
                _ev(ev_id="ev1", deadline=deadline_ev1, max_power_kw=3.0, soc_percent=0.0),
                _ev(ev_id="ev2", deadline=None, max_power_kw=3.0, soc_percent=0.0),
            ]
        )

        result = solver.solve(inp, cfg)

        # EV2 has no deadline — it should be able to charge in any slot
        ev2_total = sum(result.slots[i].ev_charger_results.get("ev2", 0.0) for i in range(4))
        assert ev2_total > 0, "EV2 with no deadline should charge"

        # EV1 after slot 0 (deadline = 1h mark = end of slot 0) must be 0
        ev1_post = sum(result.slots[i].ev_charger_results.get("ev1", 0.0) for i in range(1, 4))
        assert ev1_post < 0.01, f"EV1 must not charge after its deadline, got {ev1_post}"


class TestTwoChargersGridLimit:
    """Two chargers that together would exceed the grid import limit get staggered."""

    def test_combined_ev_power_respects_grid_limit(self):
        """Two 7.4 kW chargers with 8 kW grid limit — total EV kW never exceeds 8."""
        solver = KeplerSolver()
        # No battery, no load, 8 kW grid limit
        cfg = KeplerConfig(
            capacity_kwh=0.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            max_charge_power_kw=0.0,
            max_discharge_power_kw=0.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            wear_cost_sek_per_kwh=0.0,
            grid_import_limit_kw=8.0,
            ev_chargers=[
                _ev(ev_id="ev1", max_power_kw=7.4, soc_percent=0.0),
                _ev(ev_id="ev2", max_power_kw=7.4, soc_percent=0.0),
            ],
        )
        slots = _slots(n=4, import_price=1.0, load_kwh=0.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=0.0)

        result = solver.solve(inp, cfg)

        for i, slot in enumerate(result.slots):
            ev1 = slot.ev_charger_results.get("ev1", 0.0)
            ev2 = slot.ev_charger_results.get("ev2", 0.0)
            total = ev1 + ev2
            assert total <= 8.0 + 0.1, (
                f"Slot {i}: combined EV power {total:.2f} kW exceeds 8 kW grid limit"
            )

    def test_total_ev_energy_delivered_despite_limit(self):
        """Both chargers get some energy over 4 slots even with grid limit."""
        solver = KeplerSolver()
        cfg = KeplerConfig(
            capacity_kwh=0.0,
            min_soc_percent=0.0,
            max_soc_percent=100.0,
            max_charge_power_kw=0.0,
            max_discharge_power_kw=0.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            wear_cost_sek_per_kwh=0.0,
            grid_import_limit_kw=8.0,
            ev_chargers=[
                _ev(ev_id="ev1", max_power_kw=7.4, soc_percent=0.0),
                _ev(ev_id="ev2", max_power_kw=7.4, soc_percent=0.0),
            ],
        )
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=0.0)

        result = solver.solve(inp, cfg)

        ev1_total = sum(s.ev_charger_results.get("ev1", 0.0) for s in result.slots)
        ev2_total = sum(s.ev_charger_results.get("ev2", 0.0) for s in result.slots)
        assert ev1_total > 0, "EV1 should receive some energy"
        assert ev2_total > 0, "EV2 should receive some energy"


class TestUnpluggedCharger:
    """Unplugged charger gets no charging variables / zero kW."""

    def test_unplugged_charger_gets_zero_power(self):
        """Unplugged EV should never appear in results."""
        solver = KeplerSolver()
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        cfg = _config(
            [
                _ev(ev_id="ev1", plugged_in=True, soc_percent=0.0),
                _ev(ev_id="ev2", plugged_in=False, soc_percent=0.0),
            ]
        )

        result = solver.solve(inp, cfg)

        for slot in result.slots:
            ev2 = slot.ev_charger_results.get("ev2", 0.0)
            assert ev2 < 0.01, f"Unplugged EV2 should not charge, got {ev2}"

    def test_plugged_in_charger_still_charges_despite_unplugged_sibling(self):
        """Plugged-in EV charges normally when sibling is unplugged."""
        solver = KeplerSolver()
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        cfg = _config(
            [
                _ev(ev_id="ev1", plugged_in=True, soc_percent=0.0),
                _ev(ev_id="ev2", plugged_in=False, soc_percent=0.0),
            ]
        )

        result = solver.solve(inp, cfg)

        ev1_total = sum(s.ev_charger_results.get("ev1", 0.0) for s in result.slots)
        assert ev1_total > 0, "Plugged-in EV1 should charge"


class TestNoChargers:
    """When ev_chargers list is empty, no EV constraints are added."""

    def test_no_ev_charging_when_no_chargers(self):
        """Empty ev_chargers list → ev_charge_kw always 0."""
        solver = KeplerSolver()
        slots = _slots(n=4, import_price=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=5.0)
        cfg = _config([])

        result = solver.solve(inp, cfg)

        for slot in result.slots:
            assert slot.ev_charge_kw == pytest.approx(0.0, abs=0.01)
            assert slot.ev_charger_results == {}

    def test_battery_operates_normally_without_ev(self):
        """Battery discharges to serve load with no EV chargers configured."""
        solver = KeplerSolver()
        # High import price + load — battery should discharge to serve load
        slots = _slots(n=4, import_price=5.0, export_price=0.0, load_kwh=1.0)
        inp = KeplerInput(slots=slots, initial_soc_kwh=9.0)
        cfg = _config([])

        result = solver.solve(inp, cfg)

        total_discharge = sum(s.discharge_kwh for s in result.slots)
        assert total_discharge > 0, "Battery should discharge to serve load with no EV"
