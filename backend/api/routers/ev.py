"""Read-only EV state API (price-forecasting-module-4 section 5.1-5.3).

``GET /api/ev/chargers`` merges per-charger transient goal/progress state
(written by the planner pipeline to ``data/ev_multi_day_state.json``) with
live Home Assistant sensor data fetched on request. Used by Module 5's UI.

No ``charge_priority`` field is returned — it does not exist in this change.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter

from backend.core.ha_client import get_ha_bool, get_ha_sensor_float, get_ha_sensor_kw_normalized
from backend.core.secrets import load_yaml

logger = logging.getLogger("darkstar.api.ev")

router = APIRouter(prefix="/api/ev", tags=["ev"])

# State older than this is considered stale → charger reports ``idle``.
STATE_STALE_SECONDS = 2 * 60 * 60


def _load_ev_state() -> dict[str, dict[str, Any]]:
    """Read the transient EV state file. Returns ``{}`` if missing/unreadable."""
    path = Path("data/ev_multi_day_state.json")
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            data = json.load(f)
        if isinstance(data, dict):
            return cast("dict[str, dict[str, Any]]", data)
    except Exception as exc:
        logger.warning("Could not read EV state file: %s", exc)
    return {}


def _parse_iso_deadline(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _compute_status(
    plugged_in: bool,
    deadline: datetime | None,
    required_kwh: float | None,
    max_power_kw: float,
    now: datetime,
) -> str:
    """Classify a charger: on_track | behind | complete | idle."""
    if not plugged_in or deadline is None or required_kwh is None:
        return "idle"
    if required_kwh <= 0.0:
        return "complete"
    seconds_left = (deadline - now).total_seconds()
    if seconds_left <= 0.0:
        return "behind"
    deliverable = max_power_kw * (seconds_left / 3600.0)
    return "on_track" if deliverable + 1e-6 >= required_kwh else "behind"


@router.get(
    "/chargers",
    summary="Get EV Charger Status",
    description=(
        "Per-charger live HA sensor data merged with goal and progress from the "
        "last pipeline run. ``status ∈ {on_track, behind, complete, idle}``."
    ),
)
async def get_ev_chargers() -> list[dict[str, Any]]:
    """Return all configured EV chargers with live sensors, goal, progress, status."""
    config = load_yaml("config.yaml")
    ev_chargers_cfg: list[dict[str, Any]] = config.get("ev_chargers", []) or []
    state_by_id = _load_ev_state()
    now = datetime.now(UTC)

    async def _safe_float(entity_id: str) -> float | None:
        if not entity_id:
            return None
        try:
            return await get_ha_sensor_float(entity_id)
        except Exception:
            return None

    async def _safe_kw(entity_id: str) -> float | None:
        if not entity_id:
            return None
        try:
            return await get_ha_sensor_kw_normalized(entity_id)
        except Exception:
            return None

    async def _safe_bool(entity_id: str) -> bool | None:
        if not entity_id:
            return None
        try:
            return await get_ha_bool(entity_id)
        except Exception:
            return None

    out: list[dict[str, Any]] = []
    for ev in ev_chargers_cfg:
        if not ev.get("enabled", True):
            continue
        charger_id = str(ev.get("id", ""))

        power_kw = await _safe_kw(str(ev.get("sensor", "")))
        soc_percent = await _safe_float(str(ev.get("soc_sensor", "")))
        plugged_in = await _safe_bool(str(ev.get("plug_sensor", "")))

        persisted = state_by_id.get(charger_id, {})
        stale = False
        last_updated = persisted.get("last_updated")
        last_updated_dt = _parse_iso_deadline(last_updated) if last_updated else None
        if (
            last_updated_dt is not None
            and (now - last_updated_dt).total_seconds() > STATE_STALE_SECONDS
        ):
            stale = True

        max_power_kw = float(ev.get("max_power_kw") or 7.4)

        if not persisted or stale:
            # Missing/stale state → idle with null goal-progress; live sensors only.
            out.append(
                {
                    "id": charger_id,
                    "name": ev.get("name", charger_id),
                    "plugged_in": plugged_in,
                    "soc_percent": round(soc_percent, 1) if soc_percent is not None else None,
                    "power_kw": round(power_kw, 3) if power_kw is not None else None,
                    "target_soc_percent": None,
                    "ready_by": None,
                    "repeat": None,
                    "deadline": None,
                    "required_kwh": None,
                    "delivered_kwh": None,
                    "remaining_kwh": None,
                    "daily_quota_kwh": None,
                    "quota_schedule": None,
                    "keep_on_after_target": bool(ev.get("keep_on_after_target", False)),
                    "status": "idle",
                    "last_updated": None,
                }
            )
            continue

        deadline = _parse_iso_deadline(persisted.get("deadline"))
        required_kwh = persisted.get("required_kwh")
        if isinstance(required_kwh, str):
            try:
                required_kwh = float(required_kwh)
            except ValueError:
                required_kwh = None

        # Re-derive live status: if the live SoC already meets the target, mark complete.
        live_soc = soc_percent if soc_percent is not None else persisted.get("current_soc_percent")
        target_soc_cfg = persisted.get("target_soc_percent")
        if (
            live_soc is not None
            and target_soc_cfg is not None
            and float(live_soc) >= float(target_soc_cfg) - 1e-6
        ):
            status = "complete"
        else:
            status = _compute_status(
                plugged_in if plugged_in is not None else False,
                deadline,
                required_kwh if required_kwh is not None else None,
                max_power_kw,
                now,
            )

        out.append(
            {
                "id": charger_id,
                "name": ev.get("name", charger_id),
                "plugged_in": plugged_in,
                "soc_percent": round(soc_percent, 1) if soc_percent is not None else None,
                "power_kw": round(power_kw, 3) if power_kw is not None else None,
                "target_soc_percent": persisted.get("target_soc_percent"),
                "ready_by": persisted.get("ready_by"),
                "repeat": persisted.get("repeat"),
                "deadline": persisted.get("deadline"),
                "required_kwh": persisted.get("required_kwh"),
                "delivered_kwh": persisted.get("delivered_kwh"),
                "remaining_kwh": persisted.get("remaining_kwh"),
                "daily_quota_kwh": persisted.get("daily_quota_kwh"),
                "quota_schedule": persisted.get("quota_schedule"),
                "keep_on_after_target": bool(persisted.get("keep_on_after_target", False)),
                "status": status,
                "last_updated": persisted.get("last_updated"),
            }
        )

    return out


# Suppress unused-import warning for asyncio (kept for parity with system.py pattern).
_ = asyncio
