"""Missing SoC endpoints must not become zero-percent chart measurements."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from backend.api.routers import schedule


@pytest.mark.asyncio
@pytest.mark.parametrize("soc", [None, 0.0, 15.0])
async def test_current_slot_preserves_actual_soc(monkeypatch, tmp_path, soc):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 7, 20, 32, tzinfo=schedule.pytz.UTC).astimezone(tz)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(schedule, "datetime", FixedDatetime)
    monkeypatch.setattr(schedule, "load_yaml", lambda _: {"timezone": "Europe/Stockholm"})
    monkeypatch.setattr(schedule, "get_nordpool_data", AsyncMock(return_value=[]))
    store = AsyncMock()
    store.get_history_range.return_value = [
        {
            "slot_start": "2026-10-07T22:30:00+02:00",
            "slot_end": "2026-10-07T22:45:00+02:00",
            "soc_end_percent": soc,
            "batt_charge_kwh": 0.0,
            "batt_discharge_kwh": 0.0,
            "water_kwh": 0.0,
            "ev_charging_kwh": 0.0,
            "export_kwh": 0.0,
            "import_price_sek_kwh": 1.0,
        }
    ]
    store.get_forecasts_range.return_value = []
    store.get_plans_range.return_value = []
    store.get_observations_range.return_value = []

    result = await schedule.schedule_today_with_history(store=store)

    assert len(result["slots"]) == 1
    slot = result["slots"][0]
    assert slot["actual_soc"] == soc
    assert slot["is_executed"] is True
    assert slot["is_completed"] is False
    # Execution telemetry is useful during an active slot; water actuals stay
    # hidden until the slot ends and provenance can describe a complete sample.
    assert slot["actual_charge_kw"] == 0.0
    assert slot["actual_discharge_kw"] == 0.0
    assert slot["actual_export_kwh"] == 0.0
    assert slot["actual_ev_charging_kw"] == 0.0
    assert "actual_water_kw" not in slot
