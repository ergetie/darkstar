# Proposal

## Why

`load_kwh` is documented as base load (total load minus EV and water), but the store can hold a number that is not a base load and nothing says so. Verified on prod (2026-11-22): 978 slots (2026-03-09..08-24) have `load_kwh = 0` with `water_kwh > 0`. The old recorder took total load from a quantised, lagging cumulative counter and water from power history; subtracting mismatched time bases clamped the heater slot to 0 and inflated the next one. The current recorder integrates both from power history and has produced zero clamps since 2026-10-07, so the cause is gone. Four gaps remain in the current code and the old rows are still trusted:

- `isolate_base_load` clamps a negative result to 0 and stores it as a trusted measurement.
- A water or EV sensor with partial history coverage is integrated over the covered part only. The uncovered part of a heater run stays in base load (up to about 3 kW overstated; prod gaps 2026-11-03, 11-05, 11-11..13). A fully unavailable sensor is already marked `unknown`.
- Stray 1-2 W readings become tiny water energy when `idle_power_threshold_kw` is 0 (3,926 prod slots with 0 < water < 0.01 kWh).
- A heater that is disabled or excluded by `has_water_heater: false` while its power sensor still reads non-zero is recorded as `disabled_zero`, so its energy lands silently in base load (prod 2026-10-07..11-01, about 55 kWh).

Project rule: missing or unreliable data is stored as unknown, never as a fake 0, and models never learn from it.

## What Changes

- The recorder and backfill share one base-load isolation that reports when the subtraction went negative, instead of silently clamping.
- Slots whose base load is not trustworthy get a new `quality_flags.base_load` object (`reliable: false` plus reasons). Reasons: `negative_after_subtraction`, `device_partial_coverage`, `load_partial_coverage`, `inactive_device_drawing_power`, and for migrated history `legacy_counter_clamp`, `legacy_counter_after_clamp`, `device_disabled_but_configured`.
- The existing `unmeasured_device` predicates (Python and SQL twin) also treat `base_load.reliable == false` as unmeasured, so every consumer that already filters on them is covered automatically. Consumers that do not filter yet are listed in design.md and get the filter.
- A clamp additionally sets the `load` component method to `unknown`, so demand-based consumers (grid-only comparison, battery benchmark, calibration) also drop the slot.
- Partial coverage of the devices and of total load (`load_power`) is detected from `integrate_power_points_covered`; sensors of heaters/chargers that are disabled in config are watched and a non-zero reading is flagged and warned about once per sensor.
- Water active-power normalisation gets a built-in noise floor (named constant) so a configured cutoff of 0 no longer turns 1-2 W into energy.
- A one-time idempotent data migration flags existing rows using `quality_flags` only, identifying old-recorder rows per row (no `quality_flags.recording`), never by date. It logs counts per rule. No schema change.
- Cumulative-counter load is not reintroduced (explicitly specified).

## Capabilities

### New Capabilities
- `base-load-integrity`: when a recorded base load is reliable, how unreliable slots are flagged, which consumers skip them, and how historical rows are flagged once.

### Modified Capabilities
- `energy-recording`: "Load Isolation from Deferrable Loads" (negative result is flagged, not silently trusted), "Consistent per-heater active-power normalization" (noise floor), "Unavailable device sensors are recorded as unknown, never as fake zero" (partial coverage, inactive-but-configured devices).
- `load-training-data-quality`: "Slots with an unknown device component are not trained on" also covers slots flagged `base_load.reliable == false`.

## Impact

- Code: `backend/core/slot_energy.py`, `backend/recorder.py`, `backend/learning/backfill.py`, `backend/core/water_heating.py`, `backend/measurement_provenance.py`, `backend/learning/models.py`, `ml/load_clean.py`, `ml/forward.py`, `backend/learning/store.py` (flag merge), `backend/api/routers/{forecast,schedule}.py`, `backend/observation_provenance.py`, `backend/battery_benchmark.py`, `backend/grid_only_comparison.py`, new `backend/learning/base_load_migration.py`, startup hook in `backend/main.py`.
- Data: one-time flagging of old `slot_observations` rows. No column change, no values deleted. Reversible by removing the `base_load` key.
- Schema: none. Making `load_kwh` nullable would need a SQLite table rebuild (column is `NOT NULL` in the baseline) and was rejected, see design D1. If that is wanted later it needs separate approval.
- Dependencies: none.
- Docs: `docs/` is not edited; a note about the idle-threshold floor is a follow-up only.
