"""Shared PV slot cleaning rules."""

import pandas as pd
import pytest

from backend.learning.pv_cleaning import clean_pv_slots

LAT, LON = 59.3, 18.1
TZ = "Europe/Stockholm"
SITE = {"total_kwp": 10.0, "latitude": LAT, "longitude": LON}


def _day(date: str, **columns) -> pd.DataFrame:
    """A full local day of quarter-hour slots with a daytime baseline, overridden per column."""
    # Local midnight to next local midnight in UTC, so DST days have 92/100 slots.
    start = pd.Timestamp(date, tz=TZ).tz_convert("UTC")
    end = (pd.Timestamp(date) + pd.Timedelta(days=1)).tz_localize(TZ).tz_convert("UTC")
    idx = pd.date_range(start, end, freq="15min", inclusive="left").tz_convert(TZ)
    df = pd.DataFrame(
        {
            "slot_start": idx,
            "pv_kwh": 0.0,
            "baseline_kwh": 0.0,
            "soc_end_percent": 50.0,
            "export_kwh": 0.5,
        }
    )
    for key, value in columns.items():
        df[key] = value
    return df


def _slot(hour: int, minute: int = 0, **values) -> pd.DataFrame:
    row = {
        "slot_start": pd.Timestamp(2026, 6, 15, hour, minute, tz=TZ),
        "pv_kwh": 1.0,
        "baseline_kwh": 1.0,
        "soc_end_percent": 50.0,
        "export_kwh": 0.5,
    }
    row.update(values)
    return pd.DataFrame([row])


def _kept(df: pd.DataFrame, **site) -> int:
    return len(clean_pv_slots(df, **{**SITE, **site}))


def test_full_day_has_96_slots():
    assert len(_day("2026-06-15")) == 96


def test_shaded_zero_slot_with_small_baseline_is_kept():
    assert _kept(_slot(8, pv_kwh=0.0, baseline_kwh=0.2)) == 1


def test_night_slot_without_baseline_is_dropped():
    assert _kept(_slot(2, pv_kwh=0.0, baseline_kwh=0.0)) == 0


def test_dropout_is_dropped_but_shade_is_kept():
    assert _kept(_slot(10, pv_kwh=0.0, baseline_kwh=0.45)) == 0
    assert _kept(_slot(10, pv_kwh=0.0, baseline_kwh=0.2)) == 1


def test_spike_above_capacity_limit():
    # limit is 10 kWp * 0.25 h * 1.05 = 2.625 kWh
    assert _kept(_slot(12, pv_kwh=2.8, baseline_kwh=2.0)) == 0
    assert _kept(_slot(12, pv_kwh=2.6, baseline_kwh=2.0)) == 1


def test_spike_rule_skipped_without_capacity():
    assert _kept(_slot(12, pv_kwh=2.8, baseline_kwh=2.0), total_kwp=0.0) == 1


def test_production_at_night_is_dropped():
    assert _kept(_slot(2, pv_kwh=0.1, baseline_kwh=0.05)) == 0


def test_night_rule_skipped_without_location():
    assert _kept(_slot(2, pv_kwh=0.1, baseline_kwh=0.05), latitude=None, longitude=None) == 1


def test_curtailed_slot_dropped_only_with_full_battery_and_no_export():
    assert _kept(_slot(12, soc_end_percent=100.0, export_kwh=0.0, baseline_kwh=0.4)) == 0
    assert _kept(_slot(12, soc_end_percent=float("nan"), export_kwh=0.0, baseline_kwh=0.4)) == 1
    assert _kept(_slot(12, soc_end_percent=100.0, export_kwh=0.5, baseline_kwh=0.4)) == 1
    assert _kept(_slot(12, soc_end_percent=100.0, export_kwh=float("nan"), baseline_kwh=0.4)) == 1


def test_optional_columns_absent_skips_curtailment():
    df = _slot(12, soc_end_percent=100.0, export_kwh=0.0, baseline_kwh=0.4).drop(
        columns=["soc_end_percent", "export_kwh"]
    )
    assert _kept(df) == 1


def test_pv_far_above_baseline_but_within_cap_is_kept():
    assert _kept(_slot(12, pv_kwh=2.5, baseline_kwh=0.5)) == 1


def test_drop_counts_reported_per_rule():
    df = pd.concat(
        [_slot(10, pv_kwh=0.0, baseline_kwh=0.45), _slot(12, pv_kwh=2.8, baseline_kwh=2.0)],
        ignore_index=True,
    )
    result = clean_pv_slots(df, **SITE)
    assert result.empty
    assert result.attrs["dropped_by_rule"]["dropout"] == 1
    assert result.attrs["dropped_by_rule"]["spike"] == 1


def test_empty_frame_is_returned_empty():
    empty = _slot(12).iloc[0:0]
    assert clean_pv_slots(empty, **SITE).empty


@pytest.mark.parametrize(
    ("date", "slots"),
    [("2026-06-15", 96), ("2026-03-29", 92), ("2026-10-25", 100)],
)
def test_kept_count_is_the_same_on_dst_days(date, slots):
    # Daytime slots 10:00-13:45 local: baseline 0.5, pv 0.4 (kept); everything else night.
    df = _day(date)
    assert len(df) == slots
    local = df["slot_start"].dt.tz_convert(TZ)
    day = (local.dt.hour >= 10) & (local.dt.hour < 14)
    df.loc[day, ["pv_kwh", "baseline_kwh"]] = [0.4, 0.5]
    assert day.sum() == 16
    assert _kept(df) == 16
