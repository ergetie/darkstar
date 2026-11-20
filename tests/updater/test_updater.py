"""Updater tests: real git on local temp repos (no network), fake docker, fake health."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import sqlite3
import subprocess
import threading
import types
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

import pytest

from updater.runner import CommandResult, run_command
from updater.server import main, make_handler
from updater.service import ApplyBusy, ApplyRejected, Config, Updater, fingerprint
from updater.state import StateStore

if TYPE_CHECKING:
    from pathlib import Path

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
TOKEN = "s3cret-token"
PINNED_URL = "https://github.com/ergetie/darkstar.git"


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def commit(work: Path, version: str, revision: str | None = None) -> str:
    (work / "VERSION").write_text(version + "\n")
    if revision:
        versions = work / "alembic" / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        (versions / f"{revision}.py").write_text(f'revision: str = "{revision}"\n')
    git(work, "add", "-A")
    git(work, "commit", "-m", f"change {version}")
    return git(work, "rev-parse", "HEAD")


class FakeDocker:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.fail_build = False
        self.fail_up_first = 0  # number of leading `up` calls that return non-zero
        self.fail_stop = False
        self.on_up: Any = None  # called on every `up` (simulates the new container migrating)

    def __call__(
        self,
        argv: Any,
        *,
        cwd: str | None = None,
        env: Any = None,
        on_line: Any = None,
        user: int | None = None,
        group: int | None = None,
    ) -> CommandResult:
        argv = list(argv)
        if argv[0] == "docker":
            self.calls.append((argv, dict(env or {})))
            if on_line:
                on_line("fake docker output")
            if "up" in argv:
                if self.on_up:
                    self.on_up()
                if self.fail_up_first > 0:
                    self.fail_up_first -= 1
                    return CommandResult(1, "")
            if "stop" in argv and self.fail_stop:
                return CommandResult(1, "")
            return CommandResult(1 if self.fail_build and "build" in argv else 0, "")
        assert argv[0] == "git", f"unexpected command {argv[0]}"
        return run_command(argv, cwd=cwd, env={**GIT_ENV, **(env or {})}, on_line=on_line)


class Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.origin = tmp_path / "origin.git"
        self.work = tmp_path / "work"
        self.pusher = tmp_path / "pusher"
        git(tmp_path, "init", "--bare", "-b", "main", str(self.origin))
        git(tmp_path, "clone", str(self.origin), str(self.pusher))
        git(self.pusher, "checkout", "-b", "main")
        commit(self.pusher, "dev-260101.0000", "rev_a")
        git(self.pusher, "tag", "v1.0.0")
        commit(self.pusher, "dev-260102.0000", "rev_b")
        git(self.pusher, "push", "origin", "main", "--tags")
        git(tmp_path, "clone", "-b", "main", str(self.origin), str(self.work))
        self._redirect: Path | None = None
        self.point_origin_at(self.origin)
        self.docker = FakeDocker()
        self.db = tmp_path / "planner_learning.db"
        self.running = "dev-260102.0000"
        self.updater = Updater(
            Config(
                repo_dir=str(self.work),
                state_dir=str(tmp_path / "state"),
                db_path=str(self.db),
                health_url="http://unused.invalid",
            ),
            self.docker,
            StateStore(str(tmp_path / "state"), "dev"),
            running_version=lambda: self.running,
            sleep=lambda _s: None,
        )

    def point_origin_at(self, remote: Path) -> None:
        """Keep the pinned GitHub URL as origin; redirect it to a local bare repo (no network)."""
        git(self.work, "remote", "set-url", "origin", PINNED_URL)
        if self._redirect is not None:
            git(self.work, "config", "--unset-all", f"url.{self._redirect}.insteadOf")
        self._redirect = remote
        git(self.work, "config", f"url.{remote}.insteadOf", PINNED_URL)

    def push_dev(self, version: str) -> str:
        sha = commit(self.pusher, version)
        git(self.pusher, "push", "origin", "main")
        return sha

    def set_db_revision(self, revision: str) -> None:
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
        conn.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        conn.commit()
        conn.close()


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def test_stable_tag_prerelease_sorts_below_final(fx: Fixture) -> None:
    for tag in ("v2.7.1-beta", "v2.7.1", "v2.7.0", "v2.7.2-beta"):
        git(fx.pusher, "tag", tag)
    git(fx.pusher, "push", "origin", "--tags")
    fx.updater.repo.fetch()
    assert fx.updater.repo.latest_stable_tag() == "v2.7.2-beta"
    git(fx.pusher, "tag", "v2.7.2")
    git(fx.pusher, "push", "origin", "--tags")
    fx.updater.repo.fetch()
    assert fx.updater.repo.latest_stable_tag() == "v2.7.2"


def test_dev_up_to_date_then_behind(fx: Fixture) -> None:
    fx.updater.check(force=True)
    assert fx.updater.status()["update_available"] is False

    sha = fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    status = fx.updater.status()
    assert status["update_available"] is True
    assert status["target"]["commit"] == sha
    assert status["target"]["version"] == "dev-260103.0000"
    assert status["commits"] == ["change dev-260103.0000"]
    assert status["current"]["version"] == "dev-260102.0000"


def test_default_channel_and_stable_target(fx: Fixture) -> None:
    assert fx.updater.state.channel == "dev"
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    status = fx.updater.status()
    assert status["target"]["version"] == "1.0.0"
    assert status["update_available"] is True  # older tag still offered (DB gate decides)
    with pytest.raises(ValueError, match="channel"):
        fx.updater.set_channel("refs/heads/evil")


def test_check_is_rate_limited(fx: Fixture) -> None:
    fx.updater.check()
    fx.push_dev("dev-260103.0000")
    fx.updater.check()  # within 10 s of the first one: served from cache
    assert fx.updater.status()["update_available"] is False
    fx.updater.check(force=True)
    assert fx.updater.status()["update_available"] is True


def test_offline_fetch_reports_error_and_offers_nothing(fx: Fixture) -> None:
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    assert fx.updater.status()["update_available"] is True
    fx.point_origin_at(fx.origin.with_name("origin.git.gone"))
    fx.updater.check(force=True)
    status = fx.updater.status()
    assert status["update_available"] is False
    assert status["last_check"]["ok"] is False
    assert "fetch" in status["last_check"]["error"]
    assert status["last_success_at"] is not None


def test_stable_blocked_by_db_gate(fx: Fixture) -> None:
    fx.set_db_revision("rev_b")  # v1.0.0 only has rev_a
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    status = fx.updater.status()
    assert status["blocked"] == "Stable doesn't include your database version yet"
    with pytest.raises(ApplyRejected, match="database version"):
        fx.updater.begin_apply()
    assert not fx.updater.apply_in_progress()


def test_empty_or_absent_db_passes_gate(fx: Fixture) -> None:
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    assert fx.updater.status()["blocked"] is None


def test_dirty_tree_refused_with_file_list(fx: Fixture) -> None:
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    (fx.work / "VERSION").write_text("local edit\n")
    (fx.work / "untracked.txt").write_text("ignored by the gate")
    with pytest.raises(ApplyRejected) as err:
        fx.updater.begin_apply()
    assert err.value.files == ["VERSION"]
    assert fx.docker.calls == []


def test_apply_success_builds_then_restarts(fx: Fixture) -> None:
    sha = fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    fx.running = "dev-260103.0000"
    fx.updater.start_apply(threaded=False)

    assert git(fx.work, "rev-parse", "HEAD") == sha
    build, up = fx.docker.calls
    assert build[0][-2:] == ["build", "darkstar"]
    assert build[1]["DARKSTAR_VERSION"] == "dev-260103.0000"
    assert build[1]["DARKSTAR_RELEASE_CHANNEL"] == "dev"
    assert up[0][-4:] == ["up", "-d", "--no-deps", "darkstar"]
    assert fx.updater.status()["apply"]["state"] == "done"
    text, offset = fx.updater.read_log(0)
    assert "fake docker output" in text
    assert fx.updater.read_log(offset)[0] == ""
    assert not fx.updater.apply_in_progress()


def test_stable_apply_detaches_at_tag(fx: Fixture) -> None:
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    fx.running = "1.0.0"
    fx.updater.start_apply(threaded=False)
    assert git(fx.work, "rev-parse", "HEAD") == git(fx.work, "rev-parse", "v1.0.0^{commit}")
    assert fx.docker.calls[0][1]["DARKSTAR_RELEASE_CHANNEL"] == "stable"
    assert fx.updater.status()["current"]["version"] == "1.0.0"


def test_dev_refuses_diverged_history_before_checkout(fx: Fixture) -> None:
    local = commit(fx.work, "dev-local.0000")
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    with pytest.raises(ApplyRejected, match="Dev branch history diverged"):
        fx.updater.begin_apply()
    assert git(fx.work, "rev-parse", "HEAD") == local
    assert fx.docker.calls == []
    assert not fx.updater.apply_in_progress()


def test_stable_refuses_older_target(fx: Fixture) -> None:
    git(fx.work, "checkout", "--detach", "origin/main")
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    with pytest.raises(ApplyRejected, match="Target is older than the installed version"):
        fx.updater.begin_apply()
    assert git(fx.work, "rev-parse", "HEAD") == git(fx.work, "rev-parse", "origin/main")
    assert fx.docker.calls == []
    assert not fx.updater.apply_in_progress()


def test_dev_to_stable_switch_is_allowed_to_older_tag(fx: Fixture) -> None:
    assert git(fx.work, "symbolic-ref", "--short", "HEAD") == "main"
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    fx.running = "1.0.0"
    fx.updater.start_apply(threaded=False)
    assert git(fx.work, "rev-parse", "HEAD") == git(fx.work, "rev-parse", "v1.0.0^{commit}")
    assert fx.updater.status()["apply"]["state"] == "done"


def test_apply_installs_resolved_commit_after_tag_moves(fx: Fixture) -> None:
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    fx.running = "1.0.0"
    plan = fx.updater.begin_apply()
    assert plan.commit == git(fx.work, "rev-parse", "v1.0.0^{commit}")
    # the tag moves between the gates and the checkout
    git(fx.work, "tag", "-f", "v1.0.0", "origin/main")
    fx.updater._run_apply(plan)  # type: ignore[reportPrivateUsage]
    assert git(fx.work, "rev-parse", "HEAD") == plan.commit
    assert plan.commit != git(fx.work, "rev-parse", "origin/main")


def test_build_failure_restores_checkout_and_leaves_container(fx: Fixture) -> None:
    before = git(fx.work, "rev-parse", "HEAD")
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    fx.docker.fail_build = True
    fx.updater.start_apply(threaded=False)

    assert git(fx.work, "rev-parse", "HEAD") == before
    assert git(fx.work, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert len(fx.docker.calls) == 1  # no `up`
    apply = fx.updater.status()["apply"]
    assert apply["state"] == "failed"
    assert "untouched" in apply["message"]
    assert "fake docker output" in "\n".join(apply["log_tail"])


def _verbs(fx: Fixture) -> list[str]:
    known = ("stop", "build", "up")
    return [next(v for v in known if v in argv) for argv, _ in fx.docker.calls]


def _fast_clock(fx: Fixture) -> None:
    clock = iter(range(0, 100_000, 100))
    fx.updater._monotonic = lambda: float(next(clock))  # type: ignore[reportPrivateUsage]


def _make_db(path: Path, value: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("DELETE FROM t")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()


def _db_value(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT v FROM t").fetchone()[0]
    finally:
        conn.close()


def _simulate_migration(fx: Fixture, name: str = "pre-migration-20260101T000000Z-rev_b.db") -> Path:
    """Live DB holds the old content; on `up` the new container backs it up, then 'migrates'."""
    _make_db(fx.db, "old")
    backup = fx.db.parent / "backups" / name

    def on_up() -> None:
        if not backup.exists():  # only the first `up` is the new version's
            backup.parent.mkdir(exist_ok=True)
            shutil.copyfile(fx.db, backup)
            _make_db(fx.db, "migrated")
            fx.db.with_name(fx.db.name + "-wal").write_text("stale")

    fx.docker.on_up = on_up
    return backup


def _unhealthy_apply(fx: Fixture) -> str:
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    _fast_clock(fx)
    fx.updater.start_apply(threaded=False)  # running version never becomes the target
    apply = fx.updater.status()["apply"]
    assert apply["state"] == "failed"
    return str(apply["message"])


def test_unhealthy_after_up_rolls_back(fx: Fixture) -> None:
    before = git(fx.work, "rev-parse", "HEAD")
    message = _unhealthy_apply(fx)

    assert git(fx.work, "rev-parse", "HEAD") == before
    assert git(fx.work, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _verbs(fx) == ["build", "up", "stop", "build", "up"]
    rebuild_env = fx.docker.calls[3][1]
    assert rebuild_env["DARKSTAR_VERSION"] == "dev-260102.0000"
    assert rebuild_env["DARKSTAR_RELEASE_CHANNEL"] == "dev"
    assert rebuild_env["DARKSTAR_COMMIT"] == before[:7]
    assert fx.docker.calls[4][1] == rebuild_env
    assert "Rolled back to dev-260102.0000" in message
    assert "database was unchanged" in message
    assert "no automatic rollback" not in message
    assert not fx.updater.apply_in_progress()


def test_stable_rollback_uses_previous_channel(fx: Fixture) -> None:
    git(fx.work, "checkout", "--detach", "v1.0.0")
    fx.running = "1.0.0"
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    _fast_clock(fx)
    fx.updater.start_apply(threaded=False)
    assert fx.docker.calls[3][1]["DARKSTAR_RELEASE_CHANNEL"] == "stable"
    assert fx.docker.calls[3][1]["DARKSTAR_VERSION"] == "1.0.0"
    assert git(fx.work, "rev-parse", "HEAD") == git(fx.work, "rev-parse", "v1.0.0^{commit}")


def test_start_failure_rolls_back(fx: Fixture) -> None:
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    fx.docker.fail_up_first = 1
    fx.updater.start_apply(threaded=False)

    assert _verbs(fx) == ["build", "up", "stop", "build", "up"]
    apply = fx.updater.status()["apply"]
    assert apply["state"] == "failed"
    assert "starting the new container failed" in apply["message"]
    assert "Rolled back to dev-260102.0000" in apply["message"]


def test_migrated_db_is_restored(fx: Fixture) -> None:
    backup = _simulate_migration(fx)
    message = _unhealthy_apply(fx)

    assert _db_value(fx.db) == "old"
    assert not fx.db.with_name(fx.db.name + "-wal").exists()
    assert backup.exists()
    assert "database backup was restored" in message


def test_no_backup_leaves_db_untouched(fx: Fixture) -> None:
    _make_db(fx.db, "old")
    message = _unhealthy_apply(fx)

    assert _db_value(fx.db) == "old"
    assert "database was unchanged" in message


def test_backup_older_than_apply_is_ignored(fx: Fixture) -> None:
    _make_db(fx.db, "live")
    backups = fx.db.parent / "backups"
    backups.mkdir()
    stale = backups / "pre-migration-20250101T000000Z-x.db"
    shutil.copyfile(fx.db, stale)
    os.utime(stale, (1, 1))
    _make_db(fx.db, "kept")
    _unhealthy_apply(fx)
    assert _db_value(fx.db) == "kept"


def test_build_failure_has_no_rollback(fx: Fixture) -> None:
    fx.docker.fail_build = True
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    fx.updater.start_apply(threaded=False)
    assert _verbs(fx) == ["build"]  # no stop, no up


def test_restore_error_reports_backup_and_manual_command(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = _simulate_migration(fx)

    def boom(_db: str, _backup: Path) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr("updater.db_restore.restore", boom)
    message = _unhealthy_apply(fx)

    assert "database restore failed (disk on fire)" in message
    assert backup.name in message
    assert "cp data/backups/" in message
    assert _verbs(fx) == ["build", "up", "stop"]  # no rebuild, no retry loop


def test_corrupt_backup_aborts_rollback(fx: Fixture) -> None:
    backup = _simulate_migration(fx)
    fx.docker.on_up = lambda: (
        backup.parent.mkdir(exist_ok=True),
        backup.write_bytes(b"not a database" * 100),
    )
    message = _unhealthy_apply(fx)
    assert "Automatic rollback failed" in message
    assert backup.name in message
    assert _verbs(fx) == ["build", "up", "stop"]


def test_rollback_stop_failure_is_reported(fx: Fixture) -> None:
    fx.docker.fail_stop = True
    message = _unhealthy_apply(fx)
    assert "could not stop darkstar" in message
    assert _verbs(fx) == ["build", "up", "stop"]


def test_previous_version_unhealthy_after_rollback(fx: Fixture) -> None:
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    fx.running = "something-else"
    _fast_clock(fx)
    fx.updater.start_apply(threaded=False)
    apply = fx.updater.status()["apply"]
    assert apply["state"] == "failed"
    assert "Automatic rollback failed" in apply["message"]
    assert "dev-260102.0000 did not become healthy" in apply["message"]
    assert _verbs(fx) == ["build", "up", "stop", "build", "up"]  # one attempt only


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_read_only_data_dir_skips_restore(fx: Fixture) -> None:
    data = fx.db.parent / "ro"
    data.mkdir()
    fx.db = data / "planner_learning.db"
    fx.updater.config = types.SimpleNamespace(**{**vars(fx.updater.config), "db_path": str(fx.db)})  # type: ignore[assignment]
    backup = _simulate_migration(fx)
    # the migration step runs before the mount turns read-only in this simulation
    original = fx.docker.on_up

    def on_up() -> None:
        original()
        data.chmod(0o555)

    fx.docker.on_up = on_up
    try:
        message = _unhealthy_apply(fx)
    finally:
        data.chmod(0o755)
    assert _db_value(fx.db) == "migrated"
    assert "NOT restored" in message
    assert backup.name in message
    assert "Rolled back to dev-260102.0000" in message
    assert _verbs(fx) == ["build", "up", "stop", "build", "up"]


def test_single_flight(fx: Fixture) -> None:
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    fx.updater.begin_apply()
    with pytest.raises(ApplyBusy):
        fx.updater.begin_apply()


def test_interrupted_apply_marked_failed(fx: Fixture) -> None:
    fx.updater.state.update(apply={"state": "building"})
    fx.updater.mark_interrupted()
    assert fx.updater.state.get("apply")["state"] == "failed"


@pytest.fixture
def server(fx: Fixture):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fx.updater, TOKEN))
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield fx, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def request(
    port: int, method: str, path: str, body: dict[str, Any] | None = None, token: str | None = TOKEN
) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    conn.request(method, path, json.dumps(body) if body is not None else None, headers)
    response = conn.getresponse()
    data = json.loads(response.read())
    conn.close()
    return response.status, data


@pytest.mark.parametrize("token", [None, "", "wrong"])
def test_bad_token_is_401_and_does_nothing(server: tuple[Fixture, int], token: str | None) -> None:
    fx, port = server
    before = fx.updater.state.channel
    for method, path in [("GET", "/status"), ("POST", "/apply"), ("PUT", "/channel")]:
        status, _ = request(port, method, path, {"channel": "stable"}, token=token)
        assert status == 401
    assert fx.updater.state.channel == before
    assert fx.docker.calls == []


def test_routes_and_ref_injection_ignored(server: tuple[Fixture, int]) -> None:
    fx, port = server
    status, data = request(port, "PUT", "/channel", {"channel": "stable", "ref": "evil; rm -rf /"})
    assert status == 200 and data["channel"] == "stable"
    assert data["target"]["ref"] == "v1.0.0"

    status, _ = request(port, "PUT", "/channel", {"channel": "../../etc"})
    assert status == 400

    fx.updater.set_channel("dev")
    fx.push_dev("dev-260103.0000")
    request(port, "PUT", "/channel", {"channel": "dev"})
    fx.updater.check(force=True)
    status, data = request(port, "POST", "/apply", {"ref": "HEAD~5", "cmd": "id", "commit": "x"})
    assert status == 202
    assert data["apply"]["target_version"] == "dev-260103.0000"
    assert request(port, "GET", "/nope")[0] == 404
    status, data = request(port, "GET", "/log?offset=0")
    assert status == 200 and "offset" in data


def test_refuses_to_start_with_empty_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARKSTAR_UPDATER_TOKEN", "")
    monkeypatch.setenv("DARKSTAR_REPO_DIR", "/nonexistent")
    assert main() == 1


@pytest.mark.parametrize(("uid", "gid", "dropped"), [(1234, 5678, True), (0, 0, False)])
def test_git_runs_as_repo_owner(
    monkeypatch: pytest.MonkeyPatch, uid: int, gid: int, dropped: bool
) -> None:
    from updater import repo as repo_module

    seen: list[dict[str, Any]] = []

    def runner(argv: Any, **kwargs: Any) -> CommandResult:
        seen.append(kwargs)
        return CommandResult(0, "abc\n")

    monkeypatch.setattr(
        repo_module.Path, "stat", lambda _p: types.SimpleNamespace(st_uid=uid, st_gid=gid)
    )
    repo_module.Repo("/repo", runner).head()
    assert seen[0]["user"] == (uid if dropped else None)
    assert seen[0]["group"] == (gid if dropped else None)
    assert seen[0]["cwd"] == "/repo"


def test_git_rewrites_ssh_github_urls_to_https_and_never_prompts(tmp_path: Path) -> None:
    from updater.repo import Repo

    seen: list[tuple[list[str], Any]] = []

    def runner(argv: Any, **kwargs: Any) -> CommandResult:
        seen.append((list(argv), kwargs["env"]))
        return CommandResult(0, "git@github.com:ergetie/darkstar.git\n")

    Repo(str(tmp_path), runner).fetch()
    argv, env = next(c for c in seen if "fetch" in c[0])
    assert "url.https://github.com/.insteadOf=git@github.com:" in argv
    assert "url.https://github.com/.insteadOf=ssh://git@github.com/" in argv
    assert argv.index("fetch") > max(i for i, a in enumerate(argv) if a == "-c")
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_fetch_never_forces_or_prunes_tags(tmp_path: Path) -> None:
    from updater.repo import Repo

    seen: list[list[str]] = []

    def runner(argv: Any, **kwargs: Any) -> CommandResult:
        seen.append(list(argv))
        return CommandResult(0, PINNED_URL)

    Repo(str(tmp_path), runner).fetch()
    fetch = next(c for c in seen if "fetch" in c)
    assert fetch[fetch.index("fetch") :] == ["fetch", "--prune", "--tags", "origin"]


def test_foreign_origin_gives_check_error_and_never_fetches(fx: Fixture) -> None:
    calls: list[list[str]] = []
    real = fx.docker

    def spy(argv: Any, **kwargs: Any) -> CommandResult:
        calls.append(list(argv))
        return real(argv, **kwargs)

    fx.updater.repo._runner = spy  # type: ignore[reportPrivateUsage]
    git(fx.work, "remote", "set-url", "origin", "https://github.com/evil/darkstar.git")
    fx.updater.check(force=True)
    last = fx.updater.status()["last_check"]
    assert last["ok"] is False
    assert last["error"] == "Origin is not github.com/ergetie/darkstar"
    assert not any("fetch" in c for c in calls)


def test_foreign_origin_rejects_apply(fx: Fixture) -> None:
    fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    git(fx.work, "remote", "set-url", "origin", "https://github.com/evil/darkstar.git")
    with pytest.raises(ApplyRejected, match=r"Origin is not github\.com/ergetie/darkstar"):
        fx.updater.begin_apply()
    assert not fx.updater.apply_in_progress()


def test_moved_tag_keeps_local_tag_and_warns(fx: Fixture) -> None:
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    old = git(fx.work, "rev-parse", "v1.0.0^{commit}")
    git(fx.pusher, "tag", "-f", "v1.0.0", commit(fx.pusher, "dev-260103.0000"))
    git(fx.pusher, "push", "origin", "main")
    git(fx.pusher, "push", "-f", "origin", "v1.0.0")
    fx.updater.check(force=True)
    last = fx.updater.status()["last_check"]
    assert last["ok"] is True
    assert last["warnings"] == ["Tag v1.0.0 changed upstream; keeping the local tag"]
    assert last["target"]["commit"] == old
    assert git(fx.work, "rev-parse", "v1.0.0^{commit}") == old
    # branches still advanced despite the rejected tag
    assert git(fx.work, "rev-parse", "origin/main") == git(fx.pusher, "rev-parse", "HEAD")


def test_deleted_upstream_tag_stays_local(fx: Fixture) -> None:
    git(fx.pusher, "tag", "v1.1.0")
    git(fx.pusher, "push", "origin", "v1.1.0")
    fx.updater.set_channel("stable")
    fx.updater.check(force=True)
    assert fx.updater.status()["target"]["version"] == "1.1.0"
    git(fx.pusher, "push", "origin", ":refs/tags/v1.1.0")
    fx.updater.check(force=True)
    last = fx.updater.status()["last_check"]
    assert last["ok"] is True
    assert last["warnings"] == []
    assert last["target"]["version"] == "1.1.0"
    assert git(fx.work, "tag", "--list", "v1.1.0") == "v1.1.0"


def test_other_fetch_failure_is_still_an_error(fx: Fixture) -> None:
    fx.point_origin_at(fx.origin.with_name("origin.git.gone"))
    fx.updater.check(force=True)
    last = fx.updater.status()["last_check"]
    assert last["ok"] is False
    assert "fetch" in last["error"]


# ---- updater self-recreate -------------------------------------------------------------------
IMAGE_ID = "sha256:" + "ab" * 32


class SelfUpdateDocker(FakeDocker):
    """FakeDocker that also answers the helper-container commands."""

    def __init__(self) -> None:
        super().__init__()
        self.helper_exit = "0"
        self.helper_logs = ["helper: building"]
        self.inspect_rc = 0

    def __call__(self, argv: Any, **kwargs: Any) -> CommandResult:
        argv = list(argv)
        if argv[0] == "docker" and argv[1] in ("rm", "inspect", "run", "logs", "wait"):
            self.calls.append((argv, {}))
            if argv[1] == "inspect":
                return CommandResult(self.inspect_rc, IMAGE_ID + "\n")
            if argv[1] == "logs":
                for line in self.helper_logs:
                    kwargs["on_line"](line)
            if argv[1] == "wait":
                return CommandResult(0, self.helper_exit + "\n")
            return CommandResult(0, "")
        return super().__call__(argv, **kwargs)


def _helper_verbs(fx: Fixture) -> list[str]:
    return [a[1] for a, _ in fx.docker.calls if a[1] in ("rm", "inspect", "run", "logs", "wait")]


@pytest.fixture
def su(tmp_path: Path) -> Fixture:
    """Fixture whose repo carries `updater/` and `docker-compose.yml`, baked fingerprint set."""
    fx = Fixture(tmp_path)
    fx.docker = SelfUpdateDocker()
    fx.updater._runner = fx.docker  # type: ignore[reportPrivateUsage]
    fx.updater.repo._runner = fx.docker  # type: ignore[reportPrivateUsage]
    _push_files(fx, "dev-260102.1000", {"updater/a.py": "a = 1\n", "docker-compose.yml": "v: 1\n"})
    git(fx.work, "pull", "--ff-only", "origin", "main")
    fx.running = "dev-260102.1000"
    fx.updater._updater_fingerprint = fingerprint(  # type: ignore[reportPrivateUsage]
        str(fx.work / "updater"), str(fx.work / "docker-compose.yml")
    )
    return fx


def _push_files(fx: Fixture, version: str, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = fx.pusher / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    commit(fx.pusher, version)
    git(fx.pusher, "push", "origin", "main")


def _apply(fx: Fixture, version: str, files: dict[str, str]) -> dict[str, Any]:
    _push_files(fx, version, files)
    fx.updater.check(force=True)
    fx.running = version
    fx.updater.start_apply(threaded=False)
    return fx.updater.state.get("apply")


@pytest.mark.parametrize(
    ("files", "outdated"),
    [
        ({}, False),
        ({"updater/a.py": "a = 2\n"}, True),
        ({"docker-compose.yml": "v: 2\n"}, True),
    ],
)
def test_outdated_follows_updater_tree_and_compose(
    su: Fixture, files: dict[str, str], outdated: bool
) -> None:
    assert su.updater.status()["updater_outdated"] is False
    assert su.updater.status()["self_update"] is None
    _push_files(su, "dev-260103.0000", files)
    git(su.work, "pull", "--ff-only", "origin", "main")
    assert su.updater.status()["updater_outdated"] is outdated


def test_launch_recreate_command_and_state(su: Fixture) -> None:
    _apply(su, "dev-260103.0000", {"updater/a.py": "a = 2\n"})
    repo = str(su.work)
    calls = [a for a, _ in su.docker.calls if a[1] in ("rm", "inspect", "run")]
    assert calls[0] == ["docker", "rm", "-f", "darkstar-updater-recreate"]
    assert calls[1] == ["docker", "inspect", "--format", "{{.Image}}", "darkstar-updater"]
    assert calls[2] == [
        "docker", "run", "-d", "--name", "darkstar-updater-recreate", "--entrypoint", "sh",
        "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", f"{repo}:{repo}", IMAGE_ID,
        "-c", f"sleep 3; exec docker compose --project-directory {repo} up -d --build --no-deps updater",
    ]  # fmt: skip
    state = su.updater.state.get("self_update")
    assert state["fingerprint"] == su.updater._repo_fingerprint()  # type: ignore[reportPrivateUsage]
    assert state["at"]


def test_recreate_triggered_once_per_fingerprint(su: Fixture) -> None:
    _apply(su, "dev-260103.0000", {"updater/a.py": "a = 2\n"})
    assert _helper_verbs(su).count("run") == 1
    _apply(su, "dev-260104.0000", {})  # same updater tree: fingerprint already attempted
    assert _helper_verbs(su).count("run") == 1
    _apply(su, "dev-260105.0000", {"updater/a.py": "a = 3\n"})  # newer fingerprint: retried
    assert _helper_verbs(su).count("run") == 2


def test_no_recreate_when_up_to_date(su: Fixture) -> None:
    apply = _apply(su, "dev-260103.0000", {})
    assert apply["state"] == "done"
    assert _helper_verbs(su) == []
    assert su.updater.state.get("self_update") is None


def test_no_recreate_after_rollback_or_failed_apply(su: Fixture) -> None:
    _push_files(su, "dev-260103.0000", {"updater/a.py": "a = 2\n"})
    su.updater.check(force=True)
    _fast_clock(su)  # new version never healthy -> rollback
    su.updater.start_apply(threaded=False)
    assert su.updater.state.get("apply")["state"] == "failed"
    su.docker.fail_build = True
    su.updater.check(force=True)
    su.updater.start_apply(threaded=False)
    assert _helper_verbs(su) == []
    assert su.updater.state.get("self_update") is None


def test_helper_failure_keeps_old_updater_and_is_not_retried(su: Fixture) -> None:
    su.docker.helper_exit = "1"
    su.docker.helper_logs = ["helper: build failed"]
    apply = _apply(su, "dev-260103.0000", {"updater/a.py": "a = 2\n"})
    assert apply["state"] == "done"
    state = su.updater.state.get("self_update")
    assert state["state"] == "failed"
    assert "docker compose up -d --build updater" in state["message"]
    assert "helper: build failed" in "\n".join(state["log_tail"])
    assert "helper: build failed" in su.updater.read_log(0)[0]
    assert _helper_verbs(su)[-2:] == ["wait", "rm"]
    status = su.updater.status()
    assert status["updater_outdated"] is True  # old updater still answers
    assert status["apply"]["state"] == "done"
    assert status["self_update"] == {"state": "failed", "message": state["message"]}
    su.updater.check(force=True)
    su.updater._maybe_recreate()  # type: ignore[reportPrivateUsage]
    assert _helper_verbs(su).count("run") == 1


def test_helper_start_failure_is_recorded(su: Fixture) -> None:
    su.docker.inspect_rc = 1
    _apply(su, "dev-260103.0000", {"updater/a.py": "a = 2\n"})
    assert su.updater.state.get("self_update")["state"] == "failed"
    assert "run" not in _helper_verbs(su)


def _reconcile(su: Fixture, own: str | None, fingerprint_in_state: str = "fp") -> dict[str, Any]:
    su.updater.state.update(self_update={"state": "started", "fingerprint": fingerprint_in_state})
    su.updater._updater_fingerprint = own  # type: ignore[reportPrivateUsage]
    su.updater.reconcile_self_update()
    return su.updater.state.get("self_update")


def test_reconcile_equal_fingerprint_is_done(su: Fixture) -> None:
    assert _reconcile(su, "fp")["state"] == "done"
    assert _helper_verbs(su) == ["rm"]


def test_reconcile_different_fingerprint_is_failed(su: Fixture) -> None:
    result = _reconcile(su, "other")
    assert result["state"] == "failed"
    assert "docker compose up -d --build updater" in result["message"]
    assert _helper_verbs(su) == ["rm"]


def test_reconcile_without_state_does_nothing(su: Fixture) -> None:
    su.updater.reconcile_self_update()
    assert su.updater.state.get("self_update") is None
    assert su.docker.calls == []
