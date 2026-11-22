"""Plan archive endpoints: summary, download, clear."""

import asyncio
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers import debug as debug_router
from backend.middleware.fetch_site import FetchSiteGuard
from backend.services import plan_archive

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def archive_dir(tmp_path, monkeypatch) -> Path:
    directory = tmp_path / "plan_archive"
    monkeypatch.setattr(plan_archive, "ARCHIVE_DIR", directory)
    monkeypatch.setattr(debug_router, "load_yaml", lambda path: {})
    return directory


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(debug_router.router)
    return application


@pytest.fixture
def client(app, archive_dir) -> TestClient:
    return TestClient(app)


def _record(directory: Path, moment: datetime, outcome: str = "ok", payload: bytes = b"x") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{outcome}.json.gz"
    path.write_bytes(payload)
    return path


def test_summary_without_files(client):
    body = client.get("/api/debug/plan-archive").json()
    assert body == {
        "enabled": True,
        "retention_days": 60,
        "count": 0,
        "total_bytes": 0,
        "oldest": None,
        "newest": None,
    }


def test_summary_with_files(client, archive_dir, monkeypatch):
    monkeypatch.setattr(
        debug_router,
        "load_yaml",
        lambda path: {"debug": {"plan_archive_enabled": False, "plan_archive_retention_days": 14}},
    )
    older = NOW - timedelta(days=2)
    _record(archive_dir, older, payload=b"abc")
    _record(archive_dir, NOW, "err", payload=b"de")

    body = client.get("/api/debug/plan-archive").json()

    assert body["enabled"] is False
    assert body["retention_days"] == 14
    assert body["count"] == 2
    assert body["total_bytes"] == 5
    assert body["oldest"] == older.isoformat()
    assert body["newest"] == NOW.isoformat()


def test_download_content_and_filename(client, archive_dir):
    path = _record(archive_dir, NOW, payload=b"payload")

    response = client.get("/api/debug/plan-archive/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert "darkstar-plan-archive-" in disposition
    assert disposition.endswith('.zip"')
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert set(bundle.namelist()) == {path.name, "manifest.json"}
        assert bundle.read(path.name) == b"payload"


def test_download_days_filter(client, archive_dir):
    _record(archive_dir, NOW - timedelta(days=3))
    recent = _record(archive_dir, NOW - timedelta(hours=1))

    response = client.get("/api/debug/plan-archive/download", params={"days": 1})

    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert set(bundle.namelist()) == {recent.name, "manifest.json"}


def test_download_empty_archive_is_404(client):
    response = client.get("/api/debug/plan-archive/download")
    assert response.status_code == 404
    assert "no records" in response.json()["detail"]


@pytest.mark.parametrize("days", [0, 366])
def test_download_rejects_invalid_days(client, archive_dir, days):
    _record(archive_dir, NOW)
    assert client.get("/api/debug/plan-archive/download", params={"days": days}).status_code == 422


def test_download_temp_file_removed_afterwards(client, archive_dir):
    path = _record(archive_dir, NOW)
    client.get("/api/debug/plan-archive/download")
    assert [f.name for f in archive_dir.iterdir()] == [path.name]


def test_download_while_locked_is_409(client, archive_dir, monkeypatch):
    _record(archive_dir, NOW)
    busy = asyncio.Lock()
    asyncio.run(busy.acquire())  # a lock is only a flag here: no loop affinity until contended
    monkeypatch.setattr(debug_router, "_plan_archive_download_lock", busy)

    response = client.get("/api/debug/plan-archive/download")

    assert response.status_code == 409
    busy.release()
    assert client.get("/api/debug/plan-archive/download").status_code == 200


def test_delete_removes_only_archive_records(client, archive_dir):
    _record(archive_dir, NOW)
    _record(archive_dir, NOW - timedelta(days=1), "err")
    other = archive_dir / "notes.txt"
    other.write_text("keep")

    response = client.delete("/api/debug/plan-archive")

    assert response.json() == {"deleted": 2}
    assert [f.name for f in archive_dir.iterdir()] == ["notes.txt"]
    assert client.get("/api/debug/plan-archive").json()["count"] == 0


def test_cross_site_delete_is_rejected(app, archive_dir):
    path = _record(archive_dir, NOW)
    guarded = TestClient(FetchSiteGuard(app))

    response = guarded.delete("/api/debug/plan-archive", headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 403
    assert path.exists()
