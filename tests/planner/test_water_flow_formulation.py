"""
Tests for the water arc-flow formulation (kepler-water-flow-formulation).

Equivalence: for fixed heat patterns the flow graph pays exactly the penalty of the
previous start/spacing/discomfort/gap_over/block_overshoot formulation (rebuilt here
as a reference LP), and the solver's optimum equals a brute-force optimum over all
heat patterns priced by the rule definitions.
"""

import random
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import product

import pulp
import pytest

from planner.solver.kepler import KeplerSolver, build_water_flow, plan_water_flow
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot, WaterHeaterInput

TOL = 1e-6


@dataclass(frozen=True)
class Rules:
    spacing_h: float = 0.0
    max_gap_h: float = 0.0  # heater max_hours_between_heating
    gap_pen: float = 0.0
    max_block_h: float = 2.0
    block_pen: float = 0.0
    start_pen: float = 0.0


def _config(rules: Rules, heater: WaterHeaterInput, **extra) -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0,
        max_soc_percent=100,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        water_heaters=[heater],
        water_heating_max_gap_hours=rules.max_gap_h,
        water_gap_penalty_sek=rules.gap_pen,
        water_block_penalty_sek=rules.block_pen,
        water_block_start_penalty_sek=rules.start_pen,
        max_block_hours=rules.max_block_h,
        water_reliability_penalty_sek=100.0,
        **extra,
    )


def _heater(rules: Rules, **kw) -> WaterHeaterInput:
    return WaterHeaterInput(
        id="wh1",
        power_kw=1.0,
        min_kwh_per_day=kw.pop("min_kwh_per_day", 0.0),
        max_hours_between_heating=rules.max_gap_h,
        min_spacing_hours=rules.spacing_h,
        **kw,
    )


def _avg(hours: list[float]) -> float:
    return sum(hours) / len(hours)


def reference_penalty(pattern, hours, rules: Rules, spacing_slots, cap_slots, gap_active):
    """Penalty by the rule definitions (previous formulation); None if spacing is violated."""
    total = 0.0
    since = 0.0
    for t, on in enumerate(pattern):
        start = on and (t == 0 or not pattern[t - 1])
        if start:
            total += rules.start_pen
            if spacing_slots > 0 and any(pattern[max(0, t - spacing_slots) : t]):
                return None
        since = 0.0 if on else since + hours[t]
        if gap_active:
            total += rules.gap_pen * max(0.0, since - rules.max_gap_h)
    if rules.block_pen > 0:
        for t in range(len(pattern) - cap_slots):
            total += rules.block_pen * max(0, sum(pattern[t : t + cap_slots + 1]) - cap_slots)
    return total


def reference_lp_penalty(pattern, hours, rules: Rules, spacing_slots, cap_slots, gap_active):
    """The previous start/spacing/discomfort/gap_over/block_overshoot rows, heat fixed."""
    T = len(pattern)
    prob = pulp.LpProblem("ref", pulp.LpMinimize)
    start = pulp.LpVariable.dicts("s", range(T), cat="Binary")
    disc = pulp.LpVariable.dicts("d", range(T), lowBound=0.0)
    over = pulp.LpVariable.dicts("g", range(T), lowBound=0.0)
    ovs = pulp.LpVariable.dicts("o", range(T), lowBound=0.0)
    for t in range(T):
        if t == 0:
            prob += start[t] == pattern[t]
        else:
            prob += start[t] >= pattern[t] - pattern[t - 1]
        if spacing_slots > 0:
            lo = max(0, t - spacing_slots)
            prob += sum(pattern[lo:t]) + start[t] * spacing_slots <= spacing_slots
        if gap_active:
            prev = disc[t - 1] if t else 0
            prob += disc[t] >= prev + hours[t] - pattern[t] * 100.0
            prob += over[t] >= disc[t] - rules.max_gap_h
    if rules.block_pen > 0:
        for t in range(T - cap_slots):
            prob += sum(pattern[t : t + cap_slots + 1]) <= cap_slots + ovs[t]
    prob += (
        rules.start_pen * pulp.lpSum(start.values())
        + rules.gap_pen * pulp.lpSum(over.values())
        + rules.block_pen * pulp.lpSum(ovs.values())
    )
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] == "Infeasible":
        return None
    return pulp.value(prob.objective) or 0.0


def flow_lp_penalty(pattern, hours, rules: Rules, heater, config):
    """Flow graph (plus window rows when the heater keeps them), heat fixed."""
    T = len(pattern)
    flow_plan = plan_water_flow(heater, config, _avg(hours))
    prob = pulp.LpProblem("flow", pulp.LpMinimize)
    heat = {t: pulp.LpVariable(f"h{t}", lowBound=pattern[t], upBound=pattern[t]) for t in range(T)}
    cost = 0
    if flow_plan.needs_flow:
        terms, _ = build_water_flow(
            prob,
            "wh1",
            heat,
            hours,
            flow_plan,
            rules.gap_pen,
            rules.max_gap_h,
            rules.block_pen,
        )
        cost = pulp.lpSum(v * c for v, c in terms)
    if flow_plan.window_overshoot:
        cap = flow_plan.cap_slots
        ovs = pulp.LpVariable.dicts("o", range(T), lowBound=0.0)
        for t in range(T - cap):
            prob += pulp.lpSum(heat[j] for j in range(t, t + cap + 1)) <= cap + ovs[t]
        cost = cost + rules.block_pen * pulp.lpSum(ovs.values())
    prob += cost
    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[prob.status] == "Infeasible":
        return None
    return pulp.value(prob.objective) or 0.0 or 0.0


HOURS_FULL = [0.5] * 14
HOURS_SHORT_FIRST = [0.2] + [0.5] * 13

CASES = {
    "spacing_ge_cap_gap_start_block": Rules(2.0, 2.0, 3.0, 1.0, 2.0, 1.5),
    "spacing_lt_cap": Rules(1.0, 2.0, 3.0, 2.5, 2.0, 1.5),
    "spacing_zero": Rules(0.0, 2.0, 3.0, 1.0, 2.0, 1.5),
    "gap_off": Rules(1.5, 0.0, 3.0, 1.0, 2.0, 1.5),
    "gap_only": Rules(0.0, 1.5, 3.0, 2.0, 0.0, 0.0),
    "bulk_start_only": Rules(0.0, 0.0, 0.0, 2.0, 0.0, 2.0),
    "spacing_only": Rules(1.5, 0.0, 0.0, 2.0, 0.0, 0.0),
}


def _patterns(T: int, seed: int, n: int = 12):
    rng = random.Random(seed)
    out = [[0] * T, [1] * T, [1, 0] * (T // 2), [0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0][:T]]
    for _ in range(n):
        p = rng.choice([0.2, 0.4, 0.6])
        out.append([1 if rng.random() < p else 0 for _ in range(T)])
    return out


@pytest.mark.parametrize("hours", [HOURS_FULL, HOURS_SHORT_FIRST], ids=["full", "short_first"])
@pytest.mark.parametrize("name", list(CASES))
def test_fixed_pattern_penalty_equals_previous_formulation(name, hours):
    rules = CASES[name]
    heater = _heater(rules)
    config = _config(rules, heater)
    fp = plan_water_flow(heater, config, _avg(hours))
    infeasible = 0
    for pattern in _patterns(len(hours), seed=zlib.crc32(name.encode()) % 1000):
        expected = reference_lp_penalty(
            pattern, hours, rules, fp.spacing_slots, fp.cap_slots, fp.gap_active
        )
        by_definition = reference_penalty(
            pattern, hours, rules, fp.spacing_slots, fp.cap_slots, fp.gap_active
        )
        got = flow_lp_penalty(pattern, hours, rules, heater, config)
        if expected is None:
            infeasible += 1
            assert by_definition is None and got is None
        else:
            assert by_definition == pytest.approx(expected, abs=TOL)
            assert got == pytest.approx(expected, abs=TOL)
    if name in ("spacing_ge_cap_gap_start_block", "spacing_only"):
        assert infeasible > 0  # spacing rule actually rejects patterns


def test_flow_plan_chooses_overshoot_path_by_spacing_vs_cap():
    hours = [0.5] * 10
    ge = CASES["spacing_ge_cap_gap_start_block"]  # spacing 4 slots, cap 2
    plan = plan_water_flow(_heater(ge), _config(ge, _heater(ge)), _avg(hours))
    assert (plan.spacing_slots, plan.cap_slots) == (4, 2)
    assert plan.flow_overshoot and not plan.window_overshoot

    lt = CASES["spacing_lt_cap"]  # spacing 2 slots, cap 5
    plan = plan_water_flow(_heater(lt), _config(lt, _heater(lt)), _avg(hours))
    assert (plan.spacing_slots, plan.cap_slots) == (2, 5)
    assert plan.window_overshoot and not plan.flow_overshoot

    zero = CASES["spacing_zero"]
    plan = plan_water_flow(_heater(zero), _config(zero, _heater(zero)), _avg(hours))
    assert plan.spacing_slots == 0 and plan.window_overshoot


def test_bulk_mode_needs_flow_only_for_start_penalty():
    rules = CASES["bulk_start_only"]
    plan = plan_water_flow(_heater(rules), _config(rules, _heater(rules)), 0.5)
    assert plan.needs_flow and not plan.gap_active and plan.spacing_slots == 0
    none = Rules(block_pen=0.0)
    plan = plan_water_flow(_heater(none), _config(none, _heater(none)), 0.5)
    assert not plan.needs_flow


def test_exact_semantics_by_hand():
    hours = [0.5] * 8
    rules = Rules(spacing_h=1.5, max_gap_h=1.0, gap_pen=2.0, max_block_h=1.0, block_pen=3.0, start_pen=5.0)
    heater = _heater(rules)
    config = _config(rules, heater)
    fp = plan_water_flow(heater, config, 0.5)
    assert (fp.spacing_slots, fp.cap_slots) == (3, 2)

    # Never heated: off 8 slots, cumulative gap cost sum 2*(0.5*k - 1) for k > 2.
    never = [0] * 8
    expected = sum(2.0 * max(0.0, 0.5 * k - 1.0) for k in range(1, 9))
    assert flow_lp_penalty(never, hours, rules, heater, config) == pytest.approx(expected)

    # Start at slot 0 is allowed (spacing truncated at plan start): start + 3-slot block
    # overshoots the 2-slot cap by one slot, then 4 off slots.
    block = [1, 1, 1, 0, 0, 0, 0, 0]
    expected = 5.0 + 3.0 + sum(2.0 * max(0.0, 0.5 * k - 1.0) for k in range(1, 6))
    assert flow_lp_penalty(block, hours, rules, heater, config) == pytest.approx(expected)

    # Second start after only 2 off slots violates spacing (3 slots).
    assert flow_lp_penalty([1, 0, 0, 1, 0, 0, 0, 0], hours, rules, heater, config) is None
    # After 3 off slots it is allowed.
    assert flow_lp_penalty([1, 0, 0, 0, 1, 0, 0, 0], hours, rules, heater, config) is not None

    # Never-heated start late in the horizon is allowed.
    assert flow_lp_penalty([0, 0, 0, 0, 0, 0, 0, 1], hours, rules, heater, config) is not None


# --- End to end: solver optimum equals the brute-force optimum -----------------------


def _slots(prices: list[float], hours: float = 1.0):
    base = datetime(2026, 1, 15, 8, 0)
    out = []
    for i, price in enumerate(prices):
        start = base + timedelta(hours=hours * i)
        out.append(
            KeplerInputSlot(
                start_time=start,
                end_time=start + timedelta(hours=hours),
                load_kwh=0.0,
                pv_kwh=0.0,
                import_price_sek_kwh=price,
                export_price_sek_kwh=0.0,
            )
        )
    return out


def _brute_force(prices, slot_hours, day_hours, rules, heater, config, force_on=()):
    fp = plan_water_flow(heater, config, _avg(slot_hours))
    need = max(0.0, heater.min_kwh_per_day - heater.heated_today_kwh)
    best = None
    for pattern in product([0, 1], repeat=len(prices)):
        if any(not pattern[t] for t in force_on):
            continue
        pen = reference_penalty(
            pattern, slot_hours, rules, fp.spacing_slots, fp.cap_slots, fp.gap_active
        )
        if pen is None:
            continue
        energy = sum(p * on * slot_hours[t] for t, (p, on) in enumerate(zip(prices, pattern)))
        shortfall = max(0.0, need - sum(on * day_hours[t] for t, on in enumerate(pattern)))
        total = energy + pen + 100.0 * shortfall
        if best is None or total < best[0]:
            best = (total, pattern)
    return best


def _solve_total(prices, slot_hours, day_hours, rules, heater, config, input_kw=None):
    solver = KeplerSolver()
    result = solver.solve(
        KeplerInput(slots=_slots(prices), initial_soc_kwh=0.0, **(input_kw or {})), config
    )
    assert result.is_optimal
    pattern = tuple(1 if s.water_heat_kw > 0 else 0 for s in result.slots)
    fp = plan_water_flow(heater, config, _avg(slot_hours))
    pen = reference_penalty(
        pattern, slot_hours, rules, fp.spacing_slots, fp.cap_slots, fp.gap_active
    )
    assert pen is not None, "solver plan violates spacing"
    need = max(0.0, heater.min_kwh_per_day - heater.heated_today_kwh)
    energy = sum(p * on * slot_hours[t] for t, (p, on) in enumerate(zip(prices, pattern)))
    shortfall = max(0.0, need - sum(on * day_hours[t] for t, on in enumerate(pattern)))
    return energy + pen + 100.0 * shortfall, pattern, result


E2E_PRICES = [0.9, 0.4, 0.2, 1.5, 2.0, 0.3, 0.1, 0.35, 1.0, 0.15]
E2E_MIN_KWH = 4.0


@pytest.mark.parametrize(
    "name",
    [
        "spacing_ge_cap_gap_start_block",
        "spacing_lt_cap",
        "spacing_zero",
        "gap_off",
        "bulk_start_only",
    ],
)
def test_solver_optimum_matches_brute_force(name):
    rules = CASES[name]
    # Hourly slots here: cap = max_block_h slots, spacing = spacing_h slots.
    heater = _heater(rules, min_kwh_per_day=E2E_MIN_KWH)
    config = _config(rules, heater)
    hours = [1.0] * len(E2E_PRICES)
    best_total, _ = _brute_force(E2E_PRICES, hours, hours, rules, heater, config)
    total, _, _ = _solve_total(E2E_PRICES, hours, hours, rules, heater, config)
    assert total == pytest.approx(best_total, abs=1e-3)


def test_spacing_below_cap_end_to_end_uses_window_rows():
    # Hourly slots: spacing 2 < cap 4; five cheap slots in a row exceed the cap by one
    # window, priced by the window rows, and starts are spaced.
    rules = Rules(spacing_h=2.0, max_gap_h=0.0, gap_pen=0.0, max_block_h=4.0, block_pen=1.0)
    heater = _heater(rules, min_kwh_per_day=5.0)
    config = _config(rules, heater)
    fp = plan_water_flow(heater, config, 1.0)
    assert fp.window_overshoot and (fp.spacing_slots, fp.cap_slots) == (2, 4)
    prices = [3.0, 0.1, 0.1, 0.1, 0.1, 0.1, 3.0, 3.0]
    hours = [1.0] * len(prices)
    best_total, _ = _brute_force(prices, hours, hours, rules, heater, config)
    total, pattern, result = _solve_total(prices, hours, hours, rules, heater, config)
    assert total == pytest.approx(best_total, abs=1e-3)
    assert result.time_limit_hit is False
    assert sum(pattern) >= 5


def test_shortened_first_slot_matches_brute_force():
    rules = CASES["spacing_ge_cap_gap_start_block"]
    heater = _heater(rules, min_kwh_per_day=E2E_MIN_KWH)
    config = _config(rules, heater)
    hours = [0.5] + [1.0] * (len(E2E_PRICES) - 1)
    best_total, _ = _brute_force(E2E_PRICES, hours, [1.0] * len(hours), rules, heater, config)
    total, _, _ = _solve_total(
        E2E_PRICES,
        hours,
        [1.0] * len(hours),
        rules,
        heater,
        config,
        input_kw={"first_slot_remaining_h": 0.5},
    )
    assert total == pytest.approx(best_total, abs=1e-3)


def test_force_on_and_heated_today_act_on_water_heat():
    rules = CASES["spacing_ge_cap_gap_start_block"]
    prices = [1.0, 2.0, 3.0, 1.5, 2.5, 3.0, 1.0, 2.0, 2.5, 1.0]
    hours = [1.0] * len(prices)
    heater = _heater(rules, min_kwh_per_day=3.0, force_on_slots=[4], heated_today_kwh=1.0)
    config = _config(rules, heater)
    best_total, _ = _brute_force(prices, hours, hours, rules, heater, config, force_on=(4,))
    total, pattern, _ = _solve_total(prices, hours, hours, rules, heater, config)
    assert pattern[4] == 1
    assert total == pytest.approx(best_total, abs=1e-3)


def test_flow_result_extraction_and_time_limit_flag():
    rules = CASES["spacing_ge_cap_gap_start_block"]
    heater = _heater(rules, min_kwh_per_day=3.0)
    config = _config(rules, heater)
    prices = [1.0] * 10
    _, _, result = _solve_total(prices, [1.0] * 10, [1.0] * 10, rules, heater, config)
    assert result.is_optimal and result.time_limit_hit is False
    assert len(result.slots) == 10
    assert sum(1 for s in result.slots if s.water_heat_kw > 0) >= 3
