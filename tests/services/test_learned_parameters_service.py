"""LearnedParametersService: scheduling, error swallowing, start/stop idempotence."""

import asyncio
from datetime import datetime, timedelta

import pytest
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore
from backend.services import learned_parameters_service as module
from backend.services.learned_parameters_service import LearnedParametersService, next_run_time

TZ = pytz.timezone("Europe/Stockholm")
NOW = TZ.localize(datetime(2026, 3, 10, 12, 0))
CONFIG = {"timezone": "Europe/Stockholm", "system": {"battery": {"capacity_kwh": 30.0}}}


def _local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return TZ.localize(datetime(year, month, day, hour, minute))


def test_next_run_is_the_next_local_0040() -> None:
    assert next_run_time(_local(2026, 3, 10, 12), TZ) == _local(2026, 3, 11, 0, 40)
    assert next_run_time(_local(2026, 3, 10, 0, 10), TZ) == _local(2026, 3, 10, 0, 40)
    assert next_run_time(_local(2026, 3, 10, 0, 40), TZ) == _local(2026, 3, 11, 0, 40)


def test_spring_and_autumn_gaps_are_23_and_25_hours_apart() -> None:
    spring_a = next_run_time(_local(2026, 3, 28, 12), TZ)
    spring_b = next_run_time(spring_a, TZ)
    assert spring_b - spring_a == timedelta(hours=23)
    autumn_a = next_run_time(_local(2026, 10, 24, 12), TZ)
    autumn_b = next_run_time(autumn_a, TZ)
    assert autumn_b - autumn_a == timedelta(hours=25)


def test_next_run_accepts_utc_input() -> None:
    utc_now = _local(2026, 3, 10, 12).astimezone(pytz.UTC)
    assert next_run_time(utc_now, TZ) == _local(2026, 3, 11, 0, 40)


@pytest.fixture
async def store(tmp_path):
    value = LearningStore(str(tmp_path / "learning.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield value
    await value.close()


def _service(**kwargs) -> LearnedParametersService:
    return LearnedParametersService(
        config_loader=lambda: CONFIG, now=lambda: NOW, startup_delay=timedelta(0), **kwargs
    )


@pytest.mark.asyncio
async def test_run_once_with_no_data_changes_nothing(store) -> None:
    assert await _service().run_once(store) == []


@pytest.mark.asyncio
async def test_disabled_learning_does_not_estimate_but_still_expires(store) -> None:
    from backend.learning import learned_parameters as lp
    from backend.learning.battery_estimators import KEY_RTE

    parameters = lp.LearnedParameterStore(store)
    stale = NOW - timedelta(days=40)
    await parameters.save_state(
        lp.ParameterState(
            key=KEY_RTE, learned_value=0.96, applied_value=0.96, estimated_at=stale
        ),
        stale,
    )
    service = LearnedParametersService(
        config_loader=lambda: {**CONFIG, "learning": {"enable": False}}, now=lambda: NOW
    )

    changes = await service.run_once(store)

    assert [(c.key, c.event) for c in changes] == [(KEY_RTE, lp.EVENT_EXPIRED)]
    assert (await parameters.get_states())[KEY_RTE].estimated_at == stale


@pytest.mark.asyncio
async def test_loop_swallows_errors_and_keeps_running(store, monkeypatch) -> None:
    calls = 0
    release = asyncio.Event()

    async def failing(self, _store):
        nonlocal calls
        calls += 1
        release.set()
        raise RuntimeError("boom")

    monkeypatch.setattr(LearnedParametersService, "run_once", failing)
    service = _service()
    await service.start(store)
    await asyncio.wait_for(release.wait(), timeout=5)
    await asyncio.sleep(0.05)

    assert calls == 1
    assert service._task is not None and not service._task.done()  # waiting for tomorrow
    await service.stop()


@pytest.mark.asyncio
async def test_start_and_stop_are_idempotent(store) -> None:
    service = LearnedParametersService(
        config_loader=lambda: CONFIG, now=lambda: NOW, startup_delay=timedelta(hours=1)
    )
    await service.start(store)
    first = service._task
    await service.start(store)
    assert service._task is first

    await service.stop()
    await service.stop()
    assert service._task is None
    assert first is not None and first.cancelled()


@pytest.mark.asyncio
async def test_notifier_without_executor_reports_undelivered(monkeypatch) -> None:
    monkeypatch.setattr("backend.api.routers.executor.get_executor_instance", lambda: None)
    assert await module.executor_notifier("t", "m") is False


@pytest.mark.asyncio
async def test_notifier_uses_the_executor(monkeypatch) -> None:
    sent: list[tuple[str, str]] = []

    class Fake:
        async def send_notification(self, title: str, message: str) -> bool:
            sent.append((title, message))
            return True

    monkeypatch.setattr("backend.api.routers.executor.get_executor_instance", lambda: Fake())
    assert await module.executor_notifier("t", "m") is True
    assert sent == [("t", "m")]


@pytest.mark.asyncio
async def test_stored_sensor_losses_feed_the_fit_in_place_of_the_residual(store) -> None:
    from backend.learning.battery_estimators import KEY_CHARGE_LOSS, KEY_STANDBY_W
    from backend.learning.learned_parameters import LearnedParameterStore
    from backend.learning.models import InverterLossObservation, SlotObservation
    from tests.learning.battery_synth import after, make_rows

    rows = make_rows(40)
    sensor_rows = rows[: 96 * 20]
    for row in sensor_rows:
        row["import_kwh"] += 0.8  # residual is badly wrong for these slots
    async with store.AsyncSession() as session:
        for row in rows:
            session.add(SlotObservation(**row))
        for row in sensor_rows:
            loss = 0.06 * 0.25 + 0.075 * row["batt_charge_kwh"]
            session.add(InverterLossObservation(slot_start=row["slot_start"], loss_kwh=loss))
        await session.commit()
    service = LearnedParametersService(config_loader=lambda: CONFIG, now=lambda: after(40))

    await service.run_once(store)

    states = await LearnedParameterStore(store).get_states()
    assert states[KEY_CHARGE_LOSS].evidence["sensor_slots"] == 96 * 20
    assert states[KEY_CHARGE_LOSS].applied_value == pytest.approx(0.075 / 1.075, abs=0.01)
    assert states[KEY_STANDBY_W].applied_value == pytest.approx(60.0, abs=10.0)
