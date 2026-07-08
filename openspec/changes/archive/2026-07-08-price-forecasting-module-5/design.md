## Context

Module 4 provides the goal-based engine and a read-only `GET /api/ev/chargers` plus the `data/ev_multi_day_state.json` state file. Module 5 makes the goal self-service: a dashboard tab, a write API, and optional HA entity sync. The agreed model (stabilization-review "Agreed Direction — EV charging", 2026-06-06): the user sets **target SoC + ready-by time + optional repeat**, with a **keep-on-after-target** toggle; no penalty levels, no modes, **no `charge_priority` toggle** (surplus ordering is already owned by the shipped `excess_pv.priority[]` list).

Key existing infrastructure:
- `backend/ha_socket.py`: WebSocket client subscribing to `state_changed`; already monitors EV sensors per charger and follows the **vacation-mode** pattern (an HA entity drives planner state).
- `backend/core/ha_client.py`: REST helpers (`get_ha_sensor_float`, `get_ha_bool`, …).
- `executor/actions.py`: `HAClient.call_service()` with a domain allowlist; supports `number.set_value`, `switch.turn_on/off`; no `input_datetime` yet.
- `backend/api/routers/ev.py`: Module 4's router (`GET /api/ev/chargers`).
- `frontend/src/components/CommandDomains.tsx`: `ResourcesDomain` (Solar/Load/Water/EV); EV is a static kWh line.
- `frontend/src/components/ChartCard.tsx`: the localStorage overlay-persistence pattern (versioned key `darkstar-chart-overlays`, migration, new-user defaults) — reused for the tab state.
- `frontend/src/pages/settings/components/EntityArrayEditor.tsx`: `EVChargerEntity` settings UI.

## Goals / Non-Goals

**Goals:**
- Set/clear the goal (target SoC + ready-by + repeat + toggles) from the dashboard, no config edits.
- Show live status + progress + on-track/behind for the active goal.
- Optionally drive the goal from HA entities (ready-by `input_datetime`, target-SoC `input_number`), with HA winning when set.

**Non-Goals:**
- No changes to Module 4's engine, requirement constraint, or `MultiDayPlanner`.
- No custom calendar widget (use native date/time inputs).
- No HA helper auto-creation (the user creates the helpers).
- No penalty-level UI (retired in Module 4).

## Decisions

### 1. Dashboard placement: a persisted tab inside Energy Resources
The dashboard is full, so EV controls live in a **tab inside the Energy Resources card**, not a new top-level card and not a mode dropdown. A compact "Metrics | EV" switch in the card header toggles the body; the **EV tab is gated on `has_ev_charger`**. The **active tab is persisted in `localStorage`** reusing the ChartCard pattern: a versioned key `darkstar-resources-tab` (default `"metrics"`, with migration + new-user default). The Metrics tab keeps the at-a-glance EV summary line so glanceable info is never hidden.

```
┌─ Energy Resources ───────────[ Metrics | ●EV ]─┐
│ 🔌 Tesla            plugged · 42% SoC          │
│ Target  [ 80% ━━━━━━━━━━━━━━━━░░ ]              │
│ Ready by  [07:00]   Repeat [ Every day ▾ ]     │
│ ▣ Keep charger on after target                 │
│ Progress ▓▓▓▓▓▓░░  23 / 36 kWh   ✓ On track     │
│ Thu  Fri  Sat   ← day-by-day quota (read-only)  │
│ ⚠ Surplus absorption off — add this charger to │
│   Excess PV priority (Advanced) → [Open]        │
└─────────────────────────────────────────────────┘
```

Multiple chargers → one `EVChargingCard` block per charger inside the tab.

### 2. Goal controls, no modes
The EV tab renders: a **target SoC %** slider (default 80), a **ready-by time** input, a **repeat** selector (`daily` / `weekdays` / `weekends` / `every N days` / `specific date`), and — when `specific date` — a date input. Plus a **keep-on-after-target** checkbox. **No "EV-before-battery priority" checkbox** — surplus ordering is owned by the shipped `excess_pv.priority[]` list (battery implicitly first; users wanting EV-first edit that list under Settings → Advanced → "Excess PV Dispatch"). Changing any control calls the write API. Progress / today's quota / status / day-by-day schedule are read-only, from `GET /api/ev/chargers`.

### 3. Write API: `POST /api/ev/chargers/{id}/schedule`
Body: `{ target_soc_percent, ready_by, repeat, ready_by_date?, keep_on_after_target? }`. The endpoint validates, persists the goal to `ev_multi_day_state.json` (`source: "api"`), and — if HA entities are configured — fire-and-forget writes the ready-by to the `input_datetime` and the target SoC to the `input_number`. Returns the merged charger state. Clearing = `target_soc_percent: null` (charger reverts to no active goal; Darkstar leaves it to soak surplus PV only when listed in `excess_pv.priority[]`).

### 4. HA entity sync (two entities, HA wins)
Optional per charger: `ha_ready_by_entity` (`input_datetime`) and `ha_target_soc_entity` (`input_number`).
- **HA → Darkstar:** subscribe via the existing websocket (like the vacation-mode entity). On change, update the state file goal. **HA values take priority over the dashboard value when set** (mirrors vacation mode).
- **Darkstar → HA:** on a write-API call, push ready-by to the `input_datetime` (`set_datetime`) and target SoC to the `input_number` (`set_value`, already allowed).
- **Loop prevention:** debounce — ignore `state_changed` echoes within 5 s of a Darkstar-initiated write.
- **Parsing:** add `get_ha_datetime()` handling HA's space-separated and ISO (±tz) formats; reject time-only / unknown / unavailable with a warning.
- **Allowlist:** add `input_datetime` (service `set_datetime`) to the `call_service` domain allowlist alongside `input_number`.

### 5. Settings fields
Add optional `ha_ready_by_entity` and `ha_target_soc_entity` text inputs to the EV charger settings (`EntityArrayEditor.tsx`), styled like `switch_entity`. When a goal is active but no HA entities are set, show an informational tip (not blocking): connect HA helpers to drive the schedule from automations/voice.

### 6. Lifecycle
- **Active goal:** target not yet met, ready-by in the future → progress + quota shown.
- **Complete:** target met → status `complete`; for a repeating goal the next occurrence resolves automatically (Module 4's ready-by resolution); for a one-off it goes idle after the date passes.
- **Behind:** ready-by passed (or unreachable) with energy still required → status `behind`; not auto-cleared, surfaced in the UI.
- **Paused by load balancer:** when the fuse balancer sheds or throttles the EV (per-phase cap reached), the in-card status SHALL read "Paused by load balancer" rather than "behind on target" — so the user doesn't think the goal is failing. The balancer's decision is authoritative (the fuse is a hard physical constraint); the goal remains active and resumes when headroom returns.
- **Escape hatch:** charger not enabled in Darkstar (`switch_entity` unset) → Darkstar never controls it; the EV tab shows it as externally controlled / hidden.

### 7. In-card Excess PV link (surplus-absorption prerequisite)
A current-type charger absorbs surplus PV only when listed as an `ev` entry in `excess_pv.priority[]` (the Advanced "Excess PV Dispatch" editor). Most users won't find that on their own. The EV tab SHALL detect, per charger, whether the charger is absent from the priority list and show a non-blocking hint: *"Surplus absorption off — add this charger to Excess PV priority"* with a **jump-link** to the Advanced "Excess PV Dispatch" editor (deep-link via the settings tab router). The editor itself stays where power users expect it (Advanced). A one-tap in-card "Add to Excess PV" action that writes the priority-list entry via the existing `POST /api/config` endpoint is a **stretch enhancement**, not baseline.

A binary charger can never absorb surplus (accepted limit, documented in Module 4 D9); for binary chargers the hint SHALL be downgraded to an informational note ("binary chargers can't absorb surplus — set up a current-type charger to use free PV").

### 8. input_datetime plumbing prerequisites (currently absent)
Module 5's HA sync for ready-by relies on `input_datetime`, which has **no support anywhere** today. Four surfaces need adding — grouped here so the implementation work isn't siloed across tasks 4.1/4.2/4.3/4.5:
1. `backend/api/routers/ha.py:218` entity-list filter currently only includes `"input_number."` → add `"input_datetime."` so the entity picker surfaces `input_datetime` entities.
2. `executor/actions.py` has `set_input_number` (`:436`) but no `set_input_datetime` → add an async `set_input_datetime(entity_id, datetime)` that calls `input_datetime.set_datetime`.
3. `executor/profiles.py:19` `VALID_DOMAINS = {"select","number","switch","input_number"}` → add `"input_datetime"`.
4. `backend/ha_socket.py:136-156` only monitors `plug_sensor → ev_plug_{idx}` → for each charger with `ha_ready_by_entity` / `ha_target_soc_entity`, register `ev_ready_by_{idx}` / `ev_target_soc_{idx}` keys plus `state_changed` handlers that update the state-file goal (HA wins) and emit an `ev_schedule_changed` Socket.IO event.

### 9. State-file → config-default fallback dependency

Module 5 task 3.1 has the pipeline prefer the goal from `ev_multi_day_state.json` and fall back to `config.yaml` goal fields. The fallback is only meaningful if **Module 4 task 1.4 ships the YAML default goal** (`target_soc_percent: 80`, `ready_by: "07:00"`, `repeat: daily`). On a fresh install with no state file, a charger would otherwise silently have no goal until the user opens the dashboard. **Module 5 task 3.1 depends on Module 4 task 1.4.** Documented here so the cross-module order is explicit.

### 10. keep_on_after_target semantics — standby at max current until deadline

The **keep-on-after-target** toggle lets the EV cover ambient/cabin/battery preconditioning from grid/PV after the target SoC is met, instead of draining the traction battery. Gated on `target_soc_percent = 100` (v1 KISS; avoids overcharging chemistries sensitive to repeated full top-ups). Behaviour:

- **Before deadline, SoC < 100%** → charge normally (solver schedules cheap slots).
- **Before deadline, SoC = 100%** → post-solve injection sets `max_power_kw` for every upcoming slot until the ready-by deadline. The EV's onboard charger self-gates: it pulls 0 A for charging when satisfied, routes offered power to ambient loads (cabin heat/AC, battery conditioning) instead of discharging the pack.
- **After deadline** → charger idles. The toggle only elongates the [target-met → deadline] standby window; it does not create one when no future deadline is pending.

Implemented as a post-solve step in `planner/pipeline.py` (`_apply_keep_on_after_target`), not in the MILP itself — the solver models energy delivered to the battery (0 kWh at 100% SoC), while keep-on is a charger-actuation concern. No executor changes; the executor already follows `slot.ev_charger_plans` verbatim. Re-plug within the window re-enters standby; after the deadline the charger idles regardless. **Does not collide with `excess_pv.priority[]`** — that list governs surplus dispatch; keep-on governs post-target standby.

### 11. Departure Time removed from settings UI

`departure_time` was a Module 4-era deprecated alias for `ready_by`. The dashboard EV tab is now the single self-service surface for the goal (design D1/D2). The orphan text input in Settings → Inverter & Devices is removed; the `departure_time?` field stays on the TypeScript interface and Python config for backwards compat with existing user YAML, and the pipeline still reads it as a fallback alias (`pipeline.py:_resolve_ready_by`).

## Risks / Trade-offs
- **[Risk] Tab hides the other metrics while open.** → Acceptable: the EV tab is for occasional setup; the Metrics tab keeps the live EV summary. Chosen over a tall always-expanded card.
- **[Risk] HA echo loop.** → 5 s debounce on Darkstar-initiated writes (same as the prior deadline design).
- **[Risk] HA precedence surprises a user who also uses the dashboard.** → Documented + an indicator in the card when the value is HA-driven; last-write-wins within the 30-min cycle. Mirrors the established vacation-mode behaviour.
- **[Risk] Timezone handling on the ready-by datetime.** → Frontend sends local ISO; backend parses with the configured `timezone_name`; display in local time.
- **[Trade-off] Goal stored in the state file, not config.** → Survives restarts; if the file is deleted the goal falls back to config defaults (re-set in seconds). Same pattern as `schedule.json`.

## References
- `openspec/changes/stabilization-review/findings.md` — Finding #1 + "Agreed Direction — EV charging (2026-06-06)".
- `price-forecasting-module-4` — engine, requirement constraint, `GET /api/ev/chargers`, state file.
