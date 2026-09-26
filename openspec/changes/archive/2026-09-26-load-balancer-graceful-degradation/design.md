## Context

`executor/load_balancer.py` computes per-phase headroom as `main_fuse_a − |phase current|` from the momentary per-phase grid reading each tick. `executor/engine.py` reads that value about every 5 s (prod `executor.interval_seconds`; prod grid sensors report roughly every 5 s). For a `type: current` charger the balancer has two moves:
- lower the setpoint by the deficit;
- pause, once the needed setpoint falls below `min_current_a`.

Increases are gated on `resume_margin_percent` (90 %), checked against the momentary reading. Pause and resume use `resume_delay_s` (120 s) (replaced for balancer-paused chargers by the quick re-fit, D17).

Phase switching lives in `PhaseModeController` (`executor/ev_surplus.py`) and is driven from `_update_ev_surplus_and_phase_mode` (`engine.py` ~2883). Its only input is a target power, taken from manual, surplus, keep-on or plan kW. The balancer never influences it.

Rebase notes (after `ev-planning-model`, `ev-goal-lifecycle-feedback` and `ev-cost-accuracy-cleanup` landed):
- Grid voltage is the global `system.grid.nominal_voltage_v` (default 230 V, `backend/core/ev_power.py`); `ev_surplus.py` thresholds take `voltage_v`. This change adds no voltage settings.
- The executor gates planned charging on the live plug state every tick (`_gate_ev_plan_on_plug_state`), so an unplugged charger reaches the balancer with no planner target and never triggers relief or pause notifications.
- A balancer pause stops charging through the switch entity per `ev-current-control` "Minimum current floor with pause semantics"; the debounce hold writes `min_current_a`, never less.
- Balancer-triggered replans already go through the shared `scheduler_service.request_replan`.
- While the EV SoC is stale, goal charging is suspended and has its own notification (`on_ev_soc_stale`); the planner emits no diagnostics for that charger, which D7 treats as "not at risk" to avoid duplicate alerts.

The prod incident on 2026-09-25 had a 16 A fuse, a 12 A charger and a 23.5 A spike on L3. It produced four pauses and four push notifications in one afternoon, each correct by the current rules.

## Goals / Non-Goals

**Goals:**
- Keep charging through short spikes and through single-phase overloads, without ever exceeding the fuse for longer than today.
- Leave headroom by default (85 %) so ordinary house loads do not immediately trigger interventions.
- Stay quiet unless the user's goal is actually threatened.
- Make it impossible to configure a read-only phase-mode entity.

**Non-Goals:**
- Tolerating overload based on fuse trip curves. The fuse type is unknown, so we never deliberately run over `main_fuse_a` beyond the debounce.
- Charging below 6 A (IEC 61851 minimum).
- Changes to planner EV logic or kW derivation (handled by the `ev-planning-model` change).
- Load balancing for binary chargers beyond today's shed behavior.

## Decisions

**D1: Two sensing paths, one momentary and one averaged.**
- The balancer keeps a per-phase ring buffer of (timestamp, amps) samples, pruned to `ramp_up_window_s`.
- The momentary path drives decreases, the debounce timer and the severe check.
- The averaged path drives increases, resume, restore and the return to 3-phase.
- *Alternative:* a user toggle between momentary and average per action. Rejected: every combination except this one is unsafe or flappy, so a toggle only adds ways to misconfigure.
- *Alternative:* an EMA instead of a window. Rejected: a window is easier to explain in the UI ("average over 60 s") and to test deterministically.

**D2: The margin gates increases only.**
- A fresh start of a charger that was not paused keeps the existing momentary floor check; the target gate applies to raising setpoints, resume, restore and the return to 3-phase. When a charger's phase set grows (e.g. back to 3-phase), it restarts at `min_current_a` and ramps through the averaged gate.
- The severe check uses the momentary reading of each phase the charger draws on, including the charger's own current, exactly as specified; it is not netted against the pending reduction to the floor.
- `target_margin_percent` replaces `resume_margin_percent` as the ceiling for projected averaged current on any increase.
- It never triggers a reduction by itself. Reducing whenever a phase sits between 85 % and 100 % would make the balancer chase normal house noise and throttle constantly.
- The legacy key is migrated by value, so a user who set 80 keeps 80. The old default (90) was written into every config by the template merge, so it is indistinguishable from an untouched setting; it is dropped and the new 85 % default applies (more protective, never less).
- The EV surplus controller's resume threshold also read `resume_margin_percent`; it now reads `target_margin_percent` (one knob). With defaults that moves the surplus resume threshold from 1.9× to 1.85× the 1-phase floor power, which has no fuse-safety impact.
- The averaged path averages the rest of the house (grid minus the balancer's own chargers' draw) over the window and adds the chargers at their current draw. Averaging the raw grid reading would hide the chargers' own ramp behind the window's lag and let a 1 A/tick ramp overshoot the target by several amps (seen when replaying the prod fixture).
- "Sustained for the full `ramp_up_window_s`" is implemented as: the phase's buffer spans the full window of fresh samples and the window average satisfies the target.

**D3: Pause debounce and severe override.**
- A per-charger `overload_since` timestamp is set on the first tick where the charger is at floor and its binding phase is negative. It is cleared on any non-negative tick.
- The charger pauses when `now − overload_since ≥ pause_debounce_s`, or immediately when a phase exceeds `severe_overload_percent`.
- During the debounce the charger is held at `min_current_a`, which is already the lowest it can go.
- The 125 % default is the "don't gamble" bound: large overloads are cut at once.

**D4: The balancer drives phase relief through the existing controller.**
- The balancer's per-charger output gains a `relief_1p_requested` flag. The engine passes it into `PhaseModeController.decide(...)` as a new argument.
- The controller treats the flag as an immediate 1-phase demand, still subject to dwell and failed state, and records `relief_hold=True`.
- While `relief_hold` is set, the return to 3-phase requires the balancer's averaged "3-phase fits" signal in addition to dwell.
- One controller keeps a single owner of the contactor and its dwell. That avoids two code paths racing to write `select.*_psm`.
- *Alternative:* the balancer writes the phase entity directly. Rejected: it would duplicate idempotence, verification and fail-safe handling.

**D5: Ordering within the tick.** The phase decision currently runs before the balancer. Order:
1. Balancer computes outputs, including the relief flag, from this tick's readings.
2. The phase decision consumes that flag.
3. The setpoint is written.

The relief switch therefore takes effect this tick. On a switch tick the balancer's amps are recomputed with the 1-phase attribution (`phase_1_line`) before the write.

Implementation: the existing target-power phase decision keeps running before the balancer (the surplus controller depends on it), but it is told whether 3-phase fits so a relief-held charger does not bounce back. A dedicated relief step runs after the balancer and before the setpoint write. Relief is only requested at `min_current_a` and the charger already draws that on `phase_1_line`, so the 1-phase setpoint on the switch tick is `min_current_a` and L1's load is unchanged; no second balancer pass is needed. The engine tells the balancer per charger whether relief is available this tick (switching enabled, entity configured, controller not failed, dwell elapsed, currently 3-phase). Relief is requested where the pause would otherwise happen (after `pause_debounce_s`), so spikes shorter than the debounce never switch phases.

**D6: `phase_1_line` is user-configurable, default L1.** The Go-e and most chargers use L1 in 1-phase mode (the user verified on 2026-09-26 that the prod go-e uses L1 in 1-phase mode, so the default stays L1), but wiring varies, so the user sets the line per charger in the EV charger editor. The balancer attributes the charger's draw only to `phase_1_line` while commanded 1-phase. Where measured per-phase draw exists (`ev-measured-draw`), it overrides the attribution, as the existing spec already requires.

**D7: Goal-at-risk notifications.**
- The executor already loads schedule.json. It reads `meta.ev_goal_diagnostics` for the charger and the slot's planned goal kW.
- A pause counts as at risk if diagnostics show a shortfall or at-risk status, or if the pause falls in a goal-scheduled slot within 2 h of the deadline.
- Diagnostics count as stale (fail open, at risk) when the goal was edited after the last plan (`last_updated > last_planned_at`) or their deadline differs from the goal's. A charger with an active goal but no diagnostics entry in a plan newer than the goal was deliberately skipped by the planner (e.g. stale SoC, which has its own notification) and is not at risk.
- Every other pause is recorded in the execution log only and never notifies. There is no daily summary (dropped by the user on 2026-09-25).
- The "within 2 h" constant is internal; it can be revisited if noisy.

**D8: Picker filtering in the frontend only.** `EntitySelect` for `phase_mode_entity` gets a domain filter of `['select', 'input_select']`. The backend validation that already rejects other domains (`backend/api/routers/config.py` ~767) stays unchanged as the backstop.

**D9: Decisions approved by the user (2026-09-26).** The following agent decisions above are approved and final:
- Margin migration: a tuned `resume_margin_percent` moves to `target_margin_percent`; the untouched old default (90) is dropped so the new 85 % default applies (D2).
- The severe-overload check uses the live (momentary) phase current including the charger's own draw, not netted against the pending reduction (D2).
- The averaged ramp gate averages the rest of the house over the window and adds the balancer's chargers at their live draw (D2).
- For 60 s after a commanded phase switch (`PHASE_SWITCH_SETTLE_S`) the charger's draw is attributed to the union of its measured and commanded phases (the protective choice while the measurement may still show the old mode), and a charger whose phase set grows restarts at 6 A (`min_current_a`) and ramps through the averaged gate (D2).
- 1-phase relief is requested only at the moment the charger would otherwise pause (after `pause_debounce_s`), never for shorter spikes (D5).

**D10: Goal Planning info box.** `SettingsSection` gains an optional `infoBox` (title + paragraphs), rendered in the EV tab directly under the section title as the design-system `banner banner-info` (column layout). Only "Goal Planning" uses it. The text explains, without jargon, that published prices are optimised directly, later hours are priced at the published or forecast price plus the risk margin, how the margin ramps toward the deadline, and what the shortfall penalty means. *Alternative:* reuse the `info` field type. Rejected: its renderer is hard-coded to an unrelated "Willingness to Pay" text and it would render inside the field grid rather than under the title.

**D11: Plug-in reminder is a global notification setting.** The reminder moves from per-charger `plug_in_reminder_minutes` to `executor.notifications.on_ev_plug_in_reminder` (default off) plus `executor.notifications.ev_plug_in_reminder_minutes` (default 30, 1-1440). It sits with the other notification toggles in UI → Notifications, the Executor page's toggle list and the notifications API. The lead-time control is a number field with quick choices (15, 30) and "Custom…", implemented as an optional `presets` on number fields so parsing and validation stay those of a number field. Invalid values fall back to the default in the executor and are rejected on save. The dedupe (per charger and window, reset on plug-in) is unchanged. This modifies the `ev-plug-in-reminder` capability owned by `ev-goal-lifecycle-feedback`.

**D12: Reminder migration.** `_migrate_plug_in_reminder_to_global` runs with the other pre-merge migrations, so the startup write goes through `_write_config` (timestamped backup first). If any charger had a value > 0, the toggle is enabled with the largest value as the lead time (the most cautious reminder any charger had); zero/invalid values are dropped. The per-charger keys are always removed, and a config without them is untouched (idempotent). Running before the template merge means the merge only fills keys the migration did not set.

**D13: EV guide.** The EV Charging guide in settings search is rewritten as a numbered, plain-text guide (the viewer renders plain text with line breaks) covering setup, goals, planning, solar surplus, replanning, stale SoC, EV cost, load balancing and phase switching. Every statement was checked against the code. Two points differ from a naive summary and are written as the code behaves: the home battery takes surplus before any sink, and the EV is first among sinks only if the user puts it first in the Excess PV priority list; the "Re-planning" badge appears for goal changes only, not for plug-in, unplug or SoC recovery replans.

**D14: Collapsible info box.** `infoBox` gains an optional `tldr`. When set, `SectionInfoBox` renders the title plus the one-line summary as a disclosure button (`aria-expanded`/`aria-controls`, chevron as in the other settings editors) and the paragraphs start collapsed; without a `tldr` the box renders in full as before. Goal Planning uses the summary "Charges in the cheapest known hours; beyond published prices it only waits if forecast + safety margin is cheaper." (user request 2026-09-26: the full box was too large).
**D15: Increases also respect momentary headroom.** An increase must pass the averaged target gate and fit this tick's momentary headroom against `main_fuse_a` (the step is capped to the whole amps of momentary headroom), so a raise can never itself push a phase over the fuse. This does not make a spike reduce anything; it only stops a raise into it.
**D16: Severe overload outranks the shed-relief hold.** When a higher-listed shed entry gives way this tick on a phase a charger draws on, the charger normally holds its setpoint (never below `min_current_a`) because the shed's relief is not yet measured. That hold now applies only while every binding phase reads at or below `severe_overload_percent` of `main_fuse_a` (same live-current check and strict "above" comparison as the existing severe pause). Above it, a charging charger pauses in the same tick, and a charger waiting to start records a pause instead of the unclocked "waiting for shed relief" state. Recovery follows the normal pause recovery (since D17: the quick re-fit). Without a hold, the normal reduce/debounce/severe ladder is untouched. *Alternative:* keep the one-tick hold at any level. Rejected (user decision 2026-09-26): a fuse at > 125 % should not carry the charger's load for another tick on the assumption that an unmeasured shed will be enough.
**D17: Quick re-fit while paused ("fit what's possible within the fuse, aiming at the planned power").** User-approved 2026-09-26. The overload side (immediate cut, debounce → 1-phase relief or pause, severe > 125 % pauses at once, D16 precedence) is unchanged. Recovery from a balancer pause no longer waits `resume_delay_s` (120 s) plus the averaged gate:
- Every tick while paused, the balancer checks on the *momentary* reading whether a mode fits: every phase it would draw on has room for `min_current_a` within `target_margin_percent` of `main_fuse_a` (headroom from the running pool, so entries above it this tick are accounted for). It tracks two timers: the current mode (the charger's binding phases) and the 1-phase alternative (`phase_1_line` only), the latter only while `relief_available` (switching enabled, entity configured, controller not failed, currently 3-phase, `phase_switch_min_dwell_s` elapsed). Any stale binding phase clears both timers.
- Once a timer has run for the confirm window (`load_balancing.resume_confirm_s`, default 10 s, 5–300 s), the charger re-fits: (a) current mode if it fits, else (b) 1-phase via `relief_1p_requested` + `refit_from_pause`, else (c) stay paused. Reverse-order restore (`resume_blocked`) still applies.
- Resume amps = the largest whole amps that fit within the target margin on the chosen phases, clamped to `[min_current_a, min(max_current_a, planner target)]`; then the normal averaged ramp (D1/D2/D15). For a 1-phase re-fit the cap is the planner amps as given this tick (derived for the 3-phase count, so conservative); from the next tick the engine derives the 1-phase planner amps and the averaged ramp continues toward the planned power. The 1-phase → 3-phase return is unchanged (averaged gate + dwell, D4).
- Because a 1-phase re-fit is only safe once the switch is applied, the engine's relief step replaces the output with a pause and calls `LoadBalancer.abort_refit` (pause clock and confirm window restart, no back-off step) when the switch is refused, fails, or writes are skipped (manual override). The pool accounting for a 1-phase re-fit reserves the amps on all three binding phases for that tick (conservative).
- Anti-flap back-off, internal constants in `executor/load_balancer.py`: a pause within `REFIT_FLAP_WINDOW_S` (600 s) of the last re-fit raises the back-off step; the confirm window is `max(resume_confirm_s, REFIT_BACKOFF_STEPS_S[step])` with steps (0, 30, 120) s → 10 s → 30 s → 120 s by default, capped at the last step. A pause more than 600 s after the last re-fit resets to step 0. Stale-sensor pauses and "insufficient headroom to start" pauses do not count as flaps. Only one new setting (the confirm window); the steps and reset period are constants, following the user's preference for few settings, and there is one dwell setting only (`phase_switch_min_dwell_s`, default 600 s, matching go-e `mptwt` = 600000 ms, user-verified).
- `resume_delay_s` is kept, not removed: it still governs shed-load restore, the stale-sensor escalation from floor fallback to pause, and the EV surplus controller's resume. Only its role for balancer-paused chargers is replaced. Its help text and `config.default.yaml` comment say so. No migration is needed: `resume_confirm_s` arrives through the template merge with its default, and old code ignores it on rollback.
- *Alternative:* keep the averaged gate for resume. Rejected: the 60 s average kept a charger paused for minutes after a short spike, which is the behaviour the user wants gone; the momentary check within the 85 % target plus the confirm window and back-off bounds flapping, and the ramp after resume still uses the average.
- *Alternative:* remove `resume_delay_s`. Rejected: it still has three live consumers.

## Risks / Trade-offs

- [5 s at up to 125 % of fuse could stress a fast-acting fuse] → Configurable 0–60 s. Setting 0 restores immediate pausing. The UI help text mentions fast-acting fuses. The overload is bounded by the severe threshold.
- [The averaged window delays recovery by up to 60 s after a load ends] → Acceptable: it trades a little charging time for no flapping. Configurable.
- [A 1-phase switch interrupts the charging session briefly, and some cars dislike phase changes] → Relief is used only when the only alternative is pausing, and dwell caps it at one switch per 10 min.
- [Wrong `phase_1_line` makes the balancer "relieve" the wrong phase] → The momentary path still sees the real overload on the next tick and falls through to pause. Measured per-phase draw corrects the attribution when available.
- [A quick re-fit resumes into a load that returns seconds later] → The confirm window requires 10 s of fitting readings, the resume current leaves the 15 % target margin, and repeated pauses within 10 min lengthen the window to 30 s and 120 s.
- [Diagnostics are stale after a goal edit] → Stale diagnostics fail open: the pause counts as at risk and notifies, and the notification is not suppressed.

## Migration Plan

- Config loader migrates a tuned `resume_margin_percent` → `target_margin_percent` (the old default 90 is dropped), adds defaults for the new keys, and adds `phase_1_line: 1` implicitly.
- The config loader moves per-charger `plug_in_reminder_minutes` to the global notification setting (D12).
- `load_balancing.resume_confirm_s` (D17) is added by the template merge with its default; `resume_delay_s` is kept with a narrower role. No migration.
- No DB changes.
- Rollback: the old code ignores the unknown keys; only the migrated `resume_margin_percent` would fall back to its default of 90.

## Open Questions

None. Resolved on 2026-09-25: no daily pause summary (pause notifications only when the goal is at risk); `phase_1_line` is user-configurable with default L1; the 1-phase relief state is shown in the Load Balancer tab's live status.
