"""HTTP client for the updater sidecar (internal compose network, bearer token)."""

from __future__ import annotations

import os
from typing import Any, Protocol, cast

import aiohttp

UPDATER_TIMEOUT_S = 5


class UpdaterUnavailableError(Exception):
    """The updater could not be reached or rejected our token."""


class UpdaterClient(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]: ...


class HttpUpdaterClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        timeout = aiohttp.ClientTimeout(total=UPDATER_TIMEOUT_S)
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.request(
                    method, f"{self._base_url}{path}", json=json, params=params, headers=headers
                ) as response,
            ):
                if response.status == 401:
                    raise UpdaterUnavailableError("The updater rejected the access token")
                data = await response.json(content_type=None)
                return response.status, cast("dict[str, Any]", data)
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            raise UpdaterUnavailableError(str(exc) or type(exc).__name__) from exc


def updater_url() -> str | None:
    """Updater URL, or None when not opted in (URL or token unset): the feature stays hidden."""
    if not os.getenv("DARKSTAR_UPDATER_TOKEN"):
        return None
    return os.getenv("DARKSTAR_UPDATER_URL") or None


def get_updater_client() -> UpdaterClient:
    url = updater_url() or ""
    return HttpUpdaterClient(url, os.getenv("DARKSTAR_UPDATER_TOKEN", ""))
