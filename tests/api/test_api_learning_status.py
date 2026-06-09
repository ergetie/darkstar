import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path.cwd()))


@pytest.fixture
def client():
    from backend.main import create_app

    app = create_app()
    # Unwrap Socket.IO wrapper to get raw FastAPI app
    fastapi_app = app.other_asgi_app if hasattr(app, "other_asgi_app") else app
    # Patch LearningStore so the lifespan doesn't initialise aiosqlite in a sync context.
    # close() is called with await on shutdown so it must be an AsyncMock.
    # get_learning_engine is patched globally by the autouse fixture in conftest.py.
    with (
        patch(
            "backend.main.LearningStore",
            return_value=MagicMock(ensure_wal_mode=AsyncMock(), close=AsyncMock()),
        ),
        TestClient(fastapi_app) as client,
    ):
        yield client


def test_training_status(client):
    """Test training status endpoint."""
    mock_status = {
        "is_training": False,
        "lock_age_seconds": None,
        "models": {"test.lgb": {"age_seconds": 100}},
    }

    with patch("ml.training_orchestrator.get_training_status", return_value=mock_status):
        response = client.get("/api/learning/training-status")
        assert response.status_code == 200
        data = response.json()
        assert data["is_training"] is False
        assert "test.lgb" in data["models"]


def test_training_history(client):
    """Test training history endpoint."""
    # Mock learning_history which is called internally
    mock_history = {"runs": [{"id": 1}], "count": 1}

    with patch(
        "backend.api.routers.learning.learning_history", new_callable=MagicMock
    ) as mock_hist:
        # Since calling async function directly, we mock the return value awaitable
        async def async_return(*args, **kwargs):
            return mock_history

        mock_hist.side_effect = async_return

        response = client.get("/api/learning/training-history?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["runs"][0]["id"] == 1
