from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytz

from planner.pipeline import _apply_keep_on_after_target


def _make_slot(start: datetime, end: datetime, ev_kw: dict[str, float] | None = None) -> Any:
    """Build a minimal mock slot with the fields the flag logic reads/writes."""
    slot = MagicMock()
    slot.start_time = start
    slot.end_time = end
    slot.ev_charger_results = dict(ev_kw if ev_kw is not None else {"ev1": 0.0})
    slot.ev_charge_kw = sum(slot.ev_charger_results.values())
    slot.ev_keep_on = {}
    return slot


def _make_result(slots: list[Any]) -> Any:
    result = MagicMock()
    result.slots = slots
    return result


def test_keep_on_sets_flag_until_deadline_no_fake_power():
    """keep_on=true, target=100, SoC=100, before deadline → flag set, no power injected."""
    now = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)
    deadline = now + timedelta(hours=2)

    slots = [
        _make_slot(now + timedelta(minutes=i * 15), now + timedelta(minutes=(i + 1) * 15))
        for i in range(16)
    ]
    result = _make_result(slots)

    ev_states = [
        {
            "id": "ev1",
            "soc_percent": 100.0,
            "deadline": deadline,
            "keep_on_after_target": True,
            "plugged_in": True,
        }
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "max_power_kw": 11.0, "target_soc_percent": 100, "battery_capacity_kwh": 82.0}
    ]

    _apply_keep_on_after_target(result, ev_states, ev_chargers_cfg, now)

    for slot in slots:
        if slot.end_time <= deadline:
            assert slot.ev_keep_on == {"ev1": True}
        else:
            assert slot.ev_keep_on == {}
        assert slot.ev_charger_results["ev1"] == 0.0

    assert slots[0].ev_charge_kw == 0.0


def test_keep_on_off_no_flag():
    """keep_on=false → no flag, slots remain zero."""
    now = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)
    deadline = now + timedelta(hours=2)

    slots = [
        _make_slot(now + timedelta(minutes=i * 15), now + timedelta(minutes=(i + 1) * 15))
        for i in range(4)
    ]
    result = _make_result(slots)

    ev_states = [
        {
            "id": "ev1",
            "soc_percent": 100.0,
            "deadline": deadline,
            "keep_on_after_target": False,
            "plugged_in": True,
        }
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "max_power_kw": 11.0, "target_soc_percent": 100, "battery_capacity_kwh": 82.0}
    ]

    _apply_keep_on_after_target(result, ev_states, ev_chargers_cfg, now)

    for slot in slots:
        assert slot.ev_charger_results["ev1"] == 0.0
        assert slot.ev_keep_on == {}


def test_keep_on_target_below_100_no_flag():
    """keep_on=true but target=80 → no flag (avoids overcharge)."""
    now = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)
    deadline = now + timedelta(hours=2)

    slots = [
        _make_slot(now + timedelta(minutes=i * 15), now + timedelta(minutes=(i + 1) * 15))
        for i in range(4)
    ]
    result = _make_result(slots)

    ev_states = [
        {
            "id": "ev1",
            "soc_percent": 80.0,
            "deadline": deadline,
            "keep_on_after_target": True,
            "plugged_in": True,
        }
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "max_power_kw": 11.0, "target_soc_percent": 80, "battery_capacity_kwh": 82.0}
    ]

    _apply_keep_on_after_target(result, ev_states, ev_chargers_cfg, now)

    for slot in slots:
        assert slot.ev_charger_results["ev1"] == 0.0
        assert slot.ev_keep_on == {}


def test_keep_on_soc_below_100_no_flag():
    """keep_on=true, target=100 but SoC=70 → no flag (still needs charging)."""
    now = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)
    deadline = now + timedelta(hours=2)

    slots = [
        _make_slot(now + timedelta(minutes=i * 15), now + timedelta(minutes=(i + 1) * 15))
        for i in range(4)
    ]
    result = _make_result(slots)

    ev_states = [
        {
            "id": "ev1",
            "soc_percent": 70.0,
            "deadline": deadline,
            "keep_on_after_target": True,
            "plugged_in": True,
        }
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "max_power_kw": 11.0, "target_soc_percent": 100, "battery_capacity_kwh": 82.0}
    ]

    _apply_keep_on_after_target(result, ev_states, ev_chargers_cfg, now)

    for slot in slots:
        assert slot.ev_charger_results["ev1"] == 0.0
        assert slot.ev_keep_on == {}


def test_keep_on_after_deadline_no_flag():
    """keep_on=true, target=100, SoC=100 but deadline already passed → no flag."""
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    deadline = now - timedelta(hours=1)  # deadline in the past

    slots = [
        _make_slot(now + timedelta(minutes=i * 15), now + timedelta(minutes=(i + 1) * 15))
        for i in range(4)
    ]
    result = _make_result(slots)

    ev_states = [
        {
            "id": "ev1",
            "soc_percent": 100.0,
            "deadline": deadline,
            "keep_on_after_target": True,
            "plugged_in": True,
        }
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "max_power_kw": 11.0, "target_soc_percent": 100, "battery_capacity_kwh": 82.0}
    ]

    _apply_keep_on_after_target(result, ev_states, ev_chargers_cfg, now)

    for slot in slots:
        assert slot.ev_charger_results["ev1"] == 0.0
        assert slot.ev_keep_on == {}


def test_keep_on_does_not_touch_solver_scheduled_energy():
    """Flag logic never mutates ev_charger_results/ev_charge_kw, even if the solver already
    scheduled charging below max — keep-on is a switch-state flag, not planned energy."""
    now = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)
    deadline = now + timedelta(hours=1)

    slots = [
        _make_slot(now + timedelta(minutes=i * 15), now + timedelta(minutes=(i + 1) * 15), {"ev1": 5.0})
        for i in range(2)
    ]
    result = _make_result(slots)

    ev_states = [
        {
            "id": "ev1",
            "soc_percent": 100.0,
            "deadline": deadline,
            "keep_on_after_target": True,
            "plugged_in": True,
        }
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "max_power_kw": 11.0, "target_soc_percent": 100, "battery_capacity_kwh": 82.0}
    ]

    _apply_keep_on_after_target(result, ev_states, ev_chargers_cfg, now)

    for slot in slots:
        assert slot.ev_charger_results["ev1"] == 5.0
        assert slot.ev_charge_kw == 5.0
        assert slot.ev_keep_on == {"ev1": True}
