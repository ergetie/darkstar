"""has_water_heater=false masks planned/future water in /api/schedule; completed slots keep history."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from backend.api.routers import schedule


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("past", [False, True])
async def test_water_fields_follow_flag(monkeypatch, tmp_path, flag, past):
    start, end = (
        ("2026-10-07T22:00:00+02:00", "2026-10-07T22:15:00+02:00")
        if past
        else ("2026-10-07T22:30:00+02:00", "2026-10-07T22:45:00+02:00")
    )
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 7, 20, 32, tzinfo=schedule.pytz.UTC).astimezone(tz)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(schedule, "datetime", FixedDatetime)
    monkeypatch.setattr(
        schedule,
        "load_yaml",
        lambda _: {"timezone": "Europe/Stockholm", "system": {"has_water_heater": flag}},
    )
    monkeypatch.setattr(schedule, "get_nordpool_data", AsyncMock(return_value=[]))
    store = AsyncMock()
    store.get_history_range.return_value = [
        {
            "slot_start": start,
            "slot_end": end,
            "soc_end_percent": 50.0,
            "batt_charge_kwh": 0.0,
            "batt_discharge_kwh": 0.0,
            "water_kwh": 0.75,
            "ev_charging_kwh": 0.0,
            "export_kwh": 0.0,
            "import_price_sek_kwh": 1.0,
        }
    ]
    store.get_forecasts_range.return_value = []
    store.get_plans_range.return_value = [
        {
            "slot_start": start,
            "slot_end": end,
            "planned_charge_kwh": 0.0,
            "planned_discharge_kwh": 0.0,
            "planned_soc_percent": 50.0,
            "projected_soc_percent": 50.0,
            "planned_export_kwh": 0.0,
            "planned_water_heating_kwh": 0.5,
            "planned_ev_charging_kwh": None,
        }
    ]
    store.get_observations_range.return_value = []

    result = await schedule.schedule_today_with_history(store=store)

    slot = result["slots"][0]
    if flag or past:
        assert slot["water_heating_kw"] == pytest.approx(2.0)
        assert slot["is_historical"] is past
    else:
        assert slot["water_heating_kw"] == 0.0
        assert slot["planned_water_heating_kw"] == 0.0
        assert not {"planned_water_heaters", "actual_water_heaters_kw"} & slot.keys()
