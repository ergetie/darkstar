import logging
import subprocess
from typing import Any

import yaml
from fastapi import APIRouter

from backend.api.models.system import StatusResponse, VersionResponse
from inputs import get_home_assistant_sensor_float, load_yaml

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
    description="Get instantaneous system status (SoC, Power Flow).",
    response_model=StatusResponse,
)
async def get_system_status() -> StatusResponse:
    """Get instantaneous system status (SoC, Power Flow)."""
    config = load_yaml("config.yaml")
    sensors: dict[str, Any] = config.get("input_sensors", {})

    def get_val(key: str, default: float = 0.0) -> float:
        eid = sensors.get(key)
        if not eid:
            return default
        return get_home_assistant_sensor_float(str(eid)) or default

    soc = get_val("battery_soc")
    pv_pow = get_val("pv_power")
    load_pow = get_val("load_power")
    batt_pow = get_val("battery_power")
    grid_pow = get_val("grid_power")

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
