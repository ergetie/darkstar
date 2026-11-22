"""Round-trip efficiency from runs of contiguous eligible slots, corrected for net SoC change."""

import copy
import json
from datetime import datetime, time, timedelta

import pytest

from backend.learning import battery_estimators as be
from tests.learning.battery_synth import (
    CAPACITY_KWH,
    FIRST_DAY,
    SLOTS_PER_DAY,
    TZ,
    after,
    make_rows,
)

TRUE_RTE = 0.962


def swinging(day: int) -> float:
    """Discharge 50 % under, then 50 % over the neutral amount: SoC swings about 40 pp."""
    return 0.5 if day % 4 in (0, 1) else 1.5


def test_recovers_true_efficiency_from_35_days() -> None:
    estimate = be.estimate_round_trip_efficiency(make_rows(35), CAPACITY_KWH, after(35))

    assert estimate.accepted
    assert estimate.value == pytest.approx(TRUE_RTE, abs=0.001)
    assert estimate.confidence == pytest.approx(35 / be.RTE_CONFIDENCE_FULL_DAYS, abs=0.01)
    assert estimate.evidence["days"] == pytest.approx(35, abs=0.1)
    assert estimate.evidence["runs"] == 1
    assert estimate.evidence["window_start"] >= FIRST_DAY.isoformat()


def test_twenty_days_report_the_shortfall() -> None:
    estimate = be.estimate_round_trip_efficiency(make_rows(20), CAPACITY_KWH, after(20))

    assert not estimate.accepted
    assert estimate.value is None
    assert estimate.rejected_reason is not None
    assert "28" in estimate.rejected_reason
    assert estimate.evidence["days"] < 28


def test_days_that_are_not_soc_neutral_still_recover_the_true_value() -> None:
    rows = make_rows(42, discharge_scale_for_day=swinging)
    socs = [row["soc_end_percent"] for row in rows]
    assert max(socs) - min(socs) > 30  # every 7-day chunk ends far from where it started

    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(42))

    assert estimate.accepted
    assert estimate.value == pytest.approx(TRUE_RTE, abs=0.002)


def test_a_net_soc_drift_is_corrected() -> None:
    rows = make_rows(40, discharge_scale_for_day=lambda _: 0.97)  # battery fills up over time
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(40))

    assert estimate.evidence["soc_correction_share"] > 0.02
    assert estimate.accepted
    assert estimate.value == pytest.approx(TRUE_RTE, abs=0.003)
    plain = estimate.evidence["discharge_kwh"] / estimate.evidence["charge_kwh"]
    assert abs(plain - TRUE_RTE) > 0.02  # the plain ratio would be clearly biased


def test_correction_is_bounded_when_the_capacity_is_far_off() -> None:
    rows = make_rows(60, start_soc=10.0, discharge_scale_for_day=lambda _: 0.97)
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH * 4, after(60))

    assert not estimate.accepted
    assert estimate.rejected_reason is not None
    assert "net charge change" in estimate.rejected_reason


def test_gaps_and_unusable_slots_only_split_runs() -> None:
    rows = make_rows(50, discharge_scale_for_day=swinging)
    for day in (6, 13, 21, 29, 37, 44):  # one lost slot per week, as in recorded data
        rows[SLOTS_PER_DAY * day + 40]["batt_discharge_kwh"] = None
    del rows[SLOTS_PER_DAY * 17 + 10 : SLOTS_PER_DAY * 17 + 14]
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(50))

    assert estimate.accepted
    assert estimate.value == pytest.approx(TRUE_RTE, abs=0.003)
    assert estimate.evidence["runs"] >= 7
    assert 40 <= estimate.evidence["days"] <= 50


def test_window_with_null_discharge_is_dropped_not_counted_as_zero() -> None:
    rows = make_rows(45)
    full = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(45))
    rows[96 * 20 + 70]["batt_discharge_kwh"] = None
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(45))

    assert estimate.accepted
    assert estimate.value == pytest.approx(TRUE_RTE, abs=0.001)
    assert estimate.evidence["runs"] == 2
    assert estimate.evidence["days"] < full.evidence["days"]
    assert estimate.evidence["discharge_kwh"] < full.evidence["discharge_kwh"]


def test_old_unrecorded_history_and_a_mid_day_as_of_still_learn() -> None:
    """Shape of the production failure: only the recent part of the history is eligible.

    The first 70 days carry no provenance (not eligible), the rest has a lost slot most
    days and a SoC that swings by tens of points, and ``as_of`` falls mid-afternoon so
    no whole local day is complete anywhere.
    """
    rows = make_rows(120, discharge_scale_for_day=swinging)
    for row in rows[: SLOTS_PER_DAY * 70]:
        row["quality_flags"] = json.dumps({})
    for day in range(72, 118):
        if day % 3:
            rows[SLOTS_PER_DAY * day + 5 + day]["batt_charge_kwh"] = None
    as_of = TZ.localize(
        datetime.combine(
            FIRST_DAY + timedelta(days=118), time(17, 0)
        )
    )
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, as_of)

    assert estimate.accepted, estimate.rejected_reason
    assert estimate.value == pytest.approx(TRUE_RTE, abs=0.004)
    assert estimate.confidence >= be.MIN_CONFIDENCE
    assert estimate.evidence["days"] >= 28


def test_estimate_unchanged_by_rows_after_as_of() -> None:
    rows = make_rows(40)
    as_of = after(35)
    base = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, as_of)
    future = copy.deepcopy(rows)
    for row in future[96 * 35 :]:
        row["batt_discharge_kwh"] = 5.0
    changed = be.estimate_round_trip_efficiency(future, CAPACITY_KWH, as_of)

    assert base.value == changed.value
    assert base.evidence == changed.evidence


def test_out_of_bounds_value_is_rejected_not_clamped() -> None:
    estimate = be.estimate_round_trip_efficiency(make_rows(35, rte=0.70), CAPACITY_KWH, after(35))

    assert not estimate.accepted
    assert estimate.value == pytest.approx(0.70, abs=0.001)
    assert estimate.rejected_reason is not None
    assert "outside" in estimate.rejected_reason


def test_missing_capacity_is_rejected() -> None:
    estimate = be.estimate_round_trip_efficiency(make_rows(35), 0.0, after(35))
    assert not estimate.accepted


def test_a_missing_day_splits_the_run() -> None:
    rows = make_rows(40)
    del rows[96 * 18 : 96 * 19]
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(40))

    assert estimate.value == pytest.approx(TRUE_RTE, abs=0.001)
    assert estimate.evidence["runs"] == 2
    assert estimate.evidence["days"] <= 39


def test_inconsistent_chunks_lower_the_confidence() -> None:
    rows = make_rows(42)
    for row in rows[96 * 7 : 96 * 14]:  # one week with 10 % of the discharge missing
        row["batt_discharge_kwh"] *= 0.9
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(42))

    assert estimate.confidence < 0.5
    assert not estimate.accepted


def test_lookback_limits_old_data() -> None:
    estimate = be.estimate_round_trip_efficiency(make_rows(200), CAPACITY_KWH, after(200))

    assert estimate.evidence["days"] <= be.RTE_LOOKBACK_DAYS
    oldest = FIRST_DAY + timedelta(days=200 - be.RTE_LOOKBACK_DAYS - 1)  # DST hour
    assert estimate.evidence["window_start"] >= oldest.isoformat()
