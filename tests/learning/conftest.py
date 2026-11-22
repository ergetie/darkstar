import pytest_asyncio

from backend.learning.learned_parameters import LearnedParameterStore
from backend.learning.models import Base
from backend.learning.store import LearningStore
from tests.learning.battery_synth import TZ


@pytest_asyncio.fixture
async def learning_store(tmp_path):
    value = LearningStore(str(tmp_path / "learning.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield value
    await value.close()


@pytest_asyncio.fixture
async def parameter_store(learning_store):
    return LearnedParameterStore(learning_store)
