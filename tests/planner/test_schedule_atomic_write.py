import json
from pathlib import Path

import pandas as pd
import pytest

from backend.core.atomic_json import write_json_atomic


def test_schedule_atomic_write_preserves_existing_file_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "schedule.json"
    original = b'{"schedule": ["old"]}\n'
    target.write_bytes(original)

    with pytest.raises(TypeError):
        write_json_atomic(target, {"schedule": {object()}})

    assert target.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_schedule_atomic_write_produces_valid_json_without_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "schedule.json"

    write_json_atomic(target, {"schedule": [], "meta": {"planned": pd.Timestamp.now().isoformat()}})

    assert json.loads(target.read_text(encoding="utf-8"))["schedule"] == []
    assert list(tmp_path.glob("*.tmp")) == []
