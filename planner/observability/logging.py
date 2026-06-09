import json
import logging
from datetime import UTC, datetime
from typing import Any

from backend.learning import get_learning_engine
from backend.learning.models import PlannerDebug

logger = logging.getLogger(__name__)


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
