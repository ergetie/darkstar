"""Capacity-change warning: weekly implied capacity against its rolling baseline."""

import copy
from dataclasses import asdict

import pytest

from backend.learning import battery_warnings as bw
from tests.backend.test_battery_benchmark import _config
from tests.learning.battery_synth import after, capacity_rows

CONFIG = _config(capacity_kwh=34.0)
DAYS = 75  # latest week = days 68..74, previous week = days 61..67, baseline before day 61


def _warn(rows, days=DAYS, config=CONFIG):
    return bw.capacity_change_warning(rows, config, after(days))


def test_module_outage_warns_with_both_values() -> None:
    rows = capacity_rows(DAYS, lambda i: 34.0 if i < 61 else 19.0)

    warning = _warn(rows)

    assert warning is not None
    assert warning.baseline_kwh == pytest.approx(34.0, rel=0.02)
    assert warning.latest_kwh[0] == pytest.approx(19.0, rel=0.02)
    assert warning.latest_kwh[1] == pytest.approx(19.0, rel=0.02)
    assert warning.configured_kwh == 34.0


def test_winter_shift_of_twenty_percent_does_not_warn() -> None:
    assert _warn(capacity_rows(DAYS, lambda i: 34.0 if i < 61 else 34.0 * 1.2)) is None


def test_fewer_than_four_baseline_windows_does_not_warn() -> None:
    # 14 days of change plus 21 days of baseline: only 3 baseline weeks.
    rows = capacity_rows(35, lambda i: 34.0 if i < 21 else 19.0)
    assert _warn(rows, days=35) is None


def test_single_bad_window_does_not_warn() -> None:
    rows = capacity_rows(DAYS, lambda i: 19.0 if i >= 68 else 34.0)
    assert _warn(rows) is None


def test_no_change_gives_no_warning() -> None:
    assert _warn(capacity_rows(DAYS, lambda _i: 34.0)) is None


def test_window_without_soc_swing_is_not_valid() -> None:
    rows = capacity_rows(DAYS, lambda _i: 34.0, daily_kwh=1.0)  # ~3 pp swing
    assert all(c is None for c in bw.window_capacities(rows, CONFIG, after(DAYS)))
    assert _warn(rows) is None


def test_nothing_is_changed_by_the_check() -> None:
    rows = capacity_rows(DAYS, lambda i: 34.0 if i < 61 else 19.0)
    before_rows = copy.deepcopy(rows)
    before_config = asdict(CONFIG)

    assert _warn(rows) is not None

    assert rows == before_rows
    assert asdict(CONFIG) == before_config
    assert CONFIG.capacity_kwh == 34.0


def test_effective_efficiencies_are_used_for_the_fit() -> None:
    lossy = _config(capacity_kwh=34.0, charge_efficiency=0.9, discharge_efficiency=0.9)
    rows = capacity_rows(DAYS, lambda _i: 34.0)
    plain = bw.window_capacities(rows, CONFIG, after(DAYS))[0]
    adjusted = bw.window_capacities(rows, lossy, after(DAYS))[0]

    assert plain is not None and adjusted is not None
    assert plain != pytest.approx(adjusted, rel=0.01)


def test_pinned_constants() -> None:
    assert bw.CAPACITY_WINDOW_DAYS == 7
    assert bw.CAPACITY_BASELINE_WINDOWS == 8
    assert bw.CAPACITY_BASELINE_MIN_VALID == 4
    assert bw.CAPACITY_CHANGE_THRESHOLD == 0.25
    assert bw.CAPACITY_WINDOW_MIN_DAYS == 4
