"""Load-agnostic multi-day energy quota planner.

Uses inverse-price weighting to spread a required energy amount across the
days remaining until a deadline, with guardrails to prevent over-deferral
and respect per-day power capacity.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


class MultiDayPlanner:
    """Compute daily energy quotas from price forecasts and physical limits."""

    @staticmethod
    def compute_quota(
        remaining_kwh: float,
        deadline: datetime,
        daily_prices: dict[int, float],
        max_daily_kwh: list[float],
        min_daily_fraction: float = 0.1,
        now: datetime | None = None,
    ) -> dict[date, float]:
        """Spread ``remaining_kwh`` across the days until ``deadline``.

        Args:
            remaining_kwh: Energy still required (kWh).
            deadline: Target datetime (timezone-aware).
            daily_prices: Mapping from days-ahead offset (0 = today) to average
                price for that day. Missing offsets are filled with the average
                of the known days.
            max_daily_kwh: Per-day maximum energy (kWh), ordered from today.
                Used as a hard cap; excess is redistributed to other days.
            min_daily_fraction: Minimum share of ``remaining_kwh`` that every
                non-final day must receive (default 10%).
            now: Current datetime (timezone-aware). If None, defaults to current time.

        Returns:
            Mapping from calendar date to allocated kWh.
        """
        if remaining_kwh <= 0:
            return {}

        if now is None:
            tz = deadline.tzinfo
            now = datetime.now(tz) if tz else datetime.now()
        today = now.date()
        deadline_date = deadline.date()

        if deadline_date < today:
            return {}

        # Build the list of days from today up to and including the deadline day.
        days: list[date] = []
        d = today
        while d <= deadline_date:
            days.append(d)
            d += timedelta(days=1)

        n = len(days)
        if n == 1:
            return {today: remaining_kwh}

        # Collect prices, filling missing days with the average of known days.
        known_prices: list[float] = []
        price_for_day: list[float | None] = []
        for i in range(n):
            price = daily_prices.get(i)
            price_for_day.append(price)
            if price is not None:
                known_prices.append(price)

        avg_price = sum(known_prices) / len(known_prices) if known_prices else 1.0
        prices = [p if p is not None else avg_price for p in price_for_day]

        # Inverse-price weights.
        weights = [1.0 / max(p, 0.0001) for p in prices]
        total_weight = sum(weights)
        allocation = [remaining_kwh * (w / total_weight) for w in weights]

        # Iteratively apply min-floor and max-cap constraints.
        final_idx = n - 1
        min_floor = remaining_kwh * min_daily_fraction
        for _ in range(n * 2):
            changed = False

            # Min floor on non-final days: pull deficit from the final day.
            for i in range(final_idx):
                if allocation[i] < min_floor:
                    deficit = min_floor - allocation[i]
                    allocation[i] = min_floor
                    if allocation[final_idx] >= deficit:
                        allocation[final_idx] -= deficit
                    else:
                        # Not enough in final day; take from all later days proportionally.
                        later_total = sum(allocation[j] for j in range(i + 1, n))
                        if later_total > 0:
                            for j in range(i + 1, n):
                                allocation[j] -= deficit * (allocation[j] / later_total)
                    changed = True

            # Max cap: push excess to other uncapped days proportionally.
            for i in range(n):
                cap = max_daily_kwh[i] if i < len(max_daily_kwh) else float("inf")
                if allocation[i] > cap:
                    excess = allocation[i] - cap
                    allocation[i] = cap
                    others = [
                        j
                        for j in range(n)
                        if j != i
                        and allocation[j]
                        < (max_daily_kwh[j] if j < len(max_daily_kwh) else float("inf"))
                    ]
                    if others:
                        others_total = sum(allocation[j] for j in others)
                        headroom = sum(
                            (max_daily_kwh[j] if j < len(max_daily_kwh) else float("inf"))
                            - allocation[j]
                            for j in others
                        )
                        distribute = min(excess, headroom)
                        if others_total > 0:
                            for j in others:
                                allocation[j] += distribute * (allocation[j] / others_total)
                        if distribute < excess:
                            # Cap exceeded even after redistribution; leave remainder on final day
                            allocation[final_idx] += excess - distribute
                    else:
                        allocation[final_idx] += excess
                    changed = True

            if not changed:
                break

        # Ensure non-negative and preserve total as closely as possible.
        allocation = [max(0.0, a) for a in allocation]
        current_total = sum(allocation)
        if current_total > 0 and abs(current_total - remaining_kwh) > 1e-6:
            # Scale to maintain the requested total (when caps prevent exact redistribution).
            scale = remaining_kwh / current_total
            allocation = [a * scale for a in allocation]

        return {day: allocation[i] for i, day in enumerate(days)}
