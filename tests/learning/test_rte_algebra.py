"""Algebra and edge cases of the SoC-corrected round-trip efficiency formula."""

import math

import pytest

from backend.learning import battery_estimators as be
from tests.learning.battery_synth import CAPACITY_KWH, after, make_rows


def _residual(charge: float, discharge: float, change: float, rte: float) -> float:
    root = math.sqrt(rte)
    return charge * root - discharge / root - change


@pytest.mark.parametrize(
    ("charge", "discharge", "change"),
    [
        (832.0, 800.0, 0.0),
        (832.0, 800.0, 15.0),  # battery gained energy
        (832.0, 800.0, -15.0),  # battery lost energy (negative dS)
        (100.0, 90.0, 40.0),
        (100.0, 90.0, -40.0),
    ],
)
def test_result_satisfies_the_stored_energy_balance(
    charge: float, discharge: float, change: float
) -> None:
    value = be._rte_value(charge, discharge, change)

    assert value is not None
    assert _residual(charge, discharge, change, value) == pytest.approx(0.0, abs=1e-9)


def test_soc_neutral_pool_is_the_plain_ratio() -> None:
    assert be._rte_value(832.0, 800.0, 0.0) == pytest.approx(800.0 / 832.0)


def test_gain_raises_and_loss_lowers_the_estimate_against_the_plain_ratio() -> None:
    """Energy kept in the battery is not a loss; energy drawn from it is not free."""
    plain = 800.0 / 832.0
    gained = be._rte_value(832.0, 800.0, 15.0)
    lost = be._rte_value(832.0, 800.0, -15.0)

    assert gained is not None
    assert lost is not None
    assert gained > plain > lost


@pytest.mark.parametrize("charge", [0.0, -1.0])
def test_no_charge_gives_no_value(charge: float) -> None:
    assert be._rte_value(charge, 10.0, 0.0) is None


def test_negative_discharge_gives_no_value() -> None:
    assert be._rte_value(10.0, -1.0, 0.0) is None


def test_no_discharge_never_divides_by_zero() -> None:
    assert be._rte_value(100.0, 0.0, 0.0) == 0.0
    assert be._rte_value(100.0, 0.0, 10.0) == pytest.approx(0.01)
    assert be._rte_value(100.0, 0.0, -10.0) == 0.0  # clamps to zero, never negative or NaN


def test_large_negative_change_stays_finite_and_nonnegative() -> None:
    value = be._rte_value(1.0, 1.0, -1e9)

    assert value is not None
    assert math.isfinite(value)
    assert value >= 0.0


def test_idle_battery_is_rejected_without_error() -> None:
    rows = make_rows(40, daily_charge_kwh=0.0)
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(40))

    assert not estimate.accepted
    assert estimate.value is None


def test_negative_capacity_is_rejected() -> None:
    estimate = be.estimate_round_trip_efficiency(make_rows(40), -5.0, after(40))

    assert not estimate.accepted
    assert estimate.rejected_reason is not None
    assert "capacity" in estimate.rejected_reason


def test_a_falling_soc_is_corrected_too() -> None:
    rows = make_rows(40, start_soc=90.0, discharge_scale_for_day=lambda _: 1.03)
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH, after(40))

    assert estimate.evidence["soc_correction_kwh"] < 0
    assert estimate.accepted
    assert estimate.value == pytest.approx(0.962, abs=0.003)


def test_an_oversized_configured_capacity_hits_the_correction_bound() -> None:
    rows = make_rows(40, start_soc=90.0, discharge_scale_for_day=lambda _: 1.06)
    estimate = be.estimate_round_trip_efficiency(rows, CAPACITY_KWH * 3, after(40))

    assert not estimate.accepted
    assert estimate.rejected_reason is not None
    assert "net charge change" in estimate.rejected_reason
    assert estimate.evidence["soc_correction_share"] > be.RTE_MAX_SOC_CORRECTION_SHARE
