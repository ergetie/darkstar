"""s_index.base_factor comes from config only; stored learned metrics never override it."""

import sqlite3
from pathlib import Path

import pytest

import planner.pipeline as pipeline_module
from backend.learning.models import Base
from backend.learning.store import LearningStore
from tests.planner.test_price_reserve_pipeline import (
    TZ,
    future_base,
    reserve_config,
    run_full,
)

STALE_FACTOR = 1.4066
CONFIGURED_FACTOR = 1.1


async def _create_db_with_stale_metrics(path: Path) -> None:
    store = LearningStore(str(path), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await store.close()
    # The table no longer exists in the schema (dropped by migration); recreate it by hand.
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE learning_daily_metrics (date TEXT PRIMARY KEY, s_index_base_factor REAL)"
        )
        conn.execute(
            "INSERT INTO learning_daily_metrics (date, s_index_base_factor) VALUES (?, ?)",
            ("2026-03-15", STALE_FACTOR),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("learning_enabled", [True, False])
async def test_stale_daily_metrics_do_not_override_base_factor(
    tmp_path, monkeypatch, learning_enabled
):
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "learning.db"
    await _create_db_with_stale_metrics(db)

    config = reserve_config(db, enabled=False)
    config["learning"] = {"enable": learning_enabled, "sqlite_path": str(db)}
    config["s_index"] = {"risk_appetite": 3, "base_factor": CONFIGURED_FACTOR}

    seen_cfgs: list[dict] = []
    original = pipeline_module.calculate_dynamic_s_index

    async def spy(df, s_index_cfg, *args, **kwargs):
        seen_cfgs.append(dict(s_index_cfg))
        return await original(df, s_index_cfg, *args, **kwargs)

    monkeypatch.setattr(pipeline_module, "calculate_dynamic_s_index", spy)

    await run_full(config, future_base())

    assert seen_cfgs, "S-Index step did not run"
    assert seen_cfgs[-1]["base_factor"] == pytest.approx(CONFIGURED_FACTOR)
