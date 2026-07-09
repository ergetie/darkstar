## Context

Post-merge review of commits `bc66a163` (module 4) and `95353064` (module 5) confirmed 11 defect clusters. All findings were verified against the code; line references are to the current checkout. The production charger is `enabled: false`, so fixes land before first real use. Constraint: dashboard/API is the sole source of truth for EV goals (user decision, 2026-07-09); `every_n_days` must be fixed, not removed; HA-side editing stays in scope.

## Goals / Non-Goals

**Goals:**
- Correct energy accounting, multi-day quota enforcement, and day-0 pricing so goal charging behaves as specified.
- Working, non-destructive bidirectional HA sync (HA wins on reconnect).
- Single source of truth for goals: `data/ev_multi_day_state.json` via API/dashboard/HA; goal fields removed from config.
- Safe concurrent access to the state file; no cross-event-loop session sharing.
- Truthful frontend display; all confirmed frontend bugs fixed.
- Regression tests for the previously untested behaviors.

**Non-Goals:**
- Per-device delivered-energy metering (aggregate `ev_charging_kwh` remains; we gate its use instead — see Decisions).
- Redesign of keep-on-after-target energy accounting in published schedules (→ BACKLOG).
- Frontend `any`-type cleanup beyond the EV files touched (→ BACKLOG).
- AGENTS.md fixes (user handles separately).

## Decisions

1. **Requirement calc (double-count).** `required_kwh = (target−soc)/100×capacity` when a live SoC reading exists; subtract `delivered_today` **only** when SoC is unavailable (sensor missing/stale), falling back to `target/100×capacity − delivered_today`. Rationale: live SoC already embodies progress; the subtraction path exists solely for SoC-less chargers. `_ev_delivered_today_kwh` is additionally gated to single-enabled-charger configs (aggregate column can't attribute per charger); multi-charger SoC-less setups get a warning and no subtraction. Alternative (per-charger energy sensors) deferred to BACKLOG per Non-Goals.

2. **HA→Darkstar sync.** Register `ha_ready_by_entity`/`ha_target_soc_entity` as `ev_ready_by_{i}`/`ev_target_soc_{i}` in `_get_monitored_entities` (mirrors the vacation-mode pattern; handler at `ha_socket.py:559` already exists). Reconnect/startup rule inverts to **HA wins**: read both entities; adopt values that pass sanity (SoC 1–100, datetime parseable and not in the past); otherwise keep state file and push it to HA once. This also fixes the expired-one-off seeding bug: a past HA datetime is never adopted as a goal. `sync_goal_to_ha` (Darkstar→HA) remains for API/dashboard saves. Echo suppression: writes we initiate to HA are remembered (entity, value) and the resulting `state_changed` event is skipped, preventing sync loops.

3. **Multi-day quota in solver.** Replace `daily_quota_kwh: float | None` on `EVChargerInput` with `quota_by_day: dict[date, float] | None` (adapter maps from `quota_schedule`). Kepler applies `sum(ev_energy[d][t] for t in day) <= quota_by_day[day]` for every in-horizon day present in the map, and the soft requirement constraint changes from full `required_kwh` to `min(required_kwh, sum of quotas for in-horizon days ∩ pre-deadline)` so the shortfall term no longer forces out-of-horizon energy into the horizon. Single-day goals (no schedule) keep current behavior. Alternative considered (keep today-only cap, shrink required to today's quota): rejected — wastes in-horizon tomorrow-slot optimization when D+1 prices are known.

4. **Day-0 price.** `_fetch_price_floor_inputs_sync` also computes offset 0 from today's **remaining** slots (`slot_start >= now`), so `MultiDayPlanner.compute_quota` weighs today with its real price. Remaining-slots-only matters: past cheap morning slots must not inflate today's attractiveness.

5. **Goal source of truth.** Remove `target_soc_percent`, `ready_by`, `repeat`, `ready_by_date`, `n_days`, `departure_time` from config parsing (`executor/config.py`), `config.default.yaml`, and the pipeline's config-fallback reads. The pipeline uses the state file exclusively; a charger with no state-file goal has no goal (planner logs it, UI shows "no goal set"). `_persist_ev_multi_day_state` stops writing config-derived fallbacks (no more echo/shadowing) and preserves entries for chargers absent from the current run. One-time migration: on load, if config still carries goal fields, log a deprecation warning telling the user to set goals in the dashboard (values are ignored). Alternative (config as first-boot seed) rejected: it is exactly the mechanism that produced the shadowing bug, and the user confirmed config goals are unwanted.

6. **Shared resolver.** One `resolve_next_ready_by(...)` in a shared module (e.g. `backend/core/ev_goal.py`), used by planner pipeline, `ev.py`, and `ha_socket.py`. Single `n_days` default = 1; `every_n_days` anchored to the goal's `last_updated` date (deterministic, user-controllable by re-saving) instead of `date(2020,1,1)`. `n_days` added to the pipeline goal-merge and persist dict, and to the GET response. `repeat` normalization treats Python `None`/missing as `"daily"` (never string-compares to `"none"`).

7. **State-file concurrency.** All reads/writes go through `backend/core/ev_state.py`, which gains an inter-process file lock (`fcntl.flock` on a sidecar `.lock`; writers hold it across read-modify-write) and a unique temp file (`tempfile.NamedTemporaryFile(dir=...)` + `os.replace`). Planner (separate thread/loop) and API share the same module, so one lock covers all three writers. Alternative (route everything through one owner task) rejected as a larger refactor for the same guarantee.

8. **HA client session.** `backend` gets its own `HAClient` per event loop (lazy singleton keyed by running loop, closed on app shutdown) — `_get_ha_client` in `ev.py` and `ha_socket.py`'s sync path stop borrowing the executor's client; `_get_session`'s cross-loop close/rebind path is removed (assert same loop instead). Fallback-client leak fixed by reusing the loop-keyed singleton; bare `except: pass` replaced with logged warnings.

9. **Validation & staleness.** API validates `ready_by_date` with `date.fromisoformat` and rejects past dates (422). The GET-side 2-hour staleness rule is removed in favor of truthfulness: GET reports the goal as long as the planner would act on it, plus a `last_planned_at` field so the UI can show "planner hasn't run since …" instead of silently nulling the goal. (Aligning by *removing* the planner's use of stale goals was rejected: goals are durable user intent, not cache.)

10. **Surplus interactions.** `ev_surplus_kw` energy counts toward the per-day quota constraint (add surplus term to the day sum) so surplus days don't overshoot the plan; the net-excess sink cap subtracts concurrent battery charge power (`sinks <= max(0, pv − load − battery_charge)`), closing the grid-loophole the ≥95% SoC gate only bounded.

11. **Frontend.** `activeTab` falls back to `metrics` when `hasEvCharger` is false (render-time guard, not just toggle hiding); settings link becomes a React Router `<Link>`; goal view derives from `charger` props each render (no one-shot `isEditing` init) so phantom/stale goals can't render; `'throttling'` and `'stale_fallback'` both mapped to badges; all date math via local-date helpers (`toLocalISODate(d)`) instead of `toISOString()`; save flow snapshots submitted values and skips the reset effect until refetch resolves; `fetchChargers` clears `error` on success and guards out-of-order resolutions with a request counter. Cheap typing: `chargers` typed as `EVChargerState[]` from `api.ts`.

12. **Tests.** New: kepler net-excess cap (sink energy ≤ pv−load−battery, magnitude asserted); per-day quota enforcement across a 2-day horizon; requirement-calc with/without live SoC; `n_days` round-trip (API→state→planner→GET); HA-sync wiring (entity registered → handler fires → state file updated) and reconnect HA-wins rule; pipeline goal-merge test rewritten to invoke the real pipeline function. `test_pipeline_ev_state.py`'s copy-paste test deleted in favor of the real one.

## Risks / Trade-offs

- [Quota semantics change solver output for existing multi-day tests] → tests updated deliberately; assert spreading behavior (tomorrow capped), not just today.
- [HA-wins reconnect could adopt a value the user set long ago in HA] → sanity checks (future date, SoC bounds) plus echo suppression; a stale-but-future HA value is by definition the user's last expressed intent in HA.
- [Removing config goal fields breaks configs that carry them] → prod config verified clean (charger disabled, `departure_time: ""`); parser logs deprecation warning and ignores; documented in config.default.yaml comment.
- [File lock adds blocking I/O on the event loop] → lock held only around small JSON read/write; planner already does blocking sqlite here; API paths wrap in `asyncio.to_thread`.
- [Requirement no longer forces full multi-day energy in horizon → less charging if quotas are wrong] → quota schedule is recomputed every planner run from live SoC; day-0 price fix makes quotas trustworthy.

## Migration Plan

Deploy is a normal container update. No data migration: existing `data/ev_multi_day_state.json` entries remain valid (`n_days` absent → default 1 until next save). Config goal fields, if present, are ignored with a warning. Rollback = previous image; state file format is backward compatible (new keys only).

## Open Questions

None — all user decisions captured (dashboard as source of truth; `every_n_days` kept; HA sync in scope; minors folded in, rest to BACKLOG).
