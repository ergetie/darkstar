## Prerequisites

Module 4 (`price-forecasting-module-4`) MUST be implemented first. It provides: `backend/api/routers/ev.py` with `GET /api/ev/chargers`; `data/ev_multi_day_state.json` written by the pipeline; the goal fields on `EVChargerDeviceConfig` (`target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, `keep_on_after_target` — **no `charge_priority`**, surplus ordering is owned by `excess_pv.priority[]`); `MultiDayPlanner` + Kepler requirement wiring. **Module 4 task 1.4 (YAML default goal) MUST land too** — Module 5's `task 3.1` fallback depends on it.

## State File Schema

`data/ev_multi_day_state.json` per charger holds the **user-set goal** (written by the API / HA sync) plus **computed progress** (written by the pipeline):

```json
{
  "last_updated": "2026-06-10T14:30:00+02:00",
  "chargers": {
    "ev_charger_1": {
      "target_soc_percent": 80,
      "ready_by": "07:00",
      "repeat": "daily",
      "ready_by_date": null,
      "keep_on_after_target": true,
      "source": "api",
      "deadline": "2026-06-11T07:00:00+02:00",
      "required_kwh": 36.9,
      "delivered_kwh": 23.1,
      "remaining_kwh": 13.8,
      "daily_quota_kwh": 12.0,
      "quota_schedule": [ { "date": "2026-06-10", "quota_kwh": 12.0, "avg_price_sek": 0.45 } ],
      "paused_by_load_balancer": false,
      "status": "on_track"
    }
  }
}
```

Goal fields are written by the **write API** (group 2) and **HA sync** (group 4); `source ∈ {"api","ha"}`. Computed fields (`deadline`, `required_kwh`, `delivered_kwh`, `remaining_kwh`, `daily_quota_kwh`, `quota_schedule`, `status`) are written by the **pipeline** (Module 4). The pipeline MUST preserve goal fields (read-modify-write).

## 1. Config + settings fields

- [x] 1.1 Add `ha_ready_by_entity` (str | None) and `ha_target_soc_entity` (str | None) to `EVChargerDeviceConfig` (`executor/config.py`), parsed via the existing `_str_or_none()` helper.
- [x] 1.2 Add commented examples to `config.yaml` / `config.default.yaml` under the first `ev_chargers` entry: `# ha_ready_by_entity: "input_datetime.ev_ready_by"` and `# ha_target_soc_entity: "input_number.ev_target_soc"`.
- [x] 1.3 Add `ha_ready_by_entity?`, `ha_target_soc_entity?`, and the goal fields (`target_soc_percent?`, `ready_by?`, `repeat?`, `ready_by_date?`, `keep_on_after_target?`) to the `EVChargerEntity` TypeScript interface (`EntityArrayEditor.tsx`). **No `charge_priority?`** — the field does not exist.
- [x] 1.4 Add two "HA Ready-By Entity" / "HA Target-SoC Entity (optional)" text inputs to the EV charger settings form, styled like `switch_entity`.
- [x] 1.5 Unit tests (`tests/ev/test_ev_config.py`): both HA entity fields parse (valid / empty → None / missing → None).

## 2. Schedule write API

- [x] 2.1 Add `POST /api/ev/chargers/{id}/schedule` to `backend/api/routers/ev.py`. Pydantic body: `target_soc_percent: int | None`, `ready_by: str | None`, `repeat: str | None`, `ready_by_date: str | None = None`, `keep_on_after_target: bool | None = None`. Validate: `target_soc_percent` 0–100; `ready_by` `HH:MM`; `repeat ∈ {daily,weekdays,weekends,every_n_days,none}`; `repeat: none` requires `ready_by_date`; unknown `{id}` → 404. `target_soc_percent: null` clears the goal. **No `charge_priority` body parameter.**
- [x] 2.2 Create `backend/core/ev_state.py` with `read_ev_state()` and atomic `write_ev_state()` (`.tmp` + `os.replace`). The endpoint reads, updates the charger's goal fields + `source: "api"` + `last_updated`, and writes back (preserving other chargers' entries and computed fields).
- [x] 2.3 After persisting, fire-and-forget HA writes when configured: ready-by → `ha_ready_by_entity` via `input_datetime.set_datetime`; target SoC → `ha_target_soc_entity` via `input_number.set_value`. Wrap in try/except; never block or fail the response. Record the write time for debounce (group 4).
- [x] 2.4 Return the updated charger state (state file merged with live HA sensors), matching one entry of `GET /api/ev/chargers`.
- [x] 2.5 Tests (`tests/backend/test_ev_schedule_api.py`): set goal happy path (state written, response shape); clear goal (`target_soc_percent: null`); 404 unknown charger; 422 invalid target / bad repeat / `none` without date; state file created on first write; other chargers' entries preserved.

## 3. State file as source of truth for the goal

- [x] 3.1 In `planner/pipeline.py`, have the EV section read the goal from `ev_multi_day_state.json` (via `read_ev_state()`) and prefer it over `config.yaml` goal fields when present; fall back to config otherwise. Log the source at debug level.
- [x] 3.2 Ensure the pipeline's write-back of computed fields (Module 4) preserves the API/HA-written goal fields (read-modify-write).
- [x] 3.3 Tests (`tests/planner/test_pipeline_ev_state.py`): goal read from state file overrides config; computed write-back preserves goal fields; missing/corrupt state file → graceful fallback to config.

## 4. HA bidirectional sync (ready-by + target SoC)

- [x] 4.1 Add `get_ha_datetime(entity_id) -> datetime | None` in `backend/core/ha_client.py` (same `httpx` pattern as `get_ha_sensor_float`). Parse `"YYYY-MM-DD HH:MM:SS"`, ISO, and ISO+tz; apply system timezone when none. Return None + warning for time-only / `unknown` / `unavailable` / empty.
- [x] 4.2 Add `input_datetime` plumbing across four surfaces (all currently absent — see design D8):
  - `executor/actions.py`: new async `set_input_datetime(entity_id, datetime)` calling `input_datetime.set_datetime` (only `set_input_number:436` exists today).
  - `executor/profiles.py:19`: add `"input_datetime"` to `VALID_DOMAINS = {"select","number","switch","input_number"}`.
  - `backend/api/routers/ha.py:218`: add `"input_datetime."` to the entity-list filter so the entity picker surfaces `input_datetime` entities (today only `"input_number."`).
  - `backend/ha_socket.py:136-156`: register new monitored keys `ev_ready_by_{idx}` / `ev_target_soc_{idx}` for each charger with `ha_ready_by_entity` / `ha_target_soc_entity` (alongside the existing `ev_plug_{idx}` mapping); add `state_changed` handlers that update the state-file goal (HA wins).
  Reuse existing `input_number.set_value` for target SoC.
- [x] 4.3 In `backend/ha_socket.py` `_build_monitored_entities()`, for each charger with `ha_ready_by_entity` / `ha_target_soc_entity`, monitor them (keys `ev_ready_by_{idx}` / `ev_target_soc_{idx}`, following the `ev_plug_{idx}` pattern). Add `state_changed` handlers that update the state file goal (`read_ev_state` → update → `write_ev_state`) and emit an `ev_schedule_changed` Socket.IO event `{ charger_id }`. **HA values take priority over the dashboard value when set** (vacation-mode precedent).
- [x] 4.4 Debounce: module-level `_last_darkstar_write: dict[str, float]` (charger_id → ts), set in 2.3; in the handlers skip events within 5 s of a Darkstar write (log at debug).
- [x] 4.5 Startup sync in `_on_connected()`: for each charger with HA entities, read current HA values; if the state file has no goal and HA has valid values, seed the state file; if the state file has a goal, push it back to HA to resync.
- [x] 4.6 Tests (`tests/backend/test_ha_schedule_sync.py`): `get_ha_datetime` format variants; allowlist includes `input_datetime`; HA change updates state-file goal; debounce skips echo within 5 s, allows genuine change after; startup seed HA→state and resync state→HA.

## 5. Dashboard EV tab — frontend

- [x] 5.1 Add API types + client in `frontend/src/lib/api.ts`: `EVChargerState` / `EVChargersResponse`; `ev.chargers()` (GET) and `ev.setSchedule(id, body)` (POST `/schedule`).
- [x] 5.2 Tabbed `ResourcesDomain` (`CommandDomains.tsx`): add a "Metrics | EV" switch in the card header (EV tab only when `hasEvCharger`). Persist the active tab in `localStorage` reusing the ChartCard pattern — versioned key `darkstar-resources-tab`, default `"metrics"`, with migration + new-user default. Metrics tab keeps the existing EV summary line.
- [x] 5.3 New `frontend/src/components/EVChargingCard.tsx` (one per charger): header (name, plug icon, SoC badge); a **target SoC %** slider (default 80, debounced 500 ms); a **ready-by** `<input type="time">`; a **repeat** `<select>` (Every day / Weekdays / Weekends / Every N days / Specific date) with an `<input type="date">` shown for "Specific date"; a **keep-on-after-target** checkbox. **No "EV-before-battery priority" checkbox.** Each change calls `onScheduleChange(id, body)`. Style per `ResourcesDomain` Tailwind patterns.
- [x] 5.4 Read-only status in `EVChargingCard`: progress bar (`delivered_kwh / required_kwh`); today's quota; a status badge (`on_track` green / `behind` amber / `complete` green / `idle` grey / **`paused_by_load_balancer` blue** when the fuse balancer is throttling the EV — so the user doesn't think the goal is failing); and the day-by-day `quota_schedule` as compact day boxes (hidden when null/empty).
- [x] 5.4b Surplus-absorption hint in `EVChargingCard`: when a configured current-type charger is **not** found in `excess_pv.priority[]`, show a non-blocking hint "Surplus absorption off — add this charger to Excess PV priority" with a jump-link to Settings → Advanced → "Excess PV Dispatch". For a binary charger, downgrade to an informational note ("binary chargers can't absorb surplus — set up a current-type charger to use free PV").
- [x] 5.5 Show an HA-driven indicator when a value came from HA (`source: "ha"`), and a settings tip when a goal is active but no HA entities are configured (`text-xs text-muted` + info icon).
- [x] 5.6 Wire data in `Dashboard.tsx`: `useState` for chargers; fetch `Api.ev.chargers()` on mount + 60 s interval; refetch on `useSocket('ev_schedule_changed', …)`; pass to `ResourcesDomain`; implement `onScheduleChange` → `Api.ev.setSchedule()` then refetch.

## 6. End-to-end verification

- [x] 6.1 E2E (`tests/e2e/test_ev_schedule_e2e.py`): `POST /schedule` (target 80, ready_by 07:00, repeat daily) → state file has the goal → run pipeline (mocked prices/sensors) → state file gains `required_kwh`/`daily_quota_kwh`/`status` → `GET /api/ev/chargers` returns the full state.
- [x] 6.2 E2E HA sync: simulate a `state_changed` on the ready-by `input_datetime` and the target-SoC `input_number` → state-file goal updates and HA value wins → `GET` reflects it.
- [x] 6.3 E2E escape hatch: a charger with `switch_entity` unset is reported as externally controlled and Darkstar issues no switch command for it.
- [x] 6.4 Confirm the full suite still passes (1051+ baseline) and no penalty-level UI remains.

## 7. Post-verification fixes

- [x] 7.1 Wire `keep_on_after_target` in `planner/pipeline.py`: post-solve injection of `max_power_kw` into upcoming slots when `keep_on=true`, `target_soc_percent=100`, live SoC≥100, and `now < deadline`. Past the deadline, charger idles. Gated on target=100 to avoid overcharging (design D10). Tests in `tests/planner/test_keep_on_after_target.py`.
- [x] 7.2 Convert the keep-on checkbox in `EVChargingCard.tsx` to the design-system `Switch` component (was a raw `<input type="checkbox">`). Gate on `targetSoc === 100` with a disabled state + "(requires 100% target)" hint when target < 100.
- [x] 7.3 Remove the orphan "Departure Time" text input from the EV charger settings form (`EntityArrayEditor.tsx`). The `departure_time?` field stays on the TS interface + Python config for backwards compat; the dashboard EV tab is the single self-service surface for the goal (design D11).
