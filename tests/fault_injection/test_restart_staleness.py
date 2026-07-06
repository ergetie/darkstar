"""Restart-mid-slot and stale-schedule fault injection (spec req 4)."""

from datetime import datetime, timedelta
from pathlib import Path

from tests.fault_injection.conftest import TZ, make_slot, write_schedule


class TestStaleSchedule:
    def test_schedule_past_freshness_bound_is_rejected(self, fi_engine, temp_schedule):
        """A schedule older than max_schedule_age_hours must be held, not executed."""
        now = datetime.now(TZ)
        start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        stale_age = timedelta(hours=fi_engine.config.max_schedule_age_hours + 1)
        write_schedule(temp_schedule, [make_slot(start)], generated_at=now - stale_age)

        slot, slot_start = fi_engine._load_current_slot(now)

        assert slot is None
        assert slot_start is None
        assert fi_engine._stale_schedule_warning is not None
        assert "stale" in fi_engine._stale_schedule_warning.lower()

    def test_fresh_schedule_is_accepted(self, fi_engine, temp_schedule):
        now = datetime.now(TZ)
        start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        write_schedule(temp_schedule, [make_slot(start)], generated_at=now)

        slot, _ = fi_engine._load_current_slot(now)

        assert slot is not None
        assert fi_engine._stale_schedule_warning is None

    def test_schedule_without_generated_at_bypasses_age_check(self, fi_engine, temp_schedule):
        """A schedule with no meta.generated_at is now treated as stale (safe side)
        and held instead of dispatched (findings.md #7.7 caveat, now fixed)."""
        now = datetime.now(TZ)
        start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        write_schedule(temp_schedule, [make_slot(start)], include_meta=False)

        slot, _ = fi_engine._load_current_slot(now)

        assert slot is None  # missing generated_at -> held as stale
        assert fi_engine._stale_schedule_warning is not None

    def test_corrupt_schedule_json_returns_none(self, fi_engine, temp_schedule):
        Path(temp_schedule).write_text("{not valid json", encoding="utf-8")
        slot, slot_start = fi_engine._load_current_slot(datetime.now(TZ))
        assert slot is None and slot_start is None


class TestRestartMidSlot:
    def test_meter_state_survives_restart_without_double_counting(self, tmp_path):
        """Recorder RecorderStateStore persists to disk: a 'restart' (new instance over the
        same state file) must compute the true increment, never re-attribute the
        full cumulative meter value."""
        from backend.recorder import RecorderStateStore

        state_file = tmp_path / "recorder_state.json"
        ts0 = datetime.now(TZ) - timedelta(minutes=15)
        ts1 = datetime.now(TZ)

        m1 = RecorderStateStore(state_file=state_file)
        m1.load()
        first, valid1 = m1.get_delta("import", 1000.0, ts0, sensor_timestamp=ts0)
        assert first is None and valid1 is True  # first-ever reading: no delta

        # Restart: fresh instance, same file; meter advanced 0.5 kWh in 15 min.
        m2 = RecorderStateStore(state_file=state_file)
        m2.load()
        delta, valid2 = m2.get_delta("import", 1000.5, ts1, sensor_timestamp=ts1)

        assert valid2 is True
        assert delta is not None
        assert abs(delta - 0.5) < 0.01  # the increment, not 1000.5

    def test_negative_delta_meter_reset_is_flagged_invalid(self, tmp_path):
        from backend.recorder import RecorderStateStore

        state_file = tmp_path / "recorder_state.json"
        ts0 = datetime.now(TZ) - timedelta(minutes=15)
        m = RecorderStateStore(state_file=state_file)
        m.load()
        m.get_delta("import", 500.0, ts0, sensor_timestamp=ts0)

        m2 = RecorderStateStore(state_file=state_file)
        m2.load()
        delta, valid = m2.get_delta(
            "import", 100.0, datetime.now(TZ), sensor_timestamp=datetime.now(TZ)
        )

        assert valid is False  # meter reset detected
        assert delta is None  # never a negative energy delta

    def test_corrupt_state_file_starts_fresh_without_crash(self, tmp_path):
        from backend.recorder import RecorderStateStore

        state_file = tmp_path / "recorder_state.json"
        state_file.write_text("{corrupt", encoding="utf-8")
        m = RecorderStateStore(state_file=state_file)
        m.load()  # must not raise; corrupted file is discarded
        delta, valid = m.get_delta("import", 100.0, datetime.now(TZ))
        assert delta is None and valid is True  # treated as first reading
