## Context

`slot_observations` is the single table the recorder writes and the ML/forecast pipeline reads. The stabilization review (findings #25–#29, OQ7) confirmed that what the recorder writes is misaligned and source-dependent:

- The recorder service loop records *then* sleeps to the next boundary (`backend/services/recorder_service.py:155→160`), so in steady state it wakes just after a boundary and stamps the row with the slot that just **began**, while the cumulative deltas describe the slot that just **finished** — a +15-min shift (`backend/recorder.py:209-214`).
- EV/water energy is `mean(power) × duration` over HA history (`backend/core/ha_client.py:235-237`); because HA returns state-*change* events at irregular times (and backfills the at-start state), the live result is effectively "power at the boundary instant × 15 min" — an assumed-constant snapshot, not integrated energy (#25, #28).
- Base-load isolation (`backend/recorder.py:500-511`) subtracts that misaligned snapshot, so `load_kwh` is over/under-stated whenever controllable load fluctuates (#26).
- The gap-fill/backfill path never fetches EV/water at all (`backend/learning/backfill.py:139-145` → `engine.py:238-244`), so it writes **total** load into the same `load_kwh` column live rows store **base** load in (#27).
- The UPSERT only overwrites when the incoming value is `> 0` (`backend/learning/store.py:166-189`, "REV F35: prevents backfill from wiping data"), so an over-count can never be corrected down and a true zero can never be stored (#29).

`slot_observations` also has two writers across a module boundary: the recorder owns the energy/price columns; the executor writes `executed_action` via a raw UPDATE (`executor/history.py:155`). OQ7 asks for a canonical owner/meaning per column.

This is the solution session for OQ7. The remedies are the ones recorded in the findings ledger; this document commits to them.

## Goals / Non-Goals

**Goals:**
- Every `slot_observations` row describes exactly one completed 15-minute slot, with all fields (load/PV/grid, EV/water) aligned to that same window.
- EV/water (and any power-history) energy is time-weighted integrated, not averaged or snapshotted.
- `load_kwh` means **base load (controllable loads subtracted)** for *every* writer — live recorder and backfill alike.
- The store can accept a correction (including a lower value or a true zero) without re-opening the door to accidental backfill wipes.
- Each `slot_observations` column has a documented canonical owner and meaning (OQ7).

**Non-Goals:**
- No rewrite/migration of historical rows already written with the old semantics (recorded as a possible follow-up, not done here).
- No new UI, no schema redesign beyond what per-device storage already provides.
- No change to PV/load/grid cumulative-delta calculation (that path is correct; only its slot *label* and the controllable-load subtraction change).
- No change to the executor's `executed_action` write other than documenting ownership.

## Decisions

### D1 — Record the just-finished slot (fix the +15-min shift)
Change the recorder so the row is labeled `slot_start = floor(now) − 15 min` and every field is computed over `[slot_start, slot_end]`, a window now fully in the past. Reorder the service loop so the boundary wake triggers a record of the completed slot. **Why:** aligning the label to the data the deltas already measure is the minimal correct fix; integrating over a fully-elapsed window also means EV/water history is real data, not a forward-looking guess. **Alternative considered:** keep labeling the current slot but shift the delta source — rejected, it just moves the mismatch and leaves EV/water unintegrable.

### D2 — Time-weighted (step) integration for power history
Replace `mean(kw_values) × duration_hours` with `Σ powerᵢ · Δtᵢ` using each sample's `last_changed` timestamp (step/zero-order hold between samples, clipped to the slot window). **Why:** HA logs on state change at irregular intervals; a plain mean over-weights brief spikes and under-weights long steady periods. **Alternative considered:** trapezoidal interpolation — marginally different, more complex; step integration matches how HA state actually behaves (a value holds until the next change). The snapshot estimate (`kW × 0.25`) stays **only** as the explicit fallback when history returns `None`.

### D3 — Disaggregate controllable loads in every writer
The backfill path SHALL fetch EV/water history for each gap slot and subtract it before writing `load_kwh`, exactly like the live recorder. Backfill's window is entirely in the past, so the D2 integration is fully accurate there. **Why:** one column must have one meaning regardless of who wrote it; this is the core SSOT fix (#27). **Alternative considered:** a separate `total_load_kwh` column plus a derived base — rejected as a larger schema/consumer change; the spec already declares `load_kwh` = base load, so we make all writers honor it.

### D4 — Presence-based overwrite, not positivity-based
Replace the `excluded.X > 0` guard with a rule that distinguishes "no measurement" (skip/keep existing) from "a real measurement" (write it, including zero or a lower value). The live recorder's writes are authoritative and may correct; backfill writes only fill rows/columns that have no authoritative measurement yet. **Why:** the original guard conflated "don't wipe" with "only ever go up," which blocks legitimate corrections and true zeros (#29). **Alternative considered:** a dedicated `source`/`measured_at` provenance column — cleaner long-term, deferred to keep this change focused; a presence flag on the existing write achieves the safety goal now.

### D5 — Canonical column ownership for `slot_observations` (OQ7)
Document, in the spec and a short table in the recorder module, the owner and meaning of each column:
- **Recorder owns** the energy/price columns (`load_kwh` = base load; `pv_kwh`/`grid_*`; `ev_charging_kwh`/`water_kwh` and the per-device JSON; price columns).
- **Executor owns** `executed_action` (written via UPDATE keyed on `slot_start`).
No column is written by both owners. **Why:** OQ7 asks for one canonical definition; writing it down (and asserting `load_kwh` = base everywhere) is what closes the SSOT ambiguity. The dual-write stays, but with non-overlapping column ownership it is safe.

## Risks / Trade-offs

- **Mixed-meaning history remains.** Rows written before this change keep the old (shifted/total) semantics → ML trains on a mix until old rows age out. **Mitigation:** document it; offer an optional one-time re-derivation as a *follow-up* change, not here. The spike-filter read guards already drop the worst rows.
- **Extra HA history calls in backfill** (one EV/water fetch per gap slot) → more load on the HA history API during large gap fills. **Mitigation:** reuse the existing per-window fetch with its 10–15 s timeout and `None`-on-failure contract; fall back to snapshot exactly as the live path does.
- **Loosening the overwrite guard could let a buggy backfill lower good data.** **Mitigation:** D4 keeps backfill non-authoritative (fills only un-measured rows/columns); only the live recorder may correct downward.
- **Loop-order change touches recorder timing.** A wake that is late by more than one slot must still label correctly. **Mitigation:** derive `slot_start` from `floor(now) − 15 min` rather than from loop iteration count, and cover the late-wake/gap case in tests.
- **Retraining on corrected data** may shift forecasts for existing users. **Mitigation:** expected and desirable; no action beyond noting it in release notes.

## Migration Plan

- Pure code change; no DB schema migration. New rows use the corrected semantics immediately on deploy.
- **Rollback:** revert the change; already-written corrected rows remain valid (base-load isolated, slot-aligned) and are not harmful to old code.
- **Follow-up (out of scope):** a one-time backfill re-derivation pass to bring historical rows onto the new semantics.

## Open Questions

- Whether to add a provenance/`source` column (D4 alternative) in a later change to make corrections fully auditable — deferred.
- Whether a historical re-derivation pass is worth running given spike-filter read guards already exclude the worst rows — decide after this lands.
