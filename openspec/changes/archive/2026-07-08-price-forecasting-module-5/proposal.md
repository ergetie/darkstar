## Why

Module 4 delivers the goal-based EV charging engine (target SoC by a ready-by time, soft requirement in Kepler, excess-PV self-consumption, automatic multi-day spreading, read-only `GET /api/ev/chargers`). But it is configured only via YAML. Module 5 makes the goal **self-service**: a dashboard EV tab to set the schedule, a write API, optional Home Assistant entity sync, and settings fields. After Module 5, the EV feature — and the fix for stabilization-review **Finding #1** — is usable end-to-end without editing config.

## What Changes

- **EV tab inside the Energy Resources card.** The dashboard has no room for another top-level card, so the controls live in a **tab** within the existing Energy Resources card (`ResourcesDomain`). A small "Metrics | EV" switch toggles between the existing resource metrics and the EV controls; the **active tab is remembered in the browser** (`localStorage`), reusing the ChartCard overlay-persistence pattern. The Metrics tab keeps the at-a-glance EV summary line.
- **Goal controls (no modes).** Per charger: a **target SoC %** slider, a **ready-by time**, and a **repeat** selector (daily / chosen weekdays / every N days / a specific date). Plus a **keep-charger-on-after-target** toggle. **No "EV-before-battery priority" toggle** — surplus ordering is owned by the already-shipped `excess_pv.priority[]` list (Settings → Advanced → "Excess PV Dispatch"), with the home battery implicitly first. There is no "daily vs multi-day" mode dropdown — a specific date is just "no repeat". Progress, today's quota, on-track/behind status, and the day-by-day schedule are shown read-only.
- **In-card Excess PV link.** When a configured current-type charger is **not** found in `excess_pv.priority[]`, the EV tab SHALL show a non-blocking hint that surplus absorption is off, plus a jump-link to the Advanced "Excess PV Dispatch" editor. The editor itself stays in Advanced (where power users find it); a one-tap in-card "Add to Excess PV" action is a stretch enhancement.
- **Write API** (`POST /api/ev/chargers/{id}/schedule`): accepts the goal (`target_soc_percent`, `ready_by`, `repeat`, optional `ready_by_date`) plus `keep_on_after_target`, persists them, and (if configured) writes them to the linked HA entities.
- **Optional HA entity sync (bidirectional, HA wins).** Two optional entities per charger — an **`input_datetime`** for the ready-by time and an **`input_number`** for the target SoC %. When set in HA they take priority over the dashboard value (mirroring the existing **vacation-mode** override pattern). This lets users drive the goal from calendars, work schedules, or automations.
- **Settings fields** for the two optional HA entity IDs, with an informational tip when set.
- **Advanced control = don't enable the charger in Darkstar.** A user who wants fully custom logic simply leaves the charger's `switch_entity` unmapped; Darkstar never touches the switch and HA owns it. No extra mode needed.

## Capabilities

### New Capabilities
- `ev-dashboard-card`: The EV tab inside the Energy Resources card — target SoC, ready-by, repeat, keep-on controls, progress / quota / status display, an in-card Excess PV priority-list hint + jump-link, and a "paused by load balancer" status wording, with the active tab persisted in `localStorage`. **No `charge_priority` toggle.**
- `ev-schedule-api`: Write endpoint to set/clear a charger's goal (target SoC + ready-by + repeat + toggles) and trigger HA sync.
- `ha-schedule-sync`: Bidirectional sync of the ready-by time (`input_datetime`) and target SoC (`input_number`) with Home Assistant; HA values take priority when set.

### Modified Capabilities
- `dashboard-ev-display`: The Energy Resources card gains an EV tab (was: a static EV kWh line).
- `per-device-ev-scheduling`: Per-charger config gains optional `ha_ready_by_entity` (`input_datetime`) and `ha_target_soc_entity` (`input_number`) fields for HA sync. (The core goal fields are defined in Module 4; `charge_priority` is **not** one of them — surplus ordering is owned by `excess_pv.priority[]`.)

## Impact

- **Frontend** (`frontend/src/`): tabbed `ResourcesDomain` in `CommandDomains.tsx` with persisted active tab; new `EVChargingCard.tsx` (target/ready-by/repeat/toggles + progress/quota/status); API client calls for `GET /api/ev/chargers` and `POST /api/ev/chargers/{id}/schedule`; settings fields in `EntityArrayEditor.tsx`.
- **Backend API** (`backend/api/routers/ev.py`): add the write endpoint to the router Module 4 created.
- **Backend HA sync** (`backend/ha_socket.py`, `backend/core/ha_client.py`, `executor/actions.py`, `executor/profiles.py`, `backend/api/routers/ha.py`): subscribe to the two HA entities; add `get_ha_datetime()`; allow `input_datetime.set_datetime` (and reuse existing `input_number.set_value`); HA→Darkstar updates win; debounce echo. **Four plumbing prerequisites are currently absent and need new code:**
  - `backend/api/routers/ha.py:218` entity-list filter currently only includes `"input_number."` (needs `"input_datetime."` added so the entity picker can surface `input_datetime` entities).
  - `executor/actions.py` has `set_input_number` (`:436`) but **no `set_input_datetime`**.
  - `executor/profiles.py:19` `VALID_DOMAINS = {"select","number","switch","input_number"}` — `input_datetime` is missing.
  - `backend/ha_socket.py:136-156` only monitors `plug_sensor → ev_plug_{idx}` today; the ready-by / target-SoC entity subscription is brand-new (`ev_ready_by_{idx}` / `ev_target_soc_{idx}` keys + `state_changed` handlers + 5s debounce).
- **Config** (`executor/config.py`): optional `ha_ready_by_entity`, `ha_target_soc_entity` per charger.
- **State** (`data/ev_multi_day_state.json`): extended with the user-set goal + toggles (Module 4 writes computed progress fields).
- **Dependencies:** requires Module 4 (engine + GET API + state file). Uses existing HA websocket infrastructure and the vacation-mode override precedent.
- **Relations:** completes the resolution of stabilization-review **Finding #1**; supersedes the prior penalty-level EV UX.
- **No breaking changes:** all additive; a charger with no HA entities works dashboard-only.
