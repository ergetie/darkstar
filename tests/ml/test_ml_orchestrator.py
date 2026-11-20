import time
from unittest.mock import MagicMock, patch

import pytest

from ml import training_orchestrator


@pytest.fixture(autouse=True)
def setup_test_dirs(tmp_path, monkeypatch):
    """Setup temporary directories for models and backups."""
    test_models_dir = tmp_path / "ml" / "models"
    test_models_dir.mkdir(parents=True)

    # Patch the constants in training_orchestrator
    monkeypatch.setattr(training_orchestrator, "MODELS_DIR", test_models_dir)
    monkeypatch.setattr(training_orchestrator, "BACKUP_DIR", test_models_dir / "backup")
    monkeypatch.setattr(training_orchestrator, "LOCK_FILE", test_models_dir / ".training.lock")

    yield test_models_dir


def test_lock_mechanism(setup_test_dirs):
    """Test that lock acquisition and release work correctly."""
    assert training_orchestrator._acquire_lock() is True
    assert training_orchestrator.LOCK_FILE.exists()

    # Second acquisition should fail
    assert training_orchestrator._acquire_lock() is False

    training_orchestrator._release_lock()
    assert not training_orchestrator.LOCK_FILE.exists()
    assert training_orchestrator._acquire_lock() is True


def test_stale_lock_removal(setup_test_dirs, monkeypatch):
    """Test that stale locks are removed."""
    training_orchestrator.LOCK_FILE.touch()

    # Mock time to be 2 hours in the future
    current_time = time.time()
    monkeypatch.setattr("time.time", lambda: current_time + 7200)

    assert training_orchestrator._acquire_lock() is True


def test_backup_and_rotation(setup_test_dirs):
    """Test model backup and rotation logic."""
    # Create dummy model file
    (setup_test_dirs / "model1.lgb").touch()

    training_orchestrator._backup_models()
    assert training_orchestrator.BACKUP_DIR.exists()
    backups = list(training_orchestrator.BACKUP_DIR.iterdir())
    assert len(backups) == 1
    assert (backups[0] / "model1.lgb").exists()

    # Create more backups to test rotation
    time.sleep(1.1)
    training_orchestrator._backup_models()
    time.sleep(1.1)
    training_orchestrator._backup_models()

    backups = list(training_orchestrator.BACKUP_DIR.iterdir())
    assert len(backups) == 2  # Only keep last 2


def test_restore_backup(setup_test_dirs):
    """Test restoring models from backup."""
    (setup_test_dirs / "model1.lgb").write_text("v1")
    training_orchestrator._backup_models()

    (setup_test_dirs / "model1.lgb").write_text("v2")
    assert (setup_test_dirs / "model1.lgb").read_text() == "v2"

    assert training_orchestrator._restore_latest_backup() is True
    assert (setup_test_dirs / "model1.lgb").read_text() == "v1"


@pytest.mark.asyncio
@patch("ml.training_orchestrator.train_models")
@patch("ml.training_orchestrator.get_learning_engine")
async def test_train_all_models_flow(mock_get_engine, mock_train_main, setup_test_dirs):
    """Test the full unified training flow (corrector removed)."""
    from unittest.mock import AsyncMock

    # Setup mocks
    mock_store = MagicMock()
    mock_store.log_learning_run = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.store = mock_store
    mock_engine.db_path = "data/test_learning.db"
    mock_get_engine.return_value = mock_engine

    # Create a dummy model file so the orchestrator thinks training succeeded
    (setup_test_dirs / "load_model.lgb").touch()

    res = await training_orchestrator.train_all_models()

    assert res["status"] == "success", f"Training failed: {res.get('error')}"
    assert "load_model.lgb" in res["trained_models"]
    assert mock_train_main.called
    assert mock_store.log_learning_run.called


@pytest.mark.asyncio
@patch("ml.training_orchestrator.train_models")
@patch("ml.training_orchestrator.get_learning_engine")
async def test_train_all_models_low_graduation(mock_get_engine, mock_train_main, setup_test_dirs):
    """Test training with low graduation level (no corrector training)."""
    from unittest.mock import AsyncMock

    mock_store = MagicMock()
    mock_store.log_learning_run = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.store = mock_store
    mock_engine.db_path = "data/test_learning.db"
    mock_get_engine.return_value = mock_engine

    (setup_test_dirs / "load_model.lgb").touch()

    res = await training_orchestrator.train_all_models()

    assert res["status"] == "success", f"Training failed: {res.get('error')}"
    assert mock_train_main.called


@pytest.mark.asyncio
@patch("ml.training_orchestrator.get_learning_engine")
async def test_train_all_models_error_recovery(mock_get_engine, setup_test_dirs, monkeypatch):
    """Test auto-restore on failure."""
    from unittest.mock import AsyncMock

    # Setup mocks
    mock_store = MagicMock()
    mock_store.log_learning_run = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.store = mock_store
    mock_engine.db_path = "data/test_learning.db"
    mock_get_engine.return_value = mock_engine

    # 1. Create a "good" state and backup
    (setup_test_dirs / "load_model.lgb").write_text("good")
    training_orchestrator._backup_models()

    # 2. Mock train_models to raise an error and NOT produce a model
    def fail_training(**kwargs):
        if (setup_test_dirs / "load_model.lgb").exists():
            (setup_test_dirs / "load_model.lgb").unlink()
        raise Exception("Boom!")

    with patch("ml.training_orchestrator.train_models", side_effect=fail_training):
        res = await training_orchestrator.train_all_models()

    assert res["status"] == "error"
    # Should have restored from backup
    assert (setup_test_dirs / "load_model.lgb").read_text() == "good"


@pytest.mark.asyncio
@patch("ml.training_orchestrator.train_models")
@patch("ml.training_orchestrator.get_learning_engine")
async def test_generate_price_forecasts_called_when_training_fails(
    mock_get_engine, mock_train_main, setup_test_dirs
):
    """Test that generate_price_forecasts is called even when price model training fails."""
    from unittest.mock import AsyncMock

    # Setup mocks
    mock_store = MagicMock()
    mock_store.log_learning_run = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.store = mock_store
    mock_engine.db_path = "data/test_learning.db"
    mock_engine.config = {"price_forecast": {"model_name": "price_model.lgb"}}
    mock_get_engine.return_value = mock_engine

    # Create main model so main training succeeds
    (setup_test_dirs / "load_model.lgb").touch()

    # Mock generate_price_forecasts to return empty list
    with patch(
        "ml.price_forecast.generate_price_forecasts", new_callable=AsyncMock
    ) as mock_generate_forecasts:
        mock_generate_forecasts.return_value = []

        # Mock train_price_model to return False (insufficient data path)
        with (
            patch("ml.training_orchestrator.train_price_model", return_value=False),
            patch.object(training_orchestrator.ws_manager, "emit", new_callable=AsyncMock),
        ):
            res = await training_orchestrator.train_all_models()

    assert res["status"] == "success"
    # Verify generate_price_forecasts was called even though train_price_model returned False
    mock_generate_forecasts.assert_called_once()
    # Verify it was called with model_path=None (since training failed)
    call_args = mock_generate_forecasts.call_args
    assert call_args.kwargs.get("model_path") is None
