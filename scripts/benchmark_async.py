import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytz

# Add project root to path
sys.path.append(str(Path.cwd()))

from backend.learning.store import LearningStore
from backend.models import Base

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "data/bench_async.db"
TZ = pytz.timezone("Europe/Stockholm")


def generate_dummy_data(days: int = 30) -> pd.DataFrame:
    """Generate fake PV/Load/Price data for DB benchmarks."""
    start = datetime.now() - timedelta(days=days)
    slots = days * 96
    data = {
        "slot_start": [(start + timedelta(minutes=15 * i)).isoformat() for i in range(slots)],
        "pv_kwh": [0.5] * slots,
        "load_kwh": [1.0] * slots,
        "import_price": [1.5] * slots,
        "export_price": [1.2] * slots,
    }
    return pd.DataFrame(data)


async def benchmark_db_writes(store: LearningStore, df: pd.DataFrame):
    """Benchmark batch writing of 15-min slots."""
    logger.info(f"Benchmarking writes for {len(df)} slots...")
    start = time.perf_counter()

    # In ARC11, we use store methods or direct session
    # Simulating the heaviest write: store_slot_prices and store_forecast_slots
    # But for benchmark, let's just do a bulk insert via engine if available
    # or use the store's async session.

    from backend.models import SlotForecast

    async with store.AsyncSession() as session:
        for _index, row in df.iterrows():
            f = SlotForecast(
                slot_start=row["slot_start"],
                forecast_version="aurora",
                pv_forecast_kwh=row["pv_kwh"],
                load_forecast_kwh=row["load_kwh"],
            )
            session.add(f)
        await session.commit()

    end = time.perf_counter()
    duration = end - start
    logger.info(f"DB Write Finish: {duration:.2f}s ({len(df) / duration:.1f} slots/sec)")


async def benchmark_db_reads(store: LearningStore):
    """Benchmark typical API read patterns."""
    logger.info("Benchmarking readout speed...")
    start = time.perf_counter()

    # 1. Raw query simulation for history
    async with store.async_engine.connect() as conn:
        from sqlalchemy import text

        q = text("SELECT * FROM learning_slots_forecast LIMIT 1000")
        result = await conn.execute(q)
        result.fetchall()

    end = time.perf_counter()
    duration = end - start
    logger.info(f"DB Read Finish: {duration:.2f}s")


async def main():
    db_file = Path(DB_PATH)
    if db_file.exists():
        db_file.unlink()

    store = LearningStore(DB_PATH, TZ)

    try:
        # Initialize Schema
        async with store.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Data Gen
        logger.info("Generating 1 year of dummy data...")
        df = generate_dummy_data(days=60)  # 2 months for quick bench

        # Benchmarks
        await benchmark_db_writes(store, df)
        await benchmark_db_reads(store)

    finally:
        await store.close()
        if db_file.exists():
            db_file.unlink()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
