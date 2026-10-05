"""Tests for the first-unseen-day price reserve (sizing, fallbacks, safety-floor combination)."""

from datetime import timedelta
from typing import Any

import pandas as pd
import pytest
import pytz

from planner.strategy.price_reserve import (
    RISK_RESERVE_THRESHOLD_SEK,
    PriceReserveInputs,
    ReserveSlot,
    evaluate_price_reserve,
    reserve_threshold_sek,
    size_price_reserve,
)
from planner.strategy.s_index import calculate_safety_floor

TZ = pytz.timezone("Europe/Stockholm")
T0 = TZ.localize(pd.Timestamp(2026, 4, 10, 14, 0).to_pydatetime())
QUARTER = timedelta(minutes=15)

# Production-like battery: 27 kWh, 15% min SoC, 8.88 kW charge, 8 kW discharge.
BATTERY = {"capacity_kwh": 27.0, "min_soc_percent": 15.0, "max_soc_percent": 100.0}
MIN_SOC_KWH = 0.15 * 27.0
S_INDEX_CFG = {"risk_appetite": 3, "max_safety_buffer_percent": 20.0}

LIMITS: dict[str, Any] = {
    "max_charge_kw": 8.88,
    "max_discharge_kw": 8.0,
    "charge_efficiency": 0.95,
    "discharge_efficiency": 0.95,
    "wear_cost_sek_kwh": 0.1,
}
ROUND_TRIP = 0.95 * 0.95


def slots(n: int, price: float, *, net_load: float = 0.0, start=T0) -> list[ReserveSlot]:
    return [
        ReserveSlot(start=start + i * QUARTER, hours=0.25, price=price, net_load_kwh=net_load)
        for i in range(n)
    ]


def size(known, unseen, *, threshold=0.10, usable=20.0, above_min=0.0, **overrides):
    params = {**LIMITS, **overrides}
    return size_price_reserve(
        known_slots=known,
        unseen_slots=unseen,
        max_charge_kw=params["max_charge_kw"],
        max_discharge_kw=params["max_discharge_kw"],
        charge_efficiency=params["charge_efficiency"],
        discharge_efficiency=params["discharge_efficiency"],
        wear_cost_sek_kwh=params["wear_cost_sek_kwh"],
        threshold_sek_kwh=threshold,
        usable_capacity_kwh=usable,
        current_soc_above_min_kwh=above_min,
    )


def unseen_day(
    cheap: float, expensive: float, evening_load_kwh: float, evening_slots: int = 4
) -> list[ReserveSlot]:
    """96 slots: expensive evening slots sharing ``evening_load_kwh``, the rest cheap."""
    day = slots(96, cheap)
    for i in range(70, 70 + evening_slots):
        day[i] = ReserveSlot(day[i].start, 0.25, expensive, evening_load_kwh / evening_slots)
    return day


class TestSizing:
    def test_unseen_day_more_expensive(self):
        known = slots(16, 0.80)
        result = size(known, unseen_day(cheap=1.40, expensive=2.50, evening_load_kwh=6.0))

        assert result.reason == "active"
        assert result.reserve_kwh == pytest.approx(6.0 / 0.95)
        assert result.known_cost_sek_kwh == pytest.approx(0.80 / ROUND_TRIP + 0.1)
        assert result.own_day_cost_sek_kwh == pytest.approx(1.40 / ROUND_TRIP + 0.1)

    def test_own_day_cheaper_gives_zero(self):
        known = slots(16, 0.80)
        result = size(known, unseen_day(cheap=0.50, expensive=2.50, evening_load_kwh=6.0))

        assert result.reserve_kwh == 0.0
        assert result.reason == "own_day_cheaper"

    def test_expensive_slot_without_net_load_adds_nothing(self):
        known = slots(16, 0.80)
        result = size(known, unseen_day(cheap=1.40, expensive=2.50, evening_load_kwh=0.0))

        assert result.reserve_kwh == 0.0
        assert result.reason == "no_net_load"

    def test_only_slots_with_net_load_contribute(self):
        known = slots(16, 0.80)
        unseen = unseen_day(cheap=1.40, expensive=2.50, evening_load_kwh=0.0)
        unseen[70] = ReserveSlot(unseen[70].start, 0.25, 2.50, 1.5)
        result = size(known, unseen)

        assert result.reserve_kwh == pytest.approx(1.5 / 0.95)

    def test_net_load_limited_by_discharge_power(self):
        known = slots(40, 0.80)
        unseen = slots(96, 1.40)
        unseen[70] = ReserveSlot(unseen[70].start, 0.25, 2.50, 50.0)
        result = size(known, unseen, max_discharge_kw=4.0, usable=100.0)

        assert result.reserve_kwh == pytest.approx(4.0 * 0.25 / 0.95)

    def test_risk_threshold_changes_outcome(self):
        # Unit efficiencies and no wear: known cost 1.00, own-day cost 1.12 -> gain 0.12
        known = slots(16, 1.00)
        unseen = slots(96, 1.12, net_load=0.5)
        unit = {"charge_efficiency": 1.0, "discharge_efficiency": 1.0, "wear_cost_sek_kwh": 0.0}

        cautious = size(known, unseen, threshold=reserve_threshold_sek(1), **unit)
        neutral = size(known, unseen, threshold=reserve_threshold_sek(3), **unit)

        assert cautious.reserve_kwh == 0.0
        assert cautious.reason == "below_threshold"
        assert neutral.reserve_kwh > 0.0

    def test_threshold_map(self):
        assert RISK_RESERVE_THRESHOLD_SEK == {1: 0.20, 2: 0.15, 3: 0.10, 4: 0.05, 5: 0.00}
        assert reserve_threshold_sek(99) == 0.10

    def test_short_known_window_caps_reserve(self):
        known = slots(8, 0.80)  # 2 hours at 5 kW, 0.9 charge efficiency -> 9 kWh
        unseen = unseen_day(cheap=1.40, expensive=2.50, evening_load_kwh=15.0, evening_slots=8)
        result = size(
            known,
            unseen,
            max_charge_kw=5.0,
            charge_efficiency=0.9,
            discharge_efficiency=1.0,
            usable=20.0,
            above_min=0.0,
        )

        assert result.reserve_kwh == pytest.approx(9.0)

    def test_usable_capacity_cap(self):
        known = slots(40, 0.80)
        unseen = unseen_day(cheap=1.40, expensive=2.50, evening_load_kwh=7.0)
        result = size(known, unseen, usable=5.0)

        assert result.reserve_kwh == pytest.approx(5.0)
        assert result.capped_by == "usable_capacity"

    def test_empty_known_window(self):
        result = size([], unseen_day(cheap=1.40, expensive=2.50, evening_load_kwh=6.0))

        assert result.reserve_kwh == 0.0
        assert result.reason == "no_known_window"

    def test_no_charge_power(self):
        known = slots(16, 0.80)
        result = size(known, unseen_day(1.40, 2.50, 6.0), max_charge_kw=0.0)

        assert result.reserve_kwh == 0.0
        assert result.reason == "no_charge_capacity"

    def test_marginal_cost_rises_as_cheap_known_slots_are_used(self):
        # Two cheap known slots hold 2.1 kWh each; beyond them the known cost is 1.50.
        known = [*slots(2, 0.50), *slots(10, 1.50, start=T0 + 2 * QUARTER)]
        unseen = unseen_day(cheap=1.60, expensive=3.00, evening_load_kwh=7.0)
        result = size(known, unseen, usable=30.0)

        # Cheap slots hold 2 x 8.88 x 0.25 x 0.95 kWh; the next unit costs 1.5/0.9025+0.1=1.76
        # against own-day 1.60/0.9025+0.1=1.87 -> gain 0.11 > 0.10, so it keeps going.
        assert result.reserve_kwh == pytest.approx(7.0 / 0.95)


def _forecast_df(horizon_end, *, load=1.0, pv=0.0, hours=24, skip=0) -> pd.DataFrame:
    idx = pd.date_range(horizon_end + QUARTER, periods=hours * 4, freq="15min")
    df = pd.DataFrame({"load_forecast_kwh": load, "pv_forecast_kwh": pv}, index=idx)
    return df.iloc[skip:]


def _inputs(
    horizon_end, *, unseen_price=1.40, evening_price=2.50, **overrides
) -> PriceReserveInputs:
    prices = {}
    ts = horizon_end + QUARTER
    for i in range(96):
        prices[ts + i * QUARTER] = evening_price if 70 <= i < 74 else unseen_price
    params: dict[str, Any] = {
        "known_slots": slots(16, 0.80),
        "unseen_prices": prices,
        "current_soc_kwh": MIN_SOC_KWH,
        **LIMITS,
        "forecast_issue_timestamp": "2026-04-10T13:30:00+02:00",
    }
    params.update(overrides)
    return PriceReserveInputs(**params)


class TestEvaluate:
    horizon_end = pd.Timestamp(T0 + 40 * QUARTER)

    def _evaluate(self, inputs, df):
        return evaluate_price_reserve(
            inputs,
            df,
            self.horizon_end,
            self.horizon_end + timedelta(hours=24),
            risk_appetite=3,
            min_soc_kwh=MIN_SOC_KWH,
            max_soc_kwh=27.0,
        )

    def test_disabled(self):
        assert self._evaluate(None, _forecast_df(self.horizon_end)).reason == "disabled"

    def test_read_error(self):
        inputs = _inputs(self.horizon_end, error="forecast_read_error", unseen_prices={})
        result = self._evaluate(inputs, _forecast_df(self.horizon_end))
        assert result.reason == "forecast_read_error"
        assert result.reserve_kwh == 0.0

    def test_no_known_window(self):
        inputs = _inputs(self.horizon_end, known_slots=[])
        assert self._evaluate(inputs, _forecast_df(self.horizon_end)).reason == "no_known_window"

    def test_insufficient_price_forecast(self):
        inputs = _inputs(self.horizon_end)
        keep = sorted(inputs.unseen_prices)[: int(96 * 0.89)]
        inputs = _inputs(self.horizon_end, unseen_prices={k: inputs.unseen_prices[k] for k in keep})
        result = self._evaluate(inputs, _forecast_df(self.horizon_end))
        assert result.reason == "insufficient_forecast"

    def test_insufficient_load_forecast(self):
        inputs = _inputs(self.horizon_end)
        result = self._evaluate(inputs, _forecast_df(self.horizon_end, skip=12))  # 87.5% covered
        assert result.reason == "insufficient_load_forecast"
        assert self._evaluate(inputs, None).reason == "insufficient_load_forecast"

    def test_sizes_from_forecast_net_load(self):
        inputs = _inputs(self.horizon_end)
        df = _forecast_df(self.horizon_end, load=0.0, pv=0.0)
        df.iloc[70:74, df.columns.get_loc("load_forecast_kwh")] = 1.5
        result = self._evaluate(inputs, df)

        # Only the 4 expensive slots (1.5 kWh net load each) carry load.
        assert result.reason == "active"
        assert result.reserve_kwh == pytest.approx(6.0 / 0.95)

    def test_pv_covered_load_contributes_nothing(self):
        inputs = _inputs(self.horizon_end)
        result = self._evaluate(inputs, _forecast_df(self.horizon_end, load=1.0, pv=2.0))
        assert result.reserve_kwh == 0.0

    def test_slots_outside_window_are_ignored(self):
        inputs = _inputs(self.horizon_end)
        shifted = {k + timedelta(days=2): v for k, v in inputs.unseen_prices.items()}
        result = self._evaluate(
            _inputs(self.horizon_end, unseen_prices=shifted), _forecast_df(self.horizon_end)
        )
        assert result.reason == "insufficient_forecast"


def _safety_floor(inputs, *, load=1.5, pv=0.0, battery=BATTERY, evening_only=False):
    horizon_end = pd.Timestamp(T0 + 40 * QUARTER)
    idx = pd.date_range(T0, horizon_end, freq="15min")
    df = pd.DataFrame(
        {"load_forecast_kwh": 0.5, "pv_forecast_kwh": 0.0, "import_price_sek_kwh": 0.8}, index=idx
    )
    unseen = _forecast_df(horizon_end, load=0.0 if evening_only else load, pv=pv)
    if evening_only:
        unseen.iloc[70:74, unseen.columns.get_loc("load_forecast_kwh")] = load
    full = pd.concat([df[["load_forecast_kwh", "pv_forecast_kwh"]], unseen])
    return calculate_safety_floor(
        df,
        battery,
        S_INDEX_CFG,
        "Europe/Stockholm",
        full_forecast_df=full,
        price_horizon_end=horizon_end,
        price_reserve_inputs=inputs,
    )


class TestSafetyFloorCombination:
    horizon_end = pd.Timestamp(T0 + 40 * QUARTER)

    def test_disabled_equals_deficit_floor_and_reports_all_debug_keys(self):
        floor, debug = _safety_floor(None)

        assert floor == pytest.approx(debug["calculated_floor_kwh"], abs=0.01)
        assert debug["price_reserve_active"] is False
        assert debug["price_reserve_reason"] == "disabled"
        for key in (
            "price_reserve_threshold_sek",
            "unseen_window_start",
            "unseen_window_end",
            "known_cost_sek_kwh",
            "own_day_cost_sek_kwh",
            "price_reserve_kwh",
            "price_reserve_applied_kwh",
            "forecast_issue_timestamp",
            "final_floor_kwh",
        ):
            assert key in debug

    def test_deficit_floor_wins_when_it_covers_the_reserve(self):
        baseline, _ = _safety_floor(None, load=0.25, evening_only=True)
        floor, debug = _safety_floor(_inputs(self.horizon_end), load=0.25, evening_only=True)

        # 1 kWh of evening net load -> reserve ~1.05 kWh, far below the deficit floor.
        assert debug["price_reserve_active"] is True
        assert 0.0 < debug["price_reserve_kwh"] < baseline - MIN_SOC_KWH
        assert floor == pytest.approx(baseline)
        assert debug["price_reserve_applied_kwh"] == 0.0

    def test_reserve_wins_when_larger(self):
        baseline, _ = _safety_floor(None, load=1.5, evening_only=True)
        floor, debug = _safety_floor(_inputs(self.horizon_end), load=1.5, evening_only=True)

        # 6 kWh evening net load -> 6.32 kWh reserve; target = min_soc + reserve, not floor + reserve.
        assert debug["price_reserve_kwh"] == pytest.approx(6.0 / 0.95, abs=1e-3)
        assert floor == pytest.approx(MIN_SOC_KWH + 6.0 / 0.95, abs=0.01)
        assert floor > baseline
        assert debug["price_reserve_applied_kwh"] == pytest.approx(floor - baseline, abs=0.01)

    def test_final_floor_never_below_deficit_floor(self):
        baseline, _ = _safety_floor(None)
        inputs = _inputs(self.horizon_end, unseen_price=0.1, evening_price=0.1)  # nothing pays off
        floor, debug = _safety_floor(inputs)

        assert floor == pytest.approx(baseline)
        assert debug["price_reserve_applied_kwh"] == 0.0
        assert debug["price_reserve_active"] is False

    def test_target_clamped_to_max_soc(self):
        battery = {**BATTERY, "max_soc_percent": 50.0}
        floor, _ = _safety_floor(_inputs(self.horizon_end), battery=battery)

        assert floor <= 0.5 * 27.0 + 1e-9

    def test_forecast_read_error_keeps_floor(self):
        baseline, _ = _safety_floor(None)
        floor, debug = _safety_floor(
            _inputs(self.horizon_end, error="forecast_read_error", unseen_prices={})
        )

        assert floor == pytest.approx(baseline)
        assert debug["price_reserve_reason"] == "forecast_read_error"
