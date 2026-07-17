# Design: EV Fractional Planning and Quota Floor

## Context

The Kepler MILP declares `ev_charge[d][t]` as `cat="Binary"` for every plugged-in charger (`planner/solver/kepler.py:166-171`) and links energy via `ev_energy[d][t] == ev_charge[d][t] * max_power_kw * h` (`kepler.py:419`). A charger's `type: current` config (`min_current_a`/`max_current_a`, phases) only affects the executor's amp conversion (`executor/load_balancer.py:planned_kw_to_amps`), never what the planner may schedule. The multi-day spreader (`planner/strategy/multi_day_planner.py:compute_quota`) splits `remaining_kwh` by inverse price with min-fraction floors and per-day capacity caps, but no lower bound tied to the solver's minimum schedulable unit; `kepler.py:668` then enforces each day's quota as a hard `<=`. Observed failure: 2.6 kWh goal split into `{0.88, 1.72}` against a 2.425 kWh minimum unit → infeasible on both days → silent full shortfall at `status: Optimal`.

Uncommitted keep-on-slot-flag work touches some of the same files; that change lands first (user is closing it).

## Goals / Non-Goals

**Goals:**
- `type: current` chargers are planned semi-continuously: per slot, either off or at a power in `[min_power_kw, max_power_kw]`.
- Daily quotas are always deliverable: each day gets 0 or ≥ one minimum chunk; a goal smaller than one chunk still yields one minimum-power slot (bounded overshoot).
- Any remaining "active goal produced zero scheduled energy" outcome logs a warning.

**Non-Goals:**
- No change to `type: binary` charger planning (stays full-power-or-off).
- No change to executor control, load balancer, surplus-PV dispatch mechanics, or config schema.
- No per-slot amp *integrality* in the planner (planner emits kW; executor floors to integer amps as today).

## Decisions

### D1: Semi-continuous power via existing binary + continuous energy variable

Keep `ev_charge[d][t]` binary for all chargers (it drives source isolation at `kepler.py:399`, `any_ev_charging` at `kepler.py:432-433`, and anti-flap/keep-on logic). For `type: current` chargers, replace the equality energy link with bounds:

- `ev_energy[d][t] >= min_power_kw * h * ev_charge[d][t]`
- `ev_energy[d][t] <= max_power_kw * h * ev_charge[d][t]`

For `type: binary` chargers the equality link stays. This is the standard semi-continuous MILP pattern: no new binaries, no objective changes, all existing constraints (deadline zeroing, quota caps, import limits, energy balance, shortfall accounting) already operate on `ev_energy` and carry over unchanged. Alternative considered: a separate continuous `ev_power` variable — rejected, `ev_energy` already is that variable times `h`.

Interaction with surplus charging: `ev_surplus_kw` is gated by `(1 - ev_charge[t])` (`kepler.py:399`) — unchanged; a slot is either planned charging (now fractional) or a surplus sink, never both.

### D2: `min_power_kw` derived in the adapter, with rounding margin

`EVChargerInput` gains `min_power_kw: float = 0.0`. The adapter computes it for `type: current` chargers as `min_current_a × 230 V × phase_count / 1000`, using the charger's configured phases (default 3) and the same 230 V constant as `planned_kw_to_amps`. Because the executor *floors* kW→amps and pauses below `min_current_a`, the planner bound gets a small safety margin (multiply by 1.01, ~0.15 A equivalent) so a planned minimum never floors to `min_current_a − 1`. For `type: binary` chargers, `min_power_kw = max_power_kw` (equivalent to today's model, handled by the equality link).

### D3: Chunk-aware quota as a post-processing step in `compute_quota`

`compute_quota` gains a `min_chunk_kwh: float = 0.0` parameter (keeps the component load-type agnostic — callers pass the chunk, no EV knowledge inside). After the existing allocation/cap/rescale steps, a final normalization pass enforces: every day's allocation is either 0 or ≥ `min_chunk_kwh`. Days below the chunk are zeroed and their energy moved to the cheapest day(s) with headroom that already meet (or can be raised to) the chunk. If the *total* goal is below one chunk, allocate exactly one chunk to the cheapest feasible day (deliberate overshoot; D4 explains why). In the overwhelmingly common case a chunk is far below any day's capacity cap, so this is a non-issue. In the rare case where *every* day's cap is below the chunk (e.g. a deadline landing within minutes, leaving almost no capacity on the boundary day), there is no deliverable allocation at all — the pool is dropped rather than stranded as a sub-chunk value the solver's own quota cap would reject anyway; `_warn_on_zero_scheduled_active_goals` (D5) surfaces this as a zero-scheduled warning.

The pipeline (`_compute_daily_ev_quota`) computes `min_chunk_kwh` per charger from the solver's perspective: `min plannable power × slot_h` — `min_power_kw` for `type: current`, `max_power_kw` for `type: binary`.

Alternative considered: loosening the solver's per-day `<=` quota cap to tolerate one chunk of overshoot — rejected as the primary fix (weakens the spreading contract for all goals), but the sub-chunk-goal case (D4) uses a bounded version of the same idea at the quota level instead of the solver level.

### D4: Sub-chunk goals overshoot by design

When `remaining_kwh < min_chunk_kwh`, the quota for the chosen day is `min_chunk_kwh` (not `remaining_kwh`). The solver's shortfall variable only penalizes *under*-delivery, so scheduling one minimum-power slot satisfies the goal; the car's BMS stops at 100% regardless. Overshoot is bounded by < 1 chunk (≈0.5–1 kWh for a current-type charger at min amps, one 15-min slot). User-approved 2026-07-17.

### D5: Zero-scheduled warning in the pipeline, not the solver

After a solve, if a charger had `required_kwh > 0` and an active deadline but total scheduled energy for it is 0, the pipeline logs a WARNING naming the charger, required kWh, quota split, and min chunk. Placed in the pipeline (where quota context lives), not kepler (which only sees the already-split quotas).

## Risks / Trade-offs

- [Semi-continuous model changes solver search space] → Existing solver test suite covers deadline, quota, import-limit, surplus, and isolation behavior; add regression test reproducing the 2.6 kWh zero-out and a fractional-power assertion. Binary chargers keep byte-identical constraints.
- [Executor floor-rounding could pause a minimum-power plan] → 1% margin on `min_power_kw` (D2); executor behavior itself unchanged.
- [Chunk redistribution could starve the min-daily-fraction anti-deferral floor] → Chunk normalization runs last and only zeroes days already below one chunk — days that were never deliverable anyway; the anti-deferral intent (don't push everything to the last day) is preserved for all deliverable allocations.
- [Fractional planned kW surfaces in schedule/charts] → Output schema already carries floats per charger (`ev_chargers: {id: {charging_kw}}`); verify Executor/Dashboard pages render sensible values during change verification.

## Migration Plan

Pure planner-side change; no config, API, DB, or frontend migration. Deploy normally; next planner run picks it up. Rollback = revert commit.

## Open Questions

None — design decisions confirmed with the user 2026-07-17 (both fixes in one change; min from config, not hardcoded; current-type always fractional, no toggle; sub-chunk goals overshoot one slot).
