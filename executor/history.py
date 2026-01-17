"""
Execution History Manager

Manages the execution_log table in SQLite for storing detailed
execution records used by learning and debugging.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytz
from sqlalchemy import create_engine, select, delete, func, desc, text
from sqlalchemy.orm import sessionmaker

from backend.learning.models import ExecutionLog

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """A single execution record to be logged."""

    # Timing
    executed_at: str  # ISO timestamp
    slot_start: str  # Which slot we were executing

    # What we planned to do (from schedule.json)
    planned_charge_kw: float | None = None
    planned_discharge_kw: float | None = None
    planned_export_kw: float | None = None
    planned_water_kw: float | None = None
    planned_soc_target: int | None = None
    planned_soc_projected: int | None = None

    # What we actually commanded (after override logic)
    commanded_work_mode: str | None = None
    commanded_grid_charging: int | None = None  # 0/1
    commanded_charge_current_a: float | None = None
    commanded_discharge_current_a: float | None = None
    commanded_unit: str | None = "A"  # "A" or "W"
    commanded_soc_target: int | None = None
    commanded_water_temp: int | None = None

    # State before execution
    before_soc_percent: float | None = None
    before_work_mode: str | None = None
    before_water_temp: float | None = None
    before_pv_kw: float | None = None
    before_load_kw: float | None = None

    # Override info
    override_active: int = 0
    override_type: str | None = None
    override_reason: str | None = None

    # Execution result
    success: int = 1  # 1=success, 0=failure
    error_message: str | None = None
    duration_ms: int | None = None

    # Metadata
    source: str = "native"
    executor_version: str | None = None


class ExecutionHistory:
    """
    Manages execution history in SQLite using SQLAlchemy ORM.
    """

    def __init__(self, db_path: str, timezone: str = "Europe/Stockholm"):
        self.db_path = db_path
        self.timezone = pytz.timezone(timezone)
        self.engine = create_engine(f"sqlite:///{db_path}")
        self.Session = sessionmaker(bind=self.engine)

    def log_execution(self, record: ExecutionRecord) -> int:
        """
        Log an execution record to the database using SQLAlchemy.
        """
        with self.Session() as session:
            entry = ExecutionLog(
                executed_at=record.executed_at,
                slot_start=record.slot_start,
                planned_charge_kw=record.planned_charge_kw,
                planned_discharge_kw=record.planned_discharge_kw,
                planned_export_kw=record.planned_export_kw,
                planned_water_kw=record.planned_water_kw,
                planned_soc_target=record.planned_soc_target,
                planned_soc_projected=record.planned_soc_projected,
                commanded_work_mode=record.commanded_work_mode,
                commanded_grid_charging=record.commanded_grid_charging,
                commanded_charge_current_a=record.commanded_charge_current_a,
                commanded_discharge_current_a=record.commanded_discharge_current_a,
                commanded_unit=record.commanded_unit or "A",
                commanded_soc_target=record.commanded_soc_target,
                commanded_water_temp=record.commanded_water_temp,
                before_soc_percent=record.before_soc_percent,
                before_work_mode=record.before_work_mode,
                before_water_temp=record.before_water_temp,
                before_pv_kw=record.before_pv_kw,
                before_load_kw=record.before_load_kw,
                override_active=record.override_active,
                override_type=record.override_type,
                override_reason=record.override_reason,
                success=record.success,
                error_message=record.error_message,
                duration_ms=record.duration_ms,
                source=record.source,
                executor_version=record.executor_version
            )
            session.add(entry)
            session.commit()
            return entry.id

    def update_slot_observation(self, slot_start: str, action_summary: dict[str, Any]) -> None:
        """
        Update slot_observations.executed_action for learning integration using SQLAlchemy.
        """
        # Note: This is a cross-module update. For now using text() to avoid circular imports 
        # or needing to know about SlotObservation here if we want to keep it decoupled. 
        # However, since models.py has everything, we could import it.
        from backend.learning.models import SlotObservation
        try:
            with self.Session() as session:
                session.execute(
                    text("UPDATE slot_observations SET executed_action = :action WHERE slot_start = :start"),
                    {"action": json.dumps(action_summary), "start": slot_start}
                )
                session.commit()
        except Exception as e:
            logger.warning("Failed to update slot_observations: %s", e)

    def get_history(
        self,
        limit: int = 100,
        offset: int = 0,
        slot_start: str | None = None,
        success_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        """
        Query execution history with optional filters using SQLAlchemy.
        """
        with self.Session() as session:
            stmt = select(ExecutionLog)
            
            if slot_start:
                stmt = stmt.where(ExecutionLog.slot_start == slot_start)
            
            if success_only is not None:
                stmt = stmt.where(ExecutionLog.success == (1 if success_only else 0))
                
            stmt = stmt.order_by(desc(ExecutionLog.executed_at)).limit(limit).offset(offset)
            
            results = session.execute(stmt).scalars().all()
            
            # Convert to dicts for API compatibility
            return [
                {c.name: getattr(r, c.name) for c in ExecutionLog.__table__.columns}
                for r in results
            ]

    def get_latest(self) -> dict[str, Any] | None:
        """Get the most recent execution record."""
        records = self.get_history(limit=1)
        return records[0] if records else None

    def get_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the N most recent execution records."""
        return self.get_history(limit=limit)

    def cleanup_old_records(self, retention_days: int = 30) -> int:
        """
        Delete execution records older than retention_days using SQLAlchemy.
        """
        cutoff = (datetime.now(self.timezone) - timedelta(days=retention_days)).isoformat()
        with self.Session() as session:
            stmt = delete(ExecutionLog).where(ExecutionLog.executed_at < cutoff)
            result = session.execute(stmt)
            deleted = result.rowcount
            session.commit()
            
            if deleted > 0:
                logger.info("Cleaned up %d old execution records", deleted)
            return deleted

    def get_stats(self, days: int = 7) -> dict[str, Any]:
        """
        Get execution statistics for the last N days using SQLAlchemy.
        """
        cutoff = (datetime.now(self.timezone) - timedelta(days=days)).isoformat()

        with self.Session() as session:
            # 1. Total executions
            total = session.query(func.count(ExecutionLog.id)).filter(ExecutionLog.executed_at >= cutoff).scalar() or 0
            
            # 2. Success count
            success = session.query(func.count(ExecutionLog.id)).filter(
                ExecutionLog.executed_at >= cutoff,
                ExecutionLog.success == 1
            ).scalar() or 0
            
            # 3. Override count
            overrides = session.query(func.count(ExecutionLog.id)).filter(
                ExecutionLog.executed_at >= cutoff,
                ExecutionLog.override_active == 1
            ).scalar() or 0
            
            # 4. Override types breakdown
            override_types = session.query(
                ExecutionLog.override_type,
                func.count(ExecutionLog.id)
            ).filter(
                ExecutionLog.executed_at >= cutoff,
                ExecutionLog.override_active == 1
            ).group_by(ExecutionLog.override_type).all()

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

    def get_todays_slots(self, today_start: datetime, now: datetime) -> list[dict[str, Any]]:
        """
        Get today's execution records formatted for schedule merging using SQLAlchemy.
        """
        today_start_iso = today_start.isoformat()
        now_iso = now.isoformat()

        with self.Session() as session:
            stmt = select(
                ExecutionLog.slot_start,
                ExecutionLog.planned_charge_kw,
                ExecutionLog.planned_discharge_kw,
                ExecutionLog.planned_water_kw,
                ExecutionLog.planned_soc_target,
                ExecutionLog.planned_soc_projected,
                ExecutionLog.commanded_water_temp,
                ExecutionLog.before_soc_percent,
                ExecutionLog.executed_at
            ).where(
                ExecutionLog.slot_start >= today_start_iso,
                ExecutionLog.slot_start < now_iso
            ).order_by(ExecutionLog.slot_start.asc())
            
            rows = session.execute(stmt).all()

        # Group by slot_start, keeping latest execution per slot
        slot_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            slot_start = row[0]
            # If we already have this slot, only update if this execution is newer
            if slot_start in slot_map:
                existing_executed = slot_map[slot_start].get("_executed_at", "")
                if row[8] <= existing_executed:
                    continue

            # Parse slot_start to get end_time (15 min later)
            try:
                start_dt = datetime.fromisoformat(slot_start)
                end_dt = start_dt + timedelta(minutes=15)
                end_time = end_dt.isoformat()
            except Exception:
                end_time = slot_start  # Fallback

            slot_map[slot_start] = {
                "start_time": slot_start,
                "end_time": end_time,
                "battery_charge_kw": round(float(row[1] or 0), 2),
                "battery_discharge_kw": round(float(row[2] or 0), 2),
                "water_heating_kw": round(float(row[3] or 0), 2),
                "soc_target_percent": int(row[4] or 0),
                "projected_soc_percent": int(row[5] or 0),
                "before_soc_percent": float(row[7]) if row[7] else None,
                "is_historical": True,
                "_executed_at": row[8],  # For dedup, removed later
            }

        # Sort by start_time and assign slot numbers, remove internal fields
        preserved: list[dict[str, Any]] = []
        for i, slot_start in enumerate(sorted(slot_map.keys())):
            slot = slot_map[slot_start]
            slot["slot_number"] = i + 1
            del slot["_executed_at"]
            preserved.append(slot)

        logger.info("[preservation] Loaded %d past slots from executor SQLite", len(preserved))
        return preserved
