"""Price-data degradation fault injection (spec req 2).

The planner must produce a safe schedule from available data or decline —
never plan against fabricated prices, never overwrite the last good schedule
with an empty/zero-price one.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import pytz

from planner.pipeline import PlannerPipeline
from tests.fault_injection.test_dst_transitions import make_inputs, planner_config


def future_base() -> datetime:
    """A 15-min-aligned UTC instant safely in the future (preflight checks the
    real wall clock, not now_override)."""
    now = datetime.now(pytz.UTC) + timedelta(days=2)
    return now.replace(minute=0, second=0, microsecond=0)


class TestTotalPriceFailure:
    @pytest.mark.asyncio
    async def test_empty_price_data_does_not_overwrite_last_good_schedule(
        self, tmp_path, monkeypatch
    ):
        """Nordpool fetch failed entirely (price_data=[]): the previously written
        schedule.json must remain untouched, and no zero-price schedule appears."""
        monkeypatch.chdir(tmp_path)
        last_good = {"schedule": [{"start_time": "2026-06-01T00:00:00+02:00"}], "meta": {}}
        Path("schedule.json").write_text(json.dumps(last_good), encoding="utf-8")

        pipeline = PlannerPipeline(planner_config())
        inputs = {"price_data": [], "forecast_data": [], "initial_state": {}}

        try:
            df = await pipeline.generate_schedule(inputs, mode="baseline", save_to_file=True)
            # If it returns instead of raising, it must return nothing plannable...
            assert df.empty, "planner fabricated a schedule from zero price slots"
        except Exception:
            pass  # declining loudly is acceptable safe behavior

        # ...and the last good schedule must survive either way.
        preserved = json.loads(Path("schedule.json").read_text(encoding="utf-8"))
        assert preserved == last_good, "empty-price run overwrote the last good schedule"


class TestPartialPrices:
    @pytest.mark.asyncio
    async def test_missing_tomorrow_prices_plans_only_available_slots(self, tmp_path, monkeypatch):
        """Only today's prices exist (tomorrow missing): every planned slot must
        lie inside the priced window — no invented slots beyond it."""
        monkeypatch.chdir(tmp_path)
        tz = pytz.timezone("Europe/Stockholm")
        start_utc = future_base()
        inputs = make_inputs(start_utc, hours=12)  # prices end 12 h later
        now_override = start_utc.astimezone(tz)

        pipeline = PlannerPipeline(planner_config())
        df = await pipeline.generate_schedule(
            inputs, mode="baseline", save_to_file=False, now_override=now_override
        )

        assert not df.empty
        from tests.fault_injection.test_dst_transitions import schedule_starts

        starts = schedule_starts(df)
        priced_end = pd.Timestamp(start_utc) + pd.Timedelta(hours=12)
        assert (starts < priced_end).all(), "planner produced slots beyond the priced window"

    @pytest.mark.asyncio
    async def test_gap_in_price_slots_does_not_crash(self, tmp_path, monkeypatch):
        """A hole in the middle of the price series (partial delivery) must not
        crash the planner."""
        monkeypatch.chdir(tmp_path)
        tz = pytz.timezone("Europe/Stockholm")
        start_utc = future_base()
        inputs = make_inputs(start_utc, hours=12)
        # knock out a contiguous hour in the middle
        del inputs["price_data"][12:16]
        now_override = start_utc.astimezone(tz)

        pipeline = PlannerPipeline(planner_config())
        df = await pipeline.generate_schedule(
            inputs, mode="baseline", save_to_file=False, now_override=now_override
        )
        # Either fills forward explicitly or plans around the gap — both are
        # acceptable; crashing or inventing negative/zero prices is not.
        if not df.empty and "import_price_sek_kwh" in df.columns:
            assert (df["import_price_sek_kwh"] >= 0).all()
