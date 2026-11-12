"""Update check and apply orchestration (pure logic, injectable runner/clock/health)."""

from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .gate import blocked_message
from .repo import CHANNELS, GitError, Repo

if TYPE_CHECKING:
    from collections.abc import Callable

    from .runner import Runner
    from .state import StateStore

HEALTH_TIMEOUT_S = 300
HEALTH_POLL_S = 3
CHECK_MIN_INTERVAL_S = 10
LOG_TAIL_LINES = 40


@dataclass(frozen=True)
class Config:
    repo_dir: str
    state_dir: str
    db_path: str
    health_url: str
    service: str = "darkstar"


@dataclass(frozen=True)
class ApplyPlan:
    channel: str
    commit: str
    version: str
    ref: str


class ApplyRejected(Exception):
    """Apply refused before any change (dirty tree, DB gate, nothing to do)."""

    def __init__(self, message: str, files: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.files = files or []


class ApplyBusy(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def tree_digest(directory: str) -> str:
    """Stable digest over all files below `directory` (detects an outdated updater image)."""
    digest = hashlib.sha256()
    root = Path(directory)
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def fetch_running_version(url: str) -> str | None:
    """Version reported by the running Darkstar container, or None if unreachable."""
    import json

    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            value = json.loads(response.read()).get("version")
    except (OSError, ValueError):
        return None
    return str(value).lstrip("vV") if value else None


class Updater:
    def __init__(
        self,
        config: Config,
        runner: Runner,
        state: StateStore,
        *,
        running_version: Callable[[], str | None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        updater_digest: str | None = None,
    ) -> None:
        self.config = config
        self.repo = Repo(config.repo_dir, runner)
        self._runner = runner
        self.state = state
        self._running_version = running_version or (
            lambda: fetch_running_version(config.health_url)
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._updater_digest = updater_digest
        self._check_lock = threading.Lock()
        self._apply_lock = threading.Lock()
        self._last_check_started = float("-inf")
        self._log_lock = threading.Lock()

    # ---- log -------------------------------------------------------------
    def _log(self, line: str) -> None:
        with self._log_lock, self.state.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line.rstrip("\n") + "\n")

    def read_log(self, offset: int) -> tuple[str, int]:
        try:
            data = self.state.log_path.read_bytes()
        except OSError:
            return "", 0
        offset = max(0, min(offset, len(data)))
        return data[offset:].decode("utf-8", errors="replace"), len(data)

    def _log_tail(self) -> list[str]:
        text, _ = self.read_log(0)
        return text.splitlines()[-LOG_TAIL_LINES:]

    # ---- channel ---------------------------------------------------------
    def set_channel(self, channel: str) -> None:
        if channel not in CHANNELS:
            raise ValueError("channel must be 'dev' or 'stable'")
        if channel != self.state.channel:
            self.state.update(channel=channel, last_check=None)

    # ---- check -----------------------------------------------------------
    def check(self, *, force: bool = False) -> None:
        """Fetch and record the channel target. Rate limited unless `force`."""
        if self.apply_in_progress():
            return
        with self._check_lock:
            now = self._monotonic()
            if not force and now - self._last_check_started < CHECK_MIN_INTERVAL_S:
                return
            self._last_check_started = now
            channel = self.state.channel
            checked_at = _now()
            try:
                self.repo.fetch()
                target = self.repo.resolve_target(channel)
                if target is None:
                    raise GitError("No stable release found")
                head = self.repo.head()
                result: dict[str, Any] = {
                    "ok": True,
                    "at": checked_at,
                    "channel": channel,
                    "target": {
                        "commit": target.commit,
                        "version": target.version,
                        "ref": target.ref,
                    },
                    "commits": (
                        self.repo.commit_subjects(head, target.commit)
                        if channel == "dev" and target.commit != head
                        else []
                    ),
                    "blocked": blocked_message(
                        self.repo, self.config.db_path, target.commit, channel
                    ),
                }
                self.state.update(last_check=result, last_success_at=checked_at)
            except (GitError, ValueError) as exc:
                self.state.update(
                    last_check={
                        "ok": False,
                        "at": checked_at,
                        "channel": channel,
                        "error": str(exc),
                    }
                )

    # ---- status ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        channel = self.state.channel
        last: dict[str, Any] | None = self.state.get("last_check")
        if last and last.get("channel") != channel:
            last = None
        current: dict[str, Any] = {"version": None, "commit": None}
        dirty: list[str] = []
        try:
            head = self.repo.head()
            current = {"version": self.repo.current_version(), "commit": head}
            dirty = self.repo.dirty_files()
        except GitError as exc:
            last = {"ok": False, "at": _now(), "channel": channel, "error": str(exc)}
        target = last.get("target") if last and last.get("ok") else None
        available = bool(target and target["commit"] != current["commit"])
        return {
            "channel": channel,
            "current": current,
            "target": target,
            "update_available": available,
            "commits": (last or {}).get("commits", []) if available else [],
            "blocked": (last or {}).get("blocked") if available else None,
            "dirty_files": dirty,
            "last_check": last,
            "last_success_at": self.state.get("last_success_at"),
            "apply": self.state.get("apply") or {"state": "idle"},
            "updater_outdated": self._updater_outdated(),
        }

    def _updater_outdated(self) -> bool:
        if self._updater_digest is None:
            return False
        source = Path(self.config.repo_dir) / "updater"
        try:
            return tree_digest(str(source)) != self._updater_digest
        except OSError:
            return False

    # ---- apply -----------------------------------------------------------
    def apply_in_progress(self) -> bool:
        return self._apply_lock.locked()

    def mark_interrupted(self) -> None:
        apply: dict[str, Any] = self.state.get("apply") or {}
        if apply.get("state") in ("building", "restarting"):
            apply.update(state="failed", message="Updater restarted during the update")
            self.state.update(apply=apply)

    def begin_apply(self) -> ApplyPlan:
        """Acquire the single-flight lock and run the gates. Raises on refusal."""
        if not self._apply_lock.acquire(blocking=False):
            raise ApplyBusy
        try:
            files = self.repo.dirty_files()
            if files:
                raise ApplyRejected("Local changes to tracked files block the update", files)
            channel = self.state.channel
            target = self.repo.resolve_target(channel)
            if target is None:
                raise ApplyRejected("No stable release found")
            if target.commit == self.repo.head():
                raise ApplyRejected("Already up to date")
            blocked = blocked_message(self.repo, self.config.db_path, target.commit, channel)
            if blocked:
                raise ApplyRejected(blocked)
        except (ApplyRejected, GitError) as exc:
            self._apply_lock.release()
            if isinstance(exc, GitError):
                raise ApplyRejected(str(exc)) from exc
            raise
        return ApplyPlan(channel, target.commit, target.version, target.ref)

    def start_apply(self, *, threaded: bool = True) -> None:
        plan = self.begin_apply()
        self.state.log_path.write_text("")
        self._set_apply("building", f"Updating to {plan.version}", plan)
        if threaded:
            threading.Thread(target=self._run_apply, args=(plan,), daemon=True).start()
        else:
            self._run_apply(plan)

    def _set_apply(self, state: str, message: str, plan: ApplyPlan, **extra: Any) -> None:
        previous: dict[str, Any] = self.state.get("apply") or {}
        self.state.update(
            apply={
                "state": state,
                "message": message,
                "target_version": plan.version,
                "channel": plan.channel,
                "started_at": previous.get("started_at") or _now(),
                **extra,
            }
        )

    def _fail(self, plan: ApplyPlan, message: str) -> None:
        self._log(f"FAILED: {message}")
        self._set_apply("failed", message, plan, log_tail=self._log_tail())

    def _compose(self, *args: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--project-directory",
            self.config.repo_dir,
            *args,
        ]

    def _restore(self, prev_commit: str, prev_branch: str | None) -> None:
        try:
            if prev_branch:
                self.repo.run("checkout", "-f", "-B", prev_branch, prev_commit)
            else:
                self.repo.run("checkout", "-f", "--detach", prev_commit)
            self._log(f"Restored checkout to {prev_commit[:7]}")
        except GitError as exc:
            self._log(f"WARNING: could not restore previous checkout: {exc}")

    def _run_apply(self, plan: ApplyPlan) -> None:
        try:
            self._apply_steps(plan)
        except Exception as exc:
            self._fail(plan, f"Unexpected error: {exc}")
        finally:
            self._apply_lock.release()

    def _apply_steps(self, plan: ApplyPlan) -> None:
        prev_commit = self.repo.head()
        prev_branch = self.repo.current_branch()
        self._log(f"Checking out {plan.ref} ({plan.commit[:7]})")
        try:
            if plan.channel == "dev":
                self.repo.run("checkout", "main")
                self.repo.run("merge", "--ff-only", "origin/main")
            else:
                self.repo.run("checkout", "--detach", plan.ref)
        except GitError as exc:
            self._restore(prev_commit, prev_branch)
            self._fail(plan, str(exc))
            return

        env = {
            "DARKSTAR_VERSION": plan.version,
            "DARKSTAR_RELEASE_CHANNEL": plan.channel,
            "DARKSTAR_COMMIT": plan.commit[:7],
        }
        self._log(f"Building {self.config.service} (this can take several minutes)")
        built = self._runner(
            self._compose("build", self.config.service),
            cwd=self.config.repo_dir,
            env=env,
            on_line=self._log,
        )
        if built.returncode != 0:
            self._restore(prev_commit, prev_branch)
            self._fail(plan, "Build failed, the running version was left untouched")
            return

        self._log(f"Restarting {self.config.service}")
        started = self._runner(
            self._compose("up", "-d", "--no-deps", self.config.service),
            cwd=self.config.repo_dir,
            env=env,
            on_line=self._log,
        )
        if started.returncode != 0:
            self._fail(plan, "Starting the new container failed, see the log")
            return

        self._set_apply("restarting", f"Restarting on {plan.version}", plan)
        deadline = self._monotonic() + HEALTH_TIMEOUT_S
        while self._monotonic() < deadline:
            if self._running_version() == plan.version.lstrip("vV"):
                self._log("New version is up")
                self._set_apply("done", f"Updated to {plan.version}", plan)
                return
            self._sleep(HEALTH_POLL_S)
        self._fail(
            plan,
            "The new version did not become healthy within 5 minutes. "
            "Check `docker compose logs darkstar` and the updater log; the database may "
            "already be migrated, so no automatic rollback was done.",
        )
