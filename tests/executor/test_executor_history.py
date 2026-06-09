import contextlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytz
from sqlalchemy import inspect, text

from backend.learning.models import Base
from executor.actions import ActionResult
from executor.history import ExecutionHistory, ExecutionRecord


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


@pytest.fixture
def history(temp_db):
    """Create an ExecutionHistory instance with temp DB."""
    h = ExecutionHistory(temp_db, timezone="Europe/Stockholm")
    # Create schema for tests
    Base.metadata.create_all(h.engine)
    return h


class TestExecutionRecord:
    """Test the ExecutionRecord dataclass."""

    def test_required_fields(self):
        """ExecutionRecord requires executed_at and slot_start."""
        record = ExecutionRecord(
            executed_at="2024-01-15T10:00:00+01:00",
            slot_start="2024-01-15T10:00:00+01:00",
        )
        assert record.executed_at == "2024-01-15T10:00:00+01:00"
        assert record.slot_start == "2024-01-15T10:00:00+01:00"

    def test_default_values(self):
        """ExecutionRecord has sensible defaults."""
        record = ExecutionRecord(
            executed_at="2024-01-15T10:00:00+01:00",
            slot_start="2024-01-15T10:00:00+01:00",
        )
        assert record.success == 1
        assert record.source == "native"

    def test_ev_charge_start_record_serializes(self):
        """Verify EV charge start ExecutionRecord serializes to JSON (REV F71)."""
        record = ExecutionRecord(
            executed_at="2026-02-17T20:23:00+01:00",
            slot_start="2026-02-17T20:15:00+01:00",
            commanded_work_mode="ev_charge_start",
            before_soc_percent=50,
            success=1,
            source="ev_charger",
            duration_ms=150,
            action_results=[
                {
                    "type": "ev_charger_switch",
                    "success": True,
                    "message": "EV charger turned on",
                    "entity_id": "switch.laddare_charging",
                    "previous_value": False,
                    "new_value": True,
                    "verified_value": True,
                    "verification_success": True,
                    "skipped": False,
                    "error_details": None,
                }
            ],
        )
        json_str = json.dumps(record.__dict__)
        assert "ev_charge_start" in json_str
        assert "switch.laddare_charging" in json_str

    def test_ev_charge_stop_record_serializes(self):
        """Verify EV charge stop ExecutionRecord serializes to JSON (REV F71)."""
        record = ExecutionRecord(
            executed_at="2026-02-17T20:24:00+01:00",
            slot_start="2026-02-17T20:15:00+01:00",
            commanded_work_mode="ev_charge_stop",
            before_soc_percent=55,
            success=1,
            source="ev_charger",
            duration_ms=120,
            action_results=[
                {
                    "type": "ev_charger_switch",
                    "success": True,
                    "message": "EV charger turned off",
                    "entity_id": "switch.laddare_charging",
                    "previous_value": True,
                    "new_value": False,
                    "verified_value": False,
                    "verification_success": True,
                    "skipped": False,
                    "error_details": None,
                }
            ],
        )
        json_str = json.dumps(record.__dict__)
        assert "ev_charge_stop" in json_str

    def test_action_result_as_dict_serializable(self):
        """Verify that ActionResult converted to dict IS JSON serializable (REV F71)."""
        result = ActionResult(
            action_type="ev_charger_switch",
            success=True,
            message="EV charger turned on",
            entity_id="switch.laddare_charging",
            previous_value=False,
            new_value=True,
            verified_value=True,
            verification_success=True,
            skipped=False,
            error_details=None,
        )
        result_dict = {
            "type": result.action_type,
            "success": result.success,
            "message": result.message,
            "entity_id": result.entity_id,
            "previous_value": result.previous_value,
            "new_value": result.new_value,
            "verified_value": result.verified_value,
            "verification_success": result.verification_success,
            "skipped": result.skipped,
            "error_details": result.error_details,
        }
        json_str = json.dumps(result_dict)
        assert "ev_charger_switch" in json_str


class TestExecutionHistorySchema:
    """Test table creation and schema."""

    def test_creates_table_on_init(self, temp_db):
        """Table is created via create_all in fixture."""
        h = ExecutionHistory(temp_db)
        Base.metadata.create_all(h.engine)

        # Check table exists using inspection
        inspector = inspect(h.engine)
        assert "execution_log" in inspector.get_table_names()

    def test_schema_has_required_columns(self, temp_db):
        """Table has all required columns."""
        h = ExecutionHistory(temp_db)
        Base.metadata.create_all(h.engine)

        inspector = inspect(h.engine)
        columns = {col["name"] for col in inspector.get_columns("execution_log")}

        expected = {
            "id",
            "executed_at",
            "slot_start",
            "planned_charge_kw",
            "planned_discharge_kw",
            "planned_export_kw",
            "commanded_work_mode",
            "commanded_grid_charging",
            "before_soc_percent",
            "success",
            "source",
        }
        assert expected.issubset(columns)


class TestLogExecution:
    """Test ExecutionHistory.log_execution."""

    def test_log_basic_execution(self, history):
        """Can log a basic execution record."""
        record = ExecutionRecord(
            executed_at="2024-01-15T10:00:00+01:00",
            slot_start="2024-01-15T10:00:00+01:00",
            commanded_work_mode="Export First",
            commanded_grid_charging=0,
            success=1,
        )

        row_id = history.log_execution(record)

        assert row_id is not None
        assert row_id > 0

    def test_update_slot_observation_only_touches_executed_action(self, history):
        slot_start = "2024-01-15T10:00:00+01:00"
        with history.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO slot_observations (
                        slot_start, slot_end, import_kwh, export_kwh, pv_kwh, load_kwh,
                        water_kwh, ev_charging_kwh, import_price_sek_kwh, export_price_sek_kwh
                    ) VALUES (
                        :slot_start, :slot_end, 1.0, 2.0, 3.0, 4.0, 0.5, 0.25, 1.5, 0.75
                    )
                    """
                ),
                {"slot_start": slot_start, "slot_end": "2024-01-15T10:15:00+01:00"},
            )

        history.update_slot_observation(slot_start, {"mode": "self_use"})

        with history.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT import_kwh, export_kwh, pv_kwh, load_kwh, water_kwh,
                           ev_charging_kwh, import_price_sek_kwh, export_price_sek_kwh,
                           executed_action
                    FROM slot_observations WHERE slot_start = :slot_start
                    """
                ),
                {"slot_start": slot_start},
            ).fetchone()

        assert row[:8] == pytest.approx((1.0, 2.0, 3.0, 4.0, 0.5, 0.25, 1.5, 0.75))
        assert json.loads(row[8]) == {"mode": "self_use"}

    def test_log_full_execution(self, history):
        """Can log a full execution record with all fields."""
        record = ExecutionRecord(
            executed_at="2024-01-15T10:00:00+01:00",
            slot_start="2024-01-15T10:00:00+01:00",
            planned_charge_kw=5.0,
            planned_discharge_kw=0.0,
            planned_export_kw=0.0,
            planned_water_kw=3.0,
            planned_soc_target=80,
            planned_soc_projected=75,
            commanded_work_mode="Zero Export To CT",
            commanded_grid_charging=1,
            commanded_charge_current_a=100.0,
            commanded_discharge_current_a=0.0,
            commanded_soc_target=80,
            commanded_water_temp=60,
            before_soc_percent=45.5,
            before_work_mode="Export First",
            before_water_temp=55.0,
            before_pv_kw=2.5,
            before_load_kw=1.8,
            override_active=0,
            success=1,
            duration_ms=150,
            source="native",
            executor_version="1.0.0",
        )

        row_id = history.log_execution(record)
        assert row_id > 0


class TestGetHistory:
    """Test ExecutionHistory.get_history."""

    def test_get_history_empty(self, history):
        """Empty history returns empty list."""
        result = history.get_history()
        assert result == []

    def test_get_history_returns_records(self, history):
        """get_history returns logged records."""
        record = ExecutionRecord(
            executed_at="2024-01-15T10:00:00+01:00",
            slot_start="2024-01-15T10:00:00+01:00",
            commanded_work_mode="Export First",
            success=1,
        )
        history.log_execution(record)

        result = history.get_history()

        assert len(result) == 1
        assert result[0]["commanded_work_mode"] == "Export First"

    def test_get_history_respects_limit(self, history):
        """get_history respects limit parameter."""
        # Log 5 records
        for i in range(5):
            record = ExecutionRecord(
                executed_at=f"2024-01-15T10:0{i}:00+01:00",
                slot_start=f"2024-01-15T10:0{i}:00+01:00",
                commanded_work_mode="Export First",
                success=1,
            )
            history.log_execution(record)

        result = history.get_history(limit=3)

        assert len(result) == 3

    def test_get_history_orders_by_newest_first(self, history):
        """get_history returns newest first."""
        for i in range(3):
            record = ExecutionRecord(
                executed_at=f"2024-01-15T1{i}:00:00+01:00",
                slot_start=f"2024-01-15T1{i}:00:00+01:00",
                commanded_work_mode=f"mode_{i}",
                success=1,
            )
            history.log_execution(record)

        result = history.get_history()

        # Newest (12:00) should be first
        assert "12:00" in result[0]["executed_at"]


class TestGetLatest:
    """Test ExecutionHistory.get_latest."""

    def test_get_latest_empty(self, history):
        """get_latest returns None for empty history."""
        result = history.get_latest()
        assert result is None

    def test_get_latest_returns_most_recent(self, history):
        """get_latest returns the most recent record."""
        for i in range(3):
            record = ExecutionRecord(
                executed_at=f"2024-01-15T1{i}:00:00+01:00",
                slot_start=f"2024-01-15T1{i}:00:00+01:00",
                commanded_work_mode=f"mode_{i}",
                success=1,
            )
            history.log_execution(record)

        result = history.get_latest()

        assert result is not None
        assert "12:00" in result["executed_at"]


class TestGetStats:
    """Test ExecutionHistory.get_stats."""

    def test_get_stats_empty(self, history):
        """get_stats returns zeros for empty history."""
        stats = history.get_stats()

        assert stats["total_executions"] == 0
        assert stats["successful"] == 0

    def test_get_stats_counts_executions(self, history):
        """get_stats correctly counts executions."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # 2 successful, 1 failed - use recent dates
        for i, success in enumerate([1, 1, 0]):
            exec_time = (now - timedelta(hours=i)).isoformat()
            record = ExecutionRecord(
                executed_at=exec_time,
                slot_start=exec_time,
                commanded_work_mode="Test",
                success=success,
            )
            history.log_execution(record)

        stats = history.get_stats()

        assert stats["total_executions"] == 3
        assert stats["successful"] == 2

    def test_get_stats_counts_overrides(self, history):
        """get_stats counts override activations."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # 1 with override, 2 without - use recent dates
        for i, override in enumerate([1, 0, 0]):
            exec_time = (now - timedelta(hours=i)).isoformat()
            record = ExecutionRecord(
                executed_at=exec_time,
                slot_start=exec_time,
                commanded_work_mode="Test",
                override_active=override,
                override_type="manual_override" if override else None,
                success=1,
            )
            history.log_execution(record)

        stats = history.get_stats()

        assert stats["override_count"] == 1


class TestCleanupOldRecords:
    """Test ExecutionHistory.cleanup_old_records."""

    def test_cleanup_removes_old_records(self, temp_db):
        """cleanup_old_records removes records older than retention period."""
        history = ExecutionHistory(temp_db, timezone="Europe/Stockholm")
        Base.metadata.create_all(history.engine)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # Insert old and new records
        # Note: log_execution uses text dates, so we can just use isoformat
        old_time = (now - timedelta(days=40)).isoformat()
        new_time = (now - timedelta(days=5)).isoformat()

        history.log_execution(
            ExecutionRecord(
                executed_at=old_time,
                slot_start=old_time,
                commanded_work_mode="Old",
                success=1,
            )
        )
        history.log_execution(
            ExecutionRecord(
                executed_at=new_time,
                slot_start=new_time,
                commanded_work_mode="New",
                success=1,
            )
        )

        # Cleanup with 30-day retention
        deleted = history.cleanup_old_records(retention_days=30)

        assert deleted == 1

        # Only new record should remain
        records = history.get_history()
        assert len(records) == 1
        assert records[0]["commanded_work_mode"] == "New"
