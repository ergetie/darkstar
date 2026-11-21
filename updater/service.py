"""Update check and apply orchestration (pure logic, injectable runner/clock/health)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import db_restore, self_update
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


@dataclass(frozen=True)
class PreviousState:
    """What to return to when an apply has to be rolled back."""

    commit: str
    branch: str | None
    version: str
    channel: str
    started: float


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


def fingerprint(updater_dir: str, compose_file: str) -> str:
    """Digest of the updater source plus the compose file (what a recreate of the updater adopts)."""
    digest = hashlib.sha256()
    digest.update(tree_digest(updater_dir).encode())
    digest.update(Path(compose_file).read_bytes())
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
        updater_fingerprint: str | None = None,
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
        self._updater_fingerprint = updater_fingerprint
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
                warnings = self.repo.fetch()
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
                    "warnings": warnings,
                }
                self.state.update(last_check=result, last_success_at=checked_at)
                self._settle_completed_failure()
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
        recreate: dict[str, Any] = self.state.get("self_update") or {}
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
            "self_update": (
                {"state": recreate["state"], "message": recreate.get("message")}
                if recreate.get("state")
                else None
            ),
        }

    def _repo_fingerprint(self) -> str | None:
        """Fingerprint of the updater source and compose file currently in the repo."""
        repo = Path(self.config.repo_dir)
        try:
            return fingerprint(str(repo / "updater"), str(repo / "docker-compose.yml"))
        except OSError:
            return None

    def _updater_outdated(self) -> bool:
        if self._updater_fingerprint is None:
            return False
        current = self._repo_fingerprint()
        return current is not None and current != self._updater_fingerprint

    # ---- self update -----------------------------------------------------
    def _recreate_after_done(self) -> None:
        """Run the self-recreate once an apply is `done`; its failure never undoes the update."""
        try:
            self._maybe_recreate()
        except Exception as exc:  # the update itself succeeded: never turn it into failed
            self._log(f"WARNING: updater self-recreate failed: {exc}")

    def _maybe_recreate(self) -> None:
        """After a successful apply, recreate the updater once per changed fingerprint."""
        if not self._updater_outdated():
            return
        current = self._repo_fingerprint()
        attempted: dict[str, Any] = self.state.get("self_update") or {}
        if current is None or attempted.get("fingerprint") == current:
            return
        config = self.config
        if self_update.launch_recreate(
            self._runner,
            self.state,
            repo_dir=config.repo_dir,
            fingerprint=current,
            log=self._log,
        ):
            self_update.follow_helper(
                self._runner,
                self.state,
                repo_dir=config.repo_dir,
                log=self._log,
                tail=self._log_tail,
            )

    def reconcile_self_update(self) -> None:
        """Settle a recreate left `started` by the previous process (call at start-up)."""
        self_update.reconcile(
            self._runner,
            self.state,
            own_fingerprint=self._updater_fingerprint,
            repo_dir=self.config.repo_dir,
        )

    # ---- apply -----------------------------------------------------------
    def apply_in_progress(self) -> bool:
        return self._apply_lock.locked()

    def recover_interrupted(self, *, threaded: bool = True) -> None:
        """Settle an apply left `building`/`restarting` by the previous process (at start-up).

        The outcome is decided from the version the Darkstar container reports, not from the
        interruption: the apply may have finished (or never changed anything) while the updater
        was down. The apply lock is held until the decision is made, so checks and applies are
        refused meanwhile; the decision itself runs in a daemon thread to let the server start.
        """
        apply: dict[str, Any] = self.state.get("apply") or {}
        if apply.get("state") not in ("building", "restarting"):
            self._settle_completed_failure()
            return
        if not self._apply_lock.acquire(blocking=False):
            return
        try:
            plan = ApplyPlan(
                channel=str(apply.get("channel") or self.state.channel),
                commit="",
                version=str(apply.get("target_version") or ""),
                ref="",
            )
            self._log("Updater restarted during the update, checking its outcome")
            self._set_apply(
                "restarting", "Updater restarted, checking the outcome of the update", plan
            )
            previous = apply.get("previous")
            if threaded:
                threading.Thread(
                    target=self._run_recovery, args=(plan, previous), daemon=True
                ).start()
                return
        except BaseException:
            self._apply_lock.release()
            raise
        self._run_recovery(plan, previous)

    def _run_recovery(self, plan: ApplyPlan, previous: dict[str, Any] | None) -> None:
        try:
            self._decide_interrupted(plan, previous)
        except Exception as exc:
            # If even recording fails (state file unwritable) the lock must still be released.
            with contextlib.suppress(Exception):
                self._fail(plan, f"Unexpected error while recovering the update: {exc}")
        finally:
            self._apply_lock.release()

    def _decide_interrupted(self, plan: ApplyPlan, previous: dict[str, Any] | None) -> None:
        target = plan.version.lstrip("vV")
        # Without a recorded commit there is nothing safe to restore.
        restorable = previous if previous and previous.get("commit") else None
        old_version = str((restorable or {}).get("version") or "").lstrip("vV")
        old_seen = 0
        deadline = self._monotonic() + HEALTH_TIMEOUT_S
        while self._monotonic() < deadline:
            running = self._running_version()
            if target and running == target:
                self._log("New version is up")
                self._set_apply("done", f"Updated to {plan.version}", plan)
                self._recreate_after_done()
                return
            # Two consecutive polls: an interrupted `up` may still be stopping the old container.
            old_seen = old_seen + 1 if old_version and running == old_version else 0
            if restorable and old_seen >= 2:
                self._restore_interrupted(plan, restorable)
                return
            self._sleep(HEALTH_POLL_S)
        self._fail(
            plan,
            "Update was interrupted and Darkstar did not report the expected version; "
            f"the checkout was left untouched. {self._manual_restore_hint(None)}",
        )

    def _restore_interrupted(self, plan: ApplyPlan, previous: dict[str, Any]) -> None:
        commit = str(previous["commit"])
        branch = previous.get("branch")
        if self._restore(commit, branch):
            self._fail(plan, "Update was interrupted; nothing changed, safe to retry")
            return
        if branch:
            command = f"git checkout -f -B {branch} {commit}"
        else:
            command = f"git checkout -f --detach {commit}"
        self._fail(
            plan,
            "Update was interrupted and the checkout could not be restored. "
            f"To restore it manually: cd {self.config.repo_dir} && {command}",
        )

    def _settle_completed_failure(self) -> None:
        """Drop a stale failed apply whose target is the version now installed.

        An updater restart mid-apply is recorded as failed even when the apply went on to
        finish; the running container then already reports the target and the failure is
        noise. The check uses the version the live container reports, not the checkout: the
        checkout moves to the target before the build, so an apply killed mid-build leaves the
        repo at the target while the old version keeps running. A genuine failure, or an
        unreachable container, leaves the record untouched.
        """
        apply: dict[str, Any] = self.state.get("apply") or {}
        target = apply.get("target_version")
        if apply.get("state") != "failed" or not target:
            return
        running = self._running_version()
        if running is not None and running == str(target).lstrip("vV"):
            self.state.update(apply={"state": "idle"})

    def begin_apply(self) -> ApplyPlan:
        """Acquire the single-flight lock and run the gates. Raises on refusal."""
        if not self._apply_lock.acquire(blocking=False):
            raise ApplyBusy
        try:
            self.repo.assert_origin()
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
            head = self.repo.head()
            if channel == "dev":
                if not self.repo.is_ancestor(head, target.commit):
                    raise ApplyRejected(
                        "Dev branch history diverged, refusing non-fast-forward update"
                    )
            elif self.repo.current_branch() is None and self.repo.is_ancestor(target.commit, head):
                # Detached HEAD is a stable install; a dev install (on a branch) may switch freely.
                raise ApplyRejected("Target is older than the installed version")
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
        prior: dict[str, Any] = self.state.get("apply") or {}
        record: dict[str, Any] = {
            "state": state,
            "message": message,
            "target_version": plan.version,
            "channel": plan.channel,
            "started_at": prior.get("started_at") or _now(),
            **extra,
        }
        # The previous state lets a restarted updater recover; it is moot once the apply ended.
        carried = record.pop("previous", None) or prior.get("previous")
        if carried and state not in ("done", "failed"):
            record["previous"] = carried
        self.state.update(apply=record)

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

    def _restore(self, prev_commit: str, prev_branch: str | None) -> bool:
        try:
            if prev_branch:
                self.repo.run("checkout", "-f", "-B", prev_branch, prev_commit)
            else:
                self.repo.run("checkout", "-f", "--detach", prev_commit)
            self._log(f"Restored checkout to {prev_commit[:7]}")
        except GitError as exc:
            self._log(f"WARNING: could not restore previous checkout: {exc}")
            return False
        return True

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
        # Dev runs on a branch, stable on a detached tag (matches how apply checks out).
        prev = PreviousState(
            commit=prev_commit,
            branch=prev_branch,
            version=self.repo.current_version(),
            channel="dev" if prev_branch else "stable",
            started=time.time(),
        )
        # Persisted before the first checkout change so a restarted updater can recover.
        self._set_apply(
            "building",
            f"Updating to {plan.version}",
            plan,
            previous={
                "commit": prev.commit,
                "branch": prev.branch,
                "version": prev.version,
                "channel": prev.channel,
            },
        )
        self._log(f"Checking out {plan.ref} ({plan.commit[:7]})")
        try:
            if plan.channel == "dev":
                self.repo.run("checkout", "main")
                self.repo.run("merge", "--ff-only", plan.commit)
            else:
                self.repo.run("checkout", "--detach", plan.commit)
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
            self._rollback(plan, prev, "starting the new container failed")
            return

        self._set_apply("restarting", f"Restarting on {plan.version}", plan)
        if self._wait_for_version(plan.version):
            self._log("New version is up")
            self._set_apply("done", f"Updated to {plan.version}", plan)
            self._recreate_after_done()
            return
        self._rollback(plan, prev, "the new version did not become healthy within 5 minutes")

    def _wait_for_version(self, version: str) -> bool:
        deadline = self._monotonic() + HEALTH_TIMEOUT_S
        while self._monotonic() < deadline:
            if self._running_version() == version.lstrip("vV"):
                return True
            self._sleep(HEALTH_POLL_S)
        return False

    # ---- rollback --------------------------------------------------------
    def _manual_restore_hint(self, backup: Path | None) -> str:
        """Host-side commands (the repo is mounted at its host path, `data` sits inside it)."""
        repo = self.config.repo_dir
        if backup is None:
            return f"Check `docker compose logs {self.config.service}` in {repo}."
        db = Path(self.config.db_path).name
        return (
            f"Backup: {backup.name} (in {repo}/data/{db_restore.BACKUP_DIR_NAME}). To restore it "
            f"manually: cd {repo} && docker compose stop {self.config.service} && "
            f"cp data/{db_restore.BACKUP_DIR_NAME}/{backup.name} data/{db} && "
            f"rm -f data/{db}-wal data/{db}-shm && docker compose up -d {self.config.service}"
        )

    def _rollback(self, plan: ApplyPlan, prev: PreviousState, reason: str) -> None:
        """Return to the previous version after a failed start; report what could (not) be done."""
        failure = f"Update to {plan.version} failed ({reason})."
        self._set_apply("restarting", f"Rolling back to {prev.version}", plan)
        self._log(f"Rolling back to {prev.version}: {reason}")
        backup: Path | None = None
        try:
            backup = db_restore.find_backup(self.config.db_path, prev.started)
        except OSError as exc:
            self._log(f"WARNING: could not look for a database backup: {exc}")

        def abort(problem: str) -> None:
            self._fail(
                plan,
                f"{failure} Automatic rollback failed: {problem}. "
                f"{self._manual_restore_hint(backup)}",
            )

        stopped = self._runner(
            self._compose("stop", self.config.service),
            cwd=self.config.repo_dir,
            on_line=self._log,
        )
        if stopped.returncode != 0:
            abort(f"could not stop {self.config.service}")
            return

        database = "The database was unchanged."
        if backup is not None:
            if os.access(Path(self.config.db_path).parent, os.W_OK):
                try:
                    db_restore.restore(self.config.db_path, backup)
                except (OSError, db_restore.RestoreError) as exc:
                    abort(f"database restore failed ({exc})")
                    return
                self._log(f"Restored database from {backup.name}")
                database = "The database backup was restored."
            else:
                self._log("Data directory is read-only, database not restored")
                database = (
                    "The database was NOT restored because the updater's data directory is "
                    f"read-only. {self._manual_restore_hint(backup)}"
                )

        if not self._restore(prev.commit, prev.branch):
            abort("could not restore the previous checkout")
            return
        env = {
            "DARKSTAR_VERSION": prev.version,
            "DARKSTAR_RELEASE_CHANNEL": prev.channel,
            "DARKSTAR_COMMIT": prev.commit[:7],
        }
        self._log(f"Rebuilding {self.config.service} {prev.version}")
        for args in (("build",), ("up", "-d", "--no-deps")):
            result = self._runner(
                self._compose(*args, self.config.service),
                cwd=self.config.repo_dir,
                env=env,
                on_line=self._log,
            )
            if result.returncode != 0:
                abort(f"`docker compose {args[0]}` failed for the previous version")
                return
        if not self._wait_for_version(prev.version):
            abort(f"the previous version {prev.version} did not become healthy")
            return
        self._fail(plan, f"{failure} Rolled back to {prev.version}. {database}")
