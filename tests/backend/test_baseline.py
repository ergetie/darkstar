"""Without-Darkstar baseline: a plain self-use inverter replayed over recorded slots."""

import pytest

from backend.baseline import (
    BaselineBattery,
    BaselineSlot,
    simulate_self_use,
    simulate_self_use_with_end_state,
)

# 10 kWh battery, 10-100 % usable (1-10 kWh), 4 kW limits (1 kWh per 15-minute slot).
BATTERY = BaselineBattery(
    capacity_kwh=10.0,
    min_soc_percent=10.0,
    max_soc_percent=100.0,
    max_charge_w=4000.0,
    max_discharge_w=4000.0,
    charge_efficiency=1.0,
    discharge_efficiency=1.0,
)


def slot(pv=0.0, load=0.0, water=0.0, ev=0.0, soc_end=None) -> BaselineSlot:
    return BaselineSlot(
        pv_kwh=pv, load_kwh=load, water_kwh=water, ev_kwh=ev, soc_end_percent=soc_end
    )


def test_surplus_charges_battery_first():
    (flow,) = simulate_self_use([slot(pv=1.0, load=0.4)], BATTERY, prior_soc_percent=50.0)
    assert flow.charge_kwh == pytest.approx(0.6)
    assert flow.export_kwh == pytest.approx(0.0)
    assert flow.import_kwh == pytest.approx(0.0)


def test_demand_includes_water_and_ev():
    (flow,) = simulate_self_use(
        [slot(pv=1.0, load=0.2, water=0.3, ev=0.3)], BATTERY, prior_soc_percent=50.0
    )
    assert flow.charge_kwh == pytest.approx(0.2)


def test_surplus_beyond_room_is_exported():
    (flow,) = simulate_self_use([slot(pv=1.0)], BATTERY, prior_soc_percent=95.0)
    assert flow.charge_kwh == pytest.approx(0.5)
    assert flow.export_kwh == pytest.approx(0.5)


def test_surplus_beyond_charge_limit_is_exported():
    (flow,) = simulate_self_use([slot(pv=3.0)], BATTERY, prior_soc_percent=20.0)
    assert flow.charge_kwh == pytest.approx(1.0)
    assert flow.export_kwh == pytest.approx(2.0)


def test_deficit_covered_by_battery_then_imported():
    (flow,) = simulate_self_use([slot(load=1.5)], BATTERY, prior_soc_percent=50.0)
    assert flow.discharge_kwh == pytest.approx(1.0)
    assert flow.import_kwh == pytest.approx(0.5)
    assert flow.export_kwh == pytest.approx(0.0)


def test_deficit_limited_by_usable_energy():
    (flow,) = simulate_self_use([slot(load=1.0)], BATTERY, prior_soc_percent=15.0)
    assert flow.discharge_kwh == pytest.approx(0.5)
    assert flow.import_kwh == pytest.approx(0.5)


def test_empty_battery_imports_whole_deficit():
    (flow,) = simulate_self_use([slot(load=0.8)], BATTERY, prior_soc_percent=10.0)
    assert flow.discharge_kwh == pytest.approx(0.0)
    assert flow.import_kwh == pytest.approx(0.8)


def test_no_grid_charging_and_no_battery_export():
    flows = simulate_self_use([slot(), slot()], BATTERY, prior_soc_percent=50.0)
    assert all(f.charge_kwh == 0.0 and f.import_kwh == 0.0 and f.export_kwh == 0.0 for f in flows)
    assert all(f.discharge_kwh == 0.0 for f in flows)


def test_efficiencies_applied_to_stored_energy():
    battery = BaselineBattery(
        capacity_kwh=10.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_w=4000.0,
        max_discharge_w=4000.0,
        charge_efficiency=0.5,
        discharge_efficiency=0.5,
    )
    # 1.0 kWh AC stores 0.5 kWh; discharging 0.25 kWh AC then needs 0.5 kWh stored.
    flows = simulate_self_use(
        [slot(pv=1.0), slot(load=1.0), slot(load=1.0)], battery, prior_soc_percent=0.0
    )
    assert flows[0].charge_kwh == pytest.approx(1.0)
    assert flows[1].discharge_kwh == pytest.approx(0.25)
    assert flows[1].import_kwh == pytest.approx(0.75)
    assert flows[2].discharge_kwh == pytest.approx(0.0)


def test_efficiency_limits_charge_to_room():
    battery = BaselineBattery(
        capacity_kwh=10.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_w=40000.0,
        max_discharge_w=4000.0,
        charge_efficiency=0.5,
        discharge_efficiency=1.0,
    )
    # 1 kWh of room accepts 2 kWh AC at 50 % efficiency.
    (flow,) = simulate_self_use([slot(pv=5.0)], battery, prior_soc_percent=90.0)
    assert flow.charge_kwh == pytest.approx(2.0)
    assert flow.export_kwh == pytest.approx(3.0)


def test_default_efficiencies_are_095():
    battery = BaselineBattery(
        capacity_kwh=10.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_w=4000.0,
        max_discharge_w=4000.0,
    )
    assert battery.charge_efficiency == 0.95
    assert battery.discharge_efficiency == 0.95


def test_start_soc_from_previous_slot():
    (flow,) = simulate_self_use([slot(load=1.0, soc_end=90.0)], BATTERY, prior_soc_percent=60.0)
    assert flow.discharge_kwh == pytest.approx(1.0)
    # 60 % = 6 kWh with a 1 kWh floor leaves 5 kWh usable; the slot's own 90 % is ignored.
    flows = simulate_self_use([slot(load=1.0)] * 7, BATTERY, prior_soc_percent=60.0)
    assert sum(f.discharge_kwh for f in flows) == pytest.approx(5.0)


def test_start_soc_from_first_recorded_slot_in_period():
    slots = [slot(load=1.0)] * 2 + [slot(load=1.0, soc_end=30.0)]
    flows = simulate_self_use(slots, BATTERY)
    # Starts at 30 % = 3 kWh: 2 kWh usable above the 1 kWh floor.
    assert sum(f.discharge_kwh for f in flows) == pytest.approx(2.0)


def test_start_soc_falls_back_to_min():
    (flow,) = simulate_self_use([slot(load=1.0)], BATTERY)
    assert flow.discharge_kwh == pytest.approx(0.0)
    assert flow.import_kwh == pytest.approx(1.0)


def test_soc_carries_across_slots_and_ignores_recorded_soc():
    # Recorded SoC of 100 % in the second slot must not refill the simulated battery.
    slots = [slot(load=1.0), slot(load=1.0, soc_end=100.0)]
    flows = simulate_self_use(slots, BATTERY, prior_soc_percent=20.0)
    assert flows[0].discharge_kwh == pytest.approx(1.0)
    assert flows[1].discharge_kwh == pytest.approx(0.0)
    assert flows[1].import_kwh == pytest.approx(1.0)


def test_empty_slots():
    assert simulate_self_use([], BATTERY) == []


def test_missing_slot_leaves_soc_unchanged():
    # Slots absent from the recorded data are simply not in the list: the next slot
    # continues from the state the previous one left.
    flows = simulate_self_use([slot(pv=1.0), slot(load=0.5)], BATTERY, prior_soc_percent=10.0)
    assert flows[0].charge_kwh == pytest.approx(1.0)
    assert flows[1].discharge_kwh == pytest.approx(0.5)
    assert flows[1].import_kwh == pytest.approx(0.0)


def test_end_state_reports_final_simulated_soc():
    # 50 % of 10 kWh = 5 kWh; +0.6 kWh charged, then -1.0 kWh discharged -> 4.6 kWh = 46 %.
    result = simulate_self_use_with_end_state(
        [slot(pv=1.0, load=0.4), slot(load=1.0)], BATTERY, prior_soc_percent=50.0
    )
    assert result.end_soc_percent == pytest.approx(46.0)
    assert len(result.flows) == 2


def test_end_state_applies_efficiencies():
    battery = BaselineBattery(10.0, 10.0, 100.0, 4000.0, 4000.0, 0.9, 0.8)
    result = simulate_self_use_with_end_state([slot(pv=1.0)], battery, prior_soc_percent=50.0)
    assert result.end_soc_percent == pytest.approx(59.0)  # 5.0 + 1.0 * 0.9 kWh
    result = simulate_self_use_with_end_state([slot(load=0.8)], battery, prior_soc_percent=50.0)
    assert result.end_soc_percent == pytest.approx(40.0)  # 5.0 - 0.8 / 0.8 kWh


def test_end_state_without_slots_is_the_start_soc():
    result = simulate_self_use_with_end_state([], BATTERY, prior_soc_percent=60.0)
    assert result.flows == []
    assert result.end_soc_percent == pytest.approx(60.0)


def test_simulate_self_use_still_returns_only_flows():
    flows = simulate_self_use([slot(pv=1.0)], BATTERY, prior_soc_percent=50.0)
    assert isinstance(flows, list)
    assert flows[0].charge_kwh == pytest.approx(1.0)
