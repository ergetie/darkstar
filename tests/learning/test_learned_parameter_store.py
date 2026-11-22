"""LearnedParameterStore round-trips on a temporary database."""

from datetime import datetime, timedelta

import pytest

from backend.learning import learned_parameters as lp
from backend.learning.battery_estimators import KEY_CHARGE_LOSS, KEY_RTE
from tests.learning.battery_synth import TZ

NOW = TZ.localize(datetime(2026, 3, 1, 1, 0))


@pytest.mark.asyncio
async def test_state_round_trip(parameter_store) -> None:
    state = lp.ParameterState(
        key=KEY_RTE,
        learned_value=0.962,
        confidence=0.9,
        evidence={"days": 28, "nested": {"a": 1}},
        estimated_at=NOW,
        applied_value=0.96,
        applied_at=NOW,
        status_note="note",
    )
    await parameter_store.save_state(state, NOW)

    loaded = (await parameter_store.get_states())[KEY_RTE]
    assert loaded == state


@pytest.mark.asyncio
async def test_save_state_updates_the_existing_row(parameter_store) -> None:
    await parameter_store.save_state(lp.ParameterState(key=KEY_RTE, learned_value=0.9), NOW)
    await parameter_store.save_state(lp.ParameterState(key=KEY_RTE, learned_value=0.95), NOW)

    states = await parameter_store.get_states()
    assert len(states) == 1
    assert states[KEY_RTE].learned_value == 0.95


@pytest.mark.asyncio
async def test_history_append_list_and_filter(parameter_store) -> None:
    def event(key: str, minutes: int, notify: str) -> lp.HistoryEvent:
        return lp.HistoryEvent(
            key=key,
            at=NOW + timedelta(minutes=minutes),
            event=lp.EVENT_LEARNED,
            old_value=0.9,
            new_value=0.91,
            confidence=0.8,
            evidence={"days": 30},
            notify_state=notify,
        )

    ids = await parameter_store.add_history(
        [event(KEY_RTE, 0, lp.NOTIFY_PENDING), event(KEY_CHARGE_LOSS, 1, lp.NOTIFY_NONE)]
    )
    assert len(ids) == 2

    rows = await parameter_store.list_history(limit=10)
    assert [r.key for r in rows] == [KEY_CHARGE_LOSS, KEY_RTE]
    assert rows[1].evidence == {"days": 30}
    only = await parameter_store.list_history(limit=10, key=KEY_RTE)
    assert [r.key for r in only] == [KEY_RTE]
    assert len(await parameter_store.list_history(limit=1)) == 1


@pytest.mark.asyncio
async def test_pending_rows_and_marking(parameter_store) -> None:
    old = lp.HistoryEvent(
        KEY_RTE, NOW - timedelta(days=4), lp.EVENT_LEARNED, 0.9, 0.91, 0.8, {}, lp.NOTIFY_PENDING
    )
    fresh = lp.HistoryEvent(KEY_RTE, NOW, lp.EVENT_LEARNED, 0.91, 0.92, 0.8, {}, lp.NOTIFY_PENDING)
    ids = await parameter_store.add_history([old, fresh])

    pending = await parameter_store.pending_history(NOW - timedelta(days=3))
    assert [r.id for r in pending] == [ids[1]]

    await parameter_store.mark_notified([ids[1]], lp.NOTIFY_SENT, NOW)
    assert await parameter_store.pending_history(NOW - timedelta(days=3)) == []
    sent = (await parameter_store.list_history(limit=5))[0]
    assert sent.notify_state == lp.NOTIFY_SENT and sent.notified_at == NOW


@pytest.mark.asyncio
async def test_lock_and_unlock_write_history_without_notification(parameter_store) -> None:
    await parameter_store.set_lock(lp.KEY_DISCHARGE_EFFICIENCY, 0.95, NOW)
    state = (await parameter_store.get_states())[lp.KEY_DISCHARGE_EFFICIENCY]
    assert state.locked and state.locked_value == 0.95

    await parameter_store.set_lock(lp.KEY_DISCHARGE_EFFICIENCY, 0.96, NOW + timedelta(minutes=1))
    await parameter_store.clear_lock(lp.KEY_DISCHARGE_EFFICIENCY, NOW + timedelta(minutes=2))

    state = (await parameter_store.get_states())[lp.KEY_DISCHARGE_EFFICIENCY]
    assert not state.locked and state.locked_value is None
    history = await parameter_store.list_history(limit=10)
    assert [h.event for h in history] == [lp.EVENT_UNLOCKED, lp.EVENT_LOCK_CHANGED, lp.EVENT_LOCKED]
    assert {h.notify_state for h in history} == {lp.NOTIFY_NONE}
    assert await parameter_store.pending_history(NOW - timedelta(days=1)) == []


@pytest.mark.asyncio
async def test_lock_validates_bounds_and_key(parameter_store) -> None:
    with pytest.raises(ValueError, match="between"):
        await parameter_store.set_lock(lp.KEY_DISCHARGE_EFFICIENCY, 0.5, NOW)
    with pytest.raises(KeyError):
        await parameter_store.set_lock("nope", 0.5, NOW)
    with pytest.raises(KeyError):
        await parameter_store.clear_lock("nope", NOW)
    assert await parameter_store.get_states() == {}


@pytest.mark.asyncio
async def test_last_event_ignores_lock_events(parameter_store) -> None:
    await parameter_store.add_history([lp.HistoryEvent(KEY_RTE, NOW, lp.EVENT_EXPIRED, 0.9, None)])
    await parameter_store.set_lock(KEY_RTE, 0.95, NOW + timedelta(minutes=1))
    assert await parameter_store.last_event(KEY_RTE) == lp.EVENT_EXPIRED
