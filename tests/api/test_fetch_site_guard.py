"""Cross-site write protection: FetchSiteGuard unit tests and app-level integration tests."""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.types import Message, Scope
from starlette.websockets import WebSocketDisconnect

from backend.middleware.fetch_site import FetchSiteGuard

sys.path.append(str(Path.cwd()))

WRITE_METHODS = ["POST", "PUT", "PATCH", "DELETE"]
SAFE_METHODS = ["GET", "HEAD", "OPTIONS"]
BLOCKED = ["cross-site", "same-site", "Cross-Site", "SAME-SITE"]
ALLOWED = ["same-origin", "none", "Same-Origin", None]


async def _inner(scope: Scope, receive: Any, send: Any) -> None:
    """Inner ASGI app recording that it was reached."""
    scope["reached"] = True
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    elif scope["type"] == "websocket":
        await receive()
        await send({"type": "websocket.accept"})
    elif scope["type"] == "lifespan":
        await receive()
        await send({"type": "lifespan.startup.complete"})


async def _run(scope: Scope, incoming: list[Message]) -> list[Message]:
    queue = list(incoming)
    sent: list[Message] = []

    async def receive() -> Message:
        return queue.pop(0) if queue else {"type": "websocket.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    await FetchSiteGuard(_inner)(scope, receive, send)
    return sent


def _http_scope(method: str, site: str | None) -> dict[str, Any]:
    headers = [(b"origin", b"https://evil.example")]
    if site is not None:
        headers.append((b"sec-fetch-site", site.encode()))
    return {"type": "http", "method": method, "path": "/api/x", "headers": headers}


def _ws_scope(site: str | None, extensions: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = [] if site is None else [(b"sec-fetch-site", site.encode())]
    return {
        "type": "websocket",
        "path": "/socket.io/",
        "headers": headers,
        "extensions": extensions or {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("method", WRITE_METHODS)
@pytest.mark.parametrize("site", BLOCKED)
async def test_http_write_blocked(method: str, site: str):
    scope = _http_scope(method, site)
    sent = await _run(scope, [])
    assert sent[0]["status"] == 403
    assert json.loads(sent[1]["body"]) == {"detail": "Cross-site request blocked"}
    assert "reached" not in scope


@pytest.mark.asyncio
@pytest.mark.parametrize("method", WRITE_METHODS)
@pytest.mark.parametrize("site", ALLOWED)
async def test_http_write_allowed(method: str, site: str | None):
    scope = _http_scope(method, site)
    sent = await _run(scope, [])
    assert sent[0]["status"] == 200
    assert scope["reached"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("method", SAFE_METHODS)
@pytest.mark.parametrize("site", BLOCKED + ALLOWED)
async def test_http_safe_methods_always_pass(method: str, site: str | None):
    scope = _http_scope(method, site)
    sent = await _run(scope, [])
    assert sent[0]["status"] == 200
    assert scope["reached"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("site", BLOCKED)
async def test_websocket_blocked_closes_with_policy_violation(site: str):
    scope = _ws_scope(site)
    sent = await _run(scope, [{"type": "websocket.connect"}])
    assert sent == [{"type": "websocket.close", "code": 1008}]
    assert "reached" not in scope


@pytest.mark.asyncio
async def test_websocket_blocked_uses_http_denial_when_supported():
    scope = _ws_scope("cross-site", {"websocket.http.response": {}})
    sent = await _run(scope, [{"type": "websocket.connect"}])
    assert sent[0]["type"] == "websocket.http.response.start"
    assert sent[0]["status"] == 403
    assert "reached" not in scope


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ALLOWED)
async def test_websocket_allowed(site: str | None):
    scope = _ws_scope(site)
    sent = await _run(scope, [{"type": "websocket.connect"}])
    assert sent == [{"type": "websocket.accept"}]
    assert scope["reached"] is True


@pytest.mark.asyncio
async def test_lifespan_passes_through():
    scope: dict[str, Any] = {"type": "lifespan", "headers": []}
    sent = await _run(scope, [{"type": "lifespan.startup"}])
    assert sent == [{"type": "lifespan.startup.complete"}]
    assert scope["reached"] is True


def test_other_asgi_app_delegates():
    inner = MagicMock(other_asgi_app="fastapi-app")
    assert FetchSiteGuard(inner).other_asgi_app == "fastapi-app"


# ---------------------------------------------------------------------------
# Integration: real app
# ---------------------------------------------------------------------------


@pytest.fixture
def wrapped_app():
    from backend.main import create_app

    return create_app()


@pytest.fixture
def client(wrapped_app: Any):
    """TestClient against the guarded outermost app (same stack uvicorn serves)."""
    with (
        patch(
            "backend.main.LearningStore",
            return_value=MagicMock(ensure_wal_mode=AsyncMock(), close=AsyncMock()),
        ),
        TestClient(wrapped_app) as test_client,
    ):
        yield test_client


def test_create_app_exposes_fastapi_app(wrapped_app: Any):
    from fastapi import FastAPI

    assert isinstance(wrapped_app, FetchSiteGuard)
    assert isinstance(wrapped_app.other_asgi_app, FastAPI)


EXECUTOR_PAYLOAD = {"enabled": True, "interval_seconds": 120}
CONFIG_TEXT = "executor:\n  enabled: false\n  interval_seconds: 60\n"


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return path


def _fake_update_config(path: Path, mutate: Any, *args: Any, **kwargs: Any) -> bool:
    """Apply the mutator to the YAML file without full-config schema validation."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return True


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_cross_site_executor_config_put_blocked_and_config_unchanged(
    client: TestClient, config_file: Path, site: str
):
    with (
        patch("backend.api.routers.executor.update_config", side_effect=_fake_update_config),
        patch("backend.api.routers.executor.get_executor_instance", return_value=None),
    ):
        response = client.put(
            "/api/executor/config",
            json=EXECUTOR_PAYLOAD,
            headers={"Sec-Fetch-Site": site, "Origin": "https://evil.example"},
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site request blocked"}
    assert config_file.read_text(encoding="utf-8") == CONFIG_TEXT


@pytest.mark.parametrize(
    "headers", [{"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {}]
)
def test_same_origin_and_headerless_executor_config_put_succeeds(
    client: TestClient, config_file: Path, headers: dict[str, str]
):
    with (
        patch("backend.api.routers.executor.update_config", side_effect=_fake_update_config),
        patch("backend.api.routers.executor.get_executor_instance", return_value=None),
    ):
        response = client.put("/api/executor/config", json=EXECUTOR_PAYLOAD, headers=headers)
    assert response.status_code == 200
    assert "interval_seconds: 120" in config_file.read_text(encoding="utf-8")


def test_executor_config_invalid_json_returns_422(client: TestClient, config_file: Path):
    response = client.put(
        "/api/executor/config",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert config_file.read_text(encoding="utf-8") == CONFIG_TEXT


def test_executor_notifications_typed_body(client: TestClient, config_file: Path):
    with (
        patch("backend.api.routers.executor.update_config", side_effect=_fake_update_config),
        patch("backend.api.routers.executor.get_executor_instance", return_value=None),
    ):
        ok = client.post("/api/executor/notifications", json={"on_error": True})
        bad = client.post(
            "/api/executor/notifications",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
    assert ok.status_code == 200
    assert "on_error: true" in config_file.read_text(encoding="utf-8")
    assert bad.status_code == 422


def test_briefing_typed_body(client: TestClient):
    with (
        patch("backend.api.routers.forecast._get_engine_and_config", return_value=(None, {})),
        patch("backend.api.routers.forecast.load_yaml", return_value={}),
        patch(
            "backend.api.routers.forecast.get_aurora_briefing_text", return_value="hello"
        ) as briefing,
    ):
        ok = client.post("/api/aurora/briefing", json={"a": 1})
        bad = client.post(
            "/api/aurora/briefing",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
    assert ok.status_code == 200
    assert ok.json() == {"briefing": "hello"}
    assert briefing.call_args.args[0] == {"a": 1}
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/health"),
        ("OPTIONS", "/api/health"),
        ("OPTIONS", "/api/executor/config"),
        ("PUT", "/api/executor/config"),
        ("GET", "/socket.io/?EIO=4&transport=polling"),
        ("OPTIONS", "/socket.io/?EIO=4&transport=polling"),
    ],
)
def test_no_response_carries_access_control_allow_origin(
    client: TestClient, method: str, path: str
):
    response = client.request(
        method,
        path,
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "PUT",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_socketio_cors_disabled_and_reported_by_debug(client: TestClient):
    from backend.core.websockets import ws_manager

    eio: Any = ws_manager.sio.eio  # type: ignore[attr-defined]
    assert eio.cors_allowed_origins == []  # pyright: ignore[reportUnknownMemberType]
    response = client.get("/api/socketio-debug")
    assert response.status_code == 200
    assert response.json()["cors_allowed_origins"] == []


SOCKETIO_WS = "/socket.io/?EIO=4&transport=websocket"


def test_socketio_cross_site_handshake_refused(client: TestClient):
    for site in ("cross-site", "same-site"):
        with (
            pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)),
            client.websocket_connect(
                SOCKETIO_WS, headers={"Sec-Fetch-Site": site, "Upgrade": "websocket"}
            ),
        ):
            pass


def test_socketio_same_origin_handshake_accepted(client: TestClient):
    # Starlette's test client omits the Upgrade header that engine.io requires.
    headers = {"Sec-Fetch-Site": "same-origin", "Upgrade": "websocket"}
    with client.websocket_connect(SOCKETIO_WS, headers=headers) as ws:
        opening = ws.receive_text()
    assert opening.startswith("0{")
    assert '"sid"' in opening


def test_socketio_polling_write_cross_site_blocked(client: TestClient):
    response = client.post(
        "/socket.io/?EIO=4&transport=polling&sid=x",
        content=b"40",
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403
