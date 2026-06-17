import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from sqlalchemy import create_engine

from backend.core import secrets
from backend.learning.models import Base


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Set up a clean, hermetic test environment.

    Makes the suite reproducible on a fresh machine (e.g. CI) that has neither a
    ``config.yaml`` nor a migrated database:

    * Creates the SQLite schema in a throwaway test DB. Production builds the
      schema with Alembic, which CI and the test runner do not execute, so
      ``LearningStore`` init would otherwise hit ``no such table``.
    * Pins every DB consumer to that test DB via ``DB_PATH`` (the app lifespan
      honours this env var).
    * Seeds a ``config.yaml`` from the shipped ``config.default.yaml`` when one
      is absent, so the code paths that read ``config.yaml`` directly (bypassing
      the ``load_yaml`` mock below) do not raise ``FileNotFoundError``.

    Locally (where a real ``config.yaml`` exists) the file is left untouched.
    """
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    db_path = data_dir / "test_planner.db"

    # Pin DB access (the app lifespan respects DB_PATH) to the throwaway test DB.
    original_db_path = os.environ.get("DB_PATH")
    os.environ["DB_PATH"] = str(db_path)

    # Build the schema from the same models Alembic manages in production.
    schema_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(schema_engine)
    schema_engine.dispose()

    # Seed a config.yaml from the shipped default if the machine has none (CI),
    # pointing its DB at the test DB so file-readers and DB_PATH agree.
    config_file = Path("config.yaml")
    created_config_file = False
    if not config_file.exists():
        default_cfg = yaml.safe_load(Path("config.default.yaml").read_text(encoding="utf-8"))
        default_cfg.setdefault("learning", {})["sqlite_path"] = str(db_path)
        config_file.write_text(yaml.safe_dump(default_cfg, sort_keys=False), encoding="utf-8")
        created_config_file = True

    test_config = {
        "version": "2.5.1-beta",
        "timezone": "Europe/Stockholm",
        "learning": {
            "enable": True,
            "sqlite_path": "data/test_planner.db",
            "horizon_days": 2,
        },
        "forecasting": {
            "active_forecast_version": "aurora",
        },
        "input_sensors": {
            "battery_soc": "sensor.test_soc",
        },
    }

    original_load_yaml = secrets.load_yaml

    def mock_load_yaml(path: str) -> dict:
        if path == "config.yaml":
            return test_config
        return original_load_yaml(path)

    with patch.object(secrets, "load_yaml", mock_load_yaml):
        yield

    # Restore DB_PATH to its pre-test value.
    if original_db_path is None:
        os.environ.pop("DB_PATH", None)
    else:
        os.environ["DB_PATH"] = original_db_path

    # Remove the seeded config.yaml only if we created it (never the real one).
    if created_config_file:
        try:
            config_file.unlink()
        except Exception:
            pass

    try:
        if db_path.exists():
            db_path.unlink()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def reset_ha_http_client():
    """Reset the Home Assistant shared HTTP client dict between tests to prevent test contamination."""
    from backend.core import ha_client
    ha_client._ha_http_clients.clear()
    yield
    ha_client._ha_http_clients.clear()
