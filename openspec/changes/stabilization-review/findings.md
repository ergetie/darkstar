# Stabilization Review — Findings Ledger

> **Living document.** Append-only, numbered. Never renumber or delete an entry — retract by setting status to `wontfix` with a reason.
> **Rules live in `design.md`** (severity rubric D2, finding format D1, handoff discipline D5). This file holds the data.
> **Diagnose-only:** "Candidate remedies" are options to consider later, NOT commitments. No fix is implemented in this change.

## How to use this file (read before any phase session)
1. Read `design.md`, then this whole file.
2. Read your phase block in `tasks.md`.
3. Investigate **read-only** — trace behavior, don't just skim.
4. Append each new issue as the next `### Finding #N` using the format below.
5. Tick your phase checkbox in `tasks.md`, then stop.

**Finding format:**
```
### Finding #N — <short title>
- **Severity:** S1 | S2 | S3 | S4
- **Domain:** forecasting | solver-economics | executor | recorder-data | config-migration | infra-tests | architecture
- **Status:** open | confirmed | wontfix | → <child-change-name>
- **Location:** file:line (+ more)
- **Symptom:** <what is observably wrong>
- **Root-cause hypothesis:** <mechanism — mark CONFIRMED or UNVERIFIED>
- **Candidate remedies:** <options only — not a commitment>
- **Phase / session:** <where found>
```

**Severity quick-ref:** S1 wrong physical action/safety/money · S2 wrong decision input · S3 bounded correctness bug · S4 smell/debt/missing test.

---

## Baselines

- **Test suite (Phase 0, 2026-06-04):** `uv run python -m pytest` → **1051 passed, 0 failed** in ~60s. Clean local baseline; any future failure during the review is a regression introduced by the environment, not by this (read-only) change.

---

## Findings

### Finding #1 — EV exports surplus PV instead of charging from it
- **Severity:** S1
- **Domain:** solver-economics
- **Status:** confirmed → reframed (2026-06-06). The real defect is the **user-facing model**, not the solver math: charging is driven by hand-tuned willingness-to-pay "penalty levels" with an empty default, and there is no "reach X% by time T" requirement. Remedy = the **EV target-based charging redesign** folded into `price-forecasting-module-4/5` (penalty levels retired). See "Agreed Direction — EV charging (2026-06-06)" at the foot of this file. The Candidate-remedies line below is superseded by that section.
- **Location:** `planner/solver/kepler.py:489–500` (objective), `kepler.py:203–234` (incentive buckets), `kepler.py:642–651` (bucket reward term); config default `penalty_levels` in `config.default.yaml`; adapter `planner/solver/adapter.py:146–154`
- **Symptom:** When surplus PV is available, the solver exports it to grid rather than charging a connected, not-full EV. With `penalty_levels: []` the EV never charges; even with a bucket, it stops charging once the EV is no longer near-empty.
- **Root-cause hypothesis:** CONFIRMED. In the per-slot objective `slot_ev_cost = 0.0` — EV charging carries no intrinsic value. Charging from PV forfeits `slot_export_revenue = grid_export[t] * (export_price − export_threshold)`, which is positive per kWh. The only counterweight is the aggregate incentive-bucket reward (`ev_bucket_charged[d][i] * value_sek`), whose per-kWh value shrinks as the bucket cap shrinks with rising SoC (`kepler.py:219–226`). Once the bucket's effective per-kWh value drops below the export price, the solver exports. With no `penalty_levels` configured, reward is zero and it never charges. **Structurally: free PV → EV has no value modeled in the objective.**
- **Candidate remedies (for later session):** model an explicit value/reward for EV charging from surplus PV (e.g. credit equal to forgone export, or an opportunity-cost-aware term); and/or a hard/soft EV quota (`Sum(ev_charge·dt) >= kwh_needed`); and/or richer default `penalty_levels`. Decide in a solution session.
- **Worked numeric example (Phase 1, task 1.7).** Confirmed constants: `export_threshold_sek_per_kwh` default = `0.0` (`adapter.py:447`, `types.py:68`), so `effective_export_price = export_price` (`kepler.py:473–474`). Bucket reward per kWh = the configured `penalty_sek` (`adapter.py:147–151` maps `penalty_levels[].penalty_sek` → `IncentiveBucket.value_sek`), paid only up to `remaining_cap` = energy left to reach that bucket's `threshold_soc` (`kepler.py:217–229`); the aggregate objective subtracts `Σ ev_bucket_charged · value_sek` (`kepler.py:643–651`). Take 1 kWh of surplus PV in a slot at a representative SE4 summer-midday spot export price ≈ **0.30 SEK/kWh**:
  - **Case A — default config (`penalty_levels: []`, the UI default per `config.default.yaml:115`):** `num_buckets == 0` → the adapter builds no bucket, so the solver hits `continue` (`kepler.py:208`) **before** the `Σ ev_energy == Σ ev_bucket_charged` link (`kepler.py:232`). EV charging then has **zero value and zero requirement** in the objective. Charging the 1 kWh = +0 SEK; exporting it = +0.30 SEK. Solver exports every slot → **EV never charges from PV.** Matches the complaint exactly.
  - **Case B — weak bucket (`value_sek = 0.20`, below spot):** charge = +0.20 SEK vs export +0.30 SEK → net −0.10 SEK, still exports. Charging only ever wins when `value_sek > effective_export_price`.
  - **Case C — generous bucket (operator's `config.yaml`: one level `max_soc 100, penalty_sek 5`):** charge = +5 SEK ≫ 0.30 export → EV charges, but **only until `remaining_cap` is exhausted** (SoC reaches the bucket's `threshold_soc`); any surplus beyond that has no EV value and is exported. This is why charging is intermittent ("why not always charging"): the incentive is a fixed pot sized to the bucket, not an ongoing "self-consume into EV" preference. With a sub-100% threshold the car stops absorbing surplus well before full.
  - **Crux:** the EV's only pull on surplus PV is the configured bucket reward measured head-to-head against export revenue. Empty buckets (default) or `value_sek` ≤ spot ⇒ export wins regardless of whether the EV is plugged in and not full. No term intrinsically values self-consuming surplus into the EV.
- **Executor verification (Phase 1, task 1.7).** The executor adds **no independent PV-surplus gate** — it cannot mask or compensate this solver bug. `engine._control_ev_charger` (`executor/engine.py:1922–2036`) decides purely from the plan: `should_charge = slot.ev_charger_plans.get(charger_id, 0.0) > 0.1` (`:1938–1939`). The only autonomous behaviour is a 30-min safety timeout that **stops** charging (`:1951–1959`) — it never *starts* charging on its own. The "Excess PV" sink (`engine.py:1395–1412`) routes to a custom dump entity (e.g. water), driven by the plan's `custom_entity_active`, never to the EV. So whatever the solver decides about surplus→EV is transmitted verbatim to the hardware; the S1 lives entirely in the Kepler objective.
- **Phase / session:** Pre-seed (explore session, 2026-06-04); worked example + executor verification added Phase 1 (2026-06-04, task 1.7)

### Finding #2 — PV hybrid forecast overestimates ~2× for some users
- **Severity:** S2
- **Domain:** forecasting
- **Status:** resolved by pv-open-meteo-baseline (Open-Meteo baseline, physical ceiling, bounded residual nudge, personalization ramp, and last-good-fetch fallback shipped).
- **Location:** `ml/forward.py:308–360` — `final = physics + ml_residual`; the only clamps are night-zeroing (astro `334–343`, radiation `345–348`) + `max(0, …)` `351` + a 3-slot rolling smooth `355`. **No upper/magnitude clamp anywhere.**
- **Symptom:** For some users the hybrid estimates ~67 kWh/day where open-meteo's own solar forecast expects ~30 kWh — roughly 2× too high. Hits *some* users, not all.
- **Root-cause hypothesis:** CONFIRMED (code read, Phase 1). The hybrid has no defence against a bad daytime estimate. Whatever physics (#6) and the residual model (#7) produce in daylight is trusted verbatim. Nothing bounds the output to a physically plausible ceiling (e.g. `kWp · slot_hours · max_realistic_efficiency`, respecting the inverter AC limit). So any upstream blow-up reaches the planner unfiltered. **CORRECTION to the pre-seed hypothesis:** `physics_forecast_kwh` *is* a model feature (`train.py:443–444`, `forward.py:311–316`), so the naive "residual can't rescale across array sizes" claim is **retracted** — the real transfer problem is under-fit cold-start models (#7), not a missing feature.
- **Candidate remedies (options only — hybrid stays the driver, nothing removed):** add a **magnitude sanity clamp** on final PV (clamp to a physical ceiling, or to `physics × k`, or clamp the residual); add a **disable toggle** mirroring "Enable Price Forecasting" (physics-only fallback). *Architecture decision deferred — see Open Questions.*
- **Phase / session:** Phase 1 (2026-06-04), updated from pre-seed

### Finding #3 — CI runs only the API test subset; no type-check gate
- **Severity:** S4
- **Domain:** infra-tests
- **Status:** confirmed
- **Location:** `.github/workflows/ci.yml` (`test-api` runs only `tests/api/test_api_routes.py`); `pyright` configured strict in `pyproject.toml` but only enforced locally via `.pre-commit-config.yaml`, not in CI
- **Symptom:** **1051 tests pass locally** (Phase 0 baseline) but CI gates the build on the API subset only (`tests/api/test_api_routes.py`); planner/executor/ML tests (~69 files) can regress silently. Pyright strict isn't a merge gate.
- **Root-cause hypothesis:** CONFIRMED by reading the workflow and pyproject. Incomplete CI coverage; type-check enforcement is local-only.
- **Candidate remedies (for later session):** expand CI to run all suites + pyright as a merge gate (likely a `harden-ci-and-tests` child change). Note: frontend (~2 tests for ~100 components) is out of this review's scope but worth recording as a separate follow-up.
- **Phase / session:** Pre-seed (explore session, 2026-06-04)

---

### Finding #4 — Three half-built feature changes paused, overlapping anchor-bug code
- **Severity:** S4
- **Domain:** architecture
- **Status:** confirmed
- **Location:** `openspec/changes/price-forecasting-module-3/`, `-module-4/`, `-module-5/` (0/38, 0/11, 0/25 tasks done)
- **Symptom:** Three in-progress OpenSpec changes have zero tasks completed and target the same code as our anchor bugs: M3 = S-Index price-awareness (`planner/strategy/s_index.py`, `planner/pipeline.py`); M4 = multi-day EV deferral (`MultiDayPlanner`, EV Kepler quota, `per-device-ev-scheduling`); M5 = EV dashboard card + HA `input_datetime` deadline sync. All gated behind a `price_forecast.enabled` core ("Module 1").
- **Root-cause hypothesis:** CONFIRMED (read the three proposals). These are paused feature work, not bugs — but they are a future bug/merge surface that intersects Finding #1 (EV economics) and the S-Index. Recorded so later solution sessions don't re-derive EV/S-Index logic that a half-merged module already touches.
- **Candidate remedies:** keep paused for the duration of the freeze; when EV/S-Index fixes are scoped, explicitly check for conflicts with M3/M4. Do not resume until stabilization completes.
- **Phase / session:** Phase 0 (2026-06-04)

### Finding #5 — `backend/` core infrastructure is the largest test blind spot in scope
- **Severity:** S4
- **Domain:** infra-tests
- **Status:** confirmed
- **Location:** untested modules incl. `backend/ha_socket.py` (~855 lines), `backend/services/planner_service.py`, `backend/services/recorder_service.py`, `backend/events.py`, `backend/notify.py`, `backend/core/websockets.py`, `backend/core/secrets.py`, `backend/battery_cost.py`, `backend/strategy/analyst.py`, `backend/strategy/voice.py`
- **Symptom:** planner/ml/executor are test-dense (29/23/17 test files), but `backend/` core infra (54 src files, 9 backend-specific test files) has ~22 modules with no dedicated tests — including the HA WebSocket client and the async service wrappers that bridge planner→executor.
- **Root-cause hypothesis:** CONFIRMED by file inventory. Historical: infra/glue code was added without unit isolation. These modules are prime hiding spots for runtime (not logic) bugs and should get extra scrutiny in Phase 2b (recorder/data) and Phase 3 (async/threading).
- **Candidate remedies:** prioritize characterization tests for `ha_socket.py` and the service wrappers in a `harden-ci-and-tests` child change; flag any concrete bug found during 2b/3 as its own finding.
- **Phase / session:** Phase 0 (2026-06-04)

### Finding #6 — Aurora baseline does its OWN GHI→tilt transposition instead of using open-meteo's GTI
- **Severity:** S2 (suspected; magnitude unconfirmed — see verification below)
- **Domain:** forecasting
- **Status:** resolved by pv-open-meteo-baseline (**CONFIRMED BY DATA 2026-06-04** — see Data Confirmation section below; home-grown physics over-produced ~2.5× and is no longer the baseline/fallback).
- **Location:** Path A (Aurora): `ml/weather.py:288–393` fetches **`shortwave_radiation` (GHI), hourly**; `ml/weather.py:97–148` (`_calculate_poa_irradiance`) does Darkstar's **own** GHI→tilt transposition (isotropic, fixed diffuse fraction 0.2/0.4); `ml/weather.py:230` `pv_kw=(poa/1000)·kwp·0.85`. Path B (library): `.venv/.../open_meteo_solar_forecast/open_meteo_solar_forecast.py:225–252,366–383,511–516` requests **`global_tilted_irradiance` (GTI, 15-min)** from open-meteo and applies a temp-derate + AC-clip PV model.
- **Symptom:** For *some* users the Aurora forecast reads ~2× the open-meteo library forecast. NOT universal — operator's own config has MAE 0.12 kWh (transposition works fine for that geometry).
- **Root-cause hypothesis (UNVERIFIED):** The two paths differ in (1) **who transposes to the panel plane** — Darkstar does it itself with a crude isotropic/fixed-diffuse model vs open-meteo returning GTI server-side; (2) **no temperature derating** in Path A; (3) efficiency 0.85 vs 1.0; (4) hourly vs 15-min resolution. A crude transposition is accurate for moderate geometries but can diverge at steep tilt / E-W / low winter sun — which would explain "some users." **This is a hypothesis to be confirmed by the comparison script, NOT a confirmed bug.** Earlier "systematically over-predicts / broken pipeline" framing is **retracted** — the operator's low MAE refutes a universal defect.
- **Verification method:** `scripts/compare_pv_paths.py` — runs Path A vs Path B (no ML) for a given config, prints daily kWh + A/B ratio. Run on a good config (expect A≈B) and an affected config (expect A≫B). Result pending.
- **Candidate remedies (options only, IF confirmed):** fetch `global_tilted_irradiance` per array from open-meteo instead of self-transposing (tradeoff: one API call per array vs one GHI call total; both support history via `past_days`); or add temp derating to Path A. *Decision deferred — Open Questions.*
- **Phase / session:** Phase 1 (2026-06-04)

> **Correction (Phase 1):** the path selector is `forecasting.active_forecast_version` (`"aurora"` = physics+ML hybrid, default `"baseline_7_day_avg"`), NOT an "ML on/off toggle" — earlier wording was wrong. `_get_forecast_data_aurora` reads the hybrid from the learning DB; `_get_forecast_data_async` uses the open-meteo library live (`backend/core/forecasts.py:31–37`).

### Finding #7 — Cold-start: seed model replaced by an under-fit local model after ~1 day
- **Severity:** S2
- **Domain:** forecasting
- **Status:** resolved by pv-open-meteo-baseline (confirmed threshold by code read; addressed by Open-Meteo cold-start baseline, gradual data-volume ramp, and bounded nudge)
- **Location:** `ml/train.py:228` + `:266` (`min_samples=100`), `ml/train.py:471–479` (quantile PV residual models p10/p50/p90), `ml/training_orchestrator.py:128/204` (automatic training at `min_samples=100`); seed/runtime model swap in `ml/bootstrap.py`
- **Symptom:** New/under-trained homes get a wrong-magnitude PV forecast that the seed model didn't have, with no clamp to catch it.
- **Root-cause hypothesis:** CONFIRMED mechanism. With 15-min slots, ~100 daytime samples ≈ **one day** of data triggers automatic local training. A LightGBM quantile model fit on ~1 day of PV residuals is severely under-fit and can emit large, unstable residuals on unseen feature combinations; LightGBM also cannot extrapolate beyond the physics range seen in that tiny training set. Combined with #2 (no magnitude clamp), this is the most plausible path to a sudden 2× for *some* users — precisely those a few days into running it.
- **Candidate remedies (options only):** raise `min_samples` to a meaningful window (e.g. ≥N weeks of daytime slots); require a minimum data span (not just row count); keep physics-only (or seed) until the local model passes a validation gate; blend seed↔local by data volume. *Decision deferred — Open Questions.*
- **Phase / session:** Phase 1 (2026-06-04)

<!-- New findings appended below this line by each phase session. -->

### Finding #8 — EV charge current derived from worst-case voltage, not nominal
- **Severity:** S3
- **Domain:** executor
- **Status:** open
- **Location:** `executor/controller.py:320` (`raw_current = (slot.charge_kw * 1000) / self.config.min_voltage_v`); config fields `executor/config.py:187–188` (`nominal_voltage_v=48.0`, `min_voltage_v=46.0`)
- **Symptom:** When the charger is controlled in Amps (the default mode), Darkstar converts the planned kW to an Ampere setpoint using the *minimum* battery voltage instead of the *nominal* voltage. Lower voltage in the denominator yields a higher current, so it commands ~4% more current (48/46) than the plan intends — i.e. slightly more power than planned.
- **Root-cause hypothesis:** CONFIRMED (code read). `nominal_voltage_v` exists in config but is never used in the kW→A conversion; `min_voltage_v` (a worst-case floor) is used instead. Direction is "overshoot," not conservative undershoot. May be deliberate (ensure target reached) or an oversight — hence not yet a definite bug.
- **Candidate remedies:** use `nominal_voltage_v` for the kW→A conversion (keep `min_voltage_v` only for safety limits); or document why worst-case voltage is intended here.
- **Phase / session:** Phase 2a (2026-06-06)

### Finding #9 — Baseline forecast fills `temp_c` with load values when the temperature column is missing
- **Severity:** S3
- **Domain:** forecasting
- **Status:** open
- **Location:** `ml/evaluate.py:106` (`temp_c=("temp_c", "mean") if "temp_c" in history.columns else ("load_kwh", "mean")`)
- **Symptom:** In the `baseline_7_day_avg` forecast path, if history has no `temp_c` column the aggregation silently substitutes the mean of `load_kwh` into the `temp_c` field — so the baseline forecast carries load values disguised as temperatures.
- **Root-cause hypothesis:** CONFIRMED (code read). A copy-paste fallback aggregation key; the intent was presumably a neutral default (NaN/0), not "reuse load_kwh." Bounded: only the baseline forecast version, only when `temp_c` is absent.
- **Candidate remedies:** drop `temp_c` from the aggregation when absent, or fill with `NaN`/a sane default instead of `load_kwh`.
- **Phase / session:** Phase 2a (2026-06-06)

### Finding #10 — ML input fetches swallow failures and return empty/default silently
- **Severity:** S4
- **Domain:** forecasting
- **Status:** open
- **Location:** `ml/api.py:32–36` (config load → `except Exception: return {}`); `ml/context_features.py:61–66` and `ml/context_features.py:144–149` (HA history fetch → `except Exception: return pd.Series(...)`)
- **Symptom:** A failed `config.yaml` read returns an empty config (silently falling back to defaults), and failed Home-Assistant history fetches for context features (e.g. presence/alarm) return an empty series — both with no log line. The ML forecast then runs on missing inputs without any signal that data was lost.
- **Root-cause hypothesis:** CONFIRMED (code read). Broad `except Exception` with a silent default; no `logger.warning`. Degrades forecast quality invisibly rather than surfacing the failure.
- **Candidate remedies:** log a warning on each fallback; narrow the except to the expected error types; consider a health/alert signal when context features are unavailable.
- **Phase / session:** Phase 2a (2026-06-06)

### Finding #11 — `print()` used instead of the logger for warnings in non-UI code
- **Severity:** S4
- **Domain:** infra-tests
- **Status:** open
- **Location:** `planner/inputs/weather.py:62` (`print("Warning: Failed to fetch temperature forecast: …")`); `ml/evaluate.py:100` (`print("Warning: No history available …")`)
- **Symptom:** Operational warnings are emitted via `print()` rather than the structured logger, so they bypass log levels/handlers and won't appear in normal log capture or alerting.
- **Root-cause hypothesis:** CONFIRMED (code read). Leftover debug-style prints in library/service code.
- **Candidate remedies:** replace with `logger.warning(...)`; add a lint/CI check forbidding `print` outside scripts/CLI.
- **Phase / session:** Phase 2a (2026-06-06)

### Finding #12 — Simulation SoC projection counts only grid-sourced battery charge, omitting PV charge
- **Severity:** S4 (downgraded from S3 — display/dead-path only, see verification)
- **Domain:** solver-economics
- **Status:** confirmed → display-only (verified Phase 2b, 2026-06-06)
- **Location:** `planner/solver/adapter.py:555` (`"charge_kw": min(s.charge_kwh, s.grid_import_kwh) / duration_h`); consumer `planner/simulation.py:51` (`charge_kw = float(row.get("charge_kw", 0.0))` → drives projected SoC at `simulation.py:55–58`)
- **Symptom:** The `charge_kw` field written by the adapter is the *grid-sourced* charge only (`min(total charge, grid import)`), not total battery charge. `simulation.py` reads `charge_kw` to project battery SoC, so any battery charging that came from surplus PV is dropped from the simulated SoC curve — the projection would under-state SoC whenever the battery charges from PV.
- **Root-cause hypothesis:** CONFIRMED (Phase 2b trace, 2026-06-06) — **but NOT decision-affecting; display/dead-path only.** `planner/simulation.py:simulate_schedule` is called from exactly ONE place: `backend/api/routers/schedule.py:540` (the `POST /api/simulate` diagnostic endpoint). The **live** plan does not use it: `planner/pipeline.py:784` builds the schedule via `kepler_result_to_dataframe`, whose `projected_soc_percent` comes from Kepler's true SoC state variable `s.soc_kwh` (`adapter.py:556-557`, `kepler.py:708`) — which already includes PV charge through the energy-balance constraints. The executor likewise reads `battery_charge_kw` (full charge), not the grid-only `charge_kw`. So the grid-only `charge_kw` feeds only (a) the `/api/simulate` endpoint and (b) a human-readable reason label — neither of which drives planning or the inverter. Blast radius: the `/api/simulate` SoC curve under-states SoC; nothing else. Latent footgun if `simulate_schedule` is ever wired into the live path.
- **Candidate remedies:** have `simulation.py` consume `battery_charge_kw` (total) rather than the grid-only `charge_kw`; or rename the grid-only field to avoid the collision. Confirm consumer first (Phase 2b candidate).
- **Phase / session:** Phase 2a (2026-06-06)

### Finding #13 — Real-time error/status WebSocket push is swallowed silently
- **Severity:** S4
- **Domain:** executor
- **Status:** open
- **Location:** `executor/engine.py:1439–1444` and `executor/engine.py:1527–1532` (`ws_manager.emit_sync(...)` wrapped in `except Exception: pass`)
- **Symptom:** If the WebSocket manager raises, the executor's real-time error/status broadcast to the UI is dropped with no log. The underlying error data is still appended to `recent_errors` first (so it is persisted), but the live push to clients fails invisibly.
- **Root-cause hypothesis:** CONFIRMED (code read). Intentional "best-effort" broadcast, but the blanket silent pass hides genuine WS faults. Low blast radius because the data is persisted before the emit.
- **Candidate remedies:** log at debug/warning on emit failure; narrow the except.
- **Phase / session:** Phase 2a (2026-06-06)

### Finding #14 — Dead / no-op code cluster (smell)
- **Severity:** S4
- **Domain:** architecture
- **Status:** open
- **Location:** `planner/simulation.py:30–31` (two `float(battery_config.get(...))` results discarded — `min_soc_percent`/`max_soc_percent` parsed then thrown away); `planner/output/soc_target.py:73` (`float(battery_config.get("capacity_kwh", 34.2))` result discarded); `executor/actions.py:787` (`if entity is None:` block is unreachable — the `_is_entity_configured` guard at `:776` already rejects None); `backend/ha_socket.py:687` (redundant trailing `pass` inside an `except` that already records the error)
- **Symptom:** Several parsed-then-discarded values and an unreachable branch. No functional impact, but the discarded `min_soc_percent`/`max_soc_percent` in `simulation.py` suggests the simulator *intended* to clamp to the configured SoC band and silently does not (it clamps only to `[0, capacity]` at `:62`).
- **Root-cause hypothesis:** CONFIRMED (code read). Refactoring residue. The `simulation.py` case is the one worth a second look — the parsed min/max SoC look like a dropped clamp, not just dead code.
- **Candidate remedies:** remove the dead lines; for `simulation.py`, decide whether the SoC-band clamp was meant to be applied (then apply it) or is genuinely not wanted (then delete the reads).
- **Phase / session:** Phase 2a (2026-06-06)

---

<!-- Phase 2b findings (#15–#33) appended below — deep behavior traces. -->

### Finding #15 — Recency sample-weights can misalign or crash training when an observation has an un-parseable timestamp
- **Severity:** S3
- **Domain:** forecasting
- **Status:** open
- **Location:** `ml/train.py:103` (`return weights.values` — a bare positional array), `ml/train.py:228` (`dropna(subset=["slot_start"])` gaps the index), `ml/train.py:418` (`load_weights = sample_weights[load_df.index]`), `ml/train.py:475` (`pv_weights = sample_weights[pv_df.index]`)
- **Symptom:** The exponential recency weights get attached to the wrong training rows, or training aborts with `IndexError`, whenever the `slot_observations` table contains a row whose `slot_start` fails to parse as ISO8601.
- **Root-cause hypothesis:** CONFIRMED (code read + empirical test). `_compute_sample_weights` returns `.values` — a positional numpy array ordered 0..N-1. But it is indexed with `load_df.index` / `pv_df.index`, which are the *original pandas labels*. NumPy treats those labels as positions. In normal operation the SQL query (`ORDER BY slot_start ASC`) gives a clean contiguous `RangeIndex`, so label == position and there is no bug. But `dropna(subset=["slot_start"])` at line 228 (triggered by `errors="coerce"` turning a bad timestamp into `NaT`) **gaps** the index (e.g. `[0,2,3]`), and the subsequent left-merges preserve that gapped index (verified empirically). Indexing a length-N array with a label ≥ N raises `IndexError`; with gapped labels < N it silently picks the wrong weights. So a single malformed timestamp row either crashes the nightly training or corrupts recency weighting.
- **Candidate remedies:** `reset_index(drop=True)` after the dropna/sort (or have `_compute_sample_weights` return a Series and use `.loc`/`.reindex` alignment instead of positional `.values`).
- **Phase / session:** Phase 2b, task 3.1 (2026-06-06)

### Finding #16 — Train vs inference feature-count asymmetry when weather is unavailable during training
- **Severity:** S3
- **Domain:** forecasting
- **Status:** open
- **Location:** `ml/train.py:353-354` (only `temp_c` added when `weather_df` empty) + `ml/train.py:405-407` (optional features added *conditionally*) vs `ml/forward.py:232-235` + `267-279` (inference always forces all 3 weather columns and a fixed 11-feature list)
- **Symptom:** A model trained during an Open-Meteo outage learns on 9 features (no `cloud_cover_pct` / `shortwave_radiation_w_m2`), but every forecast feeds it an 11-column matrix. The next forecast then either raises a LightGBM feature-mismatch error or mis-maps columns.
- **Root-cause hypothesis:** CONFIRMED (code read). Inference was deliberately hardened to always create the 3 weather columns (comment at `forward.py:231` "to match trained model feature count"), but the training side was *not* made symmetric — when `weather_df` is empty it adds only `temp_c`, so the other two columns never enter `feature_cols`. Conditional: only bites when a model is (re)trained while weather fetch is failing. No feature-name validation at model load (`_load_models`) to catch it.
- **Candidate remedies:** in training, force all 3 weather columns to exist (NaN-filled) exactly as inference does; and/or persist + validate feature names at load.
- **Phase / session:** Phase 2b, task 3.1 (2026-06-06)

### Finding #17 — No quantile-crossing guard: p10/p50/p90 are independent models and the bands can invert
- **Severity:** S3
- **Domain:** forecasting
- **Status:** open
- **Location:** load `ml/forward.py:300-309`; PV `ml/forward.py:415-504`; no sort before persistence (`forward.py:531-536`) or on read (`ml/api.py:156-161`); daily aggregation sums p10/p90 independently (`backend/core/forecasts.py:325-340`)
- **Symptom:** For a given slot the stored `pv_p10`/`load_p10` can exceed its `p50`/`p90`, yielding an inverted or zero-width uncertainty band that feeds the planner's risk logic.
- **Root-cause hypothesis:** CONFIRMED (code read). The three quantiles are *separately trained* LightGBM quantile regressors with no monotonic constraint, and each is predicted/clipped/smoothed independently with no `p10 ≤ p50 ≤ p90` reconciliation anywhere before storage or use. Quantile crossing is a well-known property of independently fit quantile models; nothing here prevents it.
- **Candidate remedies:** sort the three quantile outputs per slot (cheap monotonic repair) before storing; or train with a monotonic/joint formulation.
- **Phase / session:** Phase 2b, task 3.1 (2026-06-06)

### Finding #18 — `ml/evaluate.py` scores the PV model as if it were absolute, with the wrong feature set
- **Severity:** S3
- **Domain:** forecasting
- **Status:** open
- **Location:** `ml/evaluate.py:67-73` / `425-430` (loads only the legacy `pv_model.lgb` p50 alias), `ml/evaluate.py:135-201` (`_predict_with_boosters`, builds feature_cols without `physics_forecast_kwh`, treats output as absolute PV)
- **Symptom:** The MAE/quality numbers used to judge the Aurora PV model are meaningless — the evaluator feeds the residual model the wrong feature count and never adds the Open-Meteo baseline back, so it scores `actual − openmeteo` predictions as if they were absolute PV.
- **Root-cause hypothesis:** CONFIRMED (code read). Post `pv-open-meteo-baseline`, `pv_model.lgb` is a *residual* model trained with an extra `physics_forecast_kwh` feature (`train.py:455-489`). `evaluate.py` neither appends that feature nor adds the baseline back, and only evaluates p50. The "PV forecast quality" the user sees is therefore computed on an inconsistent basis.
- **Candidate remedies:** make `evaluate.py` mirror the residual pipeline (add `physics_forecast_kwh`, add baseline back, evaluate all quantiles) — diagnostic-only, but it misleads model-acceptance judgement.
- **Phase / session:** Phase 2b, task 3.1 (2026-06-06)

### Finding #19 — Stale/misleading comments and dead duplication in the Kepler terminal-SoC block (no behavior bug)
- **Severity:** S4 (documentation/debt — the behavior is intended; only the comments and a duplicate line are wrong)
- **Domain:** solver-economics
- **Status:** open
- **Location:** `planner/solver/kepler.py:484-487` (comment references a `terminal_value` term that no longer exists), `kepler.py:510-528` (the "BIDIRECTIONAL … penalize OVER target too" comment appears twice and `target_soc_kwh` is assigned twice, `512-514` and `518`)
- **Symptom:** The code reads as if it values end-of-horizon battery energy (a "terminal value") and penalizes overshooting the target — but neither exists. Only the UNDER-target (safety-floor) penalty is implemented (`522`/`525`); the OVER branch is a `pass`. A future reader would be misled into thinking a safeguard is present.
- **Root-cause hypothesis:** CONFIRMED (code read + grep). **Operator confirms this is intended behavior, not a bug:** the terminal-value term ("TVS") was deliberately scrapped earlier, and an over-target penalty is explicitly *unwanted* — punishing SoC above target would wrongly penalize the system for harvesting more PV than forecast. So the objective is correct; the comments and the duplicate `target_soc_kwh` assignment are just stale residue from the removed feature.
- **Candidate remedies:** delete/repair the misleading comments (`484-487`, the duplicated `510-511`/`516-517`) and remove the duplicate `target_soc_kwh` assignment. No objective/behavior change.
- **Phase / session:** Phase 2b, task 3.2 (2026-06-06); reframed after operator feedback (2026-06-06)

### Finding #20 — Reported plan cost uses raw export price while the objective uses the thresholded price
- **Severity:** S4
- **Domain:** solver-economics
- **Status:** open
- **Location:** `planner/solver/kepler.py:473-476` (objective uses `export_price − export_threshold`) vs `kepler.py:751-752` (reported per-slot `cost_sek` / `final_total_cost` recompute uses raw `s.export_price_sek_kwh`)
- **Symptom:** The `total_cost_sek` shown for a plan is not the quantity the optimizer actually minimized; the two differ by `export_threshold × grid_export` per slot.
- **Root-cause hypothesis:** CONFIRMED (code read). The export threshold is applied only inside the objective, not in the reporting recompute. Decisions are correct (the optimizer is internally consistent); only the displayed cost is off. NOT a double-subtraction (the opposite — the threshold is omitted from the report).
- **Candidate remedies:** use the same effective export price in the cost recompute, or document that the reported cost is gross-of-threshold.
- **Phase / session:** Phase 2b, task 3.2 (2026-06-06)

### Finding #21 — `force_export` quick action is dead (no UI button) AND broken (caps export at 0 W)
- **Severity:** S4 (downgraded from S2 — verified there is **no UI trigger**, so the broken behaviour is unreachable in practice)
- **Domain:** executor
- **Status:** open
- **Location:** `executor/controller.py:178-179` (`_apply_override` hardcodes `export_power_w=0.0`, `export_with_load_w=0.0`); backend trigger `executor/engine.py:1140-1141`, `:482`; **no frontend caller** — the only quick action wired in the UI is `force_charge` ("Top Up", `frontend/src/components/CommandBar.tsx:154`); `force_export` is reachable only via raw API.
- **Symptom:** Two issues that compound to "nothing." (1) The `force_export` quick action is not exposed by any button in the app — the operator confirmed they couldn't find it. (2) Even if invoked via API, it puts the inverter into Export mode but writes the grid-export power limit to **0 W**, so the battery exports nothing.
- **Root-cause hypothesis:** CONFIRMED (code read + frontend grep). The override path hardcodes `export_power_w=0.0` (the normal `_follow_plan` path correctly uses `slot.export_kw * 1000`, `controller.py:226`), and no UI surfaces the action. So it is dead, broken code.
- **Candidate remedies:** **remove the `force_export` quick-action path** (override type, controller branch, engine handler) since it's unused and broken. (Only fix the 0 W bug if a force-export button is ever intentionally added.)
- **Phase / session:** Phase 2b, task 3.3 (2026-06-06); reframed after operator feedback + UI verification (2026-06-06)

### Finding #22 — "Manual override" HA entity still writes idle-mode settings to the inverter (contradicts its own "will not change settings")
- **Severity:** S2 (only for users who configure the entity — see scope)
- **Domain:** executor
- **Status:** open
- **Scope / what this is:** NOT the pause button. "Manual override" here is an **optional Home-Assistant entity** the user can name in `executor.manual_override_entity` (`executor/config.py:212`); when that entity reads `"on"`, `state.manual_override_active` is set (`engine.py:1723-1767`). It's meant as an external "hands off, I'm controlling the inverter myself" switch. If no such entity is configured (the common case), the read is skipped and this bug never triggers. The **pause button is a separate mechanism and works correctly** — `pause()` (`engine.py:539`) short-circuits the whole tick (`engine.py:1045-1056`), so during pause nothing is written.
- **Location:** `executor/override.py:136-143` (MANUAL_OVERRIDE returns `override_needed=True`, `actions={}`, reason "executor will not change settings"); `executor/controller.py:119-189` (`_apply_override` leaves `mode_intent="idle"`); executed unconditionally at `executor/engine.py:1415`. No early-return guard for manual override (unlike pause).
- **Symptom:** While the configured `manual_override_entity` is `on`, the executor still pushes a full **idle** mode profile to the inverter every tick (Deye: `work_mode→"Zero Export To CT"`, `grid_charging→off`, `max_discharge_current→15`, `max_charge_current`, `soc_target`), overwriting the user's manual settings — the opposite of the feature's promise.
- **Root-cause hypothesis:** CONFIRMED (code read). MANUAL_OVERRIDE is treated like any other override: `_apply_override` runs, `mode_intent` stays at its `"idle"` default, and `execute()` writes the idle mode's actions. No path skips hardware writes for MANUAL_OVERRIDE. Mitigated only by per-entity write thresholds.
- **Candidate remedies:** for MANUAL_OVERRIDE, skip the inverter writes entirely (early-return like pause). **Open question for the operator:** is the `manual_override_entity` feature actually wanted/used? If not, consider removing it rather than fixing it.
- **Phase / session:** Phase 2b, task 3.3 (2026-06-06); scope clarified after operator feedback (2026-06-06)

### Finding #23 — EV charger control ignores manual override and the `force_stop` quick action
- **Severity:** S3
- **Domain:** executor
- **Status:** open
- **Location:** `executor/engine.py:1370-1371` (`_control_ev_charger` is called gated only on `_has_ev_charger`, never on override/quick-action); function body `engine.py:1922-2036` reads only `original_slot.ev_charger_plans`; `force_stop` quick action sets only `soc_target`/`water_temp` (`engine.py:1142-1146`)
- **Symptom:** While manual override is `on`, or while a `force_stop` quick action is active, a plan-scheduled EV charge keeps running — the user cannot stop the car charging via manual control or the stop button. (Pause *does* stop it, because pause skips the whole tick.)
- **Root-cause hypothesis:** CONFIRMED (code read). EV switch control is a separate code path from the battery `decision` and never inspects `override` or `quick_action`. The battery is handled correctly during `force_stop` (soc_target=10), but the EV switch is missed. Bounded to EV-equipped homes with an active EV plan.
- **Candidate remedies:** gate `_control_ev_charger` on override/quick-action state (force charger off for `force_stop` and MANUAL_OVERRIDE, or skip EV control under manual override).
- **Phase / session:** Phase 2b, task 3.3 (2026-06-06)

### Finding #24 — Low-SoC water-boost cancellation notification is never sent (missing `await`)
- **Severity:** S3
- **Domain:** executor
- **Status:** open
- **Location:** `executor/engine.py:1179-1182` (`self.dispatcher._send_notification(...)` called without `await`); the function is `async` (`executor/actions.py:1215`), and is correctly awaited elsewhere (`engine.py:1237`, `actions.py:1213`)
- **Symptom:** When a water boost is cancelled because SoC dropped below `min_soc + 10%`, the intended push notification is never delivered, and Python emits a "coroutine was never awaited" runtime warning.
- **Root-cause hypothesis:** CONFIRMED (code read). The coroutine object is created and discarded unexecuted. Low blast radius (user simply isn't told their boost was cancelled).
- **Candidate remedies:** `await` the call (or wrap in `create_task`), matching the other notification call sites.
- **Phase / session:** Phase 2b, task 3.3 (2026-06-06)

### Finding #25 — Recorder labels the wrong slot and estimates EV/water from a boundary snapshot instead of integrating the finished slot
- **Severity:** S2
- **Domain:** recorder-data
- **Status:** open
- **Location:** `backend/recorder.py:209-214` (floors `now` to the *current* quarter and labels the row with it, despite the "just-finished slot" comment); `recorder.py:464`/`486` + `backend/core/ha_client.py:174-237` (EV/water energy = mean of HA samples in `[slot_start, slot_end]` × 0.25 h); loop order `backend/services/recorder_service.py:155` then `160` (record, then sleep-to-next-boundary)
- **Symptom:** In steady state the recorder wakes right *after* a 15-min boundary and records the slot that just **began**. Two compounding errors result: (1) the cumulative-delta fields (load/PV/grid) measure the slot that just **finished** but are stamped with the *next* slot's `slot_start` — a one-slot (+15 min) time-shift; (2) EV/water energy is not the slot's true energy — HA returns the device's state *at the window start* (HA backfills the at-start state), so the value is effectively **"power at the boundary instant × 15 min"**, i.e. a snapshot assumed constant for the whole slot. When EV/water power fluctuates within/across slots (the normal case), that estimate is wrong and is subtracted from a *different* slot's load than the one it came from.
- **Root-cause hypothesis:** CONFIRMED (code read; HA `include_start_time_state` behaviour). **Correction to the earlier draft:** EV/water is NOT systematically ~0 — it's a boundary snapshot, so it *is* subtracted, but the magnitude is assumed-constant and the slot label is off by one. So base-load disaggregation is **misaligned and noisy**, not absent: a device that switches near a boundary is mis-subtracted (base load over- or under-stated, occasionally clamped to 0). This feeds the load ML training set bad, time-shifted targets.
- **Candidate remedies (proper fix, not a patch):** record the slot that just **finished** (`slot_start = floor(now) − 15 min`) and **integrate** EV/water over that fully-elapsed window (true `Σ powerᵢ·Δtᵢ`, see #28), so every field describes the same, completed slot using real data — never an assumed-constant snapshot. The whole row (load/PV/grid and EV/water) must align to one slot.
- **Phase / session:** Phase 2b, task 3.4 (2026-06-06); mechanism corrected after operator feedback + HA-API verification (2026-06-06)

### Finding #26 — Base-load disaggregation subtracts a misaligned EV/water snapshot (consequence of #25)
- **Severity:** S2
- **Domain:** recorder-data
- **Status:** open
- **Location:** `backend/recorder.py:500-511` (`base_load_kwh = load_kwh − ev_charging_kwh − water_kwh`, applied when `used_cumulative_load or not disaggregator`)
- **Symptom:** On the cumulative-load-sensor path (and the no-disaggregator power path), the EV/water values subtracted to isolate base load are the boundary-snapshot estimates from #25, taken from the *wrong* slot. So `base_load = total − snapshot_EV − snapshot_water` is correct only when EV/water power is steady across the boundary; whenever it fluctuates, base load is over- or under-stated (and clamped to 0 if it goes negative). The forecaster's "base_load = CLEAN" assumption is therefore violated by noisy, time-shifted subtraction.
- **Root-cause hypothesis:** CONFIRMED (code read). The live-power disaggregator path (power snapshot, disaggregator present) subtracts live controllable power and is better-aligned; but the cumulative path depends entirely on the misaligned #25 estimate. Disaggregation is unreliable rather than absent.
- **Candidate remedies:** fix #25 (record the finished slot, integrate EV/water over it) so the subtraction uses real same-slot energy; ideally route *all* paths through one integrated, slot-aligned disaggregation so base load is consistent regardless of sensor setup.
- **Phase / session:** Phase 2b, task 3.4 (2026-06-06); mechanism corrected after operator feedback (2026-06-06)

### Finding #27 — Backfill does not disaggregate at all: it writes TOTAL load into the same column the forecaster reads as base load
- **Severity:** S2
- **Domain:** recorder-data
- **Status:** open
- **Location:** backfill `backend/learning/backfill.py:139-145` (mapping has only import/export/pv/load/soc — **no EV/water sensors**) → `backend/learning/engine.py:238-244` (writes the raw cumulative `load` delta straight into `load_kwh`); gap logic `backfill.py:105-123` (fills from the last observation forward, so it only fills genuine gaps — it does **not** rewrite existing history); live path `backend/recorder.py:500-511`
- **Symptom:** Every slot written by backfill stores `load_kwh` = full house consumption (EV + water **never subtracted**, because backfill never even fetches those sensors), whereas live rows subtract a (noisy, per #25) EV/water estimate. So the single `load_kwh` training column means *total* for gap-filled rows and *base* for live rows — and the forecaster treats them identically. This is the clearest "DB-is-SSOT" violation: the authoritative column has source-dependent meaning.
- **Root-cause hypothesis:** CONFIRMED (code read). Disaggregation lives only in the live recorder; the backfill path has no EV/water mapping and no subtraction. (The earlier note that live rows "may also end up ≈total" is retracted — live rows *do* subtract a snapshot per #25; the inconsistency between backfill-total and live-base is the real problem.)
- **Candidate remedies:** **disaggregate EVERYWHERE** — backfill must fetch EV/water history for each gap slot and subtract it, exactly like the (fixed) live path. Bonus: backfill's window is fully in the past, so the integration (see #28) is *accurate* there. Do not leave any writer storing un-disaggregated total in `load_kwh`.
- **Phase / session:** Phase 2b, task 3.4 (2026-06-06); emphasis sharpened after operator feedback (2026-06-06)

### Finding #28 — HA history energy uses an unweighted sample mean instead of time-weighted integration
- **Severity:** S3
- **Domain:** recorder-data
- **Status:** open
- **Location:** `backend/core/ha_client.py:235-237` (`mean_kw = sum(kw_values)/len(kw_values)` then `× duration_hours`)
- **Symptom:** EV/water (and any power-history) energy is biased whenever the sensor logs at irregular intervals — which is the norm in Home Assistant (state-change logging). A brief high-power spike with many samples dominates; long steady periods with few samples are under-weighted.
- **Root-cause hypothesis:** CONFIRMED (code read). HA `/history/period` returns state-change events at non-uniform timestamps; correct energy is `Σ powerᵢ·Δtᵢ`, but the code averages the values ignoring how long each persisted. Magnitude is data-dependent. (Currently masked by #25 for the live path, but bites the gap-backfill path and any caller passing a real elapsed window.)
- **Candidate remedies:** integrate with per-sample durations (trapezoidal/step over `last_changed` timestamps) instead of a plain mean.
- **Phase / session:** Phase 2b, task 3.4 (2026-06-06)

### Finding #29 — Observation UPSERT only overwrites when the new value is > 0, so it cannot correct an over-count down or store a true zero
- **Severity:** S3
- **Domain:** recorder-data
- **Status:** open
- **Location:** `backend/learning/store.py:166-189` (`case((excluded.X > 0, excluded.X), else_=existing)` for import/export/pv/load/water/ev)
- **Symptom:** Once a slot has a positive energy value, a later corrected record carrying a smaller or zero true value is silently dropped; a genuinely-zero slot can never overwrite an earlier non-zero value. The DB is therefore "first positive write wins," not self-healing.
- **Root-cause hypothesis:** CONFIRMED (code read). Intentional anti-wipe guard (comment "REV F35: prevents backfill from wiping data"), but the side effect is that a wrongly-high value (e.g. from a spike or the #25 mislabel) cannot be repaired by re-recording, and legitimate zeros are unrepresentable.
- **Candidate remedies:** distinguish "no data" (skip) from "real zero" (write) via a presence flag, or make corrections explicit; reconsider the >0 gate now that spike-filtering exists upstream.
- **Phase / session:** Phase 2b, task 3.4 (2026-06-06)

### Finding #30 — Legacy `deferrable_loads` is deleted on migration with no conversion to ARC15 arrays → silent loss of all water/EV loads
- **Severity:** S1
- **Domain:** config-migration
- **Status:** wontfix (operator confirmed 2026-06-06: no users remain on the pre-ARC15 `deferrable_loads` layout, so this path is never hit in practice). Mechanism is real but moot; recorded for history.
- **Location:** `backend/config_migration.py:74` (in `DEPRECATED_KEYS`), `:761` (`remove_deprecated_keys` deletes it); no converter exists anywhere (the only mention of "deferrable" in the module is the deprecated-key entry); consumer `backend/loads/service.py:40-45`
- **Symptom:** A pre-ARC15 config that still defines loads under `deferrable_loads` (with no `water_heaters[]`/`ev_chargers[]`) loses **every** water-heater and EV-charger definition on the first startup migration — they are deleted and never re-created in the new arrays.
- **Root-cause hypothesis:** CONFIRMED (code read). Migration runs `_migrate_ev_charger_fields` / `_migrate_water_heater_fields` (which only copy scalar fields into arrays that must *already* exist) and then `remove_deprecated_keys` unconditionally `del`s `deferrable_loads`. No step reads the `deferrable_loads` list and builds the entity arrays. After deletion, `LoadService` sees empty arrays → falls back to `_initialize_from_deferrable_loads` → finds nothing → registers no loads. The comment at line 74 ("Replaced by water_heaters[]/ev_chargers[]") asserts a conversion the code does not perform.
- **Candidate remedies:** add a real `deferrable_loads → water_heaters[]/ev_chargers[]` migration step that runs *before* `remove_deprecated_keys`; until then, do not delete `deferrable_loads` if the new arrays are empty.
- **Phase / session:** Phase 2b, task 3.5 (2026-06-06)

### Finding #31 — UI "Save Configuration" writes config non-atomically with no backup, bypassing the atomic `_write_config` helper
- **Severity:** S2
- **Domain:** config-migration
- **Status:** open
- **Location:** `backend/api/routers/config.py:301-302` (plain `config_path.open("w")` + `dump` — truncate-in-place); contrast `backend/config_migration.py:879-927` (`_write_config`: timestamped backup → `.bak` → temp file → `os.replace` → bind-mount fallback → restore-on-failure)
- **Symptom:** A crash, container kill, or disk-full during the UI save leaves `config.yaml` truncated/empty, with no backup to recover from. The migration module already has a correct atomic writer one import away, but the most-used write path doesn't use it.
- **Root-cause hypothesis:** CONFIRMED (code read). The router opens the real file in `"w"` mode (immediate truncate) and dumps directly; no temp-then-rename, no backup. Severity reasoning: not autonomous and requires an ill-timed crash, but the SSOT config can be lost with no recovery point.
- **Candidate remedies:** route `save_config` through `_write_config` (or replicate its temp+rename+backup logic).
- **Phase / session:** Phase 2b, task 3.5 (2026-06-06)

### Finding #32 — Atomic-write bind-mount fallback uses a non-atomic `shutil.copy2`
- **Severity:** S3
- **Domain:** config-migration
- **Status:** open
- **Location:** `backend/config_migration.py:908-916` (on `EBUSY`/`EXDEV`/`ETXTBSY`, falls back to `shutil.copy2(temp_path, path)`)
- **Symptom:** On a Docker bind mount (where `os.replace` across devices fails), the "atomic" write degrades to a truncate-then-stream copy of the live `config.yaml`; a crash mid-copy yields a partial/truncated config — the exact failure the atomic rename was meant to prevent.
- **Root-cause hypothesis:** CONFIRMED (code read). Mitigated by the `.bak` created at `:894` and restore at `:920-922`, but the restore is itself a non-atomic copy and only runs on a Python exception (a hard process kill skips it). Lower severity than #31 because a backup exists.
- **Candidate remedies:** write the temp file *inside the bind-mounted directory* and `os.replace` within the same filesystem (avoids EXDEV), or fsync + rename within the mount.
- **Phase / session:** Phase 2b, task 3.5 (2026-06-06)

### Finding #33 — `config_version` is never set by migration; ARC15 code paths silently disable if the template merge is skipped
- **Severity:** S3
- **Domain:** config-migration
- **Status:** open
- **Location:** `backend/config_migration.py` (no write of `config_version` anywhere — only positional validation at `:523-528`); the value is injected only via the template merge from `config.default.yaml`; consumers gate on `>= 2`: `loads/service.py:33`, `api/routers/config.py:347`, `planner/solver/adapter.py:27-29`
- **Symptom:** If the template merge is skipped — default file missing (`:782-786`) or user config fails structure validation (`:740-744`) — `config_version` is never bumped to 2, so the ARC15 entity-centric arrays are silently ignored by the planner/executor/loads.
- **Root-cause hypothesis:** CONFIRMED (code read). No explicit "set config_version = 2" migration step exists; correctness depends entirely on the template merge succeeding. In the normal path the merge injects it, so this only bites the error/skip paths — hence conditional.
- **Candidate remedies:** set `config_version` explicitly in a migration step (independent of the template merge).
- **Phase / session:** Phase 2b, task 3.5 (2026-06-06)

### Finding #34 — Inverter AC limit only caps battery discharge, not PV-to-AC (load + export)
- **Severity:** S4
- **Domain:** solver-economics
- **Status:** open
- **Location:** `planner/solver/kepler.py:431-434` (`discharge[t] <= max(0.0, inverter_ac_kwh - s.pv_kwh)`)
- **Symptom:** In a slot where forecast PV exceeds the inverter's AC rating, the model still lets all of `s.pv_kwh` flow to AC load/export, while only battery discharge is throttled. So a plan can assume grid export above what the inverter can physically push out its AC side.
- **Root-cause hypothesis:** CONFIRMED mechanism (code read). The constraint correctly enforces `pv + discharge ≤ AC_limit` for the battery, but PV-to-AC (load + export) is not independently capped — when `s.pv_kwh > inverter_ac_kwh`, discharge is forced to 0 (fine) yet PV can still route unbounded to export/load. Real-world impact is **conditional and small**: only matters when per-slot PV exceeds the inverter AC rating, and depends on DC- vs AC-coupled topology; also the whole constraint is skipped when `max_inverter_ac_kw` is unset (default), in which case nothing is AC-capped. Hardware clips the real export anyway, so the effect is an over-optimistic export estimate in peak-PV slots.
- **Candidate remedies:** add `pv_to_ac[t] = pv_kwh − pv_to_battery_charge[t]` and constrain `pv_to_ac + discharge ≤ inverter_ac_kwh` (DC-coupled), or document that the AC limit only governs battery discharge. Low priority.
- **Phase / session:** Phase 2b, task 3.2 (2026-06-06); promoted from an unverified lead after operator request to verify (2026-06-06)

<!-- Phase 3 findings (#35–#38) appended below — architecture review. -->

### Finding #35 — Executor follows the plan verbatim with no independent safety clamp; `min_soc_floor` is dead plumbing after the Emergency-Charge removal
- **Severity:** S4
- **Domain:** executor
- **Status:** open
- **Location:** `executor/override.py:115-169` (`min_soc_floor` stored at `:122` but **never read** in `evaluate()`); explicit comments `override.py:51`, `:110-112` ("Emergency charge override was removed in REV E6 … min_soc_percent is a planning/optimization target, not a safety floor"); `executor/controller.py:338-346` (`_calculate_discharge_limit` "ALWAYS return MAX"); `controller.py:238`/`:268` (`soc_target` taken verbatim from `slot.soc_target`); `executor/engine.py:1207` (passes `min_soc_floor` into the evaluator); no schedule-freshness check in `_load_current_slot` (`engine.py:1536-1597`)
- **Symptom:** Nothing in the executor independently bounds what it sends to the inverter. The kW→A/W conversions clamp to the *configured* charge/discharge limits, but the **SoC target and export power are passed straight through from the plan**, discharge is always commanded at max, and the once-present low-SoC emergency charge is gone. If the planner emits a bad `soc_target` or export figure (bad forecast → bad plan, a solver infeasibility fallback, a misconfigured `min_soc`, or a stale-but-still-covering schedule), the executor transmits it; the only backstop is the **inverter BMS hard cutoff**. The `min_soc_floor` parameter — the natural home for a runtime floor — is plumbed all the way in and then never used.
- **Root-cause hypothesis:** CONFIRMED (code read). This is **partly by design**: the operator deliberately removed Emergency Charge (REV E6) and the comments state that deep-discharge protection is delegated to the BMS, which sits below Darkstar's soft planning limit. What protects the system today: (a) Kepler's planning-time SoC/power constraints, (b) the slot-failure fallback (`override.py:145-160`: when no valid slot exists → `grid_charging=False`, `soc_target=current SoC` → hold), (c) the inverter BMS. The **gap** is defense-in-depth: there is no execution-time validation that the plan is sane, and `min_soc_floor` is now confirmed dead code (a smell that signals the absent clamp). Note a stale-but-still-covering schedule (planner died, yesterday's 48h plan still spans `now`) is followed verbatim with stale prices — SoC-safe (the stale plan is internally consistent) but economically wrong, with no freshness guard.
- **Candidate remedies (options only):** remove the dead `min_soc_floor` plumbing OR wire it into a real runtime clamp (refuse to command `soc_target` below configured `min_soc`, refuse export above a configured grid limit); add a schedule-freshness check (warn/fall-back-to-hold when the loaded schedule's `generated_at` is older than N hours). Whether a runtime clamp is wanted at all is an architecture decision — see **OQ6**.
- **Phase / session:** Phase 3, task 4.4 (2026-06-06)

### Finding #36 — `executor/engine.py` is a confirmed god object; `actions.py` is a co-location file, not a god object
- **Severity:** S4
- **Domain:** architecture
- **Status:** open
- **Location:** `executor/engine.py` (2035 lines) — class `ExecutorEngine` with ~34 instance attributes (5 dedicated to EV state), ~18 external collaborators (several lazy-imported inside methods to dodge circular imports), and `_tick` at `engine.py:1013-1535` (**~522 lines** — the single highest-risk method, mixing pause/toggle checks, slot load, state gather, override branching, the inline EV source-isolation+failure block `:1249-1354`, water/EV/excess-PV control, dispatch, error capture, history + slot-observation writes, battery-cost update, and WS broadcasts); `executor/actions.py` (1244 lines) — two small-state classes (`HAClient` 6 attrs, `ActionDispatcher` 4 attrs) plus ~430 lines of near-duplicated device-writer boilerplate (`set_water_temp`/`set_custom_entity`/`_set_max_export_power`/`set_ev_charger_switch`, `:760-1193`)
- **Symptom:** Risk and change-surface are concentrated in one class and one 522-line method that issues every physical command. A single shared `threading.Lock` (`engine.py:165`) guards quick-action, pause, water-boost, status, and config-reload state at once; `self.dispatcher` and `self._background_tasks` are touched by pause, water-boost, and EV code — so any test or change reverberates widely. The engine reaches into `dispatcher._send_notification(...)` (protected access) at `:670/:686/:1179`.
- **Root-cause hypothesis:** CONFIRMED (read both files in full via subagent + spot-verified `_tick` boundaries 1013-1535, file sizes, and the `slot_observations` cross-write at `history.py:155`). engine.py accreted ~9 responsibilities (lifecycle/threading, config reload, tick orchestration, status/metrics, quick-action, pause, water-boost, notifications, slot/state/cost/EV I/O). actions.py's problem is method-level duplication + three concerns co-located, not state concentration.
- **Candidate remedies (options only — pure refactor, no behavior change):** extract from engine — `SlotLoader` (nearly pure), `SystemStateReader`, `BatteryCostUpdater`, `WaterBoostController`, `PauseController`, `QuickActionManager`, and (highest value, hardest) an `EVChargeController` owning the 5 EV attrs + the inline isolation block; shrink `_tick` to an orchestrator over those. From actions — lift the retry helpers + `HAClient` into their own modules, fold the four device-writers onto a shared apply-primitive, and extract a public `Notifier` (which also removes the engine's protected-access calls). Sequence after the higher-severity fixes; god-file refactors are risk-bearing.
- **Phase / session:** Phase 3, task 4.2 (2026-06-06)

### Finding #37 — WAL mode on `planner_learning.db` is enabled only as a side-effect of executor init, never at startup; `ensure_wal_mode()` is test-only
- **Severity:** S3
- **Domain:** infra-tests
- **Status:** open
- **Location:** `backend/learning/store.py:43-45` (comment: "WAL mode will be enabled on first connection … we rely on the sync ExecutorHistory or migration script") + `:56-59` (`ensure_wal_mode`, **callers are only tests** — `tests/backend/test_pipeline_spike_filtering.py`, `test_recorder_deltas.py`); production WAL is set only by `executor/history.py:96-98` (`PRAGMA journal_mode=WAL`), which runs only when the executor is instantiated, and that is gated on `executor.config.enabled` (`backend/main.py:115`); the lifespan never calls `store.ensure_wal_mode()` (`main.py:136-148`)
- **Symptom:** On a fresh DB, or on an install where the executor is disabled, `planner_learning.db` can run in default rollback-journal mode, where **any writer blocks all readers**. The recorder (every 15 min), planner, and ML training all share this one file; without WAL, concurrent access is far more likely to raise `database is locked`. WAL is a persistent DB property, so once *any* run with the executor enabled sets it, it sticks — which masks the gap on most installs but leaves executor-disabled / freshly-migrated DBs exposed.
- **Root-cause hypothesis:** CONFIRMED (code read + grep for callers). The async `LearningStore` (the canonical, always-constructed accessor) explicitly defers WAL to a collaborator that may not run. The one-line guaranteed fix exists but is unwired.
- **Candidate remedies (options only):** `await store.ensure_wal_mode()` in the `main.py` lifespan right after `LearningStore` init (independent of the executor); or have the Alembic migration set WAL.
- **Phase / session:** Phase 3, task 4.3 (2026-06-06)

### Finding #38 — Synchronous SQLite/ORM reads run on the FastAPI event loop in several API routes (price + executor history), some with the 5 s default busy-timeout
- **Severity:** S4
- **Domain:** infra-tests
- **Status:** open
- **Location:** `backend/api/routers/price_forecast.py:99` (and the sibling routes at `:155`, `:233`, `:281`) call blocking `sqlite3.connect` + synchronous `cursor.execute/fetchall` inside `async def` handlers with no `to_thread`/`run_in_executor`; same pattern in `backend/core/price_outlook.py:46`/`:194`; `backend/api/routers/executor.py` history/stats routes call the sync SQLAlchemy `ExecutionHistory` on the loop; the price connections omit `timeout=`, so they use SQLite's ~5 s default busy-timeout (vs the 30 s configured elsewhere) and don't set WAL
- **Symptom:** Each such request stalls the entire FastAPI event loop for the query duration (all other requests wait), and the short-busy-timeout price connections are the most likely to raise `database is locked` when they race the recorder/planner/ML writers — especially during the daily price-forecast generation.
- **Root-cause hypothesis:** CONFIRMED for the blocking pattern (read `price_forecast.py:90-124`). **Refuted lead (verified):** the heavy MILP solve does NOT block the loop — `planner/pipeline.py:765` wraps `solver.solve` in `await asyncio.to_thread(...)`. **Unverified residual:** whether `ml/training_orchestrator.train_all_models` (awaited on the main loop from `scheduler_service`) offloads its sync `sqlite3`/sklearn/`requests` work — flagged for a later look, not confirmed here.
- **Candidate remedies (options only):** wrap the sync DB work in `asyncio.to_thread`, and/or route these reads through the async `LearningStore`; add `timeout=30` to the price connections (pairs with #37's WAL fix).
- **Phase / session:** Phase 3, task 4.3 (2026-06-06)

### Leads verified and dismissed (Phase 2b, 2026-06-06)
Two candidates raised during the traces were checked against the code and are **NOT bugs** — recorded so they aren't re-investigated:
- **Net-meter import+export "double count" (`backend/recorder.py:422-448`):** the net-meter branch reads two *independent* cumulative registers (`total_grid_import`, `total_grid_export`) and takes each one's delta. Both being non-zero in a 15-min slot is legitimate (import early, export late), and the cost calc uses them with opposite signs. Correct handling of separate registers, not double counting.
- **Duplicate-`id` array merge collapse (`backend/config_migration.py:550-598`):** `merge_arrays` appends one `result` entry per *source* item, so two user entries sharing an `id` are both preserved (not collapsed). Duplicate ids survive the merge and are caught by the save-time validator (`api/routers/config.py:493-502`). No silent loss.

---

## Open Questions (carried into solution sessions — NOT decided here)

These are the architecture decisions the diagnosis surfaces. They are intentionally left open; this change only frames them.

**PV hybrid (from #2, #6, #7):**
- OQ1 — **Magnitude clamp:** what is the right physical ceiling? Options: `kWp · slot_hours · max_efficiency` with the inverter AC limit applied; or `physics × k`; or clamp the *residual* rather than the final value. Where should it live (forward.py output)?
- OQ2 — **Cold-start policy:** what should `min_samples` (and a minimum *time span*) be? Should the system stay on physics-only/seed until a local model passes a validation gate, or blend by data volume?
- OQ3 — **Physics calibration (#6):** add temperature derating + inverter AC clipping (needs an AC-limit config field) and/or a better transposition model? Or rely on the clamp + residual instead?
- OQ4 — **Disable toggle:** add an advanced "Enable ML PV correction" switch (physics-only fallback), mirroring price-forecasting. Confirmed as wanted by operator; design detail deferred.
- OQ5 — **Two estimators (LARGELY RESOLVED by `pv-open-meteo-baseline`; documented in Phase 3 / task 4.1):** the two PV estimators are no longer independent competing truths. **Open-Meteo is now the baseline spine**, and the physics+ML "hybrid" is `final = open-meteo baseline + bounded ±residual`:
  - The hybrid path (`_get_forecast_data_aurora`, `backend/core/forecasts.py:162`) and the standalone Open-Meteo path (`_get_forecast_data_async`, `:357`) are selected by `forecasting.active_forecast_version` ("aurora" → hybrid).
  - In inference (`ml/forward.py:383-394`) the baseline is the per-slot Open-Meteo value, **falling back to the legacy home-grown physics only when Open-Meteo is NaN for that slot**. The baseline is clipped to a physical ceiling (`_pv_physical_ceiling_kwh`, `:79-91`, `:397-398`).
  - The ML residual is bounded to ±`pv_residual_bound_fraction` (default 25 %) of the baseline and scaled by a data-volume personalization ramp (`:425-427`); the **final value is re-clamped to the physical ceiling** (`:449-450`) and smoothed. So "which is truth" = Open-Meteo baseline; "should one clamp the other" = **yes, and it now does** (ceiling on both baseline and final; residual bounded). This closes the original OQ5.
  - **Disable toggle exists:** `aurora_pv_enabled=false` makes the hybrid path return the raw Open-Meteo value (`forecasts.py:193-229`, `:283`).
  - **Remaining narrow question:** the retired home-grown physics still survives as (a) the per-slot NaN-fallback baseline and (b) a diagnostic feature. Given the Data Confirmation showed it over-produces ~2.5× (capped now only by the physical ceiling), should the NaN-fallback be retired entirely (e.g. last-good Open-Meteo instead of physics)? Minor; carry into the PV solution session.

- OQ6 — **Execution-time safety clamp vs full BMS delegation (Phase 3 / task 4.4; see #34, #35):** the executor transmits the plan's `soc_target` and export power verbatim and always commands max discharge; deep-discharge and over-power protection are delegated to the inverter BMS / hardware (the operator deliberately removed Emergency Charge in REV E6, and `min_soc` is explicitly "not a safety floor"). Should Darkstar add a thin execution-time defense-in-depth clamp — refuse to command `soc_target` below configured `min_soc`, refuse export above a configured grid limit, and/or refuse to act on a stale schedule (freshness check) — or is full delegation to the BMS the intended design? The dead `min_soc_floor` parameter (#35) is the natural home for such a clamp. **Decision deferred.**

- OQ7 — **Energy-data SSOT & module boundaries (Phase 3 / task 4.5; see #12, #25, #26, #27, #29):** the "DB is SSOT" claim has source-dependent column meanings and a shared-table boundary that need a canonical definition:
  - `load_kwh` means **total** for backfill-written rows but **base load** (EV/water subtracted) for live rows (#27) — the clearest SSOT violation.
  - `charge_kw` is grid-sourced only while a sibling field is total battery charge (#12); recorder rows are labelled one slot off (#25); and the UPSERT >0 guard prevents corrections/true-zeros (#29).
  - `slot_observations` has **two writers** across module boundaries: the recorder owns the energy/price columns (`backend/recorder.py`), while the **executor** writes `executed_action` into the same table via a raw `UPDATE` (`executor/history.py:155`).
  - **Question:** define the canonical owner and meaning of each `slot_observations` column, and decide whether disaggregation should be unified across *all* writers (live recorder + backfill) so the ML training column has one consistent meaning. **Decision deferred** to the recorder/SSOT solution session.

**Batching note:** OQ1–OQ4 likely become one `fix-pv-forecast-safety` change (clamp + cold-start + toggle, with physics calibration optional); OQ5 is essentially closed by `pv-open-meteo-baseline` (only the NaN-fallback cleanup remains). OQ6 fits a `harden-executor-safety` change; OQ7 fits a `recorder-ssot` change alongside #25–#29.

---

## Agreed Direction (Phase 1 discussion, 2026-06-04) → change `pv-open-meteo-baseline`

After tracing both PV paths and the open-meteo library internals with the operator, the root cause and target architecture are agreed:

- **Root cause (most likely):** the Aurora baseline uses Darkstar's own GHI→tilt transposition (crude, fixed diffuse fraction, no temperature, ×0.85), which runs systematically **low**. Training learns `actual − physics` against that low baseline, so the ML residual carries a large positive correction that **overshoots (the 67 vs open-meteo 29 vs actual 34)**. NOT the operator's geometry (their MAE is 0.12) — geometry/cold-start dependent, hence "some users."
- **Decision:** make **open-meteo's solar-forecast API the PV baseline** (it already returns tilted irradiance + temperature + real diffuse/direct split; already wired in `backend/core/forecasts.py`; handles multiple arrays; 10k calls/day free is ample). The ML becomes a **bounded personal nudge** on top of that good baseline.
- **Retire** the home-grown GHI→physics calc — it needs the *same* open-meteo host, so it was never a valid outage backup (`weather.py:355` and library both hit `api.open-meteo.com/v1/forecast`).
- **Fallback:** store **only successful** open-meteo fetches; planner uses the latest stored forecast; on API outage keep using the last good fetch + warning banner via the **existing** `record_forecast_error` → `SystemAlert` path (`backend/health.py:889`). This SAME stored history feeds ML training (predicted-vs-actual) — one mechanism, two uses.
- **Cold-start / transition:** gradual ramp weighted by days of data (0 days = 100% open-meteo → capped nudge over ~weeks). Existing users get a **~10-day backfill** (open-meteo history × their existing actual production); production history is preserved.
- **Transparency:** status on the Aurora Command Center page (next to "PV forecast quality" / training, `pages/Aurora.tsx`): "Open-meteo baseline" → "+ personal tuning (active)" with progress; optional Dashboard badge.
- **Safety cap:** final forecast can never exceed physically possible.

This closes OQ1 (clamp), OQ2 (cold-start ramp), OQ4 (disable/fallback), OQ5 (open-meteo IS the baseline). Findings #2/#6/#7 are resolved by `pv-open-meteo-baseline`.

---

## Data Confirmation (2026-06-04, `scripts/compare_pv_paths.py` on a live API)

Ran Path A (our physics, **no ML**) vs Path B (open-meteo library) on the operator's config (7.11 kWp: 3.16 + 3.95):

| Date | A: our physics (kWh) | B: open-meteo | ratio |
|------|------|------|------|
| 2026-06-05 | 89.6 | 36.4 | **2.46×** |
| 2026-06-06 | 124.6 | 48.2 | **2.59×** |
| 2026-06-07 | 103.7 | 39.1 | **2.66×** |

(2026-06-04 was a partial day — ignore.)

**Verdict — corrects the prior analysis:** our home-grown physics **over-produces ~2.5×** and is **physically impossible** (124 kWh from 7.11 kWp ≈ 17 kWh/kWp/day; real max ~6–7). The earlier reasoning that "physics should be lower / it's the ML" was **WRONG** — the transposition (#6) is the primary defect.

**Unified mechanism (explains both the operator's 0.12 MAE AND the affected users' 2×):**
- Physics over-produces (~2.5×).
- Training sets `residual = actual − physics`, so a well-trained model learns a **large negative** correction that **cancels** the physics error → operator's forecast is accurate despite a broken baseline.
- Cold-start / under-trained homes haven't learned that big negative correction yet → the uncancelled physics over-prediction leaks through → the ~67 kWh complaint.
- → `pv-open-meteo-baseline` fixes the root cause: a sane baseline (open-meteo) means the ML only ever applies a tiny correction, so under-trained homes are never exposed to the error. The **safety ceiling** is essential — nothing today caps the impossible 124 kWh.

---

## Agreed Direction (EV charging) — 2026-06-06 → `price-forecasting-module-4/5`

Discussion with the operator settled that Finding #1 is not a solver-math bug to patch but a **wrong user-facing model**. The penalty/incentive-bucket mechanism is a hand-tuned *willingness-to-pay* curve that (a) defaults to empty → the EV silently never charges, (b) requires the user to know spot/import prices to set correctly, and (c) can never *guarantee* the car reaches a usable charge by a given time. The fix is to replace the user-facing model with a **goal**, and let cost-minimisation + self-consumption do the rest — exactly how the home battery already behaves.

**Agreed model (what the user sets, per charger):**
- **Target SoC + ready-by time + optional repeat.** One concept, not two modes. "Repeat" = daily / chosen weekdays / every N days / **none** (a one-off specific date). A specific date is simply "no repeat" — there is no separate "multi-day mode".
- **Keep charger on after target** (default off) — leaves the switch enabled past the target so the car can pre-condition / run its heater (a real user request).
- **EV-before-battery priority** (default off = battery first) — only breaks the tie for *free surplus PV*; never forces expensive grid.
- **Optional HA entities** — an `input_datetime` (ready-by) and `input_number` (target SoC). When set, **HA wins** over the Darkstar UI value, mirroring the existing vacation-mode pattern (HA entity → subscribed → drives planner state). Bidirectional sync.

**What the system does (no user knobs):**
- Treat "target SoC by ready-by time" as a **near-mandatory requirement** (soft constraint with a large shortfall penalty, so it stays feasible if the car physically can't reach it in time → drives the on-track/behind status).
- Charge from the **cheapest** slots in the window (identical to home-battery arbitrage), pulling grid only as needed to hit the target.
- **Always** route excess PV to self-consumption before export: **excess PV → battery or EV (per the priority switch) → the other → export.** High export prices never coincide with PV surplus, so "prefer export" is not a real case.
- **Penalty levels / incentive buckets are retired** from the user-facing model. The only "penalty" left is the internal, auto-set shortfall penalty — never user-tuned.

**Multi-day is automatic, not a mode:** a far ready-by date + a price forecast → the `MultiDayPlanner` spreads charging onto the cheaper days; a near date → Kepler charges within the known Nordpool horizon. The **core feature needs only the day-ahead prices the planner already has** — it is *not* gated behind `price_forecast.enabled`. The 7-day forecast (Module 1) is an optional enhancement that improves multi-day spreading only.

**Escape hatch:** "advanced" control = simply *don't enable the EV charger in Darkstar* (leave `switch_entity` unset). Darkstar then never touches the switch and HA owns it entirely. No extra toggle needed.

**Dashboard:** the EV controls live in a **tab inside the existing Energy Resources card** (no room for a new top-level card), with the active tab persisted in `localStorage` reusing the ChartCard overlay pattern (`darkstar-chart-overlays` → `darkstar-resources-tab`, versioned, default `"metrics"`). The "Metrics" tab keeps the at-a-glance EV line; the "EV" tab holds the controls.

**Disposition:** these are unstarted proposals (0 tasks done), so the redesign **amends `price-forecasting-module-4` (engine) and `price-forecasting-module-5` (UI + HA)** rather than creating a new change. Finding #1's S1 is closed when those ship.
