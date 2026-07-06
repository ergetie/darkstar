"""
Tests for the water-heating gap-comfort penalty (fix-water-comfort-truthfulness).

Covers:
- Gaps beyond the ceiling (water_heating_max_gap_hours) get broken up (6.1)
- Gaps within the ceiling are free / don't change the plan (6.2)
- Gap penalty disabled when the ceiling is 0 (enable_top_ups=false / vacation mode) (6.3)
- comfort_level maps to a monotonic gap penalty weight without touching the ceiling (6.4)
- Curtailment is preferred over loss-making export at non-positive prices (6.5, #16)
"""

from datetime import datetime, timedelta
from itertools import pairwise

from planner.solver.adapter import _comfort_level_to_penalty
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot, WaterHeaterInput


def _day_slots(cheap_hours: set[int], cheap_price: float = 0.2, expensive_price: float = 3.0):
    """24h of half-hour slots; slots whose hour is in cheap_hours get cheap_price."""
    base = datetime(2026, 1, 15, 0, 0)
    slots = []
    for i in range(48):
        s = base + timedelta(minutes=30 * i)
        price = cheap_price if s.hour in cheap_hours else expensive_price
        slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(minutes=30),
                load_kwh=0.0,
                pv_kwh=0.0,
                import_price_sek_kwh=price,
                export_price_sek_kwh=0.0,
            )
        )
    return slots


def _heater(power_kw: float = 1.0, min_kwh_per_day: float = 1.0) -> WaterHeaterInput:
    return WaterHeaterInput(
        id="wh1",
        power_kw=power_kw,
        min_kwh_per_day=min_kwh_per_day,
        max_hours_between_heating=0.0,  # per-device field is unused by the solver (Decision 3)
        min_spacing_hours=0.0,
    )


def _config(
    max_gap_hours: float,
    gap_penalty_sek: float,
    heater: WaterHeaterInput | None = None,
) -> KeplerConfig:
    # No battery: heating must draw from grid import at each slot's own price,
    # so import price actually drives WHEN the solver chooses to heat.
    return KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        water_heaters=[heater or _heater()],
        water_heating_max_gap_hours=max_gap_hours,
        water_gap_penalty_sek=gap_penalty_sek,
        water_reliability_penalty_sek=100.0,  # ensure daily minimum is met
    )


def _max_gap_hours(result) -> float:
    """Largest gap (in hours) between consecutive heating slots, including the
    gap from horizon start to the first heating slot and from the last heating
    slot to the end of the horizon (an unresolved trailing gap is still a gap)."""
    heat_map = [1 if s.water_heat_kw > 0 else 0 for s in result.slots]
    heated_indices = [i for i, h in enumerate(heat_map) if h == 1]
    n = len(heat_map)
    if not heated_indices:
        return float("inf")
    gaps = [heated_indices[0] * 0.5]
    for prev, cur in pairwise(heated_indices):
        gaps.append((cur - prev) * 0.5)
    gaps.append((n - 1 - heated_indices[-1]) * 0.5)
    return max(gaps)


def test_gaps_beyond_ceiling_are_broken_up():
    """Cheap night / expensive day: without a gap penalty the solver would bunch
    all heating into the cheapest window, leaving a long gap. With the ceiling +
    penalty active, the resulting schedule should not have a gap materially
    exceeding the 8h ceiling (one slot / 0.5h tolerance)."""
    solver = KeplerSolver()
    slots = _day_slots(cheap_hours={0, 1, 2})
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)

    config = _config(max_gap_hours=8.0, gap_penalty_sek=5.0)
    result = solver.solve(input_data, config)

    assert result.is_optimal
    assert _max_gap_hours(result) <= 8.5


def test_gaps_beyond_ceiling_without_penalty_exceed_it():
    """Sanity check: with the gap penalty disabled, the same scenario produces a
    gap that exceeds the ceiling — proving the ceiling above is actually load-bearing."""
    solver = KeplerSolver()
    slots = _day_slots(cheap_hours={0, 1, 2})
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)

    config = _config(max_gap_hours=8.0, gap_penalty_sek=0.0)
    result = solver.solve(input_data, config)

    assert result.is_optimal
    assert _max_gap_hours(result) > 8.5


def test_gaps_within_ceiling_are_free():
    """When the optimal plan already keeps gaps within the ceiling, raising the
    gap penalty weight should not change the plan (gap_over stays at 0)."""
    solver = KeplerSolver()
    # Cheap hours spread out every 6h; daily minimum exactly consumes all cheap
    # capacity (8 slots * 0.5 kWh = 4.0 kWh) so heating is naturally spread
    # across all four windows by price alone, already within an 8h ceiling.
    slots = _day_slots(cheap_hours={0, 6, 12, 18})
    heater = _heater(power_kw=1.0, min_kwh_per_day=4.0)
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)

    low_penalty_result = solver.solve(
        input_data, _config(max_gap_hours=8.0, gap_penalty_sek=0.0, heater=heater)
    )
    high_penalty_result = solver.solve(
        input_data, _config(max_gap_hours=8.0, gap_penalty_sek=500.0, heater=heater)
    )

    assert low_penalty_result.is_optimal and high_penalty_result.is_optimal
    low_heat_map = [1 if s.water_heat_kw > 0 else 0 for s in low_penalty_result.slots]
    high_heat_map = [1 if s.water_heat_kw > 0 else 0 for s in high_penalty_result.slots]
    assert low_heat_map == high_heat_map
    assert _max_gap_hours(low_penalty_result) <= 8.5


def test_gap_penalty_disabled_when_ceiling_zero():
    """water_heating_max_gap_hours == 0 (enable_top_ups=false / vacation mode) must
    disable the gap term entirely — no forced extra heating regardless of the
    configured weight."""
    solver = KeplerSolver()
    slots = _day_slots(cheap_hours={0, 1, 2})
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)

    disabled_result = solver.solve(
        input_data, _config(max_gap_hours=0.0, gap_penalty_sek=50.0)
    )
    no_penalty_result = solver.solve(
        input_data, _config(max_gap_hours=8.0, gap_penalty_sek=0.0)
    )

    assert disabled_result.is_optimal
    disabled_heat_map = [1 if s.water_heat_kw > 0 else 0 for s in disabled_result.slots]
    no_penalty_heat_map = [1 if s.water_heat_kw > 0 else 0 for s in no_penalty_result.slots]
    # Both bunch heating into the cheapest window; identical plans confirm the
    # gap term had zero effect when the ceiling is 0, even with a high weight.
    assert disabled_heat_map == no_penalty_heat_map


def test_comfort_level_gap_penalty_monotonic_ceiling_unchanged():
    """comfort_level scales only the gap-penalty weight; the ceiling is untouched."""
    weights = [
        _comfort_level_to_penalty(level, daily_kwh=3.0, heater_power_kw=3.0)[
            "water_gap_penalty_sek"
        ]
        for level in range(1, 6)
    ]
    assert weights == sorted(weights)
    assert len(set(weights)) == len(weights)  # strictly increasing

    for level in range(1, 6):
        params = _comfort_level_to_penalty(level, daily_kwh=3.0, heater_power_kw=3.0)
        assert "water_heating_max_gap_hours" not in params


def test_curtailment_preferred_over_lossmaking_export():
    """#16: at a negative effective export price, surplus PV should be curtailed
    (grid_export ~= 0); at a positive price, it should be exported.

    Note: at an effective price of exactly 0, exporting and curtailing are an
    objective tie (0 revenue vs 0 cost), so the solver may pick either — no money
    is lost, but the choice is not deterministic. Use a strictly negative price
    here so the assertion tests the real guarantee (never pay to export) rather
    than relying on arbitrary tie-breaking.
    """
    solver = KeplerSolver()
    start = datetime(2026, 1, 15, 12, 0)
    slots = [
        KeplerInputSlot(
            start_time=start,
            end_time=start + timedelta(hours=1),
            load_kwh=0.0,
            pv_kwh=5.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=-0.05,  # effective export price < 0 (paying to export)
        ),
        KeplerInputSlot(
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=2),
            load_kwh=0.0,
            pv_kwh=5.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.5,  # effective export price > 0
        ),
    ]
    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)

    config = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        curtailment_penalty_sek=0.1,
        enable_export=True,
    )

    result = solver.solve(input_data, config)

    assert result.is_optimal
    assert result.slots[0].grid_export_kwh < 0.01
    assert result.slots[1].grid_export_kwh > 4.0
