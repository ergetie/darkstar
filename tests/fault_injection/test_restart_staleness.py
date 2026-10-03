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
    def test_slot_energy_is_stateless_across_restarts(self):
        """Slot energy is integrated from history over the slot window: a 'restart'
        (a second computation from scratch) yields the identical value, and no
        recorder state is needed or persisted."""
        from backend.core.ha_client import integrate_power_points, parse_power_states

        start = datetime(2026, 10, 1, 12, 0, tzinfo=TZ)
        end = start + timedelta(minutes=15)
        states = [
            {
                "state": "2.0",
                "last_changed": start.isoformat(),
                "attributes": {"unit_of_measurement": "kW"},
            },
            {"state": "4.0", "last_changed": (start + timedelta(minutes=5)).isoformat()},
        ]

        first = integrate_power_points(parse_power_states(states), start, end)
        after_restart = integrate_power_points(parse_power_states(states), start, end)

        assert first == after_restart
        assert first is not None
        assert abs(first[0] - (2.0 * 5 + 4.0 * 10) / 60) < 1e-9
