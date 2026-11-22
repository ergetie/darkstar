"""Robust inverter loss fit (standby power and AC-side charge loss)."""

import json
from datetime import timedelta

import pytest

from backend.learning import battery_estimators as be
from tests.learning.battery_synth import CAPACITY_KWH, FIRST_DAY, after, flags, make_rows

STORED_ELL = 0.075 / 1.075  # 0.0698


def _estimate(rows, sensor=None, days=30):
    return be.estimate_inverter_loss(rows, sensor, CAPACITY_KWH, after(days))


def test_recovers_standby_and_ac_side_charge_loss_with_noise_and_outliers() -> None:
    result = _estimate(make_rows(30, outlier_share=0.03))

    assert result.charge_loss.accepted
    assert result.charge_loss.value == pytest.approx(STORED_ELL, abs=0.01)
    assert result.standby_w.accepted
    assert result.standby_w.value == pytest.approx(60.0, abs=10.0)
    assert result.charge_loss.evidence["slots"] == 30 * 96


def test_conversion_is_k_over_one_plus_k_not_one_minus_k() -> None:
    result = _estimate(make_rows(30, charge_loss_k=0.10))

    assert result.charge_loss.value == pytest.approx(0.10 / 1.10, abs=0.005)
    assert abs(result.charge_loss.value - 0.10) > 0.005


def test_flagged_slots_are_excluded_from_the_fit() -> None:
    rows = make_rows(30)
    flagged = flags({"base_load": {"reliable": False, "reasons": ["negative_after_subtraction"]}})
    for row in rows[: 96 * 10]:
        row["quality_flags"] = flagged
        row["import_kwh"] += 2.0  # would bias the fit badly if used
    result = _estimate(rows)

    assert result.charge_loss.evidence["slots"] == 20 * 96
    assert result.charge_loss.value == pytest.approx(STORED_ELL, abs=0.01)


def test_unmeasured_device_slots_are_excluded() -> None:
    rows = make_rows(30)
    decoded = json.loads(rows[0]["quality_flags"])
    decoded["recording"]["components"]["ev"]["method"] = "unknown"
    for row in rows[:96]:
        row["quality_flags"] = json.dumps(decoded)
    assert _estimate(rows).charge_loss.evidence["slots"] == 29 * 96


def test_slot_gate_and_span_gate() -> None:
    few = _estimate(make_rows(8), days=8)
    assert not few.charge_loss.accepted
    assert "1000" in (few.charge_loss.rejected_reason or "")
    assert few.standby_w.rejected_reason == few.charge_loss.rejected_reason
    # Enough slots but only 12 days: the 14-day span gate applies.
    dense = _estimate(make_rows(12), days=12)
    assert not dense.charge_loss.accepted


def test_charge_energy_gate() -> None:
    result = _estimate(make_rows(30, daily_charge_kwh=1.0))

    assert not result.charge_loss.accepted
    assert "kWh charged" in (result.charge_loss.rejected_reason or "")


def test_sensor_value_replaces_the_residual() -> None:
    rows = make_rows(30)
    for row in rows[: 96 * 15]:
        row["import_kwh"] += 0.8  # balance residual is badly wrong here
    sensor = {
        row["slot_start"]: 60.0 / 1000 * 0.25 + 0.075 * row["batt_charge_kwh"]
        for row in rows[: 96 * 15]
    }
    with_sensor = _estimate(rows, sensor)
    without = _estimate(rows)

    assert with_sensor.charge_loss.evidence["sensor_slots"] == 96 * 15
    assert with_sensor.charge_loss.value == pytest.approx(STORED_ELL, abs=0.01)
    assert with_sensor.standby_w.value == pytest.approx(60.0, abs=10.0)
    assert not without.standby_w.accepted  # the wrong residual shows up as absurd standby


def test_out_of_bounds_standby_is_rejected() -> None:
    result = _estimate(make_rows(30, standby_w=400.0))

    assert not result.standby_w.accepted
    assert result.standby_w.value == pytest.approx(400.0, abs=15.0)
    assert result.charge_loss.accepted


def test_out_of_bounds_charge_loss_is_rejected() -> None:
    result = _estimate(make_rows(30, charge_loss_k=0.30))
    assert not result.charge_loss.accepted


def test_rows_after_as_of_are_ignored() -> None:
    rows = make_rows(40)
    cutoff = FIRST_DAY + timedelta(days=30)
    base = _estimate(rows, days=30)
    for row in rows:
        if row["slot_start"] >= cutoff.isoformat():
            row["import_kwh"] += 5.0
    assert _estimate(rows, days=30).charge_loss.value == base.charge_loss.value
