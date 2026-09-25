"""Shared live EV state reader (ev-live-state)."""

from __future__ import annotations

import logging

import pytest

from backend.core import ev_plug
from backend.core.ev_live_state import EVLiveState, read_ev_live_state

SOC = "sensor.car_soc"
PLUG = "sensor.car_plug"


@pytest.fixture(autouse=True)
def _clear_last_known():
    ev_plug._last_known_plugged.clear()
    yield
    ev_plug._last_known_plugged.clear()


def _getter(states: dict[str, str | None], fail: set[str] | None = None):
    async def get_state(entity_id: str) -> str | None:
        if fail and entity_id in fail:
            raise RuntimeError("boom")
        return states.get(entity_id)

    return get_state


async def _read(states, *, soc_sensor=SOC, plug_sensor=PLUG, fail=None):
    return await read_ev_live_state(
        "ev1",
        _getter(states, fail),
        soc_sensor=soc_sensor,
        plug_sensor=plug_sensor,
        plugged_in_states="on,connected",
    )


async def test_normal_readings():
    assert await _read({SOC: "63.5", PLUG: "connected"}) == EVLiveState(63.5, "plugged")


async def test_car_disconnected():
    state = await _read({SOC: "63.5", PLUG: "disconnected"})
    assert state.plug == "unplugged"


@pytest.mark.parametrize("raw", ["unavailable", "unknown", None])
async def test_unreachable_plug_is_unknown_despite_last_known(raw):
    ev_plug.remember_plug_state("ev1", True)
    state = await _read({SOC: "50", PLUG: raw})
    assert state.plug == "unknown"


@pytest.mark.parametrize("raw", ["n/a", "unavailable", "unknown", None])
async def test_unreadable_soc_is_none(raw):
    state = await _read({SOC: raw, PLUG: "connected"})
    assert state.soc_percent is None


async def test_plug_read_error_is_unknown_and_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="backend.core.ev_live_state"):
        state = await _read({SOC: "50"}, fail={PLUG})
    assert state.plug == "unknown"
    assert any("plug read failed" in r.getMessage() for r in caplog.records)


async def test_soc_read_error_is_none():
    state = await _read({PLUG: "connected"}, fail={SOC})
    assert state == EVLiveState(None, "plugged")


async def test_no_plug_sensor_assumed_plugged():
    state = await _read({SOC: "50"}, plug_sensor="")
    assert state.plug == "plugged"


async def test_no_soc_sensor():
    state = await _read({SOC: "50", PLUG: "connected"}, soc_sensor=None)
    assert state.soc_percent is None


@pytest.mark.parametrize(("raw", "expected"), [("connected", True), ("disconnected", False)])
async def test_valid_reading_recorded_as_last_known(raw, expected):
    await _read({PLUG: raw})
    assert ev_plug.last_known_plug_state("ev1") is expected


async def test_unknown_reading_not_recorded():
    await _read({PLUG: "unavailable"})
    assert ev_plug.last_known_plug_state("ev1") is None
