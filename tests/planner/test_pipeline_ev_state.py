from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytz

from backend.core import ev_state
from planner.pipeline import _persist_ev_multi_day_state, merge_ev_goals_from_state


def test_persist_ev_multi_day_state_preserves_goals(tmp_path, monkeypatch):
    """_persist_ev_multi_day_state preserves goal fields verbatim and never
    overwrites last_updated (it anchors every_n_days) — only refreshes
    progress fields and stamps last_planned_at.
    """
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    # 1. Seed existing state written by API
    existing = {
        "ev1": {
            "target_soc_percent": 90,
            "ready_by": "08:30",
            "repeat": "weekdays",
            "ready_by_date": None,
            "n_days": None,
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
    # Config carries only hardware facts now — no goal fields.
    ev_chargers_cfg = [
        {
            "id": "ev1",
            "max_power_kw": 7.4,
            "battery_capacity_kwh": 100.0,
        }
    ]

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)

    _persist_ev_multi_day_state(ev_states, ev_chargers_cfg, sqlite_path="", tz=tz, now=now)

    # 3. Verify state file has preserved existing goal fields + source verbatim,
    # and refreshed only the progress fields.
    assert state_file.exists()
    updated = json.loads(state_file.read_text())
    assert "ev1" in updated
    charger = updated["ev1"]

    # Preserved goal fields (verbatim, byte-identical last_updated)
    assert charger["target_soc_percent"] == 90
    assert charger["ready_by"] == "08:30"
    assert charger["repeat"] == "weekdays"
    assert charger["keep_on_after_target"] is True
    assert charger["source"] == "api"
    assert charger["last_updated"] == "2026-06-10T14:30:00+02:00"

    # Updated/computed progress fields
    assert charger["required_kwh"] == 15.0
    assert charger["daily_quota_kwh"] == 10.0
    assert charger["quota_schedule"] == {"2026-06-11": 10.0}
    assert charger["current_soc_percent"] == 50.0
    assert charger["last_planned_at"] == now.isoformat()


def test_persist_skips_chargers_with_no_goal(tmp_path, monkeypatch):
    """A charger with no goal in the state file gets no persisted entry —
    the planner never invents a goal from config (config carries none)."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    assert not state_file.exists()

    ev_states = [
        {
            "id": "ev1",
            "deadline": None,
            "required_kwh": None,
            "soc_percent": 60.0,
            "plugged_in": True,
        }
    ]
    ev_chargers_cfg = [
        {
            "id": "ev1",
            "max_power_kw": 7.4,
            "battery_capacity_kwh": 100.0,
        }
    ]

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)

    _persist_ev_multi_day_state(ev_states, ev_chargers_cfg, sqlite_path="", tz=tz, now=now)

    # No goal existed, so nothing is persisted for this charger.
    if state_file.exists():
        updated = json.loads(state_file.read_text())
        assert "ev1" not in updated


def test_persist_preserves_disabled_charger_entry(tmp_path, monkeypatch):
    """A charger not processed this run (e.g. disabled) keeps its existing
    entry unchanged — persist merges into the file, it does not replace it."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    existing = {
        "ev_disabled": {
            "target_soc_percent": 70,
            "ready_by": "06:00",
            "repeat": "daily",
            "ready_by_date": None,
            "n_days": None,
            "keep_on_after_target": False,
            "source": "api",
            "last_updated": "2026-06-01T00:00:00+00:00",
            "required_kwh": 5.0,
        }
    }
    state_file.write_text(json.dumps(existing))

    # This run only processes "ev1" — "ev_disabled" is absent from ev_states.
    ev_states = [
        {
            "id": "ev1",
            "deadline": None,
            "required_kwh": None,
            "soc_percent": 40.0,
            "plugged_in": False,
        }
    ]
    ev_chargers_cfg = [{"id": "ev1", "max_power_kw": 7.4, "battery_capacity_kwh": 100.0}]

    tz = pytz.timezone("Europe/Stockholm")
    now = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)

    _persist_ev_multi_day_state(ev_states, ev_chargers_cfg, sqlite_path="", tz=tz, now=now)

    updated = json.loads(state_file.read_text())
    assert updated["ev_disabled"] == existing["ev_disabled"]


def test_merge_ev_goals_from_state_takes_precedence_over_config():
    """merge_ev_goals_from_state (the real pipeline merge code) prefers the
    state-file goal over any leftover goal-shaped keys on the config dict."""
    ev_state_data = {
        "ev1": {
            "target_soc_percent": 95,
            "ready_by": "06:00",
            "repeat": "none",
            "ready_by_date": "2026-06-12",
            "n_days": None,
            "last_updated": "2026-06-11T00:00:00+00:00",
            "keep_on_after_target": True,
        }
    }

    ev_chargers_cfg_raw = [
        {
            "id": "ev1",
            "max_power_kw": 7.4,
            "battery_capacity_kwh": 100.0,
        }
    ]

    merged = merge_ev_goals_from_state(ev_chargers_cfg_raw, ev_state_data)

    assert merged[0]["target_soc_percent"] == 95
    assert merged[0]["ready_by"] == "06:00"
    assert merged[0]["repeat"] == "none"
    assert merged[0]["ready_by_date"] == "2026-06-12"
    assert merged[0]["keep_on_after_target"] is True
    assert merged[0]["max_power_kw"] == 7.4


def test_merge_ev_goals_from_state_no_goal_is_inert():
    """A charger absent from the state file gets no goal — never a default."""
    ev_chargers_cfg_raw = [{"id": "ev1", "max_power_kw": 7.4, "battery_capacity_kwh": 100.0}]

    merged = merge_ev_goals_from_state(ev_chargers_cfg_raw, {})

    assert merged[0]["target_soc_percent"] is None
    assert merged[0]["ready_by"] is None
    assert merged[0]["repeat"] is None
    assert merged[0]["ready_by_date"] is None
    assert merged[0]["n_days"] is None
    assert merged[0]["keep_on_after_target"] is False
