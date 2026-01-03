import os
import sys

import pytest
from fastapi.testclient import TestClient

# Ensure backend can be imported
sys.path.append(os.getcwd())

@pytest.fixture
def client():
    from backend.main import create_app
    app = create_app()
    # Unwrap Socket.IO wrapper to get raw FastAPI app
    fastapi_app = app.other_asgi_app if hasattr(app, 'other_asgi_app') else app
    return TestClient(fastapi_app)

def test_health_endpoint(client):
    """Test health check (migrated to async/httpx)."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "healthy" in data
    assert "issues" in data

def test_version_endpoint(client):
    response = client.get("/api/version")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data or "commit" in data

def test_config_no_secrets(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    if "home_assistant" in data:
        assert "token" not in data["home_assistant"]

def test_aurora_dashboard(client):
    """Test Aurora Dashboard (migrated to async/aiosqlite)."""
    response = client.get("/api/aurora/dashboard")
    # Should handle missing DB gracefully
    assert response.status_code == 200
    data = response.json()
    assert "identity" in data
    assert "horizon" in data

def test_learning_history(client):
    """Test Learning History (migrated to async/aiosqlite)."""
    response = client.get("/api/learning/history")
    assert response.status_code == 200
    data = response.json()
    assert "runs" in data

def test_debug_soc(client):
    """Test Debug SoC (migrated to async/aiosqlite)."""
    response = client.get("/api/history/soc")
    assert response.status_code == 200
    data = response.json()
    assert "slots" in data
