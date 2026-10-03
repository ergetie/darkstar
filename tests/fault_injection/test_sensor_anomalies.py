"""Sensor-anomaly fault injection (spec req 3).

One bad reading must not produce a wildly wrong recorded slot. Slot energy is
step-integrated from power history, so the guard surfaces are the integrator
(unavailable and garbage states are skipped, negative samples never become PV or
load energy) and the per-slot plausibility ceiling.
"""

from datetime import datetime, timedelta

import pytz

from backend.core.ha_client import integrate_power_points, parse_power_states
from backend.validation import validate_energy_values

START = datetime(2026, 10, 1, 12, 0, tzinfo=pytz.UTC)
END = START + timedelta(minutes=15)


def state(value: str, minutes: float, unit: str = "kW") -> dict:
    return {
        "state": value,
        "last_changed": (START + timedelta(minutes=minutes)).isoformat(),
        "attributes": {"unit_of_measurement": unit},
    }


def integrate(states: list[dict]) -> tuple[float, float] | None:
    return integrate_power_points(parse_power_states(states), START, END)


class TestPowerHistoryAnomalies:
    def test_unavailable_gap_holds_the_last_good_value(self):
        """An 'unavailable' blip is skipped, not integrated as zero or garbage."""
        positive, negative = integrate([state("2.0", 0), state("unavailable", 5), state("2.0", 10)])
        assert positive == 0.5
        assert negative == 0.0

    def test_garbage_state_is_ignored(self):
        positive, _ = integrate([state("2.0", 0), state("not-a-number", 7)])
        assert positive == 0.5

    def test_sensor_dead_for_the_whole_slot_yields_no_value(self):
        """No valid sample at all -> None, so the recorder uses its snapshot fallback."""
        assert integrate([state("unavailable", 0), state("unknown", 5)]) is None

    def test_negative_glitch_is_kept_out_of_the_positive_side(self):
        """A negative PV reading (inverter standby) must not reduce PV energy."""
        positive, negative = integrate([state("3.0", 0), state("-0.2", 10)])
        assert positive == 3.0 * 10 / 60
        assert negative > 0.0  # reported separately; PV/load callers drop it

    def test_unit_outlier_spike_is_zeroed_by_the_slot_ceiling(self):
        """A W reading mistaken for kW (2 MW for the slot) is rejected, not recorded."""
        positive, _ = integrate([state("2000", 0, unit="kW")])
        record = validate_energy_values({"pv_kwh": positive, "load_kwh": 1.0}, max_kwh=16.0)
        assert record["pv_kwh"] == 0.0
        assert record["load_kwh"] == 1.0
