import pytest
import pytest_asyncio
import pytz
from sqlalchemy.ext.asyncio import create_async_engine

from backend.learning.models import Base
from backend.learning.store import LearningStore


@pytest_asyncio.fixture
async def db_store(tmp_path):
    """Create a LearningStore with initialized DB schema."""
    db_path = str(tmp_path / "system_state.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    store = LearningStore(db_path, pytz.UTC)
    yield store

    await store.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_system_state_persistence(db_store):
    store = db_store

    # Test 1: Get non-existent key
    val = await store.get_system_state("non_existent")
    assert val is None

    # Test 2: Set key and get it back
    await store.set_system_state("test_key", "test_value")
    val = await store.get_system_state("test_key")
    assert val == "test_value"

    # Test 3: Update key
    await store.set_system_state("test_key", "updated_value")
    val = await store.get_system_state("test_key")
    assert val == "updated_value"
