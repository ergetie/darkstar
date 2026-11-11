"""Plug-session tracking and history SoC lookup (ev-missed-goal-recovery plug continuity)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import ev_plug
from backend.core.ev_plug import (
    EV_PLUG_SESSION_STATE_KEY,
    EV_UNPLUG_DEBOUNCE_MINUTES,
    plug_session_start,
    remember_plug_state,
    resolve_plug_state,
)

T0 = datetime(2026, 11, 10, 7, 22, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset():
    ev_plug.reset_plug_memory()
    yield
    ev_plug.reset_plug_memory()


def test_first_seen_plugged_is_unknown_not_a_replug():
    remember_plug_state("ev", True, T0)
    assert plug_session_start("ev") is None


def test_unplugged_then_plugged_starts_session():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + timedelta(minutes=5))
    assert plug_session_start("ev") == T0 + timedelta(minutes=5)


def test_still_plugged_keeps_session_start():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + timedelta(minutes=5))
    remember_plug_state("ev", True, T0 + timedelta(minutes=30))
    assert plug_session_start("ev") == T0 + timedelta(minutes=5)


def test_unplug_clears_session_after_debounce():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0)
    remember_plug_state("ev", False, T0 + timedelta(minutes=1))
    remember_plug_state("ev", False, T0 + timedelta(minutes=1 + EV_UNPLUG_DEBOUNCE_MINUTES))
    assert plug_session_start("ev") is None


def test_unreachable_reading_never_touches_session():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + timedelta(minutes=1))
    assert resolve_plug_state("ev", "unavailable") == (True, True)
    assert plug_session_start("ev") == T0 + timedelta(minutes=1)


def test_resolve_plug_state_tracks_transition():
    resolve_plug_state("ev", "off", "on")
    resolve_plug_state("ev", "on", "on")
    assert plug_session_start("ev") is not None


@pytest.mark.asyncio
async def test_sensor_value_at_takes_last_numeric_state_at_or_before():
    from backend.core import ha_client

    at = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
    series = [
        {"state": "80", "last_changed": "2026-11-10T05:40:00+00:00"},
        {"state": "82", "last_changed": "2026-11-10T05:55:00+00:00"},
        {"state": "unavailable", "last_changed": "2026-11-10T05:58:00+00:00"},
        {"state": "66", "last_changed": "2026-11-10T06:30:00+00:00"},
    ]
    history = AsyncMock(return_value={"sensor.soc": series})
    with patch.object(ha_client, "get_power_history_batch", history):
        assert await ha_client.get_sensor_value_at("sensor.soc", at) == 82.0
    assert history.await_args.kwargs == {"fill_units": False}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [None, {"sensor.soc": []}, {"sensor.soc": [{"state": "unknown"}]}]
)
async def test_sensor_value_at_none_when_unavailable(payload):
    from backend.core import ha_client

    with patch.object(ha_client, "get_power_history_batch", AsyncMock(return_value=payload)):
        assert await ha_client.get_sensor_value_at("sensor.soc", T0) is None


# --- unplug debounce and persistence ---------------------------------------

MIN = timedelta(minutes=1)


def _saved(charger="ev"):
    from backend.core.ev_state import read_ev_state

    return read_ev_state().get(charger, {}).get(EV_PLUG_SESSION_STATE_KEY)


def _session(start=T0, first_unplugged=None):
    return {
        "start": start.isoformat(),
        "first_unplugged_at": first_unplugged.isoformat() if first_unplugged else None,
    }


def _seed(session, charger="ev", extra=None):
    from backend.core.ev_state import write_ev_state

    write_ev_state({charger: {**(extra or {}), EV_PLUG_SESSION_STATE_KEY: session}})


def _fresh_process():
    ev_plug.reset_plug_memory()


def test_short_flicker_keeps_session():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    remember_plug_state("ev", False, T0 + 30 * MIN)
    remember_plug_state("ev", True, T0 + 35 * MIN)
    assert plug_session_start("ev") == T0 + MIN
    assert _saved()["first_unplugged_at"] is None


def test_long_unplug_ends_session_and_replug_starts_new():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    remember_plug_state("ev", False, T0 + 30 * MIN)
    remember_plug_state("ev", True, T0 + (30 + EV_UNPLUG_DEBOUNCE_MINUTES) * MIN)
    assert plug_session_start("ev") == T0 + (30 + EV_UNPLUG_DEBOUNCE_MINUTES) * MIN


def test_unplug_ends_session_on_unplugged_reading_and_clears_saved():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    remember_plug_state("ev", False, T0 + 5 * MIN)
    assert plug_session_start("ev") == T0 + MIN
    remember_plug_state("ev", False, T0 + (5 + EV_UNPLUG_DEBOUNCE_MINUTES) * MIN)
    assert plug_session_start("ev") is None
    assert _saved() is None


def test_unreachable_does_not_start_or_advance_debounce():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    remember_plug_state("ev", False, T0 + 5 * MIN)
    resolve_plug_state("ev", "unavailable")
    assert _saved()["first_unplugged_at"] == (T0 + 5 * MIN).isoformat()


def test_first_unplugged_at_not_reset_by_repeated_unplugged_readings():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    remember_plug_state("ev", False, T0 + 5 * MIN)
    remember_plug_state("ev", False, T0 + 8 * MIN)
    assert _saved()["first_unplugged_at"] == (T0 + 5 * MIN).isoformat()


def test_session_survives_restart_while_plugged():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    _fresh_process()
    remember_plug_state("ev", True, T0 + 600 * MIN)
    assert plug_session_start("ev") == T0 + MIN


def test_restart_after_car_left_does_not_restore():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    remember_plug_state("ev", False, T0 + 5 * MIN)
    _fresh_process()
    remember_plug_state("ev", True, T0 + 60 * MIN)  # long after the debounce window
    assert plug_session_start("ev") is None
    assert _saved() is None


def test_restart_unplugged_without_running_debounce_is_not_restored():
    _seed(_session())
    remember_plug_state("ev", False, T0 + 60 * MIN)
    remember_plug_state("ev", True, T0 + 61 * MIN)
    assert plug_session_start("ev") == T0 + 61 * MIN  # a fresh replug, not the old session


def test_restart_mid_debounce_restores_and_replug_clears_it():
    _seed(_session(T0, T0 + 5 * MIN))
    remember_plug_state("ev", True, T0 + 8 * MIN)
    assert plug_session_start("ev") == T0
    assert _saved()["first_unplugged_at"] is None


def test_restart_mid_debounce_still_unplugged_continues_debounce():
    _seed(_session(T0, T0 + 5 * MIN))
    remember_plug_state("ev", False, T0 + 8 * MIN)
    assert plug_session_start("ev") == T0
    remember_plug_state("ev", False, T0 + 5 * MIN + EV_UNPLUG_DEBOUNCE_MINUTES * MIN)
    assert plug_session_start("ev") is None


def test_flicker_across_restart_beyond_window_not_restored():
    _seed(_session(T0, T0 + 5 * MIN))
    remember_plug_state("ev", True, T0 + (5 + EV_UNPLUG_DEBOUNCE_MINUTES) * MIN)
    assert plug_session_start("ev") is None


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"ev": 5}',
        '{"ev": {"plug_session": "x"}}',
        '{"ev": {"plug_session": {"start": "garbage"}}}',
        "",
    ],
)
def test_corrupt_state_file_means_unknown_history(content):
    from backend.core import ev_state

    ev_state.STATE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ev_state.STATE_FILE_PATH.write_text(content)
    remember_plug_state("ev", True, T0)
    assert plug_session_start("ev") is None


def test_missing_state_file_means_unknown_history():
    remember_plug_state("ev", True, T0)
    assert plug_session_start("ev") is None


def test_no_write_on_repeated_same_state_readings():
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    with patch.object(ev_plug, "_persist_session") as persist:
        for i in range(2, 8):
            remember_plug_state("ev", True, T0 + i * MIN)
        persist.assert_not_called()
    remember_plug_state("ev", False, T0 + 20 * MIN)
    with patch.object(ev_plug, "_persist_session") as persist:
        remember_plug_state("ev", False, T0 + 22 * MIN)
        persist.assert_not_called()


def test_persistence_preserves_goal_and_other_chargers():
    from backend.core.ev_state import read_ev_state, write_ev_state

    write_ev_state({"ev": {"target_soc_percent": 80}, "other": {"target_soc_percent": 60}})
    remember_plug_state("ev", False, T0)
    remember_plug_state("ev", True, T0 + MIN)
    state = read_ev_state()
    assert state["ev"]["target_soc_percent"] == 80
    assert state["other"] == {"target_soc_percent": 60}
    remember_plug_state("ev", False, T0 + 5 * MIN)
    remember_plug_state("ev", False, T0 + 20 * MIN)
    assert read_ev_state()["ev"] == {"target_soc_percent": 80}


def test_write_failure_is_swallowed():
    with patch("backend.core.ev_state.update_ev_state", side_effect=OSError("disk")):
        remember_plug_state("ev", False, T0)
        remember_plug_state("ev", True, T0 + MIN)
    assert plug_session_start("ev") == T0 + MIN


def test_torleif_real_unplug_is_not_continuous():
    remember_plug_state("goe", False, T0.replace(hour=4))
    remember_plug_state("goe", True, T0.replace(hour=5, minute=50))
    remember_plug_state("goe", False, T0.replace(hour=5, minute=56))
    remember_plug_state("goe", False, T0.replace(hour=6, minute=30))
    remember_plug_state("goe", True, T0)
    assert plug_session_start("goe") == T0


def test_flicker_across_deadline_keeps_grace_continuity():
    import pytz

    from planner.pipeline import resolve_ev_effective_deadline

    tz = pytz.timezone("Europe/Stockholm")
    missed = tz.localize(datetime(2026, 9, 24, 10, 30))
    utc_missed = missed.astimezone(UTC)
    goal = {
        "id": "ev",
        "target_soc_percent": 55,
        "ready_by": "10:30",
        "repeat": "daily",
        "missed_goal_grace_hours": 4,
        "missed_goal_tolerance_percent": 0,
    }
    remember_plug_state("ev", False, utc_missed - timedelta(hours=5))
    remember_plug_state("ev", True, utc_missed - timedelta(hours=4))
    remember_plug_state("ev", False, utc_missed - timedelta(minutes=2))
    remember_plug_state("ev", True, utc_missed + 3 * MIN)  # back inside the window
    now = missed + timedelta(minutes=4)
    state = {
        "soc_percent": 53.0,
        "plugged_in": True,
        "plug_session_start": plug_session_start("ev"),
    }
    deadline, in_grace = resolve_ev_effective_deadline(goal, state, now, tz)
    assert in_grace is True
    assert deadline == missed + timedelta(hours=4)
