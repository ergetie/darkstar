"""Row eligibility for the RTE and inverter-loss estimators, and pinned constants."""

import json
from datetime import timedelta
from typing import Any

import pytest

from backend.learning import battery_estimators as be
from tests.learning.battery_synth import after, flags, make_rows


def _row(**overrides: Any) -> dict[str, Any]:
    row = make_rows(1)[40]
    row.update(overrides)
    return row


AS_OF = after(2)


def test_clean_row_is_eligible_for_both() -> None:
    assert be.rte_slot_eligible(_row(), AS_OF)
    assert be.loss_slot_eligible(_row(), AS_OF)


def test_null_battery_value_is_not_eligible() -> None:
    assert not be.rte_slot_eligible(_row(batt_discharge_kwh=None), AS_OF)
    assert not be.loss_slot_eligible(_row(batt_charge_kwh=None), AS_OF)
    assert not be.rte_slot_eligible(_row(soc_end_percent=None), AS_OF)


def test_exclude_flag_is_not_eligible() -> None:
    row = _row(quality_flags=flags({"exclude": True}))
    assert not be.rte_slot_eligible(row, AS_OF)
    assert not be.loss_slot_eligible(row, AS_OF)


def test_unreliable_base_load_only_blocks_the_loss_fit() -> None:
    row = _row(quality_flags=flags({"base_load": {"reliable": False, "reasons": ["x"]}}))
    assert be.rte_slot_eligible(row, AS_OF)
    assert not be.loss_slot_eligible(row, AS_OF)


def test_unmeasured_device_is_not_eligible_for_loss() -> None:
    decoded = json.loads(flags())
    decoded["recording"]["components"]["water"] = {"method": "unknown", "owner": "recorder"}
    row = _row(quality_flags=json.dumps(decoded))
    assert not be.loss_slot_eligible(row, AS_OF)


def test_snapshot_recording_is_not_eligible() -> None:
    row = _row(quality_flags=flags(battery_method="snapshot"))
    assert not be.rte_slot_eligible(row, AS_OF)
    assert not be.loss_slot_eligible(row, AS_OF)


def test_future_slot_is_not_eligible() -> None:
    row = _row()
    assert not be.rte_slot_eligible(row, after(0))
    assert not be.loss_slot_eligible(row, after(0) + timedelta(hours=10))


def test_missing_or_malformed_flags_are_not_eligible() -> None:
    assert not be.rte_slot_eligible(_row(quality_flags=None), AS_OF)
    assert not be.loss_slot_eligible(_row(quality_flags="{not json"), AS_OF)


def test_balance_residual_matches_formula() -> None:
    row = _row(
        pv_kwh=1.0,
        import_kwh=2.0,
        batt_discharge_kwh=0.5,
        load_kwh=1.0,
        ev_charging_kwh=0.25,
        water_kwh=0.25,
        export_kwh=0.5,
        batt_charge_kwh=1.0,
    )
    assert be.balance_residual_kwh(row) == pytest.approx(3.5 - 3.0)


def test_pinned_constants() -> None:
    assert be.RTE_BOUNDS == (0.80, 0.995)
    assert be.CHARGE_LOSS_BOUNDS == (0.0, 0.15)
    assert be.STANDBY_W_BOUNDS == (0.0, 300.0)
    assert be.DISCHARGE_EFFICIENCY_BOUNDS == (0.85, 1.0)
    assert be.RTE_LOOKBACK_DAYS == 120
    assert be.RTE_MIN_RUN_DAYS == 1.0
    assert be.RTE_CHUNK_DAYS == 7.0
    assert be.RTE_MAX_SOC_CORRECTION_SHARE == 0.10
    assert be.RTE_MIN_POOLED_DAYS == 28
    assert be.RTE_MIN_DISCHARGE_CAPACITIES == 5.0
    assert be.RTE_CONFIDENCE_TOLERANCE == 0.03
    assert be.RTE_CONFIDENCE_FULL_DAYS == 42
    assert be.LOSS_LOOKBACK_DAYS == 120
    assert be.LOSS_MIN_SLOTS == 1000
    assert be.LOSS_MIN_SPAN_DAYS == 14
    assert be.LOSS_MIN_CHARGE_CAPACITIES == 2.0
    assert be.LOSS_CONFIDENCE_TOLERANCE == 0.03
    assert be.LOSS_CONFIDENCE_FULL_SLOTS == 2000
    assert be.HUBER_ITERATIONS == 20
    assert be.MIN_CONFIDENCE == 0.5
