"""Git operations for the updater (all through an injectable Runner)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import CommandResult, Runner

CHANNELS = ("dev", "stable")
MAX_SUBJECTS = 20
_REVISION_RE = re.compile(r"""^revision\s*(?::\s*str)?\s*=\s*['"]([^'"]+)""", re.MULTILINE)


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    commit: str
    version: str
    ref: str


def _clean_version(value: str) -> str:
    value = value.strip()
    return value[1:] if value.lower().startswith("v") else value


class Repo:
    def __init__(self, path: str, runner: Runner) -> None:
        self.path = path
        self._runner = runner

    def run(self, *args: str, check: bool = True) -> CommandResult:
        # Run git as the repo owner so root never creates files in the host's working tree/.git.
        # safe.directory: ownership may still differ from the effective user. HOME is the repo
        # (readable by the owner) because root's HOME is not.
        st = Path(self.path).stat()
        drop = st.st_uid != 0
        result = self._runner(
            ["git", "-c", f"safe.directory={self.path}", *args],
            cwd=self.path,
            env={"HOME": self.path} if drop else None,
            user=st.st_uid if drop else None,
            group=st.st_gid if drop else None,
        )
        if check and result.returncode != 0:
            raise GitError(f"git {args[0]} failed: {result.output.strip()}")
        return result

    def fetch(self) -> None:
        self.run("fetch", "--tags", "--prune", "origin")

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").output.strip()

    def current_branch(self) -> str | None:
        result = self.run("symbolic-ref", "-q", "--short", "HEAD", check=False)
        return result.output.strip() if result.returncode == 0 else None

    def short(self, commit: str) -> str:
        return commit[:7]

    def _file_at(self, ref: str, path: str) -> str | None:
        result = self.run("show", f"{ref}:{path}", check=False)
        return result.output if result.returncode == 0 else None

    def current_version(self) -> str:
        """Tag version on a detached (stable) checkout, else the VERSION file, else short sha."""
        head = self.head()
        if self.current_branch() is None:
            tag = self.run("describe", "--tags", "--exact-match", "HEAD", check=False)
            if tag.returncode == 0 and tag.output.strip():
                return _clean_version(tag.output)
        return self._version_from_file(head)

    def _version_from_file(self, commit: str) -> str:
        content = self._file_at(commit, "VERSION")
        if content and content.strip():
            return _clean_version(content)
        return self.short(commit)

    def latest_stable_tag(self) -> str | None:
        out = self.run(
            "-c", "versionsort.suffix=-", "tag", "--list", "v*", "--sort=-v:refname"
        ).output.split()
        return out[0] if out else None

    def resolve_target(self, channel: str) -> Target | None:
        if channel == "dev":
            commit = self.run("rev-parse", "origin/main").output.strip()
            return Target(commit, self._version_from_file(commit), "origin/main")
        if channel == "stable":
            tag = self.latest_stable_tag()
            if tag is None:
                return None
            commit = self.run("rev-list", "-n", "1", tag).output.strip()
            return Target(commit, _clean_version(tag), tag)
        raise ValueError(f"unknown channel: {channel}")

    def dirty_files(self) -> list[str]:
        out = self.run("status", "--porcelain", "--untracked-files=no").output
        return [line[3:] for line in out.splitlines() if line.strip()]

    def commit_subjects(self, current: str, target: str) -> list[str]:
        result = self.run(
            "log", f"--max-count={MAX_SUBJECTS}", "--format=%s", f"{current}..{target}", check=False
        )
        return (
            [s for s in result.output.splitlines() if s.strip()] if result.returncode == 0 else []
        )

    def revisions_at(self, ref: str) -> set[str]:
        """Alembic revision ids present in alembic/versions at `ref`."""
        listing = self.run("ls-tree", "--name-only", ref, "alembic/versions/", check=False)
        revisions: set[str] = set()
        for name in listing.output.splitlines():
            if not name.endswith(".py"):
                continue
            content = self._file_at(ref, name)
            match = _REVISION_RE.search(content) if content else None
            if match:
                revisions.add(match.group(1))
        return revisions
