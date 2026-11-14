## 1. Recorder and validation

- [x] 1.1 Add shared `device_source` helper in `backend/recorder.py`; rewrite the EV loop to use it, remove `power_results.get(...) or 0.0`, record `ev_charger_devices`
- [x] 1.2 Use the helper in the water loop; keep water behaviour unchanged
- [x] 1.3 Stop forcing `load=mixed` for `unknown` devices; keep `snapshot`/`mixed`/`unconfigured_zero` behaviour
- [x] 1.4 Generalise the spike-to-unknown rule in `backend/validation.py` to EV
- [x] 1.5 Make `backend/learning/backfill.py` write `unknown` for a device without history; verify `store.py` merges keep `unknown`

## 2. Grid-only comparison

- [x] 2.1 Refactor `_recording_exclusion` to return exclusion or partial components; drop `allow_unmeasured_water`
- [x] 2.2 Require import, export, battery (when present) and a priceable load; treat device unknown/snapshot/mixed as partial
- [x] 2.3 Generalise `clamp_hidden_demand` to any unknown device
- [x] 2.4 Replace `water_unmeasured` in `_SlotCosts` with partial components; add `partial_slots`, `partial_hours`, `partial_by_component`, `partial_spans`; keep water aliases

## 3. Frontend

- [x] 3.1 Add `partial_spans` parsing and types in `frontend/src/lib/api.ts`
- [x] 3.2 Add `buildPartialNotes` and component wording in `frontend/src/lib/costExclusion.ts`
- [x] 3.3 Render partial bands and notes in `CostSeriesChart.tsx` with `index.css` class; keep line unbroken
- [x] 3.4 Add one line on partial bands to `docs/design-system/AI_GUIDELINES.md` and the DesignSystem page (docs/ change approved by the user 2026-11-13)

## 4. ML training and metrics

- [x] 4.1 Add shared unknown-device filter in `ml/load_clean.py` and apply in `clean_load_observations` (drops rows with any device `unknown`/`snapshot`/`mixed` or `load=unknown`; keeps `unconfigured_zero` devices; tests: legacy cmon89-style `ev=snapshot` row dropped, `water=unconfigured_zero`/`load=mixed` row kept)
- [x] 4.2 Apply it in `ml/evaluate.py`, `learning/store.calculate_metrics`, forecast router MAE and the `energy.py` base-load average
- [x] 4.3 Report `dropped_unmeasured_device_rows` in logs, `learning_runs` metrics and the sidecar

## 5. Other consumers

- [x] 5.1 Monitors: skip unknown-device slots in `_eval_energy_balance`
- [x] 5.2 Battery benchmark: treat unknown device with derived load as usable-but-flagged and count `partial_slots`
- [x] 5.3 Schedule router and store: null `actual_ev_charging_kw` and `actual_ev_available` flag for unknown EV
- [x] 5.4 Energy API: add `unmeasured_slots_by_component`
- [x] 5.5 Confirm `comparison_history` passes `unknown` through (test only)

## 6. Tests

- [x] 6.1 Recorder: EV unavailable, water unavailable, both, snapshot present versus absent, one of two chargers
- [x] 6.2 Comparison: EV unknown partial, import missing excluded, load unknown excluded, battery required, clamp with both unknown, spans and coverage
- [x] 6.3 Parametrised guard: no device component type drops a slot with measured import and export
- [x] 6.4 Training exclusion and metrics count; monitors, benchmark, schedule router, validation tests
- [x] 6.5 Frontend tests for notes, unbroken line, parsing
- [x] 6.6 Run `./scripts/lint.sh` and the full test suites
