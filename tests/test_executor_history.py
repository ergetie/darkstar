"""
Tests for Executor History (ExecutionHistory and ExecutionRecord)

Tests the SQLite-based execution history storage.
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

import pytest
import pytz

from executor.history import ExecutionHistory, ExecutionRecord
import contextlib


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    with contextlib.suppress(OSError):
        os.unlink(db_path)


@pytest.fixture
def history(temp_db):
    """Create an ExecutionHistory instance with temp DB."""
    return ExecutionHistory(temp_db, timezone="Europe/Stockholm")


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


class TestExecutionHistorySchema:
    """Test table creation and schema."""

    def test_creates_table_on_init(self, temp_db):
        """Table is created on initialization."""
        ExecutionHistory(temp_db)

        # Check table exists
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='execution_log'"
            )
            assert cursor.fetchone() is not None

    def test_schema_has_required_columns(self, temp_db):
        """Table has all required columns."""
        ExecutionHistory(temp_db)

        with sqlite3.connect(temp_db) as conn:
            cursor = conn.execute("PRAGMA table_info(execution_log)")
            columns = {row[1] for row in cursor.fetchall()}

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
                override_type="emergency_charge" if override else None,
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
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # Insert old and new records
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
