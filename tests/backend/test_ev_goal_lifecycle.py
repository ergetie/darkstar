"""Goal lifecycle: replan triggers, HA one-off semantics, every-N-days anchor.

ev-goal-lifecycle-feedback tasks 2.5 and 3.6.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from fastapi import BackgroundTasks

from backend.api.routers import ev as ev_router
from backend.api.routers.ev import EVChargerScheduleBody, set_ev_charger_schedule
from backend.core import ev_state
from backend.core.ev_goal import resolve_next_ready_by
from backend.ha_socket import HAWebSocketClient
from backend.services.scheduler_service import ReplanReason
from backend.services.scheduler_service import request_replan as real_request_replan

TZ = pytz.timezone("Europe/Stockholm")


def _cfg() -> dict:
    return {
        "timezone": "Europe/Stockholm",
        "ev_chargers": [
            {
                "id": "ev1",
                "name": "EV-01",
                "enabled": True,
                "sensor": "sensor.ev1_power",
                "soc_sensor": "sensor.ev1_soc",
                "plug_sensor": "binary_sensor.ev1_plug",
                "rated_power_kw": 7.4,
                "ha_ready_by_entity": "input_datetime.ev1_ready",
                "ha_target_soc_entity": "input_number.ev1_soc",
            }
        ],
    }


def _ha_patches():
    return (
        patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0)),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=40.0)),
        patch(
            "backend.api.routers.ev.get_ha_entity_state",
            AsyncMock(return_value={"state": "on"}),
        ),
    )


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", path)
    return path


@pytest.fixture
def api_env(monkeypatch, state_file):
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _cfg())
    monkeypatch.setattr(ev_router, "sync_goal_to_ha", AsyncMock())
    request = MagicMock()
    monkeypatch.setattr("backend.services.scheduler_service.request_replan", request)
    return request


async def _save(body: EVChargerScheduleBody) -> dict:
    p1, p2, p3 = _ha_patches()
    with p1, p2, p3:
        return await set_ev_charger_schedule("ev1", body, BackgroundTasks())


# --- 2.5 API triggers ---


@pytest.mark.asyncio
async def test_api_save_triggers_one_goal_replan_and_reports_pending(api_env):
    res = await _save(EVChargerScheduleBody(target_soc_percent=80, ready_by="07:00", repeat="daily"))

    api_env.assert_called_once_with(ReplanReason.GOAL_CHANGE, charger_ids=["ev1"])
    assert res["target_soc_percent"] == 80


@pytest.mark.asyncio
async def test_api_save_response_pending_when_plan_is_older(api_env, state_file):
    old_plan = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 70,
                    "ready_by": "07:00",
                    "repeat": "daily",
                    "last_updated": old_plan,
                    "last_planned_at": old_plan,
                }
            }
        )
    )
    res = await _save(EVChargerScheduleBody(target_soc_percent=90, ready_by="07:00", repeat="daily"))
    assert res["plan_pending"] is True


@pytest.mark.asyncio
async def test_api_clear_triggers_goal_replan(api_env, state_file):
    state_file.write_text(json.dumps({"ev1": {"target_soc_percent": 80, "ready_by": "07:00"}}))
    await _save(EVChargerScheduleBody(target_soc_percent=None))
    api_env.assert_called_once_with(ReplanReason.GOAL_CHANGE, charger_ids=["ev1"])


@pytest.mark.asyncio
async def test_api_save_marks_pending_through_real_helper(monkeypatch, state_file):
    """The real helper flags the charger synchronously, so the response is pending."""
    from backend.services import scheduler_service as sched_mod
    from backend.services.planner_service import planner_service

    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _cfg())
    monkeypatch.setattr(ev_router, "sync_goal_to_ha", AsyncMock())
    # conftest stubs the helper; restore the real one but never run the planner.
    monkeypatch.setattr(sched_mod, "request_replan", real_request_replan)
    monkeypatch.setattr(sched_mod.scheduler_service, "request_goal_replan", AsyncMock())
    monkeypatch.setattr(sched_mod.scheduler_service, "main_loop", None)
    monkeypatch.setattr(planner_service, "_goal_waiting", set())

    start = time.monotonic()
    res = await _save(EVChargerScheduleBody(target_soc_percent=80, ready_by="07:00", repeat="daily"))
    assert time.monotonic() - start < 1.0
    assert res["plan_pending"] is True


# --- 3.6 anchor rules ---


@pytest.mark.asyncio
async def test_new_every_n_days_goal_anchors_today(api_env, state_file):
    await _save(
        EVChargerScheduleBody(target_soc_percent=80, ready_by="07:00", repeat="every_n_days", n_days=3)
    )
    written = json.loads(state_file.read_text())["ev1"]
    assert written["anchor_date"] == datetime.now(TZ).date().isoformat()


@pytest.mark.asyncio
async def test_target_change_keeps_anchor(api_env, state_file):
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 80,
                    "ready_by": "07:00",
                    "repeat": "every_n_days",
                    "n_days": 3,
                    "anchor_date": "2026-09-20",
                }
            }
        )
    )
    await _save(
        EVChargerScheduleBody(target_soc_percent=60, ready_by="07:00", repeat="every_n_days", n_days=3)
    )
    assert json.loads(state_file.read_text())["ev1"]["anchor_date"] == "2026-09-20"


@pytest.mark.asyncio
async def test_n_days_change_reanchors(api_env, state_file):
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 80,
                    "ready_by": "07:00",
                    "repeat": "every_n_days",
                    "n_days": 3,
                    "anchor_date": "2026-09-20",
                }
            }
        )
    )
    await _save(
        EVChargerScheduleBody(target_soc_percent=80, ready_by="07:00", repeat="every_n_days", n_days=2)
    )
    written = json.loads(state_file.read_text())["ev1"]
    assert written["anchor_date"] == datetime.now(TZ).date().isoformat()


@pytest.mark.asyncio
async def test_repeat_change_away_removes_anchor(api_env, state_file):
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 80,
                    "ready_by": "07:00",
                    "repeat": "every_n_days",
                    "n_days": 3,
                    "anchor_date": "2026-09-20",
                }
            }
        )
    )
    await _save(EVChargerScheduleBody(target_soc_percent=80, ready_by="07:00", repeat="daily"))
    assert "anchor_date" not in json.loads(state_file.read_text())["ev1"]


@pytest.mark.asyncio
async def test_legacy_goal_backfill_keeps_current_cycle(api_env, state_file):
    legacy_updated = datetime(2026, 9, 20, 12, 0, tzinfo=UTC).isoformat()
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 80,
                    "ready_by": "07:00",
                    "repeat": "every_n_days",
                    "n_days": 3,
                    "last_updated": legacy_updated,
                }
            }
        )
    )
    await _save(
        EVChargerScheduleBody(target_soc_percent=70, ready_by="07:00", repeat="every_n_days", n_days=3)
    )
    assert json.loads(state_file.read_text())["ev1"]["anchor_date"] == "2026-09-20"


def test_resolver_anchor_ignores_last_updated_rewrite():
    goal = {
        "ready_by": "07:00",
        "repeat": "every_n_days",
        "n_days": 3,
        "anchor_date": "2026-09-20",
        "last_updated": datetime(2026, 9, 25, 9, 0, tzinfo=UTC).isoformat(),
    }
    now = TZ.localize(datetime(2026, 9, 25, 10, 0))
    assert resolve_next_ready_by(goal, now, TZ).date() == date(2026, 9, 26)


def test_resolver_legacy_fallback_uses_last_updated():
    goal = {
        "ready_by": "07:00",
        "repeat": "every_n_days",
        "n_days": 3,
        "last_updated": datetime(2026, 9, 20, 9, 0, tzinfo=UTC).isoformat(),
    }
    now = TZ.localize(datetime(2026, 9, 24, 10, 0))
    assert resolve_next_ready_by(goal, now, TZ).date() == date(2026, 9, 26)


# --- 2.5 / 3.6 HA paths ---


def _client() -> HAWebSocketClient:
    client = HAWebSocketClient()
    client.ev_charger_configs = [{"index": 0, "name": "EV1", "id": "ev1"}]
    client.monitored_entities = {
        "input_datetime.ev1_ready": "ev_ready_by_0",
        "input_number.ev1_soc": "ev_target_soc_0",
    }
    return client


def _live_change(monkeypatch, client, entity, value):
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _p: _cfg())
    request = MagicMock()
    monkeypatch.setattr("backend.services.scheduler_service.request_replan", request)
    ev_state.last_darkstar_write.pop("ev1", None)
    with patch("backend.core.websockets.ws_manager.emit_sync"):
        client._handle_state_change(entity, {"state": value})
    return request


def test_live_ready_by_on_daily_goal_becomes_one_off_and_replans(monkeypatch, state_file):
    state_file.write_text(
        json.dumps({"ev1": {"target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily"}})
    )
    request = _live_change(monkeypatch, _client(), "input_datetime.ev1_ready", "2026-09-27 06:30:00")

    goal = json.loads(state_file.read_text())["ev1"]
    assert (goal["repeat"], goal["ready_by_date"], goal["ready_by"]) == ("none", "2026-09-27", "06:30")
    request.assert_called_once_with(ReplanReason.GOAL_CHANGE, charger_ids=["ev1"])


def test_live_soc_only_change_keeps_repeat_and_anchor(monkeypatch, state_file):
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 80,
                    "ready_by": "07:00",
                    "repeat": "every_n_days",
                    "n_days": 3,
                    "anchor_date": "2026-09-20",
                }
            }
        )
    )
    _live_change(monkeypatch, _client(), "input_number.ev1_soc", "90")
    goal = json.loads(state_file.read_text())["ev1"]
    assert goal["repeat"] == "every_n_days"
    assert goal["anchor_date"] == "2026-09-20"
    assert goal["target_soc_percent"] == 90


def test_live_soc_change_on_weekdays_goal_keeps_repeat(monkeypatch, state_file):
    state_file.write_text(
        json.dumps({"ev1": {"target_soc_percent": 80, "ready_by": "07:00", "repeat": "weekdays"}})
    )
    _live_change(monkeypatch, _client(), "input_number.ev1_soc", "70")
    goal = json.loads(state_file.read_text())["ev1"]
    assert goal["repeat"] == "weekdays"
    assert goal["ready_by"] == "07:00"


def test_live_soc_change_on_legacy_every_n_days_backfills_anchor(monkeypatch, state_file):
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 80,
                    "ready_by": "07:00",
                    "repeat": "every_n_days",
                    "n_days": 3,
                    "last_updated": datetime(2026, 9, 20, 9, 0, tzinfo=UTC).isoformat(),
                }
            }
        )
    )
    _live_change(monkeypatch, _client(), "input_number.ev1_soc", "70")
    assert json.loads(state_file.read_text())["ev1"]["anchor_date"] == "2026-09-20"


def test_echo_within_debounce_does_not_replan(monkeypatch, state_file):
    state_file.write_text(
        json.dumps({"ev1": {"target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily"}})
    )
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _p: _cfg())
    request = MagicMock()
    monkeypatch.setattr("backend.services.scheduler_service.request_replan", request)
    ev_state.last_darkstar_write["ev1"] = time.time()
    try:
        _client()._handle_state_change("input_number.ev1_soc", {"state": "90"})
    finally:
        ev_state.last_darkstar_write.pop("ev1", None)
    request.assert_not_called()


def test_live_unchanged_value_does_not_replan(monkeypatch, state_file):
    state_file.write_text(
        json.dumps({"ev1": {"target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily"}})
    )
    request = _live_change(monkeypatch, _client(), "input_number.ev1_soc", "80")
    request.assert_not_called()


def _reconnect(monkeypatch, results):
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _p: _cfg())
    monkeypatch.setattr("backend.api.routers.ev.sync_goal_to_ha", AsyncMock())
    request = MagicMock()
    monkeypatch.setattr("backend.services.scheduler_service.request_replan", request)
    HAWebSocketClient()._sync_ev_schedules_on_startup(results)
    return request


@pytest.mark.asyncio
async def test_reconnect_and_live_produce_same_one_off(monkeypatch, state_file):
    future = (datetime.now(TZ) + timedelta(days=2)).replace(hour=6, minute=30, second=0, microsecond=0)
    future_str = future.strftime("%Y-%m-%d %H:%M:%S")
    daily = {"ev1": {"target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily"}}

    state_file.write_text(json.dumps(daily))
    request = _reconnect(
        monkeypatch,
        [
            {"entity_id": "input_datetime.ev1_ready", "state": future_str},
            {"entity_id": "input_number.ev1_soc", "state": "80"},
        ],
    )
    reconnect_goal = json.loads(state_file.read_text())["ev1"]
    request.assert_called_once_with(ReplanReason.GOAL_CHANGE, charger_ids=["ev1"])

    state_file.write_text(json.dumps(daily))
    _live_change(monkeypatch, _client(), "input_datetime.ev1_ready", future_str)
    live_goal = json.loads(state_file.read_text())["ev1"]

    keys = ("repeat", "ready_by", "ready_by_date", "target_soc_percent")
    assert {k: reconnect_goal[k] for k in keys} == {k: live_goal[k] for k in keys}
    assert reconnect_goal["repeat"] == "none"


@pytest.mark.asyncio
async def test_noop_reconnect_does_not_replan(monkeypatch, state_file):
    future = (datetime.now(TZ) + timedelta(days=2)).replace(hour=6, minute=30, second=0, microsecond=0)
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 80,
                    "ready_by": "06:30",
                    "repeat": "none",
                    "ready_by_date": future.date().isoformat(),
                }
            }
        )
    )
    request = _reconnect(
        monkeypatch,
        [
            {"entity_id": "input_datetime.ev1_ready", "state": future.strftime("%Y-%m-%d %H:%M:%S")},
            {"entity_id": "input_number.ev1_soc", "state": "80"},
        ],
    )
    request.assert_not_called()


# --- plan_pending after a failed goal-triggered run; planned_start ---


def _persisted(edited: datetime, planned: datetime) -> dict:
    return {
        "target_soc_percent": 80,
        "ready_by": "07:00",
        "repeat": "daily",
        "last_updated": edited.isoformat(),
        "last_planned_at": planned.isoformat(),
    }


def test_plan_pending_false_after_failed_goal_run(monkeypatch):
    from backend.services.planner_service import planner_service

    now = datetime.now(UTC)
    persisted = _persisted(now - timedelta(minutes=1), now - timedelta(hours=1))
    monkeypatch.setattr(planner_service, "_goal_waiting", set())
    monkeypatch.setattr(planner_service, "_goal_running", set())
    monkeypatch.setattr(planner_service, "_goal_failed_at", {})
    assert ev_router._plan_pending("ev1", persisted) is True

    planner_service._goal_failed_at["ev1"] = now
    assert ev_router._plan_pending("ev1", persisted) is False

    # A later goal edit makes it pending again.
    edited_again = _persisted(now + timedelta(seconds=5), now - timedelta(hours=1))
    assert ev_router._plan_pending("ev1", edited_again) is True


def test_first_planned_starts_skips_ended_and_zero_slots():
    now = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
    schedule = {
        "schedule": [
            {
                "start_time": "2026-09-25T19:00:00+00:00",
                "end_time": "2026-09-25T19:15:00+00:00",
                "ev_chargers": {"ev1": 7.0},
            },
            {
                "start_time": "2026-09-25T20:00:00+00:00",
                "end_time": "2026-09-25T20:15:00+00:00",
                "ev_chargers": {"ev1": 0.0},
            },
            {
                "start_time": "2026-09-25T20:15:00+00:00",
                "end_time": "2026-09-25T20:30:00+00:00",
                "ev_chargers": {"ev1": 7.0},
            },
        ]
    }
    assert ev_router._first_planned_starts(schedule, now) == {"ev1": "2026-09-25T20:15:00+00:00"}


# --- last_planned_at is the run's wall-clock goal-read instant, not the slot start ---


def _plan_run(goals_read_at: datetime, slot_start: datetime) -> None:
    """Planner writeback as the pipeline does it (floored ``now`` + wall-clock read)."""
    from planner.pipeline import _persist_ev_multi_day_state

    _persist_ev_multi_day_state(
        [{"id": "ev1", "deadline": None, "required_kwh": None, "soc_percent": 50.0}],
        [{"id": "ev1", "rated_power_kw": 7.4}],
        sqlite_path="",
        tz=TZ,
        now=slot_start,
        goals_read_at=goals_read_at,
    )


@pytest.fixture
def idle_planner(monkeypatch):
    from backend.services.planner_service import planner_service

    monkeypatch.setattr(planner_service, "_goal_waiting", set())
    monkeypatch.setattr(planner_service, "_goal_running", set())
    monkeypatch.setattr(planner_service, "_goal_failed_at", {})


def test_goal_saved_early_in_slot_not_pending_after_covering_run(state_file, idle_planner):
    """Regression: goal saved at slot_start+18s, run reads it later in the same slot.

    The plan covers the edit, so it must not stay "re-planning" until the next slot.
    """
    slot_start = TZ.localize(datetime(2026, 9, 25, 22, 0))
    edited = slot_start + timedelta(seconds=18)
    state_file.write_text(
        json.dumps(
            {"ev1": {"target_soc_percent": 80, "ready_by": "07:00", "last_updated": edited.isoformat()}}
        )
    )
    _plan_run(goals_read_at=slot_start + timedelta(seconds=19), slot_start=slot_start)

    persisted = json.loads(state_file.read_text())["ev1"]
    assert persisted["last_planned_at"] == (slot_start + timedelta(seconds=19)).isoformat()
    assert ev_router._plan_pending("ev1", persisted) is False
    # The at-risk staleness check uses the same stamp: diagnostics are current.
    diagnostics = {"shortfall_kwh": 5.0, "required_kwh": 10.0, "deadline": "2026-09-26T07:00:00+02:00"}
    persisted |= {"required_kwh": 10.0, "deadline": "2026-09-26T07:00:00+02:00"}
    assert ev_router._active_goal_shortfall(diagnostics, persisted) == diagnostics


def test_goal_edited_during_run_stays_pending_until_follow_up(state_file, idle_planner):
    slot_start = TZ.localize(datetime(2026, 9, 25, 22, 0))
    first_read = slot_start + timedelta(seconds=20)
    state_file.write_text(
        json.dumps(
            {
                "ev1": {
                    "target_soc_percent": 80,
                    "ready_by": "07:00",
                    "last_updated": (slot_start + timedelta(seconds=10)).isoformat(),
                }
            }
        )
    )
    # User edits the goal after the run read the goals but before it persisted.
    edited_during_run = first_read + timedelta(seconds=5)
    state = json.loads(state_file.read_text())
    state["ev1"] |= {"target_soc_percent": 90, "last_updated": edited_during_run.isoformat()}
    state_file.write_text(json.dumps(state))

    _plan_run(goals_read_at=first_read, slot_start=slot_start)
    persisted = json.loads(state_file.read_text())["ev1"]
    assert persisted["last_updated"] == edited_during_run.isoformat()
    assert ev_router._plan_pending("ev1", persisted) is True

    # Coalesced follow-up run reads the edited goal.
    _plan_run(goals_read_at=edited_during_run + timedelta(seconds=30), slot_start=slot_start)
    persisted = json.loads(state_file.read_text())["ev1"]
    assert ev_router._plan_pending("ev1", persisted) is False
