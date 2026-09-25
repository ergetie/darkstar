## Context

The configured `load_power` entity is the gross whole-home meter reading. The Dashboard passes it directly to the Power Flow House node (`Dashboard.tsx`, `house.kw: livePower.load_kw`) while also passing `ev_kw` and `water_kw` to separate nodes. Both are backend sums across configured devices (`backend/ha_socket.py`).

The recorder stores `SlotObservation.load_kwh` as base load. Without a disaggregator (or with a cumulative load sensor) it subtracts EV and water energy from total load and clamps at zero; with a disaggregator it stores the disaggregator's base-load value directly (`backend/recorder.py`). Either way the column is base load.

The Energy Resources card takes today's actual from that column (`load_consumption_kwh`), but its average from `/api/ha/average`, which averages the gross sensor and converts a missing value to `0` on the frontend.

## Goals / Non-Goals

**Goals:**

- Show the Power Flow House node as the residual after subtracting the EV and water loads shown on their own nodes.
- Compare the Energy Resources actual and average using the same base-load definition.
- Preserve raw gross load readings for other consumers.
- Reuse existing measurements and stored observations; no schema or dependency changes.

**Non-Goals:**

- Change load forecasting, planner inputs, or recorder semantics.
- Rename or redefine the global `load_kw` / `load_power_kw` fields.
- Change `/api/ha/average` or its other consumers (e.g. PowerFlowLab, LoadBalancerStatusCard).
- Scale the average to time of day. The average stays a full-day figure next to today's so-far actual, as it is today.
- Recalculate or migrate existing database rows.

## Decisions

1. **Compute House residual in a pure frontend helper.** Add `computeHouseKw(grossKw, evKw, waterKw, enabledNodeIds)` beside `PowerFlowRegistry.ts`. It returns `max(0, grossKw - ev - water)`, subtracting `evKw` only when the `ev` node is enabled (`system.has_ev_charger`) and `waterKw` only when the `water` node is enabled (`system.has_water_heater`). Per-device `enabled` flags are already applied by the backend when it builds the `ev_kw` / `water_kw` totals, so the frontend does not re-filter devices. Missing values count as 0. `Dashboard.tsx` calls the helper; `livePower.load_kw` itself is not modified. Rejected: changing the shared load field, because other consumers rely on its gross meaning.

2. **Serve the base-load average as a field on `GET /api/energy/today`.** Add `base_load_avg_daily_kwh`: the sum of `SlotObservation.load_kwh` over the 96 completed 15-minute slots ending at the start of the current slot. The Dashboard already calls this endpoint, so no extra request is needed.
   - Coverage: return the value only when at least 87 of the 96 slots (≥90%) have a non-null `load_kwh`. The value is the recorded sum scaled to 96 slots (`sum × 96 / count`), so a few missing slots do not bias it low. Below 87 slots, return `null`.
   - Rejected: a new endpoint (extra request and surface for one number), and keeping the gross `/api/ha/average` (wrong basis).

3. **Render missing average as unavailable.** The frontend maps `null` to `loadAvg = null`, which the card already renders as its unavailable value. It never falls back to 0 or to the gross average.

## Risks / Trade-offs

- **Recorder gaps can hide the average.** Accepted. Showing nothing is better than a gross or partial number.
- **Live readings arrive as separate websocket events,** so the gross and managed values can briefly disagree. The clamp at zero covers the negative case; brief over/under readings are acceptable for a live display.
- **Unavailable managed readings count as zero,** so House can briefly show more than the true base load. No inference from the grid balance.
