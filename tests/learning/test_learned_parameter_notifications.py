"""One combined notification per run, toggle, retry window and lock events."""

from datetime import datetime, timedelta

import pytest

from backend.learning import learned_parameters as lp
from backend.learning.battery_estimators import KEY_CHARGE_LOSS, KEY_RTE
from tests.learning.battery_synth import TZ

NOW = TZ.localize(datetime(2026, 3, 10, 1, 0))


def _event(key: str, old: float | None, new: float | None, at=NOW, event=lp.EVENT_LEARNED):
    return lp.HistoryEvent(
        key, at, event, old, new, 0.9, {"days": 30}, notify_state=lp.NOTIFY_PENDING
    )


class Recorder:
    def __init__(self, result: bool = True, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.result, self.error = result, error

    async def __call__(self, title: str, message: str) -> bool:
        self.calls.append((title, message))
        if self.error:
            raise self.error
        return self.result


async def _notify(parameter_store, notifier, enabled=True, now=NOW):
    rows = await parameter_store.pending_history(now - timedelta(days=lp.NOTIFY_RETRY_DAYS))
    return await lp.notify_changes(parameter_store, rows, notifier, enabled, now)


async def _states(parameter_store) -> list[str]:
    return [h.notify_state for h in await parameter_store.list_history(limit=20)]


@pytest.mark.asyncio
async def test_two_changes_give_one_combined_message(parameter_store) -> None:
    await parameter_store.add_history(
        [_event(KEY_RTE, 0.960, 0.962), _event(KEY_CHARGE_LOSS, 0.07, 0.075)]
    )
    notifier = Recorder()

    assert await _notify(parameter_store, notifier) == lp.NOTIFY_SENT

    assert len(notifier.calls) == 1
    message = notifier.calls[0][1]
    assert "Battery round-trip efficiency: 0.960 -> 0.962 (30 days of data)" in message
    assert "Inverter charge loss: 0.070 -> 0.075" in message
    assert set(await _states(parameter_store)) == {lp.NOTIFY_SENT}


@pytest.mark.asyncio
async def test_toggle_off_marks_disabled_and_sends_nothing(parameter_store) -> None:
    await parameter_store.add_history([_event(KEY_RTE, 0.96, 0.97)])
    notifier = Recorder()

    assert await _notify(parameter_store, notifier, enabled=False) == lp.NOTIFY_DISABLED

    assert notifier.calls == []
    assert await _states(parameter_store) == [lp.NOTIFY_DISABLED]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "notifier", [Recorder(result=False), Recorder(error=RuntimeError("down")), None]
)
async def test_undeliverable_message_stays_pending_and_is_retried(
    parameter_store, notifier
) -> None:
    await parameter_store.add_history([_event(KEY_RTE, 0.96, 0.97)])

    assert await _notify(parameter_store, notifier) == lp.NOTIFY_PENDING
    assert await _states(parameter_store) == [lp.NOTIFY_PENDING]

    retry = Recorder()
    assert await _notify(parameter_store, retry, now=NOW + timedelta(days=1)) == lp.NOTIFY_SENT
    assert len(retry.calls) == 1


@pytest.mark.asyncio
async def test_four_day_old_pending_row_is_not_retried(parameter_store) -> None:
    await parameter_store.add_history([_event(KEY_RTE, 0.96, 0.97, at=NOW - timedelta(days=4))])
    notifier = Recorder()

    assert await _notify(parameter_store, notifier) == lp.NOTIFY_NONE

    assert notifier.calls == []
    assert await _states(parameter_store) == [lp.NOTIFY_PENDING]


@pytest.mark.asyncio
async def test_lock_events_send_nothing(parameter_store) -> None:
    await parameter_store.set_lock(KEY_RTE, 0.95, NOW)
    await parameter_store.clear_lock(KEY_RTE, NOW + timedelta(minutes=1))
    notifier = Recorder()

    assert await _notify(parameter_store, notifier) == lp.NOTIFY_NONE
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_expiry_and_recovery_messages(parameter_store) -> None:
    await parameter_store.add_history(
        [
            _event(KEY_RTE, 0.962, None, event=lp.EVENT_EXPIRED),
            _event(KEY_CHARGE_LOSS, 0.07, 0.072, event=lp.EVENT_RECOVERED),
        ]
    )
    notifier = Recorder()
    await _notify(parameter_store, notifier)

    message = notifier.calls[0][1]
    assert "Battery round-trip efficiency: expired, the configured value is used" in message
    assert "(recovered)" in message


def test_enabled_flag_reads_the_config_with_default_true() -> None:
    assert lp.notifications_enabled({}) is True
    assert lp.notifications_enabled({"executor": {"notifications": {}}}) is True
    off = {"executor": {"notifications": {"on_learned_parameter_change": False}}}
    assert lp.notifications_enabled(off) is False


@pytest.mark.asyncio
async def test_run_once_honours_the_toggle(parameter_store) -> None:
    from tests.learning.battery_synth import CAPACITY_KWH, after, make_rows

    config = {
        "system": {"battery": {"capacity_kwh": CAPACITY_KWH}},
        "executor": {"notifications": {"on_learned_parameter_change": False}},
    }
    notifier = Recorder()

    await lp.run_once(parameter_store, make_rows(40), config, after(40), notifier)

    assert notifier.calls == []
    assert set(await _states(parameter_store)) == {lp.NOTIFY_DISABLED}
