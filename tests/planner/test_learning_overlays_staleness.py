"""A stale learning_daily_metrics row must not override s_index.base_factor."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from planner.inputs.learning import load_learning_overlays


def _metric(days_old: int, factor: float = 0.8232) -> dict:
    day = (datetime.now(UTC).date() - timedelta(days=days_old)).isoformat()
    return {"date": day, "s_index_base_factor": factor}


@pytest.fixture
def store_with():
    def _make(metric):
        store = AsyncMock()
        store.get_latest_metrics = AsyncMock(return_value=metric)
        return patch("planner.inputs.learning.LearningStore", return_value=store)

    return _make


async def test_fresh_overlay_is_applied(store_with):
    with store_with(_metric(0, 1.15)):
        overlays = await load_learning_overlays({"enable": True})
    assert overlays == {"s_index_base_factor": 1.15}


async def test_stale_overlay_is_ignored(store_with):
    with store_with(_metric(249)):  # e.g. the 2026-03-15 row seen in November
        overlays = await load_learning_overlays({"enable": True})
    assert overlays == {}


async def test_unparseable_date_is_ignored(store_with):
    with store_with({"date": "not-a-date", "s_index_base_factor": 0.8}):
        overlays = await load_learning_overlays({"enable": True})
    assert overlays == {}


async def test_learning_disabled_returns_empty(store_with):
    with store_with(_metric(0)):
        overlays = await load_learning_overlays({"enable": False})
    assert overlays == {}
