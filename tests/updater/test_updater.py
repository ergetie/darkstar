"""Updater tests: real git on local temp repos (no network), fake docker, fake health."""

from __future__ import annotations

import http.client
import json
import os
import sqlite3
import subprocess
import threading
import types
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

import pytest

from updater.runner import CommandResult, run_command
from updater.server import main, make_handler
from updater.service import ApplyBusy, ApplyRejected, Config, Updater
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
    git(fx.work, "remote", "set-url", "origin", str(fx.origin) + ".gone")
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


def test_unhealthy_after_up_fails_without_rollback(fx: Fixture) -> None:
    sha = fx.push_dev("dev-260103.0000")
    fx.updater.check(force=True)
    clock = iter(range(0, 10_000, 100))
    fx.updater._monotonic = lambda: float(next(clock))  # type: ignore[reportPrivateUsage]
    fx.updater.start_apply(threaded=False)  # running version never changes
    assert fx.updater.status()["apply"]["state"] == "failed"
    assert git(fx.work, "rev-parse", "HEAD") == sha


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


def test_git_runs_as_repo_owner(tmp_path: Path) -> None:
    from updater.repo import Repo

    calls: list[dict[str, Any]] = []

    def fake(argv: Any, *, cwd: Any = None, env: Any = None, on_line: Any = None,
             user: Any = None, group: Any = None) -> CommandResult:
        calls.append({"user": user, "group": group, "env": env})
        return CommandResult(0, "abc\n")

    Repo(str(tmp_path), fake).head()
    st = os.stat(tmp_path)
    if st.st_uid == 0:
        assert calls[0]["user"] is None and calls[0]["group"] is None
    else:
        assert (calls[0]["user"], calls[0]["group"]) == (st.st_uid, st.st_gid)
        assert calls[0]["env"] == {"HOME": str(tmp_path), "GIT_TERMINAL_PROMPT": "0"}


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
        return CommandResult(0, "")

    Repo(str(tmp_path), runner).fetch()
    argv, env = seen[0]
    assert "url.https://github.com/.insteadOf=git@github.com:" in argv
    assert "url.https://github.com/.insteadOf=ssh://git@github.com/" in argv
    assert argv.index("fetch") > max(i for i, a in enumerate(argv) if a == "-c")
    assert env["GIT_TERMINAL_PROMPT"] == "0"
