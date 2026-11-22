"""run_once: fenced estimators, history events for change, expiry and recovery."""

from datetime import timedelta

import pytest

from backend.learning import learned_parameters as lp
from backend.learning.battery_estimators import (
    KEY_CHARGE_LOSS,
    KEY_RTE,
    KEY_STANDBY_W,
)
from tests.learning.battery_synth import CAPACITY_KWH, after, make_rows

CONFIG = {"system": {"battery": {"capacity_kwh": CAPACITY_KWH}}}
ROWS = make_rows(40)
NOW = after(40)


async def _events(parameter_store) -> list[str]:
    return [f"{h.key}:{h.event}" for h in await parameter_store.list_history(limit=50)]


@pytest.mark.asyncio
async def test_first_run_adopts_every_estimate_and_records_history(parameter_store) -> None:
    changes = await lp.run_once(parameter_store, ROWS, CONFIG, NOW)

    assert {c.key for c in changes} == {KEY_RTE, KEY_CHARGE_LOSS, KEY_STANDBY_W}
    states = await parameter_store.get_states()
    assert states[KEY_RTE].applied_value == pytest.approx(0.962, abs=0.002)
    assert states[KEY_CHARGE_LOSS].applied_value == pytest.approx(0.0698, abs=0.01)
    assert len(await parameter_store.list_history(limit=50)) == 3


@pytest.mark.asyncio
async def test_crash_in_one_estimator_does_not_stop_the_other(parameter_store, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("estimator crashed")

    monkeypatch.setattr(lp, "estimate_round_trip_efficiency", boom)

    changes = await lp.run_once(parameter_store, ROWS, CONFIG, NOW)

    assert {c.key for c in changes} == {KEY_CHARGE_LOSS, KEY_STANDBY_W}
    assert KEY_RTE not in await parameter_store.get_states()


@pytest.mark.asyncio
async def test_expiry_event_after_31_days_without_data(parameter_store) -> None:
    await lp.run_once(parameter_store, ROWS, CONFIG, NOW)

    later = NOW + timedelta(days=31)
    changes = await lp.run_once(parameter_store, [], CONFIG, later)

    expired = [c for c in changes if c.event == lp.EVENT_EXPIRED]
    assert {c.key for c in expired} == {KEY_RTE, KEY_CHARGE_LOSS, KEY_STANDBY_W}
    assert all(c.new_value is None and c.old_value is not None for c in expired)
    # A second run does not repeat the expiry.
    assert await lp.run_once(parameter_store, [], CONFIG, later + timedelta(days=1)) == []


@pytest.mark.asyncio
async def test_recovery_event_when_an_expired_parameter_gets_data(parameter_store) -> None:
    await lp.run_once(parameter_store, ROWS, CONFIG, NOW)
    await lp.run_once(parameter_store, [], CONFIG, NOW + timedelta(days=31))

    rows = make_rows(40, first_day=(NOW + timedelta(days=40)).date())
    recovery_time = after(80)
    changes = await lp.run_once(parameter_store, ROWS + rows, CONFIG, recovery_time)

    recovered = {c.key for c in changes if c.event == lp.EVENT_RECOVERED}
    assert recovered == {KEY_RTE, KEY_CHARGE_LOSS, KEY_STANDBY_W}
    assert not [c for c in changes if c.event == lp.EVENT_LEARNED]
    resolved = lp.resolve_battery_parameters(
        CONFIG, await parameter_store.get_states(), recovery_time
    )
    assert resolved.learned


@pytest.mark.asyncio
async def test_no_events_when_nothing_changed(parameter_store) -> None:
    await lp.run_once(parameter_store, ROWS, CONFIG, NOW)
    before = len(await parameter_store.list_history(limit=50))

    changes = await lp.run_once(parameter_store, ROWS, CONFIG, NOW + timedelta(days=1))

    assert changes == []
    assert len(await parameter_store.list_history(limit=50)) == before


@pytest.mark.asyncio
async def test_locked_parameter_changes_do_not_notify(parameter_store) -> None:
    await parameter_store.set_lock(KEY_RTE, 0.95, NOW - timedelta(days=1))
    sent: list[str] = []

    async def notifier(_title: str, message: str) -> bool:
        sent.append(message)
        return True

    await lp.run_once(parameter_store, ROWS, CONFIG, NOW, notifier)

    assert len(sent) == 1
    assert "round-trip" not in sent[0]
    state = (await parameter_store.get_states())[KEY_RTE]
    assert state.learned_value == pytest.approx(0.962, abs=0.002)
    assert state.applied_value is None


@pytest.mark.asyncio
async def test_run_with_no_data_reports_rejections_in_evidence(parameter_store) -> None:
    assert await lp.run_once(parameter_store, [], CONFIG, NOW) == []

    # Nothing accepted yet: rejection state is persisted.
    state = (await parameter_store.get_states())[KEY_RTE]
    assert state.learned_value is None
    assert state.status_note is not None
    assert "last_rejection" in state.evidence


@pytest.mark.asyncio
async def test_without_estimation_stale_values_still_expire_and_notify(parameter_store) -> None:
    await lp.run_once(parameter_store, ROWS, CONFIG, NOW)
    sent: list[str] = []

    async def notifier(_title: str, message: str) -> bool:
        sent.append(message)
        return True

    later = NOW + timedelta(days=31)
    changes = await lp.run_once(parameter_store, ROWS, CONFIG, later, notifier, run_estimators=False)

    assert {c.key for c in changes if c.event == lp.EVENT_EXPIRED} == {
        KEY_RTE,
        KEY_CHARGE_LOSS,
        KEY_STANDBY_W,
    }
    assert sent and "expired" in sent[0]
    states = await parameter_store.get_states()
    assert states[KEY_RTE].estimated_at == NOW  # nothing was re-estimated
