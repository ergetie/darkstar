"""Recorder integration of the optional inverter-loss sensor, and its storage."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.learning.models import Base, InverterLossObservation
from backend.learning.store import LearningStore
from tests.backend.test_recorder_slot_energy import (
    SLOT_START,
    TZ,
    base_config,
    constant,
    record,
    series,
)


def _config() -> dict:
    return base_config(input_sensors={"inverter_power_losses": "sensor.loss"})


@pytest.mark.asyncio
async def test_slot_loss_is_integrated_and_passed_to_the_store() -> None:
    history = {"sensor.loss": constant("sensor.loss", 0.16)}

    record_, history_mock = await record(_config(), history)

    assert record_["inverter_loss_kwh"] == pytest.approx(0.04)
    assert "sensor.loss" in history_mock.await_args.args[0]


@pytest.mark.asyncio
async def test_unavailable_sensor_stores_no_value_not_zero() -> None:
    history = {"sensor.loss": series("sensor.loss", [(0, "unavailable")])}

    record_, _ = await record(_config(), history)

    assert pd.isna(record_["inverter_loss_kwh"])


@pytest.mark.asyncio
async def test_watt_sensor_is_converted() -> None:
    history = {"sensor.loss": series("sensor.loss", [(0, 160.0)], unit="W")}

    record_, _ = await record(_config(), history)

    assert record_["inverter_loss_kwh"] == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_unconfigured_sensor_leaves_the_record_without_the_field() -> None:
    record_, history_mock = await record(base_config(), {})

    assert "inverter_loss_kwh" not in record_
    assert "sensor.loss" not in history_mock.await_args.args[0]


@pytest_asyncio.fixture
async def store(tmp_path):
    value = LearningStore(str(tmp_path / "learning.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield value
    await value.close()


def _observation(loss: float | None) -> pd.DataFrame:
    start = SLOT_START
    return pd.DataFrame(
        [
            {
                "slot_start": start,
                "slot_end": start + timedelta(minutes=15),
                "import_kwh": 0.1,
                "export_kwh": 0.0,
                "pv_kwh": 0.0,
                "load_kwh": 0.1,
                "water_kwh": 0.0,
                "ev_charging_kwh": 0.0,
                "inverter_loss_kwh": loss,
            }
        ]
    )


async def _rows(store: LearningStore) -> list[tuple[str, float]]:
    async with store.AsyncSession() as session:
        result = await session.execute(
            select(InverterLossObservation.slot_start, InverterLossObservation.loss_kwh)
        )
        return [(row.slot_start, row.loss_kwh) for row in result.all()]


@pytest.mark.asyncio
async def test_row_is_stored_and_a_rewrite_replaces_it(store) -> None:
    await store.store_slot_observations(_observation(0.04))
    assert [loss for _, loss in await _rows(store)] == [0.04]

    await store.store_slot_observations(_observation(0.05))
    assert [loss for _, loss in await _rows(store)] == [0.05]


@pytest.mark.asyncio
async def test_rewrite_without_a_value_removes_the_stale_row(store) -> None:
    await store.store_slot_observations(_observation(0.04))

    await store.store_slot_observations(_observation(None))

    assert await _rows(store) == []


@pytest.mark.asyncio
async def test_no_row_for_a_record_without_the_field(store) -> None:
    frame = _observation(0.04).drop(columns=["inverter_loss_kwh"])

    await store.store_slot_observations(frame)

    assert await _rows(store) == []


@pytest.mark.asyncio
async def test_backfill_writes_do_not_touch_loss_rows(store) -> None:
    await store.store_slot_observations(_observation(0.04))

    await store.store_slot_observations(_observation(None), authoritative=False)

    assert [loss for _, loss in await _rows(store)] == [0.04]


@pytest.mark.asyncio
async def test_loss_values_are_read_back_by_range(store) -> None:
    await store.store_slot_observations(_observation(0.04))
    start = TZ.localize(datetime(2026, 10, 1))

    values = await store.get_inverter_loss_values(start, start + timedelta(days=1))

    assert list(values.values()) == [0.04]
    assert await store.get_inverter_loss_values(start - timedelta(days=2), start) == {}
