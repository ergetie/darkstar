# Design: risk-aware-safety-buffer-cap

## Context

The temporal safety floor in `planner/strategy/s_index.py` is computed as `min_soc + max(deficit_reserve, min_buffer) + weather_buffer`, then capped at `min_soc + max_buffer_kwh` where `max_buffer_kwh = capacity * max_safety_buffer_percent / 100` (config default 20). The cap is risk-independent while `RISK_CONFIG` promises per-risk minimum buffers of 25/15/10/3/0 % of capacity — so Risk 1's 25% minimum is permanently suppressed by the 20% cap, and Risks 1–3 converge to identical floors on any moderate-to-high-deficit day.

The Layer 2 price addon (`calculate_price_floor_addon`) is deliberately applied *after* this cap, bounded separately at 80% of capacity. That relationship must be preserved.

`max_safety_buffer_percent` exists only in `config.yaml` / `config.default.yaml` (no settings-UI exposure). All known prod configs use the default 20.

## Goals / Non-Goals

**Goals:**
- Each risk level gets a distinct effective safety-floor ceiling.
- The configured `max_safety_buffer_percent` keeps its current meaning for Risk 3 (Neutral) — no config migration, no behavior change for neutral users.
- A risk level's cap can never be lower than its own `min_buffer_pct`.
- Debug output shows the effective cap that applied.

**Non-Goals:**
- No changes to the Layer 2 price addon or its 80% bound.
- No new config keys and no settings-UI exposure.
- No changes to risk margins or `min_buffer_pct` values.

## Decisions

### 1. Scale the configured cap with a per-risk multiplier (not a table of absolute caps)

Add a `cap_scale` field to `RISK_CONFIG`:

| Risk | cap_scale | Effective cap at config=20% |
|------|-----------|------------------------------|
| 1 Safety | 1.50 | 30% |
| 2 Conservative | 1.25 | 25% |
| 3 Neutral | 1.00 | 20% (unchanged) |
| 4 Aggressive | 0.85 | 17% |
| 5 Gambler | 0.75 | 15% |

Effective cap: `max_buffer_kwh = capacity * (max_safety_buffer_percent / 100) * cap_scale`.

*Why scaling over absolute per-risk values:* the config key stays meaningful (users who tuned it keep proportional behavior across risk levels), no migration is needed, and Risk 3 output is bit-for-bit unchanged — which keeps the blast radius small and matches the backlog's suggested 30/20/15 endpoints.

*Alternative considered:* per-risk absolute caps in `RISK_CONFIG`, ignoring the config key except as an override — rejected because it silently changes the meaning of an existing config value and requires deciding an override precedence.

### 2. Floor the effective cap at the risk level's own minimum buffer

`max_buffer_kwh = max(max_buffer_kwh, min_buffer_kwh)` after scaling. With defaults this is already satisfied (Risk 1: 30% ≥ 25%), but a user who lowers `max_safety_buffer_percent` (e.g. to 10) would otherwise reintroduce the exact bug this change fixes. This guarantee makes `min_buffer_pct` an honest promise at every config value.

### 3. Debug output: add `cap_scale` and keep `max_buffer_kwh` as the effective (post-scaling, post-floor) value

`max_buffer_kwh` in the debug dict already exists and is what run-history consumers read; it simply becomes the effective value. Add `cap_scale` alongside so a debug reader can reconstruct the raw config value. No key renames — additive only, so S-Index run history persistence and any UI reading the debug payload keep working.

### 4. Config comment update only

`config.default.yaml` line for `max_safety_buffer_percent` gets a corrected comment stating it is the Neutral (Risk 3) baseline scaled per risk level (the current comment's "(default 40%)" tail is also stale — fix it in passing). `config.yaml` gets the same comment for consistency.

## Risks / Trade-offs

- **[Higher floors for Risk 1–2 mean more grid charging on hard days]** → This is the intended effect; the proposal flags it as a user-visible behavior change. Mitigation: none needed beyond release notes; Risk 3 (the default and the maintainer's own setting) is unchanged.
- **[Existing tests may assert the flat 20% cap]** → Update assertions to the per-risk effective cap; add explicit tests that Risk 1 > Risk 3 > Risk 5 floors under a saturating deficit.
- **[Price-awareness tests assume the addon sits atop the capped Layer 1 floor]** → The addon logic is untouched, but its Layer 1 input can now be higher for Risk 1–2; verify `test_s_index_price_awareness.py` fixtures don't hard-code the 20% cap.

## Migration Plan

Pure code change, no config migration, no DB change. Deploy normally; rollback is a revert. First planner run after deploy recomputes floors with the new caps.

## Open Questions

None — multiplier values above are chosen to match the backlog's suggested endpoints (30/20/15) with a monotonic curve through all five levels.
