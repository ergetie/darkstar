## Why

The energy recorder is the source of truth that feeds ML training, forecast accuracy, and base-load analysis — but the stabilization review confirmed five defects (findings #25–#29, S2/S3) that make the stored data misaligned and source-dependent. Slot rows are stamped with the wrong 15-minute window, EV/water energy is a single boundary snapshot assumed constant, energy is averaged instead of integrated, gap-filled rows store a different *meaning* of `load_kwh` than live rows, and a save guard prevents corrections and true zeros. The training set is therefore noisy and internally inconsistent, which quietly degrades every downstream forecast and plan.

## What Changes

- **Record the slot that just finished, not the one starting** — align every field in a row (load/PV/grid and EV/water) to one completed 15-minute window, fixing the current +15-min time-shift (#25).
- **Integrate EV/water energy over the elapsed window** using time-weighted (step) integration over the sensor's actual sample timestamps, replacing the unweighted `mean(power) × duration` estimate and the assumed-constant boundary snapshot (#28, #25).
- **Disaggregate controllable loads everywhere** — the backfill/gap-fill path SHALL fetch and subtract EV/water energy exactly like the live recorder, so `load_kwh` means *base load* for every writer instead of *total* for backfilled rows and *base* for live rows (#27, #26).
- **Allow corrections and true zeros** — replace the "first positive write wins" UPSERT guard so a re-recorded slot can lower an over-counted value or store a legitimate zero, while still resisting accidental backfill wipes (#29).
- **Define a canonical owner and meaning for each `slot_observations` column**, including the recorder↔executor dual-write boundary (OQ7), documented in design.

No user-facing UI changes. The snapshot estimate remains only as an explicit fallback when history is unavailable.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `energy-recording`: change the slot-alignment, EV/water energy computation (integration vs. mean), backfill disaggregation, and storage-overwrite requirements so all writers produce slot-aligned, base-load-isolated, correctable data with one consistent column meaning.

## Impact

- **Code:** `backend/recorder.py` (slot labeling, integration, disaggregation), `backend/core/ha_client.py` (`get_*_from_ha` power-to-energy), `backend/learning/backfill.py` + `backend/learning/engine.py` (EV/water disaggregation in gap-fill), `backend/learning/store.py` (UPSERT overwrite rule), `backend/services/recorder_service.py` (record/sleep loop order).
- **Data:** `slot_observations` rows written after this change are slot-aligned and base-load-isolated; historical rows are unchanged (no migration of past data in this change).
- **Downstream consumers:** ML training (`ml/train.py`), forecast-vs-actual and bias analysis read cleaner targets — accuracy should improve, but existing models retrain against the corrected data.
- **Cross-change:** must land before resuming `price-forecasting-module-4` (EV scheduling depends on correct EV/water energy). Coordinates with the deferred `harden-ci-and-tests` for regression coverage.
- **Resolves stabilization-review findings:** #25, #26, #27, #28, #29 and Open Question OQ7.
