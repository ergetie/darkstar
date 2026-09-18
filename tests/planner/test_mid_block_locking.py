import json
import logging
from pathlib import Path

import pandas as pd
import pytest
import pytz

from planner.pipeline import _detect_mid_block_slots, _load_previous_schedule


def _slot(start: str, heater_kw: dict[str, float]) -> dict:
    return {
        "start_time": start,
        "water_heaters": {
            heater_id: {"heating_kw": power_kw} for heater_id, power_kw in heater_kw.items()
        },
    }


def test_active_heater_gets_remaining_slots_and_idle_heater_does_not(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="darkstar.planner")
    now = pd.Timestamp("2026-01-15T10:00:00+01:00")
    schedule = [
        _slot("2026-01-15T10:00:00+01:00", {"active": 3.0, "idle": 0.0}),
        _slot("2026-01-15T10:15:00+01:00", {"active": 3.0, "idle": 0.0}),
        _slot("2026-01-15T10:30:00+01:00", {"active": 0.0, "idle": 0.0}),
    ]

    forced = _detect_mid_block_slots(
        schedule, ["active", "idle"], now, pytz.timezone("Europe/Stockholm")
    )

    assert len(forced["active"]) == 2
    assert forced["idle"] == set()
    assert "heater active" in caplog.text
    assert "2 remaining slots" in caplog.text


@pytest.mark.parametrize("payload", [None, {"schedule": []}, {"not_schedule": True}])
def test_missing_or_empty_previous_schedule_logs_warning(
    tmp_path: Path, payload: dict | None, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "schedule.json"
    if payload is not None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    previous = _load_previous_schedule(path)

    assert previous == []
    assert str(path) in caplog.text
    assert "missing or empty" in caplog.text
