"""
Price reserve for the first unseen day.

The Kepler solver only sees published prices. Its terminal SoC target comes from
the deficit-based safety floor. This module sizes an additional reserve (kWh,
battery side) for the 24 hours after the price horizon: when storing energy in
the cheapest known-window slots beats buying in that unseen day's expensive hours
by more than a risk-dependent margin, the target is raised so the solver charges
in the cheapest known slots.

Everything here is pure (no I/O). The pipeline gathers the inputs; the safety
floor combines the result with the deficit floor via ``max`` (never addition).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

# Profitability threshold per delivered kWh (SEK) by risk appetite. A cautious
# user needs a larger margin before pre-charging for forecast prices.
RISK_RESERVE_THRESHOLD_SEK: dict[int, float] = {
    1: 0.20,
    2: 0.15,
    3: 0.10,
    4: 0.05,
    5: 0.00,
}
DEFAULT_RISK_APPETITE = 3

# Minimum share of unseen-window slots that must carry a price / load forecast.
MIN_WINDOW_COVERAGE = 0.90

_EPS = 1e-9


def reserve_threshold_sek(risk_appetite: int) -> float:
    """Profitability threshold for a risk level (unknown levels use risk 3)."""
    return RISK_RESERVE_THRESHOLD_SEK.get(
        risk_appetite, RISK_RESERVE_THRESHOLD_SEK[DEFAULT_RISK_APPETITE]
    )


@dataclass(frozen=True)
class ReserveSlot:
    """One time slot: length, import price and (unseen window only) net load."""

    start: datetime
    hours: float
    price: float  # import price, SEK/kWh
    net_load_kwh: float = 0.0  # max(0, load - pv); unseen-window slots only


@dataclass(frozen=True)
class PriceReserveResult:
    """Outcome of the reserve sizing."""

    reserve_kwh: float
    reason: str
    known_cost_sek_kwh: float | None = None
    own_day_cost_sek_kwh: float | None = None
    capped_by: str | None = None

    @property
    def active(self) -> bool:
        return self.reserve_kwh > _EPS


@dataclass(frozen=True)
class PriceReserveInputs:
    """Everything the pipeline gathers for the reserve (no I/O in this module)."""

    known_slots: list[ReserveSlot]  # current slot .. end of published-price horizon
    unseen_prices: Mapping[datetime, float]  # forecast import price by slot start
    current_soc_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    charge_efficiency: float
    discharge_efficiency: float
    wear_cost_sek_kwh: float
    slot_hours: float = 0.25
    forecast_issue_timestamp: str | None = None
    error: str | None = None  # set when gathering inputs failed (e.g. forecast_read_error)


class _CostCurve:
    """Marginal cost of stored energy when charging cheapest-first.

    Cost is per delivered kWh: ``price / (charge_eff * discharge_eff) + wear``.
    Each slot can add at most ``max_charge_kw * hours * charge_eff`` stored kWh.
    """

    def __init__(
        self,
        slots: list[ReserveSlot],
        max_charge_kw: float,
        charge_efficiency: float,
        discharge_efficiency: float,
        wear_cost_sek_kwh: float,
    ) -> None:
        round_trip = charge_efficiency * discharge_efficiency
        segments: list[tuple[float, float]] = []
        if round_trip > 0:
            for slot in slots:
                capacity = max_charge_kw * slot.hours * charge_efficiency
                if capacity > _EPS:
                    segments.append((slot.price / round_trip + wear_cost_sek_kwh, capacity))
        segments.sort(key=lambda seg: seg[0])
        self._costs: list[float] = []
        self._ends: list[float] = []
        total = 0.0
        for cost, capacity in segments:
            total += capacity
            self._costs.append(cost)
            self._ends.append(total)
        self.total_capacity_kwh = total

    def at(self, energy_kwh: float) -> tuple[float, float]:
        """Marginal cost at ``energy_kwh`` and the stored kWh left in that segment.

        Beyond total capacity the cost is infinite (nothing more can be charged).
        """
        for cost, end in zip(self._costs, self._ends, strict=True):
            if energy_kwh < end - _EPS:
                return cost, end - energy_kwh
        return math.inf, math.inf


def size_price_reserve(
    *,
    known_slots: list[ReserveSlot],
    unseen_slots: list[ReserveSlot],
    max_charge_kw: float,
    max_discharge_kw: float,
    charge_efficiency: float,
    discharge_efficiency: float,
    wear_cost_sek_kwh: float,
    threshold_sek_kwh: float,
    usable_capacity_kwh: float,
    current_soc_above_min_kwh: float,
) -> PriceReserveResult:
    """Size the reserve (battery-side kWh above min SoC) for the unseen window.

    Unseen slots are visited from the highest import price down. For a slot ``h``
    with price ``P_h``: ``gain_h = min(P_h, own_day_cost) - known_cost``; energy
    ``min(net_load_h, max_discharge_kw * hours) / discharge_efficiency`` is added
    while ``gain_h > threshold``, re-evaluating both marginal costs as energy
    accumulates. The result is capped by usable capacity and by what the known
    window can charge above the current SoC.
    """
    if not known_slots:
        return PriceReserveResult(0.0, "no_known_window")

    known = _CostCurve(
        known_slots, max_charge_kw, charge_efficiency, discharge_efficiency, wear_cost_sek_kwh
    )
    own = _CostCurve(
        unseen_slots, max_charge_kw, charge_efficiency, discharge_efficiency, wear_cost_sek_kwh
    )
    known_first, _ = known.at(0.0)
    own_first, _ = own.at(0.0)
    known_debug = known_first if math.isfinite(known_first) else None
    own_debug = own_first if math.isfinite(own_first) else None

    if not math.isfinite(known_first):
        return PriceReserveResult(0.0, "no_charge_capacity", known_debug, own_debug)

    candidates: list[tuple[float, float]] = []
    if discharge_efficiency > 0:
        for slot in sorted(unseen_slots, key=lambda s: s.price, reverse=True):
            energy = min(slot.net_load_kwh, max_discharge_kw * slot.hours) / discharge_efficiency
            if energy > _EPS:
                candidates.append((slot.price, energy))
    if not candidates:
        return PriceReserveResult(0.0, "no_net_load", known_debug, own_debug)

    reserve = 0.0
    stop = False
    for price, slot_energy in candidates:
        remaining = slot_energy
        while remaining > _EPS:
            known_cost, known_left = known.at(reserve)
            own_cost, own_left = own.at(reserve)
            if not (min(price, own_cost) - known_cost > threshold_sek_kwh):
                stop = True
                break
            step = min(remaining, known_left, own_left)
            if step <= _EPS:
                stop = True
                break
            reserve += step
            remaining -= step
        if stop:
            break

    capped_by: str | None = None
    if reserve > usable_capacity_kwh + _EPS:
        reserve = max(0.0, usable_capacity_kwh)
        capped_by = "usable_capacity"
    reachable = max(0.0, current_soc_above_min_kwh) + known.total_capacity_kwh
    if reserve > reachable + _EPS:
        reserve = reachable
        capped_by = "known_window_charge"

    if reserve > _EPS:
        reason = "active"
    elif own_first <= known_first:
        reason = "own_day_cheaper"
    else:
        reason = "below_threshold"
    return PriceReserveResult(reserve, reason, known_debug, own_debug, capped_by)


def inactive_price_reserve(reason: str) -> PriceReserveResult:
    """A zero reserve with the reason it is inactive."""
    return PriceReserveResult(0.0, reason)


def evaluate_price_reserve(
    inputs: PriceReserveInputs | None,
    full_forecast_df: pd.DataFrame | None,
    window_start: datetime | pd.Timestamp,
    window_end: datetime | pd.Timestamp,
    *,
    risk_appetite: int,
    min_soc_kwh: float,
    max_soc_kwh: float,
) -> PriceReserveResult:
    """Apply the fallbacks, build the unseen window and size the reserve.

    The unseen window is ``(window_start, window_end]`` over slot starts, the
    same window the deficit-based safety floor looks at. Any missing input
    degrades to a zero reserve with a specific reason.
    """
    if inputs is None:
        return inactive_price_reserve("disabled")
    if inputs.error:
        return inactive_price_reserve(inputs.error)
    if not inputs.known_slots:
        return inactive_price_reserve("no_known_window")

    expected_slots = max(1, round(24.0 / inputs.slot_hours))
    start_ts = pd.Timestamp(window_start)
    end_ts = pd.Timestamp(window_end)

    prices = {pd.Timestamp(ts): price for ts, price in inputs.unseen_prices.items()}
    priced_slots = [ts for ts in prices if start_ts < ts <= end_ts]
    if len(priced_slots) < MIN_WINDOW_COVERAGE * expected_slots:
        return inactive_price_reserve("insufficient_forecast")

    net_load: pd.Series | None = None
    if (
        full_forecast_df is not None
        and not full_forecast_df.empty
        and {"load_forecast_kwh", "pv_forecast_kwh"} <= set(full_forecast_df.columns)
    ):
        window_df = full_forecast_df.loc[
            (full_forecast_df.index > start_ts) & (full_forecast_df.index <= end_ts),
            ["load_forecast_kwh", "pv_forecast_kwh"],
        ].dropna()
        if len(window_df) >= MIN_WINDOW_COVERAGE * expected_slots:
            net_load = (window_df["load_forecast_kwh"] - window_df["pv_forecast_kwh"]).clip(
                lower=0.0
            )
    if net_load is None:
        return inactive_price_reserve("insufficient_load_forecast")

    unseen_slots = [
        ReserveSlot(
            start=ts.to_pydatetime(),
            hours=inputs.slot_hours,
            price=prices[ts],
            net_load_kwh=float(net_load.get(ts, 0.0)),
        )
        for ts in sorted(priced_slots)
    ]

    return size_price_reserve(
        known_slots=inputs.known_slots,
        unseen_slots=unseen_slots,
        max_charge_kw=inputs.max_charge_kw,
        max_discharge_kw=inputs.max_discharge_kw,
        charge_efficiency=inputs.charge_efficiency,
        discharge_efficiency=inputs.discharge_efficiency,
        wear_cost_sek_kwh=inputs.wear_cost_sek_kwh,
        threshold_sek_kwh=reserve_threshold_sek(risk_appetite),
        usable_capacity_kwh=max(0.0, max_soc_kwh - min_soc_kwh),
        current_soc_above_min_kwh=max(0.0, inputs.current_soc_kwh - min_soc_kwh),
    )
