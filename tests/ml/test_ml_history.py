from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.learning.models import Base, LearningRun
from backend.learning.store import LearningStore


@pytest_asyncio.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "test_learning.db")
    import pytz

    tz = pytz.timezone("Europe/Stockholm")
    store = LearningStore(db_path, tz)

    # Initialize schema for test
    async def init_db():
        async with store.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    await init_db()

    yield store

    # Cleanup background threads
    await store.close()


@pytest.mark.asyncio
async def test_log_learning_run_full(store):
    """Test logging a run with all new ARC11 columns."""
    start = datetime.now(UTC) - timedelta(minutes=5)

    await store.log_learning_run(
        status="success",
        training_type="automatic",
        models_trained=["model1.lgb", "model2.lgb"],
        duration_seconds=120,
        partial_failure=False,
        started_at=start,
    )

    async with store.AsyncSession() as session:
        stmt = select(LearningRun).limit(1)
        result = await session.execute(stmt)
        run = result.scalar_one()

        assert run.status == "success"
        assert run.training_type == "automatic"
        assert "model1.lgb" in run.models_trained
        assert run.training_duration_seconds == 120
        assert run.partial_failure is False
        assert run.completed_at is not None


@pytest.mark.asyncio
async def test_graduation_level_counts_runs_older_than_30_days(store):
    """Learning runs are no longer cut at 30 days, so old runs keep counting."""
    from types import SimpleNamespace

    from backend.api.routers.forecast import _compute_graduation_level

    old = datetime.now(UTC) - timedelta(days=40)
    for _ in range(14):
        await store.log_learning_run(status="success", started_at=old)

    level = await _compute_graduation_level(SimpleNamespace(store=store))  # type: ignore[arg-type]

    assert level == {"label": "statistician", "runs": 14}


@pytest.mark.asyncio
async def test_partial_failure_logging(store):
    """Test logging a partial failure."""
    await store.log_learning_run(
        status="success",
        partial_failure=True,
        error_message="Some models failed but overall success",
    )

    async with store.AsyncSession() as session:
        run = await session.scalar(select(LearningRun))
        assert run.partial_failure is True
        assert "Some models failed" in run.error_message
