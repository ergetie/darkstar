## 1. Config: goal-based per-charger schema (retire penalty levels)

- [ ] 1.1 Add per-charger fields to `EVChargerDeviceConfig` (`executor/config.py`): `target_soc_percent` (int, default 80), `ready_by` (str `HH:MM`), `repeat` (enum `daily`|`weekdays`|`weekends`|`every_n_days`|`none`, default `daily`), `n_days` (int, used when `repeat: every_n_days`), `ready_by_date` (date string, used when `repeat: none`), `keep_on_after_target` (bool, default false), `charge_priority` (enum `battery`|`ev`, default `battery`).
- [ ] 1.2 Accept `departure_time` as a deprecated alias for `ready_by` (log a one-time deprecation warning, copy value forward). Keep the existing YAML 1.2 string-parsing / sexagesimal-int handling for the time value.
- [ ] 1.3 Retire `penalty_levels`: if present, ignore for scheduling, log a deprecation warning, and auto-migrate to `target_soc_percent` = the highest configured `max_soc` (so existing users keep an equivalent target). Remove incentive-bucket plumbing from the adapter (`adapter.py:146–154`).
- [ ] 1.4 Update `config.yaml` + `config.default.yaml`: replace the `penalty_levels` example with a default goal (`target_soc_percent: 80`, `ready_by: "07:00"`, `repeat: daily`) and inline comments. Ensure a configured charger charges out of the box.
- [ ] 1.5 Unit tests (`tests/ev/test_ev_config.py`): goal fields parse; `departure_time` alias maps to `ready_by` + warns; `penalty_levels` present → ignored + migrated + warns; `repeat: none` requires `ready_by_date`; invalid/missing time handled.

## 2. Pipeline: resolve ready-by + required energy

- [ ] 2.1 Add `_resolve_ready_by(charger, now)` in `planner/pipeline.py`: from `ready_by` + `repeat` (or `ready_by_date` for `none`) compute the *next* ready-by datetime (timezone-aware). Daily = next occurrence of the time; weekdays/weekends/every_n_days = next matching day; none = the specific date/time (inert once past).
- [ ] 2.2 Add `_calculate_required_kwh(charger, db_path)`: `max(0, (target_soc_percent − current_soc_percent)/100 · battery_capacity_kwh)` minus EV energy already delivered this charging cycle (from `slot_observations` since last plug-in). Clamp ≥ 0.
- [ ] 2.3 In the EV section of `pipeline.py`, attach `required_kwh`, resolved `deadline`, `charge_priority`, and `keep_on_after_target` to each plugged charger's state dict. Skip unplugged chargers (no requirement).

## 3. MultiDayPlanner: automatic spreading (forecast-gated, graceful fallback)

- [ ] 3.1 Create `planner/strategy/multi_day_planner.py` with `MultiDayPlanner.compute_quota(remaining_kwh, deadline, daily_prices, max_daily_kwh, min_daily_fraction=0.1) -> dict[date, float]`. Inverse-price weighting: `weight[day] = 1/avg_price[day]`. Keep it **load-agnostic** (no EV-specific params).
- [ ] 3.2 Guardrails: min-daily-fraction floor on every non-final day (then redistribute), per-day power cap (`max_power_kw · available_hours`) with redistribution, single-day-remaining = allocate all, zero/negative remaining = zeros, equal prices = equal split, partial/missing prices = fill with average of known days.
- [ ] 3.3 Invoke automatically in `pipeline.py`: **only** when the resolved deadline is more than one day out **and** a 7-day forecast exists (`_get_daily_price_averages` from the Module 1 `price_forecasts` table). Set today's quota as `daily_quota_kwh` on the charger state. When the deadline is near OR no forecast exists, set `daily_quota_kwh = None` (no spreading; Kepler uses real day-ahead prices). **Do not gate the core feature on `price_forecast.enabled` — only the spreading.**
- [ ] 3.4 Unit tests (`tests/planner/test_multi_day_planner.py`): inverse-price allocation, min-fraction enforcement, power-cap redistribution, single day, zero remaining, equal prices, partial price data.

## 4. Solver: requirement + self-consumption priority (remove incentive buckets)

- [ ] 4.1 Add fields to `EVChargerInput` (`planner/inputs/types.py`): `required_kwh: float | None`, `deadline: datetime | None`, `daily_quota_kwh: float | None`, `charge_priority: str = "battery"`. Remove `incentive_buckets`.
- [ ] 4.2 In `adapter.py`, populate the new fields from charger state; delete the `penalty_levels → IncentiveBucket` mapping.
- [ ] 4.3 In `kepler.py`, **remove** the incentive-bucket variables/constraints (`:203–234`) and the `Σ ev_bucket_charged · value_sek` reward (`:642–651`).
- [ ] 4.4 Add the soft target-by-time requirement per charger: `Σ ev_energy[d][t] (t ≤ deadline) + shortfall[d] >= required_kwh`; add `shortfall[d] · EV_SHORTFALL_PENALTY` to the objective (fixed internal constant, well above any plausible import price; defined as a module constant).
- [ ] 4.5 Add the excess-PV self-consumption preference: a small objective term so surplus PV routes to battery/EV before export, ordered by `charge_priority` (default battery-first). Must be dominated by real import/export economics (tie-break only).
- [ ] 4.6 Apply `daily_quota_kwh` (when not None) as an upper bound on today's EV energy: `Σ ev_energy[d][t] <= daily_quota_kwh`.
- [ ] 4.7 Keep the deadline as a time-window constraint (`ev_energy[d][t] == 0` for slots ending after the deadline).
- [ ] 4.8 Solver tests (`tests/planner/test_kepler_ev_target.py`): configured charger charges from surplus PV instead of exporting; reaches `target_soc` by deadline when feasible; reports shortfall (stays feasible) when not; `charge_priority` flips battery/EV order for free surplus without forcing grid; daily quota caps today's energy; no incentive-bucket code path remains.

## 5. Read-only EV state API

- [ ] 5.1 Create `backend/api/routers/ev.py` with `GET /api/ev/chargers`; register in `backend/api/app.py`.
- [ ] 5.2 Persist transient state to `data/ev_multi_day_state.json` at the end of each pipeline run: per charger `id`, goal (`target_soc_percent`, `ready_by`, `repeat`, resolved `deadline`), `required_kwh`, `delivered_kwh`, `remaining_kwh`, `daily_quota_kwh`, `quota_schedule` (when spreading), `keep_on_after_target`, `charge_priority`, `status`, `last_updated`.
- [ ] 5.3 Endpoint merges state file with live HA sensor data (`plugged_in`, `soc_percent`, `power_kw`, fetched on request, reusing the system-status HA pattern). `status ∈ {on_track, behind, complete, idle}` computed from remaining vs deliverable-by-deadline.
- [ ] 5.4 Tests (`tests/backend/test_ev_api.py`): returns all configured chargers with goal + progress + status; spreading charger includes `quota_schedule`; non-spreading charger has null quota fields; missing/stale state file → `idle` + live sensors still populated.

## 6. End-to-end + migration

- [ ] 6.1 E2E test (`tests/planner/test_e2e_ev_target.py`): charger at 30% SoC, `target 80%` by tomorrow 07:00, midday surplus PV → schedule charges the EV from surplus (not export) and reaches 80% by the deadline using cheapest slots.
- [ ] 6.2 E2E multi-day: `ready_by` 3 days out + forecast with a cheap middle day → more energy allocated to the cheap day, today's quota respected, target met by the deadline.
- [ ] 6.3 Migration test: a config still using `penalty_levels` loads with a deprecation warning, migrates to an equivalent `target_soc_percent`, and charges correctly (no incentive-bucket path executed).
- [ ] 6.4 Confirm the full suite still passes (1051+ baseline) and no `incentive_bucket` references remain in planner/solver.
