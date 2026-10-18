"""Per-phase fuse limit on EV charger lines (ev-single-phase-grid-limit)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pytz import timezone as pytz_timezone

from planner.solver.adapter import (
    build_ev_charger_inputs,
    config_to_kepler_config,
    resolve_max_phase_import_kw,
)
from planner.solver.kepler import KeplerSolver
from planner.solver.types import EVChargerInput, KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz_timezone("Europe/Stockholm")
START = TZ.localize(datetime(2026, 9, 24, 0, 0))
LIMIT_KW = 20 * 0.85 * 230 / 1000  # 3.91


def _slots(n: int, load_kwh: float = 0.0) -> list[KeplerInputSlot]:
    out: list[KeplerInputSlot] = []
    for i in range(n):
        s = START + timedelta(minutes=15 * i)
        out.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(minutes=15),
                load_kwh=load_kwh if i < n - 4 else max(load_kwh, 4.0),
                pv_kwh=0.0,
                import_price_sek_kwh=0.1 if i < n - 4 else 5.0,
                export_price_sek_kwh=0.0,
            )
        )
    return out


def _ev(cid: str, phases: tuple[int, ...], required: float = 30.0) -> EVChargerInput:
    n = len(phases)
    return EVChargerInput(
        id=cid,
        max_power_kw=3.68 * n,
        min_power_kw=1.38 * n,
        battery_capacity_kwh=60.0,
        current_soc_percent=20.0,
        plugged_in=True,
        deadline=START + timedelta(hours=7),
        required_kwh=required,
        control_type="current",
        phases=phases,
    )


def _cfg(evs: list[EVChargerInput], limit: float | None) -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=20.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        max_import_power_kw=20.0,
        max_phase_import_kw=limit,
        ev_chargers=evs,
    )


def _solve(cfg: KeplerConfig, load_kwh: float = 0.0, n: int = 12):
    res = KeplerSolver().solve(KeplerInput(slots=_slots(n, load_kwh), initial_soc_kwh=2.0), cfg)
    assert res.is_optimal
    return res


def _net_kw(slot: Any) -> float:
    return (slot.grid_import_kwh - slot.grid_export_kwh) * 4


def _ev_total(res: Any, cid: str) -> float:
    return sum(s.ev_charger_results.get(cid, 0.0) * 0.25 for s in res.slots)


def _plan(res: Any) -> list[tuple[float, float]]:
    return [(round(s.grid_import_kwh, 6), round(sum(s.ev_charger_results.values()), 6)) for s in res.slots]


def test_single_phase_ev_respects_phase_limit():
    free = _solve(_cfg([_ev("a", (1,))], None))
    res = _solve(_cfg([_ev("a", (1,))], LIMIT_KW))
    for s in res.slots:
        ev = s.ev_charger_results.get("a", 0.0)
        assert ev + (_net_kw(s) - ev) / 3 <= LIMIT_KW + 1e-4
    # The unconstrained plan stacks EV + battery grid charge past the phase limit
    assert any(
        (e := s.ev_charger_results.get("a", 0.0)) + (_net_kw(s) - e) / 3 > LIMIT_KW + 1e-3
        for s in free.slots
    )


def test_three_phase_ev_unchanged():
    a = _solve(_cfg([_ev("a", (1, 2, 3))], LIMIT_KW))
    b = _solve(_cfg([_ev("a", (1, 2, 3))], None))
    assert _plan(a) == _plan(b)


def test_limit_none_unchanged():
    a = _solve(_cfg([_ev("a", (1,))], None))
    assert _ev_total(a, "a") > 0


def test_house_load_above_limit_is_feasible():
    res = _solve(_cfg([_ev("a", (1,))], LIMIT_KW), load_kwh=3.0)  # 12 kW house load, /3 > limit
    assert all(s.ev_charger_results.get("a", 0.0) < 1e-6 for s in res.slots[:-4])


def test_two_chargers_on_different_lines():
    evs = [_ev("a", (1,)), _ev("b", (2,))]
    res = _solve(_cfg(evs, LIMIT_KW))
    for s in res.slots:
        a = s.ev_charger_results.get("a", 0.0)
        b = s.ev_charger_results.get("b", 0.0)
        g = _net_kw(s)
        for own in (a, b):
            assert own + (g - a - b) / 3 <= LIMIT_KW + 1e-4


def test_adapter_max_phase_import():
    def cfg(**kw: Any) -> dict[str, Any]:
        c: dict[str, Any] = {"system": {"grid": {"main_fuse_a": 20}}}
        c["system"]["grid"].update(kw.pop("grid", {}))
        c.update(kw)
        return c

    assert abs(resolve_max_phase_import_kw(cfg()) - 3.91) < 1e-9
    assert resolve_max_phase_import_kw({"system": {"grid": {}}}) is None
    assert resolve_max_phase_import_kw(cfg(grid={"main_fuse_a": 0})) is None
    assert resolve_max_phase_import_kw(cfg(grid={"main_fuse_a": "x"})) is None
    assert abs(resolve_max_phase_import_kw(cfg(load_balancing={"target_margin_percent": 100})) - 4.6) < 1e-9
    assert abs(resolve_max_phase_import_kw(cfg(load_balancing={"target_margin_percent": "bad"})) - 3.91) < 1e-9
    assert abs(resolve_max_phase_import_kw(cfg(load_balancing={"target_margin_percent": 0})) - 3.91) < 1e-9


def test_adapter_charger_phases():
    def mk(**kw: Any) -> dict[str, Any]:
        return {"id": "c", "enabled": True, "type": "current", "min_current_a": 6,
                "max_current_a": 16, "battery_capacity_kwh": 60, **kw}

    def phases(ev: dict[str, Any]) -> tuple[int, ...]:
        return build_ev_charger_inputs([ev])[0].phases

    assert phases(mk(phases=[1])) == (1,)
    assert phases(mk(phases=[2, 1, 1])) == (1, 2)
    assert phases(mk(phases=[1, 2, 3])) == (1, 2, 3)
    assert phases(mk(phases=[1, 5])) == (1,)
    assert phases(mk(phases=[7])) == (1, 2, 3)
    assert phases(mk(type="binary", rated_power_kw=3.7, phases=[1])) == (1, 2, 3)


def test_margin_matches_executor_resolution_for_legacy_key():
    from executor.config import resolve_target_margin_percent as executor_resolve
    from planner.solver.adapter import resolve_max_phase_import_kw as planner_kw

    cases: list[dict[str, Any]] = [
        {},
        {"target_margin_percent": 70},
        {"resume_margin_percent": 95},
        {"resume_margin_percent": 90},
        {"resume_margin_percent": 60, "target_margin_percent": 75},
        {"resume_margin_percent": "bad"},
    ]
    for lb in cases:
        cfg = {"system": {"grid": {"main_fuse_a": 20}}, "load_balancing": lb}
        margin = float(executor_resolve(lb))
        assert abs((planner_kw(cfg) or 0.0) - 20 * margin / 100 * 0.23) < 1e-9, lb


def test_no_row_after_deadline():
    # Past the EV deadline the phase row is not added: import there is bounded
    # only by max_power_kw, not by 3 x the per-phase limit.
    ev = _ev("a", (1,))
    ev.deadline = START + timedelta(hours=1)
    res = _solve(_cfg([ev], LIMIT_KW), load_kwh=3.5)  # 14 kW house load > 3 x limit
    after = [s for s in res.slots[4:8]]
    assert any(_net_kw(s) > 3 * LIMIT_KW for s in after)
