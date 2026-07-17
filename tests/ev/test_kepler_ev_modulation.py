import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path.cwd()))

from executor.load_balancer import planned_kw_to_amps
from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)

MIN_CURRENT_A = 6
PHASE_COUNT = 3
# Mirrors planner/solver/adapter.py's derive_min_power_kw for a 3-phase,
# min_current_a=6 current-type charger.
MIN_POWER_KW = MIN_CURRENT_A * 230 * PHASE_COUNT / 1000 * 1.01


def _ev(
    max_power_kw=7.4,
    battery_capacity_kwh=100.0,
    soc_percent=50.0,
    plugged_in=True,
    deadline=None,
    required_kwh=None,
    control_type="binary",
    min_power_kw=0.0,
) -> EVChargerInput:
    if required_kwh is None:
        required_kwh = battery_capacity_kwh * (1.0 - soc_percent / 100.0)
    return EVChargerInput(
        id="test_ev",
        max_power_kw=max_power_kw,
        battery_capacity_kwh=battery_capacity_kwh,
        current_soc_percent=soc_percent,
        plugged_in=plugged_in,
        deadline=deadline,
        required_kwh=required_kwh,
        control_type=control_type,
        min_power_kw=min_power_kw,
    )


def _slots_15min(n, price=0.1, load_kwh=0.0, pv_kwh=0.0, start=None):
    if start is None:
        start = datetime(2026, 1, 1, 0, 0)
    out = []
    for i in range(n):
        s = start + timedelta(minutes=15 * i)
        out.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(minutes=15),
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                import_price_sek_kwh=price,
                export_price_sek_kwh=0.0,
            )
        )
    return out


def test_ev_modulation():
    print("\n--- Testing EV Modulation (Grid Limit - Now Binary Blocked) ---")
    solver = KeplerSolver()

    config = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        grid_import_limit_kw=5.0,
        ev_chargers=[
            _ev(
                max_power_kw=7.4,
                battery_capacity_kwh=100.0,
                soc_percent=50.0,
                deadline=datetime(2026, 1, 1, 1, 0),
                required_kwh=50.0,
            )
        ],
    )

    slots = [
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 0, 0),
            end_time=datetime(2026, 1, 1, 1, 0),
            load_kwh=3.0,
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=1.0,
        )
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    result = solver.solve(input_data, config)

    print(f"Status: {result.status_msg}")
    print(f"EV Charge Power: {result.slots[0].ev_charge_kw} kW")
    print(f"Grid Import: {result.slots[0].grid_import_kwh} kWh (per 1h)")

    assert abs(result.slots[0].ev_charge_kw - 0.0) < 0.1
    print("Modulation binary block test SUCCESS")


def test_ev_economic_stop():
    print("\n--- Testing EV Economic Stop (Price Guard) ---")
    solver = KeplerSolver()

    config = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[_ev(required_kwh=0.0)],
    )

    slots = [
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 0, 0),
            end_time=datetime(2026, 1, 1, 1, 0),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=3.0,
            export_price_sek_kwh=0.5,
        )
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    result = solver.solve(input_data, config)

    print(f"EV Charge Power: {result.slots[0].ev_charge_kw} kW")
    assert result.slots[0].ev_charge_kw < 0.01
    print("Economic stop test SUCCESS")


def test_deferral_to_cheaper_slots():
    print("\n--- Testing EV Deferral to Cheaper Slots ---")
    solver = KeplerSolver()

    # 70 kWh soft target can be met entirely in the two cheapest slots,
    # so the solver should avoid the expensive first slot.
    config = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=100.0,
        max_discharge_power_kw=100.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[
            _ev(
                max_power_kw=30.0,
                battery_capacity_kwh=100.0,
                soc_percent=30.0,
                deadline=datetime(2026, 1, 1, 3, 0),
                required_kwh=60.0,
            )
        ],
    )

    slots = [
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 0, 0),
            end_time=datetime(2026, 1, 1, 1, 0),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=5.0,
            export_price_sek_kwh=0.0,
        ),
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 1, 0),
            end_time=datetime(2026, 1, 1, 2, 0),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.0,
        ),
        KeplerInputSlot(
            start_time=datetime(2026, 1, 1, 2, 0),
            end_time=datetime(2026, 1, 1, 3, 0),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=0.1,
            export_price_sek_kwh=0.0,
        ),
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)

    result = solver.solve(input_data, config)

    print(f"Slot 0 (Price 5.0): {result.slots[0].ev_charge_kw} kW")
    print(f"Slot 1 (Price 1.0): {result.slots[1].ev_charge_kw} kW")
    print(f"Slot 2 (Price 0.1): {result.slots[2].ev_charge_kw} kW")

    assert abs(result.slots[0].ev_charge_kw - 0.0) < 0.1
    assert abs(result.slots[1].ev_charge_kw - 30.0) < 0.1
    assert abs(result.slots[2].ev_charge_kw - 30.0) < 0.1
    print("Deferral to cheaper slots test SUCCESS")


def test_current_type_charger_planned_at_fractional_power():
    """Spec scenario: current-type charger is planned at fractional power."""
    solver = KeplerSolver()
    slots = _slots_15min(8, price=0.1)
    ev = _ev(
        max_power_kw=11.0,
        required_kwh=2.6,
        deadline=slots[-1].end_time,
        control_type="current",
        min_power_kw=MIN_POWER_KW,
    )
    config = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[ev],
    )
    result = solver.solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), config)
    assert result.is_optimal

    active_kw = [kw for kw in (s.ev_charger_results.get("test_ev", 0.0) for s in result.slots) if kw > 0.01]
    total_kwh = sum(s.ev_charger_results.get("test_ev", 0.0) * 0.25 for s in result.slots)

    assert active_kw, "expected at least one slot with nonzero EV charging"
    for kw in active_kw:
        assert kw >= MIN_POWER_KW - 0.01, f"slot power {kw} below derived min_power_kw"
        assert kw <= 11.0 + 0.01
    # Delivered close to the requirement, not rounded up to a full-power block.
    assert total_kwh >= 2.6 - 0.01
    assert total_kwh < 2.75, "should not be forced into a full 11kW*0.25h block"
    assert any(kw < 11.0 - 0.01 for kw in active_kw), "expected genuinely fractional (sub-max) power"


def test_current_type_charger_never_below_min_amps():
    """Spec scenario: current-type charger never planned below its minimum amps."""
    solver = KeplerSolver()
    slots = _slots_15min(8, price=0.1)
    ev = _ev(
        max_power_kw=11.0,
        required_kwh=2.6,
        deadline=slots[-1].end_time,
        control_type="current",
        min_power_kw=MIN_POWER_KW,
    )
    config = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[ev],
    )
    result = solver.solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), config)
    assert result.is_optimal

    for s in result.slots:
        kw = s.ev_charger_results.get("test_ev", 0.0)
        if kw <= 0.01:
            continue
        amps = planned_kw_to_amps(kw, PHASE_COUNT, MIN_CURRENT_A, max_current_a=16)
        assert amps is not None, f"planned {kw}kW rounded below min_current_a — would pause"
        assert amps >= MIN_CURRENT_A


def test_binary_charger_keeps_full_power_or_off_planning():
    """Spec scenario: binary charger keeps full-power-or-off planning."""
    solver = KeplerSolver()
    slots = _slots_15min(4, price=0.1)
    ev = _ev(
        max_power_kw=7.4,
        required_kwh=3.0,
        deadline=slots[-1].end_time,
        control_type="binary",
    )
    config = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[ev],
    )
    result = solver.solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), config)
    assert result.is_optimal

    full_block_kwh = 7.4 * 0.25
    scheduled = False
    for s in result.slots:
        energy_kwh = s.ev_charger_results.get("test_ev", 0.0) * 0.25
        assert energy_kwh < 0.01 or abs(energy_kwh - full_block_kwh) < 0.01
        if energy_kwh > 0.01:
            scheduled = True
    assert scheduled, "expected at least one full-power slot to be scheduled"


def test_fractional_charging_still_blocks_battery_discharge():
    """Spec scenario: fractional charging still blocks battery discharge."""
    solver = KeplerSolver()
    slot = KeplerInputSlot(
        start_time=datetime(2026, 1, 1, 0, 0),
        end_time=datetime(2026, 1, 1, 0, 15),
        load_kwh=3.0,
        pv_kwh=0.0,
        import_price_sek_kwh=5.0,
        export_price_sek_kwh=0.0,
    )
    ev = _ev(
        max_power_kw=11.0,
        required_kwh=1.3,
        deadline=slot.end_time,
        control_type="current",
        min_power_kw=MIN_POWER_KW,
    )
    config = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[ev],
    )
    result = solver.solve(KeplerInput(slots=[slot], initial_soc_kwh=8.0), config)
    assert result.is_optimal

    charged_kw = result.slots[0].ev_charger_results.get("test_ev", 0.0)
    assert charged_kw > 0.01, "expected fractional charging in the only slot"
    assert charged_kw < 11.0 - 0.01, "expected genuinely fractional (sub-max) power"
    assert result.slots[0].discharge_kwh < 0.01, "discharge should be blocked while EV is charging"


if __name__ == "__main__":
    try:
        test_ev_modulation()
        test_ev_economic_stop()
        test_deferral_to_cheaper_slots()
        test_current_type_charger_planned_at_fractional_power()
        test_current_type_charger_never_below_min_amps()
        test_binary_charger_keeps_full_power_or_off_planning()
        test_fractional_charging_still_blocks_battery_discharge()
        print("\nALL VERIFICATIONS PASSED")
    except Exception as e:
        print(f"\nVERIFICATION FAILED: {e}")
        import traceback

        traceback.print_exc()
