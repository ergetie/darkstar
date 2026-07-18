import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import pytz
from sqlalchemy import select

from backend.learning.models import Base, SIndexHistory
from backend.learning.store import LearningStore
from planner.observability.logging import record_s_index_history

TZ = pytz.timezone("Europe/Stockholm")


class FakeEngine:
    def __init__(self, store):
        self.store = store


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_s_index_history.db")


@pytest_asyncio.fixture
async def store(db_path):
    store = LearningStore(db_path, TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield store

    await store.close()


@pytest.mark.asyncio
async def test_record_s_index_history_inserts_one_row(store, monkeypatch):
    monkeypatch.setattr(
        "planner.observability.logging.get_learning_engine", lambda: FakeEngine(store)
    )

    payload = {"factor": 0.42, "mode": "physical_deficit", "avg_deficit": 1.5}
    await record_s_index_history(payload)

    async with store.AsyncSession() as session:
        rows = (await session.execute(select(SIndexHistory))).scalars().all()

    assert len(rows) == 1
    assert json.loads(rows[0].payload) == payload
    # Must parse as a UTC-aware ISO-8601 timestamp
    parsed = datetime.fromisoformat(rows[0].created_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_record_s_index_history_prunes_old_rows(store, monkeypatch):
    monkeypatch.setattr(
        "planner.observability.logging.get_learning_engine", lambda: FakeEngine(store)
    )

    now = datetime.now(UTC)
    old_ts = (now - timedelta(days=400)).isoformat()
    recent_ts = (now - timedelta(days=10)).isoformat()

    async with store.AsyncSession() as session:
        session.add(SIndexHistory(created_at=old_ts, payload=json.dumps({"stale": True})))
        session.add(SIndexHistory(created_at=recent_ts, payload=json.dumps({"stale": False})))
        await session.commit()

    await record_s_index_history({"factor": 0.1})

    async with store.AsyncSession() as session:
        rows = (await session.execute(select(SIndexHistory))).scalars().all()

    created_ats = {r.created_at for r in rows}
    assert old_ts not in created_ats
    assert recent_ts in created_ats
    # recent row + the just-inserted row
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_record_s_index_history_swallows_exceptions(monkeypatch, caplog):
    class ExplodingEngine:
        store = "not-a-real-store-with-AsyncSession"

    monkeypatch.setattr(
        "planner.observability.logging.get_learning_engine", lambda: ExplodingEngine()
    )

    with caplog.at_level("WARNING"):
        await record_s_index_history({"factor": 0.1})

    assert any("Failed to record s_index history" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_record_s_index_history_skips_without_store(monkeypatch):
    class NoStoreEngine:
        pass

    monkeypatch.setattr(
        "planner.observability.logging.get_learning_engine", lambda: NoStoreEngine()
    )

    # Should not raise even though the engine has no `store` attribute.
    await record_s_index_history({"factor": 0.1})


@pytest.mark.asyncio
async def test_record_s_index_history_writes_when_learning_disabled(store, monkeypatch):
    """record_s_index_history takes no learning_config argument and must write
    even when the caller's learning config has enable: false — unlike
    record_debug_payload, it is not gated on that flag."""
    monkeypatch.setattr(
        "planner.observability.logging.get_learning_engine", lambda: FakeEngine(store)
    )

    await record_s_index_history({"factor": 0.99})

    async with store.AsyncSession() as session:
        rows = (await session.execute(select(SIndexHistory))).scalars().all()

    assert len(rows) == 1
