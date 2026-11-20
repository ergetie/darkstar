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

# The updater image has no ssh or keys and the repo is public: always fetch over anonymous HTTPS,
# whatever form origin uses. Never prompt for credentials.
_HTTPS_REWRITE = (
    "-c",
    "url.https://github.com/.insteadOf=git@github.com:",
    "-c",
    "url.https://github.com/.insteadOf=ssh://git@github.com/",
)


PINNED_REPO = "ergetie/darkstar"
PINNED_ORIGIN = f"https://github.com/{PINNED_REPO}"
_ORIGIN_FORMS = (
    ("https://github.com/", "https://github.com/"),
    ("git@github.com:", "https://github.com/"),
    ("ssh://git@github.com/", "https://github.com/"),
)
_CLOBBER_RE = re.compile(
    r"^\s*!\s+\[rejected\]\s+(\S+)\s+->\s+\S+\s+\(would clobber existing tag\)\s*$"
)
_FETCH_NOISE_RE = re.compile(r"^error: some local refs could not be updated")


class GitError(RuntimeError):
    pass


def normalize_origin(url: str) -> str:
    """Canonical https form of a GitHub remote URL (host lowercased, no `.git`, no trailing `/`).

    Anything that is not a plain GitHub https/ssh/scp-style URL is returned stripped but
    otherwise unchanged, so it can never equal the pinned origin by accident.
    """
    url = url.strip()
    lowered = url.lower()
    for prefix, https in _ORIGIN_FORMS:
        if lowered.startswith(prefix):
            url = https + url[len(prefix) :]
            break
    else:
        return url
    url = url.rstrip("/")
    url = url.removesuffix(".git").rstrip("/")
    # GitHub treats host, owner and repo names case-insensitively.
    return url.lower()


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
            ["git", "-c", f"safe.directory={self.path}", *_HTTPS_REWRITE, *args],
            cwd=self.path,
            env={**({"HOME": self.path} if drop else {}), "GIT_TERMINAL_PROMPT": "0"},
            user=st.st_uid if drop else None,
            group=st.st_gid if drop else None,
        )
        if check and result.returncode != 0:
            raise GitError(f"git {args[0]} failed: {result.output.strip()}")
        return result

    def assert_origin(self) -> None:
        """Refuse any origin other than the pinned GitHub repository."""
        # `config --get` returns the stored URL; `remote get-url` would apply insteadOf rewrites.
        result = self.run("config", "--get", "remote.origin.url", check=False)
        if result.returncode != 0 or normalize_origin(result.output) != PINNED_ORIGIN:
            raise GitError("Origin is not github.com/ergetie/darkstar")

    def fetch(self) -> list[str]:
        """Fetch branches and new tags from the pinned origin; returns non-fatal warnings.

        Tags are never force-updated or pruned: a tag that moved upstream is rejected by git
        ("would clobber existing tag"), reported as a warning, and the local tag is kept. Any
        other failure raises.
        """
        self.assert_origin()
        result = self.run("fetch", "--prune", "--tags", "origin", check=False)
        if result.returncode == 0:
            return []
        warnings: list[str] = []
        problems: list[str] = []
        for line in result.output.splitlines():
            clobber = _CLOBBER_RE.match(line)
            if clobber:
                warnings.append(f"Tag {clobber.group(1)} changed upstream; keeping the local tag")
            elif line.lstrip().startswith(("!", "error:", "fatal:")) and not _FETCH_NOISE_RE.match(
                line
            ):
                problems.append(line)
        if problems or not warnings:
            raise GitError(f"git fetch failed: {result.output.strip()}")
        return warnings

    def head(self) -> str:
        return self.run("rev-parse", "HEAD").output.strip()

    def current_branch(self) -> str | None:
        result = self.run("symbolic-ref", "-q", "--short", "HEAD", check=False)
        return result.output.strip() if result.returncode == 0 else None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """True when `ancestor` is reachable from `descendant` (a commit is its own ancestor)."""
        result = self.run("merge-base", "--is-ancestor", ancestor, descendant, check=False)
        if result.returncode not in (0, 1):
            raise GitError(f"git merge-base failed: {result.output.strip()}")
        return result.returncode == 0

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
