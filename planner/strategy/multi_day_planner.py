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
        min_chunk_kwh: float = 0.0,
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
            min_chunk_kwh: Smallest energy the downstream solver can schedule
                in one slot (device-specific, computed by the caller). 0 (the
                default) disables the chunk constraint — every day's
                allocation is either 0 or at least this much; goals smaller
                than one chunk are floored to exactly one chunk on the
                cheapest day with capacity.

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
        caps = [max_daily_kwh[i] if i < len(max_daily_kwh) else float("inf") for i in range(n)]

        # D4: the goal itself is smaller than one chunk — deliver exactly one
        # chunk on the cheapest day with capacity rather than an undeliverable
        # sub-chunk allocation. Bounded overshoot beats silent failure. If no
        # day's cap can hold a full chunk, there is no deliverable allocation
        # this run — return all-zero rather than stranding a sub-chunk value
        # the solver could never actually use (its quota cap would still
        # reject any nonzero charging slot).
        if min_chunk_kwh > 0 and remaining_kwh < min_chunk_kwh:
            order = sorted(range(n), key=lambda j: prices[j])
            target = next((j for j in order if caps[j] >= min_chunk_kwh), None)
            allocation = [0.0] * n
            if target is not None:
                allocation[target] = min_chunk_kwh
            return {day: allocation[i] for i, day in enumerate(days)}

        if n == 1:
            return {today: remaining_kwh}

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

        # Re-clamp to physical per-day caps and non-negativity — the rescale
        # above can push a day back above its cap. Redistribute any residual
        # to days with remaining headroom instead of emitting a negative or
        # above-cap allocation; if every day is at its cap, the allocation
        # legitimately sums to less than remaining_kwh (physically that's
        # all that can be delivered).
        allocation = [min(max(0.0, a), caps[i]) for i, a in enumerate(allocation)]
        for _ in range(n):
            residual = remaining_kwh - sum(allocation)
            if residual <= 1e-9:
                break
            headroom_days = [i for i in range(n) if allocation[i] < caps[i] - 1e-9]
            if not headroom_days:
                break
            total_headroom = sum(caps[i] - allocation[i] for i in headroom_days)
            if total_headroom <= 0:
                break
            distribute = min(residual, total_headroom)
            for i in headroom_days:
                share = (caps[i] - allocation[i]) / total_headroom
                allocation[i] += distribute * share
            allocation = [min(max(0.0, a), caps[i]) for i, a in enumerate(allocation)]

        if min_chunk_kwh > 0:
            allocation = MultiDayPlanner._consolidate_chunks(
                allocation, caps, prices, min_chunk_kwh
            )

        return {day: allocation[i] for i, day in enumerate(days)}

    @staticmethod
    def _consolidate_chunks(
        allocation: list[float],
        caps: list[float],
        prices: list[float],
        min_chunk_kwh: float,
    ) -> list[float]:
        """Zero out days below one chunk, redistributing their energy to the
        cheapest day(s) that already meet (or can be raised to meet) the
        chunk within their capacity caps (design D3).

        Never pushes a day above its cap, and never leaves a day with a
        nonzero allocation below the chunk. Preserves the total allocation
        except when no day's cap can hold a full chunk — that energy is
        physically undeliverable this run and is dropped rather than
        stranded as an unusable sub-chunk value.
        """
        n = len(allocation)
        allocation = list(allocation)
        for _ in range(n + 1):
            deficient = [i for i in range(n) if 1e-9 < allocation[i] < min_chunk_kwh - 1e-9]
            if not deficient:
                break

            pool = sum(allocation[i] for i in deficient)
            for i in deficient:
                allocation[i] = 0.0

            order = sorted(range(n), key=lambda j: prices[j])
            for j in order:
                if pool <= 1e-9:
                    break
                headroom = caps[j] - allocation[j]
                if headroom <= 1e-9:
                    continue
                if allocation[j] < min_chunk_kwh:
                    # Zero/deficient day: only accept if there's enough pool
                    # *and* enough headroom to raise it to at least the chunk
                    # — otherwise skip to avoid stranding a new sub-chunk
                    # pocket (e.g. a day capped below the chunk size).
                    needed = min_chunk_kwh - allocation[j]
                    if pool < needed or headroom < needed:
                        continue
                add = min(pool, headroom)
                allocation[j] += add
                pool -= add

            # Any leftover pool means no day's cap could hold a full chunk —
            # headroom is too fragmented (or too small everywhere) to
            # consolidate. Leave it undistributed rather than stranding a new
            # sub-chunk pocket the solver could never use anyway (its own
            # quota cap would reject a nonzero slot below the chunk). This is
            # the same "physically undeliverable this run" trade-off already
            # accepted by the capacity-cap handling in compute_quota.

        return allocation
