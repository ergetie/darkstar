"""The planner uses learned battery efficiencies when valid and the config otherwise."""

# ruff: noqa: F811
# (captured_solves is a fixture imported from the sibling test module)

import json
import math
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from backend.learning import learned_parameters as lp
from backend.learning.battery_estimators import KEY_CHARGE_LOSS, KEY_RTE
from backend.learning.models import Base
from backend.learning.store import LearningStore
from backend.services import plan_archive
from tests.planner.test_price_reserve_pipeline import (
    TZ,
    captured_solves,
    future_base,
    make_forecast_db,
    reserve_config,
    run_full,
)

RTE, LOSS = 0.962, 0.075
CHARGE_EFF = (1 - LOSS) * math.sqrt(RTE)
DISCHARGE_EFF = math.sqrt(RTE) * lp.DEFAULT_DISCHARGE_EFFICIENCY


async def _store_learned(db: Path, estimated_at) -> None:
    store = LearningStore(str(db), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    parameters = lp.LearnedParameterStore(store)
    for key, value in ((KEY_RTE, RTE), (KEY_CHARGE_LOSS, LOSS)):
        await parameters.save_state(
            lp.ParameterState(
                key=key,
                learned_value=value,
                applied_value=value,
                confidence=0.9,
                estimated_at=estimated_at,
                applied_at=estimated_at,
            ),
            estimated_at,
        )
    await store.close()


async def _run_captured(config: dict, start) -> dict:
    run = plan_archive.start_capture()
    try:
        await run_full(config, start)
    finally:
        plan_archive.end_capture()
    return run.data["battery_parameters"]


@pytest.mark.asyncio
async def test_learned_pair_reaches_kepler_price_reserve_and_archive(
    tmp_path,
    monkeypatch,
    captured_solves,
):
    monkeypatch.chdir(tmp_path)
    start = future_base()
    db = tmp_path / "learning.db"
    make_forecast_db(db, start)
    await _store_learned(db, start - timedelta(days=1))

    record = await _run_captured(reserve_config(db), start)

    kepler = captured_solves[0]
    assert kepler.charge_efficiency == pytest.approx(CHARGE_EFF)
    assert kepler.discharge_efficiency == pytest.approx(DISCHARGE_EFF)
    # The price reserve divides the unseen-day net load by the discharge efficiency.
    min_soc = 0.15 * 27.0
    assert kepler.target_soc_kwh == pytest.approx(min_soc + 6.0 / DISCHARGE_EFF, abs=0.05)
    assert record["basis"] == "learned"
    assert record["charge_efficiency"] == pytest.approx(CHARGE_EFF)
    assert record["sources"][KEY_RTE] == "learned"


@pytest.mark.asyncio
async def test_without_learned_rows_the_config_values_are_used(
    tmp_path,
    monkeypatch,
    captured_solves,
):
    monkeypatch.chdir(tmp_path)
    start = future_base()
    db = tmp_path / "learning.db"
    make_forecast_db(db, start)
    config = reserve_config(db)

    record = await _run_captured(config, start)

    kepler = captured_solves[0]
    assert kepler.charge_efficiency == config["battery"].get("charge_efficiency", 0.95)
    assert kepler.discharge_efficiency == config["battery"].get("discharge_efficiency", 0.95)
    assert record["basis"] == "config"
    assert record["sources"][KEY_RTE] == "config"
    assert json.dumps(record)  # serialisable


@pytest.mark.asyncio
async def test_expired_rows_fall_back_to_config(tmp_path, monkeypatch, captured_solves):
    monkeypatch.chdir(tmp_path)
    start = future_base()
    db = tmp_path / "learning.db"
    make_forecast_db(db, start)
    await _store_learned(db, start - timedelta(days=45))
    config = reserve_config(db)

    await run_full(config, start)

    assert captured_solves[0].charge_efficiency == config["battery"].get("charge_efficiency", 0.95)


@pytest.mark.asyncio
async def test_unreadable_database_keeps_config_and_does_not_fail(
    tmp_path,
    monkeypatch,
    captured_solves,
    caplog,
):
    monkeypatch.chdir(tmp_path)
    start = future_base()
    db = tmp_path / "learning.db"
    make_forecast_db(db, start)
    config = reserve_config(db)

    def broken(_path):
        raise sqlite3.DatabaseError("disk image is malformed")

    monkeypatch.setattr(lp, "read_states_sync", broken)

    await run_full(config, start)

    assert captured_solves[0].charge_efficiency == config["battery"].get("charge_efficiency", 0.95)
    assert "using config values" in caplog.text
