# Design

## Context

See proposal.md for motivation. `LoadBalancer._shed_at` currently serves as the physical off/restore clock for overload cuts, planned stops and conservative first managed starts. `ShedLoadOutput.shed` explicitly means actuate off. Executor heater and binary-EV suppression and custom entity writes depend on it. The aggregate state, notifications, both cards, transition logs and diagnostic shed set also treat it as an intervention.

Demand is tri-state: the engine resolves custom entities to true unless an excess-PV schedule supplies demand, binary chargers from schedule, and heaters from the effective controller decision (including overrides). `None` remains possible when no explicit demand can be resolved and in direct balancer callers; it must retain the existing unmanaged load behavior.

## Goals / Non-Goals

**Goals:** Correct intervention semantics across the status pipeline without altering safe physical dispatch. Make lifecycle behavior explicit and testable.

**Non-Goals:** Change the reduction trigger, give-way order, restore policy, anti-wear timing, planned demand resolution, configuration, or UI layout. No database changes or new dependency.

## Decisions

### Preserve the off-command contract and add explicit intervention provenance

Keep `_shed_at` and `ShedLoadOutput.shed` as the existing off-command/timing contract. Add an independent per-load intervention marker/reason established only by an actual overload cut while `requested_on is not False`. Expose it as a boolean `actively_shedding` on `ShedLoadOutput` and the public `shed` entries. Emit the field for every entry. The legacy `shed` field remains the off command for compatibility; do not change its meaning beneath physical dispatch consumers.

An additive field avoids a dangerous partial migration where changing `shed` makes a planned-off heater, binary charger or custom entity turn on. Reject a frontend reason-string filter: reasons are explanatory text, startup can have no reason, and the backend would still claim shedding and notify. Reject `shed and requested_on`: demand does not prove that an overload intervention occurred.

### Follow the real intervention episode without changing clocks

| Event | Off-command/timer behavior | Active intervention |
| --- | --- | --- |
| First managed off/unknown state | Existing conservative hold and gates | False |
| Ordinary planned stop | Existing minimum-on behavior | False |
| Actual overload cut, demand true or unknown | Immediate cut and existing clock | True |
| Actual overload cut, demand explicitly false | Immediate safe cut | False |
| Protection-cut load waiting for safe restore | Existing off timestamp retained | True while demand not false |
| Demand becomes false while cut | Stay off; preserve original timestamp | Clear immediately |
| Demand later becomes true while still off | Existing restore gates; no timer restart | Remain false until a new actual cut |
| Restore granted | Existing restore/ledger grant | Clear |
| Load removed/configured out | Existing cleanup | Clear matching marker |
| Balancer disabled/re-enabled | Existing feature gating | Clear intervention and notification edge state |

Apply demand cancellation before final output/state generation, including overload decisions in the same tick. A planned-on startup hold or a new scheduled start waiting for capacity is not retroactively labeled as a prior protection cut. Unknown demand alone neither creates nor cancels a genuine intervention. Do not change `has_given_way`, shared room accounting, fresh-sample guards, anti-wear clocks or reverse restoration order to derive a display flag.

### Migrate every reporting consumer together

Derive aggregate `shedding` from explicit active markers, preserving current precedence for pause, stale fallback, throttling and battery/EV states. Serialize `actively_shedding` through the shared REST/live-metrics payload. Update the frontend status type and fixtures, and both cards' filters, to use the explicit boolean. Treat a missing field as inactive for display; do not fall back to the ambiguous off-command field. New backend payloads always include it.

Use intervention edges for shedding notifications and keep them deduplicated while recovering; clear edge caches on disable/removal so future genuine episodes notify. Preserve physical off/on decision tracing, but distinguish routine plan/startup holds from overload shedding and distinguish cancellation from physical restoration. Extend diagnostics to show both the command set and intervention set so a future report can be investigated without conflating them. Keep human-readable overload provenance and current waiting explanations separate enough that a canceled episode cannot leak an old overload reason into ordinary off status.

## Risks / Trade-offs

- [Changing a reporting field can accidentally change physical dispatch] → Keep all actuation reads on `shed`; test identical off dispatch for heaters, binary EVs and custom entities.
- [Unknown demand accidentally suppresses safety reporting] → Explicitly test `None` overload and restore lifecycles as well as engine-resolved custom demand.
- [Clearing an intervention resets minimum-off time or blocks unrelated restores] → Keep timing/restore state independent and assert original timestamp and existing ordering behavior through plan transitions.
- [Startup loses an unpersisted prior overload episode] → Do not invent provenance after restart; maintain conservative startup protection and report no intervention until a new actual cut. No new persistence is introduced.
- [Mixed frontend/backend assets omit the additive field] → Missing field renders no shedding entry; normal release delivers both components together. Existing off-command API consumers remain compatible.

## Migration Plan

Implement backend provenance/output first, migrate reporting consumers and shared frontend types in the same change, then run targeted backend/frontend regressions and `./scripts/lint.sh`. No data migration. Normal application release/restart picks up the change; do not manually deploy. Rollback restores the prior reporting behavior without data conversion.

## Open Questions

None blocking. The command/provenance separation, unknown-demand behavior and recovery lifecycle are decided above.
