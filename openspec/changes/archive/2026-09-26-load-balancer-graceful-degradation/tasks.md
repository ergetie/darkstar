## 1. Config and validation

- [x] 1.1 Add `target_margin_percent`, `pause_debounce_s`, `severe_overload_percent`, `ramp_up_window_s` to `LoadBalancingConfig` (`executor/config.py`) with defaults and range validation; add `phase_1_line` to the EV charger config.
- [x] 1.2 Migrate a user-set `resume_margin_percent` to `target_margin_percent` on config load (idempotent, logged); drop the old key.
- [x] 1.3 Backend validation in `backend/api/routers/config.py`: range errors naming the key; `phase_1_line` must be in the charger's `phases`.
- [x] 1.4 Document the new keys with comments in `config.default.yaml`.
- [x] 1.5 Tests: defaults, migration, range rejection, `phase_1_line` validation.

## 2. Averaged sensing

- [x] 2.1 Add a per-phase rolling sample buffer, pruned to `ramp_up_window_s`, fed from the per-tick phase reads; reset on a stale-sensor episode.
- [x] 2.2 Expose momentary and averaged per-phase current to the balancer; block increases until a phase has a full window of fresh samples.
- [x] 2.3 Tests: a spike only moves the average proportionally; increases are blocked after startup or staleness until the window fills.

## 3. Balancer margin, debounce and severe pause

- [x] 3.1 Gate increases, resume and restore on projected averaged current ≤ `target_margin_percent` of the fuse (replacing the `resume_margin_percent` check); keep decreases momentary against the fuse.
- [x] 3.2 Add a per-charger `overload_since` timer: hold at `min_current_a` during the debounce; pause after `pause_debounce_s`; pause immediately above `severe_overload_percent`; reset on non-negative headroom.
- [x] 3.3 Tests for each spec scenario: quiet night ramp, ramp stops at target, 1 s spike no pause, severe immediate pause, momentary decrease, anti-flap resume.

## 4. 1-phase relief

- [x] 4.1 Balancer output gains `relief_1p_requested` when the charger is at floor in 3-phase, the overloaded phases exclude `phase_1_line`, and phase switching is enabled and not failed; hold instead of pausing while relief is pending.
- [x] 4.2 Extend `PhaseModeController.decide` (`executor/ev_surplus.py`) with a relief demand that bypasses hysteresis but respects dwell and failed state; track `relief_hold`; return to 3-phase only on dwell plus the balancer's averaged "3-phase fits" signal.
- [x] 4.3 Reorder the engine tick (`executor/engine.py` ~2883 and the balancer call site): balancer, then phase decision, then setpoint write; recompute amps with 1-phase attribution on a switch tick.
- [x] 4.4 Attribute a 1-phase charger's draw to `phase_1_line` only (unless measured per-phase draw overrides it).
- [x] 4.5 Tests: L3 overload moves the car to L1; overload on the 1-phase line pauses; dwell blocks the switch; relief-held 1-phase does not bounce back on target power alone; return to 3-phase after the load ends; a charger without phase switching is unchanged.

## 5. Notifications

- [x] 5.1 Gate pause notifications on goal-at-risk (`ev_goal_diagnostics` shortfall/at-risk, or a goal-scheduled slot within 2 h of the deadline); stale diagnostics count as at risk.
- [x] 5.2 Keep shed and stale-sensor notifications unchanged; relief switches never notify.
- [x] 5.3 Tests: a pause without risk sends nothing but is in the execution log; an at-risk pause pushes once.

## 6. Settings UI

- [x] 6.1 Add the four global fields with plain-language help to the load-balancing section (`frontend/src/pages/settings/types.ts`).
- [x] 6.2 Add a user-editable `phase_1_line` selector (L1/L2/L3, default L1, limited to the charger's `phases`) to the EV charger phase-switching block, shown only when phase switching is enabled (`EntityArrayEditor.tsx`), with help text explaining it is the grid phase the charger uses in 1-phase mode.
- [x] 6.3 Filter the phase-mode `EntitySelect` to `select` / `input_select`; show an inline error for a saved entity of another domain; keep the options dropdown.
- [x] 6.4 Show the 1-phase relief state in the Load Balancer tab live status (e.g. "1-phase on L1 — relieving L3").
- [x] 6.5 Frontend tests or type checks; run `./scripts/lint.sh`.

## 7. Verification

- [x] 7.1 Replay the prod 2026-09-25 afternoon phase-power history through the balancer in a test fixture: no pause for spikes shorter than 5 s; a 1-phase relief is issued for the sustained L3 overload.
- [x] 7.2 Run the full test suite and `openspec validate load-balancer-graceful-degradation`.

## 8. User-approved follow-ups (2026-09-26)

- [x] 8.1 Record the approved decisions in design.md (85 % margin migration, severe check on live phase current, averaged house load + live charger draw, post-switch dual-phase accounting and 6 A restart, relief only at the would-pause moment) and the user-verified go-e 1-phase line (L1, default unchanged).
- [x] 8.2 Goal Planning info box: optional `infoBox` on settings sections, rendered as a design-system `banner banner-info` under the section title in the EV tab; plain-language text on charge-now vs wait, risk margin and ramp, shortfall penalty; test.
- [x] 8.3 Plug-in reminder becomes global: `executor.notifications.on_ev_plug_in_reminder` (default off) and `ev_plug_in_reminder_minutes` (default 30, 1-1440) in executor config, `config.default.yaml`, the notifications API, save validation, UI → Notifications (toggle + 15/30/custom lead time) and the Executor page toggle list; remove per-charger `plug_in_reminder_minutes` from the charger editor, executor config and `config.default.yaml`.
- [x] 8.4 Idempotent startup migration (`_migrate_plug_in_reminder_to_global`, backup before write): any charger > 0 enables the toggle with the max value as lead time; per-charger keys removed.
- [x] 8.5 Executor reminder logic uses the global toggle and lead time for every charger; tests for engine, config parsing, migration (incl. end-to-end with template merge and backup) and validation.
- [x] 8.6 Rewrite the EV Charging settings guide into a complete, code-verified plain-language guide; mention the EV notifications in the Notifications guide; guide tests.
- [x] 8.7 Delta specs: MODIFY `ev-plug-in-reminder` and `ev-deferral-value`, ADD to `settings-search`; `openspec validate --strict`; full lint, pytest and frontend tests.
- [x] 8.8 Goal Planning info box collapsed by default: optional `tldr` on `infoBox`; `SectionInfoBox` shows the title and one-line summary with an accessible expand/collapse button (`aria-expanded`, `aria-controls`); tests for collapsed-by-default and expand/collapse.
- [x] 8.9 Verify follow-ups: EV card keep-on toggle works at any target (was forced off below 100 %, contrary to `ev-target-charging`); guide wording matches; EV card "Excess PV priority" hint deep-links to the Advanced tab field (`?tab=advanced&field=executor.excess_pv.priority`, which opens Advanced mode); balancer increases are also capped by momentary headroom against `main_fuse_a`, shed-relief holds never go below `min_current_a`, and a sub-floor setpoint pauses instead of being raised to the floor during an overload; tests.
- [x] 8.10 Severe overload takes precedence over the shed-relief hold (D16): above `severe_overload_percent` the charger pauses immediately (and a not-yet-started charger records a pause) even when a higher-listed shed entry gave way this tick; below it the hold is unchanged; delta spec MODIFIES "EV charger is throttled first using per-phase feedback"; tests for severe pause during hold, non-severe hold, and resume after the pause.
- [x] 8.11 Quick re-fit while paused (D17): new `load_balancing.resume_confirm_s` (default 10 s, 5–300) in executor config, save validation, `config.default.yaml`, settings UI and guides; a paused charger re-fits once its current mode (or, if dwell allows, 1-phase on `phase_1_line`) has fitted `min_current_a` within the target margin on the momentary reading for the confirm window, at the largest fitting amps capped by the plan; a refused/failed 1-phase switch keeps it paused; anti-flap back-off 10 s → 30 s → 120 s, reset after 10 min; `resume_delay_s` kept for shed restore, stale escalation and surplus resume (no migration); delta specs; tests incl. prod-fixture replay.
