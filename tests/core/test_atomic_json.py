import json
from pathlib import Path

import pytest

from backend.core.atomic_json import write_json_atomic


def test_write_json_atomic_writes_complete_json_and_uses_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "schedule.json"

    write_json_atomic(target, {"schedule": [1, 2, 3]})

    assert json.loads(target.read_text(encoding="utf-8")) == {"schedule": [1, 2, 3]}
    assert list(target.parent.glob("*.tmp")) == []


def test_write_json_atomic_preserves_target_when_serialization_fails(tmp_path: Path) -> None:
    target = tmp_path / "schedule.json"
    original = b'{"schedule": ["old"]}\n'
    target.write_bytes(original)

    with pytest.raises(TypeError):
        write_json_atomic(target, {"schedule": {1, 2, 3}})

    assert target.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []
