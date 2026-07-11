"""Route-preservation snapshot test.

Verifies that all expected API endpoints (from the services.py split) are
registered in the app. This test must pass before and after the split.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client():
    from backend.main import create_app

    app = create_app()
    fastapi_app = app.other_asgi_app if hasattr(app, "other_asgi_app") else app
    with (
        patch(
            "backend.main.LearningStore",
            return_value=MagicMock(ensure_wal_mode=AsyncMock(), close=AsyncMock()),
        ),
        TestClient(fastapi_app),
    ):
        yield fastapi_app


def test_route_snapshot(app_client):
    """Verify all 14 expected routes from services.py are registered."""
    expected_routes = {
        "GET /api/ha/entity/{entity_id}",
        "GET /api/ha/average",
        "GET /api/ha/entities",
        "GET /api/ha/services",
        "POST /api/ha/test",
        "GET /api/water/boost",
        "POST /api/water/boost",
        "DELETE /api/water/boost",
        "GET /api/energy/today",
        "GET /api/energy/range",
        "GET /api/performance/data",
        "GET /api/ha-socket",
    }

    registered = set()
    for route in app_client.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                registered.add(f"{method} {route.path}")

    for expected in expected_routes:
        assert expected in registered, f"Missing route: {expected}"
