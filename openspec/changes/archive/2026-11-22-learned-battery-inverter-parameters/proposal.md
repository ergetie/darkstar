# Proposal

## Why

Darkstar's planner models the battery with two hand-set numbers (`battery.charge_efficiency` 0.92, `battery.discharge_efficiency` 0.95) that lump battery and inverter losses together. Reflex, the old auto-tuner, never measured them: it has not run automatically since the FastAPI migration (`06b40f9a`), it edits `config.yaml` directly, and its three tuned values are broken or unobservable:

- `pv_confidence_percent` cannot converge: Reflex measures the stored forecast, but the factor is applied later in the planner, so its own changes never reach what it measures (prod dry run: 70 -> stuck at the bound for 115 days -> 95).
- `s_index.base_factor` is only the fallback when the default probabilistic S-index fails, and "no history" counted as "no low-SoC events" (prod dry run: 1.10 -> 1.00 in 10 days).
- Capacity (`get_capacity_estimate`) requires `soc_start_percent`, which the recorder never writes (11 of 36,846 prod rows), so it never produces a value. Capacity is also not identifiable separately from efficiency.
- A stale `learning_daily_metrics` row once overrode `base_factor` with 1.4066 for 8 months (2026-03-15..2026-11-19). A learned value must expire and say so.

Production backtests (2026-11-22, read-only, 368 days) show what IS measurable from the recorded data: battery round-trip efficiency (0.962, identical in two disjoint periods), and the inverter's charge-path loss (about 60 W standby plus 7.5 % of battery charge energy, beating a constant percentage about 2x in walk-forward). Discharge and PV conversion loss, capacity and real max power are not separable with the standard sensors.

## What Changes

- New learned-parameter store (new tables, Alembic) holding each learned value with evidence (rows, window), confidence, history, last-estimate time and an optional user lock. Values live outside `config.yaml`; `config.yaml` is never written by learning.
- A daily service estimates, from recorded data only, (a) battery round-trip efficiency (RTE) pooled over 4+ weeks of contiguous recorded runs and corrected for the net SoC change, from the DC-side battery counters and SoC; (b) inverter charge-path loss (fraction of battery charge energy) and standby power (W) by a robust fit of the energy balance residual over base-load-reliable slots; optionally from a configured inverter-loss sensor (new side table) instead of the balance.
- Safety rules on every value: minimum-data gate, physical bounds (out-of-bounds estimates are rejected, not clamped), bounded step per update, a deadband, expiry after 30 days without a fresh estimate (falls back to config, said so in API and UI), user lock, universal constants only.
- Learned values apply automatically. The planner (Kepler, price reserve, benchmark) uses effective `charge_efficiency = (1 - inverter_charge_loss) x sqrt(RTE)` and `discharge_efficiency = sqrt(RTE) x inverter_discharge_efficiency` (default 0.97, not measurable, lock-only). If any component is unavailable the pair falls back to the config values.
- Every applied change (learned update, expiry, recovery) sends one notification, gated by a new toggle `executor.notifications.on_learned_parameter_change` (default on) that follows the existing notification pattern (config, executor config, API, Executor page, Settings).
- User can lock any value to their own number (UI and API); a locked value never expires and is never replaced by a learned one.
- Warn-only (never applied): sudden change of implied battery capacity versus its rolling baseline, and measured battery power far below the plan's requested maximum. Surfaced as health issues (snoozable).
- Offline hindsight evaluation: a tool and automated test that replays archived planner runs and recorded flows, comparing config versus walk-forward learned values.
- **BREAKING** Remove Reflex: `backend/learning/reflex.py`, `bin/run_reflex.py`, `POST /api/aurora/config/toggle_reflex`, the Reflex part of `POST /api/learning/run`, `state.reflex_enabled`, the Aurora page toggle, the Settings toggle and "Learning Parameter Limits" section, and the config keys `learning.reflex_enabled`, `learning.max_daily_param_change` (all keys), `learning.min_sample_threshold`, `learning.min_improvement_threshold` (migrated away; sibling keys and every value Reflex ever wrote into user settings stay as the user's manual settings). `pv_confidence_percent` and `s_index.base_factor` become plain manual settings.
- Drop the dead tables `reflex_state` and `learning_daily_metrics` (nothing reads them; the stale-row bug class) and the store methods only Reflex used.
- EV charging-loss learning (Reflex `analyze_ev_losses`) is not carried over: it never ran automatically and never changed a value on prod; the planner's three-parameter EV model is not identifiable from constant-power sessions. Follow-up (see design D11).

## Capabilities

### New Capabilities
- `learned-parameters`: storage, lifecycle (gate, bounds, step, deadband, expiry), lock, effective-value resolution, history, notification, and API/UI for learned parameters.
- `battery-inverter-learning`: how RTE, inverter charge loss and standby are measured, which slots are usable, how effective planner efficiencies are composed, and the warn-only capacity and power checks.
- `learning-hindsight-evaluation`: the offline replay that compares config and learned values on archived runs.

### Modified Capabilities
- `pv-confidence-reflex`: all requirements removed (Reflex is gone; the setting is manual).
- `ev-charging-losses`: "EV loss parameters are learned automatically" removed; per-charger values are manual.
- `pv-training-data-quality`: "The same cleaning applies to the Reflex bias input" removed.
- `battery-cost-integrity`: cycle cost stays user-owned; wording no longer refers to Reflex.
- `durable-config-write`: writer lists no longer name the Reflex toggle or engine; learning never writes `config.yaml`.
- `energy-recording`: spike-row scenario for the removed Reflex reader dropped.
- `config-dead-key-removal`: Reflex keys are removed by migration; sibling-key scenarios no longer use `reflex_enabled`.
- `aurora-corrector`: sibling-key scenario no longer uses `reflex_enabled`.
- `planner-run-archive`: records carry the learned/effective battery parameters used by the run.
- `daily-battery-benchmark`: the benchmark and its capacity fit use the effective efficiencies.

## Impact

- Code: new `backend/learning/learned_parameters.py` (store access, resolution, lifecycle), `backend/learning/battery_estimators.py` (pure estimators), `backend/learning/battery_warnings.py`, `backend/learning/hindsight_evaluation.py`, `backend/services/learned_parameters_service.py` (daily loop), `backend/api/routers/learning.py` (endpoints), `scripts/evaluate_learned_parameters.py`; edits in `backend/learning/models.py`, `backend/learning/store.py`, `planner/pipeline.py`, `backend/services/benchmark_service.py`, `backend/services/plan_archive.py`, `backend/recorder.py` and `backend/core/slot_energy.py` (optional loss sensor), `backend/health.py`, `backend/config_migration.py`, `executor/config.py`, `backend/api/routers/executor.py`, `backend/api/routers/forecast.py`, `backend/main.py`, `config.default.yaml`, `pyproject.toml`; deletions: `backend/learning/reflex.py`, `bin/run_reflex.py`, `tests/ml/test_reflex*.py`.
- Frontend: Settings Battery tab (new "Learned parameters" section), Executor notification toggle, Aurora page (Reflex toggle removed), `lib/api.ts`, `lib/types.ts`, settings types and search guides.
- Schema (Alembic, approved): new tables `learned_parameters`, `learned_parameter_history`, `inverter_loss_observations`; drop `reflex_state` and `learning_daily_metrics`. `slot_observations` unchanged.
- Config: new `input_sensors.inverter_power_losses` (optional) and `executor.notifications.on_learned_parameter_change`; removed keys listed above. `config_version` unchanged.
- Dependencies: none (numpy and SQLAlchemy already used).
- Docs: `docs/ARCHITECTURE.md` (section 5.3, schema list) and `docs/DEVELOPER.md` (Reflex section) are rewritten for the learned-parameter design (tasks 12.1 and 12.2, approved by the user 2026-11-22). `docs/RELEASE_NOTES.md` untouched.
