"""Independent FastAPI application for installation telemetry."""

from __future__ import annotations

import asyncio
import base64
import binascii
import html
import json
import logging
import math
import os
import secrets
import sqlite3
import time
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.requests import ClientDisconnect

from telemetry_receiver.contracts import validate_payload
from telemetry_receiver.database import DatabaseBusyError, TelemetryDatabase

logger = logging.getLogger("telemetry_receiver")
MAX_REQUEST_BYTES = 2 * 1024
PING_BURST = 60.0
PING_RATE_PER_SECOND = 60.0


@dataclass(frozen=True)
class ReceiverSettings:
    database_path: Path
    stats_username: str
    stats_password: str

    def __post_init__(self) -> None:
        if not self.stats_username.strip() or not self.stats_password.strip():
            raise RuntimeError(
                "TELEMETRY_STATS_USERNAME and TELEMETRY_STATS_PASSWORD must be configured"
            )

    @classmethod
    def from_environment(cls) -> ReceiverSettings:
        username = os.environ.get("TELEMETRY_STATS_USERNAME", "")
        password = os.environ.get("TELEMETRY_STATS_PASSWORD", "")
        return cls(
            database_path=Path(
                os.environ.get("TELEMETRY_DB_PATH", "/var/lib/darkstar-telemetry/telemetry.sqlite3")
            ),
            stats_username=username,
            stats_password=password,
        )


class GlobalTokenBucket:
    """Single-process rate limiter without address or sender identity keys."""

    def __init__(
        self,
        *,
        capacity: float = PING_BURST,
        rate_per_second: float = PING_RATE_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = capacity
        self.rate_per_second = rate_per_second
        self._clock = clock
        self._tokens = capacity
        self._updated_at = clock()

    def consume(self) -> tuple[bool, int]:
        now = self._clock()
        elapsed = max(0.0, now - self._updated_at)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate_per_second)
        self._updated_at = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True, 0
        retry_after = max(1, math.ceil((1.0 - self._tokens) / self.rate_per_second))
        return False, retry_after


def create_app(
    *, settings_loader: Callable[[], ReceiverSettings] = ReceiverSettings.from_environment
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        settings = settings_loader()
        database = TelemetryDatabase(settings.database_path)
        await database.initialize()
        await database.collect_snapshot_and_cleanup(datetime.now(UTC))
        app.state.receiver_settings = settings
        app.state.telemetry_database = database
        app.state.maintenance_task = asyncio.create_task(
            _daily_maintenance(database), name="telemetry-maintenance"
        )
        try:
            yield
        finally:
            task = app.state.maintenance_task
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="Installation telemetry receiver",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.ping_limiter = GlobalTokenBucket()

    async def require_stats_auth(request: Request) -> None:
        settings: ReceiverSettings = request.app.state.receiver_settings
        authorization = request.headers.get("authorization", "")
        scheme, separator, encoded = authorization.partition(" ")
        decoded: str | None = None
        if separator and scheme.lower() == "basic":
            try:
                decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                decoded = None
        username, password = "", ""
        if decoded is not None:
            username, colon, password = decoded.partition(":")
            if not colon:
                username, password = "", ""
        username_matches = secrets.compare_digest(
            username.encode("utf-8"), settings.stats_username.encode("utf-8")
        )
        password_matches = secrets.compare_digest(
            password.encode("utf-8"), settings.stats_password.encode("utf-8")
        )
        if not (username_matches and password_matches):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={
                    "WWW-Authenticate": 'Basic realm="Installation statistics"',
                    "Cache-Control": "no-store",
                },
            )

    async def receive_ping(request: Request) -> Response:
        allowed, retry_after = request.app.state.ping_limiter.consume()
        if not allowed:
            return Response(status_code=429, headers={"Retry-After": str(retry_after)})

        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return Response(status_code=415)
        raw_length = request.headers.get("content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                return Response(status_code=400)
            if declared_length < 0:
                return Response(status_code=400)
            if declared_length > MAX_REQUEST_BYTES:
                return Response(status_code=413)

        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                    return Response(status_code=413)
                body.extend(chunk)
        except ClientDisconnect:
            return Response(status_code=400)
        try:
            submitted: object = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(status_code=400)
        payload = validate_payload(submitted)
        if payload is None:
            return JSONResponse({"detail": "Invalid telemetry payload"}, status_code=422)

        try:
            database: TelemetryDatabase = request.app.state.telemetry_database
            await database.upsert(payload, datetime.now(UTC))
        except DatabaseBusyError:
            return Response(status_code=503, headers={"Retry-After": "1"})
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Telemetry database write failed (%s)", type(exc).__name__)
            return Response(status_code=503)
        return Response(status_code=204)

    async def get_stats(request: Request) -> JSONResponse:
        try:
            database: TelemetryDatabase = request.app.state.telemetry_database
            result = await database.stats(datetime.now(UTC))
        except (DatabaseBusyError, OSError, sqlite3.Error) as exc:
            logger.warning("Telemetry database read failed (%s)", type(exc).__name__)
            return JSONResponse(
                {"detail": "Statistics are temporarily unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    async def summary_page(request: Request) -> HTMLResponse:
        try:
            database: TelemetryDatabase = request.app.state.telemetry_database
            result = await database.stats(datetime.now(UTC))
        except (DatabaseBusyError, OSError, sqlite3.Error) as exc:
            logger.warning("Telemetry database read failed (%s)", type(exc).__name__)
            return HTMLResponse(
                "<h1>Statistics are temporarily unavailable</h1>",
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return HTMLResponse(render_summary(result), headers={"Cache-Control": "no-store"})

    app.add_api_route(
        "/api/ping", receive_ping, methods=["POST"], status_code=204, response_class=Response
    )
    app.add_api_route(
        "/api/stats",
        get_stats,
        methods=["GET"],
        dependencies=[Depends(require_stats_auth)],
    )
    app.add_api_route(
        "/",
        summary_page,
        methods=["GET"],
        response_class=HTMLResponse,
        dependencies=[Depends(require_stats_auth)],
    )

    return app


async def _daily_maintenance(database: TelemetryDatabase) -> None:
    while True:
        now = datetime.now(UTC)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep(max(0.1, (next_midnight - now).total_seconds()))
        try:
            await database.collect_snapshot_and_cleanup(datetime.now(UTC))
        except asyncio.CancelledError:
            raise
        except (DatabaseBusyError, OSError, sqlite3.Error) as exc:
            logger.warning("Telemetry maintenance failed (%s)", type(exc).__name__)


def render_summary(stats: Mapping[str, Any]) -> str:
    """Render a local, escaped HTML summary without exposing IDs or payloads."""
    title = html.escape(str(stats.get("label", "Active reporting installations")))
    sample = html.escape(str(stats.get("sampled_at_utc", "")))
    page = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title><style>",
        ":root{color-scheme:light;--color-canvas:223 223 223;--color-surface:239 239 239;--color-line:192 192 192;--color-text:45 45 45;--color-muted:107 107 107;--color-accent:255 206 89;--radius-md:.75rem;--space-4:1rem;--space-8:2rem;--font-sans:-apple-system,BlinkMacSystemFont,'Inter','SF Pro Display',sans-serif}",
        "@media(prefers-color-scheme:dark){:root{color-scheme:dark;--color-canvas:15 18 22;--color-surface:20 25 31;--color-line:36 43 52;--color-text:230 233 239;--color-muted:166 176 191}}",
        "*{box-sizing:border-box}body{margin:0;background:rgb(var(--color-canvas));color:rgb(var(--color-text));font:15px/1.5 var(--font-sans)}",
        "main{max-width:1100px;margin:0 auto;padding:32px 20px}h1,h2{line-height:1.2}h1{font-size:1.7rem}h2{font-size:1.2rem;margin-top:28px}",
        ".muted{color:rgb(var(--color-muted))}.totals{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}",
        ".card{background:rgb(var(--color-surface));border:1px solid rgb(var(--color-line));border-radius:var(--radius-md);padding:var(--space-4);margin:10px 0}",
        ".count{display:block;color:rgb(var(--color-accent));font-size:2rem;font-weight:700}table{width:100%;border-collapse:collapse;margin-top:8px}",
        "th,td{text-align:left;padding:8px;border-bottom:1px solid rgb(var(--color-line));overflow-wrap:anywhere}th{color:rgb(var(--color-muted));font-size:.8rem}",
        "@media(max-width:600px){main{padding:22px 12px}td,th{padding:6px 4px;font-size:.82rem}}",
        "</style></head><body><main>",
        f"<h1>{title}</h1><p class=\"muted\">Execution mode reflects each installation's latest reported setting; older snapshots and unavailable settings are shown as unknown. Sampled at {sample} UTC; today's sample is partial.</p>",
        '<div class="totals">',
    ]
    for key, heading in (("active_7_days", "Last 7 days"), ("active_30_days", "Last 30 days")):
        window = _as_mapping(stats.get(key, {}))
        total = html.escape(str(window.get("total", 0))) if window is not None else "0"
        page.append(
            f'<section class="card"><h2>{heading}</h2><span class="count">{total}</span> active reporting installations'
        )
        breakdowns = _as_mapping(window.get("breakdowns", {})) if window is not None else None
        if breakdowns is not None:
            for field in (
                "version",
                "release_channel",
                "installation_type",
                "architecture",
                "inverter_profile",
                "execution_mode",
            ):
                values = _as_mapping(breakdowns.get(field, {}))
                page.append(
                    f"<h3>{html.escape(field.replace('_', ' ').title())}</h3><table><thead><tr><th>Value</th><th>Installations</th></tr></thead><tbody>"
                )
                if values:
                    for value, count in sorted(values.items(), key=lambda item: str(item[0])):
                        page.append(
                            f"<tr><td>{html.escape(str(value))}</td><td>{html.escape(str(count))}</td></tr>"
                        )
                else:
                    page.append('<tr><td colspan="2" class="muted">No reports</td></tr>')
                page.append("</tbody></table>")
        page.append("</section>")

    page.append("</div>")
    history = stats.get("history", [])
    page.append(
        '<section class="card"><h2>Daily aggregate history</h2><p class="muted">Gaps represent days when the receiver was unavailable.</p><table><thead><tr><th>UTC sample date</th><th>Sample time</th><th>7-day active</th><th>30-day active</th></tr></thead><tbody>'
    )
    history_rows = cast("list[object]", history) if isinstance(history, list) else []
    if history_rows:
        for history_row in history_rows:
            row = _as_mapping(history_row)
            if row is None:
                continue
            active_7 = _as_mapping(row.get("active_7_days", {}))
            active_30 = _as_mapping(row.get("active_30_days", {}))
            total_7 = active_7.get("total", 0) if active_7 is not None else 0
            total_30 = active_30.get("total", 0) if active_30 is not None else 0
            page.append(
                "<tr><td>"
                + html.escape(str(row.get("sample_date_utc", "")))
                + "</td><td>"
                + html.escape(str(row.get("sampled_at_utc", "")))
                + "</td><td>"
                + html.escape(str(total_7))
                + "</td><td>"
                + html.escape(str(total_30))
                + "</td></tr>"
            )
    else:
        page.append('<tr><td colspan="4" class="muted">No aggregate history yet</td></tr>')
    page.append("</tbody></table></section></main></body></html>")
    return "".join(page)


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)


app = create_app()
