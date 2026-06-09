import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.recorder_service import RecorderService


@pytest.mark.asyncio
async def test_recorder_service_start_stop_manage_background_task():
    service = RecorderService()

    with patch.object(service, "_loop", new_callable=AsyncMock) as loop:
        await service.start()
        assert service.status.running is True
        assert service._task is not None
        await asyncio.sleep(0)

        await service.stop()

    assert service.status.running is False
    assert service._task is None
    loop.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_with_retry_succeeds_on_second_attempt():
    service = RecorderService()
    service._config = {"ok": True}
    service._disaggregator = MagicMock()

    with (
        patch("backend.services.recorder_service.asyncio.sleep", new_callable=AsyncMock) as sleep,
        patch(
            "backend.services.recorder_service.record_observation_from_current_state",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("first"), None],
        ) as record,
    ):
        result = await service._record_with_retry()

    assert result is True
    assert record.await_count == 2
    assert service.status.last_record_at is not None
    sleep.assert_any_await(5)
    sleep.assert_any_await(3)


@pytest.mark.asyncio
async def test_loop_runs_startup_backfills_then_sleeps_and_records():
    service = RecorderService()
    service._running = True

    calls: list[str] = []

    async def record_once() -> bool:
        calls.append("record")
        service._running = False
        return True

    async def sleep_once() -> None:
        calls.append("sleep")

    with (
        patch.object(service, "_load_config", return_value={"loaded": True}),
        patch("backend.services.recorder_service.BackfillEngine") as backfill_cls,
        patch("backend.services.recorder_service.backfill_missing_prices", new_callable=AsyncMock) as price_backfill,
        patch("backend.services.recorder_service.LoadDisaggregator") as disaggregator_cls,
        patch.object(service, "_record_with_retry", new_callable=AsyncMock, side_effect=record_once) as record,
        patch.object(service, "_sleep_until_next_quarter", new_callable=AsyncMock, side_effect=sleep_once) as sleep_to_boundary,
    ):
        backfill_cls.return_value.run = AsyncMock()
        await service._loop()

    backfill_cls.return_value.run.assert_awaited_once()
    price_backfill.assert_awaited_once()
    disaggregator_cls.assert_called_once_with({"loaded": True})
    record.assert_awaited_once()
    sleep_to_boundary.assert_awaited_once()
    assert calls == ["sleep", "record"]
