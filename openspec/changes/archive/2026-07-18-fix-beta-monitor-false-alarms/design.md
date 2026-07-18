# Design — fix-beta-monitor-false-alarms

## Context

Evidence from a beta tester's log (2026-07-18) and a second user confirming the same banners:

1. `forecast_sanity` violation: `PV_FORECAST_CEILING_KWH = 7.11 * 0.25` in `backend/monitors.py:66` is the reference system's array, hardcoded. The tester has 14.94 kWp (four arrays); their 2.781 kWh/slot forecast is physically plausible.
2. `command_success` violation at 18/1321 failed ticks (98.64 % < 99 %). The tester's failure burst came from a first-boot window with a placeholder config; the alarm then lingers 24 h.
3. Demo load forecast despite a configured sensor: log shows `Daily total 19609.2 kWh/day ... exceeds 500 kWh sanity bound, using dummy profile`. The Fronius lifetime sensor drops to 0 (numeric, not `unavailable`) and jumps back, and `max(0, current - prev)` in `get_load_profile_from_ha` counts each jump as ~19,609 kWh. Exactly 7 jumps in 7 days ⇒ nightly inverter sleep.
4. `Profile file not found: profiles/None.yaml` ERROR on fresh installs: `config.default.yaml` ships `inverter_profile: null`, and `profiles.py:407` does `.get("inverter_profile", "generic")`, which returns `None` when the key exists with a null value.
5. Banners aren't dismissable: `SystemAlert` supports `onDismiss` but `App.tsx:112` never passes it; warning banners have no ✕ at all; collapse state resets on reload.

## Goals / Non-Goals

**Goals:**
- No false-positive invariant violations for systems that differ from the reference installation.
- Load-history profile survives cumulative-meter reset artifacts (Fronius nightly sleep).
- Honest user-facing messaging when the load forecast is degraded.
- Clean startup log on fresh installs.
- Warning banners can be snoozed, never permanently dismissed.

**Non-Goals:**
- No switch to HA long-term statistics API for load history (bigger change, deferred).
- No profile building from Darkstar's own `slot_observations` (needs 7 days uptime; deferred).
- No backend persistence of snooze state (client-side only).
- No changes to monitor episode/dedup logic.

## Decisions

### D1: PV ceiling = Σ array kWp × 0.25, from config (KISS)
`_eval_forecast_sanity` computes the ceiling from `system.solar_arrays[].kwp` at evaluation time: `sum(kwp) * 0.25` kWh per 15-min slot. DC-side is correct because Aurora forecasts panel output before inverter clipping. No efficiency factor (user decision: KISS — max value). If no arrays are configured (or sum ≤ 0), the check returns `skipped` with reason, mirroring the existing skip pattern. The `PV_FORECAST_CEILING_KWH` constant is deleted.
*Alternative rejected:* AC inverter limit — wrong side of the inverter for a pre-clipping forecast; hardcoded constant — the bug being fixed.

### D2: COMMAND_SUCCESS_MIN 0.99 → 0.95
At 60 s ticks, 24 h ≈ 1440 ticks; 95 % tolerates ~72 failed minutes/day (one HA restart or short outage passes; hours-long breakage still alarms). Plain constant change, no minimum-failure-count logic (KISS, user decision).

### D3: Per-delta guard in `get_load_profile_from_ha`
Inside the state loop, skip any single delta where `energy_delta > max_meter_delta_kwh` (read from `config.recorder.max_meter_delta_kwh`, default 50.0 — same guard the recorder already trusts). Skipped deltas are counted and logged once (`WARNING`, with count and max seen) after the loop. The 500 kWh/day bound stays as a final backstop. Note: after a skipped 0→lifetime jump, `prev_state` still advances to the lifetime value, so subsequent normal deltas are correct.
*Alternatives rejected:* HA statistics API and own-DB profile (Non-Goals — bigger changes); both remain future options.

### D4: Honest degraded messaging
`get_dummy_load_profile` currently always logs/sets "Configure total_load_consumption sensor". Differentiate: when a sensor IS configured but its data was discarded, the log warning and `set_load_forecast_status` detail say the data was discarded as implausible (and why), not that the sensor is missing. The health banner surfaces that detail. Keep the existing `degraded/demo` status code so downstream consumers don't change.

### D5: Null inverter profile → generic, quietly
`get_profile_from_config` uses `system_config.get("inverter_profile") or "generic"` so null/empty (the shipped default) resolves directly to `generic` with a single INFO line, never attempting `profiles/None.yaml` and never logging ERROR. An explicitly configured-but-missing profile name still logs the existing WARNING + fallback.

### D6: Snooze, client-side, keyed by issue code
`SystemAlert` gets an ✕ on every banner (critical and warning). Clicking stores `{key: code || category, until: now + 24h}` in `localStorage`; snoozed issues are filtered out of the rendered list. Key is `code || category` only — messages contain live numbers (e.g. "98.64 %") that change every evaluation and would defeat snoozing. Snooze expires after 24 h; an issue that clears and re-fires within the window stays snoozed (accepted trade-off, KISS). A snoozed-count chip ("N snoozed") is shown so hidden issues are discoverable and un-snoozable.
*Alternative rejected:* backend-persisted snooze tied to monitor episodes — heavier, needs API changes, and episode ids aren't exposed in health issues today.

## Risks / Trade-offs

- [Delta guard hides a real 50+ kWh interval] → Physically implausible for a 15-min house interval; guard value is user-configurable via existing `recorder.max_meter_delta_kwh`.
- [95 % threshold misses a marginal real problem (e.g. steady 3 % failures)] → Failures still surface via command-failure streak notifications and the monitors page; the invariant guards against sustained breakage.
- [Σ kWp ceiling is generous for shaded/oversized arrays] → Fine: forecast_sanity is a "physically impossible" tripwire, not an accuracy check.
- [Snooze hides a recurring flap for 24 h] → Snoozed chip keeps it one click away; critical issues still render a chip, never fully invisible.
- [localStorage snooze is per-browser] → Accepted; no server round-trip, matches KISS scope.

## Migration Plan

Pure code change; no DB migration, no config migration (reuses existing keys). Rollback = revert commit. Beta testers see the forecast_sanity and command_success banners clear within one monitor interval (15 min) after upgrade; the load forecast recovers on the next planner run.

## Open Questions

None — thresholds, ceiling formula, and snooze semantics were decided with the user (2026-07-18).
