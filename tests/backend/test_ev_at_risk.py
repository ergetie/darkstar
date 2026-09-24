"""fix-ev-current-charger-control 5.2: EV API at_risk status from plan diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.routers import ev as ev_router

NOW = datetime.now(UTC)
DEADLINE = (NOW + timedelta(hours=2)).isoformat()
PLANNED_AT = (NOW - timedelta(minutes=5)).isoformat()


def _persisted(**overrides) -> dict:
    state = {
        "target_soc_percent": 80,
        "ready_by": "18:30",
        "repeat": "daily",
        "deadline": DEADLINE,
        "required_kwh": 0.6,
        "delivered_kwh": 0.0,
        "remaining_kwh": 0.6,
        "current_soc_percent": 79.0,
        "last_updated": (NOW - timedelta(hours=1)).isoformat(),
        "last_planned_at": PLANNED_AT,
    }
    state.update(overrides)
    return state


def _diagnostics(**overrides) -> dict:
    diag = {
        "required_kwh": 0.6,
        "scheduled_kwh": 0.0,
        "shortfall_kwh": 0.6,
        "reason": "grid_limit",
        "deadline": DEADLINE,
        "max_import_kw": 8.0,
    }
    diag.update(overrides)
    return diag


async def _get(monkeypatch, persisted: dict, diagnostics: dict | None) -> dict:
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {"ev1": persisted})
    monkeypatch.setattr(
        ev_router,
        "_load_schedule_meta",
        lambda: {"ev_goal_diagnostics": {"ev1": diagnostics} if diagnostics else {}},
    )
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
                    "max_power_kw": 11.0,
                }
            ]
        },
    )
    with (
        patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0)),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=79.0)),
        patch("backend.api.routers.ev.get_ha_entity_state", AsyncMock(return_value={"state": "on"})),
    ):
        (charger,) = await ev_router.get_ev_chargers()
    return charger


@pytest.mark.asyncio
async def test_shortfall_reports_at_risk(monkeypatch):
    charger = await _get(monkeypatch, _persisted(), _diagnostics())
    assert charger["status"] == "at_risk"
    assert charger["shortfall_kwh"] == 0.6
    assert charger["shortfall_reason"] == "grid_limit"
    assert charger["max_import_kw"] == 8.0


@pytest.mark.asyncio
async def test_no_shortfall_keeps_heuristic_status(monkeypatch):
    charger = await _get(monkeypatch, _persisted(), _diagnostics(shortfall_kwh=0.0, reason=None))
    assert charger["status"] == "on_track"
    assert charger["shortfall_kwh"] is None


@pytest.mark.asyncio
async def test_goal_edited_after_plan_ignores_diagnostics(monkeypatch):
    """User changed the goal and no replan has happened yet: stale diagnostics."""
    persisted = _persisted(last_updated=NOW.isoformat())
    charger = await _get(monkeypatch, persisted, _diagnostics())
    assert charger["status"] == "on_track"


@pytest.mark.asyncio
async def test_deadline_mismatch_ignores_diagnostics(monkeypatch):
    diag = _diagnostics(deadline=(NOW + timedelta(hours=5)).isoformat())
    charger = await _get(monkeypatch, _persisted(), diag)
    assert charger["status"] == "on_track"


@pytest.mark.asyncio
async def test_required_energy_mismatch_ignores_diagnostics(monkeypatch):
    charger = await _get(monkeypatch, _persisted(required_kwh=5.0), _diagnostics())
    assert charger["status"] == "on_track"


@pytest.mark.asyncio
async def test_required_energy_within_tolerance_still_at_risk(monkeypatch):
    charger = await _get(monkeypatch, _persisted(required_kwh=0.64), _diagnostics())
    assert charger["status"] == "at_risk"
