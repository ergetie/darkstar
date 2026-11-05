"""executor-write-safety-and-success-rate: unthrottled tick counters, persisted in system_state.

Covers TickStats (record/prune/JSON), persistence through the real
ExecutionHistory on a temp sqlite file, and the engine wiring (which ticks
count, HA-down reasons, EV notice instead of a failed tick).
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.actions import ActionDispatcher, ActionResult, HACallError, HAClient
from executor.config import (
    ControllerConfig,
    EVChargerDeviceConfig,
    ExecutorConfig,
    InverterConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.engine import EVChargerState, ExecutorEngine
from executor.history import ExecutionHistory
from executor.override import SystemState
from executor.tick_stats import (
    MAX_ACTIONS_PER_BUCKET,
    MAX_ERROR_CHARS,
    TICK_STATS_KEY,
    TickStats,
)

T0 = datetime(2026, 6, 15, 10, 20, tzinfo=UTC)
EV_NOTICE_KEY = "executor_ev_charge_notice"


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "ticks.db")
    db_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(db_engine)
    db_engine.dispose()
    return path


def _totals(stats: TickStats) -> tuple[int, int]:
    return (
        sum(b["t"] for b in stats.buckets.values()),
        sum(b["f"] for b in stats.buckets.values()),
    )


class TestTickStats:
    def test_record_counts_total_and_failed_once_per_tick(self):
        stats = TickStats()
        stats.record(T0, [])
        stats.record(
            T0,
            [
                ("charge_discharge_power", "input_number.x", "HTTP 400"),
                ("work_mode", "select.y", "HTTP 500"),
            ],
        )
        bucket = stats.buckets["2026-06-15T10"]
        assert (bucket["t"], bucket["f"]) == (2, 1)
        assert bucket["a"]["charge_discharge_power"] == {
            "n": 1,
            "entity": "input_number.x",
            "err": "HTTP 400",
        }
        assert bucket["a"]["work_mode"]["n"] == 1
        assert stats.dirty is True

    def test_repeated_failures_keep_last_error(self):
        stats = TickStats()
        stats.record(T0, [("a", "number.a", "first")])
        stats.record(T0, [("a", "number.a", "second")])
        entry = stats.buckets["2026-06-15T10"]["a"]["a"]
        assert entry["n"] == 2 and entry["err"] == "second"

    def test_hour_boundary_opens_new_bucket(self):
        stats = TickStats()
        stats.record(datetime(2026, 6, 15, 10, 59, 59, tzinfo=UTC), [])
        stats.record(datetime(2026, 6, 15, 11, 0, 0, tzinfo=UTC), [])
        assert sorted(stats.buckets) == ["2026-06-15T10", "2026-06-15T11"]

    def test_buckets_are_utc_regardless_of_input_timezone(self):
        stats = TickStats()
        stats.record(pytz.timezone("Europe/Stockholm").localize(datetime(2026, 6, 15, 12, 5)), [])
        assert list(stats.buckets) == ["2026-06-15T10"]

    def test_prune_drops_buckets_older_than_25h_across_day_boundary(self):
        stats = TickStats()
        old = datetime(2026, 6, 14, 8, 0, tzinfo=UTC)
        keep = datetime(2026, 6, 14, 10, 0, tzinfo=UTC)  # 24 h before T0
        stats.record(old, [])
        stats.record(keep, [])
        stats.record(T0, [])  # prunes relative to T0
        assert sorted(stats.buckets) == ["2026-06-14T10", "2026-06-15T10"]

    def test_action_cap_and_error_truncation(self):
        stats = TickStats()
        failures = [(f"action_{i}", None, "x" * 500) for i in range(MAX_ACTIONS_PER_BUCKET + 5)]
        stats.record(T0, failures)
        actions = stats.buckets["2026-06-15T10"]["a"]
        assert len(actions) == MAX_ACTIONS_PER_BUCKET
        assert all(len(a["err"]) == MAX_ERROR_CHARS for a in actions.values())
        # the tick itself is still counted failed once
        assert _totals(stats) == (1, 1)

    def test_json_round_trip(self):
        stats = TickStats()
        stats.record(T0, [("a", "number.a", "boom")])
        stats.record(T0 + timedelta(hours=1), [])
        restored = TickStats.from_json(stats.to_json())
        assert restored.buckets == stats.buckets
        assert json.loads(stats.to_json())["v"] == 1

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "{not json",
            "[]",
            '{"v": 2, "buckets": {}}',
            '{"v": 1, "buckets": []}',
            '{"v": 1, "buckets": {"not-a-key": {"t": 1, "f": 0}}}',
            '{"v": 1, "buckets": {"2026-06-15T10": {"t": "x", "f": 0}}}',
            '{"v": 1, "buckets": {"2026-06-15T10": {"f": 0}}}',
        ],
    )
    def test_corrupt_or_foreign_json_yields_empty_stats(self, raw):
        stats = TickStats.from_json(raw)
        assert stats.buckets == {}


class TestPersistence:
    def test_history_system_state_round_trip_and_upsert(self, db_path):
        history = ExecutionHistory(db_path)
        assert history.get_system_state(TICK_STATS_KEY) is None
        history.set_system_state(TICK_STATS_KEY, "one")
        history.set_system_state(TICK_STATS_KEY, "two")
        assert history.get_system_state(TICK_STATS_KEY) == "two"

    def test_restart_restores_counters(self, db_path):
        history = ExecutionHistory(db_path)
        stats = TickStats()
        for _ in range(800):
            stats.record(T0, [])
        history.set_system_state(TICK_STATS_KEY, stats.to_json())

        restored = TickStats.from_json(ExecutionHistory(db_path).get_system_state(TICK_STATS_KEY))
        assert _totals(restored) == (800, 0)


def _make_engine(db_path: str, schedule_path: str, **config_overrides) -> ExecutorEngine:
    config = ExecutorConfig(
        enabled=True,
        schedule_path=schedule_path,
        timezone="Europe/Stockholm",
        inverter=InverterConfig(),
        water_heater=WaterHeaterConfig(),
        notifications=NotificationConfig(),
        controller=ControllerConfig(),
        **config_overrides,
    )
    with (
        patch("executor.engine.load_executor_config", return_value=config),
        patch("executor.engine.load_yaml", return_value={"input_sensors": {}}),
        patch.object(ExecutorEngine, "_get_db_path", return_value=db_path),
        patch("executor.engine.LoadDisaggregator"),
    ):
        engine = ExecutorEngine("config.yaml")
    ha = MagicMock(spec=HAClient)
    ha.get_state_value = AsyncMock(return_value="0.0")
    ha.get_state = AsyncMock(return_value={"state": "0.0", "attributes": {}})
    ha.set_number = AsyncMock(return_value=True)
    ha.set_select_option = AsyncMock(return_value=True)
    ha.set_switch = AsyncMock(return_value=True)
    engine.ha_client = ha
    engine.dispatcher = ActionDispatcher(ha, config, shadow_mode=config.shadow_mode)
    engine.dispatcher.notify_error = AsyncMock()
    # Healthy profile writes; tests that need failures patch `execute` themselves.
    engine.dispatcher.execute = AsyncMock(return_value=[])
    return engine


def _write_schedule(path: Path) -> None:
    tz = pytz.timezone("Europe/Stockholm")
    start = datetime.now(tz) - timedelta(minutes=5)
    end = start + timedelta(minutes=15)
    path.write_text(
        json.dumps(
            {
                "schedule": [
                    {
                        "start_time": start.isoformat(),
                        "end_time": end.isoformat(),
                        "end_time_kepler": end.isoformat(),
                        "battery_charge_kw": 0,
                        "battery_discharge_kw": 0,
                        "export_kwh": 0,
                        "water_heating_kw": 0,
                        "soc_target_percent": 50,
                        "projected_soc_percent": 45,
                    }
                ],
                "meta": {"generated_at": datetime.now(tz).isoformat()},
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def engine(db_path, tmp_path) -> ExecutorEngine:
    schedule = tmp_path / "schedule.json"
    _write_schedule(schedule)
    return _make_engine(db_path, str(schedule))


def _persisted(engine: ExecutorEngine) -> TickStats:
    return TickStats.from_json(engine.history.get_system_state(TICK_STATS_KEY))


@pytest.mark.asyncio
class TestEngineCounting:
    async def test_every_tick_is_counted_though_the_log_is_throttled(self, engine, db_path):
        for _ in range(6):
            await engine._tick()

        assert _totals(engine._tick_stats) == (6, 0)
        logged = len(engine.history.get_history(limit=100))
        assert logged < 6, "idle ticks must be throttled in execution_log"

    async def test_counters_flush_and_restore_on_restart(self, engine, db_path, tmp_path):
        for _ in range(3):
            await engine._tick()
        engine._flush_tick_stats(force=True)
        assert _totals(_persisted(engine)) == (3, 0)

        restarted = _make_engine(db_path, str(tmp_path / "schedule.json"))
        assert _totals(restarted._tick_stats) == (3, 0)

    async def test_flush_is_rate_limited_to_30s(self, engine):
        engine._tick_stats_flushed_at = 1000.0
        with patch("executor.engine.time.monotonic", return_value=1010.0):
            await engine._tick()
        assert engine.history.get_system_state(TICK_STATS_KEY) is None
        with patch("executor.engine.time.monotonic", return_value=1031.0):
            await engine._tick()
        assert _totals(_persisted(engine)) == (2, 0)

    async def test_flush_errors_never_raise_into_the_tick(self, engine):
        engine.history = MagicMock()
        engine.history.set_system_state.side_effect = RuntimeError("db locked")
        engine._tick_stats_flushed_at = 0.0
        with patch("executor.engine.time.monotonic", return_value=10_000.0):
            result = await engine._tick()
        assert result["success"] is True
        assert engine._tick_stats.dirty is True

    async def test_failed_action_counts_tick_once_and_action_with_entity_and_error(self, engine):
        results = [
            ActionResult(
                action_type="charge_discharge_power",
                success=False,
                entity_id="input_number.darkstar_power_rec_w",
                error_details="HTTP 400 | Response: out of range",
            ),
            ActionResult(action_type="work_mode", success=False, message="Failed to set work_mode"),
            ActionResult(action_type="soc", success=True, skipped=True),
        ]
        with patch.object(engine.dispatcher, "execute", AsyncMock(return_value=results)):
            await engine._tick()

        assert _totals(engine._tick_stats) == (1, 1)
        actions = next(iter(engine._tick_stats.buckets.values()))["a"]
        assert actions["charge_discharge_power"]["entity"] == "input_number.darkstar_power_rec_w"
        assert "out of range" in actions["charge_discharge_power"]["err"]
        assert actions["work_mode"]["err"] == "Failed to set work_mode"
        assert "soc" not in actions

    async def test_ha_unavailable_failure_is_labelled(self, engine):
        results = [
            ActionResult(
                action_type="work_mode",
                success=False,
                entity_id="select.mode",
                error_details="retries exhausted",
                ha_unavailable=True,
            )
        ]
        with patch.object(engine.dispatcher, "execute", AsyncMock(return_value=results)):
            await engine._tick()
        entry = next(iter(engine._tick_stats.buckets.values()))["a"]["work_mode"]
        assert entry["err"].startswith("HA unavailable")

    async def test_tick_exception_counts_as_engine_tick_failure(self, engine):
        with patch.object(engine, "_gather_system_state", AsyncMock(side_effect=RuntimeError("boom"))):
            result = await engine._tick()
        assert result["success"] is False
        assert _totals(engine._tick_stats) == (1, 1)
        entry = next(iter(engine._tick_stats.buckets.values()))["a"]["engine_tick"]
        assert entry["err"] == "boom"

    async def test_ha_call_error_without_status_is_labelled_ha_unavailable(self, engine):
        error = HACallError("retries exhausted", exception_type="ClientConnectorError")
        with patch.object(engine, "_gather_system_state", AsyncMock(side_effect=error)):
            await engine._tick()
        entry = next(iter(engine._tick_stats.buckets.values()))["a"]["engine_tick"]
        assert entry["err"].startswith("HA unavailable")

    async def test_paused_ticks_are_not_counted(self, engine):
        engine.pause()
        await engine._tick()
        assert engine._tick_stats.buckets == {}

    async def test_manual_override_ticks_are_not_counted(self, engine):
        state = SystemState(manual_override_active=True)
        with patch.object(engine, "_gather_system_state", AsyncMock(return_value=state)):
            await engine._tick()
        assert engine._tick_stats.buckets == {}

    async def test_shadow_mode_ticks_are_not_counted(self, db_path, tmp_path):
        schedule = tmp_path / "schedule.json"
        _write_schedule(schedule)
        shadow_engine = _make_engine(db_path, str(schedule), shadow_mode=True)
        await shadow_engine._tick()
        assert shadow_engine._tick_stats.buckets == {}

    async def test_stale_schedule_hold_is_not_counted(self, db_path, tmp_path):
        schedule = tmp_path / "schedule.json"
        _write_schedule(schedule)
        payload = json.loads(schedule.read_text(encoding="utf-8"))
        payload["meta"]["generated_at"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        schedule.write_text(json.dumps(payload), encoding="utf-8")
        stale_engine = _make_engine(db_path, str(schedule))
        await stale_engine._tick()
        assert stale_engine._stale_schedule_warning
        assert stale_engine._tick_stats.buckets == {}

    async def test_automation_toggle_off_is_not_counted(self, db_path, tmp_path):
        schedule = tmp_path / "schedule.json"
        _write_schedule(schedule)
        toggled = _make_engine(
            db_path, str(schedule), automation_toggle_entity="input_boolean.automation"
        )
        toggled.ha_client.get_state_value = AsyncMock(return_value="off")
        await toggled._tick()
        assert toggled._tick_stats.buckets == {}

    async def test_ev_logging_rows_never_feed_the_counters(self, engine):
        result = ActionResult(action_type="ev_charge_current", success=False, message="nope")
        engine._log_ev_action("c1", result, "charge", datetime.now(UTC))
        assert engine._tick_stats.buckets == {}
        assert engine._tick_stats.dirty is False


@pytest.mark.asyncio
class TestEvChargeNotice:
    """The zero-power heuristic raises a notice and never fails the tick record."""

    @pytest.fixture
    def ev_engine(self, db_path, tmp_path) -> ExecutorEngine:
        schedule = tmp_path / "schedule.json"
        _write_schedule(schedule)
        ev_engine = _make_engine(
            db_path, str(schedule), ev_chargers=[EVChargerDeviceConfig(id="c1", name="Car")]
        )
        ev_engine._has_ev_charger = True
        ev_engine._ev_charger_states["c1"] = EVChargerState(charging_active=True)
        ev_engine._request_balancer_replan = MagicMock()
        return ev_engine

    def _notice(self, engine: ExecutorEngine) -> dict | None:
        raw = engine.history.get_system_state(EV_NOTICE_KEY)
        return json.loads(raw) if raw else None

    async def test_notice_persisted_after_five_zero_power_ticks(self, ev_engine):
        now = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
        for _ in range(5):
            await ev_engine._check_ev_charge_failure(True, 0.0, now=now)

        notice = self._notice(ev_engine)
        assert notice is not None
        assert notice["active"] is True
        assert notice["since"] == now.isoformat()
        assert notice["commanded"] is True
        assert notice["actual_kw"] == 0.0
        assert "0.00kW actual" in notice["message"]
        assert notice["message"] == ev_engine.dispatcher.notify_error.call_args[0][0]

    async def test_notice_cleared_on_recovery(self, ev_engine):
        now = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
        for _ in range(5):
            await ev_engine._check_ev_charge_failure(True, 0.0, now=now)
        await ev_engine._check_ev_charge_failure(True, 3.2, now=now)
        assert self._notice(ev_engine) == {"active": False}

    async def test_notice_cleared_when_no_longer_commanded(self, ev_engine):
        now = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
        for _ in range(5):
            await ev_engine._check_ev_charge_failure(True, 0.0, now=now)
        await ev_engine._check_ev_charge_failure(False, 0.0, now=now)
        assert self._notice(ev_engine) == {"active": False}

    async def test_no_write_without_a_notice(self, ev_engine):
        ev_engine.history = MagicMock()
        ev_engine._ev_notice_active = False
        await ev_engine._check_ev_charge_failure(False, 0.0)
        await ev_engine._check_ev_charge_failure(True, 2.0)
        ev_engine.history.set_system_state.assert_not_called()

    async def test_no_notice_without_ev_charger(self, engine):
        # No EV: the tick's EV branch is skipped, so nothing is ever written.
        await engine._tick()
        assert engine.history.get_system_state(EV_NOTICE_KEY) is None

    async def test_active_notice_survives_restart_and_clears(self, ev_engine, db_path, tmp_path):
        now = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
        for _ in range(5):
            await ev_engine._check_ev_charge_failure(True, 0.0, now=now)

        restarted = _make_engine(db_path, str(tmp_path / "schedule.json"))
        assert restarted._ev_notice_active is True
        restarted._clear_ev_charge_notice()
        assert self._notice(restarted) == {"active": False}

    async def test_tick_record_stays_successful_when_ev_failure_fires(self, ev_engine):
        ev_engine._check_ev_charge_failure = AsyncMock(return_value=True)
        ev_engine._control_ev_charger = AsyncMock()
        ev_engine._read_ev_plug_states = AsyncMock(return_value={})
        ev_engine._check_plug_in_reminders = AsyncMock()
        ev_engine._check_ev_soc_stale = AsyncMock()
        ev_engine.history.log_execution = MagicMock(return_value=1)

        await ev_engine._tick()

        ev_engine._check_ev_charge_failure.assert_awaited()
        record = ev_engine.history.log_execution.call_args.args[0]
        assert record.success == 1
        assert _totals(ev_engine._tick_stats) == (1, 0)
