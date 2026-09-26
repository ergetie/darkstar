## 1. Planner run coalescing

- [x] 1.1 Replace the "Planner already running" rejection in `planner_service.run_once` with a `rerun_requested` flag plus merged per-charger plug overrides, and run exactly one follow-up after the current run (success or failure)
- [x] 1.2 Add the goal-change debounce (~2 s internal constant); plug-event requests bypass it
- [x] 1.3 Make synchronous `POST /api/run_planner` await the coalesced follow-up instead of erroring when busy
- [x] 1.4 Expose an in-memory "goal replan queued/running" flag per charger for `plan_pending`
- [x] 1.5 Tests: request during run → one follow-up; N requests → one follow-up; follow-up after failure; override merge; debounce collapses a burst; plug events not delayed

## 2. Shared replan dispatch and goal-change triggers

- [x] 2.1 Add a shared `request_replan(reason, ev_overrides=None)` helper that picks `create_task` vs `run_coroutine_threadsafe` for the calling thread
- [x] 2.2 Migrate `ha_socket._trigger_ev_replan` and executor `_request_balancer_replan` to the helper
- [x] 2.2a Goal-triggered replans do not call the executor; test that no immediate executor run happens and the next tick applies the plan
- [x] 2.3 Trigger a goal-change replan from `POST /api/ev/chargers/{id}/schedule` (set and clear) without delaying the response
- [x] 2.4 Trigger a goal-change replan from the HA live-change handler and from reconnect adoption only when the goal actually changed (never for debounced echoes)
- [x] 2.5 Tests: API save/clear triggers once and returns fast; HA change triggers; echo does not; no-op reconnect does not

## 3. Goal semantics: HA one-off and every-N-days anchor

- [x] 3.1 HA live-change path: ready-by writes `repeat: none` + `ready_by_date` + `ready_by`; remove `setdefault("repeat","daily")`; target-SoC-only change leaves repeat untouched
- [x] 3.2 Align reconnect adoption with the same helper so both paths produce identical goals
- [x] 3.3 Add `anchor_date` to the goal: set by the API write rules (new / repeat changed / n_days changed), removed on clear or repeat change away from every_n_days, preserved by HA handlers and planner writebacks
- [x] 3.4 Update the shared resolver (`backend/core/ev_goal.py`) to anchor on `anchor_date` with a `last_updated` fallback, and persist the backfill on the next goal write
- [x] 3.5 Return `anchor_date` from `GET /api/ev/chargers`
- [x] 3.6 Tests: live vs reconnect produce the same one-off; SoC-only change keeps repeat; anchor stable across HA echoes; n_days change re-anchors; legacy backfill keeps the current cycle

## 4. Plan-pending feedback (API and frontend)

- [x] 4.1 Add `plan_pending` (last_updated > last_planned_at OR goal replan queued/running) and `assumed_plugged` to `GET /api/ev/chargers` and the save response
- [x] 4.2 Frontend types in `api.ts` for `plan_pending`, `assumed_plugged`, `anchor_date`
- [x] 4.3 `EVChargingCard.tsx`: "Re-planning…" state; hide previous-plan delivered/remaining, status badge and per-day values while pending; keep goal values; show re-plan failed on `planner_error`
- [x] 4.4 `EVChargingCard.tsx`: "Planned from HH:MM — plug in the car" when `assumed_plugged`
- [x] 4.5 `CommandBar.tsx`: handle `planner_error` (failed state + error toast); confirm server-started runs spin the button
- [x] 4.6 Frontend tests for pending, failure and assumed-plugged rendering; CommandBar planner_error

## 5. Assumed-plugged planning (on top of the landed `ev-planning-model` deferral tiers)

- [x] 5.1 Pipeline: resolve deadline and `required_kwh` for unplugged chargers with a goal using live or persisted last SoC; skip when no SoC is known; mark state `assumed_plugged`. Always on for every charger; add no config toggle
- [x] 5.2 Kepler/adapter/types: create scheduled-charging variables and deferral tiers for assumed-plugged chargers, no surplus variables; include them in the energy balance and import budget; emit `assumed_plugged` in results and schedule output
- [x] 5.3 Chart: render assumed-plugged EV slots as planned-awaiting-plug-in (visual distinction following the design system)
- [x] 5.4 Tests: unplugged with goal → planned + flagged; unplugged without SoC → not planned; unplugged without goal → no variables; plugged unchanged

## 6. Executor plug gating

- [x] 6.1 Gate planned EV kW, keep-on and surplus flags on live plug state for switch control (`_charger_should_be_on`) and source isolation; unknown counts as unplugged; manual charge and the measured-draw fail-safe unchanged
- [x] 6.2 Tests: planned slot while unplugged → no switch-on, no discharge block; plug-in mid-slot → acts next tick; unknown plug state; measured draw still blocks discharge

## 7. Plug-in reminder

- [x] 7.1 Add optional per-charger `plug_in_reminder_minutes` to the executor config parsing and `config.default.yaml` (off by default, documented)
- [x] 7.2 Executor tick: find the first upcoming planned-charging window, send one reminder when unplugged within the lead time, dedupe per charger+window start, reset on plug-in
- [x] 7.3 Settings charger editor: reminder lead time with Off / 15 / 30 / custom
- [x] 7.4 Tests: sends once in the window; not when plugged; disabled when 0/absent; new window re-notifies; settings round-trip

## 8. Verification

- [x] 8.1 Run `./scripts/lint.sh` and the full test suite; fix regressions
- [x] 8.2 Manual check on dev: save goal → planner button spins, card shows Re-planning…, new plan appears; HA ready-by edit becomes one-off and replans
- [x] 8.3 Fix: stamp `last_planned_at` with the run's wall-clock goal-read time instead of the floored slot start (card stuck on Re-planning… when a goal was saved early in a slot); regression tests for early-slot save and edit-during-run
