# Proposal

## Why

The missed-goal grace window (`missed_goal_grace_hours`, commit 5440027b) only checks that the charger is plugged in *now*. Verified on the Torleif bundle (2026-11-10): the car was unplugged 05:56 at 82% (goal 85% by 06:00), driven away (SoC fell to 66%) and replugged 07:22. The grace logic treated it as "still plugged after a missed deadline", returned a 10:00 grace deadline with 15.58 kWh, overrode the rolled goal (next day 06:00) and forced ~7 kWh into 5.5-5.9 SEK slots instead of ~2.4 SEK overnight. Diagnostics also use a 15-minute-floored now, so slot-0 eligibility and min-chunk reporting are wrong for a partial slot.

## What Changes

- Grace applies only if the charger was continuously plugged across the missed deadline (plug-session start tracked in the existing in-memory plug state; non-stale SoC required; a replug after the deadline gets no grace).
- Whenever grace would otherwise be granted (plug history known as continuous, e.g. a restored saved session, or unknown), grace compares the current SoC with the SoC at the missed deadline (read from HA history of the charger's SoC sensor): a drop beyond a small noise threshold means the car was driven, so no grace. With no deadline SoC available, legacy behaviour applies.
- New per-charger `missed_goal_tolerance_percent` (default 5 percentage points, 0 = off): no grace when SoC >= target - tolerance. Applies only to the catch-up grace, not normal goal planning.
- The grace target becomes a soft target in Kepler whose shortfall penalty is derived from the horizon's import prices (cheapest price before the next regular deadline plus a fraction of the price spread), so it behaves the same in cheap and expensive markets and never forces expensive slots when the next goal can deliver cheaper.
- Goal diagnostics use the real (unfloored) now for eligibility and remaining slot-0 time, classify `deadline_too_close` when remaining time x max kW cannot cover the requirement, and no longer report a full-slot min_chunk for a partial slot.
- No DB schema change.

## Capabilities

### New Capabilities

### Modified Capabilities
- `ev-missed-goal-recovery`: grace requires plug continuity across the missed deadline; grace target is a low-penalty soft target.
- `ev-goal-shortfall-diagnostics`: diagnostics use real now and partial-slot-aware classification

## Impact

- `backend/core/ev_plug.py` (plug-session tracking), `backend/core/ev_live_state.py`, `backend/core/ha_client.py` (feed session info into ha_state)
- `planner/pipeline.py` (`resolve_ev_effective_deadline`, `_resolve_ev_charger_plan_state`, `compute_ev_goal_diagnostics`, `_warn_on_zero_scheduled_active_goals`, now plumbing ~1442/1696)
- `planner/solver/kepler.py`, `types.py`, `adapter.py` (per-charger, price-derived shortfall penalty)
- `backend/core/ha_client.py` (read SoC at the missed deadline from HA history), `config.default.yaml`, `frontend/src/pages/settings/components/EntityArrayEditor.tsx` (new tolerance field)
- Tests under `tests/planner/`. Out of scope: planning EV on forecast D+1 prices (separate change).
