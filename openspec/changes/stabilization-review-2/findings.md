# Findings Ledger — stabilization-review-2

The primary output of this review. Rules per `design.md` D2/D8.

## Rules (append-only)

- **Append-only.** Never edit or delete an existing entry. A correction to finding `#N` is a *new* entry that references `#N` (e.g. "#12 — corrects #7").
- **Numbered sequentially**: `#1, #2, …` in order of discovery, across all phases.
- **Every entry has**: severity (S1–S4), failure-mode mapping (FM1–FM8), evidence (query output / log excerpt / `file:line`), root-cause status **CONFIRMED** or **UNVERIFIED**, and a status line (open / explained-benign / superseded-by-#N).
- **Evidence is re-checked** by the session author before appending — agent/sub-agent claims are never trusted unverified (design D8).
- **Anomalies are never dismissed**: every anomaly found in evidence mining ends up here either as a finding (bug) or an explained-benign entry with the documented cause.

## Severity rubric (design D2)

| Severity | Meaning |
|----------|---------|
| **S1** | Wrong hardware action or money lost *now* |
| **S2** | Wrong data / decision inputs; degradation over time |
| **S3** | Latent bug requiring specific conditions to trigger |
| **S4** | Hygiene / robustness |

## Failure-mode catalog (design.md, the review's spine)

| ID | Failure mode | Cost class |
|----|--------------|-----------|
| FM1 | Executor commands wrong/unsafe hardware state or acts on a stale plan | Hardware + money |
| FM2 | Battery economics inverted (export when hold, loss cycling, wear ignored) | Money (compounding) |
| FM3 | EV not charged by 07:00 departure, or water comfort violated | Comfort + trust |
| FM4 | Silent control-loss (crash-loops, HA drop never recovers, ticks failing unnoticed) | Availability → money |
| FM5 | Data corruption in the feedback loop (kWh attribution, gaps/dupes, dual-writer) | Money (insidious) |
| FM6 | Forecast quality silently degrades | Money |
| FM7 | Config migration/save corrupts `config.yaml` | Availability + safety |
| FM8 | Dashboard shows wrong numbers | Trust |

## Baselines

Recorded 2026-07-01 (phase 1). Git HEAD `1efdadba` (v2.5.11-beta), Python 3.12.0, uv 0.10.9.

- **Test suite (`uv run python -m pytest`)**: **1179 passed, 0 failed** (1369 warnings, 53.88 s). Note: design.md said 1,111 tests — suite has grown since scoping; no failures, no finding.
- **`scripts/ci_local.sh`**: **all 5 gates passed** (ruff, pyright strict, pytest 1179 passed, OpenAPI schema valid with 82 paths, frontend ESLint clean) — "All CI checks passed — safe to push."
- **Production DB snapshot**: copied via `scp` 2026-07-01T21:37:25–33Z UTC to session scratchpad (`dbsnap/planner_learning.db`, 543 MB + 4 MB WAL). `PRAGMA integrity_check` = ok after local WAL checkpoint. Row counts at snapshot: `slot_observations` 23,114 · `execution_log` 255,042 · `data_quality_daily` 149 · `slot_plans` 23,110 · `schedule_planned` 92,269. Latest observation slot: `2026-07-03T00:00:00+02:00` (see #2).
- **OQ3 resolution — `slot_plans` is authoritative.** Evidence: (a) `planner/pipeline.py:877-889` stores every plan to `slot_plans` via `store.store_plan()` ("Rev UI5: Always store plan to slot_plans for performance tracking"); (b) `slot_plans` is read by learning engine, executor, and API routers (`backend/learning/store.py:817-1006`, `backend/api/routers/schedule.py`, `executor/engine.py`); (c) `schedule_planned` has **no writer and no reader** — the `SchedulePlanned` model (`backend/learning/models.py:159-165`, 4 columns) is referenced nowhere else in the codebase, and its data ends 2025-12-10T22:09 UTC (min created_at 2025-11-02). Dead since December 2025 → finding #1. All plan-vs-actual analysis (task 4.1) must use `slot_plans`.

---

## Findings

<!-- Append entries below. Format:

### #N — <one-line title>
- **Severity**: S1–S4
- **FM**: FMx
- **Evidence**: <query/log/file:line>
- **Root cause**: CONFIRMED | UNVERIFIED — <explanation>
- **Status**: open | explained-benign | superseded-by-#N
-->

### #1 — `schedule_planned` is a dead table (92,269 rows of abandoned data)
- **Severity**: S4
- **FM**: FM5 (hygiene-level: dead data in the learning DB invites accidental misuse as a plan source)
- **Evidence**: `SchedulePlanned` model defined at `backend/learning/models.py:159-165` and created in the alembic baseline (`alembic/versions/f6c8f45208da_baseline.py:226`), but referenced by **no other code** (repo-wide grep, 2026-07-01). Table data spans `created_at` 2025-11-02T08:21 → 2025-12-10T22:09 UTC only — no writes for ~7 months while the app kept running. `slot_plans` (23,110 rows, continuously written by `planner/pipeline.py:877-889`) is the authoritative plan record.
- **Root cause**: **CONFIRMED** — legacy table superseded by `slot_plans`; the writer was removed around 2025-12-10 but the table and model were left behind.
- **Status**: open. Recommend a follow-up change: drop the table + model (and its index), or archive the rows if the 2025-11→12 history has value. Not urgent; no runtime effect.

### #2 — Future-dated rows in `slot_observations` (price pre-seeding)
- **Severity**: S4 (anomaly, classified benign)
- **FM**: FM5 (candidate — resolved as intended design)
- **Evidence**: 98 rows with `slot_start` up to `2026-07-03T00:00:00+02:00` (≈25 h beyond snapshot time) containing only prices; energy columns are `0.0`, battery/SoC columns NULL. Writer: `LearningStore.store_slot_prices()` (`backend/learning/store.py:64-114`) upserts future slots with price data only, using `ON CONFLICT ... COALESCE` so later observation writes fill in energy without clobbering prices. The `0.0` energies come from column `server_default=text("0")` (`backend/learning/models.py:18-23`), not from a recorder write.
- **Root cause**: **CONFIRMED** — intentional price pre-seeding for tomorrow's slots.
- **Status**: explained-benign. Caveat for later phases: because energy columns default to `0.0` (not NULL), an *unrecorded* slot is indistinguishable from a genuinely-zero slot by value alone — phase 3 continuity/balance analysis must use `batt_charge_kwh`/`soc_*` NULLness or `quality_flags` to tell "never recorded" from "recorded as zero", and must exclude future-dated rows.

### #3 — `execution_log.error_message` is never populated (2,536/2,536 failures NULL)
- **Severity**: S4
- **FM**: FM4 (observability: failures carry no top-level reason)
- **Evidence**: snapshot query 2026-07-01: all 2,536 `success=0` rows have `error_message IS NULL`. Failure detail exists only inside the `action_results` JSON (per-action `message`/`error_details`), and `action_results` itself is NULL before 2026-02-01 (first non-NULL row `2026-02-01T11:38`), so the 878 January failures have *no* recorded reason at all.
- **Root cause**: **CONFIRMED** for the column being dead (no code path writes it — engine logs per-action detail into `action_results` instead); January-gap is a since-fixed logging limitation.
- **Status**: open. Follow-up: either populate `error_message` with a failure summary or drop the column; monitors (phase 7) must derive failure reasons from `action_results`.

### #4 — Two historical executor failure episodes (Jan 6–18, Feb 15–Mar 1), both resolved
- **Severity**: S3 (historical; resolved)
- **FM**: FM4
- **Evidence**: monthly tick failure rate: 2026-01 2.57%, 2026-02 3.67%, then 0.04%/0.07%/0.27%/0.03% (Mar–Jun). Episode 1: Jan 6–18, ~830 failures, avg `duration_ms` ≈ 10.6 s (timeout-shaped), no detail recorded (see #3). Episode 2: Feb 15–Mar 1, ~1,430 failures, all "Failed to set <action>" across every action type. Episode 2 ends exactly at the async-HTTP-client migration commits (`e81e4d25` 2026-03-01, `1a6790ce` 2026-03-02); episode 1 tapers near the WAL-mode fix (`dfb14e4b` 2026-01-21).
- **Root cause**: episode 2 **CONFIRMED** (sync HTTP client / session bugs, fixed by async migration); episode 1 **UNVERIFIED** (no error detail survives; plausibly DB locking per the WAL fix, cannot be proven).
- **Status**: explained-resolved. Post-March success rate ≥ 99.7% every month; residual failures are classified in #6/#7.

### #5 — Excess-PV water boost (85 °C) has never once succeeded — HA rejects it (HTTP 400)
- **Severity**: S2
- **FM**: FM2 + FM3 (PV surplus meant for hot water is lost; comfort feature silently dead)
- **Evidence**: action-level history over full snapshot: non-skipped `water_temp` sets succeed routinely at 40/50/60 °C (20/845/867 successes) but **0/99 at 85 °C** — all 99 attempts on 2026-05-24 (12:00–16:00, peak PV) failed `HTTP 400 Bad Request` on `input_number.set_value` for `input_number.vvbtemp`. Command source: excess-PV boost slots use `temp_max` = 85 (`executor/controller.py:351-354`, config.yaml:323); HTTP 400 from HA `input_number.set_value` indicates value outside the entity's min/max range. Additionally `execution_log.commanded_water_temp` recorded 50/60 that day (legacy aggregate `decision.water_temp`), hiding the actual per-device 85 command from the log.
- **Root cause**: **CONFIRMED** at behavior level (85 exceeds the HA slider's max; sets ≤60 succeed). Exact slider max **UNVERIFIED** — operator can read `input_number.vvbtemp` min/max in HA UI in seconds. Note `temp_boost` (70) and vacation `anti_legionella_temp_c` (65) are also >60 and would likely fail the same way.
- **Status**: open. Follow-up fix options: raise the HA input_number max, or clamp commanded temps to the entity max with a startup validation. Also fix `commanded_water_temp` logging to reflect per-device commands.
- **Addendum (same session)**: the *predecessor* implementation — the `excess_pv_heating` override (161 ticks, 2026-03-30 → 2026-05-03, since removed from `executor/override.py`) — also issued **zero** water_temp actions across all 161 ticks (action_results scan). Excess-PV water heating has therefore never functioned in *any* incarnation over the full 8 months.

### #6 — DST spring-forward day: planner produced no valid slots for 8 hours (2026-03-29 00:00–09:00)
- **Severity**: S3
- **FM**: FM5 + FM3 (no optimized control for 8 h on the 23-hour day; safe but blind)
- **Evidence**: 466 consecutive `slot_failure_fallback` ticks on 2026-03-29 from 00:00:00+01:00 through 09:00:00+02:00 (spanning the 02:00→03:00 CET→CEST jump), executor held `idle` / SoC-hold 25–26 % the whole time; first normal tick 09:01:00+02:00. This is 70 % of all fallback ticks in history (466/666). The executor safeguard **worked as designed** (no grid charging, SoC held, recovered without restart); the planner/schedule side failed to provide slots the executor considered valid for the DST morning.
- **Root cause**: **UNVERIFIED** — planner or schedule-slot-labeling DST handling for the 23-hour day; exact mechanism to be identified in task 5.3 code read and reproduced in task 6.6 DST fault-injection tests.
- **Status**: open. Note: the system has never yet lived through a fall-back (25-hour) day (started 2025-11-03; next is 2026-10-25) — that path is completely unexercised in production.
- **Addendum (phase 5, `slot_plans.created_at` forensics)**: the outage was a **~31 h planner failure**, not an executor mislabeling. New-slot writes: Mar 27 = 188 rows (horizon reaching exactly `2026-03-28T23:45+01:00` — the last slot before the DST day), Mar 28 = **0 rows all day** (every hourly run failed to extend the horizon into Mar 29), Mar 29 first write `07:00:29Z` creating slot `09:00+02:00`. So no plan for the DST day ever existed until 09:00 local; the executor fallback (00:00–09:00) behaved exactly right. Root cause is in the *planner* handling of a horizon that crosses the nonexistent 02:00–03:00 hour; still UNVERIFIED at line level (March logs expired) — task 6.6 must reproduce a planner run for a spring-forward target day, which will pinpoint the crash.

### #7 — Explained-benign batch: control-loop anomalies with verified benign causes
- **Severity**: n/a (classification entry)
- **FM**: FM1/FM4 candidates, all resolved benign
- **Evidence & classification** (all from snapshot queries, 2026-07-01):
  1. **137,865 ticks with discharge current > 0 while `planned_discharge=0`** — by design: the controller always returns max discharge current to let the battery cover house load in self-consumption mode (`executor/controller.py:325-335` "ALWAYS return MAX to allow load coverage"). Not a command to discharge.
  2. **1,402 ticks with `planned_charge>0.1` but grid charging off** — 1,256 had PV ≥ planned charge (PV-charging needs no grid switch); the remaining 146 are PV-charge slots where instantaneous PV read was momentarily below the slot-average plan (samples show `self_consumption` mode with proportional charge current set). Correct behavior.
  3. **`planned_soc_target` vs `commanded_soc_target`: 0 mismatches** in 251,004 non-override ticks. **0 ticks** ever enabled grid charging during `slot_failure_fallback`.
  4. **198 fallback ticks with SoC-target drift >2 %** — all Dec 2025/Jan 2026 (early-era fallback); the 2026-03-29 episode shows current code tracks SoC correctly per tick. Historical, superseded.
  5. **Tick durations healthy**: p50 ≈ 25 ms, p95 ≈ 100–155 ms since March (vs p50 1,299 ms in February pre-async-fix). No degradation trend; rare 40–49 s outliers coincide with HA restarts.
  6. **HA disconnects recover autonomously**: 2026-07-01 21:37 incident — WS closed 21:37:33, reconnected 21:37:53 (20 s), exactly one tick absent (21:38), zero failed ticks, recorder cycles 21:30/21:45/22:00 all normal, no app restart. Week sweep (Jun 24–Jul 1): 29 WS errors, 7 reconnects, every episode recovered. Scattered `404 Not Found` action failures (Mar–Jul, ~60 total) coincide with HA restarts (entity briefly unregistered) and self-heal next tick.
  7. **Stale-schedule safeguard verified in code**: `_load_current_slot` rejects schedules older than `max_schedule_age_hours` (config = 2 h, `config.yaml:274`) and the executor holds via fallback (`executor/engine.py:1552-1605`). Fired episodes are the fallback episodes above. Caveat: schedules missing `meta.generated_at` bypass the age check silently — covered by fault-injection task 6.5.
- **Status**: explained-benign.

### #8 — January 2026: ~129 slots recorded battery grid-charging with zero import energy
- **Severity**: S2 (historical; corrupt inputs for ML/economics analysis for those days)
- **FM**: FM5
- **Evidence**: snapshot query: slots with `batt_charge_kwh > 0.3`, `import_kwh < 0.05`, and PV < half the charge energy: **129 in 2026-01** (esp. nights of Jan 16–20, e.g. `2026-01-17T02:00` charge 1.24 kWh + load 1.59 kWh + water 0.77 kWh with import 0.0), vs 4 in March and 4 in June total. These drive the energy-balance residual tail (p0.1 = −2.2 kWh/slot; all top-12 outliers are Jan nights). Physically impossible (charging at night without import) → import under-recorded, not a real flow.
- **Root cause**: **UNVERIFIED** — coincides with the January executor instability era (#4); plausibly the import sensor or its recorder read was unavailable while the WAL/locking issues were active. HA history no longer retains January (checked: `/api/history/period` returns 0 samples for 2026-01-17), so it cannot be externally reconstructed.
- **Status**: open (historical). Consequence: January 16–20 observation data is untrustworthy for training/economics; nothing flagged it (see #9). Follow-up: consider a one-off quality re-flag of those days; the energy-balance runtime monitor (phase 7) prevents recurrence going unnoticed.

### #9 — Daily data-quality evaluation is dead: `data_quality_daily` last written 2025-11-28
- **Severity**: S2
- **FM**: FM5 (silent data corruption has no detector — exactly how #8 went unnoticed)
- **Evidence**: table contents span 2025-07-03 → 2025-11-28 (149 rows: 137 clean, 11 mask_battery, 1 exclude) — the *backfill* era only. Repo-wide grep: `data_quality_daily`/`DataQualityDaily` referenced only by `backend/learning/models.py` and the alembic baseline — **no writer and no reader in live code**. The design assumption that this table provides ongoing daily quality records is false; live-era data (Dec 2025 →) has never had a daily quality evaluation, which is why #8 was never flagged.
- **Root cause**: **CONFIRMED** — the quality-evaluation process belonged to the removed backfill pipeline; it was never ported to the live recorder.
- **Status**: open. Direct consequence for phase 7: monitors-spec invariant 7 ("most recent `data_quality_daily` status not failed") **cannot be implemented as written** — it would evaluate a 7-month-old row forever. The monitor must compute data quality from `slot_observations` directly (or a follow-up fix change must revive daily quality writing). The non-clean historical rows themselves check out (bring-up era battery masking; `2025-11-28 exclude` with 33 missing slots matches the recorder cut-over).

### #10 — Explained-benign batch: data-integrity anomalies with verified benign causes
- **Severity**: n/a (classification entry)
- **FM**: FM5 candidates, all resolved benign
- **Evidence & classification** (snapshot queries, 2026-07-01):
  1. **Slot continuity**: 23,015 past slots, 0 duplicates (PK), 0 misaligned starts, **10 gaps total — all 2025-11-14 → 2025-12-03** (bring-up era), largest 225 min. Zero gaps in 7 months since, including the 2026-03-29 DST day (the schedule failed that day, #6, but the *recorder* stayed continuous). 33 past rows have NULL SoC (never recorded), 26 of them Dec 19–22.
  2. **Energy balance**: residual (PV + import + discharge − base load − water − EV − export − charge) over 22,982 recorded slots: median +0.001 kWh, p5/p95 = −0.47/+0.26 kWh. 378 slots |residual| > 1 kWh: 186 are the January cluster (#8); the remaining ~190 (~0.8 %/month steady) are sub-2 kWh sensor-timing skew at high-power transitions (battery power integration vs cumulative meters), symmetric in sign — measurement noise, not systematic bias.
  3. **SoC continuity**: `soc_end` vs next `soc_start` — **2 jumps > 3 % in 8 months**, both Dec 19/22 2025 (the bring-up gap days). Perfect since.
  4. **Dual-writer**: disjoint by construction — recorder upserts all measurement/price columns but never `executed_action` (`backend/learning/store.py:178-245`); executor writes *only* `executed_action` (`executor/history.py:146-161`). Column-level ownership documented in `backend/recorder.py:8`. No torn rows found (the 33 NULL-SoC rows are missed recordings, not partial writes).
  5. **Recorder vs HA cumulative sensors** (task 3.6): 2026-06-30 — import 1.76 rec / 2.1 HA, export 21.7/21.9, load(base+water+EV) 19.96/20.2, PV 32.09/32.3. 2026-06-28 — 12.92/13.8, 1.25/1.3, 30.48/30.5, 26.15/25.9. 2026-06-22 — 0.65/0.6, 29.03/29.9, 13.16/13.3, 39.65/39.8. All within sensor resolution + day-boundary sampling error. Winter/January spot-check impossible: HA history retention (~10 days) no longer covers it.
- **Status**: explained-benign.

### #11 — The production EV charger is a mockup: EV optimization has never controlled a real vehicle
- **Severity**: S3
- **FM**: FM3 (EV readiness unassessable) + FM2 (phantom-load risk)
- **Evidence**: `config.yaml` `ev_chargers[0]`: `sensor: sensor.heat_pump_power`, `soc_sensor: sensor.inverter_battery` (the *house* battery), `plug_sensor: input_boolean.ev_mockup`, `switch_entity: input_boolean.ev_mockup_switch`, `battery_capacity_kwh: 10`, `enabled: true`. `slot_observations.ev_charging_kwh` is 0.0 for **every recorded slot in 8 months** (monthly sums all 0.0, zero active slots). Task 4.3 (EV-readiness audit) is therefore vacuous — there are no real plugged-in nights to audit.
- **Root cause**: **CONFIRMED** — test/development mockup left enabled in production config.
- **Status**: open. Risk: if `input_boolean.ev_mockup` is ever toggled on (HA UI slip), the planner will reserve real battery/grid capacity — and shift real money — for a phantom 10 kWh EV mapped to the heat-pump sensor. Follow-up: disable the device or gate mockup entities out of production configs. Exit statement must state FM3-EV is *not* production-verified.

### #12 — Water heating routinely violates the configured 8 h max-gap (soft constraint ineffective)
- **Severity**: S3
- **FM**: FM3
- **Evidence**: config `water_heaters[0].max_hours_between_heating: 8` with `min_kwh_per_day: 6`. Recorded heating activity (`water_kwh > 0.05`, Feb 2026 → snapshot, i.e. after the water sensor era began): **95 gaps > 8 h** — 12–26 *per month* in normal (non-vacation) months, typical size 9–18 h (39× 10–14 h, 23× 14–24 h). The >24 h gaps (May 26–31, Jun 13–16, incl. one 71 h) coincide with vacation mode (`vacation_state.last_anti_legionella_at = 2026-05-27T14:15`; vacation intentionally disables the gap constraint, `planner/pipeline.py:678-682`) — those are benign. The near-daily 10–18 h gaps in Feb–Apr are not: the solver treats the gap as a soft penalty (`water_heating_max_gap_hours`, `planner/solver/types.py:73`) and price/spacing incentives dominate it.
- **Root cause**: **CONFIRMED** at behavior level (soft penalty systematically outweighed); the exact penalty-weight interaction is examined in task 5.1.
- **Status**: open. Operator decision needed: either the 8 h figure is aspirational (→ relax config to match reality) or comfort matters (→ fix change strengthening the constraint). Note: daily `min_kwh_per_day: 6` is *also* under-delivered on ~10–12 days/month in Feb/Mar/May/Jun — partly usage-driven; listed for the same decision.

### #13 — Explained-benign batch: economics & forecast anomalies with verified causes
- **Severity**: n/a (classification entry)
- **FM**: FM2/FM6 candidates, resolved benign or resolved-by-fix
- **Evidence & classification**:
  1. **Plan-vs-actual divergence** (task 4.1): worst days fall in three classes — (i) Jan 8–14: plans not executed during the January instability era (#4/#8); (ii) Dec 25–26 & similar early days: **data artifact** — `slot_plans` rows for pre-2026-01-07 dates were backfilled with all-zero values on 2026-01-07 (4,000+ zero rows in Nov–Feb), so "plan zero, actual active" is fake divergence; (iii) recent days (Jun 12, Jun 30): planned overnight discharge exceeds actual because the executor discharges to match *actual* load in self-consumption mode while the plan assumed forecast load — the plan is an envelope, not a setpoint. Mechanism verified per-hour for 2026-06-12. No unexplained divergence class remains.
  2. **Money audit** (task 4.2): monthly realized net cost declines 3,344 SEK (Feb) → −92 SEK (Jun) as PV season starts — sane. Grid-charging at import prices above same-day export value is self-consumption arbitrage (charge cheap night, avoid expensive morning import), not a loss — benchmark against later *import* prices, not export. **58 slots exported at export price ≤ 0** (19.5 kWh, −0.53 SEK total): all PV overflow (no battery discharge involved), clustered on 2026-04/05 days including 05-24/05-27 — i.e. the days the excess-PV water boost was failing (#5). Money impact negligible; the systemic cause is #5.
  3. **Forecast drift** (task 4.5): weekly PV MAE grows 0.02 → 0.15 kWh/slot absolute, but *relative* error improves (0.70–0.77 of mean PV in winter → 0.29–0.40 in spring/summer); load MAE improves 0.28 → 0.14 kWh/slot. No degradation trend, no step change around the June fixes. Winter cold-start is the worst era, as expected.
  4. **PV forecast ceiling** (task 4.6): 36 stored forecasts exceeded the 7.11 kWp physical ceiling (max 2.26 kWh/slot ≈ 9.05 kW; best-ever observed slot is 1.43 kWh). All created 2026-03 → 2026-05 by `aurora`; **zero after the 2026-06-17 fix** `172d5764` ("Switch PV physical ceiling to DC-side limits"). Explained-resolved; runtime monitor invariant 6 (phase 7) guards recurrence.
- **Status**: explained-benign / explained-resolved.

### #14 — The water max-gap constraint does not exist in the solver (root cause of #12)
- **Severity**: S2
- **FM**: FM3
- **Evidence**: `water_heating_max_gap_hours` (`planner/solver/types.py:73`) and per-heater `max_hours_between_heating` (`types.py:27`, populated `adapter.py:93,453-457`) are **never referenced by any constraint or objective term in `kepler.py`** (grep verified). `kepler.py:557` hardcodes `gap_violation_penalty = 0.0` ("Deprecated in K16") and adds the constant twice (`kepler.py:632-633`); `adapter.py:313` forces the legacy `water_comfort_penalty_sek = 0.0`. The only active water terms are the daily-minimum penalty, block-start penalty, and a *minimum*-spacing constraint (5 h) that pushes blocks apart. 10–18 h gaps are the solver's expected optimum, not a violated intent. (Verified by session author; originally reported by review agent.)
- **Root cause**: **CONFIRMED** — the gap feature was deprecated in the solver (K16) but the config key, adapter plumbing, and UI expectation survived.
- **Status**: open. Corrects the mechanism guessed in #12 ("penalty too weak" → in fact penalty absent). Follow-up options: reimplement the gap constraint in Kepler, or delete the dead config/plumbing and document the actual comfort model.

### #15 — Water comfort penalty config keys are silently ignored (comfort_level table wins)
- **Severity**: S3
- **FM**: FM7 (config says one thing, system does another) + FM3
- **Evidence**: `adapter.py:233-311` derives all water penalties exclusively from `comfort_level` via `COMFORT_MAP` (level 3 → reliability 15 SEK, block_start 3.0, block 2.0). The config keys `reliability_penalty_sek: 1000`, `block_start_penalty_sek: 1`, `spacing_penalty_sek: 1.2` (`config.yaml:83,67,69`) are **never read by the adapter**. The operator believes a 1000 SEK "Must Have" penalty guards the daily water minimum; the solver actually uses 15 SEK — which a strong price spread can outbid, consistent with ~10–12 sub-6 kWh days/month (#12).
- **Root cause**: **CONFIRMED** (grep: those keys appear only in comments/COMFORT_MAP values, not in any config read).
- **Status**: open. Follow-up: either honor the explicit keys when present or remove them from config.yaml/UI so the comfort_level model is the single source of truth.

### #16 — Solver exports PV at zero/negative prices instead of curtailing (tiebreak inversion)
- **Severity**: S3 (money impact currently trivial; structural)
- **FM**: FM2
- **Evidence**: objective terms `kepler.py:495-525`: export revenue uses `export_price − export_threshold`, curtailment costs `curtailment_penalty` = 0.1 SEK/kWh (`adapter.py:445-447`, config `kepler.curtailment_penalty_sek`, config.yaml:232). PV surplus must go to export or curtailment; at export price 0 export costs 0 while curtailment costs 0.1 → solver **exports whenever price > −0.1 SEK/kWh**, i.e. pays the grid up to 0.1 SEK/kWh to take PV. Exactly matches the 58 production slots exported at price ≤ 0 (#13.2, −0.53 SEK total).
- **Root cause**: **CONFIRMED** — curtailment "waste penalty" applies even when exporting is worse than wasting.
- **Status**: open. Follow-up: make the curtailment penalty apply only above 0 export price (or set the export floor to max(price, −curtailment_penalty) breakeven). Low priority by money, but trivially fixable.

### #17 — Kepler objective: terms verified correct (worked example)
- **Severity**: n/a (defense evidence for FM2)
- **FM**: FM2
- **Evidence**: verified by agent review + session-author re-check of the cited lines: wear cost half-per-leg so a full cycle costs exactly `battery_cycle_cost_kwh` (`kepler.py:498`, no double-count; the Rev-K20 stored-energy double-count remains removed, comment at `kepler.py:511-514`); import cost sign/pairing correct (`kepler.py:499`); ramping term unit-correct (kWh/h → kW × SEK/kW, `kepler.py:486-506`); arbitrage breakeven hand-computed: with η=0.95 each way and wear 0.2, discharge price must exceed (charge price + 0.19)/0.9025 — ≈ 0.32 SEK/kWh spread at 1.00 SEK charge price. Sane.
- **Status**: defense recorded.

### #18 — Dashboard silently freezes on lost WebSocket: no refetch on reconnect, reconnection gives up after 10 attempts
- **Severity**: S3
- **FM**: FM8
- **Evidence**: `frontend/src/lib/socket.ts:62-65` (`reconnectionAttempts: 10`, delays 1–5 s → gives up permanently after ~50 s of backend unavailability); the `connect` handler only logs (`socket.ts:113-115`) — nothing refetches state on reconnect; `Dashboard.tsx:442-444` fetches data once on mount and thereafter relies entirely on socket pushes. No staleness indicator exists.
- **Failure scenario**: backend restarts (e.g. deploy) or network blips > ~50 s while a dashboard tab is open → tab reconnects never (or reconnects but missed events are lost) → operator sees frozen pre-outage numbers with no warning and may act on them.
- **Root cause**: **CONFIRMED** (code read).
- **Status**: open. Follow-up: refetch bundle on `connect`, set `reconnectionAttempts: Infinity`, add a visible "live/stale" indicator.

### #19 — Executor's SQLite engine shares one connection across threads (StaticPool)
- **Severity**: S4 (latent; currently benign in practice)
- **FM**: FM5
- **Evidence**: `executor/history.py:85-100` — sync engine with `poolclass=StaticPool` + `check_same_thread: False` = a single shared connection. Users: the executor tick thread (`engine.py:1490` `log_execution`) *and* FastAPI threadpool workers (`backend/api/routers/executor.py:250` calls `executor.history.get_history` for the history endpoint/CSV export). Two threads interleaving transactions on one SQLite connection is not crash-safe at the SQLAlchemy layer (shared transaction state), though CPython's serialized sqlite3 prevents memory corruption. Both engines do set `timeout: 30.0` and WAL is enabled idempotently (`store.py:57-60`, `history.py:96-98`) — the 2026-01 locking era does not reproduce from current code.
- **Root cause**: **CONFIRMED** pattern; no observed production incident since March.
- **Status**: open (low priority). Follow-up: use a regular pool (per-thread connections) — one-line change.

### #20 — Config hygiene: dead key disagreeing with the live one; mixed timestamp conventions
- **Severity**: S4
- **FM**: FM7/FM5
- **Evidence**: (a) `config.yaml` `executor.controller.inverter_ac_limit_kw: 8.8` is read by **no code** (repo grep); the solver's real AC limit is `system.inverter.max_ac_power_kw: 8` (`adapter.py:434-438`) — an operator editing the dead 8.8 key would change nothing while believing they raised the limit. (b) `charge_efficiency` exists in two live places with independent readers: `battery.charge_efficiency` (planner, `adapter.py:394`) and `executor.controller.charge_efficiency` (executor, `executor/config.py:527`) — currently both 0.92, can silently diverge. (c) DB timestamp conventions are mixed: `slot_start` is local ISO with offset, `slot_plans.created_at`/`execution_log.executed_at` refresh conventions differ (`created_at` = naive UTC via `func.current_timestamp()`, `store.py:359`; `executed_at` = local ISO) — any consumer comparing them must convert; phase-7 monitors must handle this explicitly.
- **Root cause**: **CONFIRMED** (code reads).
- **Status**: open. Follow-up: delete dead keys, single-source shared constants, document timestamp conventions.

### #21 — Phase-5 defense evidence (verified correct by code read)
- **Severity**: n/a (defense entry)
- **FM**: FM1, FM7, FM8
- **Evidence**:
  1. **FM1 — executor fail-safe**: tick success requires *all* actions to succeed (`engine.py:1483-1486`); a mid-sequence failure marks the tick failed, and the next tick (60 s) reconverges idempotently — every action skips writes when the device is already at target ("Already at X", e.g. `actions.py:794-805`), with EEPROM-protecting write thresholds (`write_threshold_a/w`, config). Manual override/pause suppresses inverter/EV/water writes (`engine.py:1389-1391` `skip_writes`); commanded-value range validation against HA entity min/max is **absent** (→ #5 follow-up).
  2. **FM7 — config writes**: `_write_config` (`config_migration.py:927-999`) validates → timestamped backup + `.bak` → temp-file write → atomic `replace` (with bind-mount fallback) → post-write re-parse verification → restore from backup on failure. Solid.
  3. **FM8 — chart unit conversion**: forecast kWh series are converted to kW via `/hourFraction` consistently, power series stay kW (`ChartCard.tsx:1680-1703`); the June 26 axis-unification fix (`1efdadba`) is in place — y1/y2/y4 share one max = max(gridMaxKw, inverterMaxKw, solarKwp), so equal kW renders equal height.
  4. **Plan storage units**: `store_plan` stores kWh columns directly from kepler kWh outputs, converts `water_heating_kw * 0.25` (`store.py:328-347`) — consistent with 15-min slots; upsert refreshes `created_at` on every planner write (`store.py:359`), making it a valid plan-freshness signal for monitors.
- **Status**: defenses recorded.

### #22 — Phase 2–5 consolidation: failure-mode coverage matrix (task 5.7)
- **Severity**: n/a (consolidation entry)
- **Evidence**: per-FM status after evidence mining + targeted review:

| FM | Defense evidence | Open findings |
|----|------------------|---------------|
| FM1 (wrong/unsafe commands, stale plan) | Fallback + stale-schedule safeguard verified in code & history (#7.7, #6 executor side); fail-safe aggregation + idempotent writes (#21.1); plan-vs-command 0 SoC mismatches in 251k ticks (#7.3) | #5 (no value-range validation), #6 (planner DST outage — safe but blind) |
| FM2 (economics inverted) | Objective terms verified w/ worked example (#17); money audit sane (#13.2) | #16 (curtailment tiebreak), #5 (PV→water dump dead) |
| FM3 (EV / water comfort) | — | #11 (EV is mockup — unverifiable), #12/#14 (gap constraint doesn't exist), #15 (comfort penalties ≠ config) |
| FM4 (silent control-loss) | HA disconnects self-heal, verified incident + week sweep (#7.6); success ≥99.7 %/mo since Mar (#4); durations healthy (#7.5) | #3 (error_message dead → weak forensics) |
| FM5 (data corruption feedback loop) | Slot/SoC continuity near-perfect (#10.1/3); dual-writer disjoint (#10.4); recorder validated vs HA (#10.5) | #8 (Jan import gap, historical), #9 (quality evaluation dead — no detector), #19, #20c |
| FM6 (forecast degradation) | Relative error improving; no drift (#13.3); PV ceiling fixed + verified (#13.4) | — (monitor to guard recurrence) |
| FM7 (config corruption) | Atomic write + backup + verify (#21.2) | #15/#20 (silently-ignored and dead keys — config *truthfulness*, not file integrity) |
| FM8 (dashboard lies) | Unit conversion + axis unification verified (#21.3) | #18 (stale-after-disconnect) |

- Every FM now has either verified defense evidence, open finding(s), or both. FM3-EV is explicitly **not production-verifiable** (#11).
- **Status**: consolidation recorded.

### #23 — Fault-injection results (phase 6): 24 scenarios, all safe; two documented gaps
- **Severity**: n/a (test-phase entry; sub-items S4)
- **FM**: FM1/FM4/FM5
- **Evidence**: new suite `tests/fault_injection/` (24 tests, all passing): HA connection-refused/timeout/404/5xx during executor tick — no unhandled exception, no command applied, clean recovery; recorder cycle with all sensors dead — survives on cached state; stale schedule (> 2 h) — held with warning; corrupt schedule.json / corrupt recorder state file — graceful; restart mid-slot — no double-counting (delta = true increment); negative meter delta — rejected as invalid; empty price data — planner refuses (`PlannerError: PRICES_UNAVAILABLE`) and the last good schedule.json is **not** overwritten; partial prices — plans only the priced window; price gaps — no crash, no negative prices; **DST spring-forward and fall-back planner runs — pass on current code** (continuous, duplicate-free slot grids), and executor slot lookup works on both sides of both transitions incl. the ambiguous hour.
- **Notable results**:
  1. **#6's crash does not reproduce on current code** (synthetic inputs, mode=baseline). Either fixed incidentally in the ~200 commits since March, or specific to the full-mode/Aurora path or the exact input shape that night. #6 stays UNVERIFIED-root-cause; the 2026-10-25 fall-back day is now pre-verified at planner level.
  2. **Gap (documented in test, S4)**: schedules missing `meta.generated_at` bypass the freshness check (`test_schedule_without_generated_at_bypasses_age_check` pins current lenient behavior).
  3. **Gap (documented in test, S4)**: cumulative-meter deltas have no plausibility ceiling — a 500 kWh/15 min spike records raw (`test_unit_outlier_spike_is_recorded_raw` pins it). The phase-7 energy-balance monitor is the systemic guard; a clamp is a follow-up fix.
  4. **Test-infrastructure note**: planner preflight (`planner/preflight.py:154-190 check_price_data`) validates prices against the real wall clock, ignoring `now_override` — historical replay/simulation through the full pipeline is impossible (tests had to target future DST transitions, computed dynamically). S4, worth a follow-up if replay matters.
- **Status**: recorded; suite gates CI from now on.

### #24 — Corrects #5: action-level command failures never notify the operator (the real defect)
- **Severity**: S2
- **FM**: FM4 + FM8
- **Evidence**: Operator review 2026-07-02: the 85 °C rejection was *site config* — the HA `input_number.vvbtemp` max was 80 °C; the operator has already raised it in production, closing the direct water impact. What remains is why 99 consecutive failures in one afternoon (plus the recurring Apr–Jun vvbtemp failures) were never seen despite `notifications.on_error: true` (config.yaml): failed `ActionResult`s are appended to the in-memory `recent_errors` deque and emitted as a WebSocket `executor_error` event only (`executor/engine.py:1444-1460`). `dispatcher.notify_error` — the path that honors `on_error` and pushes to the phone — is wired **only** to stale-schedule warnings (`engine.py:1108`), EV charge failure (`engine.py:1350`), and unhandled tick exceptions (`engine.py:1532`). Persistent hardware-command rejection is therefore silent unless the dashboard is open.
- **Root cause**: **CONFIRMED** (code read).
- **Status**: open — this supersedes #5's follow-up. Fix change should add notify-on-repeated-action-failure with episode dedup (e.g. first failure of a failure streak per action type), mirroring the EV-failure pattern at `engine.py:1343-1352`. The `command_success` runtime monitor also catches this class within hours, but the push is the operator's chosen channel. (#3, the dead `error_message` column, is part of the same observability cluster.)

### #25 — Corrects #11: Darkstar is multi-user software; the EV mockup is this instance's deliberate state
- **Severity**: S4 (downgraded from S3)
- **FM**: FM3
- **Evidence**: Operator review 2026-07-02: other Darkstar users run real EV chargers in production fine; this instance's operator has no EV yet, and the mockup entities are an intentional local test setup. #11's framing ("EV optimization has never controlled a real vehicle") was wrong at the product level — it is unverified *on this instance only*, and the evidence phase (this DB) cannot see other installs.
- **Root cause**: **CONFIRMED** (operator statement).
- **Status**: open, low priority. Residual risk stands: an enabled mockup charger on a production instance plans real battery/grid capacity around a phantom EV if `input_boolean.ev_mockup` flips on. Recommendation shrinks to: disable the device until the real EV arrives, or add a config warning for mock/test entity IDs in enabled devices. Exit statement corrected: FM3-EV is defended by other installs' operational history (anecdotal, outside this review's evidence base) — not falsified, just unverifiable here.

### #26 — Status update on #6: DST planner outage does not reproduce; treat as fixed-unverified, guarded
- **Severity**: S3 → guarded
- **FM**: FM5/FM3
- **Evidence**: fault-injection DST tests (#23) pass on current code for both transitions, including the exact production failure shape (evening-before run whose horizon crosses the nonexistent hour). March logs are expired, so *which* commit fixed it cannot be proven — likely one of the timestamp/normalization fixes in the ~200 commits since (e.g. the `dst_safe_localize` utilities are used throughout `planner/output/formatter.py` and `strategy/s_index.py` today).
- **Status**: closed-as-guarded: (a) DST tests gate CI permanently, (b) the `plan_freshness` monitor alerts within 3 h if any planner outage recurs, (c) the first live fall-back day is 2026-10-25 — the soak-window criterion should note it.

---

## Synthesis & Exit (phase 8)

### Completeness audit (task 8.1)

23 ledger entries. Every finding carries severity, FM mapping, evidence, and CONFIRMED/UNVERIFIED status. Every anomaly surfaced in phases 2–4 is classified as a numbered finding or an explained-benign entry (#7, #10, #13); no unexplained anomaly remains. UNVERIFIED root causes: #4-episode-1 (Jan failures — no error detail survives, resolved regardless), #6 (DST planner crash point — logs expired; does not reproduce on current code, see #23.1), #5's exact HA slider max (operator can read it in HA UI in seconds).

### Proposed follow-up fix changes (task 8.2 — recommendations only)

1. **`fix-water-heating-truthfulness`** (S2, do first — user-facing comfort + money): #5 (85 °C rejected — clamp commanded temps to entity max or raise the slider), #12/#14 (implement the max-gap constraint in Kepler or delete the dead config), #15 (honor or remove the ignored penalty keys). One change — same subsystem, one test surface.
2. **`fix-observability-gaps`** (S2): #9 (revive daily data quality or formally adopt the live monitor as its replacement), #3 (populate `error_message` or drop the column), #18 (dashboard refetch-on-reconnect + staleness indicator).
3. **`fix-ev-config-hygiene`** (S3): #11 (disable mockup EV in prod config; gate mock entities), optionally with #20 dead-key cleanup and #1/`schedule_planned` + `data_quality_daily` table drops (S4s ride along).
4. **`fix-minor-solver-economics`** (S3, cheapest): #16 (curtailment tiebreak below zero export price). Could ride along with change 1 (same file).
5. Deferred/no-change: #8 (historical data; optionally re-flag Jan 16–20), #19 (StaticPool — one-liner, bundle with any executor change), #23.2/.3 (generated_at bypass, meter spike ceiling — bundle with change 2), #23.4 (preflight wall-clock — only if replay is wanted).

Conflict notes: changes 1 and 4 touch `kepler.py`/`adapter.py` — sequence, don't parallelize. Change 2's monitor adoption depends on this change's monitors being deployed and green.

### Exit statement (task 8.3)

**Claim**: all catalogued failure modes (FM1–FM8) are defended by verified evidence, passing tests, or runtime monitors — except where explicitly listed as open findings above. "100 % bug free" is not claimed; 23 findings say otherwise, none of them S1.

- **Defended and verified**: FM1 (fallback + freshness safeguard + idempotent fail-safe command paths; fault-injection tested), FM4 (self-healing HA reconnects, ≥99.7 % tick success, `command_success` monitor), FM5 (near-perfect continuity/SoC/dual-writer evidence + recorder validated against HA + `slot_continuity`/`energy_balance`/`data_quality` monitors), FM6 (no drift; `forecast_sanity` monitor), FM7 (atomic verified config writes), FM2 (objective verified with worked example; #16 open but trivial in magnitude).
- **Partially defended, open findings**: FM3 — water comfort constraints are partly fictional (#12/#14/#15) and excess-PV water heating has never worked (#5); FM8 — numbers are truthful (#21.3) but go silently stale after socket loss (#18).
- **Explicitly NOT covered**: FM3-EV — there is no real EV; the entire EV subsystem is unverified against hardware (#11). Frontend has no runtime monitor (FM8 is test/read-verified only). The fall-back DST day has never occurred in production (planner-level pre-verified in tests only, #23.1).
- **Monitors**: 7 invariants evaluated every 15 min, read-only, fail-open, thresholds derived from 8-month measured distributions (documented in `backend/monitors.py`), surfaced on the SystemAlert banner + `/api/system/monitors`. Alert channel per OQ1 default: **banner only** (push notification available via `backend/notify.py` if the operator opts in).
- **Soak criterion (OQ2, default)**: 14 consecutive days with all invariants green post-deploy. Start date = production deploy date of this change (pending operator, task 7.6/8.4).

### Operator review 2026-07-02/03 — decisions on all 26 findings (task 8.4, part 1)

Walked through every finding with the operator. Recorded status:

| # | Decision |
|---|----------|
| 1 | Drop `schedule_planned` table + model (hygiene batch) → ✅ hygiene-batch tasks 1.1-1.4 |
| 2 | Closed benign |
| 3 | **Populate** `error_message` with failure summary at log time (observability change) — ✅ **specced in `fix-observability-gaps`** (task grp 2) |
| 4 | Closed resolved |
| 5 | Closed resolved (site config: HA slider max was 80 °C, operator raised it in prod 2026-07-02) — #24 is the real finding |
| 6 | Closed resolved-and-guarded (see #26); next live test = 2026-10-25 fall-back |
| 7 | Closed benign |
| 8 | Leave Jan data as-is; **add flag-aware training** (observability change) — ✅ **specced in `fix-observability-gaps`** (task grp 5). **Correction 2026-07-05:** `slot_observations.quality_flags` has NO clean/exclude taxonomy — it only stores `{"source":"recorder"\|"backfill"}` (the clean/mask_battery/exclude values were the dead `data_quality_daily.status`, a different table). Operator chose scope **"Flag + filter + tag Jan"**: define an `"exclude": true` semantic in the quality_flags JSON, make training honor it, and a dry-run-default one-off script to tag the Jan 16–20 physically-impossible slots (annotation only; measurements untouched; operator runs it in prod). |
| 9 | Monitor adopted as the data-quality replacement; drop the dead table; **add monitor UI panel** (observability change) — ✅ **specced in `fix-observability-gaps`** (task grp 4). UI placement decided: **Settings→Debug** new "Monitors" sub-tab (advanced-only diagnostics home). Table drop via Alembic migration (down_rev = current head `8f2c4d6e9a10`). |
| 10 | Closed benign |
| 11 | Closed, superseded by #25 (multi-user product; other installs run real EVs; operator's mockup is deliberate) |
| 12/14/15 | **Reimplement gap comfort** using the Jan-23 linear-discomfort formulation (O(T), performance-safe — the sliding-window versions were killed for solve time, discomfort was lost in a same-day refactor, not by design). `max_hours_between_heating` becomes live as the **fixed gap ceiling / deadband**; `comfort_level` scales **only the penalty weight** (SEK per hour beyond the ceiling), NOT the ceiling itself — **Design A, ratified 2026-07-05** (see design note below). Delete the ignored penalty keys from config+UI. Anti-sawtooth (block-start penalty + hard `water_min_spacing_hours`) and anti-long-block (max_block_hours from comfort_level) mechanisms remain unchanged. — ✅ **specced in `fix-water-comfort-truthfulness`** (task grps 1–3, 5; capability `per-device-water-scheduling`). **Correction 2026-07-05:** a **4th** dead key was found during design — `water_heating.block_penalty_sek` is also never read (grep-verified, non-test source) — so **4** keys are removed, not 3: `reliability_penalty_sek`, `block_start_penalty_sek`, `spacing_penalty_sek`, `block_penalty_sek`. Also removes the dead `KeplerConfig.water_comfort_penalty_sek` field and the doubled `gap_violation_penalty` objective lines. |
| 13 | Closed benign |
| 16 | Fix (trivial): curtailment free at export price ≤ 0 — bundle with the water/solver change — ✅ **specced in `fix-water-comfort-truthfulness`** (task grp 4; new capability `curtailment-price-floor`) |
| 17 | Accepted (defense) |
| 18 | Fix: infinite websocket retry + refetch-on-reconnect + live/stale indicator (observability change) — ✅ **specced in `fix-observability-gaps`** (task grp 3) |
| 19 | Fix: per-thread connections instead of StaticPool (hygiene batch) → ✅ hygiene-batch tasks 2.1-2.2 (delta on `database-concurrency-safety`) |
| 20 | Fix: delete dead `inverter_ac_limit_kw`, consolidate duplicated `charge_efficiency` (hygiene batch) → ✅ hygiene-batch tasks 3.1-3.4 |
| 21 | Accepted (defense) |
| 22 | Accepted; matrix reflects the above closures |
| 23 | Fix `generated_at`-bypass + meter-spike ceiling (hygiene batch); preflight/replay item explicitly skipped → ✅ hygiene-batch tasks 4.1-4.2 (generated_at), 5.1-5.3 (meter ceiling), 7.1-7.2 (flip pins); #23.4 out of scope |
| 24 | Fix: push notification on first-failure-of-streak per action type, episode-deduped, honoring `notifications.on_error` (observability change, top priority) — ✅ **specced in `fix-observability-gaps`** (task grp 1; streak threshold = 3 consecutive ticks) |
| 25 | Fix: startup warning for enabled devices pointing at mock/test entities; operator keeps the mockup until a real EV arrives (hygiene batch) → ✅ hygiene-batch tasks 6.1-6.2 |
| 26 | Closed |

### Revised follow-up changes (supersedes the earlier grouping)

1. **`fix-observability-gaps`** (S2, first): #24 notify-on-failure-streak, #3 populate error_message, #18 dashboard reconnect/staleness, #9 monitor UI panel (Settings→Debug) + drop `data_quality_daily`, #8 flag-aware training (quality_flags exclude filter). ✅ **PROPOSED 2026-07-05** — full artifacts (proposal/design/specs/tasks) written and validated at `openspec/changes/fix-observability-gaps/`, ready for `/opsx:apply`.
2. **`fix-water-comfort-truthfulness`** (S2): #12/#14/#15 linear-discomfort gap penalty + config cleanup per the table above; include #16 curtailment tiebreak (same files). ✅ **PROPOSED 2026-07-05** — full artifacts (proposal/design/specs/tasks) written and validated at `openspec/changes/fix-water-comfort-truthfulness/`, ready for `/opsx:apply`. Capabilities: modified `per-device-water-scheduling` (gap penalty + comfort-level weight + truthful control surface), new `curtailment-price-floor` (#16). Tasks are atomic with exact file:line anchors.

   **Design note — gap comfort mechanism (ratified 2026-07-05, Design A):**
   - Reinstate the **linear discomfort counter** (formulation from commit `af214dc8`): a per-slot counter of hours-since-last-heating that resets to 0 whenever the heater runs. O(T), no sliding window — the version that was performance-safe.
   - **Deadband:** the counter is penalty-free up to `max_hours_between_heating` (e.g. 8 h). This makes the config key *live* for the first time (currently parsed into `water_heating_max_gap_hours`/`types.py:73` but never read by `kepler.py`; `gap_violation_penalty` hardcoded 0.0 at `kepler.py:557`).
   - **Penalty:** beyond the deadband, a soft cost accrues per hour of overshoot. Soft = never makes the MILP infeasible; the solver inserts a top-up heat unless the price saving genuinely outweighs the comfort cost.
   - **comfort_level scales ONLY the penalty weight, not the ceiling** (Design A). Add one column `water_gap_penalty_sek` to `COMFORT_MAP` (`adapter.py:277`), scaling across levels 1→5 in the same spirit as the reliability column (L1 lenient — lets the gap stretch for good prices; L5 defends the ceiling hard). The ceiling stays exactly what the operator set in `max_hours_between_heating`. Design B (level also shortens the ceiling) was **rejected** — it would make the explicit dial partly cosmetic, the exact trap #14/#15 is climbing out of.
   - **Unchanged:** the floor/ceiling band = hard `water_min_spacing_hours` (≥5 h floor, anti-sawtooth) + this gap ceiling (≤~8 h). Block-start and max-block penalties still shape heating within the band. Daily minimum (`min_kwh_per_day`) unchanged.
   - **User-facing dials after this change:** `comfort_level`, `max_hours_between_heating`, `min_kwh_per_day`, `water_min_spacing_hours`, `power_kw`. Removed: the 3 silently-ignored penalty keys.
3. **`hygiene-batch`** (S4): #1 drop `schedule_planned`, #19 executor DB pool, #20 dead/duplicate config keys, #23 generated_at-bypass + meter-spike ceiling, #25 mock-entity warning. ✅ **PROPOSED 2026-07-05** — full artifacts (proposal/design/specs/tasks) written and validated at `openspec/changes/hygiene-batch/`, ready for `/opsx:apply`. Capabilities: new `stabilization-hygiene` (#1/#20/#23/#25), modified `database-concurrency-safety` (#19 per-thread pool). Tasks are atomic with exact file:line anchors and per-finding verification steps. Design decisions pinned: Alembic forward-migration drops the dead table; `charge_efficiency` single-sourced to `battery.charge_efficiency` behavior-preservingly (stays 0.92 here); meter-delta ceiling `recorder.max_meter_delta_kwh` default 50 kWh/slot (reject, don't clamp); missing `generated_at` → treated as stale (hold). Explicitly out of scope: #23.4 preflight-replay limitation.

### Still pending (the only open items)
1. **Task 7.6**: operator approves production deploy of the monitors → verify one green evaluation cycle on live.
2. **Task 8.4 remainder**: confirm soak window (default 14 consecutive green days from deploy; note 2026-10-25 DST day falls inside no matter what) and alert channel (banner now; push arrives with #24 fix).
