## Context

`has_water_heater` is checked in about 15 places but `water_heaters[]` is read directly in many more. The vacation anti-legionella branch is the known leak. Audit, with line numbers as of HEAD 0f7e0407:

| Path | Result |
|---|---|
| `planner/pipeline.py:1856-1860` anti-legionella rebuild from `water_heaters_cfg` | Bug, fixed in plan |
| `pipeline.py:1445-1456` `water_heaters_cfg`, `enabled_heater_ids` (mid-block, today-kWh lookups) | Fixed in plan (use helper) |
| `pipeline.py:1725` post-hoc clear when flag off | Kept as defence in depth, no longer the only guard |
| `pipeline.py:1315`, `1599` | OK (gated) |
| `pipeline.py:1816-1840` vacation branch DB read/write of anti-legionella | Fixed in plan (skipped when flag off) |
| `planner/solver/adapter.py:539-545` | Fixed in plan (use helper) |
| `backend/core/water_heating.py:75`, called from `ha_client.py:485`, `forecasts.py:783`, `config.py:825` | Fixed in plan (stale values could block planning and save) |
| `backend/loads/service.py:43-62` `LoadDisaggregator` | Fixed in plan (registers water loads regardless of flag) |
| `backend/ha_socket.py:111` | Fixed in plan (default `False` is inconsistent with all other readers, which default `True`; use the helper) |
| `backend/health.py:505, 673, 773` | OK |
| `backend/api/routers/config.py:927`, `:1071`, `:1086` | OK (the 1071 and 1086 warnings sit inside the flag-true block at 927) |
| `backend/core/ha_client.py:680` | OK |
| `backend/core/readiness.py:245` | OK |
| `backend/recorder.py:432-441` | Bug, fixed in plan. `aggregate_method` returns `disabled_zero` when flag off, but `:440` then overrides to `unknown` for any enabled entry without `sensor`. `grid_only_comparison.py:120` rejects `unknown`, so the day is unusable. Earlier audit "OK" was wrong for this config |
| `measurement_provenance.py:66`, `slot_energy.py:94`, `learning/backfill.py:135` | OK |
| `executor/engine.py` (362, 681, 1001, 2073) | OK |
| `backend/api/routers/water.py` | OK (executor refuses boost) |
| `backend/api/routers/schedule.py:335, 407, 515-560` | Fixed in plan (historical water fields shown) |
| `Dashboard.tsx:258` | OK (flag read, default true) |
| `PowerFlowRegistry.ts:97` plus `PowerFlowCard.tsx:93` | OK (`false` hides the node) |
| `CommandDomains.tsx:851` | OK |
| `Dashboard.tsx:575, 669` boost banner, `CommandBar.tsx` heater selector, water pills and vacation controls, `Dashboard.tsx` vacation banner | Fixed in plan |
| `ChartCard.tsx:409-415, 471, 1334` | Fixed in plan |
| Settings Heating tab (`settings/index.tsx:38`, `WaterTab.tsx`) | Reachable by design (existing test `SettingsNavigation.test.tsx` and the `settings-ux` behaviour); notice added |
| `backend/core/entity_roles.py` | OK (setup wizard hints only) |

## Decisions

1. Helper `active_water_heaters(config)` in `backend/core/water_heating.py`. It is pure, takes the full config, and imports nothing from the planner. The planner and backend already share `backend.core`, so there is no layering issue.
2. Fix at the source: `pipeline.py` derives `water_heaters_cfg` from the helper right after `has_water_heater`. The anti-legionella branch and the adapter then cannot see heaters. The vacation branch is additionally wrapped in `if has_water_heater` for the DB record logic.
3. `validate_water_heating_config` is the one validator gated by flag. Other validators already are.
4. The schedule router gates on the flag at the response boundary for planned/not-yet-completed slots only; completed slots keep their history, and there is no data migration.
5. BACKLOG.md line 60 note: currently inaccurate, because the vacation branch plans heating and validation can error on stale values. It becomes accurate after this change. The docs are not edited here (docs/ needs approval).

6. Recorder: `water_config` comes from the helper, so with the flag off it is empty and `aggregate_method` yields `disabled_zero`; the `:440` override then only sees active heaters.

## Rescoring already-recorded `unknown` days

Not part of this change. The rows hold `water_kwh = 0` and `recording.components.water.method = unknown` in the existing `quality_flags` text column, so a rewrite needs no schema change. But the existing annotation tool (`scripts/annotate_comparison_history.py`, `comparison-history-provenance`) only edits comparison-owned metadata and rejects replacing recorder-owned provenance, and unknown intervals must stay unknown without evidence. A rescore would be a new one-off, dry-run-first, backup-first script limited to slots where the flag was provably off. Listed as a user decision.

## Vacation mode scope (verified)

Vacation mode affects water heating only: `backend/strategy/engine.py:46-55` zeroes water min hours/kWh, `planner/pipeline.py:1804-1860` runs anti-legionella, and `backend/api/routers/analyst.py:175` only advises about water. CommandBar writes only `water_heating.vacation_mode`. So hiding the vacation controls and banner when the flag is off is the default.

## Grid-only inclusion of unmeasured water (part 2)

Why it is exact: with load method `derived_history`, `load_kwh` comes from `energy.load` minus measured EV and water (`slot_energy.isolate_base_load`). Unmeasured water is subtracted as 0, so `load + water(null as 0) + ev` equals total metered load. Not exact on the disaggregator/snapshot load paths (`recorder.py` ~460/464) or when the clamp hits.

Rule in `_recording_is_eligible`/`_slot_costs`: water `unknown` is accepted only if load method is `derived_history`, EV method is eligible, all other components eligible, and NOT (`ev_charging_kwh > 0` and `load_kwh == 0`). Clamp detection: the clamp is not stored, but it can only occur when `ev + water > total`; with unmeasured water (0) that needs EV above 0 and yields exactly `load_kwh == 0.0`. Rejecting that pair is conservative (may drop a rare real zero-load EV slot). `water_kwh` null becomes 0.0 in `_slot_costs`. EV and load `unknown` (from `validate_energy_values` zeroing) stay rejected. Note: because `load_method` is `derived_history` only when water is not snapshot/mixed/unconfigured_zero, `unknown` water does not by itself make load `mixed`.

Response: `coverage.water_unmeasured_slots` and `water_unmeasured_hours` (slots x 0.25), always present. Counted among covered slots; status unchanged. UI (`CommandDomains.tsx` near the coverage line ~509) shows a small warning-styled note per `docs/design-system/AI_GUIDELINES.md` (existing warning token, no new colours). Real data: Kristofer ~851 slots become included; torleif unaffected.

## Risks


## Rebase notes (HEAD 0f7e0407)

- Rebased over `robust-sensor-reading`, `ev-delivered-energy-guard`, `pv-forecast-partial-fallback`, `ev-single-phase-grid-limit` and `backlog-quick-fixes`. None of them touch the water paths above except `backlog-quick-fixes` (`infer_control_type`, heater-pairing validation, disabled-heater warnings, settings heater errors), which all sit inside the `has_water_heater` true block in `_validate_config_for_save`, so flag off already means no heater validation or warnings there. `active_water_heaters(config)` does not replace that gate and is not used by the validator; `validate_water_heating_config` has its own early return.
- `water_heaters_cfg` in the pipeline is now the helper result (enabled, with id), so the anti-legionella rebuild only sees heaters that are active.
- Tasks 1.x use the helper in `adapter.py` too: a heater without an id is still skipped by `build_water_heater_inputs` exactly as at HEAD; the helper itself does not filter on id, so recorder and socket behaviour for id-less heaters is unchanged.

## Decisions recorded by the user

- Heating tab stays reachable with an informational notice.
- Vacation controls and banner are hidden when the flag is off (vacation affects water only).
- PLL's old days are not rescored by a script. Part 2 (unmeasured-water slots included with a note) makes them count again.
- EV-unknown and load-unknown slots stay excluded.

## Open product decisions (resolved above)

Defaults encoded in the specs and tasks (change only if the user objects):
- Heating settings tab stays reachable with a "disabled" notice (task 3.4).
- Vacation controls and banner hidden when the flag is off (task 3.1, 3.2), because vacation mode affects water only.

Resolved: no rescoring script (see Decisions recorded by the user).
