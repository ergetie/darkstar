"""Power-shortfall warning: planned versus recorded battery power."""

from datetime import timedelta

import pytest

from backend.learning import battery_warnings as bw
from tests.backend.test_battery_benchmark import _config
from tests.learning.battery_synth import FIRST_DAY, flags, iso

CONFIG = _config(max_charge_power_kw=5.0, max_discharge_power_kw=5.0)
NOW = iso(FIRST_DAY + timedelta(days=10), 0)[0]


def _now():
    from datetime import datetime

    return datetime.fromisoformat(NOW)


def _data(slots: int, planned_kw: float, delivered_kw: float, direction: str = "charge"):
    """``slots`` consecutive slots from day 0, each planned and recorded."""
    plans, rows = [], []
    for slot in range(slots):
        start, end = iso(FIRST_DAY, slot)
        plan = {"slot_start": start, "slot_end": end}
        row = {"slot_start": start, "slot_end": end, "quality_flags": flags()}
        for kind, prefix in (("charge", "charge"), ("discharge", "discharge")):
            plan[f"planned_{prefix}_kwh"] = planned_kw * 0.25 if kind == direction else 0.0
            row[f"batt_{prefix}_kwh"] = delivered_kw * 0.25 if kind == direction else 0.0
        plans.append(plan)
        rows.append(row)
    return rows, plans


def test_thirty_slots_at_3_5_of_5_kw_warn() -> None:
    rows, plans = _data(30, 5.0, 3.5)

    [warning] = bw.power_shortfall_warning(rows, plans, CONFIG, _now())

    assert warning.direction == "charge"
    assert warning.slots == 30
    assert warning.planned_kw == pytest.approx(5.0)
    assert warning.delivered_kw == pytest.approx(3.5)
    assert warning.limit_kw == 5.0


def test_discharge_is_checked_separately() -> None:
    rows, plans = _data(30, 5.0, 3.5, direction="discharge")

    [warning] = bw.power_shortfall_warning(rows, plans, CONFIG, _now())

    assert warning.direction == "discharge"


def test_nineteen_slots_do_not_warn() -> None:
    rows, plans = _data(19, 5.0, 3.5)
    assert bw.power_shortfall_warning(rows, plans, CONFIG, _now()) == []


def test_ninety_percent_delivery_does_not_warn() -> None:
    rows, plans = _data(30, 5.0, 4.5)
    assert bw.power_shortfall_warning(rows, plans, CONFIG, _now()) == []


def test_slots_planned_below_95_percent_of_the_limit_do_not_count() -> None:
    rows, plans = _data(30, 4.5, 2.0)
    assert bw.power_shortfall_warning(rows, plans, CONFIG, _now()) == []


def test_slots_older_than_fourteen_days_do_not_count() -> None:
    rows, plans = _data(30, 5.0, 3.5)
    later = _now() + timedelta(days=10)
    assert bw.power_shortfall_warning(rows, plans, CONFIG, later) == []


def test_slots_without_measured_battery_values_do_not_count() -> None:
    rows, plans = _data(30, 5.0, 3.5)
    for row in rows[:15]:
        row["batt_charge_kwh"] = None
    for row in rows[15:]:
        row["quality_flags"] = flags(battery_method="snapshot")
    assert bw.power_shortfall_warning(rows, plans, CONFIG, _now()) == []


def test_limit_is_the_configured_one_and_constants_are_pinned() -> None:
    rows, plans = _data(30, 5.0, 3.5)
    lower = _config(max_charge_power_kw=1.0, max_discharge_power_kw=1.0)
    [warning] = bw.power_shortfall_warning(rows, plans, lower, _now())
    assert warning.limit_kw == 1.0
    assert bw.POWER_MIN_SLOTS == 20 and bw.POWER_PLANNED_SHARE == 0.95
    assert bw.POWER_DELIVERED_SHARE == 0.8 and bw.POWER_WINDOW_DAYS == 14
