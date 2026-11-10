"""Load training data rule, level feature, slot means, blend and schema retrain."""

import json
import math
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
import pytz

from backend.services.scheduler_service import SchedulerService
from ml import forward
from ml.load_clean import (
    LOAD_SCHEMA_VERSION,
    clean_load_observations,
    load_level_7d,
    slot_means_7d,
)

TZ = pytz.timezone("Europe/Stockholm")
RECORDING = {
    "recording": {
        "schema_version": 1,
        "semantics": "slot-energy-v1",
        "boundary_fingerprint": "0" * 64,
        "components": {"load": {"method": "power_history", "owner": "recorder"}},
        "soc": {"source": "live", "owner": "recorder"},
    }
}


def _day(
    year: int,
    month: int,
    day: int,
    *,
    load: float = 0.5,
    flags: str | None = None,
    slots: int = 96,
    clamp_slots: int = 0,
    flow: float = 0.3,
) -> pd.DataFrame:
    start = TZ.localize(datetime(year, month, day))
    # Build in UTC-aware local wall time so DST days keep their real slot count.
    index = pd.date_range(start, periods=slots, freq="15min", tz=TZ)
    load_values = [0.0 if i < clamp_slots else load for i in range(slots)]
    return pd.DataFrame(
        {
            "slot_start": index,
            "load_kwh": load_values,
            "import_kwh": flow,
            "pv_kwh": 0.0,
            "batt_discharge_kwh": 0.0,
            "quality_flags": flags,
        }
    )


class TestCleaner:
    def test_fake_legacy_day_flagged(self):
        df = _day(2026, 6, 1, clamp_slots=50)
        clean, stats = clean_load_observations(df)
        assert clean.empty
        assert stats["dropped_clamp_days"] == 1
        assert stats["dropped_clamp_rows"] == 96

    def test_normal_day_kept(self):
        df = _day(2026, 6, 1, clamp_slots=28)
        clean, stats = clean_load_observations(df)
        assert len(clean) == 96
        assert stats["dropped_clamp_days"] == 0

    def test_clamp_slots_without_active_flow_not_counted(self):
        df = _day(2026, 6, 1, clamp_slots=60, flow=0.0)
        assert len(clean_load_observations(df)[0]) == 96

    def test_short_day_kept(self):
        df = _day(2026, 6, 1, slots=60, clamp_slots=60)
        assert len(clean_load_observations(df)[0]) == 60

    def test_recording_day_kept(self):
        df = _day(2026, 6, 1, clamp_slots=60, flags=json.dumps(RECORDING))
        clean, stats = clean_load_observations(df)
        assert len(clean) == 96
        assert stats["dropped_clamp_days"] == 0

    def test_backfill_dropped_unless_recording(self):
        backfill = _day(2026, 6, 1, flags=json.dumps({"source": "backfill"}))
        modern = _day(
            2026, 6, 2, flags=json.dumps({"source": "backfill", **RECORDING})
        )
        clean, stats = clean_load_observations(pd.concat([backfill, modern], ignore_index=True))
        assert stats["dropped_backfill_rows"] == 96
        assert len(clean) == 96
        assert clean["slot_start"].dt.day.eq(2).all()

    def test_dst_day_is_not_short(self):
        # 2026-03-29 has 92 slots in Europe/Stockholm: still >= 80, so it can be flagged.
        df = _day(2026, 3, 29, slots=92, clamp_slots=60)
        assert clean_load_observations(df)[1]["dropped_clamp_days"] == 1

    def test_malformed_flags_treated_as_legacy(self):
        df = _day(2026, 6, 1, flags="{not json")
        assert len(clean_load_observations(df)[0]) == 96


class TestLevelAndSlotMeans:
    def _history(self, days: int, load: float = 0.5, start_day: int = 1) -> pd.DataFrame:
        return pd.concat(
            [_day(2026, 6, start_day + i, load=load) for i in range(days)], ignore_index=True
        )

    def test_level_uses_only_prior_days(self):
        hist = self._history(5)
        slots = pd.Series([TZ.localize(datetime(2026, 6, 4, 12, 0))])
        # Only June 1..3 precede June 4: 3 days of 0.5 x 96
        assert load_level_7d(hist, slots).iloc[0] == pytest.approx(48.0)

    def test_no_leakage_from_day_itself(self):
        hist = pd.concat(
            [self._history(3), _day(2026, 6, 4, load=5.0)], ignore_index=True
        )
        slots = pd.Series([TZ.localize(datetime(2026, 6, 4, 12, 0))])
        assert load_level_7d(hist, slots).iloc[0] == pytest.approx(48.0)

    def test_nan_without_three_days(self):
        slots = pd.Series([TZ.localize(datetime(2026, 6, 3, 12, 0))])
        assert math.isnan(load_level_7d(self._history(2), slots).iloc[0])

    def test_anchor_hold_for_far_future(self):
        slots = pd.Series([TZ.localize(datetime(2026, 6, 20, 12, 0))])
        # Window June 13..19 is empty; the last valid level (June 8: days 1..7... ) is held.
        value = load_level_7d(self._history(10), slots).iloc[0]
        assert value == pytest.approx(48.0)

    def test_incomplete_days_ignored(self):
        hist = pd.concat(
            [_day(2026, 6, 1, slots=40), _day(2026, 6, 2), _day(2026, 6, 3)], ignore_index=True
        )
        slots = pd.Series([TZ.localize(datetime(2026, 6, 5, 0, 0))])
        assert math.isnan(load_level_7d(hist, slots).iloc[0])

    def test_dst_day_counts_as_complete(self):
        hist = pd.concat(
            [_day(2026, 3, 28), _day(2026, 3, 29, slots=92), _day(2026, 3, 30)],
            ignore_index=True,
        )
        slots = pd.Series([TZ.localize(datetime(2026, 3, 31, 12, 0))])
        assert not math.isnan(load_level_7d(hist, slots).iloc[0])

    def test_slot_mean_arithmetic_and_minimum_days(self):
        hist = pd.concat(
            [_day(2026, 6, 1, load=0.2), _day(2026, 6, 2, load=0.3), _day(2026, 6, 3, load=0.4)],
            ignore_index=True,
        )
        now = pd.Timestamp(TZ.localize(datetime(2026, 6, 4, 10, 0)))
        slots = pd.Series(
            [TZ.localize(datetime(2026, 6, 4, 12, 0)), TZ.localize(datetime(2026, 6, 5, 12, 0))]
        )
        means = slot_means_7d(hist, slots, now)
        assert means.iloc[0] == pytest.approx(0.3)
        # June 5 sees June 1..4 where June 4 12:00 is not observed: still 3 days -> 0.3
        assert means.iloc[1] == pytest.approx(0.3)
        two_days = hist[hist["slot_start"].dt.day < 3]
        assert math.isnan(slot_means_7d(two_days, slots, now).iloc[0])

    def test_slot_mean_never_uses_observations_at_or_after_now(self):
        hist = pd.concat(
            [
                _day(2026, 6, 1, load=0.2),
                _day(2026, 6, 2, load=0.2),
                _day(2026, 6, 3, load=0.2),
                _day(2026, 6, 4, load=9.0),
            ],
            ignore_index=True,
        )
        now = pd.Timestamp(TZ.localize(datetime(2026, 6, 4, 6, 0)))
        slots = pd.Series([TZ.localize(datetime(2026, 6, 5, 3, 0))])
        # June 4 03:00 is before now (kept); June 4 12:00 would be after now.
        late = pd.Series([TZ.localize(datetime(2026, 6, 5, 12, 0))])
        assert slot_means_7d(hist, late, now).iloc[0] == pytest.approx(0.2)
        assert slot_means_7d(hist, slots, now).iloc[0] == pytest.approx((0.6 + 9.0) / 4)


class TestBlend:
    def _preds(self, p10, p50, p90):
        return {
            "load_p10": pd.Series(p10, dtype="float64"),
            "load_p50": pd.Series(p50, dtype="float64"),
            "load_p90": pd.Series(p90, dtype="float64"),
        }

    def test_normal_blend_and_shift(self):
        preds = self._preds([0.1], [0.2], [0.5])
        forward.blend_load_predictions(preds, pd.Series([0.30]))
        assert preds["load_p50"].iloc[0] == pytest.approx(0.26)
        assert preds["load_p10"].iloc[0] == pytest.approx(0.16)
        assert preds["load_p90"].iloc[0] == pytest.approx(0.56)
        spread = preds["load_p90"].iloc[0] - preds["load_p50"].iloc[0]
        assert spread == pytest.approx(0.3)

    def test_fallback_when_mean_missing(self):
        preds = self._preds([0.1, 0.1], [0.2, 0.2], [0.5, 0.5])
        forward.blend_load_predictions(preds, pd.Series([np.nan, 0.3]))
        assert preds["load_p50"].iloc[0] == pytest.approx(0.2)
        assert preds["load_p10"].iloc[0] == pytest.approx(0.1)

    def test_clamp_and_ordering(self):
        preds = self._preds([0.2], [1.0], [1.4])
        forward.blend_load_predictions(preds, pd.Series([0.0]))  # delta = -0.6
        assert preds["load_p10"].iloc[0] == pytest.approx(0.01)
        lo, mid, hi = sorted(preds[k].iloc[0] for k in ("load_p10", "load_p50", "load_p90"))
        assert lo <= mid <= hi
        assert preds["load_p50"].iloc[0] == pytest.approx(0.4)

    def test_ceiling(self):
        preds = self._preds([15.0], [15.0], [16.0])
        forward.blend_load_predictions(preds, pd.Series([30.0]))
        assert all(preds[k].iloc[0] <= 16.0 for k in preds)


def _write_model(models_dir, name, sidecar):
    rng = np.random.default_rng(1)
    model = lgb.LGBMRegressor(n_estimators=3, verbose=-1).fit(rng.random((40, 2)), rng.random(40))
    path = models_dir / f"{name}.lgb"
    model.booster_.save_model(str(path))
    if sidecar is not None:
        path.with_suffix(".features.json").write_text(json.dumps(sidecar))


class TestSchemaRejection:
    def setup_method(self):
        forward.clear_load_retrain_request()

    def teardown_method(self):
        forward.clear_load_retrain_request()

    def test_old_load_model_rejected_pv_still_loads(self, tmp_path):
        _write_model(tmp_path, "load_model_p50", {"feature_names": forward._EXPECTED_BASE_FEATURES})
        _write_model(
            tmp_path, "pv_model_p50", {"feature_names": forward._EXPECTED_PV_FEATURES}
        )
        models = forward._load_models(models_dir=str(tmp_path))
        assert "load_p50" not in models
        assert "pv_p50" in models
        assert forward.load_retrain_requested() is True

    def test_missing_sidecar_rejected_for_load(self, tmp_path):
        _write_model(tmp_path, "load_model_p50", None)
        assert "load_p50" not in forward._load_models(models_dir=str(tmp_path))
        assert forward.load_retrain_requested() is True

    def test_current_schema_loads_without_request(self, tmp_path):
        _write_model(
            tmp_path,
            "load_model_p50",
            {
                "feature_names": forward._EXPECTED_LOAD_FEATURES,
                "schema_version": LOAD_SCHEMA_VERSION,
            },
        )
        assert "load_p50" in forward._load_models(models_dir=str(tmp_path))
        assert forward.load_retrain_requested() is False


class TestSchemaRetrainHook:
    @pytest.mark.asyncio
    async def test_retrain_triggered_once_per_hour(self):
        forward.clear_load_retrain_request()
        scheduler = SchedulerService()
        train = AsyncMock(return_value={"status": "success"})
        with patch("ml.training_orchestrator.train_all_models", train):
            forward._load_retrain_requested = True
            await scheduler._check_load_schema_retrain()
            assert train.await_count == 1
            assert forward.load_retrain_requested() is False

            # rejected again within the hour: no second run, request stays pending
            forward._load_retrain_requested = True
            await scheduler._check_load_schema_retrain()
            assert train.await_count == 1
            assert forward.load_retrain_requested() is True

            scheduler._last_schema_retrain_at -= timedelta(hours=1, minutes=1)
            await scheduler._check_load_schema_retrain()
            assert train.await_count == 2
        forward.clear_load_retrain_request()

    @pytest.mark.asyncio
    async def test_no_request_no_training(self):
        forward.clear_load_retrain_request()
        train = AsyncMock()
        with patch("ml.training_orchestrator.train_all_models", train):
            await SchedulerService()._check_load_schema_retrain()
        train.assert_not_awaited()
