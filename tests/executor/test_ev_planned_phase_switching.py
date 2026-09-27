"""ev-planned-phase-switching: next-slot lookup, planned targets bypassing the
phase-mode hold window, and the idle look-ahead pre-switch (tasks 2.2, 3.4).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytz

from executor.ev_surplus import PhaseModeController
from tests.executor.test_ev_surplus_engine import (  # noqa: F401 (fixtures)
    make_engine,
    make_schedule,
    temp_db,
    temp_schedule,
)

TZ = pytz.timezone("Europe/Stockholm")


def _slot(start: datetime, goe_kw: float | None = None) -> dict:
    end = start + timedelta(minutes=15)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "end_time_kepler": end.isoformat(),
        "battery_charge_kw": 0,
        "battery_discharge_kw": 0,
        "export_kwh": 0,
        "water_heating_kw": 0,
        "soc_target_percent": 50,
        "projected_soc_percent": 50,
        "ev_chargers": {"goe": goe_kw} if goe_kw is not None else {},
    }


def _write(path: str, payload: dict) -> None:
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(payload, f)


def _phase_engine(temp_schedule, temp_db, commanded_mode: int, last_switch: datetime | None):
    engine = make_engine(temp_schedule, temp_db, excess_pv_priority=[])
    cfg = engine.config.ev_chargers[0]
    cfg.phase_mode_entity = "select.goe_phase_mode"
    cfg.phase_switching_enabled = True
    ctrl = PhaseModeController()
    ctrl.commanded_mode = commanded_mode
    ctrl.last_switch_time = last_switch
    engine._ev_phase_controllers["goe"] = ctrl
    return engine, ctrl


def _state():
    return SimpleNamespace(current_export_kw=0.0, current_import_kw=0.0)


async def _phase_tick(engine, now: datetime) -> None:
    slot, _ = engine._load_current_slot(now)
    await engine._update_ev_surplus_and_phase_mode(_state(), slot, now)


# --- 2.2 Next-slot lookup ------------------------------------------------


class TestNextSlotLookup:
    def test_next_slot_found(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, excess_pv_priority=[])
        now = datetime.now(TZ)
        start = now - timedelta(minutes=5)
        _write(
            temp_schedule,
            make_schedule([_slot(start), _slot(start + timedelta(minutes=15), 6.9)]),
        )
        slot, _ = engine._load_current_slot(now)
        assert slot is not None
        assert engine._next_slot is not None
        assert engine._next_slot.ev_charger_plans.get("goe") == pytest.approx(6.9)

    def test_last_slot_has_no_next(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, excess_pv_priority=[])
        now = datetime.now(TZ)
        _write(temp_schedule, make_schedule([_slot(now - timedelta(minutes=5), 6.9)]))
        slot, _ = engine._load_current_slot(now)
        assert slot is not None
        assert engine._next_slot is None

    def test_non_contiguous_next_entry_is_ignored(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, excess_pv_priority=[])
        now = datetime.now(TZ)
        start = now - timedelta(minutes=5)
        _write(
            temp_schedule,
            make_schedule([_slot(start), _slot(start + timedelta(minutes=45), 6.9)]),
        )
        engine._load_current_slot(now)
        assert engine._next_slot is None

    def test_stale_schedule_yields_none(self, temp_schedule, temp_db):
        engine = make_engine(temp_schedule, temp_db, excess_pv_priority=[])
        now = datetime.now(TZ)
        start = now - timedelta(minutes=5)
        _write(
            temp_schedule,
            make_schedule([_slot(start), _slot(start + timedelta(minutes=15), 6.9)]),
        )
        engine._load_current_slot(now)
        assert engine._next_slot is not None

        stale = make_schedule([_slot(start), _slot(start + timedelta(minutes=15), 6.9)])
        stale["meta"]["generated_at"] = (
            now - timedelta(hours=engine.config.max_schedule_age_hours + 1)
        ).isoformat()
        _write(temp_schedule, stale)
        slot, _ = engine._load_current_slot(now)
        assert slot is None
        assert engine._next_slot is None


# --- 3.4 Planned targets and idle look-ahead -------------------------------


@pytest.mark.asyncio
async def test_2026_09_27_planned_slot_switches_on_first_tick(temp_schedule, temp_db):
    """2026-09-27: 6.9 kW planned from 12:00 while 1-phase — switch on the
    first tick of the slot instead of waiting the 600 s hold window."""
    slot_start = TZ.localize(datetime(2026, 9, 27, 12, 0, 0))
    now = slot_start + timedelta(seconds=50)
    engine, ctrl = _phase_engine(temp_schedule, temp_db, 1, now - timedelta(hours=2))
    schedule = make_schedule([_slot(slot_start, 6.9)])
    schedule["meta"]["generated_at"] = (now - timedelta(minutes=10)).isoformat()
    _write(temp_schedule, schedule)

    await _phase_tick(engine, now)

    assert ctrl.commanded_mode == 3
    assert ctrl.last_switch_time == now


@pytest.mark.asyncio
async def test_planned_slot_still_respects_since_last_switch(temp_schedule, temp_db):
    now = datetime.now(TZ)
    engine, ctrl = _phase_engine(temp_schedule, temp_db, 1, now - timedelta(seconds=300))
    _write(temp_schedule, make_schedule([_slot(now - timedelta(minutes=1), 6.9)]))

    await _phase_tick(engine, now)
    assert ctrl.commanded_mode == 1

    later = now + timedelta(seconds=301)
    await _phase_tick(engine, later)
    assert ctrl.commanded_mode == 3


@pytest.mark.asyncio
async def test_idle_one_phase_pre_switches_for_three_phase_slot(temp_schedule, temp_db):
    """Idle at 11:50 in 1-phase, 12:00 plans 6.9 kW: switch during the 11:45
    slot and command no charging current before 12:00."""
    engine, ctrl = _phase_engine(temp_schedule, temp_db, 1, None)
    now = datetime.now(TZ)
    start = now - timedelta(minutes=5)
    _write(
        temp_schedule,
        make_schedule([_slot(start), _slot(start + timedelta(minutes=15), 6.9)]),
    )

    await engine.run_once()

    assert ctrl.commanded_mode == 3
    assert ctrl.last_switch_time is not None
    # 3.3: the balancer reads the current slot only — nothing commanded yet.
    assert engine._last_balancer_planned_targets.get("goe") is None
    current_writes = [
        c.args[1]
        for c in engine.ha_client.set_number.call_args_list
        if c.args[0] == "number.goe_current" and c.args[1] > 0
    ]
    assert current_writes == []
    assert engine._ev_charger_states["goe"].charging_active is False


@pytest.mark.asyncio
async def test_idle_three_phase_pre_switches_for_one_phase_slot(temp_schedule, temp_db):
    now = datetime.now(TZ)
    engine, ctrl = _phase_engine(temp_schedule, temp_db, 3, now - timedelta(hours=1))
    start = now - timedelta(minutes=5)
    _write(
        temp_schedule,
        make_schedule([_slot(start), _slot(start + timedelta(minutes=15), 2.0)]),
    )

    await _phase_tick(engine, now)

    assert ctrl.commanded_mode == 1


@pytest.mark.asyncio
async def test_idle_without_next_plan_keeps_hold_window(temp_schedule, temp_db):
    now = datetime.now(TZ)
    engine, ctrl = _phase_engine(temp_schedule, temp_db, 3, now - timedelta(hours=1))
    start = now - timedelta(minutes=5)
    _write(
        temp_schedule,
        make_schedule([_slot(start), _slot(start + timedelta(minutes=15))]),
    )

    await _phase_tick(engine, now)
    assert ctrl.commanded_mode == 3  # target 0 must hold for the dwell window

    await _phase_tick(engine, now + timedelta(seconds=601))
    assert ctrl.commanded_mode == 1


@pytest.mark.asyncio
async def test_charging_slot_is_not_pre_switched(temp_schedule, temp_db):
    """Charging 2.3 kW now, 6.9 kW next: stay 1-phase until the next slot."""
    now = datetime.now(TZ)
    engine, ctrl = _phase_engine(temp_schedule, temp_db, 1, now - timedelta(hours=1))
    start = now - timedelta(minutes=5)
    _write(
        temp_schedule,
        make_schedule([_slot(start, 2.3), _slot(start + timedelta(minutes=15), 6.9)]),
    )

    await _phase_tick(engine, now)

    assert ctrl.commanded_mode == 1
