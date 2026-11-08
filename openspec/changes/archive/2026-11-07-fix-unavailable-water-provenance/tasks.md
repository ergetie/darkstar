# Tasks

## 1. Store: keep recorder-owned unknown water provenance

- [x] 1.1 Reproduce with a failing test in `tests/test_observation_provenance.py`: a recorder write with `water_kwh=None` and incoming water `{unknown, recorder}` for (a) a new row, (b) an existing row whose water metadata is absent, (c) an existing row with `{unknown, unknown}`. Verify all three fail before the fix.
- [x] 1.2 In `backend/learning/store.py` `store_slot_observations`, accept incoming recorder `unknown` water metadata when the value is absent and the existing component is not a measured method; keep the stored value (0.0 for a new row); do not set `accepted_measurement`. Verify the 1.1 tests pass.
- [x] 1.3 Test that an existing measured water value and provenance are never downgraded by a later all-unavailable recorder write, and that a non-authoritative write cannot overwrite recorder-owned water. Verify both pass.
- [x] 1.4 Check `parse_water_heater_energy_metadata` and its readers with `energy_kwh: null`; store per-device metadata for unmeasured slots if safe, otherwise leave it absent. Verify with a test either way.

## 2. Recorder and comparison integration tests

- [x] 2.1 Recorder test (new file under `tests/recorder/`, modelled on `test_recorder_fallback.py`): water sensor with no valid history and no snapshot for a whole slot yields water `{unknown, recorder}`, `water_kwh` stored as 0.0, load `derived_history`.
- [x] 2.2 End-to-end test through store then `build_grid_only_comparison` over a window of consecutive fully unavailable slots (cover 08:15-12:00 shape, 16 slots): all included, `water_unmeasured_slots` equals the slot count, status `available`, one covered segment, grid-only cost equals `(load + ev) * price`.
- [x] 2.3 Boundary test: a slot with history only after the sensor returns (12:15 shape) and a slot with history only before it fails (08:00 shape) stay `power_history`, are included without a water note, and neighbouring unknown slots are included with the note. Verify no gap in segments.
- [x] 2.4 Guard tests: unknown water with snapshot/mixed load, EV above 0 with load 0, EV unknown, load unknown remain excluded after the fix.
- [x] 2.5 Run `UV_NO_SYNC=1 uv run python -m pytest tests/test_observation_provenance.py tests/test_grid_only_comparison.py tests/recorder tests/test_comparison_history.py -v` and `./scripts/lint.sh` backend part; all pass.

## 3. Backend: exclusion reasons (eligibility unchanged)

- [x] 3.1 Before changing code, add a parity test in `tests/test_grid_only_comparison.py` holding a reference copy of the current eligibility logic and a matrix of slots (provenance flags, component methods and owners, null/negative/NaN values, prices, battery on/off, water exception, clamp case). Verify it passes against the current code.
- [x] 3.2 Refactor `_recording_is_eligible` and `_slot_costs` to return the first failing check as `(reason, component)` and add `missing_slot` and `ambiguous_rows` in `build_grid_only_comparison`, using the codes and order in design.md decision 5. Verify the parity test still passes (same eligible set) and each code has a test.
- [x] 3.3 Build `excluded_spans` (maximal contiguous runs per reason and component, local ISO with offset, end exclusive, DST-safe through UTC) and `coverage.excluded_by_reason`; always present. Tests: single span, adjacent different reasons, non-contiguous same reason, DST day, nothing excluded (empty list and object), sums equal `excluded_slots`, existing keys and values unchanged (compare against a stored copy of the old response for the same input).
- [x] 3.4 Confirm the `/energy/cost-series` route passes the fields through unchanged (route test) and run `UV_NO_SYNC=1 uv run python -m pytest tests/test_grid_only_comparison.py tests/test_comparison_history.py -v`; all pass.

## 4. Frontend: bands, reason note, readout (GATED: do not start until the owner has approved the layout sketch in design.md)

- [x] 4.1 Add optional types and tolerant parsing in `frontend/src/lib/api.ts` (missing or malformed new fields are ignored, never invalidate the chart). Test with responses with, without and with malformed fields.
- [x] 4.2 Add the code-to-phrase table (fixed phrases, fallback "not compared") and the note builder (largest first, two groups then "and N more reasons"). Unit tests for each code, component wording, and the cut-off.
- [x] 4.3 Render the muted bands in `CostSeriesChart.tsx` (tokens only, hatch or edge line, `data-testid="cost-excluded-span"`) from `excluded_spans` in epoch ms, and add the reason line to the hover/focus readout. Geometry and component tests: band positions for a mid-day span and a DST day, no band when the list is empty or absent, DS and Grid-only paths identical with and without spans, readout names the reason.
- [x] 4.4 Add the reason notes under the coverage line in `CommandDomains.tsx` using the existing warning style. Component tests: single reason, several reasons, none, older backend; narrow-width check against the approved sketch.
- [x] 4.5 Run `pnpm --dir frontend test` for touched files, `pnpm --dir frontend lint` and `./scripts/lint.sh`; all pass.
- [x] 4.6 After approval to edit `docs/` (AGENTS.md: ask first), update the Cost Chart paragraph of `docs/design-system/AI_GUIDELINES.md` to describe the band and the reason note; verify it matches the rendered tokens.

## 5. Gap-aware power-history integration (added, backend)

- [x] 5.1 Verify the mechanism in `backend/core/ha_client.py` (`parse_power_states` drops unavailable/unknown states, `integrate_power_points` holds across the gap) and list every caller (recorder via `compute_slot_energy`, backfill, `get_load_profile_from_ha`, `get_energy_from_power_history`, `water_progress`).
- [x] 5.2 Tests first (fail before the fix): valid then unavailable mid-slot (08:00 shape, 2 kW for 26 s gives 0.0144 kWh), unavailable then valid (12:15 shape), `unknown`, several flaps, window fully unavailable (None), non-numeric state; update the tests that encoded the old hold (`test_unavailable_gap_holds_the_last_good_value`, garbage state, points only after the window).
- [x] 5.3 Implement gap markers in `parse_power_states` and gap-aware `integrate_power_points`; adapt `slot_energy` water active points, `backfill._value_at`, `water_progress` valid-sample lookup and the load profile valid-point count. Verify callers with tests (recorder, backfill, load profile, water progress).
- [x] 5.4 Recorder to comparison test: water valid then unavailable mid-slot stays `power_history`, `load + water + ev` equals the integrated total, the comparison includes the slot with the exact grid-only cost.

## 5b. Backfill skips slots without measured core data (added, backend)

- [x] 5b.1 Verify what backfill wrote for a fully unavailable window and the NOT NULL defaults in `SlotObservation` / `store_slot_observations`; list the readers of `pv_kwh` / `load_kwh` (design.md decision 11).
- [x] 5b.2 Restore the skip in `BackfillEngine.integrate_slots`: valid-point day check, and drop any slot whose `pv_kwh`, `load_kwh`, `import_kwh` or `export_kwh` is None. Recorder unchanged.
- [x] 5b.3 Replace the test that asserted unknown rows with tests for the skip (all unavailable, load unavailable, partial day, configured PV in a gap, database has no row) in `tests/backend/test_slot_energy_gaps.py` and `tests/backend/test_backfill_store_skip.py`; `tests/ml/test_backfill.py` fixtures now supply core history and cover a missing pv/load/grid sensor.

## 6. Frontend: en dash in ranges and non-overlapping axis labels (added)

- [x] 6.1 Test first, then use U+2013 for the excluded-span range in `CostSeriesChart.tsx`; update the existing assertion and the example in `docs/design-system/AI_GUIDELINES.md`.
- [x] 6.2 Confirm bug 3 predates the change (`buildTicks` identical in `HEAD`) and write a failing layout test for the fall-back fixture at 390 px and other widths.
- [x] 6.3 Add `layoutAxisTicks` (`frontend/src/lib/costAxisTicks.ts`) and use it from `CostSeriesChart.tsx` with a measured width; tests for priority, row choice, dropping, normal day unchanged, fall-back day at several widths, spring-forward day. Update the Cost Chart paragraph of `AI_GUIDELINES.md`.

## 6b. Frontend: bucket readout on touch (added)

- [x] 6b.1 Test first (touch tap sequence, second tap, switching, mouse hover and click, keyboard focus/Enter), then fix `CostSeriesChart.tsx` so the first touch tap opens the readout; semantics in design.md.

## 7. Wrap-up

- [x] 7.1 Confirm `openspec validate fix-unavailable-water-provenance --strict` passes, the two open questions in design.md are relayed to the owner, and no production file or database was touched.

- [x] 7.2 Run `openspec validate fix-unavailable-water-provenance --strict` and the full `./scripts/lint.sh` once at the end.

## Workflow follow-up

- Archive the change after review.
