"""Subprocess runner abstraction so tests can inject fakes (no git/docker/network)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


class Runner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
        user: int | None = None,
        group: int | None = None,
    ) -> CommandResult: ...


def run_command(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    on_line: Callable[[str], None] | None = None,
    user: int | None = None,
    group: int | None = None,
) -> CommandResult:
    """Run a command with stderr merged into stdout, streaming lines to `on_line`.

    `user`/`group` (numeric ids) drop privileges for the child via subprocess.
    """
    import os

    full_env = {**os.environ, **env} if env else None
    try:
        proc = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            user=user,
            group=group,
        )
    except OSError as exc:
        return CommandResult(127, f"{argv[0]}: {exc}")
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        if on_line is not None:
            on_line(line.rstrip("\n"))
    return CommandResult(proc.wait(), "".join(lines))
