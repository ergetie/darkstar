"""In-app update endpoints: thin authenticated proxy to the updater sidecar."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.services.installation_stats_contract import classify_installation_type
from backend.services.updater_client import (
    UpdaterClient,
    UpdaterUnavailableError,
    get_updater_client,
    updater_url,
)


def require_updater_enabled() -> None:
    """The feature exists only on docker installs with a configured updater."""
    if classify_installation_type() != "docker" or not updater_url():
        raise HTTPException(status_code=404, detail="Updates are not available on this install")


router = APIRouter(
    prefix="/api/updater", tags=["updater"], dependencies=[Depends(require_updater_enabled)]
)


class ChannelRequest(BaseModel):
    channel: Literal["dev", "stable"]


async def _call(
    client: UpdaterClient,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    try:
        return await client.request(method, path, json=json, params=params)
    except UpdaterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Updater unavailable: {exc}") from exc


async def _status_or_unavailable(
    client: UpdaterClient, method: str, path: str, json: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Updater status, or `reachable: false` so the UI can explain instead of hiding."""
    try:
        _, data = await client.request(method, path, json=json)
    except UpdaterUnavailableError as exc:
        return {"reachable": False, "error": str(exc)}
    return {"reachable": True, **data}


@router.get("/status", summary="Updater status (cached check result)")
async def get_status(client: UpdaterClient = Depends(get_updater_client)) -> dict[str, Any]:
    return await _status_or_unavailable(client, "GET", "/status")


@router.post("/check", summary="Check for updates now")
async def check(client: UpdaterClient = Depends(get_updater_client)) -> dict[str, Any]:
    return await _status_or_unavailable(client, "POST", "/check")


@router.put("/channel", summary="Switch update channel")
async def set_channel(
    body: ChannelRequest, client: UpdaterClient = Depends(get_updater_client)
) -> dict[str, Any]:
    return await _status_or_unavailable(client, "PUT", "/channel", {"channel": body.channel})


@router.post("/apply", summary="Apply the available update")
async def apply(client: UpdaterClient = Depends(get_updater_client)) -> dict[str, Any]:
    status, data = await _call(client, "POST", "/apply")
    if status >= 400:
        raise HTTPException(status_code=status, detail=data)
    return {"reachable": True, **data}


@router.get("/log", summary="Incremental apply log")
async def get_log(
    offset: int = Query(0, ge=0), client: UpdaterClient = Depends(get_updater_client)
) -> dict[str, Any]:
    _, data = await _call(client, "GET", "/log", params={"offset": offset})
    return data
