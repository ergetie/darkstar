import contextlib
import json
import logging
from typing import Any
from sqlalchemy import create_engine, select, desc
from sqlalchemy.orm import sessionmaker

from backend.learning.models import LearningDailyMetric

logger = logging.getLogger("darkstar.planner.inputs.learning")


def load_learning_overlays(learning_config: dict[str, Any]) -> dict[str, Any]:
    """
    Load latest learning adjustments using SQLAlchemy.

    Data is read from learning_daily_metrics. This method is intentionally
    tolerant: if anything fails or no data exists, it returns an empty dict.

    Args:
        learning_config: Learning configuration dictionary

    Returns:
        Dictionary with overlays
    """
    if not learning_config.get("enable", False):
        return {}

    path = learning_config.get("sqlite_path", "data/planner_learning.db")
    try:
        engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 30.0})
        Session = sessionmaker(bind=engine)
        with Session() as session:
            stmt = select(LearningDailyMetric).order_by(desc(LearningDailyMetric.date)).limit(1)
            metric = session.execute(stmt).scalar_one_or_none()
            
            if not metric:
                return {}

            def _parse_series(raw):
                if raw is None:
                    return None
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(data, list):
                        return [float(v) for v in data]
                except (TypeError, ValueError, json.JSONDecodeError):
                    return None
                return None

            overlays: dict[str, Any] = {}
            pv_adj = _parse_series(metric.pv_adjustment_by_hour_kwh)
            load_adj = _parse_series(metric.load_adjustment_by_hour_kwh)
            if pv_adj:
                overlays["pv_adjustment_by_hour_kwh"] = pv_adj
            if load_adj:
                overlays["load_adjustment_by_hour_kwh"] = load_adj
            if metric.s_index_base_factor is not None:
                with contextlib.suppress(TypeError, ValueError):
                    overlays["s_index_base_factor"] = float(metric.s_index_base_factor)

            return overlays
    except Exception as e:
        logger.debug("Failed to load learning overlays: %s", e)
        return {}
