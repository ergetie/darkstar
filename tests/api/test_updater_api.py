"""Updater proxy router tests with a fake updater client (no network, no docker)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers.updater import router
from backend.services.updater_client import UpdaterUnavailableError, get_updater_client


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []
        self.responses: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
        self.down = False

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        self.calls.append((method, path, json, params))
        if self.down:
            raise UpdaterUnavailableError("connection refused")
        return self.responses.get((method, path), (200, {}))


@pytest.fixture
def fake() -> FakeClient:
    return FakeClient()


@pytest.fixture
def client(fake: FakeClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DARKSTAR_INSTALLATION_TYPE", "docker")
    monkeypatch.setenv("DARKSTAR_UPDATER_URL", "http://updater:5001")
    monkeypatch.setenv("DARKSTAR_UPDATER_TOKEN", "secret")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_updater_client] = lambda: fake
    return TestClient(app)


def test_status_proxied(client: TestClient, fake: FakeClient) -> None:
    fake.responses[("GET", "/status")] = (200, {"channel": "dev", "update_available": True})
    data = client.get("/api/updater/status").json()
    assert data == {"reachable": True, "channel": "dev", "update_available": True}


def test_status_unavailable_is_explained_not_hidden(client: TestClient, fake: FakeClient) -> None:
    fake.down = True
    response = client.get("/api/updater/status")
    assert response.status_code == 200
    assert response.json() == {"reachable": False, "error": "connection refused"}
    assert client.post("/api/updater/check").json()["reachable"] is False


def test_channel_validated_and_proxied(client: TestClient, fake: FakeClient) -> None:
    assert client.put("/api/updater/channel", json={"channel": "evil"}).status_code == 422
    assert fake.calls == []
    assert client.put("/api/updater/channel", json={"channel": "stable"}).status_code == 200
    assert fake.calls == [("PUT", "/channel", {"channel": "stable"}, None)]


def test_apply_proxies_rejection_details(client: TestClient, fake: FakeClient) -> None:
    fake.responses[("POST", "/apply")] = (409, {"error": "dirty", "files": ["VERSION"]})
    response = client.post("/api/updater/apply")
    assert response.status_code == 409
    assert response.json()["detail"] == {"error": "dirty", "files": ["VERSION"]}
    fake.down = True
    assert client.post("/api/updater/apply").status_code == 503


def test_log_offset_forwarded(client: TestClient, fake: FakeClient) -> None:
    fake.responses[("GET", "/log")] = (200, {"text": "x", "offset": 1})
    assert client.get("/api/updater/log?offset=7").json() == {"text": "x", "offset": 1}
    assert fake.calls[-1][3] == {"offset": 7}
    assert client.get("/api/updater/log?offset=-1").status_code == 422


@pytest.mark.parametrize(
    ("install_type", "url"),
    [("ha_addon", "http://updater:5001"), ("docker", ""), ("unknown", "http://updater:5001")],
)
def test_hidden_unless_docker_and_configured(
    client: TestClient,
    fake: FakeClient,
    monkeypatch: pytest.MonkeyPatch,
    install_type: str,
    url: str,
) -> None:
    monkeypatch.setenv("DARKSTAR_INSTALLATION_TYPE", install_type)
    monkeypatch.setenv("DARKSTAR_UPDATER_URL", url)
    for method, path in [
        ("get", "/status"),
        ("post", "/check"),
        ("post", "/apply"),
        ("get", "/log"),
    ]:
        assert getattr(client, method)(f"/api/updater{path}").status_code == 404
    assert fake.calls == []


def test_hidden_without_token(
    client: TestClient, fake: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DARKSTAR_UPDATER_TOKEN")
    assert client.get("/api/updater/status").status_code == 404
    assert fake.calls == []
