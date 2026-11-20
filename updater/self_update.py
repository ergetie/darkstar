"""Recreate the updater container after an update, through a detached helper container.

`docker compose up -d --build updater` cannot run inside the updater itself (compose would stop
the container that runs it), so a helper started from the updater's own image does it. Compose
builds before it touches the running container, so a failed build leaves the old updater alive.
The command is built from the repository path and the own image id only.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from .runner import Runner
    from .state import StateStore

UPDATER_CONTAINER = "darkstar-updater"
HELPER_CONTAINER = "darkstar-updater-recreate"
DOCKER_SOCKET = "/var/run/docker.sock"
MANUAL_COMMAND = "docker compose up -d --build updater"
FAILED_MESSAGE = (
    "Updater could not be recreated, the old updater keeps working; "
    f"run `{MANUAL_COMMAND}` in the Darkstar folder"
)
_IMAGE_ID = re.compile(r"(sha256:)?[0-9a-f]{12,64}")


def _record(store: StateStore, **values: Any) -> None:
    """Merge `values` into the persisted `self_update` entry."""
    current: dict[str, Any] = store.get("self_update") or {}
    store.update(self_update={**current, **values})


def helper_argv(repo_dir: str, image_id: str) -> list[str]:
    script = (
        f"sleep 3; exec docker compose --project-directory {repo_dir} "
        "up -d --build --no-deps updater"
    )
    return [
        "docker",
        "run",
        "-d",
        "--name",
        HELPER_CONTAINER,
        "--entrypoint",
        "sh",
        "-v",
        f"{DOCKER_SOCKET}:{DOCKER_SOCKET}",
        "-v",
        f"{repo_dir}:{repo_dir}",
        image_id,
        "-c",
        script,
    ]


def launch_recreate(
    runner: Runner,
    state: StateStore,
    *,
    repo_dir: str,
    fingerprint: str,
    log: Callable[[str], None],
) -> bool:
    """Persist the attempt and start the helper. Returns False (state `failed`) if it cannot start."""
    _record(
        state,
        state="started",
        fingerprint=fingerprint,
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        message=None,
        log_tail=[],
    )
    log("Recreating the updater with the new version")
    runner(["docker", "rm", "-f", HELPER_CONTAINER], cwd=repo_dir)
    inspected = runner(
        ["docker", "inspect", "--format", "{{.Image}}", UPDATER_CONTAINER], cwd=repo_dir
    )
    image_id = inspected.output.strip()
    if inspected.returncode != 0 or not _IMAGE_ID.fullmatch(image_id):
        log("WARNING: could not determine the updater image")
        _record(state, state="failed", message=FAILED_MESSAGE)
        return False
    started = runner(helper_argv(repo_dir, image_id), cwd=repo_dir, on_line=log)
    if started.returncode != 0:
        log("WARNING: could not start the updater recreate helper")
        _record(state, state="failed", message=FAILED_MESSAGE)
        return False
    return True


def follow_helper(
    runner: Runner,
    state: StateStore,
    *,
    repo_dir: str,
    log: Callable[[str], None],
    tail: Callable[[], list[str]],
) -> None:
    """Stream the helper output while this updater survives and record a failed outcome.

    On success compose stops this container, so this call never returns normally; the new
    process settles the state in `reconcile`.
    """
    runner(["docker", "logs", "-f", HELPER_CONTAINER], cwd=repo_dir, on_line=log)
    waited = runner(["docker", "wait", HELPER_CONTAINER], cwd=repo_dir)
    try:
        code = int(waited.output.strip()) if waited.returncode == 0 else 1
    except ValueError:
        code = 1
    # Exit 0 while still running means compose finished without replacing this container.
    message = (
        FAILED_MESSAGE
        if code != 0
        else f"Updater recreate finished but the updater was not replaced; run `{MANUAL_COMMAND}`"
    )
    log(f"FAILED: {message}")
    _record(state, state="failed", message=message, log_tail=tail())
    runner(["docker", "rm", "-f", HELPER_CONTAINER], cwd=repo_dir)


def reconcile(
    runner: Runner,
    state: StateStore,
    *,
    own_fingerprint: str | None,
    repo_dir: str,
) -> None:
    """Settle an attempt left `started` by a previous process (called at start-up)."""
    current: dict[str, Any] = state.get("self_update") or {}
    if current.get("state") != "started":
        return
    if own_fingerprint is not None and own_fingerprint == current.get("fingerprint"):
        _record(state, state="done", message=None)
    else:
        _record(state, state="failed", message=FAILED_MESSAGE)
    runner(["docker", "rm", "-f", HELPER_CONTAINER], cwd=repo_dir)
