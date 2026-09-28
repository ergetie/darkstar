"""Whole-horizon hybrid PV computation matches the previous per-slot loop."""

import math

import numpy as np
import pandas as pd
import pytest
import pytz

from ml.forward import _hybrid_pv_values, _sun_up_flags


def _reference_per_slot(
    raw_pred, baseline, sun_up, radiation, bound_fraction, weight, ceiling
):
    """The per-slot loop previously in ml.forward, kept verbatim as the reference."""
    out = []
    for pos in range(len(baseline)):
        ml_residual = float(raw_pred[pos])
        base = float(baseline[pos])
        max_residual = base * bound_fraction
        ml_residual = max(-max_residual, min(ml_residual, max_residual))
        ml_residual *= weight
        val = base + ml_residual
        if not sun_up[pos]:
            val = 0.0
        rad = None if radiation is None else radiation[pos]
        if rad is not None and rad < 1.0:
            val = 0.0
        val = max(0.0, val)
        if ceiling > 0.0:
            val = min(val, ceiling)
        out.append(val)
    return out


@pytest.fixture
def fixture_672():
    rng = np.random.default_rng(20260928)
    n = 672
    hours = (np.arange(n) * 0.25) % 24
    daylight = np.clip(np.sin((hours - 4) / 16 * np.pi), 0, None)
    baseline = daylight * 1.4 + rng.uniform(0, 0.05, n)
    baseline[::97] = 0.0
    radiation = daylight * 800 + rng.uniform(-2, 2, n)
    radiation[5::50] = np.nan
    sun_up = (hours >= 4) & (hours <= 21)
    preds = {q: rng.normal(0, 0.4, n) for q in ("p10", "p50", "p90")}
    return baseline, radiation, sun_up, preds


@pytest.mark.parametrize("ceiling", [0.0, 1.2])
@pytest.mark.parametrize("weight", [0.0, 0.37, 1.0])
def test_hybrid_pv_matches_per_slot_loop(fixture_672, ceiling, weight):
    baseline, radiation, sun_up, preds = fixture_672
    for raw in preds.values():
        expected = _reference_per_slot(raw, baseline, sun_up, radiation, 0.25, weight, ceiling)
        actual = _hybrid_pv_values(raw, baseline, sun_up, radiation, 0.25, weight, ceiling)
        assert actual.tolist() == expected

        # Smoothed output (what ends up in pv_p10/p50/p90) is identical too.
        smooth = lambda v: pd.Series(v).rolling(3, center=True, min_periods=1).mean()  # noqa: E731
        assert smooth(actual).equals(smooth(expected))


def test_hybrid_pv_without_radiation_column(fixture_672):
    baseline, _, sun_up, preds = fixture_672
    raw = preds["p50"]
    expected = _reference_per_slot(raw, baseline, sun_up, None, 0.25, 1.0, 0.0)
    assert _hybrid_pv_values(raw, baseline, sun_up, None, 0.25, 1.0, 0.0).tolist() == expected


def test_night_and_low_radiation_zeroed():
    baseline = np.array([1.0, 1.0, 1.0, 1.0])
    sun_up = np.array([False, True, True, True])
    radiation = np.array([500.0, 0.5, math.nan, 500.0])
    raw = np.array([0.1, 0.1, 0.1, 0.1])
    values = _hybrid_pv_values(raw, baseline, sun_up, radiation, 0.25, 1.0, 0.0)
    assert values.tolist() == [0.0, 0.0, 1.1, 1.1]


def test_negative_baseline_bound_matches_scalar():
    baseline = np.array([-0.4])
    raw = np.array([0.0])
    expected = _reference_per_slot(raw, baseline, [True], None, 0.25, 1.0, 0.0)
    assert _hybrid_pv_values(raw, baseline, np.array([True]), None, 0.25, 1.0, 0.0).tolist() == (
        expected
    )


def test_sun_up_flags_hour_fallback():
    slots = pd.Series(pd.date_range("2026-09-28", periods=96, freq="15min", tz=pytz.UTC))
    flags = _sun_up_flags(slots, None)
    assert flags.tolist() == [5 <= ts.hour < 22 for ts in slots]


def _same(actual, expected):
    """Element-wise equality treating NaN == NaN."""
    return len(actual) == len(expected) and all(
        (math.isnan(a) and math.isnan(e)) or a == e for a, e in zip(actual, expected, strict=True)
    )


@pytest.mark.parametrize("ceiling", [0.0, 1.2])
@pytest.mark.parametrize("weight", [0.0, 0.37, 1.0])
def test_nan_residual_matches_per_slot_loop(fixture_672, ceiling, weight):
    baseline, radiation, sun_up, preds = fixture_672
    for raw in preds.values():
        raw = raw.copy()
        raw[::7] = np.nan
        expected = _reference_per_slot(raw, baseline, sun_up, radiation, 0.25, weight, ceiling)
        actual = _hybrid_pv_values(raw, baseline, sun_up, radiation, 0.25, weight, ceiling)
        assert not np.isnan(actual).any()
        assert _same(actual.tolist(), expected)


def test_nan_residual_bounds_to_negative_max():
    baseline = np.array([1.0, 1.0])
    raw = np.array([math.nan, math.nan])
    values = _hybrid_pv_values(raw, baseline, np.array([True, True]), None, 0.25, 1.0, 0.0)
    assert values.tolist() == [0.75, 0.75]


@pytest.mark.parametrize("ceiling", [0.0, 1.2])
def test_nan_baseline_and_radiation_match_per_slot_loop(fixture_672, ceiling):
    baseline, radiation, sun_up, preds = fixture_672
    baseline = baseline.copy()
    baseline[3::11] = np.nan
    raw = preds["p50"].copy()
    raw[::5] = np.nan
    expected = _reference_per_slot(raw, baseline, sun_up, radiation, 0.25, 1.0, ceiling)
    actual = _hybrid_pv_values(raw, baseline, sun_up, radiation, 0.25, 1.0, ceiling)
    assert _same(actual.tolist(), expected)
