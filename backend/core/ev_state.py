import contextlib
import fcntl
import json
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger("darkstar.core.ev_state")

STATE_FILE_PATH = Path("data/ev_multi_day_state.json")
last_darkstar_write: dict[str, float] = {}


@contextlib.contextmanager
def _locked():
    """Hold an inter-process advisory lock across a state read-modify-write.

    The lock path is derived from the CURRENT ``STATE_FILE_PATH`` on every
    call (not cached at import time) so that tests monkeypatching
    ``STATE_FILE_PATH`` alone redirect the lock file too.
    """
    lock_path = STATE_FILE_PATH.with_suffix(".json.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _read_ev_state_unlocked() -> dict[str, dict[str, Any]]:
    if not STATE_FILE_PATH.exists():
        return {}
    try:
        with STATE_FILE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return cast("dict[str, dict[str, Any]]", data)
    except Exception as exc:
        logger.warning("Could not read EV state file: %s", exc)
    return {}


def _write_ev_state_unlocked(state: dict[str, dict[str, Any]]) -> None:
    STATE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=STATE_FILE_PATH.parent,
        prefix=f".{STATE_FILE_PATH.name}.",
        suffix=".tmp",
        delete=False,
    ) as f:
        tmp_path = Path(f.name)
        try:
            json.dump(state, f, indent=2, default=str)
        except Exception:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise
    tmp_path.replace(STATE_FILE_PATH)


def read_ev_state() -> dict[str, dict[str, Any]]:
    """Read the EV multi-day state file. Returns an empty dict if not found or invalid."""
    with _locked():
        return _read_ev_state_unlocked()


def write_ev_state(state: dict[str, dict[str, Any]]) -> None:
    """Write the EV multi-day state file atomically using a unique temp file.

    Prefer :func:`update_ev_state` for read-modify-write callers — a bare
    ``write_ev_state`` after a bare ``read_ev_state`` is not atomic across the
    two calls and can lose concurrent updates.
    """
    try:
        with _locked():
            _write_ev_state_unlocked(state)
    except Exception as exc:
        logger.error("Failed to write EV state file: %s", exc)
        raise


def update_ev_state(
    mutator_fn: Callable[[dict[str, dict[str, Any]]], dict[str, dict[str, Any]] | None],
) -> dict[str, dict[str, Any]]:
    """Locked read-modify-write. ``mutator_fn`` receives the current state dict
    and may mutate it in place and/or return a replacement dict. Returns the
    state that was written.
    """
    with _locked():
        state = _read_ev_state_unlocked()
        result = mutator_fn(state)
        new_state = result if result is not None else state
        _write_ev_state_unlocked(new_state)
        return new_state
