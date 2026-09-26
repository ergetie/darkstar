## Context

Current behaviour, from mapping the code on 2026-09-25:

- **Goal writers.**
  - `POST /api/ev/chargers/{id}/schedule` (`backend/api/routers/ev.py:110-241`) writes the state file, schedules the HA sync as a background task, and returns `get_ev_chargers()` built from the previous plan. It never calls the planner.
  - The HA live change (`backend/ha_socket.py:634-727`) updates the goal and emits `ev_schedule_changed`, but does not replan. It keeps the existing `repeat`, only updates `ready_by_date` when repeat is already `none`, and falls back to `setdefault("repeat","daily")`.
  - The HA reconnect adoption (`ha_socket.py:343-480`) always forces `repeat: none` plus a date. The same HA datetime can therefore mean a one-off or a daily goal depending on which path handled it.
- **Replan plumbing.**
  - `scheduler_service.trigger_now(...)` → `planner_service.run_once(...)`.
  - `run_once` holds a lock and returns an immediate failure, "Planner already running" (`planner_service.py:180-184`), when a run is in progress. The request is lost.
  - Plug replans dispatch cross-thread via `run_coroutine_threadsafe` (`ha_socket._trigger_ev_replan`, `:1089-1170`).
  - `trigger_now` is not gated by the Auto scheduler toggle.
- **`every_n_days`.** The shared resolver (`backend/core/ev_goal.py:32-120`) anchors the cycle on the date of `last_updated`. HA echoes and reconnect adoption rewrite `last_updated` (`ha_socket.py:442`, `:704`), which silently shifts the cycle.
- **Unplugged chargers.** The pipeline only resolves a deadline when the charger is plugged (`pipeline.py:1400-1474`). Kepler only creates variables for plugged chargers (`kepler.py:158`). So an unplugged car's goal never shows in the plan until the plug-in replan.
- **Executor.** It turns the switch on whenever the planned kW is above 0.1 (`engine.py:3434-3447`). Source isolation blocks battery discharge whenever the scheduled `ev_charging_kw` is above 0.1 (`engine.py:1759-1880`). Neither checks the plug state.
- **Frontend.**
  - The CommandBar spinner is driven by the global `planner_progress` socket event (`CommandBar.tsx:128-140, 272`), so a server-started run already spins it.
  - CommandBar does not listen to `planner_error`.
  - The EV card refetches on `ev_schedule_changed` and `schedule_updated`. It has no notion of a plan that hasn't caught up with the goal yet.
  - The backend already detects staleness (`last_updated > last_planned_at`, `ev.py:323-326`) but only uses it to drop at-risk diagnostics.

## Goals / Non-Goals

**Goals:**
- A goal change from any source produces a new plan within seconds, without delaying the write.
- No replan request is ever silently dropped. Bursts collapse into one run.
- The UI tells the truth while the plan catches up.
- HA ready-by semantics are identical on every path.
- The `every_n_days` cycle only moves when the user changes it.
- The plan shows planned goal charging even while the car is unplugged, with zero executor risk.
- An optional reminder to plug in.

**Non-Goals:**
- How goal energy is allocated across days or against forecasts. That belongs to `ev-planning-model` (landed: deferral tiers, `planned_by_day`).
- Load-balancer notifications (sibling `load-balancer-graceful-degradation`).
- Replanning on manual charge start/stop.
- Changing the scheduler cadence.

## Decisions

### D1. Fire-and-forget goal replan through one helper
Add one backend helper, `request_replan(reason, *, ev_overrides=None)`. It schedules `scheduler_service.trigger_now(...)` on the main event loop:
- `asyncio.create_task` when called from the main loop, which is the API case;
- `run_coroutine_threadsafe` when called from the HA websocket thread.

Callers:
- the API save/clear, after the state-file write and before building the response;
- the HA live change and the reconnect adoption, only when the goal actually changed. Echo writes are already ignored within the 5 s debounce.

The existing `_trigger_ev_replan` for plug events migrates to the same helper, so there is one dispatch path.
- **Rejected:** awaiting `/api/run_planner` synchronously. It blocks the save for the whole solve.
- **Executor timing (decided by the user on 2026-09-25):** a goal-triggered replan does NOT run the executor immediately. Unlike the CommandBar button (which calls `Api.executor.run()` after planning), the executor picks up the new plan on its next regular tick.

### D2. Coalescing inside `planner_service`
`run_once` no longer fails when busy.
- If a run is in progress, the request sets `rerun_requested` and merges its EV plug overrides into a pending-overrides map (latest value per charger wins). It then returns a "queued" result.
- When the current run finishes, successfully or not, and `rerun_requested` is set, the service runs exactly once more with the merged overrides.
- Goal-change requests also pass through a short debounce (about 2 s, internal constant), so HA editing target and ready-by as two events yields one run.
- Plug events skip the debounce. They already carry a correctness-critical override.
- Placement: coalescing lives in `planner_service.run_once`; the goal-change debounce lives in `scheduler_service.request_goal_replan`, reached through the shared `request_replan` helper (`backend/services/scheduler_service.py`).

The manual CommandBar run, through synchronous `/api/run_planner`, keeps its response contract. If a run is in progress, it awaits the coalesced follow-up instead of erroring.

- **Rejected:** a general job queue. We only ever need "the latest state, planned once more".

### D3. `plan_pending` is derived server-side
`GET /api/ev/chargers` adds `plan_pending: bool` per charger. It is true when either:
- the goal's `last_updated` is later than `last_planned_at`; or
- a goal-triggered run is queued or running. The service exposes this as an in-memory flag.

`last_planned_at` is the wall-clock instant the run read the goal state (not the floored 15-minute slot start used as the plan's `now`, and not `now_override`), because `last_updated` is also wall-clock. A goal saved early in a slot is therefore covered by a run that read it, and an edit made while a run is in progress stays pending for the coalesced follow-up run. The at-risk diagnostics staleness check uses the same comparison.

The flag clears when a run completes and `schedule_updated` is emitted, or on `planner_error`. After a failed goal-triggered run the service remembers the failure time per charger, so the `last_updated > last_planned_at` rule stops reporting that edit as pending until the goal is edited again. `GET /api/ev/chargers` also returns `planned_start` (first upcoming planned slot) so the card can show "Planned from HH:MM".

While `plan_pending` is true, the card:
- shows "Re-planning…";
- keeps the submitted goal values (existing no-revert rule);
- hides delivered/remaining, status and `planned_by_day` chips from the previous plan.

On `planner_error`, the card shows "Re-plan failed — showing last plan" and restores the numbers, marked as stale.

- **Rejected:** a pure frontend timer. It lies when HA changed the goal, or when another tab did.

### D4. CommandBar listens to `planner_error`
CommandBar handles `planner_error` like the `failed` phase: failed state, cleared after 3 s, plus an error toast with the message. Server-started runs keep spinning the button through `planner_progress`, as today.

### D5. HA ready-by is always one-off
On both HA paths, an HA ready-by datetime writes `ready_by` = HH:MM, `ready_by_date` = its date, and `repeat: none`. The `setdefault("repeat","daily")` is removed.

A target-SoC-only change from HA never touches `repeat`. The rationale: a user who drives the goal from HA owns the schedule through their own automation. Recurrence lives in HA, not in the Darkstar goal.

### D6. Stable `anchor_date` for `every_n_days`
New goal field `anchor_date` (ISO date). It is set only by the API write when `repeat` is `every_n_days` and either the repeat mode or `n_days` changed, or no anchor exists yet. The value is the local date of that save.
- HA handlers and planner writebacks preserve it and never write it.
- The resolver uses `anchor_date`, falling back to the local date of `last_updated` for legacy goals.
- The first API or planner write that sees a legacy goal persists the backfilled value. That locks the cycle as it currently resolves, so nothing moves on upgrade.

### D7. Assumed-plugged planning for unplugged chargers
Always on for every charger, with no per-charger or global toggle (decided by the user on 2026-09-25). For an enabled charger that is unplugged but has an active goal:
1. **Pipeline.** Resolve the deadline as if plugged. Compute `required_kwh` from the last known SoC: the live reading if HA still reports it, else the persisted `current_soc_percent`. If there is none, the charger is not planned (no fabricated SoC). Mark the state `assumed_plugged: true`.
2. **Kepler.** Create scheduled-charging variables and the goal requirement (in-horizon energy + deferral tiers from `planner/strategy/ev_deferral.py` + shortfall) for it, exactly as for a plugged charger. It gets no surplus-charging variables: surplus is opportunistic and needs a real plug. Its planned energy does count in the energy balance and the import budget, so the plan is honest about cost.
3. **Output.** The per-charger results carry `assumed_plugged: true`. The chart and card render those slots as "planned — awaiting plug-in".
4. **Executor.** Planned EV kW, keep-on and surplus flags for a charger count only when the executor's live plug state for it is connected. They then drive neither the switch nor source isolation. An unknown plug state is treated as unplugged for this gate. The existing fail-safe on measured EV draw still blocks discharge if power actually flows.
5. **Plug-in.** The existing plug-in replan then replans with real state.

- **Rejected:** showing the plan only in the UI (a frontend projection). It would diverge from what the solver and cost model assume.

### D8. Plug-in reminder evaluated in the executor
New optional per-charger config `plug_in_reminder_minutes` (int, 0 or null = off; the UI offers 15 and 30 plus custom).

On each tick the executor finds the charger's first upcoming slot with planned EV kW above 0.1. If the charger is not plugged in and `now >= slot_start - lead`, it sends one notification through the existing executor notification path (`executor/actions.py:452`), for example: "Go-e: charging planned at 22:00 but the car isn't plugged in".

Dedupe key: charger id plus that charging window's start. Plugging in resets it.

The executor is chosen because it already owns the live plug state, the current schedule and notifications.

## Risks / Trade-offs

- **[Replan storm from rapid edits or a flapping HA entity]** → the D2 debounce plus coalescing bounds it to one extra run per burst.
- **[Assumed-plugged energy displaces battery or other plans that then don't happen]** → accepted. It reflects the user's stated intent. The plug-in and unplug replans correct it. If it proves noisy, a follow-up can let the user pick.
- **[Stale SoC for an unplugged car]** → we use the last known value. Once the car is plugged, real SoC takes over. Sibling `ev-cost-accuracy-cleanup` defines the stale-SoC timeout for plugged chargers. Assumed-plugged planning is display and planning only, so the executor risk is zero.
- **[BREAKING semantics: a repeating goal converts to one-off on an HA ready-by edit]** → explicitly desired. Documented in the release notes by the user.
- **[Executor gating regresses keep-on or manual charge]** → manual charge is excluded from the gate: it already checks the plug itself. Tests cover keep-on while plugged.

## Migration Plan

- The state-file field `anchor_date` is additive and backfilled lazily (D6). There is no DB change.
- The config key `plug_in_reminder_minutes` is optional, defaults to off, and goes in `config.default.yaml`.
- Rollback: revert the code. Unknown state-file fields are ignored by older code.
- Ordering: `ev-planning-model` landed first (36f36a67); D7 is built on its deferral-tier model (no quotas).

## Open Questions

None. Resolved on 2026-09-25: assumed-plugged planning is always on (no toggle); a goal-triggered replan leaves the executor to pick up the plan on its next tick.
