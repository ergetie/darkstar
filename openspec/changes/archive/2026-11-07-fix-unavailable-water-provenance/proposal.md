# Proposal

## Why

On 2026-11-05 `sensor.vvb_power` (the water heater) was `unavailable` in Home Assistant from 08:00:26 to 12:23:50 local. Slots 08:15 to 12:00 (16 slots) were stored with `water.method = unknown, owner = unknown` and were excluded from the grid-only comparison, so the "Actual cost so far" chart broke into two segments and the dashboard coverage dropped. The archived `water-heater-disabled-guard` change and the main `grid-only-comparison` spec already say a slot whose configured water sensor was unavailable is included with a note. That behaviour never triggers, because the recorder's `unknown` provenance is discarded on the way to the database. Separately, the dashboard hides why slots were left out: an excluded span is a silent gap in the chart and the card only says "N excluded".

## What Changes

- Recorder write path: a recorder-authored water component with method `unknown` and no measured value (every water source unavailable) is stored as `method unknown, owner recorder`, instead of being replaced by `owner unknown`. Existing guards in the comparison stay as they are (derived-history load required, snapshot/mixed load rejected, EV above 0 with load 0 rejected, EV or load `unknown` rejected).
- A recorder write never downgrades or overwrites an already measured water value or its provenance.
- Comparison response (additive): every slot excluded from the grid-only comparison is reported in `excluded_spans` (contiguous slots grouped by reason, with start, end, slot count, machine reason code and optional component) and `coverage.excluded_by_reason` (per-reason totals). One reason per slot, chosen by a fixed check order. Which slots are eligible does not change.
- Cost chart and card: a muted band over each excluded span, a short plain-language reason note next to the coverage text, and the reason in the hover readout. DS and Grid-only lines stay unconnected across spans. The UI is gated on the owner's approval of the layout sketch in design.md.
- Power-history integration (all callers): a state that is not a usable reading (`unavailable`, `unknown`, empty, non-numeric) ends the zero-order hold at its timestamp instead of being skipped, so the last valid value is no longer carried across the unavailable period. Energy is integrated over valid intervals only; a window with no valid interval has no value. This replaces "hold the previous valid power across the excluded interval" in `energy-recording`. Example: 2 kW valid for 26 s, then unavailable, integrates to about 0.014 kWh, not 0.5 kWh.
- Cost chart: time ranges in the excluded-span readout use an en dash (`08:15–12:15`), matching the rest of the UI.
- Cost chart axis: tick labels are laid out against the measured chart width and a label is moved to the other row, or dropped, when it would overlap another, so labels never overlap at any width (DST fall-back days repeat an hour and add labels such as `02+2` and `02+1`).
- Tests for a fully unavailable water sensor across whole slots, the partial-unavailable boundary slots (08:00 and 12:15), the reason codes and the chart bands.
- Decision recorded: already stored slots with `owner unknown` (prod 2026-11-05, 16 slots) are not repaired.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `energy-recording`: a recorder write keeps its own `unknown` water provenance when no water source could be read; power-history integration ends the hold at an unavailable or unknown state.
- `grid-only-comparison`: excluded slots are reported with a reason code, as spans and per-reason totals; the coverage requirement wording now says excluded slots carry a reason.
- `grid-financial-wear-display`: the cost chart marks excluded spans with a band and the card explains them in words; lines stay unconnected; ranges use an en dash and axis labels never overlap.

## Impact

- `backend/learning/store.py` (`store_slot_observations` provenance merge), possibly `backend/recorder.py`.
- `backend/core/ha_client.py` (`parse_power_states`, `integrate_power_points`, `get_load_profile_from_ha` valid-point count) and its callers `backend/core/slot_energy.py`, `backend/core/water_progress.py`, `backend/learning/backfill.py`. The pending change `load-profile-fetch-resilience` also edits `get_load_profile_from_ha`; only the valid-point count line overlaps.
- `backend/grid_only_comparison.py` (reason reporting only; eligibility unchanged), `backend/api/routers/energy.py` passes the result through unchanged.
- `frontend/src/lib/api.ts` (optional fields and types), `CostSeriesChart.tsx` (also axis tick layout and the en dash in ranges), `CommandDomains.tsx` and their tests; `docs/design-system/AI_GUIDELINES.md` (Cost Chart section; ask first per AGENTS.md, not part of this planning step).
- No schema change, no new dependency; the API change is additive.
