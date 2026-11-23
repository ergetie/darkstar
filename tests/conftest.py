import asyncio
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from functools import wraps
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

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


_REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Real workspace protection ------------------------------------------------
#
# The suite must never read or write the developer's real ``data/`` directory,
# ``config.yaml`` or ``secrets.yaml``. Three layers enforce that:
#
# 1. Sandbox working directory: every test process runs with its cwd set to a throwaway
#    directory that mirrors the repository (symlinks) but has its own empty ``data/`` and a
#    ``config.yaml`` seeded from ``config.default.yaml``. Relative paths such as
#    ``data/schedule.json`` or ``config.yaml`` therefore never reach the workspace, and the
#    suite behaves the same on a fresh checkout (CI) as on a machine with real state.
# 2. Write guard: an audit hook refuses (and records) any write, delete or SQLite connect
#    on the real protected paths made through an absolute path (for example paths computed
#    from ``__file__``) and fails the offending test.
# 3. Snapshot backstop: file list, sizes and mtimes of the real ``data/`` are compared at the
#    start and end of the session; any difference fails the run (catches what hooks cannot
#    see, such as SQLite's own -wal/-shm files).

_PROTECTED_FILES = ("config.yaml", "secrets.yaml")
_SANDBOX_SKIP = frozenset(
    {
        "data",
        "config.yaml",
        "config.yaml.bak",
        "secrets.yaml",
        "schedule.json",
        "darkstar.db",
        "logs",
        "backups",
        "memory",
    }
)
_SNAPSHOT_GUARD_ENV = "DARKSTAR_TEST_DATA_SNAPSHOT_GUARD"


def _variants(path: Path) -> set[str]:
    return {os.path.abspath(path), os.path.realpath(path)}


_REAL_DATA_DIRS = _variants(_REPO_ROOT / "data")
_REAL_PROTECTED_FILES = {v for name in _PROTECTED_FILES for v in _variants(_REPO_ROOT / name)}


def _is_protected(path: str) -> bool:
    if path in _REAL_PROTECTED_FILES:
        return True
    return any(path == d or path.startswith(d + os.sep) for d in _REAL_DATA_DIRS)


class RealWorkspaceWriteError(PermissionError):
    """A test tried to modify the real workspace state."""


# event -> (indexes of mutated path arguments, indexes of dir_fd arguments)
_MUTATING_EVENTS: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "os.mkdir": ((0,), (2,)),
    "os.rmdir": ((0,), (1,)),
    "os.remove": ((0,), (1,)),
    "os.rename": ((0, 1), (2, 3)),
    "os.truncate": ((0,), ()),
    "os.utime": ((0,), (3,)),
    "os.chmod": ((0,), (2,)),
    "os.chown": ((0,), (3,)),
    "os.symlink": ((1,), (2,)),
    "os.link": ((0, 1), (2, 3)),
    "shutil.copyfile": ((1,), ()),
    "shutil.copymode": ((1,), ()),
    "shutil.copystat": ((1,), ()),
    "shutil.copytree": ((1,), ()),
    "shutil.rmtree": ((0,), (1,)),
    "shutil.move": ((0, 1), ()),
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

_violations: list[tuple[str, str, str]] = []
_current_test: list[str] = ["<outside a test>"]


def _as_abs(value: object) -> str | None:
    if isinstance(value, (str, bytes, os.PathLike)):
        return os.path.abspath(os.fsdecode(value))
    return None


def _sqlite_target(database: object) -> str | None:
    """Real path an ``sqlite3.connect`` call would write to; None for read-only/in-memory."""
    if isinstance(database, bytes):
        database = os.fsdecode(database)
    if isinstance(database, os.PathLike):
        database = os.fspath(database)
    if not isinstance(database, str):
        return None
    if database.startswith("file:"):
        parsed = urlparse(database)
        if "mode=ro" in parsed.query:
            return None
        database = parsed.path
    if database in ("", ":memory:"):
        return None
    return os.path.abspath(database)


def _guard_hook(event: str, args: tuple[object, ...]) -> None:
    targets: list[str | None] = []
    if event == "open":
        path, flags = args[0], args[2]
        if isinstance(flags, int) and flags & _WRITE_FLAGS:
            targets.append(_as_abs(path))
    elif event == "sqlite3.connect":
        targets.append(_sqlite_target(args[0]))
    elif event in _MUTATING_EVENTS:
        indexes, fd_indexes = _MUTATING_EVENTS[event]
        if any(i < len(args) and args[i] not in (None, -1) for i in fd_indexes):
            return
        targets.extend(_as_abs(args[i]) for i in indexes if i < len(args))
    else:
        return
    for target in targets:
        if target is not None and _is_protected(target):
            _violations.append((event, target, _current_test[0]))
            raise RealWorkspaceWriteError(
                f"test attempted {event} on the real workspace path {target}; "
                "tests must use tmp paths (see tests/conftest.py)"
            )


sys.addaudithook(_guard_hook)


def _snapshot_data_dir() -> dict[str, tuple[int, int]]:
    """Relative path -> (size, mtime_ns) for files, (-1, 0) for directories."""
    root = _REPO_ROOT / "data"
    snap: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return snap
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            snap[os.path.relpath(os.path.join(dirpath, name), root)] = (-1, 0)
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            snap[os.path.relpath(full, root)] = (st.st_size, st.st_mtime_ns)
    return snap


def _diff_snapshots(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> list[str]:
    lines = [f"added: {name}" for name in sorted(after.keys() - before.keys())]
    lines += [f"removed: {name}" for name in sorted(before.keys() - after.keys())]
    lines += [
        f"modified: {name} (size/mtime_ns {before[name]} -> {after[name]})"
        for name in sorted(before.keys() & after.keys())
        if before[name] != after[name]
    ]
    return lines


_sandbox_dir: Path | None = None
_original_cwd: str | None = None
_data_snapshot: dict[str, tuple[int, int]] | None = None


def _is_xdist_worker(config) -> bool:
    return hasattr(config, "workerinput")


def _is_xdist_controller(config) -> bool:
    return not _is_xdist_worker(config) and getattr(config.option, "dist", "no") != "no"


def _build_sandbox() -> Path:
    sandbox = Path(tempfile.mkdtemp(prefix="darkstar-test-cwd-"))
    for entry in _REPO_ROOT.iterdir():
        if entry.name not in _SANDBOX_SKIP and not entry.name.endswith(".bak"):
            (sandbox / entry.name).symlink_to(entry)
    data = sandbox / "data"
    data.mkdir()
    # The app log is not worth keeping in tests: send it to /dev/null (a non-regular file,
    # which RotatingFileHandler never rolls over) so workers cannot fill the RAM-backed /tmp.
    (data / "darkstar.log").symlink_to(os.devnull)
    default_cfg = yaml.safe_load((_REPO_ROOT / "config.default.yaml").read_text(encoding="utf-8"))
    (sandbox / "config.yaml").write_text(
        yaml.safe_dump(default_cfg, sort_keys=False), encoding="utf-8"
    )
    return sandbox


def pytest_sessionstart(session):
    """Snapshot the real ``data/`` and move this process into the sandbox working dir."""
    global _sandbox_dir, _original_cwd, _data_snapshot
    if not _is_xdist_worker(session.config) and os.environ.get(_SNAPSHOT_GUARD_ENV) != "0":
        _data_snapshot = _snapshot_data_dir()
    if _is_xdist_controller(session.config):
        return  # the controller runs no tests; workers each build their own sandbox
    _original_cwd = os.getcwd()
    _sandbox_dir = _build_sandbox()
    os.chdir(_sandbox_dir)


def pytest_sessionfinish(session, exitstatus):
    """Leave the sandbox, remove it and verify the real ``data/`` is untouched."""
    global _sandbox_dir, _data_snapshot
    if _sandbox_dir is not None:
        if _original_cwd is not None:
            with suppress(OSError):
                os.chdir(_original_cwd)
        # Symlinks are unlinked, never followed, so the repository is not touched.
        shutil.rmtree(_sandbox_dir, ignore_errors=True)
        _sandbox_dir = None
    problems: list[str] = [f"{event} {path} (in {where})" for event, path, where in _violations]
    if _data_snapshot is not None:
        problems += _diff_snapshots(_data_snapshot, _snapshot_data_dir())
        _data_snapshot = None
    if problems:
        message = (
            "\nFAILED: the test run touched the real workspace "
            f"(set {_SNAPSHOT_GUARD_ENV}=0 only if the app is running against data/):\n  "
            + "\n  ".join(problems)
        )
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(message, red=True)
        else:
            print(message)
        if session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def _real_workspace_guard(request):
    """Fail the test that tried to modify the real workspace, and name the culprit."""
    _current_test[0] = request.node.nodeid
    start = len(_violations)
    yield
    _current_test[0] = "<outside a test>"
    new = _violations[start:]
    if new:
        del _violations[start:]
        details = "; ".join(f"{event} {path}" for event, path, _ in new)
        pytest.fail(f"test modified the real workspace: {details}", pytrace=False)


@pytest.fixture(scope="session")
def real_workspace():
    """Locations and helpers of the real-workspace protection (for its own tests)."""
    from types import SimpleNamespace

    return SimpleNamespace(
        repo_root=_REPO_ROOT,
        data_dir=_REPO_ROOT / "data",
        diff_snapshots=_diff_snapshots,
    )


@pytest.fixture
def expect_real_workspace_violation(_real_workspace_guard):
    """Let a test deliberately trigger the guard (used only by the guard's own tests)."""
    start = len(_violations)
    yield
    del _violations[start:]


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
def isolated_nordpool_last_good(monkeypatch, tmp_path):
    """Per-test last-good Nordpool price file and fetch state.

    A complete price fetch writes the last-good file, so tests must never touch the real
    data/ file or inherit another test's stored prices, retry window or fallback log state.
    """
    from backend.core import prices

    monkeypatch.setattr(prices, "_LAST_GOOD_PATH", tmp_path / "nordpool_last_good.json")
    prices.reset_price_fetch_state()
    yield
    prices.reset_price_fetch_state()


@pytest.fixture(autouse=True)
def isolated_plan_archive(monkeypatch, tmp_path):
    """Per-test plan archive directory.

    Planner service runs archive a record (also on failure), so tests must never write
    into the real ``data/plan_archive``.
    """
    from backend.services import plan_archive

    monkeypatch.setattr(plan_archive, "ARCHIVE_DIR", tmp_path / "plan_archive")


@pytest.fixture(autouse=True)
def isolated_strategy_history(monkeypatch, tmp_path):
    """Per-test strategy history file.

    Strategy runs append events to ``HISTORY_FILE``; tests must never write the real
    ``data/strategy_history.json`` or inherit events from it. Tests read the patched
    ``backend.strategy.history.HISTORY_FILE`` rather than a literal path.
    """
    from backend.strategy import history

    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "strategy_history.json")


@pytest.fixture(autouse=True)
def isolated_kepler_debug_lp(monkeypatch, tmp_path):
    """Per-test Kepler debug LP dump (written when the solver is not optimal)."""
    from planner.solver import kepler

    monkeypatch.setattr(kepler, "DEBUG_LP_PATH", tmp_path / "kepler_debug.lp")


@pytest.fixture(autouse=True)
def isolated_ml_bootstrap(monkeypatch, tmp_path_factory):
    """Run model bootstrap against a throwaway project root, never the real ``data/ml``.

    ``ensure_active_models`` (called by the app lifespan) anchors its paths to
    ``ml/bootstrap.py``: it purges stale files in, seeds and rewrites
    ``data/ml/models/defaults``. The fake root exposes the shipped defaults read-only
    through a symlink so seeding behaves as in production. Tests that set
    ``bootstrap.__file__`` themselves still override this.
    """
    import ml.bootstrap as bootstrap

    root = tmp_path_factory.mktemp("bootstrap_root")
    (root / "ml" / "models").mkdir(parents=True)
    (root / "ml" / "models" / "defaults").symlink_to(_REPO_ROOT / "ml" / "models" / "defaults")
    monkeypatch.setattr(bootstrap, "__file__", str(root / "ml" / "bootstrap.py"))


@pytest.fixture(autouse=True)
def isolated_default_learning_db(monkeypatch, tmp_path):
    """Point the hard-coded default learning database at a per-test (absent) file.

    ``get_forecast_db_path`` always returned ``data/planner_learning.db`` relative to the
    working directory, so health checks, price outlook, analyst and forecast code opened
    whatever database the workspace happened to have. Tests that need a database patch
    the function (or pass explicit paths) as before.
    """
    from backend.core import forecasts, price_outlook

    path = str(tmp_path / "default_planner_learning.db")
    monkeypatch.setattr(forecasts, "get_forecast_db_path", lambda: path)
    monkeypatch.setattr(price_outlook, "get_forecast_db_path", lambda: path)


@pytest.fixture(autouse=True)
def isolated_recorder_obsolete_state(monkeypatch, tmp_path):
    """Per-test location of the obsolete recorder state file the service deletes on start."""
    from backend.services import recorder_service

    monkeypatch.setattr(recorder_service, "OBSOLETE_STATE_FILE", tmp_path / "recorder_state.json")


@pytest.fixture(autouse=True)
def isolated_price_forecast_db(monkeypatch, tmp_path):
    """Keep the D+1 price-forecast fallback off the real ``data/planner_learning.db``.

    ``get_nordpool_data`` falls back to ``ml.price_forecast.get_d1_price_forecast_fallback``
    before 13:00 local when no tomorrow prices are known. That reads the default database
    path, so a workspace with a real database leaks forecast slots into price tests.
    Calls that use the default path are redirected to an empty per-test database; calls
    with an explicit ``db_path`` are untouched.
    """
    import ml.price_forecast as price_forecast

    real = price_forecast.get_price_forecasts_from_db
    default_path = "data/planner_learning.db"
    isolated_path = str(tmp_path / "isolated_planner_learning.db")

    @wraps(real)
    async def redirected(*args, **kwargs):
        if args:
            if args[0] == default_path:
                args = (isolated_path, *args[1:])
        elif kwargs.get("db_path", default_path) == default_path:
            kwargs["db_path"] = isolated_path
        return await real(*args, **kwargs)

    monkeypatch.setattr(price_forecast, "get_price_forecasts_from_db", redirected)


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


@pytest.fixture(autouse=True)
def _restore_logging_state() -> Iterator[None]:
    """Undo logging changes a test leaks into later tests in the same worker.

    ``alembic/env.py`` calls ``logging.config.fileConfig`` (``disable_existing_loggers``),
    which disables every logger created so far and replaces the root handlers; tests that
    run an in-process ``command.upgrade`` would otherwise break ``caplog`` assertions in
    unrelated tests that run later on the same xdist worker.
    """
    root = logging.getLogger()
    manager = logging.root.manager
    root_state = (root.level, root.handlers[:], root.disabled)
    saved = {
        name: (lg.disabled, lg.level, lg.propagate, lg.handlers[:])
        for name, lg in manager.loggerDict.items()
        if isinstance(lg, logging.Logger)
    }
    disable_level = manager.disable
    try:
        yield
    finally:
        manager.disable = disable_level
        root.setLevel(root_state[0])
        root.handlers[:] = root_state[1]
        root.disabled = root_state[2]
        for name, lg in list(manager.loggerDict.items()):
            if not isinstance(lg, logging.Logger):
                continue
            if name in saved:
                lg.disabled, level, lg.propagate, handlers = saved[name]
                lg.setLevel(level)
                lg.handlers[:] = handlers
            else:
                lg.disabled = False


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
