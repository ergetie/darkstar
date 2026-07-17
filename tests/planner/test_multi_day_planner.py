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


# ---------------------------------------------------------------------------
# Chunk-aware quota (min_chunk_kwh) — design D3/D4.
# ---------------------------------------------------------------------------


def test_sub_chunk_slices_consolidated_onto_cheaper_day() -> None:
    """Observed bug: 2.6 kWh over 2 days with chunk 2.425 must not strand a
    sub-chunk amount on each day — it should all land on the cheaper day."""
    deadline = _deadline(1)
    prices = {0: 2.0, 1: 1.0}  # tomorrow is cheaper
    max_daily = [100.0, 100.0]

    unconstrained = MultiDayPlanner.compute_quota(2.6, deadline, prices, max_daily)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    # Sanity: without the chunk constraint this reproduces the bug (both days
    # get a sub-chunk slice).
    assert 0 < unconstrained[today] < 2.425
    assert 0 < unconstrained[tomorrow] < 2.425

    quota = MultiDayPlanner.compute_quota(
        2.6, deadline, prices, max_daily, min_chunk_kwh=2.425
    )
    assert quota[today] == pytest.approx(0.0, abs=1e-6)
    assert quota[tomorrow] == pytest.approx(2.6, abs=1e-6)


def test_allocations_at_or_above_chunk_are_unchanged() -> None:
    """When every day's price-weighted allocation already meets the chunk,
    the chunk constraint must not alter the result."""
    deadline = _deadline(2)
    prices = {0: 1.0, 1: 1.0, 2: 1.0}
    max_daily = [100.0, 100.0, 100.0]

    unconstrained = MultiDayPlanner.compute_quota(60.0, deadline, prices, max_daily)
    quota = MultiDayPlanner.compute_quota(
        60.0, deadline, prices, max_daily, min_chunk_kwh=2.425
    )
    assert quota == pytest.approx(unconstrained)


def test_zero_chunk_disables_constraint() -> None:
    """min_chunk_kwh=0 (the default) must be byte-identical to calling
    without the parameter at all."""
    deadline = _deadline(2)
    prices = {0: 2.0, 1: 1.5, 2: 0.5}
    max_daily = [100.0, 100.0, 100.0]

    without_param = MultiDayPlanner.compute_quota(37.0, deadline, prices, max_daily)
    with_zero = MultiDayPlanner.compute_quota(
        37.0, deadline, prices, max_daily, min_chunk_kwh=0.0
    )
    assert with_zero == without_param


def test_sub_chunk_goal_floored_to_one_chunk() -> None:
    """A goal smaller than one chunk gets floored to exactly one chunk on the
    cheapest day, not an undeliverable sub-chunk allocation."""
    deadline = _deadline(2)
    prices = {0: 2.0, 1: 0.5, 2: 1.0}  # day 1 is cheapest
    max_daily = [100.0, 100.0, 100.0]

    quota = MultiDayPlanner.compute_quota(
        0.3, deadline, prices, max_daily, min_chunk_kwh=1.05
    )
    nonzero = {d: v for d, v in quota.items() if v > 1e-9}
    assert len(nonzero) == 1
    (day, value) = next(iter(nonzero.items()))
    assert value == pytest.approx(1.05)
    assert day == date.today() + timedelta(days=1)
    assert sum(quota.values()) <= 1.05 + 1e-6


def test_chunk_redistribution_never_exceeds_capacity_cap() -> None:
    """Redistributing sub-chunk energy must respect per-day capacity caps."""
    deadline = _deadline(1)
    prices = {0: 2.0, 1: 1.0}
    # Tomorrow (cheapest) has almost no headroom, forcing redistribution to
    # respect its cap instead of dumping everything there.
    max_daily = [100.0, 0.5]

    quota = MultiDayPlanner.compute_quota(2.6, deadline, prices, max_daily, min_chunk_kwh=2.425)
    for v, cap in zip(quota.values(), max_daily):
        assert v <= cap + 1e-6
        assert v <= 1e-9 or v >= 2.425 - 1e-9  # no day left below the chunk
    assert sum(quota.values()) <= 2.6 + 1e-6
    # Tomorrow's cap (0.5) is below the chunk, so the chunk lands on today.
    assert quota[date.today()] == pytest.approx(2.6)


def test_consolidation_drops_energy_when_no_day_can_hold_a_full_chunk() -> None:
    """If every day's cap is below the chunk, a day must never be left with a
    sub-chunk allocation the solver could never use — the energy is dropped
    (physically undeliverable this run) rather than stranded."""
    deadline = _deadline(1)
    prices = {0: 1.0, 1: 2.0}
    max_daily = [0.5, 0.5]  # both caps below the 1.0 kWh chunk

    quota = MultiDayPlanner.compute_quota(1.0, deadline, prices, max_daily, min_chunk_kwh=1.0)
    assert all(v <= 1e-9 for v in quota.values())


def test_sub_chunk_goal_yields_no_allocation_when_no_day_has_capacity() -> None:
    """D4 floor must not allocate a capacity-clamped (and therefore
    sub-chunk) amount when no day's cap can hold a full chunk."""
    deadline = _deadline(1)
    prices = {0: 1.0, 1: 2.0}
    max_daily = [0.3, 0.3]  # both caps below the 1.0 kWh chunk

    quota = MultiDayPlanner.compute_quota(0.2, deadline, prices, max_daily, min_chunk_kwh=1.0)
    assert all(v <= 1e-9 for v in quota.values())


import pytest
