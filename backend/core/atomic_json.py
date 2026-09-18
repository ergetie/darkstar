"""Helpers for durable JSON file writes."""

import contextlib
import json
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(
    path: str | Path,
    payload: Any,
    *,
    encoder: type[json.JSONEncoder] | None = None,
    indent: int | str | None = 2,
) -> None:
    """Write JSON to *path* by replacing it with a complete temporary file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_path = Path(temp_file.name)
        try:
            json.dump(payload, temp_file, indent=indent, cls=encoder)
        except Exception:
            with contextlib.suppress(OSError):
                temp_path.unlink()
            raise

    temp_path.replace(target)
