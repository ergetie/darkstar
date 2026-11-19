import contextlib
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytz

from backend.learning.store import LearningStore

logger = logging.getLogger("darkstar.planner.inputs.learning")

# learning_daily_metrics is no longer written (its writer went with the corrector in
# fad904e3), so an old row would otherwise override s_index.base_factor forever and
# mask the value Reflex tunes in config.yaml. Only a recent row may act as an overlay.
MAX_OVERLAY_AGE = timedelta(days=2)

_stale_overlay_logged_for: str | None = None


def _is_fresh(metric_date: Any, today: date) -> bool:
    """True when the metric row's date is within MAX_OVERLAY_AGE of today."""
    try:
        parsed = date.fromisoformat(str(metric_date)[:10])
    except ValueError:
        return False
    return today - parsed <= MAX_OVERLAY_AGE


async def load_learning_overlays(learning_config: dict[str, Any]) -> dict[str, Any]:
    """
    Load latest learning adjustments asynchronously.

    Data is read from learning_daily_metrics via LearningStore.
    This method is intentionally tolerant: if anything fails or no data exists,
    it returns an empty dict.

    Note: Hourly adjustment overlays (pv_adjustment_by_hour_kwh, load_adjustment_by_hour_kwh)
    have been removed as part of removing the Analyst/Auto-Tuner. The base model now
    handles adaptation through recency-weighted training.

    Args:
        learning_config: Learning configuration dictionary

    Returns:
        Dictionary with overlays (s_index_base_factor only)
    """
    if not learning_config.get("enable", False):
        return {}

    path = learning_config.get("sqlite_path", "data/planner_learning.db")
    try:
        # We don't have timezone here easily, but we don't need it for just fetching metrics
        store = LearningStore(path, timezone=pytz.UTC)
        metric = await store.get_latest_metrics()

        if not metric:
            return {}

        if not _is_fresh(metric.get("date"), datetime.now(UTC).date()):
            global _stale_overlay_logged_for
            if _stale_overlay_logged_for != str(metric.get("date")):
                logger.info(
                    "Ignoring stale learning overlay from %s (older than %s); "
                    "using s_index.base_factor from config",
                    metric.get("date"),
                    MAX_OVERLAY_AGE,
                )
                _stale_overlay_logged_for = str(metric.get("date"))
            return {}

        overlays: dict[str, Any] = {}

        s_index_base_factor = metric.get("s_index_base_factor")
        if s_index_base_factor is not None:
            with contextlib.suppress(TypeError, ValueError):
                overlays["s_index_base_factor"] = float(s_index_base_factor)

        return overlays
    except Exception as e:
        logger.debug("Failed to load learning overlays: %s", e)
        return {}
