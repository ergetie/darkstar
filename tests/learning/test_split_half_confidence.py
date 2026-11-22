"""Split-half confidence and the acceptance threshold in both estimators."""

import pytest

from backend.learning import battery_estimators as be
from tests.learning.battery_synth import CAPACITY_KWH, after, make_rows


def test_consistent_halves_with_full_data_give_confidence_one() -> None:
    assert be.split_half_confidence(0.962, 0.962, 2000, 2000, 0.03) == pytest.approx(1.0)


def test_halves_one_tolerance_apart_give_zero() -> None:
    assert be.split_half_confidence(0.95, 0.98, 5000, 2000, 0.03) == pytest.approx(0.0)


def test_small_data_scales_confidence_down() -> None:
    assert be.split_half_confidence(0.962, 0.962, 1000, 2000, 0.03) == pytest.approx(0.5)


def test_missing_half_gives_zero() -> None:
    assert be.split_half_confidence(None, 0.9, 100, 100, 0.02) == 0.0


def test_low_confidence_rte_is_rejected_with_a_reason() -> None:
    # Efficiency drifts between the first and second half of the period.
    rows = make_rows(21, rte=0.93) + make_rows(21, rte=0.99, first_day=after(21).date())
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(42))

    assert not estimate.accepted
    assert estimate.confidence < be.MIN_CONFIDENCE
    assert estimate.rejected_reason is not None
    assert "confidence" in estimate.rejected_reason
    assert estimate.value is not None


def test_low_confidence_loss_is_rejected_with_a_reason() -> None:
    first = make_rows(15, charge_loss_k=0.02)
    second = make_rows(15, charge_loss_k=0.12, first_day=after(15).date())
    result = be.estimate_inverter_loss(first + second, None, CAPACITY_KWH, after(30))

    assert not result.charge_loss.accepted
    assert "confidence" in (result.charge_loss.rejected_reason or "")
