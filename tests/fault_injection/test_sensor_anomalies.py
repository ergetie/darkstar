"""Sensor-anomaly fault injection (spec req 3).

One bad reading must not produce a wildly wrong recorded slot. The recorder's
delta layer (RecorderStateStore) is the guard surface for cumulative meters.
"""

from datetime import datetime, timedelta

import pytz

from backend.recorder import RecorderStateStore

TZ = pytz.timezone("Europe/Stockholm")


def primed_meter(tmp_path, key: str = "import", value: float = 1000.0) -> RecorderStateStore:
    m = RecorderStateStore(state_file=tmp_path / "recorder_state.json")
    m.load()
    m.get_delta(
        key,
        value,
        datetime.now(TZ) - timedelta(minutes=15),
        sensor_timestamp=datetime.now(TZ) - timedelta(minutes=15),
    )
    return m


class TestCumulativeMeterAnomalies:
    def test_negative_delta_rejected(self, tmp_path):
        """Spec scenario: cumulative meter goes backwards -> no negative energy."""
        m = primed_meter(tmp_path)
        delta, valid = m.get_delta(
            "import", 900.0, datetime.now(TZ), sensor_timestamp=datetime.now(TZ)
        )
        assert valid is False
        assert delta is None

    def test_stuck_meter_yields_zero_not_garbage(self, tmp_path):
        m = primed_meter(tmp_path)
        delta, valid = m.get_delta(
            "import", 1000.0, datetime.now(TZ), sensor_timestamp=datetime.now(TZ)
        )
        assert valid is True
        assert delta == 0.0

    def test_spike_delta_is_not_amplified_by_scaling(self, tmp_path):
        """A large jump outside the 5-60 min scaling window must be passed raw
        (never scaled up)."""
        m = primed_meter(tmp_path)
        # sensor timestamp only 1 min after previous -> outside scaling window
        delta, valid = m.get_delta(
            "import",
            1002.0,
            datetime.now(TZ),
            sensor_timestamp=datetime.now(TZ) - timedelta(minutes=14),
        )
        assert valid is True
        assert delta is not None
        # raw jump is 2.0 kWh; scaling (900/60 = 15x) must NOT inflate it
        assert delta <= 2.0 + 1e-9

    def test_unit_outlier_spike_is_recorded_raw(self, tmp_path):
        """A 500 kWh jump in one 15-min slot (~2 MW — physically impossible for
        this site) is now rejected by RecorderStateStore's plausibility ceiling
        (recorder.max_meter_delta_kwh, default 50 kWh) instead of being recorded
        raw. The baseline still advances so the next reading computes correctly."""
        m = primed_meter(tmp_path)
        delta, valid = m.get_delta(
            "import", 1500.0, datetime.now(TZ), sensor_timestamp=datetime.now(TZ)
        )
        assert valid is False
        assert delta is None
