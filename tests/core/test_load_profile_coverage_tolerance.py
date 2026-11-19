"""A slot measured exactly once must count as supported despite float rounding.

The 7-day load-profile window starts off the 15-minute grid, so each local slot's
covered seconds are the sum of two interval pieces. For a sensor with a single day of
history that sum is 900 s give or take float error; 899.9999... used to fail the
">= 900" check, dropping roughly a quarter of the measured slots.
"""

import random
from datetime import datetime, timedelta

import pytz

from backend.core.ha_client import (
    _SLOT_SECONDS,
    _coverage_averaged_profile,
    _distribute_interval_energy,
    integrate_power_points_covered,
)

TZ = pytz.timezone("Europe/Stockholm")


def _single_day_coverage(now_utc: datetime) -> tuple[int, int]:
    """Mimic _build_load_profile for a sensor that started reporting 10 h ago."""
    start_time = now_utc - timedelta(days=7)
    first = now_utc - timedelta(hours=10, seconds=7)
    rng = random.Random(42)  # HA power sensors report at irregular intervals
    points = []
    ts = first
    while ts < now_utc:
        points.append((ts, rng.uniform(0.3, 2.0)))
        ts += timedelta(seconds=rng.uniform(5.0, 15.0))

    sums = [0.0] * 96
    covered = [0.0] * 96
    for day in range(7):
        day_start = start_time + timedelta(days=day)
        day_end = day_start + timedelta(days=1)
        slot_start = day_start
        while slot_start < day_end:
            slot_end = min(slot_start + timedelta(seconds=_SLOT_SECONDS), day_end)
            result = integrate_power_points_covered(points, slot_start, slot_end)
            if result is not None:
                positive, _negative, seconds = result
                for target, amount in ((sums, positive), (covered, seconds)):
                    _distribute_interval_energy(
                        target,
                        slot_start,
                        slot_end,
                        amount,
                        TZ,
                        window_start=start_time,
                        window_end=now_utc,
                    )
            slot_start = slot_end

    fully_measured = sum(1 for c in covered if abs(c - _SLOT_SECONDS) < 1e-3)
    _profile, supported = _coverage_averaged_profile(sums, covered)
    return fully_measured, supported


def test_every_fully_measured_slot_is_supported():
    # Off-grid "now" (as in production) at several offsets.
    base = TZ.localize(datetime(2026, 11, 19, 21, 18, 22, 123456)).astimezone(pytz.UTC)
    for offset_s in (0, 37.5, 211.9, 444.4, 873.1):
        fully_measured, supported = _single_day_coverage(base + timedelta(seconds=offset_s))
        assert fully_measured >= 38
        assert supported >= fully_measured


def test_slot_just_below_full_by_float_error_is_supported():
    covered = [0.0] * 96
    sums = [0.0] * 96
    covered[10] = _SLOT_SECONDS - 1e-9
    sums[10] = 0.25
    _profile, supported = _coverage_averaged_profile(sums, covered)
    assert supported == 1


def test_clearly_partial_slot_is_not_supported():
    covered = [0.0] * 96
    sums = [0.0] * 96
    covered[10] = _SLOT_SECONDS - 1.0
    sums[10] = 0.25
    _profile, supported = _coverage_averaged_profile(sums, covered)
    assert supported == 0
