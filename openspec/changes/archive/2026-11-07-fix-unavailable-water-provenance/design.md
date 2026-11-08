# Design

## Context

See proposal.md for motivation. Verified current behaviour (read from code and, read-only, from the prod database):

- `backend/recorder.py` already builds `recording.components.water = {method: unknown, owner: recorder}` when every water source is unavailable (`aggregate_method` returns `unknown` if any device is `unavailable`), and sets `record["water_kwh"] = None` (~578-583). The load method stays `derived_history`.
- `backend/learning/store.py` `store_slot_observations` (~245-300) only takes incoming provenance for a column when `has_measurement(column)` is true. With `water_kwh = None` it takes the `elif existing` branch (keeps `old_meta`, else `{method: unknown, owner: unknown}`) or, for a new row, the `elif column in {...}` branch (stores `0.0` and writes no water component at all). The `water_kwh` column is `NOT NULL DEFAULT 0`, hence the stored `0.0`.
- `backend/grid_only_comparison.py` `_recording_is_eligible` (~137-150) accepts `unknown` water only for `owner == "recorder"`, so `owner: unknown` (or a missing component) is rejected. `_slot_costs` already treats null water as 0 and applies the clamp guard.
- Prod rows 2026-11-05 08:15 to 12:00 (16 slots) have `water.method=unknown, water.owner=unknown`, `water_kwh=0.0`, `source=recorder`, `load.method=derived_history`, no `water_heater_energy`. The 08:00 and 12:15 slots are `power_history`, owner `recorder`.
- Partial slots: `parse_power_points` skips `unavailable` states and `integrate_power_points` returns None without any valid point in the window, else it holds nothing before the first valid point. So 08:00 (unavailable from 08:00:26) and 12:15 (available again 12:23:50) integrate over their valid part only, are `power_history`, and the unavailable minutes count as 0 water. This is harmless for the comparison: `load = total - water` under `derived_history`, so `load + water + ev` still equals the metered total.
- `grid-financial-wear-display` (main spec) requires lines and shading not to connect across excluded slots. The chart draws nothing for an excluded span in comparison mode (`CostSeriesChart.tsx` ~249-304 builds only from `comparison.segments`), and the card shows only "(N excluded)" (`CommandDomains.tsx` ~528).
- Exclusions happen in `_recording_is_eligible` and `_slot_costs` (`grid_only_comparison.py` ~93-277) and in `build_grid_only_comparison` (no row, or more than one row, for an expected slot). `excluded = total - covered` carries no reason today. A row with a misaligned or naive start is dropped before matching, so it appears as `missing_slot`; a separate invalid-time code is not needed.
- Existing reason pattern: `backend/battery_benchmark.py` records one `reason` string per day and aggregates `by_reason` counts. The new fields mirror it (`reason` per span, `excluded_by_reason` counts).
- `frontend/src/lib/api.ts` validates only known fields of the comparison, so additional fields are tolerated by the current client.

Corrections to the brief: the recorder already emits recorder-owned `unknown`; the defect is that the store discards it. The "pre-created placeholder" is not a distinct object: the `unknown/unknown` metadata is the store's fallback for an existing row without water metadata, and a brand-new row ends up with no water component at all. Both paths fail the comparison. What creates the pre-existing row for each affected slot was not identified (the recorder writes once per quarter; backfill is non-authoritative); the fix must cover both paths.

## Goals / Non-Goals

**Goals:**
- A fully unavailable water sensor yields recorder-owned `unknown` provenance for every affected slot, for new and existing rows, so the existing comparison exception applies.
- Never lose or downgrade a measured value or its provenance.
- Make every excluded slot visible with a reason (response, chart band, note), following the design system.
- Universal behaviour: no sensor names, times or thresholds specific to one installation.

**Non-Goals:**
- No change to eligibility rules in `grid_only_comparison.py`.
- No change to how partial slots are classified (see Decision 4).
- No repair of already stored slots (decided, see Decisions).
- No change to which slots are eligible; no metered-cost overlay across excluded spans (dropped by the owner).

## Decisions

1. **Fix in the store, not by faking a measurement in the recorder.** For an authoritative write where the incoming recording has a component with method `unknown` owned by the writer and the value is absent, the store records that component's metadata (owner set to the writer) and keeps the stored value (`0.0` for a new row). It does not set `accepted_measurement`, so legacy attestation and `water_heater_energy` handling are unaffected by the unmeasured case. Scope: the water component only, since EV and load `unknown` must stay rejected and only water can legitimately be absent.
   - Alternative: recorder writes `water_kwh = 0.0` so the existing `has_measurement` path accepts it. Rejected: it turns "not measured" into a recorded zero, removes the null signal that `_slot_costs` and tests rely on, and `validate_energy_values` could then mark it differently.
   - Alternative: relax `_recording_is_eligible` to accept `owner: unknown`. Rejected: it would admit backfill and legacy rows whose unknown water has no recorder attestation, weakening a deliberate guard.
2. **Order of precedence on merge.** Incoming recorder `unknown` is applied only when the existing water metadata is absent, `unknown`, or owned by `unknown`/`backfill` with no measured method. If the existing component has a measured method (`power_history`, `snapshot`, `mixed`, `derived_history`, `disabled_zero`) the existing value and metadata win. Non-authoritative writes keep their current rules (they cannot touch recorder-owned data).
3. **Per-device metadata.** Store `water_heater_energy` with `energy_kwh: null`, `coverage: unavailable` when the recorder supplies it for an unmeasured slot, so the per-device record is truthful. This needs a check that `parse_water_heater_energy_metadata` and its readers handle null energy; if any reader breaks, drop this and leave the key absent (current behaviour). It does not change eligibility.
4. **Partial slots stay `power_history`.** 08:00- and 12:15-style slots have a real integration over their valid part (after Decision 8 both integrate only valid intervals); the unavailable minutes contribute 0 water and the derived load absorbs the difference, so the grid-only bill is exact (`load = total - water - ev`, so `load + water + ev` equals the integrated total whatever the water integrates to; water integrating over less time can only lower the clamp risk). Marking them `unknown` would add noise without changing any cost. Called out in tests so the behaviour is intentional. Re-checked against the code after Decision 8: nothing in the recorder, store or comparison needs a partial-coverage class, so the decision stands.
5. **Exclusion reasons in the response (additive).** `_recording_is_eligible` and `_slot_costs` are refactored to return the first failing check as `(reason, component)` while the boolean outcome stays identical; `build_grid_only_comparison` adds `missing_slot` and `ambiguous_rows`. Codes, in check order: `missing_slot`, `ambiguous_rows`, `battery_cost_invalid`, `not_recorder` (source, placeholder, backfill), `user_excluded` (exclude flag, exclude-from-comparison annotation), `unsupported_provenance` (schema, semantics, components malformed), then per component `unconfigured_sensor`, `estimated_component` (snapshot or mixed), `unknown_component` (unknown, or not recorder-owned), `battery_disabled_zero`, then `missing_price`, `missing_energy_value`, `clamp_hidden_demand`, `disabled_nonzero`. The suggested `estimated_load` became `estimated_component` because snapshot/mixed applies to any relevant component, not only load; `legacy_schema` became `unsupported_provenance` (a `recording` of `None` is valid legacy data and stays eligible); `invalid_slot_time` was dropped (see Context). The first failing check wins, which is simply the order the code already evaluates, so the reason is deterministic and needs no priority table to keep in sync.
   - Response: `excluded_spans: [{start, end, slots, reason, component}]` (local ISO with offset, end exclusive, `component` null when not applicable), maximal runs of contiguous slots with the same reason and component, chronological; and `coverage.excluded_by_reason: {code: slots}`. Both always present; `excluded_spans` slots and `excluded_by_reason` values each sum to `excluded_slots`. Existing fields are untouched; the frontend treats the new fields as optional and ignores them if malformed.
   - Guard: a parity test runs a matrix of slots through the old boolean logic (kept in the test as a reference copy) and the new code to prove eligibility is unchanged.
   - Alternative: reason strings built in the route or frontend. Rejected: the checks live in one backend module and the frontend cannot see provenance flags.
   - Alternative: only a count per reason, no spans. Rejected: the chart needs positions.
6. **Chart and card.** Bands: one `<rect>` per span from the response (epoch ms, so DST-safe), `fill-muted` low opacity plus a hatch pattern or edge line so it is not colour alone, `data-testid="cost-excluded-span"`, drawn under the lines; DS and Grid-only paths untouched. Note: the card's coverage line keeps "Completed through ... N of M slots (K excluded)" and adds one line per reason group, largest first, at most two groups then "and N more reasons", text from a fixed code-to-phrase table (for example `unknown_component` + `ev` gives "EV charger not measured", `unknown_component` + `water` gives "water heater not measured", `missing_slot` gives "not recorded", `missing_price` gives "price missing", `clamp_hidden_demand` gives "demand may be hidden by EV or water", `not_recorder` gives "backfilled data", `user_excluded` gives "excluded by you"). Unknown future codes fall back to "not compared". Existing warning style (`text-warn`) as used by the water-unmeasured note. Owner decision: the reason notes stay inside the ⓘ bill-details popover (`#grid-only-bill-details`), under the "Completed through ... (K excluded)" line, together with the water-unmeasured note. The card's always-visible line only shows the coverage percentage and the ⓘ button; the band and the hover readout on the chart are the always-visible cues. Hover or focus on a bucket overlapping a span adds a readout line naming the reason and time range. Stored data cannot tell an unavailable sensor from one with an empty sensor entry (both are method `unknown`), so water text says "not measured", not "unavailable".
   - Layout sketch below; the UI tasks are gated on the owner approving it.
7. **Repair of stored slots: decided, do nothing.** The 16 prod slots (2026-11-05 08:15-12:00) keep `owner unknown`; they now appear as a labelled band ("water heater not measured") instead of a silent gap. No script, no annotation, no read-time rule.
8. **Integration ends the hold at an unavailable state (all callers).** Verified mechanism: `parse_power_states` (`backend/core/ha_client.py`) drops states whose value is `unknown`, `unavailable`, empty or unparsable, so `integrate_power_points` sees the previous valid point as the current one until the next valid point. Fix at the shared parse/integrate pair, not per metric: `parse_power_states` keeps such a state as a gap marker `(timestamp, None)` (`PowerPoint = tuple[datetime, float | None]`, still time-sorted, still learns the unit from it); `integrate_power_points` sets the held value to none at a gap, accumulates only while a valid value is held, and returns None when no valid interval overlaps `[start, end]` (this also covers a window that lies entirely inside an unavailable period, or before the first valid point, where the old code returned `(0.0, 0.0)` or held a stale value). Example: 2 kW valid 26 s then unavailable gives 2 x 26/3600 = 0.0144 kWh. The first valid state after a gap resumes the hold from its own timestamp, so a 12:15-style slot integrates from the return time.
   - Callers (all verified): the recorder per metric through `compute_slot_energy` (pv, load, grid, battery, EV, water; None falls back to the snapshot or `unknown` as before); `backfill._build_record` through the same function (a metric with no valid interval is now None instead of a held value or a measured zero, and `BackfillEngine.integrate_slots` then skips the slot, see decision 11; `_value_at` for SoC returns None inside a gap instead of the stale value); `get_load_profile_from_ha` (valid-point count must exclude gap markers, gaps simply add no energy); `get_energy_from_power_history`; `water_progress._history_energy`, which already tracks gaps itself and only needs the markers filtered out of its valid-sample lookup. No water-specific code.
   - Not every non-reading state is "unavailable" in HA, but a numeric power sensor reporting text is equally not a measurement, so empty and non-numeric states end the hold too (the main spec previously listed them with `unknown` and `unavailable`).
   - Trade-off: for a metric whose own sensor flaps (for example the total load sensor) a partially unavailable slot now records the energy of the valid part only instead of an extrapolated hold. That is the specified correct behaviour (no invented energy); the slot is still `power_history`. The grid-only comparison stays internally exact because it uses only recorded components.
   - Alternative: drop the unavailable period from a slot-level scale-up (extrapolate the valid mean). Rejected: invents energy.
   - Alternative: keep `PowerPoint` floats and use NaN as the marker. Rejected: an implicit convention every consumer must remember; `None` is checked by the type checker.
9. **Time ranges use an en dash.** `ChartCard.logic.ts` (`formatTimeRange`, `formatRangeFromLabel`) and the settings editors print ranges as `14:15–14:30` with U+2013 and no spaces. The excluded-span readout in `CostSeriesChart.tsx` followed the same pattern with a hyphen and now uses `–`; the design-system example text follows.
10. **Axis tick labels are laid out against the measured width.** The tick positions are percentages and the labels have a fixed pixel size, so whether two labels overlap depends on the width; on a 25 h fall-back day the repeated `02+2`/`02+1` labels sit 4 percent apart and collided with `00:00`/`05:00` on a narrow card. This predates the change: `buildTicks` and the tick rendering are identical in `HEAD`; the change only added a fixture that shows it. Fix: a pure `layoutAxisTicks` (in `frontend/src/lib/costAxisTicks.ts`) takes the ticks and the chart width in pixels, estimates each compacted label's width from its character count plus a gap, and places ticks in priority order (axis start, axis end, repeated-hour labels, then the rest). A tick keeps its preferred row, tries the other row if that collides, and is dropped if both collide, so no two labels in a row ever overlap at any width. The chart measures its own width with a `ResizeObserver` (layout effect, no flash). Width unknown (no layout, as in jsdom) leaves the ticks unfiltered. The full label stays in the `title`.
11. **Backfill writes a slot only with measured core data.** Verified before this decision: gap markers made the day-level check in `BackfillEngine.integrate_slots` (`any(series.get(entity))`) true for a fully unavailable day, because a list of `(ts, None)` markers is truthy. `_build_record` then produced a record with `load_kwh = None`, `pv_kwh`/`import_kwh`/`export_kwh` unset or 0.0, `water_kwh = 0.0` (method `unknown`, owner `backfill`) and the store wrote it. The columns `import_kwh`, `export_kwh`, `pv_kwh`, `load_kwh`, `water_kwh`, `ev_charging_kwh` are `NOT NULL DEFAULT 0` (`SlotObservation`), and `store_slot_observations` writes `0.0` for a new row when the incoming value is absent (the `elif column in {...}` branch). A probe of the old path stored `import=0.0, export=0.0, pv=0.0, load=0.0, water=0.0, ev=0.0, soc_end=NULL` for a fully unavailable slot. Aurora training and the forecast and evaluation MAE read these columns as numbers. A partial case was affected too: a configured PV sensor in a gap with a valid load sensor stored `pv_kwh = 0.0` next to a real load, which `ml/train.py` (`load_kwh > 0.001`, then `pv_kwh`) consumes as a PV training sample of zero.
   - Rule: `integrate_slots` drops a slot when any of `pv_kwh`, `load_kwh`, `import_kwh`, `export_kwh` is None after `_build_record`. These four are the NOT NULL energy columns that training, stats and the benchmark treat as measurements. A source that is not configured or is disabled integrates to a real `0.0` (`unconfigured_zero` / `disabled_zero` provenance) and is not affected; None therefore always means a configured sensor with no valid interval in that slot. A skipped slot leaves no row, so nothing downstream can mistake it for data, and the next run retries it because the last stored observation does not advance (capped at 10 days).
   - Day-level check: it now tests for a valid (non-None) point instead of a non-empty series, which restores the old early return for a fully unavailable day.
   - Not core, kept as is: water and EV are NOT NULL too, but they are not a basis for load or PV training; an unmeasured value keeps `unknown`/`mixed` provenance (like the recorder) and is 0 only for load isolation. Battery charge/discharge and SoC are nullable and stay NULL when there is no history.
   - Trade-off: a sensor that is permanently unavailable for part of the day (for example a PV inverter that goes offline at night) now stops backfill from writing those slots. The recorder is unchanged and keeps recording live slots; only the gap-fill after downtime is narrower. Preferred over writing a fabricated 0 that the models would learn.
   - Alternative: relax the schema to NULL. Rejected: schema changes are out of scope and every reader would need a NULL guard.
   - Alternative: write the row with `exclude` flags. Rejected: readers other than `ml/train.py` (evaluate, forecast MAE, graduation) do not check the flag.

### Layout sketch (narrow mobile PWA card, about 360 px)

Amended by owner decision: the "Completed through" line and the `!` reason notes at the bottom of the sketch are shown inside the ⓘ bill-details popover, not under the chart. The chart, band, x-axis and hover readout are as drawn.

```
+------------------------------------------+
| Actual cost so far              -12.40 kr|
| DS ____  Grid-only ....                  |
|  kr                                      |
|   0 +--DS--\          ///////     /---   |
|     |       \         ///////    /       |
|     |        \_______ ///////___/        |
|     |  . . . . . . . ///////. . . . . .  |
|     +--------+--------+-------+-------+  |
|     00       06   08:15  12:15   18      |
|                  [hatched muted band]    |
| (hover/tap) 10:00 - 3.2 kr import / 0.4  |
|   export - Not compared: EV charger      |
|   not measured (08:15-12:15)             |
|                                          |
| Completed through 14:15 - 40 of 56 slots |
| (16 excluded)                            |
| ! 3 h not compared: EV charger not       |
|   measured                               |
| ! 1 h not compared: price missing        |
|   and 1 more reason                      |
+------------------------------------------+
```
The band is full chart height and hatched (not colour alone); notes use the existing warning text style and wrap on narrow widths; no new colours or tokens.

## Decisions (addendum): bucket readout on touch

Pre-existing bug in `CostSeriesChart.tsx`: a touch tap fires emulated `mouseenter` and `focus` (both set the hover) and then `click`, which toggled it back to null, so the readout only appeared on the second tap (seen with CDP touch emulation).

- Follow the pattern in `TransferFeeRulesEditor.tsx`: hover via `onPointerEnter` ignoring `pointerType === 'touch'`.
- A ref records the pointer type of the press (`onPointerDown`). `onFocus` shows the readout only when no pointer press is in progress (keyboard focus), so a tap's focus no longer opens it before the click.
- Click semantics: touch toggles (tap opens, same bucket closes, another bucket switches). Mouse and keyboard clicks (Enter/Space) only set the bucket and never close it, because hover or focus already shows it; this avoids flicker. Blur hides; leaving the chart with the mouse still clears (unchanged desktop behaviour).
- Tapping outside the chart clears via the existing container `mouseleave`.

## Risks / Trade-offs

- [Store change touches the recorder provenance merge, which is dense and heavily tested] -> Limit to water and the absent-value branch; add tests for new row, existing row with and without metadata, measured-existing, backfill; run `tests/test_observation_provenance.py` and `tests/test_grid_only_comparison.py`.
- [Unmeasured water now counts as covered, so coverage rises and the existing "Water not measured for N h, included" note appears] -> This is the specified behaviour; note wording already exists.
- [Refactoring eligibility checks to return reasons could change which slots are eligible] -> Parity test against a reference copy of the old boolean logic over a full matrix of provenance and value cases.
- [Notes could get long with many reasons] -> At most two groups plus a count.
- [Partial slots recorded as measured even though some minutes were unavailable] -> Documented non-goal; cost impact nil under derived load.
- [Anything built on `water_kwh` itself (water statistics, learning) will read `0.0` for unmeasured slots] -> Unchanged from today; provenance now says `unknown` with owner `recorder`, which consumers may use.
- [`docs/design-system/AI_GUIDELINES.md` edit] -> AGENTS.md says ask first for docs changes; the task list holds it until approved.
- [UI built before the layout is agreed] -> UI tasks are explicitly gated on the owner's approval of the sketch.

## Migration Plan

No schema change. Deploy backend and frontend together (the frontend tolerates a backend without the new fields). Slots recorded after deploy carry the new provenance. Rollback is a plain revert. Already stored slots keep `owner: unknown` (decision 7).

## Open Questions

- Should slots that are excluded today for `estimated_component` (snapshot/mixed load), `unknown_component` on EV, or `clamp_hidden_demand` be included with a visible note, as unmeasured water is? Not decided and not part of this change. Inclusion would change eligibility and totals, so it needs its own analysis of when `load + water + ev` still equals metered demand for each case.
- Should "water heater not measured" distinguish a sensor that was unavailable from one that is not configured? It needs a recorded distinction that does not exist today.

## Addendum: load profile averaging follow-up

Decision 11's gap markers made `integrate_power_points` end the hold at `unavailable` and `unknown` states. `get_load_profile_from_ha` still divided every slot by the 7 days fetched, so a sensor outage counted as zero load and pulled the baseline down (before the change the last value was held, which hid the problem). This was found before commit and fixed in the same working tree:

- `integrate_power_points_covered` returns `(positive_kwh, negative_kwh, covered_seconds)`; `integrate_power_points` keeps its two-value shape for the other callers.
- The profile accumulates energy and covered seconds per local slot (apportioned identically across the UTC grid) and sets each slot to energy over covered time, scaled to 900 s. This is a power-based mean, exact for partly covered slots, where a per-slot day count would weight a 5-minute reading like a full day. A 25 h DST day no longer inflates the repeated hour; a 23 h day no longer deflates the skipped one.
- A slot with under one slot length of valid data in the whole window is interpolated circularly from its nearest measured neighbours. With fewer than 48 of 96 slots measured the profile is discarded (fallback and degraded message naming the sensor), because the shape of the day would be mostly guessed. Constants are universal, not per installation. The 500 kWh/day bound and existing messages are unchanged.
- Two tests asserted the old divide-by-7 result and were updated: the DST fall-back slot (was 8/7 of the mean) and the unavailable-lead-in-watts test (was 24 - 1/3600 kWh).

Spec: `energy-recording`, requirement "Load Profile Averages Over Measured Time". The pending `load-profile-fetch-resilience` builds on this.
