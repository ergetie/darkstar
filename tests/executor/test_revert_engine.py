"""Engine side of inverter revert detection: windows, notice, notification, resets."""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from executor.actions import ActionDispatcher, RevertEvent
from executor.engine import (
    REVERT_NOTICE_KEY,
    REVERT_WINDOW_MIN_S,
    ExecutorEngine,
)
from executor.override import SystemState

WORK_MODE = "select.inverter_work_mode"
SWITCH = "switch.inverter_battery_grid_charging"


def _write_config(path: Path, extra: str = "") -> None:
    path.write_text(
        "system:\n  inverter_profile: deye\nexecutor:\n  shadow_mode: false\n" + extra
    )
    os.utime(path, (1000, 1000))


def _ha() -> MagicMock:
    ha = MagicMock()
    ha.get_state_value = AsyncMock(return_value="on")
    ha.get_state = AsyncMock(return_value={"state": "on", "attributes": {}})
    ha.send_notification = AsyncMock(return_value=True)
    return ha


class FakeStore:
    def __init__(self):
        self.data: dict[str, str] = {}

    def get_system_state(self, key):
        return self.data.get(key)

    def set_system_state(self, key, value):
        self.data[key] = value


def _make_engine(tmp_path, monkeypatch, extra="", notify_toggle=True):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    config_path = tmp_path / "config.yaml"
    notif = "" if notify_toggle else "  notifications:\n    on_inverter_mode_revert: false\n"
    _write_config(config_path, extra + notif)
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("home_assistant:\n  url: http://test\n  token: test\n")
    engine = ExecutorEngine(str(config_path), str(secrets))
    engine.reload_config()
    engine.history = FakeStore()
    engine.ha_client = _ha()
    engine.dispatcher = ActionDispatcher(
        engine.ha_client, engine.config, profile=engine.inverter_profile
    )
    engine._gather_system_state = AsyncMock(return_value=SystemState())
    engine._get_planner_decision = AsyncMock(return_value=MagicMock())
    return engine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    return _make_engine(tmp_path, monkeypatch)


def _event(entity=WORK_MODE):
    return RevertEvent(entity, "Zero Export To CT", "Export First")


async def _feed(engine, *events):
    engine.dispatcher.drain_revert_events = MagicMock(return_value=list(events))
    await engine._process_reverts(engine_now())


def engine_now():
    from datetime import datetime

    import pytz

    return datetime.now(pytz.UTC)


def _notice(engine):
    raw = engine.history.data.get(REVERT_NOTICE_KEY)
    return json.loads(raw) if raw else None


@pytest.mark.asyncio
async def test_two_events_do_not_warn_third_does(engine):
    await _feed(engine, _event(), _event())
    assert _notice(engine) is None
    engine.ha_client.send_notification.assert_not_awaited()

    await _feed(engine, _event())
    notice = _notice(engine)
    assert notice["active"] is True
    assert notice["entities"] == [
        {"entity": WORK_MODE, "count": 3, "commanded": "Zero Export To CT", "observed": "Export First"}
    ]
    engine.ha_client.send_notification.assert_awaited_once()
    assert WORK_MODE in engine.ha_client.send_notification.await_args.args[2]


@pytest.mark.asyncio
async def test_events_on_two_entities_do_not_add_up(engine):
    await _feed(engine, _event(WORK_MODE), _event(WORK_MODE), _event(SWITCH), _event(SWITCH))
    assert _notice(engine) is None

    await _feed(engine, _event(SWITCH))
    notice = _notice(engine)
    assert [e["entity"] for e in notice["entities"]] == [SWITCH]


@pytest.mark.asyncio
async def test_one_notification_per_episode(engine):
    await _feed(engine, _event(), _event(), _event())
    await _feed(engine, _event())
    await _feed(engine, _event())
    engine.ha_client.send_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_notification_toggle_off_still_raises_notice(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path, monkeypatch, notify_toggle=False)
    await _feed(engine, _event(), _event(), _event())
    assert _notice(engine)["active"] is True
    engine.ha_client.send_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_notice_clears_after_window_and_next_episode_notifies_again(engine):
    with patch("executor.engine.time.monotonic") as mono:
        mono.return_value = 1000.0
        await _feed(engine, _event(), _event(), _event())
        assert _notice(engine)["active"] is True

        mono.return_value = 1000.0 + REVERT_WINDOW_MIN_S + 1
        await _feed(engine)  # events aged out
        assert _notice(engine) == {"active": False}

        await _feed(engine, _event(), _event(), _event())
        assert _notice(engine)["active"] is True
    assert engine.ha_client.send_notification.await_count == 2


@pytest.mark.asyncio
async def test_notice_stays_while_events_remain_in_window(engine):
    with patch("executor.engine.time.monotonic") as mono:
        mono.return_value = 1000.0
        await _feed(engine, _event(), _event())
        mono.return_value = 2000.0
        await _feed(engine, _event())
        assert _notice(engine)["active"] is True

        mono.return_value = 1000.0 + REVERT_WINDOW_MIN_S + 1  # two events expired
        await _feed(engine)
        assert _notice(engine)["active"] is True  # one left: no flapping

        mono.return_value = 2000.0 + REVERT_WINDOW_MIN_S + 1
        await _feed(engine)
        assert _notice(engine) == {"active": False}
    assert engine.ha_client.send_notification.await_count == 1


@pytest.mark.asyncio
async def test_window_scales_with_interval(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path, monkeypatch, extra="  interval_seconds: 1800\n")
    assert engine._revert_window_s() == 4 * 1800


@pytest.mark.asyncio
async def test_restart_keeps_notice_without_renotifying(tmp_path, monkeypatch):
    store = FakeStore()
    store.data[REVERT_NOTICE_KEY] = json.dumps(
        {"active": True, "since": "2026-01-01T00:00:00+00:00", "entities": []}
    )
    with patch.object(
        ExecutorEngine, "_read_system_state", lambda self, key: store.data.get(key)
    ):
        engine = _make_engine(tmp_path, monkeypatch)
    engine.history = store
    assert engine._revert_notice_active is True
    assert engine._revert_since == "2026-01-01T00:00:00+00:00"

    await _feed(engine)  # no events after restart: notice held for one window
    assert json.loads(store.data[REVERT_NOTICE_KEY])["active"] is True

    await _feed(engine, _event(), _event(), _event())  # same condition recurs
    engine.ha_client.send_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_override_tick_clears_baselines(engine):
    engine.dispatcher._verified_command[WORK_MODE] = ("x", 1.0)
    engine._gather_system_state = AsyncMock(
        return_value=SystemState(manual_override_active=True)
    )
    with patch.object(engine, "_load_current_slot", return_value=(None, None)):
        await engine._tick()
    assert engine.dispatcher._verified_command == {}


@pytest.mark.asyncio
async def test_paused_tick_clears_baselines(engine):
    engine.dispatcher._verified_command[WORK_MODE] = ("x", 1.0)
    engine.pause(60)
    await engine._tick()
    assert engine.dispatcher._verified_command == {}


@pytest.mark.asyncio
async def test_automation_toggle_off_clears_baselines(tmp_path, monkeypatch):
    engine = _make_engine(
        tmp_path, monkeypatch, extra="  automation_toggle_entity: input_boolean.darkstar\n"
    )
    engine.ha_client.get_state_value = AsyncMock(return_value="off")
    engine.dispatcher._verified_command[WORK_MODE] = ("x", 1.0)
    await engine._tick()
    assert engine.dispatcher._verified_command == {}


@pytest.mark.asyncio
async def test_shadow_tick_clears_baselines(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path, monkeypatch)
    engine.config.shadow_mode = True
    engine.dispatcher._verified_command[WORK_MODE] = ("x", 1.0)
    with patch.object(engine, "_load_current_slot", return_value=(None, None)):
        await engine._tick()
    assert engine.dispatcher._verified_command == {}
