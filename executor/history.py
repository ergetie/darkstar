"""
Execution History Manager

Manages the execution_log table in SQLite for storing detailed
execution records used by learning and debugging.
"""

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """A single execution record to be logged."""

    # Timing
    executed_at: str  # ISO timestamp
    slot_start: str  # Which slot we were executing

    # What we planned to do (from schedule.json)
    planned_charge_kw: Optional[float] = None
    planned_discharge_kw: Optional[float] = None
    planned_export_kw: Optional[float] = None
    planned_water_kw: Optional[float] = None
    planned_soc_target: Optional[int] = None
    planned_soc_projected: Optional[int] = None

    # What we actually commanded (after override logic)
    commanded_work_mode: Optional[str] = None
    commanded_grid_charging: Optional[int] = None  # 0/1
    commanded_charge_current_a: Optional[float] = None
    commanded_discharge_current_a: Optional[float] = None
    commanded_soc_target: Optional[int] = None
    commanded_water_temp: Optional[int] = None

    # State before execution
    before_soc_percent: Optional[float] = None
    before_work_mode: Optional[str] = None
    before_water_temp: Optional[float] = None
    before_pv_kw: Optional[float] = None
    before_load_kw: Optional[float] = None

    # Override info
    override_active: int = 0
    override_type: Optional[str] = None
    override_reason: Optional[str] = None

    # Execution result
    success: int = 1  # 1=success, 0=failure
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None

    # Metadata
    source: str = "native"
    executor_version: Optional[str] = None


class ExecutionHistory:
    """
    Manages execution history in SQLite.

    Uses the existing planner_learning.db database to keep
    everything in one place for learning integration.
    """

    def __init__(self, db_path: str, timezone: str = "Europe/Stockholm"):
        self.db_path = db_path
        self.timezone = pytz.timezone(timezone)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the execution_log table if it doesn't exist."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    
                    -- Timing
                    executed_at TEXT NOT NULL,
                    slot_start TEXT NOT NULL,
                    
                    -- What we planned to do (from schedule.json)
                    planned_charge_kw REAL,
                    planned_discharge_kw REAL,
                    planned_export_kw REAL,
                    planned_water_kw REAL,
                    planned_soc_target INTEGER,
                    planned_soc_projected INTEGER,
                    
                    -- What we actually commanded (after override logic)
                    commanded_work_mode TEXT,
                    commanded_grid_charging INTEGER,
                    commanded_charge_current_a REAL,
                    commanded_discharge_current_a REAL,
                    commanded_soc_target INTEGER,
                    commanded_water_temp INTEGER,
                    
                    -- State before execution
                    before_soc_percent REAL,
                    before_work_mode TEXT,
                    before_water_temp REAL,
                    before_pv_kw REAL,
                    before_load_kw REAL,
                    
                    -- Override info
                    override_active INTEGER DEFAULT 0,
                    override_type TEXT,
                    override_reason TEXT,
                    
                    -- Execution result
                    success INTEGER NOT NULL,
                    error_message TEXT,
                    duration_ms INTEGER,
                    
                    -- Metadata
                    source TEXT DEFAULT 'native',
                    executor_version TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_log_slot ON execution_log(slot_start)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_log_time ON execution_log(executed_at)"
            )
            conn.commit()

    def log_execution(self, record: ExecutionRecord) -> int:
        """
        Log an execution record to the database.

        Returns the inserted row ID.
        """
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.execute(
                """
                INSERT INTO execution_log (
                    executed_at, slot_start,
                    planned_charge_kw, planned_discharge_kw, planned_export_kw,
                    planned_water_kw, planned_soc_target, planned_soc_projected,
                    commanded_work_mode, commanded_grid_charging,
                    commanded_charge_current_a, commanded_discharge_current_a,
                    commanded_soc_target, commanded_water_temp,
                    before_soc_percent, before_work_mode, before_water_temp,
                    before_pv_kw, before_load_kw,
                    override_active, override_type, override_reason,
                    success, error_message, duration_ms,
                    source, executor_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.executed_at,
                    record.slot_start,
                    record.planned_charge_kw,
                    record.planned_discharge_kw,
                    record.planned_export_kw,
                    record.planned_water_kw,
                    record.planned_soc_target,
                    record.planned_soc_projected,
                    record.commanded_work_mode,
                    record.commanded_grid_charging,
                    record.commanded_charge_current_a,
                    record.commanded_discharge_current_a,
                    record.commanded_soc_target,
                    record.commanded_water_temp,
                    record.before_soc_percent,
                    record.before_work_mode,
                    record.before_water_temp,
                    record.before_pv_kw,
                    record.before_load_kw,
                    record.override_active,
                    record.override_type,
                    record.override_reason,
                    record.success,
                    record.error_message,
                    record.duration_ms,
                    record.source,
                    record.executor_version,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def update_slot_observation(self, slot_start: str, action_summary: Dict[str, Any]) -> None:
        """
        Update slot_observations.executed_action for learning integration.

        This links the executor's commanded actions to the observation record.
        """
        try:
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                conn.execute(
                    """
                    UPDATE slot_observations 
                    SET executed_action = ?
                    WHERE slot_start = ?
                    """,
                    (json.dumps(action_summary), slot_start),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to update slot_observations: %s", e)

    def get_history(
        self,
        limit: int = 100,
        offset: int = 0,
        slot_start: Optional[str] = None,
        success_only: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query execution history with optional filters.

        Args:
            limit: Maximum number of records to return
            offset: Offset for pagination
            slot_start: Filter by specific slot start time
            success_only: Filter by success status (True=success, False=failure, None=all)

        Returns:
            List of execution records as dictionaries
        """
        query = "SELECT * FROM execution_log WHERE 1=1"
        params: List[Any] = []

        if slot_start:
            query += " AND slot_start = ?"
            params.append(slot_start)

        if success_only is not None:
            query += " AND success = ?"
            params.append(1 if success_only else 0)

        query += " ORDER BY executed_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Get the most recent execution record."""
        records = self.get_history(limit=1)
        return records[0] if records else None

    def cleanup_old_records(self, retention_days: int = 30) -> int:
        """
        Delete execution records older than retention_days.

        Returns the number of deleted records.
        """
        cutoff = (datetime.now(self.timezone) - timedelta(days=retention_days)).isoformat()
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.execute(
                "DELETE FROM execution_log WHERE executed_at < ?",
                (cutoff,),
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info("Cleaned up %d old execution records", deleted)
            return deleted

    def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """
        Get execution statistics for the last N days.

        Returns summary stats like success rate, override frequency, etc.
        """
        cutoff = (datetime.now(self.timezone) - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            # Total executions
            total = conn.execute(
                "SELECT COUNT(*) FROM execution_log WHERE executed_at >= ?",
                (cutoff,),
            ).fetchone()[0]

            # Success count
            success = conn.execute(
                "SELECT COUNT(*) FROM execution_log WHERE executed_at >= ? AND success = 1",
                (cutoff,),
            ).fetchone()[0]

            # Override count
            overrides = conn.execute(
                "SELECT COUNT(*) FROM execution_log WHERE executed_at >= ? AND override_active = 1",
                (cutoff,),
            ).fetchone()[0]

            # Override types breakdown
            override_types = conn.execute(
                """
                SELECT override_type, COUNT(*) as count 
                FROM execution_log 
                WHERE executed_at >= ? AND override_active = 1
                GROUP BY override_type
                """,
                (cutoff,),
            ).fetchall()

        return {
            "period_days": days,
            "total_executions": total,
            "successful": success,
            "failed": total - success,
            "success_rate": round(success / total * 100, 1) if total > 0 else 0,
            "override_count": overrides,
            "override_rate": round(overrides / total * 100, 1) if total > 0 else 0,
            "override_types": {row[0]: row[1] for row in override_types if row[0]},
        }
