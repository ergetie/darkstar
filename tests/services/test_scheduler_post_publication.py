"""Tests for the post-publication price forecast run in the scheduler."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.learning.models import Base, PriceForecast
from backend.services.scheduler_service import SchedulerService

TZ = pytz.timezone("Europe/Stockholm")


def _local(day_offset: int, hour: int = 0, minute: int = 0) -> datetime:
    return TZ.localize(datetime(2026, 4, 10 + day_offset, hour, minute))


def _now(hour: int, minute: int = 0) -> datetime:
    return _local(0, hour, minute).astimezone(UTC)


def _full_day(day_offset: int) -> dict[datetime, float]:
    slot = _local(day_offset).astimezone(UTC)
    end = _local(day_offset + 1).astimezone(UTC)
    prices: dict[datetime, float] = {}
    while slot < end:
        prices[slot] = 0.5
        slot += timedelta(minutes=15)
    return prices


@pytest.fixture
def harness(tmp_path):
    db_path = str(tmp_path / "learning.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    learning_engine = SimpleNamespace(
        db_path=db_path,
        config={"timezone": "Europe/Stockholm"},
        reload_config_if_changed=MagicMock(),
    )
    scheduler = SchedulerService()
    known_spot = AsyncMock(return_value={**_full_day(0), **_full_day(1)})
    generate = AsyncMock(return_value=[{"days_ahead": 2}])

    with (
        patch.object(
            scheduler, "_load_global_config", return_value={"timezone": "Europe/Stockholm"}
        ),
        patch("backend.learning.get_learning_engine", return_value=learning_engine),
        patch("backend.core.prices.get_known_spot_by_slot", new=known_spot),
        patch("ml.price_forecast.generate_price_forecasts", new=generate),
    ):
        yield SimpleNamespace(
            scheduler=scheduler, engine=engine, known_spot=known_spot, generate=generate
        )
    engine.dispose()


def _store_run(engine, issued: datetime, known_until: datetime | None) -> None:
    session = sessionmaker(bind=engine)()
    session.add(
        PriceForecast(
            slot_start=_local(2, 12).isoformat(),
            issue_timestamp=issued.isoformat(),
            days_ahead=2,
            known_prices_until=known_until.isoformat() if known_until else None,
        )
    )
    session.commit()
    session.close()


@pytest.mark.asyncio
async def test_runs_once_after_publication(harness):
    scheduler = harness.scheduler

    await scheduler._check_post_publication_forecast(now=_now(13, 20))

    harness.generate.assert_awaited_once()
    assert harness.generate.await_args.kwargs["days_ahead_range"] == range(2, 8)
    assert scheduler.status.last_post_publication_forecast_at is not None
    assert scheduler.status.current_task == "idle"


@pytest.mark.asyncio
async def test_not_before_noon(harness):
    await harness.scheduler._check_post_publication_forecast(now=_now(11, 50))

    harness.generate.assert_not_awaited()
    harness.known_spot.assert_not_awaited()


@pytest.mark.asyncio
async def test_throttled_to_ten_minutes(harness):
    harness.known_spot.return_value = _full_day(0)  # tomorrow unpublished
    scheduler = harness.scheduler

    await scheduler._check_post_publication_forecast(now=_now(13, 0))
    await scheduler._check_post_publication_forecast(now=_now(13, 5))
    assert harness.known_spot.await_count == 1

    harness.known_spot.return_value = {**_full_day(0), **_full_day(1)}
    await scheduler._check_post_publication_forecast(now=_now(13, 10))
    assert harness.known_spot.await_count == 2
    harness.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_skipped_when_tomorrow_incomplete(harness):
    partial = _full_day(1)
    partial.pop(_local(1, 23, 45).astimezone(UTC))
    harness.known_spot.return_value = {**_full_day(0), **partial}

    await harness.scheduler._check_post_publication_forecast(now=_now(16))

    harness.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_rerun_after_restart(harness):
    _store_run(harness.engine, issued=_local(0, 13, 25), known_until=_local(2))

    # A fresh scheduler instance (restart) must not run again
    await harness.scheduler._check_post_publication_forecast(now=_now(15))

    harness.generate.assert_not_awaited()
    harness.known_spot.assert_not_awaited()


@pytest.mark.asyncio
async def test_morning_run_does_not_count_as_post_publication(harness):
    # 06:00 run knew only today's prices; yesterday's full run does not count either
    _store_run(harness.engine, issued=_local(0, 6), known_until=_local(1))
    _store_run(harness.engine, issued=_local(-1, 13, 30), known_until=_local(1))

    await harness.scheduler._check_post_publication_forecast(now=_now(13, 20))

    harness.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_failure_is_logged_not_raised_and_retried(harness, caplog):
    harness.generate.side_effect = RuntimeError("weather down")
    scheduler = harness.scheduler

    with caplog.at_level("ERROR", logger="darkstar.services.scheduler"):
        await scheduler._check_post_publication_forecast(now=_now(13, 20))

    assert "Post-publication price forecast failed" in caplog.text
    assert scheduler.status.last_post_publication_forecast_at is None
    assert scheduler.status.current_task == "idle"

    harness.generate.side_effect = None
    await scheduler._check_post_publication_forecast(now=_now(13, 31))
    assert scheduler.status.last_post_publication_forecast_at is not None
