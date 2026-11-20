"""Shared harness to run the start-up shell scripts against stubbed commands.

The scripts call ``python3``/``alembic``/``uvicorn``/``sleep`` by name. A stub ``bin``
directory placed first on ``PATH`` replaces them:

* ``python3`` forwards to the real interpreter, except for the config bootstrap modules
  (no-ops) and ``backend.db_safety compact`` (recorded and answered with exit 0, so the
  tests do not depend on that command being implemented), and ``-m alembic`` (stub).
* ``alembic`` records its call and, when ``STUB_ALEMBIC_FAIL=1``, half-migrates the
  database (creates a table) and fails, like a migration that breaks half way.
* ``uvicorn`` records its call and exits at once.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_S = 120


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_stub_bin(directory: Path) -> Path:
    """Create the stub commands in ``directory`` and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    real = sys.executable
    _write_exec(
        directory / "python3",
        f"""#!/bin/bash
case "$*" in
    "-m backend.config_migration"*|"-m backend.addon_bootstrap"*) exit 0 ;;
    "-m backend.db_safety compact"*) echo "compact $*" >> "$STUB_LOG"; exit 0 ;;
    "-m alembic "*) exec alembic "${{@:3}}" ;;
esac
exec "{real}" "$@"
""",
    )
    _write_exec(
        directory / "alembic",
        f"""#!/bin/bash
echo "alembic $*" >> "$STUB_LOG"
if [ "$STUB_ALEMBIC_FAIL" = "1" ]; then
    "{real}" -c "import os, sqlite3; c = sqlite3.connect(os.environ['DB_PATH']); \\
c.execute('CREATE TABLE half_migrated (x)'); c.commit()"
    echo "boom: migration exploded" >&2
    exit 1
fi
echo "stub upgrade ok"
""",
    )
    _write_exec(directory / "uvicorn", '#!/bin/bash\necho "uvicorn $*" >> "$STUB_LOG"\n')
    # The entrypoint polls its server with a 30 s sleep; keep that instant.
    _write_exec(directory / "sleep", "#!/bin/bash\nexec /bin/sleep 0.2\n")
    return directory


def run_script(
    script: Path,
    *,
    cwd: Path,
    stub_bin: Path,
    log: Path,
    env: dict[str, str],
    alembic_fails: bool = False,
) -> subprocess.CompletedProcess[str]:
    full_env = {
        **os.environ,
        "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": str(ROOT),
        "STUB_LOG": str(log),
        "STUB_ALEMBIC_FAIL": "1" if alembic_fails else "0",
        **env,
    }
    return subprocess.run(
        ["bash", str(script)],
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        check=False,
    )


def make_behind_db(path: Path) -> None:
    """A WAL database with data whose recorded revision is behind the Alembic head."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version VALUES ('deadbeef0000')")
        conn.execute("CREATE TABLE readings (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO readings (v) VALUES (?)", [(f"row-{i}",) for i in range(50)])
        conn.commit()
    finally:
        conn.close()


def dump_db(path: Path) -> list[str]:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def log_lines(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []
