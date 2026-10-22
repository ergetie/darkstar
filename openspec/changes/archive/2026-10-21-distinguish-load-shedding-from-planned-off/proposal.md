# Proposal

## Why

The load balancer reports ordinary scheduled-off loads and conservative startup holds as active load shedding. This produces false red warnings, intervention state and potentially notifications, undermining confidence in fuse protection.

## What Changes

- Distinguish commanded-off state from an active fuse-protection shedding intervention using explicit intervention provenance.
- Keep physical off dispatch, minimum switching times, restore ordering and capacity/cooling gates intact.
- Drive public intervention status, both load-balancer cards, notification edges and intervention diagnostics from the explicit intervention state.
- Cover scheduled off, startup, actual shedding, delayed recovery, schedule transitions and unmanaged custom-load demand with regressions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `phase-load-balancing`: Define truthful intervention reporting separately from safe on/off commands, including lifecycle and notification semantics.
- `powerflow-load-balancer-tab`: Exclude ordinary off/hold states from warnings and automatic intervention attention; apply the same distinction to the Executor card.

## Impact

`executor/load_balancer.py`, `executor/engine.py`, the shared frontend load-balancer status contract, compact/detail cards and associated tests. Additive status field; existing off-command semantics remain compatible. No dependencies, configuration changes or database migrations.
