"""Pydantic models for system-related API responses."""

from pydantic import BaseModel


class VersionResponse(BaseModel):
    """Response model for /api/version endpoint."""

    version: str


class StatusResponse(BaseModel):
    """Response model for /api/status endpoint."""

    status: str
    mode: str
    rev: str
    soc_percent: float
    pv_power_kw: float
    load_power_kw: float
    battery_power_kw: float
    grid_power_kw: float


class LogInfoResponse(BaseModel):
    """Response model for /api/system/log-info endpoint."""

    filename: str
    size_bytes: int
    last_modified: str
