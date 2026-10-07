from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from backend.services.installation_stats_service import InstallationStatsService
from backend.services.installation_stats_state import InstallationStatsState
from telemetry_receiver.app import ReceiverSettings, create_app
from telemetry_receiver.database import TelemetryDatabase

if TYPE_CHECKING:
    from pathlib import Path


class FakeClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class InProcessReceiverTransport(httpx.AsyncBaseTransport):
    """Route sender HTTPS requests into the receiver ASGI app without networking."""

    def __init__(self, app: object) -> None:
        self.app = app
        self.requested = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        assert request.url.host == "telemetry.wxl.se"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://receiver.test"
        ) as local_client:
            response = await local_client.request(
                request.method,
                request.url.path,
                headers={
                    "content-type": request.headers.get("content-type", ""),
                },
                content=await request.aread(),
            )
            outgoing = httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=await response.aread(),
                request=request,
            )
            self.requested.set()
            return outgoing


class ImmediateDueService(InstallationStatsService):
    def __init__(self, *args: object, clock: FakeClock, **kwargs: object) -> None:
        super().__init__(*args, now=clock, **kwargs)
        self.clock = clock

    async def _wait(self, seconds: float) -> None:
        self.clock.advance(seconds)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_sender_to_receiver_smoke_uses_only_in_process_transport(tmp_path: Path) -> None:
    settings = ReceiverSettings(
        database_path=tmp_path / "receiver.sqlite3",
        stats_username="stats-user",
        stats_password="a-long-test-password",
    )
    receiver_app = create_app(settings_loader=lambda: settings)
    database = TelemetryDatabase(settings.database_path)
    await database.initialize()
    await database.collect_snapshot_and_cleanup(datetime.now(UTC))
    receiver_app.state.receiver_settings = settings
    receiver_app.state.telemetry_database = database

    transport = InProcessReceiverTransport(receiver_app)
    clock = FakeClock(datetime.now(UTC))
    sender = ImmediateDueService(
        data_dir=tmp_path / "sender-data",
        config_loader=lambda: {
            "system": {"inverter_profile": "generic"},
            "installation_stats": {
                "enabled": True,
                "endpoint": "https://telemetry.wxl.se/api/ping",
            },
        },
        client_factory=lambda: httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(5),
            verify=True,
            follow_redirects=False,
        ),
        clock=clock,
        randint=lambda _low, _high: 60,
    )

    await sender.start()
    await asyncio.wait_for(transport.requested.wait(), timeout=3)
    await sender.stop()

    state = InstallationStatsState(tmp_path / "sender-data" / "installation_stats.stable.json")
    state.load()
    stats = await database.stats(datetime.now(UTC))
    assert stats["active_7_days"]["total"] == 1  # type: ignore[index]
    assert stats["active_30_days"]["breakdowns"]["inverter_profile"] == {"generic": 1}  # type: ignore[index]
    assert stats["active_30_days"]["breakdowns"]["execution_mode"] == {"unknown": 1}  # type: ignore[index]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=receiver_app), base_url="http://receiver.test"
    ) as reader:
        unauthorized = await reader.get("/")
        assert unauthorized.status_code == 401
        assert unauthorized.headers["cache-control"] == "no-store"
        summary = await reader.get("/", auth=(settings.stats_username, settings.stats_password))
        protected_stats = await reader.get(
            "/api/stats", auth=(settings.stats_username, settings.stats_password)
        )

    assert summary.status_code == 200
    assert protected_stats.status_code == 200
    assert protected_stats.headers["cache-control"] == "no-store"
    assert state.installation_id not in summary.text
    assert state.installation_id not in protected_stats.text
