"""Per-phase fuse limit including water heaters (water-heater-phase-aware-planning)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from planner.solver.adapter import build_water_heater_inputs
from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    KeplerBenchmark,
    KeplerConfig,
    KeplerInput,
    WaterHeaterInput,
)
from tests.planner.test_kepler_ev_phase_limit import LIMIT_KW, _ev, _slots

HEATER_KW = 3.0


def _heater(phases: tuple[int, ...], **kw: Any) -> WaterHeaterInput:
    return WaterHeaterInput(
        id="wh",
        power_kw=HEATER_KW,
        min_kwh_per_day=kw.pop("min_kwh_per_day", 3.0),
        max_hours_between_heating=0.0,
        min_spacing_hours=0.0,
        phases=phases,
        **kw,
    )


def _cfg(
    heaters: list[WaterHeaterInput],
    evs: list[EVChargerInput],
    limit: float | None = LIMIT_KW,
) -> KeplerConfig:
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
        water_reliability_penalty_sek=50.0,
        water_heaters=heaters,
        ev_chargers=evs,
    )


def _solve(cfg: KeplerConfig, load_kwh: float = 0.0, n: int = 24, benchmark: Any = None):
    res = KeplerSolver().solve(
        KeplerInput(slots=_slots(n, load_kwh), initial_soc_kwh=2.0, benchmark=benchmark), cfg
    )
    assert res.is_optimal
    return res


def _share(phases: tuple[int, ...], line: int) -> float:
    return 1 / len(phases) if line in phases else 0.0


def _line_load(slot: Any, line: int, heater: WaterHeaterInput, evs: list[EVChargerInput]) -> float:
    net = (slot.grid_import_kwh - slot.grid_export_kwh) * 4
    load = net / 3
    load += (_share(heater.phases, line) - 1 / 3) * slot.water_heater_results.get(heater.id, 0.0)
    for ev in evs:
        load += (_share(ev.phases, line) - 1 / 3) * slot.ev_charger_results.get(ev.id, 0.0)
    return load


def test_heater_and_ev_on_same_phase_stay_under_limit():
    heater = _heater((3,))
    ev = _ev("a", (3,), required=8.0)
    res = _solve(_cfg([heater], [ev]))
    assert any(s.water_heater_results.get("wh", 0.0) > 0 for s in res.slots)
    assert any(s.ev_charger_results.get("a", 0.0) > 0 for s in res.slots)
    for s in res.slots:
        assert _line_load(s, 3, heater, [ev]) <= LIMIT_KW + 1e-4
        # They cannot run together on L3 (3 kW + 3.68 kW > limit)
        assert not (
            s.water_heater_results.get("wh", 0.0) > 1e-6
            and s.ev_charger_results.get("a", 0.0) > 1e-6
        )


def test_heater_on_other_phase_than_ev_is_not_restricted():
    heater = _heater((2,))
    ev = _ev("a", (3,), required=8.0)
    res = _solve(_cfg([heater], [ev]))
    for s in res.slots:
        for line in (1, 2, 3):
            assert _line_load(s, line, heater, [ev]) <= LIMIT_KW + 1e-4
    # Different lines: both may run in the same slot
    assert any(
        s.water_heater_results.get("wh", 0.0) > 1e-6 and s.ev_charger_results.get("a", 0.0) > 1e-6
        for s in res.slots
    )


def test_three_phase_heater_adds_no_rows():
    with_limit = _solve(_cfg([_heater((1, 2, 3))], [], LIMIT_KW))
    without = _solve(_cfg([_heater((1, 2, 3))], [], None))
    assert [round(s.grid_import_kwh, 6) for s in with_limit.slots] == [
        round(s.grid_import_kwh, 6) for s in without.slots
    ]
    assert [s.water_heater_results for s in with_limit.slots] == [
        s.water_heater_results for s in without.slots
    ]


def test_single_phase_heater_alone_activates_constraint():
    # 12 kW house load on every line (net/3 = 4 > limit): the heater on L3 may not run
    heater = _heater((3,))
    res = _solve(_cfg([heater], []), load_kwh=3.0)
    heated = [s for s in res.slots[:-4] if s.water_heater_results.get("wh", 0.0) > 1e-6]
    assert not heated


def test_forced_on_slot_over_limit_stays_feasible(caplog: pytest.LogCaptureFixture):
    heater = _heater((3,), force_on_slots=[0, 1, 2, 3])
    with caplog.at_level(logging.WARNING, logger="darkstar.kepler"):
        res = _solve(_cfg([heater], []), load_kwh=3.0)
    for t in range(4):
        assert res.slots[t].water_heater_results.get("wh", 0.0) == pytest.approx(HEATER_KW)
    assert "Per-phase limit exceeded" in caplog.text


def test_min_kwh_per_day_penalised_not_infeasible_with_limit():
    # Limit blocks all heating (house load above limit): solve is still optimal
    heater = _heater((3,), min_kwh_per_day=6.0)
    res = _solve(_cfg([heater], []), load_kwh=3.0)
    assert res.is_optimal


def test_min_kwh_per_day_met_when_limit_allows():
    heater = _heater((3,), min_kwh_per_day=6.0)
    res = _solve(_cfg([heater], []))
    total = sum(s.water_heater_results.get("wh", 0.0) * 0.25 for s in res.slots)
    assert total >= 6.0 - 1e-6


def test_benchmark_mode_ignores_phase_limit():
    heater = _heater((3,))
    n = 8
    bench = KeplerBenchmark(terminal_soc_kwh=2.0, no_discharge_slots=[False] * n)
    a = _solve(_cfg([heater], [], LIMIT_KW), load_kwh=3.0, n=n, benchmark=bench)
    b = _solve(_cfg([heater], [], None), load_kwh=3.0, n=n, benchmark=bench)
    assert [round(s.grid_import_kwh, 6) for s in a.slots] == [
        round(s.grid_import_kwh, 6) for s in b.slots
    ]


def test_adapter_reads_and_sanitises_heater_phases(caplog: pytest.LogCaptureFixture):
    def build(**kw: Any) -> WaterHeaterInput:
        wh = {"id": "t", "enabled": True, "power_kw": 3.0, **kw}
        return build_water_heater_inputs([wh])[0]

    assert build().phases == (1, 2, 3)
    assert build(phases=[3]).phases == (3,)
    assert build(phases=[3, 1, 3]).phases == (1, 3)
    with caplog.at_level(logging.WARNING, logger="darkstar.planner.solver.adapter"):
        assert build(phases=[4]).phases == (1, 2, 3)
        assert build(phases=[]).phases == (1, 2, 3)
    assert "no valid phases" in caplog.text
