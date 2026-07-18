"""
Tests for the s_index_history write hook in save_schedule_to_json:
it must be skipped when the S-Index debug dict is empty/None, and
invoked with the debug dict otherwise.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from planner.output import schedule as schedule_module


def _make_schedule_df():
    now = datetime(2024, 6, 1, 10, 0, tzinfo=UTC)
    times = pd.date_range(now, periods=2, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "start_time": times,
            "end_time": times + pd.Timedelta(hours=1),
            "battery_charge_kw": [0.0, 1.0],
            "battery_discharge_kw": [0.0, 0.0],
            "ev_charge_kw": [0.0, 0.0],
            "grid_import_kw": [0.0, 1.0],
            "grid_export_kw": [0.0, 0.0],
            "pv_kw": [5.0, 4.0],
            "water_heater_kw": [0.0, 0.0],
            "import_price_sek_kwh": [0.5, 0.5],
            "export_price_sek_kwh": [0.1, 0.1],
        }
    )


@pytest.mark.parametrize("empty_debug", [None, {}])
@pytest.mark.asyncio
async def test_save_schedule_skips_s_index_history_when_debug_empty(
    monkeypatch, tmp_path, empty_debug
):
    mock_record = AsyncMock()
    monkeypatch.setattr(schedule_module, "record_s_index_history", mock_record)

    await schedule_module.save_schedule_to_json(
        schedule_df=_make_schedule_df(),
        config={},
        now_slot=None,
        forecast_meta={},
        s_index_debug=empty_debug,
        window_responsibilities=[],
        planner_state={},
        output_path=str(tmp_path / "schedule.json"),
    )

    mock_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_schedule_calls_s_index_history_when_debug_present(monkeypatch, tmp_path):
    mock_record = AsyncMock()
    monkeypatch.setattr(schedule_module, "record_s_index_history", mock_record)

    debug_payload = {"mode": "physical_deficit", "base_factor": 1.1}

    await schedule_module.save_schedule_to_json(
        schedule_df=_make_schedule_df(),
        config={},
        now_slot=None,
        forecast_meta={},
        s_index_debug=debug_payload,
        window_responsibilities=[],
        planner_state={},
        output_path=str(tmp_path / "schedule.json"),
    )

    mock_record.assert_awaited_once_with(debug_payload)
