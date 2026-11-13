"""Tests for the pipeline result merge — index-aligned assignment with crash safety."""

import logging

import numpy as np
import pandas as pd
import pytest


def _do_merge(future_df: pd.DataFrame, result_df: pd.DataFrame, logger=None) -> pd.DataFrame:
    water_heating_series = (
        future_df["water_heating_kw"].copy() if "water_heating_kw" in future_df.columns else None
    )

    final_df = future_df.join(result_df, rsuffix="_kepler")

    if logger is not None and len(result_df) != len(future_df):
        logger.error(
            "Result merge length mismatch: result_df=%d, future_df=%d — "
            "possible duplicate timestamps in price input",
            len(result_df),
            len(future_df),
        )

    for col in result_df.columns:
        final_df[col] = result_df[col]

    if water_heating_series is not None:
        final_df["water_heating_kw"] = water_heating_series

    return final_df


def test_merge_normal_case():
    times = pd.date_range("2026-04-10 00:00", periods=96, freq="15min")
    future_df = pd.DataFrame(
        {
            "water_heating_kw": np.zeros(96),
            "battery_charge_kw": np.zeros(96),
        },
        index=times,
    )
    result_df = pd.DataFrame(
        {
            "battery_charge_kw": np.arange(96, dtype=float),
            "grid_import_kw": np.zeros(96),
        },
        index=times,
    )

    final_df = _do_merge(future_df, result_df)

    assert len(final_df) == 96
    np.testing.assert_array_equal(final_df["battery_charge_kw"].values, np.arange(96))


def test_merge_length_mismatch_index_aligned_no_valueerror():
    """When result_df has more rows than future_df (different planning horizon),
    index-aligned assignment populates matched rows and leaves unmatched as NaN — no ValueError.

    This mimics the scenario where Kepler processes fewer/different slots than
    the full future_df. The old positional .values assignment would crash;
    index-aligned assignment succeeds.
    """
    future_times = pd.date_range("2026-04-10 00:00", periods=96, freq="15min")
    future_df = pd.DataFrame(
        {
            "water_heating_kw": np.zeros(96),
            "battery_charge_kw": np.zeros(96),
        },
        index=future_times,
    )

    result_times = pd.date_range("2026-04-10 00:00", periods=48, freq="15min")
    result_df = pd.DataFrame(
        {
            "battery_charge_kw": np.arange(48, dtype=float),
            "grid_import_kw": np.zeros(48),
        },
        index=result_times,
    )

    final_df = _do_merge(future_df, result_df)

    assert len(final_df) == 96

    for col in ["battery_charge_kw", "grid_import_kw"]:
        assert col in final_df.columns

    assert final_df.loc[: result_times[-1], "battery_charge_kw"].notna().all()
    assert (
        final_df.loc[result_times[-1] + pd.Timedelta(minutes=15) :, "battery_charge_kw"]
        .isna()
        .all()
    )


def test_merge_length_mismatch_logged(caplog):
    """When result_df length differs from future_df, an error should be logged."""
    future_times = pd.date_range("2026-04-10 00:00", periods=96, freq="15min")
    future_df = pd.DataFrame(
        {
            "water_heating_kw": np.zeros(96),
            "battery_charge_kw": np.zeros(96),
        },
        index=future_times,
    )

    result_times = pd.date_range("2026-04-10 00:00", periods=48, freq="15min")
    result_df = pd.DataFrame(
        {
            "battery_charge_kw": np.arange(48, dtype=float),
            "grid_import_kw": np.zeros(48),
        },
        index=result_times,
    )

    logger = logging.getLogger("test.merge")

    with caplog.at_level(logging.ERROR, logger="test.merge"):
        _do_merge(future_df, result_df, logger=logger)

    assert any("Result merge length mismatch" in r.message for r in caplog.records)
