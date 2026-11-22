"""save_schedule_to_json returns the dict it wrote (the plan archive stores it verbatim)."""

import json

import pytest

from planner.output import schedule as schedule_module
from tests.planner.test_schedule_output_s_index_write import _make_schedule_df


@pytest.mark.asyncio
async def test_returned_output_equals_written_file(monkeypatch, tmp_path):
    monkeypatch.setattr(schedule_module, "record_s_index_history", lambda *a, **k: None)
    path = tmp_path / "schedule.json"

    output = await schedule_module.save_schedule_to_json(
        schedule_df=_make_schedule_df(),
        config={},
        now_slot=None,
        forecast_meta={"a": 1},
        s_index_debug=None,
        window_responsibilities=[],
        planner_state={},
        output_path=str(path),
    )

    assert output["schedule"]
    assert json.loads(json.dumps(output, default=lambda o: o.isoformat())) == json.loads(
        path.read_text()
    )
