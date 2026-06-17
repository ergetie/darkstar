## Context

`get_learning_engine()` (`backend/learning/__init__.py`) returns a process-wide singleton. `LearningEngine.__init__` loads `config.yaml` once into `self.config` and nothing ever resets `_engine_instance` or re-reads the file. `ml/forward.py` reads `engine.config` throughout forecast generation: PV physical ceiling, solar-array geometry for the Open-Meteo fetch, weather lat/lon, load/PV/price tuning. The executor and planner, by contrast, reload config each tick (the executor explicitly via `executor.reload_config()` on config save, `config.py:310-318`), so after any config edit the forecast layer is frozen on the startup snapshot while the rest of the system tracks current config — a split-brain confirmed in a tester's log (Kepler battery config changed between runs while the forecast kept clipping at a stale inverter limit).

Separately, the physical ceiling in `_pv_physical_ceiling_kwh` (`ml/forward.py:79-91`) takes `min(total_kwp * efficiency, max_dc_input_kw, max_ac_power_kw)`. Including `max_ac_power_kw` is wrong for DC-coupled batteries: surplus PV above the AC limit charges the battery on the DC side and is still real generation, so clipping the *generation* forecast at AC understates available solar.

The existing `config-caching` capability already establishes mtime-gated reload for the executor and the shared `load_yaml` loader — this change extends the same pattern to the forecast layer rather than inventing a new mechanism.

## Goals / Non-Goals

**Goals:**
- The forecast layer reflects current `config.yaml` without a process restart, using mtime-gated reload (no per-forecast disk I/O when unchanged).
- Config save through the API refreshes the forecast layer, not only the executor.
- PV generation ceiling is DC-side only (panel capacity + DC input); AC limit no longer truncates the generation forecast on DC-coupled systems.
- The effective ceiling is logged for diagnosability.

**Non-Goals:**
- Changing how the planner/executor consume config (already fresh).
- Reworking AC-side dispatch limits in Kepler (export/inverter throughput limits stay; only the *generation forecast* ceiling changes).
- Hot-reloading config into long-lived objects beyond the forecast engine.
- Adding a config-change file watcher/daemon — reload stays pull-based (mtime check at use).

## Decisions

- **Mtime-gated reload inside `LearningEngine`, checked before each forecast run.** Store the config file path and last-seen mtime; on a reload hook, re-parse only when mtime changed. Rationale: mirrors the established `config-caching` pattern, keeps reads cheap, and avoids restart. Alternative considered: reset the singleton to `None` on save and lazily rebuild — rejected because the engine also holds DB handles/state that are costly to rebuild and reused elsewhere; reloading just the config dict is narrower and safer.
- **Config save explicitly refreshes the engine** (`config.py` save path) in addition to the mtime check. Rationale: makes UI saves take effect immediately and deterministically, even before the next mtime tick; belt-and-suspenders with the mtime gate. Alternative: rely on mtime alone — works, but the explicit refresh removes any ordering ambiguity.
- **Drop `max_ac_power_kw` from the generation ceiling; keep `min(total_kwp * efficiency, max_dc_input_kw)`.** Rationale: matches DC-coupled physics. Alternative considered: gate AC-clipping on `topology != dc_coupled` — deferred; for the forecast of *generation*, DC-side is the correct bound regardless of topology, and AC-coupled throughput is already modelled downstream in the planner.
- **Log the effective ceiling and binding input.** Rationale: a stale or misconfigured ceiling was undiagnosable from the log; one line at generation time makes future cases self-evident.

## Risks / Trade-offs

- [Reloading mid-process could race with an in-flight forecast read of `engine.config`] → Reload is a single dict reassignment performed at the start of a forecast run (not mid-iteration); readers capture the reference once per run. Avoid mutating the dict in place.
- [Mtime checks add disk stat calls] → `stat` is cheap and gated; only a changed mtime triggers a re-parse. Net I/O drops versus any naive always-reload approach.
- [Higher PV forecasts on oversized-array systems change planner behaviour] → Intended (more accurate PV); validate the planner still respects AC/export throughput limits so the extra forecast PV is curtailed/charged, not double-counted as exportable.
- [A partial/corrupt config write observed mid-save] → Engine refresh runs only after a successful save; the existing durable-config-write guarantees the file is complete.

## Migration Plan

1. Ship `LearningEngine` mtime-aware reload + config-save refresh hook.
2. Ship DC-side ceiling change + logging.
3. No data migration required. Rollback = revert; behaviour returns to startup-snapshot config and AC-clipped ceiling.
4. Field verification: on the tester's box, after deploy, a config edit (or restart) should move the PV plateau off the stale AC limit; the new ceiling log line confirms the bound.

## Open Questions

- Should the mtime reload also cover `secrets.yaml` for the engine, or is `config.yaml` sufficient for forecast inputs? (Leaning: `config.yaml` only — secrets don't affect forecast shape.)
- Is there any other long-lived consumer of `engine.config` outside `ml/forward.py` and the scheduler that also needs the refreshed reference within the same run? (Audit during implementation.)
