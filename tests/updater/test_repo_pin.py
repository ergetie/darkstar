"""Origin pinning: accepted URL forms and refusal of anything else (fake runner, no git/network)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from updater.repo import GitError, Repo, normalize_origin
from updater.runner import CommandResult

if TYPE_CHECKING:
    from pathlib import Path

PINNED = "https://github.com/ergetie/darkstar"


def repo_with_origin(url: str | None, path: Path) -> Repo:
    def runner(argv: Any, **_kwargs: Any) -> CommandResult:
        assert "config" in argv
        return CommandResult(0, url + "\n") if url is not None else CommandResult(1, "")

    return Repo(str(path), runner)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/ergetie/darkstar",
        "https://github.com/ergetie/darkstar.git",
        "https://github.com/ergetie/darkstar/",
        "https://GitHub.com/ergetie/darkstar.git",
        "git@github.com:ergetie/darkstar.git",
        "git@github.com:ergetie/darkstar",
        "ssh://git@github.com/ergetie/darkstar.git",
        "ssh://git@github.com/ergetie/darkstar",
    ],
)
def test_accepted_forms(url: str, tmp_path: Path) -> None:
    assert normalize_origin(url) == PINNED
    repo_with_origin(url, tmp_path).assert_origin()


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/evil/darkstar.git",
        "https://github.com/ergetie/darkstar-fork",
        "https://github.com/ergetie/darkstar.git.evil",
        "https://gitlab.com/ergetie/darkstar.git",
        "https://github.com.evil.example/ergetie/darkstar.git",
        "https://user:pw@github.com/ergetie/darkstar.git",
        "http://github.com/ergetie/darkstar.git",
        "git@evil.example:ergetie/darkstar.git",
        "/srv/local/darkstar",
        "",
    ],
)
def test_foreign_origin_refused(url: str, tmp_path: Path) -> None:
    with pytest.raises(GitError, match=r"Origin is not github\.com/ergetie/darkstar"):
        repo_with_origin(url, tmp_path).assert_origin()


def test_missing_origin_refused(tmp_path: Path) -> None:
    with pytest.raises(GitError, match="Origin is not"):
        repo_with_origin(None, tmp_path).assert_origin()
