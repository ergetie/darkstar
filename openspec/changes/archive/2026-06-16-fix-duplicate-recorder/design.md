## Context

The recorder is the single source of truth feeding ML training, forecast accuracy, and base-load analysis. Two recorder instances run concurrently in the root-`Dockerfile` runtime:

1. **Standalone** — `scripts/docker-entrypoint.sh` launches `python -m backend.recorder` (its `backend.recorder.main()` loop), logs piped through `[RECORDER] …`.
2. **In-process** — `backend/main.py` lifespan calls `recorder_service.start()`, running `RecorderService._loop()` as an asyncio task inside uvicorn; logs as `INFO: recorder - …`.

Both call `record_observation_from_current_state()`, both use the default `RecorderStateStore` (`data/recorder_state.json`), and both upsert `slot_observations` keyed on `slot_start` via `store_slot_observations(authoritative=True)`.

The shared meter-state file makes the two loops mutually destructive. `RecorderStateStore.get_delta()` reads the previous cumulative value, computes `current − previous`, then **immediately persists** `current`. So whichever loop runs first gets the real delta; the second reads the just-saved value and computes ≈0. `RecorderService._record_with_retry()` sleeps 5 s after the quarter boundary before recording, so the in-process loop is deterministically the later reader **and** the later DB writer — its zero overwrites the standalone loop's real value. Observed on the server: `2026-06-16 10:30` recorded as `PV=0.450` (standalone) and `PV=0.000` (in-process) for the same slot; stored value is `0.0`.

This was latent until `2026-06-10-recorder-ssot` (deployed 2026-06-13) replaced the "first positive write wins" UPSERT guard with authoritative last-writer-wins (the `energy_update`/`authoritative` logic in `store.py`), intentionally allowing genuine zeros and downward corrections for a *single* writer. Energy columns read `0.0` for every slot from 2026-06-14 onward; prices and SoC are intact (they use `coalesce`, keeping existing non-null values).

The HA add-on entrypoints (`darkstar/run.sh`, `darkstar-dev/run.sh`) already run uvicorn only — no standalone recorder — so they are unaffected and serve as the reference topology.

## Goals / Non-Goals

**Goals:**
- Guarantee exactly one live recorder instance writes `slot_observations`.
- Make root-`Dockerfile` and add-on topologies behave identically (in-process recorder only).
- Add regression coverage so a second recorder cannot silently return.
- Restore the zeroed `2026-06-14 → present` range before it keeps biasing nightly retrains.

**Non-Goals:**
- No change to recording/delta/storage logic (`recorder.py`, `recorder_service.py`, `store.py`) — that logic is correct for a single writer.
- No schema change or DB migration.
- No new self-healing/zero-detection capability in the auto-backfill path (larger scope, separate change). Healing here is a one-time operational step.
- No change to the `authoritative` last-writer-wins UPSERT semantics — they are correct given a single writer.

## Decisions

**Decision: Keep the in-process `RecorderService`; remove the standalone launch.**
- Rationale: `RecorderService` is the canonical recorder the product is built around — it integrates with the FastAPI lifecycle (clean start/stop), exposes health/status (`RecorderStatus`, surfaced via the API/dashboard), and has retry logic. The `2026-06-10-recorder-ssot` proposal explicitly lists `recorder_service.py` (record/sleep loop order) as the recorder it modified. The add-on entrypoints already keep only this one.
- Alternative considered: keep the standalone (process isolation from the API event loop), remove the in-process service. Rejected — it would break the dashboard recorder-health integration and diverge from the add-on topology, a larger and riskier change.

**Decision: Fix only `scripts/docker-entrypoint.sh`.**
- Remove the initial `python -m backend.recorder …` launch (~line 129), the auto-restart block in the monitor loop (~line 160), and the now-unused `RECORDER_PID` tracking. This is the single place the duplicate originates (grep-confirmed: only two references, both in this file). The add-on `run.sh` files need no change.

**Decision: Heal the corrupted range with the existing `bin/backfill_ha.py`, as an operational runbook step.**
- It performs a direct `UPDATE slot_observations SET load_kwh/pv_kwh/import_kwh/export_kwh/batt_charge_kwh/batt_discharge_kwh WHERE slot_start = ?`, bypassing the authoritative/source guard — so it overwrites the bogus zeros (which the guarded auto-backfill cannot: `get_last_observation_time()` sees rows exist → "up to date" → no-op, and non-authoritative backfill cannot overwrite recorder-sourced rows).
- This is operational tooling, not committed fix code — consistent with the repo's existing `bin/`/`scripts/` repair tools (`fix_load_gaps.py`, `fix_price_gaps.py`, `repair_soc.py`, `backfill_prices.py`). Nothing one-time is added to the application path, so there is no lingering code and no "remove later" backlog item.

**Decision: Run the heal before the next nightly retrain.**
- Training uses 30-day-half-life recency weighting and retrains nightly (last run 2026-06-16 03:00), so the recent zeros are in the heaviest-weighted window and are actively biasing PV/load forecasts downward. Healing first means the next retrain sees clean data.

## Risks / Trade-offs

- [Running image is not built from the root `Dockerfile`] → Verify at deploy time which Dockerfile builds the running container. The `[RECORDER]` log prefix confirms the server currently uses `docker-entrypoint.sh`; if a future deploy switches to the add-on build, the duplicate is already absent there.
- [`bin/backfill_ha.py` writes raw `load_kwh` without EV/water subtraction] → Healed `load_kwh` may represent total rather than base load, inconsistent with live rows. Mitigation: confirm the tool's output meaning before running; if it does not isolate base load, adjust the tool or the range so healed rows match the live base-load definition. Still strictly better than zeros.
- [In-process recorder shares the uvicorn event loop] → Recording does async I/O; under load the API is already slow. Mitigation: this is the pre-existing, intended topology (the add-on already runs this way) and removing the standalone does not add load — it removes a process.
- [HA history unavailable for part of the heal window] → Re-running the backfill is idempotent (direct UPDATE per slot); re-run once HA history is reachable. Brief HA outages were observed but are transient.
- [Duplicate recorder silently reintroduced later] → Mitigation: the regression test asserts the entrypoint launches no standalone recorder, failing CI if the line returns.

## Migration Plan

1. Edit `scripts/docker-entrypoint.sh` to remove the standalone recorder launch, restart block, and `RECORDER_PID` usage.
2. Add regression test(s) asserting the entrypoint starts no `python -m backend.recorder` and the single-writer invariant holds.
3. Build and deploy; confirm logs show only the in-process recorder (`INFO: recorder - …`), no `[RECORDER]` lines, and that new slots record non-zero PV/load.
4. Run the one-time heal: `bin/backfill_ha.py 2026-06-14 <today>` (after confirming base-load handling); verify `slot_observations` PV/load/import/export for the range are restored and the dashboard cards populate.
5. Confirm the next nightly retrain consumes the healed data.

**Rollback:** the entrypoint change is a small, self-contained diff; revert the file and redeploy to restore prior behavior. The data heal is forward-only (it can only improve the zeroed rows) and a DB backup is taken by the entrypoint before migrations.

## Open Questions

- Confirm whether `bin/backfill_ha.py` should subtract EV/water to match the live base-load definition of `load_kwh`, or whether a small adjustment is warranted for the heal. (Resolve before running step 4.)
