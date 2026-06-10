"""Tests for planner.simulation.simulate_schedule."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from planner.simulation import simulate_schedule


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame indexed by start_time with end_time column."""
    start = datetime(2025, 1, 1, 12, 0)
    records = []
    for i, r in enumerate(rows):
        slot_start = start + timedelta(minutes=15 * i)
        slot_end = start + timedelta(minutes=15 * (i + 1))
        records.append({"end_time": slot_end, **r})
    df = pd.DataFrame(records, index=[start + timedelta(minutes=15 * i) for i in range(len(rows))])
    return df


def test_pv_sourced_charge_raises_soc():
    """battery_charge_kw (from PV) increases projected SoC, not the grid-only charge_kw."""
    df = _make_df([
        # PV charges battery 2 kW for 15 min = 0.5 kWh
        # grid-only charge_kw = 0 (PV only); battery_charge_kw = 2.0
        {"battery_charge_kw": 2.0, "charge_kw": 0.0, "discharge_kw": 0.0},
    ])

    config = {
        "battery": {
            "capacity_kwh": 10.0,
            "min_soc_percent": 0.0,
            "max_soc_percent": 100.0,
            "roundtrip_efficiency_percent": 100.0,
        }
    }
    initial_state = {"battery_soc_kwh": 2.0}

    result = simulate_schedule(df, config, initial_state)

    # SoC should increase from 2.0 to 2.5 kWh (2kW × 0.25h, efficiency=1)
    assert result["projected_soc_kwh"].iloc[0] == pytest.approx(2.5, abs=0.01)
    assert result["projected_soc_percent"].iloc[0] == pytest.approx(25.0, abs=0.1)


def test_soc_projection_respects_min_soc_band():
    """Projection clamps at min_soc_kwh, not zero."""
    df = _make_df([
        # Heavy discharge that would go below min SoC
        {"battery_charge_kw": 0.0, "charge_kw": 0.0, "discharge_kw": 10.0},
    ])

    config = {
        "battery": {
            "capacity_kwh": 10.0,
            "min_soc_percent": 10.0,  # min = 1.0 kWh
            "max_soc_percent": 100.0,
            "roundtrip_efficiency_percent": 100.0,
        }
    }
    initial_state = {"battery_soc_kwh": 3.0}

    result = simulate_schedule(df, config, initial_state)

    # Should be clamped at 10% = 1.0 kWh, not go below
    assert result["projected_soc_kwh"].iloc[0] >= 1.0 - 0.01


def test_soc_projection_respects_max_soc_band():
    """Projection clamps at max_soc_kwh (max_soc_percent), not capacity."""
    df = _make_df([
        # Charge from near-full — would exceed max_soc cap
        {"battery_charge_kw": 10.0, "charge_kw": 5.0, "discharge_kw": 0.0},
    ])

    config = {
        "battery": {
            "capacity_kwh": 10.0,
            "min_soc_percent": 0.0,
            "max_soc_percent": 80.0,  # max = 8.0 kWh
            "roundtrip_efficiency_percent": 100.0,
        }
    }
    initial_state = {"battery_soc_kwh": 7.5}  # starts at 75%

    result = simulate_schedule(df, config, initial_state)

    # Should be clamped at 80% = 8.0 kWh
    assert result["projected_soc_kwh"].iloc[0] <= 8.0 + 0.01
    assert result["projected_soc_percent"].iloc[0] <= 80.0 + 0.1
