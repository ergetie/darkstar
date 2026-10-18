# Design

## Context

`_gather_system_state` builds a list of `(key, callable)` reads, runs them, then parses all results inside one try/except (engine.py ~2630-2801). Parsing errors abort everything after the failing line. The water temp is only used for `before_water_temp` history logging (engine.py ~2914, default 50.0 in override.py:73). `control_type` is validated in backend/api/routers/config.py.

## Goals / Non-Goals

**Goals:** per-sensor isolation; accurate per-entity diagnostics; accurate stale messages.
**Non-Goals:** changing stale thresholds or balancer control logic; reading real tank temperature for switch heaters; config changes.

## Decisions

- Skip the water temperature read for any device with `control_type == "switch"`. engine.py (~2637-2645) reads only `water_heater_devices[0].target_entity` into the single `current_water_temp`; that stays unchanged, so in practice the check applies to the first device, but the rule is phrased per-device so it stays correct if more devices are read. Legacy global `water_heater.target_entity` (no devices) is treated as temperature-controlled. Alternative: parse leniently; rejected, a switch has no temperature.
- Add a small helper `_safe_float(key, entity, raw)` returning float or None and logging via a per-entity rate limiter (dict entity -> last warn monotonic time, ~5 min). Alternative: try/except around each block; helper is less repetitive.
- Wrap the phase block in its own try/except as a backstop, so unexpected errors there or elsewhere stay local, with the outer except kept for read-level failures and logged with the entity-level helper.
- Load balancer: `_is_stale` stays boolean; add a helper that describes each stale phase ("L2 no reading" / "L2 age 90s"), computed from `grid_current_updated_at`. Message uses it; the stale-since duration is labelled "paused for Ns".
- Phase labels use "L1..L3" rather than bare ints.

- Spec deltas: the stale message change is a MODIFIED delta of the existing "Stale sensor fail-safe" requirement (full text copied and extended), since the message reports that fail-safe's condition and is not orthogonal; a parallel ADDED requirement would duplicate its trigger. The water-temp read rule is a MODIFIED delta of "Water heater sensor reads are gated by has_water_heater flag", the nearest requirement governing water heater reads and gating; "Per-device water temperature control" covers setting temperatures, not reading, so it is untouched. "Sensor reads are isolated" is new behaviour and stays ADDED.

## Risks / Trade-offs

- [Message text change breaks tests or UI parsing] -> grep tests/frontend for the old strings and update.
- [Rate limiter hides new faults] -> keyed per entity and reason-agnostic interval; first occurrence always logs.

## Resolved questions (verified in code)

- Legacy global heater: `WaterHeaterGlobalConfig` has no `target_entity` field (executor/config.py:118-128 is the device config; the global class lacks it), so the `hasattr` branch at engine.py:2642-2643 never reads anything. Only `water_heater_devices[0].target_entity` is read (engine.py:2640-2645); the legacy statement is moot, no behaviour to define.
- Order of failure: `float(water_str)` at engine.py:2713-2715 runs before the phase block (2722+), inside the single try whose `except` is at engine.py:2800-2801; `"on"` is truthy so `float("on")` raises. Any earlier parse failure aborts the same way.
- `current_water_temp` only feeds `before_water_temp` history (engine.py:2914) and defaults to 50.0 (override.py:73); keeping the default for switch heaters is safe.
- `control_type` is normalised in executor/config.py:776-779 (anything but "switch" becomes "temperature"), so the check can compare against "switch" directly.
- The recorder does not read heater target entities as temperatures (backend/recorder.py:308-338 reads power sensors only); out of scope.
- Message consumers: grep finds the "Phase sensor(s)" strings only in executor/load_balancer.py:452,464 plus a settings helper text (frontend/src/pages/settings/types.ts:1433, unaffected wording) and the existing spec scenario; no test or frontend code asserts on them (tests/executor/test_load_balancer.py asserts `state` only, :267-280). Task 2.2 is a verification, no expected edits besides load_balancer.py.
- Stale age source: `grid_current_updated_at` is built per phase at engine.py:2727-2798; a missing phase has no entry (age undefined, "no reading"). Pause duration is `now - _ev_stale_since` (load_balancer.py:446-452).
- Rate limit interval: 300 s, module constant, state held on the executor instance keyed by entity id; first occurrence always logs.
- Non-numeric states "unknown"/"unavailable" count as failures of that sensor and are logged once per interval like any other.
