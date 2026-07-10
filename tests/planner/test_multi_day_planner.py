"""Tests for the load-agnostic MultiDayPlanner."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytz

from planner.strategy.multi_day_planner import MultiDayPlanner


TZ = pytz.timezone("Europe/Stockholm")


def _deadline(days_out: int) -> datetime:
    now = datetime.now(TZ)
    naive = (now + timedelta(days=days_out)).replace(
        hour=7, minute=0, second=0, microsecond=0, tzinfo=None
    )
    return TZ.localize(naive)


def test_inverse_price_allocation() -> None:
    deadline = _deadline(2)
    prices = {0: 1.5, 1: 0.5, 2: 1.0}
    max_daily = [100.0, 100.0, 100.0]
    quota = MultiDayPlanner.compute_quota(60.0, deadline, prices, max_daily)

    assert len(quota) == 3
    # Day 1 (cheapest) should receive the largest share.
    assert quota[(date.today() + timedelta(days=1))] > quota[date.today()]
    assert quota[(date.today() + timedelta(days=1))] > quota[(date.today() + timedelta(days=2))]
    assert sum(quota.values()) == pytest.approx(60.0)


def test_min_daily_fraction_enforced() -> None:
    deadline = _deadline(2)
    prices = {0: 3.0, 1: 3.0, 2: 0.1}
    max_daily = [100.0, 100.0, 100.0]
    quota = MultiDayPlanner.compute_quota(60.0, deadline, prices, max_daily)

    today = date.today()
    assert quota[today] >= 6.0
    assert quota[today + timedelta(days=1)] >= 6.0
    assert sum(quota.values()) == pytest.approx(60.0)


def test_power_cap_redistributes() -> None:
    deadline = _deadline(2)
    prices = {0: 0.5, 1: 1.5, 2: 1.5}
    # Today can only accept 10 kWh.
    max_daily = [10.0, 100.0, 100.0]
    quota = MultiDayPlanner.compute_quota(60.0, deadline, prices, max_daily)

    today = date.today()
    assert quota[today] <= 10.0
    assert sum(quota.values()) == pytest.approx(60.0)


def test_single_day_all_energy() -> None:
    frozen_now = datetime(2026, 7, 8, 10, 0, 0, tzinfo=TZ)
    deadline = frozen_now + timedelta(hours=6)
    quota = MultiDayPlanner.compute_quota(40.0, deadline, {}, [100.0], now=frozen_now)

    assert len(quota) == 1
    assert quota[frozen_now.date()] == pytest.approx(40.0)


def test_zero_remaining() -> None:
    deadline = _deadline(2)
    quota = MultiDayPlanner.compute_quota(0.0, deadline, {0: 1.0, 1: 1.0}, [10.0, 10.0])
    assert quota == {}


def test_equal_prices_equal_split() -> None:
    deadline = _deadline(2)
    prices = {0: 1.0, 1: 1.0, 2: 1.0}
    max_daily = [100.0, 100.0, 100.0]
    quota = MultiDayPlanner.compute_quota(60.0, deadline, prices, max_daily)

    values = list(quota.values())
    assert values[0] == pytest.approx(20.0, abs=0.01)
    assert values[1] == pytest.approx(20.0, abs=0.01)
    assert values[2] == pytest.approx(20.0, abs=0.01)


def test_partial_price_data_fills_with_average() -> None:
    deadline = _deadline(4)
    prices = {0: 1.0, 1: 2.0, 2: 3.0}  # days 3 and 4 missing
    max_daily = [100.0, 100.0, 100.0, 100.0, 100.0]
    quota = MultiDayPlanner.compute_quota(100.0, deadline, prices, max_daily)

    assert len(quota) == 5
    assert sum(quota.values()) == pytest.approx(100.0)


def test_today_cheapest_gets_largest_quota() -> None:
    """When today's (offset 0) real price is the cheapest, day 0 gets the
    largest share — validates the day-0 real-price fix is actually usable by
    the allocator (a filled-in average would never make day 0 the cheapest
    when it's set to 0.2 and the others are 1.0-1.5)."""
    deadline = _deadline(2)
    prices = {0: 0.2, 1: 1.5, 2: 1.0}
    max_daily = [100.0, 100.0, 100.0]
    quota = MultiDayPlanner.compute_quota(60.0, deadline, prices, max_daily)

    today = date.today()
    assert quota[today] > quota[today + timedelta(days=1)]
    assert quota[today] > quota[today + timedelta(days=2)]
    assert sum(quota.values()) == pytest.approx(60.0)


def test_clamping_when_floors_exceed_later_day_capacity() -> None:
    """Extreme case: every day's physical cap is smaller than an equal split
    would allocate. The result must clamp to each day's cap and sum to <=
    remaining_kwh — never negative, never above a day's physical max."""
    deadline = _deadline(2)
    prices = {0: 1.0, 1: 1.0, 2: 1.0}
    max_daily = [2.0, 2.0, 2.0]  # only 6 kWh total deliverable, 60 requested
    quota = MultiDayPlanner.compute_quota(60.0, deadline, prices, max_daily)

    assert all(0.0 <= v <= 2.0 + 1e-6 for v in quota.values())
    assert sum(quota.values()) <= 60.0 + 1e-6
    assert sum(quota.values()) == pytest.approx(6.0, abs=0.5)


import pytest
