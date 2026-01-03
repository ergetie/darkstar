"""
Learning Inputs

Functions for loading learning overlays and adjustments from the database.
"""

import json
import sqlite3
from typing import Any
import contextlib


def load_learning_overlays(learning_config: dict[str, Any]) -> dict[str, Any]:
    """
    Load latest learning adjustments (PV/load bias and S-index base factor).

    Data is read from learning_daily_metrics, which stores one row per date
    with 24h adjustment arrays and scalars. This method is intentionally
    tolerant: if anything fails or no data exists, it returns an empty dict.

    Args:
        learning_config: Learning configuration dictionary

    Returns:
        Dictionary with overlays (pv_adjustment_by_hour_kwh, load_adjustment_by_hour_kwh, s_index_base_factor)
    """
    if not learning_config.get("enable", False):
        return {}

    path = learning_config.get("sqlite_path", "data/learning.db")
    try:
        with sqlite3.connect(path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT date,
                       pv_adjustment_by_hour_kwh,
                       load_adjustment_by_hour_kwh,
                       s_index_base_factor
                FROM learning_daily_metrics
                ORDER BY date DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
    except sqlite3.Error:
        return {}

    if not row:
        return {}

    _, pv_adj_json, load_adj_json, s_index_base = row

    def _parse_series(raw):
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [float(v) for v in data]
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return None

    overlays: dict[str, Any] = {}
    pv_adj = _parse_series(pv_adj_json)
    load_adj = _parse_series(load_adj_json)
    if pv_adj:
        overlays["pv_adjustment_by_hour_kwh"] = pv_adj
    if load_adj:
        overlays["load_adjustment_by_hour_kwh"] = load_adj
    if s_index_base is not None:
        with contextlib.suppress(TypeError, ValueError):
            overlays["s_index_base_factor"] = float(s_index_base)

    return overlays
