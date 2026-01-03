import asyncio
import logging
import subprocess
from typing import Any

import yaml
from fastapi import APIRouter

from backend.api.models.system import StatusResponse, VersionResponse
from inputs import (
    async_get_ha_sensor_float,
    load_yaml,
)

logger = logging.getLogger("darkstar.api.system")
router = APIRouter(tags=["system"])


def _get_git_version() -> str:
    """Get version from git tags, falling back to darkstar/config.yaml."""
    try:
        return (
            subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        pass

    # Fallback: read from darkstar/config.yaml (add-on version)
    try:
        from pathlib import Path

        with Path("darkstar/config.yaml").open() as f:
            addon_config = yaml.safe_load(f)
        if addon_config and addon_config.get("version"):
            return addon_config["version"]
    except Exception:
        pass

    return "dev"


@router.get(
    "/api/version",
    summary="Get System Version",
    description="Returns the current version, commit hash, and build date.",
    response_model=VersionResponse,
)
async def get_version() -> VersionResponse:
    """Return the current system version."""
    return VersionResponse(version=_get_git_version())


@router.get(
    "/api/status",
    summary="Get System Status",
    description="Get instantaneous system status (SoC, Power Flow) in parallel.",
    response_model=StatusResponse,
)
async def get_system_status() -> StatusResponse:
    """Get instantaneous system status (SoC, Power Flow) using parallel async fetching."""
    config = load_yaml("config.yaml")
    sensors: dict[str, Any] = config.get("input_sensors", {})

    # Define keys to fetch
    keys = ["battery_soc", "pv_power", "load_power", "battery_power", "grid_power"]
    tasks = []
    for key in keys:
        eid = sensors.get(key)
        if eid:
            tasks.append(async_get_ha_sensor_float(str(eid)))
        else:
            tasks.append(asyncio.sleep(0, result=0.0))

    results = await asyncio.gather(*tasks)

    soc = results[0] or 0.0
    pv_pow = results[1] or 0.0
    load_pow = results[2] or 0.0
    batt_pow = results[3] or 0.0
    grid_pow = results[4] or 0.0

    return StatusResponse(
        status="online",
        mode="fastapi",
        rev="ARC1",
        soc_percent=round(soc, 1),
        pv_power_kw=round(pv_pow / 1000.0, 3),
        load_power_kw=round(load_pow / 1000.0, 3),
        battery_power_kw=round(batt_pow / 1000.0, 3),
        grid_power_kw=round(grid_pow / 1000.0, 3),
    )
