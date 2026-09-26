## Why

Saving or clearing an EV goal — in the dashboard or in Home Assistant — does nothing until the next scheduled planner run (up to 60 min), and meanwhile the EV card shows the previous goal's numbers under an optimistic "On track". Goal semantics also drift: an HA ready-by edit can become either a one-off or a daily goal depending on timing, and `every_n_days` cycles silently shift whenever `last_updated` is rewritten. Users need the plan to react immediately, visible feedback while it does, predictable goal semantics, and a nudge when the car is not plugged in for planned charging.

## What Changes

- Goal save/clear via `POST /api/ev/chargers/{id}/schedule` triggers an immediate, fire-and-forget replan; the HTTP response is not delayed.
- HA goal changes (live `state_changed` and startup/reconnect adoption) trigger the same replan.
- Replan requests arriving while the planner is running are coalesced into exactly one follow-up run instead of being dropped ("Planner already running"). Bursts (e.g. HA editing target and ready-by separately) collapse into one run.
- `GET /api/ev/chargers` exposes `plan_pending` per charger (goal edited after the last plan, or a goal-triggered run queued/running). The EV card shows a "Re-planning…" state and hides the previous plan's progress, status and per-day numbers until the new plan lands.
- CommandBar surfaces `planner_error` (failed state plus message), not only the `failed` progress phase.
- **BREAKING (semantics)**: a ready-by set in HA always produces a one-off goal (`repeat: none` + `ready_by_date`) on both the live-change and reconnect paths. An existing repeating goal becomes one-off when its ready-by is edited in HA.
- `every_n_days` is anchored on a new stable `anchor_date` goal field, set only when the user saves the repeat configuration via the API; HA echoes, reconnect adoption and planner writebacks never move it. Legacy goals are backfilled from `last_updated` once.
- The plan shows goal charging for an unplugged charger (assumed plug-in), so the user sees what will happen once the car is connected. The executor never acts on assumed-plugged slots (no switch-on, no discharge block) until the charger is actually plugged.
- Optional per-charger "car not plugged in" notification sent a configurable lead time (e.g. 15/30 min) before the first planned charging slot while the charger is unplugged.

## Capabilities

### New Capabilities
- `planner-run-coalescing`: planner run requests are queued/coalesced instead of dropped when a run is in progress.
- `ev-plug-in-reminder`: optional notification when charging is planned soon but the charger is not plugged in.

### Modified Capabilities
- `ev-charging-replan`: goal changes (API and HA) trigger an immediate replan.
- `ev-target-charging`: read-only API adds `plan_pending`.
- `ev-dashboard-card`: card shows a re-planning state and suppresses stale plan numbers.
- `command-bar`: planner button surfaces `planner_error`.
- `ha-schedule-sync`: HA ready-by always produces a one-off goal; HA changes never move the `every_n_days` anchor.
- `per-device-ev-scheduling`: `every_n_days` anchored on `anchor_date`; unplugged chargers with an active goal get assumed-plugged decision variables.
- `ev-schedule-api`: the write endpoint persists `anchor_date` and triggers a replan.

## Impact

- Backend: `backend/api/routers/ev.py` (save/clear → trigger replan, `anchor_date`, `plan_pending`), `backend/ha_socket.py` (live-change + reconnect adoption → one-off and replan), `backend/services/planner_service.py` + `scheduler_service.py` (coalescing), `backend/core/ev_goal.py` (anchor), `backend/core/ev_state.py` (new field).
- Planner: `planner/pipeline.py` (resolve deadline for unplugged chargers with a goal, SoC source), `planner/solver/kepler.py` + `adapter.py` + `types.py` (assumed-plugged chargers get variables; no surplus terms for them).
- Executor: `executor/engine.py` (gate plan use on live plug state; plug-in reminder check).
- Frontend: `EVChargingCard.tsx`, `CommandBar.tsx`, charger settings editor (reminder lead time), `api.ts` types.
- Config: new optional per-charger `plug_in_reminder_minutes` in `config.default.yaml`.
- Sibling change `ev-planning-model` has landed (deferral tiers, no quotas). This change touches Kepler only to widen which chargers get variables and deferral tiers.
