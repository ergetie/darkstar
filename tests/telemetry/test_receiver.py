from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from telemetry_receiver.app import ReceiverSettings, create_app
from telemetry_receiver.database import DatabaseBusyError, TelemetryDatabase

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)


def make_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "installation_id": str(uuid.uuid4()),
        "version": "2.8.0",
        "release_channel": "stable",
        "installation_type": "ha_addon",
        "architecture": "aarch64",
        "inverter_profile": "deye",
        "execution_mode": "unknown",
    }
    payload.update(overrides)
    return payload


def auth_header(username: str = "operator", password: str = "long-secret") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def receiver(tmp_path: Path):
    settings = ReceiverSettings(tmp_path / "receiver.sqlite3", "operator", "long-secret")
    app = create_app(settings_loader=lambda: settings)
    with TestClient(app) as client:
        yield client, app, settings


def test_public_ingestion_deduplicates_and_protected_stats_are_no_store(receiver: Any) -> None:
    client, _, _ = receiver
    payload = make_payload()

    first = client.post("/api/ping", json=payload)
    updated = client.post("/api/ping", json={**payload, "version": "2.8.1"})

    assert first.status_code == updated.status_code == 204
    assert first.content == updated.content == b""
    assert client.get("/api/stats").status_code == 401
    summary = client.get("/", headers=auth_header())
    stats = client.get("/api/stats", headers=auth_header())
    assert summary.status_code == stats.status_code == 200
    assert summary.headers["cache-control"] == "no-store"
    assert stats.headers["cache-control"] == "no-store"
    body = stats.json()
    assert body["active_7_days"]["total"] == 1
    assert body["active_7_days"]["breakdowns"]["version"] == {"2.8.1": 1}
    assert body["active_7_days"]["breakdowns"]["execution_mode"] == {"unknown": 1}
    assert payload["installation_id"] not in stats.text
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_equivalent_uuid_spellings_update_one_installation(receiver: Any) -> None:
    client, _, settings = receiver
    payload = make_payload()
    identifier = uuid.UUID(payload["installation_id"])
    for spelling in (str(identifier), str(identifier).upper(), identifier.hex, identifier.urn):
        assert (
            client.post("/api/ping", json={**payload, "installation_id": spelling}).status_code
            == 204
        )
    assert client.get("/api/stats", headers=auth_header()).json()["active_7_days"]["total"] == 1
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT installation_id FROM installations").fetchall() == [
            (str(identifier),)
        ]


def test_invalid_payloads_do_not_mutate_database(receiver: Any) -> None:
    client, _, _ = receiver
    payload = make_payload()
    invalid_payloads = [
        {**payload, "timestamp": "client supplied"},
        {**payload, "installation_id": "not-a-uuid"},
        {**payload, "inverter_profile": "private-custom-name"},
        {**payload, "version": "v" * 129},
        {**payload, "version": ""},
        {**payload, "installation_id": str(uuid.uuid1())},
        {**payload, "release_channel": "beta"},
        {**payload, "installation_type": "source"},
        {**payload, "architecture": "x86_64"},
        {**payload, "version": 28},
        {**payload, "execution_mode": "LIVE"},
    ]
    for item in invalid_payloads:
        assert client.post("/api/ping", json=item).status_code == 422
    stats = client.get("/api/stats", headers=auth_header()).json()
    assert stats["active_7_days"]["total"] == 0


def test_legacy_payload_defaults_to_unknown_and_current_payload_requires_valid_mode(
    receiver: Any,
) -> None:
    client, _, _ = receiver
    legacy_payload = make_payload()
    legacy_payload.pop("execution_mode")
    current_payload = make_payload(execution_mode="live")
    invalid_payload = make_payload(execution_mode="executing")

    assert client.post("/api/ping", json=legacy_payload).status_code == 204
    assert client.post("/api/ping", json=current_payload).status_code == 204
    assert client.post("/api/ping", json=invalid_payload).status_code == 422
    stats = client.get("/api/stats", headers=auth_header()).json()
    assert stats["active_7_days"]["total"] == 2
    assert stats["active_7_days"]["breakdowns"]["execution_mode"] == {
        "live": 1,
        "unknown": 1,
    }


def test_same_installation_can_change_mode_without_increasing_counts(receiver: Any) -> None:
    client, _, settings = receiver
    payload = make_payload(execution_mode="shadow")
    assert client.post("/api/ping", json=payload).status_code == 204
    assert client.post("/api/ping", json={**payload, "execution_mode": "live"}).status_code == 204

    stats = client.get("/api/stats", headers=auth_header()).json()
    assert stats["active_7_days"]["total"] == 1
    assert stats["active_30_days"]["total"] == 1
    assert stats["active_7_days"]["breakdowns"]["execution_mode"] == {"live": 1}
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM installations").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_cancelled_database_call_keeps_slot_until_worker_finishes(tmp_path: Path) -> None:
    database = TelemetryDatabase(tmp_path / "bounded.sqlite3")
    database._slots = asyncio.Semaphore(1)
    started = threading.Event()
    release = threading.Event()

    def blocked_operation() -> None:
        started.set()
        assert release.wait(timeout=3)

    caller = asyncio.create_task(database.run(blocked_operation))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        with pytest.raises(DatabaseBusyError):
            await database.run(lambda: None)
    finally:
        release.set()
    await database.run(lambda: None)


def test_concurrent_write_does_not_change_statistics_read_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = TelemetryDatabase(tmp_path / "consistent.sqlite3")
    database._initialize_sync()
    first = make_payload(version="before")
    database._upsert_sync(first, NOW)
    original_window = database._window
    written = False

    def window_with_concurrent_write(
        connection: sqlite3.Connection, as_of: datetime, days: int
    ) -> dict[str, object]:
        nonlocal written
        result = original_window(connection, as_of, days)
        if not written:
            written = True
            database._upsert_sync(make_payload(version="after"), NOW)
        return result

    monkeypatch.setattr(database, "_window", window_with_concurrent_write)
    stats = database._stats_sync(NOW)
    assert stats["active_7_days"]["total"] == stats["active_30_days"]["total"] == 1
    assert stats["active_30_days"]["breakdowns"]["version"] == {"before": 1}


def test_body_limit_applies_with_and_without_content_length(receiver: Any) -> None:
    client, _, _ = receiver
    headers = {"content-type": "application/json"}
    with_length = client.post("/api/ping", content=b" " * 2049, headers=headers)

    def oversized_chunks():
        yield b'{"version":"'
        yield b"x" * 2048

    streamed = client.post("/api/ping", content=oversized_chunks(), headers=headers)

    assert with_length.status_code == 413
    assert streamed.status_code == 413
    stats = client.get("/api/stats", headers=auth_header()).json()
    assert stats["active_7_days"]["total"] == 0


def test_global_rate_limit_returns_retry_after_before_sqlite_write(receiver: Any) -> None:
    client, app, settings = receiver
    limiter = app.state.ping_limiter
    limiter._tokens = 0
    limiter._updated_at = time.monotonic()

    response = client.post("/api/ping", json=make_payload())

    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    stats = client.get("/api/stats", headers=auth_header()).json()
    assert stats["active_7_days"]["total"] == 0
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM installations").fetchone()[0] == 0


def test_stats_auth_is_generic_and_missing_credentials_fail_closed(
    receiver: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = receiver
    missing = client.get("/")
    wrong = client.get("/api/stats", headers=auth_header("wrong", "wrong"))
    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["www-authenticate"].startswith("Basic ")
    assert missing.json() == wrong.json() == {"detail": "Unauthorized"}
    assert missing.headers["cache-control"] == "no-store"
    assert wrong.headers["cache-control"] == "no-store"

    monkeypatch.delenv("TELEMETRY_STATS_USERNAME", raising=False)
    monkeypatch.delenv("TELEMETRY_STATS_PASSWORD", raising=False)
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(tmp_path / "private.sqlite3"))
    app = create_app()
    with pytest.raises(RuntimeError, match="must be configured"), TestClient(app):
        pass


def test_html_escapes_metadata_and_contains_no_installation_ids(receiver: Any) -> None:
    client, _, _ = receiver
    payload = make_payload(version="<script>alert(1)</script>")
    assert client.post("/api/ping", json=payload).status_code == 204

    page = client.get("/", headers=auth_header())

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "Execution Mode" in page.text
    assert "unknown" in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert payload["installation_id"] not in page.text


def test_database_failures_return_service_unavailable_and_restart_is_durable(
    receiver: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app, settings = receiver
    database = app.state.telemetry_database

    async def fail_write(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("synthetic failure")

    monkeypatch.setattr(database, "upsert", fail_write)
    failure = client.post("/api/ping", json=make_payload())
    assert failure.status_code == 503

    monkeypatch.undo()
    payload = make_payload()
    assert client.post("/api/ping", json=payload).status_code == 204
    client.close()

    restarted = create_app(settings_loader=lambda: settings)
    with TestClient(restarted) as new_client:
        stats = new_client.get("/api/stats", headers=auth_header()).json()
    assert stats["active_7_days"]["total"] == 1


def test_database_windows_include_exact_boundaries_and_breakdowns_sum(tmp_path: Path) -> None:
    database = TelemetryDatabase(tmp_path / "bounds.sqlite3")

    async def scenario() -> dict[str, object]:
        await database.initialize()
        observations = (
            (7, "v7", "shadow"),
            (10, "v10", "live"),
            (30, "v30", "unknown"),
            (30, "old", "shadow"),
        )
        for days, version, execution_mode in observations:
            offset = timedelta(days=days) + (
                timedelta(microseconds=1) if version == "old" else timedelta()
            )
            await database.upsert(
                make_payload(version=version, execution_mode=execution_mode),
                NOW - offset,
            )
        return await database.stats(NOW)

    stats = asyncio.run(scenario())
    window_7 = stats["active_7_days"]
    window_30 = stats["active_30_days"]
    assert window_7["total"] == 1
    assert window_30["total"] == 3
    assert window_7["breakdowns"]["execution_mode"] == {"shadow": 1}
    assert window_30["breakdowns"]["execution_mode"] == {
        "live": 1,
        "shadow": 1,
        "unknown": 1,
    }
    for window in (window_7, window_30):
        total = window["total"]
        for breakdown in window["breakdowns"].values():
            assert sum(breakdown.values()) == total


def test_out_of_order_database_workers_preserve_latest_observation(tmp_path: Path) -> None:
    database = TelemetryDatabase(tmp_path / "latest.sqlite3")
    database._initialize_sync()
    payload = make_payload(version="new")
    database._upsert_sync(payload, NOW)
    database._upsert_sync({**payload, "version": "old"}, NOW - timedelta(seconds=1))
    stats = database._stats_sync(NOW)
    assert stats["active_7_days"]["breakdowns"]["version"] == {"new": 1}
    with sqlite3.connect(database.path) as connection:
        row = connection.execute("SELECT last_seen_utc FROM installations").fetchone()
    assert datetime.fromisoformat(row[0]) == NOW


def test_cleanup_boundary_snapshots_keep_history_gaps_and_contain_no_ids(tmp_path: Path) -> None:
    database_path = tmp_path / "retention.sqlite3"
    database = TelemetryDatabase(database_path)
    exact_60 = make_payload()
    stale = make_payload()
    jan_1 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    jan_3 = datetime(2026, 1, 3, 12, tzinfo=UTC)

    async def scenario() -> dict[str, object]:
        await database.initialize()
        await database.upsert(exact_60, jan_3 - timedelta(days=60))
        await database.upsert(stale, jan_3 - timedelta(days=60, microseconds=1))
        await database.collect_snapshot_and_cleanup(jan_1)
        await database.collect_snapshot_and_cleanup(jan_1 + timedelta(hours=1))
        await database.collect_snapshot_and_cleanup(jan_3)
        return await database.stats(jan_3)

    stats = asyncio.run(scenario())
    with sqlite3.connect(database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM installations").fetchone()[0]
        snapshot_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(daily_snapshots)").fetchall()
        }
    history = stats["history"]
    assert count == 1
    assert [row["sample_date_utc"] for row in history] == ["2026-01-01", "2026-01-03"]
    assert exact_60["installation_id"] not in str(history)
    assert stale["installation_id"] not in str(history)
    assert "installation_id" not in snapshot_columns


def test_new_snapshots_include_execution_mode_breakdowns(tmp_path: Path) -> None:
    database = TelemetryDatabase(tmp_path / "mode-snapshots.sqlite3")

    async def scenario() -> dict[str, object]:
        await database.initialize()
        await database.upsert(make_payload(execution_mode="shadow"), NOW)
        await database.upsert(make_payload(execution_mode="live"), NOW)
        await database.collect_snapshot_and_cleanup(NOW)
        return await database.stats(NOW)

    stats = asyncio.run(scenario())
    history = stats["history"]
    assert history[0]["active_7_days"]["breakdowns"]["execution_mode"] == {
        "live": 1,
        "shadow": 1,
    }
    assert history[0]["active_30_days"]["breakdowns"]["execution_mode"] == {
        "live": 1,
        "shadow": 1,
    }


def test_original_sqlite_schema_migrates_additively_and_idempotently(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    first_seen = (NOW - timedelta(days=1)).isoformat(timespec="microseconds")
    second_seen = (NOW - timedelta(days=10)).isoformat(timespec="microseconds")
    breakdowns_7 = {
        "version": {"old-7": 1},
        "release_channel": {"stable": 1},
        "installation_type": {"docker": 1},
        "architecture": {"amd64": 1},
        "inverter_profile": {"generic": 1},
    }
    breakdowns_30 = {
        "version": {"old-7": 1, "old-30": 1},
        "release_channel": {"stable": 2},
        "installation_type": {"docker": 2},
        "architecture": {"amd64": 2},
        "inverter_profile": {"generic": 2},
    }
    snapshot_date = "2026-05-30"
    snapshot_time = "2026-05-30T12:00:00.000000+00:00"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE installations (
                installation_id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                release_channel TEXT NOT NULL,
                installation_type TEXT NOT NULL,
                architecture TEXT NOT NULL,
                inverter_profile TEXT NOT NULL,
                last_seen_utc TEXT NOT NULL
            );
            CREATE INDEX idx_installations_last_seen ON installations(last_seen_utc);
            CREATE TABLE daily_snapshots (
                sample_date_utc TEXT PRIMARY KEY,
                sampled_at_utc TEXT NOT NULL,
                active_7_days INTEGER NOT NULL,
                active_30_days INTEGER NOT NULL,
                breakdowns_7_days_json TEXT NOT NULL,
                breakdowns_30_days_json TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO installations VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (first_id, "old-7", "stable", "docker", "amd64", "generic", first_seen),
                (second_id, "old-30", "stable", "docker", "amd64", "generic", second_seen),
            ],
        )
        connection.execute(
            """
            INSERT INTO daily_snapshots VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_date,
                snapshot_time,
                1,
                2,
                json.dumps(breakdowns_7, separators=(",", ":")),
                json.dumps(breakdowns_30, separators=(",", ":")),
            ),
        )
        original_snapshot = connection.execute(
            "SELECT * FROM daily_snapshots WHERE sample_date_utc = ?", (snapshot_date,)
        ).fetchone()

    database = TelemetryDatabase(database_path)
    database._initialize_sync()
    migrated_stats = database._stats_sync(NOW)
    with sqlite3.connect(database_path) as connection:
        observations = connection.execute(
            "SELECT installation_id, version, last_seen_utc, execution_mode "
            "FROM installations ORDER BY version"
        ).fetchall()
        migrated_snapshot = connection.execute(
            "SELECT sample_date_utc, sampled_at_utc, active_7_days, active_30_days, "
            "breakdowns_7_days_json, breakdowns_30_days_json, "
            "execution_modes_7_days_json, execution_modes_30_days_json "
            "FROM daily_snapshots WHERE sample_date_utc = ?",
            (snapshot_date,),
        ).fetchone()

    assert observations == [
        (second_id, "old-30", second_seen, "unknown"),
        (first_id, "old-7", first_seen, "unknown"),
    ]
    assert migrated_snapshot[:6] == original_snapshot
    assert json.loads(migrated_snapshot[6]) == {"unknown": 1}
    assert json.loads(migrated_snapshot[7]) == {"unknown": 2}
    assert migrated_stats["history"][0]["active_7_days"]["breakdowns"]["execution_mode"] == {
        "unknown": 1
    }
    assert migrated_stats["history"][0]["active_30_days"]["breakdowns"]["execution_mode"] == {
        "unknown": 2
    }

    database._initialize_sync()
    repeated_stats = database._stats_sync(NOW)
    assert repeated_stats["history"] == migrated_stats["history"]


def test_logs_and_storage_do_not_retain_request_headers_or_credentials(
    receiver: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, _, settings = receiver
    secret_ip = "203.0.113.123"
    secret_agent = "private-test-agent"
    secret_password = "long-secret"
    payload = make_payload()
    assert (
        client.post(
            "/api/ping",
            json=payload,
            headers={"user-agent": secret_agent, "x-forwarded-for": secret_ip},
        ).status_code
        == 204
    )
    assert (
        client.get("/api/stats", headers=auth_header(password=secret_password)).status_code == 200
    )

    with sqlite3.connect(settings.database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(installations)").fetchall()
        }
    assert columns == {
        "installation_id",
        "version",
        "release_channel",
        "installation_type",
        "architecture",
        "inverter_profile",
        "execution_mode",
        "last_seen_utc",
    }
    assert secret_ip not in caplog.text
    assert secret_agent not in caplog.text
    assert secret_password not in caplog.text
