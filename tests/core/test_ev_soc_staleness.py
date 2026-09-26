"""Resolved SoC with carry window, stale suspension and notification (ev-soc-staleness)."""

from __future__ import annotations

import contextlib
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.core.ev_live_state import (
    consume_soc_recoveries,
    discard_soc_recovery,
    interpret_ev_live_state,
    last_known_soc,
    resolve_soc,
    soc_stale_after_minutes,
    stale_soc_episodes,
    update_stale_soc_episode,
)
from backend.learning.models import Base
from executor.config import EVChargerDeviceConfig, ExecutorConfig, NotificationConfig
from executor.engine import ExecutorEngine
from backend.services.scheduler_service import ReplanReason
from planner.pipeline import _resolve_ev_charger_plan_state

T0 = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
TZ = pytz.timezone("Europe/Stockholm")


def test_live_reading_is_remembered():
    r = resolve_soc("ev1", 62.0, 15, now=T0)
    assert (r.soc_percent, r.status) == (62.0, "live")
    assert last_known_soc("ev1") == (62.0, T0)


def test_carried_within_window():
    resolve_soc("ev1", 55.0, 15, now=T0)
    r = resolve_soc("ev1", None, 15, now=T0 + timedelta(minutes=6))
    assert (r.soc_percent, r.status) == (55.0, "carried")
    assert r.age_minutes == pytest.approx(6.0)


def test_stale_after_window():
    resolve_soc("ev1", 40.0, 15, now=T0)
    r = resolve_soc("ev1", None, 15, now=T0 + timedelta(minutes=40))
    assert (r.soc_percent, r.status) == (None, "stale")
    assert r.age_minutes == pytest.approx(40.0)


def test_custom_window():
    resolve_soc("ev1", 40.0, 30, now=T0)
    assert resolve_soc("ev1", None, 30, now=T0 + timedelta(minutes=20)).status == "carried"


def test_never_read_is_stale():
    r = resolve_soc("ev1", None, 15, now=T0)
    assert (r.status, r.age_minutes) == ("stale", None)


def test_unreadable_does_not_overwrite_last_known():
    interpret_ev_live_state("ev1", "62.0", None, has_soc_sensor=True, has_plug_sensor=False)
    stored = last_known_soc("ev1")
    live = interpret_ev_live_state(
        "ev1", "unavailable", None, has_soc_sensor=True, has_plug_sensor=False
    )
    assert live.soc_percent is None
    assert last_known_soc("ev1") == stored


def test_window_config_default_and_custom():
    assert soc_stale_after_minutes({}) == 15
    assert soc_stale_after_minutes({"soc_stale_after_minutes": 30}) == 30
    assert soc_stale_after_minutes({"soc_stale_after_minutes": "bad"}) == 15


def test_valid_reading_ends_episode():
    stale = resolve_soc("ev1", None, 15, now=T0)
    update_stale_soc_episode("ev1", stale)
    assert "ev1" in stale_soc_episodes()
    resolve_soc("ev1", 70.0, 15, now=T0 + timedelta(minutes=1))
    assert stale_soc_episodes() == {}


def test_recovery_is_reported_once_per_episode():
    update_stale_soc_episode("ev1", resolve_soc("ev1", None, 15, now=T0))
    interpret_ev_live_state("ev1", "70", None, has_soc_sensor=True, has_plug_sensor=False)
    assert consume_soc_recoveries() == {"ev1"}
    assert consume_soc_recoveries() == set()
    # Further valid readings without a new episode are not recoveries.
    resolve_soc("ev1", 71.0, 15)
    assert consume_soc_recoveries() == set()


def test_valid_reading_without_prior_episode_is_not_a_recovery():
    resolve_soc("ev1", 70.0, 15, now=T0)
    assert consume_soc_recoveries() == set()


def test_unplug_ending_episode_is_not_a_recovery():
    update_stale_soc_episode("ev1", resolve_soc("ev1", None, 15, now=T0))
    update_stale_soc_episode("ev1", None)
    assert consume_soc_recoveries() == set()


def test_planner_run_discards_the_recovery_it_planned_from():
    update_stale_soc_episode("ev1", resolve_soc("ev1", None, 15, now=T0))
    resolve_soc("ev1", 70.0, 15)
    discard_soc_recovery("ev1")
    assert consume_soc_recoveries() == set()


# --- Planner ---

GOAL = {
    "id": "ev1",
    "soc_sensor": "sensor.car_soc",
    "battery_capacity_kwh": 60.0,
    "target_soc_percent": 80,
    "ready_by": "07:00",
    "repeat": "daily",
}
NOW = TZ.localize(datetime(2026, 9, 25, 22, 0))


def test_plugged_stale_soc_suspends_goal():
    state = _resolve_ev_charger_plan_state(
        GOAL,
        {"plugged_in": True, "soc_percent": None, "soc_status": "stale", "soc_age_minutes": 40.0},
        {"current_soc_percent": 50.0},
        NOW,
        TZ,
        "",
    )
    assert state["required_kwh"] is None
    assert state["soc_suspended"] is True


def test_plugged_carried_soc_plans_normally():
    state = _resolve_ev_charger_plan_state(
        GOAL,
        {"plugged_in": True, "soc_percent": 50.0, "soc_status": "carried"},
        {},
        NOW,
        TZ,
        "",
    )
    assert state["required_kwh"] == pytest.approx(18.0)
    assert state["soc_suspended"] is False


def test_unplugged_stale_soc_uses_persisted_soc():
    """Assumed-plugged planning is not suspended by staleness (design D4a)."""
    state = _resolve_ev_charger_plan_state(
        GOAL,
        {"plugged_in": False, "soc_percent": None, "soc_status": "stale"},
        {"current_soc_percent": 70.0},
        NOW,
        TZ,
        "",
    )
    assert state["assumed_plugged"] is True
    assert state["required_kwh"] == pytest.approx(6.0)


def test_no_soc_sensor_keeps_socless_path():
    cfg = {k: v for k, v in GOAL.items() if k != "soc_sensor"}
    state = _resolve_ev_charger_plan_state(cfg, {"plugged_in": True}, {}, NOW, TZ, "")
    assert state["required_kwh"] == pytest.approx(48.0)
    assert state["soc_suspended"] is False


def test_kepler_gets_no_goal_for_suspended_charger():
    from planner.solver.adapter import build_ev_charger_inputs

    cfg = {**GOAL, "type": "binary", "rated_power_kw": 11.0, "switch_entity": "switch.ev1"}
    state = _resolve_ev_charger_plan_state(
        cfg, {"plugged_in": True, "soc_percent": None, "soc_status": "stale"}, {}, NOW, TZ, ""
    )
    inputs = build_ev_charger_inputs([cfg], [state], 230.0)
    assert all(i.required_kwh is None for i in inputs)


# --- Executor notification ---


@pytest.fixture
def engine_factory():
    paths: list[str] = []

    def _make(on_ev_soc_stale: bool = True) -> ExecutorEngine:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            schedule = f.name
        paths.extend([db_path, schedule])
        Base.metadata.create_all(create_engine(f"sqlite:///{db_path}"))
        charger = EVChargerDeviceConfig(id="ev1", name="Go-e", soc_sensor="sensor.car_soc")
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=schedule,
                timezone="Europe/Stockholm",
                ev_chargers=[charger],
                notifications=NotificationConfig(on_ev_soc_stale=on_ev_soc_stale),
            )
            with (
                patch("executor.engine.load_yaml", return_value={}),
                patch.object(ExecutorEngine, "_get_db_path", return_value=db_path),
            ):
                eng = ExecutorEngine("config.yaml")
        eng.dispatcher = MagicMock()
        eng.dispatcher.notify_ev_soc_stale = AsyncMock()
        return eng

    yield _make
    for p in paths:
        with contextlib.suppress(OSError):
            Path(p).unlink()


@pytest.fixture(autouse=True)
def replan_mock():
    with patch("backend.services.scheduler_service.request_replan") as mock:
        yield mock


def _go_stale() -> None:
    update_stale_soc_episode("ev1", resolve_soc("ev1", None, 15, now=T0))


@pytest.mark.asyncio
async def test_one_notification_per_episode(engine_factory):
    eng = engine_factory()
    _go_stale()
    for _ in range(3):
        _go_stale()
        await eng._check_ev_soc_stale()
    eng.dispatcher.notify_ev_soc_stale.assert_awaited_once()
    assert "Go-e" in eng.dispatcher.notify_ev_soc_stale.await_args.args[0]

    # Recovery resets the episode; a new episode notifies again.
    resolve_soc("ev1", 60.0, 15)
    await eng._check_ev_soc_stale()
    _go_stale()
    await eng._check_ev_soc_stale()
    assert eng.dispatcher.notify_ev_soc_stale.await_count == 2


@pytest.mark.asyncio
async def test_no_notification_when_toggle_off(engine_factory):
    eng = engine_factory(on_ev_soc_stale=False)
    _go_stale()
    await eng._check_ev_soc_stale()
    eng.dispatcher.notify_ev_soc_stale.assert_not_awaited()
    # Planning is still suspended: the episode is still reported.
    assert "ev1" in stale_soc_episodes()


@pytest.mark.asyncio
async def test_soc_recovery_requests_exactly_one_replan(engine_factory, replan_mock):
    eng = engine_factory()
    for _ in range(3):
        _go_stale()
        await eng._check_ev_soc_stale()
    replan_mock.assert_not_called()  # no replan while stale

    interpret_ev_live_state("ev1", "65", None, has_soc_sensor=True, has_plug_sensor=False)
    for _ in range(3):
        interpret_ev_live_state("ev1", "65", None, has_soc_sensor=True, has_plug_sensor=False)
        await eng._check_ev_soc_stale()
    replan_mock.assert_called_once_with(ReplanReason.SOC_RECOVERED, charger_ids=["ev1"])


@pytest.mark.asyncio
async def test_no_replan_while_fresh_without_prior_stale(engine_factory, replan_mock):
    eng = engine_factory()
    for _ in range(3):
        resolve_soc("ev1", 60.0, 15)
        await eng._check_ev_soc_stale()
    replan_mock.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_of_unconfigured_charger_is_ignored(engine_factory, replan_mock):
    eng = engine_factory()
    update_stale_soc_episode("other", resolve_soc("other", None, 15, now=T0))
    resolve_soc("other", 60.0, 15)
    await eng._check_ev_soc_stale()
    replan_mock.assert_not_called()
