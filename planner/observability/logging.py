import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete

from backend.learning import get_learning_engine
from backend.learning.models import PlannerDebug, SIndexHistory

logger = logging.getLogger(__name__)

S_INDEX_HISTORY_RETENTION_DAYS = 365


# ensure_learning_schema is no longer needed as Alembic handles schema.
# Kept as no-op if called from legacy code, or can be removed if confident.
def ensure_learning_schema(db_path: str) -> None:
    """Legacy no-op: Schema is managed by Alembic."""
    pass


async def record_debug_payload(payload: dict[str, Any], learning_config: dict[str, Any]) -> None:
    """
    Persist planner debug payloads for observability.

    Args:
        payload: The debug payload dictionary
        learning_config: Learning configuration dictionary
    """
    if not learning_config.get("enable", False):
        return

    try:
        engine = get_learning_engine()
        # Ensure store is available
        if not hasattr(engine, "store"):
            # If engine/store not initialized (e.g. running outside full app context),
            # we skip recording to avoid duplicate initialization logic or crashes.
            return

        timestamp = datetime.now(UTC).isoformat()

        async with engine.store.AsyncSession() as session:
            record = PlannerDebug(created_at=timestamp, payload=json.dumps(payload))
            session.add(record)
            await session.commit()

    except Exception as e:
        logger.warning("[observability] Failed to record debug payload: %s", e)


async def record_s_index_history(s_index_debug: dict[str, Any]) -> None:
    """
    Persist the S-Index debug record for one planner run, for calibration/diagnostics.

    Unlike record_debug_payload, this is NOT gated on learning_config["enable"] —
    the record must exist even on installs with learning disabled. It still
    degrades to a no-op if the learning engine/store is unavailable, since the
    table lives in the same DB as the learning store.
    """
    try:
        engine = get_learning_engine()
        if not hasattr(engine, "store"):
            return

        timestamp = datetime.now(UTC).isoformat()
        cutoff = (datetime.now(UTC) - timedelta(days=S_INDEX_HISTORY_RETENTION_DAYS)).isoformat()

        async with engine.store.AsyncSession() as session:
            record = SIndexHistory(created_at=timestamp, payload=json.dumps(s_index_debug))
            session.add(record)
            await session.execute(delete(SIndexHistory).where(SIndexHistory.created_at < cutoff))
            await session.commit()

    except Exception as e:
        logger.warning("[observability] Failed to record s_index history: %s", e)
