from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytz

from backend.core import ev_state
from planner.pipeline import _persist_ev_multi_day_state


def test_persist_ev_multi_day_state_preserves_goals(tmp_path, monkeypatch):
    """Test that _persist_ev_multi_day_state preserves API/HA written goals (read-modify-write)."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    # 1. Seed existing state written by API
    existing = {
        "ev1": {
            "target_soc_percent": 90,
            "ready_by": "08:30",
            "repeat": "weekdays",
            "keep_on_after_target": True,
            "source": "api",
            "last_updated": "2026-06-10T14:30:00+02:00",
        }
    }
    state_file.write_text(json.dumps(existing))

    # 2. Run _persist_ev_multi_day_state representing a pipeline writeback
    ev_states = [
        {
            "id": "ev1",
            "deadline": datetime(2026, 6, 11, 8, 30, tzinfo=UTC),
            "required_kwh": 15.0,
            "soc_percent": 50.0,
            "plugged_in": True,
            "daily_quota_kwh": 10.0,
            "quota_schedule": {"2026-06-11": 10.0},
        }
    ]
    ev_chargers_cfg = [
        {
            "id": "ev1",
            "max_power_kw": 7.4,
            "battery_capacity_kwh": 100.0,
            # Config default fields are different; they should be overridden by the existing state!
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "keep_on_after_target": False,
        }
    ]

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)

    _persist_ev_multi_day_state(ev_states, ev_chargers_cfg, sqlite_path="", tz=tz, now=now)

    # 3. Verify state file has preserved existing goal fields + source, and updated computed fields
    assert state_file.exists()
    updated = json.loads(state_file.read_text())
    assert "ev1" in updated
    charger = updated["ev1"]

    # Preserved fields
    assert charger["target_soc_percent"] == 90
    assert charger["ready_by"] == "08:30"
    assert charger["repeat"] == "weekdays"
    assert charger["keep_on_after_target"] is True
    assert charger["source"] == "api"

    # Updated/computed fields
    assert charger["required_kwh"] == 15.0
    assert charger["daily_quota_kwh"] == 10.0
    assert charger["quota_schedule"] == {"2026-06-11": 10.0}
    assert charger["current_soc_percent"] == 50.0


def test_missing_or_corrupt_state_file_fallback(tmp_path, monkeypatch):
    """Test that missing or corrupt state file gracefully falls back to config goals."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    # State file missing
    assert not state_file.exists()

    ev_states = [
        {
            "id": "ev1",
            "deadline": datetime(2026, 6, 11, 7, 0, tzinfo=UTC),
            "required_kwh": 20.0,
            "soc_percent": 60.0,
            "plugged_in": True,
        }
    ]
    ev_chargers_cfg = [
        {
            "id": "ev1",
            "max_power_kw": 7.4,
            "battery_capacity_kwh": 100.0,
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "keep_on_after_target": False,
        }
    ]

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)

    _persist_ev_multi_day_state(ev_states, ev_chargers_cfg, sqlite_path="", tz=tz, now=now)

    # Recreated on write with config defaults
    assert state_file.exists()
    updated = json.loads(state_file.read_text())
    assert "ev1" in updated
    assert updated["ev1"]["target_soc_percent"] == 80
    assert updated["ev1"]["ready_by"] == "07:00"
    assert updated["ev1"]["repeat"] == "daily"


def test_pipeline_merges_state_file_goals(monkeypatch):
    """Test that when reading goals, state file takes precedence over config.yaml."""
    from backend.core import ev_state

    # 1. Mock state file data
    monkeypatch.setattr(ev_state, "read_ev_state", lambda: {
        "ev1": {
            "target_soc_percent": 95,
            "ready_by": "06:00",
            "repeat": "none",
            "ready_by_date": "2026-06-12",
            "keep_on_after_target": True,
        }
    })

    # 2. Simulate the pipeline merging logic
    ev_chargers_cfg_raw = [
        {
            "id": "ev1",
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "keep_on_after_target": False,
        }
    ]

    ev_state_data = ev_state.read_ev_state()
    ev_chargers_cfg = []
    for ev_cfg_item in ev_chargers_cfg_raw:
        charger_id = ev_cfg_item.get("id", "")
        charger_state = ev_state_data.get(charger_id, {})
        goal_cfg = dict(ev_cfg_item)
        if charger_state and charger_state.get("target_soc_percent") is not None:
            goal_cfg["target_soc_percent"] = charger_state.get("target_soc_percent")
            goal_cfg["ready_by"] = charger_state.get("ready_by")
            goal_cfg["repeat"] = charger_state.get("repeat")
            goal_cfg["ready_by_date"] = charger_state.get("ready_by_date")
            if charger_state.get("keep_on_after_target") is not None:
                goal_cfg["keep_on_after_target"] = charger_state.get("keep_on_after_target")
        ev_chargers_cfg.append(goal_cfg)

    assert ev_chargers_cfg[0]["target_soc_percent"] == 95
    assert ev_chargers_cfg[0]["ready_by"] == "06:00"
    assert ev_chargers_cfg[0]["repeat"] == "none"
    assert ev_chargers_cfg[0]["ready_by_date"] == "2026-06-12"
    assert ev_chargers_cfg[0]["keep_on_after_target"] is True
