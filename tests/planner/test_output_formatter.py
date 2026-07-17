"""
Tests for planner output formatter - per-device EV charger data in schedule output.
"""

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from planner.output.formatter import dataframe_to_json_response
from planner.solver.adapter import kepler_result_to_dataframe
from planner.solver.types import KeplerResult, KeplerResultSlot


def _make_schedule_df(ev_chargers_col=None):
    """Build a minimal schedule DataFrame with optional ev_chargers column."""
    now = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
    times = pd.date_range(now, periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "start_time": times,
            "end_time": times + pd.Timedelta(hours=1),
            "battery_charge_kw": [0.0, 1.0, 0.0],
            "battery_discharge_kw": [0.0, 0.0, 2.0],
            "ev_charge_kw": [3.0, 0.0, 0.0],
            "grid_import_kw": [0.0, 1.0, 0.0],
            "grid_export_kw": [0.0, 0.0, 0.0],
            "pv_kw": [5.0, 4.0, 3.0],
            "water_heater_kw": [0.0, 0.0, 0.0],
            "import_price_sek_kwh": [0.5, 0.5, 0.5],
            "export_price_sek_kwh": [0.1, 0.1, 0.1],
        }
    )
    if ev_chargers_col is not None:
        df["ev_chargers"] = ev_chargers_col
    return df


class TestEvChargersInOutput:
    def test_per_device_breakdown_present(self):
        """Each slot should include ev_chargers dict with per-device kW."""
        ev_data = [
            {"charger_a": 3.0, "charger_b": 0.0},
            {"charger_a": 0.0, "charger_b": 0.0},
            {"charger_a": 0.0, "charger_b": 0.0},
        ]
        df = _make_schedule_df(ev_chargers_col=ev_data)
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        assert len(records) == 3
        assert records[0]["ev_chargers"] == {"charger_a": 3.0, "charger_b": 0.0}
        assert records[1]["ev_chargers"] == {"charger_a": 0.0, "charger_b": 0.0}

    def test_nan_ev_chargers_normalised_to_empty_dict(self):
        """NaN in ev_chargers column (non-solver rows) must become {}."""
        df = _make_schedule_df(ev_chargers_col=[float("nan"), None, float("nan")])
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        for record in records:
            assert record["ev_chargers"] == {}

    def test_missing_ev_chargers_column_produces_empty_dict(self):
        """When ev_chargers column is absent, output should still include {} per slot."""
        df = _make_schedule_df()
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        for record in records:
            assert record["ev_chargers"] == {}

    def test_aggregate_ev_charge_kw_preserved(self):
        """ev_charge_kw aggregate should still be present alongside ev_chargers."""
        ev_data = [{"charger_a": 3.0}, {"charger_a": 0.0}, {"charger_a": 0.0}]
        df = _make_schedule_df(ev_chargers_col=ev_data)
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        assert records[0]["ev_charge_kw"] == 3.0
        assert "ev_chargers" in records[0]

    def test_numpy_nan_in_ev_chargers_normalised(self):
        """numpy.nan values in ev_chargers column are also normalised to {}."""
        df = _make_schedule_df(ev_chargers_col=[np.nan, np.nan, np.nan])
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        for record in records:
            assert record["ev_chargers"] == {}

    def test_mixed_ev_chargers_column(self):
        """Mixed dict/NaN column: dicts pass through, NaN becomes {}."""
        ev_data = [{"charger_a": 2.5}, float("nan"), {"charger_a": 0.0}]
        df = _make_schedule_df(ev_chargers_col=ev_data)
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        assert records[0]["ev_chargers"] == {"charger_a": 2.5}
        assert records[1]["ev_chargers"] == {}
        assert records[2]["ev_chargers"] == {"charger_a": 0.0}


def _make_kepler_result_slot(start, end, ev_keep_on=None):
    return KeplerResultSlot(
        start_time=start,
        end_time=end,
        charge_kwh=0.0,
        discharge_kwh=0.0,
        grid_import_kwh=0.0,
        grid_export_kwh=0.0,
        soc_kwh=0.0,
        cost_sek=0.0,
        ev_keep_on=dict(ev_keep_on) if ev_keep_on is not None else {},
    )


class TestEvKeepOnRoundTrip:
    """Task 1.6: KeplerResultSlot.ev_keep_on round-trips through adapter + formatter."""

    def test_keep_on_slot_round_trips_to_json(self):
        now = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        slot = _make_kepler_result_slot(now, now + pd.Timedelta(hours=1), ev_keep_on={"ev1": True})
        result = KeplerResult(slots=[slot], total_cost_sek=0.0, is_optimal=True, status_msg="ok")

        df = kepler_result_to_dataframe(result)
        records = dataframe_to_json_response(df, now_override=now)

        assert len(records) == 1
        assert records[0]["ev_keep_on"] == {"ev1": True}
        assert records[0]["ev_charging_kw"] == 0.0

    def test_slot_without_keep_on_round_trips_empty(self):
        now = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        slot = _make_kepler_result_slot(now, now + pd.Timedelta(hours=1))
        result = KeplerResult(slots=[slot], total_cost_sek=0.0, is_optimal=True, status_msg="ok")

        df = kepler_result_to_dataframe(result)
        records = dataframe_to_json_response(df, now_override=now)

        assert len(records) == 1
        assert records[0]["ev_keep_on"] == {}


def _make_schedule_df_with_water(water_heaters_col=None):
    """Build a minimal schedule DataFrame with optional water_heaters column."""
    now = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
    times = pd.date_range(now, periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "start_time": times,
            "end_time": times + pd.Timedelta(hours=1),
            "battery_charge_kw": [0.0, 1.0, 0.0],
            "battery_discharge_kw": [0.0, 0.0, 2.0],
            "ev_charge_kw": [0.0, 0.0, 0.0],
            "grid_import_kw": [3.0, 1.0, 0.0],
            "grid_export_kw": [0.0, 0.0, 0.0],
            "pv_kw": [0.0, 0.0, 0.0],
            "water_heating_kw": [3.0, 0.0, 2.0],  # Aggregate column (used by formatter)
            "import_price_sek_kwh": [0.5, 0.5, 0.5],
            "export_price_sek_kwh": [0.1, 0.1, 0.1],
        }
    )
    if water_heaters_col is not None:
        df["water_heaters"] = water_heaters_col
    return df


class TestWaterHeatersInOutput:
    def test_per_device_water_heater_breakdown(self):
        """Each slot should include water_heaters dict with per-device heating_kw dicts."""
        water_data = [
            {"wh1": 3.0, "wh2": 0.0},
            {"wh1": 0.0, "wh2": 0.0},
            {"wh1": 0.0, "wh2": 2.0},
        ]
        df = _make_schedule_df_with_water(water_heaters_col=water_data)
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        assert len(records) == 3
        # Formatter wraps raw kW as {"heating_kw": float} dicts
        assert records[0]["water_heaters"] == {
            "wh1": {"heating_kw": 3.0},
            "wh2": {"heating_kw": 0.0},
        }
        assert records[1]["water_heaters"] == {
            "wh1": {"heating_kw": 0.0},
            "wh2": {"heating_kw": 0.0},
        }
        assert records[2]["water_heaters"] == {
            "wh1": {"heating_kw": 0.0},
            "wh2": {"heating_kw": 2.0},
        }

    def test_nan_water_heaters_normalised_to_empty_dict(self):
        """NaN in water_heaters column must become {}."""
        df = _make_schedule_df_with_water(water_heaters_col=[float("nan"), None, np.nan])
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        for record in records:
            assert record["water_heaters"] == {}

    def test_missing_water_heaters_column_produces_empty_dict(self):
        """When water_heaters column is absent, output should include {} per slot."""
        df = _make_schedule_df_with_water()
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        for record in records:
            assert record["water_heaters"] == {}

    def test_aggregate_water_heating_kw_preserved(self):
        """water_heating_kw aggregate should still be present alongside water_heaters."""
        water_data = [{"wh1": 3.0}, {"wh1": 0.0}, {"wh1": 2.0}]
        df = _make_schedule_df_with_water(water_heaters_col=water_data)
        # Also set water_heating_kw in the df
        df["water_heater_kw"] = [3.0, 0.0, 2.0]
        records = dataframe_to_json_response(
            df, now_override=datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
        )

        # water_heating_kw comes straight from the DataFrame column
        assert records[0].get("water_heating_kw") == 3.0
        assert records[2].get("water_heating_kw") == 2.0
        assert "water_heaters" in records[0]
        assert records[0]["water_heaters"] == {"wh1": {"heating_kw": 3.0}}
