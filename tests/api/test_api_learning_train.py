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


def test_learning_train_success(client):
    """Test manual training trigger success."""
    with patch("ml.training_orchestrator.train_all_models", new_callable=AsyncMock) as mock_train:
        mock_train.return_value = {
            "status": "success",
            "trained_models": ["model1.lgb"],
            "duration_seconds": 10.5,
        }

        response = client.post("/api/learning/train")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "model1.lgb" in data["trained_models"]

        mock_train.assert_called_once_with(training_type="manual")


def test_learning_train_busy(client):
    """Test manual training trigger when busy."""
    with patch("ml.training_orchestrator.train_all_models", new_callable=AsyncMock) as mock_train:
        mock_train.return_value = {
            "status": "busy",
            "error": "Training already in progress",
            "duration_seconds": 0,
        }

        response = client.post("/api/learning/train")
        assert response.status_code == 409
        data = response.json()
        assert "Training already in progress" in data["detail"]


def test_learning_train_error(client):
    """Test manual training trigger unexpected error."""
    with patch("ml.training_orchestrator.train_all_models", new_callable=AsyncMock) as mock_train:
        mock_train.side_effect = Exception("Crash")

        response = client.post("/api/learning/train")
        assert response.status_code == 500
        data = response.json()
        assert "Crash" in data["detail"]


def test_learning_run_success(client):
    """Test full learning run success."""
    with (
        patch("ml.training_orchestrator.train_all_models", new_callable=AsyncMock) as mock_train,
        patch("backend.learning.reflex.AuroraReflex.run", new_callable=AsyncMock) as mock_reflex,
    ):
        mock_train.return_value = {"status": "success"}
        mock_reflex.return_value = {"updated": True}

        response = client.post("/api/learning/run")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["training_result"]["status"] == "success"
        assert data["reflex_report"]["updated"] is True

        mock_train.assert_called_once_with(training_type="manual")
