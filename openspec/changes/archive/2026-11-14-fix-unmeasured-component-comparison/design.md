## Context

The recorder (`backend/recorder.py`) builds per-device energy with `or_snapshot` and `power_results.get(...) or 0.0`. For water, 7765cda4 added an `unavailable` source and aggregate `unknown`; EV never got that. `grid_only_comparison._recording_exclusion` rejects `snapshot`/`mixed` as `estimated_component`, and allows unknown only for water via `allow_unmeasured_water`. Grid-only cost is `(load + water + ev) * import_price`; DS cost is `import*price - export*price` plus battery wear `(charge + discharge) * cycle_cost * 0.5`.

When total load is integrated, `isolate_base_load(total, ev, water)` subtracts the device energy. With a 0 placeholder the derived load still contains the device energy, so demand `load + water + ev` stays correct. That is why an unknown device is safe for the comparison but unsafe for training (load is not base load).

## Goals / Non-Goals

**Goals:** unknown instead of fake zero for all devices; partial instead of excluded in the comparison; visible notes; no training on contaminated load; consumer review.
**Non-Goals:** DB schema change, rewriting history, new sensors, unrelated backlog.

## Decisions

### D1. Recorder: unknown for every device
- EV loop mirrors water: `snapshot = power_results.get(f"ev_{sensor}")`; if integrated is None and snapshot is None the charger source is `unavailable`, energy contributes 0 to the aggregate and the charger is left out of `ev_charger_energy`. A real snapshot stays `snapshot` (0.25 h times kW as today). The `or 0.0` on the snapshot is removed.
- Aggregate EV method uses the existing `aggregate_method`: any `unavailable` gives `unknown`. A mix of measured chargers and one unavailable charger is `unknown` (never hides a gap), and measured chargers keep their per-charger energy.
- Per-charger detail goes in a new `ev_charger_devices` entry in quality_flags (same shape as `water_heater_devices`: `energy_kwh` null when unavailable, `source`, `coverage`).
- Any other device component present in `recording_metadata` gets the same treatment through one shared helper `device_source(integrated, snapshot)` returning `power_history|snapshot|unavailable`; EV and water both use it, so no device type has its own copy.
- `load_method`: `mixed` is only forced by `snapshot`, `mixed`, `unconfigured_zero` device methods. `unknown` no longer forces `mixed`; the load stays `derived_history` because it is integrated. A device `unknown` is what marks the load as containing device energy (see D4).
- Numeric columns: placeholder 0, no schema change.
- `measurement_provenance.parse_recording` takes an optional `allowed_methods` (default: the measured methods, so existing callers still reject `unknown`). Readers that must see unavailable-sensor rows (benchmark, load training filter) pass `SUPPORTED_METHODS`. This keeps every other consumer's strictness unchanged.
- `validation.py` today only flips water to unknown on a spike. The same rule is generalised to `ev_charging_kwh` (spike zeroed gives `ev` unknown and per-charger devices unavailable), via one helper over a `{column: component}` map.

### D2. Grid-only comparison: partial instead of excluded
- `_recording_exclusion` returns a tuple `(exclusion, partial)`. `allow_unmeasured_water` is removed; the `water`-only branch becomes general.
- Required measured components (exclusion if not): `import`, `export`, `battery_charge`, `battery_discharge` when a battery is present, with recorder owner. Battery is required: it is not in the grid-only cost, but it IS in `ds_wear_cost` and so `ds_cost` and `saving_sek`; a slot without battery flows would show a wrong DS cost. A configured battery with unknown flows stays excluded.
- `load` is required to be `derived_history`, `power_history`, `snapshot` or `mixed`. `unknown` and `unconfigured_zero` exclude: demand cannot be priced without it. `snapshot`/`mixed` load is partial.
- Device components (`ev`, `water`, any other device name in the components map that is not import/export/load/pv/battery_*): `unknown`, `snapshot`, `mixed` give partial with reason `unmeasured_component`, one entry per component. A device component absent from the provenance map is ignored (pre-provenance rows and sites without that device must not be excluded); only import, export, load and battery (when present) are required keys. `load` with `snapshot`/`mixed` is partial under its own `load` component and span, except that `load=mixed` adds no `load` entry when at least one device component in the slot is itself partial: the mixed-ness then comes from the device, whose entry already explains it, and the total load was measured from history. `load=snapshot`, or `mixed` with no partial device, keeps the `load` entry. Partial reasons carry the component only, not the method: the note wording is fixed per component. `unconfigured_zero` for a device also gives partial (reason `unconfigured_sensor`): the device energy is still inside the measured total load, so the grid-only cost is correct, and one sensorless device must never wipe the comparison. `disabled_zero` stays valid.
- The `clamp_hidden_demand` check covers any unknown device: it runs when any device is `unknown` and `load_kwh == 0` and any device kWh is above 0 or the slot has import above 0. Spec states the exact trigger: `load_kwh == 0` with a device unknown and `import_kwh > 0`.
- `pv` is not required (not used in either cost).
- Numeric: for unknown devices the 0 placeholder is used as measured value, as water does today (`water_value = 0.0` when None).
- Reason ordering: first failing exclusion wins; partial reasons are collected afterwards, only if no exclusion occurred.
- `_SlotCosts` gets `partial_components: tuple[str, ...]` replacing `water_unmeasured`.
- Coverage adds `partial_slots`, `partial_hours`, `partial_by_component`. `water_unmeasured_slots/hours` stay as aliases. A new top-level `partial_spans` is built with the existing span builder (maximal UTC-contiguous runs sharing component). Status logic is unchanged: partial slots count as covered, so a fully partial window is `available`; the user learns about it from `partial_spans`.
- Each slot contributes one partial entry per unknown component; if EV and water are both unknown two spans list.

### D3. Frontend
- `ExcludedSpan` type is reused as `PartialSpan` with same fields; `parseExcludedSpans` is reused by `parsePartialSpans`. `partial_spans` is optional.
- `costExclusion.ts` gets `buildPartialNotes(spans)` giving lines like "EV not measured for 26 h 15 min (Nov 9 10:00-Nov 10 12:15)" using `formatSlotDuration` and component labels; one line per component with merged spans uses the largest span's time range; adds "and N more" under the existing two-line cap. Wording: `<Label> not measured` for every partial reason except `unconfigured_sensor` (`<Label> sensor not set up`); partial reasons carry no method, so snapshot/mixed use the same phrase. The former water-only note (`water-unmeasured-note`) is replaced by these notes.
- `CostSeriesChart` draws partial spans with the existing hatched band class in a lighter tone via a second CSS class `cost-partial-band` defined next to the excluded one in `index.css` using existing tokens only; lines are not broken. AI_GUIDELINES.md gets one line describing partial vs excluded bands (docs/ change approved by the user 2026-11-13).
- Component labels stay in `COMPONENT_LABELS`; unknown device names fall back to "device".

### D4. ML training
- Training reads `slot_observations` in `ml/train.py::_load_raw_slot_observations` (four SQL branches that already select `quality_flags`), consumed by `load_clean.clean_load_observations` through `load_clean_load_observations`, and by `_load_slot_observations`. The new rule goes in `ml/load_clean.py` as a pure function applied inside `clean_load_observations`, so both the training and the load-inference path use it. `_load_slot_observations` (price/PV callers) gets the same rule via a shared helper only if it feeds load; PV training does not use load and is unchanged.
- Rule: drop a row when `recording.components` has `unknown` for any device component or for `load`, or when any device component is `snapshot` or `mixed` (its subtracted energy is a live reading or a fake 0, so the base load is not measured). The rule reads the device components (every device name, via the shared helper), not `load=mixed`: `load=mixed` is also set for enabled devices without a sensor (`unconfigured_zero`), and dropping those would discard all training data for such users. `unconfigured_zero` devices do not drop a row, as today. This also drops legacy rows such as cmon89's fake 0 `ev=snapshot`, without rewriting history. Rows without `recording` are untouched.
- Other ML consumers of slot load: `ml/evaluate.py` raw SQL (metrics only; apply the same helper to its dataframe), `learning/store.calculate_metrics` MAE (filtered in SQL by the shared `unmeasured_device_clause()` in `backend/learning/models.py`, a `json_each` over `recording.components` that mirrors `has_unmeasured_device` exactly and guards malformed JSON with `json_valid`; used by store metrics, the forecast router MAE and the energy base-load average), forecast router MAE (`backend/api/routers/forecast.py` lines ~136 and ~428): excluded the same way. Anything fed by `energy.py` base-load average (`_base_load_avg`, line ~64): excludes those slots and counts only remaining slots toward the existing 87-slot threshold.
- Counts: `dropped_unmeasured_device_rows` in the clean stats, `learning_runs.result_metrics_json` and the sidecar, as the existing dropped counts.

### D5. Consumer review
- `energy.py` range and daily totals: show device kWh from the placeholder; no change to sums, but the response adds `unmeasured_slots_by_component` (counts, from quality_flags) so the UI can note understatement. The EV cost attribution query is unchanged (0 EV means 0 attributed cost, correct as "unknown"); base-load average changes per D4.
- Monitors `_eval_energy_balance`: residual is broken by an unknown device (EV 0 placeholder). Slots with an unknown device component are skipped in that invariant, so no false violation. `data_quality` monitor unchanged.
- `backfill.py`: sets `ev`/`water` methods by its own rule; backfill rows are already `not_recorder` and excluded from the comparison and training. It writes `unknown` for a device whose history is None instead of summing `or 0.0` (generalised from water); no further change.
- `battery_benchmark`: `slot_recording` currently returns None for any method outside clean and snapshot, so unknown devices make the whole day `not_clean_recording`, exactly the cmon89 failure. Apply the same rule: unknown device component with `load=derived_history` and live SoC is a "partial" slot, counted in a new `partial_slots` next to `snapshot_slots` and reported as the `partial_slots` warning. Because demand `load + water + ev` is exact for such a slot, partial slots do NOT count toward `MAX_UNVERIFIED_SLOTS` (unlike snapshot slots); unknown `load`, `import`, `export` or battery methods stay None. The demand `load + water + ev` stays correct for the same reason as D2.
- `comparison_history`: annotation and manifest only; the column list is unchanged. No change except that `unknown` provenance must pass through `parse_recording` unmodified (covered by a test).
- `validation.py`: see D1.
- Schedule router: `actual_ev_charging_kw` (line ~254) returns null when the slot `ev` component is unknown, mirroring `actual_water_available`; adds `actual_ev_available`. The store builds it from the same quality flags as `actual_water_available`.
- `observation_provenance.py` and `store.py` write paths: `unknown` method passes through; verify the merge rules in store.py keep `unknown` and do not coerce to measured when a later row merges.

### D6. Tests
Backend: recorder EV unavailable, water unavailable, both, snapshot present versus absent; comparison: EV unknown included and partial, import missing still excluded, load unknown excluded, battery flows required, parametrised guard over every device component name that none can drop a slot while import and export are measured, both unknown with zero load excluded; spans and coverage; training exclusion; monitor skip; benchmark partial; schedule router null EV; validation spike. Frontend: notes text for EV 26 h 15 min and both devices, unbroken line, no partial data, API parsing.

## Risks / Trade-offs

- Partial slots price grid-only demand from a derived load that includes the device energy; correct when total load was measured, understated when load is `snapshot`/`mixed`. Those slots are marked partial with the component, which is the accepted trade-off.
- Existing stored rows with fake `snapshot` for EV (like cmon89) stay as stored; they become partial under the new rule without rewriting history. Training drops them through the device-component rule (D4); rewriting stored rows is out of scope.
- Adding `partial_*` response fields is additive and optional for old clients.

## Migration Plan

No data migration or schema change. Rollback is a code revert.

## Open Questions

None.
