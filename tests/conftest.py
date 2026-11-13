import asyncio
import os
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from functools import wraps
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from alembic import command
from backend.core import secrets
from backend.learning.models import Base


class PollingEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    """Make cross-thread callbacks reliable in this restricted test runtime.

    The sandbox blocks asyncio's socketpair wakeup, which normally alerts an
    event loop when a worker thread completes.  Polling the selector briefly
    preserves normal thread-based behavior while preventing callbacks from
    waiting indefinitely.
    """

    def new_event_loop(self):
        loop = super().new_event_loop()
        selector = loop._selector  # type: ignore[attr-defined]
        original_select = selector.select

        @wraps(original_select)
        def polling_select(timeout=None):
            if timeout is None or timeout > 0.005:
                timeout = 0.005
            return original_select(timeout)

        selector.select = polling_select
        return loop


asyncio.set_event_loop_policy(PollingEventLoopPolicy())


@pytest.fixture
def stockholm_tz(monkeypatch):
    """Run a test with the host timezone set to Europe/Stockholm."""
    original_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Europe/Stockholm")
    time.tzset()
    try:
        yield
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        time.tzset()


@pytest.fixture(autouse=True)
def disable_external_nordpool_requests(monkeypatch):
    """Keep the suite hermetic when tests exercise executor price updates."""

    def empty_fetch(*args, **kwargs):
        return {"areas": {}}

    monkeypatch.setattr("nordpool.elspot.Prices.fetch", empty_fetch)


@pytest.fixture(autouse=True)
def isolated_ev_state_file(monkeypatch, tmp_path):
    """Point the EV state file at a per-test temp path.

    The executor restores/persists manual charges there on construction and
    on start/stop, so tests must never read or write the real data/ file.
    Tests that set STATE_FILE_PATH themselves still override this.
    """
    from backend.core import ev_state

    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", tmp_path / "ev_multi_day_state.json")


@pytest.fixture(autouse=True)
def isolated_onboarding_state(monkeypatch, tmp_path):
    """Keep onboarding/acknowledgement state and the PV site ratio cache per test."""
    from backend import health
    from backend.core import onboarding_state

    monkeypatch.setattr(onboarding_state, "STATE_FILE_PATH", tmp_path / "onboarding_state.json")
    monkeypatch.setattr(health, "_pv_site_ratio_cache", None)


@pytest.fixture(autouse=True)
def isolated_ev_soc_memory():
    """Clear the process-wide last-known SoC / stale-episode memory per test."""
    from backend.core.ev_live_state import reset_soc_memory

    reset_soc_memory()
    yield
    reset_soc_memory()


@pytest.fixture(autouse=True)
def no_background_replans(monkeypatch):
    """Keep goal/plug writes from dispatching real background planner runs.

    Goal saves and HA goal changes call ``request_replan`` (fire-and-forget),
    which would otherwise run the real planner against the test config after
    the debounce. Tests that assert dispatch patch it themselves or call the
    imported function object directly.
    """
    from unittest.mock import MagicMock

    monkeypatch.setattr("backend.services.scheduler_service.request_replan", MagicMock())


_SEEDED_CONFIG = Path("config.yaml")
_config_seeded_by_session = False


def _is_xdist_worker(config) -> bool:
    return hasattr(config, "workerinput")


def pytest_sessionstart(session):
    """Seed a ``config.yaml`` from the shipped default when the machine has none (CI).

    Code paths that read ``config.yaml`` directly (bypassing the ``load_yaml`` mock
    below) would otherwise raise ``FileNotFoundError``. Done once by the controller
    process, before any xdist worker starts, so workers never race to create or
    delete it. Locally (a real ``config.yaml`` exists) the file is left untouched.
    """
    global _config_seeded_by_session
    if _is_xdist_worker(session.config) or _SEEDED_CONFIG.exists():
        return
    default_cfg = yaml.safe_load(Path("config.default.yaml").read_text(encoding="utf-8"))
    _SEEDED_CONFIG.write_text(yaml.safe_dump(default_cfg, sort_keys=False), encoding="utf-8")
    _config_seeded_by_session = True


def pytest_sessionfinish(session, exitstatus):
    """Remove the seeded ``config.yaml`` (only if this session created it)."""
    global _config_seeded_by_session
    if _config_seeded_by_session and not _is_xdist_worker(session.config):
        with suppress(Exception):
            _SEEDED_CONFIG.unlink()
        _config_seeded_by_session = False


@pytest.fixture(scope="session", autouse=True)
def setup_test_env(tmp_path_factory):
    """Set up a clean, hermetic, per-process test environment.

    Makes the suite reproducible on a fresh machine (e.g. CI) that has neither a
    ``config.yaml`` nor a migrated database, and safe under pytest-xdist:

    * Creates the SQLite schema in a throwaway test DB inside this process's own
      base temp dir (each xdist worker gets its own). Production builds the schema
      with Alembic, which CI and the test runner do not execute, so
      ``LearningStore`` init would otherwise hit ``no such table``.
    * Pins every DB consumer to that test DB via ``DB_PATH`` (the app lifespan
      honours this env var).
    * Mocks ``secrets.load_yaml`` for ``config.yaml`` with a minimal test config.
    """
    Path("data").mkdir(exist_ok=True)

    db_path = tmp_path_factory.mktemp("planner_db") / "test_planner.db"

    original_db_path = os.environ.get("DB_PATH")
    os.environ["DB_PATH"] = str(db_path)

    # Build the schema from the same models Alembic manages in production.
    schema_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(schema_engine)
    schema_engine.dispose()

    test_config = {
        "version": "2.5.1-beta",
        "timezone": "Europe/Stockholm",
        "learning": {
            "enable": True,
            "sqlite_path": str(db_path),
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


@pytest.fixture(autouse=True)
def reset_ha_http_client():
    """Reset the Home Assistant shared HTTP client dict between tests to prevent test contamination."""
    from backend.core import ha_client

    ha_client._ha_http_clients.clear()
    yield
    ha_client._ha_http_clients.clear()


@pytest.fixture(autouse=True)
def isolated_load_profile_state(monkeypatch, tmp_path):
    """Per-test load profile failure memo, in-flight builds and last good profile file.

    The last good profile is written after every successful live build, so tests must
    never touch the real data/ file or inherit another test's cooldown.
    """
    from backend.core import ha_client

    monkeypatch.setattr(
        ha_client, "_LOAD_PROFILE_STORE_PATH", tmp_path / "load_profile_last_good.json"
    )
    ha_client.reset_load_profile_state()
    yield
    ha_client.reset_load_profile_state()


@pytest.fixture(autouse=True)
def isolated_ml_state(monkeypatch, tmp_path_factory):
    """Keep ML global state and model files from leaking between tests.

    - ``ml.forward._load_retrain_requested`` is reset so a rejected-schema test
      cannot make a later scheduler loop start a real retrain.
    - ``ml.training_orchestrator.MODELS_DIR`` and friends point at a temp dir so
      no test can train into or overwrite the real ``data/ml/models``.
    """
    import ml.forward as forward
    import ml.training_orchestrator as orchestrator

    monkeypatch.setattr(forward, "_load_retrain_requested", False)
    models_dir = tmp_path_factory.mktemp("ml_models")
    monkeypatch.setattr(orchestrator, "MODELS_DIR", models_dir)
    monkeypatch.setattr(orchestrator, "BACKUP_DIR", models_dir / "backup")
    monkeypatch.setattr(orchestrator, "LOCK_FILE", models_dir / ".training.lock")


@pytest.fixture(autouse=True)
def single_threaded_lightgbm(monkeypatch):
    """Keep LightGBM at one thread per test; xdist workers already parallelise."""
    monkeypatch.setenv("DARKSTAR_ML_THREADS", "1")


# --- Alembic migration tests ------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def _fast_sqlite() -> Iterator[None]:
    """Disable fsync/journaling on SQLite connections (throwaway test DBs only)."""

    def _set_pragmas(dbapi_conn, _record):
        if not isinstance(dbapi_conn, sqlite3.Connection):
            return
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA synchronous=OFF")
        cur.execute("PRAGMA journal_mode=MEMORY")
        cur.close()

    event.listen(Engine, "connect", _set_pragmas)
    try:
        yield
    finally:
        event.remove(Engine, "connect", _set_pragmas)


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def _alembic_templates(tmp_path_factory) -> Callable[[str], Path]:
    """Per-worker cache of DBs migrated from base to a revision (built once each)."""
    cache: dict[str, Path] = {}
    root = tmp_path_factory.mktemp("alembic_templates")

    def get(revision: str) -> Path:
        if revision not in cache:
            path = root / f"{revision}.db"
            with pytest.MonkeyPatch.context() as mp, _fast_sqlite():
                mp.setenv("DB_PATH", str(path))
                command.upgrade(_alembic_config(), revision)
            cache[revision] = path
        return cache[revision]

    return get


@pytest.fixture
def alembic_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _alembic_templates: Callable[[str], Path]
) -> Iterator[Callable[[str], tuple[Config, Path]]]:
    """Factory ``alembic_db(revision) -> (config, db_path)``.

    The DB is a private copy of a template already migrated base -> ``revision``,
    so a test only runs the migration step it is actually about. DB_PATH points
    at the copy; SQLite fsync is off for the duration of the test.
    """
    db_path = tmp_path / "migration.db"

    def make(revision: str) -> tuple[Config, Path]:
        shutil.copyfile(_alembic_templates(revision), db_path)
        monkeypatch.setenv("DB_PATH", str(db_path))
        return _alembic_config(), db_path

    with _fast_sqlite():
        yield make
