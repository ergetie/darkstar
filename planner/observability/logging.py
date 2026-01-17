import json
from datetime import UTC, datetime
from typing import Any

from backend.learning import get_learning_engine
from backend.learning.models import PlannerDebug

# ensure_learning_schema is no longer needed as Alembic handles schema.
# Kept as no-op if called from legacy code, or can be removed if confident.
def ensure_learning_schema(db_path: str) -> None:
    """Legacy no-op: Schema is managed by Alembic."""
    pass


def record_debug_payload(payload: dict[str, Any], learning_config: dict[str, Any]) -> None:
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
        
        with engine.store.Session() as session:
            record = PlannerDebug(
                created_at=timestamp,
                payload=json.dumps(payload)
            )
            session.add(record)
            session.commit()

    except Exception as e:
        # Use simple print as fallback if logger not available/configured
        print(f"[observability] Failed to record debug payload: {e}")
