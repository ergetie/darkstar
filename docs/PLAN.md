# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

No active Antares Phase 2 revisions. Phase 2 (Rev 64–68) is completed; see `docs/CHANGELOG.md` and `docs/ANTARES_EPISODE_SCHEMA.md` for details.

### Rev 69 — Antares v1 Training Pipeline (Phase 3)

**Goal:** Train the first Antares v1 supervised model that imitates MPC’s per-slot decisions on validated `system_id="simulation"` data (battery + export focus) and establishes a baseline cost performance.

**Scope / Design Decisions:**
*   Targets: next-slot MPC control signals derived from simulation episodes (e.g. `battery_charge_kw`, `battery_discharge_kw`, and `export_kwh`), optionally extended later; `water_kwh` stays deterministic/context in v1.
*   Inputs: features built on top of `ml.api.get_antares_slots(dataset_version="v1")`, including time (hour-of-day, day-of-week), prices, `load_kwh`, `pv_kwh`, SoC, and recent history; days with `status="mask_battery"` are used but battery targets are ignored/zero-weighted where `battery_masked=True`.
*   Data split: use a time-based split over the July–now window (e.g. train on July–Oct `clean` + `mask_battery` days, validate on Nov+ `clean` + `mask_battery` days) with a fixed random seed and recorded date bounds so the dataset is reproducible.
*   Model family: LightGBM (or equivalent gradient-boosted trees) as the only supported model type for Rev 69; RL and neural networks are explicitly deferred to later Antares revisions in Phase 3.
*   Metrics: primary metrics are MAE/RMSE for each target plus cost-based evaluation on the validation slice by replaying predicted actions through the existing cost model (versus MPC baseline).

**Implementation Steps:**
1.  Define the exact feature/target contract for Antares v1 (Python dataclass or documented schema) based on `get_antares_slots("v1")`, including how `battery_masked` days are filtered or down-weighted per target.
2.  Create an `antares_training_runs` table in SQLite (`data/planner_learning.db`) to log each training run with: `run_id`, timestamps, dataset_version, date range, target set, model type, hyperparameters, metrics (per-target + cost-based), and artifact paths; add an optional mirror to MariaDB later.
3.  Extend `ml/train_antares.py` to: load the v1 dataset, apply the time-based train/validation split, build feature matrices/target vectors, train one LightGBM model per target (or a multi-output variant), and persist artifacts with versioned filenames (e.g. `models/antares_v1_<date>_<hash>.joblib`).
4.  Add a lightweight CLI/entrypoint (kept within `ml/train_antares.py`) that prints a concise training summary (data sizes, metrics, cost comparison vs MPC on the validation window) and records a row in `antares_training_runs`.
5.  Document the v1 model contract (inputs, targets, artifact naming, and where to load it from) in `docs/ANTARES_EPISODE_SCHEMA.md` or a new short `docs/ANTARES_MODEL_CONTRACT.md` so later Antares phases and tools can consume it without re-reading the training code.

**Status:** Planned (next active Antares revision; ready for implementation when approved).

**Verification Plan:**
1.  Run `python -m bin.run_planner`: record training episodes for real scheduler runs.
2.  Use the Planning Lab simulation: confirm no `training_episodes` rows appear.
3.  Monitor DB size over 24h to ensure the new table stays lightweight.

### Rev 63 — Export What-If Simulator (Lab Prototype) (ongoing/on hold)

**Goal:** Provide a deterministic, planner-consistent way to answer “what if we export X kWh at tomorrow’s price peak?” so users can see the net SEK impact before changing arbitrage settings.

**Scope:**
*   Add a debug tool (`debug/test_export_scenarios.py`) that:
    *   Uses the Learning engine’s `DeterministicSimulator` and `simulate_schedule` to re-run a **full day** (00:00–24:00) through the planner.
    *   Applies progressively stronger “export at peaks” manual plans across the highest-price slots, re-simulating the whole horizon each time.
    *   Computes full-horizon cashflow metrics (grid import cost, export revenue, battery wear) for baseline vs scenarios using the existing `_evaluate_schedule` cost model.
    *   Reports target vs realized export energy and net SEK deltas vs baseline for each scenario (prototype for Lab “Export What-If”).
*   Planner core logic stays untouched; all what-if behaviour is driven via `prepare_df` → `apply_manual_plan` → `simulate_schedule`.

**Current status:** Prototype script is in place and structurally correct, but with today’s conservative export economics most scenarios still realize ≈0 kWh of extra export (planner chooses to hold), so the tool currently acts as a “sanity check” rather than a tuner.

**Next:** Switch the simulator to use **live Nordpool + Aurora forecasts** for an arbitrary day (not just data persisted in `planner_learning.db`), and add a dedicated “relaxed economics” mode (lower cycle cost / profit margin bounds) so the Lab UI can explore truly hypothetical export behaviour without changing production guardrails.

### Rev XX - PUT THE NEXT REVISION ABOVE THIS LINE!

---

## Backlog

### 🧠 Strategy & Aurora (AI)
*   **[Rev A25] Manual Plan Simulate Regression**: Verify if manual block additions in the Planning Tab still work correctly with the new `simulate` signature (Strategy engine injection).
*   **[Rev A27] Scheduled Retraining**: Automate `ml/train.py` execution (e.g., weekly) to keep Aurora models fresh without manual intervention. Similar to Rev 57!
*   **[Rev A28] The Analyst (Expansion)**: Add "Grid Peak Shaving" capability—detect monthly peaks and force-discharge battery to cap grid import fees.
*   **[Rev A29] Smart EV Integration**: Prioritize home battery vs. EV charging based on "Departure Time" (requires new inputs).

### 🖥️ UI & Dashboard
*   **[UI] Reset Learning**: Add "Reset Learning for Today" button to Settings/Debug to clear cached S-index/metrics without using CLI.
*   **[UI] Chart Polish**:
    *   Render `soc_target` as a step-line series.
    *   Add zoom support (wheel/controls).
    *   Offset tooltips to avoid covering data points.
    *   Ensure price series includes full 24h history even if schedule is partial.
*   **[UI] Mobile**: Improve mobile responsiveness for Planning Timeline and Settings.

### ⚙️ Planner & Core
*   **[Core] Dynamic Window Expansion (Smart Thresholds)**: *Note: Rev 20 in Aurora v2 Plan claimed this was done, but validating if fully merged/tested.* Logic: Allow charging in "expensive" slots if the "cheap" window is physically too short to reach Target SoC.
*   **[Core] Sensor Unification**: Refactor `inputs.py` / `learning.py` to read *all* sensor IDs from `config.yaml` (`input_sensors`), removing the need for `secrets.yaml` to hold entity IDs.

### 🛠️ Ops & Infrastructure
*   **[Ops] Deployment**: Document/Script the transfer of `planner_learning.db` and models to production servers.
*   **[Ops] Error Handling**: Audit all API calls for graceful failure states (no infinite spinners).

---

## Future Ideas (Darkstar 3.x+?)
*   **Multi-Model Aurora**: Separate ML models for Season or Weekday/Weekend.
*   **Admin Tools:** Force Retrain button, Clear Learning Cache button.
