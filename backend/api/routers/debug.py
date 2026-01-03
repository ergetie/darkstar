"""
Debug API Router - Rev ARC1

Provides debug endpoints for logs, history, and diagnostics.
"""

import json
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

import aiosqlite
import pytz
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("darkstar.api.debug")

router = APIRouter(tags=["debug"])


# --- Ring Buffer for Logs ---
class RingBufferHandler(logging.Handler):
    """In-memory ring buffer for log entries that the UI can poll."""

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            timestamp = datetime.fromtimestamp(record.created, tz=UTC)
        except Exception:
            timestamp = datetime.now(UTC)
        entry = {
            "timestamp": timestamp.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        }
        self._buffer.append(entry)

    def get_logs(self) -> list[dict[str, Any]]:
        return list(self._buffer)


# Global ring buffer handler
_ring_buffer_handler = RingBufferHandler(maxlen=1000)
_ring_buffer_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
_ring_buffer_handler.setFormatter(_ring_buffer_formatter)

# Attach to root logger
root_logger = logging.getLogger()
if not any(isinstance(h, RingBufferHandler) for h in root_logger.handlers):
    root_logger.addHandler(_ring_buffer_handler)


@router.get(
    "/api/debug",
    summary="Get Planner Debug Data",
    description="Return comprehensive planner debug data from schedule.json.",
)
async def debug_data() -> dict[str, Any]:
    """Return comprehensive planner debug data from schedule.json."""
    try:
        with open("schedule.json") as f:
            data = json.load(f)

        debug_section = data.get("debug", {})
        if not debug_section:
            return {
                "error": (
                    "No debug data available. "
                    "Enable debug mode in config.yaml with enable_planner_debug: true"
                )
            }

        return debug_section

    except FileNotFoundError:
        raise HTTPException(404, "schedule.json not found. Run the planner first.")


@router.get(
    "/api/debug/logs",
    summary="Get Server Logs",
    description="Return recent server logs stored in the ring buffer handler.",
)
async def debug_logs() -> dict[str, Any]:
    """Return recent server logs stored in the ring buffer handler."""
    try:
        return {"logs": _ring_buffer_handler.get_logs()}
    except Exception as exc:
        logger.exception("Failed to fetch debug logs")
        raise HTTPException(500, str(exc))


@router.get(
    "/api/history/soc",
    summary="Get Historic SoC",
    description="Return historic SoC data for today from learning database.",
)
async def historic_soc(date: str = Query("today")) -> dict[str, Any]:
    """Return historic SoC data for today from learning database."""
    try:
        from backend.learning import get_learning_engine

        tz = pytz.timezone("Europe/Stockholm")

        # Determine target date
        if date == "today":
            target_date = datetime.now(tz).date()
        else:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(400, 'Invalid date format. Use YYYY-MM-DD or "today"')

        # Get learning engine and query historic SoC data
        engine = get_learning_engine()
        db_path = str(getattr(engine, "db_path", ""))

        async with aiosqlite.connect(db_path) as conn:
            query = """
                SELECT slot_start, soc_end_percent, quality_flags
                FROM slot_observations
                WHERE DATE(slot_start) = ?
                  AND soc_end_percent IS NOT NULL
                ORDER BY slot_start ASC
            """
            async with conn.execute(query, (target_date.isoformat(),)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return {
                "date": target_date.isoformat(),
                "slots": [],
                "message": "No historical SoC data available for this date",
            }

        # Convert to JSON format
        slots: list[dict[str, Any]] = []
        for row in rows:
            slots.append(
                {"timestamp": row[0], "soc_percent": row[1], "quality_flags": row[2] or ""}
            )

        return {"date": target_date.isoformat(), "slots": slots, "count": len(slots)}

    except Exception as e:
        logger.exception("Failed to fetch historical SoC data")
        raise HTTPException(500, f"Failed to fetch historical SoC data: {e!s}")


@router.get(
    "/api/performance/metrics",
    summary="Get Performance Metrics",
    description="Get performance metrics for charts.",
)
async def get_performance_metrics(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    """Get performance metrics for charts."""
    try:
        from typing import cast

        from backend.learning import get_learning_engine
        engine = get_learning_engine()
        data = cast("dict[str, Any]", engine.get_performance_series(days_back=days)) # type: ignore
        return data
    except Exception:
        logger.exception("Failed to get performance metrics")
        return {"soc_series": [], "cost_series": []}


from inputs import get_dummy_load_profile, get_load_profile_from_ha, load_yaml


@router.get(
    "/api/debug/load_profile",
    summary="Debug Load Profile",
    description="Debug endpoint to test HA load profile fetching.",
)
async def debug_load_profile() -> dict[str, Any]:
    """Debug endpoint to test HA load profile fetching."""
    try:
        conf = load_yaml("config.yaml") or {}
        try:
            profile = get_load_profile_from_ha(conf)
            return {
                "source": "ha",
                "profile_sum": sum(profile),
                "profile": profile,
                "message": "Successfully fetched from HA",
            }
        except Exception as e:
            dummy = get_dummy_load_profile(conf)
            return {
                "source": "dummy_fallback",
                "error": str(e),
                "profile_sum": sum(dummy),
                "profile": dummy,
                "message": "Failed to fetch from HA, used dummy",
            }
    except Exception as e:
        return {"error": f"Critical error: {e!s}"}
