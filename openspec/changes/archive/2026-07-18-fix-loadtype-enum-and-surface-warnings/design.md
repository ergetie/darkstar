## Context

Two related but independent problems, discovered together while reading dev logs:

1. `backend/loads/base.py`'s `LoadType` enum (`BINARY`/`FIXED`/`VARIABLE`) has no `CURRENT` member, so `backend/loads/service.py`'s `LoadDisaggregator._initialize_from_entity_arrays` fails to parse `ev_chargers[].type: "current"`, catches the `ValueError`, logs a warning, and silently mislabels the load as `BINARY`. This only corrupts the `/api/loads/debug` dashboard endpoint and recorder telemetry — confirmed by tracing every consumer of `DeferrableLoad`/`LoadDisaggregator` (`backend/api/routers/loads.py`, `backend/recorder.py`, `backend/services/recorder_service.py`, `scripts/visualize_loads.py`). Actual charging control (`executor/engine.py:3047` `is_current_type = charger_cfg.type == "current"`, and `planner/pipeline.py`/`planner/solver/adapter.py`) reads `type` directly from config and is unaffected.

   The identical defect exists for water heaters: `EntityArrayEditor.tsx:575` offers `"modulating"` as a water heater `type` option, `LoadType` has no `MODULATING` member either, and `backend/loads/service.py`'s water-heater branch (lines 76-82) hits the same fallback-to-binary path with the same warning shape. Water heaters have no config-validation check for `type` at all today (`backend/api/routers/config.py` validates EV charger type at lines 607-616 but nothing equivalent for water heaters), so this half of the bug is currently invisible even to the existing warning pipeline.

2. This class of bug — a config value accepted as valid by one validation layer (or not checked at all) but silently rejected/downgraded by another consuming module — was invisible in the app. It was only found by reading raw dev-server logs. The app already has a proactive, global config-warning mechanism: `App.tsx` calls `Api.configValidate()` (→ `POST /api/config/validate`) on every page mount and renders a `banner-warning` for any returned issue (`App.tsx:52-53,115-124`). `backend/api/routers/config.py:607-616` already validates EV charger `type` against a **hardcoded tuple** `("binary", "current")` — the exact same two values `LoadType` should recognize, but the two lists are independent and drifted apart.

## Goals / Non-Goals

**Goals:**
- Fix the `LoadType` enum gap so `type: "current"` (EV) and `type: "modulating"` (water heater) are recognized correctly by the load-disaggregation subsystem.
- Close the structural gap that let (1) happen: derive the config-validation allowed-type-list from the same source of truth the runtime code uses, for both EV chargers and water heaters, so a future drift between "config accepts X" and "runtime understands X" is caught by the existing validation pipeline instead of silently degrading behavior.
- Reuse the existing, already-wired warning surface (`/api/config/validate` → `App.tsx` global banner). No new UI component.

**Non-Goals:**
- Not building a general log-viewer or piping arbitrary backend log lines to the UI (explicitly rejected — too noisy, not what "relevant" means here).
- Not touching planner/executor control logic — already correct.
- Not re-architecting `backend/loads/` into something bigger than a monitoring/telemetry subsystem.

## Decisions

**1. Add `CURRENT = "current"` and `MODULATING = "modulating"` to `LoadType`, remove the dead fallback paths for them.**
`backend/loads/service.py`'s `try/except ValueError` around `LoadType(l_type_str)` stays in both the water-heater and EV-charger branches (still needed for genuinely unrecognized future values), but with both members added to the enum, neither value raises anymore, so the warning and the silent downgrade stop for these two values specifically.

**2. Single source of truth for accepted load types, shared by EV and water heater validation.**
Instead of `backend/api/routers/config.py` hardcoding `("binary", "current")` for EV chargers (and having no check at all for water heaters), both validators import and check against the same definition derived from `LoadType` — e.g. `{t.value for t in LoadType}` filtered to the values relevant to each device kind, or an explicit shared constant living next to the enum in `backend/loads/base.py`. Alternative considered: leave the hardcoded EV tuple and just add a second, separate check that cross-validates `LoadType` membership — rejected as duplicative; a single source of truth is simpler and structurally prevents recurrence rather than just adding another list to keep in sync.

**3. No new UI surface — extend the existing one.**
The existing `/api/config/validate` + `App.tsx` banner already is the "relevant warnings" mechanism: it's global (shown on every page), proactive (checked on mount, not just on save), and already scoped to config-correctness issues (not generic logs). Building a second mechanism would fragment where users look for problems. Alternative considered: a new `/api/system/warnings` endpoint mirroring the executor-health warnings pattern (`backend/api/routers/executor.py:586-611` / Dashboard.tsx) — rejected for this change since the issue here is fundamentally a config-validation gap, not a live-runtime-health signal; revisit only if a future warning genuinely can't be expressed as a config-validation issue.

## Risks / Trade-offs

- **[Risk]** Changing the accepted-type source could change validation behavior in ways that reject values that were previously silently accepted. → **Mitigation:** the shared source is derived from `LoadType`, which already had to accept `binary`/`fixed`/`variable`; adding `current`/`modulating` only ever widens what's accepted, never narrows it.
- **[Risk]** Removing the fallback log line for `"current"`/`"modulating"` could mask a real future typo (e.g. user manually edits `config.yaml` to `type: curent`). → **Mitigation:** the fallback/warning path remains for any value outside the now-correct accepted set — only the two previously-mismatched values change behavior.
- **[Risk]** Adding a net-new water heater type validation check could surface a warning for existing installations that already have an out-of-range `type` value and previously saw nothing. → **Mitigation:** this is the intended outcome (surfacing a real, previously-silent misconfiguration); the warning severity is `"warning"`, not `"error"`, so it doesn't block saves.

## Migration Plan

No data migration. Both fixes are code-only:
1. Deploy enum + validator changes together (they share the single-source-of-truth constant).
2. On next backend restart, the startup warning disappears and `/api/loads/debug` correctly reports `current`-type chargers.
3. Rollback: revert the commit; no persisted state changes.
