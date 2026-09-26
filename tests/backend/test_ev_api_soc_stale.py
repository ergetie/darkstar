"""EV API reports soc_unavailable for a stale SoC (ev-soc-staleness 4.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.routers import ev as ev_router
from backend.core.ev_live_state import remember_soc, stale_soc_episodes

NOW = datetime.now(UTC)


def _persisted() -> dict:
    return {
        "target_soc_percent": 80,
        "ready_by": "18:30",
        "repeat": "daily",
        "deadline": (NOW + timedelta(hours=4)).isoformat(),
        "required_kwh": 6.0,
        "current_soc_percent": 70.0,
        "last_updated": (NOW - timedelta(hours=1)).isoformat(),
        "last_planned_at": (NOW - timedelta(minutes=5)).isoformat(),
    }


async def _get(monkeypatch, soc: float | None, plug: str = "on") -> dict:
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {"ev1": _persisted()})
    monkeypatch.setattr(ev_router, "_load_schedule_meta", lambda _schedule=None: {})
    monkeypatch.setattr(
        ev_router,
        "load_yaml",
        lambda _p: {
            "ev_chargers": [
                {
                    "id": "ev1",
                    "name": "EV",
                    "sensor": "sensor.p",
                    "soc_sensor": "sensor.soc",
                    "plug_sensor": "binary_sensor.plug",
                    "rated_power_kw": 11.0,
                }
            ]
        },
    )
    with (
        patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0)),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=soc)),
        patch("backend.api.routers.ev.get_ha_entity_state", AsyncMock(return_value={"state": plug})),
    ):
        (charger,) = await ev_router.get_ev_chargers()
    return charger


@pytest.mark.asyncio
async def test_stale_soc_reports_soc_unavailable(monkeypatch):
    remember_soc("ev1", 65.0, NOW - timedelta(minutes=40))
    charger = await _get(monkeypatch, None)
    assert charger["status"] == "soc_unavailable"
    assert charger["soc_percent"] is None
    assert charger["soc_status"] == "stale"
    assert charger["soc_age_minutes"] == pytest.approx(40.0, abs=0.5)
    assert "ev1" in stale_soc_episodes()


@pytest.mark.asyncio
async def test_carried_soc_is_not_unavailable(monkeypatch):
    remember_soc("ev1", 65.0, NOW - timedelta(minutes=5))
    charger = await _get(monkeypatch, None)
    assert charger["soc_status"] == "carried"
    assert charger["status"] != "soc_unavailable"
    assert stale_soc_episodes() == {}


@pytest.mark.asyncio
async def test_unplugged_stale_soc_is_not_unavailable(monkeypatch):
    charger = await _get(monkeypatch, None, plug="off")
    assert charger["soc_status"] == "stale"
    assert charger["status"] != "soc_unavailable"
    assert stale_soc_episodes() == {}


@pytest.mark.asyncio
async def test_live_soc(monkeypatch):
    charger = await _get(monkeypatch, 72.0)
    assert charger["soc_status"] == "live"
    assert charger["soc_percent"] == 72.0
