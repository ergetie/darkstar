"""Smoke tests for all API endpoints relocated from services.py.

Each test verifies the endpoint is reachable and returns a non-500 response
with dependencies mocked. These are NOT functional tests — they verify
the wiring (route registration, imports, basic error handling) is correct.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import create_app

    mock_result = MagicMock()
    mock_result.fetchone.return_value = None

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_store = MagicMock()
    mock_store.AsyncSession.return_value = mock_session_ctx
    mock_store.ensure_wal_mode = AsyncMock()
    mock_store.close = AsyncMock()

    app = create_app()
    fastapi_app = app.other_asgi_app if hasattr(app, "other_asgi_app") else app
    with (
        patch("backend.main.LearningStore", return_value=mock_store),
        TestClient(fastapi_app) as c,
    ):
        yield c


def test_smoke_ha_entity(client):
    with patch(
        "backend.core.ha_client.get_ha_entity_state",
        new_callable=AsyncMock,
        return_value={"entity_id": "sensor.test", "state": "1.0"},
    ):
        resp = client.get("/api/ha/entity/sensor.test")
    assert resp.status_code != 500


def test_smoke_ha_average(client):
    with (
        patch(
            "backend.api.routers.ha._fetch_ha_history_avg",
            new_callable=AsyncMock,
            return_value=42.0,
        ),
        patch("backend.core.cache.cache") as mock_cache,
    ):
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock(return_value=None)
        resp = client.get("/api/ha/average?entity_id=sensor.test&hours=1")
    assert resp.status_code != 500


def test_smoke_ha_entities(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"entity_id": "sensor.test", "attributes": {"friendly_name": "Test"}}
    ]
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with (
        patch(
            "backend.core.secrets.load_home_assistant_config",
            return_value={"url": "http://test:8123", "token": "test"},
        ),
        patch("httpx.AsyncClient", return_value=mock_ctx),
    ):
        resp = client.get("/api/ha/entities")
    assert resp.status_code != 500


def test_smoke_ha_services(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"domain": "light", "services": {"turn_on": {}}}]
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with (
        patch(
            "backend.core.secrets.load_home_assistant_config",
            return_value={"url": "http://test:8123", "token": "test"},
        ),
        patch("httpx.AsyncClient", return_value=mock_ctx),
    ):
        resp = client.get("/api/ha/services")
    assert resp.status_code != 500


def test_smoke_ha_test(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with (
        patch(
            "backend.core.secrets.load_home_assistant_config",
            return_value={"url": "http://test:8123", "token": "test"},
        ),
        patch("httpx.AsyncClient", return_value=mock_ctx),
    ):
        resp = client.post("/api/ha/test")
    assert resp.status_code != 500


def test_smoke_water_boost_get(client):
    with patch("backend.api.routers.executor.get_executor_instance", return_value=None):
        resp = client.get("/api/water/boost")
    assert resp.status_code != 500


def test_smoke_water_boost_set(client):
    with patch("backend.api.routers.executor.get_executor_instance", return_value=None):
        resp = client.post("/api/water/boost", json={"duration_minutes": 30})
    assert resp.status_code == 503


def test_smoke_water_boost_delete(client):
    with patch("backend.api.routers.executor.get_executor_instance", return_value=None):
        resp = client.delete("/api/water/boost")
    assert resp.status_code != 500


def test_smoke_energy_today(client):
    resp = client.get("/api/energy/today")
    assert resp.status_code == 200


def test_smoke_energy_range(client):
    resp = client.get("/api/energy/range?period=today")
    assert resp.status_code == 200


def test_smoke_performance_data(client):
    resp = client.get("/api/performance/data")
    assert resp.status_code == 200


def test_smoke_ha_socket(client):
    with patch(
        "backend.ha_socket.get_ha_socket_status",
        return_value={"status": "connected"},
    ):
        resp = client.get("/api/ha-socket")
    assert resp.status_code != 500
