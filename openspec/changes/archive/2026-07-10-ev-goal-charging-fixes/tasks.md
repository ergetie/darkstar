## 1. Shared goal foundations (do first — later groups depend on these)

- [x] 1.1 Create `backend/core/ev_goal.py` with a single `resolve_next_ready_by(goal: dict, now: datetime, tz) -> datetime | None`. Rules: `repeat` missing/None → treat as `"daily"` (never compare `str(None)`); `every_n_days` uses `n_days` from the goal (default 1) anchored to the goal's `last_updated` date — no `date(2020, 1, 1)` anchor; `repeat: "none"` with a past `ready_by_date` returns None (inert). Done when: unit tests cover daily/weekdays/weekends/every_n_days/none, past one-off, and null repeat.
- [x] 1.2 Replace `_resolve_ready_by` in `planner/pipeline.py` with calls to the shared resolver (delete the local copy). Done when: pipeline tests pass with identical deadlines for daily/none modes.
- [x] 1.3 Replace `resolve_next_ready_by` in `backend/api/routers/ev.py` with the shared resolver; `backend/ha_socket.py` uses it too (delete both local copies). Done when: no duplicate resolver code remains (`grep resolve.*ready_by` finds only the shared module and its callers).
- [x] 1.4 Add locking to `backend/core/ev_state.py`: an inter-process lock (`fcntl.flock` on `data/ev_multi_day_state.json.lock`) held across read-modify-write; write via `tempfile.NamedTemporaryFile(dir=...)` + `os.replace` (unique temp per writer — remove the shared `.with_suffix(".tmp")` path). Expose `update_ev_state(mutator_fn)` that does locked read→mutate→write. Done when: a test with two concurrent writers shows no lost update and valid JSON.
- [x] 1.5 Route all three writers through `update_ev_state`: `set_ev_charger_schedule` (`backend/api/routers/ev.py`), the HA handlers + startup sync (`backend/ha_socket.py`), and `_persist_ev_multi_day_state` (`planner/pipeline.py`). Done when: no caller does bare `read_ev_state()` → `write_ev_state()` outside the helper.

## 2. Goals live only in the state file (BREAKING config change)

- [x] 2.1 Remove goal fields from `config.default.yaml` EV charger entries: `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, `keep_on_after_target`, `departure_time`. Add a comment that goals are set in the dashboard (stored in `data/ev_multi_day_state.json`). Keep hardware fields and `ha_ready_by_entity`/`ha_target_soc_entity`.
- [x] 2.2 In `executor/config.py`: stop parsing the goal fields (and the `penalty_levels` → target migration). If any goal field, `departure_time`, or `penalty_levels` is present in a charger entry, log ONE deprecation warning naming the dashboard, and ignore the values. Malformed values (e.g. `target_soc_percent: "80%"`) must not raise. Done when: a config carrying all legacy fields loads cleanly with warnings.
- [x] 2.3 In `planner/pipeline.py` goal-merge (~line 1170): read goals ONLY from the state file — delete the config fallback branch. A charger with no state-file goal has no goal (log at debug). Copy `n_days` in the merge alongside the other goal fields.
- [x] 2.4 In `_persist_ev_multi_day_state` (`planner/pipeline.py` ~line 404): remove every `cfg.get(...)` goal fallback — preserve the existing state-file goal fields verbatim (including `n_days` and `source`); remove the duplicate `target_soc_percent_cfg` key.
- [x] 2.5 In `_persist_ev_multi_day_state`: merge into the existing file instead of replacing it — chargers not processed this run (disabled/skipped) keep their entries unchanged. Done when: test disables a charger in config, runs persist, and its goal survives.
- [x] 2.6 In `backend/api/routers/ev.py`: remove the 2-hour staleness nulling in GET — return the goal whenever the state file has one (it is what the planner acts on) and add `last_planned_at` (the state entry's planner timestamp, null if never planned) to the response model.
- [x] 2.7 In `backend/api/routers/ev.py`: return `n_days` in GET; validate on POST: `ready_by_date` parsed with `date.fromisoformat` (422 on invalid like `2026-02-31`), 422 when in the past, `n_days` must be int ≥ 1 when provided.
- [x] 2.8 Tests: `n_days` round-trip (POST with `every_n_days`/`n_days: 3` → state file → planner run → deadline 3 days out → GET returns `n_days: 3`); past/impossible `ready_by_date` → 422; goal survives a planner persist cycle byte-identical.
- [x] 2.9 Rewrite `test_pipeline_merges_state_file_goals` (`tests/planner/test_pipeline_ev_state.py:126`) to call the real pipeline merge code path; delete the inline copy-paste of the merge loop.

## 3. Energy accounting (the double-count bug)

- [x] 3.1 In `_calculate_required_kwh` (`planner/pipeline.py:171`): when a live SoC reading is available, `required = max(0, (target − soc)/100 × capacity)` with NO delivered subtraction. Only when SoC is unavailable (sensor missing/unreadable — distinguish from a real 0.0 reading), fall back to `target/100 × capacity − delivered_today`.
- [x] 3.2 Gate the fallback's delivered subtraction to configs with exactly one enabled charger (the `slot_observations.ev_charging_kwh` column is an unattributable aggregate). Multiple chargers + no SoC → log a warning, subtract nothing.
- [x] 3.3 Keep `delivered_kwh` as a progress/display field in the state file and API; verify `remaining_kwh` and the `complete`/`behind` status derive from the corrected `required_kwh`.
- [x] 3.4 Tests: live SoC at 65% with 15 kWh delivered → required is 15, not 0 (the regression case); SoC-less single charger still subtracts; SoC-less multi-charger warns and doesn't subtract.

## 4. Multi-day spreading (solver + allocator)

- [x] 4.1 In `planner/solver/types.py` and `adapter.py`: replace `daily_quota_kwh: float | None` on the EV charger input with `quota_by_day: dict[date, float] | None`, mapped from the pipeline's `quota_schedule`. No schedule (single-day goal) → None.
- [x] 4.2 In `planner/solver/kepler.py` (EV goal constraints, ~line 617): when `quota_by_day` is set, add one cap per in-horizon day: `sum(ev_energy[d][t] for slots in that day) <= quota_by_day[day]` (replaces the today-only cap).
- [x] 4.3 Same block: cap the soft requirement at what's actually allowed in-horizon — `effective_required = min(required_kwh, sum of quota_by_day for in-horizon days whose slots end ≤ deadline)` (no schedule → `required_kwh` as today). This stops the shortfall term from slamming tomorrow's slots to deliver the whole multi-day requirement.
- [x] 4.4 Same block: include `ev_surplus_kw` energy in each day's quota sum so surplus charging counts against the day's allocation.
- [x] 4.5 In `_fetch_price_floor_inputs_sync` (`planner/pipeline.py:497`): also compute offset 0 as the average `spot_p50` of TODAY's remaining slots (`slot_start >= now`), so `MultiDayPlanner.compute_quota` gets a real price for day 0 instead of the future-day average.
- [x] 4.6 In `planner/strategy/multi_day_planner.py`: after floor-redistribution and rescaling, clamp every allocation to `[0, that day's max_daily_kwh]`; redistribute any residual rather than emitting negative or above-cap days. Done when: the extreme case (floors exceed later-day capacity) yields all-physical allocations summing to ≤ remaining_kwh.
- [x] 4.7 In `planner/solver/kepler.py` net-excess sink cap (~line 437): subtract planned battery charging — `sum(sinks) <= max-style linear form of (pv − load − battery_charge)` per flagged slot — so sinks can't collect the surplus reward while grid power covers the battery.
- [x] 4.8 Solver tests: 2-day-horizon multi-day goal → tomorrow's energy ≤ tomorrow's quota AND horizon total ≤ in-horizon quota sum; net-excess magnitude test (PV 10/load 2/battery 8 → sinks get 0); surplus-counts-toward-quota test.
- [x] 4.9 Allocator/pipeline tests: today-cheapest → day 0 gets the largest quota; clamping edge case; update existing multi-day and e2e tests to the new semantics deliberately (assert spreading behavior, not just constants).

## 5. HA sync: wire it, make reconnect safe

- [x] 5.1 In `backend/ha_socket.py` `_get_monitored_entities` (EV block, ~line 131): register `ev.get("ha_ready_by_entity")` → `ev_ready_by_{active_idx}` and `ev.get("ha_target_soc_entity")` → `ev_target_soc_{active_idx}` (same dedup pattern as the sensor mappings). This makes the existing handler at ~line 559 reachable.
- [x] 5.2 Rewrite `_sync_ev_schedules_on_startup` (~line 336) to HA-wins-with-sanity: read both entities; adopt target SoC when 1–100; adopt datetime when parseable AND in the future (a past datetime is never adopted — kills the expired-goal seeding bug); for fields where HA is missing/insane, keep the state-file value and push it to HA once. Never blanket-push the state file on reconnect.
- [x] 5.3 Keep/verify echo suppression: Darkstar-initiated HA writes must not re-enter as goal changes (the existing debounce covers the POST path — confirm it also covers the new startup pushes).
- [x] 5.4 Deduplicate the inline `input_datetime` parsing (ha_socket ~lines 376–384 and 597–601) via `backend/core/ha_client.py`'s `get_ha_datetime`, or delete `get_ha_datetime` if unused after this — no dead code either way.
- [x] 5.5 Tests: config with `ha_ready_by_entity` → entity present in `monitored_entities`; synthetic `state_changed` → state file updated; reconnect with HA SoC changed while offline → goal updated, nothing written back to HA; reconnect with past HA datetime → not adopted, state file pushed instead.

## 6. Backend HTTP session ownership

- [x] 6.1 Add a backend-owned `HAClient` provider (e.g. in `backend/core/ha_client.py`): lazy singleton keyed by the running event loop, closed on FastAPI shutdown. Use it in `backend/api/routers/ev.py` `_get_ha_client` and in `ha_socket`'s sync path — never the executor's client instance.
- [x] 6.2 In `HAClient._get_session`: remove the loop-mismatch close-and-rebind path (raise or create-per-loop instead — a session must never be closed from a foreign loop).
- [x] 6.3 In `backend/api/routers/ev.py`: fix the fallback `HAClient` leak (reuse the provider), replace the bare `except: pass` blocks with logged warnings, and delete the `_ = asyncio` lint hack.
- [x] 6.4 Test: saving a schedule from the API loop does not close a session created on another loop (loop-isolation unit test with two event loops).

## 7. Frontend fixes

- [x] 7.1 `CommandDomains.tsx` (~line 392): when `hasEvCharger` is false, render the Metrics view regardless of the persisted `darkstar-resources-tab` value (guard at render, not just by hiding the toggle). Done when: localStorage `'ev'` + no chargers still shows Metrics.
- [x] 7.2 `CommandDomains.tsx` `fetchChargers` (~line 539): call `setError(null)` on success, and add a request-sequence counter so a stale (out-of-order) response never overwrites a newer one.
- [x] 7.3 `EVChargingCard.tsx`: derive view-vs-edit mode from the current `charger` prop every render (remove the one-shot `useState(charger.target_soc_percent === null)` init) so a goal cleared server-side shows the no-goal state, never a phantom 80%/07:00 goal.
- [x] 7.4 `EVChargingCard.tsx` save flow: keep the just-submitted values displayed until the refetch resolves (snapshot on save; skip the reset-from-props effect while the save's refetch is pending) — no revert flash, no indefinite desync if the refetch fails.
- [x] 7.5 `EVChargingCard.tsx` reset effect (~line 41): reset `readyByDate` and `nDays` unconditionally from props (including to defaults when server values are null), matching the other fields.
- [x] 7.6 `EVChargingCard.tsx` (~line 53): balancer badge matches the real states — `'throttling'` (not `'throttled'`), `'paused'`, and `'stale_fallback'` (fail-safe pause must not show "ON TRACK").
- [x] 7.7 `EVChargingCard.tsx` (~line 386): replace `<a href="/settings?tab=advanced">` with React Router `<Link to=...>` (basename-safe under HA Ingress); point it at the tab non-advanced users can actually reach (match `LoadBalancerStatusCard.tsx:151` pattern).
- [x] 7.8 `EVChargingCard.tsx` date handling: add a local-date helper (`toLocalISODate`) and use it for the "tomorrow" default (lines ~29–34, ~331), the `isToday` chip comparison (~line 352), and weekday labels (~lines 350–351) — no `toISOString().slice(0,10)` or `new Date("YYYY-MM-DD")` for calendar logic.
- [x] 7.9 Type the EV data flow narrowly: `chargers` as `EVChargerState[]` (from `lib/api.ts`) in `CommandDomains.tsx` and `EVChargingCard.tsx` props (broader `any` cleanup stays in BACKLOG).

## 8. Docs and verification

- [x] 8.1 Update `config.default.yaml` comments and any EV docs: goals are set in the dashboard, stored in `data/ev_multi_day_state.json`; config carries hardware facts + HA entity mappings only.
- [x] 8.2 Run `./scripts/lint.sh` and the full test suite (`pytest`); fix fallout in existing tests deliberately (assert the new spreading/accounting semantics — do not just bump expected constants to whatever the code now returns).
- [x] 8.3 End-to-end verify on a dev config: set a multi-day goal in the dashboard → planner run → quotas per day are sane and today is priced → HA entities updated → edit target SoC in HA → state file follows without echo loop → restart backend → nothing reverts, no expired goal appears.
